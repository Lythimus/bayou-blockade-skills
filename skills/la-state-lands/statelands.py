#!/usr/bin/env python3
"""Louisiana state lands: State Land Office water-bottom claims, state-owned land, and Office of State
Resources (formerly OMR) mineral leases and operating agreements, including CO2 storage (CCS) agreements,
from the public SONRIS ArcGIS services (no login, no CAPTCHA), plus State Mineral and Energy Board agendas.

Run with: uv run -q --no-project python -I statelands.py <command> ...
Responses are cached for a day (--refresh forces a re-fetch). Cache: ~/.cache/bayou/la-state-lands/.

  statelands.py health                              layers up, count == unique ids paged, CCS crosswalk complete
  statelands.py at <lat> <lon> [--radius M]         claim status, state land, leases and OAs at a point
  statelands.py overlap <aor.geojson> | --point <lat> <lon> --radius M [--samples N]
                                                    acres of an AoR on CCS OAs, state-claimed bottoms, state land,
                                                    mineral leases, legal areas; acres outside every CCS OA
  statelands.py ccs [--parish P]                    CCS operating agreements: operator, computed vs stated acres
  statelands.py lease <SL 344 | 22159 | CS05A | SAL 18542 | B1021>
                                                    one lease or OA, with its SONRIS record and document URLs
  statelands.py search <text|A|B> [--layer L ...]   lessee, bidder, applicant, agency or water-body name
  statelands.py smeb [--url PDF]                    current SMEB agenda: acres under contract, legal items, CCS items
  statelands.py get <CS05 | CS05A | url> [--out DIR] [--yes]   download executed agreement PDFs
"""
import argparse
import datetime
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/bayou/la-state-lands")
TTL = 24 * 3600
UA = "Mozilla/5.0 (bayou-la-state-lands)"
SMEB_PAGE = "https://www.dce.louisiana.gov/state-mineral-and-energy-board"
SMEB_SITE = "https://www.dce.louisiana.gov"
NOTICE_PAGE = "https://www.dce.louisiana.gov/page/mineral-and-energy-board-notice-of-publication"
LEASE_INFO = ("https://sonlite.dnr.state.la.us/ords/r/sonris_pub/sonris_data_portal/state-lease-information"
              "?clear=CR,9075&ig[ig_master]_lease_num=%s")
LEASE_DOCS = "https://sonlite.dnr.state.la.us/ords/r/sonris/ucmsearch/finddocuments?qtype=eq&idx=xstateleasenum&val=%s"
SONRIS_GET = ("node ${CLAUDE_PLUGIN_ROOT}/skills/sonris-session/sonris_get.js --url '%s' --throttle 2500")
SQM_PER_ACRE = 4046.8564224
# Request bodies above this go by POST; long objectId lists overflow GET limits.
MAX_GET = 1800
BIG_BYTES = 25 * 1024 * 1024
DATE_FIELDS = {"SALE_DATE", "LEASE_EFF_DATE", "DATE_ESTAB", "CREATE_DATE", "UPDATE_DATE", "ENTER_DATE"}
NOT_PRIVATE_NOTE = ("These layers map state claims and state-managed land only. Private pore-space and "
                    "mineral ownership is not in them: for acreage outside the state layers, find the surface "
                    "owners with parish-assessor-gis and the mineral servitudes in the parish conveyance records.")
EMPTY_NOTE = ("Not in these layers. That is not a finding that the bottom is private or unclaimed: the "
              "water-body layers are incomplete (banks, small bayous, accreted land) and a point on a "
              "bank misses the channel. Retry with --radius 100, or ask the State Land Office for a title review.")
REFRESH = False


class SourceDown(Exception):
    pass


