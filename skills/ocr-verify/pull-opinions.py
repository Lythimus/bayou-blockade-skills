"""Given a rendered .txt line number, recover the canonical OCR line it came from and pull every
backend's opinion on it plus its neighbors -- the evidence-gathering step behind ocr-verify's
fixed output block (see SKILL.md).

Usage: pull-opinions.py <work-dir> <stem> <txt-file> <txt-line> [--context 3]

- <work-dir>  the OCR pipeline's $WORK dir (holds results/<stem>/results.json,
  canonical/<stem>.json, azure/<stem>.layout.json)
- <stem>      the document stem (matches <stem>.pdf / <stem>.txt)
- <txt-file>  the rendered .txt file that <txt-line> is a line number into (usually
  $OUT_TXT/<stem>.txt, but any .txt rendered from this stem's canonical file works)
- <txt-line>  1-based line number, e.g. from `rg -n`

Locates the page marker ("=== PAGE n ===", see render-txt.py) at or before <txt-line> by
scanning backward, then re-derives the exact per-page line order render-txt.py used
(render_txt.sorted_page_lines, imported directly so the two can never drift) to recover which
canonical line record <txt-line> is. Verifies the pick against the .txt file's own text before
trusting it -- a silent off-by-one here would hand a downstream reader evidence for the wrong
line.

Prints one JSON object to stdout: {page, target_line_id, lines: [...]}, one entry per line in
[<target> - context, <target> + context] (clamped to the page), each carrying the full canonical
record plus, when this document has an Azure pass, that line's own geometrically-matched Azure
word text/confidence (Azure words carry no line-level identity of their own -- see
output-schema.md -- so this is computed here via bbox_norm overlap, the schema's only
cross-backend-comparable field, rather than trusted from anywhere in canonical.json).

Reads only canonical.json + the raw Azure layout file, per output-schema.md -- olmocr/chandra/
mineru's own raw outputs are already folded into canonical.json's `agreement`; this script never
touches $WORK/readers/*.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCUMENT_OCR_DIR = SCRIPT_DIR.parent / "document-ocr"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render_txt = _load_module("render_txt", DOCUMENT_OCR_DIR / "render-txt.py")
merge_canonical = _load_module("merge_canonical", DOCUMENT_OCR_DIR / "merge-canonical.py")

PAGE_MARKER_PREFIX = "=== PAGE "


def find_page_marker(txt_lines, target_line_idx):
    """Scan backward from target_line_idx (0-based) for the nearest page marker.

    Returns (page_num, marker_idx). Mirrors the plain backward-scan every consumer of this .txt
    format uses (see output-schema.md) -- no index is built, since a linear scan from any one
    citation is exactly the operation permit-analysis and ocr-verify both already do.
    """
    for i in range(target_line_idx, -1, -1):
        line = txt_lines[i]
        if line.startswith(PAGE_MARKER_PREFIX):
            try:
                page_num = int(line[len(PAGE_MARKER_PREFIX):].split(" ")[0])
            except ValueError:
                continue
            return page_num, i
    raise SystemExit(f"[OCR] verify failed: no page marker found before line {target_line_idx + 1}")


def locate_canonical_line(canonical, txt_lines, target_line_idx):
    """Return (page_dict, ordered_lines, ordinal, line_record) for the .txt line at
    target_line_idx (0-based).
    """
    page_num, marker_idx = find_page_marker(txt_lines, target_line_idx)
    ordinal = target_line_idx - marker_idx - 1
    if ordinal < 0:
        raise SystemExit(f"[OCR] verify failed: line {target_line_idx + 1} is a page marker itself")

    page = next((p for p in canonical.get("pages", []) if p["page"] == page_num), None)
    if page is None:
        raise SystemExit(f"[OCR] verify failed: canonical.json has no page {page_num}")

    ordered_lines = render_txt.sorted_page_lines(page)
    if ordinal >= len(ordered_lines):
        raise SystemExit(
            f"[OCR] verify failed: page {page_num} has {len(ordered_lines)} lines, "
            f"but line {target_line_idx + 1} implies ordinal {ordinal}"
        )

    candidate = ordered_lines[ordinal]
    expected_text = txt_lines[target_line_idx].rstrip("\n")
    if candidate.get("text", "") != expected_text:
        # Ordinal landed on the wrong line (e.g. canonical.json regenerated since the .txt was
        # rendered). Fall back to a unique text match on this page before giving up -- guessing
        # silently here would hand a downstream reader evidence for the wrong citation.
        matches = [l for l in ordered_lines if l.get("text", "") == expected_text]
        if len(matches) == 1:
            candidate = matches[0]
            ordinal = ordered_lines.index(candidate)
        else:
            raise SystemExit(
                f"[OCR] verify failed: line {target_line_idx + 1} ordinal mismatch -- "
                f"canonical page {page_num} line {ordinal} reads {candidate.get('text', '')!r}, "
                f".txt reads {expected_text!r}, and {len(matches)} candidate(s) share that exact "
                f"text on this page. canonical.json may be stale relative to this .txt "
                f"(--rerender resyncs them)."
            )

    return page, ordered_lines, ordinal, candidate


# --- Azure word-level evidence, computed geometrically (see output-schema.md: Azure words carry
# no line identity of their own, so a canonical line's Azure "opinion" is whichever words overlap
# its bbox_norm on the same page, not anything stored on the line record itself). -------------


def bbox_norm_overlaps(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def azure_words_for_line(azure_path, page_num, line_bbox_norm):
    """Words from the raw Azure layout file whose own bbox_norm overlaps this line's bbox_norm.

    Recomputes each word's bbox_norm from its polygon directly (adapt_azure's word_pages only
    carries content+confidence, not geometry, since that's all the merge needs) -- reusing
    merge_canonical.polygon_to_bbox_norm so the normalization is identical to the one already
    used, and verified, for selection marks and table cells.
    """
    with open(azure_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = data.get("analyzeResult", data)

    for page in result.get("pages", []):
        if int(page.get("pageNumber", 1)) != page_num:
            continue
        width = page.get("width", 1) or 1
        height = page.get("height", 1) or 1
        matched = []
        for word in page.get("words", []):
            word_bbox = merge_canonical.polygon_to_bbox_norm(word.get("polygon", []), width, height)
            if bbox_norm_overlaps(word_bbox, line_bbox_norm):
                matched.append((word.get("content", ""), word.get("confidence")))
        return matched
    return []


def build_line_record(line, page_num, azure_path, has_azure):
    record = {
        "line_id": line.get("line_id"),
        "text": line.get("text"),
        "page": page_num,
        "bbox": line.get("bbox"),
        "bbox_norm": line.get("bbox_norm"),
        "confidence": line.get("confidence"),
        "confidence_source": line.get("confidence_source"),
        "layout_score": line.get("layout_score"),
        "agreement": line.get("agreement"),
        "cell": line.get("cell"),
        "selection_mark": line.get("selection_mark"),
    }
    if has_azure and azure_path and line.get("bbox_norm"):
        words = azure_words_for_line(azure_path, page_num, line["bbox_norm"])
        if words:
            record["azure_words"] = {
                "text": " ".join(w[0] for w in words),
                "confidences": [w[1] for w in words if w[1] is not None],
            }
        else:
            record["azure_words"] = None  # ran, but nothing overlapped this line's region
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir")
    parser.add_argument("stem")
    parser.add_argument("txt_file")
    parser.add_argument("txt_line", type=int)
    parser.add_argument("--context", type=int, default=3)
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    results_path = work_dir / "results" / args.stem / "results.json"
    canonical_path = work_dir / "canonical" / f"{args.stem}.json"
    azure_path = work_dir / "azure" / f"{args.stem}.layout.json"

    if not results_path.exists():
        raise SystemExit(f"[OCR] verify failed: no results.json at {results_path}")

    canonical = render_txt.load_canonical(
        str(canonical_path) if canonical_path.exists() else None, str(results_path)
    )

    with open(args.txt_file, "r", encoding="utf-8") as f:
        txt_lines = f.read().split("\n")

    target_idx = args.txt_line - 1
    if target_idx < 0 or target_idx >= len(txt_lines):
        raise SystemExit(f"[OCR] verify failed: {args.txt_file} has no line {args.txt_line}")

    page, ordered_lines, ordinal, target_line = locate_canonical_line(canonical, txt_lines, target_idx)

    has_azure = bool(canonical.get("azure")) and azure_path.exists()

    lo = max(0, ordinal - args.context)
    hi = min(len(ordered_lines) - 1, ordinal + args.context)
    lines_out = [
        build_line_record(ordered_lines[i], page["page"], str(azure_path), has_azure)
        for i in range(lo, hi + 1)
    ]

    output = {
        "stem": args.stem,
        "page": page["page"],
        "target_ordinal": ordinal,
        "target_line_id": target_line.get("line_id"),
        "readers": canonical.get("readers", []),
        "azure": has_azure,
        "lines": lines_out,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
