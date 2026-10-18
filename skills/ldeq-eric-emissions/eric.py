#!/usr/bin/env python3
"""LDEQ ERIC state emissions inventory: annual certified emissions by AI, release-point actual and
permitted rates, parish totals.

Run with: uv run -q --no-project --with openpyxl --with xlrd python -I eric.py <command> ...
The statewide xlsx files are re-checked for a new Last-Modified once a day (--refresh forces it);
radius and parish reports are cached for a day. Cache: ~/.cache/bayou/ldeq-eric-emissions/.

  eric.py health                                     sources up, years offered, crosswalk drift
  eric.py facility <AI> [--years 2015-2024]          annual criteria (tons) and TAPs (lb) by year
  eric.py search "<name>"                            AI numbers whose ERIC name matches
  eric.py peers <AI> [--year Y] [--by naics|sic]     Louisiana facilities with the same primary code
  eric.py points <AI> [--year Y|baseline] [--permitted]   release points for the AI
  eric.py radius <lat> <lon> --radius-m N --pollutant X   all facilities near a point, one pollutant
  eric.py sources <AI | lat lon --radius-m N> [--receptor lat,lon] [--strouhal]   low-frequency noise candidates
  eric.py parish "<parish|all>" --pollutant X --year Y    parish totals
  eric.py reconcile <AI> --year Y --pollutant X      radius-report sum vs the annual xlsx value
  eric.py pollutants [query]                         name/code/CAS crosswalk
"""
import argparse
import collections
import csv
import datetime
import gzip
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/bayou/ldeq-eric-emissions")
TTL = 24 * 3600
UA = "Mozilla/5.0 (bayou-ldeq-eric-emissions)"
PUB = "https://deq.louisiana.gov/assets/docs/Air/EmissionsInventory/Public_Reports/"
XLSX = {"gte2015": PUB + "AnnualCertificationsgte2015.xlsx",
        "lt2015": PUB + "AnnualCertificationslt2015.xlsx"}
ERIC = "https://business.deq.louisiana.gov/Eric/EricReports/"
BASELINE = 1900
ID_COLS = ["REPORTING_YEAR", "AI_NUMBER", "AI_NAME", "PARISH_OR_COUNTY_DESC",
           "latitude", "longitude", "PRIMARY_NAICS_CODE", "PRIMARY_SIC_CODE"]
CRITERIA_DEFAULT = ["Nitrogen Oxides - tons", "Sulfur dioxide - tons", "Carbon monoxide - tons", "VOC, Total - tons",
                    "Particulate matter (10 microns or less) - tons", "Particulate matter (2_5 microns or less) - tons"]
WIDEN_M = [5000, 20000, 50000]
TSP_NOTE = ("Baseline is legacy EIS data of no single year; in Baseline, PM10 was reported as total suspended "
            "particulate (TSP). Do not compare Baseline PM with later PM10/PM2.5.")
PERMIT_NOTE = ("Permitted rows are TEMPO limits in current operating permits as of the retrieval date, not tied to "
               "the reporting year, and exclude pending applications. Never add rates across Statistical Basis, and "
               "never add a group's members to the group cap (Group memberships) — both double count.")


