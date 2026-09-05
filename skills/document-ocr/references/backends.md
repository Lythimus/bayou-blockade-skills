# Backend output formats

`merge-canonical.py` contains one adapter function per backend (`adapt_olmocr`, `adapt_chandra`,
`adapt_mineru`, `adapt_azure`). This doc records the researched invocation and output shape each
adapter targets, and which fields each backend can and cannot contribute to the canonical schema
(`references/output-schema.md`).

| Backend | Output | Per-line bbox? | Confidence? |
|---|---|---|---|
| olmOCR 2 | Dolma JSONL + markdown; page slices via `attributes.pdf_page_numbers` | **No** | **No** |
| Chandra 2 | `.md` / `.html` / `_metadata.json` (block-level `bbox`/`label`/`content`) | Block only | **No** |
| MinerU 2.5 | `_middle.json` (block→line→span bboxes), `_content_list.json`, `_model.json`, `.md` | **Yes** | `score` is **layout detection, not transcription** |
| Azure `prebuilt-layout` | `analyzeResult`: `pages[].words[]`, `pages[].selectionMarks[]`, `tables[].cells[]` | **Yes** | **Yes, per word** |

## olmOCR 2

Apache-2.0. Best-in-class reading order among the readers in this stack, with built-in
auto-rotation — directly relevant to the rotated/landscape engineering sheets these permits
contain.

Raw output is a Dolma-format JSONL file: one record per source document, `{"text": "<full doc
markdown>", "attributes": {"pdf_page_numbers": [[start_char, end_char, page_num], ...]}, ...}`.
`adapt_olmocr` slices `text` by each `(start, end)` span to recover a page's text.

**Contributes to canonical:** `agreement` votes and `reader_pages` only. **No geometry, no
confidence, ever** — olmOCR never populates `bbox`, `confidence`, or `layout_score` on any line.

