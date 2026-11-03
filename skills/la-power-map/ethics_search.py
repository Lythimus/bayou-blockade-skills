#!/usr/bin/env python3
"""Search the Louisiana Ethics Administration's lobbyist and campaign-finance portals.

    ethics_search.py lobbyists [<company>] [--lobbyist <last name>] [--past]
    ethics_search.py contributions <contributor-name> [--from MM/DD/YYYY] [--to MM/DD/YYYY]
    ethics_search.py officials [--contributions FILE.csv] [--section REGEX] [--roster FILE.md]

Output is CSV on stdout. Standard library only.
"""
import argparse
import csv
import datetime
import glob
import html
import http.cookiejar
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
LOBBY = "https://ethics.la.gov/LobbyistData/SearchByCompRep.aspx"
CF_BASE = "https://www.ethics.la.gov/CampaignFinanceSearch/"
P = "ctl00$ContentPlaceHolder1$"


def session():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch(opener, url, data=None, referer=None, timeout=180):
    headers = dict(UA)
    if referer:
        headers["Referer"] = referer
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    resp = opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=timeout)
    return resp.read().decode("utf-8", "replace")


def hidden_fields(page):
    fields = {}
    for tag in re.findall(r'<input[^>]*type="hidden"[^>]*>', page):
        name = re.search(r'name="([^"]*)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[name.group(1)] = html.unescape(value.group(1)) if value else ""
    return fields


def table_rows(page, min_cells):
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        ]
        if len(cells) >= min_cells and any(cells):
            rows.append(cells)
    return rows


def lobbyist_page(company_op, company, include_past, lobbyist):
    """One search; returns (rows, number of result pages)."""
    opener = session()
    form = fetch(opener, LOBBY)
    data = hidden_fields(form)
    data.update({
        P + "LastNameTextBox": lobbyist,
        P + "RepNameDropDownList": company_op,
        P + "RepNameTextBox": company,
        P + "PaidDropDownList": "Select...",
        P + "SubjMatterDropDownList": "All Subject Matters",
        P + "CurrentDropDownList": "Include Past Representations" if include_past else "Currently Representing Only",
        P + "BrDropDownList": "Contains",
        P + "BranchDropDownList": "Select...",
        P + "AndOrRadioButtonList": "AND",
        # 100 is the largest page the form offers.
        P + "PageSizeDropDownList": "100",
        P + "OrderByDropDownList": "[Rep_Name]",
        P + "SearchButton": "Find Records",
    })
    page = fetch(opener, LOBBY, data, referer=LOBBY)
    pages = re.search(r'CurrentPageLabel"[^>]*>\s*of\s*(\d+)', page)
    total = int(pages.group(1)) if pages else 1
    # An unfiltered result set means the search parameters were dropped (the results
    # page falls back to every registration on file when it has no session state).
    if total >= 100:
        sys.exit("lobbyist search returned the unfiltered list; the form fields may have changed")
    rows = []
    for cells in table_rows(page, 5):
        if len(cells) != 5 or cells[1] == "Paid?":
            continue
        # The header row is merged into the first cell of the grid's caption row.
        if cells[0].startswith("Results by Company Representation"):
            continue
        rows.append(cells)
    return rows, total


