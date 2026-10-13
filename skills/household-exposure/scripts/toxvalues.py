"""Chronic inhalation toxicity values from EPA OAQPS Table 1.

One table on purpose: it is EPA's own prioritized pick across IRIS, ATSDR and CalEPA, and it
is what AirToxScreen uses, so results stay comparable. The CSV beside this skill is a
column-for-column copy of EPA's spreadsheet (inhalation columns only); regenerate it from
SOURCE_URL when EPA reissues the table and update TABLE_DATE and SOURCE_SHA256.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tri-release-report", "scripts"))
from proposed_emissions import norm_id  # noqa: E402

TABLE_DATE = "2021-09-29"
SOURCE_URL = ("https://www.epa.gov/system/files/documents/2021-09/"
              "chronicfinaloutput_9_29_2021-12-46-18-pm.xlsx")
SOURCE_SHA256 = "7443bd7da8f4838597f671df05f86f8417f66d209e1954cd61a5d063cd713a5d"
NOTES_URL = ("https://www.epa.gov/fera/additional-information-adjustments-and-special-cases-"
             "dose-response-values-tables-1-and-2")
CSV_PATH = os.path.join(os.path.dirname(HERE), "references", f"oaqps-table1-{TABLE_DATE}.csv")

REFS = os.path.join(os.path.dirname(HERE), "references")
CATEGORY_MAP_PATH = os.path.join(REFS, "tri-category-map.csv")
ORGANS_PATH = os.path.join(REFS, "airtoxscreen-2020-target-organs.csv")
ORGANS_URL = ("https://www.epa.gov/system/files/other-files/2024-06/"
              "2020-airtoxscreen-supplemental-data-files.zip")
ORGANS_SHA256 = "e67bce36da13aab8bf87b9a597ed0ff7e29d8db82f3d8d82cf3502c4062b75a4"

MG_TO_UG = 1000.0

# Both codes call for age-dependent adjustment factors below age 16 (Table 1 notes 2 and 3).
MUTAGENIC_MOA = {"M", "m-rpf"}

# Chemicals where the table's flag or value does not mean what it means for the rest.
SPECIAL = {
    # Table 1 note 2: the factors apply only to the kidney-cancer part of the unit risk.
    # IRIS gives that part as 1.0e-6 of the 4.1e-6 total, which reproduces EPA's stated
    # full-lifetime adjusted value of 4.8e-6.
    "79016": {"adaf_share": 1.0e-6 / 4.1e-6,
              "note": "age factors applied to the kidney-cancer share of the unit risk only "
                      "(EPA Table 1 note 2)"},
    # Table 1 note 13: not flagged mutagenic because the listed value already covers
    # exposure from birth. IRIS's adult-only value is half of it.
    "75014": {"note": "unit risk is EPA's value for continuous exposure from birth; for "
                      "exposure that began in adulthood it overstates risk by up to 2x "
                      "(EPA Table 1 note 13)"},
}


def _num(s):
    """Blank or zero in the table means no value was derived, never a value of zero."""
    v = float(s) if s.strip() else 0.0
    return v or None


def load(path=CSV_PATH):
    """{normalized CAS: record}. Concentration-based values are returned in ug/m3 terms."""
    table = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = norm_id(r["cas"])
            if key in table:
                raise ValueError(f"duplicate CAS in toxicity table: {r['cas']}")
            rfc_mg = _num(r["rfc_mg_m3"])
            special = SPECIAL.get(key, {})
            table[key] = {
                "chemical": r["chemical"],
                "cas": r["cas"],
                "rfc_ug_m3": rfc_mg * MG_TO_UG if rfc_mg is not None else None,
                "rfc_source": r["rfc_source"] or None,
                "ure_per_ug_m3": _num(r["ure_per_ug_m3"]),
                "ure_source": r["ure_source"] or None,
                "epa_woe": r["epa_woe"] or None,
                "epa_moa": r["epa_moa"] or None,
                "mutagenic": r["epa_moa"] in MUTAGENIC_MOA,
                "adaf_share": special.get("adaf_share", 1.0),
                "note": special.get("note"),
            }
    return table


def lookup(table, cas):
    """Record for a CAS in any spelling (71-43-2, 71432, 0000071432), or None."""
    return table.get(norm_id(cas))


def load_category_map(path=CATEGORY_MAP_PATH):
    """{normalized RSEI/TRI id: {"cas", "basis", "note"}} for ids Table 1 lists another way.

    TRI reports metals and some groups as categories (N420, lead compounds). Table 1 files
    most metal compounds under the element's CAS number. A category with no row here has no
    defensible single value and stays unquantified.
    """
    with open(path, newline="", encoding="utf-8") as f:
        return {norm_id(r["rsei_id"]): {"cas": r["table1_cas"], "basis": r["basis"], "note": r["note"]}
                for r in csv.DictReader(f)}


def resolve(table, catmap, rsei_id):
    """(record or None, key, basis, note) for a chemical as RSEI or TRI identifies it.

    `key` is the normalized Table 1 CAS when one applies, else the normalized id itself, so
    lead and lead compounds land on one row. basis is "direct" or "assumed"; an assumed
    pairing carries a note the report must show.
    """
    key = norm_id(rsei_id)
    mapped = catmap.get(key)
    if mapped:
        return table.get(norm_id(mapped["cas"])), norm_id(mapped["cas"]), mapped["basis"], mapped["note"]
    return table.get(key), key, "direct", None


def load_organs(path=ORGANS_PATH):
    """{normalized CAS: [target organ, ...]} from AirToxScreen 2020's pollutant list.

    Table 1 has no organ column. These are the organ systems EPA sums hazard quotients
    within for AirToxScreen; only the organ flags are taken from that workbook, never its
    toxicity values.
    """
    with open(path, newline="", encoding="utf-8") as f:
        return {norm_id(r["cas"]): r["organs"].split(";") for r in csv.DictReader(f) if r["organs"]}


ORGAN_NAMES = {"resp": "respiratory", "liver": "liver", "neuro": "neurological",
               "dev": "developmental", "reprod": "reproductive", "kidney": "kidney",
               "ocular": "ocular", "endoc": "endocrine", "hemato": "hematological",
               "immune": "immunological", "skeletal": "skeletal", "spleen": "spleen",
               "thyroid": "thyroid", "wholebod": "whole body"}


def provenance():
    return {"table": "EPA OAQPS Table 1, Prioritized Chronic Dose-Response Values",
            "date": TABLE_DATE, "url": SOURCE_URL, "sha256": SOURCE_SHA256, "notes": NOTES_URL,
            "target_organs": {"table": "2020AirToxScreenPollutants.xlsx, AirToxScreen 2020 "
                                       "supplemental data", "url": ORGANS_URL, "sha256": ORGANS_SHA256}}
