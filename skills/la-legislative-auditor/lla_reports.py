#!/usr/bin/env python3
"""Search the Louisiana Legislative Auditor's public audit reports. No browser, no key.

These are the JSON feeds the auditor's own report pages call.

  lla_reports.py search "Industrial Tax Exemption" [--type Performance] [--year 2022] [--month 10]
  lla_reports.py parish Ascension [--grep "Industrial|Port"] [--type Contracted] [--year 2026]
  lla_reports.py agency "Louisiana Public Facilities Authority" [--year 2026]
  lla_reports.py agencies "public facilities"       # exact names the agency command accepts
  lla_reports.py new                                # the auditor's recent-releases feed

Every command takes --limit N (default 50, 0 for all) and --json.
Exit 0 with rows, 1 with no rows (the site answered), 2 when the site could not be read.
Standard library only.
"""
import argparse, json, re, sys, time
import urllib.error, urllib.parse, urllib.request

BASE = "https://app.lla.la.gov/"
UA = {"User-Agent": "Mozilla/5.0 (bayou-la-legislative-auditor)"}
PAGE = 10000  # the most the auditor's own pages ask a view for at once
TYPES = ["Actuarial", "Advisory", "Contracted", "Data Analytics Medicaid", "Executive", "Financial",
         "Investigative", "Performance", "Recovery"]
# The parish feed files these two under spellings people rarely type.
PARISH_ALIASES = {"de soto": "DeSoto", "la salle": "Lasalle", "saint": "St."}
DOWN = ("could not read the auditor's site ({}). This says nothing about whether a report exists.\n"
        "Try https://lla.la.gov/reports/audit-reports in a browser, or a web search limited to "
        "lla.la.gov, and report the result as not checked here.")


class SiteError(Exception):
    pass


