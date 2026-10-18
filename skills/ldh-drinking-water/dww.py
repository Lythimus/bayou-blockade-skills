#!/usr/bin/env python3
"""Louisiana public drinking water near a proposed injection well or outfall: LDH water-system records,
public-supply wells and surface intakes, and source-water protection areas rebuilt from the LDEQ SWAP
delineation rules, plus the federal SDWIS record (violations, lead and copper) from EPA Envirofacts.

Run with: uv run -q --no-project python -I dww.py <command> ...
Responses are cached (system data 1 day, joins and traces 7 days; --refresh forces a re-fetch).
Cache: ~/.cache/bayou/ldh-drinking-water/.

LDH's sample, violation and site-visit grids need a reCAPTCHA pass for anonymous users. This script never
requests them. dww_capture.js runs those searches in a visible browser (a person clicks "I'm not a robot" if Google
asks); it saves what the viewer loads, and the commands here read that.

  dww.py health                                   LDH, Envirofacts and NLDI answer; facility index intact
  dww.py systems "<name>" | --parish P | --id LA1089001 [--inactive]
                                                  find water systems (federal SDWIS inventory)
  dww.py system <PWSID>                           LDH header and status gauges, facilities with coordinates,
                                                  sellers and buyers, next sanitary survey, LDH page link
  dww.py violations <PWSID> [--since YYYY-MM-DD]  federal SDWIS violations (default 10 years) + LDH status gauge
  dww.py samples <PWSID> [--analyte TEXT] [--exceed]
                                                  lead/copper 90th percentiles (federal), plus LDH chemical,
                                                  coliform and lead/copper grids captured with dww_capture.js
  dww.py visits <PWSID>                           LDH sanitary surveys and site visits (captured), deficiency
                                                  gauge, next survey due
  dww.py captured [PWSID]                         what dww_capture.js has saved, its date windows and gaps
  dww.py near <lat> <lon> [--radius M] [--all-status] | near --aor aor.geojson
                                                  public-supply wells and intakes near a point or in an AoR,
                                                  with the SWAP default protection radius test
  dww.py downstream <lat> <lon> [--km K] [--buffer M]
                                                  surface intakes downstream of an outfall (USGS NLDI trace),
                                                  flow distance, SWAP critical-area and Mississippi corridor flags
"""
import argparse
import datetime
import difflib
import hashlib
import http.cookiejar
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/bayou/ldh-drinking-water")
DAY = 24 * 3600
UA = "Mozilla/5.0 (bayou-ldh-drinking-water)"
LDH = "https://sdw.ldh.la.gov/"
EF = "https://data.epa.gov/efservice/"
NLDI = "https://api.water.usgs.gov/nldi/linked-data/comid/"
MILE = 1609.344
TNC_RADIUS = 1000 * 0.3048
CRITICAL_M = 5 * MILE
# The Mississippi reference trace starts near Lake Providence and runs to the Gulf; a snapped COMID in it
# means the point is on the mainstem, where SWAP section 5.4.2 makes every downstream intake's SWPA reach it.
MS_REF = (32.80, -91.12)
MS_KM = 1200
# Bayou Lafourche is fed by pumps at Donaldsonville and NHDPlus does not connect it to the river, so an
# NLDI trace from the Mississippi never reaches the Lafourche intakes.
DONALDSONVILLE = (30.1006, -90.9935)
LAFOURCHE_HEAD = 22357447
LAFOURCHE_KM = 250
# 40 CFR 141.80(c). The Lead and Copper Rule Improvements lower the lead action level to 0.010 mg/L
# from 2027-11-01.
ACTION_LEVEL = {"PB90": ("lead", 0.015), "CU90": ("copper", 1.3)}
PWS_TYPE = {"CWS": "community", "NTNCWS": "non-transient non-community", "TNCWS": "transient non-community"}
COMPLIANCE = {"K": "known (unaddressed)", "O": "open", "R": "returned to compliance"}
# SDWIS violation categories that EPA counts as health-based (maximum contaminant level, maximum residual
# disinfectant level, treatment technique); monitoring, reporting and notice categories are not.
HEALTH_BASED = {"MCL", "MRDL", "TT"}
GAUGE = {
    "ViolationsGauge": {"HIGH": "Unresolved Health-Based Violations",
                        "MEDIUM": "Unresolved Non Health-Based Violations", "LOW": "No Unresolved Violations"},
    "DeficienciesGauge": {"HIGH": "Unresolved Significant Deficiencies",
                          "MEDIUM": "Unresolved Minor Deficiencies", "LOW": "No Unresolved Deficiencies"},
}
# Fields kept from Envirofacts WATER_SYSTEM; the rest are the administrator's name, email and phone.
WS_FIELDS = ("pwsid", "pws_name", "pws_activity_code", "pws_deactivation_date", "pws_type_code",
             "primary_source_code", "population_served_count", "service_connections_count", "owner_type_code",
             "is_wholesaler_ind", "source_water_protection_code", "city_name")
CAPTURED = os.path.join(CACHE, "captured")
CAPTURE_PAGES = {"ChemicalGrid": "chem", "LeadAndCopperSummGrid": "chem", "SamplingColiformGrid": "micro",
                 "SamplingNonColiformGrid": "micro", "SamplingMicrobialSummariesGrid": "micro",
                 "Violations": "violations", "SiteVisits": "visits"}
# Only codes seen labelled on the viewer; others print as LDH's bare code.
VISIT_REASON = {"SNSV": "sanitary survey, finished"}
SAMPLES_NOTE = (
    "Routine chemical and coliform results are not in the federal SDWIS extract; they are on the LDH "
    "Drinking Water Viewer, whose sample grids need a reCAPTCHA pass for anonymous users. This script does "
    "not request them; dww_capture.js runs those searches in a visible browser.")
SWAP_NOTE = (
    "SWAP default radius (LDEQ SWAP document section 4.1): 1 mile for community and non-transient "
    "non-community wells, 1,000 ft for transient non-community wells. LDEQ used 1/2 mile for wells screened "
    "below 1,000 ft completed before 1985-11-01 and for TNC wells in the Terrace Aquifer; LDH data has no "
    "screen depth, so those cases cannot be decided here. This is a reconstruction, not LDEQ's delineation: "
    "get the system's source water assessment from the LDEQ Aquifer Evaluation and Protection Unit.")
PLACEHOLDER_IDS = {"0000000", "1234567", "9999999"}
REFRESH = False


class SourceDown(Exception):
    pass


