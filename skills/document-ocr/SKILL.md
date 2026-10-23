---
name: document-ocr
description: OCR a folder (or single) scanned/image PDF into searchable .txt with per-line evidence (confidence, cross-reader agreement, table/checkbox structure), for any document source (LDEQ EDMS, USACE, FAA, or elsewhere). Flags the pages that look like tables and offers Azure Document Intelligence on just those pages (or the whole document), producing a readable <stem>.azure.txt with real table rows. Use between downloading raw permit PDFs and running /bayou:permit-analysis, which requires machine-readable text.
argument-hint: <input-dir-or-pdf> <output-txt-dir> [work-dir] [--backend <name>] [--azure] [--rerender]
allowed-tools: Bash, Read, AskUserQuestion
---

# bayou:document-ocr — bridge raw scanned PDFs to OCRed text + evidence

`/bayou:permit-analysis` requires machine-readable text (its extractor searches with `rg -in` and
cites `<file>.txt:<line>`), but document sources hand back raw, often scanned, image-only PDFs —
LDEQ EDMS, USACE public notices, FAA filings, whatever the source. This skill is the bridge: Surya
supplies geometry (page layout, per-line bounding boxes, confidence), one or more independent VLM
readers supply reading order and a disagreement signal, and the two are merged into a per-line
evidence record before `.txt` is ever written. It is **source-agnostic** — nothing here is
LDEQ-specific.

Every tier is **grid + reader(s)**: Surya alone is not the accuracy frontier on old scans, dense
numeric tables, or rotated engineering sheets, and VLM readers alone fabricate — clean, plausible,
wrong numbers. Neither is trustworthy solo. `agreement.m` on every canonical line records how many
independent readers actually voted, so a downstream consumer can tell a strong signal from a weak
one instead of assuming agreement that never happened.

## What this produces

```
$WORK/results/<stem>/results.json    # raw Surya -- single-witness geometry/confidence
$WORK/canonical/<stem>.json          # merged, per-line, with agreement + provenance
$OUT_TXT/<stem>.txt                  # rendered from canonical, with page markers
$WORK/tables/<stem>.json             # which pages look like tables (detect-table-pages.py)
$OUT_TXT/<stem>.azure.txt            # only after an Azure run: Azure's reading, tables as rows
```

`results.json` stays a **single witness** even though the pipeline now merges multiple readers:
`permit-analysis`'s blankness rule ("no text_line at all across a cell range is real evidence of
blankness") only holds if one engine attests it. If a reader hallucinated text into a genuinely
blank cell and that landed in the same file, the rule would silently invert. `canonical/<stem>.json`
is the merged sidecar — see `references/output-schema.md` for its full shape; `render-txt.py`,
`ocr-verify`, and `ocr-validate` read only that schema, never a backend's native output.

