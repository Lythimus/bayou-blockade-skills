#!/usr/bin/env python3
"""LDEQ LELAP laboratory accreditation: current scopes, the accredited-lab directory, and the EDMS
certificate history that answers "was this lab accredited for this analysis on that date?"

Run with: uv run -q --no-project python -I lelap.py <command> ...
Scope queries and directory/EDMS pulls are cached for a day (--refresh forces a re-fetch).
Cache: ~/.cache/bayou/ldeq-lelap-labs/.

  lelap.py health                                   pages up, module config scraped, row counts agree
  lelap.py labs [text]                              accredited-lab directory (AI, name, city, state)
  lelap.py scope <lab|AI> [--matrix M] [--method X] [--analyte Y]   current scope rows
  lelap.py who --method X [--analyte Y] [--matrix M]                labs currently holding that analysis
  lelap.py check <lab|AI> --method X --analyte Y --matrix M --date YYYY-MM-DD
  lelap.py history <AI> [--fy 2019] [--all-docs]    EDMS LELAP certificates, amendments, suspensions
  lelap.py methods|analytes <text>                  exact dropdown values containing <text>
  lelap.py export <out.csv> [--yes]                 the whole statewide scope table (~14 MB)
"""
import argparse
import collections
import csv
import datetime
import hashlib
import html
import http.cookiejar
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE = os.path.expanduser("~/.cache/bayou/ldeq-lelap-labs")
TTL = 24 * 3600
UA = "Mozilla/5.0 (bayou-ldeq-lelap-labs)"
PORTAL = "https://internet.deq.louisiana.gov/portal"
SCOPE_PAGE = PORTAL + "/divisions/lelap/laboratory-scopes-of-accreditation"
DIR_PAGE = PORTAL + "/divisions/lelap/accredited-laboratories"
OWS = PORTAL + "/DesktopModules/OWS/IM.aspx"
EDMS = "https://edms.deq.louisiana.gov/edmsv2/documentSearch/filter"
EDMS_VIEW = "https://edms.deq.louisiana.gov/app/doc/view?doc="
PRR = "https://edms.deq.louisiana.gov/prr/RequestForm.aspx"
LELAP_EMAIL = "LDEQ.LabAccreditationProgram@LA.GOV"
EXPORT_SIZE = "about 72,000 rows / 14 MB"

MATRICES = {"NPW": "nonpotable water", "SCM": "solid and chemical material",
            "AE": "air emissions", "BT": "biological tissue"}
SCOPE_COLS = ["lelap_id", "ai", "lab_state", "lab_name", "matrix", "analyte", "method", "accreditation_type"]

LIMITS = [
    "The live scope table shows accreditation as of today only. It cannot confirm accreditation on a past "
    "sample date, and a lab or method missing from it today does not prove the lab lacked accreditation then.",
    "Accreditation Type is the basis of the listing (LA = LDEQ primary; FL, TX, NELAP, A2LA, ISO 17025, etc. = "
    "the accrediting body LDEQ relied on under reciprocity or interim acceptance, §4713/§4715/Ch. 59). "
    "A non-LA value is still LELAP accreditation, not its absence.",
]
SCREEN = [
    ("Commercial lab?", "Subpart 3 covers commercial labs: those testing for third parties for a fee "
     "(LAC 33:I.4501.A.1, §4503). A facility's own in-house lab analyzing its own samples is not a commercial lab, "
     "though government in-house labs must still apply (§4707.B) and a permit condition may require an "
     "accredited lab anyway; read the permit."),
    ("Field test?", "pH, temperature, flow rate, soil classification and fugitive (LDAR) monitoring done on site "
     "are field tests, and the regulations do not apply to them (§4503 'Field Test', §4719.D)."),
    ("LDH program?", "Drinking-water and other analyses under a Louisiana Department of Health accreditation "
     "program, and NRC/LAC 33:XV personnel monitoring, are excluded (§4501.E)."),
    ("WET / EPA-only toxicity?", "LELAP's interpretations say WET methods need no accreditation, and drilling-mud "
     "or sediment toxicity reported only to EPA needs none (LELAP Interpretations)."),
]
SCREEN_NOTE = ("Call a gap a procedural defect under §4501.A.2 ('shall not be accepted by the department') only "
               "after every screen question above is answered and none of the exclusions applies.")

# EDMS LELAP documents that set or change what a lab was accredited for. Everything else under the
# LELAP media (PT results, assessments, corrective-action plans) is evidence about compliance, not scope.
STATUS_RE = re.compile(r"suspen|discredit|revo[ck]|withdraw|reinstat|expir", re.I)
CERT_RE = re.compile(r"certificate|scope|approval package|renewal|annual|amend|\bFY\s?\d", re.I)
REQUEST_RE = re.compile(r"request|application", re.I)


