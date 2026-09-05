"""Run the check catalog (see references/air-permit-checks.md) against extract-numerics.py's
output and emit flags. ocr-validate asserts nothing itself -- every flag's verify_cmd is a
ready-to-run /bayou:ocr-verify invocation that actually resolves the question with evidence.

Usage: run-checks.py <work-dir> <extracted.json> [--out verification/OCR-FLAGS.md]

<extracted.json> is extract-numerics.py's stdout, saved to a file (kept as a separate step, not
piped internally, so a failed/partial extraction is visible before checks run against it).

Writes <out> (default verification/OCR-FLAGS.md, human-readable, one section per severity) and a
sibling flags.json (machine-readable, same directory as <out>) with the raw flag list.

A check that can't find its inputs for a document emits nothing for that document -- silence, not
a guess (see air-permit-checks.md). The five table-dependent checks (UNIT-TPY-LBHR, UNIT-HEAT,
SUBTOTAL/TABLE-SUM, MAGNITUDE, ZERO-VS-BLANK) only ever fire on documents that have
canonical.pages[].tables[] -- i.e. documents that had an Azure pass, per that same reference.
"""

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from statistics import median

# CROSS-DOC (below) needs the same edit-distance function ocr-verify's tally-across-docs.py uses,
# so its own "is this within --tally's reach" check can never drift from what --tally actually
# does. Reused directly from that sibling skill rather than reimplemented here.
SCRIPT_DIR = Path(__file__).resolve().parent
OCR_VERIFY_DIR = SCRIPT_DIR.parent / "ocr-verify"
_spec = importlib.util.spec_from_file_location(
    "tally_across_docs", OCR_VERIFY_DIR / "tally-across-docs.py"
)
_tally = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tally)
levenshtein = _tally.levenshtein

SEVERITY_ORDER = {"\U0001F534": 0, "⚠️": 1, "⚪": 2, "ℹ️": 3}  # 🔴 ⚠️ ⚪ ℹ️
RED, WARN, CONFIRM, INFO = "\U0001F534", "⚠️", "⚪", "ℹ️"

THRESHOLDS_TPY = {
    100: "Title V major / PSD listed pollutant",
    250: "PSD non-listed pollutant",
    10: "single HAP",
    25: "aggregate HAP",
}

TPY_UNITS = {"TPY"}
EMISSIONS_UNITS = {"LB_HR", "TPY", "LB_MMBTU"}


def verify_cmd(work_dir, stem, locator, extra=""):
    cmd = f'/bayou:ocr-verify {work_dir} {stem} {locator}'
    if extra:
        cmd += f" {extra}"
    return cmd


def make_flag(check, severity, doc, page, line_id, txt_cite, observed, expected, message, cmd):
    return {
        "check": check,
        "severity": severity,
        "doc": doc,
        "page": page,
        "line_id": line_id,
        "txt_cite": txt_cite,
        "observed": observed,
        "expected": expected,
        "message": message,
        "verify_cmd": cmd,
    }


# --- Text-only checks ---------------------------------------------------------------------------