Each reader's own raw output also persists, but its location depends on which backend produced it
— there is no single normalized path for it (an earlier design sketch assumed one; the real layout
diverged once each backend's actual output turned out to be several files, not one):

- `remote` tier: `$WORK/remote-out/<stem>/` (rsynced down from `holos`, plus `manifest.tsv`
  mapping each reader name to its file).
- `local` tier: `$WORK/mineru/<stem>/<method>/<stem>_middle.json` (+ siblings).
- `surya-only`: no reader output — the tier ran with none.
- `--azure`: `$WORK/azure/<stem>.layout.json` (raw `analyzeResult`).

## Backend tiers

| `OCR_BACKEND` | Geometry | Readers | `m` | When |
|---|---|---|---|---|
| `remote` *(default, via `auto`)* | Surya on `holos` | olmOCR 2 + Chandra 2 | 2 | box probes clean |
| `local` | Surya | MinerU 2.5 | 1 | no box; laptop; single doc |
| `surya-only` | Surya | none | 0 | degenerate — no MinerU installed |
| `--azure` | *(additive at any tier — see below)* | Document Intelligence | +1 on pages it analyzed | offered for table pages; costs money |

`surya-only` is a genuine degradation, not a peer tier: with `m = 0` there is no agreement signal
at all, and every contested value falls back to Surya confidence plus a rendered crop
(`bayou:ocr-verify`). Don't treat it as equivalent to `remote`/`local` when reading its output.

`OCR_BACKEND=auto` (the default) probes `holos` (`lib/probe.sh`) and falls back to `local` with a
one-line stderr notice if the probe fails. It never switches mid-batch; the chosen backend is
stamped per-file in `canonical["backend"]`, so a mixed batch stays legible. Force a tier with
either the `OCR_BACKEND` env var or the equivalent `--backend <name>` CLI flag (`remote` / `local`
/ `surya-only` / `auto`) — an explicit `--backend` wins over any `OCR_BACKEND` already exported.

## Running it

**Install `rapidfuzz` locally first** (`python3 -m pip install --user rapidfuzz`, adding
`--break-system-packages` on a PEP 668-managed Python like Homebrew's): `merge-canonical.py`'s
line-matching runs on every backend, including `remote`, and falls back to stdlib `difflib` if
`rapidfuzz` is missing. That fallback isn't a minor slowdown -- on a real ~2000-page document it
turned a few-minutes merge into a multi-hour stall (reproduced: 2+ hours, still not done). Confirm
it's importable before a large batch: `python3 -c "import rapidfuzz"`.

Always launch in the **background** (`run_in_background: true` on the Bash tool) — a real batch
takes hours and must not block the conversation:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/ocr-pipeline.sh <INPUT_DIR_OR_PDF> <OUTPUT_TXT_DIR> [WORK_DIR]
```

- `INPUT_DIR_OR_PDF` — a directory of PDFs (e.g. a `bayou:ldeq-edms-download --out` folder) or a
  single PDF file.
- `OUTPUT_TXT_DIR` — where the final `.txt` files land, one per input PDF (same stem).
- `WORK_DIR` (optional, default `./.ocr-work`) — everything under "What this produces" above.

Run the script directly under `run_in_background: true`. **Don't wrap it in `nohup … &`
inside that call.** The Bash call then returns as soon as the wrapper backgrounds itself, and the
pipeline was observed dying after its first file.

Attach a `Monitor` to the background job's output, watching for `[OCR] done|FAIL|ALL DONE`,
`[tables]` and `Traceback|Error` — each is one stdout line, so Monitor surfaces progress and
crashes without polling. Each done stem is followed by a `[tables]` line (see "Tables" below);
collect those and act on them once the batch finishes, not one at a time.

**Stopping a run.** `ocr-pipeline.sh` `exec`s into `lib/backend-local.sh` (or `lib/backend-remote.sh`), so
after startup the running process has the backend's name, not `ocr-pipeline.sh`. Send
TERM to whichever is running:

```bash
pkill -TERM -f 'document-ocr/(ocr-pipeline|lib/backend-(local|remote))\.sh'
```

Both scripts trap TERM, INT and HUP and kill their own `conda run` → surya/mineru children
before exiting. They print `[OCR] stopped by signal` to stderr. Afterwards, confirm nothing
is left (`pgrep -fl 'surya_ocr|mineru'`). Never use `kill -9` on the batch script: the
trap can't run, and its children are reparented to PID 1 and keep OCRing (and slowing the
machine) until they finish. A remote-tier job on `holos` is detached on purpose so that it
can resume, so stopping the local script doesn't stop it.

**Fallback cost.** With `OCR_BACKEND=auto`, an unreachable `holos` costs only one stderr line
(`remote box not available -- falling back to OCR_BACKEND=local`). The run then switches to
laptop speed. On Apple Silicon, Surya + MinerU took **several minutes per 4-page PDF**, so a
batch of 18 short PDFs takes over an hour. Before you launch a batch with `auto` while the box
might be down, say what the fallback will cost, or pick a tier explicitly.

**Quick path for clean typed tables: tesseract.** Some lookups don't need per-line evidence,
such as finding one applicant or permit number in an image-only status report. For those,
`tesseract` is fine, and it takes seconds per page:

```bash
pdftoppm -r 170 -png in.pdf page && for p in page-*.png; do tesseract "$p" "${p%.png}" --psm 6; done
```

On the two OCM coastal-use status reports where it was compared with Surya, it found the same
entries. `--psm 6` keeps each table row on one line. Surya's output puts every table cell on
its own line, which makes it hard to `rg` a row. This path produces no `canonical.json`, so its
output is not an input to `permit-analysis` citations. When the table values themselves matter
(a number you will cite), use the Azure table path below instead.

**Resumable by design**: local skips a stem when `.txt` is non-empty *and* `canonical/<stem>.json`
parses (not just `.txt` existing — a half-finished merge must not look done). If a run is
interrupted, re-running the exact same command picks up only the remaining files, and on the
`remote` tier, re-attaches to a still-running remote job rather than restarting it. Per-file
failures (`[OCR] FAIL <stem>: <stage>`) don't stop the batch — one bad PDF doesn't waste hours of
otherwise-good work.

**Diagnosing a per-file `FAIL` without reading the whole log.** Each reader's log
(`$WORK/logs/<stem>.<reader>.log` — `mineru`, `olmocr`, `chandra`) is dominated by tqdm-style
progress-bar spam: hundreds of lines like `OCR-rec Predict: 80%|████ | ...` per stage, none of
which carry diagnostic value once that stage has moved on. The actual error is always near the
end, right before the process exits. Read the last ~15-20 lines (`tail -20 <log>`) or grep directly
for the failure (`grep -B2 -A10 -iE "error|traceback|exception" <log>`) instead of reading the
whole file — a full read burns far more context for the same information. A per-file `FAIL` also
doesn't require touching the rest of the batch: that stem's own log is self-contained, and if a
retry looks warranted (an environment-dependent crash — memory pressure, a network timeout during
a model download — rather than something specific to that document), point a fresh
`INPUT_DIR_OR_PDF` at just that one PDF with the same `WORK_DIR`; the resume-skip logic above means
already-succeeded stems won't be redone.

**Watching the Monitor output efficiently.** The `[OCR] done|FAIL|ALL DONE` stream is one line per
completed/failed file plus a final summary — there's no need to produce a user-facing reply to
every intermediate per-file line in a large batch. Reserve an actual response for the batch
finishing, a failure that needs a decision (skip vs. retry vs. accept degraded), or a pattern
worth flagging (e.g. multiple stems failing the same way) — not a running commentary on each tick.

**Remote (`holos`) probe failures.** `OCR_BACKEND=remote` (or `auto` falling through to it) fails
with one of two distinguishable messages: the OCR box is VPN-gated (hostname doesn't resolve — the
message tells you to connect the VPN, and separately warns that while that VPN is up,
`huggingface.co` is unreachable, which only matters for `local`/`surya-only`), or the box is
reachable but not provisioned (missing tools/weights/server, named explicitly). Neither is a
reason to guess — follow the message.

## `--rerender` (regenerate `.txt` without re-OCRing)

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/ocr-pipeline.sh <INPUT_DIR_OR_PDF> <OUTPUT_TXT_DIR> [WORK_DIR] --rerender
```

Regenerates `<stem>.txt` from an existing `results.json` (+ `canonical.json` if a merge already
ran), bypassing the "skip if `.txt` is non-empty" check. Seconds per document — no GPU, no
network, no backend selection (it only ever reads what's already on disk).

**Policy: in-flight campaigns stay frozen on their existing artifacts.** `.txt` line numbers move
whenever `.txt` is regenerated — the *text* is still there, just at a new line number — so
re-rendering a package invalidates every `<file>.txt:<line>` citation a `permit-analysis` run has
already gathered for it, and that citation set has to be re-extracted (5a), not just re-verified.
`--rerender` is opt-in per package for exactly that reason: default to leaving an in-flight
package's `.txt` alone, and only re-render deliberately, knowing that cost.

## Reading the output

- **`$WORK/results/<stem>/results.json`** — the single-witness Surya artifact. Structure:
  `{stem: [{text_lines: [{polygon, confidence, text, bbox}], languages, image_bbox, page}, ...]}`.
  Still authoritative for "is this cell genuinely blank" — see `references/output-schema.md`.
  **This schema is specific to `surya-ocr==0.6.13`** — Surya 2 (`0.22.1`+) is a different
  architecture (spawns its own vLLM/Docker backend, different CLI, different output shape) and
  will not produce this structure; `references/remote-setup.md` explains why the remote tier pins
  the older version deliberately rather than tracking latest.
- **`$WORK/canonical/<stem>.json`** — the merged evidence record `ocr-verify`/`ocr-validate` read.
  Per-line: text, `bbox`/`bbox_norm`, `confidence`, `agreement {m, n, agreed, dissent, absent}`,
  `cell`, `selection_mark`. Full schema in `references/output-schema.md`.
- **`$OUT_TXT/<stem>.txt`** — what `permit-analysis` actually searches with `rg -in`. Carries an
  explicit `=== PAGE <n> ===` marker line at every page boundary, including pages Surya found no
  text on, so a page number is recovered by **scanning backward from any line to the nearest
  marker** — a plain text operation, no separate tool needed. (The old pipeline used `pdfgrep`
  against a positioned-text PDF for this; that PDF stage is gone — see
  `references/output-schema.md` for why.) Never treat a marker line itself as document content.

`.txt` is convenient for citations but is still a flattened derivative — it carries no confidence
or agreement data. **Don't resolve a contested value by re-reading `.txt` or by a blind visual
re-render of the source page** — that adds no independently verifiable signal a downstream reader
can cite. Use `bayou:ocr-verify` instead: it pulls every backend's opinion on a line (from
`canonical.json`), optionally tallies a value across the whole package, and crops the source region
at high DPI only when the evidence doesn't already agree. Use `bayou:ocr-validate` to find
candidates worth checking in the first place (unit-conversion mismatches, subtotal errors,
implausible values) before spending a verification pass on them one at a time.

## Tables → Azure Document Intelligence (`--azure`, additive at any tier, costs money)

Surya reads a table one cell per line and orders lines by position, so on a table page a value
can land beside the wrong row label in `<stem>.txt`. A column of `0.00` totals interleaved one row
off from their labels is the typical failure. Document Intelligence `prebuilt-layout` returns
real rows and columns. It is also the only real checkbox source in this stack
(`selectionMarks[].state` + confidence — Surya collapses every checkbox glyph to the same bracket
by construction) and the only per-word confidence source. It's additive: run it **after** the base
OCR pass, never instead of it.

**This skill always uses direct REST (`azure-layout.py`), never an MCP connector**, even if one is
present. A third-party Azure MCP server (`asklokesh/azure-mcp-server` was evaluated) means
inheriting someone else's output schema — the one thing this pipeline controls tightly for the
merge — and its tool surface can't be verified up front. This is a deliberate exception to the
house pattern elsewhere in this plugin (e.g. `kit-dissemination`, which does prefer its connector
when available): here, schema control wins over connector convenience.

### Which pages: the `[tables]` lines

Every tier runs `detect-table-pages.py` on each stem as it finishes and prints:

```
[tables] <stem>: <k>/<n> pages look tabular (<spec>) -> azure: whole|pages|none
```

It also writes `$WORK/tables/<stem>.json` (per-page features, `selected_pages`, `pages_spec`,
`recommendation`). The detector reads only Surya's `results.json` geometry: visual rows of
side-by-side narrow cells whose left edges line up into columns, plus short-table header rows.
It makes no model call, so it costs nothing and returns the same answer every run. Measured against
Azure's own table detection on ~400 pages of scanned regulatory filings, it found 94% of table
pages at 92% precision. Most of its "false positives" are aligned label/value forms, which Azure
also reads better. The thresholds were tuned on those same pages, so expect somewhat lower numbers
on very different layouts. Most misses are continuation pages that hold the last few rows of a
table from the page before. `--neighbors` adds the pages on either side of each hit to catch
them, but on a table-heavy document that selects nearly every page.

- `pages`: fewer than half the pages look tabular, so send just those (`--pages <spec>`).
- `whole`: half or more do, so send the whole document. That is simpler, and the extra pages
  cost little.
- `none`: nothing tabular was found. Don't offer Azure unless the user asks, or the document has
  checkboxes that matter.

For a work dir OCRed before this check existed, run it standalone:
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/detect-table-pages.py <WORK_DIR> [--stem <stem> ...]`.

**Offer Azure whenever a batch has `pages` or `whole` stems.** Don't wait to be asked. Surya's
reading of a table is the part of its output most likely to be wrong, and the fix costs about a
cent a page. Make the offer once, at the end of the batch, covering every flagged stem. Default
to the detector's recommendation for each stem. If the user has already said in this conversation
to run Azure on anything that looks like a table, that is the confirmation. Still state the page
count and cost as you start.

### Cost and confirmation

**Cost: ~$10/1000 pages (~$2 for a 200-page permit).** This is a per-run sanity prompt, not a hard
ceiling — do the following for the whole batch you're about to submit, once, not per document:

**Hard caps — not a pricing concern, a submission concern:** `prebuilt-layout` refuses any request
over **500 MB or 2,000 pages**, whichever hits first. The 500 MB cap applies to the uploaded file
even with `--pages`, since the whole PDF is still sent. A file over 500 MB, or a run that needs
more than 2,000 pages analyzed, needs the extract route in "Submitting a document over the caps"
below. Check both the file size and the page count before estimating cost.

1. For each target stem, take the page count from `$WORK/tables/<stem>.json`: `len(selected_pages)`
   for a page-subset run, `n_pages` for a whole-document run.
2. Sum across the batch, multiply by ~$0.01/page, and show the per-document breakdown and total,
   both for table pages only and for whole documents.
3. **Unless the user has already approved Azure for table pages**, ask with `AskUserQuestion`,
   once, before submitting anything: table pages only (recommended, with its page count and cost),
   whole documents (with its count and cost), or skip. This is the `pacer-case-search` house
   pattern. Nothing is submitted until it is confirmed.
4. `Read` `~/.claude/bayou-credentials.md` for `AZURE_DOCINTEL_ENDPOINT` / `AZURE_DOCINTEL_KEY`
   (unless already exported). Missing either: fail clearly, point at
   `bayou-credentials.example.md`'s `## Azure Document Intelligence` section — do not prompt the
   user for key material through chat. Load them into the environment of the command that needs
   them without echoing the key.

### Submitting

For each confirmed stem, locate its source PDF (same ad hoc search `bayou:ocr-verify` uses — near
`WORK_DIR` and the output `.txt` directory, since `$WORK` retains no source-PDF pointer of its own
— zero or multiple matches means stop and ask, not guess):

```bash
mkdir -p "$WORK/azure"
# whole document
python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/azure-layout.py <source.pdf> "$WORK/azure/<stem>.layout.json"
# table pages only -- <spec> is pages_spec from $WORK/tables/<stem>.json, e.g. 3,7-9,14
python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/azure-layout.py <source.pdf> "$WORK/azure/<stem>.layout.json" --pages <spec>
```

`--pages` is the service's own `pages` parameter. Only those pages are analyzed and billed, and
the result keeps the **source document's page numbers** (verified: `--pages 9,12` returns pages
`[9, 12]`). So no extract and no renumbering are needed, and the result merges directly.

**`azure-layout.py` bills Azure at submission**, not at poll completion. It persists the
`Operation-Location` it gets back from that submission to `<out>.layout.json.operation` before it
starts polling, and on startup checks for that file first — so a timeout (default 3600s, `--timeout`
to raise it further) or an interrupted run **resumes and retrieves the already-paid-for result
instead of re-submitting**. Re-running the same command after a timeout is therefore safe and is
the right move, not a re-bill. The `.operation` file also records the `--pages` spec. Resuming
with a different spec is refused, because it would return the old run's pages. To analyze more
pages of a stem that already has a result, either write to a new output path or delete the
`.operation` file, which means a fresh, billed submission.

### Submitting a document over the caps

Under 500 MB, `--pages` handles any page subset without an extract. This route is only for a file
over 500 MB, which can't be uploaded at all, or for a run that needs more than 2,000 pages
analyzed. The target pages are extracted into a smaller PDF, submitted, then **renumbered** back
to source page numbers before rendering or merging, because Azure numbers pages 1..N in whatever
PDF it was actually handed. `selected_pages` from `$WORK/tables/<stem>.json` is a ready-made page
map:

1. Pick the target pages and extract them: `qpdf --empty --pages <source.pdf> <ranges> --
   <extract.pdf>`, where `<ranges>` is comma-separated and each piece is a single page or a
   contiguous run — e.g. `204,206-208,214` for the non-contiguous case (this is the normal case;
   the pages a PSD/Title V comment needs are rarely contiguous). Verified working syntax
   (`--empty` as the primary input, `<source.pdf>` only inside `--pages`, `--` before the single
   output path — `qpdf --pages <source.pdf> <ranges> -- <extract.pdf> <extract.pdf>` **fails**,
   it is not a valid invocation). Save the page map — the ordered list of original page numbers
   the extract covers, in the exact order the `<ranges>` argument produced them, e.g.
   `[204, 206, 207, 208, 214]` for the range above — as a small JSON file; `renumber-azure-pages.py`
   needs it and there's no other record of the correspondence once the extract exists.
2. Submit the extract: `azure-layout.py <extract.pdf> <out>.layout.json`.
3. Renumber the result back to source page numbers before it ever reaches `merge-canonical.py`:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/renumber-azure-pages.py \
     <out>.layout.json <page-map.json> <out>.renumbered.layout.json
   ```
   This writes a **new** file — it never edits in place — and refuses outright if the page-map
   length doesn't match the layout's page count, rather than guess at the correspondence. Use
   `<out>.renumbered.layout.json` (not the raw `<out>.layout.json`) for `azure-to-text.py` and as
   the `--azure` argument in the merge below. Skipping the renumber silently attaches the
   extract's page-1-relative tables and selection marks to the wrong pages.

### Readable tables: `<stem>.azure.txt`

Always render the result to text. This is the step that makes the tables readable:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/azure-to-text.py "$WORK/azure/<stem>.layout.json" "$OUT_TXT/<stem>.azure.txt"
```

Each table comes out as `[table N]` … `[/table]` with one `| a | b | c |` line per row, so a value
stays on the same line as its row label and `rg` finds whole rows. Merged cells are filled with
`^` (continues the cell above) and `<` (continues the cell to the left), so a blank always means an
empty cell. Prose comes out in Azure's paragraph order. The `=== PAGE n ===` markers are source
page numbers, matching `<stem>.txt`. A page-subset run only has markers for the pages it covered.

`<stem>.azure.txt` is a **second, independent reading** (Azure's OCR, not Surya's), with its own
line numbers. Cite it as its own file. Don't copy its lines into `<stem>.txt`. When the two
readings disagree on a value, that value is contested: resolve it with `bayou:ocr-verify` against
the page image, not by preferring one file.

### Merging into canonical.json (for `ocr-verify` / `ocr-validate`)

This step is optional. It adds Azure's cells, checkboxes and vote to the per-line evidence that
`bayou:ocr-verify` reads. It does not change `<stem>.txt`, because Azure never contributes text or
reading order to the merge. The `surya-only` tier writes no `canonical/<stem>.json`, so for those
stems the merge below creates it (`--backend surya-only`, no `--reader` arguments).

This is the step most likely to go wrong, because `merge-canonical.py` **rebuilds canonical from scratch on every
invocation — it never reads an existing canonical.json as a base.** Omitting the original
`--reader` arguments here doesn't fail loudly; it silently produces a canonical file with
`agreement.m` dropped back to 0, every `agreed`/`dissent` array empty, and `ocr-verify` treating a
two-reader document as if it were `surya-only`.

1. Before re-merging, `Read` the **existing** `$WORK/canonical/<stem>.json` and note its
   `"backend"` and `"readers"` fields — these name what must reappear in the re-merge. No
   canonical file means a `surya-only` stem: backend `surya-only`, no readers, and step 3 has
   nothing to save.
2. Reconstruct each reader's raw-artifact path (mirrors the lookup already done internally by
   `lib/backend-remote.sh`'s `land_stem()` and `lib/backend-local.sh` — this is now a third copy of
   that logic, so if those scripts' output layout ever changes, this recipe has to change with
   them):
   - `backend == remote`: for each name in `readers`, `awk -F'\t' '$1=="<name>"{print $2}'
     $WORK/remote-out/<stem>/manifest.tsv` gives a path relative to that directory.
   - `backend == local`: `find $WORK/mineru/<stem> -name "<stem>_middle.json"` → `--reader
     mineru=<path>`.
   - `backend == surya-only`: no `--reader` args — Azure becomes the only additional witness.
   - If the reconstructed reader-name set doesn't match `readers` from step 1 exactly (a raw
     artifact went missing or moved since the base run), **stop** — don't re-merge with a partial
     reader set silently.
