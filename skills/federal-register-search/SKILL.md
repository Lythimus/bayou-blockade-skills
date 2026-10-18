---
name: federal-register-search
description: Search the Federal Register for EPA/agency notices, proposed rules, and rules mentioning a facility, location, or topic, and surface open public comment deadlines; then follow the docket into regulations.gov for its documents, attachments and public comments, including MARAD Deepwater Port Act licensing and USCG Waterway Suitability Assessment records
allowed-tools: Bash, AskUserQuestion
---

# Federal Register Search

Query the Federal Register's public API (`federalregister.gov/api/v1`) for notices, proposed rules, and final rules, then follow a document's docket into regulations.gov (`api.regulations.gov/v4`) for everything else filed in it. The Federal Register API needs no key. The regulations.gov steps need a free api.data.gov key (Step 3).

Useful for:
- catching open EPA comment periods affecting Louisiana;
- finding a specific facility's regulatory history (applicability determinations, SIP actions, NOVs referenced in a Federal Register notice);
- tracking rule dockets over time;
- pulling the record of a docket: supporting documents, license applications, EIS volumes, and the public comments filed on it;
- MARAD deepwater port license dockets and USCG Waterway Suitability Assessment notices (see "Deepwater ports and waterway suitability assessments").

## Parsing arguments

The user may provide:
- A **search term** (facility name, chemical, rule topic — e.g. "Shell Norco", "Clean Air Act flare", "benzene NESHAP")
- An **agency filter** (default to EPA if the context is environmental)
- A **document type**: Notice, Proposed Rule, Rule, Presidential Document
- A **date range**
- A request to find **open comment periods** specifically
- A **regulations.gov docket ID** (e.g. `MARAD-2025-0096`, `EPA-R06-OAR-2024-0123`) or document ID (`MARAD-2025-0096-3068`). Go straight to Step 3.

If ambiguous, default to `conditions[agencies][]=environmental-protection-agency` and all document types, then narrow based on result count.

## Step 1: Basic search

The API's default response leaves out `comments_close_on`, `docket_ids` and `regulations_dot_gov_info`. Request them with `fields[]`, or the comment deadline and docket link silently come back missing. Once any `fields[]` is passed, only the listed fields are returned, so the list below repeats the useful defaults.

```bash
FR_FIELDS=(title type abstract document_number html_url pdf_url publication_date agencies excerpts comments_close_on docket_ids regulations_dot_gov_info)
curl -s --get "https://www.federalregister.gov/api/v1/documents.json" \
  --data-urlencode "conditions[term]=Shell Norco" \
  --data-urlencode "conditions[agencies][]=environmental-protection-agency" \
  $(printf -- '--data-urlencode fields[]=%s ' "${FR_FIELDS[@]}") \
  --data-urlencode "per_page=20" \
  --data-urlencode "order=newest" 2>/dev/null | python3 -m json.tool
```

Useful `conditions[...]` parameters (repeat the flag for array values):
- `conditions[term]` — free text search
- `conditions[agencies][]` — e.g. `environmental-protection-agency`, `army-corps-of-engineers`, `fish-and-wildlife-service`, `maritime-administration`, `coast-guard`
- `conditions[type][]` — `RULE`, `PRORULE` (proposed rule), `NOTICE`, `PRESDOCU`
- `conditions[publication_date][gte]` / `[lte]` — `YYYY-MM-DD`
- `conditions[docket_id]` — a specific regulations.gov docket ID if known
- `conditions[near][location]` + `conditions[near][within]` — geographic proximity (miles) for facility-siting notices, if the document has location metadata (not all do)

