---
name: epa-webfire-reports
description: Search and download the NESHAP/NSPS compliance reports that facilities file through EPA CEDRI and that EPA publishes in WebFIRE — semiannual periodic/compliance and excess-emissions reports (flare root-cause analyses, LDAR, pressure-relief releases), performance tests, and notifications of compliance status
allowed-tools: Bash, AskUserQuestion
---

# EPA WebFIRE Report Search (CEDRI filings)

Facilities subject to 40 CFR Part 60/62/63 standards must submit many of their required reports
electronically through EPA's **CEDRI** (Compliance and Emissions Data Reporting Interface). EPA
then publishes copies in **WebFIRE**, where they are public: periodic reports about 30 days after
submission and performance tests about 60 days after. These are the operator's own sworn
compliance filings to EPA. They often carry more equipment-level detail than anything in ECHO:
- deviations and their causes;
- flare events and the root-cause/corrective-action analyses that 40 CFR 63.670(o) requires;
- LDAR results;
- pressure-relief-device releases;
- periods of monitor downtime.

This skill covers three WebFIRE report types:

| `--type` | WebFIRE label | What it holds |
|---|---|---|
| `AER` (default) | Air Emissions Reports | Periodic / semiannual compliance reports, excess-emissions reports, fenceline-monitoring reports |
| `ST` | Performance Test Reports | Stack tests, performance evaluations, RATAs |
| `NOCS` | Notification of Compliance Status | Initial-compliance certifications |

**What this is not:** ECHO (`/bayou:epa-echo-search`) carries inspections, violations and
enforcement; WebFIRE carries the reports themselves. State-filed reports, such as Title V
semiannual deviation reports and incident reports, live in the state system, for Louisiana
`/bayou:ldeq-edms-search`. A facility can file overlapping content in both, so check both.

## Prerequisites

One-time setup, from this skill's directory:

```bash
cd ~/.claude/plugins/bayou/skills/epa-webfire-reports
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

The script runs headless (WebFIRE has no CAPTCHA). Add `--headful` to watch it.

## Step 0: health check

WebFIRE's results page (`eSearchResults.cfm`) sometimes fails server-side for **every** query. It
returns EPA's "Resource Not Found … application or system error" page (HTTP 200 or 500), even for
an empty search in an ordinary browser. Check first:

```bash
node ~/.claude/plugins/bayou/skills/epa-webfire-reports/webfire_search.js --health
```

Exit code 0 means all three stages are OK. **Exit code 3** means EPA's side is down: tell the user,
don't retry in a loop, and suggest trying again later or reporting it to the WebFIRE contact on
the page. A down `results` stage alone is the known outage mode, so the form and subpart lookup can
report OK while searches fail.

## Parsing arguments

Resolve these before searching:
- **Facility.** Location (`--state`, `--county`, `--city`), `--frs` registry IDs, or free-text
  `--org` / `--facility`. Get the FRS IDs from `/bayou:epa-frs-crosswalk`. A large industrial site
  often has several FRS IDs (the complex, each operating company, each plant side).
  **Avoid `--county`.** It matches the county text the filer typed, exactly, and filers spell it
  many ways (`ST. CHARLES`, `ST. CHARLES PARISH`, `ST CHARLES`, `SAINT CHARLES`, `St. Charles`), so
  one value misses most filings. Organization and facility names vary just as much between filings
  of the same plant. The reliable pattern is `--state` plus a short distinctive `--facility`
  substring (e.g. `"NORCO CHEMICAL PLANT"`), or `--state` alone, then filter `webfire_INDEX.csv`
  on City/Facility/Organization client-side. A statewide search returns thousands of rows in one
  page and is fine to run.
- **Rule.** `--part` (`Part 60`, `Part 62`, `Part 63`) and one or more exact `--subpart` values.
  List them with:
  ```bash
  node ~/.claude/plugins/bayou/skills/epa-webfire-reports/webfire_search.js --list-subparts --part "Part 63"
  ```
- **Window.** `--from` / `--to` in MM/DD/YYYY. These dates are the **CEDRI submission** dates, not
  the compliance period. A semiannual report for Jul–Dec is usually submitted in the following
  Jan–Mar, so extend `--to` at least 90 days past the period you care about.

### Which subparts to search, by facility type

| Facility / question | Part 63 subparts | Part 60 subparts |
|---|---|---|
| Ethylene / olefins cracker (flares follow 63.670 via EMACT) | `Subpart YY` (EMACT source category), `Subpart XX` (heat exchangers, waste), `Subpart SS` (control devices), `Subpart UU` (LDAR) | `Subpart VVa` |
| Petroleum refinery (flares, fenceline benzene) | `Subpart CC`, `Subpart UUU` (FCCU, reformer, SRU) | `Subpart Ja` |
| SOCMI / HON chemical plant | `Subpart F`, `Subpart G`, `Subpart H` | `Subpart VV / VVa / VVb` |
| Miscellaneous organic chemicals (MON) | `Subpart FFFF` | — |
| "Equipment leaks / repeat leak repairs" | `Subpart UU`, `Subpart H` | `Subpart VVa` |

The index has **no rule/subpart column**; the rule shows only in the downloaded file names. The
subpart a plant actually files under can differ from the table above: an olefins plant's elevated
flares may appear only as control devices in its NSPS NNN (distillation) and RRR (reactor)
reports, whose Excel templates carry `Flares` (pilot-flame-absent periods) and `Bypass_Events`
sheets. So when unsure, search by facility with no `--part`/`--subpart`, download, and read the
rules off the file names.

## Running a search

```bash
node ~/.claude/plugins/bayou/skills/epa-webfire-reports/webfire_search.js \
  --type AER --state LA --facility "NORCO CHEMICAL PLANT" \
  --from 07/01/2023 --to 12/31/2026 \
  --out /path/to/webfire-out [--download]