def lobbyists(company, include_past, lobbyist=""):
    """With only `lobbyist` (a last name), lists every client that lobbyist registered for;
    the script-rendered LobbyistDetail page cannot be read without a browser."""
    header = [["company", "paid", "branch", "lobbyist", "dates_represented"]]
    rows, pages = lobbyist_page("Contains", company, include_past, lobbyist)
    if pages == 1:
        return header + rows
    if company:
        sys.exit("more than 100 registrations; use a longer company name or add --lobbyist")
    # The grid's Next button posts back into a reset search, so a long client list is
    # fetched as one search per first character of the company name instead.
    buckets = [("Less Than", "A")] + [("Begins With", c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [("Greater Than", "ZZZZZZZZ")]
    seen, out = set(), []
    for op, value in buckets:
        part, pages = lobbyist_page(op, value, include_past, lobbyist)
        if pages > 1:
            sys.exit("more than 100 registrations starting with %r; narrow by lobbyist name" % value)
        for r in part:
            if tuple(r) not in seen:
                seen.add(tuple(r))
                out.append(r)
    return header + sorted(out, key=lambda r: r[0].lower())


def contributions(name, date_from, date_to):
    search_page = "SearchEfilingContributors.aspx"
    results_page = "SearchResultsByContributions.aspx"
    name_field = "ContNameTextBox"
    opener = session()
    url = CF_BASE + search_page
    form = fetch(opener, url)
    if (P + name_field) not in form:
        sys.exit("field %s not found on %s; the form has changed" % (name_field, search_page))
    data = hidden_fields(form)
    data.update({
        "__EVENTTARGET": P + "PerformSearchLinkButton",
        "__EVENTARGUMENT": "",
        P + name_field: name,
    })
    # The POST answers with a frameset that redirects; the results live in the session,
    # so the results page has to be requested on the same cookie jar.
    fetch(opener, url, data, referer=url)
    page = fetch(opener, CF_BASE + results_page, referer=url)
    count = re.search(r'id="ctl00_ContentPlaceHolder1_CountLabel"[^>]*>([^<]*)', page)
    print(count.group(1).strip() if count else "no record count on results page", file=sys.stderr)
    export = hidden_fields(page)
    export.update({"__EVENTTARGET": P + "ExportToCSVLinkButton", "__EVENTARGUMENT": ""})
    body = fetch(opener, CF_BASE + results_page, export, referer=CF_BASE + results_page)
    if body.lstrip().startswith("<"):
        sys.exit("CSV export returned HTML; fall back to the results grid at " + CF_BASE + results_page)
    rows = [[c.strip() for c in r] for r in csv.reader(body.splitlines())]
    if not (date_from or date_to) or not rows:
        return rows
    # The form's date boxes are Telerik widgets whose state is built in the browser, and a
    # plain POST of the date text is ignored, so the range is applied to the export here.
    col = rows[0].index("ContributionDate")
    parse = lambda s: datetime.datetime.strptime(s, "%m/%d/%Y").date()
    lo = parse(date_from) if date_from else datetime.date.min
    hi = parse(date_to) if date_to else datetime.date.max
    kept = [r for r in rows[1:] if len(r) > col and r[col] and lo <= parse(r[col]) <= hi]
    print("%d records in the requested date range." % len(kept), file=sys.stderr)
    return [rows[0]] + kept


ROSTER_PATH = os.path.join("skills", "scp-meeting-record", "references", "officials.md")
SUFFIX = re.compile(r"[,\s]+(jr|sr|ii|iii|iv|v)\.?$", re.I)


def find_roster(given=None):
    """The optional scp-civics officials roster. Checks a sibling checkout, then the home plugin
    folder, then installed plugin copies, so bayou never depends on where scp-civics lives, or on having it."""
    if given:
        return given if os.path.isfile(given) else None
    here = os.path.dirname(os.path.abspath(__file__))
    plugins = os.path.expanduser(os.path.join("~", ".claude", "plugins"))
    spots = [os.path.join(here, "..", "..", "..", "scp-civics", ROSTER_PATH),
             os.path.join(plugins, "scp-civics", ROSTER_PATH)]
    spots += sorted(glob.glob(os.path.join(plugins, "cache", "*", "scp-civics", "*", ROSTER_PATH)), reverse=True)
    return next((os.path.normpath(p) for p in spots if os.path.isfile(p)), None)


def read_roster(path):
    """(generated date or '', [(name, section)]). The first table column is the name; a parenthetical is a seat."""
    generated, section, people = "", "", []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.search(r"Generated by .*? on (\d{4}-\d{2}-\d{2})", line)
            if m:
                generated = m.group(1)
            if line.startswith("## "):
                section = line[3:].strip()
            elif line.startswith("|") and not re.match(r"\|\s*(-+|Name)\s*\|", line):
                name = re.sub(r"\s*\(.*?\)", "", line.split("|")[1]).strip()
                if name:
                    people.append((name, section))
    return generated, people


def fold(text):
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", plain.lower())


def surname(name):
    parts = SUFFIX.sub("", name.strip()).split()
    return fold(parts[-1]) if parts else ""


def match_filers(path, people):
    """Contribution rows whose filer shares a surname with someone on the roster. Filers have separate name
    fields; a matching first name is labeled, because a surname alone is often someone else."""
    by_last = {}
    for name, section in people:
        by_last.setdefault(surname(name), []).append((name, section))
    out = [["match", "official", "section", "filer", "report", "contributor", "date", "amount"]]
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            last, first = r.get("FilerLastName") or "", r.get("FilerFirstName") or ""
            for name, section in by_last.get(surname(last), []):
                given = fold(name.split()[0])
                full = bool(fold(first)) and (given.startswith(fold(first)) or fold(first).startswith(given))
                out.append(["first and last" if full else "last name only", name, section, (first + " " + last).strip(),
                            r.get("ReportNumber", ""), r.get("ContributorName", ""), r.get("ContributionDate", ""),
                            r.get("ContributionAmt", "")])
    return out


def officials(args):
    path = find_roster(args.roster)
    if not path:
        print("no officials roster found (it comes from the optional scp-civics plugin); give officials of "
              "interest by name instead. Nothing was checked against a roster.", file=sys.stderr)
        return 3
    generated, people = read_roster(path)
    if args.section:
        people = [p for p in people if re.search(args.section, p[1], re.I)]
    print("St. Charles Parish roster generated %s, %d names. It lists current officials of one parish; "
          "a name match is a lead, not an identification." % (generated or "on an unknown date", len(people)), file=sys.stderr)
    rows = match_filers(args.contributions, people) if args.contributions else [["official", "section"]] + people
    csv.writer(sys.stdout).writerows(rows)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lob = sub.add_parser("lobbyists")
    lob.add_argument("company", nargs="?", default="")
    lob.add_argument("--lobbyist", default="", help="lobbyist last name; alone, lists all of that lobbyist's clients")
    lob.add_argument("--past", action="store_true", help="include ended representations")
    cf = sub.add_parser("contributions")
    cf.add_argument("name")
    cf.add_argument("--from", dest="date_from")
    cf.add_argument("--to", dest="date_to")
    of = sub.add_parser("officials", help="optional: the scp-civics roster, or a contributions CSV checked against it")
    of.add_argument("--contributions", help="CSV saved from the contributions command")
    of.add_argument("--section", help="regex on the roster section, such as 'Parish Council|Planning'")
    of.add_argument("--roster", help="roster file; found automatically if scp-civics is installed")
    args = ap.parse_args()
    if args.cmd == "officials":
        sys.exit(officials(args))
    if args.cmd == "lobbyists":
        if not (args.company or args.lobbyist):
            ap.error("give a company name, --lobbyist, or both")
        rows = lobbyists(args.company, args.past, args.lobbyist)
    else:
        rows = contributions(args.name, args.date_from, args.date_to)
    csv.writer(sys.stdout).writerows(rows)


if __name__ == "__main__":
    main()
