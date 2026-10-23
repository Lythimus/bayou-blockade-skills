"""Flag the pages of an OCRed document that look like tables, so Azure can be sent just those.

Surya reads a table one cell per line and orders lines by position, so on a table page a value can
land next to the wrong label in the rendered .txt (a column of "0.00"s interleaved one row off from
their row labels is the typical failure). Azure `prebuilt-layout` returns real row/column cells.
This script decides where that is worth paying for, from Surya's own geometry -- no model call, so
it is free, deterministic, and runs on every tier (results.json exists on all of them).

Signal: group a page's lines into visual rows (y-centres within 0.6 x the median line height).
A "cell row" has 2+ lines side by side, at least one under 30% of the page width -- which excludes
two-column prose, where both halves are wide. A page is tabular when it has >= 4 cell rows whose
cells' left edges line up into >= 2 recurring columns (an x-cluster within 2% of page width with
3+ members). A page also counts when one row holds >= 4 narrow cells and at least 2 of them have
a narrow line starting under them within the next 6 rows -- the header of a short table whose
wrapped data rows never form clean visual rows (a two-row corrective-action table is the usual
case). The "below" requirement is what keeps justified prose out: Surya sometimes splits a
justified line into single words, and those words line up with the letterhead above, not with
anything under them. `strong` needs >= 3 recurring columns.

Measured against Azure's own table detection on 396 pages of scanned regulatory filings --
excess-emission summaries, flare/deviation reports, monitoring reports, inspection forms: recall
0.94, precision 0.92 against tables of >= 2 rows x >= 2 cols (0.95 / 0.87 at >= 3 rows).
Thresholds were tuned on that same set, so treat the numbers as optimistic for very different
layouts. Most "false positives" were
genuinely tabular (aligned label/value forms) where Azure chose not to emit a table. Misses are
mostly continuation pages carrying a few rows of a table that started on the previous page;
--neighbors adds the pages on either side of each hit to catch those, at the cost of selecting
most of a table-heavy document.

Usage:
  detect-table-pages.py <WORK_DIR> [--stem STEM ...] [--neighbors] [--whole-fraction 0.5]

Writes $WORK/tables/<stem>.json and prints one line per stem:
  [tables] <stem>: <k>/<n> pages look tabular (<spec>) -> azure: whole|pages|none
where <spec> is ready for `azure-layout.py --pages`. "whole" means enough of the document is
tabular (>= --whole-fraction) that submitting all of it is simpler than a page subset.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROW_TOL = 0.6  # x median line height: max y-centre distance for two lines to share a row
NARROW = 0.30  # x page width: a cell row needs one line narrower than this
COL_TOL = 0.02  # x page width: left edges within this distance are the same column
MIN_ROWS = 4
MIN_COLS = 2
HEADER_CELLS = 4
HEADER_LOOKAHEAD = 6  # rows below a header searched for cells aligned under it
HEADER_ALIGNED = 2
STRONG_COLS = 3

NUMERIC_RE = re.compile(r"^[\s$(<>~+-]*[\d.,/:%-]*\d[\d.,/:%-]*[\s%)a-zA-Z/]{0,8}$")


def visual_rows(lines):
    lines = [l for l in lines if l.get("bbox") and (l.get("text") or "").strip()]
    if not lines:
        return []
    median_h = statistics.median(l["bbox"][3] - l["bbox"][1] for l in lines) or 1
    lines.sort(key=lambda l: (l["bbox"][1] + l["bbox"][3]) / 2)
    rows, cur, cur_y = [], [], None
    for l in lines:
        y = (l["bbox"][1] + l["bbox"][3]) / 2
        if cur and abs(y - cur_y) <= ROW_TOL * median_h:
            cur.append(l)
            cur_y = sum((x["bbox"][1] + x["bbox"][3]) / 2 for x in cur) / len(cur)
        else:
            if cur:
                rows.append(cur)
            cur, cur_y = [l], y
    if cur:
        rows.append(cur)
    return rows


def page_features(page):
    bbox = page.get("image_bbox") or [0, 0, 1, 1]
    width = (bbox[2] - bbox[0]) or 1
    rows = visual_rows(page.get("text_lines") or [])
    n_lines = sum(len(r) for r in rows)
    cell_rows = [
        r for r in rows
        if len(r) >= 2 and min(l["bbox"][2] - l["bbox"][0] for l in r) < NARROW * width
    ]
    lefts = sorted(l["bbox"][0] for r in cell_rows for l in r)
    clusters = []
    for x in lefts:
        if clusters and x - clusters[-1][-1] <= COL_TOL * width:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    columns = sum(1 for c in clusters if len(c) >= 3)
    # Justified prose can come back from Surya as one line per word, which looks like a row of
    # narrow cells; what separates a real header is that the rows just below it line up under it.
    def aligned_below(idx):
        below = [
            l["bbox"][0] for r in rows[idx + 1 : idx + 1 + HEADER_LOOKAHEAD] for l in r
            if l["bbox"][2] - l["bbox"][0] < NARROW * width
        ]
        cells = sorted(rows[idx], key=lambda l: l["bbox"][0])[1:]
        return sum(
            1 for l in cells if any(abs(l["bbox"][0] - x) <= COL_TOL * width for x in below)
        )

    header_row = any(
        len(r) >= HEADER_CELLS
        and max(l["bbox"][2] - l["bbox"][0] for l in r) < NARROW * width
        and aligned_below(i) >= HEADER_ALIGNED
        for i, r in enumerate(rows)
    )
    numeric = sum(1 for r in rows for l in r if NUMERIC_RE.match(l["text"].strip()))
    return {
        "lines": n_lines,
        "rows": len(rows),
        "cell_rows": len(cell_rows),
        "columns": columns,
        "header_row": header_row,
        "numeric_frac": round(numeric / n_lines, 3) if n_lines else 0.0,
    }


def to_spec(pages):
    """[3, 7, 8, 9, 14] -> "3,7-9,14" (the service's `pages` syntax)."""
    parts, start, prev = [], None, None
    for p in sorted(pages):
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            parts.append(f"{start}-{prev}" if prev > start else str(start))
            start = prev = p
    if start is not None:
        parts.append(f"{start}-{prev}" if prev > start else str(start))
    return ",".join(parts)


def find_results(work, stem):
    # Surya's layout varies by version: some nest an extra "surya/" directory under results/.
    for p in (work / "results" / "surya" / stem / "results.json", work / "results" / stem / "results.json"):
        if p.is_file() and p.stat().st_size:
            return p
    return None


def detect(results_path, stem, neighbors, whole_fraction):
    data = json.loads(results_path.read_text(encoding="utf-8"))
    pages = data.get(stem) or next(iter(data.values()), [])
    n = len(pages)
    per_page, flagged, strong = [], [], []
    for i, page in enumerate(pages, start=1):
        num = int(page.get("page") or i)
        f = page_features(page)
        f["page"] = num
        f["tabular"] = (f["cell_rows"] >= MIN_ROWS and f["columns"] >= MIN_COLS) or f["header_row"]
        f["strong"] = f["tabular"] and f["columns"] >= STRONG_COLS
        per_page.append(f)
        if f["tabular"]:
            flagged.append(num)
        if f["strong"]:
            strong.append(num)

    selected = set(flagged)
    if neighbors:
        valid = {f["page"] for f in per_page}
        for p in flagged:
            selected |= {p - 1, p + 1} & valid
    selected = sorted(selected)

    if not selected:
        recommendation = "none"
    elif n and len(selected) / n >= whole_fraction:
        recommendation = "whole"
    else:
        recommendation = "pages"

    return {
        "stem": stem,
        "n_pages": n,
        "tabular_pages": flagged,
        "strong_pages": strong,
        "selected_pages": selected,
        "pages_spec": to_spec(selected),
        "neighbors": neighbors,
        "recommendation": recommendation,
        "per_page": per_page,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir")
    ap.add_argument("--stem", action="append", default=[])
    ap.add_argument("--neighbors", action="store_true", help="also select the pages next to each hit")
    ap.add_argument("--whole-fraction", type=float, default=0.5)
    args = ap.parse_args()

    work = Path(args.work_dir)
    stems = args.stem
    if not stems:
        stems = sorted(
            {p.parent.name for p in (work / "results").glob("*/results.json")}
            | {p.parent.name for p in (work / "results" / "surya").glob("*/results.json")}
        )
    out_dir = work / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)

    status = 0
    for stem in stems:
        results_path = find_results(work, stem)
        if not results_path:
            print(f"[tables] {stem}: no results.json under {work}/results -- skipped", file=sys.stderr)
            status = 1
            continue
        r = detect(results_path, stem, args.neighbors, args.whole_fraction)
        (out_dir / f"{stem}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        spec = f" ({r['pages_spec']})" if r["pages_spec"] else ""
        print(
            f"[tables] {stem}: {len(r['selected_pages'])}/{r['n_pages']} pages look tabular{spec} "
            f"-> azure: {r['recommendation']}"
        )
    sys.exit(status)


if __name__ == "__main__":
    main()
