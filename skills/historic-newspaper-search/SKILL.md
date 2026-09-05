---
name: historic-newspaper-search
description: Search Library of Congress Chronicling America and Internet Archive fulltext for historic newspaper coverage of a place, person, plantation, or event — documentary research for chain-of-title, community history, and cultural-resource screens
argument-hint: <search terms> [state/parish] [date range]
allowed-tools: Bash
---

# Historic Newspaper & Archive Search

Searches two free, no-key digitized-newspaper/text corpora for historic coverage of a place name, person, or event: **Library of Congress Chronicling America** (1770s–1963, national) and **Internet Archive** fulltext (books, annual reports, directories). Built for documentary-history questions — establishing when a place name appears, tracing a named individual's public record, or checking whether a specific claim (a plantation name, a community, a company) shows up in the period record at all.

## Step 1: Chronicling America search

```bash
python3 -c "import urllib.parse; print(urllib.parse.quote('\"exact phrase here\"'))"
```

Use the URL-encoded output in:

```bash
ENCODED='%22exact+phrase+here%22'
curl -s --max-time 30 "https://www.loc.gov/collections/chronicling-america/?q=${ENCODED}&fa=location_state:louisiana&fo=json" -o loc_results.json
python3 -c "
import json
d = json.load(open('loc_results.json'))
print('total:', d.get('pagination', {}).get('of'))
for item in d.get('results', []):
    print(item.get('date'), '|', item.get('title'), '|', item.get('id'))
"
```

**Use `www.loc.gov/collections/chronicling-america/`, not the old `chroniclingamerica.loc.gov` host** — the old host now 308-redirects and following redirects blind wastes a round trip; the `www.loc.gov` endpoint is the current, direct one.

**Wrap the search term in literal `"double quotes"` before URL-encoding it** for an exact-phrase match. Without them, multi-word terms silently become an OR-of-words match and the result count balloons with noise (a search for `Cedar Grove Plantation` without quotes will surface every article mentioning any Cedar Grove, anywhere, plus every unrelated plantation).

**Batch multiple queries with an explicit `--max-time` on each `curl`, and expect the occasional hang.** Firing off five or six phrase searches in a shell loop without a timeout has been observed to hang past a 2-minute tool timeout on one query in the batch; add `--max-time 30` to every call and retry individually rather than re-running the whole batch.

**A "zero hits" result is only meaningful once you've confirmed the corpus actually covers the right geography and era.** Before trusting an absence, run a second query for a broad term you *know* should hit (the parish name, a known-common word) against the same date/location filters — if that also comes back empty, the filter or corpus coverage is the problem, not the fact you're checking.

### Step 1b: Get OCR full text for a specific hit

Each search result's `id` is a page URL, not the text itself. Getting the actual OCR text is a **two-step fetch**:

```bash
python3 -c "
import json, urllib.request

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 research script'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

item_url = 'https://www.loc.gov/resource/sn85034322/1921-01-08/ed-1/?sp=1'
sep = '&' if '?' in item_url else '?'
meta = fetch_json(item_url + sep + 'fo=json')
fulltext_url = meta['resource']['fulltext_file']

req = urllib.request.Request(fulltext_url, headers={'User-Agent': 'Mozilla/5.0 research script'})
with urllib.request.urlopen(req, timeout=30) as r:
    raw = r.read().decode('utf-8', errors='replace')
data = json.loads(raw)
key = list(data.keys())[0]
print(data[key]['full_text'])
"
```

**The `fulltext_file` URL includes `format=alto_xml` in its query string but actually returns JSON, not XML** — `{"<segment-path>": {"full_text": "...", "height": "...", "width": "..."}}`. Parse it as JSON. (If you pipe the raw response through a tool expecting ALTO XML, or manually strip a leading line-number/tab prefix expecting a different format, it will fail — there is no such prefix; that appearance only comes from viewing the saved file through a line-numbering tool like `cat -n` or the `Read` tool afterward, not from the actual bytes on the wire.)

**Always fetch `https://` — a plain `http://` request 301-redirects and `curl` without `-L` (or Python's default non-following behavior in some contexts) will silently return 0 bytes.**

**Extracting multi-word context around a match**: shell `grep -o -E ".{100}term.{100}"` will not match across newlines (the OCR text is heavily line-broken), so it frequently returns nothing even when the term is clearly present. Use Python instead:

```bash
python3 -c "
import re
txt = open('ocr_output.txt', encoding='utf-8').read()
for m in re.finditer(r'search term', txt, re.IGNORECASE):
    s, e = max(0, m.start()-150), min(len(txt), m.end()+150)
    print(repr(txt[s:e]))
    print('---')
"
```

## Step 2: Internet Archive fulltext search

```bash
curl -s --max-time 30 "https://archive.org/advancedsearch.php?q=title%3A%28search+terms%29&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=year&rows=30&output=json" -o ia_results.json
python3 -c "
import json
d = json.load(open('ia_results.json'))
print('numFound:', d['response']['numFound'])
for doc in d['response']['docs']:
    print(doc.get('year'), doc.get('title'), doc.get('identifier'))
"
```

To pull an item's OCR text (works well for annual reports, crop statements, and county/parish histories):

```bash
IDENTIFIER="some-archive-org-identifier"
curl -sL --max-time 30 "https://archive.org/download/${IDENTIFIER}/${IDENTIFIER}_djvu.txt" -o ia_fulltext.txt
```

**`-L` (follow redirects) is required** — a plain request without it has been observed to return an HTTP 200 with a 0-byte body rather than an error, which looks like "no text" when it's actually "wrong URL handling." Confirm with `wc -c` that something non-trivial actually downloaded before concluding a search term isn't present.

Confirm the item actually has a `_djvu.txt` file before assuming this pattern works for it:

```bash
curl -s --max-time 20 "https://archive.org/metadata/${IDENTIFIER}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for f in d.get('files', []):
    if f.get('name','').endswith('_djvu.txt'):
        print(f['name'])
"
```

## Presenting results

Quote the matched passage in context (not just the search-hit fragment), with the paper name, date, and page/image number, and the retrieval date. State plainly when a search came back empty and what that does and doesn't establish (see the corpus-coverage caution above) — an absence is often worth reporting explicitly rather than silently moving on, especially in a documentary-research memo where "we checked and didn't find X" is itself part of the record.

### Citation format

> ***The St. Charles Herald* (Hahnville, La.), January 8, 1921, p. 1**, source: [Library of Congress, Chronicling America](https://www.loc.gov/collections/chronicling-america/) (retrieved 2026-07-22).
>
> ***New Orleans Price Current, Yearly Report of the Sugar and Rice Crops of Louisiana*** (1877–78), source: [Internet Archive](https://archive.org/details/neworleanspricec1877loui) (retrieved 2026-07-22).

$ARGUMENTS
