# Failure cases that motivate this skill

Two real incidents from a past permit-analysis campaign. Both are reproduced verbatim from
`permit-analysis/SKILL.md`'s prior 5b verification prose, which they originally motivated — they
now live here, and `ocr-verify`'s escalation flow in `SKILL.md` exists specifically to make both
of them unrepresentable in a future finding.

## The checkbox collapse

A claim that something is "blank," "empty," "illegible," or "cannot be determined" is itself a
citation and needs the same rigor as a quoted figure — never write one of these words into a
finding on the strength of the flattened `.txt` or a low OCR confidence score alone. Two failures
from a real campaign motivate this: a checkbox's flattened line read `[ Yes [ No` — Surya collapses
every checkbox glyph to the same bracket regardless of which box is actually marked, so the *text*
is uninformative about check-state by construction, not because the scan is bad. The verifier wrote
"the mark is illegible" from that text; the rendered page at 300+ DPI showed an unambiguous ☒ on
"No," in the same style as three other checkboxes on the same page. Separately, a claim that one
document showed an undefined "T" where a related document showed "1" rested on a single
0.636-confidence OCR misread; rendering both cells side by side at high DPI showed both plainly
read "1." Before writing "blank"/"empty"/"illegible"/"cannot be determined" into any finding: (1)
pull every witness line in the region — a field with **no text_line at all** across a table's
row/cell range is real evidence of blankness; a low-confidence guess is evidence the OCR pass
struggled, not evidence the source is illegible; (2) locate the page, then rasterize it (or crop to
the bbox with generous padding) at 300–400 DPI from the source PDF; (3) look at the rendered image
and say plainly what it shows. A vision-capable model can usually resolve this outright, and "I
rendered it and it reads X" is a stronger, cheaper finding than an unverified claim of illegibility
— don't skip straight to asserting the negative.

## The `7777-00936-00` nine-citation tally

A claim that the same field disagrees across citations — especially when the two readings are
near-identical strings (a repeated-digit count off by one, a transposed digit, one extra/missing
character) — needs a tally across the whole package before it is asserted as a real inconsistency,
and high per-citation OCR confidence does not excuse this step. A campaign asserted a permit number
read `7777-00936-00` in the public notice and Specific Requirements header but `777-00936-00` in
the signed draft approval letter — a plausible two-source discrepancy on its face, each reading
individually at 0.97+ confidence. It wasn't real: the same source PDF cites that permit number
**nine** times, and only two of the nine — both still high-confidence reads — dropped a digit; the
other seven, plus the user's own visual check of the source pages, agreed on `7777-00936-00`. Surya
can confidently misread a run of identical or near-identical glyphs (four `7`s as three) on one page
rendering while reading the same field correctly everywhere else in the same document — confidence
score alone cannot distinguish that from a genuine drafting error, because the model is confident
about what it saw, not about whether a repeated-glyph run was miscounted. Before writing any
"document/section A says X, document/section B says Y" finding where X and Y differ by a small edit
distance: (1) search the claimed value(s) across *every* OCRed document in the package, not just the
two already cited; (2) tally how many independent citations support each reading; (3) a minority
reading against an otherwise-unanimous field (as here) is a probable OCR artifact — pull its
confidence anyway, but treat a high score as uninformative on this specific question, and escalate
before asserting the finding. Contrast this with a genuine inconsistency that survives the tally:
two different figures (e.g. a 48-hour vs. 240-hour flare duration) each corroborated identically and
repeatedly across multiple independently-scanned documents, with no majority/minority split — that
pattern is evidence of an actual drafting inconsistency in the source, not an OCR artifact, and does
not need the escalation below.

## What `ocr-verify` does with these

- The checkbox case is why `BLANK-ATTESTED` requires all three of: no Surya line in the region, no
  Azure selection mark or cell content there either, and a rendered crop confirming no mark — never
  a bare absence claim from `.txt` or a confidence score alone.
- The `7777-00936-00` case is exactly what `--tally` (see `tally-across-docs.py`) automates: count
  every near-neighbor citation across the package before a cross-citation disagreement is asserted,
  and flag a minority reading as a probable OCR artifact rather than a real discrepancy — noting
  explicitly that a high confidence score is uninformative on that specific question.
