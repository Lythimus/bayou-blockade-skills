---
name: sonris-doc-search
description: Search SONRIS documents by operator code, well serial number, parish, and/or document type, then bulk-download the matching PDFs — covers well permits and orders as well as coastal, mineral-lease, and inspection records for any DNR-regulated operator
argument-hint: <operator code or name> [well serial] [parish] [doctype] [download]
allowed-tools: Bash, AskUserQuestion
---

# SONRIS Document Search & Download

Finds and retrieves the actual document files SONRIS holds for an operator — permits,
applications, orders, inspections, coastal use authorizations, and more — not just well
data. This is the retrieval half of the pipeline; `bayou:sonris-operator-lookup` resolves
the company name to a code first, and `bayou:document-ocr` → `bayou:permit-analysis` pick
up whatever gets downloaded here.

> **Throttling is not optional.** SONRIS's Terms of Use prohibit automated access and
> describe a 7-day IP ban for detected bot-like behavior. Every request in this skill goes
> through `sonris_get.js`, which enforces a minimum delay (default 2.5s + jitter) and a
> per-run cap (default 200) automatically — **do not raise `--throttle` down or `--max` up
> "to go faster."** A handful of well-targeted searches and a handful of document
> downloads is the normal shape of a research session here; if a task is starting to look
> like it needs hundreds of documents, stop and point the user at SONRIS's paid Data
> Subscription Service instead of grinding through it request-by-request.

## Step 0 — check the local case file first

Before any network call, check whether the documents already exist on disk (a prior
download, a party's own filing, an OCR'd copy from a comment letter):

```bash
rg -il -e "sonris" -e "dDocname" -e "UIC CLASS VI" -e "<well/operator name>" .
```

If the case directory already has the SONRIS documents needed, use those — say so
explicitly rather than re-downloading.

## Step 1 — resolve inputs

- If given a company name instead of an operator code, run `bayou:sonris-operator-lookup`
  first.
- Confirm a session: `node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js --check`.
  If none, walk the user through `bayou:sonris-session` before continuing.

## Step 2 — build the search

Two paths, prefer the first:

**A. A user-pasted SONRIS results URL** (`.../document_access/findalldocumentsresults?p22_query=...&cs=...`)
— if the user already ran a search in their own browser and copied the URL, use it
as-is via `sonris_get.js`. Its `cs=` checksum is valid for that exact query only (see
`references/sonris-vocabulary.md`) — don't try to edit the query string and reuse the
checksum.

**B. Constructed `idx`/`val` search** — build one URL per known field (see
`references/sonris-vocabulary.md` for the confirmed/hypothesized field list):

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_get.js \
  --url "https://sonlite.dnr.state.la.us/ords/r/sonris/ucmsearch/finddocuments?idx=xOperatorCode&val=H1166" \
  --throttle 2500
```

**Only one `idx`/`val` pair per request is confirmed to work.** For a multi-condition
search (operator + parish + doctype, matching what the user's own example search does),
run one request per condition and **intersect the results client-side** by matching
`dDocname` values across the result sets, rather than assuming the URL accepts repeated
params — see the vocabulary reference for why.

## Step 3 — parse results

The result page's structure hasn't been formally documented (see the vocabulary
reference); the reliable extraction heuristic is to pull every `dDocname=` value out of
the returned HTML, since SONRIS's own document links always embed it:

```bash
python3 -c "
import re, sys
html = sys.stdin.read()
ids = sorted(set(re.findall(r'dDocname=([A-Za-z0-9_.-]+)', html)))
for i in ids:
    print(i)
"
```

Pull whatever title/doctype/date text sits near each match in the surrounding HTML too —
inspect a real result page once per session to confirm the row structure hasn't drifted,
rather than assuming a fixed column layout.

If a search returns zero `dDocname` hits, don't assume "no documents" — first check
whether the response is actually the CAPTCHA page (`sonris_get.js` should have already
caught this and exited 2, but verify) or a Cloudflare/edge block that slipped through as
an empty-looking body (exit 3 — see `bayou:sonris-session`'s exit-code table) before
reporting an empty result to the user.

## Step 4 — download

Direct document bytes are at `dnrservices/redirectUrl.jsp`:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_get.js \
  --url "https://sonlite.dnr.state.la.us/dnrservices/redirectUrl.jsp?dDocname=<id>&showInline=True" \
  --out-dir . --throttle 2500
```

Pass `--url` once per document (repeatable) or `--url-file` for a longer list. Default
output directory should be the current case-file directory unless the user names another,
matching the existing `~1.pdf`-style convention already used for hand-downloaded SONRIS
files in these folders.

If the user asks to "download all" on a large result set, warn them first how many
documents that is and confirm before running — mirrors `bayou:ldeq-edms-download`'s
batching warning, even though this flow has no per-batch CAPTCHA (just the throttle).

## Step 5 — hand off

Once files are down, offer:
- `bayou:document-ocr` for any image-only scan (check `pdftotext file.pdf - | wc -c` — a
  near-zero byte count means it's a scan needing OCR, same check already used on
  `Resolution LA Mineral and Energy Board.pdf` in this case directory).
- `bayou:permit-analysis` once the set is text-readable.

## Presenting results

Table: `dDocname` | Title | Doctype | Date | Saved path (once downloaded). Note the
operator/well/parish the search was scoped to, and whether results came from a
user-pasted URL or a constructed `idx`/`val` search.

### Citation format

> SONRIS document `<dDocname>`, "<title>" (<doctype>, <date if known>), operator
> `<code>`, source: [sonlite.dnr.state.la.us](https://sonlite.dnr.state.la.us) (retrieved
> 2026-08-15, session-authenticated).

## Troubleshooting

- **`sonris_get.js` exits 2** — no valid session (missing or no longer carries the
  `SONRIS_CAPTCHA2.0` cookie); re-run `bayou:sonris-session`, then resume from wherever
  the batch stopped (don't restart a large download from scratch).
- **`sonris_get.js` exits 3** — the request was blocked or rejected at the edge (a
  Cloudflare challenge or a 502/504), **not** a session problem — re-running
  `bayou:sonris-session` won't fix this. Try a stronger `--transport` per its `--help`,
  or pause and retry after a longer gap.
- **Zero results for a known-good operator** — double check the operator code (not the
  company name) is what's in `val=`, and that `idx=` field casing/name is right per the
  vocabulary reference; try the DCE Class VI page or `bayou:la-class-vi` as a
  cross-check if the operator is CCS-related.
- **A downloaded file is 0 bytes or looks like an HTML error page, not a PDF** —
  `sonris_get.js` now catches this itself (exit 3, file not written); if one slips
  through anyway, confirm with `file <path>`.

$ARGUMENTS
