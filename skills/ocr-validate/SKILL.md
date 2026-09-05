---
name: ocr-validate
description: Cheap, mechanical pre-pass over an OCRed permit package — flags unit-conversion mismatches, subtotal errors, implausible values, date inconsistencies, and cross-document identifier disagreements, each pointing at a ready-to-run bayou:ocr-verify command. Use once per package before bayou:permit-analysis's verify pass.
argument-hint: <work-dir> [--doc <stem>...] [--out verification/OCR-FLAGS.md]
allowed-tools: Bash, Read
---

# bayou:ocr-validate — find candidates cheaply, resolve them with ocr-verify

`ocr-validate` never asserts anything on its own. It scans `$WORK/canonical/*.json` for numeric,
date, and identifier patterns that are *statistically* worth a second look — a subtotal that
doesn't sum, a value implausible on its face, a permit number shaped differently from every other
one in the package — and emits one flag per candidate, each carrying a ready-to-run
`/bayou:ocr-verify` command that actually resolves it with evidence. Validate finds candidates;
`bayou:ocr-verify` (and its `--tally`) settles them. See `references/air-permit-checks.md` for the
full check catalog and exactly which rule each check applies.

## Invocation

```
/bayou:ocr-validate <work-dir> [--doc <stem>...] [--out verification/OCR-FLAGS.md]
```

- `<work-dir>` — the OCR pipeline's `$WORK` dir.
- `--doc <stem>` — restrict to specific documents (repeatable); default is every
  `$WORK/canonical/*.json`.
- `--out` — where to write the human-readable report (default `verification/OCR-FLAGS.md`, relative
  to the current directory). A machine-readable `flags.json` is written alongside it in the same
  directory.

## Running it

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/ocr-validate/extract-numerics.py <work-dir> [--doc <stem> ...] > /tmp/ocr-extracted.json
python3 ${CLAUDE_PLUGIN_ROOT}/skills/ocr-validate/run-checks.py <work-dir> /tmp/ocr-extracted.json --out <out-path>
```

Two steps, not piped together, so a partial or empty extraction is visible before checks run
against it — if `extract-numerics.py` produced nothing for a document that clearly has numeric
tables, that's worth noticing before trusting a clean `OCR-FLAGS.md`.

`run-checks.py` prints `[OCR] validate done -> <out> (<n> flags)` to stderr. Read `<out>` and hand
the flags to the user as a pre-seeded 🔍 TODO list — one to resolve (via the printed `verify_cmd`)
before any 🔴/⚠️ finding in `permit-analysis` cites the value it points at.

## Coverage — read before trusting a quiet run

Ten checks total; five need real table structure (`canonical.pages[].tables[]`, populated **only
when `--azure` ran** for that document) and five work off plain OCRed text on any tier. See
`references/air-permit-checks.md` for the full split and every rule's exact threshold. **A document
with no Azure pass gets zero flags from the five table-dependent checks (`UNIT-TPY-LBHR`,
`UNIT-HEAT`, `SUBTOTAL`/`TABLE-SUM`, `MAGNITUDE`, `ZERO-VS-BLANK`)** — that is a coverage gap in the
input, not evidence the tables are clean. Say so plainly when handing off a report for a package
that ran without `--azure` on its emissions tables.

## Why `ocr-validate` never asserts

A check that guesses at which column is which, or which value is "the" pollutant, produces false
flags — worse than missing a real one, since a false flag burns a verification cycle and erodes
trust in the ones that are real. Every check either has enough structure to be confident (a labeled
header column, a row literally marked "total") or it stays silent for that document. This is the
same split `permit-analysis`'s own verify pass already enforces for blank/illegible claims (see
`ocr-verify/references/failure-cases.md`) — `ocr-validate` applies the identical discipline to
arithmetic instead of prose.

$ARGUMENTS
