---
name: csb-nrc-hazmat
description: Federal chemical-incident records for a facility, company, parish or radius — U.S. Coast Guard National Response Center (NRC) spill and release reports from the yearly FOIA workbooks (1990 to date; material, amount, medium, injuries, evacuations, the caller's narrative, state agency report number), U.S. Chemical Safety Board investigations (findings, final reports, every recommendation with its recipient and open/closed status), and the CSB Accidental Release Events list under 40 CFR Part 1604 (2020 on; fatality, serious injury or $1M+ damage, with incident-report PDFs). Use to build a documented release history against "no significant risk" claims, count and characterize a facility's releases over time, check CSB recommendation follow-through, and compare federal release reports with a facility's self-reported RMP accident history (epa-rmp-lookup). NRC here is the National Response Center, not the Nuclear Regulatory Commission.
argument-hint: nrc --state LA --county "<parish>" [--company "A|B"] [--years 2021-2026] | nrc-report <SEQNOS> | nrc-summary ... | csb-investigations --state LA | csb-detail <slug> | csb-releases --state Louisiana | health
allowed-tools: Bash, Read, AskUserQuestion, WebFetch
---

# CSB and National Response Center incident records

**Disambiguation.** The **National Response Center (NRC)** is the federal spill and release hotline (1-800-424-8802), staffed by the U.S. Coast Guard. It has nothing to do with the Nuclear Regulatory Commission, which is `bayou:nrc-adams-search`.

Three federal sources, one script:

| Source | What it records | Coverage | Reads as |
|---|---|---|---|
| **NRC reports** | Every call to the hotline: oil and chemical releases, sheens, pipeline and rail incidents, potential releases | 1990 to date; Louisiana: 5,033 reports in 2010, 2,444 in 2020, 1,749 in 2026 through early October | **Frequency.** The caller's account, usually the operator's |
| **CSB Accidental Release Events** (40 CFR 1604) | Air releases from stationary sources causing a death, inpatient hospitalization, or ≥ $1M property damage | 2020-03-23 on; 675 events nationally, 93 in Louisiana (Sept 2026 list) | **Severity threshold met**, by the operator's own report |
| **CSB investigations** | Root-cause investigations CSB chose to open, with recommendations | 1998 on; 134 completed, 6 current | **Severity and cause**, with federal findings |

Each source catches what the others miss. A gap between them is a question to ask, not a finding (see "Comparing sources").

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/csb-nrc-hazmat"
uv run -q --no-project --with openpyxl python -I "$S/hazmat.py" <command> ...
```

| Command | Does |
|---|---|
| `health` | NRC file listing and dates, CSB listing parse, the current Accidental Release Events workbook link, cached NRC years |
| `nrc --state LA [--county X] [--city X] [--type PIPELINE] [--company "A\|B"] [--text X] [--material X] [--years 2021-2026] [--near LAT LON --radius-km N] [--csv out.csv]` | NRC reports, one entry per report number, newest first. Drills are excluded unless `--include-drills` |
| `nrc-summary` (same filters) | Counts by year, incident type, medium, parish, cause, company and material; injury, evacuation and reached-water totals |
| `nrc-report <SEQNOS> [--year YYYY]` | Every field of one report, across all the workbook's sheets |
| `csb-investigations [--state LA] [--company X] [--status current\|completed]` | CSB investigation list with location, date and summary |
| `csb-detail <slug or URL>` | Facts, description, final-report links, and each recommendation's number, recipient, text and status |
| `csb-releases [--state Louisiana] [--company X] [--city X] [--csv out.csv]` | 40 CFR 1604 events with harm flags and incident-report PDF links |

`--json` and `--refresh` work on either side of the command. Exit codes: 3 no match or not found, 4 download needs confirmation, 5 source down (cached copies are used when they exist).

**Downloads (exit code 4).** NRC data comes as one workbook per year, 10–18 MB each (`CY26.xlsx` 10.1 MB, `CY25.xlsx` 18.0 MB, `CY10.xlsx` 17.8 MB). Each is fetched once, parsed, and cached as compact JSON in `~/.cache/bayou/csb-nrc-hazmat/nrc/`. The current and previous year are re-checked against the server's Last-Modified date once a day. When a command needs more than one uncached workbook, or more than 50 MB, it prints each file, its size and date, and exits 4. Show that list to the user with AskUserQuestion. Rerun with `--yes` only if they agree, or narrow `--years`. **Never pass `--yes` on your own.** A single-file download prints its size to stderr and proceeds; mention the size when you report results. The default window (the last 5 years) is about 73 MB on first run. Full history (1990 to date) is about 37 files and over 500 MB.

## NRC reports

### Finding a facility's reports

NRC records have no facility ID. Match on what the caller said:

1. **Parish plus company, with aliases.** `--county "St. Charles" --company "SHELL|MOTIVA"`. A single site appears under many names: Shell Norco's 54 reports in 2010 used 8 spellings (MOTIVA ENTERPRISES, SHELL CHEMICAL, SHELL MOTIVA, SHELL/ MOTIVA ENTERPRISES, SHELL, MOTIVA, MOTIVA NORCO REFINERY, SHELL PIPELINE COMPANY). To build the alias set, run `nrc-summary --city <town>` (or `--text "<street number> <street>"`) and read its company list. It shows up to 60 names, so one-off spellings are included. Then rerun with the aliases.
2. **Address or landmark words.** `--text "15536 RIVER"` with `--city NORCO`. Words must all appear in the description, location or address. Use both routes and merge the results: for Shell Norco in 2010 the alias search found 54 reports and the refinery-address search found 50, because Shell Chemical and pipeline reports give other addresses.
3. **Radius last.** `--near LAT LON --radius-km N` keeps only reports with coordinates, and most fixed-facility reports have none: 30 of 39 St. Charles reports in 2026 lacked them. The output says how many matches it dropped for that reason. Use radius search for sheens, vessels and pipelines, not plants.

Parish names follow NRC's spelling (`ST. CHARLES`, `E. BATON ROUGE`, `ST. JOHN THE BAPTIST`). The script normalizes "Parish", "Saint" and "East/West", so `--county "Saint Charles Parish"` works. Offshore blocks appear as pseudo-parishes (`GREEN CANYON AREA`, `MAIN PASS AREA`). Filters use the **incident** location, never the responsible party's address.

**`--years` is the year NRC received the call.** Each workbook holds the calls received that year, so a late-December incident can sit in the next year's file: CY26's first report is a 12/31/2025 incident. For a calendar-year count, add the following year and filter on `incident_date`.

### Reading a report

- **The caller's account, not a finding.** NRC states that its spreadsheets "contain INITIAL incident data that has not been validated or investigated by a federal/state response agency". Quote it as "reported to the NRC by [caller]", not as fact.
- **Unknown is not zero.** About 60% of material lines in 2026 say `UNKNOWN AMOUNT` (the script prints "unknown amount"). CAS `000000-00-0` means none was given. Do not sum amounts across reports with mixed units or unknowns.
- **Reports are not events.** Count follow-ups separately. The script flags reports whose description cites an earlier report number ("UPDATE TO NRC 1461720", "CORRECTION TO NRC REPORT 1470627", PHMSA 48-hour updates) as `update of N`, and the header counts them. `POTENTIAL` marks reports of a threatened release with none confirmed at the time (a sinking vessel, a damaged tank). In St. Charles 2026, 39 reports include 6 updates and 1 potential report.
- **Why a release was reported.** 40 CFR 302.6 requires anyone in charge of a facility to notify the NRC immediately on learning of a release of a CERCLA hazardous substance at or above its reportable quantity. Oil discharges in a harmful quantity, which includes a sheen (40 CFR 110.3, notice under 110.6) and pipeline, rail and vessel incidents are also reported. A report is evidence a release was called in. It is not proof the reportable quantity was exceeded, and callers report below-RQ releases too.
- **Louisiana follow-up.** `STATE_AGENCY_NOTIFIED` and `STATE_AGENCY_REPORT_NUM` (for example `LA STATE POLICE / LDEQ`, `26-02887`) appear in `nrc-report`. Only 253 of the 1,749 Louisiana reports in 2026 carry a state report number. Most are State Police numbers in `YY-NNNNN` form, the same form as the "LSP Case #" on LDEQ release reports, so the number can tie an NRC call to the state file. In Louisiana, the discharger must also call the State Police hazmat hotline: within 1 hour for an emergency condition, regardless of amount (LAC 33:I.3915), or within 24 hours for a non-emergency release over a reportable quantity (LAC 33:I.3917). It must then file a written report with LDEQ's Single Point of Contact within 7 calendar days (LAC 33:I.3925). Find those written reports with `bayou:ldeq-edms-search` (function `Single Point of Contact (SPOC)` or `Incidents - Emergency`), searching by AI number and date. They usually carry the cause analysis and the quantity estimate the NRC call lacked.
- Workbook quirks the script handles: a line break inside a free-text field can push the rest of the record onto a new row, and the script keeps those fragments with the report as `_CONTINUED`. One continuous-release sheet is spelled `MATERIAL_INV0LVED_CR` (with a zero). Workbooks from 1990, 2000, 2010 and 2026 share the same sheets and columns.

## CSB Accidental Release Events (40 CFR 1604)

`csb-releases` reads the list CSB links from its [reporting-rule page](https://www.csb.gov/news/incident-report-rule-form-/), re-reading the link each day because the filename carries the list's date. The list gives date, company (often a short name such as "Valero" or "LACC"), city, state, and which threshold was met. About a quarter of the Louisiana rows link an incident-report PDF.

What the rule says (40 CFR 1604.2–1604.6, checked 2026-10-16):
- It applies to an accidental release of a regulated or extremely hazardous substance into the ambient air from a stationary source that results in a fatality, a **serious injury (death or inpatient hospitalization)**, or **substantial property damage (≥ $1,000,000)**. It took effect 2020-03-23.
- The operator either sends CSB its **NRC report number within 30 minutes** of calling the NRC, or reports **directly to CSB within 8 hours** (1604.3(b)–(c)). So an event may or may not have an NRC report.
- CSB revises the list quarterly, including late-reported events. Full reports are available through a FOIA request to CSB (1604.6, 40 CFR Part 1601).
- Being on the list does not mean CSB investigated.

The compiled Incident Report Volumes I–IV, linked on the same page and printed by the command, collect the published incident reports.

## CSB investigations

`csb-investigations` reads CSB's current and completed investigation listings (about 21 pages, cached 7 days). `--state` matches the listing's "City, ST" location. `csb-detail` takes the slug from that listing. Slugs often end in a stray hyphen (`williams-olefins-plant-explosion-and-fire-`), and a near-miss slug prints the listed alternatives.

Louisiana investigations currently listed: Dow Louisiana Operations (Plaquemine, final report 2026), Honeywell Geismar (2025), Bio-Lab Lake Charles (2023), Packaging Corporation of America DeRidder (2018), ExxonMobil Baton Rouge (2017), Williams Olefins Geismar (2016), Honeywell Baton Rouge (2005), Sonat Exploration Pitkin (2000), Union Carbide Hahnville (1999).

Reading CSB records:
- **Recommendations.** Each has a number (`2023-03-I-LA-1`), a recipient (the company, a trade group such as API or NFPA, or a regulator) and a status. "Open - Awaiting Response or Evaluation/Approval of Response", "Open - Unacceptable Response/No Response Received" and "Closed - Unacceptable Action/No Response Received" are the ones that show a known hazard not yet addressed. CSB's status-change summaries are linked from each recommendation on the page.
- **Current investigations** are not findings yet. Cite them as an ongoing federal investigation.
- The listing covers investigations only. CSB safety studies, and incidents it screened and declined to investigate, are not in it.

## Comparing sources

**NRC vs RMP.** `bayou:epa-rmp-lookup accidents <EPAFacilityID>` lists the accidents a facility put in its Risk Management Plans. RMP accident criteria cover only covered processes and only on-site deaths, injuries or significant property damage, or known off-site deaths, injuries, evacuations, sheltering, or property or environmental damage. NRC takes every reportable-quantity release, sheen and potential release. **Many more NRC reports than RMP accidents is the normal pattern, not evidence of under-reporting.** Shell Norco filed 54 NRC reports in 2010 (46 to air, none with injuries or evacuations) and listed one 2010 RMP accident (2010-01-22, 1 lb propane and 3 lb butane). No NRC report in the 2010 file matches that date. Different triggers explain gaps in both directions. A specific NRC report describing injuries, an evacuation or shelter-in-place at an RMP-covered process, with no matching RMP accident, is the gap worth taking to the facility or the RMP implementing agency (LDEQ in Louisiana), as a question.

**CSB events vs NRC.** Because operators can report to CSB either through the NRC or directly, a CSB event without a matching NRC report is allowed under 1604.3(c). Valero Meraux's 2020-04-10 event (one serious injury, about $5.15M damage, about 49,000 lb of hydrogen and hydrocarbon released, per the CSB incident report) has no matching report in the 2020 NRC file: none of the Louisiana reports for April 10–11 mention Valero, Meraux or the refinery, and the CSB report cites no NRC number. Whether a CERCLA or state notification was separately due turns on the substance and amount released, which the incident-report PDF and the LDEQ written report (LAC 33:I.3925) will show.

**CSB and NRC vs OSHA and ECHO.** Releases that injure workers often lead to OSHA inspections (`bayou:osha-inspections`), and repeated releases can surface as Clean Air Act violations or enforcement in ECHO (`bayou:epa-echo-search`). Look for them; don't assume them.

## Workflow

1. **Identify the facility**: name, address, parish, AI number and coordinates, using `bayou:ldeq-ai-lookup`, `bayou:epa-frs-crosswalk` or `bayou:facility-coordinates`.
2. **Severity**: `csb-releases --state Louisiana --company <short name>` and `csb-investigations --state LA --company <name>`, then `csb-detail` on any hit for recommendations and status.
3. **Frequency**: `nrc-summary --county <parish> --company "<alias|alias>" --years <range>` (confirm downloads with the user), then refine the alias set from its company list and run `nrc` for the rows, or `--csv` for a table.
4. **Detail**: `nrc-report <SEQNOS>` for the reports that matter (injuries, evacuations, water, large or repeated releases), then the LDEQ written follow-up in `bayou:ldeq-edms-search`. For a release to water, `bayou:ldh-drinking-water downstream <lat> <lon>` lists the drinking-water intakes below the release point.
5. **Self-reported history**: `bayou:epa-rmp-lookup facility` and `accidents`, compared as above.
6. **Enforcement**: `bayou:epa-echo-search` and `bayou:osha-inspections`.

## How to present findings

### Volume
> "The National Response Center received N reports of releases at or from [facility] between [year] and [year] (NRC FOIA data, call years [range]); M were updates to earlier reports. The reports name [key materials]; [X] were to air and [Y] reached water. Quantities were not given in [Z] reports."

### Severity
> "Under 40 CFR Part 1604, [operator] reported [N] accidental releases at [facility] to the Chemical Safety Board since 2020 that caused [a death / an inpatient hospitalization / at least $1 million in property damage]: [dates]."

> "The CSB investigated [incident] ([year]) at [facility], which [deaths/injuries/damage]. The Board found [key finding] ([final report title], [date])."

### Pattern
> "Of the N reports, [X] involve [chemical] from [unit or cause], a recurring release pathway. [Operator] nonetheless characterizes [project] as presenting no significant risk."

### Recommendation follow-through
> "CSB Recommendation [number] to [recipient], issued after the [incident] investigation, called for [action]. CSB lists its status as '[status]' (retrieved [date])."

### NRC and RMP side by side (a lead, not a finding)
> "[Facility]'s Risk Management Plans list [N] accidents in [period]; [M] reports were made to the National Response Center over the same period. RMP accident criteria are narrower than NRC reporting, so the counts are not expected to match. However, NRC report [SEQNOS] ([date]) describes [injuries / an evacuation / shelter-in-place] involving [chemical], and no RMP accident on that date appears in any submission. We ask [the facility / LDEQ] to explain whether this event met the RMP accident-history criteria."

## Citation format

> National Response Center report 1472419, received 2026-09-01: DOW CHEMICAL, 355 Hwy 3142, Hahnville, St. Charles Parish, LA; ethylene diamine to air, amount unknown; state agency report 26-02887. U.S. Coast Guard National Response Center, FOIA data file CY26.xlsx (Last-Modified 2026-10-05), https://nrc.uscg.mil/FOIAFiles/CY26.xlsx, retrieved 2026-10-16. Initial report, not validated by a response agency.

> CSB Accidental Release Events list (September 1, 2026): Valero, Meraux, Louisiana, 2020-04-10, serious injury and substantial property damage; incident report https://www.csb.gov/assets/1/6/2020-04-10_valero_incident_report.pdf. U.S. Chemical Safety and Hazard Investigation Board, https://www.csb.gov/news/incident-report-rule-form-/, retrieved 2026-10-16.

> U.S. Chemical Safety and Hazard Investigation Board, Dow Louisiana Operations Explosions (Plaquemine, LA; incident 2023-07-14; final report released 2026-02-26), Recommendation 2023-03-I-LA-1 to Dow Chemical Company, status "Open - Acceptable Response or Alternate Response". https://www.csb.gov/dow-louisiana-operations-explosions/, retrieved 2026-10-16.

Every command prints its source URL, the workbook's Last-Modified date or the list's date, and the retrieval date. Carry them into the citation.

$ARGUMENTS