def fetch(path, tries=3):
    url = BASE + path
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # A 4xx will not change on retry; a 5xx often does.
            if e.code < 500 or attempt == tries - 1:
                raise SiteError(f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == tries - 1:
                raise SiteError(str(getattr(e, "reason", e))) from e
        time.sleep(2 * (attempt + 1))
    raise SiteError("no response")


def parse_feed(text):
    """Rows from a feed. An empty view answers 200 with an HTML fragment inside the JSON."""
    if "No documents found" in text[:200]:
        return []
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SiteError(f"a report feed did not return JSON, so its format may have changed: {e}") from e
    rows = data.get("data") if isinstance(data, dict) else data
    if rows is None:
        raise SiteError("a report feed returned JSON without its data list, so its format may have changed")
    return [r for r in rows if r]


def view(name, category=None):
    """Every row of a view, paging past the per-request cap."""
    rows, start = [], 1
    while True:
        q = f"{name}?OpenView&Count={PAGE}&Start={start}"
        if category:
            q += "&RestrictToCategory=" + urllib.parse.quote(category)
        page = parse_feed(fetch("publicreports.nsf/" + q))
        rows += page
        if len(page) < PAGE:
            return rows
        start += PAGE
        time.sleep(1)


def norm(row):
    """One report. The feeds have no separate title: `agency` holds 'Entity - Title' or just the entity."""
    published = (row.get("agency") or "").strip()
    link = row.get("reportlink") or ""
    summary = row.get("summarylink") or ""
    # Feeds mix two hostnames for one report; use the one the auditor's own pages link to.
    host = re.compile(r"^https?://app\.lla\.state\.la\.us/", re.I)
    # `date` is the date the auditor posted the report. Reports loaded in bulk carry the load date,
    # years after the report's own: the March 2000 LPFA audit shows 2005-02-18.
    return {"date": iso(row.get("issuedatesort"), row.get("issuedate")),
            "title": published,
            "entity": published.split(" - ")[0].strip(),
            "type": (row.get("serviceweb") or "").strip(),
            "work": (row.get("worktype") or "").strip(),  # printed as published; some are bare codes
            "period": (row.get("period") or "").strip(),
            "report_number": (row.get("acn") or "").strip(),
            "link": host.sub("https://lla.la.gov/", link),
            "summary": host.sub("https://lla.la.gov/", summary)}


def iso(sort_key, shown):
    if sort_key and re.fullmatch(r"\d{8}", sort_key):
        return f"{sort_key[:4]}-{sort_key[4:6]}-{sort_key[6:]}"
    return (shown or "").strip()


def keep(rows, a):
    out = [norm(r) for r in rows]
    if getattr(a, "type", None):
        out = [r for r in out if r["type"].lower() == a.type.lower()]
    if getattr(a, "year", None):
        out = [r for r in out if r["date"].startswith(str(a.year))]
    if getattr(a, "month", None):
        out = [r for r in out if r["date"][5:7] == f"{a.month:02d}"]
    if getattr(a, "grep", None):
        rx = re.compile(a.grep, re.I)
        out = [r for r in out if rx.search(r["title"])]
    return sorted(out, key=lambda r: r["date"], reverse=True)


def show(rows, a, scope):
    total = len(rows)
    shown = rows[:a.limit] if a.limit else rows
    if a.json:
        print(json.dumps({"scope": scope, "total": total, "reports": shown}, indent=1))
    elif not rows:
        print(f"0 reports: {scope}. The site answered. Not finding a report here does not mean no audit exists.")
    else:
        print(f"{total} report(s): {scope}" + (f"; newest {len(shown)} shown, --limit 0 for all" if len(shown) < total else ""))
        for r in shown:
            kind = r["type"] + (f" / {r['work']}" if r["work"] else "")
            print(f"{r['date']}  {kind or '?'}  {r['title']}")
            print(f"    entity: {r['entity']}  period: {r['period'] or '?'}  no. {r['report_number']}")
            print(f"    {r['link']}" + (f"\n    summary: {r['summary']}" if r["summary"] else ""))
    return 0 if rows else 1


def cmd_search(a):
    params = {"query": a.terms}
    if a.type:
        params["sa"] = a.type
    if a.year:
        params["issueyear"] = str(a.year)
    if a.month:
        params["issuemonth"] = f"{a.month:02d}"
    text = fetch("publicreports.nsf/searchReportsJSON-V1.20?OpenAgent&" + urllib.parse.urlencode(params))
    return show(keep(parse_feed(text), a), a, f'names field contains every word of "{a.terms}"')


def parish_name(name):
    key = name.strip()
    for alias, real in PARISH_ALIASES.items():
        if key.lower().startswith(alias):
            key = real + key[len(alias):]
    return re.sub(r"\s+parish$", "", key, flags=re.I)


def cmd_parish(a):
    name = parish_name(a.parish)
    return show(keep(view("vwPRByParishJSON", name), a), a, f'filed under parish "{name}"')


def agency_names():
    try:
        return [r["custname"] for r in json.loads(fetch("agentcentral.nsf/getAgencyListJSON?Open")) if r.get("custname")]
    except ValueError as e:
        raise SiteError(f"the agency list did not return JSON: {e}") from e


def cmd_agency(a):
    rows = keep(view("vwPRByAgencyJSON", a.name), a)
    code = show(rows, a, f'agency "{a.name}"')
    if not rows and not a.json:
        words = [w.lower() for w in a.name.split()]
        close = [n for n in agency_names() if all(w in n.lower() for w in words)]
        print("The agency command needs the exact name. Try `agencies`" +
              (": " + "; ".join(close[:10]) if close else "."))
    return code


def cmd_agencies(a):
    words = a.terms.lower().split()
    names = [n for n in agency_names() if all(w in n.lower() for w in words)]
    names = names[:a.limit] if a.limit else names
    print(json.dumps(names, indent=1) if a.json else ("\n".join(names) or "0 agency names match."))
    return 0 if names else 1


def cmd_new(a):
    return show(keep(parse_feed(fetch("publicreports.nsf/vwPRNew-21daysJSON?OpenView")), a), a, "recent-releases feed")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **flags):
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        s.add_argument("--limit", type=int, default=50)
        s.add_argument("--json", action="store_true")
        if flags.get("filters"):
            s.add_argument("--type", choices=TYPES, type=lambda v: next((t for t in TYPES if t.lower() == v.lower()), v))
            s.add_argument("--year", type=int)
            s.add_argument("--month", type=int, choices=range(1, 13), metavar="1-12")
        if flags.get("grep"):
            s.add_argument("--grep", help="regex on the published title, applied after fetching")
        return s

    add("search", cmd_search, filters=True).add_argument("terms")
    add("parish", cmd_parish, filters=True, grep=True).add_argument("parish")
    add("agency", cmd_agency, filters=True, grep=True).add_argument("name")
    add("agencies", cmd_agencies).add_argument("terms")
    add("new", cmd_new, filters=True, grep=True)

    a = p.parse_args()
    try:
        return a.fn(a)
    except SiteError as e:
        print(DOWN.format(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
