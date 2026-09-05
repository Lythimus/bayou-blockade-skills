---
name: ocr-verify
description: Resolve a single OCR-contested value with evidence — every backend's opinion on a line, an optional cross-package tally, and a rendered crop when needed. Use before writing "blank," "empty," "illegible," "cannot be determined," or a cross-citation disagreement into any bayou:permit-analysis finding.
argument-hint: <work-dir> <stem|file.txt> <"snippet"|file.txt:LINE|page:x0,y0,x1,y1> [--field "<label>"] [--tally] [--no-crop]
allowed-tools: Bash, Read
---

# bayou:ocr-verify — resolve one OCR-contested value with evidence

`bayou:document-ocr` produces `.txt` for searching and `$WORK/canonical/<stem>.json` for evidence
(see its `references/output-schema.md`). `permit-analysis` searches the `.txt`, but a `.txt` line
alone can never justify a claim of blankness, illegibility, or cross-document disagreement — see
`references/failure-cases.md` for the two real incidents that motivate this skill. `ocr-verify` is
the resolution step: given one contested value, it pulls every backend's opinion, optionally tallies
it across the whole package, and — when the evidence doesn't already agree — crops the source region
at high DPI so a plain visual read can settle it.

## Invocation

```
/bayou:ocr-verify <work-dir> <stem|file.txt> <"snippet"|file.txt:LINE|page:x0,y0,x1,y1> [--field "<label>"] [--tally] [--no-crop]
```

- `<work-dir>` — the OCR pipeline's `$WORK` dir (`results/`, `canonical/`, `azure/` live here).
- `<stem|file.txt>` — the document, named either way.
- Third argument — where in it, one of three forms:
  - a quoted snippet, located with `rg -n -F`;
  - `file.txt:LINE` (the same form `permit-analysis` already cites) — used directly, no search
    needed; prefer this when re-verifying a citation already in hand;
  - `page:x0,y0,x1,y1` (a bare page number and a `bbox_norm` rect) — for a region with **no OCR
    text to search for at all**, e.g. a table cell `ocr-validate`'s `ZERO-VS-BLANK` check flagged
    as empty. Skips Steps 2–4 entirely (there is no canonical line to pull opinions on) and goes
    straight to Step 5's crop; EVIDENCE in this mode is the rendered crop alone, and STATUS is
    almost always `BLANK-ATTESTED` (crop confirms nothing there) or `ESCALATE-TO-USER` (crop shows
    something no backend transcribed at all — worth a bigger look, not just this one cell).
- `--field "<label>"` — optional human-readable label for the field being checked (e.g. `"AI
  Number"`), echoed in the output block's context but not parsed structurally.
- `--tally` — also run the cross-package minority-reading check (see `tally-across-docs.py` below).
- `--no-crop` — skip the rendered-image escalation even if the evidence would otherwise call for
  one; use only when a crop genuinely isn't obtainable (no source PDF locatable) and you're
  reporting `ESCALATE-TO-USER` instead.

## Step 1 — resolve the document and the target line

If the third argument is `page:x0,y0,x1,y1`, there is no line to locate — skip straight to Step 5
with that page and rect.

Otherwise: if `<stem|file.txt>` ends in `.txt` and exists as a path, that's `txt_path`; derive
`stem` from its basename. Otherwise it's a bare stem — find its `.txt` by searching near
`<work-dir>` (its parent, sibling `txt`/`out` directories, or the current working tree): `find .
-iname "<stem>.txt"`. Zero or more-than-one match: stop and ask which file, rather than guessing.
**This resolved path always wins** — it is the one you actually verified exists.

If the third argument matches `<path>.txt:<N>`, take `N` as the target line. Use its `<path>` only
as a check, never as a substitute for the resolved `txt_path` above: if `<path>` is a bare filename
(e.g. `run-checks.py`'s emitted `verify_cmd`s always write it this way — a `verify_cmd` has no way
to know your working directory) that doesn't independently resolve from the current directory,
that's expected — the stem it names should match the `stem` already resolved from the second
argument, and `txt_path` from that resolution is what you read. If `<path>`'s stem *disagrees*
with the second argument's stem, flag that mismatch before proceeding rather than silently picking
one. Otherwise (the third argument is a snippet, not `path.txt:N`): `rg -n -F -- "<snippet>"
"<txt_path>"`. Zero matches: report that
plainly and stop (there is nothing to verify). More than one match: list them and ask which
occurrence, unless `--tally` was requested and the point is exactly to compare all of them.

