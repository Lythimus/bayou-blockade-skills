#!/usr/bin/env python3
"""Colonial waterbird nesting colonies near a point, from the Gulfwide Avian
Colony Monitoring data (The Water Institute / CPRA, AWS Open Data bucket
s3://twi-aviandata, no credentials).

Usage:
  avian_colonies.py --lat 29.58 --lon -92.35 [--radius-mi 10] [--imagery] [--photos N] [--json]

Nest counts come from the program's curated per-colony totals (the ReadMe's
"final and best estimates"), not from summing photo rows: overlapping photos,
May+June combining and the BestForBPE flag make a raw row sum wrong.
Stdlib only.
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BUCKET = "https://twi-aviandata.s3.amazonaws.com"
DOT = "avian_monitoring/dotting_information"
SOURCES = {
    # 2010-2021 curated totals; has no coordinates.
    "totals": f"{DOT}/Colibri2010-21ColonyTotalsMayJuneCombined_8Nov22.xlsx",
    # Generated summary with coordinates; used only to place the curated totals.
    "coords": f"{DOT}/processed_data/SummaryFileGenerated.xlsx",
    # 2022-2023 summary (Louisiana only), with coordinates.
    "y2023": f"{DOT}/processed_data/SummaryFileGenerated2023.xlsx",
    # Photo-level rows, used only to point at the dotted screenshots and photos.
    "photos": f"{DOT}/processed_data/avianmonitoring_2010-2021_Nulls.csv.gz",
    "photos2023": f"{DOT}/processed_data/avianmonitoring_2022-2023_Nulls.csv.gz",
}
CACHE = os.path.expanduser("~/.cache/bayou/avian-colonies")
MAX_AGE_DAYS = 90
SURVEY_YEARS = "2010-2013, 2015, 2018, 2021, 2022-2023 (2024: imagery only, not yet counted)"

# From tblSpeciesCodes in ColibriReadMe_2010-2021_Final.pdf.
SPECIES = {
    "AMAV": "American Avocet", "AMCO": "American Coot", "AMOY": "American Oystercatcher",
    "ANHI": "Anhinga", "AWPE": "American White Pelican", "BBPL": "Black-bellied Plover",
    "BBWD": "Black-bellied Whistling-Duck", "BCNH": "Black-crowned Night-Heron",
    "BLSK": "Black Skimmer", "BLTE": "Black Tern", "BNST": "Black-necked Stilt",
    "BRNO": "Brown Noddy", "BRPE": "Brown Pelican", "BWTE": "Blue-winged Teal",
    "CAEG": "Cattle Egret", "CANG": "Canada Goose", "CARO": "Caspian/Royal Tern",
    "CATE": "Caspian Tern", "COGA": "Common Gallinule", "COMO": "Common Moorhen",
    "COTE": "Common Tern", "CRCA": "Crested Caracara", "DAIB": "Glossy/White-faced Ibis",
    "DCCO": "Double-crested Cormorant", "DUCK": "Duck sp.", "FICR": "Fish Crow",
    "FOCO": "Forster's/Common Tern", "FOTE": "Forster's Tern", "FUWD": "Fulvous Whistling-Duck",
    "GBHE": "Great Blue Heron", "GBTE": "Gull-billed Tern", "GLIB": "Glossy Ibis",
    "GREG": "Great Egret", "GRFL": "Greater Flamingo", "GRHE": "Green Heron",
    "GTGR": "Great-tailed Grackle", "HERG": "Herring Gull", "LAGU": "Laughing Gull",
    "LBBG": "Lesser Black-backed Gull", "LBHE": "Little Blue Heron", "LEBI": "Least Bittern",
    "LETE": "Least Tern", "MABO": "Masked Booby", "MAFR": "Magnificent Frigatebird",
    "MAGO": "Marbled Godwit", "MODU": "Mottled Duck", "NECO": "Neotropic Cormorant",
    "NSHO": "Northern Shoveler", "OSPR": "Osprey", "RBGU": "Ring-billed Gull",
    "REEG": "Reddish Egret", "REKN": "Red Knot", "ROSA": "Royal or Sandwich Tern",
    "ROSP": "Roseate Spoonbill", "ROST": "Roseate Tern", "ROYT": "Royal Tern",
    "RSHA": "Red-shouldered Hawk", "RUTU": "Ruddy Turnstone", "SATE": "Sandwich Tern",
    "SBDO": "Short-billed Dowitcher", "SNEG": "Snowy Egret", "SONO": "Sooty Tern or Brown Noddy",
    "SOTE": "Sooty Tern", "TRHE": "Tricolored Heron", "TRSN": "Tricolored Heron or Snowy Egret",
    "ULGU": "Unknown large gull", "ULTE": "Unknown large tern", "UNCO": "Cormorant sp.",
    "UNCR": "Unknown crow", "UNDU": "Unknown duck", "UNEG": "Unknown egret",
    "UNGT": "Unknown gull or tern", "UNGU": "Unknown gull", "UNHG": "Unknown heron or egret",
    "UNID": "Unidentified bird", "UNNH": "Unknown night-heron", "UNRA": "Unknown rail",
    "UNSB": "Unknown shorebird", "UNSH": "Unknown shorebird", "UNTE": "Unknown tern",
    "UNWA": "Unknown waterbird", "UNWW": "Unknown white wader", "USTE": "Unknown small tern",
    "WADE": "Wader sp.", "WFIB": "White-faced Ibis", "WHEG": "White egret sp.",
    "WHIB": "White Ibis", "WILL": "Willet", "WIPH": "Wilson's Phalarope",
    "WIPL": "Wilson's Plover", "WOST": "Wood Stork", "YCNH": "Yellow-crowned Night-Heron",
}

XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
S3NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def url(key):
    return f"{BUCKET}/{urllib.parse.quote(key)}"


def fetch(name, refresh=False):
    key = SOURCES[name]
    path = os.path.join(CACHE, os.path.basename(key))
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE_DAYS * 86400
    if refresh or not fresh:
        os.makedirs(CACHE, exist_ok=True)
        try:
            with urllib.request.urlopen(url(key), timeout=120) as r:
                data = r.read()
        except OSError as e:
            if os.path.exists(path):
                print(f"warning: refresh of {key} failed ({e}); using cached copy", file=sys.stderr)
                return path
            raise
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return path


def read_xlsx(path):
    """First sheet as a list of dicts keyed by the header row."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(XNS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(XNS + "t")))
    out, header = [], None
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(XNS + "row"):
        cells = {}
        for c in row.iter(XNS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v, t = c.find(XNS + "v"), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(XNS + "t"))
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            cells[col] = val
        if header is None:
            header = cells
            continue
        out.append({header[k]: v for k, v in cells.items() if k in header})
    return out


