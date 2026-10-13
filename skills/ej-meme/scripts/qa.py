#!/usr/bin/env python3
"""Legibility QA for rendered memes. Flags; does not decide.

    qa.py RENDER_DIR                         # uses RENDER_DIR/manifest.json from render.py
    qa.py --csv old.csv --images DIR         # old renders: match Meme_Title to DIR/<title>.(png|jpg)
    options: --feed-width 400 --min-height 7.5 --soft-height 9 --min-coverage 0.35
             --soft-coverage 0.6 [--json out.json] [--only TITLE,TITLE]

Per image, for each caption:
  coverage  share of the caption's letters that OCR recovers, in order (best of three
            preprocessings). Low coverage = text crushed by auto-shrink, clipped, or lost
            against the background.
  height    median height of matched OCR words, scaled to --feed-width (a phone feed).
  edge      a matched word touching the image border = probably overflowing.

Impact-style outlined text OCRs badly (outline strokes merge words: "AIR|PRODUCTS"), so
matching is on letters only and the thresholds are heuristics calibrated on known-good
memes. Every flagged image still needs a human/Claude look before anyone acts on it.

Requires: Pillow, tesseract on PATH (or /opt/homebrew/bin/tesseract).
"""
import argparse
import csv
import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

TESSERACT = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"


