---
name: doj-sec-search
description: Search SEC EDGAR filings and DOJ ENRD press releases for criminal/civil enforcement actions and material environmental liabilities disclosed to investors
allowed-tools: Bash, Read, AskUserQuestion
---

# DOJ ENRD & SEC EDGAR Enforcement Search

Surface criminal and civil enforcement history and investor-disclosed environmental liabilities by searching:

- **SEC EDGAR EFTS** — full-text search across every public company filing (10-K, 8-K, 10-Q, proxy statements, etc.)
- **DOJ ENRD press releases** — DOJ Environment and Natural Resources Division announcements of civil and criminal enforcement actions, consent decrees, and settlements
- **DOJ consent decree database** — guidance on locating filed consent decrees

No credentials required. EDGAR requires a descriptive `User-Agent` header per SEC policy.

---

## Parsing arguments

The user may provide:
- A **company name** (e.g., "Entergy Louisiana", "Entergy Nuclear Operations")
- A **facility or project name** (e.g., "Waterford Steam Electric", "Waterford 3")
- A **date range** (e.g., "since 2010", "2015–2023"); default to last 15 years if unspecified
- **Search terms** (e.g., "environmental liability", "consent decree", "Superfund", "NRC fine")
- A **form type** preference (e.g., "8-K only", "annual reports"); default to 8-K + 10-K + 10-Q
- A **source filter** (EDGAR only, DOJ only, or both); default both

If no company or facility name is provided, ask for one before proceeding.

---

## SEC EDGAR

No API key required. Every request must include:
```
User-Agent: BayouResearch research@example.com
```

### Step 1: Full-text filing search (EFTS)

Searches the complete text of every public filing — the most powerful path for surfacing buried disclosures.

```bash
# QUERY is already URL-encoded: %22 wraps an exact phrase, %20 separates AND-ed terms.
# Do not wrap the whole query in quotes; that turns every term into one long phrase.
QUERY='%22Waterford%203%22%20decommissioning'
FORMS='8-K,10-K,10-Q'
START='2010-01-01'
END='2026-12-31'

curl -s "https://efts.sec.gov/LATEST/search-index?q=${QUERY}&forms=${FORMS}&dateRange=custom&startdt=${START}&enddt=${END}" \
  -H "User-Agent: BayouResearch research@example.com" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = d.get('hits', {}).get('hits', [])
total = d.get('hits', {}).get('total', {}).get('value', 0)
print(f'Total results: {total}')
for h in hits:
    s = h.get('_source', {})
    print(s.get('file_date',''), '|', s.get('form',''), '|', '; '.join(s.get('display_names',[])), '|', h.get('_id',''))
"
```

Omit `&forms=` to search every form type (prospectus supplements and proxies often carry project
language that 8-Ks do not). An occasional `Internal server error` response is transient; retry
before concluding the endpoint is down.

#### Query construction tips

| Goal | Query string |
|---|---|
| Exact phrase | `"environmental liability"` |
| Company + topic | `"Entergy" "consent decree"` |
| Facility-specific | `"Waterford Steam Electric" "penalty"` |
| Nuclear-specific | `"nuclear" "decommissioning" "contingency"` |
| Criminal exposure | `"DOJ" OR "Department of Justice" "criminal"` |

Multiple terms without quotes use AND logic; use `OR` explicitly for alternatives.

#### Key response fields

```python
hits.hits[]._source:
  display_names[]   # Every registrant on the filing, each as "NAME  (TICKER)  (CIK 0000000000)"
  ciks[]            # Zero-padded CIKs, same order as display_names
  file_date         # YYYY-MM-DD
  form              # 8-K, 10-K, 10-Q, etc. (file_type is the type of the matched document)
  period_ending     # Reporting period end date
  adsh              # Accession number with hyphens
  biz_locations[]   # City, state of each registrant

hits.hits[]._id     # "<accession>:<filename>" of the matched document
```

The response carries no text excerpt. To see where a term appears, download the document and
search its text (Step 4).

#### Build the filing URL from accession number

The `_id` field is `<accession>:<filename>`, with the accession formatted as `XXXXXXXXXX-YY-NNNNNN`. Strip hyphens to form the directory path. The directory CIK is any registrant on the filing, without leading zeros; the first entry of `ciks` always works:

```bash
ID="0000065984-26-000174:etr-20251231.htm"   # from _id
CIK="65984"                                   # first entry of ciks, leading zeros removed
ACCNO=$(echo "${ID%%:*}" | tr -d '-')
FILE="${ID##*:}"

# The matched document itself
echo "https://www.sec.gov/Archives/edgar/data/${CIK}/${ACCNO}/${FILE}"

# Filing index page (lists all documents in this filing)
echo "https://www.sec.gov/Archives/edgar/data/${CIK}/${ACCNO}/"

# EDGAR viewer
echo "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${CIK}&type=8-K&dateb=&owner=include&count=40"
```

---

### Step 2: Look up a company's CIK

