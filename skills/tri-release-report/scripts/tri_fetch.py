"""Download EPA TRI Basic Data Files and summarize one facility or a radius.

Usage:
  tri_fetch.py facility --trifd 70079SHLLL1205R [--years 2015-2024] --out DIR
  tri_fetch.py radius --at 30.0,-90.4 | --at TRIFD [--radius 2] [--year 2023]
               [--state LA ...] [--proposed CSV] [--hours 8760] --out DIR

Writes DIR/summary.json (consumed by tri_charts.py) and caches raw files in
DIR/raw/. Run with `uv run --with matplotlib python -I`; stdlib only here.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposed_emissions  # noqa: E402

BULK_URL = "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/{year}_{st}/csv"
CHEM_URL = "https://data.epa.gov/efservice/tri_chem_info/CSV"
FAC_URL = "https://data.epa.gov/efservice/tri_facility/tri_facility_id/{fid}/JSON"
SOURCE = "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/"

# Parent columns 54/57/61 hold pre-2003 undivided quantities and the lettered
# sub-columns hold post-split ones, so the full set (not either alone) sums to
# col 65 in every reporting year.
MEDIA = {
    "air_fugitive": ["51"],
    "air_stack": ["52"],
    "water": ["53"],
    "uic": ["54", "55", "56"],
    "land": ["57", "58", "59", "60", "61", "62", "63", "64"],
}

# Rough lat/lon envelopes. Over-fetching a neighbor is harmless (the distance
# filter discards its rows); missing one silently undercounts, so these err wide.
STATE_BBOX = {
    "LA": (28.85, 33.05, -94.10, -88.75),
    "TX": (25.80, 36.55, -106.70, -93.45),
    "MS": (30.10, 35.05, -91.70, -88.05),
    "AR": (32.95, 36.55, -94.65, -89.60),
    "AL": (30.10, 35.05, -88.50, -84.85),
}

UA = {"User-Agent": "bayou-tri-release-report"}


def num(x):
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def http_get(url, dest):
    """GET to dest; returns False on 404. HEAD is not used: the endpoint 500s on it."""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(dest + ".part", "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    os.replace(dest + ".part", dest)
    return True


def fetch_state_year(raw_dir, year, st):
    dest = os.path.join(raw_dir, f"{year}_{st}.csv")
    if os.path.exists(dest):
        return dest
    return dest if http_get(BULK_URL.format(year=year, st=st), dest) else None


def latest_year(raw_dir, st):
    """Probe downward from last calendar year; EPA publishes each year's data the following autumn."""
    y = dt.date.today().year - 1
    for cand in range(y, y - 4, -1):
        if fetch_state_year(raw_dir, cand, st):
            return cand
    sys.exit(f"No TRI basic data file found for {st} in {y - 3}..{y}")


def load_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        key = {h.split(".")[0].strip(): i for i, h in enumerate(header)}
        for rec in reader:
            if rec:
                yield {k: rec[i] if i < len(rec) else "" for k, i in key.items()}


def row_media(r):
    """Per-medium quantities; asserts they reconcile to the file's own on-site total."""
    m = {name: sum(num(r[c]) for c in cols) for name, cols in MEDIA.items()}
    total = num(r["65"])
    s = sum(m.values())
    assert abs(s - total) <= max(0.01, 1e-6 * total), (
        f"media sum {s} != on-site total {total} for {r['2']} {r['37']} {r['1']}"
    )
    return m, total


def is_grams(r):
    unit = r["50"].strip().lower()
    assert unit in ("pounds", "grams"), f"unexpected unit {r['50']!r}"
    return unit == "grams"


