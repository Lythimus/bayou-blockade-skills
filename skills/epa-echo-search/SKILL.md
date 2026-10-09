---
name: epa-echo-search
description: Search EPA ECHO for facility compliance and enforcement history (recent five years via REST, decades of CAA/CWA/RCRA violations, inspections and enforcement cases via EPA's bulk downloads); also returns GPS coordinates (lat/lon) for regulated facilities
allowed-tools: Bash, AskUserQuestion
---

# EPA ECHO Facility Search

Search the EPA Enforcement and Compliance History Online (ECHO) database for facilities regulated under CAA, CWA, RCRA, and SDWA programs. ECHO is also a reliable source of **GPS coordinates** for petrochemical, O&G, utility, and manufacturing facilities — see the coordinates section below.

## Parsing arguments

The user may provide:
- A **facility name** (e.g., "Waterford Steam Electric", "Entergy Louisiana")
- A **state** abbreviation (e.g., "LA")
- A **city** or **zip code**
- A **registry ID** (FRS/ECHO ID)
- A request like "find violations", "compliance history", "inspections"
- A request for **GPS coordinates** or **location** of a facility

If no state or location is provided, ask for one to narrow results.

## How to search

### Step 1: Get facility list and QID

```bash
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_facilities?output=json&p_fn=FACILITY_NAME&p_st=STATE&p_rows=25" 2>/dev/null
```

Key query parameters:
- `p_fn` — facility name (partial match)
- `p_st` — state code (e.g., `LA`)
- `p_city` — city name
- `p_zip` — zip code
- `p_fips` — 5-digit state+county FIPS code (e.g. `22121` = West Baton Rouge Parish, LA). **This is the working way to scope a query to one county.** `p_county` is accepted by the endpoint but silently ignored — verified live (2026-08-12): `p_st=LA&p_county=West Baton Rouge` (and four other value formats: uppercase, `"... Parish"`, the FIPS code itself, `p_cnty`) all returned the identical statewide "Queryset Limit would be exceeded" error as omitting the param entirely. Reach for `p_fips`, not `p_county`.
- `p_frs` — registry ID (exact). **Not `p_id`:** `get_facilities` silently ignores `p_id` and runs nationwide (verified 2026-10-08: "Rows Returned would be 5742849. Queryset Limit would be exceeded"). `p_id` is the right name only for `get_facility_info` and `get_dfr`.
- `p_act` — active facilities only: `Y`
- `p_sic` — 4-digit SIC code (e.g. `2911` petroleum refining). **One code per query:** `p_sic=2911,2869` returns an error, so run one query per code. Verified live 2026-10-07: `p_sic=2911&p_st=LA&p_act=Y` returned 35 rows, and national `p_sic=2911&p_act=Y` returned 470 rows with no queryset error.
- `p_ncs` — NAICS code (e.g. `324110`). **`p_naics` is silently ignored**: `p_naics=324110&p_st=LA` returned all 39,861 Louisiana facilities. Always use `p_ncs`.
- `p_rows` — max rows (default 100)
- `p_c1lat`, `p_c1lon`, `p_c2lat`, `p_c2lon` — bounding box search (WGS84 decimal degrees; c1 = SW corner, c2 = NE corner)

The response `Results.QueryID` is a QID used to paginate. `Results.QueryRows` is the total count — but see "Reading `Results`" below before assuming that key is always present.

### Reading `Results` — rollups and the error shape

Two undocumented facts about the `Results` object, both verified live (2026-08-12):

- **An over-broad query returns an error, not an empty/large result set.** Querying too broadly (e.g. `p_st=LA` alone, no county/facility narrowing) returns `Results.Error.ErrorMessage` (e.g. `"Rows Returned would be 102935. Queryset Limit would be exceeded"`) and **no `QueryRows` key at all**. A naive `d['Results'].get('QueryRows')` silently returns `None` — do not treat that as zero results. **Always check `Results.get('Error')` first**, before reading `QueryRows`.
- **`Results` carries aggregate rollups**, which answer county-profiling questions in a single request with no paging needed: `QueryRows` (total facilities), `CAARows`, `CWARows`, `RCRRows`, `TRIRows`, `INSPRows`, `FEARows`, `SVRows`, and `TotalPenalties`. Verified: `p_act=Y&p_fips=22005` (Ascension Parish, active facilities) → `QueryRows: 1255`, `CAARows: 97`, `TotalPenalties: $4,939,501`. This is faster than pulling every facility and summing client-side.
  - **Scope warning: the rollups are all-program, not per-program.** `TotalPenalties` for Ascension ($4,939,501) sums CAA + CWA + RCRA together. A CAA-only figure computed by summing `CAAPenalties` per facility will be smaller (e.g. ~$1.62M for the same parish) — both are correct, but at different scopes. Never present a `Results`-level rollup as if it were specific to one program; state the scope explicitly whenever you cite one. This generalizes: before citing any aggregate field from any API, confirm what it actually aggregates rather than assuming it matches the label you were looking for.

### Step 2: Retrieve facility records using QID

```bash
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_qid?output=json&qid=QID&pageno=1&p_rows=25" 2>/dev/null
```

### Step 3 (optional): Get detailed facility report

```bash
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info?output=json&p_id=REGISTRY_ID" 2>/dev/null
```

### Full history: ECHO bulk downloads

The DFR's enforcement and compliance sections (`FormalActions`, `EnforcementComplianceSummaries`) cover only five years. Its TRI and waste history blocks reach further back. Verified 2026-10-08: Shell Norco's DFR `FormalActions` window opens 10/03/2021 and lists 9 actions. The bulk files cover decades. For the refinery's one air ID (`LA0000002208900002`) they hold 30 CAA formal actions dated 1986-08-26 to 2026-08-25, and for its RCRA ID (`LAD008186579`) 17 violations dated 1987–2002. Use them for "pattern of non-compliance" history and for any sweep across many facilities, since they also sidestep the rate limit below.

Zips live at `https://echo.epa.gov/files/echodownloads/<name>`, are refreshed weekly (per echo.epa.gov/tools/data-downloads), and need no key. Every member listed below decoded as strict UTF-8 in a full pass on 2026-10-08. Contents as listed that day:

| Zip (size) | Member CSVs worth knowing | Facility key column | FRS `pgm_sys_acrnm` to look up |
|---|---|---|---|
| `ICIS-AIR_downloads.zip` (70 MB) | `ICIS-AIR_VIOLATION_HISTORY` (HPV/FRV), `ICIS-AIR_FORMAL_ACTIONS` (`PENALTY_AMOUNT`), `ICIS-AIR_INFORMAL_ACTIONS` (NOVs), `ICIS-AIR_FCES_PCES` (inspections), `ICIS-AIR_STACK_TESTS`, `ICIS-AIR_TITLEV_CERTS` | `PGM_SYS_ID` | **`AIR`** (e.g. `LA0000002208900002`). The 10-digit `AIRS/AFS` ID matches nothing. |
| `npdes_downloads.zip` (355 MB) | `NPDES_QNCR_HISTORY` (quarterly noncompliance), `NPDES_SE_VIOLATIONS` / `NPDES_PS_VIOLATIONS` / `NPDES_CS_VIOLATIONS`, `NPDES_INSPECTIONS`, `NPDES_FORMAL_ENFORCEMENT_ACTIONS` | `NPDES_ID` | `NPDES` |
| `rcra_downloads.zip` (120 MB) | `RCRA_VIOLATIONS`, `RCRA_VIOSNC_HISTORY`, `RCRA_EVALUATIONS` (inspections), `RCRA_ENFORCEMENTS` | `ID_NUMBER` | `RCRAINFO` |
| `case_downloads.zip` (82 MB) | `CASE_FACILITIES` (has `REGISTRY_ID`), `CASE_ENFORCEMENTS` (`ENF_SUMMARY_TEXT`), `CASE_PENALTIES`, `CASE_DEFENDANTS`, `CASE_ENFORCEMENT_CONCLUSION_SEP` | `ACTIVITY_ID` / `CASE_NUMBER` | Start from `REGISTRY_ID` in `CASE_FACILITIES`. |

Get the program IDs from `bayou:epa-frs-crosswalk`. One registry ID usually maps to several air, NPDES and RCRA IDs, so pass them all.

Cache the zips in `~/.cache/bayou/echo/`, where `bayou:comparable-facilities` keeps its bulk file. Stream one member and filter as you go, so the 100–500 MB CSVs never load whole:

```bash
mkdir -p ~/.cache/bayou/echo
Z=ICIS-AIR_downloads.zip
[ -f ~/.cache/bayou/echo/$Z ] || curl -s -f -o ~/.cache/bayou/echo/$Z "https://echo.epa.gov/files/echodownloads/$Z"

python3 -I -c "
import sys, zipfile, io, csv
zpath, member, key, *ids = sys.argv[1:]
with zipfile.ZipFile(zpath).open(member) as fh:
    for r in csv.DictReader(io.TextIOWrapper(fh, encoding='utf-8', newline='')):
        if r[key] in ids:
            print({k: v for k, v in r.items() if v.strip()})
" ~/.cache/bayou/echo/$Z ICIS-AIR_FORMAL_ACTIONS.csv PGM_SYS_ID LA0000002208900002 LA0000002208900079
```

**Date formats are not uniform.** A tally of the first 300,000 rows of each file, run 2026-10-08, found:
- `ICIS-AIR_VIOLATION_HISTORY` (every date column) and `ICIS-AIR_FCES_PCES` (`ACTUAL_END_DATE`) use `MM-DD-YYYY`.
- Every other file above uses `MM/DD/YYYY`.
- `NPDES_QNCR_HISTORY.YEARQTR` is `YYYYQ`, e.g. `20061` for 2006 Q1.

Parse each file with its own format. Sorting the strings as they are mixes up years.

Re-download a zip when its `Last-Modified` header (`curl -sI`) is newer than the cached copy. Name the file and its `Last-Modified` date in any citation.

### SIC/NAICS codes by source system

`dfr_rest_services.get_dfr?output=JSON&p_id=REGISTRY_ID` returns `Results.SIC.Sources[].SICCodes[]` and `Results.NAICS.Sources[].NAICSCodes[]`. Each entry carries `EPASystem` (`ICIS-Air`, `TRI`, `GHGRP`, `EIS`, `ICIS-NPDES`, `RMP`) and `SourceID`, which shows which code belongs to the air permit and which to another program. The facility-search `FacSICCodes`/`FacNAICSCodes` fields merge them all into one space-separated string. The codes can be wrong: Shell Norco's EIS record lists NAICS 311812 (commercial bakeries). Prefer the ICIS-Air SIC for anything about the air permit. The endpoint sometimes returns 503, so retry.

To find industry peers by these codes and compare their emissions, use `bayou:comparable-facilities`.

### Demographics around a facility (official ACS profile)

The Detailed Facility Report endpoint, `https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?output=JSON&p_id=REGISTRY_ID`, returns `Results.ACS2024Demographics` and `Results.ACS2023Demographics`. Each block holds population, % people of color, % below low-income and poverty levels, and race, age, education, and income breakdowns for the population within **1 mile** of the facility's ECHO coordinate. With EJScreen offline, this is the remaining EPA-hosted source for fenceline demographics. Verified live 2026-10-07:
- The radius is fixed at 1 mile; `p_radius`, `p_dist`, and `radius` are ignored.
- The facility-search demographic fields (`FacPercentMinority`, `PercentPeopleOfColor`, `PercentBelowLowincome3mile`, `AcsPopulationDensity`) appear in the `metadata` column list but return null.
- It returns no percentiles and no EJ indexes. For those, and for the screening workflow that pairs them with this profile, use `bayou:ejscreen-report` (its Step 3 has the parsing snippet and the citation format).

## GPS Coordinates

ECHO stores geographic coordinates for most regulated facilities, but the two endpoints split them:

- **Latitude** (`FacLat`) — returned in the `get_qid` JSON response
- **Longitude** (`FacLong`) — returned in the `get_download` CSV response

To get **both coordinates** for matched facilities, run two requests against the same QID:

```bash
QID=<your QID>

# Step A: get latitude from JSON
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_qid?output=json&qid=${QID}&pageno=1&p_rows=25" 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
for f in d.get('Results', {}).get('Facilities', []):
    print(f.get('RegistryID'), '|', f.get('FacName'), '|', f.get('FacLat'))
"

# Step B: get longitude from CSV download
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_download?output=csv&qid=${QID}" 2>/dev/null | \
  python3 -c "
import sys, csv
for row in csv.DictReader(sys.stdin):
    print(row.get('RegistryID'), '|', row.get('FacName'), '|', row.get('FacLong'))
"
```

Join on `RegistryID` to assemble complete `(FacLat, FacLong)` pairs.

**If `FacLat` is null** (indicated by `FacMapIcon` containing `no_ll`), ECHO does not have georeferenced coordinates for that facility. Use the address fields for manual geocoding or cross-reference with the `bayou:facility-coordinates` skill.

Geographic search (find facilities within a bounding box):
```bash
# SW corner: 29.5°N 91.0°W  NE corner: 30.5°N 89.5°W
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_facilities?output=json&p_c1lat=29.5&p_c1lon=-91.0&p_c2lat=30.5&p_c2lon=-89.5&p_rows=50" 2>/dev/null
```

## How to present results

Parse `Results.Facilities[]` from the `get_qid` JSON response. Key fields per facility:

| Field | Source | Description |
|---|---|---|
| `FacName` | JSON | Facility name |
| `FacStreet`, `FacCity`, `FacState`, `FacZip` | JSON | Address |
| `FacCounty` | JSON | County |
| `RegistryID` | JSON | ECHO Registry ID (use for detail lookups and coordinate joins) |
| `FacLat` | JSON (get_qid) | Latitude — WGS84 decimal degrees |
| `FacLong` | CSV (get_download) | Longitude — WGS84 decimal degrees |
| `FacMapIcon` | JSON | Contains `no_ll` if facility lacks georeferenced coordinates |
| `FacComplianceStatus` | JSON | Overall compliance status |
| `CAAComplianceStatus` | JSON | Clean Air Act status |
| `CWAComplianceStatus` | JSON | Clean Water Act status |
| `RCRAComplianceStatus` | JSON | Hazardous waste status |
| `FacInspectionCount` | JSON | Number of inspections |
| `FacDateLastInspection` | JSON | Date of last inspection |
| `CAAFormalActionCount` | JSON | Number of formal CAA enforcement actions |
| `CAAPenalties` | JSON | Total CAA penalties |
| `FacPenaltyCount` | JSON | Total penalty count |
| `FacDateLastPenalty` | JSON | Date of last penalty |

### Presentation rules:
- Show a summary table: Name | Lat | Lon | County | State | Compliance Status | Inspections | Penalties
- **Flag a facility only on an exact-string match against the real values below, checked per program** — never on a substring match for "Violation" and never against the fictional "No Violation" value (see below). For each flagged facility, name the specific program (`CAAComplianceStatus`, `CWAComplianceStatus`, `RCRAComplianceStatus`) and its exact status string.
- **Exclude `null` from both the numerator and denominator of any "N flagged out of M" count.** `null` means the facility is not regulated under that program — it is neither compliant nor a violation, and including it either way misstates the rate.
- Construct the ECHO detail link: `https://echo.epa.gov/facilities/facility-search/facility?fid=REGISTRY_ID`
- If more than 10 results, show top 10 and note total count

### Interpreting ECHO data

ECHO records what agencies and facilities reported, not what happened. Word findings to match:
- Say "reported violations" and "estimated emissions". Emissions figures are mostly facility estimates, not measurements.
- **No recorded violation is not evidence of compliance.** A violation is recorded only if the facility reports it or an inspector finds it, and inspections have been declining for years. Treat a clean record as "none recorded", and pair it with the inspection count and the last inspection date.
- **Compliance with a permit does not make the permit adequate.** Permit limits seldom account for cumulative exposure from neighboring sources. Keep "in compliance" separate from "safe".
- **Missing data is common and uneven.** EDGI's *Gaps and Disparities* report (2022) found that most program-specific fields were blank for the typical facility, and that gaps were worse in majority-minority areas. Cite it by name and year as a documented pattern. Do not quote its percentages as current figures.
- CWA/NPDES records are generally the most *reliable*, because federal rules require permittees to submit DMRs electronically to EPA (Cynthia Giles, *Next Generation Compliance*, 2020). Reliable does not mean complete: EDGI found CWA-specific fields blank more often than CAA ones.

### Compliance status values

The values below are per-program (`FacComplianceStatus`, `CAAComplianceStatus`, `CWAComplianceStatus`, `RCRAComplianceStatus` each have their own vocabulary) and were confirmed against a live sample (West Baton Rouge Parish, LA, n=408 facilities, 2026-08-12) — an earlier version of this list was largely fictional (`No Violation`, `In Violation`, `High Priority Violation` do not occur in live data) and its presentation rule flagged every facility as a result, because `No Violation` never matches the real value `No Violation Identified`.

- **`FacComplianceStatus`** (overall) — `No Violation Identified`, `Violation Identified`, `Significant Violation`, `Violation`, `Unknown`, or `null`
- **`CAAComplianceStatus`** — `No Violation Identified`, `Violation Addressed; State Has Lead Enforcement`, `Violation Addressed; EPA Has Lead Enforcement`, or `null`. **`Violation Addressed...` means the violation is resolved** — it is not an open violation, despite containing the word.
- **`CWAComplianceStatus`** — adds `Significant/Category I Noncompliance`, `Terminated Permit`, `Not Applicable`
- **`RCRAComplianceStatus`** — adds `Significant Noncomplier`
- **`null` is the single most common value across all three program fields** (332/408 for CAA in the sample) and means "not regulated under this program" — not compliant, not violating. Treat it as excluded from the count, never as either outcome.

No API key required. QIDs expire after ~30 minutes.

For a water permit's receiving-water context (303(d) impairments, TMDLs, other dischargers in the watershed, calculated loads), use `bayou:cwa-watershed-context`.

Cross-link `bayou:epa-frs-crosswalk` for full program-ID resolution — one FRS `registry_id` lookup returns every program ID a facility holds (TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP `E-GGRT`, and LDEQ's `LA-TEMPO` ID), which is faster than resolving each one individually through its own program's search.

> **⚠️ Rate limit (verified 2026-06-09).** ECHO throttles at **300 requests/hour and 1,500/day**. Exceeding it returns **HTTP 429** with an error body — `"If your requests exceed 300 per hour or 1,500 per day, we will throttle your request. ECHO has exports of bulk data available for download at https://echo.epa.gov/tools/data-downloads."` — and the same-day quota does not reset until the next day. Pace requests (don't loop tightly over many RegistryIDs), and for multi-facility sweeps prefer the **bulk data downloads** (see "Full history: ECHO bulk downloads" above) over the REST endpoints.
>
> **Maintenance outages are a different failure.** ECHO REST often goes down around midnight Central, sometimes for hours. It returns **HTTP 503** with an Apache "maintenance downtime or capacity problems" page, or the request times out. That is not throttling; only 429 means the quota is spent. Retry later.

$ARGUMENTS
