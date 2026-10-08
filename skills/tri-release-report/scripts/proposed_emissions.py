"""Load a proposed-emissions CSV and match it against the TRI chemical list.

Schema (same as skills/permit-analysis/templates/proposed-emissions.csv):
  chemical,cas,amount,unit,basis,source_doc,page,ocr_verified

Every row lands in exactly one bucket, so nothing is dropped silently:
  tri_nearby       on the TRI list and reported by a facility in the radius
  tri_not_nearby   on the TRI list, no neighbor reports it (still added as a layer)
  not_tri          criteria pollutant / GHG: not TRI-reportable, never summed in
  unmatched        CAS not on the TRI list and not a recognized criteria pollutant
  unconvertible    unit not understood; amount not usable
Called by tri_fetch.py; can also run standalone for a dry check:
  proposed_emissions.py CSV CHEM_LIST_CSV [--hours N]
"""
import csv
import os
import re
import sys

COLUMNS = ["chemical", "cas", "amount", "unit", "basis", "source_doc", "page", "ocr_verified"]

# Factor to pounds per year. lb/hr needs operating hours and is handled separately.
TO_LB_YR = {
    "tpy": 2000.0, "ton/yr": 2000.0, "tons/yr": 2000.0, "tons/year": 2000.0,
    "ton/year": 2000.0, "tons per year": 2000.0,
    "lb/yr": 1.0, "lbs/yr": 1.0, "lb/year": 1.0, "lbs/year": 1.0, "pounds/year": 1.0,
    "kg/yr": 2.20462, "kg/year": 2.20462,
    "tonne/yr": 2204.62, "metric tons/yr": 2204.62,
}
GRAMS = {"g/yr", "g/year", "grams/yr", "grams/year"}
LB_HR = {"lb/hr", "lbs/hr", "lb/hour"}

NOT_TRI_CAS = {
    "10102440",  # nitrogen dioxide
    "10102439",  # nitric oxide
    "11104931",  # NOx
    "7446095",   # sulfur dioxide
    "630080",    # carbon monoxide
    "124389",    # carbon dioxide
    "74828",     # methane
    "10024972",  # nitrous oxide
}
NOT_TRI_NAME = re.compile(
    r"\b(nox|nitrogen oxides?|nitrogen dioxide|so2|sulfur dioxide|co|carbon monoxide|"
    r"pm|pm10|pm2\.5|pm-10|pm-2\.5|particulate( matter)?|tsp|vocs?|volatile organic( compounds?)?|"
    r"co2e?|carbon dioxide|ghg|greenhouse gas(es)?|methane|nitrous oxide)\b",
    re.I,
)


def norm_id(s):
    """Strip dashes and leading zeros so 71-43-2, 0000071432, and 71432 compare equal."""
    s = re.sub(r"[^0-9A-Za-z]", "", s or "").upper()
    return s.lstrip("0") or s


def resolve_path(p):
    if os.path.isdir(p):
        for cand in ("verification/proposed-emissions.csv", "proposed-emissions.csv"):
            full = os.path.join(p, cand)
            if os.path.exists(full):
                return full
        sys.exit(
            f"No proposed-emissions.csv under {p}.\n"
            "Run permit-analysis Step 6 (which writes verification/proposed-emissions.csv), "
            "or hand-fill skills/permit-analysis/templates/proposed-emissions.csv."
        )
    if not os.path.exists(p):
        sys.exit(f"{p} not found")
    return p


def convert(amount, unit, hours):
    """Returns (value, layer, note). layer is 'lb', 'g', or None when not convertible."""
    u = re.sub(r"\s+", " ", unit.strip().lower())
    if u in TO_LB_YR:
        f = TO_LB_YR[u]
        return amount * f, "lb", f"{amount:g} {unit} × {f:g} = lb/yr" if f != 1 else "as reported"
    if u in LB_HR:
        h = hours or 8760.0
        basis = "application's stated hours" if hours else "assumes continuous operation"
        return amount * h, "lb", f"{amount:g} lb/hr × {h:g} h/yr ({basis})"
    if u in GRAMS:
        return amount, "g", "grams/yr; kept separate from pounds"
    return None, None, f"unit {unit!r} not recognized"


def load(path, chem_rows, nearby_ids=frozenset(), hours=None):
    path = resolve_path(path)
    by_id = {}
    by_name = {}
    for c in chem_rows:
        by_id[norm_id(c["cas_registry_number"])] = c
        by_id[norm_id(c["tri_chem_id"])] = c
        by_name[c["chem_name"].strip().lower()] = c
    nearby = {norm_id(i) for i in nearby_ids}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"{path} is missing columns: {', '.join(missing)}")
        raw = [r for r in reader if any((v or "").strip() for v in r.values())]

    rows = []
    for r in raw:
        name, cas = r["chemical"].strip(), r["cas"].strip()
        try:
            amount = float(r["amount"].replace(",", ""))
        except ValueError:
            amount = None
        value, layer, note = convert(amount, r["unit"], hours) if amount is not None else (None, None, "amount not numeric")
        chem = by_id.get(norm_id(cas)) if cas else None
        matched_by = "cas" if chem else None
        if not chem and not cas:
            # Exact TRI name only; a fuzzy match could attach the wrong chemical's flags.
            chem = by_name.get(name.lower())
            matched_by = "name" if chem else None
        if chem:
            bucket = "tri_nearby" if norm_id(chem["tri_chem_id"]) in nearby else "tri_not_nearby"
        elif norm_id(cas) in NOT_TRI_CAS or NOT_TRI_NAME.search(name):
            bucket = "not_tri"
        else:
            bucket = "unmatched"
        if bucket.startswith("tri") and layer is None:
            bucket = "unconvertible"
        rows.append({
            "chemical": name, "cas": cas, "amount": amount, "unit": r["unit"].strip(),
            "basis": r["basis"].strip(), "source_doc": r["source_doc"].strip(),
            "page": r["page"].strip(),
            "ocr_verified": r["ocr_verified"].strip().lower() in ("yes", "y", "true", "1"),
            "bucket": bucket, "layer": layer, "value": value, "conversion": note,
            "tri_chem_id": chem["tri_chem_id"] if chem else None,
            "matched_by": matched_by,
            "tri_name": chem["chem_name"] if chem else None,
            "carcinogen": bool(chem and chem["carc_ind"] == "1"),
        })

    tri = [r for r in rows if r["bucket"] in ("tri_nearby", "tri_not_nearby")]
    lb = [r for r in tri if r["layer"] == "lb"]
    return {
        "path": os.path.abspath(path),
        "hours": hours,
        "rows": rows,
        "totals": {
            "lb_yr": sum(r["value"] for r in lb),
            "carcinogen_lb_yr": sum(r["value"] for r in lb if r["carcinogen"]),
            "g_yr": sum(r["value"] for r in tri if r["layer"] == "g"),
            "n_unverified": sum(1 for r in rows if not r["ocr_verified"]),
        },
    }


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("chem_list")
    p.add_argument("--hours", type=float)
    a = p.parse_args()
    with open(a.chem_list, newline="", encoding="utf-8-sig") as f:
        chems = list(csv.DictReader(f))
    print(json.dumps(load(a.csv, chems, hours=a.hours), indent=1))