class NotFound(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


with open(os.path.join(HERE, "layers.json")) as _fh:
    REG = json.load(_fh)
with open(os.path.join(HERE, "ccs_agreements.json")) as _fh:
    CCS = json.load(_fh)


def iso(ms):
    if ms is None:
        return None
    # Pre-1970 sale dates are negative epoch milliseconds, which fromtimestamp rejects on some platforms.
    d = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(milliseconds=ms)
    # Dates are stored as Central midnight, i.e. 05:00 or 06:00 UTC, so the UTC date is the local date.
    return d.date().isoformat()


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024


def acres(m2):
    return m2 / SQM_PER_ACRE


# ---------------------------------------------------------------- HTTP

def _http(url, body):
    if len(body) > MAX_GET:
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    else:
        req = urllib.request.Request(url + "?" + body.decode(), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def get_json(url, params=None, cache=True):
    params = dict(params or {})
    params.setdefault("f", "json")
    body = urllib.parse.urlencode(params).encode()
    path = os.path.join(CACHE, "http", hashlib.sha1(url.encode() + b"?" + body).hexdigest() + ".json")
    cache = cache and not REFRESH
    if cache and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL:
        with open(path) as fh:
            return json.load(fh)
    err = None
    for attempt in range(2):
        if attempt:
            time.sleep(2)
        try:
            raw = _http(url, body)
        except urllib.error.HTTPError as e:
            err = "HTTP %d" % e.code
            if e.code == 403:
                # la.gov sits behind Cloudflare, whose WAF rejects some SQL-looking where clauses
                # (e.g. LIKE combined with IS NULL). Retrying the same clause gets the same answer.
                err += " (Cloudflare WAF rejected the request; keep where clauses to equality, IN or one LIKE)"
                break
            if e.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = "unreachable (%s)" % getattr(e, "reason", e)
            continue
        text = raw.lstrip()
        if text[:1] == b"<":
            m = re.search(rb"<title>([^<]*)", raw, re.I)
            err = "HTML instead of JSON (%s)" % (m.group(1).decode(errors="replace").strip() if m else "no title")
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            err = "unparseable response"
            continue
        if isinstance(data, dict) and "error" in data:
            e = data["error"]
            err = "ArcGIS error %s: %s %s" % (e.get("code"), e.get("message"), "; ".join(e.get("details") or []))
            if (e.get("code") or 0) >= 500:
                continue
            break
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w") as fh:
            json.dump(data, fh)
        os.replace(path + ".part", path)
        return data
    raise SourceDown("%s -> %s" % (url, err))


def get_bytes(url, cache=True, name=None):
    path = os.path.join(CACHE, "files", name or hashlib.sha1(url.encode()).hexdigest())
    if cache and not REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL:
        with open(path, "rb") as fh:
            return fh.read(), path
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound("%s -> HTTP 404" % url)
        raise SourceDown("%s -> HTTP %d" % (url, e.code))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceDown("%s -> unreachable (%s)" % (url, getattr(e, "reason", e)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    return raw, path


def head_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or 0), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound("%s -> HTTP 404" % url)
        raise SourceDown("%s -> HTTP %d" % (url, e.code))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceDown("%s -> unreachable (%s)" % (url, getattr(e, "reason", e)))


# ---------------------------------------------------------------- ArcGIS

def layer_url(key):
    return REG["base"] + REG["layers"][key]["path"]


def point_filter(lat, lon, radius=None):
    f = {"geometry": "%r,%r" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": 4326,
         "spatialRel": "esriSpatialRelIntersects"}
    if radius:
        f.update({"distance": radius, "units": "esriSRUnit_Meter"})
    return f


def envelope_filter(bbox):
    xmin, ymin, xmax, ymax = bbox
    return {"geometry": "%r,%r,%r,%r" % (xmin, ymin, xmax, ymax), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}


def object_ids(url, where="1=1", spatial=None):
    base = {"where": where, "returnIdsOnly": "true"}
    base.update(spatial or {})
    return get_json(url + "/query", base).get("objectIds") or []


def query(url, where="1=1", spatial=None, fields="*", geometry=True, offset=None):
    """All matching features, however many pages that takes.

    The id list first, then the ids in chunks: maxRecordCount is 1000 on this server and a plain query
    silently truncates there (exceededTransferLimit).
    """
    oids = sorted(set(object_ids(url, where, spatial)))
    feats = []
    for i in range(0, len(oids), 500):
        part = oids[i:i + 500]
        p = {"objectIds": ",".join(map(str, part)), "outFields": fields,
             "returnGeometry": "true" if geometry else "false", "outSR": 4326}
        if geometry and offset:
            p["maxAllowableOffset"] = offset
        feats.extend(get_json(url + "/query", p).get("features") or [])
    return feats


def count(url, where="1=1", spatial=None):
    p = {"where": where, "returnCountOnly": "true"}
    p.update(spatial or {})
    return get_json(url + "/query", p).get("count")


def out_fields(key, extra=()):
    return ",".join(["OBJECTID"] + list(REG["layers"][key]["fields"]) + list(extra))


def clean(attrs):
    out = {}
    for k, v in attrs.items():
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v).strip()
        if v in (None, "") or k.upper().startswith("SHAPE"):
            continue
        if k in DATE_FIELDS and isinstance(v, (int, float)):
            v = iso(v)
        out[k] = v
    return out


def layer_rows(key, where="1=1", spatial=None, geometry=False, offset=None, extra=()):
    feats = query(layer_url(key), where, spatial, out_fields(key, extra), geometry, offset)
    rows = []
    for f in feats:
        r = {"attrs": clean(f.get("attributes") or {})}
        if geometry:
            r["rings"] = (f.get("geometry") or {}).get("rings") or []
        rows.append(r)
    return rows


def legend(field, value):
    return (REG["legends"].get(field) or {}).get(str(value).strip(), None)


def sql(v):
    return "'%s'" % str(v).replace("'", "''")


# ---------------------------------------------------------------- geometry

class Proj:
    """Local equirectangular projection in metres; well under 1% error across a parish-sized area."""

    def __init__(self, lat0, lon0):
        r = math.radians(lat0)
        self.ky = 111132.954 - 559.822 * math.cos(2 * r) + 1.175 * math.cos(4 * r)
        self.kx = 111412.84 * math.cos(r) - 93.5 * math.cos(3 * r)
        self.lat0, self.lon0 = lat0, lon0

    def xy(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def lonlat(self, x, y):
        return (self.lon0 + x / self.kx, self.lat0 + y / self.ky)

    def rings(self, rings):
        return [[self.xy(pt[0], pt[1]) for pt in r] for r in rings]


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys))


def edges(r):
    return zip(r, r[1:] + r[:1])


def signed_area(r):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(r)) / 2.0


def inside(p, rings):
    """Even-odd test across all rings, so holes in Esri polygons come out right without classifying them."""
    x, y = p[0], p[1]
    c = False
    for r in rings:
        for a, b in edges(r):
            if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                c = not c
    return c


def area_m2(xy_rings):
    # Esri winds outer rings clockwise and holes counter-clockwise, so the signed sum nets out holes.
    return abs(sum(signed_area(r) for r in xy_rings))


