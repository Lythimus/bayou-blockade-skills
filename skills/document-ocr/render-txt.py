"""Render the canonical OCR JSON (see references/output-schema.md) into searchable .txt.

Replaces the old results.json -> make-pdf-reportlab.py -> pdftotext round-trip. Reading order
comes from the canonical file's own line order (already resolved by merge-canonical.py from the
highest-priority reader present); if no canonical file exists yet, this script derives a
degenerate zero-reader canonical structure directly from Surya's results.json and falls back to
sorting lines by (page, y, x). Stdlib only -- no reportlab, no pdftotext, no poppler.

Usage: render-txt.py <results.json> <out.txt> [canonical.json]

Emits a page marker line ("=== PAGE <n> ===") at every page boundary, including pages with zero
text lines, so page numbers never shift after a blank/separator page.
"""

import json
import sys


def load_results_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def surya_to_canonical(results):
    """Degenerate zero-reader canonical structure, built directly from a Surya results.json.

    Mirrors the shape merge-canonical.py produces, but with agreement.m = 0 on every line and no
    reader contributions -- this is the surya-only fallback path, used when
    $WORK/canonical/<stem>.json does not exist (older run, or before Phase 2's merge step runs).
    """
    pages = []
    for _stem, content_list in results.items():
        if not isinstance(content_list, list):
            continue
        for idx, block in enumerate(content_list):
            page_num = block.get("page", idx + 1)
            image_bbox = block.get("image_bbox") or [0, 0, 0, 0]
            width = image_bbox[2] - image_bbox[0]
            height = image_bbox[3] - image_bbox[1]
            frame = {"width": width, "height": height, "unit": "px"}

            lines = []
            text_lines = block.get("text_lines") or []
            for i, line in enumerate(text_lines):
                bbox = line.get("bbox", [0, 0, 0, 0])
                if width > 0 and height > 0:
                    bbox_norm = [
                        bbox[0] / width,
                        bbox[1] / height,
                        bbox[2] / width,
                        bbox[3] / height,
                    ]
                else:
                    bbox_norm = [0, 0, 0, 0]
                lines.append(
                    {
                        "line_id": f"p{page_num}-l{i}",
                        "text": line.get("text", ""),
                        "backend": "surya",
                        "surya_ref": i,
                        "bbox": bbox,
                        "bbox_norm": bbox_norm,
                        "bbox_frame": "surya-px",
                        "confidence": line.get("confidence"),
                        "confidence_source": "surya" if line.get("confidence") is not None else None,
                        "layout_score": None,
                        "agreement": {
                            "m": 0,
                            "n": 0,
                            "agreed": [],
                            "dissent": [],
                            "absent": [],
                            "method": "none",
                        },
                        "cell": None,
                        "selection_mark": None,
                    }
                )

            pages.append(
                {
                    "page": page_num,
                    "frame": frame,
                    "selection_marks": [],
                    "tables": [],
                    "reader_pages": {},
                    "lines": lines,
                }
            )

    pages.sort(key=lambda p: p["page"])
    return {"stem": None, "backend": "surya-only", "readers": [], "azure": False, "pages": pages}


def load_canonical(canonical_path, results_path):
    if canonical_path:
        try:
            with open(canonical_path, "r", encoding="utf-8") as f:
                canonical = json.load(f)
            if canonical.get("pages") is not None:
                return canonical
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    results = load_results_json(results_path)
    return surya_to_canonical(results)


def reading_order_key(line):
    """Fallback sort when a page carries no reader-assigned order: (y0, x0) of bbox_norm."""
    bbox_norm = line.get("bbox_norm") or [0, 0, 0, 0]
    return (bbox_norm[1], bbox_norm[0])


def sorted_page_lines(page):
    """The exact per-page line order render() writes to .txt.

    Pulled out as its own function so ocr-verify's pull-opinions.py can recover which canonical
    line a given rendered .txt line number came from, by reproducing this same order rather than
    re-deriving it -- any drift between the two would silently point evidence at the wrong line.
    """
    lines = page.get("lines") or []
    if any("reading_order" in line for line in lines):
        return sorted(lines, key=lambda line: line.get("reading_order", 0))
    return sorted(lines, key=reading_order_key)


def render(canonical, out_path):
    with open(out_path, "w", encoding="utf-8") as out:
        for page in sorted(canonical.get("pages", []), key=lambda p: p["page"]):
            out.write(f"=== PAGE {page['page']} ===\n")
            for line in sorted_page_lines(page):
                out.write(line.get("text", "") + "\n")


def line_number_map(canonical):
    """{line_id: 1-based .txt line number}, computed by simulating render()'s own loop without
    writing a file.

    Lets a consumer (ocr-validate's run-checks.py) cite `<stem>.txt:<line>` in a verify_cmd
    without needing the actual rendered .txt on disk -- the mapping is a pure function of
    canonical.json, identical to what render() would produce, so the two can never drift as long
    as both go through this same function and sorted_page_lines().
    """
    mapping = {}
    line_no = 0
    for page in sorted(canonical.get("pages", []), key=lambda p: p["page"]):
        line_no += 1  # the "=== PAGE n ===" marker line
        for line in sorted_page_lines(page):
            line_no += 1
            if line.get("line_id"):
                mapping[line["line_id"]] = line_no
    return mapping


def main():
    if len(sys.argv) not in (3, 4):
        print("Usage: render-txt.py <results.json> <out.txt> [canonical.json]", file=sys.stderr)
        sys.exit(1)

    results_path = sys.argv[1]
    out_path = sys.argv[2]
    canonical_path = sys.argv[3] if len(sys.argv) == 4 else None

    canonical = load_canonical(canonical_path, results_path)
    render(canonical, out_path)


if __name__ == "__main__":
    main()
