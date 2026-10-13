#!/usr/bin/env python3
"""Pre-render checks for a meme CSV (Meme_Title, Template_ID, Caption1..N [, Source]).

    lint.py memes.csv [--mode standalone|in-post] [--allow AAF] [--legacy]

Errors (exit 1):
  - Template_ID unusable, or more boxes than the template has
  - a box over its hard word cap, or the meme over its total cap
  - an acronym not in the allowlist (plain-language.md) or --allow
  - digits in a caption with an empty Source column (unless --legacy)
Warnings:
  - fewer boxes than the template's minimum, more than its curated roles
  - a box over the target length (6 words)
  - percentages over 100% (usually clearer as "N times")
  - template not found in any catalog (render will tell)

--legacy is for old campaign CSVs that predate the Source column: the citation check
becomes a warning so the rest of the report is still useful.
"""
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import templates as tpl  # noqa: E402

PLAIN = os.path.join(HERE, "..", "references", "plain-language.md")
WORD = re.compile(r"[A-Za-z0-9$%][A-Za-z0-9$%.,'’/-]*")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9&.-]*[A-Z0-9]\b")


def allowlist():
    """Backticked tokens under the '## Acronym allowlist' heading of plain-language.md."""
    try:
        text = open(PLAIN, encoding="utf-8").read()
    except FileNotFoundError:
        return set()
    m = re.search(r"^## Acronym allowlist\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return set(re.findall(r"`([^`]+)`", m.group(1))) if m else set()


_DICT = None


def is_english(token):
    """True for all-caps emphasis ("LESS", "YOU'RE") rather than an acronym, via the system word list."""
    global _DICT
    if _DICT is None:
        _DICT = set()
        for p in ("/usr/share/dict/words", "/usr/dict/words"):
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="ignore") as f:
                    _DICT = {w.strip().lower() for w in f if w.strip().islower()}
                break
    return len(token) >= 3 and token.lower() in _DICT


def words(s):
    return WORD.findall(s)


def is_shouting(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 6 and all(c.isupper() for c in letters)


def lint_row(row, caps, args, allow, defaults):
    errs, warns = [], []
    tid = (row.get("Template_ID") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
        errs.append(f"unusable Template_ID {tid!r}")
        return errs, warns

    key, cur = tpl.curated_lookup(tid)
    lim = tpl.box_limit(tid)
    n = len(caps)
    if lim is None:
        warns.append(f"template {tid} not in curated list or cached catalogs; box count unchecked")
    else:
        lo, hi = lim
        catalog_hi = hi
        if cur:
            catalog_hi = max(hi, cur.get("imgflip_box_count") or 0, cur.get("memegen_lines") or 0)
        if n > catalog_hi:
            errs.append(f"{n} boxes, template has {catalog_hi}")
        elif n > hi:
            warns.append(f"{n} boxes; curated roles cover {hi} — check where box {n} lands")
        if n < lo:
            warns.append(f"{n} boxes; template expects at least {lo}")

    caps_only = [c for c in caps if c.strip()]
    single = len(caps_only) == 1
    total = sum(len(words(c)) for c in caps)
    total_cap = defaults["max_words_single_box"] if single else defaults["max_words_total"]
    total_target = defaults["target_words_single_box"] if single else defaults["target_words_total"]
    if total > total_cap:
        errs.append(f"{total} words total (cap {total_cap})")
    elif total > total_target:
        warns.append(f"{total} words total (target {total_target})")

    for i, c in enumerate(caps):
        w = len(words(c))
        if not w:
            continue
        # Targets are what the best memes hit; hard caps sit a few words above so the
        # user's own picks (15–22 words) pass with a warning while 25+ word walls fail.
        if single:
            target, hard = defaults["target_words_single_box"], defaults["max_words_single_box"]
        else:
            target = defaults["target_words_per_box"]
            if cur and i < len(cur.get("target_words", [])):
                target = cur["target_words"][i]
            hard = max(defaults["max_words_per_box"], target + 4)
        if w > hard:
            errs.append(f"box {i+1}: {w} words (cap {hard}) — {c[:60]!r}")
        elif w > target:
            warns.append(f"box {i+1}: {w} words (target {target})")

        if is_shouting(c):
            # All-caps captions (e.g. the last Panik panel) are a style choice; only flag
            # tokens that the row also writes as acronyms in a normal-case caption.
            known = {t for o in caps if not is_shouting(o) for t in ACRONYM.findall(o)}
            tokens = [t for t in ACRONYM.findall(c) if t in known]
        else:
            # Contractions in caps ("YOU'RE") are emphasis, not two acronyms.
            tokens = ACRONYM.findall(re.sub(r"\b[A-Z]+['’][A-Z]+\b", "", c))
        for t in tokens:
            if t in allow or t.rstrip("s") in allow:
                continue
            if is_english(t):
                warns.append(f"box {i+1}: all-caps {t!r} read as emphasis — use sparingly")
                continue
            hint = "" if args.mode == "standalone" else " (or --allow it if the post explains it)"
            errs.append(f"box {i+1}: acronym {t!r} — spell it out or describe it{hint}")

        for p in re.findall(r"(\d[\d,.]*)\s*%", c):
            try:
                if float(p.replace(",", "")) > 100:
                    warns.append(f"box {i+1}: {p}% — 'N times' usually reads better (recompute: X% above = 1 + X/100 times)")
            except ValueError:
                pass

    if any(re.search(r"\d", c) for c in caps) and not (row.get("Source") or "").strip():
        (warns if args.legacy else errs).append("caption has a number but Source is empty")
    return errs, warns


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--mode", choices=["standalone", "in-post"], default="standalone")
    ap.add_argument("--allow", default="", help="comma-separated local names allowed in in-post mode")
    ap.add_argument("--legacy", action="store_true", help="old CSV without a Source column")
    args = ap.parse_args()
    args.allow = {a.strip() for a in args.allow.split(",") if a.strip()}
    if args.mode == "standalone" and args.allow:
        print("note: --allow applies only to in-post mode; standalone memes must explain every name",
              file=sys.stderr)
    allow = allowlist() | (args.allow if args.mode == "in-post" else set())
    defaults = tpl.curated()["defaults"]

    n_err = n_rows = 0
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cap_cols = sorted([c for c in reader.fieldnames or [] if re.fullmatch(r"Caption\d+", c or "")],
                          key=lambda c: int(c[7:]))
        for row in reader:
            title = (row.get("Meme_Title") or "").strip()
            if not title:
                continue
            caps = [(row.get(c) or "").strip() for c in cap_cols]
            while caps and not caps[-1]:
                caps.pop()
            n_rows += 1
            errs, warns = lint_row(row, caps, args, allow, defaults)
            if errs or warns:
                print(f"{'FAIL' if errs else 'warn'}  {title}")
                for e in errs:
                    print(f"      error: {e}")
                for w in warns:
                    print(f"      warn:  {w}")
            else:
                print(f"ok    {title}")
            n_err += bool(errs)
    print(f"\n{n_rows - n_err}/{n_rows} rows pass")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
