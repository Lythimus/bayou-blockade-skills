---
name: epa-frs-crosswalk
description: Resolve a facility to its EPA Facility Registry Service (FRS) registry ID and list every environmental program ID (TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP, LA-TEMPO) held at that physical site — the crosswalk between federal program databases and LDEQ's state ID
allowed-tools: Bash, AskUserQuestion
---

# EPA Facility Registry Service (FRS) Crosswalk

Query EPA's Facility Registry Service (`data.epa.gov/efservice`, tables `FRS_FACILITY_SITE` and `FRS_PROGRAM_FACILITY`) to resolve one physical facility to every environmental program ID EPA and its state partners hold for it. FRS is the join table underneath all the single-program EPA databases (TRI, ECHO, GHGRP, RCRAInfo) — a `registry_id` here is the stable key that ties them together, and critically, it also carries the state-issued ID (`LA-TEMPO` for Louisiana) that bridges federal EPA data into LDEQ's own systems.

Run this **first** when you have a facility name and want to know which other bayou skills apply — it tells you whether a facility reports to TRI, GHGRP, has an NPDES water permit, an air permit, or hazardous waste activity, before you spend a query against each program's skill individually.

## Parsing arguments

The user may provide:
- A **facility name** (e.g., "Air Liquide Norco", "Shell Norco Chemical Plant")
- A **city + state** (e.g., "Norco, LA")
- A known **registry ID** (12-digit numeric, e.g. `110000597140`)
- A known **program ID** from another system (TRI ID, NPDES permit number, AIRS/AFS ID, RCRAInfo handler ID) — FRS can reverse-resolve any of these back to the registry ID and then to every sibling ID

If no state is given, ask. Like TRI, a single city can host many distinct FRS sites under similar names — always confirm by street address, not name alone, before reporting program IDs.

## Step 1: Find candidate registry IDs by name or location

```bash
curl -s "https://data.epa.gov/efservice/FRS_FACILITY_SITE/STATE_CODE/LA/CITY_NAME/NORCO/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
for f in json.load(sys.stdin):
    print(f['registry_id'], '|', f['primary_name'], '|', f.get('location_address'), ',', f.get('city_name'), f.get('state_code'))
"
```

`FRS_FACILITY_SITE` does **not** carry coordinates (verified live 2026-08-20 — no lat/lon field exists on this table, despite FRS being geospatial data at its core). For coordinates, cross-link `bayou:facility-coordinates` or `bayou:epa-echo-search` once you have a name/registry ID to search with.

Or filter by name fragment across a state:

```bash
curl -s "https://data.epa.gov/efservice/FRS_FACILITY_SITE/STATE_CODE/LA/PRIMARY_NAME/CONTAINING/SHELL/JSON" 2>/dev/null
```

`primary_name` is FRS's own denormalized site name and can differ from the name any individual program uses for the same site (see Step 2 note). Confirm the match against `location_address` before proceeding.

## Step 2: Pull every program ID for a registry ID

```bash
RID="110000597140"   # replace with resolved registry_id
curl -s "https://data.epa.gov/efservice/FRS_PROGRAM_FACILITY/REGISTRY_ID/${RID}/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print('NOT FOUND — no program facility records for this registry_id')
    sys.exit()
for r in rows:
    print(r['pgm_sys_acrnm'], '|', r['pgm_sys_id'], '|', r.get('primary_name'))
"
```

`FRS_PROGRAM_FACILITY` returns **one row per program**, not one row per site — a site with 7 program enrollments returns 7 rows, and `primary_name` can vary slightly row to row for the exact same physical site (observed live at this registry ID). **Dedupe and group on `registry_id`, never on name.**

### Trap: an unknown registry ID returns an empty array, not an error

Verified live 2026-08-20: querying a made-up or nonexistent `registry_id` returns **HTTP 200** with body `[]` — a syntactically valid but empty JSON array, not an error object and not a 4xx status. `json.load()` succeeds and simply yields an empty list, so there is no exception to catch — the Step 2 script above checks `if not rows` explicitly. Skipping that check produces a silent no-op rather than a clear "not found," which reads the same as "this facility has no program enrollments" — always state explicitly which one it was.

