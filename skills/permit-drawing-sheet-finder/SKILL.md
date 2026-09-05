---
name: permit-drawing-sheet-finder
description: Locate a specific engineering drawing sheet (e.g. "Sheet A-3 of A-42", "Overall Area Map") inside a large multi-page CAD-exported permit exhibit PDF, when a comment letter or report cites the sheet by number but not by PDF page
argument-hint: <path-to-pdf> <cited sheet number, e.g. "A-3">
allowed-tools: Bash
---

# Permit Drawing Sheet Finder

Permit applications routinely attach CAD-exported drawing sets (site plans, civil drawings, "overall area maps") running 30–100+ pages, where every sheet carries its own printed sheet number in a title block (e.g. "SHEET NUMBER: A-3 OF A-42") that has **no fixed relationship to the PDF's page number**. Comment letters, expert reports, and your own prior research will cite a sheet by its printed number ("Overall Area Map, Sheet A-3") — this skill finds which actual PDF page that is, without opening and eyeballing the whole document one page at a time.

## Step 0 — get the actual page count and confirm it's a text-extractable or image-only PDF

```bash
PDF="path/to/drawing-set.pdf"
pdfinfo "$PDF" 2>&1 | grep -E "Pages|Page size"
```

If `pdfinfo`/`pdftotext`/`pdftoppm` aren't on `PATH` (common in non-interactive shells), fall back to `/opt/homebrew/bin/<tool>` before assuming poppler isn't installed.

## Step 1 — try text extraction first (fast, sometimes unreliable)

```bash
pdftotext -layout "$PDF" /tmp/drawingset.txt
python3 -c "
import re
text = open('/tmp/drawingset.txt', encoding='utf-8', errors='replace').read()
pages = text.split('\f')
print('pages in text layer:', len(pages))
for i, pg in enumerate(pages, 1):
    m = re.findall(r'([A-Z]?-?\d+)\s+OF\s+([A-Z]?-?\d+)', pg, re.IGNORECASE)
    if m:
        print(i, m)
"
```

**This regularly only works for some of the pages, not all of them — expect it, don't debug it as a failure.** CAD-to-PDF exports place text runs in drawing (insertion) order, not visual reading order, so `pdftotext`'s output for a given page can arrive scrambled or split across unrelated fragments (a sheet number like "A-20" can come out as two separate tokens, "2" and "A-19", nowhere near each other). In practice this means: **later pages in a sequential drawing set often extract cleanly while earlier ones (title/index/legend pages, or ones with dense annotation) don't** — use whatever clean matches you get to establish the sheet-number-to-PDF-page **offset**, then compute the rest.

**Watch for false positives**: a sheet number pattern can appear as *content* on a page rather than as *that page's own* title-block stamp — e.g., an index/key sheet showing which sheets cover which map tiles (grid callouts "A-1", "A-2", "A-3", "A-4" pointing at neighboring areas), or a detail sheet where "A-1" through "A-4" are equipment/tank labels, not sheet numbers at all. A real title-block stamp is usually the pattern `<prefix>-<number> OF <prefix>-<total>` appearing once, near "SHEET NUMBER" or "SHEET NO." — a bare grid of `A-1, A-2, A-3, A-4` scattered across a drawing without that framing is very likely something else on the page, not a sheet index. If you get a hit, sanity-check it against the rendered page (Step 3) before trusting it.

## Step 2 — compute the offset and target page

Once you have at least one confirmed `PDF page N = Sheet <prefix>-M`, the drawing set is almost always sequential from there:

```bash
python3 -c "
confirmed_pdf_page = 25
confirmed_sheet_num = 20   # e.g. confirmed 'A-20' visually
target_sheet_num = 3       # looking for 'A-3'
print('estimated target PDF page:', confirmed_pdf_page - confirmed_sheet_num + target_sheet_num)
"
```

This only holds if the set has no gaps (skipped sheets, sheets out of order, or front-matter pages inserted mid-sequence) — treat it as a strong first guess to render and visually confirm, not a certainty.

## Step 3 — render and visually confirm

```bash
mkdir -p /tmp/sheet-check
pdftoppm -f <estimated-page> -l <estimated-page> -r 150 -png "$PDF" /tmp/sheet-check/page
```

Read the resulting PNG and check the title block (almost always bottom-right) for "SHEET NUMBER: A-3 OF A-42" or equivalent, plus the drawing title, to confirm you have the right sheet before doing anything else with it — including telling the user you found it. If it's off by one or more pages, adjust and re-render; this is normal and fast at 150 DPI.

## Step 4 — read fine detail (labels, small icons, legends)

150 DPI is enough to confirm identity but usually too coarse to read small annotations, legend text, or icons (a cemetery symbol, a small callout label). Re-render at higher resolution and crop to the region of interest rather than rendering the whole sheet at high DPI (which produces an unwieldy multi-thousand-pixel image that's still hard to read at a glance):

```bash
pdftoppm -f <page> -l <page> -r 400 -png "$PDF" /tmp/sheet-check/page_hires
# find dimensions, then crop with gdal_translate (needs GDAL — see bayou:usgs-historic-topo-lidar's
# prerequisites note on installing it) or with a plain PNG tool:
gdal_translate -q -srcwin <x_offset> <y_offset> <width> <height> \
  /tmp/sheet-check/page_hires-XX.png /tmp/sheet-check/crop.png
```

**Your first crop window will often be wrong** — estimate the region's approximate position as a fraction of the full sheet from the 150 DPI overview, crop generously wide, read it, then narrow. This is the same iterate-don't-fight-the-math pattern as the historic-topo crop workflow.

## Presenting results

State the printed sheet number, its title/description, and which PDF page it actually is, e.g.: *"Sheet A-3 of A-42 ('Overall Area Map, Facility Site Permit Drawing') is PDF page 8 of `<filename>`."* If a specific claim from a comment letter or report cited this sheet for a particular feature (a distance line, a labeled icon), say plainly whether you could or couldn't confirm that feature at the resolution available — don't imply confirmation you didn't actually get a clear look at.

$ARGUMENTS
