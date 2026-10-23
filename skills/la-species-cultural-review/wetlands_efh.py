#!/usr/bin/env python3
"""Essential Fish Habitat (NOAA) and National Wetlands Inventory (USFWS) at and
around a point, from the agencies' public ArcGIS services (no key).

Usage:
  wetlands_efh.py --lat 29.9344 --lon -90.3561 [--efh-radius-mi 1] [--nwi-radius-mi 0.5] [--json]
  wetlands_efh.py ... --only efh|nwi

Each check reports found, none_found or source_failed, and a failed check is never
folded into "none"; nor is a point outside coverage. EFH is reported at the point and, separately, within the radius,
because a bank-side facility point often falls just landward of the near-shore EFH
polygons it discharges or dredges into.
Exit status: 0 checked, 2 a source failed, 4 a check was out of coverage.
Stdlib only.
"""
import argparse
import collections
import json
import sys
import time
import urllib.parse
import urllib.request

EFH = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/EFH/FeatureServer/0"
NWI = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0"
NWI_SOURCE = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Data_Source/MapServer/3"
COUNCILS = {
    "GFMC": "Gulf of Mexico Fishery Management Council", "AHMS": "NMFS Atlantic Highly Migratory Species",
    "SAFMC": "South Atlantic FMC", "MAFMC": "Mid-Atlantic FMC", "NEFMC": "New England FMC",
    "CFMC": "Caribbean FMC", "PFMC": "Pacific FMC", "NPFMC": "North Pacific FMC",
    "WPFMC": "Western Pacific FMC", "PHMS": "NMFS Pacific Highly Migratory Species",
}
# Rough boxes around U.S. states, territories and their offshore waters. Outside them
# neither layer maps anything, so an empty answer is out of coverage, not "none".
US_BOXES = ((23.0, 50.0, -128.0, -65.0), (50.0, 73.0, -180.0, -129.0), (17.0, 24.0, -162.0, -153.0),
            (16.5, 19.5, -68.5, -63.5), (12.5, 21.5, 143.5, 147.0), (-15.0, -10.5, -172.0, -167.5))
# Cowardin system letter, the first character of the NWI ATTRIBUTE code.
SYSTEMS = {"M": "Marine", "E": "Estuarine", "R": "Riverine", "L": "Lacustrine", "P": "Palustrine"}


class SourceError(Exception):
    pass


