---
name: la-rs-search
description: Look up Louisiana Revised Statutes text by R.S. number (e.g., R.S. 30:2020) or search for statutory language by keyword
allowed-tools: Bash, WebSearch, AskUserQuestion
---

# Louisiana Revised Statutes Search

Fetch current statutory text directly from the Louisiana Legislature website (legis.la.gov). Use for penalty provisions, inspection authority, hearing procedures, financial-assurance requirements, and other EQA language cited in regulatory documents.

**Scope**: All Louisiana Revised Statutes — but most useful for:
- **Title 30**: Minerals, Oil, Gas, and Environmental Quality (the EQA)
- **Title 56**: Wildlife and Fisheries
- **Title 33**: Municipalities (not the LAC — for LAC 33 use `bayou:lac33-search`)

---

## Method A — Direct lookup by R.S. number (preferred)

When you have a specific section number (e.g., "R.S. 30:2025" or "Title 30, §2025"):

### Step 1: Get ViewState tokens

```bash
python3 - <<'PYEOF'
import urllib.request, urllib.parse, re, http.cookiejar, json

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

url = 'https://legis.la.gov/legis/LawSearch.aspx'
resp = opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15)
html = resp.read().decode('utf-8', errors='replace')

vs  = re.search(r'id="__VIEWSTATE" value="([^"]+)"', html)
ev  = re.search(r'id="__EVENTVALIDATION" value="([^"]+)"', html)
vsg = re.search(r'id="__VIEWSTATEGENERATOR" value="([^"]+)"', html)

# POST to look up the section
TITLE   = "30"   # change as needed
SECTION = "2025" # change as needed

data = urllib.parse.urlencode({
    '__VIEWSTATE':           vs.group(1)  if vs  else '',
    '__EVENTVALIDATION':     ev.group(1)  if ev  else '',
    '__VIEWSTATEGENERATOR':  vsg.group(1) if vsg else '',
    'ctl00$ctl00$PageBody$PageContent$tbFirstNumber':  TITLE,
    'ctl00$ctl00$PageBody$PageContent$tbSecondNumber': SECTION,
    'ctl00$ctl00$PageBody$PageContent$btnViewLaw':     'View',
}).encode()

req = urllib.request.Request(url, data=data, headers={
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Referer': url,
})
resp2 = opener.open(req, timeout=15)
print("Statute URL:", resp2.geturl())

html2 = resp2.read().decode('utf-8', errors='replace')
# Strip HTML tags and normalize whitespace
text = re.sub(r'<style[^>]*>.*?</style>', '', html2, flags=re.S)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
text = re.sub(r'<[^>]+>', ' ', text)
text = re.sub(r'&nbsp;', ' ', text)
text = re.sub(r'&sect;', '§', text)
text = re.sub(r'&quot;', '"', text)
text = re.sub(r'&#167;', '§', text)
text = re.sub(r'\s+', ' ', text).strip()

# Isolate the statute body (between the RS number and footer)
m = re.search(r'RS \d+:\d+.*?If you experience', text, re.S)
if m:
    print(m.group(0).strip())
else:
    # Fallback: print anything after the navigation
    idx = text.find('§' + SECTION)
    if idx >= 0:
        print(text[idx:idx+4000])
    else:
        print(text[-3000:])
PYEOF
```

### Parsing the output

The statute URL will look like `https://legis.la.gov/Legis/Law.aspx?d=NNNNN`. Save this for future reference. The statute text will appear with:
- The section header (`§2025. Penalties — Civil`)
- Subsection text with lettered/numbered subdivisions
- The enacting statute history at the end (`Acts YYYY, No. NN, §N`)

### Handling sub-sections

The form takes the base section number only. Sub-sections (like `§2025(A)(1)`) are within the full section text — the entire section is returned and you read the relevant sub-paragraphs.

### Common EQA sections (Title 30)

| R.S. Section | Subject |
|---|---|
| 30:2001 | Short title — "Louisiana Environmental Quality Act" |
| 30:2002 | Purpose |
| 30:2003 | Policy declaration |
| 30:2004 | Definitions |
| 30:2011 | LDEQ secretary powers and duties |
| 30:2014 | Inspections and investigations |
| 30:2017 | Declaratory rulings |
| 30:2024 | Adjudicatory hearings; appeals |
| 30:2025 | Penalties — civil |
| 30:2026 | Penalties — criminal |
| 30:2027 | Citizens suits |
| 30:2030 | Environmental trust fund |
| 30:2076 | Air quality — permit requirements |
| 30:2109 | Solid waste — financial responsibility |
| 30:2194 | Hazardous waste — financial responsibility |
| 30:2288 | UST — financial responsibility |

---

## Method B — Text search (keyword in statute)

When you don't know the section number, use WebSearch to find it.

```bash
# Example searches:
# Find sections containing "financial assurance" in Title 30:
# Query: site:legis.la.gov "financial assurance" "R.S. 30" OR "Title 30"
# Find sections about civil penalties:
# Query: site:legis.la.gov "§" "civil penalties" "environmental quality"
```

Use WebSearch with queries like:
- `site:legis.la.gov "waste of oil" "R.S. 30"` — find specific phrase in Title 30
- `site:legis.la.gov "financial responsibility" "Title 30"` — find sections
- `site:legis.la.gov "30:2025"` — find citations to a specific section
- `Louisiana Revised Statutes "R.S. 30" "adjudicatory hearing" penalty site:legis.la.gov`

WebSearch will return links like `https://legis.la.gov/Legis/Law.aspx?d=NNNNN`. Once you have a doc ID, fetch the text directly:

```bash
curl -s "https://legis.la.gov/Legis/Law.aspx?d=NNNNN" -A "Mozilla/5.0" 2>/dev/null | python3 -c "
import sys, re
html = sys.stdin.read()
text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.S)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
text = re.sub(r'<[^>]+>', ' ', text)
text = re.sub(r'&nbsp;', ' ', text)
text = re.sub(r'&#167;', '§', text)
text = re.sub(r'\s+', ' ', text).strip()
m = re.search(r'RS \d+:\d+.*?If you experience', text, re.S)
if m: print(m.group(0).strip())
"
```

---

## Fetching multiple consecutive sections

To browse consecutive sections, note the doc ID returned from a lookup and increment/decrement by 1 to get adjacent sections. IDs are sequential within a title but not guaranteed to be contiguous across chapters.

Alternatively, after fetching one section, parse the `ButtonNext` control from the page to find the next section's URL:
```python
next_link = re.search(r'ButtonNext.*?href="(Law\.aspx\?d=\d+)"', html)
```

---

## How to present findings

- Quote the statute text verbatim, including subsection letters/numbers
- Always cite the full R.S. number (e.g., "R.S. 30:2025(A)(1)") and the URL
- Include the enacting statute history (Acts YYYY, No. NN) — this establishes when the provision became effective
- Note any amendments in the history that affect current penalty levels or effective dates

### Citation format

> **R.S. 30:2025(A)(1)** ([legis.la.gov](https://legis.la.gov/Legis/Law.aspx?d=NNNNN)): [verbatim text]

$ARGUMENTS