def read_csv_gz(path):
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def miles(lat1, lon1, lat2, lon2):
    p = math.radians
    h = (math.sin(p(lat2 - lat1) / 2) ** 2
         + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(p(lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def load_colonies(refresh=False):
    """{colony name: {lat, lon, state, region, counts: {year: {species: (nests, birds)}}}}"""
    colonies = {}

    def colony(name, state, region, lat, lon):
        c = colonies.setdefault(name, {"name": name, "state": state, "region": region,
                                       "lat": None, "lon": None, "counts": {}})
        if c["lat"] is None and lat not in (None, ""):
            c["lat"], c["lon"] = float(lat), float(lon)
        return c

    for r in read_xlsx(fetch("coords", refresh)):
        colony(r["ColonyName"], r["State"], r["GeoRegion"], r.get("Latitude_y"), r.get("Longitude_y"))
    for r in read_xlsx(fetch("totals", refresh)):
        c = colony(r["ColonyName"], r["State"], r["GeoRegion"], None, None)
        c["counts"].setdefault(r["Year"], {})[r["SpeciesCode"].upper()] = (num(r["Nests"]), num(r["Birds"]))
    for r in read_xlsx(fetch("y2023", refresh)):
        c = colony(r["ColonyName"], r["State"], r["GeoRegion"], r.get("Latitude"), r.get("Longitude"))
        # The 2022-2023 summary is per survey date, so a species flown in May and June appears
        # twice; keep the larger count rather than adding (the program's convention for
        # 2010-2021 was to pick or combine per species, which this file does not record).
        sp = c["counts"].setdefault(r["Year"], {})
        code = r["SpeciesCode"].upper()
        old = sp.get(code, (0.0, 0.0))
        sp[code] = (max(old[0], num(r["Nests"])), max(old[1], num(r["Birds"])))
    return colonies


def photos_for(names, refresh=False):
    """Best photo evidence per colony and year: the dotted screenshot and source photo
    with the most nests among BestForBPE photos."""
    nests, shots = {}, {}
    for src in ("photos", "photos2023"):
        for r in read_csv_gz(fetch(src, refresh)):
            name = r["ColonyName"]
            if name not in names or r.get("BestForBPE", "Y") == "N":
                continue
            k = (name, r["Year"], r["HighResImage_new"] or r["uid"].split("#")[0])
            nests[k] = nests.get(k, 0) + num(r["total_nests"])
            shots.setdefault(k, r.get("candidate_screenshot") or r.get("screenshot_new") or "")
    out = {}
    for (name, year, photo), n in nests.items():
        out.setdefault(name, []).append({"year": year, "nests_in_photo": n, "photo": photo,
                                         "dotted_screenshot": shots[(name, year, photo)]})
    for v in out.values():
        v.sort(key=lambda p: (-int(p["year"]), -p["nests_in_photo"]))
    return out


def s3_list(prefix, delimiter="/"):
    """(common prefixes, [(key, size)]) for one S3 prefix, following pagination."""
    prefixes, objects, token = [], [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "delimiter": delimiter}
        if token:
            q["continuation-token"] = token
        with urllib.request.urlopen(f"{BUCKET}/?{urllib.parse.urlencode(q)}", timeout=60) as r:
            root = ET.fromstring(r.read())
        prefixes += [p.text for p in root.iter(S3NS + "Prefix") if p.text != prefix]
        objects += [(c.find(S3NS + "Key").text, int(c.find(S3NS + "Size").text))
                    for c in root.iter(S3NS + "Contents")]
        token = root.findtext(S3NS + "NextContinuationToken")
        if not token:
            return prefixes, objects


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def tfw_origin(key):
    """Upper-left (lat, lon) from an ESRI world file: lines 5 and 6 are x and y."""
    with urllib.request.urlopen(url(key), timeout=60) as r:
        lines = r.read().decode().split()
    return float(lines[5]), float(lines[4])


def imagery_2024(names, known, lat, lon, radius_mi):
    """2024 imagery for the named colonies, plus 2024 folders for colonies absent from the
    counted data (new or renamed sites), placed by their first frame's world file and kept
    if inside the radius. Region folder spellings in the bucket differ from GeoRegion
    ("Vermillion Bay", "Atachafalya Bay"), so match on colony name only."""
    root = "avian_monitoring/high_resolution_photos/2024/"
    wanted = {norm(n): n for n in names}
    known = {norm(n) for n in known}
    found, extra = {}, []
    regions, _ = s3_list(root)
    for region in regions:
        folders, _ = s3_list(region)
        for folder in folders:
            folder_name = folder.rstrip("/").rsplit("/", 1)[-1]
            name = wanted.get(norm(folder_name))
            if not name and norm(folder_name) in known:
                continue
            _, objs = s3_list(folder, delimiter="")
            tifs = [(k, s) for k, s in objs if k.lower().endswith(".tif")]
            entry = {
                "folder": folder,
                "frames": [{"key": k, "mb": round(s / 1e6, 1)} for k, s in tifs if "/Base Map/" not in k],
                "mosaics": [{"key": k, "mb": round(s / 1e6, 1)} for k, s in tifs if "/Base Map/" in k],
            }
            if name:
                found[name] = entry
                continue
            tfw = next((k for k, _ in objs if k.lower().endswith(".tfw") and "/Base Map/" not in k), None)
            if not tfw:
                continue
            flat, flon = tfw_origin(tfw)
            d = miles(lat, lon, flat, flon)
            if d <= radius_mi:
                extra.append(dict(entry, colony=folder_name, lat=flat, lon=flon, distance_mi=round(d, 1)))
    return found, sorted(extra, key=lambda e: e["distance_mi"])


def summarize(c, dist):
    years = sorted(c["counts"])
    nests_by_year = {y: sum(n for n, _ in c["counts"][y].values()) for y in years}
    active = [y for y in years if nests_by_year[y] > 0]
    peak = {}
    for y in years:
        for code, (n, _) in c["counts"][y].items():
            if n > peak.get(code, (0, ""))[0]:
                peak[code] = (n, y)
    return {
        "colony": c["name"], "state": c["state"], "region": c["region"],
        "lat": c["lat"], "lon": c["lon"], "distance_mi": round(dist, 1),
        "years_surveyed": years, "years_with_nests": active,
        "nests_by_year": {y: int(nests_by_year[y]) for y in years},
        "latest_year_with_nests": active[-1] if active else None,
        "breeding_species_peak": sorted(
            [{"code": k, "species": SPECIES.get(k, k), "peak_nests": int(n), "peak_year": y}
             for k, (n, y) in peak.items()], key=lambda s: -s["peak_nests"]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius-mi", type=float, default=10)
    ap.add_argument("--nearest", type=int, default=3,
                    help="also report this many nearest colonies outside the radius (default 3)")
    ap.add_argument("--photos", type=int, default=0, help="list up to N evidence photos per colony")
    ap.add_argument("--imagery", action="store_true", help="list 2024 TIF frames and mosaics (no download)")
    ap.add_argument("--refresh", action="store_true", help="re-download the source tables")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    every = load_colonies(a.refresh)
    colonies = [c for c in every.values() if c["lat"] is not None]
    ranked = sorted(((miles(a.lat, a.lon, c["lat"], c["lon"]), c) for c in colonies), key=lambda t: t[0])
    inside = [summarize(c, d) for d, c in ranked if d <= a.radius_mi]
    outside = [summarize(c, d) for d, c in ranked if d > a.radius_mi][:a.nearest]
    names = {s["colony"] for s in inside + outside}
    photos = photos_for(names, a.refresh) if a.photos else {}
    imagery, imagery_only = (imagery_2024(names, every, a.lat, a.lon, a.radius_mi)
                             if a.imagery else ({}, []))
    for s in inside + outside:
        if a.photos:
            s["photos"] = [dict(p, photo_url=url(p["photo"]),
                                dotted_screenshot_url=url(p["dotted_screenshot"]) if p["dotted_screenshot"] else None)
                           for p in photos.get(s["colony"], [])[:a.photos]]
        if a.imagery:
            s["imagery_2024"] = imagery.get(s["colony"])

    result = {"query": {"lat": a.lat, "lon": a.lon, "radius_mi": a.radius_mi},
              "survey_years": SURVEY_YEARS, "within_radius": inside, "nearest_outside_radius": outside,
              "imagery_only_2024_within_radius": imagery_only,
              "source": "Gulfwide Avian Colony Monitoring, The Water Institute / CPRA, s3://twi-aviandata",
              "retrieved": time.strftime("%Y-%m-%d")}
    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    print(f"Colonies within {a.radius_mi:g} mi of {a.lat}, {a.lon}: {len(inside)}")
    print(f"Survey years in the data: {SURVEY_YEARS}")
    for label, group in (("WITHIN RADIUS", inside), ("NEAREST OUTSIDE RADIUS", outside)):
        if not group:
            continue
        print(f"\n== {label}")
        for s in group:
            print(f"\n{s['colony']} ({s['state']}, {s['region']}) {s['lat']:.4f}, {s['lon']:.4f}"
                  f" | {s['distance_mi']} mi")
            print("  nests by year: " + ", ".join(f"{y}: {n}" for y, n in s["nests_by_year"].items()))
            top = [f"{x['species']} {x['peak_nests']} ({x['peak_year']})"
                   for x in s["breeding_species_peak"] if x["peak_nests"] > 0][:8]
            print("  peak nests by species: " + ("; ".join(top) or "no nests counted in any survey"))
            for p in s.get("photos", []):
                print(f"  photo {p['year']}: {p['nests_in_photo']:.0f} nests | {p['photo_url']}")
                if p["dotted_screenshot_url"]:
                    print(f"    dotted: {p['dotted_screenshot_url']}")
            if a.imagery:
                im = s.get("imagery_2024")
                if not im:
                    print("  2024 imagery: none in the bucket for this colony")
                else:
                    mb = sum(f["mb"] for f in im["frames"])
                    print(f"  2024 imagery: {len(im['frames'])} frames ({mb:.0f} MB total), "
                          f"{len(im['mosaics'])} georeferenced mosaics")
                    for m in im["mosaics"]:
                        print(f"    mosaic {m['mb']:.0f} MB | {m['key']}")
    if imagery_only:
        print("\n== 2024 IMAGERY ONLY (colony not in the counted data; location from first frame's world file)")
        for e in imagery_only:
            mb = sum(f["mb"] for f in e["frames"])
            print(f"\n{e['colony']} ~{e['lat']:.4f}, {e['lon']:.4f} | {e['distance_mi']} mi")
            print(f"  {len(e['frames'])} frames ({mb:.0f} MB total), {len(e['mosaics'])} mosaics | {e['folder']}")


if __name__ == "__main__":
    main()
