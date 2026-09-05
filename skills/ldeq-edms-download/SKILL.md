---
name: ldeq-edms-download
description: Actually download document files (PDFs/zips) from LDEQ EDMS by driving a real headful browser, surfacing the CAPTCHA for the user to solve
allowed-tools: Bash, AskUserQuestion
---

# LDEQ EDMS Document Download

Downloads the real bytes of LDEQ EDMS documents — not just search/citation. `/bayou:ldeq-edms-search`
can find and cite documents but cannot retrieve them: the download path is gated by a **visible
reCAPTCHA v2 "I'm not a robot" checkbox** that only a real browser (with a human) can solve. This
skill drives an actual Chrome window through the EDMS UI — search, select, click Download — and
waits for the user to solve the CAPTCHA in that window, then captures and saves the resulting
file(s).

**This is local-only.** It opens a real, visible Chrome window on the user's machine and needs a
display — never run it in CI or a headless environment. It requires no EDMS login (search/download
are public).

## Prerequisites

One-time setup, from this skill's directory:

```bash
cd ~/.claude/plugins/bayou/skills/ldeq-edms-download
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` skips re-fetching Chromium — Playwright reuses whatever
Chromium build is already cached at `~/Library/Caches/ms-playwright/` (Claude Code's environment
already has one). If `node -e "require.resolve('playwright')"` run from this directory succeeds,
setup is done and this step can be skipped on future runs.

## Parsing arguments

Requires an **AI number**. Then one of:
- Specific **document IDs** — the plain numeric "Document ID" shown in the EDMS results grid
  (this is the `id` field from `/bayou:ldeq-edms-search` results, *not* the hex `docIDSecured`
  used for viewer links). If the user is following up on a prior `ldeq-edms-search` result, use
  the `id` values from that result.
- **"download all"** — every document in the AI's first results page (up to 100 documents).

Examples:
- `26336 doc 15257395` — download one specific document
- `26336 docs 15257395 15257366 15240861` — download several specific documents
- `26336 download all` — download everything on the first results page

If the user hasn't already narrowed the result set and asks to "download all" for an AI with a
large number of documents, warn them first (see "Batching and CAPTCHA count" below) and confirm
with AskUserQuestion before proceeding — each batch of 20 needs its own manual CAPTCHA solve.

## Running the download

```bash
node ~/.claude/plugins/bayou/skills/ldeq-edms-download/edms_download.js \
  --ai 26336 --doc 15257395 --doc 15257366 \
  --out /path/to/output/dir
```

Or for "download all":

```bash
node ~/.claude/plugins/bayou/skills/ldeq-edms-download/edms_download.js \
  --ai 26336 --all --out /path/to/output/dir
```

Tell the user, before running: **a visible Chrome window will open.** For each batch it will show
a classic "I'm not a robot" checkbox — click it (and solve the image challenge if Google shows
one). That's the only manual step; the script then polls for EDMS's own "Document has been
processed." download link and fetches it automatically (see "How the script works" below) — no
second click needed. The script waits up to `--timeout` seconds per batch (default 3600 — see
"Timeout sizing" below) for the whole checkbox-plus-processing sequence.

**Timeout sizing.** Solving the checkbox does not mean the file is ready — EDMS still has to
gather and zip the requested documents server-side, and for large batches (multi-hundred/
thousand-page PDFs, e.g. a 2,165-page "Material Associated with Proposed Permit" bundle) that
alone has been observed to take well over 10 minutes. Run the download in
the background (`run_in_background: true` on the Bash call) rather than blocking on it, and don't
shorten `--timeout` back down for a "just a couple small docs" case unless you've confirmed the
batch is actually small — an oversized timeout costs nothing (it returns as soon as the file is
ready), while a timeout that fires early means redoing the CAPTCHA from scratch.

If no `--out` is given, files land in `~/Downloads/edms-<AI>-<timestamp>/`.

### Batching and CAPTCHA count

EDMS caps "Download selected documents" at **20 documents per click**. This script batches
automatically, but each batch of 20 opens its own window and needs its own CAPTCHA solve. For
`--doc` with a handful of specific documents this is usually 1 batch. For `--all` on an AI with
many documents, warn the user up front how many batches (`ceil(N/20)`) — and therefore how many
manual CAPTCHA solves — the run will need, and suggest narrowing the search first (via
`/bayou:ldeq-edms-search` filters) if that number is large.

## How the script works (for troubleshooting)

1. Launches a **headful**, **persistent** Chromium profile (kept in `.pw-profile/` next to the
   script) — persistence keeps cookies/history across runs, which tends to reduce how often
   Google escalates to an image challenge.
2. Navigates to `/quick-search`, fills the AI number, searches.
3. Reads the results grid (`tr.k-master-row`); document IDs are each row's second cell.
4. For `--doc`, pages through results (up to 20 pages) hunting for the requested IDs; for `--all`,
   takes the first page as-is.
5. Selects the target rows' checkboxes and clicks the grid's download button, which opens a
   **popup window** at `/doc/download?docid=...`.
6. Waits for the user to solve the popup's "I'm not a robot" checkbox. After that, EDMS does
   **not** fire a browser download event on its own — it takes an unpredictable amount of time
   (minutes, for large batches) to assemble the requested documents into a zip server-side, then
   swaps the popup's content to "Document has been processed." and reveals
   `<a id="download-link" href=".../app/cache/<uuid>.zip">` (rendered as an SVG icon with no text,
   which is why an early version of this script's `:has-text("Download")` button-search never
   matched it and always timed out). The script polls for that anchor's `href` to become
   non-empty, then fetches it directly via `context.request.get()` — reusing the browser
   context's cookies — and writes the bytes to disk. No click on the link and no `download` event
   wait is needed; confirmed against a live single-document test.
7. Closes the popup and repeats for the next batch.

## Presenting results

List the saved file paths (printed as the script's final lines). **LDEQ EDMS documents are
scanned/rasterized images with no embedded text layer — confirmed across all 13 documents in an
AI 248885 batch (2-page notices through a 2,165-page permit bundle all returned zero extractable
characters via `pdftotext`).** Assume this for any EDMS download until proven otherwise; don't
hand raw EDMS PDFs to `/bayou:permit-analysis` (or any text-search step) without running
`/bayou:document-ocr` on them first — it will silently see empty/no text rather than erroring.
If the user's underlying goal is to read/analyze the contents (e.g. confirm a numeric limit in a
permit), the actual next step is: `/bayou:document-ocr` on the downloaded folder, then
`/bayou:permit-analysis` on the OCR output.

## Troubleshooting

- **"Download button not found"** — the EDMS UI changed. Re-pin selectors by loading
  `https://edms.deq.louisiana.gov/edmsv2/quick-search` in a normal browser, inspecting the
  search input, results grid, and download button, and updating the selectors at the top of
  `edms_download.js`.
- **Timed out waiting for CAPTCHA / file to be ready** — this can mean either the CAPTCHA was
  never solved, or (more likely for a large batch) EDMS is still assembling the zip server-side;
  re-run with a larger `--timeout` (the default is already 3600s for this reason), or check that
  the Chrome window wasn't accidentally closed/backgrounded during the wait.
- **Some `--doc` IDs not found** — the script scans up to 20 result pages (2,000 documents); IDs
  beyond that, or IDs that don't actually belong to the given AI, will be reported as not found.
- **`#download-link` selector stops matching** — the EDMS UI changed the post-processing markup.
  Re-pin by loading a doc URL directly (`/doc/download?docid=...`), solving the CAPTCHA, and
  inspecting the DOM once "Document has been processed." appears.

$ARGUMENTS
