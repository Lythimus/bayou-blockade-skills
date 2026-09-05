---
name: federal-register-search
description: Search the Federal Register for EPA/agency notices, proposed rules, and rules mentioning a facility, location, or topic, and surface open public comment deadlines
allowed-tools: Bash, AskUserQuestion
---

# Federal Register Search

Query the Federal Register's public API (`federalregister.gov/api/v1`) for notices, proposed rules, and final rules. No API key required. Useful for: catching open EPA comment periods affecting Louisiana, finding a specific facility's regulatory history (applicability determinations, SIP actions, NOVs referenced in a Federal Register notice), and tracking rule dockets over time.

## Parsing arguments

The user may provide:
- A **search term** (facility name, chemical, rule topic — e.g. "Shell Norco", "Clean Air Act flare", "benzene NESHAP")
- An **agency filter** (default to EPA if the context is environmental)
- A **document type**: Notice, Proposed Rule, Rule, Presidential Document
- A **date range**
- A request to find **open comment periods** specifically

If ambiguous, default to `conditions[agencies][]=environmental-protection-agency` and all document types, then narrow based on result count.

## Step 1: Basic search

```bash
curl -s --get "https://www.federalregister.gov/api/v1/documents.json" \
  --data-urlencode "conditions[term]=Shell Norco" \
  --data-urlencode "conditions[agencies][]=environmental-protection-agency" \
  --data-urlencode "per_page=20" \
  --data-urlencode "order=newest" 2>/dev/null | python3 -m json.tool
```

Useful `conditions[...]` parameters (repeat the flag for array values):
- `conditions[term]` — free text search
- `conditions[agencies][]` — e.g. `environmental-protection-agency`, `army-corps-of-engineers`, `fish-and-wildlife-service`
- `conditions[type][]` — `RULE`, `PRORULE` (proposed rule), `NOTICE`, `PRESDOCU`
- `conditions[publication_date][gte]` / `[lte]` — `YYYY-MM-DD`
- `conditions[docket_id]` — a specific regulations.gov docket ID if known
- `conditions[near][location]` + `conditions[near][within]` — geographic proximity (miles) for facility-siting notices, if the document has location metadata (not all do)

Response fields per document: `title`, `type`, `abstract`, `document_number`, `html_url`, `pdf_url`, `publication_date`, `agencies[]`, `comments_close_on`, `excerpts` (highlighted match context — read this before opening the full document, it's often enough to tell relevance).

## Step 2: Find open public comment periods

The operational point of this skill is catching comment windows before they close. Filter to proposed rules and notices, sort newest first, and check `comments_close_on`:

```bash
curl -s --get "https://www.federalregister.gov/api/v1/documents.json" \
  --data-urlencode "conditions[term]=Louisiana" \
  --data-urlencode "conditions[agencies][]=environmental-protection-agency" \
  --data-urlencode "conditions[type][]=PRORULE" \
  --data-urlencode "conditions[type][]=NOTICE" \
  --data-urlencode "per_page=40" \
  --data-urlencode "order=newest" 2>/dev/null | python3 -c "
import json, sys, datetime
d = json.load(sys.stdin)
today = datetime.date.today().isoformat()
print(f'{d[\"count\"]} total matches')
for r in d.get('results', []):
    close = r.get('comments_close_on')
    if close and close >= today:
        print(f\"OPEN until {close} | {r['publication_date']} | {r['type']} | {r['title'][:90]}\")
        print(f\"  {r['html_url']}\")
"
```

`comments_close_on` is `null` for documents that never had a comment period (most final Rules, many Notices) — that's expected, not a data gap. Widen the search (drop the term, or broaden to all EPA documents in a date range) if nothing has an open window; comment periods are frequently short (30-60 days) and the search may simply be timed after a relevant one closed.

## Step 3 (optional): Hand off to regulations.gov

The Federal Register API does not itself expose comment *submissions* (that's regulations.gov, which requires a free api.data.gov key this skill does not use). Once you've found a relevant docket via `conditions[docket_id]` in the result JSON (look for a `regulations_dot_gov_info` or `docket_ids` field on the document, when present), hand the docket number to the user directly:

> To read or submit comments on this docket, go to `https://www.regulations.gov/docket/<DOCKET_ID>`.

---

## Presenting the results

1. **Summary line**: "Found N documents matching [term]" with the filters applied.
2. **Results table**: Date | Type | Title | Comment Deadline (or "—" if none) | Link
3. **Lead with open comment periods** if any exist — that's the actionable item — before listing historical documents.
4. Quote the relevant `excerpts` snippet when a document's relevance isn't obvious from the title alone.
5. Note total result count if truncated (`per_page` default 20, max 1000).

### Citation format

> **Federal Register Doc. [document_number]**, "[title]" ([type], published [publication_date]), source: [federalregister.gov](https://www.federalregister.gov/documents/...) (retrieved 2026-07-21). Comment period: [open until DATE / closed / none].

$ARGUMENTS
