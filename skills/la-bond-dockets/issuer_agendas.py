#!/usr/bin/env python3
"""Conduit-issuer side of a Louisiana bond: LPFA TEFRA notices, and board/commission agendas for
LPFA, the three Mississippi River ports, and the Ascension Parish Industrial Development Board.

    issuer_agendas.py lpfa-notices [--since 2026-01-01] [--grep hyundai]
    issuer_agendas.py agendas lpfa --since 2026-09-01 --grep hyundai
    issuer_agendas.py agendas portsl|portnola|portgbr|ascension-idb [--since DATE] [--until DATE]
                      [--grep "TERM|TERM"] [--kind agenda|minutes|all] [--list]
    add --json for machine-readable output, --yes to allow a large download

Agenda hits are reported for bond/financing vocabulary by default; --grep adds terms (regex).
A "notice of sale" hit is flagged: under La. R.S. 9:2347(G) the 30-day contest period for
public-trust bonds runs from publication of that notice.
Standard library plus poppler's pdftotext.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bond_common as bc  # noqa: E402

LPFA_API = "https://www.lpfa.com/wp-json/wp/v2"
ISSUERS = {
    "lpfa": {"name": "Louisiana Public Facilities Authority",
             "pages": ["https://www.lpfa.com/about-lpfa/board-meeting-agendas/"]},
    "portsl": {"name": "Port of South Louisiana",
               "pages": ["https://portsl.com/meeting-agendas/"],
               "keep": r"(?i)agenda|minute"},
    "portnola": {"name": "Port of New Orleans",
                 "pages": ["https://portnola.com/info/board-and-staff/past-board-meetings",
                           "https://portnola.com/info/board-and-staff/board-meetings"],
                 "keep": r"(?i)/board-meeting/"},
    "portgbr": {"name": "Port of Greater Baton Rouge",
                "pages": ["https://www.portgbr.com/meetingsminutes", "https://www.portgbr.com/meetingsminutes-25",
                          "https://www.portgbr.com/meetingsminutes-24", "https://www.portgbr.com/meetingsminutes-23"],
                "keep": r"/s/"},
    "ascension-idb": {"name": "Industrial Development Board of the Parish of Ascension",
                      "pages": ["https://ascensionedc.com/industrial-development-board/board-meetings"],
                      "keep": r"(?i)IDB"},
}
DEFAULT_TERMS = (r"\bbonds?\b|TEFRA|public hearing|revenue|lease|PILOT|payment in lieu|cooperative endeavor|"
                 r"notice of sale|inducement|bond counsel|volume cap|indenture|obligor|\bCEA\b")
SALE_RE = re.compile(r"notice of (?:the )?sale", re.I)


# ---------------------------------------------------------------- LPFA public notices

def lpfa_category():
    cats = json.loads(bc.fetch_text(LPFA_API + "/categories?slug=public-notices"))
    if not cats:
        sys.exit("LPFA site changed: no 'public-notices' category at %s" % LPFA_API)
    return cats[0]["id"]


def lpfa_notices(since, grep):
    cat, out, page = lpfa_category(), [], 1
    while True:
        q = {"categories": cat, "per_page": 100, "page": page, "_fields": "date,link,title,content"}
        if since:
            q["after"] = since.isoformat() + "T00:00:00"
        try:
            posts = json.loads(bc.fetch_text(LPFA_API + "/posts?" + urllib.parse.urlencode(q)))
        except bc.urllib.error.HTTPError as e:
            if e.code == 400:  # past the last page
                break
            raise
        if not posts:
            break
        for p in posts:
            title = bc.norm(bc.html.unescape(re.sub(r"<[^>]+>", " ", p["title"]["rendered"])))
            body = bc.norm(bc.html.unescape(re.sub(r"<[^>]+>", " ", p["content"]["rendered"])))
            if grep and not re.search(grep, title + " " + body, re.I):
                continue
            out.append(dict({"posted": p["date"][:10], "title": title, "url": p["link"]}, **notice_fields(body)))
        if len(posts) < 100:
            break
        page += 1
    return out


def notice_fields(t):
    def grab(rx):
        m = re.search(rx, t, re.I | re.S)
        return bc.norm(m.group(1)) if m else None
    return {
        "par_not_to_exceed": grab(r"not to exceed (\$[\d,]+)"),
        "hearing": grab(r"will hold a public hearing (on .*?),? with respect to"),
        # The borrower named in the notice. A project caption alone does not identify the obligor.
        "borrower": grab(r"loaned by the Authority to (.+?)\s*\(the [“\"]?(?:Company|Borrower)"),
        "owner_statement": grab(r"([^.]*initial (?:legal )?owner[^.]*\.)"),
        "irc_section_cited": grab(r"within the meaning of (Section [\w()]+) of the Internal Revenue Code"),
        "project_location": grab(r"\(the [“\"]?Project[”\"]?\)\s*located at (.+?)(?:,\s*\(ii\)|;|\.\s)"),
        "written_comments": grab(r"([^.]*submit their views in writing to (?:(?:Ms|Mr|Mrs|Dr)\. )?[^.]*\.)"),
    }


# ---------------------------------------------------------------- agenda listings

def list_docs(key):
    cfg = ISSUERS[key]
    docs, seen = [], set()
    for page in cfg["pages"]:
        try:
            html_text = bc.fetch_text(page)
        except (bc.urllib.error.URLError, OSError) as e:
            print("warning: could not load %s (%s)" % (page, e), file=sys.stderr)
            continue
        for href, text in bc.links(html_text, page):
            if not href.lower().split("?")[0].endswith(".pdf") or href in seen:
                continue
            if cfg.get("keep") and not re.search(cfg["keep"], href + " " + text):
                continue
            fname = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(href).path))
            d = bc.parse_date(text) or bc.parse_date(fname)
            if d is None:
                continue
            seen.add(href)
            low = (fname + " " + text).lower()
            kind = "minutes" if "minute" in low else "agenda"
            stage = "preliminary" if "prel" in low else ("final" if "final" in low else None)
            docs.append({"issuer": key, "date": d.isoformat(), "kind": kind, "stage": stage, "label": text or fname,
                         "file": fname, "url": href, "canceled": "cancel" in low})
    if not docs:
        sys.exit("%s: no dated PDF links found on %s; the page layout may have changed" % (key, ", ".join(cfg["pages"])))
    return sorted(docs, key=lambda x: (x["date"], x["kind"]))


def scan(doc, cache, terms):
    text = bc.pdf_text(bc.get_pdf(doc["url"], cache, doc["issuer"]))
    if not bc.has_text_layer(text):
        return dict(doc, text_layer=False, hits=[], notice_of_sale=False)
    rx = re.compile(terms, re.I)
    hits = []
    for pno, page in enumerate(text.split("\f"), 1):
        lines = [ln.strip() for ln in page.split("\n")]
        idx = [i for i, ln in enumerate(lines) if ln and rx.search(ln)]
        # Matches on neighbouring lines are one passage; report each passage once.
        groups = []
        for i in idx:
            if groups and i - groups[-1][-1] <= 2:
                groups[-1].append(i)
            else:
                groups.append([i])
        for g in groups:
            ctx = bc.norm(" ".join(x for x in lines[max(0, g[0] - 1):g[-1] + 2] if x))
            hits.append({"page": pno, "line": lines[g[0]], "context": ctx, "notice_of_sale": bool(SALE_RE.search(ctx))})
    return dict(doc, text_layer=True, hits=hits, notice_of_sale=any(h["notice_of_sale"] for h in hits))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--yes", action="store_true", help="allow downloads over the size guard")
    common.add_argument("--cache", default=bc.DEFAULT_CACHE)
    common.add_argument("--since", help="earliest date (default: Jan 1 of this year)")
    common.add_argument("--grep", help="regex; for agendas it is added to the default financing terms")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("lpfa-notices", parents=[common])
    a = sp.add_parser("agendas", parents=[common])
    a.add_argument("issuer", choices=sorted(ISSUERS))
    a.add_argument("--until")
    a.add_argument("--kind", choices=["agenda", "minutes", "all"], default="all")
    a.add_argument("--only", action="store_true", help="match only --grep, not the default financing terms")
    a.add_argument("--list", action="store_true", help="list documents without downloading")
    args = ap.parse_args()
    today = datetime.date.today()
    since = bc.arg_date(args.since) if args.since else datetime.date(today.year, 1, 1)

    if args.cmd == "lpfa-notices":
        rows = lpfa_notices(since, args.grep)
        if args.json:
            return print(json.dumps(rows, indent=2))
        if not rows:
            print("No LPFA public notices since %s%s." % (since, " matching %r" % args.grep if args.grep else ""))
            return
        for r in rows:
            print("## %s — %s\n%s" % (r["posted"], r["title"], r["url"]))
            for k in ("par_not_to_exceed", "hearing", "borrower", "owner_statement", "irc_section_cited", "project_location", "written_comments"):
                if r.get(k):
                    print("- **%s:** %s" % (k.replace("_", " "), r[k]))
            print()
        print("Check the IRC section the notice cites against what it describes (financing posture, Tier 1).")
        return

    until = bc.arg_date(args.until) if args.until else today + datetime.timedelta(days=60)
    docs = [d for d in list_docs(args.issuer) if since.isoformat() <= d["date"] <= until.isoformat()
            and (args.kind == "all" or d["kind"] == args.kind)]
    if args.list:
        if args.json:
            return print(json.dumps(docs, indent=2))
        for d in docs:
            print("%s  %-7s %-11s %s%s" % (d["date"], d["kind"], d["stage"] or "", d["url"], "  (canceled)" if d["canceled"] else ""))
        return
    terms = args.grep if args.only and args.grep else DEFAULT_TERMS + ("|" + args.grep if args.grep else "")
    try:
        bc.guard([d["url"] for d in docs if not d["canceled"]], args.cache, args.issuer, args.yes)
    except bc.GuardStop as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)
    results = [scan(d, args.cache, terms) for d in docs if not d["canceled"]]
    if args.grep:
        user = re.compile(args.grep, re.I)
        for r in results:
            r["user_term_hits"] = [h for h in r["hits"] if user.search(h["context"])]
    if args.json:
        return print(json.dumps({"issuer": ISSUERS[args.issuer]["name"], "since": since.isoformat(), "until": until.isoformat(),
                                 "terms": terms, "documents": results}, indent=2))
    print("%s: %d document(s) %s to %s\n" % (ISSUERS[args.issuer]["name"], len(results), since, until))
    for r in results:
        hits = r.get("user_term_hits", r["hits"]) if args.grep else r["hits"]
        flag = ""
        if not r["text_layer"]:
            print("- %s %s %s: no text layer (scanned); OCR it with bayou:document-ocr before relying on this. %s"
                  % (r["date"], r["kind"], r["stage"] or "", r["url"]))
            continue
        print("### %s %s%s (%d hit%s)%s\n%s" % (r["date"], r["kind"], " " + r["stage"] if r["stage"] else "", len(hits),
                                               "" if len(hits) == 1 else "s", flag, r["url"]))
        for h in hits[:15]:
            print("- p.%d: %s" % (h["page"], h["context"]))
        if len(hits) > 15:
            print("- ... %d more (use --json)" % (len(hits) - 15))
        # Listed on its own because it may belong to a different agenda item than the --grep hits.
        for h in r["hits"]:
            if h["notice_of_sale"]:
                print("- **notice of sale** p.%d: %s" % (h["page"], h["context"]))
        print()
    if args.grep and not any(r.get("user_term_hits") for r in results):
        print("No document in this range matches %r. Absence here is not evidence the item never went before"
              " the board; agendas can be posted late, renamed, or scanned without text." % args.grep)


if __name__ == "__main__":
    main()
