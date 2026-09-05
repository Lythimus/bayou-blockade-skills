# Canonical OCR schema

Every backend adapter (Surya, olmOCR 2, Chandra 2, MinerU 2.5, Azure Document Intelligence)
normalizes into **this** shape. `render-txt.py`, `ocr-verify`, and `ocr-validate` read only this
schema — never a backend's native output format. The one deliberate exception is `render-txt.py`'s
own fallback: if `$WORK/canonical/<stem>.json` does not exist (an older run, or a package that
hasn't gone through `merge-canonical.py` yet), it derives a degenerate zero-reader canonical
structure directly from `$WORK/results/<stem>/results.json` rather than failing. That fallback logic
lives only in `render-txt.py` and produces the same shape documented here — it is not a second
schema.

File: `$WORK/canonical/<stem>.json`

```json
{
  "stem": "example-permit",
  "backend": "remote",
  "readers": ["olmocr", "chandra"],
  "azure": false,
  "pages": [
    {
      "page": 7,
      "frame": { "width": 2550, "height": 3300, "unit": "px" },
      "selection_marks": [],
      "tables": [],
      "reader_pages": { "olmocr": 7, "chandra": 6, "azure": null },
      "lines": [
        {
          "line_id": "p7-l0",
          "text": "7777-00936-00",
          "backend": "surya",
          "surya_ref": 0,
          "bbox": [412, 88, 900, 130],
          "bbox_norm": [0.1616, 0.0267, 0.3529, 0.0394],
          "bbox_frame": "surya-px",
          "confidence": 0.971,
          "confidence_source": "surya",
          "layout_score": null,
          "reading_order": 4.0,
          "agreement": {
            "m": 2,
            "n": 2,
            "agreed": ["olmocr", "chandra"],
            "dissent": [],
            "absent": [],
            "method": "rapidfuzz.partial_ratio"
          },
          "cell": null,
          "selection_mark": null
        }
      ]
    }
  ]
}
```

## Top-level fields

- `stem` — file stem, matches `<stem>.txt` / `<stem>.pdf`.
- `backend` — `remote` | `local` | `surya-only`. Which tier produced this file (stamped per-file,
  not per-batch — a mixed batch can have different backends across its `canonical/*.json` files).
- `readers` — which reader(s) actually ran and contributed lines: `[]`, `["mineru"]`, or
  `["olmocr", "chandra"]`. `azure` is tracked separately since it's additive at any tier.
- `azure` — `true` if `$WORK/azure/<stem>.layout.json` exists and was merged in.
- `match_method` — `"rapidfuzz.partial_ratio"`, `"difflib"`, or `"none"` (no readers ran, so no
  fuzzy matching happened). Same value as the per-line `agreement.method` field, but hoisted to the
  top level so a mixed-`match_method` batch (e.g. one document merged before `rapidfuzz` was
  installed, the rest after) is visible from `canonical.json` alone rather than requiring a scan of
  every line. `difflib` is dramatically slower than `rapidfuzz` and merge-canonical.py prints a
  loud stderr warning when it falls back to it.
- `pages` — array, one entry per source page, **in page order, including pages with zero text
  lines**. A blank/separator page still gets a `pages[]` entry (empty `lines[]`) so the page-marker
  sequence in the rendered `.txt` never skips a page number. This is the defect the old
  `make-pdf-reportlab.py` had (page numbers shifted after any blank page) and the reason this schema
  requires every page to be represented explicitly rather than only pages with content.

## Per-page fields

- `page` — 1-based page number.
- `frame` — `{width, height, unit}` for **this page's Surya render** (`bbox` on every line in this
  page is in this frame, verbatim Surya pixels). `unit` is always `"px"` for the Surya-derived
  frame; see the coordinate-spaces hazard below for what other backends' native units look like
  before an adapter normalizes them into `bbox_norm`.
- `selection_marks` — `[]` unless Azure ran. Azure is the only backend in this stack with a real
  selection-mark concept; see Phase 2 notes below. Each entry: `{bbox_norm, state, confidence}`
  where `state` is `"selected"` or `"unselected"`.
- `tables` — `[]` unless a backend emitted table structure (Azure `tables[].cells[]`, or MinerU's
  content-list table blocks). Each entry: `{bbox_norm, rows, cols, cells: [{row, col, text,
  bbox_norm}]}`.
- `reader_pages` — maps each reader name to **that reader's own page index for this same source
  page**, after the adapter has converted it to 1-based (see the page-index-base hazard below). Lets
  a consumer go from a canonical page back to a specific reader's native output file/offset. `null`
  if that reader didn't cover this page (linearized it away, or didn't run).
- `lines` — array of per-line records, see below. Empty array is valid and means "no witness saw
  any text here" — real evidence of blankness (see `ZERO-VS-BLANK` in `ocr-validate`).

## Per-line fields

