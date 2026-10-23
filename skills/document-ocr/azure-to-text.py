"""Render an Azure Document Intelligence prebuilt-layout result as page-marked text with real tables.

Usage: azure-to-text.py <stem>.layout.json <out>.azure.txt

The merge into canonical.json only borrows Azure's cells and checkboxes as metadata on Surya's
lines; the main <stem>.txt is still Surya's one-cell-per-line reading. This file is what makes a
table readable: each table is emitted as pipe-delimited rows, so a value stays on the same line
as its row label.

Non-table paragraphs are emitted in Azure's own paragraph order. Each table is emitted once per
page it touches, at the point where its first cell would have appeared in that order -- emitting
cells as ordinary paragraphs interleaves them with the prose around them.

Row format: a literal "|" inside a cell is written "\\|" (Azure sometimes reads a roman numeral I
as a pipe), and merged cells are fanned out with continuation markers -- "^" continues the cell
above, "<" the cell to the left -- so a blank always means an empty cell, never "see above", and
every row in a table block has the same number of fields.

`=== PAGE n ===` markers use Azure's pageNumber, which is the source document's page number even
for a `--pages` subset run, so they line up with the Surya .txt's markers. Pages outside the
subset are simply absent. Line numbers are unrelated to <stem>.txt's: this is a second,
independent reading (Azure's OCR, not Surya's), cited as its own file.
"""

import bisect
import json
import sys


def flat(s):
    return " ".join(s.split())


def render(ar):
    pages = [p["pageNumber"] for p in ar.get("pages", [])]
    tables = ar.get("tables", [])

    # Character intervals of each table's cells, so a paragraph can be attributed to its table.
    spans = []
    for ti, t in enumerate(tables):
        for c in t["cells"]:
            for sp in c.get("spans", []):
                spans.append((sp["offset"], sp["offset"] + sp["length"], ti))
    spans.sort()
    span_starts = [s[0] for s in spans]

    def table_of(par):
        if not par.get("spans"):
            return None
        off = par["spans"][0]["offset"]
        i = bisect.bisect_right(span_starts, off) - 1
        if i >= 0 and spans[i][0] <= off < spans[i][1]:
            return spans[i][2]
        return None

    def first_page(c):
        regs = c.get("boundingRegions") or []
        return regs[0]["pageNumber"] if regs else None

    def table_rows(t, page):
        # A cell belongs to the page where it starts, so a table split across pages prints each
        # part under its own page marker.
        rowset = sorted({c["rowIndex"] for c in t["cells"] if first_page(c) == page})
        if not rowset:
            return []
        grid = {r: {} for r in rowset}
        for c in t["cells"]:
            r0, c0 = c["rowIndex"], c["columnIndex"]
            rs, cs = c.get("rowSpan", 1), c.get("columnSpan", 1)
            text = flat(c.get("content", "")).replace("|", "\\|")
            for r in range(r0, r0 + rs):
                if r not in grid:
                    continue
                for ci in range(c0, c0 + cs):
                    if r == r0 and ci == c0 and first_page(c) == page:
                        grid[r][ci] = text
                    else:
                        grid[r][ci] = "^" if r != r0 else "<"
        ncols = t["columnCount"]
        return ["| " + " | ".join(grid[r].get(ci, "") for ci in range(ncols)) + " |" for r in rowset]

    out = {p: [] for p in pages}
    emitted = set()
    for par in ar.get("paragraphs", []):
        regions = par.get("boundingRegions") or []
        page = regions[0]["pageNumber"] if regions else (pages[0] if pages else None)
        if page not in out:
            continue
        ti = table_of(par)
        if ti is None:
            out[page].append(flat(par["content"]))
            continue
        if (ti, page) in emitted:
            continue
        emitted.add((ti, page))
        rows = table_rows(tables[ti], page)
        if rows:
            out[page].append(f"[table {ti + 1}]")
            out[page].extend(rows)
            out[page].append("[/table]")

    lines = []
    for p in pages:
        lines.append(f"=== PAGE {p} ===")
        lines.extend(out[p])
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        doc = json.load(f)
    ar = doc.get("analyzeResult", doc)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(render(ar))
    print(f"[azure-to-text] {len(ar.get('pages', []))} pages, {len(ar.get('tables', []))} tables -> {dst}")


if __name__ == "__main__":
    main()
