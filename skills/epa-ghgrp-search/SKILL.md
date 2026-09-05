---
name: epa-ghgrp-search
description: Query EPA's Greenhouse Gas Reporting Program (GHGRP) for a facility's annual CO2e emissions, broken down by subpart (source category) and gas, and surface every co-located reporting facility for cumulative-impact framing
allowed-tools: Bash, AskUserQuestion
---

# EPA Greenhouse Gas Reporting Program (GHGRP) Search

Query EPA's Envirofacts GHGRP tables (`data.epa.gov/efservice`, `PUB_DIM_FACILITY` / `PUB_FACTS_SUBP_GHG_EMISSION` / `PUB_DIM_SUBPART` / `PUB_DIM_GHG`) for a facility's self-reported greenhouse gas emissions. No API key required. Covers facilities that exceed GHGRP's reporting threshold (generally 25,000 t CO2e/yr) — not every regulated facility reports.

**One physical industrial complex is often several distinct GHGRP `facility_id`s.** At Norco, LA alone there are five: Norco Manufacturing Complex (`1005911`), Shell Chemical LP Norco Chemical Plant West (`1006133`), Norco Fractionation Plant (`1005070`), Rain CII Carbon Norco Coke Plant (`1005716`), and Air Products Norco SMR (`1011460`) — each reports independently, so a permit application for one treats it as a standalone source while the surrounding community absorbs all five. Always search by city/area, not just the one facility name in a permit application, and itemize + sum when several sites cluster together — this is the cumulative-impact / single-source-aggregation argument, quantified.

## ⚠️ Trap: facility CO2e totals must come from `PUB_FACTS_SUBP_GHG_EMISSION`, never `PUB_FACTS_SECTOR_GHG_EMISSION`

The sector table repeats the same underlying emissions across multiple `(sector_id, subsector_id)` pairs, so summing `co2e_emission` there overstates the total. **Verified live 2026-08-20** for Norco Manufacturing Complex (`facility_id 1005911`), year 2023:

- `PUB_FACTS_SUBP_GHG_EMISSION` (correct, subpart-level): **4,143,881 t CO2e**
- `PUB_FACTS_SECTOR_GHG_EMISSION` (wrong, sector-level): **32,752,641 t CO2e** — ~7.9× inflated

Neither number is obviously absurd on its own, which is what makes this dangerous in a public comment letter. **Always use `PUB_FACTS_SUBP_GHG_EMISSION` for a facility's reported CO2e total.** The sector table exists for EPA's own national sector-level rollups, not facility-level reporting.

## Parsing arguments

The user may provide:
- A **facility name** (e.g., "Norco Manufacturing Complex", "Shell Chemical Norco")
- A **city + state** (e.g., "Norco, LA") — preferred, since it surfaces every co-located facility
- A known **GHGRP facility ID** (numeric, e.g. `1005911`) — from a permit application, or from `bayou:epa-frs-crosswalk`'s `E-GGRT` program ID
- A **year** or year range (data currently runs through **2023**, the most recent reporting year live in Envirofacts as of 2026-08-20 — GHGRP data lags roughly two years behind the current date)

If no state is given, ask. Prefer searching by city over a single facility name — see the multi-facility note above.

## Step 1: Find facilities by name or city/state

```bash
curl -s "https://data.epa.gov/efservice/PUB_DIM_FACILITY/STATE/LA/FACILITY_NAME/CONTAINING/NORCO/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
d = json.load(sys.stdin)
latest = {}
for f in d:
    fid = f['facility_id']
    if fid not in latest or f['year'] > latest[fid]['year']:
        latest[fid] = f
for fid, f in latest.items():
    print(fid, '|', f['facility_name'], '| (', f['year'], ') |', f.get('parent_company'), '|', f.get('reported_subparts'), '|', f.get('frs_id'))
"
```