class NotFound(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def ldh_page(pwsid):
    return LDH + "WaterSystem?n0=" + pwsid


# ---------------------------------------------------------------- HTTP

def cache_path(key):
    return os.path.join(CACHE, "http", hashlib.sha1(key.encode()).hexdigest() + ".json")


def cached(key, ttl):
    path = cache_path(key)
    if not REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as fh:
            return True, json.load(fh)
    return False, None


def store(key, data):
    path = cache_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w") as fh:
        json.dump(data, fh)
    os.replace(path + ".part", path)
    return data


def fetch(url, headers=None, opener=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
        return r.read()


def parse_json(raw, what):
    text = raw.strip()
    if not text:
        # LDH answers an over-limit $top with an empty 200; reading it as zero rows would be a silent miss.
        raise SourceDown("%s returned an empty body" % what)
    if text[:1] == b"<":
        m = re.search(rb"<title>([^<]*)", raw, re.I)
        raise SourceDown("%s returned HTML (%s)" % (what, m.group(1).decode(errors="replace").strip() if m else "no title"))
    try:
        return json.loads(raw)
    except ValueError:
        raise SourceDown("%s returned unparseable JSON" % what)


def get_json(url, ttl=DAY):
    hit, data = cached(url, ttl)
    if hit:
        return data
    err = None
    for attempt in range(2):
        if attempt:
            time.sleep(2)
        try:
            data = parse_json(fetch(url), url)
        except urllib.error.HTTPError as e:
            err = "HTTP %d" % e.code
            if e.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = "unreachable (%s)" % getattr(e, "reason", e)
            continue
        except SourceDown as e:
            err = str(e)
            continue
        if isinstance(data, dict) and "error" in data:
            raise SourceDown("%s -> %s" % (url, data["error"]))
        return store(url, data)
    raise SourceDown("%s -> %s" % (url, err))


class Ldh:
    """The LDH viewer's anti-forgery handshake: GET / sets an XSRF-TOKEN cookie that every /sdwis/ call must echo
    in a header. A call without it gets HTTP 500, not 403, so a 500 here usually means the handshake failed."""

    def __init__(self):
        self.opener = None
        self.token = None

    def start(self):
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            fetch(LDH, opener=self.opener, timeout=60)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SourceDown("LDH viewer unreachable (%s)" % getattr(e, "reason", e))
        self.token = next((c.value for c in jar if c.name == "XSRF-TOKEN"), None)
        if not self.token:
            raise SourceDown("LDH viewer set no XSRF-TOKEN cookie; the site's session handshake has changed")

    def get(self, path, ttl=DAY, allow_empty=False):
        url = LDH + path
        hit, data = cached(url, ttl)
        if hit:
            return data
        for attempt in range(2):
            if not self.token or attempt:
                self.start()
            try:
                raw = fetch(url, {"Content-Type": "application/json", "X-XSRF-TOKEN": self.token}, self.opener, 90)
            except urllib.error.HTTPError as e:
                body = e.read()[:2000]
                if e.code == 403 and b"Application-Gateway" in body:
                    # Never retried: each further request extends the gateway's block on this IP.
                    raise SourceDown("LDH's gateway is blocking scripted requests from this IP (HTTP 403). "
                                     "Wait before retrying, or open the LDH page in a browser.")
                if e.code == 500 and not attempt:
                    continue
                if e.code == 500:
                    raise SourceDown("LDH returned HTTP 500 twice with a fresh session for %s; likely a session or "
                                     "filter problem (the XSRF header or a required parameter), not an outage" % path)
                raise SourceDown("LDH %s -> HTTP %d" % (path, e.code))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise SourceDown("LDH unreachable (%s)" % getattr(e, "reason", e))
            if allow_empty and not raw.strip():
                return store(url, None)
            return store(url, parse_json(raw, "LDH " + path))


LDH_S = Ldh()


def n0(pwsid):
    """LDH stores NUMBER0 space-padded to 12 characters and rejects the bare id."""
    return urllib.parse.quote(pwsid.ljust(12), safe="")


def ldh_main(pwsid):
    d = LDH_S.get("sdwis/DashMain?$filter=%s&$count=false&n0=%s" % (
        urllib.parse.quote("NUMBER0 eq '%s'" % pwsid.ljust(12), safe=""), n0(pwsid)))
    rows = d.get("value") if isinstance(d, dict) else None
    if rows is None:
        raise SourceDown("LDH DashMain answered without a value list")
    return rows[0] if rows else None


def ldh_gauge(widget, pwsid):
    limit = "ViolationAgeLimit" if widget == "ViolationsGauge" else "DeficiencyAgeLimit"
    d = LDH_S.get("sdwis/%s?$skip=0&$top=1&n0=%s&%s=0&wv=p" % (widget, n0(pwsid), limit))
    v = d.get("Value") if isinstance(d, dict) else None
    return {"value": v, "label": GAUGE[widget].get(v, v)}


def ldh_next_survey(pwsid):
    # A system with no survey scheduled (often an inactive one) gets an empty body, not null.
    d = LDH_S.get("sdwis/NxtSanSurveyDueDt?number0=%s&wv=p" % n0(pwsid), allow_empty=True)
    return d[:10] if isinstance(d, str) else None


def ldh_lookup(name):
    rows = LDH_S.get("LookUp/" + name, ttl=7 * DAY)
    if not isinstance(rows, list) or not rows:
        raise SourceDown("LDH LookUp/%s returned no rows" % name)
    out = {}
    for r in rows:
        # Code lists come as {code, text}; plain lists such as Counties as {value}.
        code = r.get("code", r.get("value"))
        out.setdefault(str(code).strip(), (r.get("text") or code).strip())
    return out


def ef(*path, ttl=DAY):
    parts = [urllib.parse.quote(str(p), safe="") for p in path]
    rows = get_json(EF + "/".join(parts) + "/JSON", ttl)
    if not isinstance(rows, list):
        raise SourceDown("Envirofacts %s answered %r" % ("/".join(path), str(rows)[:200]))
    # Envirofacts caps an unpaged answer at 10,000 rows without saying so.
    if len(rows) >= 10000:
        raise SourceDown("Envirofacts %s hit the 10,000-row cap; narrow the query" % "/".join(path))
    return rows


def water_system(pwsid, ttl=DAY):
    rows = ef("WATER_SYSTEM", "PWSID", pwsid, ttl=ttl)
    return {k: rows[0].get(k) for k in WS_FIELDS} if rows else None


def norm_pwsid(s):
    s = s.strip().upper().replace(" ", "")
    if re.fullmatch(r"\d{7}", s):
        s = "LA" + s
    if not re.fullmatch(r"LA\d{7}", s):
        raise ValueError("PWSID must look like LA1089001 (or the 7 digits)")
    return s


def d10(s):
    return (s or "")[:10]


# ---------------------------------------------------------------- facility index

def load_index():
    with open(os.path.join(HERE, "facilities.json")) as fh:
        idx = json.load(fh)
    keys = ["id", "ident", "name", "status", "type", "availability", "water", "lat", "lon"]
    rows = []
    for r in idx["rows"]:
        f = dict(zip(keys, r))
        # LDH keeps example and test records ("GWR 4LOG EXAMPLE", "TEST INTAKE") under dummy system numbers.
        if (f["ident"] or "")[:7] in PLACEHOLDER_IDS:
            continue
        m = re.match(r"(\d{7})-\d{3}", f["ident"] or "")
        f["pwsid"] = "LA" + m.group(1) if m else None
        rows.append(f)
    return idx, rows


def index_age_days(idx):
    return (datetime.date.today() - datetime.date.fromisoformat(idx["pulled"])).days


# ---------------------------------------------------------------- geometry

def dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1, math.sqrt(a)))


def seg_project(lat, lon, a, b):
    """Distance from the point to segment a-b ([lon, lat] each) and the fraction along it, in local metres."""
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy), t


def edges(r):
    return zip(r, r[1:] + r[:1])


def inside(p, rings):
    """Even-odd test across all rings, so holes come out right without classifying them."""
    x, y = p[0], p[1]
    c = False
    for r in rings:
        for a, b in edges(r):
            if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                c = not c
    return c


def geojson_polys(path):
    """Each polygon in a GeoJSON file as a list of [lon, lat] rings."""
    try:
        with open(path) as fh:
            g = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError("cannot read %s: %s" % (path, e))
    feats = g["features"] if g.get("type") == "FeatureCollection" else [
        g if g.get("type") == "Feature" else {"geometry": g}]
    polys = []
    for f in feats:
        geom = f.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys.append(geom["coordinates"])
        elif geom.get("type") == "MultiPolygon":
            polys.extend(geom["coordinates"])
    if not polys:
        raise ValueError("%s has no Polygon or MultiPolygon geometry; for a point use near <lat> <lon>" % path)
    return polys


def poly_distance(lat, lon, polys):
    """0 inside any polygon, else metres to the nearest edge."""
    if any(inside((lon, lat), rings) for rings in polys):
        return 0.0
    return min(seg_project(lat, lon, a, b)[0] for rings in polys for r in rings for a, b in zip(r, r[1:]))


# ---------------------------------------------------------------- NLDI traces

def snap(lat, lon):
    d = get_json(NLDI + "position?f=json&coords=" + urllib.parse.quote("POINT(%r %r)" % (lon, lat)), 7 * DAY)
    feats = d.get("features") or []
    if not feats:
        raise NotFound("NLDI found no NHDPlus flowline at %s,%s" % (lat, lon))
    return int(feats[0]["properties"]["comid"])


