---
name: lac33-search
description: Search Louisiana Administrative Code Title 33 (LDEQ environmental regulations) by section number (e.g., LAC 33:I.317) or keyword
allowed-tools: Bash, WebFetch, AskUserQuestion
---

# Louisiana Administrative Code Title 33 Search

Fetch current regulatory text directly from the Louisiana Division of Administration's official DOCX files. Title 33 contains all LDEQ environmental regulations — penalties, permit requirements, inspection procedures, financial assurance, hearing procedures, and emission limits.

**Distinct from R.S. 30**: The LAC contains LDEQ's implementing regulations; R.S. 30 contains the enabling statutes. For the statute itself, use `bayou:la-rs-search`.

---

## Title 33 Volume Map

| Part | Subject | Typical citations |
|---|---|---|
| **I** | Office of the Secretary — procedural rules, adjudications, penalties, enforcement | LAC 33:I.101, LAC 33:I.317, LAC 33:I.4001 |
| **III** | Air Quality — Title V, NSR, emission standards, excess emissions | LAC 33:III.501, LAC 33:III.919 |
| **V** | Hazardous Waste and Hazardous Materials — RCRA, LDR, financial assurance | LAC 33:V.3701, LAC 33:V.4903 |
| **VI** | Inactive and Abandoned Hazardous Waste Site Remediation (RECAP) | LAC 33:VI.101 |
| **VII** | Solid Waste | LAC 33:VII.501 |
| **IX** | Water Quality — LPDES, stormwater, discharge limits | LAC 33:IX.2301 |
| **XI** | Underground Storage Tanks | LAC 33:XI.101 |
| **XV** | Radiation Protection | LAC 33:XV.101 |

---

## Step 1: Identify the correct volume

Parse the arguments to determine which Part:
- If a specific section is given (e.g., `LAC 33:III.501`), the Roman numeral tells you the Part → **III → Air**
- If only a keyword is given, infer the Part from subject matter:
  - "penalty", "adjudication", "hearing", "enforcement", "financial assurance" → **Part I** (general procedure)
  - "permit", "Title V", "excess emissions", "NOx", "SO2", "flare", "emission limit" → **Part III** (Air)
  - "hazardous waste", "RCRA", "manifest", "Land Disposal Restrictions" → **Part V** (HazWaste)
  - "LPDES", "discharge", "effluent", "TMDL", "water quality" → **Part IX** (Water)
  - "storage tank", "UST", "petroleum release" → **Part XI** (UST)
  - "solid waste", "landfill" → **Part VII** (Solid Waste)
- If uncertain, ask the user which Part or start with Part I (most procedural citations).

---

## Step 2: Resolve the current DOCX URL

DOCX URLs contain a hash that changes when files are re-uploaded. Resolve the current URL before downloading:

```bash
python3 -c "
import urllib.request, re

url = 'https://www.doa.la.gov/doa/osr/louisiana-administrative-code/'
resp = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15)
html = resp.read().decode('utf-8', errors='replace')

# Find all 33vXX.docx links
volumes = re.findall(r'href=\"(/media/[a-z0-9]+/(33v\d+)\.docx)\"', html)
for path, name in volumes:
    print(name, 'https://www.doa.la.gov' + path)
"
```

This prints a map like:
```
33v01  https://www.doa.la.gov/media/kxtnwnbr/33v01.docx
33v03  https://www.doa.la.gov/media/q4eanemv/33v03.docx
...
```

Volume-to-Part mapping (volume number = Part number in Roman numerals):
- `33v01` → Part I (Office of Secretary)
- `33v03` → Part III (Air)
- `33v05` → Part V (Hazardous Waste)
- `33v06` → Part VI (RECAP)
- `33v07` → Part VII (Solid Waste)
- `33v09` → Part IX (Water Quality)
- `33v11` → Part XI (UST)
- `33v15` → Part XV (Radiation)

---

## Step 3: Download and extract the text

