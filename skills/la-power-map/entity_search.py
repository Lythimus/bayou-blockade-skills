#!/usr/bin/env python3
"""Resolve corporate parents and subsidiaries from GLEIF and SEC Exhibit 21.

    entity_search.py gleif <name> [--max 20]
    entity_search.py gleif-children <LEI> [--region US-LA]
    entity_search.py ex21 <name> [--from YYYY] [--to YYYY]

Output is CSV on stdout; counts and caveats go to stderr. Standard library only.
"""
import argparse
import csv
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GLEIF = "https://api.gleif.org/api/v1/lei-records"
EFTS = "https://efts.sec.gov/LATEST/search-index"
# SEC policy requires a descriptive User-Agent; anonymous ones get 403.
SEC_UA = {"User-Agent": "BayouResearch research@example.com"}
GLEIF_UA = {"User-Agent": "BayouResearch", "Accept": "application/vnd.api+json"}


def get_json(url, headers, timeout=60):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    return None


def note(msg):
    print(msg, file=sys.stderr)


def name_of(record):
    ent = record["attributes"]["entity"]
    return ent["legalName"]["name"]


def parent_or_exception(lei, rel, links):
    """Return the parent as 'NAME (LEI)', or ('', exception reason)."""
    if "lei-record" in links:
        data = get_json(f"{GLEIF}/{lei}/{rel}", GLEIF_UA)
        if data and data.get("data"):
            p = data["data"]
            return f"{name_of(p)} ({p['id']})", ""
    exc = get_json(f"{GLEIF}/{lei}/{rel}-reporting-exception", GLEIF_UA)
    if exc and exc.get("data"):
        return "", f"{rel}: {exc['data']['attributes']['reason']}"
    return "", ""


def cmd_gleif(args):
    q = urllib.parse.urlencode({"filter[fulltext]": args.name, "page[size]": args.max})
    data = get_json(f"{GLEIF}?{q}", GLEIF_UA)
    records = data["data"] if data else []
    total = data["meta"]["pagination"]["total"] if data else 0
    note(f"GLEIF fulltext '{args.name}': {total} record(s), showing {len(records)}")
    if not records:
        note("No LEI found. Most small LLCs never obtain one, so this does not mean the entity has no parent.")
    w = csv.writer(sys.stdout)
    w.writerow(["lei", "legal_name", "status", "legal_jurisdiction", "hq_region",
                "direct_parent", "ultimate_parent", "exception_reason"])
    for r in records:
        ent = r["attributes"]["entity"]
        # Fulltext also matches other names, addresses and transliterations, so a hit can be unrelated.
        if args.name.lower() not in ent["legalName"]["name"].lower():
            note(f"{r['id']} {ent['legalName']['name']}: legal name does not contain '{args.name}'; check before using")
        rels = r.get("relationships", {})
        direct, dx = parent_or_exception(r["id"], "direct-parent", rels.get("direct-parent", {}).get("links", {}))
        ultimate, ux = parent_or_exception(r["id"], "ultimate-parent", rels.get("ultimate-parent", {}).get("links", {}))
        w.writerow([r["id"], ent["legalName"]["name"], ent["status"], ent.get("jurisdiction") or "",
                    (ent.get("headquartersAddress") or {}).get("region") or "",
                    direct, ultimate, "; ".join(x for x in (dx, ux) if x)])


def cmd_children(args):
    w = csv.writer(sys.stdout)
    w.writerow(["lei", "legal_name", "status", "legal_jurisdiction", "legal_region", "hq_region", "hq_city"])
    page, seen, kept = 1, 0, 0
    while True:
        q = urllib.parse.urlencode({"page[size]": 100, "page[number]": page})
        data = get_json(f"{GLEIF}/{args.lei}/direct-children?{q}", GLEIF_UA)
        if not data or not data.get("data"):
            break
        for r in data["data"]:
            seen += 1
            ent = r["attributes"]["entity"]
            legal = (ent.get("legalAddress") or {}).get("region") or ""
            hq = ent.get("headquartersAddress") or {}
            if args.region and args.region not in (legal, hq.get("region")):
                continue
            kept += 1
            w.writerow([r["id"], ent["legalName"]["name"], ent["status"], ent.get("jurisdiction") or "",
                        legal, hq.get("region") or "", hq.get("city") or ""])
        if page >= data["meta"]["pagination"]["lastPage"]:
            break
        page += 1
        time.sleep(0.5)
    note(f"{seen} direct child record(s) for {args.lei}; {kept} kept"
         + (f" with legal or HQ region {args.region}" if args.region else ""))
    note("Only children that reported this parent to GLEIF appear. Run `gleif` on each child to walk further down.")


def cmd_ex21(args):
    # Listing "10-K/A" in forms collapses the result set to a handful of hits; amendments
    # are rare carriers of Exhibit 21 anyway.
    params = {"q": f'"{args.name}"', "forms": "10-K,10-K405,20-F,S-1,S-4,10-12B"}
    if args.start or args.end:
        params.update({
            "dateRange": "custom",
            "startdt": f"{args.start or 2001}-01-01",
            "enddt": f"{args.end or datetime.date.today().year}-12-31",
        })
    w = csv.writer(sys.stdout)
    w.writerow(["filer", "cik", "form", "file_date", "file_type", "document_url"])
    offset, total, kept, other = 0, None, 0, {}
    while total is None or offset < min(total, 1000):
        q = urllib.parse.urlencode({**params, "from": offset})
        data = get_json(f"{EFTS}?{q}", SEC_UA)
        if not data:
            break
        total = data["hits"]["total"]["value"]
        hits = data["hits"]["hits"]
        if not hits:
            break
        for h in hits:
            s = h["_source"]
            ft = s.get("file_type") or ""
            if not ft.upper().startswith("EX-21"):
                other[ft] = other.get(ft, 0) + 1
                continue
            kept += 1
            cik = s["ciks"][0].lstrip("0")
            accession, filename = h["_id"].split(":", 1)
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"
            w.writerow([s["display_names"][0], cik, s.get("form", ""), s.get("file_date", ""), ft, url])
        offset += len(hits)
        time.sleep(0.2)
    note(f"EFTS '{args.name}': {total or 0} hit(s) in annual/registration filings; {kept} in an Exhibit 21")
    if total and total > 1000:
        note("More than 1000 hits; only the first 1000 were scanned. Narrow with --from/--to or a longer name.")
    if not kept and other:
        top = ", ".join(f"{k} x{v}" for k, v in sorted(other.items(), key=lambda kv: -kv[1])[:8])
        note(f"Name appears only outside Exhibit 21 ({top}). Open those documents to see the context.")
    if not total:
        note("No hits. Exhibit 21 exists only for SEC-registered parents; private-equity and foreign owners rarely file one.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gleif", help="LEI records matching a name, with direct and ultimate parents")
    g.add_argument("name")
    g.add_argument("--max", type=int, default=20)
    g.set_defaults(func=cmd_gleif)
    c = sub.add_parser("gleif-children", help="direct children of an LEI")
    c.add_argument("lei")
    c.add_argument("--region", help="ISO 3166-2 region, e.g. US-LA, matched on legal or HQ address")
    c.set_defaults(func=cmd_children)
    e = sub.add_parser("ex21", help="SEC filers whose Exhibit 21 subsidiary list names this entity")
    e.add_argument("name")
    e.add_argument("--from", dest="start", type=int, help="first filing year")
    e.add_argument("--to", dest="end", type=int, help="last filing year")
    e.set_defaults(func=cmd_ex21)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