Required to pull filings by company. Search by name via the EDGAR company search (Atom feed):

```bash
COMPANY="Entergy+Louisiana"

curl -s "https://www.sec.gov/cgi-bin/browse-edgar?company=${COMPANY}&CIK=&type=10-K&dateb=&owner=include&count=20&search_text=&action=getcompany&output=atom" \
  -H "User-Agent: BayouResearch research@example.com" \
  2>/dev/null | python3 -c "
import sys, re
content = sys.stdin.read()
entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)
for e in entries[:10]:
    name = re.search(r'<company-name>(.*?)</company-name>', e)
    cik  = re.search(r'<cik-number>(\d+)</cik-number>', e)
    state = re.search(r'<state-of-inc>(.*?)</state-of-inc>', e)
    print('Name:', name.group(1) if name else '?')
    print('CIK: ', cik.group(1)  if cik  else '?')
    print('State:', state.group(1) if state else '?')
    print()
"
```

Common Entergy entity CIKs for reference:
| Entity | CIK |
|---|---|
| Entergy Corporation (parent) | 65984 |
| Entergy Louisiana, LLC | 1348952 |
| Entergy Arkansas, LLC | 7323 |
| Entergy Mississippi, LLC | 66901 |
| Entergy New Orleans, LLC | 71508 |
| Entergy Texas, Inc. | 1427437 |
| System Energy Resources, Inc. (SERI) | 202584 |
| Entergy Nuclear Operations, Inc. | (search to confirm) |

Entergy and its operating companies file one combined 10-K and 10-Q under the parent's accession
prefix (`0000065984-`), so those documents sit under CIK 65984. Bond prospectus supplements are
filed by the individual operating company.

---

### Step 3: Recent filings by CIK (submissions API)

Pull the full filing history for a known company — faster than EFTS for targeted lookups:

```bash
CIK="0000065984"   # zero-pad to 10 digits

curl -s "https://data.sec.gov/submissions/CIK${CIK}.json" \
  -H "User-Agent: BayouResearch research@example.com" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Company:', d.get('name'))
filings = d.get('filings', {}).get('recent', {})
forms   = filings.get('form', [])
dates   = filings.get('filingDate', [])
accs    = filings.get('accessionNumber', [])
descs   = filings.get('primaryDocument', [])
for form, date, acc, doc in zip(forms, dates, accs, descs):
    if form in ('8-K','10-K','10-Q'):
        print(date, '|', form, '|', acc, '|', doc)
" | head -50
```

---

### Step 4: Retrieve and parse a specific filing

```bash
CIK="65984"
ACCNO="000006598424000123"   # accession number, no hyphens

# Fetch the filing index to find the primary document filename
curl -s "https://www.sec.gov/Archives/edgar/data/${CIK}/${ACCNO}/${ACCNO}-index.json" \
  -H "User-Agent: BayouResearch research@example.com" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for f in d.get('directory', {}).get('item', []):
    print(f.get('name'), '|', f.get('type'), '|', f.get('size'))
"

# Once you have the filename (e.g., entergy8k.htm), fetch its text:
curl -s "https://www.sec.gov/Archives/edgar/data/${CIK}/${ACCNO}/entergy8k.htm" \
  -H "User-Agent: BayouResearch research@example.com" \
  2>/dev/null | python3 -c "
import sys
from html.parser import HTMLParser
class T(HTMLParser):
    def handle_data(self, d): print(d, end='')
T().feed(sys.stdin.read())
" | grep -A5 -B2 -i 'environmental\|penalty\|consent\|DOJ\|violation\|liability' | head -100
```

---

### What to look for in EDGAR filings

| Filing type | Key sections to search |
|---|---|
| **10-K** (annual) | Note 15+ (Commitments & Contingencies), Legal Proceedings, Risk Factors |
| **8-K** (material events) | Items 1.01 (agreement), 8.01 (other), especially 8-K/A amendments |
| **10-Q** (quarterly) | Updated contingency disclosures, changes in legal proceedings |
| **DEF 14A** (proxy) | Executive comp tied to compliance; litigation risk language |

To find which public parent lists an LLC as a subsidiary (Exhibit 21), use `entity_search.py ex21` in `bayou:la-power-map` instead of reading 10-Ks by hand.

**Red flags that contradict permit applications:**
- Dollar amounts under "environmental contingencies" or "contingent liabilities"
- Disclosure of NRC, EPA, or DOJ investigations not mentioned in permit filings
- Changes in decommissioning cost estimates
- New Superfund site designations or CERCLA liability acknowledgments
- Material regulatory uncertainty language added between filing cycles

---

## DOJ ENRD Press Releases

> **⚠️ The DOJ public JSON API is dead (verified 2026-06-08).** `https://www.justice.gov/api/v1/pressreleases.json` no longer returns JSON — it serves the site's HTML shell regardless of query params. Do not rely on it. Use the WebSearch / WebFetch paths below instead.

### Search via WebSearch scoped to justice.gov (recommended)

