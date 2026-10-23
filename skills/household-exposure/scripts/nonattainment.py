#!/usr/bin/env python3
"""Clean Air Act area designations at a point, from EPA's Green Book map service
(OAR_OAQPS/NonattainmentAreas, no key).

Usage:
  nonattainment.py --lat 30.0951 --lon -90.9925 [--radius-mi 25] [--json]

Checks every NAAQS layer, including the revoked 1-hour and 1997 8-hour ozone
standards (EPA keeps their areas in the service): a revoked
nonattainment designation can still carry anti-backsliding obligations (NNSR offsets,
major-source thresholds), so a "maintenance" answer under the current standards is
not the whole story. Each layer reports one of: designated, none_at_point, or
source_failed. A failed layer is never folded into "none".
Exit status: 0 checked, 2 a layer failed, 4 point outside the layer's coverage.
Stdlib only.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

SERVICE = "https://gispub.epa.gov/arcgis/rest/services/OAR_OAQPS/NonattainmentAreas/MapServer"
DV_TABLES = "https://www.epa.gov/air-trends/air-quality-design-values"
LAYERS = {
    0: "Ozone 8-hr (1997 standard, revoked 2015)",
    1: "Ozone 8-hr (2008 standard)",
    2: "Ozone 8-hr (2015 standard)",
    3: "Lead (2008 standard)",
    4: "SO2 1-hr (2010 standard)",
    5: "PM2.5 24-hr (2006 standard)",
    6: "PM2.5 annual (1997 standard)",
    7: "PM2.5 annual (2012 standard)",
    8: "PM10 (1987 standard)",
    9: "CO (1971 standard)",
    10: "Ozone 1-hr (1979 standard, revoked 2005)",
    11: "NO2 (1971 standard)",
}
FIELDS = ("area_name", "state_abbreviation", "pollutant_name", "current_status", "classification",
          "classification_citation", "designation_citation", "designation_effective_date",
          "redesignation_final_citation", "redesignation_effective_date", "design_value",
          "dv_units", "dv_years", "meets_naaqs", "composite_id")
# Rough boxes for the states and territories the layer covers. Outside them a
# "none" would mean nothing, so it is reported as out of coverage.
US_BOXES = ((24.0, 50.0, -125.5, -66.5), (51.0, 72.0, -180.0, -129.0), (18.5, 22.5, -161.0, -154.5),
            (17.5, 18.6, -67.5, -64.4), (13.0, 21.0, 144.0, 146.5), (-14.6, -10.9, -171.2, -168.0))


class SourceError(Exception):
    pass


def arcgis_query(layer_url, params):
    """All features for a query. ArcGIS reports errors as HTTP 200 with an
    {"error": ...} body; treat that, or a body without "features", as a failure."""
    out, offset = [], 0
    while True:
        q = dict(params, f="json", resultOffset=offset)
        req = urllib.request.Request(f"{layer_url}/query?{urllib.parse.urlencode(q)}",
                                     headers={"User-Agent": "bayou-nonattainment"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.load(r)
        except (OSError, ValueError) as e:
            raise SourceError(f"{layer_url}: {e}") from e
        if "error" in body or "features" not in body:
            raise SourceError(f"{layer_url}: {body.get('error', 'no features key in response')}")
        out += [f["attributes"] for f in body["features"]]
        if not body.get("exceededTransferLimit") or not body["features"]:
            return out
        offset += len(body["features"])


def point_params(lat, lon, radius_mi=None):
    p = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
         "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(FIELDS), "returnGeometry": "false"}
    if radius_mi:
        p.update(distance=radius_mi, units="esriSRUnit_StatuteMile")
    return p


def day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000)) if ms else None


def tidy(a):
    a = dict(a)
    for k in ("designation_effective_date", "redesignation_effective_date"):
        a[k] = day(a.get(k))
    return a


def check(lat, lon, radius_mi, service=SERVICE):
    results = []
    for lid, label in LAYERS.items():
        url = f"{service}/{lid}"
        row = {"layer": lid, "standard": label}
        try:
            here = [tidy(a) for a in arcgis_query(url, point_params(lat, lon))]
            near = []
            if radius_mi:
                ids = {a["composite_id"] for a in here}
                near = [tidy(a) for a in arcgis_query(url, point_params(lat, lon, radius_mi))
                        if a["composite_id"] not in ids]
        except SourceError as e:
            row.update(status="source_failed", error=str(e))
            results.append(row)
            continue
        row.update(status="designated" if here else "none_at_point", at_point=here,
                   within_radius_not_at_point=near)
        results.append(row)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius-mi", type=float, default=25,
                    help="also list designated areas within this distance (default 25; 0 to skip)")
    ap.add_argument("--service", default=SERVICE, help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    covered = any(s <= a.lat <= n and w <= a.lon <= e for s, n, w, e in US_BOXES)
    result = {"query": {"lat": a.lat, "lon": a.lon, "radius_mi": a.radius_mi},
              "coverage": "in_coverage" if covered else "out_of_coverage",
              "source": f"EPA Green Book nonattainment areas, {SERVICE}",
              "retrieved": time.strftime("%Y-%m-%d"), "layers": []}
    if covered:
        result["layers"] = check(a.lat, a.lon, a.radius_mi, a.service)
    failed = [r for r in result["layers"] if r["status"] == "source_failed"]

    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"CAA area designations at {a.lat}, {a.lon} (EPA Green Book, retrieved {result['retrieved']})")
        if not covered:
            print("OUT OF COVERAGE: the point is outside the U.S. states and territories the layer maps. "
                  "No designation was checked.")
        for r in result["layers"]:
            print(f"\n{r['standard']}: ", end="")
            if r["status"] == "source_failed":
                print(f"SOURCE FAILED, not checked ({r['error']})")
                continue
            if not r["at_point"]:
                print("not in a nonattainment or maintenance area at this point")
            for x in r["at_point"]:
                print(f"{x['current_status']} - {x['area_name']}, {x['state_abbreviation']}"
                      f" | classification {x['classification'] or 'none'} ({x['classification_citation'] or 'no citation'})")
                print(f"    designated {x['designation_effective_date'] or '?'} ({x['designation_citation'] or 'no citation'})", end="")
                if x["redesignation_final_citation"]:
                    print(f"; redesignated to maintenance {x['redesignation_effective_date']} "
                          f"({x['redesignation_final_citation']})", end="")
                print()
                if x["design_value"] is not None:
                    # Baton Rouge 2008 ozone: the layer said 0.069 for 2023-2025 while EPA's
                    # official table said 0.073, so the layer value is a lead, never a citation.
                    print(f"    map-layer design value {x['design_value']:.3f} {x['dv_units']} ({x['dv_years']}), "
                          f"meets NAAQS: {x['meets_naaqs']} -- unofficial; cite EPA's design value tables")
            for x in r.get("within_radius_not_at_point", []):
                print(f"    within {a.radius_mi:g} mi: {x['current_status']} - {x['area_name']}, "
                      f"{x['state_abbreviation']} ({x['classification'] or 'no classification'})")
        print(f"\nDesign values: cite EPA's official tables ({DV_TABLES}), not the map layer. Their 'Other "
              "Violations' sheet lists monitors violating a standard in areas never designated nonattainment.")
        if failed:
            print(f"\n{len(failed)} of {len(LAYERS)} layers failed; rerun before reporting attainment for them.")
    sys.exit(2 if failed else 0 if covered else 4)


if __name__ == "__main__":
    main()