def flowlines(comid, nav, km):
    d = get_json(NLDI + "%d/navigation/%s/flowlines?f=json&distance=%d" % (comid, nav, km), 7 * DAY)
    feats = d.get("features")
    if not feats:
        raise SourceDown("NLDI %s trace from COMID %d returned no flowlines" % (nav, comid))
    return [(int(f["properties"]["nhdplus_comid"]), f["geometry"]["coordinates"]) for f in feats]


class Line:
    """An ordered downstream-mainstem trace as one polyline with cumulative along-channel metres."""

    def __init__(self, feats):
        self.v, self.a, self.comid_at = [], [], []
        for comid, coords in feats:
            for i, c in enumerate(coords):
                if self.v and i == 0 and c == self.v[-1]:
                    continue
                if self.v:
                    self.a.append(self.a[-1] + dist_m(self.v[-1][1], self.v[-1][0], c[1], c[0]))
                else:
                    self.a.append(0.0)
                self.v.append(c)
                self.comid_at.append(comid)
        self.comids = {c for c, _ in feats}

    def locate(self, lat, lon, max_m=None):
        """(distance to the line, along-channel metres of the nearest point), or None beyond max_m."""
        best = None
        pad = (max_m or 5e4) / 90000.0
        for i in range(len(self.v) - 1):
            a, b = self.v[i], self.v[i + 1]
            if max_m is not None and (min(a[0], b[0]) - pad > lon or max(a[0], b[0]) + pad < lon
                                      or min(a[1], b[1]) - pad > lat or max(a[1], b[1]) + pad < lat):
                continue
            d, t = seg_project(lat, lon, a, b)
            if best is None or d < best[0]:
                best = (d, self.a[i] + t * (self.a[i + 1] - self.a[i]))
        if best is None or (max_m is not None and best[0] > max_m):
            return None
        return best


def near_lines(feats, lat, lon, max_m):
    best = None
    pad = max_m / 90000.0
    for _, coords in feats:
        for a, b in zip(coords, coords[1:]):
            if (min(a[0], b[0]) - pad > lon or max(a[0], b[0]) + pad < lon
                    or min(a[1], b[1]) - pad > lat or max(a[1], b[1]) + pad < lat):
                continue
            d = seg_project(lat, lon, a, b)[0]
            if best is None or d < best:
                best = d
    return best if best is not None and best <= max_m else None


def mississippi():
    feats = flowlines(snap(*MS_REF), "DM", MS_KM)
    # The reference point may snap to a short tributary reach before the river.
    return Line(feats[1:])


def mississippi_comids():
    return mississippi().comids


# ---------------------------------------------------------------- commands

def cmd_health(a):
    checks = []

    def check(name, fn):
        try:
            ok, detail = fn()
        except (SourceDown, NotFound, KeyError, ValueError, TypeError) as e:
            ok, detail = False, str(e)
        checks.append({"check": name, "ok": ok, "detail": detail})

    def ldh_main_ok():
        m = ldh_main("LA1089001")
        return bool(m) and "ST CHARLES" in m["NAME"], "%s, population %s" % (m["NAME"].strip(), m["D_POPULATION_COUNT"])

    def gauge_ok():
        g = ldh_gauge("ViolationsGauge", "LA1089001")
        return g["value"] in GAUGE["ViolationsGauge"], "%s (%s)" % (g["value"], g["label"])

    def lookup_ok():
        n = len(ldh_lookup("Counties"))
        return n >= 64, "%d parishes" % n

    def ef_ok():
        w = water_system("LA1089001")
        return bool(w) and w["population_served_count"] > 0, "%s, population %s" % (w["pws_name"], w["population_served_count"])

    def nldi_ok():
        c = snap(29.995, -90.41)
        return c == 22799303, "Norco snaps to COMID %d" % c

    def ms_ok():
        s = mississippi_comids()
        return len(s) > 100 and 22799303 in s, "%d mainstem COMIDs; Norco reach included: %s" % (len(s), 22799303 in s)

    def index_ok():
        idx, rows = load_index()
        ids = {r["id"] for r in rows}
        joined = sum(1 for r in rows if r["pwsid"])
        coords = sum(1 for r in rows if r["lat"] is not None)
        return (len(ids) == len(rows) and joined / len(rows) > 0.99,
                "%d wells/intakes, %d unique ids, %d join to a PWSID, %d with coordinates; pulled %s (%d days ago)"
                % (len(rows), len(ids), joined, coords, idx["pulled"], index_age_days(idx)))

    check("LDH DashMain (session + XSRF)", ldh_main_ok)
    check("LDH ViolationsGauge", gauge_ok)
    check("LDH LookUp/Counties", lookup_ok)
    check("Envirofacts WATER_SYSTEM", ef_ok)
    check("NLDI position", nldi_ok)
    check("Mississippi reference trace", ms_ok)
    check("facility index", index_ok)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def cmd_systems(a):
    if a.id:
        pwsid = norm_pwsid(a.id)
        w = water_system(pwsid)
        rows = [w] if w else []
        how = "PWSID %s" % pwsid
    elif a.parish:
        p = re.sub(r"\s+parish$", "", a.parish.strip(), flags=re.I)
        # GEOGRAPHIC_AREA spells parishes "St. Charles Parish"; the comparison is case-sensitive.
        p = " ".join({"st": "St.", "st.": "St.", "ste": "Ste.", "ste.": "Ste."}.get(w.lower(), w.capitalize())
                     for w in p.split())
        got = ef("GEOGRAPHIC_AREA", "PRIMACY_AGENCY_CODE", "LA", "COUNTY_SERVED", "CONTAINING", p, "WATER_SYSTEM")
        seen, rows = set(), []
        for r in got:
            if r["pwsid"] not in seen:
                seen.add(r["pwsid"])
                rows.append({k: r.get(k) for k in WS_FIELDS} | {"county_served": r.get("county_served")})
        how = "parish containing %r" % p
    elif a.name:
        got = ef("WATER_SYSTEM", "PRIMACY_AGENCY_CODE", "LA", "PWS_NAME", "CONTAINING", a.name.strip().upper())
        rows = [{k: r.get(k) for k in WS_FIELDS} for r in got]
        how = "name containing %r" % a.name.strip().upper()
    else:
        raise ValueError("give a name, --parish or --id")
    total = len(rows)
    if not total:
        raise NotFound("no water systems match %s" % how)
    if not a.inactive:
        rows = [r for r in rows if r["pws_activity_code"] == "A"]
    rows.sort(key=lambda r: -(r["population_served_count"] or 0))
    return {"query": how, "matched": total, "shown": len(rows), "inactive_included": bool(a.inactive), "systems": rows}


def facilities_for(pwsid, rows):
    return [r for r in rows if r["pwsid"] == pwsid]


def cmd_system(a):
    pwsid = norm_pwsid(a.pwsid)
    idx, rows = load_index()
    w = water_system(pwsid)
    main = ldh_main(pwsid)
    if not w and not main:
        known = sorted({r["pwsid"] for r in rows if r["pwsid"]})
        near = difflib.get_close_matches(pwsid, known, 5, 0.8)
        raise NotFound("%s is not in LDH or federal SDWIS.%s" % (
            pwsid, " Near ids in the facility index: " + ", ".join(near) if near else ""))
    out = {"pwsid": pwsid, "ldh_page": ldh_page(pwsid), "federal": w}
    if main:
        out["ldh"] = {"name": main["NAME"].strip(), "status": main["ACTIVITY_STATUS_CD"],
                      "parish": main["D_PRIN_CNTY_SVD_NM"].strip(), "fed_type": main["D_PWS_FED_TYPE_CD"].strip(),
                      "primary_source": main["D_FED_PRIM_SRC_CD"].strip(), "population": main["D_POPULATION_COUNT"],
                      "connections": main["SVC_CONNECT_CNT"],
                      "source_pct": {"surface": main["SURF_WTR_RATIO"], "surface_purchased": main["SURF_WTR_PUR_RATIO"],
                                     "ground": main["GRND_WTR_RATIO"], "ground_purchased": main["GRND_WTR_PUR_RATIO"],
                                     "gwudi": main["GRND_WTR_UDI_RATIO"]}}
        out["violations_gauge"] = ldh_gauge("ViolationsGauge", pwsid)
        out["deficiencies_gauge"] = ldh_gauge("DeficienciesGauge", pwsid)
        out["next_sanitary_survey"] = ldh_next_survey(pwsid)
    out["sources"] = facilities_for(pwsid, rows)
    out["index_pulled"] = idx["pulled"]
    fac = ef("WATER_SYSTEM_FACILITY", "PWSID", pwsid)
    out["purchases"] = [{"seller": f["seller_pwsid"], "seller_name": f["seller_pws_name"], "facility": f["facility_name"],
                         "active": f["facility_activity_code"] == "A"} for f in fac if f.get("seller_pwsid")]
    buyers = ef("WATER_SYSTEM_FACILITY", "SELLER_PWSID", pwsid)
    out["buyers"] = sorted({(b["pwsid"], b["facility_activity_code"] == "A") for b in buyers})
    out["federal_facility_count"] = len(fac)
    return out


