"""Rewrite an Azure layout JSON's page numbers from extract-relative back to source-relative.

Azure numbers pages 1..N in whatever PDF it was handed. When that PDF is a qpdf extract of a
subset of a larger document, every `pageNumber` in the result refers to the extract, not the
original. merge-canonical.py's adapt_azure() keys selection_marks and tables_by_page directly on
those numbers and merges them onto canonical pages of the same number -- so without this rewrite,
original page 204's tables get attached to canonical page 1.

`pageNumber` appears in several places in analyzeResult (pages[], tables[].boundingRegions[],
tables[].cells[].boundingRegions[], paragraphs[], figures[], sections[], ...), and the exact set
varies with the document. Rather than enumerate them, this walks the whole structure and rewrites
every "pageNumber" key it finds, which is safe because the key means the same thing everywhere in
this schema.

Writes a new file; never edits in place, so a bad map can't destroy the paid-for result.

Usage: renumber-azure-pages.py <in.layout.json> <page-map.json> <out.layout.json>
  page-map.json: JSON list of original page numbers, in extract order.
                 element i (0-based) is the source page of extract page i+1.
"""

import json
import sys


def walk(node, mapping, stats):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pageNumber" and isinstance(v, int):
                if v not in mapping:
                    raise SystemExit(
                        f"[renumber] extract page {v} not in page map (map covers "
                        f"1..{max(mapping)}) -- wrong map for this layout file?"
                    )
                node[k] = mapping[v]
                stats["rewritten"] += 1
            else:
                walk(v, mapping, stats)
    elif isinstance(node, list):
        for item in node:
            walk(item, mapping, stats)


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    in_path, map_path, out_path = sys.argv[1:4]

    data = json.load(open(in_path))
    originals = json.load(open(map_path))
    mapping = {i + 1: orig for i, orig in enumerate(originals)}

    ar = data.get("analyzeResult", data)
    n_pages = len(ar.get("pages", []))
    if n_pages != len(originals):
        raise SystemExit(
            f"[renumber] layout has {n_pages} pages but page map has {len(originals)} entries "
            f"-- refusing to guess the correspondence"
        )

    before = [p.get("pageNumber") for p in ar.get("pages", [])[:5]]
    stats = {"rewritten": 0}
    walk(data, mapping, stats)
    after = [p.get("pageNumber") for p in ar.get("pages", [])[:5]]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    print(f"[renumber] {stats['rewritten']} pageNumber values rewritten across {n_pages} pages")
    print(f"[renumber] first five: {before} -> {after}")
    print(f"[renumber] wrote {out_path}")


if __name__ == "__main__":
    main()