**Unverified:** whether `pdf_page_numbers` is 0-based or 1-based. `adapt_olmocr` assumes 1-based
(matching Surya/Azure) pending a real run against holos — the highest-risk silent off-by-one in
the merge (see output-schema.md's page-index hazard). Confirm with the first real Phase 3 run: a
known page-N span should recover text that is actually on source page N.

## Chandra 2

Modified OpenRAIL-M — free for research/personal use, restricted from competing with Datalab's
commercial API. Fine for this use (a personal environmental-justice research pipeline), noted here
because it's a real license constraint, unlike the other three backends. Best table and old-scan
scores among the readers.

Raw output: `.md`, `.html`, and `_metadata.json` (a list of blocks: `{page, bbox, label,
content}`). `adapt_chandra` reads `_metadata.json`.

**Contributes to canonical:** `agreement` votes, optionally scoped to the Chandra block whose bbox
contains a Surya line's centroid. **No per-line geometry, no confidence** — Chandra cannot answer
"is this cell empty," so it never gets its own `lines[]` entries, only votes on Surya's.

**Unverified:** DeepWiki documents per-block `bbox`/`label`/`content` in `_metadata.json`; a closed
GitHub issue claims the CLI exposes no layout information at all. If a real run's
`_metadata.json` lacks `bbox`, block-scoped matching degrades cleanly to page-global matching —
this is an optional refinement, not a hard dependency. Confirm with one real Phase 3 run.

## MinerU 2.5

**Confirmed against a real local run** (2026-08-23, `mineru` 3.4.5, page 3 of `15308230.pdf`,
`-b pipeline`, Apple Silicon MPS, no dedicated GPU):

- **Backend enum**, from a real `mineru --help` on this machine — neither published variant the
  plan flagged as disagreeing was exactly right:
  `pipeline | vlm-engine | hybrid-engine | vlm-http-client | hybrid-http-client` (CLI default:
  `hybrid-engine`). `lib/backend-local.sh` defaults `MINERU_BACKEND` to `pipeline` instead — the
  `vlm-*`/`hybrid-*` engines are VLM-backed and unconfirmed on laptop-class hardware, whereas
  `pipeline` completed end-to-end on this machine in under a minute (once weights were cached)
  and produced clean, correctly-ordered text (verified against `page3.md`).
- **Output directory layout**: `<OUT>/<stem>/<method>/<stem>_middle.json` (+
  `_content_list.json`, `_content_list_v2.json`, `_model.json`, `.md`, `_layout.pdf`,
  `_origin.pdf`, `_span.pdf`). `<method>` comes from `-m/--method` (default `auto`), **not** from
  `-b/--backend** — the two are independent flags. `lib/backend-local.sh` globs for
  `${stem}_middle.json` under `<OUT>/<stem>/` rather than hardcoding `auto`, since `-m` is never
  passed explicitly.
- **`_middle.json` shape confirmed**: `{"pdf_info": [...], "_backend": "pipeline", "_version_name":
  "3.4.5"}`; each `pdf_info[]` entry has `page_idx` (0-based, confirmed against a single-page
  input == 0), `page_size` (`[width_px, height_px]` — `[606, 806]` on the test page),
  `para_blocks[]`, each with `bbox`, `score`, `type`, and `lines[].spans[].content`/`.score`. This
  matches `adapt_mineru`'s existing implementation exactly — **no adapter code changes were
  needed**, only confirmation.
- **Coordinate space**: `_middle.json` bboxes are raw pixels in MinerU's own internal render
  resolution (`page_size` on the same page entry), which is **not** the same resolution as
  Surya's own page pixel space. Doesn't matter for the current merge algorithm — `adapt_mineru`
  only extracts `(content, score)` text units for fuzzy matching, never MinerU's own bbox — but
  matters the moment anything ever wants to plot a MinerU box directly: always read `page_size`
  fresh, never assume it matches Surya's.
- **Weight download**: first run fetches from `modelscope.cn` (China-region HF mirror MinerU
  falls back to) via `models_download_utils.py`'s `auto_download_and_get_model_root_path`, not
  `huggingface_hub` directly. **Hits the identical VPN TLS-interception failure already
  documented for Surya + huggingface.co** (self-signed cert on the box), just against a different
  host — confirmed live on this machine: failed with GlobalProtect connected, succeeded
  immediately after disconnecting it. No offline-retry escape hatch exists for this one (unlike
  Surya's `HF_HUB_OFFLINE`) because it's a first-time download, not a revalidation of an existing
  cache — so **the first `OCR_BACKEND=local` run on a fresh machine needs the VPN down** if that
  VPN is the same TLS-intercepting one gating `holos`. Once weights are cached, subsequent runs
  don't re-trigger this.

Raw output: `_middle.json` (`pdf_info[]`, one entry per page — `page_idx` 0-based — containing
`para_blocks[].lines[].spans[]`, each span carrying `content` and `score`), plus
`_content_list.json`, `_model.json`, and a flattened `.md`. `adapt_mineru` reads `_middle.json`.

**Contributes to canonical:** `agreement` votes, and — uniquely among the readers — real per-line
geometry via `layout_score` (kept **strictly separate from `confidence`**: it is a
layout/detection-quality score, not a transcription confidence, and must never be read as one).

## Azure Document Intelligence `prebuilt-layout` (`--azure`, opt-in)

`api-version=2024-11-30` (v4.0 GA) — pinned; do not drift to a newer version without re-checking
the response shape. Raw output: `analyzeResult.pages[]` (1-based `pageNumber`, `unit` = `"inch"`
for PDF input or `"pixel"` for image input — read at runtime), each page carrying `words[]`
(`content`/`polygon`/`confidence`/`span`) and `selectionMarks[]` (`state`/`confidence`); top-level
`tables[].cells[]` (`rowIndex`/`columnIndex`/`content`).

**Confirmed against a real live run** (2026-08-23, resource `bayou-docintel`, `eastus`, S0 tier,
a real 2-page PDF slice submitted via `azure-layout.py`): `POST …prebuilt-layout:analyze` returns
202 with an `Operation-Location` header; polling it returns `{status, analyzeResult}`, `status`
transitions straight to `"succeeded"` on a document this small (no `"running"` state observed, but
`azure-layout.py`'s poll loop handles it either way). `analyzeResult.pages[]` confirmed exactly as
documented — `pageNumber` 1-based, `unit: "inch"` on this PDF input, real per-word `confidence`
(e.g. `0.995`), `polygon` as 8 floats (4 corners) in that page's `unit`. `tables[].cells[]`
confirmed with 0-based `rowIndex`/`columnIndex` and plain-text `content`; 4 tables detected across
the 2 test pages. `merge-canonical.py`'s existing `adapt_azure()` consumed the real response file
unmodified and produced correctly-shaped `word_pages`/`tables` — **no adapter code changes
needed**, only confirmation (same outcome as MinerU's Phase 4 verification). **Not exercised by
this run:** the test pages had no checkboxes, so `selectionMarks[]` was empty on both — the field
shape is unverified against a real mark, only against the public API docs `adapt_azure()` was
already written against.

**Contributes to canonical:** `agreement` votes from `words[]`; `selection_marks` copied
per-page (normalized to `bbox_norm` using the page's own `unit`/`width`/`height`); `tables`
copied from `tables[].cells[]`.

**Azure is the only backend in this stack with a real selection-mark concept.** Surya collapses
every checkbox glyph to the same bracket regardless of which option is marked; without `--azure`,
`selection_marks` is always `[]` and any checkbox question must escalate to a rendered crop (see
`ocr-verify`).

**Caveat to carry into `ocr-verify`/`ocr-validate`:** practitioners report Azure/Textract checkbox
confidence often reads under 75% even when the surrounding cell reads over 90%, and both struggle
with non-standard marks. Checkboxes get the same escalation treatment as numbers — Azure narrows
candidates, it doesn't settle them on its own.

## What cannot be mapped, period

- **olmOCR emits no geometry and no confidence, ever.**
- **Chandra has no per-line geometry and no confidence.**
- **MinerU's `score` is layout detection, not transcription confidence.**
- **Surya has no selection-mark concept.**
- **Reader absence (`agreement.absent`) is never blankness evidence.** A cell missing from a
  reader's output means the reader linearized it away — only an empty Surya `lines[]` (no witness
  at all) is real evidence a cell is blank.

## Merge algorithm notes (implementation detail, `merge-canonical.py`)

Normalize NFKC → casefold → collapse whitespace → strip markdown/HTML table syntax before any
comparison. **Digit lookalikes (`1`/`l`/`I`, `7`/`1`, `0`/`O`) are deliberately never normalized**
— collapsing them would destroy exactly the repeated-glyph-miscount signal this whole merge exists
to catch (the `7777-00936-00` case, see `ocr-verify/references/failure-cases.md`).

Character-level fuzzy ratio alone is not sufficient to catch a dropped/repeated digit inside an
otherwise near-identical numeric string — `"777-00936-00"` and `"7777-00936-00"` differ by one
character in thirteen, which scores as near-total similarity under plain `rapidfuzz.partial_ratio`
or `difflib`. `merge-canonical.py`'s `digit_run_score_cap` addresses this directly: when a Surya
line and a candidate reader span both contain digits and their concatenated digit sequences
differ, the match score is capped below the "agree" threshold (≥ 90) regardless of overall
character similarity — this is what makes `agreement.n < agreement.m` actually fire on a
digit-run misread and not just on prose-level differences.

Matching windows reader units (words/lines/blocks depending on backend) longest-Surya-line-first,
growing a window of up to 12 consecutive unconsumed reader units and keeping the best-scoring
span; matched units are removed from the pool so one reader region can't satisfy multiple Surya
lines. ≥ 90 → agree, 75–89 → dissent (reader's exact span text recorded verbatim), < 75 → absent.

Short Surya lines (≤ 3 normalized characters — `1`, `X`, `N/A`) get `match_quality: "low"` on
their `agreement` object regardless of verdict: such spans fuzzy-match against almost anything, so
their agreement is non-evidence and a downstream consumer must not treat it as a real signal.

**Needs `rapidfuzz`; falls back to stdlib `difflib`** if it isn't installed (`pip install
rapidfuzz` in whichever environment runs `merge-canonical.py` — this script is not part of the
no-dependency remote path; only `render-txt.py` is stdlib-only). `difflib`'s ratio is a weaker
signal than `rapidfuzz.partial_ratio` (whole-string ratio vs. best-substring ratio) — prefer
installing `rapidfuzz` where possible.

**Reading order** (`reading_order`, see output-schema.md) is derived from whichever reader in
`READER_PRIORITY` (`olmocr` > `chandra` > `mineru` > `azure` — a documented judgment call, the
plan doesn't pin this) matched anything on a given page. `match_reader_to_page` now also returns
each match's position in that reader's own linear unit stream; `assign_reading_order` gives
matched lines that position directly and linearly interpolates unmatched lines between their
nearest matched neighbors in Surya's original line order, so a dropped/unmatched cell stays near
where Surya found it instead of jumping to the end. Verified against a real local-tier run
(Surya + MinerU) on `15308230.pdf` pages 3–7: `reading_order` populated on every line of a page
MinerU matched anything on, and produced at least one real reordering vs. the old pure-bbox-sort
output — on that particular page set the reorderings were mostly small, because MinerU and Surya
largely agreed on sequence for those specific pages; this reflects the input, not a no-op in the
code (confirmed by inspecting the assigned values directly, not just the rendered diff).

**`layout_score`** is populated the same pass: `adapt_mineru`'s per-span score is kept in a side
table index-aligned with the (score-stripped) text units matching uses, and copied onto any line
MinerU matched (agree or dissent) via the match's reported position — never inferred or
interpolated the way `reading_order` is, since a score only means something for a real match.
