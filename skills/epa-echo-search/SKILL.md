---
name: epa-echo-search
description: Search EPA ECHO for facility compliance and enforcement history; also returns GPS coordinates (lat/lon) for regulated facilities
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
- `p_id` — registry ID (exact)
- `p_act` — active facilities only: `Y`
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

### Compliance status values

The values below are per-program (`FacComplianceStatus`, `CAAComplianceStatus`, `CWAComplianceStatus`, `RCRAComplianceStatus` each have their own vocabulary) and were confirmed against a live sample (West Baton Rouge Parish, LA, n=408 facilities, 2026-08-12) — an earlier version of this list was largely fictional (`No Violation`, `In Violation`, `High Priority Violation` do not occur in live data) and its presentation rule flagged every facility as a result, because `No Violation` never matches the real value `No Violation Identified`.

- **`FacComplianceStatus`** (overall) — `No Violation Identified`, `Violation Identified`, `Significant Violation`, `Violation`, `Unknown`, or `null`
- **`CAAComplianceStatus`** — `No Violation Identified`, `Violation Addressed; State Has Lead Enforcement`, `Violation Addressed; EPA Has Lead Enforcement`, or `null`. **`Violation Addressed...` means the violation is resolved** — it is not an open violation, despite containing the word.
- **`CWAComplianceStatus`** — adds `Significant/Category I Noncompliance`, `Terminated Permit`, `Not Applicable`
- **`RCRAComplianceStatus`** — adds `Significant Noncomplier`
- **`null` is the single most common value across all three program fields** (332/408 for CAA in the sample) and means "not regulated under this program" — not compliant, not violating. Treat it as excluded from the count, never as either outcome.

No API key required. QIDs expire after ~30 minutes.

Cross-link `bayou:epa-frs-crosswalk` for full program-ID resolution — one FRS `registry_id` lookup returns every program ID a facility holds (TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP `E-GGRT`, and LDEQ's `LA-TEMPO` ID), which is faster than resolving each one individually through its own program's search.

> **⚠️ Rate limit (verified 2026-06-09).** ECHO throttles at **300 requests/hour and 1,500/day**. Exceeding it returns **HTTP 429** with an error body — `"If your requests exceed 300 per hour or 1,500 per day, we will throttle your request. ECHO has exports of bulk data available for download at https://echo.epa.gov/tools/data-downloads."` — and the same-day quota does not reset until the next day. Pace requests (don't loop tightly over many RegistryIDs), and for multi-facility sweeps prefer the **bulk data downloads** (https://echo.epa.gov/tools/data-downloads) over the REST endpoints.

$ARGUMENTS