def cmd_violations(a):
    pwsid = norm_pwsid(a.pwsid)
    since = a.since or (datetime.date.today() - datetime.timedelta(days=3652)).isoformat()
    w = water_system(pwsid)
    if not w:
        raise NotFound("%s is not in federal SDWIS (Envirofacts WATER_SYSTEM); try: systems --id %s" % (pwsid, pwsid))
    vt, an = ldh_lookup("ViolationTypes"), ldh_lookup("AnalyteCodes")
    rows = {}
    for v in ef("VIOLATION", "PWSID", pwsid):
        # The extract repeats a violation once per row it joins to, so the same id can appear several times.
        rows.setdefault(v["violation_id"], {
            "begin": d10(v["compl_per_begin_date"]), "end": d10(v["compl_per_end_date"]),
            "category": v["violation_category_code"], "health_based": v["is_health_based_ind"] == "Y",
            "code": v["violation_code"], "type": vt.get(str(v["violation_code"]).strip(), ""),
            "contaminant": an.get(str(v["contaminant_code"]).strip(), v["contaminant_code"]),
            "status": COMPLIANCE.get(v["compliance_status_code"], v["compliance_status_code"]),
            "rtc_date": d10(v["rtc_date"]), "measure": v["viol_measure"], "unit": v["unit_of_measure"],
            "pn_tier": v["public_notification_tier"], "id": v["violation_id"], "table": "VIOLATION"})
    # Neither federal table is complete: VIOLATION lacks some older violations that the enforcement view
    # keeps, and the enforcement view lacks recent ones. The view has no status or health-based flag.
    for v in ef("SDW_VIOL_ENFORCEMENT", "PWSID", pwsid):
        if v["vioid"] in rows:
            continue
        rows[v["vioid"]] = {
            "begin": d10(v["compperbegindate"]), "end": d10(v["compperenddate"]), "category": v["vtype"],
            "health_based": v["vtype"] in HEALTH_BASED, "code": v["vcode"], "type": v["vname"] or "",
            "contaminant": v["cname"] or v["ccode"], "status": "status not reported", "rtc_date": "",
            "measure": None, "unit": None, "pn_tier": None, "id": v["vioid"], "table": "SDW_VIOL_ENFORCEMENT"}
    # A violation still open is kept whatever its age: dropping it would make the system look clean.
    rows = [r for r in rows.values() if r["begin"] >= since or r["status"] in (COMPLIANCE["K"], COMPLIANCE["O"])]
    rows.sort(key=lambda r: r["begin"], reverse=True)
    out = {"pwsid": pwsid, "name": w["pws_name"], "since": since, "violations": rows,
           "health_based": sum(r["health_based"] for r in rows), "ldh_page": ldh_page(pwsid),
           "state": state_violations(pwsid), "capture": capture_cmd(pwsid, ["violations"], since)}
    try:
        out["ldh_gauge"] = ldh_gauge("ViolationsGauge", pwsid)
    except SourceDown as e:
        out["ldh_gauge"] = {"value": None, "label": "unavailable: %s" % e}
    return out


def cmd_samples(a):
    pwsid = norm_pwsid(a.pwsid)
    w = water_system(pwsid)
    if not w:
        raise NotFound("%s is not in federal SDWIS (Envirofacts WATER_SYSTEM)" % pwsid)
    periods = {s["sample_id"]: (d10(s["sampling_start_date"]), d10(s["sampling_end_date"]))
               for s in ef("LCR_SAMPLE", "PWSID", pwsid)}
    lcr = []
    for r in ef("LCR_SAMPLE_RESULT", "PWSID", pwsid):
        name, al = ACTION_LEVEL.get(r["contaminant_code"], (r["contaminant_code"], None))
        start, end = periods.get(r["sample_id"], ("", ""))
        lcr.append({"period_start": start, "period_end": end, "analyte": name + " 90th percentile",
                    "value": r["sample_measure"], "unit": r["unit_of_measure"], "action_level": al,
                    "over_action_level": al is not None and r["sample_measure"] is not None and r["sample_measure"] > al,
                    "sample_id": r["sample_id"]})
    lcr.sort(key=lambda r: (r["period_end"], r["analyte"]), reverse=True)
    grids = ["ChemicalGrid", "LeadAndCopperSummGrid", "SamplingColiformGrid", "SamplingNonColiformGrid",
             "SamplingMicrobialSummariesGrid"]
    cap = captured(pwsid, grids)
    other = {g: plain_rows(cap[g]["rows"]) for g in grids[1:] if g in cap and g != "SamplingColiformGrid"}
    return {"pwsid": pwsid, "name": w["pws_name"], "lcr": lcr, "ldh_page": ldh_page(pwsid), "note": SAMPLES_NOTE,
            "chemical": chem_rows(cap, a.analyte, a.exceed) if "ChemicalGrid" in cap else None,
            "chemical_filter": {"analyte": a.analyte, "exceed_only": a.exceed}, "other_grids": other,
            "coliform": micro_summary(cap) if "SamplingColiformGrid" in cap else None,
            "searches": capture_summary(cap), "capture": capture_cmd(pwsid, ["chem", "micro"])}


def capture_cmd(pwsid, pages, since=None):
    return "node %s --pws %s --pages %s%s" % (os.path.join(HERE, "dww_capture.js"), pwsid, ",".join(sorted(set(pages))),
                                            " --since %s" % since if since else "")


RESULT_CAP = 4500


def captured(pwsid, widgets):
    """Rows dww_capture.js saved for these grids, merged across searches, with each search's date window and
    whether every page of it loaded. A search with pages missing is reported, never treated as complete."""
    out = {}
    folder = os.path.join(CAPTURED, pwsid)
    for w in widgets:
        rows, seen, wins = [], set(), []
        for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if not f.startswith(w + "__") or not f.endswith(".json"):
                continue
            with open(os.path.join(folder, f)) as fh:
                rec = json.load(fh)
            # Unique rows, not a page sum: changing the page size mid-search leaves overlapping pages behind.
            mine, results = set(), 0
            for page in rec["pages"].values():
                for r in page:
                    k = json.dumps(r, sort_keys=True)
                    if k not in mine:
                        results += len(r["Results"]) if isinstance(r.get("Results"), list) else 1
                    mine.add(k)
                    if k not in seen:
                        seen.add(k)
                        rows.append(r)
            have = len(mine)
            # LDH stops a search at 5,000 result rows before sorting and counts only what it kept, so a
            # window near that total is a cut-off sample of its dates even when every page loaded.
            # With pages missing, the loaded rows' results per row stand in for the rest.
            n = rec.get("count")
            capped = (results * n / have if have and isinstance(n, int) and n > have else results) >= RESULT_CAP
            wins.append({"bd": rec.get("bd"), "ed": rec.get("ed"), "rows": have, "count": rec.get("count"),
                         "capped": capped,
                         "complete": not capped and (rec.get("count") is None or have >= rec["count"]),
                         "captured_at": rec["captured_at"][:16].replace("T", " ") + "Z", "query": rec["query"]})
        for x in wins:
            x["covered"] = not x["complete"] and tiled(x, [y for y in wins if y["complete"] and y["query"] != x["query"]])
        if wins:
            out[w] = {"rows": rows, "searches": sorted(wins, key=lambda x: x["bd"] or "")}
    return out


