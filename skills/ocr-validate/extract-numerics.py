"""Pull numeric facts, dates, and identifier-shaped tokens out of one or more canonical OCR files
-- the cheap, mechanical first pass `run-checks.py` runs its checks against. See
references/air-permit-checks.md for what each check does with these facts.

Usage: extract-numerics.py <work-dir> [--doc <stem> ...]

Reads $WORK/canonical/<stem>.json for each stem given (or every *.json in $WORK/canonical/ if
--doc is omitted). Two kinds of fact, kept deliberately separate because they have different
reliability:

- **Line-level facts** (numbers-with-units, dates, identifier-shaped tokens) come from a regex
  scan over every canonical line's plain text, in canonical reading order. These work on any
  backend tier, including surya-only -- no table structure is required -- but a value's "meaning"
  (which pollutant, which column) is only as good as a small nearby-text window, so these facts
  carry a `context` string (the line's own text) for a human to judge, never a claimed row/column
  identity.
- **Table facts** (row/column-aligned cells) come only from `canonical.pages[].tables[]`, which
  today is populated only when `--azure` ran for that document (see document-ocr's
  merge-canonical.py -- MinerU table ingestion into the canonical schema is not implemented, a
  known gap, not something this script papers over). Table facts carry real row/col identity, so
  checks that need to sum a column or match a value across two named columns in the same row
  (UNIT-TPY-LBHR, UNIT-HEAT, SUBTOTAL/TABLE-SUM, MAGNITUDE, ZERO-VS-BLANK) require them and simply
  produce nothing for a document that has none -- see run-checks.py's docstring.

Every fact/date/identifier carries `txt_cite` (`<stem>.txt:<line>`), computed via
document-ocr/render-txt.py's line_number_map so citations always match the real rendered .txt
without needing that file to exist on disk.

Emits one JSON object to stdout: {stem: {facts: [...], dates: [...], identifiers: [...],
tables: [...]}}, one entry per requested stem.
"""

import argparse
import importlib.util
import json
import re
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

# --- Units -------------------------------------------------------------------------------------

UNIT_ALIASES = {
    "lb/hr": "LB_HR", "lbs/hr": "LB_HR", "lb/hour": "LB_HR",
    "tpy": "TPY", "tons/yr": "TPY", "tons/year": "TPY", "ton/yr": "TPY",
    "lb/mmbtu": "LB_MMBTU", "lbs/mmbtu": "LB_MMBTU",
    "mmbtu/hr": "MMBTU_HR", "mmbtu/hour": "MMBTU_HR",
    "%": "PERCENT",
    "ft": "FT", "feet": "FT",
    "°f": "DEGF", "deg f": "DEGF", "degf": "DEGF",
    "acfm": "FLOW", "scfm": "FLOW", "dscfm": "FLOW", "gpm": "FLOW",
}
_UNIT_PATTERN = "|".join(sorted((re.escape(u) for u in UNIT_ALIASES), key=len, reverse=True))
NUMBER_UNIT_RE = re.compile(
    # (?!\w) rather than \b: a symbolic unit like "%" is itself non-word, so \b would never match
    # right after it (both sides of the boundary need to disagree on wordness) -- this fires
    # correctly for both "98.5%" at end-of-line and "150 ft," before punctuation.
    #
    # (?<![%\d.]) blocks a match from starting right after a digit/%/decimal point -- without it,
    # a bare "-" glued to a preceding token (a range like "70%-99%", or the exponent sign in
    # scientific notation like "1.30E-03") gets read as a fresh unary minus, producing a bogus
    # negative value. The [eE][+-]?\d+ group below then lets a real scientific-notation number
    # match as one token (so "1.30E-03 lb/hr" is captured whole as 0.00130, not split into a
    # failed match on "1.30" and a spurious "-03").
    rf"(?<![%\d.])(-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)\s*({_UNIT_PATTERN})(?!\w)", re.IGNORECASE
)

DATE_RE = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
DATE_ROLE_KEYWORDS = {
    "issuance": ["issu"],
    "expiration": ["expir"],
    "effective": ["effective"],
    "submitted": ["submit", "received"],
}

