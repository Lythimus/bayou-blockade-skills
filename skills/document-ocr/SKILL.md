---
name: document-ocr
description: OCR a folder (or single) scanned/image PDF into searchable .txt with per-line evidence (confidence, cross-reader agreement, table/checkbox structure), for any document source (LDEQ EDMS, USACE, FAA, or elsewhere). Use between downloading raw permit PDFs and running /bayou:permit-analysis, which requires machine-readable text.
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
| `--azure` | *(additive at any tier — see below)* | Document Intelligence | +1 | opt-in, costs money |

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

Attach a `Monitor` to the background job's output, watching for `[OCR] done|FAIL|ALL DONE` and
`Traceback|Error` — each is one stdout line, so Monitor surfaces progress and crashes without
polling.

**Resumable by design**: local skips a stem when `.txt` is non-empty *and* `canonical/<stem>.json`
parses (not just `.txt` existing — a half-finished merge must not look done). If a run is
interrupted, re-running the exact same command picks up only the remaining files, and on the
`remote` tier, re-attaches to a still-running remote job rather than restarting it. Per-file
failures (`[OCR] FAIL <stem>: <stage>`) don't stop the batch — one bad PDF doesn't waste hours of
otherwise-good work.

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

## `--azure` (opt-in, additive at any tier, costs money)

Document Intelligence `prebuilt-layout` is the only real checkbox source in this stack
(`selectionMarks[].state` + confidence — Surya collapses every checkbox glyph to the same bracket
by construction) and the only per-word confidence source. It's additive: run it **after** the base
OCR pass above has already produced `canonical/<stem>.json` for the documents you want it on, not
instead of that pass.

**This skill always uses direct REST (`azure-layout.py`), never an MCP connector**, even if one is
present. A third-party Azure MCP server (`asklokesh/azure-mcp-server` was evaluated) means
inheriting someone else's output schema — the one thing this pipeline controls tightly for the
merge — and its tool surface can't be verified up front. This is a deliberate exception to the
house pattern elsewhere in this plugin (e.g. `kit-dissemination`, which does prefer its connector
when available): here, schema control wins over connector convenience.

**Cost: ~$10/1000 pages (~$2 for a 200-page permit).** This is a per-run sanity prompt, not a hard
ceiling — do the following for the whole batch you're about to submit, once, not per document:

**Hard caps — not a pricing concern, a submission concern:** `prebuilt-layout` refuses any request
over **500 MB or 2,000 pages**, whichever hits first. A document over either limit cannot be
submitted whole no matter what it costs — it must be extracted down to a qualifying page range
first (see "Submitting a document over the caps" below). Check both the PDF's file size and its
page count against these caps before estimating cost; a page count under 2,000 doesn't guarantee
the file is under 500 MB.

1. For each target stem, `Read` `$WORK/canonical/<stem>.json` and take `len(pages)` as its page
   count (or `grep -c '^=== PAGE ' <stem>.txt` if canonical is somehow absent — same number). Skip
   and say so for any stem with no canonical.json yet; `--azure` can't run ahead of the base pass.
2. Sum page counts across the batch; multiply by ~$0.01/page for the estimate. Show the per-document
   breakdown and the total.
3. **`AskUserQuestion`, once, before submitting anything** — page count and estimated cost for the
   whole batch — the `pacer-case-search` house pattern. Nothing is submitted until this confirms.
4. `Read` `~/.claude/bayou-credentials.md` for `AZURE_DOCINTEL_ENDPOINT` / `AZURE_DOCINTEL_KEY`
   (unless already exported). Missing either: fail clearly, point at
   `bayou-credentials.example.md`'s `## Azure Document Intelligence` section — do not prompt the
   user for key material through chat.

For each confirmed stem, locate its source PDF (same ad hoc search `bayou:ocr-verify` uses — near
`WORK_DIR` and the output `.txt` directory, since `$WORK` retains no source-PDF pointer of its own
— zero or multiple matches means stop and ask, not guess):

