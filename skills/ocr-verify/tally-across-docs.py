"""Tally how many times a value (and its near-neighbors) appear across every .txt in a package
-- the minority-reading rule from a real campaign incident (see references/failure-cases.md): a
single high-confidence OCR misread of a repeated-glyph run (e.g. a dropped digit) can look like a
genuine cross-document discrepancy until counted against every other citation of the same field.

Usage: tally-across-docs.py <txt-dir> <value> [--max-distance 2]

Reads every *.txt in <txt-dir> (a permit-analysis "package" -- all the OCRed documents for one
review), tokenizes each line on whitespace (trimming a small set of enclosing punctuation so
"PER20250001," and "PER20250001" count as the same token, without touching internal characters
like dashes/slashes that are load-bearing in permit/AI/EQT numbers), and keeps every token within
edit distance <= --max-distance of <value> -- this includes <value> itself, at distance 0.

Prints one JSON object: {value, max_distance, readings: [{text, distance, count, citations:
[{file, line}, ...]}, ...]}, readings sorted by count descending. A reading is a probable OCR
artifact if it is a small minority against an otherwise-dominant reading, especially when its
citations all fall inside files also carrying the majority reading (recorded as
`minority_confined_to_majority_files` on the result) -- see SKILL.md for how this feeds STATUS.
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from rapidfuzz.distance import Levenshtein as _rf_levenshtein

    def levenshtein(a, b):
        return _rf_levenshtein.distance(a, b)
except ImportError:

    def levenshtein(a, b):
        if a == b:
            return 0
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, start=1):
                cost = 0 if ca == cb else 1
                curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            prev = curr
        return prev[-1]


TRIM_RE = re.compile(r'^[,;:()\[\]"\'.]+|[,;:()\[\]"\'.]+$')


def tokenize(line):
    return [TRIM_RE.sub("", tok) for tok in line.split() if TRIM_RE.sub("", tok)]


def tally(txt_dir, value, max_distance):
    readings = {}  # text -> {"distance": int, "count": int, "citations": [...]}
    for txt_path in sorted(Path(txt_dir).glob("*.txt")):
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                for token in tokenize(line):
                    if abs(len(token) - len(value)) > max_distance:
                        continue
                    dist = levenshtein(token, value)
                    if dist > max_distance:
                        continue
                    entry = readings.setdefault(
                        token, {"distance": dist, "count": 0, "citations": []}
                    )
                    entry["count"] += 1
                    entry["citations"].append({"file": txt_path.name, "line": line_no})

    ranked = sorted(
        (
            {"text": text, "distance": r["distance"], "count": r["count"], "citations": r["citations"]}
            for text, r in readings.items()
        ),
        key=lambda r: (-r["count"], r["distance"]),
    )

    minority_confined = None
    if len(ranked) >= 2:
        majority_files = {c["file"] for c in ranked[0]["citations"]}
        minority_files = set()
        for r in ranked[1:]:
            minority_files |= {c["file"] for c in r["citations"]}
        minority_confined = minority_files.issubset(majority_files)

    return {
        "value": value,
        "max_distance": max_distance,
        "readings": ranked,
        "minority_confined_to_majority_files": minority_confined,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("txt_dir")
    parser.add_argument("value")
    parser.add_argument("--max-distance", type=int, default=2)
    args = parser.parse_args()

    result = tally(args.txt_dir, args.value, args.max_distance)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