`PUB_DIM_FACILITY` returns **one row per facility per reporting year** (verified live: the Norco query above returns 66 rows for only 5 distinct facilities, spanning years 2010–2023) — dedupe on `facility_id` **keeping the highest `year`**, not just the first row seen, since ownership and subpart mix drift over time (verified live: naively taking the first row per `facility_id` reports `1005070`'s parent as "Enterprise Gas Processing, LLC," while the 2023 row reports "ENTERPRISE PRODUCTS PARTNERS LP" — both true at different times, but only one is current). `1006133`'s `reported_subparts` is populated in earlier years but `null` for 2023, meaning it likely stopped reporting or fell under the threshold — don't assume a null on the latest row means "never reported."

Each row also carries `latitude`/`longitude`, `frs_id` (the FRS `registry_id` — cross-link `bayou:epa-frs-crosswalk`), `naics_code`, and `facility_types` (e.g. "Supplier, Direct Emitter").

## Step 2: Annual CO2e total, from the subpart table

```bash
FID="1005911"   # replace with resolved facility_id
YEAR="2023"
curl -s "https://data.epa.gov/efservice/PUB_FACTS_SUBP_GHG_EMISSION/FACILITY_ID/${FID}/YEAR/${YEAR}/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print('NOT FOUND — no subpart emissions rows for this facility_id/year')
    sys.exit()
total = sum(float(r['co2e_emission']) for r in rows)
print(f'Total {total:,.0f} t CO2e across {len(rows)} subpart/gas rows')
"
```

An invalid `facility_id` or a year the facility didn't report returns **HTTP 200 with body `[]`** (verified live 2026-08-20, same behavior as FRS in `bayou:epa-frs-crosswalk`) — not an error, not HTML. Guard with `if not rows`, never assume a decode failure.

To get every year at once, drop `/YEAR/${YEAR}` and group client-side on the `year` field.

## Step 3: Subpart breakdown (source category)

Each row in `PUB_FACTS_SUBP_GHG_EMISSION` is one `(sub_part_id, gas_id)` pair, not a full facility total by itself — join `sub_part_id` against `PUB_DIM_SUBPART` for the human-readable name:

```bash
curl -s "https://data.epa.gov/efservice/PUB_FACTS_SUBP_GHG_EMISSION/FACILITY_ID/${FID}/YEAR/${YEAR}/JSON" 2>/dev/null | \
  python3 -c "
import json, sys, subprocess

rows = json.load(sys.stdin)
by_subpart = {}
for r in rows:
    by_subpart[r['sub_part_id']] = by_subpart.get(r['sub_part_id'], 0) + float(r['co2e_emission'])

for sp_id, total in sorted(by_subpart.items(), key=lambda x: -x[1]):
    resp = subprocess.run(['curl', '-s', f'https://data.epa.gov/efservice/PUB_DIM_SUBPART/SUBPART_ID/{sp_id}/JSON'], capture_output=True, text=True).stdout
    d = json.loads(resp)
    name = d[0]['subpart_name'] if d else '?'
    cat = d[0]['subpart_category'] if d else '?'
    print(f'Subpart {name} ({cat}): {total:,.0f} t CO2e')
"
```

Verified live 2026-08-20 for `1005911`/2023: Subpart C (Stationary Combustion) 3,129,616 t, Subpart Y (Petroleum Refining) 961,840 t, Subpart X (Petrochemical Production) 52,425 t — summing to the 4,143,881 t total from Step 2.

## Step 4: Gas breakdown

The same `PUB_FACTS_SUBP_GHG_EMISSION` rows carry `gas_id` — join against `PUB_DIM_GHG`:

```bash
curl -s "https://data.epa.gov/efservice/PUB_DIM_GHG/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
for g in json.load(sys.stdin):
    print(g['gas_id'], '|', g['gas_code'], '|', g['gas_name'])
"
```

Common `gas_id` values observed live: `1` = CO2, `2` = CH4, `3` = N2O. Note that `co2e_emission` is already CO2-equivalent (methane and N2O are pre-converted using their global warming potentials) — do not re-multiply by a GWP factor.

## How to present results

1. **Facility identification**: `facility_id`, name, parent company, address/coordinates, `frs_id`.
2. **If multiple facilities were found in one city/area**: list every one with its own total, then a combined sum — this is usually the point of running the search.
3. **Year × CO2e table**: at minimum the most recent year; multi-year if the user wants a trend.
4. **Subpart breakdown**: table of Subpart | Category | t CO2e, sorted largest first.
5. **Gas breakdown** where it matters (e.g. a large CH4 share signals fugitive/venting sources worth naming specifically, not just "greenhouse gases").
6. State plainly which table the number came from if there's any chance of confusion — "(from the subpart-level table, not the sector table, per the note above)."

### Citation format

> **GHGRP Facility ID `1005911`** (Norco Manufacturing Complex, Shell Petroleum Inc.), reporting year 2023, source: [EPA Greenhouse Gas Reporting Program via Envirofacts](https://data.epa.gov/efservice/) (retrieved 2026-08-20): 4,143,881 t CO2e total — Subpart C (Stationary Combustion) 3,129,616 t, Subpart Y (Petroleum Refining) 961,840 t, Subpart X (Petrochemical Production) 52,425 t.

## Notes & limits

- No API key required.
- Data lags: 2023 is the most recent reporting year available as of 2026-08-20. Do not assume the current calendar year is live.
- GHGRP only covers facilities above the reporting threshold — a facility with no GHGRP `facility_id` may still emit GHGs below that threshold, or may report through a different program. Absence here is not evidence of zero emissions.
- Distinct from `bayou:epa-campd-search`: CAMPD/CAMD covers combustion units under Clean Air Act market programs (Acid Rain Program, CSAPR, NOx Budget) and requires an API key; GHGRP is broader — it includes process emissions (e.g. petrochemical production, refining) that CAMPD never sees, and covers non-power-sector facilities CAMPD doesn't track at all. Use both when a facility has both an ORISPL (CAMPD) and a GHGRP `facility_id` — they answer different questions, not redundant ones.
- Cross-link `bayou:epa-frs-crosswalk` to find every sibling program ID (and every co-located `E-GGRT` facility) for a physical site, and `bayou:epa-echo-search` for compliance/enforcement context (GHGRP itself has no violation data — it's self-reported emissions only, not a permit limit).
- Observed latency: each query returns in a few seconds; the per-subpart lookup in Step 3 issues one request per distinct subpart (typically 2–5), still well under a minute total.

$ARGUMENTS
