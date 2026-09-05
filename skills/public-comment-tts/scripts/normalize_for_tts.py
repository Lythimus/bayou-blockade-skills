#!/usr/bin/env python3
"""Apply references/tts-substitutions.json to a pandoc plain-text export.

Order (load-bearing, see the table's own "notes" field):
  table linearization -> numeric_brackets -> patterns -> brackets_unwrap
  -> chars -> NFKD fallback -> whitespace cleanup -> unknown-character audit

Table linearization runs first, against pandoc's untouched column-aligned
output, because it depends on character-offset alignment that later passes
(especially whitespace cleanup, which collapses multi-space padding) destroy.
Everything table linearization emits is plain sentence text, so it still
flows through every later pass normally (a linearized cell containing
"µg/m³" still gets expanded by the patterns tier, same as prose).
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_TABLE = Path(__file__).resolve().parent.parent / "references" / "tts-substitutions.json"

_DOLLAR_GROUP_REF = re.compile(r"\$(\d+)")
_BORDER_RE = re.compile(r"^[ \t]*-+[ \t]*$")
_SEGMENTED_DASH_RE = re.compile(r"^([ \t]*)-+(?:[ \t]+-+)+[ \t]*$")
_PLACEHOLDER_CELL_RE = re.compile(r"^[-‒–—―−]*$")


def _column_spans(sep_line: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"-+", sep_line)]
    if spans:
        spans[-1] = (spans[-1][0], 1 << 30)  # let the last column run to end-of-line
    return spans


def _slice_row(line: str, spans: list[tuple[int, int]]) -> list[str]:
    return [line[s:min(e, len(line))].strip() for s, e in spans]


def linearize_tables(text: str) -> tuple[str, dict]:
    """Detect pandoc plain-writer tables (bordered or borderless — pandoc
    omits top/bottom rules for some tables) and rewrite each row as a
    "Header: value." sentence instead of column-mashed text.

    Detection: a "segmented" dash line (multiple dash runs separated by
    whitespace, e.g. "---- ----- ---") is a column-boundary line. The line
    directly above it is the header. An optional lone full-dash line directly
    above the header is a top border, consumed along with it. Column offsets
    come from the segmented line; header/data rows are sliced at those exact
    character positions. A table's extent (with no bottom border to rely on)
    is bounded by indentation: every row pandoc emits for a table — border,
    header, separator, data — shares the same leading indent, while prose
    resuming after the table starts back at column 0. That indent match is
    what marks where the table ends when no bottom border is present.
    """
    lines = text.split("\n")
    n = len(lines)
    out: list[str] = []
    stats = {"tables_linearized": 0, "rows_linearized": 0, "borders_stripped": 0, "tables_skipped": 0}

    i = 0
    while i < n:
        line = lines[i]
        m = _SEGMENTED_DASH_RE.match(line)
        header_ok = m and i >= 1 and lines[i - 1].strip() != ""
        if not header_ok:
            out.append(line)
            i += 1
            continue

        indent = m.group(1)
        header_idx = i - 1
        sep_idx = i
        spans = _column_spans(line)

        if len(spans) < 2:
            out.append(line)
            i += 1
            continue

        headers = _slice_row(lines[header_idx], spans)

        # The header line was appended to `out` verbatim in the previous
        # loop iteration (it looked like ordinary text at the time) — pull
        # it back out, since it's being folded into each row's sentence
        # instead of surviving as its own raw line.
        if out and out[-1] == lines[header_idx]:
            out.pop()

        # Same for an optional top border directly above the header.
        top_border_idx = None
        if header_idx >= 1 and _BORDER_RE.match(lines[header_idx - 1]):
            top_border_idx = header_idx - 1
            if out and out[-1] == lines[top_border_idx]:
                out.pop()

        # Consume data rows: any non-blank line sharing the table's indent,
        # or a bottom border (which ends the table). A non-blank line that
        # does NOT share the indent means the table is over (prose resumed).
        rows: list[list[str]] = []
        j = sep_idx + 1
        bottom_border_idx = None
        while j < n:
            cur = lines[j]
            if cur.strip() == "":
                j += 1
                continue
            if _BORDER_RE.match(cur) and cur.startswith(indent):
                bottom_border_idx = j
                j += 1
                break
            if not cur.startswith(indent):
                break
            rows.append(_slice_row(cur, spans))
            j += 1

        if not rows:
            # Nothing usable — leave the segmented line as-is and move on;
            # whitespace cleanup will still tidy it later.
            stats["tables_skipped"] += 1
            out.append(line)
            i += 1
            continue

        stats["tables_linearized"] += 1
        if top_border_idx is not None:
            stats["borders_stripped"] += 1
        if bottom_border_idx is not None:
            stats["borders_stripped"] += 1

        for row_cells in rows:
            parts = []
            for header, value in zip(headers, row_cells):
                value = value.strip()
                if value == "" or _PLACEHOLDER_CELL_RE.match(value):
                    continue
                header = header.strip()
                parts.append(f"{value}." if header == "" else f"{header}: {value}.")
            if parts:
                out.append(" ".join(parts))
                out.append("")
                stats["rows_linearized"] += 1

        i = j

    return "\n".join(out), stats


def strip_thematic_breaks(text: str) -> tuple[str, int]:
    """Drop leftover horizontal-rule lines (markdown `---` section dividers)
    that linearize_tables didn't consume because they aren't attached to a
    table. Pure decoration — the heading text right after each one already
    signals the section change, so there's nothing lost by dropping it."""
    lines = text.split("\n")
    kept = [l for l in lines if not _BORDER_RE.match(l)]
    return "\n".join(kept), len(lines) - len(kept)


