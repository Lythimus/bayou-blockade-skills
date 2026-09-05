---
name: epa-rcra-waste
description: Query EPA's RCRA Hazardous Waste Biennial Report (Envirofacts BR_REPORTING) for a facility's self-reported hazardous waste generation tonnage by cycle, waste type, and management method
allowed-tools: Bash, AskUserQuestion
---

# EPA RCRA Hazardous Waste Biennial Report Search

Query EPA's Envirofacts `BR_REPORTING` table (`data.epa.gov/efservice`) for a RCRA-regulated facility's self-reported hazardous waste generation, from the Biennial Report (BR) filed by large-quantity generators and treatment/storage/disposal facilities (TSDFs). No API key required. **Reporting is odd years only** — 2011, 2013, 2015, 2017, 2019, 2021, 2023 — there is no even-year data to look for.

This gives quantities (tons generated, by waste code and management method); it does **not** cover compliance or violations — cross-link `bayou:epa-echo-search` for RCRA enforcement history on the same handler.

## ⚠️ Trap 1: `generation_tons` can be NULL for an entire reporting cycle — never coerce to 0

**Verified live 2026-08-20** for Motiva Norco Refinery (`handler_id LAD008186579`), `br_form='GM'`: every one of the 8 rows in the **2021** cycle has `generation_tons: null`, while every other cycle from 2001–2023 is fully populated (e.g. 2019 = 2,345.09 tons, 2023 = 504.94 tons). A null-to-zero default renders as "generated no hazardous waste in 2021," which is false — the facility simply didn't report a tonnage figure that cycle (or EPA hasn't backfilled it). Always report a null cycle as **"not reported / unavailable,"** never as `0.0 tons`.

## ⚠️ Trap 2: `BR_REPORTING` mixes generation and waste-received records — filter to `br_form='GM'`

Each row's `br_form` field is one of:
- `GM` — **G**eneration and **M**anagement: waste this handler generated. This is what "how much hazardous waste did this facility produce" means.
- `WR` — **W**aste **R**eceived: waste a TSDF took in *from other generators*. Summing this with `GM` overstates what the facility itself produced by counting waste that arrived from elsewhere.
- `XX` — other/unclassified.

**Verified live 2026-08-20**: across the 732 `BR_REPORTING` rows for Norco, LA, the form-code mix is 501 `GM`, then 222 `GM` / 9 `WR` / 1 `XX` in the remaining page — `WR` rows are real and present at this location, not a theoretical edge case. **Always filter `br_form='GM'` before summing generation tonnage.**

## Parsing arguments

The user may provide:
- A **city + state** (e.g., "Norco, LA") — finds every RCRA handler at that location
- A **handler ID** (EPA ID number, e.g. `LAD008186579`) — from a permit application, or from `bayou:epa-frs-crosswalk`'s `RCRAINFO` program ID
- A **facility/company name fragment**
- A **report cycle** or range (odd years only: 2011–2023 currently populated)

If no state is given, ask.

## Step 1: Find handlers by city/state

```bash
curl -s "https://data.epa.gov/efservice/BR_REPORTING/ACTIVITY_LOCATION/LA/LOCATION_CITY/NORCO/rows/0:500/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
rows = json.load(sys.stdin)
handlers = {}
for r in rows:
    handlers.setdefault(r['handler_id'], r['handler_name'])
for hid, name in handlers.items():
    print(hid, '|', name)
"
```

`BR_REPORTING` is a wide, denormalized table — one row per waste stream per cycle per handler, not one row per handler. **Verified live 2026-08-20**: Norco, LA alone returns 732 rows across 9 distinct handlers, spanning cycles 2001–2023. `rows/0:500` only returns the first page — if the handler count looks incomplete, page further (`rows/500:1000`, etc.) or check the total first:

```bash
curl -s "https://data.epa.gov/efservice/BR_REPORTING/ACTIVITY_LOCATION/LA/LOCATION_CITY/NORCO/count" 2>/dev/null
# returns XML: <REQUESTRECORDCOUNT>732</REQUESTRECORDCOUNT>
```

An invalid `handler_id` or a location with no RCRA handlers returns **HTTP 200 with body `[]`** (verified live 2026-08-20 — same empty-array pattern as `bayou:epa-frs-crosswalk` and `bayou:epa-ghgrp-search`), not an error and not HTML. Guard with `if not rows`.

