"""Detect a reader that ran, didn't crash, and returned structurally-valid emptiness.

merge-canonical.py's per-line `agreement` record can only capture what a reader *did*
match -- if a reader silently elides a whole table body (well-formed output, closing tags,
correct notes, just no rows), nothing in the merge pipeline notices: the file is non-empty,
the JSON/JSONL parses, the manifest entry is valid. Two independent signals catch this after
the fact, both run directly over already-merged canonical/*.json (and each reader's raw
output), so this never needs an OCR re-run:

  1. Coverage math: a page where Surya found >= SURYA_LINE_THRESHOLD lines but a reader's
     agreement.absent rate on that page is >= ABSENT_RATE_THRESHOLD. Usually this means the
     reader did not read the page -- but it has a known false-positive mode on dense tables: a
     reader that emits one HTML row per table row (e.g. "<tr><td>a</td><td>b</td>...</tr>")
     collapses many of Surya's individual per-cell lines into one block, which fuzzy-matches
     poorly even though every value is present verbatim in the reader's raw output and makes it
     into the rendered .txt. Confirmed on the Hyundai POSCO fixture: doc 01 pages 50/64/68 flag
     at 90%+ absent with zero actual data loss. Treat a coverage-only flag (no corresponding
     elision hit) as "needs a look," not "confirmed broken" -- spot-check the reader's raw output
     for that page (adapt_olmocr/adapt_chandra/adapt_mineru, same as this script uses) before
     concluding content was dropped.
  2. Elision grep: a reader's raw output announcing its own omission via an HTML comment
     placeholder (e.g. "<!-- Table rows follow -->"). Narrower than the coverage math -- it
     only fires when the reader *announces* the elision -- but zero-false-positive when it
     does, and is the stronger signal of the two: treat an elision hit as confirmed broken.

Usage:
  check-reader-coverage.py <work-dir> [--stem <stem>...]

<work-dir> is the pipeline's $WORK directory (contains canonical/, remote-out/, mineru/).
With no --stem, checks every file in canonical/*.json. Informational only: always exits 0,
and never modifies canonical.json -- writes its machine-readable findings to a sibling
<work-dir>/canonical/<stem>.coverage.json.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("merge_canonical", SCRIPT_DIR / "merge-canonical.py")
_merge_canonical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_merge_canonical)

# Starting thresholds -- tuned against the Hyundai POSCO fixture (see plan Verification):
# doc 04 pages 311/313/315/317/319/322/323/324 and 108 pages in doc 01 must flag; doc 09-13
# (clean prose) must not.
SURYA_LINE_THRESHOLD = 50
ABSENT_RATE_THRESHOLD = 0.90

ELISION_RE = re.compile(
    r"<!--[^>]*\b(?:rows?|data|omitted|follow|content|continue[sd]?)\b[^>]*-->",
    re.IGNORECASE,
)

# Only readers with an adapter that recovers per-page text can be grepped for elision
# placeholders -- Azure returns structured layout, not summarized prose, so it isn't checked.
READER_ADAPTERS = {
    "olmocr": _merge_canonical.adapt_olmocr,
    "chandra": _merge_canonical.adapt_chandra,
    "mineru": _merge_canonical.adapt_mineru,
}


def check_coverage(canonical_path):
    """Per-page, per-reader: flag when Surya lines are plentiful but a reader saw ~none.

    Deliberately excludes "azure": unlike olmocr/chandra/mineru, Azure is additive and often
    page-scoped (a targeted extract, not a full-document run) -- output-schema.md's own
    `readers` field definition excludes it for the same reason. A page outside Azure's
    submitted range legitimately shows every line "absent" for azure; that is not a reader
    failure, so folding it into this math would flag the vast majority of any partially-Azure'd
    document.
    """
    data = json.loads(canonical_path.read_text(encoding="utf-8"))
    stem = data.get("stem", canonical_path.stem)
    readers = list(data.get("readers", []))

    flags = []
    for page in data.get("pages", []):
        lines = page.get("lines", [])
        n_lines = len(lines)
        if n_lines < SURYA_LINE_THRESHOLD:
            continue
        for reader in readers:
            absent = sum(
                1 for line in lines if reader in line.get("agreement", {}).get("absent", [])
            )
            rate = absent / n_lines
            if rate >= ABSENT_RATE_THRESHOLD:
                flags.append(
                    {
                        "stem": stem,
                        "page": page.get("page"),
                        "reader": reader,
                        "surya_lines": n_lines,
                        "absent": absent,
                        "absent_rate": round(rate, 3),
                    }
                )
    return flags


def raw_reader_paths(work_dir, stem):
    """Best-effort discovery of each reader's raw output file for a stem, across backend tiers."""
    paths = {}

    manifest = work_dir / "remote-out" / stem / "manifest.tsv"
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            reader, relpath = parts
            if reader == "surya":
                continue
            full = work_dir / "remote-out" / stem / relpath
            if full.is_file():
                paths[reader] = full

    mineru_dir = work_dir / "mineru" / stem
    if mineru_dir.is_dir():
        match = next(mineru_dir.rglob(f"{stem}_middle.json"), None)
        if match is not None:
            paths["mineru"] = match

    return paths


