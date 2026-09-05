# Check catalog

Every check reads facts from `extract-numerics.py` (see its docstring for `facts`/`dates`/
`identifiers`/`tables`) and emits zero or more flags. **A check that can't find its inputs emits
nothing for that document** — silence, not a guess. `ocr-validate` asserts nothing itself; every
flag's `verify_cmd` is a ready-to-run `/bayou:ocr-verify` invocation that actually resolves the
question with evidence (see that skill's `SKILL.md`).

Severity markers: 🔴 (likely error, needs resolution before a finding cites this value), ⚠️ (probable
issue, resolve before relying on this value), ⚪ (routine confirmation), ℹ️ (informational —
`CROSS-DOC` only; never asserts which reading is right, always routes to a tally).

## Table-dependent checks

These five need real row/column structure — `canonical.pages[].tables[]`, which today is populated
**only when `--azure` ran** for that document (`document-ocr/merge-canonical.py` does not ingest
MinerU's table structure into the canonical schema — a known gap, not something this skill papers
over). **On a document with no Azure pass, none of these five checks produce any flags for it** —
that's an input limitation of the run, not a check failure. Re-run `document-ocr --azure` on the
specific documents with detailed emissions tables if this coverage matters.

| id | rule |
|---|---|
| `UNIT-TPY-LBHR` | Header row identifies an lb/hr column and a tpy column (by unit keyword in the header cell text). Per data row: `tpy ≤ lb_hr × 4.38` (8760 h/yr). Over by >2% ⇒ 🔴 digit error *or* an undisclosed short-term limit. Under by >5% ⇒ ⚪ confirm hours of operation. |
| `UNIT-HEAT` | Header identifies lb/MMBtu, MMBtu/hr, and lb/hr columns. Per row: `lb/MMBtu × MMBtu/hr` must equal the stated `lb/hr` within ±5% ⇒ 🔴 outside. |
| `SUBTOTAL` / `TABLE-SUM` | A row whose label cell contains "total"/"subtotal" vs. the sum of the other data rows in that column. Mismatch > `max(0.5%, 0.1 tpy)` ⇒ 🔴. Stays silent (not a guess) when a table has more than one "total"-labeled row — e.g. a `Total HAPs` row and a separate `Total TAPs` row in the same table are each a subtotal of a different, mostly-unlisted set of pollutants, not a sum of the visible criteria-pollutant rows above them, so there is no single row the check can safely treat as "the" total. |
| `MAGNITUDE` | Within same-row-label groups (≥3 rows sharing that label, excluding header/total rows), a value >10× or <0.1× the group's median ⇒ ⚠️ probable digit shift/drop. |
| `ZERO-VS-BLANK` | Any table cell whose text is the empty string, in a data row that has at least one non-blank cell in a numeric column. **Never conflate this with a literal `0`, `—`, or `N/A` cell — none of those are flagged.** A row where every numeric-column cell is blank is treated as a spacer/footer artifact or an unused optional form line (e.g. a permit form's "list up to 3 fuel types" block where only row `a` was filled in), not a missing value, and produces no flags — this alone removed 88% of this check's flags on the Hyundai POSCO fixture. ⇒ ⚪, routed to `ocr-verify` via the `page:bbox_norm` locate form (see that skill's `SKILL.md`) since a blank cell has no OCR text to search for. |

**Known unsound on wide "matrix" tables (Hyundai POSCO doc 01/04):** `UNIT-TPY-LBHR`, `UNIT-HEAT`,
and `MAGNITUDE` all assume a narrow table — one column per unit, and a row-label column that
identifies the pollutant. Some emissions tables in this package instead list many named pollutants
as *columns* (e.g. one `(lb/hr)` column per HAP) with a generic `Stack Type`/`Point`/`Fugitive`
label in column 0. On those tables:
- `header_column_map` keeps only the *last* header cell matching a given unit keyword (`col_map[key]
  = cell["col"]` overwrites), so on a table with several `lb/hr` columns the check silently picks
  whichever one happened to sort last, not a meaningful one.
- `MAGNITUDE`'s row-label grouping degenerates to grouping by `Point`/`Fugitive` (column 0's actual
  content on these tables), so it takes a median across dozens of unrelated pollutants that
  legitimately span orders of magnitude — flagging most of them.

These three checks were not redesigned to handle that table shape — treat their flags on doc 01/04
as low-confidence until reviewed, and expect flag volume to look disproportionate to the number of
genuine emissions tables in a package like this one.

## Text-only checks (work on any backend tier)

These five run off the plain-text numeric/date/identifier scan (`extract-numerics.py`'s line-level
facts), which exists regardless of whether Azure or MinerU or nothing ran. A fact's "meaning" here
is only as good as its `context` (the source line's own text) — every flag carries that context so
a human can judge the association, since there's no guaranteed column identity behind it.

| id | rule |
|---|---|
| `THRESHOLD` | A `tpy` fact within 2% **below** 100 (Title V major / PSD listed), 250 (PSD non-listed), 10 (single HAP), or 25 (aggregate HAP) ⇒ ⚠️ **even when there's no arithmetic to check** — a near-miss below a major-source threshold is worth a second look regardless. |
| `PLAUSIBILITY` | Negative emissions (any emissions-unit fact <0) ⇒ 🔴. Control efficiency (context contains "efficiency", unit `%`) outside 0–100% ⇒ 🔴. Stack height (context contains "height", unit `ft`) <5 or >600 ⇒ ⚠️. Exit/stack temperature (context contains "temp", unit `°F`) <32 (a fixed ambient-floor approximation, not a real ambient reading) or >2000 ⇒ ⚠️. Flow (unit acfm/scfm/dscfm/gpm) ≤0 ⇒ 🔴. Opacity (context contains "opacity", unit `%`) >100 ⇒ 🔴. |
| `DATE-SANITY` | A document with both an issuance-labeled and expiration-labeled date: expiration before issuance ⇒ 🔴. Both an effective- and submitted-labeled date: effective before submitted ⇒ 🔴. Date-role labeling is a nearby-keyword heuristic (`issu`, `expir`, `effective`, `submit`/`received`) — a date with no confident role match is never used for this check. |
| `FORMAT` | An identifier (`AI_NUMBER`/`PERMIT_NUMBER`/`ACTIVITY_NUMBER`/`EQT_NUMBER`) whose digit-length differs from the majority length for that kind across the run (only applied once ≥3 observations of that kind exist — not enough signal below that) ⇒ ⚠️, routed to `ocr-verify --tally`. |
| `CROSS-DOC` | The same identifier kind resolves to more than one distinct value across more than one document in the run ⇒ ℹ️, **always** a tally, **never** a finding — this check does not claim any one reading is correct. |

## Why identifiers use digit-length instead of a full regex-per-kind

`AI_NUMBER`/`ACTIVITY_NUMBER`/`EQT_NUMBER`/`PERMIT_NUMBER` are already extracted by a kind-specific
regex in `extract-numerics.py`, so every candidate already matches that kind's general shape by
construction. What `FORMAT` catches is a *within-kind* outlier — one `AI_NUMBER` with 4 digits when
every other one in the run has 5 — which a single fixed regex can't see, since the outlier still
matches the same pattern, just with a different digit count. This is deliberately the same
diagnostic the `7777-00936-00` failure case (`ocr-verify/references/failure-cases.md`) is about: a
repeated-glyph miscount that a shape-level check alone won't catch, and a straight majority-length
comparison will.
