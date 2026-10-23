#!/usr/bin/env python3
"""CDC/ATSDR Social Vulnerability Index 2022 for the census tract at a point (and,
with --radius-mi, every tract touching that radius), plus its county, from CDC's
public ArcGIS service (no key).

Usage:
  svi.py --lat 30.0951 --lon -90.9925 [--radius-mi 1] [--json]

Percentile ranks (RPL_*) are national: 0.90 means more vulnerable than 90% of
U.S. tracts. CDC publishes -999 where a value could not be computed; it is
reported as null, never as a rank. SVI is tract-level, EJScreen block-group-level,
so the two can disagree for the same address.
Exit status: 0 checked, 2 a source failed, 4 no tract at the point (out of coverage).
Stdlib only.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

SERVICE = ("https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
           "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer")
TRACTS, COUNTIES = f"{SERVICE}/2", f"{SERVICE}/1"
THEMES = {"RPL_THEMES": "Overall", "RPL_THEME1": "Socioeconomic status",
          "RPL_THEME2": "Household characteristics", "RPL_THEME3": "Racial and ethnic minority status",
          "RPL_THEME4": "Housing type and transportation"}
# Estimated percentages shown beside the ranks; CDC's 16 SVI variables plus race detail.
PCTS = {"EP_POV150": "below 150% of poverty", "EP_UNEMP": "unemployed", "EP_HBURD": "housing cost-burdened",
        "EP_NOHSDP": "no high-school diploma", "EP_UNINSUR": "uninsured", "EP_AGE65": "aged 65+",
        "EP_AGE17": "aged 17 or under", "EP_DISABL": "with a disability", "EP_SNGPNT": "single-parent households",
        "EP_LIMENG": "limited English", "EP_MINRTY": "racial/ethnic minority", "EP_AFAM": "Black/African American",
        "EP_HISP": "Hispanic/Latino", "EP_MUNIT": "in 10+ unit structures", "EP_MOBILE": "mobile homes",
        "EP_CROWD": "crowded housing", "EP_NOVEH": "no vehicle", "EP_GROUPQ": "in group quarters"}
FIELDS = ("FIPS", "LOCATION", "COUNTY", "ST_ABBR", "STCNTY", "E_TOTPOP", "M_TOTPOP", "F_TOTAL") + tuple(THEMES) + tuple(PCTS)


class SourceError(Exception):
    pass


def arcgis_query(layer_url, params):
    """All features for a query. ArcGIS reports errors as HTTP 200 with an
    {"error": ...} body; treat that, or a body without "features", as a failure."""
    out, offset = [], 0
    while True:
        q = dict(params, f="json", returnGeometry="false", resultOffset=offset)
        req = urllib.request.Request(f"{layer_url}/query?{urllib.parse.urlencode(q)}",
                                     headers={"User-Agent": "bayou-svi"})
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


def clean(a):
    return {k: (None if isinstance(v, (int, float)) and v == -999 else v) for k, v in a.items()}


def point(lat, lon, radius_mi=None):
    p = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
         "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(FIELDS)}
    if radius_mi:
        p.update(distance=radius_mi, units="esriSRUnit_StatuteMile")
    return p


def fmt_rank(v):
    return "n/a (-999)" if v is None else f"{v:.2f}"


def show(a, detail=True, among="tracts"):
    print(f"\n== {a['LOCATION']} (FIPS {a['FIPS']}), population {a['E_TOTPOP']:,} ±{a['M_TOTPOP'] or 0:,}")
    for k, name in THEMES.items():
        print(f"  {name:<34} percentile rank among U.S. {among} {fmt_rank(a.get(k))}")
    print(f"  Flags (indicators at or above the 90th percentile): {a['F_TOTAL'] if a['F_TOTAL'] is not None else 'n/a'}")
    if detail:
        vals = [f"{a[k]:.1f}% {label}" for k, label in PCTS.items() if a.get(k) is not None]
        print("  " + "; ".join(vals))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius-mi", type=float, default=0, help="also list every tract touching this radius")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    result = {"query": {"lat": a.lat, "lon": a.lon, "radius_mi": a.radius_mi},
              "retrieved": time.strftime("%Y-%m-%d"), "source": SERVICE, "vintage": "SVI 2022 (ACS 2018-2022)",
              "ranking": "national (U.S.-wide) percentile ranks"}
    status = 0
    try:
        here = [clean(x) for x in arcgis_query(TRACTS, point(a.lat, a.lon))]
        if not here:
            result["status"], status = "out_of_coverage", 4
        else:
            result["status"] = "found"
            result["tract"] = here[0]
            county = arcgis_query(COUNTIES, {"where": f"STCNTY='{here[0]['STCNTY']}'", "outFields": ",".join(FIELDS)})
            result["county"] = clean(county[0]) if county else None
            if a.radius_mi:
                near = [clean(x) for x in arcgis_query(TRACTS, point(a.lat, a.lon, a.radius_mi))]
                result["tracts_touching_radius"] = sorted(near, key=lambda x: -(x["RPL_THEMES"] or -1))
    except SourceError as e:
        result.update(status="source_failed", error=str(e))
        status = 2

    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"CDC/ATSDR SVI 2022 at {a.lat}, {a.lon} (national percentile ranks; retrieved {result['retrieved']})")
        if result["status"] == "source_failed":
            print(f"SOURCE FAILED, not checked ({result['error']})")
        elif result["status"] == "out_of_coverage":
            print("OUT OF COVERAGE: no SVI census tract at this point (offshore, or outside the U.S.).")
        else:
            show(result["tract"])
            if result["county"]:
                show(result["county"], detail=False, among="counties")
            for t in result.get("tracts_touching_radius", []):
                if t["FIPS"] != result["tract"]["FIPS"]:
                    print(f"  within {a.radius_mi:g} mi: {t['LOCATION']} overall {fmt_rank(t['RPL_THEMES'])}, "
                          f"minority {t['EP_MINRTY']}%, below 150% poverty {t['EP_POV150']}%")
    sys.exit(status)


if __name__ == "__main__":
    main()
