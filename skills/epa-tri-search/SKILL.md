---
name: epa-tri-search
description: Search EPA's Toxics Release Inventory (TRI) for a facility's year-over-year chemical releases, by medium (air/water/land) and carcinogen status, via the Envirofacts REST API
allowed-tools: Bash, AskUserQuestion
---

# EPA Toxics Release Inventory (TRI) Search

Query EPA's Envirofacts TRI tables directly (`data.epa.gov/efservice`) for a facility's self-reported chemical releases. No API key required. This is the data behind the TRI Explorer / TRI Toolbox web tools, but reachable as structured JSON.

Distinct from `bayou:epa-echo-search`: ECHO tracks **compliance and enforcement** (inspections, violations, penalties). TRI tracks **self-reported release quantities** under EPCRA §313 — a facility can be fully "in compliance" in ECHO while TRI shows it releasing tons of a listed carcinogen every year, because TRI reporting is not itself a permit limit. Run both for a complete picture; cross-link a TRI facility to its ECHO/FRS record when possible.

## Parsing arguments

The user may provide:
- A **facility name** (e.g., "Shell Norco", "Valero Norco")
- A **city + state** (e.g., "Norco, LA")
- A known **TRI facility ID** (12-char alphanumeric, e.g. `70079SHLLL1205R`)
- A **chemical name** to filter on (e.g., "benzene", "1,3-butadiene")
- A **year range**

If no state is given, ask. A city can host many TRI facilities under similarly generic names (Norco, LA alone has 13) — always disambiguate by full facility name and street address before reporting numbers, not by ID guesswork.

## ⚠️ Do not assume a facility ID from memory or a prior conversation

TRI facility IDs are not derived from the company name in any predictable way, and near-identical-looking IDs can belong to different companies. **Confirmed live:** `70079NRCFR15536` (Norco, LA) is **Enterprise Products' Norco Fractionator** (public contact domain `@eprod.com`), not Shell — despite the "NRCFR" fragment suggesting "Norco". Shell's actual Norco TRI facilities are:

| TRI Facility ID | Name |
|---|---|
| `70079SHLLL1205R` | SHELL NORCO CHEMICAL PLANT |
| `70079SHLLL265RI` | SHELL NORCO CHEMICAL PLANT WEST SITE |

Always run Step 1 to resolve the ID from the facility name before pulling release data — never hardcode an ID from a previous session without re-resolving it.

---

## Step 1: Resolve the facility name to a TRI facility ID

```bash
curl -s "https://data.epa.gov/efservice/tri_facility/state_abbr/LA/city_name/NORCO/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
for f in json.load(sys.stdin):
    print(f['tri_facility_id'], '|', f['facility_name'], '|', f['street_address'], '|', f.get('parent_co_name'))
"
```

`city_name` and `state_abbr` require exact matches (all caps, no punctuation tricks). If the city is unknown, drop `city_name` and filter by `state_abbr` alone, then grep the output for the company name — TRI has no fuzzy/CONTAINING search on `facility_name` that reliably narrows results, so pulling the full state or city list and filtering client-side is the reliable path.

Each record also carries `pref_latitude`/`pref_longitude` (WGS84) and `parent_co_name` — useful for cross-referencing against `bayou:epa-echo-search` or `bayou:facility-coordinates`.

## Step 2: Pull reporting-form records for the facility

```bash
FID="70079SHLLL1205R"   # replace with resolved ID

# IMPORTANT: /rows/N:M/ must come BEFORE /JSON in the path, or Envirofacts
# silently returns an empty list instead of an error.
curl -s "https://data.epa.gov/efservice/tri_reporting_form/tri_facility_id/${FID}/rows/0:200/JSON" 2>/dev/null
```

Check the total row count first so you know whether 200 rows covers the whole history:

```bash
curl -s "https://data.epa.gov/efservice/tri_reporting_form/tri_facility_id/${FID}/count" 2>/dev/null
# returns XML: <REQUESTRECORDCOUNT>2120</REQUESTRECORDCOUNT>
```

TRI reporting goes back to 1987 for core chemicals (later for chemicals added to the list since). A single facility can have thousands of rows (one row per chemical per year); page through with `rows/0:200`, `rows/200:400`, etc. if the count exceeds what you pulled.

