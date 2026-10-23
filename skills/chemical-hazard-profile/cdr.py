#!/usr/bin/env python3
"""What a site reported making or importing under TSCA Chemical Data Reporting
(2024 CDR cycle: production volumes for 2020-2023, uses for 2023), from EPA's
public CSV release.

Usage:
  cdr.py --frs 110018861793                      # by EPA FRS registry ID
  cdr.py --site "union carbide" --state LA       # site or parent company name
  cdr.py --near 29.98 -90.45 --radius-mi 3       # sites within a radius
  cdr.py --cas 75-21-8 --state LA                # which sites report a chemical
  cdr.py ... --uses                              # add industrial and consumer/commercial uses
  cdr.py ... --json

Every volume is one of three things: pounds, "CBI" (claimed confidential), or not
reported (blank). CBI and blank are never zero and are never added into a total.
The public file is a floor: sites whose identity is CBI are missing from site
searches, and volumes under the reporting threshold are not reported at all.

The release (14.4 MB zip, April 2026) is downloaded once into ~/.cache/bayou/tsca-cdr/.
Exit status: 0 checked, 2 the release could not be read, 3 a download over 100 MB
is waiting for --yes.
Stdlib only.
"""
import argparse
import csv
import html
import io
import json
import math
import os
import re
import shutil
import sys
import urllib.request
import zipfile

URL = "https://www.epa.gov/system/files/other-files/2026-04/2024-cdr-public-csv-data.zip"
PAGE = "https://www.epa.gov/chemical-data-reporting/access-cdr-data"
CACHE = os.path.expanduser("~/.cache/bayou/tsca-cdr")
ZIP = os.path.join(CACHE, os.path.basename(URL))
CONFIRM_BYTES = 100 * 1024 * 1024
MANUFACTURE = "2024 CDR Manufacture-Import Information.csv"
INDUSTRIAL = "2024 CDR Industrial Processing and Use Information.csv"
CONSUMER = "2024 CDR Consumer and Commercial Use Information.csv"
YEARS = ("2023", "2022", "2021", "2020")
# The release's display text lost "≥" in encoding ("? 90%"); the code columns are
# intact, so labels come from the codes.
WORKERS = {"W1": "<10", "W2": "10-<25", "W3": "25-<50", "W4": "50-<100", "W5": "100-<500",
           "W6": "500-<1,000", "W7": "1,000-<10,000", "W8": ">=10,000"}
MAX_CONC = {"M1": "<1%", "M2": "1-<30%", "M3": "30-<60%", "M4": "60-<90%", "M5": ">=90%"}
BYPRODUCT = {"B1": "0%", "B2": ">0-<50%", "B3": ">=50-<100%", "B4": "100%"}
SPECIAL = {"CBI": "CBI", "NKRA": "not known (NKRA)", "": "not reported"}


def ensure_zip(yes=False, refresh=False):
    if os.path.exists(ZIP) and not refresh:
        return ZIP
    req = urllib.request.Request(URL, method="HEAD", headers={"User-Agent": "Mozilla/5.0 bayou-cdr"})
    with urllib.request.urlopen(req, timeout=60) as r:
        size = int(r.headers.get("Content-Length") or 0)
    os.makedirs(CACHE, exist_ok=True)
    free = shutil.disk_usage(CACHE).free
    msg = f"{os.path.basename(URL)}: {size / 1e6:.1f} MB to {CACHE} ({free / 1e9:.1f} GB free)"
    if size > CONFIRM_BYTES and not yes:
        print(f"DOWNLOAD WAITING: {msg}. Rerun with --yes to fetch it.", file=sys.stderr)
        sys.exit(3)
    print(f"downloading {msg}", file=sys.stderr)
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 bayou-cdr"})
    with urllib.request.urlopen(req, timeout=600) as r, open(ZIP + ".part", "wb") as f:
        shutil.copyfileobj(r, f)
    zipfile.ZipFile(ZIP + ".part").testzip()
    os.replace(ZIP + ".part", ZIP)
    return ZIP


def rows(z, name):
    with z.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="cp1252", errors="replace", newline=""))


def volume(v):
    v = (v or "").strip()
    if re.fullmatch(r"[\d,]+(\.\d+)?", v):
        return float(v.replace(",", ""))
    return SPECIAL.get(v, v)


def coded(code, table):
    code = (code or "").strip()
    return table.get(code) or SPECIAL.get(code, code)


def miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def matches(x, a):
    if a.frs and x["EPA FACILITY REGISTRY ID"].strip() != a.frs:
        return False
    if a.tsca_id and x["EPA-TSCA PROGRAM ID"].strip().upper() != a.tsca_id.upper():
        return False
    if a.cas and x["CHEMICAL ID"].strip() != a.cas:
        return False
    if a.state and x["SITE STATE"].strip().upper() != a.state.upper():
        return False
    if a.city and x["SITE CITY"].strip().upper() != a.city.upper():
        return False
    if a.site:
        names = " ".join(x[k] for k in ("SITE NAME", "STANDARDIZED PARENT COMPANY NAME", "DOMESTIC PARENT COMPANY NAME"))
        if a.site.lower() not in names.lower():
            return False
    if a.near:
        try:
            d = miles(a.near[0], a.near[1], float(x["SITE LATITUDE"]), float(x["SITE LONGITUDE"]))
        except ValueError:
            return False
        if d > a.radius_mi:
            return False
        x["_distance_mi"] = round(d, 2)
    return True


def chemical(x):
    return {"chemical": x["CHEMICAL NAME"], "id": x["CHEMICAL ID"], "id_type": x["CHEMICAL ID TYPE"],
            "activity": SPECIAL.get(x["ACTIVITY"], x["ACTIVITY"]),
            "pv_lb": {y: volume(x[f"{y} PV"]) for y in YEARS},
            "pv_2023_domestic_lb": volume(x["2023 DOMESTIC PV"]), "pv_2023_import_lb": volume(x["2023 IMPORT PV"]),
            "national_aggregate_2023_lb": x["2023 NATIONALLY AGGREGATED PV"] or None,
            "never_at_site": SPECIAL.get(x["CHEM NEVER AT SITE"], x["CHEM NEVER AT SITE"]),
            "workers_likely_exposed": coded(x["WORKERS CODE"], WORKERS),
            "max_concentration": coded(x["MAX CONC CODE"], MAX_CONC),
            "pct_byproduct": coded(x["PCT BYP CODE"], BYPRODUCT),
            "physical_forms": x["PHYSICAL FORM(S) LIST"] or None}


def add_uses(z, sites):
    """Use rows join on TSCA program ID + chemical ID: the FRS IDs in the use files
    were saved in scientific notation (1.10065E+11) and no longer match."""
    keys = {(s["tsca_program_id"], c["id"]): c for s in sites.values() for c in s["chemicals"]}
    for c in keys.values():
        c["industrial_uses"], c["consumer_commercial_uses"] = [], []
    for x in rows(z, INDUSTRIAL):
        c = keys.get((x["EPA-TSCA PROGRAM ID"], x["CHEMICAL ID"]))
        if c is not None and x["IND TYPE CODE"]:
            c["industrial_uses"].append({k: x[f] or None for k, f in (
                ("operation", "INDUSTRIAL TYPE OF PROCESS OR USE OPERATION"), ("sector", "INDUSTRIAL SECTOR"),
                ("function", "INDUSTRIAL FUNCTION CATEGORY"), ("pct_pv", "IND PV PCT"),
                ("sites", "INDUSTRIAL SITES"), ("workers", "INDUSTRIAL WORKERS REASONABLY LIKELY EXPOSED"))})
    for x in rows(z, CONSUMER):
        c = keys.get((x["EPA-TSCA PROGRAM ID"], x["CHEMICAL ID"]))
        if c is not None and x.get("C / C PROD CAT CODE"):
            c["consumer_commercial_uses"].append({k: x.get(f) or None for k, f in (
                ("product_category", "CONSUMER / COMMERCIAL PRODUCT CATEGORY"),
                ("function", "CONSUMER / COMMERCIAL FUNCTION CATEGORY"), ("use", "CONS AND/OR COMM USE"),
                ("children", "USED IN PROD FOR CHILDREN"), ("pct_pv", "C / C PV PCT"))})