def arcgis_query(layer_url, params):
    """All features for a query. ArcGIS reports errors as HTTP 200 with an
    {"error": ...} body; treat that, or a body without "features", as a failure."""
    out, offset = [], 0
    while True:
        q = dict(params, f="json", resultOffset=offset)
        req = urllib.request.Request(f"{layer_url}/query?{urllib.parse.urlencode(q)}",
                                     headers={"User-Agent": "bayou-wetlands-efh"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body = json.load(r)
        except (OSError, ValueError) as e:
            raise SourceError(f"{layer_url}: {e}") from e
        if "error" in body or "features" not in body:
            raise SourceError(f"{layer_url}: {body.get('error', 'no features key in response')}")
        out += [f["attributes"] for f in body["features"]]
        if not body.get("exceededTransferLimit") or not body["features"]:
            return out
        offset += len(body["features"])


def point_params(lat, lon, fields, radius_mi=None):
    p = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
         "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "returnGeometry": "false"}
    if radius_mi:
        p.update(distance=radius_mi, units="esriSRUnit_StatuteMile")
    return p


def efh_row(a):
    return {"species_or_fmp": a["SITENAME_L"], "life_stage": a["LIFESTAGE"], "council": a["FMC"],
            "council_name": COUNCILS.get(a["FMC"], a["FMC"]), "fmp_document": (a["FMP_REPORT"] or "").strip() or None}


def efh_check(lat, lon, radius_mi):
    fields = "OBJECTID,SITENAME_L,LIFESTAGE,TYPE,FMC,FMP_REPORT,DATACAVEAT"
    try:
        here = arcgis_query(EFH, point_params(lat, lon, fields))
        near = arcgis_query(EFH, point_params(lat, lon, fields, radius_mi)) if radius_mi else []
    except SourceError as e:
        return {"status": "source_failed", "error": str(e)}
    ids = {a["OBJECTID"] for a in here}
    caveats = sorted({a["DATACAVEAT"].strip() for a in here + near if (a.get("DATACAVEAT") or "").strip()})
    return {"status": "found" if here or near else "none_found",
            "at_point": [efh_row(a) for a in here],
            "within_radius_not_at_point": [efh_row(a) for a in near if a["OBJECTID"] not in ids],
            "radius_mi": radius_mi, "data_caveats": caveats,
            "not_checked": "Habitat Areas of Particular Concern (HAPC) and EFH conservation areas: "
                           "this layer holds EFH extents only."}


def nwi_check(lat, lon, radius_mi):
    fields = "OBJECTID,ATTRIBUTE,WETLAND_TYPE,ACRES"
    try:
        here = arcgis_query(NWI, point_params(lat, lon, fields))
        near = arcgis_query(NWI, point_params(lat, lon, fields, radius_mi)) if radius_mi else []
    except SourceError as e:
        return {"status": "source_failed", "error": str(e)}
    try:
        src, src_error = arcgis_query(NWI_SOURCE, point_params(
            lat, lon, "PROJECT_NAME,IMAGE_YR,IMAGE_DATE,ALL_SCALES,SOURCE_TYPE")), None
    except SourceError as e:
        src, src_error = [], str(e)
    groups = collections.defaultdict(lambda: {"polygons": 0, "whole_polygon_acres": 0.0})
    for a in near or here:
        g = groups[(a["ATTRIBUTE"], a["WETLAND_TYPE"])]
        g["polygons"] += 1
        g["whole_polygon_acres"] += a["ACRES"] or 0
    by_code = [{"cowardin_code": k[0], "system": SYSTEMS.get((k[0] or " ")[0], "?"), "wetland_type": k[1],
                "polygons": v["polygons"], "whole_polygon_acres": round(v["whole_polygon_acres"], 1)}
               for k, v in sorted(groups.items(), key=lambda kv: -kv[1]["whole_polygon_acres"])]
    if not here and not near and not src and not src_error:
        return {"status": "out_of_coverage",
                "detail": "no NWI mapping project covers this point (offshore, or outside NWI's mapped area)"}
    return {"status": "found" if here or near else "none_found",
            "at_point": [{"cowardin_code": a["ATTRIBUTE"], "wetland_type": a["WETLAND_TYPE"],
                          "whole_polygon_acres": round(a["ACRES"] or 0, 1)} for a in here],
            "radius_mi": radius_mi, "polygons_touching_radius": len(near), "by_code": by_code,
            "mapping_source": [{"project": s["PROJECT_NAME"], "image_year": s["IMAGE_YR"], "image_date": s["IMAGE_DATE"],
                                "scale": s["ALL_SCALES"], "imagery": s["SOURCE_TYPE"]} for s in src],
            "mapping_source_error": src_error}


def print_efh(r):
    print("\n== ESSENTIAL FISH HABITAT (NOAA EFH Mapper layer)")
    if r["status"] == "source_failed":
        print(f"SOURCE FAILED, not checked ({r['error']})")
        return
    if r["status"] == "out_of_coverage":
        print(f"OUT OF COVERAGE: {r['detail']}. Not checked.")
        return
    if not r["at_point"]:
        print("At the point: no mapped EFH")
    else:
        print("At the point:")
        for x in r["at_point"]:
            print(f"  {x['species_or_fmp']} | life stage {x['life_stage']} | {x['council_name']} | {x['fmp_document']}")
    if r["radius_mi"]:
        extra = r["within_radius_not_at_point"]
        print(f"Within {r['radius_mi']:g} mi but not at the point: " + ("none" if not extra else ""))
        for x in extra:
            print(f"  {x['species_or_fmp']} | life stage {x['life_stage']} | {x['council_name']}")
    if r["status"] == "none_found":
        print("No EFH is mapped here. The layer's near-shore and upstream extents follow coastline and habitat "
              "data and may not match where NMFS asserts EFH; inland river points are the usual case.")
    for c in r["data_caveats"]:
        print(f"Layer caveat (truncated by the source): {c}")
    print(f"Not checked: {r['not_checked']}")


def print_nwi(r):
    print("\n== NATIONAL WETLANDS INVENTORY (USFWS)")
    if r["status"] == "source_failed":
        print(f"SOURCE FAILED, not checked ({r['error']})")
        return
    if r["status"] == "out_of_coverage":
        print(f"OUT OF COVERAGE: {r['detail']}. Not checked.")
        return
    if r["at_point"]:
        for x in r["at_point"]:
            print(f"At the point: {x['cowardin_code']} ({x['wetland_type']}), polygon {x['whole_polygon_acres']} ac")
    else:
        print("At the point: no NWI polygon")
    if r["radius_mi"]:
        print(f"Polygons touching a {r['radius_mi']:g} mi radius: {r['polygons_touching_radius']}"
              " (acres are whole-polygon totals, not the area inside the radius)")
        for x in r["by_code"]:
            print(f"  {x['cowardin_code']:<10} {x['system']:<11} {x['wetland_type']:<34} "
                  f"{x['polygons']:>4} polygons {x['whole_polygon_acres']:>10,.1f} ac")
    for s in r["mapping_source"]:
        print(f"Mapped from {s['imagery']} imagery dated {s['image_date']} ({s['image_year']}), {s['scale']}, "
              f"project {s['project']}")
    if r["mapping_source_error"]:
        print(f"Mapping source/date: SOURCE FAILED ({r['mapping_source_error']})")
    elif not r["mapping_source"]:
        print("Mapping source/date: not found at this point")
    print("NWI is a planning inventory, not a jurisdictional determination under CWA Section 404.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--efh-radius-mi", type=float, default=1)
    ap.add_argument("--nwi-radius-mi", type=float, default=0.5)
    ap.add_argument("--only", choices=("efh", "nwi"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    result = {"query": {"lat": a.lat, "lon": a.lon}, "retrieved": time.strftime("%Y-%m-%d"),
              "sources": {"efh": EFH, "nwi": NWI, "nwi_source_dates": NWI_SOURCE}}
    covered = any(s <= a.lat <= n and w <= a.lon <= e for s, n, w, e in US_BOXES)
    outside = {"status": "out_of_coverage", "detail": "the point is outside U.S. states, territories and waters"}
    if a.only != "nwi":
        result["efh"] = efh_check(a.lat, a.lon, a.efh_radius_mi) if covered else outside
    if a.only != "efh":
        result["nwi"] = nwi_check(a.lat, a.lon, a.nwi_radius_mi) if covered else outside
    statuses = [result[k]["status"] for k in ("efh", "nwi") if k in result]

    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"EFH and wetlands at {a.lat}, {a.lon} (retrieved {result['retrieved']})")
        if "efh" in result:
            print_efh(result["efh"])
        if "nwi" in result:
            print_nwi(result["nwi"])
    sys.exit(2 if "source_failed" in statuses else 4 if "out_of_coverage" in statuses else 0)


if __name__ == "__main__":
    main()