3. **Before overwriting anything**, save what re-merging is about to destroy — `merge-canonical.py`
   writes `$WORK/canonical/<stem>.json` in place, so the pre-azure version has to be captured first
   or step 4's comparison has nothing left to compare against:
   ```bash
   cp "$WORK/canonical/<stem>.json" "$WORK/canonical/<stem>.json.pre-azure"
   ```
4. ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/merge-canonical.py \
     "$WORK/results/<stem>/results.json" "$WORK/canonical/<stem>.json" \
     --stem <stem> --backend <original-backend> \
     --reader <name>=<path> [--reader <name>=<path> ...] \
     --azure "$WORK/azure/<stem>.layout.json"
   ```
5. **Verify the re-merge actually stayed additive** before trusting it, then render to a temp path
   rather than `$OUT_TXT` directly — for the same reason as step 3, `render-txt.py` also writes in
   place, so the live `.txt` has to survive long enough to compare against:
   - On a page Azure analyzed (listed in the new top-level `azure_pages`), `agreement.m` on a
     sampled non-trivial line must be **exactly 1 higher** than in `<stem>.json.pre-azure` (or than
     0, for a surya-only stem). On any other page it must be unchanged. Azure votes only on pages it
     saw, so after a `--pages` run most pages keep their old `m`. The top-level `readers` field
     must also stay **unchanged**. Azure is tracked through `azure: true` and `azure_pages`, not
     added to `readers`.
   - ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/render-txt.py \
       "$WORK/results/<stem>/results.json" <scratch>/<stem>.post-azure.txt "$WORK/canonical/<stem>.json"
     cmp "$OUT_TXT/<stem>.txt" <scratch>/<stem>.post-azure.txt
     ```
     must report no difference — Azure only ever contributes `cell`/`selection_mark`/`tables`/
     `selection_marks`, never text or reading order, so nothing about the rendered text should
     change. (`merge-canonical.py` keeps Azure out of its reading-order priority list for this
     reason: on a surya-only stem it would otherwise be the only reader and reorder every page.)
     If `cmp` reports a difference, the readers were dropped or reading order shifted;
     **stop and investigate rather than copying `<scratch>/<stem>.post-azure.txt` over the live `.txt`.**
   - Only once both checks pass: copy `<scratch>/<stem>.post-azure.txt` over `$OUT_TXT/<stem>.txt` (a
     no-op given the `cmp` above, but keeps `canonical.json` and `.txt` from ever silently
     diverging) and remove `<stem>.json.pre-azure` and the temp `.txt`.

