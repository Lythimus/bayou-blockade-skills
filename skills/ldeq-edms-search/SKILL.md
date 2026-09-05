---
name: ldeq-edms-search
description: Search LDEQ EDMS documents by AI number with intelligent filtering
allowed-tools: Bash, AskUserQuestion
---

# LDEQ EDMS Document Search

Search the LDEQ Electronic Document Management System for documents associated with a facility's AI (Agency Interest) number. Interpret the user's natural language request to apply appropriate filters.

## Parsing arguments

The arguments should contain an **AI number** (numeric, e.g. `26336`). Everything else is a natural language description of what they're looking for.

If no AI number is provided, ask the user for one. Suggest they use `/bayou:ldeq-ai-lookup` to find the AI number by company name.

Examples:
- `26336` — all documents for AI 26336
- `26336 Title V air permits from the last 2 years` — filtered search
- `26336 enforcement actions` — filtered search
- `26336 flare incidents` — filtered search with description keyword

## How to search

Use Bash with curl to POST to `https://edms.deq.louisiana.gov/edmsv2/documentSearch/filter`.

### Step 1: Map the user's request to API filters

Analyze what the user is asking for and map it to these filter dimensions. You can combine multiple filters. Use ONLY the exact string values listed below — the API requires exact matches.

**Media** (`refinerFilter.medias`) — the environmental domain:
- `Accident Prevention`
- `Air Quality` — use for anything about air permits, emissions, flares, Title V, stacks
- `Asbestos`
- `Biosolids`
- `Ground Water`
- `Hazardous Waste`
- `Inactive & Abandoned Sites`
- `Lead`
- `Multi-Media`
- `Non-Applicable`
- `Radiation`
- `Solid Waste`
- `Surface Water`
- `Underground Storage Tanks`

**Function** (`refinerFilter.functions`) — the LDEQ organizational function:
- `Air Emissions Inventory`
- `Air Modeling`
- `Air Monitoring and Analysis`
- `Air Planning`
- `Air Stack and Tank Testing`
- `Chemical Accident Prevention`
- `Enforcement` — use for violations, warning letters, compliance orders, penalties
- `Financial`
- `Incidents - Emergency` — use for emergency spills, releases, events
- `Incidents - Non-Emergency` — use for routine incident reports, excess emissions
- `Inspections` — use for site inspections, compliance evaluations
- `Legal` — use for legal actions, consent decrees, adjudicatory hearings
- `Office of the Secretary (OSEC)`
- `Permit Support Services`
- `Permits` — use for permit applications, renewals, modifications, final permits
- `Radiological Services`
- `Remediation Services`
- `Single Point of Contact (SPOC)` — use for notifications, startup/shutdown, SPOC reports
- `Unassigned`
- `Water Quality Standards and Assessment`

**Document Type** (`refinerFilter.documentTypes`):
- `Analytical Data`
- `Compliance`
- `Correspondence-Internal`
- `Correspondence-Received`
- `Correspondence-Sent`
- `Financial`
- `Forms`
- `Legal`
- `Permits`
- `Plans`
- `Reports`

**Document Subtype** (`refinerFilter.documentSubtypes`) — common values:
- `ADVF` — Alleged Deviation First (excess emissions notifications)
- `Annual`
- `Application`
- `Assessment/Investigation`
- `Below Reportable Quantity Event`
- `Certificate/License/Registration`
- `Compliance Order Enforcement`
- `Confidentiality Request`
- `Corrective Action`
- `DMR` — Discharge Monitoring Reports
- `Emission Event`
- `Emissions Inventory`
- `Final Permit`
- `Inspection Report`
- `Invoice`
- `NOV/Warning Letter`
- `Penalty`
- `Public Notice`
- `Quarterly`
- `Semi-Annual`
- `Warning Letters`

**Date Range** (`filter.documentDateRange`): Use ISO 8601 format. Calculate relative dates from today's date. Example: "past 2 years" from 2026-04-13 = `{"start":"2024-04-13T00:00:00Z","end":null}`.

**Description Keywords — no working filter exists.** `filter.keywords` **has no effect on the live API**, in either `descriptionMode` — verified 2026-08-12: on AI 41475, `keywords: []` returns `total: 1536`, and `keywords: ["variance"]` with `descriptionMode: "Contains"` *and* with `"Exact"` both also return `total: 1536`, identical to the unfiltered baseline. `filter.keywordValues` is not a free-text substitute either — it expects typed `IndexKeywordValues` objects, not strings, and passing a string array (`keywordValues: ["variance"]`) returns **HTTP 400** (`"could not be converted to ASC.Lib.EDMS.Models.IndexKeywordValues"`). **There is no known working server-side free-text description filter on this endpoint.**

**Working recipe instead:** narrow server-side with the `refinerFilter.*` facet arrays below (`medias`, `functions`, `documentTypes`, `documentSubtypes` — all confirmed effective, e.g. `refinerFilter.medias: ["Air Quality"]` on AI 41475 returns `total: 361`, correctly narrowed from 1536), pull with `rows: 500`, then match the free-text term against each record's `description` field client-side in Python. This is what resolved the AI 41475 campaign's variance-history and technical-review-worksheet lookups — 361 records is a comfortable size to filter client-side, and it is more reliable than trusting a keyword filter that turns out to be inert.

**Sanity check for any filter, not just keywords:** after applying a filter, compare its `total` against the same request with that filter removed. **Equal totals mean the filter was ignored** — silently returning the unfiltered set rather than erroring — so do not report results from that query as if they were filtered until you've confirmed the totals actually differ.

### Step 2: Build and execute the curl command

```bash
curl -s 'https://edms.deq.louisiana.gov/edmsv2/documentSearch/filter' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'content-type: application/json' \
  -H 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' \
  --data-raw '<JSON_BODY>'
```