def load_table(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def to_python_repl(replacement: str) -> str:
    """Translate $1-style group references (as written in the JSON table) to
    Python re's \\g<1> syntax. re.sub does not understand $1 on its own — it
    would insert the literal text "$1" instead of the captured group."""
    return _DOLLAR_GROUP_REF.sub(r"\\g<\1>", replacement)


def apply_numeric_brackets(text: str, rule: dict) -> tuple[str, int]:
    pattern = re.compile(rule["regex"])
    text, n = pattern.subn(to_python_repl(rule["replacement"]), text)
    return text, n


def apply_patterns(text: str, patterns: list[dict]) -> tuple[str, list[tuple[str, int]]]:
    counts = []
    for rule in patterns:
        pattern = re.compile(rule["regex"])
        text, n = pattern.subn(to_python_repl(rule["replacement"]), text)
        counts.append((rule["regex"], n))
    return text, counts


def apply_brackets_unwrap(text: str, rule: dict) -> tuple[str, int]:
    pattern = re.compile(rule["regex"])
    text, n = pattern.subn(to_python_repl(rule["replacement"]), text)
    return text, n


def apply_chars(text: str, chars: list[dict]) -> tuple[str, Counter]:
    counts: Counter = Counter()
    for entry in chars:
        ch = entry["char"]
        n = text.count(ch)
        if n:
            text = text.replace(ch, entry["replacement"])
            counts[f"{entry['name']} ({entry['codepoint']})"] = n
    return text, counts


def nfkd_fallback(text: str) -> tuple[str, Counter]:
    """Decompose remaining non-ASCII chars and drop combining marks.

    Catches accented Latin letters generically (e.g. o-with-diaeresis -> o)
    without needing every one enumerated in the char table.
    """
    counts: Counter = Counter()
    out_chars = []
    for ch in text:
        if ord(ch) < 128:
            out_chars.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        if stripped and all(ord(c) < 128 for c in stripped):
            if stripped != ch:
                try:
                    name = unicodedata.name(ch)
                except ValueError:
                    name = "UNNAMED"
                counts[f"{name} (U+{ord(ch):04X}) -> {stripped!r}"] += 1
            out_chars.append(stripped)
        else:
            out_chars.append(ch)
    return "".join(out_chars), counts


def whitespace_cleanup(text: str) -> str:
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line)
        line = re.sub(r"\s+,", ",", line)
        line = re.sub(r"\s+;", ";", line)
        line = re.sub(r"\s+\.", ".", line)
        line = re.sub(r"(,\s*){2,}", ", ", line)
        line = re.sub(r"(;\s*){2,}", "; ", line)
        line = re.sub(r"^,\s*", "", line)
        line = line.strip()
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def unknown_char_audit(text: str) -> Counter:
    counts: Counter = Counter()
    for ch in text:
        if ord(ch) > 127:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "UNNAMED"
            counts[f"{name} (U+{ord(ch):04X}) [{ch!r}]"] += 1
    return counts