- `line_id` — stable id, `p<page>-l<index>`, unique within the file.
- `text` — the Surya-geometry line's text, verbatim (not reader text — see `backend`).
- `backend` — always `"surya"` today. Every line in `lines[]` originates from Surya's grid; readers
  never contribute their own line entries, only `agreement` votes on Surya's lines and `text` from
  a dissenting reader recorded inline (see `agreement.dissent` shape in Phase 2). This is what makes
  `results.json` a single witness for blankness even though multiple backends can vote.
- `surya_ref` — index into that page's `text_lines` array in the raw `results.json` block, so a
  consumer can jump back to the untouched source record.
- `bbox` — **verbatim Surya pixel bbox** `[x0, y0, x1, y1]`, this page's `frame`. `ocr-verify` crops
  from this field directly — never round-trip it through a normalization and back.
- `bbox_norm` — `[x0, y0, x1, y1]` each divided by `frame.width`/`frame.height`, range `0.0–1.0`.
  **This is the only bbox field ever compared across backends** (e.g. matching an Azure word to a
  Surya line by bbox overlap). Never compare raw `bbox` values from two different backends directly
  — they are in different pixel spaces.
- `bbox_frame` — always `"surya-px"` for the `bbox` field on this record (documents which frame
  `bbox`, not `bbox_norm`, is expressed in — mandatory per hazard below).
- `confidence` — Surya's own per-line confidence, or Azure's word-level confidence if this line was
  matched and Azure ran and the config says prefer Azure for this field. `null` if no real
  transcription-confidence score is available (default: Surya's is always available, so this is
  `null` only in unusual cases).
- `confidence_source` — which backend the `confidence` value came from (`"surya"` or `"azure"`).
  Never left ambiguous — a consumer must be able to tell whose number this is.
- `layout_score` — MinerU's `score` field when a MinerU line matched this record (agree or
  dissent — either verdict still tells us which MinerU span this is), `null` otherwise. Kept
  **strictly separate from `confidence`**: it is a layout/detection-quality score, not a
  transcription confidence, and must never be read as one.