def tiled(win, complete):
    """Whether complete searches cover every day of this window. The viewer stops at 1,000 rows per search,
    so dww_capture.js re-searches a fuller window as shorter ones and the long window stays partial."""
    if not win["bd"] or not win["ed"]:
        return False
    day = datetime.timedelta(days=1)
    cur, end = datetime.date.fromisoformat(win["bd"]), datetime.date.fromisoformat(win["ed"])
    spans = sorted((datetime.date.fromisoformat(y["bd"]), datetime.date.fromisoformat(y["ed"]))
                   for y in complete if y["bd"] and y["ed"])
    for b, e in spans:
        if b > cur:
            break
        if e >= cur:
            cur = e + day
        if cur > end:
            return True
    return cur > end


def capture_summary(cap):
    return {w: [{k: x[k] for k in ("bd", "ed", "rows", "count", "complete", "capped", "covered", "captured_at")} for x in c["searches"]]
            for w, c in cap.items()}


def s10(v):
    return (v or "")[:10]


def strip(v):
    return v.strip() if isinstance(v, str) else v


def state_violations(pwsid):
    cap = captured(pwsid, ["Violations"]).get("Violations")
    if not cap:
        return None
    rows = [{"determined": s10(v.get("DETERMINATION_DATE")), "begin": s10(v.get("STATE_PRD_BEGIN_DT")),
             "end": s10(v.get("STATE_PRD_END_DT")), "code": strip(v.get("TMNVTYPE_TYPE_CODE")),
             "type": strip(v.get("TMNVTYPE_NAME")), "analyte": strip(v.get("TSAANLYT_NAME")),
             "facility": strip(v.get("ST_ASGN_IDENT_CD")), "rtc": strip(v.get("RTC")), "id": v.get("TMNVIOL_IS_NUMBER")}
            for v in cap["rows"]]
    rows.sort(key=lambda r: r["begin"], reverse=True)
    return {"rows": rows, "searches": capture_summary({"Violations": cap})["Violations"]}


def over_mcl(v):
    # Only "N/A" has been seen live; any value that is not a plain no counts, so an unfamiliar spelling of yes
    # is shown rather than filtered away.
    return str(strip(v) or "").upper() not in ("", "N/A", "NA", "N", "NO", "FALSE", "NONE")


def chem_rows(cap, analyte, exceed):
    out = []
    for smp in cap.get("ChemicalGrid", {}).get("rows", []):
        for r in smp.get("Results") or []:
            name = strip(r.get("AnalyteName")) or ""
            if analyte and analyte.lower() not in name.lower() and analyte != strip(r.get("AnalyteCode")):
                continue
            if exceed and not over_mcl(r.get("ExceedsMCL")):
                continue
            out.append({"collected": s10(smp.get("CollectionDate")), "type": strip(smp.get("Type")),
                        "point": strip(smp.get("SamplePoint")), "location": strip(smp.get("Location")),
                        "facility": strip(smp.get("FacilityName")), "lab": strip(smp.get("LaboratoryId")),
                        "lab_sample": strip(smp.get("SampleLabId")), "analyte": name, "code": strip(r.get("AnalyteCode")),
                        "less_than": r.get("ResultLessInd") == "Y", "value": r.get("ResultMeasure"),
                        "unit": strip(r.get("ResultMeasureCode")), "result": strip(r.get("Detection")),
                        "mcl": strip(r.get("MaximumContaminantLevel")), "exceeds_mcl": strip(r.get("ExceedsMCL")),
                        "method": strip(r.get("Method"))})
    out.sort(key=lambda r: (r["collected"], r["analyte"]), reverse=True)
    return out


def micro_summary(cap):
    """Coliform samples are presence/absence; a positive is the finding, so all are counted and positives listed."""
    rows = cap.get("SamplingColiformGrid", {}).get("rows", [])
    tally, positives = {}, []
    for smp in rows:
        for r in smp.get("Results") or []:
            name = strip(r.get("AnalyteName")) or strip(r.get("AnalyteCode"))
            t = tally.setdefault(name, {"tested": 0, "present": 0})
            t["tested"] += 1
            if strip(r.get("PresenceIndicator")) == "P":
                t["present"] += 1
                positives.append({"collected": s10(smp.get("CollectionDate")), "type": strip(smp.get("Type")),
                                  "point": strip(smp.get("SamplePoint")), "location": strip(smp.get("Location")),
                                  "analyte": name, "count": strip(r.get("MicrobialResultCount")),
                                  "chlorine_total": smp.get("TotalChlorineResidualMeasure"),
                                  "chlorine_free": smp.get("FreeChlorineResidualMeasure"), "lab": strip(smp.get("LaboratoryId"))})
    positives.sort(key=lambda r: r["collected"], reverse=True)
    return {"samples": len(rows), "by_analyte": tally, "positives": positives}