The JSON body template (fill in the appropriate values, leave unused arrays empty):

```json
{
  "filter": {
    "numberOfRecordsPerPage": 25,
    "skip": 0,
    "totalCount": 0,
    "filters": [],
    "keywords": [],
    "keywordValues": [],
    "descriptionMode": "Exact",
    "contentSearchMode": "Exact",
    "descriptionFuzzy": false,
    "documentDateRange": {"start": null, "end": null},
    "entryDateRange": {"start": null, "end": null},
    "aiInformation": "AI_NUMBER"
  },
  "refinerFilter": {
    "documentDates": [],
    "functions": [],
    "medias": [],
    "documentTypes": [],
    "documentSubtypes": [],
    "ais": [],
    "activities": [],
    "classifications": [],
    "pwsids": []
  },
  "start": 0,
  "rows": 100,
  "sort": "documentDate",
  "asc": false,
  "highlight": false
}
```

Pipe the output through `python3 -m json.tool` for readability if needed, or use python3 to parse and format the results.

> **Response shape (confirmed 2026-06):** the top-level JSON keys are **`total`** (integer total matching count) and **`data`** (the array of document records) — *not* `documents`/`results`. The third key is **`refinerOptions`**, whose sub-arrays (`medias`, `functions`, `documentTypes`, `documentSubtypes`, …) are lists of **`{"key": "<label>", "value": <count>}`** objects. Reading `refinerOptions` from a `rows:1` request is the cheapest way to profile an AI's holdings by media/function *without* paging all documents — the per-key `value` counts tell you, e.g., that an AI has `Inactive & Abandoned Sites = 0` or `Remediation Services = 1` before you pull any rows. Beware mislabeled records: a single `function` hit may be a misfiled document (e.g., an air report tagged "Remediation Services"), so pull and read the actual `data` rows before drawing a conclusion from one count.

> **AI lookup gotcha:** to resolve a facility name → AI number first, use `bayou:ldeq-ai-lookup` with its exact payload (`filter.keyword` *singular*, the value wrapped in escaped quotes for an exact phrase, `fuzzyMatch:false`). A `keywords` *array* or an unquoted keyword tends to return the entire ~213k-record table instead of a filtered match.

### Step 3: If too many results, suggest narrowing

If the search returns more than 100 results and the user didn't specify filters, tell them the total count and suggest filter options based on the `refinerOptions` in the response. The response includes `refinerOptions` with counts for each filter value — use these to suggest the most relevant narrowing options.

## How to present results

Parse the JSON response. Key fields per document:
- `documentDate` — the document date
- `description` — document description
- `documentType` — e.g., Permits, Reports, Compliance
- `documentSubtype` — e.g., Final Permit, Warning Letters
- `media` — array, e.g., ["Air Quality"]
- `function` — e.g., Enforcement, Permits
- `pages` — page count
- `id` — document ID (use to construct view link)
- `activityNumbers` — array of activity tracking numbers
- `preparedByName` — who prepared the document
- `entryDate` — when it was entered into EDMS

### Presentation format:

1. **Summary line**: "Found N documents for AI XXXXX" (with filters described, e.g., "Found 12 Air Quality permits for AI 26336 since 2024")
2. **Results table** with columns: Date | Type / Subtype | Description | Pages
3. For each document, construct the EDMS viewer link using the `docIDSecured` field: `https://edms.deq.louisiana.gov/edmsv2/document/DOC_ID_SECURED`
4. If results exceed 25, show the first 25 and note the total. Ask if the user wants to see more or refine further.

> **Downloading the actual PDF is gated (reCAPTCHA).** The listing/search API is fully scriptable, but fetching a document's bytes is **not**: the `/edmsv2/document/<docIDSecured>/{content,download}` routes all return the Angular SPA HTML shell (~21 KB), because the real download goes through a reCAPTCHA-protected `CreateDownloadRequest` flow that curl cannot satisfy (confirmed live: a visible "I'm not a robot" v2 checkbox on the download popup). So this skill can identify and cite documents (date, type, description, viewer link, `docIDSecured`) but **cannot extract permit/report text** (e.g., to confirm a numeric throughput/hour cap inside a Title V permit). To actually retrieve files, use `/bayou:ldeq-edms-download` — it drives a real browser through search/select/download and lets the user solve the CAPTCHA in a visible window — passing it the AI number and each document's plain numeric `id` (not `docIDSecured`).

### Mapping natural language to filters — examples:

| User says | Filters to apply |
|---|---|
| "Title V air permits" | medias: ["Air Quality"], functions: ["Permits"]; pull rows, then client-side filter `description` contains "Title V" |
| "enforcement actions in the last year" | functions: ["Enforcement"], documentDateRange.start: 1 year ago |
| "flare incidents" | medias: ["Air Quality"], functions: ["Incidents - Emergency", "Incidents - Non-Emergency"]; pull rows, then client-side filter `description` contains "flare" |
| "warning letters" | documentSubtypes: ["Warning Letters"] |
| "inspection reports since 2023" | functions: ["Inspections"], documentDateRange.start: "2023-01-01T00:00:00Z" |
| "excess emissions" | documentSubtypes: ["ADVF", "Emission Event"] |
| "all permits" | documentTypes: ["Permits"] |
| "water discharge monitoring" | medias: ["Surface Water"], documentSubtypes: ["DMR"] |
| "flaring variances" | medias: ["Air Quality"], rows: 500; pull rows, then client-side filter `description` contains "variance" (this is the pattern that resolved the AI 41475 campaign's variance-history lookup) |

When the user's request is ambiguous, prefer casting a wider net (fewer filters) and letting them refine, rather than being too restrictive and missing relevant documents.

$ARGUMENTS