def interior_point(rings):
    outer = max(rings, key=lambda r: abs(signed_area(r)))
    a = signed_area(outer)
    if a:
        cx = sum((p[0] + q[0]) * (p[0] * q[1] - q[0] * p[1]) for p, q in edges(outer)) / (6 * a)
        cy = sum((p[1] + q[1]) * (p[0] * q[1] - q[0] * p[1]) for p, q in edges(outer)) / (6 * a)
        if inside((cx, cy), rings):
            return (cx, cy)
    pts = grid_points(rings, 400)
    return pts[len(pts) // 2] if pts else tuple(outer[0][:2])


def grid_points(rings, target=900):
    """Grid of points inside the polygon, about `target` across its bounding box, shaped to its aspect."""
    x0, y0, x1, y1 = bbox_of(rings)
    w, h = max(x1 - x0, 1e-12), max(y1 - y0, 1e-12)
    nx = max(3, min(target, int(math.sqrt(target * w / h))))
    ny = max(3, min(target, target // nx))
    pts = []
    for i in range(nx):
        for j in range(ny):
            p = (x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if inside(p, rings):
                pts.append(p)
    return pts


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
        raise ValueError("%s has no Polygon or MultiPolygon geometry; for a point use --point LAT LON --radius M"
                         % path)
    return polys


def circle(lat, lon, radius, n=72):
    pj = Proj(lat, lon)
    ring = [pj.lonlat(radius * math.cos(2 * math.pi * k / n), radius * math.sin(2 * math.pi * k / n))
            for k in range(n)]
    return [[list(p) for p in ring + ring[:1]]]


class Prepared:
    """A feature's rings in local metres with per-ring bounding boxes, for fast repeated point tests."""

    def __init__(self, xy_rings):
        self.rings = [r for r in xy_rings if len(r) > 2]
        self.ring_bb = [bbox_of([r]) for r in self.rings]
        self.bbox = bbox_of(self.rings) if self.rings else (0, 0, 0, 0)

    def contains(self, p):
        x, y = p
        c = False
        for r, b in zip(self.rings, self.ring_bb):
            # A ring whose y-span misses the point contributes no crossings.
            if y < b[1] or y > b[3] or x > b[2]:
                continue
            for a, q in edges(r):
                if (a[1] > y) != (q[1] > y) and x < (q[0] - a[0]) * (y - a[1]) / (q[1] - a[1]) + a[0]:
                    c = not c
        return c


# ---------------------------------------------------------------- CCS crosswalk

def ccs_part(num):
    num = num.upper()
    part = CCS["parts"].get(num)
    if not part:
        return None
    agr = CCS["agreements"][part["agreement"]]
    return dict(part, number=num, operator=agr["operator"], resolution=agr["resolution"],
                board_approval=agr["board_approval"], pdf=CCS["pdf_base"] + num + ".pdf")


def is_ccs(label):
    return bool(re.match(r"^CS\d", (label or "").upper()))


# ---------------------------------------------------------------- commands

def cmd_health(a):
    checks = []
    ok = True
    for key, spec in REG["layers"].items():
        if not spec.get("health"):
            continue
        url = layer_url(key)
        try:
            n = count(url)
            ids = object_ids(url)
        except SourceDown as e:
            checks.append({"layer": key, "ok": False, "error": str(e)})
            ok = False
            continue
        good = n == len(set(ids)) == len(ids)
        ok &= good
        checks.append({"layer": key, "path": spec["path"], "count": n, "unique_ids": len(set(ids)), "ok": good})
    # Page every Active Leases row: a plain query stops at 1,000 of the ~1,080 rows.
    rows = layer_rows("leases")
    labels = [r["attrs"].get("STATE_LEAS", "") for r in rows]
    prefixes = {}
    for lab in labels:
        m = re.match(r"^([A-Z]+)", lab.upper())
        pre = m.group(1) if m else "?"
        prefixes[pre] = prefixes.get(pre, 0) + 1
    lease_check = next(c for c in checks if c["layer"] == "leases")
    paged_ok = len(rows) == lease_check.get("count")
    ok &= paged_ok
    gis_cs = sorted(lab.upper() for lab in labels if is_ccs(lab))
    missing_entry = [c for c in gis_cs if c not in CCS["parts"]]
    not_in_gis = [c for c in CCS["parts"] if c not in gis_cs]
    unconfirmed = [c for c, p in CCS["parts"].items() if p.get("status") != "verified"]
    ok &= not missing_entry
    return {"ok": ok, "layers": checks, "leases_paged": len(rows), "leases_paged_ok": paged_ok,
            "lease_prefixes": prefixes, "ccs_in_gis": gis_cs, "ccs_missing_crosswalk": missing_entry,
            "ccs_crosswalk_not_in_gis": not_in_gis, "ccs_unconfirmed": unconfirmed}


AT_LAYERS = ["claimed", "waterbodies", "major", "stateland", "wma", "refuge", "leases", "sal", "blease",
             "legal", "tracts", "landsale", "parish"]


def cmd_at(a):
    spatial = point_filter(a.lat, a.lon, a.radius)
    res = {"lat": a.lat, "lon": a.lon, "radius_m": a.radius, "layers": {}}
    for key in AT_LAYERS:
        rows = [r["attrs"] for r in layer_rows(key, spatial=spatial)]
        for r in rows:
            for fld in ("WEB_STATUS", "STATECLAIM", "USE", "SURF_INT"):
                if fld in r and legend(fld, r[fld]):
                    r[fld + "_MEANS"] = legend(fld, r[fld])
            if key == "leases" and is_ccs(r.get("STATE_LEAS")):
                r["CCS"] = ccs_part(r["STATE_LEAS"])
        res["layers"][key] = rows
    c17 = sorted({"%s: %s" % (r.get("NAME", "?"), r.get("WEB_STATUS")) for r in res["layers"]["claimed"]})
    c20 = sorted({"%s: %s" % (r.get("NAME", "?"), r.get("STATECLAIM")) for r in res["layers"]["waterbodies"]})
    res["claim"] = {"layer17_state_claimed": c17, "layer20_title_index": c20}
    if not c17 and not c20:
        res["claim"]["note"] = EMPTY_NOTE
    else:
        s17 = {r.get("WEB_STATUS") for r in res["layers"]["claimed"]}
        s20 = {r.get("STATECLAIM") for r in res["layers"]["waterbodies"]}
        if (s17 and s20 and ("Y" in s17) != ("Y" in s20)) or bool(s17) != bool(s20):
            res["claim"]["note"] = ("The two State Land Office layers disagree here. Layer 17 is the published "
                                    "claim map; layer 20 indexes title files, where NO TITLE FILE means not "
                                    "reviewed, not unclaimed. Cite both, and the title file if there is one.")
    return res


OVERLAP_LAYERS = [("leases", None), ("claimed", "WEB_STATUS"), ("waterbodies", "STATECLAIM"),
                  ("stateland", "SURF_INT"), ("wma", "NAME"), ("refuge", "NAME"), ("legal", "POLY_TYPE"),
                  ("sal", "STATE_LEAS")]


def cmd_overlap(a):
    if a.aor and a.point:
        raise ValueError("give either an AoR GeoJSON file or --point, not both")
    if a.point:
        if not a.radius:
            raise ValueError("--point needs --radius in metres")
        polys = [circle(a.point[0], a.point[1], a.radius)]
        source = "circle r=%gm at %s,%s" % (a.radius, a.point[0], a.point[1])
    elif a.aor:
        polys = geojson_polys(a.aor)
        source = a.aor
    else:
        raise ValueError("give an AoR GeoJSON file or --point LAT LON --radius M")
    allr = [r for p in polys for r in p]
    bb = bbox_of(allr)
    pj = Proj((bb[1] + bb[3]) / 2, (bb[0] + bb[2]) / 2)
    xy_polys = [pj.rings(p) for p in polys]
    aor_m2 = sum(area_m2(p) for p in xy_polys)
    if aor_m2 <= 0:
        raise ValueError("AoR has zero area")
    step = math.sqrt(aor_m2 / a.samples)
    pts = []
    xb = bbox_of([r for p in xy_polys for r in p])
    preps = [Prepared(p) for p in xy_polys]
    y = xb[1] + step / 2
    while y < xb[3]:
        x = xb[0] + step / 2
        while x < xb[2]:
            if any(pp.contains((x, y)) for pp in preps):
                pts.append((x, y))
            x += step
        y += step
    if not pts:
        raise ValueError("no sample points fell inside the AoR; raise --samples")
    cell_ac = acres(aor_m2) / len(pts)
    # Simplify returned geometry to a quarter of the sample spacing: finer vertices cannot change the result.
    offset = max(1e-5, step / 4 / pj.ky)
    spatial = envelope_filter(bb)
    hits = {}
    feats_out = {}
    for key, group in OVERLAP_LAYERS:
        rows = layer_rows(key, spatial=spatial, geometry=True, offset=offset)
        feats_out[key] = []
        for r in rows:
            if not r["rings"]:
                continue
            prep = Prepared(pj.rings(r["rings"]))
            b = prep.bbox
            inn = {i for i, p in enumerate(pts) if b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3] and prep.contains(p)}
            if not inn:
                continue
            at = r["attrs"]
            label = at.get(REG["layers"][key]["label"]) or "?"
            if key == "leases":
                # No attribute separates gas-storage OAs from oil-and-gas OAs, so every A#### is
                # reported apart from mineral leases and must be checked with `lease`.
                up = label.upper()
                cat = ("ccs" if is_ccs(up) else "operating_agreements" if re.match(r"^A\d", up)
                       else "wind" if up.startswith("WE") else "no_leasing" if up.startswith("NO")
                       else "mineral_leases")
            else:
                cat = key
            item = {"label": label, "acres": round(len(inn) * cell_ac, 1), "_pts": inn}
            if group and key not in ("wma", "refuge"):
                item["code"] = at.get(group)
                if legend(group, at.get(group)):
                    item["means"] = legend(group, at.get(group))
            if cat == "ccs":
                item["crosswalk"] = ccs_part(label)
            if cat in ("mineral_leases", "operating_agreements"):
                item["lessee"] = at.get("ORIGINAL_LESSEE") or at.get("BIDDER_NM")
                item["class"] = at.get("LEASE_CLASS_CODE_DESCR")
            hits.setdefault(cat, []).append(item)
    union = lambda items, pred=lambda i: True: set().union(*[i["_pts"] for i in items if pred(i)]) if items else set()
    ccs_pts = union(hits.get("ccs", []))
    state_pts = (union(hits.get("claimed", []), lambda i: i.get("code") in ("Y", "DC"))
                 | union(hits.get("waterbodies", []), lambda i: i.get("code") in ("Y", "PARTIAL"))
                 | union(hits.get("stateland", []), lambda i: i.get("code") in ("FULL_INTEREST", "PART_INTEREST")))
    dual_pts = union(hits.get("claimed", []), lambda i: i.get("code") == "DC")
    jac_pts = union(hits.get("claimed", []), lambda i: i.get("code") == "JAC")
    lease_pts = union(hits.get("mineral_leases", []))
    oa_pts = union(hits.get("operating_agreements", []))
    allp = set(range(len(pts)))
    to_ac = lambda s: round(len(s) * cell_ac, 1)
    by_cat = {}
    for cat, items in hits.items():
        merged = {}
        for i in items:
            k = (i["label"], i.get("code"))
            if k in merged:
                merged[k]["_pts"] |= i["_pts"]
                merged[k]["acres"] = to_ac(merged[k]["_pts"])
            else:
                merged[k] = dict(i, _pts=set(i["_pts"]))
        by_cat[cat] = sorted(merged.values(), key=lambda i: -i["acres"])
        for i in by_cat[cat]:
            i.pop("_pts")
    return {
        "aor": source, "aor_acres": round(acres(aor_m2), 1), "samples": len(pts), "acres_per_sample": round(cell_ac, 2),
        "summary": {
            "in_ccs_oa": to_ac(ccs_pts),
            "state_claimed_or_owned": to_ac(state_pts),
            "state_claimed_outside_every_ccs_oa": to_ac(state_pts - ccs_pts),
            "dual_claimed_DC": to_ac(dual_pts),
            "judgment_against_state_JAC": to_ac(jac_pts),
            "under_state_mineral_lease": to_ac(lease_pts),
            "mineral_lease_inside_ccs_oa": to_ac(lease_pts & ccs_pts),
            "under_A_operating_agreement": to_ac(oa_pts),
            "neither_state_layers_nor_ccs_oa": to_ac(allp - state_pts - ccs_pts),
        },
        "categories": by_cat,
        "note": NOT_PRIVATE_NOTE,
    }


def cmd_ccs(a):
    rows = layer_rows("leases", where="STATE_LEAS like 'CS%'", geometry=True)
    parts = []
    for r in rows:
        lab = r["attrs"].get("STATE_LEAS", "").upper()
        rings = r["rings"]
        if not rings:
            continue
        bb = bbox_of(rings)
        pj = Proj((bb[1] + bb[3]) / 2, (bb[0] + bb[2]) / 2)
        ac = acres(area_m2(pj.rings(rings)))
        sample = grid_points(rings, 300)
        par = layer_rows("parish", spatial=envelope_filter(bb), geometry=True, offset=0.001)
        shares = {}
        for p in par:
            prep = Prepared(p["rings"])
            k = sum(1 for s in sample if prep.contains(s))
            if k:
                shares[p["attrs"].get("PARISH", "?").title()] = k
        tot = sum(shares.values()) or 1
        cw = ccs_part(lab)
        parts.append({"number": lab, "computed_acres": round(ac), "parishes": {k: round(100.0 * v / tot)
                      for k, v in sorted(shares.items(), key=lambda kv: -kv[1])},
                      "gis_posted": "%s-%s" % (r["attrs"]["YEAR_NUM"], r["attrs"].get("MONTH_NUM", "?"))
                      if r["attrs"].get("YEAR_NUM") else None,
                      "gis_flag": r["attrs"].get("CD_SOURCE"), "crosswalk": cw})
    if a.parish:
        want = a.parish.lower()
        parts = [p for p in parts if any(want in k.lower() for k in p["parishes"])]
        if not parts:
            raise NotFound("no CCS operating agreement polygon touches a parish matching %r" % a.parish)
    groups = {}
    for p in parts:
        g = (p["crosswalk"] or {}).get("agreement") or p["number"]
        groups.setdefault(g, []).append(p)
    agreements = []
    for g, ps in sorted(groups.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0)):
        agr = CCS["agreements"].get(g, {})
        missing = [n for n, v in CCS["parts"].items() if v["agreement"] == g and n not in {p["number"] for p in ps}]
        stated_mapped = None
        if missing:
            stated_mapped = sum((p["crosswalk"] or {}).get("stated_acres") or 0 for p in ps) or None
        agreements.append({"agreement": g, "operator": agr.get("operator", "not in crosswalk"),
                           "resolution": agr.get("resolution"), "board_approval": agr.get("board_approval"),
                           "stated_acres": agr.get("stated_acres"), "stated_acres_mapped_parts": stated_mapped,
                           "computed_acres": sum(p["computed_acres"] for p in ps),
                           "parts": sorted(ps, key=lambda p: p["number"]), "parts_not_in_gis": missing,
                           "text": agr.get("text"), "gis_note": agr.get("gis_note")})
    lrr = CCS["lease_review_report"]
    return {"agreements": agreements, "computed_total": sum(x["computed_acres"] for x in agreements),
            "stated_total": round(sum(v["stated_acres"] for v in CCS["agreements"].values()), 2),
            "lease_review_report": lrr, "listing_page": CCS["listing_page"]}


def norm_lease(s):
    s = re.sub(r"\s+", " ", s.strip().upper())
    m = re.match(r"^(SL|WL|WE|SAL|STATE LEASE|LEASE)\s*#?\s*(\d+)$", s)
    if m:
        pre = {"STATE LEASE": "SL", "LEASE": "SL"}.get(m.group(1), m.group(1))
        return pre, str(int(m.group(2)))
    if re.fullmatch(r"\d+", s):
        return "", str(int(s))
    return "", s.replace(" ", "")


def sonris_links(attrs, num):
    info = attrs.get("HYPERLINK") if str(attrs.get("HYPERLINK", "")).startswith("https://sonlite") else None
    docs = attrs.get("DOC_ACCESS") if str(attrs.get("DOC_ACCESS", "")).startswith("https://sonlite") else None
    # State Agency Lease rows still carry pre-2020 sundown/ucmwww links, which now land on the same CAPTCHA.
    info = info or LEASE_INFO % num
    docs = docs or LEASE_DOCS % num
    return {"lease_information": info, "documents": docs,
            "gated": "SONRIS reCAPTCHA. Fetch with the sonris-session skill: " + SONRIS_GET % docs}


def cmd_lease(a):
    pre, num = norm_lease(a.id)
    tries = []
    if pre:
        tries += [("leases", "STATE_LEAS=%s" % sql("%s %s" % (pre, num)))]
        if pre == "SAL":
            tries += [("sal", "STATE_LEAS=%s" % sql("SAL %s" % num))]
    elif re.fullmatch(r"\d+", num):
        tries += [("leases", "LEASE_NUM=%s" % sql(num.zfill(5))), ("sal", "LEASE_NUM=%s" % sql(num)),
                  ("sal", "LEASE_NUM=%s" % sql(num.zfill(5)))]
    else:
        tries += [("leases", "STATE_LEAS=%s" % sql(num)), ("leases", "LEASE_NUM=%s" % sql(num)),
                  ("blease", "LEASE_NUM=%s" % sql(num))]
    for key, where in tries:
        rows = layer_rows(key, where=where)
        if rows:
            out = []
            for r in rows:
                at = r["attrs"]
                ln = at.get("LEASE_NUM") or num
                rec = {"layer": key, "attrs": at, "sonris": sonris_links(at, ln)}
                if is_ccs(at.get("STATE_LEAS")):
                    rec["crosswalk"] = ccs_part(at["STATE_LEAS"])
                out.append(rec)
            return {"query": a.id, "records": out}
    hist = []
    if re.fullmatch(r"\d+", num):
        hist = [r["attrs"] for r in layer_rows("archive", where="LEASE_NUM=%s" % sql(num))]
        if not hist:
            hist = [r["attrs"] for r in layer_rows("archive", where="LEASE_NUM=%s" % sql(num.zfill(5)))]
    if hist:
        return {"query": a.id, "records": [], "archive": hist,
                "note": "Not an active lease on the GIS layers; the tract archive has its sale record. It may "
                        "have expired or been released. SONRIS: " + LEASE_INFO % num.zfill(5),
                "sonris": sonris_links({}, num.zfill(5))}
    names = [r["attrs"].get("STATE_LEAS", "") for k in ("leases", "sal") for r in layer_rows(k)]
    near = difflib.get_close_matches(("%s %s" % (pre, num)).strip(), names, n=8, cutoff=0.6)
    raise NotFound("%s: not on the Active Leases, State Agency Leases, B Lease or Tract Archive layers.%s"
                   % (a.id, (" Near: " + ", ".join(near)) if near else ""))


SEARCH_DEFAULT = ["leases", "sal", "blease", "tracts", "legal"]


def cmd_search(a):
    layers = a.layer or SEARCH_DEFAULT
    if "all" in layers:
        layers = [k for k, v in REG["layers"].items() if v.get("search")]
    pats = [p.strip().lower() for p in a.text.split("|") if p.strip()]
    if not pats:
        raise ValueError("empty search text")
    res = {"text": a.text, "layers": {}}
    total = 0
    for key in layers:
        spec = REG["layers"][key]
        fields = spec["search"]
        extra = [f for f in fields if f not in spec["fields"]]
        rows = layer_rows(key, extra=extra)
        hits = []
        for r in rows:
            at = r["attrs"]
            blob = " | ".join(str(at.get(f, "")) for f in fields).lower()
            if any(p in blob for p in pats):
                hits.append(at)
        res["layers"][key] = {"count": len(hits), "rows": hits[:a.limit]}
        total += len(hits)
    cw = [dict(v, agreement=k) for k, v in CCS["agreements"].items()
          if any(p in v["operator"].lower() for p in pats)]
    if cw:
        res["ccs_operators"] = cw
        res["ccs_note"] = ("CCS operating agreements carry no operator on the GIS layer; these come from the "
                           "crosswalk. Run `ccs` for their polygons and acreage.")
    if not total and not cw:
        raise NotFound("no match for %r in %s. Lessee fields hold the original lessee only (assignments are on "
                       "SONRIS); CCS operators are matched from the crosswalk; tract archive search needs "
                       "--layer archive." % (a.text, ", ".join(layers)))
    return res


LRR_RE = re.compile(r"^\s*([A-Z][A-Za-z&/ ]+?(?:Leases|Agreements))\s*\n\s*[•\-\*o]\s*([\d,]+)\s+(\w+)\s*[–\-]+\s*"
                    r"approx\.?\s*([\d,]+)\s*acres", re.M)
CCS_WATCH = re.compile(r"sequestration|carbon dioxide|carbon capture|\bCCS\b|pore space|conditional approval|"
                       r"storage operating agreement", re.I)


def cmd_smeb(a):
    page_links = []
    url = a.url
    if not url:
        raw, _ = get_bytes(SMEB_PAGE)
        html = raw.decode("utf-8", "replace")
        if "Just a moment" in html[:4000] or "cf-chl" in html:
            raise SourceDown("%s returned a Cloudflare challenge page" % SMEB_PAGE)
        hrefs = re.findall(r'href="([^"]+)"', html)
        agendas = [h for h in hrefs if "Notices-Agendas-Reports" in h and h.lower().endswith(".pdf")]
        if not agendas:
            raise SourceDown("no agenda PDF linked from %s; the page layout may have changed" % SMEB_PAGE)
        url = urllib.parse.urljoin(SMEB_SITE, agendas[0])
        page_links = [urllib.parse.urljoin(SMEB_SITE, h) for h in hrefs if "Resources-For-Board-Members" in h][:6]
    raw, path = get_bytes(url, name="agenda-" + hashlib.sha1(url.encode()).hexdigest()[:12] + ".pdf")
    if not raw.startswith(b"%PDF"):
        raise SourceDown("%s did not return a PDF" % url)
    if not shutil.which("pdftotext"):
        raise ValueError("pdftotext (poppler) is required: brew install poppler")
    text = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    m = re.search(r"NOTICE AND AGENDA\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    meeting = m.group(1) if m else None
    lrr = {}
    m = re.search(r"approximately\s+([\d,]+)\s+state\s+acres", text, re.I)
    if m:
        lrr["total_state_acres_under_contract"] = int(m.group(1).replace(",", ""))
    for cat, n, unit, ac in LRR_RE.findall(text):
        lrr[re.sub(r"\s+", " ", cat.strip())] = {"count": int(n.replace(",", "")), "unit": unit,
                                                 "acres": int(ac.replace(",", ""))}

    def section(title):
        # Case-sensitive: the agenda's table of contents repeats each memo title in title case, and only
        # the upper-case memo heading starts the memo body.
        m = re.search(title + r"(.*?)(?=\n\s*TO:\s|\Z)", text, re.S)
        return m.group(1) if m else ""

    legal = [re.sub(r"\s+", " ", x).strip() for x in
             re.split(r"\n\s*\d+\.\s+", "\n" + section(r"LEGAL\s*&\s*TITLE\s+CONTROVERSY\s+REPORT"))[1:]]
    nom = [re.sub(r"\s+", " ", s).strip() for s in
           re.findall(r"[^.]*nominat[^.]*\.", section(r"NOMINATION\s+AND\s+TRACT\s+REPORT"), re.I)]
    lrr_block = section(r"LEASE\s+REVIEW\s+REPORT")
    watch = []
    for line in text.splitlines():
        if CCS_WATCH.search(line) and line.strip() and line not in lrr_block:
            watch.append(line.strip())
    return {"meeting": meeting, "agenda_pdf": url, "lease_review_report": lrr, "legal_title_items": legal,
            "nomination_report": nom, "ccs_mentions_outside_lease_report": watch,
            "board_presentations": page_links, "notice_of_publication": NOTICE_PAGE,
            "note": "Only the current month's agenda is linked from the Board page; earlier months' PDFs are "
                    "not published at a guessable URL. Pass --url for a saved copy."}


def cmd_get(a):
    ident = a.id.strip()
    if re.match(r"^https?://", ident):
        urls = [ident]
    else:
        key = ident.upper()
        if key in CCS["parts"]:
            urls = [CCS["pdf_base"] + key + ".pdf"]
        elif key in CCS["agreements"]:
            urls = [CCS["pdf_base"] + n + ".pdf" for n, p in CCS["parts"].items() if p["agreement"] == key]
        else:
            raise NotFound("%s is not a CS number or agreement in the crosswalk (%s)"
                           % (ident, ", ".join(sorted(CCS["parts"]))))
    sizes = [(u,) + head_size(u) for u in urls]
    total = sum(s[1] for s in sizes)
    if total > BIG_BYTES and not a.yes:
        die("%d file(s), %s in total. Re-run with --yes to download.\n%s" % (
            len(urls), human(total), "\n".join("  %10s  %s" % (human(s[1]), s[0]) for s in sizes)), 2)
    os.makedirs(a.out, exist_ok=True)
    saved = []
    for u, size, ctype in sizes:
        req = urllib.request.Request(u, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SourceDown("%s -> %s" % (u, getattr(e, "reason", e)))
        if not data.startswith(b"%PDF"):
            raise SourceDown("%s returned %s, not a PDF" % (u, ctype or "unknown content"))
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(urllib.parse.urlparse(u).path)) or "file.pdf"
        path = os.path.join(os.path.abspath(a.out), name)
        with open(path, "wb") as fh:
            fh.write(data)
        saved.append({"url": u, "path": path, "bytes": len(data)})
    return {"saved": saved, "bytes": total,
            "note": "Executed agreements are scans; run document-ocr before searching their text."}


# ---------------------------------------------------------------- output

def p(s=""):
    print(s)


def fmt_attrs(at, skip=()):
    return "; ".join("%s=%s" % (k, v) for k, v in at.items() if k not in skip and k != "OBJECTID"
                     and not isinstance(v, dict))


def show(cmd, r):
    if cmd == "health":
        p("health: %s" % ("OK" if r["ok"] else "PROBLEM"))
        for c in r["layers"]:
            if "error" in c:
                p("  %-12s ERROR %s" % (c["layer"], c["error"]))
            else:
                p("  %-12s %-22s count %6d  unique ids %6d  %s" % (c["layer"], c["path"], c["count"],
                                                                   c["unique_ids"], "ok" if c["ok"] else "MISMATCH"))
        p("  Active Leases paged by objectId: %d rows (%s)" % (r["leases_paged"], "ok" if r["leases_paged_ok"] else "MISMATCH"))
        p("  label prefixes: " + ", ".join("%s %d" % kv for kv in sorted(r["lease_prefixes"].items(), key=lambda kv: -kv[1])))
        p("  CCS numbers on GIS: " + ", ".join(r["ccs_in_gis"]))
        if r["ccs_missing_crosswalk"]:
            p("  NOT IN CROSSWALK (add with a source): " + ", ".join(r["ccs_missing_crosswalk"]))
        if r["ccs_crosswalk_not_in_gis"]:
            p("  in crosswalk, absent from GIS: " + ", ".join(r["ccs_crosswalk_not_in_gis"]))
        if r["ccs_unconfirmed"]:
            p("  crosswalk entries unconfirmed: " + ", ".join(r["ccs_unconfirmed"]))
        return
    if cmd == "at":
        p("%s, %s%s" % (r["lat"], r["lon"], " (within %g m)" % r["radius_m"] if r["radius_m"] else ""))
        c = r["claim"]
        p("Water-bottom claim:")
        p("  layer 17 State Claimed Water Bodies: %s" % ("; ".join(c["layer17_state_claimed"]) or "none"))
        p("  layer 20 State Water Bodies (title index): %s" % ("; ".join(c["layer20_title_index"]) or "none"))
        if c.get("note"):
            p("  " + c["note"])
        for key in AT_LAYERS:
            if key in ("claimed", "waterbodies"):
                continue
            rows = r["layers"][key]
            if not rows:
                continue
            p("%s:" % REG["layers"][key]["title"])
            for at in rows[:25]:
                cw = at.pop("CCS", None)
                p("  " + fmt_attrs(at, skip=("HYPERLINK", "DOC_ACCESS")))
                if cw:
                    p("    CCS operating agreement: %s, resolution %s (%s); %s" % (
                        cw["operator"], cw["resolution"], cw["board_approval"], cw["pdf"]))
            if len(rows) > 25:
                p("  ... %d more (use --json)" % (len(rows) - 25))
        return
    if cmd == "overlap":
        p("AoR %s: %.1f acres, %d sample points (%.2f ac each)" % (r["aor"], r["aor_acres"], r["samples"],
                                                                   r["acres_per_sample"]))
        s = r["summary"]
        p("  inside a CCS operating agreement ............ %10.1f ac" % s["in_ccs_oa"])
        p("  state-claimed bottom or state-owned surface . %10.1f ac" % s["state_claimed_or_owned"])
        p("    of which outside every CCS OA ............. %10.1f ac" % s["state_claimed_outside_every_ccs_oa"])
        p("    dual claimed (DC) ......................... %10.1f ac" % s["dual_claimed_DC"])
        p("  judgment/compromise against state (JAC) ..... %10.1f ac" % s["judgment_against_state_JAC"])
        p("  under a state mineral lease ................. %10.1f ac" % s["under_state_mineral_lease"])
        p("    of which inside a CCS OA .................. %10.1f ac" % s["mineral_lease_inside_ccs_oa"])
        p("  under an A#### operating agreement .......... %10.1f ac  (oil/gas or gas storage: check each with `lease`)"
          % s["under_A_operating_agreement"])
        p("  in neither the state layers nor a CCS OA .... %10.1f ac" % s["neither_state_layers_nor_ccs_oa"])
        p("A CS polygon does not prove the agreement is still in force (the SMEB report counts fewer CCS OAs "
          "than GIS draws); confirm on the SONRIS lease record before asserting control.")
        names = {"ccs": "CCS operating agreements", "mineral_leases": "State mineral leases (SL/WL)",
                 "operating_agreements": "State operating agreements (A####)", "wind": "Wind operating agreements",
                 "no_leasing": "No-leasing areas",
                 "claimed": "State Claimed Water Bodies (17)", "waterbodies": "State Water Bodies (20)",
                 "stateland": "State Owned/Leased Lands", "wma": "Wildlife Management Areas",
                 "refuge": "Wildlife Refuges", "legal": "Legal Areas", "sal": "State Agency Leases"}
        for cat, items in r["categories"].items():
            p("%s:" % names.get(cat, cat))
            for i in items[:20]:
                extra = ""
                if i.get("crosswalk"):
                    extra = "  %s (res. %s, %s)" % (i["crosswalk"]["operator"], i["crosswalk"]["resolution"],
                                                    i["crosswalk"]["board_approval"])
                elif cat == "ccs":
                    extra = "  NOT IN CROSSWALK"
                if i.get("lessee"):
                    extra = "  %s %s" % (i["lessee"], i.get("class") or "")
                code = " [%s%s]" % (i["code"], ": " + i["means"] if i.get("means") else "") if i.get("code") and cat not in ("sal",) else ""
                p("  %10.1f ac  %s%s%s" % (i["acres"], i["label"], code, extra))
            if len(items) > 20:
                p("  ... %d more (use --json)" % (len(items) - 20))
        p(r["note"])
        return
    if cmd == "ccs":
        for g in r["agreements"]:
            p("%s  %s  res. %s (%s)  stated %s ac%s, GIS %s ac" % (
                g["agreement"], g["operator"], g["resolution"], g["board_approval"],
                "{:,}".format(g["stated_acres"]) if g["stated_acres"] else "?",
                " (%s for the mapped parts)" % "{:,}".format(g["stated_acres_mapped_parts"])
                if g["stated_acres_mapped_parts"] else "", "{:,}".format(g["computed_acres"])))
            for pt in g["parts"]:
                cw = pt["crosswalk"] or {}
                tag = " ".join(x for x in (pt["gis_posted"], pt["gis_flag"]) if x)
                p("  %-6s GIS %7s ac  stated %7s  %s%s" % (
                    pt["number"], "{:,}".format(pt["computed_acres"]),
                    "{:,}".format(cw["stated_acres"]) if cw.get("stated_acres") else "-",
                    ", ".join("%s %d%%" % kv for kv in pt["parishes"].items()), "  [GIS %s]" % tag if tag else ""))
                if cw.get("area"):
                    p("         %s" % cw["area"])
            if g["parts_not_in_gis"]:
                p("  listed but not on the GIS layer: " + ", ".join(g["parts_not_in_gis"]))
            if g.get("gis_note"):
                p("  " + g["gis_note"])
        lrr = r["lease_review_report"]
        p("Totals: GIS %s ac; executed agreements state %s ac." % ("{:,}".format(r["computed_total"]),
                                                                 "{:,}".format(r["stated_total"])))
        p("SMEB Lease Review Report %s: %d CCS OAs, about %s ac. %s" % (lrr["date"], lrr["oas"],
                                                                         "{:,}".format(lrr["acres"]), lrr["note"]))
        p("Run `smeb` for the current month's figure. Agreement list: " + r["listing_page"])
        return
    if cmd == "lease":
        for rec in r["records"]:
            p("[%s] %s" % (rec["layer"], fmt_attrs(rec["attrs"], skip=("HYPERLINK", "DOC_ACCESS"))))
            if rec.get("crosswalk"):
                cw = rec["crosswalk"]
                p("  CCS operating agreement: %s; resolution %s, approved %s; %s" % (
                    cw["operator"], cw["resolution"], cw["board_approval"], cw["pdf"]))
            p("  SONRIS lease record: " + rec["sonris"]["lease_information"])
            p("  SONRIS documents:    " + rec["sonris"]["documents"])
            p("  " + rec["sonris"]["gated"])
        if r.get("archive"):
            p(r["note"])
            for at in r["archive"]:
                p("  [archive] " + fmt_attrs(at))
        return
    if cmd == "search":
        for key, v in r["layers"].items():
            if not v["count"]:
                continue
            p("%s: %d match(es)" % (REG["layers"][key]["title"], v["count"]))
            for at in v["rows"]:
                p("  " + fmt_attrs(at, skip=("HYPERLINK", "DOC_ACCESS")))
            if v["count"] > len(v["rows"]):
                p("  ... %d more (raise --limit or use --json)" % (v["count"] - len(v["rows"])))
        for c in r.get("ccs_operators", []):
            p("CCS %s: %s, resolution %s (%s), %s ac stated, parishes %s" % (
                c["agreement"], c["operator"], c["resolution"], c["board_approval"], "{:,}".format(c["stated_acres"]),
                ", ".join(c["parishes"])))
        if r.get("ccs_note"):
            p(r["ccs_note"])
        return
    if cmd == "smeb":
        p("SMEB meeting %s  %s" % (r["meeting"] or "(date not parsed)", r["agenda_pdf"]))
        lrr = r["lease_review_report"]
        if lrr:
            p("Lease Review Report:")
            for k, v in lrr.items():
                p("  %-45s %s" % (k, ("%d %s, about %s ac" % (v["count"], v["unit"], "{:,}".format(v["acres"])))
                                   if isinstance(v, dict) else "{:,}".format(v)))
        else:
            p("Lease Review Report: not parsed; read the PDF.")
        if r["legal_title_items"]:
            p("Legal & Title Controversy items:")
            for i, x in enumerate(r["legal_title_items"], 1):
                p("  %d. %s" % (i, x))
        if r["nomination_report"]:
            p("Nomination and Tract Report:")
            for x in r["nomination_report"]:
                p("  " + x)
        p("CCS / sequestration mentions outside the Lease Review Report: %s" % (
            "none" if not r["ccs_mentions_outside_lease_report"] else ""))
        for x in r["ccs_mentions_outside_lease_report"]:
            p("  " + x)
        p("Tracts advertised for the next sale: " + r["notice_of_publication"])
        for u in r["board_presentations"]:
            p("Board presentation: " + u)
        p(r["note"])
        return
    if cmd == "get":
        for s in r["saved"]:
            p("%s  %s" % (human(s["bytes"]), s["path"]))
        p(r["note"])
        return
    p(json.dumps(r, indent=1, default=str))


def main():
    global REFRESH
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

    sub.add_parser("health", help="layers up, count == unique ids paged, CCS crosswalk complete")

    s = sub.add_parser("at", help="everything state-related at a point")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--radius", type=float, help="metres around the point")

    s = sub.add_parser("overlap", help="acres of an AoR on CCS OAs, state-claimed bottoms, state land, leases")
    s.add_argument("aor", nargs="?", help="GeoJSON Polygon/MultiPolygon (EPSG:4326)")
    s.add_argument("--point", nargs=2, type=float, metavar=("LAT", "LON"))
    s.add_argument("--radius", type=float, help="metres, with --point")
    s.add_argument("--samples", type=int, default=4000, help="grid points across the AoR (default 4000)")

    s = sub.add_parser("ccs", help="CCS operating agreements with operator, stated and computed acres")
    s.add_argument("--parish")

    s = sub.add_parser("lease", help="one lease or operating agreement")
    s.add_argument("id", nargs="+")

    s = sub.add_parser("search", help="name search across lease, tract and water-body layers")
    s.add_argument("text", help="substring; A|B matches either")
    s.add_argument("--layer", action="append", choices=sorted(
        [k for k, v in REG["layers"].items() if v.get("search")] + ["all"]))
    s.add_argument("--limit", type=int, default=25)

    s = sub.add_parser("smeb", help="current State Mineral and Energy Board agenda")
    s.add_argument("--url", help="agenda PDF URL instead of the one linked from the Board page")

    s = sub.add_parser("get", help="download executed CCS agreement PDFs")
    s.add_argument("id", help="CS number (CS05A), agreement (CS05) or URL")
    s.add_argument("--out", default=".")
    s.add_argument("--yes", action="store_true", help="confirm a download over 25 MB")

    args = ap.parse_args()
    REFRESH = bool(args.refresh)
    if args.cmd == "lease":
        args.id = " ".join(args.id)
    if args.cmd == "at" and not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        die("lat/lon out of range (give latitude first)")
    if args.cmd == "at" and not (28.5 <= args.lat <= 33.1 and -94.1 <= args.lon <= -88.7):
        die("%s,%s is outside Louisiana (give latitude first, longitude negative)" % (args.lat, args.lon))
    if getattr(args, "samples", 100) < 100:
        die("--samples must be at least 100")
    fn = {"health": cmd_health, "at": cmd_at, "overlap": cmd_overlap, "ccs": cmd_ccs, "lease": cmd_lease,
          "search": cmd_search, "smeb": cmd_smeb, "get": cmd_get}[args.cmd]
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
