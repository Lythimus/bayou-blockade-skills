"""Merge Surya geometry + any available reader(s) + optional Azure layout into the canonical
schema (see references/output-schema.md).

Surya's results.json is always the single witness for line existence -- every line in the
output's lines[] originates from Surya's grid. Readers only ever vote on Surya's lines
(agreement.agreed/dissent/absent); they never inject new lines. This is what keeps the
blankness rule sound even when multiple backends are merged (see output-schema.md).

Usage:
  merge-canonical.py <results.json> <out_canonical.json>
      [--stem STEM]
      [--reader olmocr=PATH] [--reader chandra=PATH] [--reader mineru=PATH]
      [--azure PATH]
      [--backend remote|local|surya-only]

Each --reader flag names one backend and its raw output file. --azure points at a raw
analyzeResult JSON. All are optional; with none given this produces the same degenerate
zero-reader structure render-txt.py's own fallback builds directly from results.json.

Needs rapidfuzz for fuzzy line matching; falls back to stdlib difflib if rapidfuzz isn't
installed (this script is not part of the no-dependency remote path -- only render-txt.py is).
"""

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz

    def fuzzy_ratio(a, b):
        return _rapidfuzz_fuzz.partial_ratio(a, b)

    MATCH_METHOD = "rapidfuzz.partial_ratio"
except ImportError:
    import difflib

    def fuzzy_ratio(a, b):
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio() * 100

    MATCH_METHOD = "difflib"
    print(
        "[OCR] WARN rapidfuzz not installed -- falling back to stdlib difflib for line matching. "
        "This is dramatically slower (a 2+ hour stall has been observed on a ~2000-page document "
        "vs. minutes with rapidfuzz) and, if only some documents in a batch see this, produces a "
        "package with a mixed match_method -- `pip install rapidfuzz` before merging a large batch.",
        file=sys.stderr,
    )

SCRIPT_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("render_txt", SCRIPT_DIR / "render-txt.py")
_render_txt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_render_txt)
surya_to_canonical = _render_txt.surya_to_canonical
load_results_json = _render_txt.load_results_json

TABLE_SYNTAX_RE = re.compile(r"[|┃│]|</?t[dhr]>|</?table>|^[\-\s]+$", re.IGNORECASE | re.MULTILINE)
WHITESPACE_RE = re.compile(r"\s+")
SHORT_LINE_MAX_LEN = 3
# A checkbox glyph's Surya line and its Azure selectionMarks[] entry are two independently
# detected regions for the same physical mark, not the same box -- 3% of the page's own
# width/height is generous enough to bridge that gap without also catching an unrelated mark
# elsewhere on a dense form.
SELECTION_MARK_PROXIMITY_NORM = 0.03


def normalize(text):
    """NFKC -> casefold -> collapse whitespace -> strip markdown/HTML table syntax.

    Deliberately does NOT normalize digit lookalikes (1/l/I, 7/1, 0/O) -- that would destroy
    the repeated-glyph-miscount signal the merge exists to catch (see the 7777-00936-00 case
    in ocr-verify's references/failure-cases.md).
    """
    text = unicodedata.normalize("NFKC", text)
    text = TABLE_SYNTAX_RE.sub(" ", text)
    text = text.casefold()
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


# --- Per-backend adapters: raw reader output -> {page_num (1-based): [unit_text, ...]} ---------
# Each adapter returns page -> list of discrete text units (words/lines/blocks) that can be
# windowed and matched against a Surya line, and consumed once matched. Page-index conversion to
# 1-based happens here, at each adapter's own boundary (see output-schema.md's page-index hazard).


def adapt_olmocr(path):
    """Dolma JSONL; page slices recovered via attributes.pdf_page_numbers char-span triples.

    UNVERIFIED: whether pdf_page_numbers is 0-based or 1-based has not been confirmed against a
    real olmOCR 2 run (see plan's Open risks). Assumed 1-based here, matching Surya/Azure; if a
    real run shows otherwise, this is the first place to fix.
    """
    pages = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            text = doc.get("text", "")
            spans = doc.get("attributes", {}).get("pdf_page_numbers", [])
            for start, end, page_num in spans:
                page_num = int(page_num)
                slice_text = text[int(start) : int(end)]
                units = [u for u in slice_text.split("\n") if u.strip()]
                pages.setdefault(page_num, []).extend(units)
    return pages