### Key `pgm_sys_acrnm` values and what they unlock

| Acronym | Program | Feeds into |
|---|---|---|
| `TRIS` | Toxics Release Inventory | `bayou:epa-tri-search` (this is the `tri_facility_id`) |
| `AIRS/AFS` | Air Facility System | `bayou:epa-echo-search` CAA data |
| `NPDES` | Water discharge permits | `bayou:epa-echo-search` CWA data |
| `RCRAINFO` | Hazardous waste handler ID | `bayou:epa-rcra-waste` (this is the `handler_id`) |
| `ICIS` | Integrated Compliance Information System | general EPA enforcement records |
| `E-GGRT` | Greenhouse Gas Reporting Program | `bayou:epa-ghgrp-search` (this is the `facility_id`) — not present at every site; only facilities that exceed GHGRP reporting thresholds have one |
| `LA-TEMPO` | **Louisiana's own facility ID system** | `bayou:ldeq-ai-lookup` and `bayou:ldeq-permit-status` — this is the federal↔state bridge; the numeric value is LDEQ's AI-adjacent ID used in LA-TEMPO, LDEQ's permit tracking system |

Not every site has every program ID — a small facility might have only `AIRS/AFS`, a major refinery complex will have most of the row above.

## Step 3: Reverse lookup — from a known program ID back to the registry ID

If you already have a TRI ID, NPDES number, or AIRS/AFS ID from another skill and want the sibling IDs:

```bash
PGMID="70079SHLLL1205R"   # e.g. a TRI facility ID
curl -s "https://data.epa.gov/efservice/FRS_PROGRAM_FACILITY/PGM_SYS_ID/${PGMID}/JSON" 2>/dev/null | \
  python3 -c "
import json, sys
rows = json.load(sys.stdin)
for r in rows:
    print(r['registry_id'], '|', r['pgm_sys_acrnm'], '|', r.get('primary_name'))
"
```

This is an exact match on `pgm_sys_id` across all programs, so it's safe even without knowing which program the ID belongs to. Take the `registry_id` from the result and re-run Step 2 to get every other program's ID for that same site.

## How to present results

1. **Site identification**: `registry_id`, `primary_name` (from `FRS_FACILITY_SITE`, not a per-program row), address, coordinates.
2. **Program-ID table**: Program | ID | Bayou skill it feeds.
3. Call out `LA-TEMPO` explicitly and by name as the LDEQ join key whenever present — this is usually the reason to run this skill in the first place.
4. **Multi-facility framing**: if resolving several nearby names (e.g. everything at "Norco") returns multiple distinct `registry_id`s at the same or adjacent addresses, say so explicitly — several legally separate registry IDs clustered at one industrial complex is the common-control / single-source aggregation signal worth flagging to the analyst, not just a data quirk.
5. Note any program acronym that is absent (e.g. no `E-GGRT` row means the facility doesn't clear GHGRP's reporting threshold — worth stating plainly rather than silently omitting).

### Citation format

> **FRS Registry ID `110000597140`** (Air Liquide Large Industries, Norco, LA), source: [EPA Facility Registry Service](https://data.epa.gov/efservice/) (retrieved 2026-08-20): program IDs — TRIS `[id]`, AIRS/AFS `2208900029`, NPDES `LA0051764`, LA-TEMPO `3483`.

## Notes & limits

- No API key required.
- `/rows/N:M/` is not needed for these queries in practice (a single facility's program list is small), but if listing many facilities by city/state, add `rows/0:200/` before `/JSON` as in the other Envirofacts skills.
- `FRS_FACILITY_SITE` carries no coordinate field — for GPS coordinates, hand off to `bayou:facility-coordinates` or `bayou:epa-echo-search`.
- Cross-link `bayou:epa-ghgrp-search` (via `E-GGRT`), `bayou:epa-rcra-waste` (via `RCRAINFO`), `bayou:epa-tri-search` (via `TRIS`), `bayou:ldeq-ai-lookup` / `bayou:ldeq-permit-status` (via `LA-TEMPO`), `bayou:epa-echo-search` / `bayou:facility-coordinates` (via `AIRS/AFS` / `NPDES` / registry ID itself).

$ARGUMENTS