Key fields per row: `doc_ctrl_num` (join key), `reporting_year`, `tri_chem_id` (join key), `cas_chem_name` (chemical name, denormalized for convenience), `production_ratio` (this year's production relative to a baseline — a rough proxy for whether releases tracked or diverged from output), `certif_date_signed`.

To scope by year without pulling everything, filter client-side on `reporting_year` after fetching, or add `reporting_year/YYYY` as another path segment before `rows`:

```bash
curl -s "https://data.epa.gov/efservice/tri_reporting_form/tri_facility_id/${FID}/reporting_year/2022/JSON" 2>/dev/null
```

## Step 3: Get release quantities per chemical, per medium

```bash
DOC="1322221262189"   # doc_ctrl_num from a Step 2 row
curl -s "https://data.epa.gov/efservice/tri_release_qty/doc_ctrl_num/${DOC}/rows/0:20/JSON" 2>/dev/null
```

`environmental_medium` values observed: `AIR FUG` (fugitive air emissions), `AIR STACK` (stack/point-source air emissions), `WATER`, `LAND TREA` (land treatment), `UNINJ IIV` (underground injection). `total_release` is the reported pounds — but note it is frequently `null` with `release_na: "1"` when the facility instead reported a **range code** (`release_range_code`, 1–5) rather than an exact quantity, which TRI permits for smaller releases. When `total_release` is null, report the range code and state plainly that an exact figure wasn't disclosed — don't silently treat it as zero.

## Step 4: Get chemical name and carcinogen flag

```bash
CHEMID="0000071432"   # tri_chem_id from a Step 2 row (zero-padded CAS number)
curl -s "https://data.epa.gov/efservice/tri_chem_info/tri_chem_id/${CHEMID}/rows/0:2/JSON" 2>/dev/null
```

Key fields: `chem_name`, `cas_registry_number`, `carc_ind` (`"1"` = EPA-designated carcinogen for TRI purposes), `pbt_ind` (persistent bioaccumulative toxic), `pfas_ind`.

## Step 5 (optional): Off-site waste transfers

Where the facility's waste physically goes (recycling, treatment, disposal) rather than what it releases directly:

```bash
curl -s "https://data.epa.gov/efservice/tri_transfer_qty/doc_ctrl_num/${DOC}/rows/0:20/JSON" 2>/dev/null
```

`type_of_waste_management` is a short code (e.g. `M24` metals recovery, `P91` other) — decode against EPA's TRI waste management code list if the meaning matters to the argument being made.

### Source reduction / P2 data — not available via this API

The bookmarked "TRI P2 Search Tool" covers Form R Section 8 (source reduction and recycling activities). No Envirofacts table for it was found live (`tri_source_reduction*`, `tri_srce_reduc*`, `tri_pollution_prevention*`, and related guesses all returned "table is not available"). Use `production_ratio` from Step 2 as an imperfect proxy (releases that grow faster than production suggest no meaningful source reduction), and note explicitly that a true P2-activity narrative requires the TRI P2 Search Tool directly (`enviro.epa.gov` TRI tools) or the underlying Form R Section 8 PDF.

---

## Presenting the results

1. **Facility identification**: name, TRI ID, address, parent company, coordinates — always state which exact facility/site (e.g. "West Site" vs. main plant) the numbers below cover.
2. **Year-over-year release table**: Year | Chemical | Medium | Release (lbs) | Carcinogen?
3. **Flag carcinogens** (`carc_ind = "1"`) explicitly in prose, not just the table.
4. Note any years with only range-code (non-exact) reporting.
5. Cross-link: "For compliance/enforcement history on this facility, see `bayou:epa-echo-search`."
6. Cross-link the other Envirofacts skills — they cover different reporting regimes, not overlapping ones: `bayou:epa-frs-crosswalk` (resolve this facility's other program IDs — NPDES, RCRAInfo, GHGRP `E-GGRT` — from one registry ID), `bayou:epa-ghgrp-search` (greenhouse gas emissions; TRI does not cover CO2/CH4/N2O), `bayou:epa-rcra-waste` (hazardous waste generation tonnage; TRI covers listed-chemical *releases*, not waste quantities). Run TRI, GHGRP, and RCRA BR together for a full self-reported picture — each is a complement, not a substitute, for the others.

### Citation format

> **TRI Facility `70079SHLLL1205R`** (SHELL NORCO CHEMICAL PLANT), reporting year 2022, source: [EPA Envirofacts TRI](https://data.epa.gov/efservice/) (retrieved 2026-07-21): Benzene, AIR FUG, [X] lbs. EPA carcinogen flag: yes.

$ARGUMENTS