## Step 2 — pull every backend's opinion

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/ocr-verify/pull-opinions.py <work-dir> <stem> <txt_path> <line> --context 3
```

This locates the page marker at or before `<line>` (scanning backward — the same operation
`permit-analysis` already does for any citation), re-derives which canonical line that ordinal is
(reusing `document-ocr/render-txt.py`'s own line-ordering function so the two can never drift),
verifies its text actually matches the `.txt` line before trusting it, and returns that line plus 3
neighbors each way with: Surya `confidence`, full `agreement` (`m`/`n`/`agreed`/`dissent`/`absent`,
plus `match_quality: "low"` when the underlying text is a handful of characters), `layout_score`
(MinerU only — never read this as confidence), `cell`/`selection_mark` (Azure-derived, `null` unless
Azure ran), and — when this document has an Azure pass — that line's own Azure word text/confidence,
matched geometrically by `bbox_norm` overlap (Azure carries no line-level identity of its own; see
`output-schema.md`).

## Step 3 — decide STATUS

- **`m == 0`** (no reader ran — `surya-only`): there is no agreement signal at all. `n == m` is
  trivially true here and must never be read as agreement — go straight to the crop unless the
  value is unambiguous on its face (e.g. a long, cleanly-formed string at very high Surya
  confidence with no digit-run or glyph-collapse risk).
- **Escalate to a crop** if any of: `agreement.n < agreement.m`, `agreement.match_quality ==
  "low"`, `confidence` is not `null` and `< 0.85`, the text is a single glyph or a checkbox-bracket
  shape, the text is blank/whitespace-only, or `--tally` (step 4) shows a split.
- **`RESOLVED`** without a crop only when `m > 0`, full agreement (`n == m`), confidence `>= 0.85`
  (or no confidence field but every reader agrees), and (if run) `--tally` shows no split.
- **`BLANK-ATTESTED`** requires **all** of: no Surya line at all in the target region (an empty
  `lines[]` slice, not merely a low-confidence one), no Azure pass covering it or an Azure cell
  there reading `""`, and a rendered crop confirming no mark. Reader *absence* (`agreement.absent`)
  never counts as blankness evidence — it means a reader linearized the region away, not that the
  source is empty (see `output-schema.md`).
- **`AMBIGUOUS`** — evidence pulled, genuinely split, crop still doesn't settle it (heavy
  artifacting, a redaction, physical damage).
- **`ESCALATE-TO-USER`** — the citation is load-bearing for a 🔴 finding and step 3's own tools
  (crop included) still leave real ambiguity; put the rendered image in front of the user rather
  than guessing.

## Step 4 — `--tally` (the minority-reading rule)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/ocr-verify/tally-across-docs.py <dir-of-txt_path> "<value>" --max-distance 2
```

Counts every occurrence of `<value>` and its near-neighbors (edit distance ≤ 2, computed on
whitespace-delimited tokens after trimming enclosing punctuation — internal characters like `-`/`/`
are never touched, since a repeated-digit miscount is exactly the signal this exists to catch, see
`references/failure-cases.md`) across every `.txt` in the same directory as `txt_path` — i.e. the
whole review package, not just the two documents already in question. A minority reading against an
otherwise-dominant one is a probable OCR artifact, **not** a real cross-document discrepancy — say
so explicitly, and note that a high confidence score on the minority citation is uninformative on
this specific question. Contrast with a genuine inconsistency: two different values each repeated
consistently with no majority/minority split is real, not an artifact — don't apply this rule to
that case.

## Step 5 — crop (unless resolved without one, or `--no-crop`)

Locate the source PDF: search near `<work-dir>` and `txt_path`'s directory for `<stem>.pdf` (`find`
under the input directory, `<work-dir>`'s siblings, or the current working tree — the same ad hoc
resolution as step 1, since `$WORK` itself no longer retains a source-PDF pointer; the old
`$WORK/pdf/` stage was deleted, see `document-ocr`'s plan). Not found: fall back to
`ESCALATE-TO-USER` rather than guessing at a path.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/ocr-verify/crop-region.py <source.pdf> <page> <x0> <y0> <x1> <y1> <out.png> --dpi 400
```

`<page>` and `<x0 y0 x1 y1>` (`bbox_norm`) come straight from step 2's output — crop from
`bbox_norm`, never from a backend-native pixel `bbox` (five different coordinate spaces exist across
backends; `bbox_norm` is the only one that's a plain fraction of the page regardless of which
backend produced the line). Then `Read` the PNG and say plainly what it shows — a vision-capable
model looking at the actual page beats a re-guess from OCR text every time.

## Output block

Reproduce this exactly — `permit-analysis` pastes it verbatim under **Verified citations**:

```
VALUE:     7777-00936-00
STATUS:    RESOLVED | AMBIGUOUS | BLANK-ATTESTED | ESCALATE-TO-USER
CITATION:  <file>.txt:1284  (page 12, bbox_norm [0.31,0.44,0.52,0.46])
EVIDENCE:
  - surya   "777-00936-00"  conf 0.971  agreement 1/3
  - olmocr  "7777-00936-00" —
  - chandra "7777-00936-00" —
  - azure   "7777-00936-00" word-conf 0.988
  - tally across package: 7777-00936-00 x9, 777-00936-00 x2 (both same doc)
  - rendered crop @400dpi: reads 7777-00936-00
NOTE:      minority reading is an OCR artifact, not a source discrepancy
```

Omit the `tally` line when `--tally` wasn't run, and the `rendered crop` line when step 3 resolved
without one. `olmocr`/`chandra` show `—` for confidence — neither backend produces one (see
`output-schema.md`); their text comes from `agreement.agreed` (their reading matched Surya's line at
≥90%, so it's shown as Surya's own text) or `agreement.dissent`'s recorded substring when they
disagreed. `mineru` shows `layout-score` in place of `conf` when present — it is a layout-detection
score, never a transcription confidence, and must be labeled as such so a reader never confuses the
two.

$ARGUMENTS