def chem_list(raw_dir):
    dest = os.path.join(raw_dir, "tri_chem_info.csv")
    if not os.path.exists(dest) and not http_get(CHEM_URL, dest):
        sys.exit("Could not download TRI chemical list")
    with open(dest, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def facility_info(fid):
    req = urllib.request.Request(FAC_URL.format(fid=fid), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if not data:
        sys.exit(f"TRI facility {fid} not found in Envirofacts")
    return data[0]


def parse_years(s, default_end, default_span):
    if not s:
        return list(range(default_end - default_span + 1, default_end + 1))
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in s.split(",")]


def flags(r):
    return {
        "carcinogen": r["46"].strip().upper() == "YES",
        "pbt": r["47"].strip().upper() == "YES",
        "pfas": r["48"].strip().upper() == "YES",
    }


def is_form_a(r):
    # Form A certifies the reportable amount is <= 500 lb and discloses no quantity;
    # the bulk file fills its quantity columns with 0.000, which is not a measured zero.
    return r["49"].strip().upper() == "A"


def possible_range_midpoint(m):
    # Form R lets small releases be reported as range codes; the bulk file
    # carries a numeric value with no flag, so exact 5/250/750 is ambiguous.
    return any(v in (5.0, 250.0, 750.0) for v in m.values())


# ---------------------------------------------------------------- facility

def cmd_facility(a):
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    info = facility_info(a.trifd)
    st = info["state_abbr"]
    end = latest_year(raw, st)
    years = parse_years(a.years, end, 10)

    by_year = {}
    chems = {}
    grams = []
    missing = []
    name = info.get("facility_name")
    parent = info.get("parent_co_name")
    lat = lon = None
    for y in years:
        path = fetch_state_year(raw, y, st)
        if not path:
            missing.append(y)
            continue
        yr = {k: 0.0 for k in MEDIA}
        yr.update(total_lb=0.0, carcinogen_lb=0.0, pbt_lb=0.0, pfas_lb=0.0,
                  n_chemicals=0, range_midpoint_rows=0, offsite_lb=0.0, form_a=[])
        for r in load_rows(path):
            if r["2"] != a.trifd:
                continue
            name, parent = r["4"] or name, r["15"] or parent
            if r["12"] and r["13"]:
                lat, lon = float(r["12"]), float(r["13"])
            if is_form_a(r):
                yr["form_a"].append(r["37"])
                continue
            m, total = row_media(r)
            fl = flags(r)
            if is_grams(r):
                grams.append({"year": y, "chemical": r["37"], "onsite_g": total,
                              "air_g": m["air_fugitive"] + m["air_stack"]})
                continue
            yr["n_chemicals"] += 1
            for k in MEDIA:
                yr[k] += m[k]
            yr["total_lb"] += total
            yr["offsite_lb"] += num(r["88"])
            if possible_range_midpoint(m):
                yr["range_midpoint_rows"] += 1
            for f in ("carcinogen", "pbt", "pfas"):
                if fl[f]:
                    yr[f + "_lb"] += total
            c = chems.setdefault(r["37"], {"chemical": r["37"], "cas": r["40"], **fl,
                                           "by_year": {}, "prod_ratio": {}})
            c["by_year"][y] = c["by_year"].get(y, 0.0) + total
            if r["122"]:
                c["prod_ratio"][y] = num(r["122"])
        by_year[y] = yr

    if not any(v["n_chemicals"] for v in by_year.values()) and not grams:
        sys.exit(f"No TRI rows for {a.trifd} in {years[0]}-{years[-1]} ({st})")
    last = max(y for y, v in by_year.items() if v["n_chemicals"]) if by_year else years[-1]
    top = sorted(chems.values(), key=lambda c: -c["by_year"].get(last, 0.0))
    top = [c for c in top if c["by_year"].get(last, 0.0) > 0][: a.top]

    out = {
        "mode": "facility",
        "retrieved": dt.date.today().isoformat(),
        "source": SOURCE,
        "facility": {"trifd": a.trifd, "name": name, "parent": parent, "state": st,
                     "address": info.get("street_address"), "city": info.get("city_name"),
                     "lat": lat, "lon": lon},
        "years": [y for y in years if y in by_year],
        "missing_years": missing,
        "latest_year": last,
        "by_year": {str(y): v for y, v in sorted(by_year.items())},
        "top_chemicals": [
            {"chemical": c["chemical"], "cas": c["cas"], "carcinogen": c["carcinogen"],
             "pbt": c["pbt"], "pfas": c["pfas"], "latest_lb": c["by_year"].get(last, 0.0),
             "period_lb": sum(c["by_year"].values()),
             "prod_ratio_latest": c["prod_ratio"].get(last)}
            for c in top
        ],
        # Single-year jumps are worth a Form R check before anyone quotes them:
        # they are either a real event (upset, expansion) or a reporting error.
        "jumps": sorted(
            [{"chemical": c["chemical"], "carcinogen": c["carcinogen"],
              "prior_lb": c["by_year"].get(last - 1, 0.0), "latest_lb": c["by_year"][last]}
             for c in chems.values()
             if c["by_year"].get(last, 0.0) >= 1000
             and c["by_year"][last] >= 3 * max(1.0, c["by_year"].get(last - 1, 0.0))],
            key=lambda j: -j["latest_lb"]),
        "grams_rows": grams,
    }
    write(a.out, out)


# ---------------------------------------------------------------- radius

def states_for(lat, lon, radius, extra):
    dlat = radius / 69.0
    dlon = radius / (69.0 * max(0.1, math.cos(math.radians(lat))))
    hits = [st for st, (s, n, w, e) in STATE_BBOX.items()
            if lat - dlat <= n and lat + dlat >= s and lon - dlon <= e and lon + dlon >= w]
    out = sorted(set(hits) | set(extra))
    if not out:
        sys.exit("Center is outside the built-in state envelopes; pass --state XX (repeatable).")
    return out


def cmd_radius(a):
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    center_label = a.at
    year = a.year
    extra = list(a.state or [])
    if "," in a.at:
        lat, lon = (float(x) for x in a.at.split(","))
    else:
        info = facility_info(a.at)
        st = info["state_abbr"]
        extra.append(st)
        year = year or latest_year(raw, st)
        lat = lon = None
        path = fetch_state_year(raw, year, st)
        for r in load_rows(path) if path else []:
            if r["2"] == a.at and r["12"] and r["13"]:
                lat, lon = float(r["12"]), float(r["13"])
                break
        if lat is None:
            # Envirofacts pref_longitude is stored unsigned; every TRI site outside
            # the Pacific territories is in the western hemisphere.
            lat, lon = float(info["pref_latitude"]), float(info["pref_longitude"])
            if lon > 0 and st not in ("GU", "MP", "AS"):
                lon = -lon
        center_label = f"{info['facility_name']} ({a.at})"
    states = states_for(lat, lon, a.radius, extra)
    year = year or latest_year(raw, states[0])

    facs = {}
    chems = {}
    grams = []
    fetched = []
    for st in states:
        path = fetch_state_year(raw, year, st)
        if not path:
            print(f"warning: no {year} file for {st}", file=sys.stderr)
            continue
        fetched.append(st)
        for r in load_rows(path):
            try:
                flat, flon = float(r["12"]), float(r["13"])
            except ValueError:
                continue
            d = haversine_miles(lat, lon, flat, flon)
            if d > a.radius:
                continue
            m, total = row_media(r)
            fl = flags(r)
            f = facs.setdefault(r["2"], {"trifd": r["2"], "name": r["4"], "city": r["6"],
                                         "state": r["8"], "parent": r["15"],
                                         "distance_mi": round(d, 2), "onsite_lb": 0.0,
                                         "air_lb": 0.0, "carcinogen_lb": 0.0, "onsite_g": 0.0,
                                         "form_a": 0})
            c = chems.setdefault(r["39"], {"tri_chem_id": r["39"], "chemical": r["37"],
                                           "cas": r["40"], **fl, "onsite_lb": 0.0,
                                           "air_lb": 0.0, "facilities": set(),
                                           "form_a_facilities": set()})
            if is_form_a(r):
                f["form_a"] += 1
                c["form_a_facilities"].add(r["2"])
                continue
            if is_grams(r):
                f["onsite_g"] += total
                grams.append({"trifd": r["2"], "facility": r["4"], "chemical": r["37"],
                              "onsite_g": total})
                continue
            f["onsite_lb"] += total
            f["air_lb"] += m["air_fugitive"] + m["air_stack"]
            if fl["carcinogen"]:
                f["carcinogen_lb"] += total
            c["onsite_lb"] += total
            c["air_lb"] += m["air_fugitive"] + m["air_stack"]
            c["facilities"].add(r["2"])

    for c in chems.values():
        c["n_facilities"] = len(c.pop("facilities"))
        c["n_form_a"] = len(c.pop("form_a_facilities"))
    reported_ids = set(chems)
    # Gram-only (dioxin) entries stay out of the pounds table; grams_rows carries them.
    chems = {k: c for k, c in chems.items() if c["n_facilities"] or c["n_form_a"]}

    proposed = None
    if a.proposed:
        proposed = proposed_emissions.load(
            a.proposed, chem_list(raw), nearby_ids=reported_ids, hours=a.hours)

    out = {
        "mode": "radius",
        "retrieved": dt.date.today().isoformat(),
        "source": SOURCE,
        "center": {"lat": lat, "lon": lon, "label": center_label},
        "radius_mi": a.radius,
        "year": year,
        "states": fetched,
        "facilities": sorted(facs.values(), key=lambda f: -f["onsite_lb"]),
        "chemicals": sorted(chems.values(), key=lambda c: -c["onsite_lb"]),
        "grams_rows": grams,
        "totals": {
            "onsite_lb": sum(f["onsite_lb"] for f in facs.values()),
            "air_lb": sum(f["air_lb"] for f in facs.values()),
            "carcinogen_lb": sum(f["carcinogen_lb"] for f in facs.values()),
            "onsite_g": sum(f["onsite_g"] for f in facs.values()),
            "n_facilities": len(facs),
        },
        "proposed": proposed,
    }
    write(a.out, out)


def write(out_dir, data):
    path = os.path.join(out_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=1, default=str)
    print(path)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facility")
    f.add_argument("--trifd", required=True)
    f.add_argument("--years", help="e.g. 2015-2024 or 2019,2023; default last 10 available")
    f.add_argument("--top", type=int, default=10)
    f.add_argument("--out", required=True)
    r = sub.add_parser("radius")
    r.add_argument("--at", required=True, help="lat,lon or TRIFD")
    r.add_argument("--radius", type=float, default=2.0)
    r.add_argument("--year", type=int)
    r.add_argument("--state", action="append", help="extra state file(s) to include")
    r.add_argument("--proposed", help="proposed-emissions.csv or permit-analysis dir")
    r.add_argument("--hours", type=float, help="operating hours/yr for lb/hr rows")
    r.add_argument("--out", required=True)
    a = p.parse_args()
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    {"facility": cmd_facility, "radius": cmd_radius}[a.cmd](a)


if __name__ == "__main__":
    main()
