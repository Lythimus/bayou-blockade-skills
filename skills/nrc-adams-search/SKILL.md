---
name: nrc-adams-search
description: Use only when explicitly asked to search NRC ADAMS for nuclear regulatory documents (inspection reports, decommissioning, licenses).
allowed-tools: Bash, Read, AskUserQuestion
---

# NRC ADAMS Document Search

Search the Nuclear Regulatory Commission's Agencywide Documents Access and Management System (ADAMS) for publicly available NRC documents — inspection reports, decommissioning records, license amendments, correspondence, and more.

## Authentication

Read `~/.claude/bayou-credentials.md` to get the NRC credentials. The file contains the registration email/password and instructions for retrieving the subscription key from the developer portal.

If `NRC_ADAMS_KEY` is not yet populated in that file:
1. Note the email and password from the credentials file
2. Tell the user: "The NRC subscription key hasn't been retrieved yet. Please log in to https://adams-api-developer.nrc.gov/, go to Products → ADAMS Public Search API → view your subscription key, and share it so I can add it to the credentials file."
3. Once provided, update `~/.claude/bayou-credentials.md` with the key value.

**Header**: `Ocp-Apim-Subscription-Key: KEY_FROM_CREDENTIALS_FILE`

## Parsing arguments

The user may provide:
- A **facility name** or **docket number** (e.g., "Waterford 3", "05000382")
- A **document type** (inspection report, license amendment, decommissioning)
- A **date range**
- A **free-text search** query (e.g., "steam generator replacement", "10 CFR 50.59")
- An **accession number** (e.g., "ML25123A456") for a specific document

If the user gives an accession number directly, use the Get Document endpoint. Otherwise, use Search Document Library.

## How to search

### Get a single document by accession number

```bash
curl -s -X GET "https://adams-api.nrc.gov/aps/api/search/ACCESSION_NUMBER" \
  -H "Ocp-Apim-Subscription-Key: YOUR_KEY" \
  -H "Accept: application/json" 2>/dev/null
```

### Search the document library (most common)

```bash
curl -s -X POST "https://adams-api.nrc.gov/aps/api/search" \
  -H "Ocp-Apim-Subscription-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  --data-raw 'SEARCH_BODY' 2>/dev/null
```

### Search body template

```json
{
  "q": "SEARCH_TEXT",
  "filters": [
    {"field": "DocumentType", "value": "TYPE", "operator": "equals"},
    {"field": "DocumentDate", "value": "(DocumentDate ge '2020-01-01')"}
  ],
  "anyFilters": [],
  "mainLibFilter": true,
  "legacyLibFilter": false,
  "sort": "DocumentDate",
  "sortDirection": 1,
  "skip": 0
}
```

### Mapping user requests to search parameters

| User request | `q` value | `filters` |
|---|---|---|
| Waterford 3 inspection reports | `"Waterford"` | `DocumentType = "Inspection Report"` |
| Docket 05000382 documents | `"05000382"` | none (docket in `q`) |
| Decommissioning documents | `"decommissioning"` | none |
| License amendments 2020-present | `"license amendment"` | `DocumentDate ge '2020-01-01'` |
| 10 CFR 50.59 evaluations | `"50.59"` | none |
| Safety evaluation reports | `""` | `DocumentType = "Safety Evaluation"` |

### Date filter syntax

Use OData-style in the `value` field:
- Since 2022: `"(DocumentDate ge '2022-01-01')"`
- In 2024: `"(DocumentDate ge '2024-01-01' and DocumentDate le '2024-12-31')"`

### `sortDirection` values
- `0` = Ascending
- `1` = Descending (newest first — default)

### Pagination
Add `"skip": N` to page through results (N = number of records to skip).

## How to present results

The response has a `documents` array. Key fields per document:

| Field | Description |
|---|---|
| `AccessionNumber` | ADAMS accession number (e.g., ML25123A456) |
| `DocumentTitle` | Document title |
| `DocumentDate` | Date of document |
| `DocumentType` | Type (Inspection Report, License Amendment, etc.) |
| `AuthorName` | Author(s) |
| `EstimatedPageCount` | Page count |
| `Url` | Direct link to document in ADAMS |

### Presentation format:
1. **Summary**: "Found N documents matching [query]"
2. **Table**: Date | Type | Title | Pages | Accession Number
3. Link each accession number: `https://adams-search.nrc.gov/document/ML_ACCESSION`
4. If more than 20 results, show first 20 and ask to refine or paginate
5. If no results, suggest broader query or check spelling of docket/facility name

**Waterford 3 docket number**: 05000382 (also 05000382 for Unit 3 operating license)

$ARGUMENTS
