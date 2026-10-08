---
name: la-coastal-use-permits
description: Find Louisiana coastal use permits (CUPs) by parish, applicant or period — OCM semi-monthly status reports, current OCM public notices, and St. Charles Parish local coastal program notices — then resolve a CUP number to its site location through SONRIS
argument-hint: <parish | applicant | CUP number> [date range]
allowed-tools: Bash, WebFetch, Read, AskUserQuestion, Skill
---

# Louisiana Coastal Use Permits

Most work in Louisiana's coastal zone needs a coastal use permit (CUP), including fill, pipelines,
roads, timber-mat access, dredging and bulkheads. CUPs are issued by the Office of Coastal
Management (OCM), or by a parish that runs its own Local Coastal Program (LCP). This skill finds
which CUPs exist. The location of a CUP comes from its permit document in SONRIS, through
`bayou:sonris-doc-search`.

Use it when a Corps search comes up empty. The Corps publishes notices only for individual
permits, but nearly every coastal-zone job still needs a CUP.

## Sources

| Source | What it has | Access |
|---|---|---|
| OCM status reports (semi-monthly PDFs) | Every application acknowledged and every decision: applicant, parish, CUP number, and often the Corps number. **No site location.** | `curl`, no session |
| OCM current public notices | Notices open for comment now, with a project description and location | WebFetch |
| St. Charles Parish LCP notices | Parish-level CUPs (`SCP-yyyy-nn`) published as legal notices | Herald-Guide legals PDF |
| SONRIS document index | The CUP application and authorization, whose `LOCATION:` line gives the lat/long | `bayou:sonris-doc-search` (CAPTCHA session) |

## Step 1: Status reports — which CUPs exist

```
https://www.denr.louisiana.gov/assets/OCM/PublicNotices/SR_{yyyy}/SR_{mm}_{01|16}_{yyyy}.pdf
```

Each file is named for the **start** of its period: `SR_01_16_2025.pdf` covers 16–31 January
2025. Download them sequentially, not in parallel:

```bash
mkdir -p sr && cd sr
for y in 2025 2026; do for m in 01 02 03 04 05 06 07 08 09 10 11 12; do for d in 01 16; do
  f="SR_${m}_${d}_${y}.pdf"
  curl -sf -o "$f" "https://www.denr.louisiana.gov/assets/OCM/PublicNotices/SR_${y}/$f" || rm -f "$f"
  sleep 1
done; done; done
```

A missing period returns an error and is skipped. Future periods simply don't exist yet.

**Getting text out:**
- **2025 files have a text layer.** Use `pdftotext -layout SR_….pdf`.
- **2026 files are image-only** (producer "Microsoft: Print To PDF"), so `pdftotext` returns
  nothing. Use the tesseract quick path from `bayou:document-ocr`, which is enough for these
  clean typed tables:
  ```bash
  pdftoppm -r 170 -png SR_01_16_2026.pdf SR_01_16_2026 \
    && for p in SR_01_16_2026-*.png; do tesseract "$p" "${p%.png}" --psm 6; done
  ```
  The full `document-ocr` pipeline is far slower here and puts each table cell on its own line.

Rows look like this. Columns are applicant, parish, CUP number and Corps number, and decision
sections add a date:

```
CHEVRON ENVIRONMENTAL MANAGEMENT COMPANY          ST. CHARLES         P20250035
SHELL PIPELINE COMPANY LP                         IBERIA              P20250012    MVN 2025-00060 WB
```

Filter by parish or applicant with `rg -i "ST\.? CHARLES" *.txt`. OCR can misread a parish name,
so for 2026 files also try a looser pattern such as `CHARL`. Each report starts with a summary
table of status counts (under review, more information needed, no permit required, …).

## Step 2: CUP number → site location

The status report does not say where the work is. For each candidate `P{yyyy}{nnnn}`, run the
**"Coastal use permits (CUP number → site)"** recipe in `bayou:sonris-doc-search`. It searches
SONRIS by `xRefNum`, downloads the newest AUTHORIZATIONS document (else APPLICATION), and greps
its `LOCATION:` and `DESCRIPTION:` lines, which include lat/long.

Batch the searches into one `sonris_get.js` run and the downloads into a second run. SONRIS
blocks aggressive or machine-like traffic for about 48 hours. Don't loop over CUPs one call at
a time, and never raise the throttle or `--max`. Before downloading, cut the candidates by
parish and applicant type.

## Step 3: Current OCM public notices

```
https://www.dce.louisiana.gov/page/coastal-management-public-notices
```

The old `dnr.louisiana.gov` address redirects here. Every section is an accordion on one page
of text, so a single WebFetch reads it all. Only notices currently open for comment appear;
past notices are not archived on this page.

## Step 4: St. Charles Parish Local Coastal Program

St. Charles Parish runs its own LCP, so some CUPs there never pass through OCM's reports.
These notices are titled "Notice of Pending Application" and numbered `SCP-yyyy-nn`. They
are published in the **Herald-Guide** legal notices, which come out on Thursdays:

```
https://www.heraldguide.com/wp-content/uploads/{yyyy}/{mm}/HGLegals_{yyyymmdd}.pdf
```

The PDFs have a text layer, but WebFetch cannot parse them. Download each one with `curl` and
read it with `pdftotext -layout`. The parish Coastal Zone Advisory Committee meets monthly at
noon in Hahnville. The parish coastal contact named in the notices is Clay Ledet,
985-783-5060.

Other coastal parishes also run LCPs. Only St. Charles's publication channel is documented here.
For another parish, find its legal-notice newspaper before assuming OCM's reports are complete.

## How to present results

1. A table of candidate CUPs: CUP # | Applicant | Parish | Corps # | Report period | Status.
2. For any CUP resolved through SONRIS, add its `LOCATION:` lat/long and its `DESCRIPTION:`.
   When the user gave a target point, add the distance to it (`bayou:geo-distance`).
3. Say which sources were checked and which periods were missing.
4. Status reports carry no location. A CUP that hasn't been resolved through SONRIS is a
   candidate, not a match.

$ARGUMENTS
