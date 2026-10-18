#!/usr/bin/env python3
"""Parcel, owner, zoning, footprint and receptor lookups against parish ArcGIS REST layers.

Standard library only. Layer URLs and field maps live in parishes.json next to this file.
HTTP responses are cached for a day under ~/.cache/bayou/parish-assessor-gis/.

  parcels.py at <lat> <lon>                      parcel, owner, zoning at a point
  parcels.py address "<street, city, LA>"        geocode, then `at`
  parcels.py parcel <pin> --parish <key>         look up by parcel number
  parcels.py owner "<A|B>" --near <lat> <lon>    parcels whose owner matches
  parcels.py footprint --owner "<A|B>" --near <lat> <lon> --out fp.geojson
  parcels.py receptors --footprint fp.geojson --radius-mi 1
  parcels.py health [parish]
"""
import argparse
import collections
import datetime
import hashlib
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
UA = "Mozilla/5.0 (bayou-parish-assessor-gis)"
CACHE = os.path.expanduser("~/.cache/bayou/parish-assessor-gis")
CACHE_TTL = 24 * 3600
TIGER_COUNTIES = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1"
CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
M_PER_MI = 1609.344
FT_PER_M = 3.28084
SQM_PER_ACRE = 4046.8564224
# Request bodies above this go by POST; polygon geometries and long objectId lists overflow GET limits.
MAX_GET = 1800
SHAPE_FIELDS = re.compile(r"^(shape|st_area|st_length|shape__|shape\.)", re.I)