## Step 2: Generation tonnage by cycle, for one handler

```bash
HID="LAD008186579"   # replace with resolved handler_id
curl -s "https://data.epa.gov/efservice/BR_REPORTING/HANDLER_ID/${HID}/BR_FORM/GM/rows/0:200/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print('NOT FOUND — no GM-form biennial report rows for this handler_id')
    sys.exit()
by_cycle = {}
for r in rows:
    by_cycle.setdefault(r['report_cycle'], []).append(r['generation_tons'])
for c in sorted(by_cycle):
    vals = by_cycle[c]
    if all(v is None for v in vals):
        print(c, '-> NOT REPORTED (all null — do not render as 0)')
    else:
        total = sum(float(v) for v in vals if v is not None)
        print(c, f'-> {total:,.2f} tons across {len(vals)} waste-stream rows')
"
```

Note the explicit `BR_FORM/GM` filter in the URL — this is Trap 2 applied. Verified live 2026-08-20 for `LAD008186579`: 2001–2019 and 2023 all populated (e.g. 2023 = 504.94 tons), 2021 entirely null (Trap 1).

## Step 3: Waste stream breakdown for one cycle

```bash
YEAR="2023"
curl -s "https://data.epa.gov/efservice/BR_REPORTING/HANDLER_ID/${HID}/BR_FORM/GM/REPORT_CYCLE/${YEAR}/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
for r in json.load(sys.stdin):
    tons = r['generation_tons']
    tons_str = f\"{float(tons):,.2f} tons\" if tons is not None else 'NOT REPORTED'
    print(r['description'], '|', tons_str, '| waste code group:', r.get('waste_code_group'), '| mgmt method:', r.get('management_method'), '| federal waste?', r.get('federal_waste'))
"
```

Key fields per row: `description` (human-readable waste name — most useful for presentation), `waste_code_group` (RCRA waste code, e.g. `F037`), `source_code` (how the waste arises, e.g. `G14`), `form_code` (physical/chemical form), `management_method` (how it was handled, e.g. `H050` = treatment code), `federal_waste` (`Y`/`N` — federally vs. state-only regulated), `wastewater` (`Y`/`N`).

## Presenting results

1. **Facility identification**: `handler_id`, `handler_name`, address, parish (`county_name`).
2. **Tonnage-by-cycle table**: Cycle | Generation Tons | Notes — render null cycles as "not reported," never `0`.
3. **Waste stream breakdown** for the most recent (or requested) cycle: waste description, code group, management method.
4. **Multi-handler framing**: if several distinct `handler_id`s share a city (as at Norco: Valero, Motiva, Hexion, two Shell sites, Cypress ×2, Enterprise, ChemTreat), list each with its own tonnage and note the cumulative total for the area.
5. State explicitly that figures reflect only `br_form='GM'` (generation) — not waste received from elsewhere — and only odd-numbered report cycles.

### Citation format

> **RCRA Handler ID `LAD008186579`** (Motiva Enterprises LLC – Norco Refinery), 2023 Biennial Report, source: [EPA RCRAInfo Biennial Report via Envirofacts](https://data.epa.gov/efservice/) (retrieved 2026-08-20): 504.94 tons hazardous waste generated (GM form). 2021 cycle not reported.

## Notes & limits

- No API key required.
- Biennial Report cycles are **odd years only** (2011, 2013, …, 2023 currently populated; earlier cycles back to 2001 also present for some handlers).
- `generation_tons` (and other tonnage fields) can be `null` for an entire cycle — see Trap 1. Never default to zero.
- Always filter `br_form='GM'` for generation figures — see Trap 2. `WR` (waste received) and `XX` rows exist in this dataset and will overstate generation if summed in.
- `BR_REPORTING` is one row per waste stream per cycle, not one row per handler — a single handler can have a dozen-plus rows per cycle.
- Only large-quantity generators and TSDFs are required to file a Biennial Report — a facility with no `handler_id` here may still generate hazardous waste below the reporting threshold.
- Cross-link `bayou:epa-frs-crosswalk` (via the `RCRAINFO` program ID, to find this handler ID from a facility name/registry ID) and `bayou:epa-echo-search` (RCRA compliance/enforcement — this skill has no violation data, only self-reported quantities).
- Observed latency: each query returns in a few seconds, well within a reasonable timeout.

$ARGUMENTS