- `reading_order` — float, present only on pages where at least one reader matched something (see
  `merge-canonical.py`'s `assign_reading_order`); absent entirely otherwise. `render-txt.py` sorts
  a page's lines by this field when present, falling back to Surya `(y, x)` bbox order when it
  isn't. Matched lines get the chosen reader's own linear position on that page (see
  `READER_PRIORITY` in `merge-canonical.py` for which reader wins when more than one is present);
  lines that reader never matched are linearly interpolated between their nearest matched
  neighbors *in Surya's original line order*, so an unmatched line stays near where Surya found it
  rather than jumping elsewhere. Not comparable across lines from different pages or different
  primary readers — it is a per-page sort key, nothing more.
- `agreement` — see below.
- `cell` — `{table_id, row, col}` if this line falls inside a detected table cell, else `null`.
- `selection_mark` — `{state, confidence}` copied from the nearest Azure `selectionMarks[]` entry if
  this line is a checkbox/mark region, else `null`. Surya has no selection-mark concept at all — a
  checkbox always reads as the same bracket glyph regardless of which option is marked, so without
  Azure this field is always `null` and any checkbox question must escalate to a rendered crop.

### `agreement` object

```json
{
  "m": 2,
  "n": 2,
  "agreed": ["olmocr", "chandra"],
  "dissent": [],
  "absent": [],
  "method": "rapidfuzz.partial_ratio"
}
```

- `m` — how many independent readers **ran** for this document (0 for `surya-only`, 1 for `local`,
  2 for `remote`, +1 more if `--azure`). Constant across every line in the file. Lets a consumer
  tell a strong signal (`m=2`, everyone agreed) from a weak one (`m=0`, no signal exists at all) —
  never treat `n == m` at `m=0` as agreement.
- `n` — how many of those `m` readers **agreed** with this Surya line (fuzzy match ≥ 90, see Phase
  2's merge algorithm). `n < m` is the disagreement signal that replaces confidence thresholds.
- `agreed` — reader names that matched ≥ 90.
- `dissent` — reader names that matched 75–89, each as `{"reader": "olmocr", "text": "777-00936-00"}`
  — the reader's own substring is recorded verbatim so the disagreement is inspectable without going
  back to the reader's raw file.
- `absent` — reader names whose page slice had no matching span at all (< 75, or the reader
  linearized this region away entirely). **Absence is never blankness evidence** — it means the
  reader dropped or merged the region, not that the source is empty.
- `method` — matching method used, `"rapidfuzz.partial_ratio"` or `"difflib"` fallback.

`match_quality: "low"` is added to this object (alongside the fields above) when the underlying
Surya line is short (`1`, `X`, `N/A` — a handful of characters) — such spans fuzzy-match against
almost anything, so their `agreement` is non-evidence and must be flagged, not trusted at face value
by a downstream consumer.

## Hazard: five coordinate spaces

`bbox` (verbatim, backend-native pixels) exists in **five different spaces** across this stack:

| Backend | Native unit |
|---|---|
| Surya | pixels, per-page render |
| Chandra 2 | pixels, of its **own** render (not Surya's) |
| MinerU 2.5 | pixels, **or** 0–1000 normalized, **or** 0–1 normalized — depends on which output file |
| Azure (PDF input) | inches |
| Azure (image input) | pixels |

**Read `pages[].unit` (Azure) or the equivalent per-backend field at runtime — never hardcode a
unit assumption.** `bbox_frame` is mandatory on every line record specifically so a reader of this
canonical file never has to guess which space `bbox` is in. `bbox_norm` exists precisely to give the
merge algorithm and any cross-backend comparison one space that always means the same thing
(fraction of that page's own width/height, `0.0–1.0`).

## Hazard: four page-index bases

Every backend indexes pages differently, and every adapter must convert to 1-based **at its own
boundary** before anything reaches this schema:

| Backend | Native base |
|---|---|
| Surya | 1-based (`page` field) |
| Azure | 1-based (`pages[]` array position + 1, or explicit `pageNumber`) |
| MinerU 2.5 | 0-based (`page_idx`) |
| Chandra 2 | 0-based (block-id path) |
| olmOCR 2 | no page field — recovered from `attributes.pdf_page_numbers` char-span triples, base
  unconfirmed until Phase 3's first real run |

This canonical schema is **always 1-based** (`pages[].page`, `reader_pages{}` values). A silent
off-by-one here is the highest-risk merge bug in the whole pipeline — every adapter's page-number
conversion is the first thing to check if a citation's page marker looks wrong by exactly one.

## What cannot be mapped (Phase 2 — documented here so consumers know the gaps up front)

- **olmOCR** emits no geometry and no confidence, ever. Its only contribution to this schema is
  `agreement` votes and `reader_pages` entries — it never populates `bbox`, `confidence`, or
  `layout_score` on any line.
- **Chandra** has no per-line geometry and no confidence. It cannot answer "is this cell empty," so
  it contributes `agreement` votes only, scoped by its own block-level bbox when available.
- **MinerU's `score`** is a layout-detection score, not transcription confidence — it only ever
  populates `layout_score`, never `confidence`.
- **Surya has no selection-mark concept** — every checkbox glyph collapses to the same bracket by
  construction. Without `--azure`, `selection_marks` is always `[]` and `selection_mark` is always
  `null` on every line; any checkbox question must escalate to a rendered crop.
- **Reader absence (`agreement.absent`) is never blankness evidence.** A cell missing from a
  reader's output means the reader linearized it away, not that the source page is blank. Only an
  empty `lines[]` array (no Surya witness at all) is real blankness evidence.

## `<stem>.coverage.json` (sibling file, not part of canonical.json)

`check-reader-coverage.py` writes one of these alongside each `canonical/<stem>.json` it checks —
informational only, never read by `ocr-verify`/`ocr-validate`, and safe to delete/regenerate at
will. It exists because a reader can silently elide content (a well-formed, structurally-valid
empty table body) in a way `agreement.absent` alone documents but nothing flags as anomalous — see
the previous bullet.

```json
{
  "stem": "<stem>",
  "coverage": [
    {"stem": "<stem>", "page": 323, "reader": "olmocr", "surya_lines": 1041,
     "absent": 970, "absent_rate": 0.932}
  ],
  "elision": [
    {"stem": "<stem>", "page": 323, "reader": "olmocr", "elision_hits": 1}
  ]
}
```

- `coverage[]` — pages where Surya found plentiful lines but one reader's `agreement.absent` rate on
  that page crossed a threshold. Usually a reader that didn't read the page, but has a known
  false-positive mode on dense tables: a reader that emits one HTML row per table row collapses
  many of Surya's per-cell lines into one block, which fuzzy-matches poorly even though every value
  is present in the reader's raw output and the rendered `.txt` (confirmed on this fixture — doc 01
  pages 50/64/68 flag at 90%+ absent with nothing actually missing). Treat a `coverage[]` entry with
  no matching `elision[]` entry on the same page as "worth a look," not "confirmed broken."
  Deliberately excludes `azure` from this math — Azure is additive/page-scoped, and a page outside
  its submitted range legitimately shows every line absent for it, which isn't a reader failure.
- `elision[]` — pages where a reader's raw output matched an omission-placeholder pattern (e.g.
  `<!-- Table rows follow -->`). Narrower than `coverage[]` (only fires when the reader announces
  its own omission) but close to zero-false-positive when it does — the stronger of the two
  signals, treat a hit as confirmed content loss; the two lists are not subsets of one another — a
  page can appear in one, the other, or both.