def letters(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def variants(im):
    """Grayscale plus two masks: white fill (classic meme text) and dark text (labels on light panels)."""
    g = ImageOps.grayscale(im)
    return {
        "gray": g,
        "white": g.point(lambda p: 0 if p > 215 else 255),
        "dark": g.point(lambda p: 0 if p < 60 else 255),
    }


def ocr_words(img, tmpdir):
    path = os.path.join(tmpdir, "v.png")
    img.save(path)
    out = subprocess.run([TESSERACT, path, "-", "--psm", "11", "tsv"],
                         capture_output=True, text=True).stdout
    words = []
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            conf = float(p[10])
        except ValueError:
            continue
        words.append({"text": p[11], "l": int(p[6]), "t": int(p[7]), "w": int(p[8]), "h": int(p[9]), "conf": conf})
    return words


def coverage(caption, stream):
    a = letters(caption)
    if not a:
        return 1.0
    sm = difflib.SequenceMatcher(None, a, stream, autojunk=False)
    # Ignore 1–2 character coincidences; real recovery comes in runs.
    return sum(b.size for b in sm.get_matching_blocks() if b.size >= 3) / len(a)


def check(path, captions, opts):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    # Upscale small renders so tesseract sees ~30px glyphs; boxes are mapped back below.
    scale = 2 if W < 1000 else 1
    big = im.resize((W * scale, H * scale), Image.LANCZOS) if scale > 1 else im
    caps = [c for c in captions if letters(c)]
    cap_words = [{letters(x) for x in c.split()} for c in caps]
    best = {i: 0.0 for i in range(len(caps))}
    # Word heights per caption, keyed by variant so heights come from one consistent pass.
    per_cap = {i: [] for i in range(len(caps))}
    edge = set()
    with tempfile.TemporaryDirectory() as td:
        for v in variants(big).values():
            words = ocr_words(v, td)
            stream = "".join(letters(w["text"]) for w in words)
            for i, c in enumerate(caps):
                best[i] = max(best[i], coverage(c, stream))
            for w in words:
                t = letters(w["text"])
                if len(t) < 3 or w["conf"] <= 20:
                    continue
                # A word shared by two captions is credited to the shorter one: shorter
                # captions are the ones most likely to be rendered small.
                # Whole-word match, or a 5+ letter run inside the caption (outlines merge
                # words: "AIRPRODUCTS"). Shorter fragments are usually OCR noise from the
                # artwork ("lls" off a cartoon building) and would credit a fake height.
                owners = sorted((i for i, c in enumerate(caps)
                                 if t in cap_words[i] or (len(t) >= 5 and t in letters(c))),
                                key=lambda i: len(caps[i]))
                if not owners:
                    continue
                per_cap[owners[0]].append(w["h"] / scale * opts.feed_width / W)
                # Only a box flush with the border suggests clipping; imgflip's full-width
                # text routinely sits 1–3px from the edge and is fine.
                if w["l"] <= 0 or w["t"] <= 0 or w["l"] + w["w"] >= big.width or w["t"] + w["h"] >= big.height:
                    edge.add(w["text"])

    flags, notes, heights = [], [], []
    for i, c in enumerate(caps):
        cv = best[i]
        h = statistics.median(per_cap[i]) if per_cap[i] else None
        heights.append(round(h, 1) if h else None)
        label = f"caption {i+1} {c[:45]!r}"
        # One short outlined word (a company name on a label) often OCRs as nothing even
        # when it is huge, so very short captions only earn a note.
        short = len(letters(c)) < 8
        if cv < opts.min_coverage and not short:
            flags.append(f"{label}: only {cv:.0%} recovered — dropped, crushed, or tiny?")
        elif cv < opts.soft_coverage:
            notes.append(f"{label}: {cv:.0%} recovered (short, rotated or condensed text OCRs poorly)")
        n_words = len(c.split())
        if h is not None and h < opts.min_height:
            flags.append(f"{label}: ~{h:.1f}px tall at {opts.feed_width}px feed width (min {opts.min_height})")
        elif h is not None and h < opts.soft_height and n_words > 12:
            # memegen and imgflip shrink long text to fit, so a long caption that came out
            # small is a wall of text even when each letter is technically legible.
            flags.append(f"{label}: {n_words} words shrunk to ~{h:.1f}px at feed width — wall of text")
        elif h is not None and h < opts.soft_height:
            notes.append(f"{label}: ~{h:.1f}px tall at feed width — small but probably readable")
        elif h is None and any(per_cap.values()):
            # Other captions measured fine but this one yielded no clean word: often tiny text.
            notes.append(f"{label}: height not measurable — look at it")
    if caps and not any(per_cap.values()):
        flags.append("no caption words recovered at all")
    if edge:
        notes.append(f"words flush with the border (possible clipping): {sorted(edge)[:5]}")
    return {
        "file": os.path.basename(path), "size": [W, H],
        "coverage": [round(best[i], 2) for i in range(len(caps))],
        "feed_text_height": heights,
        "flags": flags, "notes": notes,
    }


def from_manifest(d):
    with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
        for e in json.load(f):
            if e.get("file"):
                yield e["title"], os.path.join(d, e["file"]), e["captions"]


def from_csv(csv_path, img_dir):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cap_cols = sorted([c for c in reader.fieldnames or [] if re.fullmatch(r"Caption\d+", c or "")],
                          key=lambda c: int(c[7:]))
        for row in reader:
            title = (row.get("Meme_Title") or "").strip()
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                p = os.path.join(img_dir, title + ext)
                if os.path.exists(p):
                    yield title, p, [(row.get(c) or "").strip() for c in cap_cols]
                    break


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--csv")
    ap.add_argument("--images")
    ap.add_argument("--only", help="comma-separated titles")
    ap.add_argument("--feed-width", type=int, default=400)
    ap.add_argument("--min-height", type=float, default=7.5)
    ap.add_argument("--soft-height", type=float, default=9.0)
    ap.add_argument("--min-coverage", type=float, default=0.35)
    ap.add_argument("--soft-coverage", type=float, default=0.6)
    ap.add_argument("--json")
    opts = ap.parse_args()
    if not os.path.exists(TESSERACT):
        sys.exit("tesseract not found (brew install tesseract)")
    if opts.csv and opts.images:
        items = from_csv(opts.csv, opts.images)
    elif opts.dir:
        items = from_manifest(opts.dir)
    else:
        ap.error("give RENDER_DIR or --csv + --images")
    only = set(opts.only.split(",")) if opts.only else None

    results, n_flag = [], 0
    for title, path, caps in items:
        if only and title not in only:
            continue
        r = check(path, caps, opts)
        r["title"] = title
        results.append(r)
        n_flag += bool(r["flags"])
        cov = " ".join(f"{c:.0%}" for c in r["coverage"])
        hts = " ".join("-" if h is None else f"{h:g}" for h in r["feed_text_height"])
        tag = "FLAG" if r["flags"] else ("note" if r["notes"] else "ok  ")
        print(f"{tag}  {title:45} h=[{hts}]  cov=[{cov}]")
        for fl in r["flags"]:
            print(f"        ! {fl}")
        for n in r["notes"]:
            print(f"        . {n}")
    out = opts.json or (os.path.join(opts.dir, "qa.json") if opts.dir else None)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n{n_flag}/{len(results)} flagged" + (f" -> {out}" if out else ""))


if __name__ == "__main__":
    main()