```bash
python3 - <<'PYEOF'
import urllib.request, io, zipfile, re, sys

DOCX_URL = "https://www.doa.la.gov/media/kxtnwnbr/33v01.docx"  # replace with target volume

print(f"Downloading {DOCX_URL} ...", file=sys.stderr)
req = urllib.request.Request(DOCX_URL, headers={'User-Agent': 'Mozilla/5.0'})
data = urllib.request.urlopen(req, timeout=60).read()
print(f"Downloaded {len(data):,} bytes", file=sys.stderr)

z = zipfile.ZipFile(io.BytesIO(data))
xml = z.read('word/document.xml').decode('utf-8', errors='replace')

# Extract paragraphs
paras = re.findall(r'<w:p[ >].*?</w:p>', xml, re.S)
para_texts = []
for p in paras:
    t = re.sub(r'<[^>]+>', '', p)
    t = re.sub(r'\s+', ' ', t).strip()
    if t and not re.match(r'^PAGEREF|^TOC\\b|^\s*\\h\s', t):
        para_texts.append(t)

print(f"Extracted {len(para_texts)} paragraphs", file=sys.stderr)

# ---- SEARCH LOGIC ---- #
# Option A: find by section number
SECTION = "317"  # e.g., "317" for §317, or "501" for §501
# Option B: find by keyword
KEYWORD = ""     # e.g., "financial assurance" or "penalty"

TARGET = SECTION or KEYWORD
results = []
for i, pt in enumerate(para_texts):
    if TARGET and TARGET.lower() in pt.lower():
        # Skip TOC entries (contain PAGEREF)
        if 'PAGEREF' not in pt and '\\h' not in pt:
            results.append(i)

if not results:
    print(f"No matches for '{TARGET}' in {len(para_texts)} paragraphs")
    sys.exit(0)

print(f"\nFound {len(results)} matching paragraph(s):\n")

for idx in results[:5]:  # show up to 5 hit locations
    # Print the section header (look back for nearest §-prefixed paragraph)
    header_idx = idx
    for j in range(idx, max(0, idx-20), -1):
        if para_texts[j].startswith('§') or re.match(r'^(Chapter|Part|Subpart)\s', para_texts[j]):
            header_idx = j
            break
    print(f"--- Found near paragraph {idx} ---")
    for k in range(header_idx, min(len(para_texts), idx + 15)):
        print(para_texts[k])
    print()
PYEOF
```

### Adjusting the search

- To search by **section number**: set `SECTION = "317"` (digits only, without §)
- To search by **keyword**: set `SECTION = ""` and `KEYWORD = "financial assurance"`
- For a **known LAC citation** like `LAC 33:I.317`, set the volume to `33v01` and `SECTION = "317"`
- For subparts (e.g., `§317.A.1`), search for the parent section `"317"` and read the surrounding paragraphs

---

## Step 4: Presenting the results

Present regulatory text verbatim. Structure:

1. **Citation**: `LAC 33:I.317.A` (full citation including part, section, subsection)
2. **Source**: DOCX URL + date of last update (from the volume map in Step 2)
3. **Text**: verbatim regulatory language, preserving subsection lettering
4. **Cross-references**: note any R.S. or other LAC sections cited in the text

### Citation format

> **LAC 33:I.317.A** (current as of April 2026, [doa.la.gov](https://www.doa.la.gov/doa/osr/louisiana-administrative-code/)): [verbatim text]

### Common cross-reference pattern

LAC 33:I frequently cross-references `R.S. 30:2024` (adjudicatory hearings) and `R.S. 30:2025` (penalties). When you see these in regulatory text, follow up with `bayou:la-rs-search` to fetch the corresponding statutory language.

---

## Common LAC 33:I sections (procedural/enforcement)

| Section | Subject |
|---|---|
| §§101-109 | Public Notification of Contamination |
| §§301-357 | Adjudications (hearing procedures, discovery, evidence) |
| §317 | Requests for Adjudicatory Hearings |
| §§401-499 | Small Business Compliance Assistance |
| §§501-599 | Environmental Compliance Inspections |
| §§701-799 | Emergency Order Procedures |
| §§4001-4099 | Civil Penalty Policy |

## Common LAC 33:III sections (Air)

| Section | Subject |
|---|---|
| §501 | Permit procedures (NSR/PSD) |
| §519 | Title V operating permit requirements |
| §901-919 | Excess emissions and malfunctions |
| §2160 | Financial assurance for closure |
| §5120 | Reasonably Available Control Technology (RACT) |

---

## File size guidance

Large volumes (33v03 Air = ~5 MB; 33v05 HazWaste = ~2.4 MB) may take 15-30 seconds to download. For targeted lookups, it is faster to download just the volume you need rather than all 8.

$ARGUMENTS