class SourceDown(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


with open(os.path.join(HERE, "parishes.json")) as _fh:
    REG = json.load(_fh)


# ---------------------------------------------------------------- HTTP

def _http(url, body):
    if len(body) > MAX_GET:
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    else:
        req = urllib.request.Request(url + "?" + body.decode(), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def get_json(url, params=None, cache=True):
    params = dict(params or {})
    params.setdefault("f", "json")
    body = urllib.parse.urlencode(params).encode()
    path = os.path.join(CACHE, "http", hashlib.sha1(url.encode() + b"?" + body).hexdigest() + ".json")
    if cache and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
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
            if e.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = "unreachable (%s)" % getattr(e, "reason", e)
            continue
        text = raw.lstrip()
        # ArcGIS Web Adaptors (geo.apgov.us) answer an outage with HTTP 200 and an HTML page.
        if text[:1] == b"<":
            m = re.search(rb"(Could not access any server machines[^<]*|<title>([^<]*))", raw, re.I)
            err = "HTML error page: %s" % (m.group(0).decode(errors="replace") if m else "no JSON")
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


def layer_info(url, cache=True):
    return get_json(url, {}, cache=cache)


def field_types(url):
    return {f["name"]: f["type"] for f in layer_info(url).get("fields") or []}


def oid_field_of(url):
    # Older MapServer layers omit objectIdField from their metadata; the field list still types it.
    info = layer_info(url)
    return info.get("objectIdField") or next(
        (f["name"] for f in info.get("fields") or [] if f["type"] == "esriFieldTypeOID"), "OBJECTID")


def vintage(url):
    try:
        info = layer_info(url)
    except SourceDown:
        return "layer metadata unavailable"
    ed = info.get("editingInfo") or {}
    ms = ed.get("dataLastEditDate") or ed.get("lastEditDate")
    return "layer data last edited %s" % iso(ms) if ms else "layer publishes no edit date"


def iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()


def sql_lit(value, ftype):
    if ftype in ("esriFieldTypeInteger", "esriFieldTypeSmallInteger", "esriFieldTypeBigInteger",
                 "esriFieldTypeDouble", "esriFieldTypeSingle", "esriFieldTypeOID"):
        return str(int(value)) if re.fullmatch(r"-?\d+", str(value)) else str(float(value))
    return "'%s'" % str(value).replace("'", "''")


def point_filter(lat, lon):
    return {"geometry": "%r,%r" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects"}


def envelope_filter(bbox):
    xmin, ymin, xmax, ymax = bbox
    return {"geometry": "%r,%r,%r,%r" % (xmin, ymin, xmax, ymax), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}


def polygon_filter(rings):
    return {"geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPolygon", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}


def query(url, where="1=1", spatial=None, fields="*", geometry=True, max_records=1000):
    """All matching features, however many pages that takes.

    Fetching objectIds first and then pulling them in chunks works on every server version,
    including MapServers that do not advertise supportsPagination.
    """
    # No outSR here: maps.scpgis.com silently drops ~10% of envelope matches when outSR accompanies
    # a spatial filter. The id list needs no output reference anyway.
    base = {"where": where}
    base.update(spatial or {})
    ids = get_json(url + "/query", dict(base, returnIdsOnly="true"))
    oids = sorted(ids.get("objectIds") or [])
    chunk = max(1, min(max_records, 500))
    feats = []
    for i in range(0, len(oids), chunk):
        part = oids[i:i + chunk]
        r = get_json(url + "/query", {"objectIds": ",".join(map(str, part)), "outFields": fields,
                                      "returnGeometry": "true" if geometry else "false", "outSR": 4326})
        feats.extend(r.get("features") or [])
    return feats


def count(url, where="1=1", spatial=None, cache=True):
    p = {"where": where, "returnCountOnly": "true"}
    p.update(spatial or {})
    return get_json(url + "/query", p, cache=cache).get("count")


# ---------------------------------------------------------------- registry

def parish(key):
    p = REG["parishes"].get(key)
    if p is None:
        die("unknown parish %r; registry keys: %s" % (key, ", ".join(REG["parishes"])))
    if p.get("status") == "unprobed":
        die("%s is in the registry but its layers have not been probed yet. See 'Adding a parish' in "
            "SKILL.md: search ArcGIS Online for the parish org, unwrap the parish viewer's app config, "
            "or fall back to the assessor's site and a public-records request.%s"
            % (p["name"], ("\nHint: " + p["hint"]) if p.get("hint") else ""), 4)
    p["key"] = key
    return p


def detect_parish(lat, lon):
    feats = get_json(TIGER_COUNTIES + "/query", dict(point_filter(lat, lon), outFields="GEOID,NAME",
                                                     returnGeometry="false")).get("features") or []
    if not feats:
        die("no parish contains %s, %s (offshore or a bad coordinate?)" % (lat, lon))
    a = feats[0]["attributes"]
    for key, p in REG["parishes"].items():
        if p.get("fips") == a["GEOID"]:
            return key
    die("%s (FIPS %s) is not in the registry" % (a["NAME"], a["GEOID"]), 4)


def owner_layer(p):
    """(layer spec, field map, url of the geometry-of-record layer when it differs)."""
    if "owner" in p["parcels"]["field_map"]:
        return p["parcels"], p["parcels"]["field_map"], None
    for src in p.get("owner_sources") or []:
        if (src.get("field_map") or {}).get("owner"):
            return src, src["field_map"], p["parcels"]["url"]
    die("%s has no owner source with a field map" % p["name"])


# ---------------------------------------------------------------- attributes

def fmtv(v, ftype):
    if v is None:
        return None
    if ftype == "esriFieldTypeDate" and isinstance(v, (int, float)):
        return iso(v)
    if isinstance(v, str):
        return " ".join(v.split()) or None
    # Parcel numbers stored as Double (Ascension PARCEL_NO) must stringify the same as text copies.
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def canon(attrs, fmap, types):
    out = {}
    for k, spec in (fmap or {}).items():
        if isinstance(spec, list):
            vals = []
            for n in spec:
                v = fmtv(attrs.get(n), types.get(n))
                if v not in (None, "") and str(v) not in vals:
                    vals.append(str(v))
            out[k] = ("; " if k == "owner" else ", ").join(vals) or None
        else:
            out[k] = fmtv(attrs.get(spec), types.get(spec))
    return out


def raw_attrs(attrs, types):
    return {k: fmtv(v, types.get(k)) for k, v in attrs.items()
            if not SHAPE_FIELDS.match(k) and v not in (None, "")}


# ---------------------------------------------------------------- geometry

class Proj:
    """Local equirectangular projection in metres; accurate to well under 1% across a parish."""

    def __init__(self, lat0, lon0):
        r = math.radians(lat0)
        self.ky = 111132.954 - 559.822 * math.cos(2 * r) + 1.175 * math.cos(4 * r)
        self.kx = 111412.84 * math.cos(r) - 93.5 * math.cos(3 * r)
        self.lat0, self.lon0 = lat0, lon0

    def xy(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def rings(self, rings):
        return [[self.xy(pt[0], pt[1]) for pt in r] for r in rings]

    def pad(self, bbox, metres):
        dx, dy = metres / self.kx, metres / self.ky
        return (bbox[0] - dx, bbox[1] - dy, bbox[2] + dx, bbox[3] + dy)


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_union(bbs):
    return (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))


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


def seg_d2(p, a, b):
    ax, ay = a[0], a[1]
    dx, dy = b[0] - ax, b[1] - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    ex, ey = ax + t * dx - p[0], ay + t * dy - p[1]
    return ex * ex + ey * ey


def area_m2(xy_rings):
    # Esri winds outer rings clockwise and holes counter-clockwise, so the signed sum nets out holes.
    return abs(sum(signed_area(r) for r in xy_rings))


class Shape:
    """Polygons in local metres with grid indexes over edges and vertices for nearest-edge queries."""

    def __init__(self, polys):
        self.polys = [(bbox_of(rs), rs) for rs in polys if rs and any(rs)]
        if not self.polys:
            raise ValueError("empty geometry")
        self.bbox = bbox_union([b for b, _ in self.polys])
        w, h = self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]
        self.cs = max(5.0, max(w, h) / 64.0)
        self.nx = int(w / self.cs) + 1
        self.ny = int(h / self.cs) + 1
        self.grid = collections.defaultdict(list)
        self.vgrid = collections.defaultdict(list)
        for _, rs in self.polys:
            for r in rs:
                for a, b in edges(r):
                    if a == b:
                        continue
                    self.vgrid[self.cell(a)].append(a)
                    for c in self._cells_on(a, b):
                        self.grid[c].append((a, b))

    def cell(self, p):
        return (int((p[0] - self.bbox[0]) // self.cs), int((p[1] - self.bbox[1]) // self.cs))

    def _cells_on(self, a, b):
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / (self.cs / 2)) + 1
        out, prev = set(), None
        for k in range(n + 1):
            c = self.cell((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
            out.add(c)
            # A step that changes both indices can cut a corner cell; include both neighbours.
            if prev and prev[0] != c[0] and prev[1] != c[1]:
                out.add((prev[0], c[1]))
                out.add((c[0], prev[1]))
            prev = c
        return out

    def _ring(self, cx, cy, r):
        if r == 0:
            if 0 <= cx < self.nx and 0 <= cy < self.ny:
                yield (cx, cy)
            return
        for i in range(max(cx - r, 0), min(cx + r, self.nx - 1) + 1):
            for j in (cy - r, cy + r):
                if 0 <= j < self.ny:
                    yield (i, j)
        for j in range(max(cy - r + 1, 0), min(cy + r - 1, self.ny - 1) + 1):
            for i in (cx - r, cx + r):
                if 0 <= i < self.nx:
                    yield (i, j)

    def contains(self, p):
        return any(b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3] and inside(p, rs) for b, rs in self.polys)

    def nearest_edge(self, p, cap=math.inf):
        """Distance in metres from p to the nearest edge, or inf if beyond cap."""
        cx, cy = self.cell(p)
        r = max(0, -cx, cx - (self.nx - 1), -cy, cy - (self.ny - 1))
        rmax = r + max(self.nx, self.ny) + 1
        best = math.inf
        while r <= rmax:
            # p lies inside cell (cx, cy), so every edge in ring r is at least (r-1) cells away.
            floor = max(0, r - 1) * self.cs
            if floor * floor >= best or floor > cap:
                break
            for c in self._ring(cx, cy, r):
                for a, b in self.grid.get(c, ()):
                    d = seg_d2(p, a, b)
                    if d < best:
                        best = d
            r += 1
        return math.sqrt(best)

    def vertices_in(self, bb):
        i0, j0 = self.cell((bb[0], bb[1]))
        i1, j1 = self.cell((bb[2], bb[3]))
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                for v in self.vgrid.get((i, j), ()):
                    if bb[0] <= v[0] <= bb[2] and bb[1] <= v[1] <= bb[3]:
                        yield v

    def distance_to(self, geom, cap=math.inf):
        """Edge-to-edge distance in metres from this shape to a point (x, y) or a list of xy rings."""
        if isinstance(geom, tuple):
            return 0.0 if self.contains(geom) else self.nearest_edge(geom, cap)
        verts = [v for r in geom for v in r]
        if any(self.contains(v) for v in verts):
            return 0.0
        d1 = min(self.nearest_edge(v, cap) for v in verts)
        # Our own vertices can still lie within cap of the other shape's edges when its vertices do not.
        pad = min(d1, cap)
        bb = bbox_of(geom)
        near = list(self.vertices_in((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad)))
        if any(inside(v, geom) for v in near):
            return 0.0
        best = d1 * d1
        for v in near:
            for r in geom:
                for a, b in edges(r):
                    best = min(best, seg_d2(v, a, b))
        return math.sqrt(best)


def interior_point(rings):
    """A point (lon, lat) inside the polygon; the centroid when it falls inside, else a sampled point."""
    outer = max(rings, key=lambda r: abs(signed_area(r)))
    a = signed_area(outer)
    if a:
        cx = sum((p[0] + q[0]) * (p[0] * q[1] - q[0] * p[1]) for p, q in edges(outer)) / (6 * a)
        cy = sum((p[1] + q[1]) * (p[0] * q[1] - q[0] * p[1]) for p, q in edges(outer)) / (6 * a)
        if inside((cx, cy), rings):
            return (cx, cy)
    pts = sample_points(rings, 400)
    return pts[len(pts) // 2] if pts else tuple(outer[0][:2])


def sample_points(rings, target=900):
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


def esri_to_geojson_polys(rings):
    """Split an Esri ring list into GeoJSON polygon coordinate arrays (outer CCW, holes CW)."""
    outers, holes = [], []
    for r in rings:
        r = [[p[0], p[1]] for p in r]
        if r[0] != r[-1]:
            r.append(r[0])
        (outers if signed_area(r) < 0 else holes).append(r)
    if not outers:
        outers, holes = holes, []
    polys = [[o[::-1]] for o in outers]
    for hl in holes:
        for poly, o in zip(polys, outers):
            if inside(hl[0], [o]):
                poly.append(hl[::-1])
                break
    return polys


def geojson_rings(path):
    """Every ring in a GeoJSON file, flattened, plus the properties of its first feature."""
    with open(path) as fh:
        g = json.load(fh)
    feats = g["features"] if g.get("type") == "FeatureCollection" else [g if g.get("type") == "Feature" else {"geometry": g}]
    rings, props = [], (feats[0].get("properties") or {}) if feats else {}
    for f in feats:
        geom = f["geometry"]
        if geom["type"] == "Polygon":
            rings.append(geom["coordinates"])
        elif geom["type"] == "MultiPolygon":
            rings.extend(geom["coordinates"])
        elif geom["type"] == "Point":
            rings.append([[geom["coordinates"]]])
    return rings, props


# ---------------------------------------------------------------- parcel description

def describe(p, feat, types, with_zoning=True):
    pl = p["parcels"]
    rings = feat["geometry"]["rings"]
    a = canon(feat["attributes"], pl["field_map"], types)
    ip = interior_point(rings)
    proj = Proj(ip[1], ip[0])
    row = {
        "pin": a.get("pin"),
        "acres": round(area_m2(proj.rings(rings)) / SQM_PER_ACRE, 2),
        "source_url": pl["url"], "authority": pl["authority"], "vintage": vintage(pl["url"]),
        "attributes": {k: v for k, v in a.items() if k != "pin" and v not in (None, "")},
        "polygons": feat.get("parts", 1),
        "interior_point": [round(ip[1], 6), round(ip[0], 6)],
        "rings": rings,
    }
    row["owner"] = owner_for(p, a, rings, ip)
    if p.get("assessor_link") and a.get("pin"):
        row["assessor_link"] = p["assessor_link"].format(pin=urllib.parse.quote(str(a["pin"])))
    if with_zoning:
        row["zoning"], row["zoning_notes"] = zoning_for(p, rings)
    return row


def merge_parts(pl, feats, types):
    """One feature per parcel number, with the rings of every feature that shares it.

    Parish layers split multipart parcels into separate features, so the polygon under a point
    can be only part of the parcel (SCP 160100000930 and Ascension 2026400 both are).
    """
    f = pl["field_map"]["pin"]
    out, seen = [], set()
    for x in feats:
        pin = fmtv(x["attributes"].get(f), types.get(f))
        if pin in (None, "") or pin in seen:
            if pin in (None, ""):
                out.append(x)
            continue
        seen.add(pin)
        parts = query(pl["url"], "%s = %s" % (f, sql_lit(pin, types.get(f))), max_records=pl["max_records"])
        rings = [r for y in parts for r in (y.get("geometry") or {}).get("rings") or []]
        out.append(dict(x, geometry={"rings": rings or x["geometry"]["rings"]}, parts=max(1, len(parts))))
    return out


def owner_for(p, a, rings, ip):
    pl = p["parcels"]
    if "owner" in pl["field_map"]:
        return {"name": a.get("owner"), "mail": a.get("owner_mail"), "source_url": pl["url"],
                "authority": pl["authority"], "vintage": vintage(pl["url"])}
    notes = []
    for src in p.get("owner_sources") or []:
        try:
            types = field_types(src["url"])
            if src["match"] == "join":
                j = src["join"]
                key = a.get("pin")
                if key in (None, ""):
                    notes.append("no parcel number to join on")
                    continue
                where = "%s = %s" % (j["to"], sql_lit(key, types.get(j["to"])))
                feats = query(src["url"], where, geometry=False)
            else:
                feats = query(src["url"], spatial=point_filter(ip[1], ip[0]), geometry=False)
        except (SourceDown, ValueError) as e:
            notes.append("%s: %s" % (src["authority"], e))
            continue
        if not feats:
            notes.append("%s %s: no record for this parcel" % (src["authority"], src["url"]))
            continue
        attrs = feats[0]["attributes"]
        out = {"source_url": src["url"], "authority": src["authority"], "vintage": vintage(src["url"])}
        if src.get("field_map"):
            c = canon(attrs, src["field_map"], types)
            out.update(name=c.get("owner"), mail=c.get("owner_mail"),
                       extra={k: v for k, v in c.items() if k not in ("owner", "owner_mail") and v not in (None, "")})
        else:
            out.update(name=None, raw=raw_attrs(attrs, types),
                       note="field names unverified; read the owner from the raw attributes")
        if src.get("stale"):
            out["stale"] = src["stale"]
        if notes:
            out["skipped"] = notes
        return out
    return {"name": None, "skipped": notes, "note": "no owner source answered"}


def zoning_for(p, rings):
    """Every zoning district intersecting the parcel, with the share of parcel area it covers."""
    out, notes = [], []
    pts = sample_points(rings)
    for z in p.get("zoning") or []:
        try:
            feats = query(z["url"], spatial=polygon_filter(rings))
        except SourceDown as e:
            notes.append("%s unavailable: %s" % (z["label"], e))
            continue
        types = field_types(z["url"])
        for f in feats:
            at = f["attributes"]
            zr = (f.get("geometry") or {}).get("rings") or []
            share = sum(1 for q in pts if inside(q, zr)) / len(pts) if pts else None
            row = {"label": z["label"], "authority": z["authority"], "source_url": z["url"],
                   "code": fmtv(at.get(z["code_field"]), None) if z.get("code_field") else "overlay",
                   "share": round(share, 3) if share is not None else None}
            if z.get("desc_field"):
                row["desc"] = fmtv(at.get(z["desc_field"]), None)
            extra = {k: fmtv(at.get(k), types.get(k)) for k in z.get("extra_fields") or []}
            row["extra"] = {k: v for k, v in extra.items() if v not in (None, "")}
            if share == 0:
                row["note"] = "touches the parcel edge or covers a sliver below sampling resolution (~0.1%)"
            out.append(row)
        if z.get("note"):
            notes.append("%s: %s" % (z["label"], z["note"]))
    if p.get("zoning_gap"):
        notes.insert(0, p["zoning_gap"])
    # Zoning layers are often split into many polygons per district; report one row per district.
    merged = {}
    for r in out:
        k = (r["source_url"], r["code"], r.get("desc"), json.dumps(r["extra"], sort_keys=True, default=str))
        if k in merged:
            m = merged[k]
            m["share"] = round((m["share"] or 0) + (r["share"] or 0), 3)
            m["polygons"] += 1
        else:
            merged[k] = dict(r, polygons=1)
    out = list(merged.values())
    for r in out:
        if r["share"]:
            r.pop("note", None)
    out.sort(key=lambda r: -(r["share"] or 0))
    return out, notes


# ---------------------------------------------------------------- commands

def cmd_at(args, lat=None, lon=None):
    lat = args.lat if lat is None else lat
    lon = args.lon if lon is None else lon
    key = args.parish or detect_parish(lat, lon)
    p = parish(key)
    pl = p["parcels"]
    feats = query(pl["url"], spatial=point_filter(lat, lon), max_records=pl["max_records"])
    types = field_types(pl["url"])
    rows = [describe(p, f, types) for f in merge_parts(pl, feats, types)]
    if pl["field_map"].get("parcel_zoning_attr"):
        for r in rows:
            r["parcel_zoning_attr"] = r["attributes"].pop("parcel_zoning_attr", None)
    res = {"parish": key, "parish_name": p["name"], "point": [lat, lon], "parcels": rows}
    if not rows:
        res["note"] = "no parcel polygon contains this point (water, road right-of-way, or a gap in the layer)"
    write_parcels_geojson(args, res, rows)
    return res


def write_parcels_geojson(args, res, rows):
    if getattr(args, "out", None) and rows:
        props = {"parish": res["parish"], "pins": list(dict.fromkeys(r["pin"] for r in rows)),
                 "owners": sorted({(r["owner"] or {}).get("name") or "" for r in rows} - {""}),
                 "acres": round(sum(r["acres"] for r in rows), 2),
                 "source_url": rows[0]["source_url"], "generated": datetime.date.today().isoformat()}
        save_geojson(args.out, [r["rings"] for r in rows], props)
        res["wrote"] = args.out


def cmd_address(args):
    r = get_json(CENSUS_GEOCODER, {"address": args.address, "benchmark": "Public_AR_Current", "format": "json"})
    matches = (r.get("result") or {}).get("addressMatches") or []
    if not matches:
        die("Census geocoder found no match for %r; pass coordinates to `at` instead" % args.address, 3)
    m = matches[0]
    lat, lon = m["coordinates"]["y"], m["coordinates"]["x"]
    key = args.parish or detect_parish(lat, lon)
    p = parish(key)
    geo = {"input": args.address, "census_match": m["matchedAddress"], "census_point": [lat, lon],
           "note": "Census points are interpolated along the street segment and can sit on a neighbour's lot."}
    ad = p.get("addresses") or {}
    num = re.match(r"\s*(\d+)", m["matchedAddress"])
    if ad.get("number_field") and num:
        try:
            types = field_types(ad["url"])
            proj = Proj(lat, lon)
            bb = proj.pad((lon, lat, lon, lat), 400)
            where = "%s = %s" % (ad["number_field"], sql_lit(num.group(1), types.get(ad["number_field"])))
            pts = query(ad["url"], where, envelope_filter(bb))
            best = None
            for f in pts:
                g = f.get("geometry") or {}
                if "x" not in g:
                    continue
                d = math.dist(proj.xy(g["x"], g["y"]), (0, 0))
                if best is None or d < best[0]:
                    best = (d, g, f["attributes"].get(ad["full_field"]))
            if best:
                lat, lon = best[1]["y"], best[1]["x"]
                geo.update(parish_address_point=[lat, lon], parish_address=best[2],
                           census_offset_ft=round(best[0] * FT_PER_M), used="parish address point")
            else:
                geo["used"] = "census point (no parish address point with that number within 400 m)"
        except SourceDown as e:
            geo["used"] = "census point (address layer down: %s)" % e
    else:
        geo["used"] = "census point (this parish has no address-number field registered)"
    args.parish = key
    res = cmd_at(args, lat, lon)
    res["geocode"] = geo
    return res


def cmd_parcel(args):
    p = parish(args.parish)
    pl = p["parcels"]
    types = field_types(pl["url"])
    f = pl["field_map"]["pin"]
    feats = query(pl["url"], "%s = %s" % (f, sql_lit(args.pin, types.get(f))), max_records=pl["max_records"])
    rows = [describe(p, x, types) for x in merge_parts(pl, feats, types)]
    res = {"parish": args.parish, "parish_name": p["name"], "pin": args.pin, "parcels": rows}
    if not rows:
        res["note"] = "no parcel with %s = %s in %s" % (f, args.pin, pl["url"])
        if p.get("assessor_link"):
            res["assessor_link"] = p["assessor_link"].format(pin=urllib.parse.quote(args.pin))
    write_parcels_geojson(args, res, rows)
    return res


def owner_where(pattern, fields):
    fields = fields if isinstance(fields, list) else [fields]
    pats = [s.strip().upper().replace("'", "''") for s in pattern.split("|") if s.strip()]
    return "(" + " OR ".join("UPPER(%s) LIKE '%%%s%%'" % (f, s) for s in pats for f in fields) + ")"


def owner_parcels(args):
    """Parcels whose owner matches, as dicts with pin, owner, situs, rings (current geometry where possible)."""
    if args.near:
        lat, lon = args.near
        key = args.parish or detect_parish(lat, lon)
    elif args.parish:
        key = args.parish
    else:
        die("give --near <lat> <lon> or --parish")
    p = parish(key)
    src, fmap, geom_url = owner_layer(p)
    spatial = None
    if args.near:
        proj = Proj(lat, lon)
        spatial = envelope_filter(proj.pad((lon, lat, lon, lat), args.radius_mi * M_PER_MI))
    elif args.bbox:
        spatial = envelope_filter(tuple(args.bbox))
    types = field_types(src["url"])
    feats = query(src["url"], owner_where(args.pattern, fmap["owner"]), spatial, max_records=src.get("max_records", 1000))
    rows = []
    for f in feats:
        if not (f.get("geometry") or {}).get("rings"):
            continue
        c = canon(f["attributes"], fmap, types)
        rows.append({"pin": c.get("pin"), "owner": c.get("owner"), "situs": c.get("situs"),
                     "rings": f["geometry"]["rings"], "geometry_source": src["url"]})
    if geom_url and rows:
        # Owner copy may be years old; take parcel shapes from the current parish layer by parcel number.
        pf = p["parcels"]["field_map"]["pin"]
        gt = field_types(geom_url)
        current = {}
        pins = [r["pin"] for r in rows if r["pin"] not in (None, "")]
        for i in range(0, len(pins), 200):
            where = "%s IN (%s)" % (pf, ",".join(sql_lit(x, gt.get(pf)) for x in pins[i:i + 200]))
            for f in query(geom_url, where, max_records=p["parcels"]["max_records"]):
                # One parcel number can span several features (multipart parcels split on publish).
                current.setdefault(str(fmtv(f["attributes"].get(pf), None)), []).extend(f["geometry"]["rings"])
        for r in rows:
            if str(r["pin"]) in current:
                r["rings"], r["geometry_source"] = current[str(r["pin"])], geom_url
            else:
                r["geometry_note"] = "parcel number not in the current parish layer (split, merged or renumbered); 2016 shape used"
    meta = {"parish": key, "parish_name": p["name"], "owner_source": src["url"], "authority": src["authority"],
            "vintage": vintage(src["url"]), "stale": src.get("stale")}
    return p, meta, rows


def cmd_owner(args):
    p, meta, rows = owner_parcels(args)
    for r in rows:
        ip = interior_point(r["rings"])
        proj = Proj(ip[1], ip[0])
        r["acres"] = round(area_m2(proj.rings(r["rings"])) / SQM_PER_ACRE, 2)
        if args.near:
            pr = Proj(args.near[0], args.near[1])
            r["miles_from_near"] = round(Shape([pr.rings(r["rings"])]).distance_to((0.0, 0.0)) / M_PER_MI, 2)
        del r["rings"]
    rows.sort(key=lambda r: r.get("miles_from_near", 0))
    meta.update(pattern=args.pattern, count=len(rows), parcels=rows,
                total_acres=round(sum(r["acres"] for r in rows), 1))
    return meta


def cmd_footprint(args):
    if args.pins:
        if not args.parish:
            die("--pins needs --parish")
        p = parish(args.parish)
        pl = p["parcels"]
        types = field_types(pl["url"])
        f = pl["field_map"]["pin"]
        pins = [s.strip() for s in args.pins.split(",") if s.strip()]
        feats = query(pl["url"], "%s IN (%s)" % (f, ",".join(sql_lit(x, types.get(f)) for x in pins)),
                      max_records=pl["max_records"])
        rows = []
        for x in feats:
            d = describe(p, x, types, with_zoning=False)
            rows.append({"pin": d["pin"], "owner": (d["owner"] or {}).get("name"), "rings": d["rings"]})
        missing = sorted(set(pins) - {str(r["pin"]) for r in rows})
        meta = {"parish": args.parish, "parish_name": p["name"], "selection": "pins", "missing_pins": missing}
    else:
        if not (args.owner and args.near):
            die("give --pins (with --parish) or --owner with --near")
        args.pattern = args.owner
        p, meta, rows = owner_parcels(args)
        meta["selection"] = "owner %r within %.1f mi of %s" % (args.owner, args.radius_mi, args.near)
    if not rows:
        die("no parcels selected", 3)
    lat0 = sum(interior_point(r["rings"])[1] for r in rows) / len(rows)
    lon0 = sum(interior_point(r["rings"])[0] for r in rows) / len(rows)
    proj = Proj(lat0, lon0)
    xy = [proj.rings(r["rings"]) for r in rows]
    clusters = cluster(xy, args.gap_ft / FT_PER_M)
    if args.near and not args.all_clusters:
        q = proj.xy(args.near[1], args.near[0])
        keep = min(clusters, key=lambda c: Shape([xy[i] for i in c]).distance_to(q))
        # Clusters are built from polygons, and a multipart parcel can straddle two of them;
        # listing a parcel number while dropping some of its polygons would understate the site.
        if not args.polygons_only:
            kept_pins = {rows[i]["pin"] for i in keep}
            added = [i for i in range(len(rows)) if rows[i]["pin"] in kept_pins and i not in keep]
            if added:
                core = Shape([xy[i] for i in keep])
                meta["detached_parts"] = ["%s: %.1f ac, %d ft from the rest" % (
                    rows[i]["pin"], area_m2(xy[i]) / SQM_PER_ACRE, core.distance_to(xy[i]) * FT_PER_M) for i in added]
                meta["detached_rule"] = ("kept because the parcel number is in the site; rerun with --polygons-only "
                                         "if these tracts are not part of the facility")
            keep = sorted(set(keep) | set(added))
        dropped = len(rows) - len(keep)
        rows = [rows[i] for i in keep]
        xy = [xy[i] for i in keep]
        meta["clusters_found"] = len(clusters)
        meta["parcels_dropped"] = dropped
        meta["cluster_rule"] = ("kept the group of parcels within %g ft of each other that contains or is nearest "
                                "the --near point; --all-clusters keeps every group" % args.gap_ft)
    acres = sum(area_m2(r) for r in xy) / SQM_PER_ACRE
    props = {"parish": meta["parish"], "pins": list(dict.fromkeys(r["pin"] for r in rows)),
             "owners": sorted({r["owner"] or "" for r in rows} - {""}), "acres": round(acres, 2),
             "selection": meta["selection"], "gap_ft": args.gap_ft,
             "geometry_sources": sorted({r.get("geometry_source", p["parcels"]["url"]) for r in rows}),
             "generated": datetime.date.today().isoformat(),
             "note": "MultiPolygon of member parcels, not dissolved; shared parcel lines remain inside."}
    save_geojson(args.out, [r["rings"] for r in rows], props)
    meta.update(wrote=args.out, parcels=len(rows), acres=round(acres, 1), pins=props["pins"], owners=props["owners"])
    notes = [r["geometry_note"] for r in rows if r.get("geometry_note")]
    if notes:
        meta["geometry_notes"] = "%d parcel(s): %s" % (len(notes), notes[0])
    return meta


def cluster(xy, gap_m):
    n = len(xy)
    shapes = [Shape([rs]) for rs in xy]
    bbs = [s.bbox for s in shapes]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            a, b = bbs[i], bbs[j]
            if a[0] - gap_m > b[2] or b[0] - gap_m > a[2] or a[1] - gap_m > b[3] or b[1] - gap_m > a[3]:
                continue
            if find(i) != find(j) and shapes[i].distance_to(xy[j], gap_m) <= gap_m:
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return list(groups.values())


def save_geojson(path, ring_lists, props):
    coords = [poly for rings in ring_lists for poly in esri_to_geojson_polys(rings)]
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": props,
                                                     "geometry": {"type": "MultiPolygon", "coordinates": coords}}]}
    with open(path, "w") as fh:
        json.dump(fc, fh)


BANDS_MI = [0.25, 0.5, 1, 2, 3, 5, 10]


def summarize(dists_m, radius_mi):
    inside_n = sum(1 for d in dists_m if d == 0)
    within = sorted(d for d in dists_m if 0 < d <= radius_mi * M_PER_MI)
    bands, lo = [], 0
    for hi in BANDS_MI + [math.inf]:
        top = min(hi, radius_mi)
        n = sum(1 for d in within if lo * M_PER_MI < d <= top * M_PER_MI)
        bands.append({"from_mi": lo, "to_mi": top, "count": n})
        if hi >= radius_mi:
            break
        lo = hi
    return {"inside_footprint": inside_n, "within_radius": len(within), "bands": bands,
            "nearest_ft": [round(d * FT_PER_M) for d in within[:5]]}


def cmd_receptors(args):
    if args.footprint:
        lonlat_polys, props = geojson_rings(args.footprint)
        if not lonlat_polys:
            die("no geometry in %s" % args.footprint)
        bb = bbox_union([bbox_of(r) for r in lonlat_polys])
        lat0, lon0 = (bb[1] + bb[3]) / 2, (bb[0] + bb[2]) / 2
        pins = {str(x) for x in props.get("pins") or []}
        origin = "footprint %s (%s acres, %d parcel(s))" % (args.footprint, props.get("acres", "?"), len(pins))
    elif args.point:
        lat0, lon0 = args.point
        lonlat_polys, pins, props = None, set(), {}
        bb = (lon0, lat0, lon0, lat0)
        origin = "point %s, %s (point distance; pass --footprint for edge-to-edge)" % (lat0, lon0)
    else:
        die("give --footprint FILE or --point LAT LON")
    key = args.parish or props.get("parish") or detect_parish(lat0, lon0)
    p = parish(key)
    proj = Proj(lat0, lon0)
    if lonlat_polys:
        fp = Shape([proj.rings(rs) for rs in lonlat_polys])
    else:
        fp = Shape([[[(0.0, 0.0), (0.01, 0.0), (0.0, 0.01)]]])
    radius_m = args.radius_mi * M_PER_MI
    env = envelope_filter(proj.pad(bb, radius_m))
    # Tax agents ("RYAN, LLC - C/O") appear on many unrelated parcels, so they are not owner matches.
    own = [o.strip().upper() for x in props.get("owners") or [] for o in x.split(";")
           if o.strip() and "C/O" not in o.upper() and len(o.strip()) >= 6]
    res = {"parish": key, "parish_name": p["name"], "origin": origin, "radius_mi": args.radius_mi,
           "occupied_structures": [], "residential_zoning": [], "notes": []}

    def dist(geom):
        if "x" in geom:
            return fp.distance_to(proj.xy(geom["x"], geom["y"]), radius_m)
        return fp.distance_to(proj.rings(geom["rings"]), radius_m)

    for s in p.get("structures") or []:
        try:
            oid_field = oid_field_of(s["url"])
            fields = [oid_field, s.get("owner_field")] + (s.get("private_fields") or [] if args.private else [])
            feats = query(s["url"], s["base_where"], env, fields=",".join(dict.fromkeys(x for x in fields if x)))
            res_ids = set(get_json(s["url"] + "/query", dict(env, where="(%s) AND (%s)" % (s["base_where"], s["residential_where"]),
                                                              returnIdsOnly="true")).get("objectIds") or [])
        except SourceDown as e:
            res["notes"].append("%s unavailable: %s" % (s["label"], e))
            continue
        resid, other, near = [], [], []
        facility_owned = 0
        for f in feats:
            g = f.get("geometry")
            if not g:
                continue
            d = dist(g)
            oid = f["attributes"].get(oid_field)
            # Small buildings owned by the facility itself are guard shacks and outbuildings, not homes.
            if oid in res_ids and own and s.get("owner_field"):
                bo = (f["attributes"].get(s["owner_field"]) or "").upper()
                if any(o in bo for o in own):
                    res_ids.discard(oid)
                    facility_owned += 1
            (resid if oid in res_ids else other).append(d)
            if not args.private:
                f["attributes"].pop(s.get("owner_field"), None)
            if args.private and oid in res_ids and d <= radius_m:
                near.append((d, {k: fmtv(v, None) for k, v in f["attributes"].items() if k != oid_field and fmtv(v, None) not in (None, "")}))
        row = {"label": s["label"], "source_url": s["url"], "authority": s["authority"], "vintage": vintage(s["url"]),
               "basis": s["residential_basis"], "residential": summarize(resid, args.radius_mi),
               "other_within_radius": sum(1 for d in other if 0 < d <= radius_m),
               "other_inside_footprint": sum(1 for d in other if d == 0),
               "facility_owned_small_buildings": facility_owned}
        if args.private:
            row["nearest_private"] = [dict(a, ft=round(d * FT_PER_M)) for d, a in sorted(near, key=lambda t: t[0])[:args.top]]
        res["occupied_structures"].append(row)

    pl = p["parcels"]
    zsrc = [z for z in p.get("zoning") or [] if z.get("residential_codes")]
    parcels_cache = None
    for z in zsrc:
        try:
            ztypes = field_types(z["url"])
            where = "%s IN (%s)" % (z["code_field"], ",".join(sql_lit(c, ztypes.get(z["code_field"])) for c in z["residential_codes"]))
            zones = [(fmtv(f["attributes"].get(z["code_field"]), None), f["geometry"]["rings"])
                     for f in query(z["url"], where, env) if (f.get("geometry") or {}).get("rings")]
            if parcels_cache is None:
                ptypes = field_types(pl["url"])
                pfields = list(dict.fromkeys(sum(([v] if isinstance(v, str) else v for k, v in pl["field_map"].items()
                                                  if k in ("pin", "owner", "situs")), [])))
                parcels_cache = [(canon(f["attributes"], pl["field_map"], ptypes), f["geometry"]["rings"])
                                 for f in query(pl["url"], spatial=env, fields=",".join(pfields), max_records=pl["max_records"])
                                 if (f.get("geometry") or {}).get("rings")]
        except SourceDown as e:
            res["notes"].append("%s unavailable: %s" % (z["label"], e))
            continue
        zone_d = [dist({"rings": zr}) for _, zr in zones]
        zbb = [bbox_of(zr) for _, zr in zones]
        dists, near = [], []
        for a, rings in parcels_cache:
            if str(a.get("pin")) in pins:
                continue
            ip = interior_point(rings)
            code = next((zones[i][0] for i in range(len(zones))
                         if zbb[i][0] <= ip[0] <= zbb[i][2] and zbb[i][1] <= ip[1] <= zbb[i][3] and inside(ip, zones[i][1])), None)
            if code is None:
                continue
            d = dist({"rings": rings})
            dists.append(d)
            if args.private and d <= radius_m:
                near.append((d, {"pin": a.get("pin"), "owner": a.get("owner"), "situs": a.get("situs"), "zone": code}))
        row = {"label": z["label"], "source_url": z["url"], "authority": z["authority"], "vintage": vintage(z["url"]),
               "residential_codes": z["residential_codes"], "parcels": summarize(dists, args.radius_mi),
               "nearest_residential_district_ft": round(min(zone_d) * FT_PER_M) if zone_d else None,
               "parcel_source": pl["url"]}
        if zone_d and min(zone_d) == 0:
            row["note"] = "a residential zoning district touches or overlaps the footprint"
        if args.private:
            row["nearest_private"] = [dict(a, ft=round(d * FT_PER_M)) for d, a in sorted(near, key=lambda t: t[0])[:args.top]]
        res["residential_zoning"].append(row)
    if p.get("zoning_gap"):
        res["notes"].append(p["zoning_gap"])
    return res


def cmd_health(args):
    keys = [args.parish] if args.parish else [k for k, v in REG["parishes"].items() if v.get("status") != "unprobed"]
    out = []
    for key in keys:
        p = parish(key)
        layers = [("parcels", p["parcels"])]
        layers += [("owner", s) for s in p.get("owner_sources") or []]
        if p.get("owner_fallback"):
            layers.append(("owner-fallback", p["owner_fallback"]))
        layers += [("zoning", z) for z in p.get("zoning") or []]
        layers += [("structures", s) for s in p.get("structures") or []]
        if p.get("addresses"):
            layers.append(("addresses", p["addresses"]))
        for role, spec in layers:
            row = {"parish": key, "role": role, "source_url": spec["url"], "authority": spec["authority"]}
            try:
                info = layer_info(spec["url"], cache=False)
                row["name"] = info.get("name")
                row["max_records"] = info.get("maxRecordCount")
                row["count"] = count(spec["url"], cache=False)
                row["vintage"] = vintage(spec["url"])
                row["status"] = "ok"
                vc = spec.get("vintage_check")
                if vc and vc["method"] == "max_date":
                    st = json.dumps([{"statisticType": "max", "onStatisticField": vc["field"], "outStatisticFieldName": "m"}])
                    r = get_json(spec["url"] + "/query", {"where": "1=1", "outStatistics": st}, cache=False)
                    m = (r.get("features") or [{}])[0].get("attributes", {}).get("m")
                    if m:
                        row["currency"] = "max %s = %s" % (vc["field"], iso(m) if isinstance(m, (int, float)) else m)
                elif vc and vc["method"] == "recent_count":
                    since = (datetime.date.today() - datetime.timedelta(days=vc["days"])).isoformat()
                    n = None
                    for form in ("%s >= DATE '%s'", "%s >= TIMESTAMP '%s 00:00:00'"):
                        try:
                            n = count(spec["url"], form % (vc["field"], since), cache=False)
                            break
                        except SourceDown:
                            continue
                    row["currency"] = "%s parcels with %s since %s" % (n, vc["field"], since)
                if spec.get("stale"):
                    row["status"] = "stale"
                    row["stale"] = spec["stale"]
            except SourceDown as e:
                row["status"] = "DOWN"
                row["error"] = str(e)
            out.append(row)
    return {"layers": out}


# ---------------------------------------------------------------- text output

def show_parcel(r):
    print("Parcel %s  (%s acres%s)" % (r["pin"], r["acres"], ", %d polygons" % r["polygons"] if r.get("polygons", 1) > 1 else ""))
    print("  source: %s [%s; %s]" % (r["source_url"], r["authority"], r["vintage"]))
    for k, v in r["attributes"].items():
        print("  %-14s %s" % (k, v))
    o = r.get("owner") or {}
    print("  OWNER: %s" % (o.get("name") or "(not in source)"))
    if o.get("mail"):
        print("  owner mail:    %s" % o["mail"])
    if o.get("source_url"):
        print("    from %s [%s; %s]" % (o["source_url"], o["authority"], o["vintage"]))
    if o.get("stale"):
        print("    STALE: %s" % o["stale"])
    for k, v in (o.get("extra") or {}).items():
        print("    %-12s %s" % (k, v))
    for k, v in (o.get("raw") or {}).items():
        print("    %-12s %s" % (k, v))
    for s in o.get("skipped") or []:
        print("    skipped: %s" % s)
    if r.get("assessor_link"):
        print("  assessor: %s" % r["assessor_link"])
    if "zoning" in r:
        if r.get("parcel_zoning_attr") is not None or "parcel_zoning_attr" in r:
            print("  parcel-layer zoning attribute: %s (not authoritative; see districts below)" % (r.get("parcel_zoning_attr") or "blank"))
        if r["zoning"]:
            print("  ZONING (districts intersecting the parcel):")
            for z in r["zoning"]:
                share = ("%.0f%%" % (100 * z["share"]) if z["share"] >= 0.005 else "<1%") if z["share"] else "edge"
                desc = (" - " + z["desc"]) if z.get("desc") else ""
                extra = (" " + json.dumps(z["extra"])) if z["extra"] else ""
                print("    %-6s %s%s%s  [%s, %s]" % (share, z["code"], desc, extra, z["label"], z["authority"]))
        else:
            print("  ZONING: no district in the registered layers")
        for n in r.get("zoning_notes") or []:
            print("    note: %s" % n)


def show(cmd, res):
    if cmd in ("at", "address", "parcel"):
        print("%s  %s" % (res["parish_name"], res.get("point") or res.get("pin")))
        g = res.get("geocode")
        if g:
            print("geocode: %s -> %s; used %s" % (g["input"], g["census_match"], g["used"]))
            if g.get("parish_address"):
                print("  parish address point: %s (%s ft from the Census point)" % (g["parish_address"], g["census_offset_ft"]))
        for r in res["parcels"]:
            print()
            show_parcel(r)
        for k in ("note", "assessor_link", "wrote"):
            if res.get(k):
                print("%s: %s" % (k, res[k]))
    elif cmd == "owner":
        print("%s: %d parcel(s), %.1f acres, owner matching %r" % (res["parish_name"], res["count"], res["total_acres"], res["pattern"]))
        print("owner source: %s [%s; %s]" % (res["owner_source"], res["authority"], res["vintage"]))
        if res.get("stale"):
            print("STALE: %s" % res["stale"])
        for r in res["parcels"]:
            print("  %-14s %-40.40s %8.2f ac  %s%s" % (r["pin"], r["owner"] or "", r["acres"],
                  ("%.2f mi  " % r["miles_from_near"]) if "miles_from_near" in r else "", r.get("situs") or ""))
    elif cmd == "footprint":
        print("wrote %s: %d polygon(s), %d parcel number(s), %.1f acres" % (res["wrote"], res["parcels"], len(res["pins"]), res["acres"]))
        print("selection: %s" % res["selection"])
        print("owners: %s" % "; ".join(res["owners"]))
        print("pins: %s" % ", ".join(map(str, res["pins"])))
        for k in ("cluster_rule", "clusters_found", "parcels_dropped", "missing_pins", "detached_parts", "detached_rule", "owner_source", "vintage", "stale", "geometry_notes"):
            if res.get(k) not in (None, [], ""):
                print("%s: %s" % (k, res[k]))
    elif cmd == "receptors":
        print("%s - receptors within %s mi of %s" % (res["parish_name"], res["radius_mi"], res["origin"]))
        print("\n(a) OCCUPIED RESIDENTIAL STRUCTURES (whatever the zoning)")
        for s in res["occupied_structures"]:
            show_summary(s, s["residential"])
            print("    other buildings within radius: %d; other buildings inside footprint: %d; "
                  "small buildings owned by the footprint owner (moved to other): %d"
                  % (s["other_within_radius"], s["other_inside_footprint"], s["facility_owned_small_buildings"]))
            print("    basis: %s" % s["basis"])
            show_private(s)
        print("\n(b) RESIDENTIALLY ZONED PARCELS")
        if not res["residential_zoning"]:
            print("  none available from the registered layers")
        for z in res["residential_zoning"]:
            show_summary(z, z["parcels"])
            nd = z["nearest_residential_district_ft"]
            print("    residential codes: %s; nearest residential district edge: %s%s"
                  % (", ".join(z["residential_codes"]), "%d ft" % nd if nd is not None else "none in search area",
                     ("  (" + z["note"] + ")") if z.get("note") else ""))
            show_private(z)
        for n in res["notes"]:
            print("note: %s" % n)
    elif cmd == "health":
        for r in res["layers"]:
            print("%-11s %-15s %-6s %-15s %s" % (r["parish"], r["role"], r["status"], r["authority"], r["source_url"]))
            if r["status"] == "DOWN":
                print("    %s" % r["error"])
                continue
            print("    %s: %s records (max %s/request); %s%s" % (r.get("name"), r.get("count"), r.get("max_records"),
                  r.get("vintage"), ("; " + r["currency"]) if r.get("currency") else ""))
            if r.get("stale"):
                print("    STALE: %s" % r["stale"])


def show_summary(s, summ):
    print("  %s  [%s; %s]" % (s["label"], s["authority"], s["vintage"]))
    print("    %s" % s["source_url"])
    print("    inside footprint: %d; within radius: %d" % (summ["inside_footprint"], summ["within_radius"]))
    print("    " + "; ".join("%g-%g mi: %d" % (b["from_mi"], b["to_mi"], b["count"]) for b in summ["bands"]))
    if summ["nearest_ft"]:
        print("    nearest (edge to edge): %s" % ", ".join("%d ft (%.2f mi)" % (f, f / 5280) for f in summ["nearest_ft"]))


def show_private(s):
    for r in s.get("nearest_private") or []:
        print("      %6d ft  %s" % (r["ft"], ", ".join("%s=%s" % (k, v) for k, v in r.items() if k != "ft")))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--parish", help="registry key (st-charles, ascension, st-james, ...); default: detect from the point")
    # Repeat the globals on each subcommand so they work on either side of it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--parish", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    s = sub.add_parser("at", help="parcel, owner and zoning at a point")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--out", help="also write the parcel polygon as GeoJSON")

    s = sub.add_parser("address", help="geocode an address, then `at`")
    s.add_argument("address")
    s.add_argument("--out")

    s = sub.add_parser("parcel", help="look up by parcel number (needs --parish)")
    s.add_argument("pin")
    s.add_argument("--out")

    for name in ("owner", "footprint"):
        s = sub.add_parser(name, help="parcels by owner name" if name == "owner" else "merge an owner's or listed parcels into GeoJSON")
        if name == "owner":
            s.add_argument("pattern", help="substring(s) of the owner name, '|' separated, case-insensitive")
        else:
            s.add_argument("--owner", help="owner substring(s), '|' separated")
            s.add_argument("--pins", help="comma-separated parcel numbers (needs --parish)")
            s.add_argument("--out", default="footprint.geojson")
            s.add_argument("--gap-ft", type=float, default=150, help="parcels this close count as one site (roads, ditches)")
            s.add_argument("--all-clusters", action="store_true")
            s.add_argument("--polygons-only", action="store_true",
                           help="keep only the clustered polygons, even when that splits a parcel number")
        s.add_argument("--near", nargs=2, type=float, metavar=("LAT", "LON"))
        s.add_argument("--radius-mi", type=float, default=2.0)
        s.add_argument("--bbox", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))

    s = sub.add_parser("receptors", help="nearest homes and residentially zoned parcels")
    s.add_argument("--footprint", help="GeoJSON from `footprint` or `at --out`")
    s.add_argument("--point", nargs=2, type=float, metavar=("LAT", "LON"))
    s.add_argument("--radius-mi", type=float, default=1.0)
    s.add_argument("--private", action="store_true", help="include addresses and names (household use only)")
    s.add_argument("--top", type=int, default=10)

    s = sub.add_parser("health", help="reachability, counts and currency of every registered layer")
    s.add_argument("which", nargs="?", metavar="parish")

    args = ap.parse_args()
    if args.cmd == "health" and args.which:
        args.parish = args.which
    fn = {"at": cmd_at, "address": cmd_address, "parcel": cmd_parcel, "owner": cmd_owner,
          "footprint": cmd_footprint, "receptors": cmd_receptors, "health": cmd_health}[args.cmd]
    if args.cmd == "parcel" and not args.parish:
        die("parcel needs --parish")
    try:
        res = fn(args)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    if args.json:
        if "parcels" in res and isinstance(res["parcels"], list):
            for r in res["parcels"]:
                if isinstance(r, dict):
                    r.pop("rings", None)
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
