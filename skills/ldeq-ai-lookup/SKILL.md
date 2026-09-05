---
name: ldeq-ai-lookup
description: Look up a company's LDEQ EDMS AI (Agency Interest) number by name
allowed-tools: WebFetch, AskUserQuestion
---

# LDEQ EDMS AI Number Lookup

The user wants to find the LDEQ EDMS AI number for a company. If they provided a company name, use it. Otherwise, ask them for the company name.

## How to search

Use WebFetch to POST to `https://edms.deq.louisiana.gov/edmsv2/aiSearch/filter` with these settings:

- Method: POST
- Headers:
  - `Content-Type: application/json`
  - `Accept: application/json`
- Body (JSON): Replace `SEARCH_TERM` with the user's company name wrapped in escaped quotes for exact match:

```json
{"filter":{"keywordSearchType":"Name","fuzzyMatch":false,"keyword":"\"SEARCH_TERM\""},"refinerFilter":{"regions":[],"regionIds":[],"parishes":[],"cities":[],"typeNames":[],"typeCodes":[]},"start":0,"rows":100,"sort":"name","asc":false,"highlight":true}
```

If the exact match returns 0 results, retry with `fuzzyMatch` set to `true` and remove the escaped quotes around the keyword to do a broader search.

## How to present results

The response JSON has `total` (count) and `data` (array of facilities).

For each result, extract and display:
- **AI Number**: the `id` field — this is the primary identifier the user needs
- **Name**: the `name` field (strip any HTML `<span>` highlighting tags)
- **Physical Address**: `physicalAddress`
- **Parish**: `parish`
- **City**: `city`
- **Industry**: `typeName`
- **Alternate IDs**: `alternateIds` (these include permit numbers, EPA IDs, etc.)

### Presentation rules:
- If there are **0 results**: tell the user no matches were found and suggest trying a different search term.
- If there is **1 result**: present it directly as the match.
- If there are **2-10 results**: present a numbered list and ask the user to select which facility they meant.
- If there are **more than 10 results**: show the first 10 and suggest the user narrow their search term.

Always make the AI number prominent — it's the main thing the user is looking for.

Cross-link `bayou:epa-frs-crosswalk` — an FRS `registry_id` lookup returns a `LA-TEMPO` program ID, which is LDEQ's own federal↔state bridge and often lines up with (or points to) the AI number found here. Useful when starting from a federal program ID (TRI, NPDES, RCRAInfo) instead of a company name.

$ARGUMENTS