class SourceDown(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def today():
    return datetime.date.today()


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().casefold()


# ---------------------------------------------------------------- HTTP

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _req(url, data=None, headers=None, timeout=120):
    h = {"User-Agent": UA}
    h.update(headers or {})
    try:
        with _opener.open(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceDown("%s: %s" % (url, e))


def cache_path(name):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)


def fresh(path, refresh):
    return not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL


class Module:
    """One DNN OpenWebStudio list module. The page GET sets the session cookie the AJAX endpoint needs and
    carries the module config string (module id, tab, GUID), which LDEQ can change on any site rebuild, so
    it is scraped each run rather than stored."""

    def __init__(self, page_url, list_var="lxList"):
        self.page_url = page_url
        self.page = _req(page_url).decode("utf-8", "replace")
        m = re.search(r"var\s+%s\s*=\s*'(\d+)'" % list_var, self.page)
        mid = m.group(1) if m else None
        configs = dict(re.findall(r"ows\.Create\('(\d+)',-?\d+,-?\d+,'([^']+)'", self.page))
        if not configs:
            raise SourceDown("%s: no ows.Create module config on the page (layout changed?)" % page_url)
        self.mid = mid if mid in configs else next(iter(configs))
        self.config = configs[self.mid]

    def options(self, field):
        m = re.search(r"<select[^>]*name=%s[^>]*>(.*?)</select>" % field, self.page, re.S)
        if not m:
            return []
        out = []
        for v in re.findall(r'<option value="([^"]*)"', m.group(1)):
            # Many option values carry a trailing space, and the filter matches trimmed data against the
            # untrimmed query, so "EPA 8260 " returns nothing while "EPA 8260" returns its rows.
            v = html.unescape(v).strip()
            # "[Analyte]"-style values are OWS template placeholders, not data.
            if v and not (v.startswith("[") and v.endswith("]")) and v not in out:
                out.append(v)
        return out

    def fetch(self, fields, rows=100000):
        q = "Action=Filter&_OWS_=lxC:%d,lxP:0,%s&RA=%d" % (rows, self.config, random.randint(1, 10 ** 9))
        body = _req(OWS + "?" + q, urllib.parse.urlencode(fields).encode(),
                    {"Content-Type": "application/x-www-form-urlencoded", "Referer": self.page_url})
        t = body.decode("utf-8", "replace")
        m = re.search(r"Total Records:\s*(\d+)", t)
        total = int(m.group(1)) if m else None
        # An empty filter result is just the count followed by "Standard No Results", with no table.
        if total is None and re.match(r"\s*0\s*Standard No Results", t):
            return 0, []
        out = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if tds:
                out.append([html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in tds])
        if total is None and not out:
            raise SourceDown("%s: the filter endpoint returned no table (%d bytes)" % (OWS, len(body)))
        return total, out


_scope_mod = None


def scope_module():
    global _scope_mod
    if _scope_mod is None:
        _scope_mod = Module(SCOPE_PAGE)
    return _scope_mod


def dropdowns(refresh=False):
    path = cache_path("dropdowns.json")
    if fresh(path, refresh):
        with open(path) as fh:
            return json.load(fh)
    m = scope_module()
    d = {"labs": m.options("txtFlt_LabName"), "analytes": m.options("txtFlt_Analyte"),
         "methods": m.options("txtFlt_MethodRef"), "config": m.config}
    with open(path, "w") as fh:
        json.dump(d, fh)
    return d


def scope_rows(lab="", analyte="", method="", refresh=False):
    """Server-filtered scope rows. Filter values must be exact (trimmed) dropdown values."""
    fields = {"txtFlt_LabName": lab.strip(), "txtFlt_Analyte": analyte.strip(), "txtFlt_MethodRef": method.strip()}
    key = hashlib.sha1(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:20]
    path = cache_path("scope_%s.json" % key)
    if fresh(path, refresh):
        with open(path) as fh:
            d = json.load(fh)
        return d["total"], d["rows"]
    total, raw = scope_module().fetch(fields)
    rows = []
    for r in raw:
        if len(r) < 8:
            continue
        rec = dict(zip(SCOPE_COLS, r[:8]))
        # A handful of rows carry the OWS template token instead of a matrix code.
        if rec["matrix"].startswith("["):
            continue
        rows.append(rec)
    with open(path, "w") as fh:
        json.dump({"total": total, "parsed": len(raw), "rows": rows, "fields": fields}, fh)
    remember_ids(rows)
    return total, rows


def remember_ids(rows):
    """AI -> LELAP lab ID, learned from every scope pull, so the directory listing can show IDs it lacks."""
    path = cache_path("lelap_ids.json")
    known = {}
    if os.path.exists(path):
        with open(path) as fh:
            known = json.load(fh)
    for r in rows:
        if r["ai"] and r["lelap_id"]:
            known[r["ai"]] = r["lelap_id"]
    with open(path, "w") as fh:
        json.dump(known, fh)


def known_ids():
    path = cache_path("lelap_ids.json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


def directory(refresh=False):
    path = cache_path("directory.json")
    if fresh(path, refresh):
        with open(path) as fh:
            return json.load(fh)
    total, raw = Module(DIR_PAGE).fetch({}, rows=5000)
    # Contact person, street address, phone and email are on the page; keep only what identifies the site.
    # The city/ST columns are the mailing address (often a corporate office), so the physical-location
    # state is kept separately and is the one that distinguishes same-name sites.
    out = [{"ai": r[0], "name": r[1], "state": r[2], "city": r[5], "mail_state": r[6]} for r in raw if len(r) >= 7]
    if total is not None and total != len(out):
        raise SourceDown("directory: Total Records %d but parsed %d rows" % (total, len(out)))
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


# ---------------------------------------------------------------- resolution

def resolve_value(query, values, kind):
    """Exact match after whitespace/case folding only. Method revisions (8260B vs 8260D, 624 vs 624.1) and
    analyte synonyms are distinct accreditations, so nothing fuzzier may pick a value silently."""
    q = norm(query)
    hits = [v for v in values if norm(v) == q]
    if hits:
        return hits
    toks = [t for t in re.split(r"[\s,/()-]+", q) if t]
    cands = [v for v in values if all(t in norm(v) for t in toks)]
    if not cands:
        core = max(toks, key=len) if toks else q
        cands = [v for v in values if core in norm(v)]
    msg = ["no %s exactly matches %r on the LELAP scope page." % (kind, query)]
    if cands:
        msg.append("Values containing those terms (exact strings; a different revision is a different method):")
        msg += ["  %r" % c for c in cands[:40]]
        if len(cands) > 40:
            msg.append("  ... %d more; narrow the text" % (len(cands) - 40))
    else:
        msg.append("Nothing similar. If the report names this method exactly, no lab currently holds it.")
    die("\n".join(msg), 3)


def resolve_lab(query, refresh=False):
    """-> (directory sites, dropdown lab-name values). A name can cover several sites with separate AIs."""
    d = directory(refresh)
    labs = dropdowns(refresh)["labs"]
    q = query.strip()
    if q.isdigit():
        sites = [s for s in d if s["ai"] == q]
        if not sites:
            # LELAP lab IDs are zero-padded five digits ("05126"); map back to the AI once a scope pull has seen it.
            ais = [ai for ai, lid in known_ids().items() if lid == q.zfill(5)]
            sites = [s for s in d if s["ai"] in ais]
        if not sites:
            die("AI %s is not in the LELAP accredited-laboratories directory. Use `labs <name>` to search; "
                "a lab missing today may still have held accreditation earlier (`history %s`)." % (q, q), 3)
    else:
        sites = [s for s in d if norm(s["name"]) == norm(q)]
        if not sites:
            sites = [s for s in d if norm(q) in norm(s["name"])]
        names = sorted({s["name"] for s in sites})
        if len(names) > 1:
            die("%r matches several directory names; give the full name or the AI:\n%s"
                % (query, "\n".join("  %s  %s (located %s; mail %s)" % (s["ai"], s["name"], s["state"], s["city"])
                                    for s in sorted(sites, key=lambda s: s["name"]))), 3)
        if not sites:
            vals = [v for v in labs if norm(q) in norm(v)]
            if not vals:
                die("no accredited lab name contains %r. Use `labs` to list them." % query, 3)
            return [], sorted(set(vals))
    names = {norm(s["name"]) for s in sites}
    vals = [v for v in labs if norm(v) in names]
    return sites, vals


def rows_for_sites(sites, vals, refresh=False):
    rows, totals = [], []
    for v in vals:
        total, rs = scope_rows(lab=v, refresh=refresh)
        totals.append(total)
        rows += rs
    if sites:
        ais = {s["ai"] for s in sites}
        rows = [r for r in rows if r["ai"] in ais]
    return rows, totals


def filt(rows, matrix=None, method=None, analyte=None):
    out = rows
    if matrix:
        out = [r for r in out if r["matrix"] == matrix]
    if method is not None:
        out = [r for r in out if norm(r["method"]) in {norm(m) for m in method}]
    if analyte is not None:
        out = [r for r in out if norm(r["analyte"]) in {norm(a) for a in analyte}]
    return out


def fiscal_year(d):
    """LDEQ fiscal years run Jul 1 - Jun 30 and are labeled by the ending year (FY16 = 2015-07-01..2016-06-30)."""
    fy = d.year + 1 if d.month >= 7 else d.year
    return fy, datetime.date(fy - 1, 7, 1), datetime.date(fy, 6, 30)


# ---------------------------------------------------------------- EDMS

def edms_docs(ai, refresh=False):
    path = cache_path("edms_%s.json" % ai)
    if fresh(path, refresh):
        with open(path) as fh:
            return json.load(fh)
    docs, start = [], 0
    while True:
        body = {"filter": {"numberOfRecordsPerPage": 25, "skip": 0, "totalCount": 0, "filters": [],
                           "keywords": [], "keywordValues": [], "descriptionMode": "Exact",
                           "contentSearchMode": "Exact", "descriptionFuzzy": False,
                           "documentDateRange": {"start": None, "end": None},
                           "entryDateRange": {"start": None, "end": None}, "aiInformation": str(ai)},
                "refinerFilter": {"documentDates": [], "functions": [], "medias": ["LELAP"], "documentTypes": [],
                                  "documentSubtypes": [], "ais": [], "activities": [], "classifications": [],
                                  "pwsids": []},
                "start": start, "rows": 200, "sort": "documentDate", "asc": False, "highlight": False}
        raw = _req(EDMS, json.dumps(body).encode(), {"Accept": "application/json", "Content-Type": "application/json"})
        try:
            d = json.loads(raw)
        except ValueError:
            raise SourceDown("EDMS returned non-JSON (%d bytes)" % len(raw))
        page = d.get("data") or []
        for x in page:
            docs.append({"id": x.get("id"), "date": (x.get("documentDate") or "")[:10],
                         "type": x.get("documentType") or "", "subtype": x.get("documentSubtype") or "",
                         "description": re.sub(r"\s+", " ", x.get("description") or "").strip(),
                         "pages": x.get("pages")})
        start += len(page)
        if not page or start >= (d.get("total") or 0):
            break
    for x in docs:
        x["class"] = classify(x)
    with open(path, "w") as fh:
        json.dump(docs, fh)
    return docs


def classify(x):
    desc = x["description"]
    if STATUS_RE.search(desc) and not re.search(r"PT |proficiency", desc, re.I):
        return "status" if x["type"] == "Permits" else "related"
    if x["type"] == "Permits":
        if x["subtype"] == "Application" or REQUEST_RE.search(desc):
            return "related"
        return "certificate"
    # Some years' scopes were filed as outgoing letters ("Scope of Accreditation FY 2015") rather than permits.
    if x["type"] == "Correspondence-Sent" and re.search(r"scope of accreditation|certificate", desc, re.I) \
            and not re.search(r"schedul|incomplet", desc, re.I):
        return "certificate"
    if x["type"] in ("Correspondence-Sent", "Legal"):
        return "related"
    if x["type"] == "Correspondence-Received" and CERT_RE.search(desc) and not re.search(r"proficiency", desc, re.I):
        return "related"
    return "other"


def fy_label(desc):
    m = re.search(r"\bFY\s?(20)?(\d\d)\b", desc, re.I)
    return 2000 + int(m.group(2)) if m else None


def certificate_for(docs, fy, fy_start):
    """The annual certificate/scope for a fiscal year: labeled with that FY, or a certificate-class document
    issued in the renewal window around July 1 (LDEQ dates them anywhere from late June to early July).
    An unamended annual issue is preferred, but some years exist only as an "Annual Amend" reissue."""
    certs = [x for x in docs if x["class"] == "certificate"]
    lo, hi = (fy_start - datetime.timedelta(days=60)).isoformat(), (fy_start + datetime.timedelta(days=45)).isoformat()
    labeled = [x for x in certs if fy_label(x["description"]) == fy]
    window = [x for x in certs if lo <= x["date"] <= hi and fy_label(x["description"]) in (None, fy)]
    # A same-day cover letter and the certificate itself are both filed some years; prefer the Permits record.
    for pool, latest in ((labeled, False), (window, True)):
        plain = [x for x in pool if "amend" not in x["description"].lower()] or pool
        if plain:
            return min(plain, key=lambda x: (x["type"] != "Permits", x["date"] if not latest else -int(x["date"].replace("-", ""))))
    return None


# ---------------------------------------------------------------- commands

def cmd_health(a):
    m = scope_module()
    dd = dropdowns(True)
    lab = next((v for v in dd["labs"] if v.startswith("A&B Labs Louisiana")), dd["labs"][0] if dd["labs"] else "")
    total, rows = scope_rows(lab=lab, refresh=True)
    dirs = directory(True)
    ok = bool(dd["labs"] and dd["methods"] and dd["analytes"]) and total is not None
    with open(cache_path("scope_%s.json" % hashlib.sha1(json.dumps(
            {"txtFlt_LabName": lab, "txtFlt_Analyte": "", "txtFlt_MethodRef": ""}, sort_keys=True).encode()
            ).hexdigest()[:20])) as fh:
        parsed = json.load(fh)["parsed"]
    return {"scope_page": SCOPE_PAGE, "module": m.mid, "config": m.config,
            "dropdown_counts": {"labs": len(dd["labs"]), "analytes": len(dd["analytes"]), "methods": len(dd["methods"])},
            "probe_lab": lab, "probe_total_records": total, "probe_parsed_rows": parsed,
            "probe_rows_after_placeholder_drop": len(rows), "directory_labs": len(dirs),
            "ok": ok and total == parsed, "retrieved": today().isoformat()}


def cmd_labs(a):
    d = directory(a.refresh)
    ids = known_ids()
    q = norm(a.text) if a.text else ""
    out = [dict(s, lelap_id=ids.get(s["ai"], "")) for s in d if q in norm(s["name"]) or q == s["ai"]]
    counts = collections.Counter(norm(s["name"]) for s in d)
    for s in out:
        s["sites_with_this_name"] = counts[norm(s["name"])]
    return {"query": a.text, "labs": sorted(out, key=lambda s: (s["name"], s["ai"])),
            "retrieved": today().isoformat(), "source": DIR_PAGE}


def resolve_filters(a, dd):
    method = resolve_value(a.method, dd["methods"], "method") if getattr(a, "method", None) else None
    analyte = resolve_value(a.analyte, dd["analytes"], "analyte") if getattr(a, "analyte", None) else None
    return method, analyte


def cmd_scope(a):
    dd = dropdowns(a.refresh)
    method, analyte = resolve_filters(a, dd)
    sites, vals = resolve_lab(a.lab, a.refresh)
    if not vals:
        die("%s is in the directory but has no rows in the scope table today." % a.lab, 3)
    rows, totals = rows_for_sites(sites, vals, a.refresh)
    sel = filt(rows, a.matrix, method, analyte)
    return {"lab": a.lab, "sites": sites, "lab_name_values": vals, "page_total_records": totals,
            "rows_for_sites": len(rows), "matrix": a.matrix, "method": method, "analyte": analyte,
            "rows": sel, "retrieved": today().isoformat(), "source": SCOPE_PAGE, "limits": LIMITS}


def cmd_who(a):
    dd = dropdowns(a.refresh)
    method, analyte = resolve_filters(a, dd)
    rows = []
    for mv in method:
        for av in (analyte or [""]):
            rows += scope_rows(method=mv, analyte=av, refresh=a.refresh)[1]
    rows = filt(rows, a.matrix)
    by = collections.OrderedDict()
    for r in sorted(rows, key=lambda r: (r["lab_name"], r["ai"])):
        g = by.setdefault((r["ai"], r["lab_name"]), {"ai": r["ai"], "lelap_id": r["lelap_id"], "lab_name": r["lab_name"],
                                                      "lab_state": r["lab_state"], "matrices": set(), "types": set(),
                                                      "analytes": set()})
        g["matrices"].add(r["matrix"])
        g["types"].add(r["accreditation_type"])
        g["analytes"].add(r["analyte"])
    labs = [dict(g, matrices=sorted(g["matrices"]), types=sorted(g["types"]), analytes=sorted(g["analytes"]))
            for g in by.values()]
    return {"method": method, "analyte": analyte, "matrix": a.matrix, "labs": labs,
            "retrieved": today().isoformat(), "source": SCOPE_PAGE, "limits": LIMITS}


def current_status(rows, matrix, method, analyte):
    exact = filt(rows, matrix, method, analyte)
    if exact:
        return "LISTED", exact
    m_rows = filt(rows, matrix, method)
    if m_rows:
        return "METHOD_LISTED_ANALYTE_NOT", m_rows
    other_matrix = filt(rows, None, method, analyte)
    if other_matrix:
        return "OTHER_MATRIX_ONLY", other_matrix
    return "NOT_LISTED", []


def cmd_check(a):
    try:
        sample = datetime.date.fromisoformat(a.date)
    except ValueError:
        die("--date must be YYYY-MM-DD", 2)
    if a.matrix not in MATRICES:
        die("--matrix must be one of %s" % ", ".join(MATRICES), 2)
    dd = dropdowns(a.refresh)
    method, analyte = resolve_filters(a, dd)
    sites, vals = resolve_lab(a.lab, a.refresh)
    ais = sorted({s["ai"] for s in sites})
    if len(ais) > 1:
        die("%r covers %d sites with separate AIs and separate scopes. Rerun with the AI of the site that ran the "
            "samples (the lab report's address tells you which):\n%s"
            % (a.lab, len(ais), "\n".join("  %s  %s (located %s; mail %s)" % (s["ai"], s["name"], s["state"], s["city"])
                                          for s in sites)), 3)
    res = {"lab": a.lab, "site": sites[0] if sites else None, "matrix": a.matrix, "method": method,
           "analyte": analyte, "sample_date": sample.isoformat(), "retrieved": today().isoformat()}
    rows = rows_for_sites(sites, vals, a.refresh)[0] if vals else []
    # No rows at all for the site means its directory name and scope-table name stopped lining up (or the
    # site has no published scope), which says nothing about this analysis, so it must not read as NOT_LISTED.
    status, ev = current_status(rows, a.matrix, method, analyte) if rows else ("UNMAPPED", [])
    res["current"] = {"status": status, "rows": ev[:60], "rows_total": len(ev),
                      "accreditation_types": sorted({r["accreditation_type"] for r in ev})}
    if status == "NOT_LISTED":
        base = re.findall(r"\d{3,4}", " ".join(method))
        res["current"]["same_method_family_on_scope"] = sorted(
            {r["method"] for r in filt(rows, a.matrix) if any(b in r["method"] for b in base)})
    fy, fy_start, fy_end = fiscal_year(sample)
    res["fiscal_year"] = {"fy": fy, "start": fy_start.isoformat(), "end": fy_end.isoformat()}
    if sample >= today():
        res["history"] = None
        res["history_note"] = "Sample date is today or later: only current status applies."
    elif not ais:
        res["history"] = None
        res["history_note"] = ("No AI resolved for this lab, so EDMS cannot be searched. Find the lab's AI "
                               "(lab report letterhead, `ldeq-edms-search`) and rerun `history <AI>`.")
    else:
        docs = edms_docs(ais[0], a.refresh)
        cert = certificate_for(docs, fy, fy_start)
        since = cert["date"] if cert else fy_start.isoformat()
        changes = [x for x in docs if x["class"] in ("certificate", "status") and x is not cert
                   and since <= x["date"] <= sample.isoformat()]
        related = [x for x in docs if x["class"] == "related" and fy_start.isoformat() <= x["date"] <= sample.isoformat()]
        earlier = [x for x in docs if x["class"] == "certificate" and x["date"] < fy_start.isoformat()]
        later = [x for x in docs if x["class"] in ("certificate", "status") and sample.isoformat() < x["date"] <= fy_end.isoformat()]
        res["history"] = {"edms_ai": ais[0], "lelap_docs": len(docs), "fy_certificate": cert,
                          "changes_before_sample": sorted(changes, key=lambda x: x["date"]),
                          "related_correspondence": sorted(related, key=lambda x: x["date"]),
                          "later_same_fy": sorted(later, key=lambda x: x["date"]),
                          "last_certificate_before_fy": max(earlier, key=lambda x: x["date"]) if earlier else None}
        if cert:
            ids = [cert["id"]] + [x["id"] for x in res["history"]["changes_before_sample"]]
            res["history_note"] = ("Pull these with ldeq-edms-download, then document-ocr, and read the scope pages "
                                   "for %s / %s / %s: %s. A suspension or withdrawal only matters if its test category "
                                   "or method covers this analysis (§5705.A allows partial suspension)."
                                   % (a.matrix, "; ".join(method), "; ".join(analyte), ", ".join(map(str, ids))))
        else:
            res["history_note"] = ("EDMS holds no FY%02d certificate or scope for AI %s. That is a gap in the public "
                                   "file, not proof the lab was unaccredited. Request the FY%02d certificate and scope "
                                   "of accreditation (and any amendment, suspension or withdrawal notices dated %s to %s) "
                                   "through la-public-records-request / the LDEQ PRR form (%s); program questions to %s."
                                   % (fy % 100, ais[0], fy % 100, fy_start, sample, PRR, LELAP_EMAIL))
    res["limits"] = LIMITS
    res["applicability_screen"] = [{"question": q, "rule": r} for q, r in SCREEN]
    res["screen_note"] = SCREEN_NOTE
    return res


def cmd_history(a):
    docs = edms_docs(a.ai, a.refresh)
    sel = docs if a.all_docs else [x for x in docs if x["class"] in ("certificate", "status", "related")]
    if a.fy:
        fy, s, e = int(a.fy), datetime.date(int(a.fy) - 1, 7, 1), datetime.date(int(a.fy), 6, 30)
        lo = (s - datetime.timedelta(days=60)).isoformat()
        sel = [x for x in sel if lo <= x["date"] <= e.isoformat() or fy_label(x["description"]) == fy]
    if not docs:
        die("EDMS has no LELAP-media documents under AI %s. Check the AI (`labs`), or the lab's file may sit under "
            "a predecessor AI after a move or ownership change." % a.ai, 3)
    return {"ai": a.ai, "fy": a.fy, "lelap_docs": len(docs),
            "classes": dict(collections.Counter(x["class"] for x in docs)),
            "docs": sorted(sel, key=lambda x: x["date"], reverse=True), "retrieved": today().isoformat(),
            "source": EDMS, "download": "doc ids -> ldeq-edms-download (CAPTCHA) -> document-ocr"}


def cmd_values(a):
    dd = dropdowns(a.refresh)
    vals = dd["methods" if a.cmd == "methods" else "analytes"]
    q = norm(a.text)
    return {"kind": a.cmd, "query": a.text, "values": [v for v in vals if q in norm(v)]}


def cmd_export(a):
    if not a.yes:
        die("export pulls the whole statewide scope table in one request (%s). Rerun with --yes to proceed; "
            "for one lab or method, `scope`/`who` fetch only what they need." % EXPORT_SIZE, 2)
    total, rows = scope_rows(refresh=a.refresh)
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, SCOPE_COLS)
        w.writeheader()
        w.writerows(rows)
    return {"out": a.out, "total_records": total, "rows_written": len(rows), "retrieved": today().isoformat()}


# ---------------------------------------------------------------- text output

def doc_line(x):
    return "  %s  %-9s %-24s %s" % (x["date"], x["id"], (x["type"] + ("/" + x["subtype"] if x["subtype"] else ""))[:24],
                                    x["description"][:110])


def show(cmd, r):
    p = print
    if cmd == "health":
        for k, v in r.items():
            p("%-34s %s" % (k, v))
        return
    if cmd == "labs":
        p("%-8s %-6s %-58s %-3s %s" % ("AI", "LELAP", "Name", "ST", "Mailing city, ST"))
        for s in r["labs"]:
            p("%-8s %-6s %-58s %-3s %s%s" % (s["ai"], s["lelap_id"], s["name"][:58], s["state"],
                                             (s["city"] + ", " + s.get("mail_state", ""))[:26],
                                              "   (%d sites share this name)" % s["sites_with_this_name"]
                                              if s["sites_with_this_name"] > 1 else ""))
        p("\n%d labs. Source: %s, retrieved %s." % (len(r["labs"]), r["source"], r["retrieved"]))
        return
    if cmd == "scope":
        for s in r["sites"]:
            p("Site: AI %s  %s (located %s; mail %s)" % (s["ai"], s["name"], s["state"], s["city"]))
        p("Page Total Records for %s: %s; rows for these sites: %d; after filters: %d"
          % (" | ".join(r["lab_name_values"]), r["page_total_records"], r["rows_for_sites"], len(r["rows"])))
        p("%-6s %-8s %-4s %-45s %-30s %s" % ("LELAP", "AI", "Mtx", "Analyte", "Method", "Type"))
        for x in sorted(r["rows"], key=lambda x: (x["matrix"], x["method"], x["analyte"])):
            p("%-6s %-8s %-4s %-45s %-30s %s" % (x["lelap_id"], x["ai"], x["matrix"], x["analyte"][:45],
                                                  x["method"][:30], x["accreditation_type"]))
        p("\n" + "\n".join("Note: " + l for l in r["limits"]))
        p("Source: %s, retrieved %s." % (r["source"], r["retrieved"]))
        return
    if cmd == "who":
        p("Method: %s%s%s" % (" | ".join(r["method"]), "  Analyte: " + " | ".join(r["analyte"]) if r["analyte"] else "",
                              "  Matrix: " + r["matrix"] if r["matrix"] else ""))
        p("%-8s %-6s %-55s %-3s %-14s %-12s %s" % ("AI", "LELAP", "Lab", "ST", "Matrices", "Types", "Analytes"))
        for g in r["labs"]:
            p("%-8s %-6s %-55s %-3s %-14s %-12s %d" % (g["ai"], g["lelap_id"], g["lab_name"][:55], g["lab_state"],
                                                     ",".join(g["matrices"]), ",".join(g["types"])[:12], len(g["analytes"])))
        p("\n%d lab sites. Source: %s, retrieved %s." % (len(r["labs"]), r["source"], r["retrieved"]))
        p("\n".join("Note: " + l for l in r["limits"]))
        return
    if cmd == "check":
        s = r["site"]
        p("Lab: %s" % ("AI %s  %s (located %s; mail %s)" % (s["ai"], s["name"], s["state"], s["city"]) if s else r["lab"]))
        p("Analysis: %s / %s / %s (%s)   Sample date: %s   FY%02d (%s to %s)"
          % (r["matrix"], " | ".join(r["method"]), " | ".join(r["analyte"]), MATRICES[r["matrix"]], r["sample_date"],
             r["fiscal_year"]["fy"] % 100, r["fiscal_year"]["start"], r["fiscal_year"]["end"]))
        c = r["current"]
        p("\nCurrent scope (%s): %s" % (r["retrieved"], {
            "LISTED": "LISTED for this matrix, method and analyte; accreditation type %s" % ", ".join(c["accreditation_types"]),
            "METHOD_LISTED_ANALYTE_NOT": "method listed for this matrix, but NOT for this analyte (%d other analytes)" % c["rows_total"],
            "OTHER_MATRIX_ONLY": "method and analyte listed only for another matrix: %s" % ", ".join(sorted({x["matrix"] for x in c["rows"]})),
            "NOT_LISTED": "NOT LISTED for this matrix and method",
            "UNMAPPED": "UNKNOWN: no scope rows found for this site. Its directory name may differ from the scope "
                        "table's; try `scope` with a name variant or `labs` before drawing any conclusion"}[c["status"]]))
        if c.get("same_method_family_on_scope"):
            p("  Same method number on this lab's %s scope (different method strings, not equivalent): %s"
              % (r["matrix"], "; ".join(c["same_method_family_on_scope"])))
        if c["status"] == "METHOD_LISTED_ANALYTE_NOT":
            p("  Analytes listed under this method: %s" % "; ".join(sorted({x["analyte"] for x in c["rows"]}))[:900])
        h = r["history"]
        p("\nHistory (EDMS, LELAP media):")
        if h:
            p("  %d LELAP documents under AI %s." % (h["lelap_docs"], h["edms_ai"]))
            if h["fy_certificate"]:
                p("  FY certificate/scope:")
                p(doc_line(h["fy_certificate"]))
            else:
                p("  FY certificate/scope: NONE in EDMS for this fiscal year.")
                if h["last_certificate_before_fy"]:
                    p("  Last certificate before this FY:")
                    p(doc_line(h["last_certificate_before_fy"]))
            if h["changes_before_sample"]:
                p("  Other certificates, amendments, suspensions, withdrawals from then to the sample date:")
                for x in h["changes_before_sample"]:
                    p(doc_line(x))
            if h["related_correspondence"]:
                p("  Related requests and correspondence in the FY before the sample date:")
                for x in h["related_correspondence"]:
                    p(doc_line(x))
            if h["later_same_fy"]:
                p("  Later in the same FY (after the sample date; context only):")
                for x in h["later_same_fy"]:
                    p(doc_line(x))
        p("  " + r["history_note"])
        p("\nLimits:")
        for l in r["limits"]:
            p("  - " + l)
        p("\nApplicability screen (answer each before calling a gap a defect):")
        for q in r["applicability_screen"]:
            p("  - %s %s" % (q["question"], q["rule"]))
        p("  " + r["screen_note"])
        return
    if cmd == "history":
        p("AI %s: %d LELAP-media documents in EDMS (%s)." % (r["ai"], r["lelap_docs"],
                                                         ", ".join("%s %d" % kv for kv in sorted(r["classes"].items()))))
        for x in r["docs"]:
            p("%-11s" % x["class"] + doc_line(x))
        p("\nSource: %s, retrieved %s. To read: %s." % (r["source"], r["retrieved"], r["download"]))
        return
    if cmd in ("methods", "analytes"):
        for v in r["values"]:
            p(repr(v))
        p("\n%d values." % len(r["values"]))
        return
    p(json.dumps(r, indent=1, default=str))


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

    sub.add_parser("health", help="pages up, module config scraped, Total Records == parsed rows")

    s = sub.add_parser("labs", help="accredited-lab directory search")
    s.add_argument("text", nargs="?", default="")

    s = sub.add_parser("scope", help="current scope rows for one lab (name or AI)")
    s.add_argument("lab")
    s.add_argument("--matrix", choices=sorted(MATRICES))
    s.add_argument("--method")
    s.add_argument("--analyte")

    s = sub.add_parser("who", help="labs currently accredited for a method (and analyte)")
    s.add_argument("--method", required=True)
    s.add_argument("--analyte")
    s.add_argument("--matrix", choices=sorted(MATRICES))

    s = sub.add_parser("check", help="was this lab accredited for this analysis on this date?")
    s.add_argument("lab")
    s.add_argument("--method", required=True)
    s.add_argument("--analyte", required=True)
    s.add_argument("--matrix", required=True, choices=sorted(MATRICES))
    s.add_argument("--date", required=True)

    s = sub.add_parser("history", help="EDMS LELAP document index for a lab AI")
    s.add_argument("ai")
    s.add_argument("--fy", help="fiscal year by its ending year, e.g. 2019 = 2018-07-01..2019-06-30")
    s.add_argument("--all-docs", action="store_true", help="include PT results, assessments and CAPs")

    for name in ("methods", "analytes"):
        s = sub.add_parser(name, help="exact %s dropdown values containing text" % name[:-1])
        s.add_argument("text")

    s = sub.add_parser("export", help="whole statewide scope table to CSV (%s)" % EXPORT_SIZE)
    s.add_argument("out")
    s.add_argument("--yes", action="store_true", help="confirm the large download")

    args = ap.parse_args()
    fn = {"health": cmd_health, "labs": cmd_labs, "scope": cmd_scope, "who": cmd_who, "check": cmd_check,
          "history": cmd_history, "methods": cmd_values, "analytes": cmd_values, "export": cmd_export}[args.cmd]
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