def fmt_pv(v):
    return f"{v:,.0f} lb" if isinstance(v, float) else v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frs", help="EPA FRS registry ID (bayou:epa-frs-crosswalk)")
    ap.add_argument("--tsca-id", help="EPA-TSCA program ID, e.g. TSCA122445")
    ap.add_argument("--site", help="substring of site or parent company name")
    ap.add_argument("--cas", help="CAS number or accession number")
    ap.add_argument("--state")
    ap.add_argument("--city")
    ap.add_argument("--near", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--radius-mi", type=float, default=3)
    ap.add_argument("--uses", action="store_true", help="add 2023 industrial and consumer/commercial use rows")
    ap.add_argument("--yes", action="store_true", help="allow a download over 100 MB")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not any((a.frs, a.tsca_id, a.site, a.cas, a.state, a.city, a.near)):
        ap.error("give at least one of --frs, --tsca-id, --site, --cas, --state, --city, --near")

    try:
        z = zipfile.ZipFile(ensure_zip(a.yes, a.refresh))
        sites, cbi_identity_rows = {}, 0
        for x in rows(z, MANUFACTURE):
            if x["SITE NAME"] == "CBI":
                cbi_identity_rows += a.cas is not None and x["CHEMICAL ID"].strip() == a.cas
                continue
            if not matches(x, a):
                continue
            key = x["EPA-TSCA PROGRAM ID"]
            s = sites.setdefault(key, {
                "site": x["SITE NAME"], "address": html.unescape(", ".join(v for v in (x["SITE ADDRESS LINE1"], x["SITE CITY"],
                                                                         x["SITE STATE"], x["SITE POSTAL CODE"]) if v)),
                "parish_county": x["SITE COUNTY / PARISH"] or None, "lat": x["SITE LATITUDE"] or None,
                "lon": x["SITE LONGITUDE"] or None, "frs_id": x["EPA FACILITY REGISTRY ID"] or None,
                "tsca_program_id": key, "parent": x["STANDARDIZED PARENT COMPANY NAME"] or None,
                "naics": x["SITE NAICS CODE 1"] or None, "distance_mi": x.get("_distance_mi"), "chemicals": []})
            s["chemicals"].append(chemical(x))
        if a.uses and sites:
            add_uses(z, sites)
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        print(f"SOURCE FAILED: CDR release not read ({e}). Nothing was checked.", file=sys.stderr)
        sys.exit(2)

    for s in sites.values():
        pv = [c["pv_lb"]["2023"] for c in s["chemicals"]]
        s["counts_2023"] = {"with_volume": sum(isinstance(v, float) for v in pv), "volume_cbi": pv.count("CBI"),
                            "not_reported": pv.count("not reported")}
        s["chemicals"].sort(key=lambda c: (not isinstance(c["pv_lb"]["2023"], float),
                                           -(c["pv_lb"]["2023"] if isinstance(c["pv_lb"]["2023"], float) else 0),
                                           c["chemical"]))
    result = {"source": URL, "source_page": PAGE, "cycle": "2024 CDR (production 2020-2023, uses 2023)",
              "filters": {k: v for k, v in vars(a).items()
                          if v and k not in ("json", "yes", "refresh") and (k != "radius_mi" or a.near)},
              "sites": sorted(sites.values(), key=lambda s: (s["distance_mi"] or 0, s["site"]))}
    if a.cas:
        result["rows_nationwide_for_this_chemical_with_site_identity_cbi"] = cbi_identity_rows
    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    print(f"TSCA CDR 2024 cycle. Filters: {result['filters']}")
    if not sites:
        print("\nNo non-confidential site matches. This is not evidence the site makes nothing: sites whose "
              "identity is CBI are hidden, and volumes under the reporting threshold are not reported.")
    for s in result["sites"]:
        dist = f" | {s['distance_mi']} mi" if s["distance_mi"] is not None else ""
        print(f"\n== {s['site']} | {s['address']} ({s['parish_county'] or 'parish not given'}){dist}")
        print(f"   FRS {s['frs_id']} | {s['tsca_program_id']} | parent {s['parent']} | {s['naics']}")
        n = s["counts_2023"]
        print(f"   {len(s['chemicals'])} chemicals; 2023 volume given for {n['with_volume']}, "
              f"CBI for {n['volume_cbi']}, not reported for {n['not_reported']}")
        for c in s["chemicals"]:
            pv = c["pv_lb"]
            print(f"   {c['chemical'][:60]:<60} {c['id']:<12} {c['activity']:<11} 2023 {fmt_pv(pv['2023']):>16}"
                  f" | 2020-22 {', '.join(str(fmt_pv(pv[y])) for y in ('2022', '2021', '2020'))}")
            print(f"      national 2023 {c['national_aggregate_2023_lb'] or '-'} lb | workers {c['workers_likely_exposed']}"
                  f" | max conc {c['max_concentration']} | never at site: {c['never_at_site']}")
            for u in c.get("industrial_uses", [])[:6]:
                print(f"      industrial: {u['operation']} | {u['sector']} | {u['function']}")
            if a.uses and not c["industrial_uses"] and not c["consumer_commercial_uses"]:
                print("      uses: no use rows matched this site and chemical")
            for u in c.get("consumer_commercial_uses", [])[:6]:
                print(f"      {u['use'] or 'consumer/commercial'}: {u['product_category']} | {u['function']}"
                      + (" | in children's products" if (u["children"] or "").lower() == "yes" else ""))
    if a.cas:
        print(f"\nRows for {a.cas} nationwide from sites whose identity is CBI (not listed above, location unknown): "
              f"{cbi_identity_rows}")
    print("\nCBI and 'not reported' volumes are not zeros; do not total them. The list is a floor: CBI-identity "
          "sites and sub-threshold volumes are absent.")


if __name__ == "__main__":
    main()