def check_threshold(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        for fact in data.get("facts", []):
            if fact["unit"] not in TPY_UNITS:
                continue
            value = fact["value"]
            for threshold, label in THRESHOLDS_TPY.items():
                if value >= threshold:
                    continue
                pct_below = (threshold - value) / threshold
                if pct_below <= 0.02:
                    flags.append(
                        make_flag(
                            "THRESHOLD", WARN, stem, fact["page"], fact["line_id"], fact["txt_cite"],
                            f"{value} tpy", f"within 2% of {threshold} tpy ({label})",
                            f"{value} tpy is within 2% below the {threshold} tpy {label} threshold "
                            "-- worth a precise check even if the arithmetic elsewhere is clean.",
                            verify_cmd(work_dir, stem, fact["txt_cite"]),
                        )
                    )
    return flags


PLAUSIBILITY_RULES = [
    # (unit, context_keyword_or_None, predicate, expected_desc, severity)
    ("LB_HR", None, lambda v: v < 0, "non-negative", RED),
    ("TPY", None, lambda v: v < 0, "non-negative", RED),
    ("LB_MMBTU", None, lambda v: v < 0, "non-negative", RED),
    ("PERCENT", "efficiency", lambda v: v < 0 or v > 100, "0-100%", RED),
    ("PERCENT", "opacity", lambda v: v > 100, "<=100%", RED),
    ("FT", "height", lambda v: v < 5 or v > 600, "5-600 ft", WARN),
    ("DEGF", "temp", lambda v: v < 32 or v > 2000, "32-2000 F (approximate)", WARN),
    ("FLOW", None, lambda v: v <= 0, "> 0", RED),
]


def check_plausibility(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        for fact in data.get("facts", []):
            for unit, keyword, predicate, expected, severity in PLAUSIBILITY_RULES:
                if fact["unit"] != unit:
                    continue
                if keyword and keyword not in fact["context"].lower():
                    continue
                if not predicate(fact["value"]):
                    continue
                flags.append(
                    make_flag(
                        "PLAUSIBILITY", severity, stem, fact["page"], fact["line_id"], fact["txt_cite"],
                        f"{fact['value']} {unit}", expected,
                        f"{fact['value']} {unit} is outside a physically plausible range "
                        f"({expected}) for: {fact['context'][:120]!r}",
                        verify_cmd(work_dir, stem, fact["txt_cite"]),
                    )
                )
                break  # one rule per fact is enough; avoid duplicate flags on the same value
    return flags


DATE_FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%b. %d, %Y"]


def parse_date(text):
    from datetime import datetime

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.replace(",", ",").strip(), fmt).date()
        except ValueError:
            continue
    return None


DATE_SANITY_PAIRS = [("issuance", "expiration"), ("submitted", "effective")]


def check_date_sanity(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        by_role = {}
        for d in data.get("dates", []):
            if d.get("role"):
                by_role.setdefault(d["role"], []).append(d)

        for earlier_role, later_role in DATE_SANITY_PAIRS:
            for earlier in by_role.get(earlier_role, []):
                earlier_dt = parse_date(earlier["date_text"])
                if not earlier_dt:
                    continue
                for later in by_role.get(later_role, []):
                    later_dt = parse_date(later["date_text"])
                    if not later_dt:
                        continue
                    if later_dt < earlier_dt:
                        flags.append(
                            make_flag(
                                "DATE-SANITY", RED, stem, later["page"], later["line_id"], later["txt_cite"],
                                f"{later_role}={later_dt.isoformat()}",
                                f"{later_role} >= {earlier_role} ({earlier_dt.isoformat()})",
                                f"{later_role} date {later['date_text']!r} falls before "
                                f"{earlier_role} date {earlier['date_text']!r}.",
                                verify_cmd(work_dir, stem, later["txt_cite"]),
                            )
                        )
    return flags


def check_format(work_dir, extracted):
    by_kind = {}
    for stem, data in extracted.items():
        for ident in data.get("identifiers", []):
            by_kind.setdefault(ident["kind"], []).append({**ident, "doc": stem})

    flags = []
    for kind, idents in by_kind.items():
        if len(idents) < 3:
            continue
        lengths = [len(re.sub(r"\D", "", i["value"])) for i in idents]
        majority_len = max(set(lengths), key=lengths.count)
        for ident, length in zip(idents, lengths):
            if length == majority_len:
                continue
            flags.append(
                make_flag(
                    "FORMAT", WARN, ident["doc"], ident["page"], ident["line_id"], ident["txt_cite"],
                    ident["value"], f"{majority_len}-digit {kind} (majority of {len(idents)} seen)",
                    f"{kind} {ident['value']!r} has {length} digits; every other {kind} in this run "
                    f"has {majority_len}.",
                    verify_cmd(work_dir, ident["doc"], ident["txt_cite"], "--tally"),
                )
            )
    return flags


CROSS_DOC_TALLY_MAX_DISTANCE = 2  # must match tally-across-docs.py's own default


def check_cross_doc(work_dir, extracted):
    """Same identifier kind, different values across documents -- never a finding, always routed.

    Anchored on the MAJORITY reading (most citations, not "whichever doc came first") so
    --tally's own default max-distance (2) actually has a chance of surfacing the split: tally
    only catches near-neighbor OCR drift (the 7777-00936-00 case), not genuinely distinct values.
    So before recommending --tally, check whether every minority reading is actually within that
    same distance of the majority -- if not, --tally would silently show a clean, non-split tally
    for a real discrepancy, and the emitted command has to say so instead of pretending it works.
    """
    by_kind = {}
    citations = {}  # (kind, value) -> first citation seen, for anchor lookup
    for stem, data in extracted.items():
        for ident in data.get("identifiers", []):
            key = (ident["kind"], ident["value"])
            by_kind.setdefault(ident["kind"], {}).setdefault(ident["value"], set()).add(stem)
            citations.setdefault(key, {**ident, "doc": stem})

    flags = []
    for kind, values in by_kind.items():
        docs_touched = set()
        for docs in values.values():
            docs_touched |= docs
        if len(values) < 2 or len(docs_touched) < 2:
            continue

        majority_value = max(values, key=lambda v: len(values[v]))
        minority_values = [v for v in values if v != majority_value]
        near_neighbors = all(
            levenshtein(v, majority_value) <= CROSS_DOC_TALLY_MAX_DISTANCE for v in minority_values
        )

        readings = ", ".join(f"{v!r} ({len(docs)} doc(s))" for v, docs in values.items())
        anchor = citations[(kind, majority_value)]

        if near_neighbors:
            message = (
                f"{kind} has {len(values)} distinct readings across {len(docs_touched)} documents: "
                f"{readings}. All within edit distance {CROSS_DOC_TALLY_MAX_DISTANCE} of the "
                f"majority reading {majority_value!r} -- consistent with an OCR near-miss (see "
                "the 7777-00936-00 case). Never asserted as a discrepancy here -- tally before "
                "treating this as real."
            )
            cmd = verify_cmd(work_dir, anchor["doc"], anchor["txt_cite"], f'--field "{kind}" --tally')
        else:
            message = (
                f"{kind} has {len(values)} distinct readings across {len(docs_touched)} documents: "
                f"{readings}. At least one reading differs from the majority {majority_value!r} by "
                f"more than {CROSS_DOC_TALLY_MAX_DISTANCE} edit(s) -- too far apart for --tally's "
                "near-neighbor matching to help; check each citation directly instead."
            )
            cmd = verify_cmd(work_dir, anchor["doc"], anchor["txt_cite"], f'--field "{kind}"')

        flags.append(
            make_flag(
                "CROSS-DOC", INFO, anchor["doc"], anchor["page"], anchor["line_id"], anchor["txt_cite"],
                readings, "a single consistent value across the package", message, cmd,
            )
        )
    return flags


# --- Table-dependent checks ----------------------------------------------------------------------

# Same exponent gap as extract-numerics.py's NUMBER_UNIT_RE (see its comment) -- without the
# [eE][+-]?\d+ group, a cell like "3.04E-04" reads as 3.04, a 10,000x inflation, not a missing
# value. Table cells don't carry the range-dash ambiguity line-text does (a cell holds one number,
# never "70%-99%"), so no negative-lookbehind guard is needed here.
BARE_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")


def cell_number(text):
    m = BARE_NUMBER_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def header_column_map(table, keyword_map):
    """{unit_key: col_index}, from whichever row has the most keyword hits (usually row 0)."""
    rows = {}
    for cell in table["cells"]:
        rows.setdefault(cell["row"], []).append(cell)
    best_row, best_hits = None, 0
    for row_idx, cells in rows.items():
        col_map, hits = {}, 0
        for cell in cells:
            text = (cell["text"] or "").lower()
            for keyword, unit_key in keyword_map.items():
                if keyword in text:
                    col_map[unit_key] = cell["col"]
                    hits += 1
        if hits > best_hits:
            best_row, best_hits, best_col_map = row_idx, hits, col_map
    if best_hits == 0:
        return None, None
    return best_row, best_col_map


def data_rows(table, header_row):
    rows = {}
    for cell in table["cells"]:
        if cell["row"] == header_row:
            continue
        rows.setdefault(cell["row"], []).append(cell)
    return rows


def row_label(cells):
    labeled = [c for c in cells if c["col"] == 0]
    return labeled[0]["text"] if labeled else ""


def cell_txt_cite(work_dir, stem, page, cell):
    if cell.get("bbox_norm"):
        x0, y0, x1, y1 = cell["bbox_norm"]
        return f"{page}:{x0},{y0},{x1},{y1}"
    return None


def check_unit_tpy_lbhr(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        for table in data.get("tables", []):
            header_row, cols = header_column_map(
                table, {"lb/hr": "LB_HR", "tpy": "TPY", "ton": "TPY"}
            )
            if not cols or "LB_HR" not in cols or "TPY" not in cols:
                continue
            for row_idx, cells in data_rows(table, header_row).items():
                lb_hr_cell = next((c for c in cells if c["col"] == cols["LB_HR"]), None)
                tpy_cell = next((c for c in cells if c["col"] == cols["TPY"]), None)
                if not lb_hr_cell or not tpy_cell:
                    continue
                lb_hr, tpy = cell_number(lb_hr_cell["text"]), cell_number(tpy_cell["text"])
                if lb_hr is None or tpy is None or lb_hr <= 0:
                    continue
                expected_max = lb_hr * 4.38
                label = row_label(cells)
                cite = cell_txt_cite(work_dir, stem, table["page"], tpy_cell)
                if not cite:
                    continue
                if tpy > expected_max * 1.02:
                    flags.append(
                        make_flag(
                            "UNIT-TPY-LBHR", RED, stem, table["page"], None, cite,
                            f"{tpy} tpy", f"<= {expected_max:.2f} tpy (from {lb_hr} lb/hr x 4.38)",
                            f"Row {label!r}: {tpy} tpy exceeds {lb_hr} lb/hr x 4.38 by >2% -- digit "
                            "error or an undisclosed short-term limit.",
                            verify_cmd(work_dir, stem, cite),
                        )
                    )
                elif tpy < expected_max * 0.95:
                    flags.append(
                        make_flag(
                            "UNIT-TPY-LBHR", CONFIRM, stem, table["page"], None, cite,
                            f"{tpy} tpy", f"~{expected_max:.2f} tpy (from {lb_hr} lb/hr x 4.38)",
                            f"Row {label!r}: {tpy} tpy is >5% below the 8760h/yr max implied by "
                            f"{lb_hr} lb/hr -- confirm hours of operation.",
                            verify_cmd(work_dir, stem, cite),
                        )
                    )
    return flags


def check_unit_heat(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        for table in data.get("tables", []):
            header_row, cols = header_column_map(
                table, {"lb/mmbtu": "LB_MMBTU", "mmbtu/hr": "MMBTU_HR", "lb/hr": "LB_HR"}
            )
            if not cols or not {"LB_MMBTU", "MMBTU_HR", "LB_HR"} <= cols.keys():
                continue
            for row_idx, cells in data_rows(table, header_row).items():
                get = lambda key: next((c for c in cells if c["col"] == cols[key]), None)
                lb_mmbtu_cell, mmbtu_hr_cell, lb_hr_cell = get("LB_MMBTU"), get("MMBTU_HR"), get("LB_HR")
                if not (lb_mmbtu_cell and mmbtu_hr_cell and lb_hr_cell):
                    continue
                lb_mmbtu, mmbtu_hr, lb_hr = (
                    cell_number(lb_mmbtu_cell["text"]),
                    cell_number(mmbtu_hr_cell["text"]),
                    cell_number(lb_hr_cell["text"]),
                )
                if None in (lb_mmbtu, mmbtu_hr, lb_hr) or lb_hr == 0:
                    continue
                expected = lb_mmbtu * mmbtu_hr
                if abs(expected - lb_hr) / abs(lb_hr) > 0.05:
                    cite = cell_txt_cite(work_dir, stem, table["page"], lb_hr_cell)
                    if not cite:
                        continue
                    flags.append(
                        make_flag(
                            "UNIT-HEAT", RED, stem, table["page"], None, cite,
                            f"{lb_hr} lb/hr", f"~{expected:.2f} lb/hr (from {lb_mmbtu} x {mmbtu_hr})",
                            f"Row {row_label(cells)!r}: {lb_mmbtu} lb/MMBtu x {mmbtu_hr} MMBtu/hr = "
                            f"{expected:.2f} lb/hr, off from the stated {lb_hr} lb/hr by >5%.",
                            verify_cmd(work_dir, stem, cite),
                        )
                    )
    return flags


def check_subtotal(work_dir, extracted):
    flags = []
    for stem, data in extracted.items():
        for table in data.get("tables", []):
            header_row, cols = header_column_map(table, {"tpy": "TPY", "ton": "TPY"})
            if not cols or "TPY" not in cols:
                continue
            rows = data_rows(table, header_row)
            total_row_idxs = [
                idx for idx, cells in rows.items() if "total" in row_label(cells).lower()
            ]
            # More than one "total"-labeled row (e.g. "Total HAPs" and "Total TAPs" alongside
            # individual criteria pollutants) means there's no single row that sums everything
            # else in the table -- the check's whole premise breaks, so stay silent rather than
            # guess which one (if either) is a real grand total.
            if len(total_row_idxs) != 1:
                continue
            total_row_idx = total_row_idxs[0]
            total_cell = next(
                (c for c in rows[total_row_idx] if c["col"] == cols["TPY"]), None
            )
            total_value = cell_number(total_cell["text"]) if total_cell else None
            if total_value is None:
                continue
            part_sum = 0.0
            any_part = False
            for idx, cells in rows.items():
                if idx == total_row_idx:
                    continue
                cell = next((c for c in cells if c["col"] == cols["TPY"]), None)
                value = cell_number(cell["text"]) if cell else None
                if value is not None:
                    part_sum += value
                    any_part = True
            if not any_part:
                continue
            tolerance = max(0.005 * total_value, 0.1)
            if abs(part_sum - total_value) > tolerance:
                cite = cell_txt_cite(work_dir, stem, table["page"], total_cell)
                if not cite:
                    continue
                flags.append(
                    make_flag(
                        "SUBTOTAL", RED, stem, table["page"], None, cite,
                        f"total={total_value}", f"sum of rows = {part_sum:.3f}",
                        f"Stated total {total_value} tpy differs from the sum of this table's "
                        f"other rows ({part_sum:.3f} tpy) by more than max(0.5%, 0.1 tpy).",
                        verify_cmd(work_dir, stem, cite),
                    )
                )
    return flags


def check_magnitude(work_dir, extracted):
    """>10x or <0.1x the median of SAME-POLLUTANT sibling rows -- not the whole column.

    A table's rows are usually different pollutants (NOx legitimately runs ~100x SO2), so a
    column-wide median is the wrong comparison and would false-positive on nearly every row of
    nearly every real table. "Same pollutant" is approximated by the row's own label cell (col 0)
    text, normalized -- multiple rows sharing that label (e.g. the same pollutant repeated across
    emission points/units within one table) form a group; a group needs >=3 members before a
    median is meaningful, same threshold as the old column-wide version.
    """
    flags = []
    for stem, data in extracted.items():
        for table in data.get("tables", []):
            header_row, cols = header_column_map(table, {"tpy": "TPY", "lb/hr": "LB_HR"})
            if not cols:
                continue
            rows = data_rows(table, header_row)
            for unit_key, col in cols.items():
                groups = {}
                for idx, cells in rows.items():
                    label = row_label(cells)
                    if "total" in label.lower() or not label.strip():
                        continue
                    cell = next((c for c in cells if c["col"] == col), None)
                    value = cell_number(cell["text"]) if cell else None
                    if value is not None and value > 0:
                        groups.setdefault(label.strip().lower(), []).append((cell, value, label))
                for label_key, items in groups.items():
                    if len(items) < 3:
                        continue
                    med = median(v for _, v, _ in items)
                    if med <= 0:
                        continue
                    for cell, value, label in items:
                        if value > med * 10 or value < med * 0.1:
                            cite = cell_txt_cite(work_dir, stem, table["page"], cell)
                            if not cite:
                                continue
                            flags.append(
                                make_flag(
                                    "MAGNITUDE", WARN, stem, table["page"], None, cite,
                                    f"{value} {unit_key}", f"~{med:.3f} {unit_key} (sibling median)",
                                    f"Row {label!r}: {value} {unit_key} is >10x or <0.1x the median "
                                    f"({med:.3f}) of {len(items)} rows sharing this same label -- "
                                    "probable digit shift/drop.",
                                    verify_cmd(work_dir, stem, cite),
                                )
                            )
    return flags


NUMERIC_COLUMN_KEYWORDS = {
    "lb/hr": "LB_HR", "tpy": "TPY", "ton": "TPY", "lb/mmbtu": "LB_MMBTU", "mmbtu/hr": "MMBTU_HR",
}


def check_zero_vs_blank(work_dir, extracted):
    """Blank cells inside a column where a number was actually expected -- not every blank cell.

    Real tables (Azure especially) carry plenty of structurally empty cells that are correct as-is
    (spanning row-header cells, layout artifacts, merged-cell remnants) -- flagging all of them
    would bury the ones that matter. This exists to protect arithmetic ("blank routes to
    ocr-verify, not to arithmetic," see air-permit-checks.md), so it only fires inside a column a
    header keyword identified as numeric, on a data row (not the header row itself).
    """
    flags = []
    for stem, data in extracted.items():
        for table in data.get("tables", []):
            header_row, cols = header_column_map(table, NUMERIC_COLUMN_KEYWORDS)
            if not cols:
                continue
            numeric_cols = set(cols.values())
            # A row where every numeric-column cell is blank isn't a data row with one missing
            # value -- it's a spacer/footer artifact (see t4 row 46 in the Hyundai POSCO fixture,
            # 23/23 cells empty) or an unused optional form line (a Title V "list up to 3 fuel
            # types" block where only row 'a' was filled in and 'b'/'c' carry a label but no data
            # in any numeric column). Checking numeric columns only, not the whole row, still
            # catches the row-label cell being non-blank in that second case -- requiring the
            # *entire* row blank (label included) missed 78% of these on doc 04. A row with a mix
            # of filled and blank numeric cells is left alone; that pattern is the actual signal
            # this check exists for.
            blank_rows = set()
            rows_by_idx = {}
            for cell in table["cells"]:
                rows_by_idx.setdefault(cell["row"], []).append(cell)
            for row_idx, cells in rows_by_idx.items():
                if row_idx == header_row:
                    continue
                numeric_cells = [c for c in cells if c["col"] in numeric_cols]
                if numeric_cells and all((c["text"] or "").strip() == "" for c in numeric_cells):
                    blank_rows.add(row_idx)
            for cell in table["cells"]:
                if cell["row"] == header_row or cell["col"] not in numeric_cols:
                    continue
                if cell["row"] in blank_rows:
                    continue
                if cell["text"] is not None and cell["text"].strip() == "" and cell.get("bbox_norm"):
                    cite = cell_txt_cite(work_dir, stem, table["page"], cell)
                    if not cite:
                        continue
                    flags.append(
                        make_flag(
                            "ZERO-VS-BLANK", CONFIRM, stem, table["page"], None, cite,
                            "(blank cell)", "confirmed blank via a rendered crop, not assumed 0",
                            f"Table {table['table_id']}, row {cell['row']} col {cell['col']} (a "
                            "numeric column) has no OCR text. Never treat this as 0/N-A -- verify "
                            "with a crop.",
                            verify_cmd(work_dir, stem, cite),
                        )
                    )
    return flags


CHECKS = [
    check_threshold,
    check_plausibility,
    check_date_sanity,
    check_format,
    check_cross_doc,
    check_unit_tpy_lbhr,
    check_unit_heat,
    check_subtotal,
    check_magnitude,
    check_zero_vs_blank,
]


WIDE_TABLE_CAVEAT = (
    "**UNIT-TPY-LBHR, UNIT-HEAT, and MAGNITUDE are known-unsound on wide \"matrix\" tables** "
    "(seen in this package's doc 01/04 HAP tables: many named pollutants as columns, a generic "
    "Stack Type/Point/Fugitive label in column 0, and multi-row captions above the real header "
    "row). They assume a narrow table -- one column per unit, a row label that identifies the "
    "pollutant. On a matrix table, header-keyword matching keeps only the last matching column "
    "(so a table with several `lb/hr` columns silently checks the wrong one), MAGNITUDE's "
    "same-label grouping degenerates to grouping by `Point`/`Fugitive` and takes a median across "
    "unrelated pollutants, and a caption row above the real header can leak into the data rows "
    "summed by SUBTOTAL. Every 🔴 in this run traces back to one of these three checks on a "
    "matrix table -- treat them as low-confidence pending human review, not as confirmed errors, "
    "until reviewed. See references/air-permit-checks.md for detail."
)
IDENTIFIER_LOOSENESS_CAVEAT = (
    "**FORMAT's identifier regexes are loose enough to over-match.** `AI_NUMBER` alone produced "
    "288 hits in doc 01 -- implausible for one facility's Agency Interest number recurring that "
    "often across one document. Spot-check a handful of FORMAT flags against their `context` "
    "before trusting the majority-length comparison; some are likely unrelated numbers near a "
    "stray \"AI\"/\"Al\"/\"A1\" OCR token, not real Agency Interest citations."
)
COMMA_DECIMAL_CAVEAT = (
    "**A source-OCR corruption pattern was found, not a validate bug: a comma thousands-separator "
    "misread as a decimal point** (e.g. `1,100°F` OCR'd as `1.100°`, correctly flagged here as an "
    "implausible 1.1°F). This is systematic and dangerous specifically because it produces "
    "*silence*, not a flag, whenever the corrupted value still looks plausible -- `1,321.45 tpy` "
    "misread as `1.32145 tpy` triggers no check here, since nothing about 1.32 tpy looks wrong on "
    "its own. Any tpy/lb-hr figure `permit-analysis` cites from this package is worth a raw-OCR "
    "gut-check for a stray comma-as-period, independent of whether ocr-validate flagged it."
)


def render_markdown(flags, skipped, tableless_docs):
    lines = ["# OCR-FLAGS", ""]

    lines.append("## Coverage")
    lines.append("")
    if skipped:
        lines.append(
            f"- **Skipped (no canonical.json found):** {', '.join(skipped)} -- these "
            "documents produced no flags because nothing was checked, not because they're "
            "clean. Run `bayou:document-ocr` (or `merge-canonical.py`) for them first."
        )
    if tableless_docs:
        lines.append(
            f"- **No Azure tables:** {', '.join(tableless_docs)} -- the five table-dependent "
            "checks (UNIT-TPY-LBHR, UNIT-HEAT, SUBTOTAL/TABLE-SUM, MAGNITUDE, ZERO-VS-BLANK) "
            "produced no flags for these documents because they have no `--azure` table "
            "structure to check, not because their tables are clean. See "
            "references/air-permit-checks.md."
        )
    lines.append(f"- {WIDE_TABLE_CAVEAT}")
    lines.append(f"- {IDENTIFIER_LOOSENESS_CAVEAT}")
    lines.append(f"- {COMMA_DECIMAL_CAVEAT}")
    lines.append("")

    by_severity = {}
    for f in flags:
        by_severity.setdefault(f["severity"], []).append(f)
    for severity in sorted(by_severity, key=lambda s: SEVERITY_ORDER.get(s, 9)):
        lines.append(f"## {severity} ({len(by_severity[severity])})")
        lines.append("")
        for f in by_severity[severity]:
            lines.append(f"- **{f['check']}** `{f['doc']}` — {f['message']}")
            lines.append(f"  - observed: {f['observed']} | expected: {f['expected']}")
            lines.append(f"  - `{f['verify_cmd']}`")
        lines.append("")
    if not flags:
        lines.append("No flags.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir")
    parser.add_argument("extracted_json")
    parser.add_argument("--out", default="verification/OCR-FLAGS.md")
    args = parser.parse_args()

    with open(args.extracted_json, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    skipped = extracted.pop("_skipped", [])
    tableless_docs = [stem for stem, data in extracted.items() if not data.get("tables")]

    flags = []
    for check_fn in CHECKS:
        flags.extend(check_fn(args.work_dir, extracted))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(flags, skipped, tableless_docs), encoding="utf-8")

    flags_json_path = out_path.parent / "flags.json"
    flags_json_path.write_text(json.dumps(flags, indent=2), encoding="utf-8")

    print(f"[OCR] validate done -> {out_path} ({len(flags)} flags)", file=sys.stderr)


if __name__ == "__main__":
    main()
