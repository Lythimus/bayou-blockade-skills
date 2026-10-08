"""Find industry peers for a facility and pull their reported emissions.

Subcommands (all read/write OUT/summary.json and OUT/raw/):
  codes       --id RID [--id RID ...]                      SIC/NAICS per EPA source system (ECHO DFR)
  candidates  --target RID [...] --sic CODE [...] [--ncs CODE ...] --state XX
              [--scopes state,region,national]              ECHO facility search, clustered into sites
  emissions   [--min 5] [--band 3] [--top 5] [--exclude RID ...] [--include RID ...] [--zip PATH]
                                                            ECHO combined-emissions bulk file, per site

A physical plant often holds 2-3 Registry IDs, with GHGRP rows under one and NEI rows under
another, so every comparison here is between site clusters, never raw Registry IDs.
"""
import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ECHO = "https://echodata.epa.gov/echo/"
EMIS_URL = "https://echo.epa.gov/files/echodownloads/POLL_RPT_COMBINED_EMISSIONS.zip"
CACHE = os.path.expanduser("~/.cache/bayou/echo")
UA = {"User-Agent": "bayou-comparable-facilities"}

# ECHO facility-search column IDs (from get_facilities metadata). get_download returns a
# trimmed default column set, so the program-ID and code columns are requested explicitly.
# FacSICCodes/FacNAICSCodes merge every program's codes (a refinery with an ammonia unit
# lists 2873); 106 CAANAICS and 107 CAASICs are the air permit's own codes.
QCOLUMNS = "1,2,3,4,6,7,8,15,17,19,20,21,22,28,29,30,32,97,106,107"

EPA_REGIONS = {
    1: "CT ME MA NH RI VT", 2: "NJ NY PR VI", 3: "DE DC MD PA VA WV",
    4: "AL FL GA KY MS NC SC TN", 5: "IL IN MI MN OH WI", 6: "AR LA NM OK TX",
    7: "IA KS MO NE", 8: "CO MT ND SD UT WY", 9: "AZ CA HI NV AS GU MP",
    10: "AK ID OR WA",
}
STATE_REGION = {st: r for r, s in EPA_REGIONS.items() for st in s.split()}
SCOPES = ["state", "region", "national"]

# NEI pollutant names exactly as the bulk file spells them. PM2.5/PM10 use the
# filterable+condensible totals; the "portion" rows (CAP and OTH) are subsets of these.
CAPS = [
    ("NOx", "Nitrogen oxides"), ("SO2", "Sulfur dioxide"), ("CO", "Carbon monoxide"),
    ("VOC", "Volatile organic compounds"), ("PM2.5", "Primary PM2.5 (filterables and condensibles)"),
    ("PM10", "Primary PM10 (filterables and condensibles)"), ("NH3", "Ammonia"), ("Lead", "Lead"),
]
# Compared one by one. NEI lists pollutant groups alongside their members (PAH and
# naphthalene), so a summed HAP total would double-count.
KEY_HAPS = ["Benzene", "1,3-Butadiene", "Ethylene oxide", "Chloroprene", "Formaldehyde",
            "Hydrochloric acid", "Hydrogen sulfide"]
LB_TO_T = 0.000453592
# NEI is triennial, so a peer one cycle off is still comparable; two cycles off (2008 against
# 2020) describes a different plant configuration and control era.
NEI_MAX_GAP = 3
# GHGRP reporting threshold for most source categories (40 CFR 98.2), metric tonnes CO2e.
GHGRP_MIN_T = 25000