IDENTIFIER_PATTERNS = {
    # \)? tolerates the common "Agency Interest (AI) No. 41475" header form, not just bare "AI No.".
    "AI_NUMBER": re.compile(r"\bA[Il1]\)?\s*(?:No\.?|Number|#)?\s*[:\-]?\s*(\d{3,7})\b", re.IGNORECASE),
    "PERMIT_NUMBER": re.compile(r"\b(\d{4}-\d{4,5}-\d{2})\b"),
    "ACTIVITY_NUMBER": re.compile(r"\b(PER\d{6,10})\b", re.IGNORECASE),
    "EQT_NUMBER": re.compile(r"\b(EQT\d{4,8})\b", re.IGNORECASE),
}


def normalize_number(raw):
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def extract_line_facts(stem, canonical, txt_line_map):
    facts, dates, identifiers = [], [], []
    for page in canonical.get("pages", []):
        for line in render_txt.sorted_page_lines(page):
            text = line.get("text", "")
            if not text:
                continue
            txt_cite = f"{stem}.txt:{txt_line_map.get(line.get('line_id'))}"
            base = {
                "doc": stem,
                "page": page["page"],
                "line_id": line.get("line_id"),
                "txt_cite": txt_cite,
                "context": text,
            }

            for m in NUMBER_UNIT_RE.finditer(text):
                value = normalize_number(m.group(1))
                if value is None:
                    continue
                unit = UNIT_ALIASES[m.group(2).lower()]
                facts.append({**base, "value": value, "unit": unit})

            for m in DATE_RE.finditer(text):
                lowered = text.lower()
                role = next(
                    (r for r, kws in DATE_ROLE_KEYWORDS.items() if any(k in lowered for k in kws)),
                    None,
                )
                dates.append({**base, "date_text": m.group(0), "role": role})

            for kind, pattern in IDENTIFIER_PATTERNS.items():
                for m in pattern.finditer(text):
                    identifiers.append({**base, "kind": kind, "value": m.group(1)})

    return facts, dates, identifiers


def extract_table_facts(stem, canonical, txt_line_map):
    tables = []
    for page in canonical.get("pages", []):
        for table in page.get("tables") or []:
            cells = []
            for cell in table.get("cells", []):
                cells.append(
                    {
                        "row": cell.get("row"),
                        "col": cell.get("col"),
                        "text": cell.get("text", ""),
                        "bbox_norm": cell.get("bbox_norm"),
                    }
                )
            tables.append(
                {
                    "doc": stem,
                    "page": page["page"],
                    "table_id": table.get("table_id"),
                    "rows": table.get("rows"),
                    "cols": table.get("cols"),
                    "cells": cells,
                }
            )
    return tables


def extract_stem(stem, canonical_path):
    with open(canonical_path, "r", encoding="utf-8") as f:
        canonical = json.load(f)
    txt_line_map = render_txt.line_number_map(canonical)
    facts, dates, identifiers = extract_line_facts(stem, canonical, txt_line_map)
    tables = extract_table_facts(stem, canonical, txt_line_map)
    return {"facts": facts, "dates": dates, "identifiers": identifiers, "tables": tables}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir")
    parser.add_argument("--doc", action="append", default=[])
    args = parser.parse_args()

    canonical_dir = Path(args.work_dir) / "canonical"
    if args.doc:
        stems = args.doc
    else:
        # p.suffixes == [".json"] excludes check-reader-coverage.py's <stem>.coverage.json
        # siblings in the same directory -- p.stem alone would treat each as its own document.
        stems = sorted(p.stem for p in canonical_dir.glob("*.json") if p.suffixes == [".json"])

    output = {}
    skipped = []
    for stem in stems:
        canonical_path = canonical_dir / f"{stem}.json"
        if not canonical_path.exists():
            print(f"[OCR] validate skip {stem}: no canonical.json", file=sys.stderr)
            skipped.append(stem)
            continue
        output[stem] = extract_stem(stem, canonical_path)

    # A reserved key, not a document stem -- run-checks.py pops it before iterating docs. Carried
    # in the JSON itself (not just stderr) so a skipped doc is visible in OCR-FLAGS.md too, not
    # just in a log a reader may not see (this is exactly the "quiet run" failure this skill's own
    # SKILL.md warns about).
    output["_skipped"] = skipped

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