**Checkbox caveat**: practitioners report Azure/Textract checkbox confidence often reads below 75%
even when the surrounding cell reads above 90%, and both struggle with non-standard marks. A
checkbox gets the same escalation treatment as a contested number — `bayou:ocr-verify` narrows
candidates with Azure's `selection_mark`, it doesn't settle them outright.

## When it finishes

On `[OCR] ALL DONE (<n> files) -> <OUT_TXT>`, list the produced `.txt` files. If the summary line
reports any degraded stems, or the run's console output has `[coverage]` warnings, treat those
documents as suspect before analysis starts — see below. If any `[tables]` line said `pages` or
`whole`, offer Azure for those stems now, per "Tables → Azure Document Intelligence" above, before
anyone quotes a number from a table page of `<stem>.txt`. The natural next steps:
`/bayou:ocr-validate <work-dir>` to flag arithmetic/plausibility candidates cheaply, then
`/bayou:permit-analysis <file1.txt> [file2.txt ...] [--project-info <path>]` — using
`bayou:ocr-verify` during its verify pass whenever a citation needs resolving with evidence rather
than a guess.

**Reader coverage.** `check-reader-coverage.py <work-dir> [--stem <stem>...]` runs automatically
against each stem as it lands during a `remote`-tier run, but is also safe to run standalone
against any already-merged `canonical/*.json` — including documents merged before this check
existed. It catches something `agreement.m` alone cannot: a reader that ran, didn't crash, and
returned structurally-valid emptiness (e.g. a well-formed table with every row silently elided). It
combines two signals of different strength — a grep of each reader's raw output for self-announced
omission placeholders (`<!-- Table rows follow -->` and similar), which is close to
zero-false-positive: treat a hit as confirmed content loss. And a page where Surya found plenty of
lines but a reader's `absent` rate on that page is very high, which usually means the reader didn't
read the page but has a known false-positive mode on dense tables: a reader that emits one row of
HTML per table row collapses many of Surya's per-cell lines into one block, which fuzzy-matches
poorly even though the values are all present in the reader's raw output and in the rendered `.txt`
(confirmed on this fixture — doc 01 pages 50/64/68 flag at 90%+ absent with nothing actually
missing). Treat a coverage-only flag (no matching elision hit on the same page) as "worth a look,"
not "confirmed broken" — check the reader's raw output for that page before concluding content was
dropped. Findings print as `[coverage] <stem>: ...` lines and are also written to
`canonical/<stem>.coverage.json` for later inspection; it's purely informational and never modifies
`canonical.json` itself.

$ARGUMENTS