def context_snippets(text: str, ch: str, limit: int = 2) -> list[str]:
    snippets = []
    start = 0
    while len(snippets) < limit:
        idx = text.find(ch, start)
        if idx == -1:
            break
        lo = max(0, idx - 20)
        hi = min(len(text), idx + 21)
        snippets.append(text[lo:hi].replace("\n", " "))
        start = idx + 1
    return snippets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    ap.add_argument("--keep-brackets", action="store_true")
    ap.add_argument("--keep-tables", action="store_true", help="don't linearize tables into sentences")
    args = ap.parse_args()

    table = load_table(args.table)
    text = args.input.read_text(encoding="utf-8")

    table_stats = {"tables_linearized": 0, "rows_linearized": 0, "borders_stripped": 0, "tables_skipped": 0}
    if not args.keep_tables:
        text, table_stats = linearize_tables(text)
    text, thematic_break_count = strip_thematic_breaks(text)

    text, numeric_bracket_count = apply_numeric_brackets(text, table["numeric_brackets"])
    text, pattern_counts = apply_patterns(text, table["patterns"])

    bracket_count = 0
    if not args.keep_brackets:
        text, bracket_count = apply_brackets_unwrap(text, table["brackets_unwrap"])

    text, char_counts = apply_chars(text, table["chars"])
    text, nfkd_counts = nfkd_fallback(text)
    text = whitespace_cleanup(text)
    unknown_counts = unknown_char_audit(text)

    args.out.write_text(text, encoding="utf-8")

    total_pattern_hits = sum(n for _, n in pattern_counts)
    total_char_hits = sum(char_counts.values())

    print(f"[TTS] normalize done -> {args.out}", file=sys.stderr)
    if args.keep_tables:
        print("  tables linearized: skipped (--keep-tables)", file=sys.stderr)
    else:
        print(
            f"  tables linearized: {table_stats['tables_linearized']} "
            f"({table_stats['rows_linearized']} rows, {table_stats['borders_stripped']} border lines dropped, "
            f"{table_stats['tables_skipped']} candidate table(s) skipped as unparseable)",
            file=sys.stderr,
        )
    print(f"  thematic-break / section-divider lines dropped: {thematic_break_count}", file=sys.stderr)
    print(f"  numeric-bracket citations dropped: {numeric_bracket_count}", file=sys.stderr)
    print(f"  phrase patterns applied: {total_pattern_hits}", file=sys.stderr)
    for regex, n in pattern_counts:
        if n:
            print(f"    {regex!r}: {n}", file=sys.stderr)
    if args.keep_brackets:
        print("  bracket-citations unwrapped: skipped (--keep-brackets)", file=sys.stderr)
    else:
        print(f"  bracket-citations unwrapped: {bracket_count}", file=sys.stderr)
    print(f"  single-char substitutions: {total_char_hits} across {len(char_counts)} distinct characters", file=sys.stderr)
    for name, n in char_counts.most_common():
        print(f"    {name}  x{n}", file=sys.stderr)
    if nfkd_counts:
        print(f"  NFKD fallback transliterations: {sum(nfkd_counts.values())}", file=sys.stderr)
        for name, n in nfkd_counts.most_common():
            print(f"    {name}  x{n}", file=sys.stderr)
    else:
        print("  NFKD fallback transliterations: 0", file=sys.stderr)

    if unknown_counts:
        print(f"  unknown/uncatalogued non-ASCII remaining: {sum(unknown_counts.values())}", file=sys.stderr)
        for name, n in unknown_counts.most_common():
            ch = name.split("[", 1)[1].rstrip("]").strip("'")
            snippets = context_snippets(text, ch)
            snippet_str = " | ".join(snippets)
            print(f"    UNKNOWN: {name}  x{n}  ...{snippet_str}...", file=sys.stderr)
    else:
        print("  unknown/uncatalogued non-ASCII remaining: 0", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