class SourceDown(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- HTTP

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_session = False


def _req(url, data=None, headers=None, method=None, timeout=180):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        return _opener.open(req, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceDown("%s: %s" % (url, e))


def eric_session():
    # The report endpoints want the ASP.NET session cookie the selector page sets; no token is involved.
    global _session
    if not _session:
        _req(ERIC + "RadiusReportSelector").read()
        _session = True


def cache_path(*parts):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, *parts)


def cached_post(endpoint, fields, ext, refresh=False):
    key = hashlib.sha1((endpoint + json.dumps(fields, sort_keys=True)).encode()).hexdigest()[:20]
    path = cache_path("%s_%s.%s" % (endpoint, key, ext))
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL:
        with open(path, "rb") as fh:
            return fh.read(), os.path.getmtime(path)
    eric_session()
    body = _req(ERIC + endpoint, urllib.parse.urlencode(fields).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"}).read()
    with open(path, "wb") as fh:
        fh.write(body)
    return body, time.time()


def html_error(body):
    t = body.decode("utf-8", "replace")
    m = re.search(r'class="[^"]*(?:validation-summary-errors|field-validation-error|error)[^"]*"[^>]*>(.*?)</', t, re.S)
    if m and m.group(1).strip():
        return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip()
    m = re.search(r"You must[^<]*", t)
    return m.group(0).strip() if m else "ERIC returned an HTML page instead of a report"


def pollutant_list(year, refresh=False):
    """ERIC's dropdown for a year: [(code, text, group)], group = CRITERIA POLLUTANTS / TOXIC AIR POLLUTANTS."""
    path = cache_path("pollutants_%s.json" % year)
    if refresh or not os.path.exists(path) or time.time() - os.path.getmtime(path) >= TTL:
        eric_session()
        body = _req(ERIC + "PopulatePollutants", json.dumps({"ReportingYear": str(year)}).encode(),
                    {"Content-Type": "application/json; charset=utf-8"}).read()
        json.loads(body)
        with open(path, "wb") as fh:
            fh.write(body)
    out, grp = [], None
    with open(path) as fh:
        for o in json.load(fh):
            v = o.get("Value") or ""
            if v in ("CRITERIA POLLUTANTS", "TOXIC AIR POLLUTANTS"):
                grp = v
            elif v:
                out.append((v, html.unescape(o.get("Text", "")), grp))
    return out


# ---------------------------------------------------------------- statewide xlsx

def _state():
    p = cache_path("state.json")
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {}


def _save_state(st):
    with open(cache_path("state.json"), "w") as fh:
        json.dump(st, fh, indent=1)


def head(url):
    r = _req(url, method="HEAD", timeout=60)
    return r.headers.get("Last-Modified"), r.headers.get("Content-Length")


def ensure_xlsx(which, refresh=False):
    """Local path and Last-Modified of one statewide file, downloading only when LDEQ has a newer one."""
    st = _state()
    s = st.get(which, {})
    path = cache_path("AnnualCertifications%s.xlsx" % which)
    fresh = time.time() - s.get("checked", 0) < TTL
    if os.path.exists(path) and fresh and not refresh:
        return path, s.get("last_modified")
    try:
        lm, _ = head(XLSX[which])
    except SourceDown:
        if os.path.exists(path):
            print("note: %s unreachable; using the copy from %s" % (XLSX[which], s.get("last_modified")), file=sys.stderr)
            return path, s.get("last_modified")
        raise
    if not os.path.exists(path) or lm != s.get("last_modified"):
        body = _req(XLSX[which], timeout=300).read()
        if body[:2] != b"PK":
            raise SourceDown("%s did not return an xlsx" % XLSX[which])
        with open(path + ".part", "wb") as fh:
            fh.write(body)
        os.replace(path + ".part", path)
    st[which] = {"checked": time.time(), "last_modified": lm}
    _save_state(st)
    return path, lm


def load_file(which, refresh=False):
    """Parsed rows of one statewide file. Blank cells are dropped from `v`, so absence means not reported."""
    path, lm = ensure_xlsx(which, refresh)
    tag = hashlib.sha1((lm or str(os.path.getmtime(path))).encode()).hexdigest()[:12]
    parsed = cache_path("parsed_%s_%s.json.gz" % (which, tag))
    if os.path.exists(parsed):
        with gzip.open(parsed, "rt") as fh:
            return json.load(fh)
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = [str(h).strip() if h is not None else "" for h in next(it)]
    if hdr[:len(ID_COLS)] != ID_COLS:
        raise SourceDown("%s: unexpected leading columns %s" % (which, hdr[:len(ID_COLS)]))
    pcols = hdr[len(ID_COLS):]
    rows = []
    for r in it:
        if r[0] is None or r[1] is None:
            continue
        v = {pcols[i]: x for i, x in enumerate(r[len(ID_COLS):]) if x is not None and x != ""}
        rows.append({"year": int(r[0]), "ai": int(r[1]), "name": (r[2] or "").strip(),
                     "parish": (r[3] or "").strip(), "lat": r[4], "lon": r[5],
                     "naics": str(r[6]).strip() if r[6] is not None else "",
                     "sic": str(r[7]).strip() if r[7] is not None else "", "v": v})
    data = {"file": os.path.basename(XLSX[which]), "url": XLSX[which], "last_modified": lm,
            "columns": pcols, "rows": rows}
    for old in os.listdir(CACHE):
        if old.startswith("parsed_%s_" % which):
            os.remove(os.path.join(CACHE, old))
    with gzip.open(parsed, "wt") as fh:
        json.dump(data, fh)
    return data


def merge_certifications(rows):
    """One record per AI-year. When ownership changes mid-year, each owner certifies its own part of the year
    as a separate row; the facility-year value is their sum, and `parts` keeps each certification. Rows whose
    pollutant values are identical are the same certification listed twice (often under the old and new
    owner's name); the radius report carries it once, so it is kept once."""
    by = collections.OrderedDict()
    for r in rows:
        by.setdefault((r["ai"], r["year"]), []).append(r)
    out = []
    for grp in by.values():
        if len(grp) == 1:
            out.append(grp[0])
            continue
        m = dict(grp[-1])
        if all(r["v"] == grp[0]["v"] for r in grp):
            m["name"] = " + ".join(dict.fromkeys(r["name"] for r in grp))
            m["duplicate_of"] = [r["name"] for r in grp]
            out.append(m)
            continue
        v = {}
        for r in grp:
            for c, x in r["v"].items():
                if isinstance(x, (int, float)):
                    v[c] = v.get(c, 0) + x
                else:
                    v.setdefault(c, x)
        m["v"] = v
        m["name"] = " + ".join(dict.fromkeys(r["name"] for r in grp))
        m["parts"] = [{"name": r["name"], "v": r["v"]} for r in grp]
        out.append(m)
    return out


class Inventory:
    def __init__(self, refresh=False):
        self.files = {w: load_file(w, refresh) for w in ("lt2015", "gte2015")}
        self.rows = merge_certifications(self.files["lt2015"]["rows"] + self.files["gte2015"]["rows"])
        self.cols = {w: set(f["columns"]) for w, f in self.files.items()}
        # A column can sit in the file for years before LDEQ began collecting it (POM is in the 2015+
        # file but first holds data in 2025). Outside the statewide first..last year with any value, a
        # blank means not collected rather than not reported.
        self.span = {}
        for r in self.rows:
            for c in r["v"]:
                lo, hi = self.span.get(c, (r["year"], r["year"]))
                self.span[c] = (min(lo, r["year"]), max(hi, r["year"]))
        n = collections.Counter(r["year"] for r in self.rows)
        self.ai_count = dict(sorted(n.items()))
        years = sorted(n)
        # The newest year fills in over months (late certifications and revisions arrive all year);
        # treat a year as complete once it has at least 90% of the prior year's facilities.
        self.complete = max(y for y in years if y - 1 not in n or n[y] >= 0.9 * n[y - 1])

    def era(self, year):
        return "gte2015" if year >= 2015 else "lt2015"

    def collected(self, col, year):
        lo, hi = self.span.get(col, (None, None))
        return col in self.cols[self.era(year)] and lo is not None and lo <= year <= hi

    def source(self, year):
        f = self.files[self.era(year)]
        return "%s (Last-Modified %s)" % (f["file"], f["last_modified"])

    def for_ai(self, ai):
        return sorted((r for r in self.rows if r["ai"] == ai), key=lambda r: r["year"])

    def all_columns(self):
        seen, out = set(), []
        for w in ("gte2015", "lt2015"):
            for c in self.files[w]["columns"]:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out


# ---------------------------------------------------------------- crosswalk

def crosswalk():
    with open(os.path.join(HERE, "pollutants.csv"), newline="") as fh:
        return list(csv.DictReader(fh))


def resolve(q, rows=None):
    """Crosswalk rows matching a name (with or without unit), ERIC code, ERIC form text, or CAS. Exact only."""
    rows = rows or crosswalk()
    k = q.strip().lower()
    def keys(r):
        # The ERIC form text ends in the usual abbreviation, e.g. "(NOx)", "(PM2.5)", "(SO2)".
        abbr = re.findall(r"\(([A-Za-z0-9.]+)\)\s*$", r["eric_text"])
        base = r["xlsx_name"].rsplit(" - ", 1)[0]
        return {r["xlsx_name"].lower(), base.lower(), re.sub(r"\s*\(Table 51_\d\)", "", base).lower(),
                r["eric_text"].lower(),
                r["eric_code"].lower(), r["eric_code_baseline"].lower(), r["cas"].lower()} | \
               {x.lower() for x in abbr}
    hits = [r for r in rows if k and k in keys(r)]
    if len(hits) > 1:
        # "Lead" names the criteria column exactly; prefer an exact xlsx-name hit over a CAS or text hit.
        exact = [r for r in hits if r["xlsx_name"].rsplit(" - ", 1)[0].lower() == k or r["xlsx_name"].lower() == k]
        hits = exact or hits
    return hits


def resolve_one(q, rows=None):
    hits = resolve(q, rows)
    if len(hits) == 1:
        return hits[0]
    rows = rows or crosswalk()
    if not hits:
        sug = [r["xlsx_name"] or r["eric_text"] for r in rows
               if q.lower() in (r["xlsx_name"] + " " + r["eric_text"]).lower()][:12]
        die("pollutant %r not in pollutants.csv. %s" % (q, ("Candidates: " + "; ".join(sug)) if sug
                                                       else "Run `eric.py pollutants` to list names."))
    die("pollutant %r is ambiguous: %s" % (q, "; ".join(r["xlsx_name"] or r["eric_text"] for r in hits)))


def code_for(row, year):
    """Radius-report code for a year. Before 2021 the dropdown uses the Baseline-era codes for some
    pollutants (Lead (Pb) 002573, TSP 001810), so check the year's own list."""
    if year == BASELINE:
        return row["eric_code_baseline"]
    cands = [c for c in (row["eric_code"], row["eric_code_baseline"]) if c]
    if not cands:
        return ""
    try:
        offered = {c for c, _, _ in pollutant_list(year)}
    except SourceDown:
        return cands[0]
    return next((c for c in cands if c in offered), "")


# ---------------------------------------------------------------- formatting

def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        s = "{:,.6f}".format(v).rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def parse_years(s):
    if not s:
        return None
    if "-" in s:
        a, b = s.split("-", 1)
        return int(a), int(b)
    return int(s), int(s)


def parse_year(s):
    if s is None:
        return None
    return BASELINE if str(s).lower() == "baseline" else int(s)


def year_label(y):
    return "Baseline" if y == BASELINE else str(y)


def drift(recs, key):
    seen = collections.OrderedDict()
    for r in recs:
        val = r[key] if key != "coords" else (r["lat"], r["lon"])
        seen.setdefault(val, []).append(r["year"])
    return [{"value": k if key != "coords" else list(k), "years": span(v)} for k, v in seen.items()]


def span(years):
    runs = []
    for y in sorted(set(years)):
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return ",".join(str(a) if a == b else "%d-%d" % (a, b) for a, b in runs)


# ---------------------------------------------------------------- commands: statewide

def cmd_facility(a):
    inv = Inventory(a.refresh)
    recs = inv.for_ai(a.ai)
    if not recs:
        die("AI %d is not in either statewide file (it may not meet the LAC 33:III.919 / 5107 reporting "
            "thresholds, or it reports under another AI). Try `search` or ldeq-ai-lookup." % a.ai, 3)
    yr = parse_years(a.years)
    if yr:
        recs = [r for r in recs if yr[0] <= r["year"] <= yr[1]]
        if not recs:
            die("AI %d has no rows in %s" % (a.ai, a.years), 3)
    xw = {r["xlsx_name"]: r for r in crosswalk() if r["xlsx_name"]}
    if a.pollutants:
        cols = [resolve_one(p)["xlsx_name"] for p in a.pollutants.split(";")]
        cols = [c for c in cols if c]
    else:
        reported = {c for r in recs for c in r["v"]}
        cols = [c for c in inv.all_columns() if c in reported]
    cols.sort(key=lambda c: (not c.endswith(" - tons"), c.lower()))
    years = [r["year"] for r in recs]
    table = []
    for c in cols:
        vals = {}
        for r in recs:
            vals[r["year"]] = r["v"].get(c) if inv.collected(c, r["year"]) else "n/c"
        x = xw.get(c, {})
        table.append({"pollutant": c, "unit": c.rsplit(" - ", 1)[1], "cas": x.get("cas", ""),
                      "eric_code": x.get("eric_code", ""), "values": vals})
    res = {"ai": a.ai, "years": years, "complete_through": inv.complete,
           "provisional_years": [y for y in years if y > inv.complete],
           "multiple_certifications": {r["year"]: [p["name"] for p in r["parts"]] for r in recs if r.get("parts")},
           "duplicate_rows": {r["year"]: r["duplicate_of"] for r in recs if r.get("duplicate_of")},
           "names": drift(recs, "name"), "parishes": drift(recs, "parish"), "coords": drift(recs, "coords"),
           "naics": drift(recs, "naics"), "sic": drift(recs, "sic"), "table": table,
           "sources": sorted({inv.source(y) for y in years}), "retrieved": today()}
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["year", "ai", "ai_name", "pollutant", "unit", "value", "status", "cas", "eric_code", "source"])
            names = {r["year"]: r["name"] for r in recs}
            for t in table:
                for y in years:
                    v = t["values"][y]
                    status = "not collected" if v == "n/c" else "not reported" if v is None else "reported"
                    val = v if status == "reported" else ""
                    if status == "reported" and y in res["multiple_certifications"]:
                        status = "sum of %d certifications" % len(res["multiple_certifications"][y])
                    w.writerow([y, a.ai, names[y], t["pollutant"], t["unit"], val, status, t["cas"], t["eric_code"], inv.source(y)])
        res["csv"] = a.csv
    return res


def cmd_search(a):
    inv = Inventory(a.refresh)
    pat = re.compile(re.escape(a.name), re.I)
    by = collections.defaultdict(list)
    for r in inv.rows:
        if pat.search(r["name"]):
            by[r["ai"]].append(r)
    out = []
    for ai, rs in sorted(by.items(), key=lambda kv: -max(r["year"] for r in kv[1])):
        allrs = inv.for_ai(ai)
        out.append({"ai": ai, "names": drift(allrs, "name"), "parish": allrs[-1]["parish"],
                    "naics": allrs[-1]["naics"], "years": span([r["year"] for r in allrs])})
    return {"query": a.name, "matches": out}


def cmd_peers(a):
    inv = Inventory(a.refresh)
    recs = inv.for_ai(a.ai)
    if not recs:
        die("AI %d is not in the statewide files" % a.ai, 3)
    year = parse_year(a.year) if a.year else max((r["year"] for r in recs if r["year"] <= inv.complete),
                                                 default=recs[-1]["year"])
    me = next((r for r in recs if r["year"] == year), None)
    if not me:
        die("AI %d has no %d row; it reported in %s" % (a.ai, year, span([r["year"] for r in recs])), 3)
    code = me[a.by]
    if not code:
        die("AI %d has no primary %s code in %d" % (a.ai, a.by.upper(), year), 3)
    cohort = [r for r in inv.rows if r["year"] == year and r[a.by] == code]
    if a.pollutants:
        cols = [resolve_one(p)["xlsx_name"] for p in a.pollutants.split(";")]
    else:
        cols = [c for c in CRITERIA_DEFAULT if c in me["v"]]
        taps = sorted(((v, c) for c, v in me["v"].items() if c.endswith(" - lb") and isinstance(v, (int, float))),
                      reverse=True)
        cols += [c for v, c in taps[:5] if v > 0]
    out = []
    for c in cols:
        rep = sorted(((r["v"][c], r) for r in cohort if isinstance(r["v"].get(c), (int, float))),
                     key=lambda t: -t[0])
        rank = next((i + 1 for i, (v, r) in enumerate(rep) if r["ai"] == a.ai), None)
        vals = [v for v, _ in rep]
        med = sorted(vals)[len(vals) // 2] if vals else None
        out.append({"pollutant": c, "target": me["v"].get(c), "rank": rank, "of": len(rep),
                    "not_reporting": len(cohort) - len(rep), "median": med,
                    "top": [{"ai": r["ai"], "name": r["name"], "parish": r["parish"], "value": v}
                            for v, r in rep[:a.top]]})
    note = None
    if year > inv.complete:
        note = "%d is provisional (%d facilities so far vs %d in %d); the cohort is incomplete." % (
            year, inv.ai_count.get(year, 0), inv.ai_count.get(year - 1, 0), year - 1)
    return {"ai": a.ai, "name": me["name"], "year": year, "by": a.by, "code": code, "cohort_size": len(cohort),
            "cohort": [{"ai": r["ai"], "name": r["name"], "parish": r["parish"]} for r in cohort],
            "pollutants": out, "note": note, "source": inv.source(year), "retrieved": today()}


# ---------------------------------------------------------------- radius report

def check_year(year):
    # The form offers only the latest five years, but the endpoint answers for earlier years too
    # (release-point sums reconcile with the xlsx back to at least 1995).
    if year == BASELINE:
        return
    newest = max((int(v) for v in available_years() if v != str(BASELINE)), default=None)
    if year < 1991 or (newest and year > newest):
        die("ERIC has no %d data (inventory years run 1991-%s, plus Baseline)." % (year, newest), 3)


def radius_report(year, code, lat, lon, radius_m, permitted=False, refresh=False):
    check_year(year)
    fields = {"ReportType": "Both" if permitted else "Actual", "ReportingYear": str(year), "PollutantCode": code,
              "CoordType": "LatLon", "Latitude": "%.6f" % lat, "Longitude": "%.6f" % lon, "Radius": str(int(radius_m))}
    body, fetched = cached_post("RadiusReport", fields, "xls", refresh)
    if body[:4] != b"\xd0\xcf\x11\xe0":
        if b"No results were returned" in body:
            empty = {"meta": {}, "header": [], "rows": [], "unit": None, "value_col": None}
            return {"params": fields, "retrieved": datetime.date.fromtimestamp(fetched).isoformat(),
                    "actual": empty, "permitted": dict(empty) if permitted else None, "no_results": True}
        raise SourceDown("RadiusReport %s: %s" % (fields, html_error(body)))
    import xlrd
    with open(os.devnull, "w") as quiet:
        book = xlrd.open_workbook(file_contents=body, logfile=quiet)
    out = {"params": fields, "retrieved": datetime.date.fromtimestamp(fetched).isoformat(),
           "actual": None, "permitted": None}
    for sh in book.sheets():
        if not sh.nrows:
            continue
        title = str(sh.cell_value(0, 0))
        kind = "permitted" if (sh.name == "PermittedEmissions" or "Permitted" in title) else \
               "actual" if (sh.name == "ActualEmissions" or "Actual" in title) else None
        hr = next((r for r in range(min(sh.nrows, 40)) if str(sh.cell_value(r, 0)).strip() == "AI Number"), None)
        if kind is None or hr is None:
            continue
        meta = {}
        for r in range(hr):
            k, v = str(sh.cell_value(r, 0)).strip().rstrip(":"), sh.cell_value(r, 1)
            if k and v != "":
                meta[k] = v
        # Actual-sheet headers wrap their units onto a second line ("Height\n(ft)").
        hdr = [re.sub(r"\s+", " ", str(h)).strip() for h in sh.row_values(hr)]
        rows = []
        for r in range(hr + 1, sh.nrows):
            vals = sh.row_values(r)
            if vals[0] == "":
                continue
            d = dict(zip(hdr, vals))
            d["AI Number"] = int(d["AI Number"])
            rows.append(d)
        unit = None
        if kind == "actual":
            m = re.search(r"Emissions \(([^)]+)\)\s*$", hdr[-1])
            unit = m.group(1) if m else None
        out[kind] = {"meta": meta, "header": hdr, "rows": rows, "unit": unit, "value_col": hdr[-1]}
    if out["actual"] is None and out["permitted"] is None:
        raise SourceDown("RadiusReport returned a workbook with no recognizable report sheet")
    return out


def ai_actual(rep, ai):
    rows = [r for r in rep["actual"]["rows"] if r["AI Number"] == ai] if rep["actual"] else []
    vc = rep["actual"]["value_col"] if rep["actual"] else None
    if not vc:
        return [], 0
    return rows, sum((r[vc] or 0) for r in rows if isinstance(r[vc], (int, float)))


def center_for(inv, ai, year):
    recs = [r for r in inv.for_ai(ai) if r["lat"] and r["lon"]]
    if not recs:
        return None, None
    pick = next((r for r in recs if r["year"] == year), recs[-1])
    return pick, (float(pick["lat"]), float(pick["lon"]))


def fetch_for_ai(ai, year, code, center, expected, start_m, permitted, refresh, widen=True):
    """Radius report around the AI's xlsx coordinate, widening while the AI's sum falls short of the xlsx."""
    steps = [m for m in WIDEN_M if m > start_m] if widen else []
    tried = []
    for m in [start_m] + steps:
        rep = radius_report(year, code, center[0], center[1], m, permitted, refresh)
        rows, total = ai_actual(rep, ai)
        tried.append(m)
        short = expected is not None and total < expected * (1 - 1e-9) - 1e-9
        if rows and not short:
            break
        if expected is None and rows:
            break
    return rep, rows, total, tried


def actual_view(rows, vc):
    keep = ["Release Point ID", "EIQ Point ID No.", "Source ID", "Source Type", "Source Status", "Source Description",
            "Release Point Type", "Release Point Description", "Height (ft)", "Exit Gas Temperature (deg F)",
            "Diameter (ft)", "Exit Gas Velocity (ft/sec)", "Exit Gas Flow Rate (cfs)", "Orientation (degrees)",
            "Width (ft)", "Length (ft)", "Permit No.", "Release Point Latitude (dec. deg)",
            "Release Point Longitude (dec. deg)", "Distance from Center Point (m)"]
    out = []
    for r in rows:
        d = {k: r.get(k) for k in keep if k in r}
        d["value"] = r[vc]
        out.append(d)
    return sorted(out, key=lambda d: -(d["value"] if isinstance(d["value"], (int, float)) else 0))


def permitted_view(rep, ai):
    if not rep["permitted"]:
        return {}
    by = collections.OrderedDict()
    for r in rep["permitted"]["rows"]:
        if r["AI Number"] != ai:
            continue
        basis = str(r.get("Statistical Basis", "")).strip() or "(no basis)"
        by.setdefault(basis, []).append({k: r.get(k) for k in (
            "Permit No.", "Permit Type", "Activity No.", "EIQ Point ID No.", "Subject Item ID", "Subject Item Type",
            "Subject Item Description", "Emission Rate", "Emission Rate Units", "Phase Description",
            "Group memberships", "ERIC Release Point ID", "Height", "Height Units", "Diameter", "Diameter Units",
            "Exit Gas Velocity", "Exit Gas Velocity Units", "Exit Gas Temperature", "Exit Gas Temperature Units",
            "Exit Gas Flow Rate", "Exit Gas Flow Rate Units", "Release Point Latitude (dec deg)",
            "Release Point Longitude (dec deg)") if k in r})
    return by


def cmd_points(a):
    inv = Inventory(a.refresh)
    year = parse_year(a.year) if a.year else min(max(r["year"] for r in inv.for_ai(a.ai) or [{"year": 0}]),
                                                 inv.complete)
    pick, center = center_for(inv, a.ai, year)
    if not center:
        die("AI %d has no coordinates in the statewide files; pass the facility's coordinates to `radius`." % a.ai, 3)
    xw = crosswalk()
    me = next((r for r in inv.for_ai(a.ai) if r["year"] == year), None)
    if a.pollutants:
        targets = [resolve_one(p, xw) for p in a.pollutants.split(";")]
    else:
        if not me:
            die("AI %d has no %s row in the statewide files; pass --pollutants" % (a.ai, year_label(year)), 3)
        by_name = {r["xlsx_name"]: r for r in xw if r["xlsx_name"]}
        rep_cols = [c for c, v in me["v"].items() if isinstance(v, (int, float)) and v > 0 and c in by_name]
        tons = [c for c in rep_cols if c.endswith(" - tons")]
        lbs = sorted((c for c in rep_cols if c.endswith(" - lb")), key=lambda c: -me["v"][c])
        chosen = tons + lbs
        targets = [by_name[c] for c in chosen[:a.max]]
        skipped = chosen[a.max:]
    notes = []
    if not a.pollutants and skipped:
        notes.append("Queried the first %d of %d pollutants this AI reported (criteria, then TAPs by lb). Not "
                     "queried: %s. Pass --pollutants or --max." % (a.max, len(chosen), "; ".join(skipped)))
    if year == BASELINE:
        notes.append(TSP_NOTE)
    if a.permitted:
        notes.append(PERMIT_NOTE)
    if year != BASELINE and year > inv.complete:
        notes.append("%d is provisional; revisions arrive all year." % year)
    results = []
    start = a.radius_m
    for t in targets:
        code = code_for(t, year)
        label = t["xlsx_name"] or t["eric_text"]
        if not code:
            results.append({"pollutant": label, "skipped": "no ERIC radius-report code for %s" % year_label(year)})
            continue
        expected = me["v"].get(t["xlsx_name"]) if (me and year != BASELINE and t["xlsx_name"]) else None
        # A pollutant the xlsx shows as not reported that year has nothing to find farther out.
        widen = not (me and year != BASELINE and t["xlsx_name"] and expected is None)
        rep, rows, total, tried = fetch_for_ai(a.ai, year, code, center, expected, start, a.permitted, a.refresh,
                                               widen)
        # Release points for one AI sit together, so the radius that found them for one pollutant is the
        # starting point for the rest.
        if rows:
            start = max(start, tried[-1])
        vc = rep["actual"]["value_col"] if rep["actual"] else None
        r = {"pollutant": label, "eric_code": code, "eric_text": t["eric_text"], "cas": t["cas"],
             "unit": rep["actual"]["unit"] if rep["actual"] else None, "radius_m": tried[-1],
             "radius_tried_m": tried, "release_points": actual_view(rows, vc) if vc else [],
             "radius_sum": total if rows else None, "xlsx_value": expected, "retrieved": rep["retrieved"]}
        if rows and expected is not None:
            r["match"] = abs(total - expected) <= max(1e-6, 1e-9 * abs(expected))
        if not rows and year == BASELINE:
            n_all = len(rep["actual"]["rows"]) if rep["actual"] else 0
            r["missing"] = ("no Baseline rows for AI %d within %d m (the report has %d rows from other AIs). "
                            "Baseline is legacy EIS data and covers far fewer TAPs and facilities than 2021 on."
                            % (a.ai, tried[-1], n_all))
        elif not rows and not widen:
            r["missing"] = ("not reported by AI %d in %d (blank in the xlsx), and no release points within %d m"
                            % (a.ai, year, tried[-1]))
        elif not rows:
            r["missing"] = ("no release points for AI %d within %d m of its xlsx coordinate. About 19%% of "
                            "facilities have no coordinates in ERIC; others have wrong ones." % (a.ai, tried[-1]))
        if a.permitted:
            r["permitted"] = permitted_view(rep, a.ai)
        results.append(r)
    return {"ai": a.ai, "name": pick["name"], "year": year_label(year), "center": center,
            "center_source": "xlsx %d coordinates (NAD83)" % pick["year"], "pollutants": results, "notes": notes,
            "source": ERIC + "RadiusReport", "retrieved": today()}


def cmd_radius(a):
    year = parse_year(a.year) if a.year else max(int(c) for c in available_years() if c != str(BASELINE))
    t = resolve_one(a.pollutant)
    code = code_for(t, year) or (a.pollutant if re.fullmatch(r"[0-9A-Za-z]{6}", a.pollutant) else "")
    if not code:
        die("%s has no ERIC radius-report code for %s" % (t["xlsx_name"] or t["eric_text"], year_label(year)))
    rep = radius_report(year, code, a.lat, a.lon, a.radius_m, a.permitted, a.refresh)
    by = collections.OrderedDict()
    if rep["actual"]:
        vc = rep["actual"]["value_col"]
        for r in rep["actual"]["rows"]:
            d = by.setdefault(r["AI Number"], {"ai": r["AI Number"], "name": r.get("AI Name"), "points": 0,
                                               "total": 0.0, "nearest_m": None})
            d["points"] += 1
            d["total"] += r[vc] if isinstance(r[vc], (int, float)) else 0
            dist = r.get("Distance from Center Point (m)")
            if isinstance(dist, (int, float)):
                d["nearest_m"] = dist if d["nearest_m"] is None else min(d["nearest_m"], dist)
    perm = collections.OrderedDict()
    if rep["permitted"]:
        for r in rep["permitted"]["rows"]:
            k = (r["AI Number"], str(r.get("Statistical Basis", "")).strip())
            p = perm.setdefault(k, {"ai": r["AI Number"], "name": r.get("AI Name"), "basis": k[1], "rows": 0,
                                    "grouped_rows": 0})
            p["rows"] += 1
            p["grouped_rows"] += 1 if str(r.get("Group memberships", "")).strip() else 0
    notes = [PERMIT_NOTE] if a.permitted else []
    if year == BASELINE:
        notes.append(TSP_NOTE)
    return {"center": [a.lat, a.lon], "radius_m": a.radius_m, "year": year_label(year),
            "pollutant": t["xlsx_name"] or t["eric_text"], "eric_code": code,
            "unit": rep["actual"]["unit"] if rep["actual"] else None,
            "facilities": sorted(by.values(), key=lambda d: -d["total"]),
            "permitted": sorted(perm.values(), key=lambda x: (x["ai"], x["basis"])), "notes": notes, "params": rep["params"], "retrieved": rep["retrieved"]}


# Low-frequency noise candidates. Exact Source Type values are as ERIC reports them (2024 rows); the
# description keywords catch compressors, turbines and vents, which ERIC files under "Other",
# "Insignificant Activities" or an engine type rather than a type of their own.
LF_TYPES = {"Flare": "flare", "Internal combustion engine": "engine", "Cooling tower": "cooling tower",
            "Furnace": "heater/boiler", "Boiler": "heater/boiler", "Incinerator": "incinerator"}
LF_WORDS = [("COMPRESS", "compressor"), ("TURBINE", "turbine"), ("BLOWDOWN", "vent/blowdown"),
            ("FLARE", "flare"), ("COOLING TOWER", "cooling tower"), ("COOLING WATER TOWER", "cooling tower"),
            ("ENGINE", "engine"), ("GENERATOR", "engine"), ("BLOWER", "fan/blower"), (" FAN", "fan/blower"),
            ("VENT", "vent/blowdown")]
LF_POLLUTANTS = ["Nitrogen Oxides - tons", "Particulate matter (10 microns or less) - tons", "VOC, Total - tons"]
COORD_NOTE = ("Release-point coordinates are self-reported in ERIC and often wrong or copied from the facility "
              "centroid; verify against a plot plan, satellite-imagery or parish-assessor-gis before using a "
              "distance.")
STROUHAL_NOTE = ("strouhal_hz is judgment, not retrieval: the jet-mixing-noise peak estimate f = 0.2 * V_exit / D "
                 "from the reported exit velocity and diameter. Order of magnitude only; flare and engine noise "
                 "are dominated by combustion and exhaust pulsation, not jet mixing.")


# Tank breathing vents, separators and fugitive components carry "Vent" release points but make no
# low-frequency noise worth listing.
LF_SKIP_TYPES = {"Above ground storage vessel", "Underground storage tank", "Oil/water separator",
                 "Fugitive Emissions", "Loading apparatus"}


def lf_category(r):
    t = str(r.get("Source Type") or "").strip()
    if t in LF_TYPES:
        return LF_TYPES[t]
    d = " " + " ".join(str(r.get(k) or "") for k in ("Source Description", "Release Point Description")).upper()
    for word, cat in LF_WORDS:
        if word in d and (t not in LF_SKIP_TYPES or cat in ("compressor", "turbine", "flare", "engine")):
            return cat
    return None


def cmd_sources(a):
    import math
    inv = None
    year = parse_year(a.year) if a.year else None
    if len(a.target) == 1:
        ai = int(a.target[0])
        inv = Inventory(a.refresh)
        year = year or min(max(r["year"] for r in inv.for_ai(ai) or [{"year": 0}]), inv.complete)
        pick, center = center_for(inv, ai, year)
        if not center:
            die("AI %d has no coordinates in the statewide files; pass lat lon --radius-m instead." % ai, 3)
        me = next((r for r in inv.for_ai(ai) if r["year"] == year), None)
    elif len(a.target) == 2:
        if not a.radius_m:
            die("lat lon needs --radius-m")
        ai, center, me, pick = None, (float(a.target[0]), float(a.target[1])), None, None
        year = year or max(int(c) for c in available_years() if c != str(BASELINE))
    else:
        die("expected <AI> or <lat> <lon> --radius-m N")
    by, queried, retrieved, radius_used = collections.OrderedDict(), [], None, None
    for name in LF_POLLUTANTS:
        t = resolve_one(name)
        code = code_for(t, year)
        if not code:
            continue
        if ai is not None:
            expected = me["v"].get(name) if me else None
            rep, rows, _, tried = fetch_for_ai(ai, year, code, center, expected, a.radius_m or WIDEN_M[0], False,
                                               a.refresh, widen=expected is not None)
            radius_used = max(radius_used or 0, tried[-1])
        else:
            rep = radius_report(year, code, center[0], center[1], a.radius_m, False, a.refresh)
            rows = rep["actual"]["rows"] if rep["actual"] else []
            radius_used = a.radius_m
        retrieved = rep["retrieved"]
        queried.append("%s [%s]" % (name, code))
        for r in rows:
            cat = lf_category(r)
            if not cat or (a.category and cat not in a.category):
                continue
            # One row per stack: loading operations routed to a vapor-recovery flare, or two heaters on a
            # shared stack, are one physical emission (and noise) point with several ERIC sources.
            k = (r["AI Number"], r.get("Release Point ID") or r.get("Source ID"))
            d = by.get(k)
            if d is not None and r.get("Source Description") not in d["sources"]:
                d["sources"].append(r.get("Source Description"))
            if d is None:
                d = by[k] = {"ai": r["AI Number"], "ai_name": r.get("AI Name"), "category": cat,
                             "source_type": r.get("Source Type"), "source_status": r.get("Source Status"),
                             "source": r.get("Source Description"), "sources": [r.get("Source Description")],
                             "release_point_id": r.get("Release Point ID"),
                             "eiq": r.get("EIQ Point ID No."), "rp_type": r.get("Release Point Type"),
                             "lat": r.get("Release Point Latitude (dec. deg)"),
                             "lon": r.get("Release Point Longitude (dec. deg)"),
                             "height_ft": r.get("Height (ft)"), "diameter_ft": r.get("Diameter (ft)"),
                             "exit_velocity_fps": r.get("Exit Gas Velocity (ft/sec)"),
                             "exit_temp_f": r.get("Exit Gas Temperature (deg F)"), "pollutants": []}
            if name.split(" - ")[0] not in d["pollutants"]:
                d["pollutants"].append(name.split(" - ")[0])
    out = list(by.values())
    for d in out:
        num = lambda v: v if isinstance(v, (int, float)) and v > 0 else None
        if a.receptor and isinstance(d["lat"], (int, float)) and isinstance(d["lon"], (int, float)):
            rl, rn = a.receptor
            p1, p2, dl = math.radians(d["lat"]), math.radians(rl), math.radians(rn - d["lon"])
            h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            d["to_receptor_m"] = round(6371000 * 2 * math.asin(math.sqrt(h)))
            d["bearing_to_receptor"] = round(math.degrees(math.atan2(
                math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
                % 360)
        if a.strouhal and num(d["exit_velocity_fps"]) and num(d["diameter_ft"]) and d["rp_type"] == "Stack" \
                and d["category"] != "flare":
            d["strouhal_hz"] = round(0.2 * d["exit_velocity_fps"] / d["diameter_ft"], 3)
    order = ["flare", "engine", "turbine", "compressor", "cooling tower", "fan/blower", "vent/blowdown",
             "heater/boiler", "incinerator"]
    out.sort(key=lambda d: (d.get("to_receptor_m", 0), order.index(d["category"]), str(d["source"])))
    notes = [COORD_NOTE, "One row per release point (stack); sources sharing it are listed under it.",
             "Only release points that report NOx, PM10 or VOC appear; a source with none of these "
             "(an electric-drive compressor, a fan) is not in ERIC."]
    if any(d["category"] == "flare" and d["exit_velocity_fps"] == 65.6 for d in out):
        notes.append("Flares showing 65.6 ft/s and 1,832 F carry the standard flare modeling defaults (20 m/s, "
                     "1273 K), not measured exit conditions; no Strouhal estimate is given for flares.")
    if a.strouhal:
        notes.append(STROUHAL_NOTE)
    return {"ai": ai, "name": pick["name"] if pick else None, "year": year_label(year), "center": center,
            "radius_m": radius_used, "receptor": a.receptor, "queried": queried,
            "counts": dict(collections.Counter(d["category"] for d in out)), "sources": out, "notes": notes,
            "source_url": ERIC + "RadiusReport", "retrieved": retrieved or today()}


def year_options(body):
    m = re.search(r'<select[^>]*name="ReportingYear".*?</select>', body.decode("utf-8", "replace"), re.S)
    return [(v, t.strip()) for v, t in re.findall(r'<option value="(\d{4})"[^>]*>\s*([^<]*)', m.group(0) if m else "")]


def available_years():
    body, _ = cached_get("RadiusReportSelector")
    return [v for v, _ in year_options(body)]


def cached_get(page, refresh=False):
    path = cache_path("%s.html" % page)
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL:
        with open(path, "rb") as fh:
            return fh.read(), os.path.getmtime(path)
    body = _req(ERIC + page).read()
    with open(path, "wb") as fh:
        fh.write(body)
    return body, time.time()


def cmd_parish(a):
    year = parse_year(a.year)
    if year == BASELINE:
        die("The parish report offers 2021 onward only; ERIC has no Baseline parish totals.")
    t = resolve_one(a.pollutant)
    code = code_for(t, year)
    if not code:
        die("%s has no ERIC code for %s" % (t["xlsx_name"] or t["eric_text"], year))
    body, fetched = cached_post("ParishReport", {"ReportingYear": str(year), "PollutantCode": code}, "html", a.refresh)
    txt = body.decode("utf-8", "replace")
    m = re.search(r"<th[^>]*>\s*Parish\s*</th>\s*<th[^>]*>(.*?)</th>", txt, re.S | re.I)
    col = re.sub(r"<[^>]+>|\s+", " ", html.unescape(m.group(1))).strip() if m else None
    pairs = re.findall(r"<tr[^>]*>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>\s*([-0-9.,]+)\s*</td>\s*</tr>", txt)
    if not pairs:
        raise SourceDown("ParishReport: %s" % html_error(body))
    rows = [{"parish": re.sub(r"<[^>]+>|\s+", " ", html.unescape(p)).strip(), "value": float(v.replace(",", ""))}
            for p, v in pairs]
    if a.name.lower() != "all":
        k = a.name.lower().replace("parish", "").replace("saint ", "st. ").strip()
        rows = [r for r in rows if r["parish"].lower() == k] or die("parish %r not in the %d report for %s; "
                                                                   "parishes with no reporting facility are omitted"
                                                                   % (a.name, year, col or code), 3)
    return {"year": year, "pollutant": t["xlsx_name"] or t["eric_text"], "eric_code": code, "column": col,
            "rows": rows, "source": ERIC + "ParishReport",
            "retrieved": datetime.date.fromtimestamp(fetched).isoformat()}


def cmd_reconcile(a):
    inv = Inventory(a.refresh)
    year = parse_year(a.year)
    if year == BASELINE:
        die("Baseline has no annual xlsx counterpart to reconcile against.")
    t = resolve_one(a.pollutant)
    if not t["xlsx_name"]:
        die("%s is in the radius report only; there is no xlsx column to reconcile against." % t["eric_text"])
    me = next((r for r in inv.for_ai(a.ai) if r["year"] == year), None)
    if not me:
        die("AI %d has no %d row in %s" % (a.ai, year, inv.source(year)), 3)
    expected = me["v"].get(t["xlsx_name"])
    pick, center = center_for(inv, a.ai, year)
    if not center:
        die("AI %d has no coordinates in any year of the statewide files, so the radius report cannot be "
            "centered on it (LDEQ: about 19%% of facilities lack coordinates)." % a.ai, 3)
    code = code_for(t, year)
    if not code:
        die("%s has no radius-report code for %d" % (t["xlsx_name"], year))
    rep, rows, total, tried = fetch_for_ai(a.ai, year, code, center, expected, a.radius_m, False, a.refresh,
                                           widen=expected is not None)
    res = {"ai": a.ai, "name": me["name"], "year": year, "pollutant": t["xlsx_name"], "eric_code": code,
           "xlsx_value": expected, "xlsx_source": inv.source(year), "radius_sum": total if rows else None,
           "release_points": len(rows), "radius_m": tried[-1], "radius_tried_m": tried,
           "radius_name": rows[0].get("AI Name") if rows else None, "retrieved": rep["retrieved"]}
    if expected is None:
        res["verdict"] = "not reported in the xlsx" + (" but the radius report has %s" % fmt(total) if rows else "")
    elif not rows:
        res["verdict"] = ("no release points within %d m of the xlsx coordinate: missing or wrong coordinates in "
                          "ERIC (LDEQ: about 19%% of facilities have none)" % tried[-1])
    elif abs(total - expected) <= max(1e-6, 1e-9 * abs(expected)):
        res["verdict"] = "exact match"
    elif total < expected:
        res["verdict"] = ("radius sum short by %s even at %d m: release points outside the radius (wrong "
                          "coordinates), or the xlsx and live database differ by a revision"
                          % (fmt(expected - total), tried[-1]))
    else:
        res["verdict"] = ("radius sum exceeds the xlsx by %s: the live database has a revision newer than the "
                          "xlsx (%s), or the AI's rows include another inventory" % (fmt(total - expected),
                                                                                   inv.source(year)))
    if rows and res["radius_name"] and res["radius_name"] not in me["name"].split(" + "):
        res["name_note"] = "ERIC's current name differs from the xlsx row's name (name drift, same AI)."
    return res


def cmd_pollutants(a):
    rows = crosswalk()
    if a.query:
        rows = resolve(a.query, rows) or [r for r in rows if a.query.lower() in
                                          (r["xlsx_name"] + " " + r["eric_text"] + " " + r["cas"]).lower()]
    return {"rows": rows}


def cmd_health(a):
    out = {"files": [], "eric": None, "drift": {}}
    for w, url in XLSX.items():
        try:
            lm, size = head(url)
            out["files"].append({"file": url, "up": True, "last_modified": lm, "bytes": size})
        except SourceDown as e:
            out["files"].append({"file": url, "up": False, "error": str(e)})
    try:
        body, _ = cached_get("RadiusReportSelector", refresh=True)
        years = year_options(body)
        out["eric"] = {"up": True, "years": [t for _, t in years]}
    except SourceDown as e:
        out["eric"] = {"up": False, "error": str(e)}
        return out
    xw = crosswalk()
    known = {r["eric_code"] for r in xw} | {r["eric_code_baseline"] for r in xw}
    new_codes, offered = [], set()
    for v, label in years:
        for code, text, grp in pollutant_list(v, refresh=True):
            offered.add(code)
            if code not in known:
                new_codes.append("%s %s (%s)" % (code, text, label.strip()))
    out["drift"]["eric_codes_not_in_crosswalk"] = sorted(set(new_codes))
    out["drift"]["crosswalk_codes_no_longer_offered"] = sorted(
        "%s %s" % (r["eric_code"], r["eric_text"]) for r in xw if r["eric_code"] and r["eric_code"] not in offered)
    try:
        inv = Inventory(refresh=True)
        cols = set(inv.all_columns())
        names = {r["xlsx_name"] for r in xw if r["xlsx_name"]}
        out["drift"]["xlsx_columns_not_in_crosswalk"] = sorted(cols - names)
        out["drift"]["crosswalk_columns_missing_from_xlsx"] = sorted(names - cols)
        out["years"] = {"ai_count_by_year": inv.ai_count, "complete_through": inv.complete}
    except SourceDown as e:
        out["drift"]["xlsx"] = "not checked: %s" % e
    return out


# ---------------------------------------------------------------- text output

def show(cmd, res):
    p = print
    if cmd == "facility":
        p("AI %d — ERIC annual certified emissions" % res["ai"])
        for k in ("names", "parishes", "naics", "sic", "coords"):
            d = res[k]
            flag = "  ** changes across years **" if len(d) > 1 else ""
            p("  %-8s %s%s" % ({"names": "name", "parishes": "parish", "coords": "coords"}.get(k, k),
                               "; ".join("%s [%s]" % (x["value"] if x["value"] not in ("", None, [None, None]) else "(blank)",
                                                        x["years"]) for x in d), flag))
        if res["provisional_years"]:
            p("  provisional (still filling in, revisions arrive all year): %s"
              % ", ".join(map(str, res["provisional_years"])))
        mc = res["multiple_certifications"]
        for y, names in mc.items():
            p("  %s*: %d certifications summed (ownership change mid-year): %s" % (y, len(names), " | ".join(names)))
        for y, names in res["duplicate_rows"].items():
            p("  %s: the file lists the same certification twice (identical values); counted once: %s"
              % (y, " | ".join(names)))
        years = res["years"]
        w = max([len(t["pollutant"]) for t in res["table"]] + [20])
        p()
        p("%-*s  %s" % (w, "pollutant", "  ".join("%12s" % ("%s%s" % (y, "*" if y in mc else "")) for y in years)))
        for t in res["table"]:
            p("%-*s  %s" % (w, t["pollutant"], "  ".join("%12s" % fmt(t["values"][y]) for y in years)))
        p()
        p("— = blank cell, not reported (never zero).  n/c = not collected: outside the years any Louisiana "
          "facility reported this column.  "
          "Criteria and ethylene/propylene/butene in tons, TAPs in lb.")
        p("Source: %s; retrieved %s" % ("; ".join(res["sources"]), res["retrieved"]))
        if res.get("csv"):
            p("Wrote %s" % res["csv"])
    elif cmd == "search":
        for m in res["matches"]:
            p("AI %-7d %-14s NAICS %-7s years %s" % (m["ai"], m["parish"], m["naics"], m["years"]))
            for n in m["names"]:
                p("           %s [%s]" % (n["value"], n["years"]))
        if not res["matches"]:
            p("No ERIC names match %r. ERIC lists only facilities that report under LAC 33:III.919 or 5107; "
              "use ldeq-ai-lookup for the AI number." % res["query"])
    elif cmd == "peers":
        p("AI %d %s — %d peers by primary %s %s in %d" % (res["ai"], res["name"], res["cohort_size"],
                                                         res["by"].upper(), res["code"], res["year"]))
        if res["note"]:
            p("  note: " + res["note"])
        for t in res["pollutants"]:
            p()
            p("%s: target %s, rank %s of %s reporting (%d in cohort did not report), median %s" % (
                t["pollutant"], fmt(t["target"]), t["rank"] or "—", t["of"], t["not_reporting"], fmt(t["median"])))
            for i, x in enumerate(t["top"], 1):
                mark = " <" if x["ai"] == res["ai"] else ""
                p("  %2d. %-14s AI %-7d %-55.55s %s%s" % (i, fmt(x["value"]), x["ai"], x["name"], x["parish"], mark))
        p()
        p("Source: %s; retrieved %s" % (res["source"], res["retrieved"]))
    elif cmd == "points":
        p("AI %d %s — release points, %s; center %.5f, %.5f (%s)" % (
            res["ai"], res["name"], res["year"], res["center"][0], res["center"][1], res["center_source"]))
        for n in res["notes"]:
            p("  note: " + n)
        for r in res["pollutants"]:
            p()
            if r.get("skipped"):
                p("%s: skipped — %s" % (r["pollutant"], r["skipped"]))
                continue
            p("%s [%s] (%s), radius %d m%s" % (r["pollutant"], r["eric_code"], r["unit"], r["radius_m"],
                                                " (widened from %d)" % r["radius_tried_m"][0]
                                                if len(r["radius_tried_m"]) > 1 else ""))
            if r.get("missing"):
                p("  " + r["missing"])
            else:
                p("  actual: %d release points, sum %s; xlsx %s%s" % (
                    len(r["release_points"]), fmt(r["radius_sum"]), fmt(r["xlsx_value"]),
                    "" if "match" not in r else ("  [match]" if r["match"] else "  [MISMATCH — run reconcile]")))
                for x in r["release_points"][:40]:
                    p("   %-14s RP %-10s EIQ %-12s %-10s H %-6s ft  T %-6s F  D %-5s ft  V %-6s ft/s  %-40.40s" % (
                        fmt(x["value"]), x.get("Release Point ID"), x.get("EIQ Point ID No."),
                        x.get("Release Point Type"), fmt(x.get("Height (ft)")),
                        fmt(x.get("Exit Gas Temperature (deg F)")), fmt(x.get("Diameter (ft)")),
                        fmt(x.get("Exit Gas Velocity (ft/sec)")), x.get("Source Description")))
                if len(r["release_points"]) > 40:
                    p("   ... %d more (use --json)" % (len(r["release_points"]) - 40))
            if "permitted" in r:
                if not r["permitted"]:
                    p("  permitted: no TEMPO rows for this AI within the radius")
                for basis, rows in r["permitted"].items():
                    p("  permitted — %s (%d rows; not summed):" % (basis, len(rows)))
                    for x in rows[:40]:
                        grp = str(x.get("Group memberships") or "").strip()
                        p("   %-12s %-10s EIQ %-12s %-38.38s %s%s" % (
                            fmt(x.get("Emission Rate")), x.get("Emission Rate Units"), x.get("EIQ Point ID No."),
                            x.get("Subject Item Description"), x.get("Permit No."),
                            ("  group: " + grp) if grp else ""))
                    if len(rows) > 40:
                        p("   ... %d more (use --json)" % (len(rows) - 40))
        p()
        p("Source: %s (%s); retrieved %s" % (res["source"], "radius parameters per pollutant above", res["retrieved"]))
    elif cmd == "radius":
        p("%s [%s] (%s) within %d m of %.5f, %.5f — %s" % (res["pollutant"], res["eric_code"], res["unit"],
                                                           res["radius_m"], res["center"][0], res["center"][1],
                                                           res["year"]))
        for n in res["notes"]:
            p("  note: " + n)
        for f in res["facilities"]:
            p("  %-14s AI %-7d %3d pts  nearest %7s m  %s" % (fmt(f["total"]), f["ai"], f["points"],
                                                             fmt(round(f["nearest_m"])) if f["nearest_m"] is not None
                                                             else "—", f["name"]))
        if res["permitted"]:
            p()
            p("Permitted rows by AI and statistical basis (counts only; rates are not additive):")
            for x in res["permitted"]:
                p("  AI %-7d %-28s %4d rows (%d in a group)  %s" % (x["ai"], x["basis"], x["rows"],
                                                                    x["grouped_rows"], x["name"]))
        p()
        p("Source: %sRadiusReport %s; retrieved %s" % (ERIC, json.dumps(res["params"]), res["retrieved"]))
    elif cmd == "sources":
        p("Low-frequency noise candidates — %s, %s; center %.5f, %.5f, radius %s m" % (
            "AI %d %s" % (res["ai"], res["name"]) if res["ai"] else "all AIs", res["year"], res["center"][0],
            res["center"][1], res["radius_m"]))
        p("  queried: %s" % "; ".join(res["queried"]))
        p("  counts: %s" % ", ".join("%s %d" % kv for kv in res["counts"].items()))
        for n in res["notes"]:
            p("  note: " + n)
        p()
        rc = res["receptor"] is not None
        p("  %-13s %-7s %-44s %-5s %9s %10s %6s %5s %6s %6s%s%s" % (
            "category", "AI", "source", "RP", "lat", "lon", "H ft", "D ft", "V fps", "T F",
            "  to rcp m  brg" if rc else "", "  f_St Hz" if any("strouhal_hz" in d for d in res["sources"]) else ""))
        for d in res["sources"]:
            p("  %-13s %-7s %-44.44s %-5.5s %9s %10s %6s %5s %6s %6s%s%s" % (
                d["category"], d["ai"], d["source"], d["rp_type"], fmt(d["lat"]), fmt(d["lon"]), fmt(d["height_ft"]),
                fmt(d["diameter_ft"]), fmt(d["exit_velocity_fps"]), fmt(d["exit_temp_f"]),
                ("  %8s %4s" % (d.get("to_receptor_m", "—"), d.get("bearing_to_receptor", "—"))) if rc else "",
                ("  %7s" % d["strouhal_hz"]) if "strouhal_hz" in d else ""))
            for extra in d["sources"][1:]:
                p("  %-13s %-7s   + %-42.42s (same release point %s)" % ("", "", extra, d["release_point_id"]))
        p()
        p("Source: %s (%s, release-point coordinates self-reported); retrieved %s" % (
            res["source_url"], res["year"], res["retrieved"]))
    elif cmd == "parish":
        p("%s — %s, %d" % (res["column"] or res["pollutant"], "ERIC parish report", res["year"]))
        for r in res["rows"]:
            p("  %-22s %s" % (r["parish"], fmt(r["value"])))
        p("Source: %s (ReportingYear=%d, PollutantCode=%s); retrieved %s" % (res["source"], res["year"],
                                                                            res["eric_code"], res["retrieved"]))
    elif cmd == "reconcile":
        p("AI %d %s — %s, %d" % (res["ai"], res["name"], res["pollutant"], res["year"]))
        p("  xlsx:   %s  (%s)" % (fmt(res["xlsx_value"]), res["xlsx_source"]))
        p("  radius: %s  (%d release points within %d m; tried %s)" % (
            fmt(res["radius_sum"]), res["release_points"], res["radius_m"],
            ", ".join(map(str, res["radius_tried_m"]))))
        p("  verdict: " + res["verdict"])
        if res.get("name_note"):
            p("  note: %s Radius report: %r" % (res["name_note"], res["radius_name"]))
        p("  retrieved %s" % res["retrieved"])
    elif cmd == "pollutants":
        for r in res["rows"]:
            p("%-48.48s %-4s eric %-6s base %-6s CAS %-11s %-24s LAC %-9s %s %s" % (
                r["xlsx_name"] or "(radius only)", r["unit"], r["eric_code"] or "—", r["eric_code_baseline"] or "—",
                r["cas"] or "—", r["cas_kind"] or "", r["lac33_table"] or "—", r["eric_text"], r["match"]))
    elif cmd == "health":
        for f in res["files"]:
            p("%-4s %s  Last-Modified %s  %s bytes" % ("up" if f["up"] else "DOWN", f["file"],
                                                       f.get("last_modified"), f.get("bytes")))
        e = res["eric"]
        p("%-4s %sRadiusReportSelector  years: %s" % ("up" if e["up"] else "DOWN", ERIC,
                                                      ", ".join(e.get("years", [])) or e.get("error")))
        if "years" in res:
            p("statewide files: complete through %d; facilities per year %s" % (
                res["years"]["complete_through"],
                ", ".join("%s:%s" % kv for kv in list(res["years"]["ai_count_by_year"].items())[-6:])))
        for k, v in res["drift"].items():
            p("%s: %s" % (k, "none" if not v else (v if isinstance(v, str) else "; ".join(v))))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--refresh", action="store_true", help="bypass the one-day cache")
    # Repeat the globals on each subcommand so they work on either side of it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    sub.add_parser("health", help="sources up, years offered, crosswalk drift")

    s = sub.add_parser("facility", help="annual emissions for one AI, all years")
    s.add_argument("ai", type=int)
    s.add_argument("--years", help="A-B or a single year")
    s.add_argument("--pollutants", help="';'-separated names, ERIC codes or CAS numbers")
    s.add_argument("--csv", help="write long-form rows here")

    s = sub.add_parser("search", help="AI numbers by ERIC facility name")
    s.add_argument("name")

    s = sub.add_parser("peers", help="same-NAICS/SIC Louisiana facilities, ranked")
    s.add_argument("ai", type=int)
    s.add_argument("--year")
    s.add_argument("--by", choices=["naics", "sic"], default="naics")
    s.add_argument("--pollutants")
    s.add_argument("--top", type=int, default=10)

    s = sub.add_parser("points", help="release-point actual (and permitted) rows for one AI")
    s.add_argument("ai", type=int)
    s.add_argument("--year", help="2021-2025 or baseline")
    s.add_argument("--pollutants")
    s.add_argument("--permitted", action="store_true", help="include the TEMPO permitted sheet")
    s.add_argument("--radius-m", type=int, default=WIDEN_M[0])
    s.add_argument("--max", type=int, default=12, help="most pollutants to query when --pollutants is not given")

    s = sub.add_parser("radius", help="all facilities' release points near a point, one pollutant")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--radius-m", type=int, required=True)
    s.add_argument("--pollutant", required=True)
    s.add_argument("--year")
    s.add_argument("--permitted", action="store_true")

    s = sub.add_parser("sources", help="flares, engines, turbines, compressors, cooling towers, vents with stack "
                                       "parameters (low-frequency noise candidates)")
    s.add_argument("target", nargs="+", help="<AI> or <lat> <lon>")
    s.add_argument("--radius-m", type=int)
    s.add_argument("--year")
    s.add_argument("--receptor", type=lambda v: tuple(float(x) for x in v.split(",")), help="lat,lon")
    s.add_argument("--category", action="append", help="repeatable: flare, engine, turbine, compressor, "
                                                        "cooling tower, fan/blower, vent/blowdown, heater/boiler, "
                                                        "incinerator")
    s.add_argument("--strouhal", action="store_true", help="add the f = 0.2 V/D estimate (judgment)")

    s = sub.add_parser("parish", help="parish totals of actual emissions")
    s.add_argument("name", help="parish name, or 'all'")
    s.add_argument("--pollutant", required=True)
    s.add_argument("--year", required=True)

    s = sub.add_parser("reconcile", help="radius-report sum vs xlsx annual value for one AI")
    s.add_argument("ai", type=int)
    s.add_argument("--year", required=True)
    s.add_argument("--pollutant", required=True)
    s.add_argument("--radius-m", type=int, default=WIDEN_M[0])

    s = sub.add_parser("pollutants", help="crosswalk of xlsx names, ERIC codes, CAS and LAC 33:III table")
    s.add_argument("query", nargs="?")

    args = ap.parse_args()
    fn = {"health": cmd_health, "facility": cmd_facility, "search": cmd_search, "peers": cmd_peers,
          "points": cmd_points, "radius": cmd_radius, "sources": cmd_sources, "parish": cmd_parish,
          "reconcile": cmd_reconcile,
          "pollutants": cmd_pollutants}[args.cmd]
    try:
        res = fn(args)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