def plain_rows(rows):
    """Grids whose layout has not been checked against a live response are shown field by field, as LDH sent them."""
    keep = []
    for r in rows:
        keep.append({k: (s10(v) if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\dT", v) else strip(v))
                     for k, v in r.items() if not isinstance(v, (list, dict)) and not k.endswith(("_IS_NUMBER", "_ST_CODE"))})
    return keep


def cmd_visits(a):
    pwsid = norm_pwsid(a.pwsid)
    cap = captured(pwsid, ["SiteVisits"]).get("SiteVisits")
    out = {"pwsid": pwsid, "ldh_page": ldh_page(pwsid), "capture": capture_cmd(pwsid, ["visits"]), "visits": None}
    if cap:
        out["visits"] = sorted(({"date": s10(v.get("VISIT_DATE")), "reason": strip(v.get("REASON_CD")),
                                 "reason_text": VISIT_REASON.get(strip(v.get("REASON_CD")), ""),
                                 "severity": strip(v.get("Severity")), "id": v.get("TINVISIT_IS_NUMBER")}
                                for v in cap["rows"]), key=lambda v: v["date"], reverse=True)
        out["searches"] = capture_summary({"SiteVisits": cap})["SiteVisits"]
    try:
        out["deficiency_gauge"] = ldh_gauge("DeficienciesGauge", pwsid)
        out["next_survey"] = ldh_next_survey(pwsid)
    except SourceDown as e:
        out["deficiency_gauge"], out["next_survey"] = {"value": None, "label": "unavailable: %s" % e}, None
    return out


def cmd_captured(a):
    root = CAPTURED
    ids = [norm_pwsid(a.pwsid)] if a.pwsid else sorted(os.listdir(root)) if os.path.isdir(root) else []
    return {"systems": {i: capture_summary(captured(i, list(CAPTURE_PAGES))) for i in ids}, "folder": root}



def system_info(pwsids):
    """Name, type and population per PWSID from federal SDWIS, cached a week because near/downstream fan out."""
    out = {}
    for p in sorted(pwsids):
        try:
            out[p] = water_system(p, ttl=7 * DAY)
        except SourceDown as e:
            out[p] = {"error": str(e)}
    return out


def retired(info, pwsid):
    """LDH leaves a facility active after its system is retired or merged (St. Charles WD2's intake is still
    'A' under an inactive LA1089002), so the system's own status decides."""
    s = info.get(pwsid) or {}
    return bool(s.get("pws_activity_code")) and s["pws_activity_code"] != "A"


def swap_radius(info):
    if info and info.get("pws_type_code") == "TNCWS":
        return TNC_RADIUS, "TNC 1,000 ft"
    return MILE, "1 mile"


def cmd_near(a):
    idx, rows = load_index()
    statuses = None if a.all_status else {"A"}
    polys = geojson_polys(a.aor) if a.aor else None
    hits = []
    for r in rows:
        if r["lat"] is None or (statuses and r["status"] not in statuses):
            continue
        if polys:
            d = poly_distance(r["lat"], r["lon"], polys)
            # A well outside the AoR still matters when its 1-mile SWPA reaches into it.
            if d > MILE:
                continue
        else:
            d = dist_m(a.lat, a.lon, r["lat"], r["lon"])
            if d > a.radius:
                continue
        hits.append(dict(r, distance_m=round(d)))
    info = system_info({h["pwsid"] for h in hits if h["pwsid"]})
    dropped = [] if a.all_status else [h for h in hits if retired(info, h["pwsid"])]
    hits = [h for h in hits if h not in dropped]
    for h in hits:
        s = info.get(h["pwsid"]) or {}
        h["system"] = s.get("pws_name")
        h["system_type"] = s.get("pws_type_code")
        h["population"] = s.get("population_served_count")
        if h["type"] == "WL":
            rad, label = swap_radius(s)
            h["swap_radius"] = label
            h["in_swap_default"] = h["distance_m"] <= rad
            h["in_aor"] = bool(polys) and h["distance_m"] == 0
    hits.sort(key=lambda h: h["distance_m"])
    found = {h["pwsid"] for h in hits}
    missing = [r for r in rows if r["pwsid"] in found and r["lat"] is None
               and (not statuses or r["status"] in statuses)]
    return {"mode": "aor" if polys else "point", "aor": a.aor, "lat": a.lat, "lon": a.lon,
            "radius_m": None if polys else a.radius, "statuses": sorted(statuses) if statuses else "all",
            "facilities": hits, "no_coordinates": missing, "index_pulled": idx["pulled"],
            "inactive_system_dropped": [h["ident"] for h in dropped],
            "index_age_days": index_age_days(idx), "note": SWAP_NOTE}


def cmd_downstream(a):
    idx, rows = load_index()
    intakes = [r for r in rows if r["type"] == "IN" and r["lat"] is not None and (a.all_status or r["status"] == "A")]
    comid = snap(a.lat, a.lon)
    ms = mississippi()
    ms_hit = ms.locate(a.lat, a.lon, max_m=1000)
    mainstem = comid in ms.comids or a.mississippi
    if a.mississippi and not ms_hit:
        raise ValueError("--mississippi: the point is more than 1 km from the Mississippi mainstem")
    km = MS_KM if mainstem else a.km
    line = ms if mainstem else Line(flowlines(comid, "DM", km))
    # The trace includes all of the starting reach, which can begin kilometres above the point.
    snap_m, s0 = line.locate(a.lat, a.lon)
    river_m = None if mainstem or not ms_hit else round(ms_hit[0])
    found = []
    for r in intakes:
        hit = line.locate(r["lat"], r["lon"], a.buffer)
        if hit and hit[1] >= s0:
            km_down = (hit[1] - s0) / 1000.0
            found.append(dict(r, route="mainstem", flow_km=round(km_down, 1), off_line_m=round(hit[0]),
                              critical_area=km_down * 1000 <= CRITICAL_M))
    seen = {f["id"] for f in found}
    dd_start = line.comid_at[min(range(len(line.v)), key=lambda i: abs(line.a[i] - s0))]
    branches = [(c, g) for c, g in flowlines(dd_start, "DD", km) if c not in line.comids]
    for r in intakes:
        if r["id"] in seen:
            continue
        d = near_lines(branches, r["lat"], r["lon"], a.buffer)
        if d is not None:
            found.append(dict(r, route="diverging branch", flow_km=None, off_line_m=round(d), critical_area=None,
                              straight_km=round(dist_m(a.lat, a.lon, r["lat"], r["lon"]) / 1000, 1)))
            seen.add(r["id"])
    lafourche = None
    dv = line.locate(*DONALDSONVILLE, max_m=2500) if mainstem else None
    if dv and dv[1] >= s0:
        lafourche = round((dv[1] - s0) / 1000.0, 1)
        lf = flowlines(LAFOURCHE_HEAD, "DD", LAFOURCHE_KM)
        for r in intakes:
            if r["id"] in seen:
                continue
            d = near_lines(lf, r["lat"], r["lon"], a.buffer)
            if d is not None:
                found.append(dict(r, route="Bayou Lafourche (pumped diversion)", flow_km=None, off_line_m=round(d),
                                  critical_area=None))
                seen.add(r["id"])
    info = system_info({f["pwsid"] for f in found if f["pwsid"]})
    dropped = [] if a.all_status else [f for f in found if retired(info, f["pwsid"])]
    found = [f for f in found if f not in dropped]
    info = {p: s for p, s in info.items() if a.all_status or not retired(info, p)}
    buyers = {}
    for p in sorted(info):
        try:
            buyers[p] = sorted({b["pwsid"] for b in ef("WATER_SYSTEM_FACILITY", "SELLER_PWSID", p, ttl=7 * DAY)
                                if b["facility_activity_code"] == "A"})
        except SourceDown:
            buyers[p] = None
    binfo = system_info({b for bl in buyers.values() if bl for b in bl} - set(info))
    buyers = {p: [b for b in bl if not retired(binfo, b)] if bl is not None else None for p, bl in buyers.items()}
    for f in found:
        s = info.get(f["pwsid"]) or {}
        f["system"] = s.get("pws_name")
        f["population"] = s.get("population_served_count")
        f["buyers"] = buyers.get(f["pwsid"])
    systems = {}
    for p, s in info.items():
        bl = buyers.get(p) or []
        bpop = sum((binfo.get(b) or info.get(b) or {}).get("population_served_count") or 0 for b in bl if b != p)
        systems[p] = {"name": (s or {}).get("pws_name"), "population": (s or {}).get("population_served_count"),
                      "buyers": [{"pwsid": b, "name": (binfo.get(b) or info.get(b) or {}).get("pws_name"),
                                  "population": (binfo.get(b) or info.get(b) or {}).get("population_served_count")}
                                 for b in bl if b != p],
                      "buyer_population": bpop}
    # A buyer can also own an intake on the list (Belle Chasse buys from two sellers), so count each system once.
    pops = {p: (s or {}).get("population_served_count") or 0 for p, s in info.items()}
    for s in systems.values():
        for b in s["buyers"]:
            pops.setdefault(b["pwsid"], b["population"] or 0)
    order = {"mainstem": 0, "diverging branch": 1}
    found.sort(key=lambda f: (order.get(f["route"], 2), f["flow_km"] if f["flow_km"] is not None else 1e9))
    return {"lat": a.lat, "lon": a.lon, "comid": comid, "snap_m": round(snap_m), "mississippi_mainstem": mainstem,
            "mississippi_nearby_m": river_m, "forced": bool(a.mississippi) and comid not in ms.comids,
            "km": km, "buffer_m": a.buffer, "traced_km": round((line.a[-1] - s0) / 1000, 1),
            "lafourche_via_donaldsonville_km": lafourche, "intakes": found, "systems": systems,
            "inactive_system_dropped": [f["ident"] for f in dropped],
            "population_total": sum(pops.values()), "systems_counted": len(pops), "index_pulled": idx["pulled"]}


# ---------------------------------------------------------------- output

def p(s=""):
    print(s)


def fmt_pop(n):
    return "{:,}".format(n) if isinstance(n, (int, float)) else "?"


def show_searches(wins, grid):
    for x in wins:
        p("  %s window %s..%s: %d%s rows, captured %s%s" % (
            grid, x["bd"] or "?", x["ed"] or "?", x["rows"], "" if x["count"] is None else " of %d" % x["count"],
            x["captured_at"], "" if x["complete"] else
            "  (too large for one search; covered in full by the shorter windows)" if x.get("covered") else
            "  CUT OFF: LDH stopped this search at 5,000 results; dates in it may be missing" if x.get("capped") else
            "  INCOMPLETE: not every page was loaded in the browser"))
    p("  Only these date windows were searched; nothing outside them is implied.")


def show(cmd, r):
    if cmd == "health":
        p("health: %s" % ("OK" if r["ok"] else "PROBLEM"))
        for c in r["checks"]:
            p("  %-32s %s  %s" % (c["check"], "ok " if c["ok"] else "FAIL", c["detail"]))
        return
    if cmd == "systems":
        p("%d systems match %s%s" % (r["matched"], r["query"], "" if r["inactive_included"] else
                                     "; %d active shown (--inactive for all)" % r["shown"]))
        for s in r["systems"]:
            p("  %s  %-44s %-6s %-2s %s pop %s%s" % (s["pwsid"], (s["pws_name"] or "")[:44], s["pws_type_code"],
                                                    s["primary_source_code"], s["pws_activity_code"],
                                                    fmt_pop(s["population_served_count"]),
                                                    "  (" + s["county_served"] + ")" if s.get("county_served") else ""))
        p("Source: federal SDWIS inventory (EPA Envirofacts), which follows LDH's data by about a quarter.")
        return
    if cmd == "system":
        l, w = r.get("ldh"), r.get("federal") or {}
        p("%s  %s" % (r["pwsid"], (l or {}).get("name") or w.get("pws_name")))
        if l:
            p("  LDH: status %s, %s, parish %s, source %s, population %s, connections %s" % (
                l["status"], l["fed_type"], l["parish"], l["primary_source"], fmt_pop(l["population"]),
                fmt_pop(l["connections"])))
            sp = {k: v for k, v in l["source_pct"].items() if v}
            p("  source mix %%: %s" % ", ".join("%s %g" % kv for kv in sp.items()))
            p("  violations: %s;  deficiencies: %s;  next sanitary survey due %s" % (
                r["violations_gauge"]["label"], r["deficiencies_gauge"]["label"], r["next_sanitary_survey"]))
        else:
            p("  not found in the LDH viewer (federal record only)")
        if w:
            p("  federal: %s %s, population %s, wholesaler %s, source water protection code %s" % (
                w["pws_type_code"], w["pws_activity_code"], fmt_pop(w["population_served_count"]),
                w["is_wholesaler_ind"], w["source_water_protection_code"]))
        p("  wells and intakes (LDH facility index, pulled %s):" % r["index_pulled"])
        for f in r["sources"]:
            p("    %-12s %s %s %-2s %-38s %s" % (f["ident"], f["type"], f["status"], f["availability"] or "",
                                              f["name"][:38], "%.5f, %.5f" % (f["lat"], f["lon"])
                                              if f["lat"] is not None else "NO COORDINATES"))
        if not r["sources"]:
            p("    none: a consecutive system takes its water from the sellers below")
        for x in r["purchases"]:
            p("  buys from %s %s (%s)%s" % (x["seller"], x["seller_name"] or "", x["facility"],
                                          "" if x["active"] else " inactive"))
        if r["buyers"]:
            p("  sells to: " + ", ".join(b + ("" if act else " (inactive)") for b, act in r["buyers"]))
        p("  LDH page: %s" % r["ldh_page"])
        return
    if cmd == "violations":
        p("%s %s: %d federal SDWIS violations since %s, %d health-based" % (
            r["pwsid"], r["name"], len(r["violations"]), r["since"], r["health_based"]))
        for v in r["violations"]:
            p("  %s..%s %-5s %s %-32s %-28s %s%s" % (
                v["begin"], v["end"] or "          ", v["category"], "HB" if v["health_based"] else "  ",
                (v["type"] or v["code"])[:32], str(v["contaminant"])[:28], v["status"],
                " " + v["rtc_date"] if v["rtc_date"] else ""))
        p("LDH status gauge: %s. The gauge has no age limit and reads HIGH for most systems, so it says only "
          "that LDH holds some unresolved health-based violation, possibly decades old or state-only."
          % r["ldh_gauge"]["label"])
        st = r["state"]
        if st:
            p("LDH state record (captured with dww_capture.js): %d violations" % len(st["rows"]))
            for v in st["rows"]:
                p("  %s..%s %-4s %-40s %-24s %s%s" % (v["begin"], v["end"] or "          ", v["code"] or "",
                                                    (v["type"] or "")[:40], (v["analyte"] or "")[:24], v["rtc"] or "",
                                                    "  facility " + v["facility"] if v["facility"] else ""))
            show_searches(st["searches"], "Violations")
            earliest = min((x["bd"] or "9999") for x in st["searches"])
            if earliest > r["since"]:
                p("  The captured LDH window starts %s, after --since %s. Widen Vio Begin in the browser and capture "
                  "again to cover the gap:\n  %s" % (earliest, r["since"], r["capture"]))
        else:
            p("State-only actions (boil advisories, state rule violations) are on the LDH page, not in the federal "
              "data. Not captured yet; with a person at the screen, run:\n  %s" % r["capture"])
        return
    if cmd == "samples":
        p("%s %s: lead and copper 90th percentiles (federal SDWIS)" % (r["pwsid"], r["name"]))
        for x in r["lcr"]:
            p("  %s..%s %-26s %s %s%s" % (x["period_start"], x["period_end"], x["analyte"], x["value"], x["unit"],
                                         "  OVER ACTION LEVEL %s" % x["action_level"] if x["over_action_level"] else ""))
        if not r["lcr"]:
            p("  none reported")
        if r["chemical"] is not None:
            f = r["chemical_filter"]
            p("LDH chemical results (captured)%s: %d results" % (
                "".join([" analyte~%s" % f["analyte"] if f["analyte"] else "",
                         " exceeding the MCL only" if f["exceed_only"] else ""]), len(r["chemical"])))
            for x in r["chemical"]:
                p("  %s %-2s %-28s %-16s MCL %-10s %-4s %-18s lab %s" % (
                    x["collected"], x["type"] or "", x["analyte"][:28], (x["result"] or "")[:16], (x["mcl"] or "")[:10],
                    "OVER" if over_mcl(x["exceeds_mcl"]) else "", (x["location"] or x["point"] or "")[:18],
                    x["lab"] or ""))
            show_searches(r["searches"]["ChemicalGrid"], "ChemicalGrid")
        c = r["coliform"]
        if c is not None:
            p("LDH coliform samples (captured): %d samples; %s" % (c["samples"], "; ".join(
                "%s present in %d of %d" % (k, v["present"], v["tested"]) for k, v in c["by_analyte"].items())))
            for x in c["positives"]:
                p("  %s %-2s PRESENT %-16s %-10s %-28s chlorine total %s free %s  lab %s" % (
                    x["collected"], x["type"] or "", x["analyte"][:16], x["point"] or "", (x["location"] or "")[:28],
                    x["chlorine_total"], x["chlorine_free"], x["lab"] or ""))
            show_searches(r["searches"]["SamplingColiformGrid"], "SamplingColiformGrid")
        for g, rows in r["other_grids"].items():
            p("LDH %s (captured, fields as LDH sent them): %d rows" % (g, len(rows)))
            for x in rows:
                p("  " + "; ".join("%s=%s" % kv for kv in x.items() if kv[1] not in (None, "")))
            show_searches(r["searches"][g], g)
        if r["chemical"] is None and r["coliform"] is None and not r["other_grids"]:
            p(r["note"])
            p("With a person at the screen, run:\n  %s" % r["capture"])
        p("LDH page: %s" % r["ldh_page"])
        return
    if cmd == "visits":
        p("%s site visits and sanitary surveys (LDH)" % r["pwsid"])
        if r["visits"] is None:
            p("  not captured yet; with a person at the screen, run:\n  %s" % r["capture"])
        else:
            for v in r["visits"]:
                p("  %s  %-5s %-28s severity %s" % (v["date"], v["reason"] or "", v["reason_text"], v["severity"] or "?"))
            if not r["visits"]:
                p("  none in the captured window")
            show_searches(r["searches"], "SiteVisits")
        p("deficiency gauge: %s;  next sanitary survey due %s" % (r["deficiency_gauge"]["label"], r["next_survey"] or "none scheduled"))
        p("LDH page: %s" % r["ldh_page"])
        return
    if cmd == "captured":
        if not r["systems"]:
            p("nothing captured yet (%s)" % r["folder"])
        for pid, grids in r["systems"].items():
            p(pid + (":" if grids else ": nothing captured"))
            for g, wins in grids.items():
                show_searches(wins, g)
        return
    if cmd == "near":
        where = ("AoR %s (wells inside it, or within 1 mile of it)" % r["aor"] if r["mode"] == "aor"
                 else "%s,%s within %d m" % (r["lat"], r["lon"], r["radius_m"]))
        p("%d public-supply wells/intakes near %s; status %s" % (len(r["facilities"]), where, r["statuses"]))
        for f in r["facilities"]:
            tag = ""
            if f["type"] == "WL":
                tag = ("IN AoR" if f.get("in_aor") else
                       "point inside SWAP default (%s)" % f["swap_radius"] if f["in_swap_default"] and r["mode"] == "point"
                       else "SWAP default (%s) reaches AoR" % f["swap_radius"] if f["in_swap_default"]
                       else "outside SWAP default (%s)" % f["swap_radius"])
            else:
                tag = "surface intake: run downstream from the discharge point"
            p("  %6d m  %-12s %s %s %-30s %-34s %s pop %s  %s" % (
                f["distance_m"], f["ident"], f["type"], f["status"], f["name"][:30], (f["system"] or "?")[:34],
                f["system_type"] or "", fmt_pop(f["population"]), tag))
        if r["no_coordinates"]:
            p("  no coordinates in LDH (location unknown, may be nearby): " +
              ", ".join("%s %s" % (m["ident"], m["name"]) for m in r["no_coordinates"]))
        if r["inactive_system_dropped"]:
            p("  omitted, system inactive in SDWIS though LDH lists the facility active (--all-status to show): "
              + ", ".join(r["inactive_system_dropped"]))
        p("Facility index pulled %s (%d days ago)." % (r["index_pulled"], r["index_age_days"]))
        p(r["note"])
        return
    if cmd == "downstream":
        p("Outfall %s,%s -> %s (%d m from point); %s; traced %s km downstream, buffer %d m" % (
            r["lat"], r["lon"],
            "Mississippi mainstem (forced; NHDPlus drains the point to COMID %d)" % r["comid"] if r["forced"]
            else "NHDPlus COMID %d" % r["comid"], r["snap_m"],
            "MISSISSIPPI MAINSTEM: traced to the Gulf" if r["mississippi_mainstem"] else "search limit %d km" % r["km"],
            r["traced_km"], r["buffer_m"]))
        if r["mississippi_nearby_m"] is not None:
            p("  WARNING: the point is %d m from the Mississippi but drains, per NHDPlus, to another flowline. If the "
              "outfall discharges to the river, rerun with --mississippi." % r["mississippi_nearby_m"])
        if r["snap_m"] > 500 and not r["forced"]:
            p("  WARNING: the point is %d m from the traced flowline; check that it is on the receiving water"
              % r["snap_m"])
        for f in r["intakes"]:
            where = ("%6.1f km" % f["flow_km"]) if f["flow_km"] is not None else "   n/a   "
            flag = ("SWAP CRITICAL AREA (<5 mi)" if f["critical_area"] else
                    "Mississippi corridor SWPA" if r["mississippi_mainstem"] and f["route"] == "mainstem" else
                    "watershed SWPA" if f["route"] == "mainstem" else f["route"])
            p("  %s  %-12s %s %-36s %-34s pop %-9s %4d m off line  %s" % (
                where, f["ident"], f["status"], f["name"][:36], (f["system"] or "?")[:34], fmt_pop(f["population"]),
                f["off_line_m"], flag))
        if not r["intakes"]:
            p("  no public-supply intakes within the buffer of the trace")
        if r["inactive_system_dropped"]:
            p("  omitted, system inactive in SDWIS though LDH lists the intake active (--all-status to show): "
              + ", ".join(r["inactive_system_dropped"]))
        served = [(p_, s) for p_, s in r["systems"].items() if s["buyers"]]
        for p_, s in served:
            p("  %s sells to %d systems (population %s): %s" % (p_, len(s["buyers"]), fmt_pop(s["buyer_population"]),
                                                              ", ".join(b["pwsid"] for b in s["buyers"])))
        p("  population served by these %d systems, including buyers, each counted once: %s" % (
            r["systems_counted"], fmt_pop(r["population_total"])))
        if r["mississippi_mainstem"]:
            p("SWAP section 5.4.2: each Mississippi intake's SWPA is the river corridor upstream of it to the state "
              "line, so this point is inside the SWPA of every mainstem intake listed.")
        if r["lafourche_via_donaldsonville_km"] is not None:
            p("The point is %.1f km above the Donaldsonville pumps that feed Bayou Lafourche; NHDPlus does not "
              "connect the bayou, so its intakes are listed from a separate trace from its head." %
              r["lafourche_via_donaldsonville_km"])
        p("SWAP section 4.2: an intake's SWPA is its whole upstream watershed; the critical area is the 5 miles "
          "upstream. Flow km is along NHDPlus flowlines from the point. Intake coordinates are LDH's (index %s)."
          % r["index_pulled"])
        return


def main():
    global REFRESH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--refresh", action="store_true", help="bypass the cache")
    # Repeat the globals on each subcommand so they work on either side of it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    sub.add_parser("health", help="LDH, Envirofacts and NLDI answer; facility index intact")

    s = sub.add_parser("systems", help="find water systems by name, parish or id")
    s.add_argument("name", nargs="?")
    s.add_argument("--parish")
    s.add_argument("--id")
    s.add_argument("--inactive", action="store_true", help="include inactive systems")

    s = sub.add_parser("system", help="one water system: header, status, sources, sellers and buyers")
    s.add_argument("pwsid")

    s = sub.add_parser("violations", help="federal SDWIS violations and the LDH status gauge")
    s.add_argument("pwsid")
    s.add_argument("--since", help="YYYY-MM-DD (default 10 years ago)")

    s = sub.add_parser("samples", help="lead/copper 90th percentiles; LDH sample grids captured in a browser")
    s.add_argument("pwsid")
    s.add_argument("--analyte", help="captured chemical results: analyte name fragment or LDH code")
    s.add_argument("--exceed", action="store_true", help="captured chemical results over the MCL only")

    s = sub.add_parser("visits", help="LDH site visits and sanitary surveys (captured), next survey due")
    s.add_argument("pwsid")

    s = sub.add_parser("captured", help="what dww_capture.js has saved, by system and date window")
    s.add_argument("pwsid", nargs="?")

    s = sub.add_parser("near", help="public-supply wells and intakes near a point or in an AoR")
    s.add_argument("lat", type=float, nargs="?")
    s.add_argument("lon", type=float, nargs="?")
    s.add_argument("--radius", type=float, default=2 * MILE, help="metres (default 3219, two miles)")
    s.add_argument("--aor", help="GeoJSON Polygon/MultiPolygon (EPSG:4326)")
    s.add_argument("--all-status", action="store_true", help="include inactive and proposed facilities")

    s = sub.add_parser("downstream", help="surface intakes downstream of an outfall")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--km", type=int, default=150, help="trace length off the Mississippi (default 150)")
    s.add_argument("--buffer", type=float, default=1500, help="metres from the flowline (default 1500)")
    s.add_argument("--all-status", action="store_true", help="include inactive intakes")
    s.add_argument("--mississippi", action="store_true",
                   help="trace from the nearest point on the Mississippi mainstem (for a bank-side outfall)")

    args = ap.parse_args()
    REFRESH = bool(args.refresh)
    if args.cmd == "near" and not args.aor and (args.lat is None or args.lon is None):
        die("near needs <lat> <lon> or --aor FILE")
    if getattr(args, "since", None) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        die("--since must be YYYY-MM-DD")
    if getattr(args, "lat", None) is not None and not (28.5 <= args.lat <= 33.1 and -94.1 <= args.lon <= -88.7):
        die("%s,%s is outside Louisiana (give latitude first, longitude negative)" % (args.lat, args.lon))
    if getattr(args, "km", 1) < 1 or getattr(args, "km", 1) > MS_KM:
        die("--km must be between 1 and %d" % MS_KM)
    fn = {"health": cmd_health, "systems": cmd_systems, "system": cmd_system, "violations": cmd_violations,
          "samples": cmd_samples, "visits": cmd_visits, "captured": cmd_captured, "near": cmd_near, "downstream": cmd_downstream}[args.cmd]
    try:
        res = fn(args)
    except ValueError as e:
        die(str(e), 2)
    except NotFound as e:
        die(str(e), 3)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)
    if args.cmd == "health" and not res["ok"]:
        sys.exit(5)


if __name__ == "__main__":
    main()