```

WebFIRE returns every match in one response and pages it in the browser (DataTables, 50 per
page); the script reads all rows through the DataTables API and stops with an error if the row
count differs from WebFIRE's "shows the N records" line.

Outputs in `--out`:
- `webfire_INDEX.csv`: one row per result. The columns are WebFIRE's own table headers
  (Organization, Facility, City, State, County, Submission Date, Report Type, Report Sub Type, …),
  plus `links` (one `dspERTDocumentDetails.cfm?ID=` URL per row, which serves the file directly)
  and `onclick`.
- `results-page1.html`: the raw results page, kept so that a layout the parser missed can be
  re-read.
- With `--download`: `files/row<NNNN>-<i>-<name>` for every linked document, plus
  `webfire_DOWNLOADS.csv` (row, URL, file, bytes, content type, sha256).
- `error-page.html` when the search fails server-side (exit 3).

Run long pulls with `run_in_background: true`. Downloads have no per-file timeout.

## Verifying downloads

Every download is checked before it is kept. A non-200 response, a zero-byte body, or an HTML
error page in place of a document **aborts the run** with the row number and URL; nothing is
silently skipped. After a run:
- confirm that every `webfire_INDEX.csv` row with a link has a matching `webfire_DOWNLOADS.csv`
  row;
- expect duplicates: EPA often publishes one submission under two document IDs, so the same file
  arrives twice. Group by `sha256` before counting reports;
- spot-check that each file's facility and period match its index row before citing it.

CEDRI periodic reports usually arrive as a **zip** containing the submission XML or an Excel
reporting template, plus PDF attachments. Unzip them, then:
- The XML/XLSX/XLSM holds the structured tables: deviations, flare events, root-cause analyses
  and PRD releases. Read it directly (`uv run --with openpyxl python3 …` if openpyxl is not
  installed). Template sheets begin with `e.g.:` example rows and a `Last Updated Date` row; skip
  those. The `Company_Information` sheet carries the per-site "No exceedances …" / "There were
  exceedances …" declaration.
- The PDF inside the zip is usually a scan with no text layer; it needs `/bayou:document-ocr`
  before text search.

## Presenting results

For each relevant report, give:
- facility and FRS ID;
- rule and subpart;
- report type;
- compliance period;
- submission date;
- the file path.

When reporting findings from a report, cite the downloaded file and the table or page, never the
WebFIRE index row alone. If a search returns nothing, say what was searched (IDs, subparts, dates),
so that "none filed through CEDRI" stays distinct from "search failed".

## Known limits

- Reports older than a rule's electronic-reporting start date were filed on paper and are not in
  WebFIRE. For those, use the state system or a FOIA request.
- Confidential business information (CBI) is withheld from WebFIRE copies.

$ARGUMENTS
