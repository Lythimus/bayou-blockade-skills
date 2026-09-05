---
name: csb-nrc-hazmat
description: Search CSB chemical incident investigations and USCG National Response Center (NRC) hazmat spill/release reports to build a concrete incident record
allowed-tools: Bash, Read, WebFetch, AskUserQuestion
---

# CSB & National Response Center Hazmat Incident Search

Search two complementary federal databases for chemical safety incidents and hazmat release reports. Use these to build a documented incident record — a concrete counter to "no significant risk" assertions.

**Critical disambiguation:** The **National Response Center (NRC)** is a USCG-operated hazmat hotline, wholly unrelated to the Nuclear Regulatory Commission. The nuclear NRC is covered by `bayou:nrc-adams-search`.

---

## Two databases, one goal

| Database | Agency | Coverage | Best for |
|---|---|---|---|
| **CSB** | Chemical Safety Board | Significant accidents formally investigated | Root cause, recommendations, casualties, systemic failures |
| **NRC Query** | USCG / National Response Center | All reported hazmat releases since 1990 (500k+ records) | Volume, pattern, near-misses, operator self-reports |

CSB records document severity. NRC records document frequency. Both together undermine "no significant risk" framings.

---

## 1. CSB Incident Database

### Source
- Main incident list: `https://www.csb.gov/incidents/`
- No formal public REST API; use WebFetch to retrieve and parse
- Each investigation has a dedicated case page with full findings

### Searching for a facility or company

**Option A — Search the incidents index:**
```
WebFetch: https://www.csb.gov/incidents/
```
Parse the returned HTML for `<article>` or incident card elements. The page lists all investigations with title, date, location, and status. Filter by reading all entries and matching against the facility name or operator.

**Option B — Site search:**
```
WebFetch: https://www.csb.gov/?s=COMPANY+NAME+STATE
```
Replace `COMPANY+NAME+STATE` with URL-encoded search terms (e.g., `Entergy+Louisiana`).

**Option C — Geographic filter via URL:**
```
WebFetch: https://www.csb.gov/incidents/?F_State=LA
```
State filter parameter. Can combine: `?F_State=LA&F_Year=2019`

### Fetching a specific investigation

Once you identify a case from the index, fetch its full page:
```
WebFetch: https://www.csb.gov/incidents/CASE-SLUG/
```

Example: `https://www.csb.gov/incidents/2013-west-fertilizer-explosion-and-fire/`

### Key data to extract per incident

| Field | Where to find it |
|---|---|
| Incident name & date | Page title / header |
| Location (facility, city, state) | Summary section |
| Company / operator | Summary section |
| Casualties | Deaths and injuries count in summary |
| Chemicals involved | Summary or investigation report |
| Root cause / key findings | "Key Findings" or investigation report link |
| Recommendations | "Recommendations" section |
| Investigation status | Open / Closed / No-Go |
| Reports & videos | Linked documents at bottom of page |

### Interpreting CSB findings

- **Open investigations**: Findings not yet final — cite as ongoing federal review
- **Closed with recommendations**: Check whether recommendations were accepted/implemented; unimplemented recommendations = known unaddressed hazard
- **No-Go decisions**: CSB declined to investigate; note this does not mean no incident occurred
- Recommendations to industry (not just the specific facility) indicate systemic risk recognized by the federal safety board

---

## 2. USCG National Response Center (NRC) Hazmat Query

### Source
- Public query interface: `https://nrc.uscg.mil/`
- All reports submitted to the NRC Hotline (1-800-424-8802) since ~1990
- Regulatory reporters: facilities, pipeline operators, carriers, vessel operators
- Reports are legally required under CERCLA, EPCRA, Clean Water Act, OPA, and HMTA

### Why NRC reports matter

When an operator releases a regulated substance above its **Reportable Quantity (RQ)**, federal law requires an NRC call. The report is the operator's own admission of a release. High volumes of small NRC reports reveal a pattern the operator may characterize as "routine" — but each report is a documented release event.

### Querying the NRC

The NRC runs on Oracle APEX (ORDS). Use WebFetch to access the query form and parse results.

**Step 1 — Load the query form:**
```
WebFetch: https://nrc.uscg.mil/ords/f?p=171:3
```

**Step 2 — Identify form fields in the returned HTML:**
Key form inputs to look for:
- `P3_RPTTYPE` — Incident type (Fixed Facility, Pipeline, Vessel, Vehicle/Railroad, Other)
- `P3_DATEFRM` — Date from (MM/DD/YYYY)
- `P3_DATETO` — Date to (MM/DD/YYYY)
- `P3_STATE` — State (two-letter code, e.g., `LA`)
- `P3_CNTY` — County name
- `P3_RESPPARTY` — Responsible party / company name
- `P3_MATERIAL` — Chemical/material name