```bash
mkdir -p "$WORK/azure"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/azure-layout.py <source.pdf> "$WORK/azure/<stem>.layout.json"
```

**`azure-layout.py` bills Azure at submission**, not at poll completion. It persists the
`Operation-Location` it gets back from that submission to `<out>.layout.json.operation` before it
starts polling, and on startup checks for that file first — so a timeout (default 3600s, `--timeout`
to raise it further) or an interrupted run **resumes and retrieves the already-paid-for result
instead of re-submitting**. Re-running the same command after a timeout is therefore safe and is
the right move, not a re-bill; only delete the `.operation` file if you specifically want a fresh
submission.

### Submitting a document over the caps

A document over 500 MB or 2,000 pages (see the hard caps above) can't go to `azure-layout.py`
directly — it must be extracted to a qualifying page range first, submitted, then **renumbered**
back to source page numbers before merging, because Azure numbers pages 1..N in whatever PDF it
was actually handed:

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
   `<out>.renumbered.layout.json` (not the raw `<out>.layout.json`) as the `--azure` argument in
   the re-merge step below; skipping the renumber attaches the extract's page-1-relative tables and
   selection marks to the wrong canonical pages silently.

Then **re-merge** `canonical/<stem>.json` with the Azure result folded in. This is the step most
likely to go wrong, because `merge-canonical.py` **rebuilds canonical from scratch on every
invocation — it never reads an existing canonical.json as a base.** Omitting the original
`--reader` arguments here doesn't fail loudly; it silently produces a canonical file with
`agreement.m` dropped back to 0, every `agreed`/`dissent` array empty, and `ocr-verify` treating a
two-reader document as if it were `surya-only`.

1. Before re-merging, `Read` the **existing** `$WORK/canonical/<stem>.json` and note its
   `"backend"` and `"readers"` fields — these name what must reappear in the re-merge.
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
   - `agreement.m` on the same sampled non-trivial line must have increased by **exactly 1**
     between `<stem>.json.pre-azure` and the new `<stem>.json` — Azure votes (`merge-canonical.py`
     appends it to the reader set used for the verdict), so `m` going e.g. 1 → 2 is the correct,
     expected outcome, not a sign anything broke. The top-level `readers` field itself should stay
     **unchanged** — Azure is tracked separately via the top-level `azure: true` flag, not added to
     `readers`.
   - ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/document-ocr/render-txt.py \
       "$WORK/results/<stem>/results.json" /tmp/<stem>.post-azure.txt "$WORK/canonical/<stem>.json"
     cmp "$OUT_TXT/<stem>.txt" /tmp/<stem>.post-azure.txt
     ```
     must report no difference — Azure only ever contributes `cell`/`selection_mark`/`tables`/
     `selection_marks`, never text or reading order, so nothing about the rendered text should
     change. If `cmp` reports a difference, the readers were dropped or reading order shifted;
     **stop and investigate rather than copying `/tmp/<stem>.post-azure.txt` over the live `.txt`.**
   - Only once both checks pass: copy `/tmp/<stem>.post-azure.txt` over `$OUT_TXT/<stem>.txt` (a
     no-op given the `cmp` above, but keeps `canonical.json` and `.txt` from ever silently
     diverging) and remove `<stem>.json.pre-azure` and the temp `.txt`.

**Checkbox caveat**: practitioners report Azure/Textract checkbox confidence often reads below 75%
even when the surrounding cell reads above 90%, and both struggle with non-standard marks. A
checkbox gets the same escalation treatment as a contested number — `bayou:ocr-verify` narrows
candidates with Azure's `selection_mark`, it doesn't settle them outright.

## When it finishes

On `[OCR] ALL DONE (<n> files) -> <OUT_TXT>`, list the produced `.txt` files. If the summary line
reports any degraded stems, or the run's console output has `[coverage]` warnings, treat those
documents as suspect before analysis starts — see below. The natural next steps:
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
