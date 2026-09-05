#!/usr/bin/env python3
"""Simulate how Nextdoor's email-notification subject line truncates a post's
opening line, so a draft post's cold-open can be checked before it's finalized.

Empirical model (reverse-engineered from real truncated Nextdoor subject lines,
not from any documented API): take up to ~70 characters of the raw text: if
that lands mid-word, back off to the end of the last full word; otherwise keep
it as-is. Append a plain three-period "..." (no space, no single-glyph ellipsis)
only when the text was actually cut. No other rewriting, casing, or punctuation
cleanup happens — Nextdoor's real behavior preserves ALL CAPS, emoji, and even
a dangling stray quote mark, since this is naive substring truncation, not a
summarizer.

Usage:
    python3 preview_subject_line.py "opening line or full post text"
    echo "opening line" | python3 preview_subject_line.py

Exits non-zero (and prints a WARNING) when the computed preview looks like it
would land badly — but that judgment call (evocative? clear? sensational only
if warranted?) is still the drafting model's job, not this script's. The
script only checks the mechanical part: length and word-boundary.
"""
import sys

LIMIT = 70  # Nextdoor's own stated sponsored-content subject-line limit


def preview(text: str) -> tuple[str, bool]:
    text = text.rstrip("\n")
    if len(text) <= LIMIT:
        return text, False

    candidate = text[:LIMIT]
    # If the char right after the cut is not whitespace, we're mid-word —
    # back off to the end of the last full word inside the candidate.
    if LIMIT < len(text) and not text[LIMIT].isspace():
        last_space = candidate.rfind(" ")
        if last_space != -1:
            candidate = candidate[:last_space]
    candidate = candidate.rstrip()
    return candidate + "...", True


def main() -> int:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read()

    result, truncated = preview(text)
    kept_len = len(result[:-3]) if truncated else len(result)

    print(f"Preview: {result}")
    print(f"Truncated: {truncated}")
    print(f"Characters kept before '...': {kept_len}" if truncated
          else f"Characters (untruncated): {kept_len}")

    exit_code = 0
    if truncated and kept_len < 20:
        print("WARNING: very little survives truncation — front-load the point earlier.")
        exit_code = 1
    if not truncated and len(result) < 15:
        print("NOTE: short line — fine if intentional, but confirm it's not just a fragment.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