This is the most reliable path and surfaces both press releases **and** lodged consent-decree PDFs (which live under `justice.gov/enrd/media/...`):

```
WebSearch: query="<Company> DOJ ENRD environmental enforcement consent decree Clean Air Act settlement" allowed_domains=["justice.gov"]
```

Then fetch a specific consent-decree PDF. Note WebFetch returns **HTTP 403** on `justice.gov/enrd/media/.../dl` links — download with curl + a browser User-Agent instead, then parse the PDF locally:

```bash
curl -s -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -o /tmp/decree.pdf "https://www.justice.gov/enrd/media/<ID>/dl?inline=" 2>/dev/null
python3 -c "import pdfplumber;print('\n'.join((p.extract_text() or '') for p in pdfplumber.open('/tmp/decree.pdf').pages[:8]))"
```

The decree caption gives the case number, court, defendants, statute (CERCLA §107, CWA, CAA, etc.), and the payment/penalty section gives per-defendant amounts.

### (Legacy — no longer works) Search via DOJ public API

```bash
# DEAD — returns HTML, kept only to document the deprecated endpoint
QUERY="Entergy+Louisiana+nuclear"
curl -s "https://www.justice.gov/api/v1/pressreleases.json?q=${QUERY}&sort_by=field_pr_date&sort_order=DESC&pagesize=25&page=0" 2>/dev/null
```

#### Filter to ENRD-specific releases

Add `environment` or `ENRD` to the query, or search the component directly:

```bash
# Include "environment" component in query
curl -s "https://www.justice.gov/api/v1/pressreleases.json?q=Entergy+environment&sort_by=field_pr_date&sort_order=DESC&pagesize=25&page=0" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for r in d.get('results', []):
    comps = r.get('field_pr_components', [])
    if any('environment' in str(c).lower() for c in comps):
        print(r.get('field_pr_date','')[:10], '|', r.get('title',''))
        print('  URL:', r.get('url',''))
        print()
"
```

#### Pagination

```bash
# Page 0 = first 25 results; increment page for more
# d['count'] = total results; d['next'] = URL for next page if present
```

---

### DOJ Consent Decrees

Consent decrees are filed as federal court documents. The best paths:

1. **ENRD consent decree database** (browse/text search):
   `https://www.justice.gov/enrd/consent-decrees`

2. **DOJ ENRD search** (ENRD-scoped full-text):
   `https://www.justice.gov/enrd/search`
   Use `curl` + HTML parsing, or direct the user to the browser for consent decree PDFs.

3. **PACER** — consent decrees appear as "Consent Decree" docket entries in civil cases. Once you have a case number from a DOJ press release, use `bayou:pacer-case-search` to pull the docket sheet and locate the filed decree.

4. **Cross-reference tip**: DOJ press releases typically include the court, case number, and filing date. Extract those and hand off to `bayou:pacer-case-search`.

---

## Integrated workflow

1. **Start with DOJ ENRD** — search for company name and facility name separately; note all case numbers and dates found in press releases
2. **Run EDGAR EFTS** — search for company name + facility name + relevant legal terms; capture hits by year
3. **Pull 10-K contingency notes** — for any year where a DOJ action occurred, retrieve that year's 10-K and search Note sections for dollar amounts disclosed
4. **Look for gaps** — if DOJ shows a penalty in year X but the permit application omits it, that's a contradiction to flag
5. **Check XBRL quantitative data** (optional) — for structured environmental liability figures from XBRL-tagged filings:
   ```bash
   CIK="0000065984"
   curl -s "https://data.sec.gov/api/xbrl/companyfacts/CIK${CIK}.json" \
     -H "User-Agent: BayouResearch research@example.com" \
     2>/dev/null | python3 -c "
   import sys, json
   d = json.load(sys.stdin)
   facts = d.get('facts', {}).get('us-gaap', {})
   # Look for environmental liability line items
   for key in facts:
       if 'environmental' in key.lower() or 'contingenc' in key.lower():
           units = facts[key].get('units', {})
           for unit, entries in units.items():
               for e in entries[-5:]:
                   print(key, '|', e.get('end',''), '|', unit, e.get('val',''))
   "
   ```

---

## How to present results

### DOJ results table
| Date | Title | Case/Decree | Court | Amount |
|---|---|---|---|---|

- Flag criminal actions separately from civil
- Note whether a consent decree has been filed (vs. press release only)
- Include the DOJ press release URL for each finding

### SEC EDGAR results table
| Filed | Form | Company | Entity | Description | Link |
|---|---|---|---|---|---|

- For 10-K hits: quote the exact contingency language and dollar amount
- For 8-K hits: note the item number and nature of the material event
- Flag any disclosure that appeared after a DOJ press release date — late disclosure is itself a finding
- Link to the EDGAR filing viewer: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={CIK}&type=8-K&dateb=&owner=include&count=40`

### Contradiction summary
After surfacing results, present a one-paragraph synthesis: what was disclosed to investors vs. what the permit application represents, and where the two diverge.

$ARGUMENTS
