#!/usr/bin/env python3
"""FEMA National Risk Index for the census tract and parish/county at a point,
from FEMA's public NRI ArcGIS services (no key).

Usage:
  nri.py --lat 29.8446 --lon -90.2805 [--top 6] [--release march-2023] [--json]

Hazards are ranked by expected annual loss (EAL, dollars per year). A hazard's
risk score and rating are percentiles *within that hazard* across all U.S.
tracts (or counties), so they say how this place compares with others for that
hazard, not which hazard is largest here. Quote "highest risk" with the measure.
--release march-2023 reads FEMA's archived v1.19.0 layers, the release most
2023-2025 permit applications cite; ratings and hazard names differ from the current one.
Exit status: 0 checked, 2 a source failed, 4 no tract at the point (out of coverage).
Stdlib only.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services"
HAZARDS = {
    "AVLN": "Avalanche", "CFLD": "Coastal flooding", "CWAV": "Cold wave", "DRGT": "Drought",
    "ERQK": "Earthquake", "HAIL": "Hail", "HWAV": "Heat wave", "HRCN": "Hurricane",
    "ISTM": "Ice storm", "IFLD": "Inland flooding", "LNDS": "Landslide", "LTNG": "Lightning",
    "SWND": "Strong wind", "TRND": "Tornado", "TSUN": "Tsunami", "VLCN": "Volcanic activity",
    "WFIR": "Wildfire", "WNTW": "Winter weather",
}
# March 2023 called inland flooding "riverine flooding" (RFLD), with a narrower definition.
RELEASES = {
    "current": {"tracts": f"{BASE}/National_Risk_Index_Census_Tracts/FeatureServer/0",
                "counties": f"{BASE}/National_Risk_Index_Counties/FeatureServer/0", "hazards": HAZARDS},
    "march-2023": {"tracts": f"{BASE}/National_Risk_Index_Census_Tracts_(March_2023)/FeatureServer/0",
                   "counties": f"{BASE}/National_Risk_Index_Counties_(March_2023)/FeatureServer/0",
                   "hazards": {("RFLD" if k == "IFLD" else k): ("Riverine flooding" if k == "IFLD" else v)
                               for k, v in HAZARDS.items()}},
}
SUMMARY = ("NRI_VER", "STATEABBRV", "COUNTY", "COUNTYTYPE", "STCOFIPS", "POPULATION", "BUILDVALUE",
           "RISK_SCORE", "RISK_RATNG", "EAL_VALT", "EAL_RATNG", "SOVI_SCORE", "SOVI_RATNG",
           "RESL_SCORE", "RESL_RATNG")


def fields(hazards):
    return SUMMARY + ("TRACTFIPS",) + tuple(f"{h}_{s}" for h in hazards for s in ("EALT", "RISKS", "RISKR", "AFREQ"))


class SourceError(Exception):
    pass


def arcgis_query(layer_url, params):
    """ArcGIS reports errors as HTTP 200 with an {"error": ...} body; treat that,
    or a body without "features", as a failure."""
    q = dict(params, f="json", returnGeometry="false")
    req = urllib.request.Request(f"{layer_url}/query?{urllib.parse.urlencode(q)}",
                                 headers={"User-Agent": "bayou-nri"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
    except (OSError, ValueError) as e:
        raise SourceError(f"{layer_url}: {e}") from e
    if "error" in body or "features" not in body:
        raise SourceError(f"{layer_url}: {body.get('error', 'no features key in response')}")
    return [f["attributes"] for f in body["features"]]


def profile(a, top, hazards):
    rows = []
    for h, name in hazards.items():
        eal = a.get(f"{h}_EALT")
        rows.append({"hazard": name, "code": h, "eal_usd": round(eal) if eal is not None else None,
                     "risk_score_within_hazard": round(a[f"{h}_RISKS"], 1) if a.get(f"{h}_RISKS") is not None else None,
                     "risk_rating_within_hazard": a.get(f"{h}_RISKR"), "annual_frequency": a.get(f"{h}_AFREQ")})
    rows.sort(key=lambda r: -(r["eal_usd"] or 0))
    out = {k.lower(): a.get(k) for k in SUMMARY}
    out["hazards_by_eal"] = rows[:top]
    out["highest_rated_hazards"] = [r["hazard"] for r in rows
                                    if r["risk_rating_within_hazard"] == best_rating(rows)]
    return out


ORDER = ["Very High", "Relatively High", "Relatively Moderate", "Relatively Low", "Very Low"]


def best_rating(rows):
    found = [r["risk_rating_within_hazard"] for r in rows if r["risk_rating_within_hazard"] in ORDER]
    return min(found, key=ORDER.index) if found else None


def show(label, p):
    print(f"\n== {label}")
    print(f"Composite risk {p['risk_ratng']} (score {p['risk_score']:.1f}); expected annual loss "
          f"${p['eal_valt']:,.0f} ({p['eal_ratng']}); social vulnerability {p['sovi_ratng']}; "
          f"community resilience {p['resl_ratng']}")
    print("Hazards by expected annual loss (score/rating are within-hazard national percentiles):")
    for r in p["hazards_by_eal"]:
        score = f"{r['risk_score_within_hazard']:.1f}" if r["risk_score_within_hazard"] is not None else "n/a"
        print(f"  {r['hazard']:<18} EAL ${r['eal_usd'] or 0:>14,.0f}/yr   risk {score:>5}  {r['risk_rating_within_hazard']}")
    print(f"Highest-rated hazard(s): {', '.join(p['highest_rated_hazards']) or 'none rated'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--top", type=int, default=6, help="hazards to list, ranked by EAL (default 6)")
    ap.add_argument("--release", choices=sorted(RELEASES), default="current",
                    help="NRI release to read (default current; march-2023 is v1.19.0)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rel = RELEASES[a.release]
    hz, flds = rel["hazards"], fields(rel["hazards"])
    result = {"query": {"lat": a.lat, "lon": a.lon, "release": a.release}, "retrieved": time.strftime("%Y-%m-%d"),
              "sources": {"tracts": rel["tracts"], "counties": rel["counties"]}}
    status = 0
    try:
        tracts = arcgis_query(rel["tracts"], {"geometry": f"{a.lon},{a.lat}", "geometryType": "esriGeometryPoint",
                                       "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                       "outFields": ",".join(flds)})
        if not tracts:
            result["status"] = "out_of_coverage"
            status = 4
        else:
            t = tracts[0]
            result["tract"] = dict(profile(t, a.top, hz), tractfips=t["TRACTFIPS"])
            counties = arcgis_query(rel["counties"], {"where": f"STCOFIPS='{t['STCOFIPS']}'",
                                                      "outFields": ",".join(f for f in flds if f != "TRACTFIPS")})
            result["county"] = profile(counties[0], a.top, hz) if counties else None
            result["status"] = "found"
    except SourceError as e:
        result.update(status="source_failed", error=str(e))
        status = 2

    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"FEMA National Risk Index at {a.lat}, {a.lon} (retrieved {result['retrieved']})")
        if result["status"] == "source_failed":
            print(f"SOURCE FAILED, not checked ({result['error']})")
        elif result["status"] == "out_of_coverage":
            print("OUT OF COVERAGE: no NRI census tract at this point (offshore, or outside the U.S.).")
        else:
            t = result["tract"]
            print(f"NRI version {t['nri_ver']}")
            show(f"Census tract {t['tractfips']} ({t['county']} {t['countytype']}, {t['stateabbrv']}), "
                 f"population {t['population']:,}", t)
            if result["county"]:
                c = result["county"]
                show(f"{c['county']} {c['countytype']}, {c['stateabbrv']} (county level)", c)
            else:
                print(f"\nCounty record {t['stcofips']} not found in the county layer.")
    sys.exit(status)


if __name__ == "__main__":
    main()