Response fields per document (with the `fields[]` above): `title`, `type`, `abstract`, `document_number`, `html_url`, `pdf_url`, `publication_date`, `agencies[]`, `comments_close_on`, `docket_ids[]` (strings like `"Docket No. MARAD-2025-0096"`), `regulations_dot_gov_info` (`docket_id`, `document_id`, `comments_count`, when the agency posts to regulations.gov), and `excerpts` (highlighted match context — read this before opening the full document, it's often enough to tell relevance).

## Step 2: Find open public comment periods

The operational point of this skill is catching comment windows before they close. Filter to proposed rules and notices, sort newest first, and check `comments_close_on`:

```bash
curl -s --get "https://www.federalregister.gov/api/v1/documents.json" \
  --data-urlencode "conditions[term]=Louisiana" \
  --data-urlencode "conditions[agencies][]=environmental-protection-agency" \
  --data-urlencode "conditions[type][]=PRORULE" \
  --data-urlencode "conditions[type][]=NOTICE" \
  $(printf -- '--data-urlencode fields[]=%s ' title type document_number html_url publication_date comments_close_on regulations_dot_gov_info) \
  --data-urlencode "per_page=40" \
  --data-urlencode "order=newest" 2>/dev/null | python3 -c "
import json, sys, datetime
d = json.load(sys.stdin)
today = datetime.date.today().isoformat()
print(f'{d[\"count\"]} total matches')
for r in d.get('results', []):
    close = r.get('comments_close_on')
    if close and close >= today:
        dk = (r.get('regulations_dot_gov_info') or {}).get('docket_id', '—')
        print(f\"OPEN until {close} | {r['publication_date']} | {r['type']} | {dk} | {r['title'][:90]}\")
        print(f\"  {r['html_url']}\")
"
```

`comments_close_on` is `null` for documents that never had a comment period (most final Rules, many Notices) — that's expected, not a data gap. It is also `null` for some notices that do set a deadline in their text: MARAD deepwater port notices of availability and public-meeting notices are an example. When a notice announces a comment period but the field is empty, read the DATES section of the notice (`html_url`) for the deadline. Step 3c gives a second check through regulations.gov.

Widen the search (drop the term, or broaden to all EPA documents in a date range) if nothing has an open window; comment periods are frequently short (30-60 days) and the search may simply be timed after a relevant one closed.

FERC notices (NOIs for an EIS, notices of availability of a draft EIS, notices of application) are published here, but the FERC docket and the full record live in eLibrary, not regulations.gov. Use `bayou:ferc-elibrary` (`notices <docket>`, then the notice PDF) for the scoping, DEIS comment and intervention deadlines.

## Step 3: Follow the docket into regulations.gov

The Federal Register carries only what an agency publishes there. The docket on regulations.gov holds the rest: supporting documents, applications, EIS volumes, meeting transcripts and the public comments. The bridge is the docket ID from Step 1 (`regulations_dot_gov_info.docket_id`, or the ID inside `docket_ids[]`). In the other direction, a regulations.gov document's `frDocNum` is the Federal Register `document_number`.

### API key

Any api.data.gov key works, so a key saved for another bayou skill can be reused. Read the first one present:

```bash
CREDS=~/.claude/bayou-credentials.md
for k in REGULATIONS_GOV_API_KEY CAMPD_API_KEY ATTAINS_API_KEY; do
  RGOV_KEY=$(rg "^$k:" "$CREDS" 2>/dev/null | cut -d' ' -f2); [ -n "$RGOV_KEY" ] && break
done
RGOV_KEY=${RGOV_KEY:-DEMO_KEY}; echo "key source: ${k:-none} ${RGOV_KEY:0:4}…"
RGOV=https://api.regulations.gov/v4
```

If it falls through to `DEMO_KEY`, tell the user: "regulations.gov needs a free api.data.gov key. Register at https://api.data.gov/signup/ (instant) and share the key so I can save it." Then save it as `REGULATIONS_GOV_API_KEY: <key>` under `## Regulations.gov (api.data.gov)` in `~/.claude/bayou-credentials.md` (template: `bayou-credentials.example.md`). `DEMO_KEY` allows 10 requests an hour, enough to look at one docket and little more. A registered key allows 1,000 requests an hour (the `x-ratelimit-remaining` response header shows what is left).

### 3a. Find documents

```bash
curl -s --get "$RGOV/documents" \
  --data-urlencode 'filter[searchTerm]="deepwater port"' \
  --data-urlencode "filter[agencyId]=MARAD" \
  --data-urlencode "sort=-postedDate" \
  --data-urlencode "page[size]=25" \
  --data-urlencode "api_key=$RGOV_KEY" | python3 -c "
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
def et(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(ET).strftime('%Y-%m-%d %I:%M %p ET') if s else '—'
d = json.load(sys.stdin)
print(d['meta']['totalElements'], 'documents')
for x in d['data']:
    a = x['attributes']
    print(f\"{x['id']} | {a['postedDate'][:10]} | {a['documentType']}/{a.get('subtype') or '-'} | FR {a.get('frDocNum') or '-'} | closes {et(a.get('commentEndDate'))}\")
    print(f\"  {a['title'][:110]}\")
"
```

Filters (all `filter[...]`):
- `searchTerm` — full text. **Quote multi-word phrases** inside the value (`'"waterway suitability assessment"'`). Unquoted, the words match independently: that search returned 17,707 hits, mostly FWS species assessments, against 80 when quoted.
- `agencyId` — the regulations.gov agency acronym: `EPA`, `MARAD`, `USCG`, `USACE`, `FWS`, `NOAA`, `PHMSA`, `FERC`, `DOE`.
- `docketId` — every document in one docket.
- `documentType` — `Notice`, `Proposed Rule`, `Rule`, `Supporting & Related Material`, `Other`.
- `withinCommentPeriod=true` — only documents accepting comments now.
- `postedDate[ge]` / `postedDate[le]` — `YYYY-MM-DD`.
- `lastModifiedDate[ge]` / `[le]` — `YYYY-MM-DD HH:MM:SS` exactly. A date alone returns HTTP 400.
- `frDocNum` — the Federal Register document number, to go from a Step 1 hit to its regulations.gov copy.

`sort` takes `postedDate`, `lastModifiedDate`, `title` or `documentId`, with a leading `-` for descending. `page[size]` runs 5–250. Past the last page, `data` comes back empty with `hasNextPage: false`. The API documentation caps one query at 5,000 rows (20 pages of 250). For a larger set, sort by `lastModifiedDate` and restart from the last row's timestamp with `filter[lastModifiedDate][ge]`.

### 3b. Docket overview

```bash
DOCKET=MARAD-2025-0096
curl -s "$RGOV/dockets/$DOCKET?api_key=$RGOV_KEY" | python3 -c "
import json, sys
a = json.load(sys.stdin)['data']['attributes']
for k in ('title', 'dkAbstract', 'docketType', 'category', 'modifyDate'):
    print(f'{k}: {a.get(k)}')
"
curl -s --get "$RGOV/documents" \
  --data-urlencode "filter[docketId]=$DOCKET" \
  --data-urlencode "sort=postedDate" \
  --data-urlencode "page[size]=250" \
  --data-urlencode "api_key=$RGOV_KEY" | python3 -c "
import json, sys, collections
d = json.load(sys.stdin)
groups = collections.defaultdict(list)
for x in d['data']:
    a = x['attributes']
    groups[a['documentType']].append(f\"  {a['postedDate'][:10]} {x['id']} {a['title'][:90]}\")
print(d['meta']['totalElements'], 'documents')
for t, rows in groups.items():
    print(f'{t} ({len(rows)})'); print('\n'.join(rows))
"
```

`docketType` is `Rulemaking` or `Nonrulemaking`; license applications and permit actions are non-rulemaking. `category` is the agency's own status label (e.g. `Pending`).

### 3c. Open comment windows

Add `filter[withinCommentPeriod]=true` to the 3a query (with or without a search term or agency). The 3a printer converts `commentEndDate` to Eastern time. The field is UTC: `2026-12-01T04:59:59Z` is 11:59 PM ET on November 30, so slicing the first ten characters reports the deadline a day late. Always print the converted value.

When `commentEndDate` is `null` on a document that announces a comment period, check the Federal Register copy:

```bash
curl -s "https://www.federalregister.gov/api/v1/documents/<frDocNum>.json?fields[]=comments_close_on&fields[]=html_url"
```

If that is also `null`, the deadline is only in the notice text: open the document (3d) and read its DATES section. Report the deadline with its source ("per the DATES section of FR Doc. 2026-14963").

### 3d. Pull documents and attachments

```bash
DOC=MARAD-2025-0096-3068
curl -s "$RGOV/documents/$DOC?include=attachments&api_key=$RGOV_KEY" | python3 -c "
import json, sys
d = json.load(sys.stdin)
a = d['data']['attributes']
print(a['title']); print('pages:', a.get('pageCount'))
for f in a.get('fileFormats') or []:
    print(f\"  main  {f['format']:5} {f.get('size', 0)/1e6:8.1f} MB  {f['fileUrl']}\")
for inc in d.get('included', []):
    ia = inc['attributes']
    for f in ia.get('fileFormats') or []:
        print(f\"  att   {f['format']:5} {f.get('size', 0)/1e6:8.1f} MB  {f['fileUrl']}  ({ia.get('title')})\")
"
```

Files live on `downloads.regulations.gov` and need no key, but its CloudFront front end returns HTTP 403 to curl's default User-Agent, so send a browser one. Before downloading, total the sizes. If the set is large (EIS volumes and license applications often run to hundreds of MB), give the user the total and confirm first. Download into a new directory per docket, under the case folder or the scratchpad:

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
mkdir -p "$OUT/$DOCKET" && curl -sSfL -A "$UA" -o "$OUT/$DOCKET/$DOC.pdf" "<fileUrl>"
```

Scanned PDFs need `bayou:document-ocr` before `bayou:permit-analysis` can read them.

### 3e. Public comments

```bash
curl -s --get "$RGOV/comments" \
  --data-urlencode "filter[docketId]=$DOCKET" \
  --data-urlencode "sort=-postedDate" \
  --data-urlencode "page[size]=25" \
  --data-urlencode "api_key=$RGOV_KEY" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d['meta']['totalElements'], 'comments')