**Step 3 — Submit the form** and parse the results table.

### Direct report lookup by NRC report number

If you have a specific NRC report number (e.g., from an OSHA citation or news report):
```
WebFetch: https://nrc.uscg.mil/ords/f?p=171:2:0::::P2_ID:REPORT_NUMBER
```

### NRC report fields

| Field | Description |
|---|---|
| Report # | Unique NRC incident number |
| Date / Time | When the call was made (note: may be same day as incident or next business day) |
| Incident Type | Fixed facility, pipeline, vessel, vehicle/railroad |
| Responsible Party | Company/operator name and contact |
| Incident Location | Address, county, state; lat/lon when available |
| Material(s) | Chemical(s) involved |
| Quantity Released | Amount (in pounds or gallons); "unknown" is common |
| Medium Affected | Air, water (specify body), land, groundwater |
| Injuries / Deaths | Casualties (0 if none) |
| Evacuation | Whether nearby areas were evacuated |
| Description | Free-text narrative of the incident |

### Interpreting NRC report patterns

- **Frequency**: Count reports per year — a trend of increasing reports is significant
- **"Unknown" quantities**: Operators often report unknown quantities; do not let this minimize the record
- **Same material, same location**: Repeat releases of the same chemical establish a persistent failure pattern
- **RQ thresholds**: Even a release just over the RQ (the minimum reportable amount) is legally required to be reported — these small entries are real events, not administrative artifacts
- **Lag between incident and report**: NRC calls can be made up to 24 hours after discovery; FOIA the actual NRC call log if exact timing matters

---

## 3. Supplementary: EPA RMP Accident History

Facilities storing regulated substances above threshold quantities must file a **Risk Management Plan (RMP)** with EPA that includes a 5-year accident history. This is the operator's self-reported version of the same events that would appear in NRC and CSB records — and under-reporting or omission is itself a violation.

### Searching RMP data

```bash
# Search RMP facilities by name and state via EPA's public RMPDB
curl -s "https://ofmpub.epa.gov/apex/rmpdb/r/rmpdb_public/facility-search" \
  --data-urlencode "q=FACILITY_NAME" \
  --data-urlencode "state=LA" \
  2>/dev/null
```

Or via EPA's RMP portal:
```
WebFetch: https://www.epa.gov/rmp
```

Then navigate to facility search and filter by company name and state.

### What RMP accident history contains

- Date of accident
- Chemical involved and quantity released
- Deaths, injuries, evacuations, sheltering-in-place
- Off-site impacts (property damage, environmental damage)
- Initiating event (equipment failure, human error, external cause)
- Contributing factors
- Changes made after the accident

Compare RMP accident history against NRC reports for the same facility. Gaps (events in NRC but not in RMP) may indicate under-reporting.

---

## Cross-database workflow

1. **Confirm facility identity** — use `bayou:facility-coordinates` or `bayou:epa-echo-search` to get the exact registered name and location
2. **Search CSB** by company name and state — note all investigations, open and closed
3. **Query NRC** for all hazmat reports at that facility name and/or county + state
4. **Check OSHA** (`bayou:osha-inspections`) — NRC incidents frequently trigger OSHA Process Safety Management (PSM) investigations; citations cite the same events
5. **Pull RMP accident history** for the facility — compare against NRC record for gaps
6. **Check EPA ECHO** (`bayou:epa-echo-search`) — some NRC releases trigger EPA enforcement actions documented in ECHO

---

## How to present findings

### Volume summary
> "NRC records show N hazmat release reports filed by [operator] at [facility] between [year] and [year], including releases of [list key chemicals]."

### Severity summary
> "The CSB investigated [N] incidents at [operator] facilities nationally, including [incident name] ([year]) in [state], which resulted in [deaths/injuries] and identified [root cause]. The investigation found [key finding]."

### Pattern analysis
> "Of the N NRC reports, [X] involve [specific chemical], suggesting a recurring release pathway. [Y] reports describe releases affecting [air/water/land]. Despite these documented releases, [operator] characterizes [project] as presenting no significant risk."

### Recommendation non-compliance
> "CSB Recommendation [#] to [operator or industry], issued [date], called for [action]. As of [date], this recommendation remains [open/unresolved], indicating the systemic hazard identified by federal investigators has not been corrected."

### RMP discrepancy
> "EPA RMP records for [facility] list [N] accidents in the 5-year reporting period. NRC records for the same period show [M] release reports. The discrepancy of [M-N] events warrants scrutiny of the facility's RMP compliance."

$ARGUMENTS