def check_elision(work_dir, stem):
    """Per-reader raw output: flag pages whose recovered text announces its own omission."""
    flags = []
    for reader, path in raw_reader_paths(work_dir, stem).items():
        adapter = READER_ADAPTERS.get(reader)
        if adapter is None:
            continue
        try:
            pages = adapter(path)
        except Exception as exc:
            print(
                f"[coverage] {stem}: could not parse {reader} raw output ({path}): {exc}",
                file=sys.stderr,
            )
            continue
        for page_num, units in pages.items():
            hits = len(ELISION_RE.findall("\n".join(units)))
            if hits:
                flags.append(
                    {"stem": stem, "page": page_num, "reader": reader, "elision_hits": hits}
                )
    return flags


def check_document(work_dir, canonical_path):
    stem = canonical_path.stem
    coverage_flags = check_coverage(canonical_path)
    elision_flags = check_elision(work_dir, stem)

    cov_pages = sorted({f["page"] for f in coverage_flags})
    el_pages = sorted({f["page"] for f in elision_flags})

    if cov_pages or el_pages:
        print(
            f"[coverage] {stem}: {len(cov_pages)} page(s) flagged by coverage math, "
            f"{len(el_pages)} page(s) flagged by elision grep"
        )
        if cov_pages:
            print(f"[coverage] {stem}: coverage-flagged pages: {cov_pages}")
        if el_pages:
            print(f"[coverage] {stem}: elision-flagged pages: {el_pages}")
    else:
        print(f"[coverage] {stem}: clean")

    out_path = work_dir / "canonical" / f"{stem}.coverage.json"
    out_path.write_text(
        json.dumps({"stem": stem, "coverage": coverage_flags, "elision": elision_flags}, indent=2),
        encoding="utf-8",
    )
    return coverage_flags, elision_flags


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("work_dir")
    parser.add_argument(
        "--stem",
        action="append",
        default=None,
        help="Limit to this stem (repeatable); default is every canonical/*.json",
    )
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    canonical_dir = work_dir / "canonical"
    if not canonical_dir.is_dir():
        raise SystemExit(f"[coverage] no canonical/ directory under {work_dir}")

    if args.stem:
        canonical_paths = [canonical_dir / f"{s}.json" for s in args.stem]
        missing = [p for p in canonical_paths if not p.is_file()]
        if missing:
            raise SystemExit(
                "[coverage] missing canonical file(s): "
                + ", ".join(str(m) for m in missing)
            )
    else:
        canonical_paths = sorted(
            p for p in canonical_dir.glob("*.json") if p.suffixes == [".json"]
        )

    total_coverage = 0
    total_elision = 0
    for canonical_path in canonical_paths:
        coverage_flags, elision_flags = check_document(work_dir, canonical_path)
        total_coverage += len(coverage_flags)
        total_elision += len(elision_flags)

    if total_coverage or total_elision:
        print(
            f"[coverage] {total_coverage} coverage flag(s), {total_elision} elision flag(s) "
            f"across {len(canonical_paths)} document(s)"
        )


if __name__ == "__main__":
    main()