for x in d['data']:
    a = x['attributes']; print(f\"{x['id']} | {a['postedDate'][:10]} | {a['title'][:90]}\")
"
```

The list gives only IDs and titles. The comment text, submitter organization and attachments come from `GET $RGOV/comments/<commentId>?include=attachments`, one request each. The text is `attributes.comment` and the submitter is `organization` or `firstName`/`lastName`. Long comments usually say "see attached" and put the substance in `included[]` (each with its own `fileFormats`); the Earthjustice comment on MARAD-2025-0096 had 20 attachments. A docket with thousands of comments (MARAD-2025-0096 had 3,042) would use the hourly allowance several times over, so sample, filter by `searchTerm`, or ask the user before reading them all. `filter[searchTerm]` works on `/comments` too, e.g. to find a named organization's comment.

The docket page for a human reader is `https://www.regulations.gov/docket/<DOCKET_ID>`, and comments are submitted at `https://www.regulations.gov/commenton/<DOCUMENT_ID>`. This skill never submits comments.

## Deepwater ports and waterway suitability assessments

These are 3a/3b recipes, not a separate source.

**MARAD Deepwater Port Act licensing.** Offshore oil and LNG export terminals (Blue Marlin, ST LNG and others off Louisiana and Texas) are licensed by MARAD under the Deepwater Port Act, with the Coast Guard preparing the EIS jointly. Search `filter[agencyId]=MARAD` with `'"deepwater port"'`, then pull the docket (3b). A license docket typically holds:
- the license application and its appendices (often posted as `Other` or `Supporting & Related Material`, in many volumes);
- the notice of application and notice of intent to prepare an EIS;
- notices of availability for the draft and final EIS, and public-meeting notices;
- the public comments and the Record of Decision.

The FR notices for these dockets often leave `comments_close_on` and `commentEndDate` empty. Get the deadline from the notice text (3c).

**USCG Waterway Suitability Assessments.** For a waterfront LNG or liquefied hazardous gas terminal, the Coast Guard reviews the operator's WSA of the transit route and issues a Letter of Recommendation on whether the waterway is suitable. Search `'"waterway suitability assessment"'` (quoted). With `filter[agencyId]=USCG` the results are the Coast Guard's notices on individual terminals. Without the agency filter, the results also include FERC LNG EIS notices, whose EIS summarizes the WSA and the Letter of Recommendation. The FERC record itself is in `bayou:ferc-elibrary`. The full WSA is often withheld as security-sensitive, so the public record is usually the notice, the public comments and the Letter of Recommendation. Request the rest from the USCG Sector by FOIA. This bears on question bank INF-002 (impacts to existing waterway users).

---

## Presenting the results

1. **Summary line**: "Found N documents matching [term]" with the filters applied.
2. **Results table**: Date | Type | Title | Docket | Comment Deadline (ET, or "—" if none) | Link
3. **Lead with open comment periods** if any exist — that's the actionable item — before listing historical documents. Give each deadline in Eastern time with its source field (`comments_close_on`, `commentEndDate` or the DATES section).
4. Quote the relevant `excerpts` snippet when a document's relevance isn't obvious from the title alone.
5. Note total result count if truncated (Federal Register `per_page` default 20, max 1000; regulations.gov `page[size]` max 250).
6. For a docket, give the overview (title, type, status, document count by type, comment count) before individual documents.

### Citation format

> **Federal Register Doc. [document_number]**, "[title]" ([type], published [publication_date]), source: [federalregister.gov](https://www.federalregister.gov/documents/...) (retrieved [today's date]). Comment period: [open until DATE / closed / none].

> **Regulations.gov Doc. [document id]**, "[title]" ([documentType], Docket [docketId], posted [postedDate]), source: [regulations.gov](https://www.regulations.gov/document/[document id]) (retrieved [today's date]).

$ARGUMENTS