def adapt_chandra(path):
    """_metadata.json: block-level {page, bbox, label, content}.

    UNVERIFIED: DeepWiki documents per-block bbox/label/content; a closed GitHub issue claims
    the CLI exposes no layout information at all. If this file lacks 'bbox', block-scoped
    matching degrades to page-global (see match_reader_to_page's optional bbox scoping).
    Page index assumed 0-based (block-id path convention) and converted to 1-based here.
    """
    pages = {}
    with open(path, "r", encoding="utf-8") as f:
        blocks = json.load(f)
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks", [])
    for block in blocks:
        page_num = int(block.get("page", 0)) + 1
        content = block.get("content", "")
        units = [u for u in content.split("\n") if u.strip()]
        pages.setdefault(page_num, []).extend(units)
    return pages


def adapt_mineru(path):
    """_middle.json: pdf_info[] (page_idx 0-based) -> para_blocks -> lines -> spans{content,score}.

    Returns page -> [(unit_text, score_or_None), ...]. MinerU's score is a layout-detection
    score, not transcription confidence -- carried through separately as layout_score, never
    written into confidence.
    """
    pages = {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for page_entry in data.get("pdf_info", []):
        page_num = int(page_entry.get("page_idx", 0)) + 1
        units = []
        for block in page_entry.get("para_blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    content = span.get("content", "")
                    if content.strip():
                        units.append((content, span.get("score")))
        if units:
            pages.setdefault(page_num, []).extend(units)
    return pages


def polygon_to_bbox_norm(polygon, width, height):
    """[x0,y0,x1,y1] as a fraction of the page's own width/height.

    Fraction-of-page is unit-agnostic: Azure reports polygon points and page width/height in the
    same unit (inch for PDF input, pixel for image input, per output-schema.md's coordinate-space
    hazard), so dividing by width/height cancels the unit regardless of which one it is -- no
    inch-vs-pixel branch is needed here.
    """
    xs = polygon[0::2] or [0]
    ys = polygon[1::2] or [0]
    return [min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height]


def bbox_norm_center(bbox_norm):
    return ((bbox_norm[0] + bbox_norm[2]) / 2, (bbox_norm[1] + bbox_norm[3]) / 2)


def point_in_bbox_norm(point, bbox_norm):
    x, y = point
    return bbox_norm[0] <= x <= bbox_norm[2] and bbox_norm[1] <= y <= bbox_norm[3]


def union_bbox_norm(bboxes):
    xs0 = [b[0] for b in bboxes]
    ys0 = [b[1] for b in bboxes]
    xs1 = [b[2] for b in bboxes]
    ys1 = [b[3] for b in bboxes]
    return [min(xs0), min(ys0), max(xs1), max(ys1)]


def adapt_azure(path):
    """analyzeResult: pages[].words[] (content/polygon/confidence), selectionMarks[], tables[].

    pages[] index is already 1-based (pageNumber); pages[].unit distinguishes inch (PDF input)
    from pixel (image input) -- read at runtime, never hardcoded, per output-schema.md.

    Returns (word_pages, selection_marks, tables_by_page). tables_by_page is keyed by page number
    (a table can span pages; confirmed against a real run that each cell carries its own
    boundingRegions[0].pageNumber, so a spanning table is split into one entry per page it
    actually has cells on, sharing a stable table_id). Each table entry carries a table-level
    bbox_norm (the union of its own cells' bbox_norm on that page) plus per-cell bbox_norm --
    output-schema.md documents both as required, and merge-canonical.py's line["cell"] assignment
    below needs the per-cell rects to test line-centroid containment against.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = data.get("analyzeResult", data)

    page_dims = {}  # page_num -> (width, height), needed to convert a cell's own page polygon
    word_pages = {}
    selection_marks = {}
    for page in result.get("pages", []):
        page_num = int(page.get("pageNumber", 1))
        width = page.get("width", 1) or 1
        height = page.get("height", 1) or 1
        page_dims[page_num] = (width, height)

        words = [(w.get("content", ""), w.get("confidence")) for w in page.get("words", [])]
        if words:
            word_pages[page_num] = words

        marks = []
        for mark in page.get("selectionMarks", []):
            marks.append(
                {
                    "bbox_norm": polygon_to_bbox_norm(mark.get("polygon", []), width, height),
                    "state": mark.get("state"),
                    "confidence": mark.get("confidence"),
                }
            )
        if marks:
            selection_marks[page_num] = marks

    tables_by_page = {}
    for table_index, table in enumerate(result.get("tables", [])):
        table_id = f"t{table_index}"
        table_regions = table.get("boundingRegions") or []
        default_page = int(table_regions[0]["pageNumber"]) if table_regions else 1

        cells_by_page = {}
        for cell in table.get("cells", []):
            cell_regions = cell.get("boundingRegions") or []
            if cell_regions:
                cell_page = int(cell_regions[0].get("pageNumber", default_page))
                polygon = cell_regions[0].get("polygon", [])
            else:
                cell_page = default_page
                polygon = []
            width, height = page_dims.get(cell_page, (1, 1))
            bbox_norm = polygon_to_bbox_norm(polygon, width, height) if polygon else None
            cells_by_page.setdefault(cell_page, []).append(
                {
                    "row": cell.get("rowIndex"),
                    "col": cell.get("columnIndex"),
                    "text": cell.get("content", ""),
                    "bbox_norm": bbox_norm,
                }
            )

        for page_num, cells in cells_by_page.items():
            located = [c["bbox_norm"] for c in cells if c["bbox_norm"]]
            tables_by_page.setdefault(page_num, []).append(
                {
                    "table_id": table_id,
                    "bbox_norm": union_bbox_norm(located) if located else None,
                    "rows": table.get("rowCount"),
                    "cols": table.get("columnCount"),
                    "cells": cells,
                }
            )

    return word_pages, selection_marks, tables_by_page


# --- Matching -------------------------------------------------------------------------------


DIGITS_RE = re.compile(r"\d+")


def digit_run_score_cap(target_digits, candidate):
    """Cap a fuzzy score when digit runs disagree.

    Character-level fuzzy ratio is a poor judge of a dropped/repeated digit inside an otherwise
    near-identical numeric string ("777-00936-00" vs "7777-00936-00" scores as near-total
    similarity by length alone). Since digit lookalikes are deliberately never normalized (see
    normalize()), a mismatch in the concatenated digit sequence caps the score below the "agree"
    threshold even if overall character similarity is high -- this is what lets the merge
    surface exactly the repeated-glyph-miscount signal it exists to catch.

    target_digits is precomputed by the caller (constant across the whole candidate scan for a
    given target line) rather than re-extracted via regex on every one of the O(U*max_window)
    candidate comparisons -- profiled as a meaningful share of match_reader_to_page's cost
    alongside the normalize() redundancy fixed above.
    """
    candidate_digits = "".join(DIGITS_RE.findall(candidate))
    if target_digits and candidate_digits and target_digits != candidate_digits:
        return 89
    return 100


def match_reader_to_page(surya_lines, reader_units, max_window=12):
    """Match Surya lines (longest-first) against a reader's page slice, windowing and consuming
    reader units so one reader region can't satisfy many Surya lines.

    reader_units: list of unit strings (mutated: consumed units removed as matches are found).
    Returns {surya_line_index: (verdict, reader_text_or_None, reader_pos_or_None)} where verdict
    is "agree" (>=90), "dissent" (75-89), or "absent" (<75), and reader_pos is that match's
    starting index in the *original* (pre-consumption) reader_units list -- used only to derive
    reading_order, never to re-locate text (consumption already mutates positions as we go, so
    reader_pos is captured before this match's span is deleted from `remaining`).
    """
    order = sorted(
        range(len(surya_lines)),
        key=lambda i: -len(normalize(surya_lines[i])),
    )
    # Track each remaining unit's original index alongside its text so a match's position can be
    # reported even after earlier matches have deleted other units from `remaining`.
    remaining = list(enumerate(reader_units))
    results = {}

    for i in order:
        target = normalize(surya_lines[i])
        if not target:
            results[i] = ("absent", None, None)
            continue
        target_digits = "".join(DIGITS_RE.findall(target))

        # normalize() (NFKC + two regex substitutions) dominates this function's runtime --
        # profiled at ~66% of it on a real large document -- because every unit gets re-normalized
        # once per window width it appears in (up to max_window times) rather than once. Since
        # `remaining` only changes (via the del below) between surya-line iterations, not within
        # this scan, normalizing each unit exactly once here and reusing it in every window below
        # is the same computation with the redundant ~max_window multiplier removed.
        norm_units = [normalize(u[1]) for u in remaining]

        best_score = -1
        best_span = None
        best_text = None
        best_pos = None
        for start in range(len(remaining)):
            joined = ""
            for width in range(1, min(max_window, len(remaining) - start) + 1):
                joined = " ".join(norm_units[start : start + width])
                if not joined:
                    continue
                score = min(fuzzy_ratio(target, joined), digit_run_score_cap(target_digits, joined))
                if score > best_score:
                    best_score = score
                    best_span = (start, start + width)
                    best_text = " ".join(u[1] for u in remaining[start : start + width])
                    best_pos = remaining[start][0]

        if best_score >= 90:
            results[i] = ("agree", best_text, best_pos)
            if best_span:
                del remaining[best_span[0] : best_span[1]]
        elif best_score >= 75:
            results[i] = ("dissent", best_text, best_pos)
            if best_span:
                del remaining[best_span[0] : best_span[1]]
        else:
            results[i] = ("absent", None, None)

    return results


# Priority order for which reader's own linearization becomes a page's reading order, when more
# than one is present. olmOCR is called out in the plan as best-in-class on reading order
# specifically (incl. rotated/landscape tables); Chandra is next-best on tables; MinerU's
# reading order comes from its own layout detection, generally solid but not singled out in the
# plan the way the other two are; Azure's words[] array is reliable but untested here for
# reading order specifically, so it's last. Not specified by the plan -- a documented judgment
# call, easy to reorder if a real run shows a different reader deserves priority.
READER_PRIORITY = ["olmocr", "chandra", "mineru", "azure"]


def assign_reading_order(lines, primary_matches):
    """Give every line on a page a reading_order float, derived from primary_matches:
    {surya_line_index: reader_unit_position} for whichever lines the chosen primary reader
    actually matched (agree or dissent -- either verdict still tells us where the reader placed
    that content).

    Matched lines get the reader's own linear position directly. A line the reader never matched
    (dropped cell, absent reader) is anchored by linear interpolation between its nearest matched
    neighbors *in Surya's own original line order* -- keeping it near where Surya found it rather
    than flinging it to the end, without claiming a reader position that was never observed.

    If primary_matches is empty (reader ran but matched nothing on this page, or no reader
    present at all), leaves reading_order unset -- render-txt.py's fallback to Surya (y, x)
    bbox-sort then applies unchanged.
    """
    if not primary_matches:
        return
    n = len(lines)
    anchor_idxs = sorted(primary_matches.keys())
    order_values = [None] * n
    for i in anchor_idxs:
        order_values[i] = float(primary_matches[i])

    def fill_range(lo, hi, lo_val, hi_val):
        span = hi - lo + 1
        for k, idx in enumerate(range(lo, hi + 1), start=1):
            order_values[idx] = lo_val + (hi_val - lo_val) * k / (span + 1)

    if anchor_idxs[0] > 0:
        first_val = order_values[anchor_idxs[0]]
        fill_range(0, anchor_idxs[0] - 1, first_val - 1.0, first_val)
    for a, b in zip(anchor_idxs, anchor_idxs[1:]):
        if b - a > 1:
            fill_range(a + 1, b - 1, order_values[a], order_values[b])
    if anchor_idxs[-1] < n - 1:
        last_val = order_values[anchor_idxs[-1]]
        fill_range(anchor_idxs[-1] + 1, n - 1, last_val, last_val + 1.0)

    for i, line in enumerate(lines):
        line["reading_order"] = order_values[i]


def build_canonical(results_json_path, backend, readers, azure_path):
    results = load_results_json(results_json_path)
    canonical = surya_to_canonical(results)

    reader_page_units = {}  # reader_name -> {page_num: [unit, ...]}
    mineru_page_scores = {}  # page_num -> [score_or_None, ...], index-aligned with
    # reader_page_units["mineru"][page_num] -- layout_score is MinerU-only (see output-schema.md),
    # kept as a side table rather than threaded through match_reader_to_page's generic string
    # matching, which every other reader also uses and has no notion of a per-unit score.
    reader_names = []
    for name, path in readers.items():
        if not path:
            continue
        if name == "olmocr":
            reader_page_units[name] = adapt_olmocr(path)
        elif name == "chandra":
            reader_page_units[name] = adapt_chandra(path)
        elif name == "mineru":
            mineru_pages = adapt_mineru(path)
            reader_page_units[name] = {
                p: [u[0] for u in units] for p, units in mineru_pages.items()
            }
            mineru_page_scores = {
                p: [u[1] for u in units] for p, units in mineru_pages.items()
            }
        else:
            continue
        reader_names.append(name)

    azure_word_pages, azure_selection_marks, azure_tables_by_page = {}, {}, {}
    if azure_path:
        azure_word_pages, azure_selection_marks, azure_tables_by_page = adapt_azure(azure_path)

    all_reader_names = list(reader_names)
    if azure_path:
        all_reader_names.append("azure")
    m = len(all_reader_names)

    for page in canonical["pages"]:
        page_num = page["page"]
        lines = page["lines"]
        surya_texts = [line["text"] for line in lines]

        # Attach Azure's page-scoped geometry before the per-line loop below, which tests line
        # centroids against these rects for cell/selection_mark assignment.
        if page_num in azure_selection_marks:
            page["selection_marks"] = azure_selection_marks[page_num]
        if page_num in azure_tables_by_page:
            page["tables"] = azure_tables_by_page[page_num]
        page_marks = page.get("selection_marks") or []
        page_cell_entries = [
            (table["table_id"], cell)
            for table in (page.get("tables") or [])
            for cell in table["cells"]
            if cell.get("bbox_norm")
        ]

        per_reader_verdicts = {}
        for name in reader_names:
            units = list(reader_page_units.get(name, {}).get(page_num, []))
            per_reader_verdicts[name] = match_reader_to_page(surya_texts, units)
        if azure_path:
            units = [w[0] for w in azure_word_pages.get(page_num, [])]
            per_reader_verdicts["azure"] = match_reader_to_page(surya_texts, units)

        for i, line in enumerate(lines):
            agreed, dissent, absent = [], [], []
            for name in all_reader_names:
                verdict, text, _pos = per_reader_verdicts.get(name, {}).get(i, ("absent", None, None))
                if verdict == "agree":
                    agreed.append(name)
                elif verdict == "dissent":
                    dissent.append({"reader": name, "text": text})
                else:
                    absent.append(name)

            if "mineru" in per_reader_verdicts:
                mineru_verdict, _mineru_text, mineru_pos = per_reader_verdicts["mineru"].get(
                    i, ("absent", None, None)
                )
                if mineru_verdict in ("agree", "dissent") and mineru_pos is not None:
                    scores = mineru_page_scores.get(page_num, [])
                    if mineru_pos < len(scores) and scores[mineru_pos] is not None:
                        line["layout_score"] = scores[mineru_pos]

            line["agreement"] = {
                "m": m,
                "n": len(agreed),
                "agreed": agreed,
                "dissent": dissent,
                "absent": absent,
                "method": MATCH_METHOD if m > 0 else "none",
            }
            if len(normalize(line["text"])) <= SHORT_LINE_MAX_LEN:
                line["agreement"]["match_quality"] = "low"

            line["cell"] = None
            if page_cell_entries and line.get("bbox_norm"):
                center = bbox_norm_center(line["bbox_norm"])
                for table_id, cell in page_cell_entries:
                    if point_in_bbox_norm(center, cell["bbox_norm"]):
                        line["cell"] = {"table_id": table_id, "row": cell["row"], "col": cell["col"]}
                        break

            line["selection_mark"] = None
            if page_marks and line.get("bbox_norm"):
                center = bbox_norm_center(line["bbox_norm"])
                best, best_dist = None, None
                for mark in page_marks:
                    mx, my = bbox_norm_center(mark["bbox_norm"])
                    dist = ((center[0] - mx) ** 2 + (center[1] - my) ** 2) ** 0.5
                    if dist <= SELECTION_MARK_PROXIMITY_NORM and (best_dist is None or dist < best_dist):
                        best, best_dist = mark, dist
                if best:
                    line["selection_mark"] = {"state": best["state"], "confidence": best["confidence"]}

        # Reading order: try each reader in READER_PRIORITY, first one with any match on this
        # page wins -- see assign_reading_order for how unmatched lines get interpolated in.
        for reader_name in READER_PRIORITY:
            if reader_name not in per_reader_verdicts:
                continue
            primary_matches = {
                i: pos
                for i, (verdict, _text, pos) in per_reader_verdicts[reader_name].items()
                if pos is not None
            }
            if primary_matches:
                assign_reading_order(lines, primary_matches)
                break

        page["reader_pages"] = {name: page_num for name in all_reader_names}

    canonical["backend"] = backend
    canonical["readers"] = reader_names
    canonical["azure"] = bool(azure_path)
    canonical["stem"] = Path(results_json_path).parent.name
    canonical["match_method"] = MATCH_METHOD if m > 0 else "none"

    return canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_json")
    parser.add_argument("out_canonical")
    parser.add_argument("--stem", default=None)
    parser.add_argument("--reader", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--azure", default=None)
    parser.add_argument("--backend", default="surya-only", choices=["remote", "local", "surya-only"])
    args = parser.parse_args()

    readers = {}
    for spec in args.reader:
        if "=" not in spec:
            print(f"--reader must be NAME=PATH, got: {spec}", file=sys.stderr)
            sys.exit(2)
        name, path = spec.split("=", 1)
        readers[name] = path

    canonical = build_canonical(args.results_json, args.backend, readers, args.azure)
    if args.stem:
        canonical["stem"] = args.stem

    with open(args.out_canonical, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2)


if __name__ == "__main__":
    main()