def log(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- HTTP

def fetch(url, tries=4):
    """GET with backoff. ECHO returns 503 under load; 429 means the hourly/daily quota is spent."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=150) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sys.exit("ECHO returned 429: the 300/hour or 1,500/day quota is spent. "
                         "Re-run later; cached responses under OUT/raw are reused.")
            if e.code not in (500, 502, 503, 504) or i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
        wait = 15 * (i + 1)
        log(f"  ECHO unavailable, retrying in {wait}s")
        time.sleep(wait)


def echo_json(service, params, raw, tag):
    path = os.path.join(raw, f"{tag}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = ECHO + service + "?" + urllib.parse.urlencode({"output": "JSON", **params})
    body = fetch(url)
    try:
        d = json.loads(body)
    except ValueError:
        sys.exit(f"ECHO returned non-JSON for {url}:\n{body[:300]!r}")
    with open(path, "w") as f:
        json.dump(d, f)
    return d


def key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def split_ids(s):
    return [x for x in re.split(r"[\s,]+", s or "") if x]


def facility_search(params, raw):
    """One get_facilities + one get_download. Returns (rows, error) with row keys normalized
    so both ColumnName (REGISTRY_ID) and ObjectName (RegistryID) spellings read the same."""
    tag = "fac-" + hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
    csv_path = os.path.join(raw, tag + ".csv")
    if not os.path.exists(csv_path):
        # The QID is only good for ~30 minutes, so the get_facilities response is never cached:
        # a re-run after a failed download must ask for a fresh QID.
        url = ECHO + "echo_rest_services.get_facilities?" + urllib.parse.urlencode({"output": "JSON", **params})
        for attempt in range(3):
            body = fetch(url)
            try:
                res = json.loads(body).get("Results", {})
                break
            except ValueError:
                # Seen right after a maintenance window: HTTP 200 with an empty or HTML body.
                if attempt == 2:
                    sys.exit(f"ECHO returned non-JSON for {url}:\n{body[:300]!r}")
                time.sleep(10)
        # An over-broad query returns Results.Error and no QueryRows key at all.
        if res.get("Error"):
            return None, res["Error"].get("ErrorMessage", str(res["Error"]))
        if int(res.get("QueryRows") or 0) == 0:
            return [], None
        body = fetch(ECHO + "echo_rest_services.get_download?" + urllib.parse.urlencode(
            {"output": "CSV", "qid": res["QueryID"], "qcolumns": QCOLUMNS}))
        head = body[:2000].decode("utf-8-sig", errors="replace")
        if "registryid" not in key(head.splitlines()[0] if head else ""):
            sys.exit(f"get_download did not return a facility CSV for {params}:\n{head[:300]}")
        # ECHO recycles QIDs across users; a stale one returns someone else's rows with a valid header.
        n = sum(1 for _ in csv.reader(io.StringIO(body.decode("utf-8-sig", errors="replace")))) - 1
        if n != int(res["QueryRows"]):
            sys.exit(f"get_download returned {n} rows but the query matched {res['QueryRows']} "
                     f"({params}); the QID was likely recycled. Re-run.")
        with open(csv_path + ".part", "wb") as f:
            f.write(body)
        os.replace(csv_path + ".part", csv_path)
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = [{key(k): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]
    return rows, None


# ---------------------------------------------------------------- summary.json

def load_summary(out):
    p = os.path.join(out, "summary.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def write_summary(out, d):
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(d, f, indent=1)


# ---------------------------------------------------------------- codes

def cmd_codes(a):
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    found = []
    for rid in a.id:
        d = echo_json("dfr_rest_services.get_dfr", {"p_id": rid}, raw, f"dfr-{rid}")
        res = d.get("Results", {})
        for block, field in (("SIC", "SICCodes"), ("NAICS", "NAICSCodes")):
            for src in ((res.get(block) or {}).get("Sources") or []):
                for c in src.get(field) or []:
                    found.append({"registry_id": rid, "type": block, "system": c.get("EPASystem"),
                                  "source_id": c.get("SourceID"),
                                  "code": c.get(block + "Code"), "desc": c.get(block + "Desc")})
    seen = set()
    rows = []
    for c in found:
        k = (c["type"], c["system"], c["source_id"], c["code"])
        if k not in seen:
            seen.add(k)
            rows.append(c)
    # The air permit's own codes (ICIS-Air) best match a repermit. TRI and GHGRP NAICS are
    # self-reported and usually right. EIS codes are often stale (Shell Norco's EIS record says
    # "Commercial Bakeries"), so they count only when another system agrees. RMP and NPDES
    # codes describe other units.
    sic = sorted({c["code"] for c in rows if c["type"] == "SIC" and c["system"] == "ICIS-Air"})
    trusted = {c["code"] for c in rows if c["type"] == "NAICS" and c["system"] in ("ICIS-Air", "TRI", "GHGRP")}
    ncs = sorted(x for x in trusted if len(x or "") == 6)
    print(f"{'type':5} {'system':10} {'source id':22} {'code':7} description")
    for c in sorted(rows, key=lambda c: (c["type"], c["system"] or "", c["code"] or "")):
        print(f"{c['type']:5} {c['system'] or '':10} {c['source_id'] or '':22} {c['code'] or '':7} {c['desc'] or ''}")
    print(f"\nSuggested match set: --sic {' --sic '.join(sic) or '(none from ICIS-Air)'}"
          + (f" --ncs {' --ncs '.join(ncs)}" if ncs else ""))
    d = load_summary(a.out)
    d["codes"] = {"target_ids": a.id, "rows": rows, "suggested_sic": sic, "suggested_ncs": ncs}
    write_summary(a.out, d)


# ---------------------------------------------------------------- candidates

def haversine_miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


GENERIC = {"THE", "INC", "LLC", "LP", "CO", "CORP", "COMPANY", "CORPORATION", "US", "USA", "OF"}


def name_token(name):
    for t in re.findall(r"[A-Z0-9]+", (name or "").upper()):
        if t not in GENERIC and len(t) > 1:
            return t
    return ""


def fac_record(r):
    return {
        "registry_id": r.get("registryid"), "name": r.get("facname"), "street": r.get("facstreet"),
        "city": r.get("faccity"), "state": r.get("facstate"), "county": r.get("faccounty"),
        "lat": fnum(r.get("faclat")), "lon": fnum(r.get("faclong")),
        "sic": split_ids(r.get("facsiccodes")), "naics": split_ids(r.get("facnaicscodes")),
        "caa_sic": split_ids(r.get("caasics")), "caa_naics": split_ids(r.get("caanaics")),
        "air_ids": split_ids(r.get("airids")), "tri_ids": split_ids(r.get("triids")),
        "ghg_ids": split_ids(r.get("ghgids")), "eis_ids": split_ids(r.get("eisids")),
        "camd_ids": split_ids(r.get("camdids")), "caa_permit_types": r.get("caapermittypes"),
        "matched": [],
    }


def geo_of(fac_state, state):
    if fac_state == state:
        return "state"
    return "region" if STATE_REGION.get(fac_state) == STATE_REGION[state] else "national"


def run_code(scopes, state, base, raw):
    """One national query per code, scoped afterwards by FacState. Per-state queries only when
    the national one is refused as too large, or when national was not requested."""
    if "national" in scopes:
        got, err = facility_search(dict(base), raw)
        if not err:
            return got
        log(f"  national query refused ({err}); querying state by state")
        states = sorted(STATE_REGION)
    elif "region" in scopes:
        states = sorted(EPA_REGIONS[STATE_REGION[state]].split())
    else:
        states = [state]
    rows = []
    for st in states:
        got, err = facility_search(dict(base, p_st=st), raw)
        if err:
            log(f"  {st}: {err}")
        rows += got or []
    return rows


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def cluster(facs, target_ids, near_mi=0.5):
    """Union Registry IDs that share any air/TRI/GHGRP/EIS/CAMD program ID, or that sit within
    near_mi of each other under the same leading name word. Distance alone would merge
    neighboring plants of different companies, which are legitimate peers of each other."""
    dsu = DSU()
    owner = {}
    for rid, f in facs.items():
        dsu.find(rid)
        for k in ("air_ids", "tri_ids", "ghg_ids", "eis_ids", "camd_ids"):
            for pid in f[k]:
                o = owner.setdefault((k, pid), rid)
                if o != rid:
                    dsu.union(rid, o)
    ids = [r for r in facs if facs[r]["lat"] is not None and facs[r]["lon"] is not None]
    for i, a in enumerate(ids):
        fa = facs[a]
        for b in ids[i + 1:]:
            fb = facs[b]
            if abs(fa["lat"] - fb["lat"]) > 0.01 or abs(fa["lon"] - fb["lon"]) > 0.012:
                continue
            if (haversine_miles(fa["lat"], fa["lon"], fb["lat"], fb["lon"]) <= near_mi
                    and name_token(fa["name"]) == name_token(fb["name"])):
                dsu.union(a, b)
    for t in target_ids[1:]:
        dsu.union(t, target_ids[0])
    groups = {}
    for rid in facs:
        groups.setdefault(dsu.find(rid), []).append(rid)
    return list(groups.values())


def cmd_candidates(a):
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    st = a.state.upper()
    if st not in STATE_REGION:
        sys.exit(f"Unknown state {st}")
    scopes = [s.strip() for s in a.scopes.split(",")]
    facs = {}

    for rid in a.target:
        # get_facilities ignores p_id (it runs nationwide and hits the queryset limit); p_frs filters.
        got, err = facility_search({"p_frs": rid}, raw)
        if err or not got:
            sys.exit(f"Target {rid} not found in ECHO ({err or 'no rows'})")
        for r in got:
            facs[r["registryid"]] = dict(fac_record(r), target=True)

    queries = [("sic", c, {"p_sic": c, "p_act": "Y"}) for c in a.sic]
    queries += [("naics", c, {"p_ncs": c, "p_act": "Y"}) for c in a.ncs]
    for kind, code, base in queries:
        log(f"{kind} {code}")
        for r in run_code(scopes, st, base, raw):
            rid = r.get("registryid")
            if not rid or geo_of(r.get("facstate"), st) not in scopes:
                continue
            f = facs.get(rid) or dict(fac_record(r), target=False)
            if f"{kind}:{code}" not in f["matched"]:
                f["matched"].append(f"{kind}:{code}")
            facs[rid] = f

    n_all = len(facs)
    # No air program ID means no air emissions record to compare; keep the target regardless.
    facs = {k: f for k, f in facs.items()
            if f["target"] or f["air_ids"] or f["eis_ids"] or f["ghg_ids"] or f["camd_ids"]}
    groups = cluster(facs, a.target)
    sites = []
    tgt = None
    for g in groups:
        members = [facs[r] for r in g]
        is_target = any(r in a.target for r in g)
        # Representative: the member matching the most codes, then the one with NEI IDs.
        rep = max(members, key=lambda f: (f["target"], len(f["matched"]), bool(f["eis_ids"]),
                                           bool(f["ghg_ids"])))
        site = {
            "registry_ids": sorted(g, key=lambda r: r != rep["registry_id"]),
            "name": rep["name"], "street": rep["street"], "city": rep["city"], "state": rep["state"],
            "lat": rep["lat"], "lon": rep["lon"],
            "sic": sorted({c for m in members for c in m["sic"]}),
            "naics": sorted({c for m in members for c in m["naics"]}),
            "caa_sic": sorted({c for m in members for c in m["caa_sic"]}),
            "caa_naics": sorted({c for m in members for c in m["caa_naics"]}),
            "matched": sorted({c for m in members for c in m["matched"]}),
            "program_ids": {k: sorted({p for m in members for p in m[k]})
                            for k in ("air_ids", "tri_ids", "ghg_ids", "eis_ids", "camd_ids")},
            "members": [{"registry_id": m["registry_id"], "name": m["name"], "street": m["street"],
                         "city": m["city"]} for m in members],
        }
        if is_target:
            site["auto_merged"] = [r for r in g if r not in a.target]
            tgt = site
        else:
            sites.append(site)
    for s in sites:
        s["geo"] = geo_of(s["state"], st)
        if tgt and None not in (tgt["lat"], tgt["lon"], s["lat"], s["lon"]):
            s["distance_mi"] = round(haversine_miles(tgt["lat"], tgt["lon"], s["lat"], s["lon"]), 1)

    d = load_summary(a.out)
    d["candidates"] = {
        "target_ids": a.target, "state": st, "region": STATE_REGION[st], "scopes": scopes,
        "sic": a.sic, "ncs": a.ncs, "retrieved": dt.date.today().isoformat(),
        "n_registry_ids": n_all, "n_with_air_ids": len(facs) - len(a.target),
        "target": tgt, "sites": sites,
    }
    d.pop("emissions", None)
    write_summary(a.out, d)
    by = {g: sum(1 for s in sites if s["geo"] == g) for g in SCOPES}
    print(f"Target site: {tgt['name']} ({', '.join(tgt['registry_ids'])})")
    if tgt["auto_merged"]:
        print(f"  auto-merged into target (shared program ID or co-located): {', '.join(tgt['auto_merged'])}")
    print(f"{n_all} Registry IDs matched; {len(sites)} peer sites with an air program "
          f"(in {st}: {by['state']}, rest of EPA Region {STATE_REGION[st]}: {by['region']}, "
          f"elsewhere: {by['national']})")


# ---------------------------------------------------------------- emissions

def zip_path(override):
    if override:
        return override
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, "POLL_RPT_COMBINED_EMISSIONS.zip")
    stamp = dest + ".last-modified"
    req = urllib.request.Request(EMIS_URL, headers=UA, method="HEAD")
    lm = None
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            lm = r.headers.get("Last-Modified", "")
    except (urllib.error.URLError, TimeoutError) as e:
        if os.path.exists(dest):
            log(f"Could not check {EMIS_URL} ({e}); using the cached copy")
            return dest
    if os.path.exists(dest) and os.path.exists(stamp) and open(stamp).read() == lm:
        return dest
    log(f"Downloading {EMIS_URL} (~150 MB)")
    with urllib.request.urlopen(urllib.request.Request(EMIS_URL, headers=UA), timeout=600) as r, \
            open(dest + ".part", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(dest + ".part", dest)
    with open(stamp, "w") as f:
        f.write(lm or "")
    return dest


def extract(zpath, rids, raw):
    """Stream the ~900 MB CSV once and keep the wanted Registry IDs (about 15 s)."""
    sig = hashlib.sha1((os.path.abspath(zpath) + str(os.path.getmtime(zpath))
                        + ",".join(sorted(rids))).encode()).hexdigest()[:12]
    path = os.path.join(raw, f"emissions-{sig}.csv")
    if not os.path.exists(path):
        z = zipfile.ZipFile(zpath)
        with z.open(z.namelist()[0]) as src, open(path + ".part", "w", newline="") as dst:
            r = csv.reader(io.TextIOWrapper(src, encoding="utf-8", errors="replace"))
            w = csv.writer(dst)
            w.writerow(next(r))
            for row in r:
                if row[1] in rids:
                    w.writerow(row)
        os.replace(path + ".part", path)
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def nearest(years, want):
    if not years:
        return None
    if want in years:
        return want
    return min(years, key=lambda y: (abs(y - want), y > want))


def site_emissions(rows):
    """Rows for one site's Registry IDs -> per-program, per-year pollutant totals.

    A program ID listed under two Registry IDs of the same site appears twice in the file;
    de-duplicating on (program, program ID, year, pollutant) counts it once."""
    seen = set()
    nei, ghg, tri, camd = {}, {}, {}, {}
    nei_units = set()
    for r in rows:
        k = (r["PGM_SYS_ACRNM"], r["PGM_SYS_ID"], r["REPORTING_YEAR"], r["POLLUTANT_NAME"])
        if k in seen:
            continue
        seen.add(k)
        try:
            v = float(r["ANNUAL_EMISSION"])
        except ValueError:
            continue
        y = int(r["REPORTING_YEAR"])
        p, pgm = r["POLLUTANT_NAME"], r["PGM_SYS_ACRNM"]
        if pgm == "EIS":
            if r["UNIT_OF_MEASURE"] != "Pounds":
                nei_units.add(r["UNIT_OF_MEASURE"])
                continue
            yr = nei.setdefault(y, {"cap": {}, "hap": {}, "other": {}, "eis_ids": set()})
            yr["eis_ids"].add(r["PGM_SYS_ID"])
            bucket = "hap" if r["NEI_TYPE"] == "HAP" else "cap" if r["NEI_TYPE"] in ("CAP", "GHG") else "other"
            yr[bucket][p] = yr[bucket].get(p, 0.0) + v
        elif pgm == "E-GGRT":
            g = ghg.setdefault(y, {})
            g[p] = g.get(p, 0.0) + v
        elif pgm == "TRIS":
            t = tri.setdefault(y, {})
            t[p] = t.get(p, 0.0) + v
        elif pgm == "CAMDBS":
            c = camd.setdefault(y, {})
            c[p] = c.get(p, 0.0) + v
    for yr in nei.values():
        yr["eis_ids"] = sorted(yr["eis_ids"])
    return {"nei": nei, "ghg": ghg, "tri": tri, "camd": camd, "nei_units_skipped": sorted(nei_units)}


def nei_value(yr, name):
    for b in ("cap", "hap", "other"):
        if name in yr[b]:
            return yr[b][name]
    return None


def summarize(site, em, nei_year, ghg_year, tri_year):
    """Pick comparable years and the headline numbers. Returns a flat dict."""
    s = {"nei_year": None, "nei_year_flag": "", "ghg_year": None, "tri_year": None}
    ny = nearest(sorted(em["nei"]), nei_year) if nei_year else (max(em["nei"]) if em["nei"] else None)
    if ny is not None and nei_year and abs(ny - nei_year) > NEI_MAX_GAP:
        s["nei_year_flag"] = f"latest NEI is {max(em['nei'])}; not compared"
        ny = None
    if ny is not None:
        yr = em["nei"][ny]
        s["nei_year"] = ny
        if nei_year and ny != nei_year:
            s["nei_year_flag"] = f"NEI {ny}, not {nei_year}"
        s["eis_ids"] = yr["eis_ids"]
        s["cap_lb"] = {lbl: nei_value(yr, nm) for lbl, nm in CAPS}
        s["hap_lb"] = dict(yr["hap"])
        for nm in KEY_HAPS:
            v = nei_value(yr, nm)
            if v is not None:
                s["hap_lb"][nm] = v
        s["nei_co2_t"] = yr["cap"].get("Carbon Dioxide", 0.0) * LB_TO_T or None
    gy = nearest(sorted(em["ghg"]), ghg_year) if ghg_year else (max(em["ghg"]) if em["ghg"] else None)
    if gy is not None:
        s["ghg_year"] = gy
        s["ghg_t_co2e"] = sum(em["ghg"][gy].values())
        s["ghg_by_gas"] = em["ghg"][gy]
    ty = nearest(sorted(em["tri"]), tri_year) if tri_year else (max(em["tri"]) if em["tri"] else None)
    if ty is not None:
        s["tri_year"] = ty
        s["tri_air_lb"] = em["tri"][ty]
    if em["camd"]:
        cy = max(em["camd"])
        s["camd_year"] = cy
        s["camd_lb"] = em["camd"][cy]
    # Size proxy: GHGRP CO2e first; NEI CO2 (converted to metric tonnes) only as a fallback.
    if s.get("ghg_t_co2e"):
        s["size"], s["size_source"], s["size_year"] = s["ghg_t_co2e"], "GHGRP CO2e", s["ghg_year"]
    elif s.get("nei_co2_t"):
        s["size"], s["size_source"], s["size_year"] = s["nei_co2_t"], "NEI CO2", s["nei_year"]
    else:
        s["size"], s["size_source"], s["size_year"] = None, "size unknown", None
    s["nei_units_skipped"] = em["nei_units_skipped"]
    return s


AIR_MISMATCH = 4


def older_missing_eis(listed, em):
    """EIS IDs listed for the site, absent from the emissions file, and older than every ID that is
    present. EIS IDs tend to rise with record age, so a missing older ID is often the plant's
    original record and the present one a side unit. A missing newer ID is usually a unit or record added
    after the last NEI and leaves the totals whole (Martinez, Suncor Commerce City)."""
    seen = {i for yr in em["nei"].values() for i in yr["eis_ids"]}
    if not seen:
        return []
    floor = min(int(i) for i in seen if i.isdigit()) if any(i.isdigit() for i in seen) else None
    return sorted(i for i in set(listed) - seen if floor is not None and i.isdigit() and int(i) < floor)


def match_rank(site, sic, ncs):
    """Rank how well a site's codes describe the target's industry, air-permit codes first.

    A site whose air permit carries codes, none of them the requested ones, matched only through
    another program's records (Chevron's Pascagoula refinery via an ammonia unit, a Lyondell
    chemical plant whose air permit says warehousing). Its whole-facility emissions belong to a
    different industry, so it never makes the shortlist."""
    air_sic = bool(set(site.get("caa_sic") or []) & set(sic))
    air_ncs = bool(set(site.get("caa_naics") or []) & set(ncs))
    if air_sic and (air_ncs or not ncs):
        return 0, "air permit SIC + NAICS" if ncs else "air permit SIC"
    if air_sic or air_ncs:
        return 1, "air permit SIC" if air_sic else "air permit NAICS"
    if site.get("caa_sic") or site.get("caa_naics"):
        return AIR_MISMATCH, "air permit is " + " ".join(
            [f"SIC {c}" for c in site.get("caa_sic") or []] + [f"NAICS {c}" for c in site.get("caa_naics") or []])
    has_sic = any(c.startswith("sic:") for c in site["matched"]) or bool(set(site["sic"]) & set(sic))
    has_ncs = any(c.startswith("naics:") for c in site["matched"]) or bool(set(site["naics"]) & set(ncs))
    # No air-permit codes on record: the facility-level match is the best evidence available.
    if has_sic and has_ncs:
        return 2, "facility SIC + NAICS"
    return 3, "facility SIC" if has_sic else "facility NAICS"


def cmd_emissions(a):
    d = load_summary(a.out)
    c = d.get("candidates")
    if not c:
        sys.exit("Run `candidates` first.")
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    tgt = c["target"]
    excl = set(a.exclude or [])
    incl = set(a.include or [])
    sites = [s for s in c["sites"] if not excl & set(s["registry_ids"])]
    rids = set(tgt["registry_ids"]) | {r for s in sites for r in s["registry_ids"]}
    zp = zip_path(a.zip)
    rows = extract(zp, rids, raw)
    by_rid = {}
    for r in rows:
        by_rid.setdefault(r["REGISTRY_ID"], []).append(r)

    tem = site_emissions([r for rid in tgt["registry_ids"] for r in by_rid.get(rid, [])])
    if not (tem["nei"] or tem["ghg"]):
        sys.exit("The target has no NEI or GHGRP rows in the combined-emissions file. Check that "
                 "every Registry ID for the site was passed with --target.")
    nei_year = max(tem["nei"]) if tem["nei"] else None
    ghg_year = max(tem["ghg"]) if tem["ghg"] else None
    tri_year = max(tem["tri"]) if tem["tri"] else None
    target = dict(tgt, **summarize(tgt, tem, nei_year, ghg_year, tri_year))
    tsize = target["size"]
    target["nei_missing_eis"] = older_missing_eis(tgt["program_ids"]["eis_ids"], tem)
    if target["nei_missing_eis"]:
        log(f"WARNING: the target's EIS IDs {', '.join(target['nei_missing_eis'])} are listed in ECHO but have "
            "no rows in the emissions file; its NEI totals may be partial. Check for a missing --target ID.")

    sic, ncs = c["sic"], c["ncs"]
    peers = []
    for s in sites:
        em = site_emissions([r for rid in s["registry_ids"] for r in by_rid.get(rid, [])])
        p = dict(s, **summarize(s, em, nei_year, ghg_year, tri_year))
        p["match_rank"], p["match"] = match_rank(s, sic, ncs)
        # NEI carries every criteria pollutant and HAP; a GHGRP-only peer adds one row to the
        # comparison, so it qualifies only when the target has no NEI either.
        p["has_data"] = bool(p["nei_year"]) if tem["nei"] else bool(p.get("ghg_t_co2e"))
        if not p["nei_year"] and not p["nei_year_flag"]:
            p["nei_year_flag"] = "no NEI record linked in ECHO"
        # ECHO can list a plant's main EIS ID while the combined file holds rows only for a minor
        # one (Ponca City Refinery: 1 tpy NOx). Totals from such a site are a fragment, not a plant.
        p["nei_missing_eis"] = older_missing_eis(s["program_ids"]["eis_ids"], em)
        if p["nei_missing_eis"] and p["nei_year"]:
            p["has_data"] = False if tem["nei"] else p["has_data"]
            p["nei_year_flag"] = (f"partial NEI: EIS {', '.join(p['nei_missing_eis'])} listed in ECHO "
                                  "but absent from the emissions file")
        p["code_ok"] = p["match_rank"] < AIR_MISMATCH
        if incl & set(s["registry_ids"]):
            # Air-permit codes are sometimes plainly wrong (Marathon's Robinson, IL refinery is coded
            # SIC 1422, crushed limestone); --include is the reviewed override.
            p["code_ok"], p["match"] = True, p["match"] + " (included by user)"
        if tsize and p["size"]:
            # Different proxy sources are not on the same scale, so they never set the ratio.
            if p["size_source"] == target["size_source"]:
                p["size_ratio"] = p["size"] / tsize
            else:
                p["size_ratio"] = None
        else:
            p["size_ratio"] = None
        r = p["size_ratio"]
        p["in_band"] = bool(r and 1 / a.band <= r <= a.band)
        p["below_ghgrp"] = (p["size"] is None and target["size_source"] == "GHGRP CO2e"
                            and tsize / a.band > GHGRP_MIN_T)
        if p["below_ghgrp"]:
            # Not reporting to GHGRP bounds the site under the threshold (or it is outside every
            # covered source category), which is already below the band's floor.
            p["size_source"] = f"no GHGRP report (<{GHGRP_MIN_T:,} t or not covered)"
        peers.append(p)

    geo_rank = {g: i for i, g in enumerate(SCOPES)}

    def usable(p):
        return p["has_data"] and p["in_band"] and p["code_ok"]

    chosen = "national"
    for g in SCOPES:
        allowed = SCOPES[: SCOPES.index(g) + 1]
        if sum(1 for p in peers if p["geo"] in allowed and usable(p)) >= a.min:
            chosen = g
            break
    if chosen not in c["scopes"] and c["scopes"]:
        chosen = max(c["scopes"], key=SCOPES.index)
    allowed = SCOPES[: SCOPES.index(chosen) + 1]

    def sort_key(p):
        lr = abs(math.log(p["size_ratio"])) if p["size_ratio"] else 99
        return (p["geo"] not in allowed, not p["code_ok"], not p["has_data"], not p["in_band"],
                p["match_rank"], lr,
                geo_rank[p["geo"]])

    peers.sort(key=sort_key)
    eligible = [p for p in peers if p["geo"] in allowed and usable(p)]
    shortlist = eligible[: a.top]
    if len(shortlist) < a.top:
        # Too few in-band peers: fill with peers whose size is unknown, flagged as such.
        extra = [p for p in peers if p["geo"] in allowed and p["has_data"] and p["code_ok"]
                 and p["size"] is None and not p["below_ghgrp"]]
        shortlist += extra[: a.top - len(shortlist)]
    short_ids = {p["registry_ids"][0] for p in shortlist}
    for i, p in enumerate(peers, 1):
        p["rank"] = i
        p["shortlisted"] = p["registry_ids"][0] in short_ids

    write_csv(os.path.join(a.out, "comparables.csv"), target, peers)
    lite = ("hap_lb", "tri_air_lb", "ghg_by_gas", "camd_lb", "members", "program_ids")
    d["emissions"] = {
        "source": EMIS_URL, "zip": zp,
        "file_date": dt.datetime.fromtimestamp(os.path.getmtime(zp)).date().isoformat(),
        "retrieved": dt.date.today().isoformat(),
        "nei_year": nei_year, "ghg_year": ghg_year, "tri_year": tri_year,
        "band": a.band, "min": a.min, "top": a.top, "scope": chosen, "excluded": sorted(excl),
        "target": target, "shortlist": shortlist,
        "others": [{k: v for k, v in p.items() if k not in lite} for p in peers if not p["shortlisted"]],
        "counts": {g: {"sites": sum(1 for p in peers if p["geo"] == g),
                       "with_data": sum(1 for p in peers if p["geo"] == g and p["has_data"]),
                       "in_band": sum(1 for p in peers if p["geo"] == g and usable(p)),
                       "other_industry": sum(1 for p in peers if p["geo"] == g and not p["code_ok"])}
                   for g in SCOPES},
    }
    write_summary(a.out, d)

    print(f"Target: {target['name']} — size {fmt_size(target)}; NEI {nei_year}, GHGRP {ghg_year}, TRI {tri_year}")
    where = {"state": f"in {c['state']}", "region": f"rest of EPA Region {c['region']}", "national": "elsewhere"}
    for g in SCOPES:
        n = d["emissions"]["counts"][g]
        print(f"  {where[g]:22}: {n['sites']} sites, {n['with_data']} with emissions, {n['in_band']} within {a.band:g}x size"
              f" ({n['other_industry']} set aside: air permit names another industry)")
    print(f"Scope used: {chosen}" + ("" if any(usable(p) for p in shortlist) else "  (no peer inside the size band)"))
    aside = [p for p in peers if p["geo"] in allowed and not p["code_ok"] and p["has_data"] and p["in_band"]]
    if aside:
        print("In-band sites set aside because their air permit names another industry. Review: a miscoded "
              "permit is a real peer (re-run with --include RID):")
        for p in aside:
            print(f"   {p['name'][:42]:42} {p['state']:2} {p['match']}  {p['registry_ids'][0]}")
    n_usable = len(eligible)
    if n_usable < a.min:
        print(f"Only {n_usable} peer(s) within {a.band:g}x of the target's size in scope '{chosen}'"
              + (f"; {len(shortlist) - n_usable} more of unknown size fill the shortlist" if len(shortlist) > n_usable else "")
              + f". The target may be unusually large or small for its industry: re-run with a wider "
              f"band (--band {a.band * 2:g}) and say so in the report, or compare against fewer peers.")
    print(f"\n{'#':>2} {'site':42} {'st':2} {'match':22} {'size (t CO2e)':>15} {'ratio':>6} {'NEI':>5} ids")
    for p in shortlist:
        print(f"{p['rank']:>2} {p['name'][:42]:42} {p['state']:2} {p['match'][:22]:22} {fmt_size(p):>15} "
              f"{(p['size_ratio'] or 0):6.2f} {p['nei_year'] or '':>5} {' '.join(p['registry_ids'])}")
    print(f"\nAll {len(peers)} candidates: {os.path.join(a.out, 'comparables.csv')}")


def fmt_size(s):
    if s.get("below_ghgrp"):
        return f"<{GHGRP_MIN_T:,} (no GHGRP)"
    if s["size"] is None:
        return "unknown"
    return f"{s['size']:,.0f}" + ("" if s["size_source"] == "GHGRP CO2e" else f" ({s['size_source']})")


def write_csv(path, target, peers):
    cols = ["rank", "shortlisted", "role", "name", "city", "state", "geo", "distance_mi", "match",
            "registry_ids", "sic", "naics", "caa_sic", "caa_naics", "size_t", "size_source", "size_year", "size_ratio", "in_band",
            "nei_year", "nei_year_flag"]
    cols += [f"{lbl}_tpy" for lbl, _ in CAPS[:-1]] + ["Lead_lb"]
    cols += [f"{h}_lb" for h in KEY_HAPS] + ["ghg_year", "ghg_t_co2e", "tri_year", "tri_air_lb"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for role, p in [("target", target)] + [("peer", p) for p in peers]:
            cap = p.get("cap_lb") or {}
            hap = p.get("hap_lb") or {}
            row = [p.get("rank", ""), p.get("shortlisted", ""), role, p["name"], p["city"], p["state"],
                   p.get("geo", ""), p.get("distance_mi", ""), p.get("match", ""), " ".join(p["registry_ids"]),
                   " ".join(p["sic"]), " ".join(p["naics"]),
                   " ".join(p.get("caa_sic") or []), " ".join(p.get("caa_naics") or []),
                   round(p["size"]) if p["size"] else "", p["size_source"], p["size_year"] or "",
                   round(p["size_ratio"], 3) if p.get("size_ratio") else "", p.get("in_band", ""),
                   p["nei_year"] or "", p["nei_year_flag"]]
            row += [round(cap[lbl] / 2000, 2) if cap.get(lbl) is not None else "" for lbl, _ in CAPS[:-1]]
            row += [round(cap["Lead"], 2) if cap.get("Lead") is not None else ""]
            row += [round(hap[h], 1) if h in hap else "" for h in KEY_HAPS]
            row += [p["ghg_year"] or "", round(p["ghg_t_co2e"]) if p.get("ghg_t_co2e") else "",
                    p["tri_year"] or "", round(sum((p.get("tri_air_lb") or {}).values())) if p.get("tri_air_lb") else ""]
            w.writerow(row)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("codes")
    p.add_argument("--id", action="append", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("candidates")
    p.add_argument("--target", action="append", required=True)
    p.add_argument("--sic", action="append", default=[])
    p.add_argument("--ncs", action="append", default=[])
    p.add_argument("--state", required=True)
    p.add_argument("--scopes", default="state,region,national")
    p.add_argument("--out", required=True)
    p = sub.add_parser("emissions")
    p.add_argument("--min", type=int, default=5)
    p.add_argument("--band", type=float, default=3.0)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--exclude", action="append")
    p.add_argument("--include", action="append")
    p.add_argument("--zip")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == "candidates" and not (a.sic or a.ncs):
        sys.exit("Pass at least one --sic or --ncs.")
    {"codes": cmd_codes, "candidates": cmd_candidates, "emissions": cmd_emissions}[a.cmd](a)


if __name__ == "__main__":
    main()
