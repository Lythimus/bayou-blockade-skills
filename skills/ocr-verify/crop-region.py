"""Crop a padded region from the source PDF at high DPI, for visual verification of an
OCR-contested value (see SKILL.md's escalation flow).

Crops from bbox_norm -- the canonical schema's only field with a stable meaning independent of
which backend produced it (fraction of the page's own width/height; see document-ocr's
references/output-schema.md, "Hazard: five coordinate spaces") -- never from a backend-native
pixel bbox.

Usage: crop-region.py <pdf> <page> <x0> <y0> <x1> <y1> <out.png> [--dpi 400] [--pad 0.15]

x0/y0/x1/y1 are bbox_norm fractions (0.0-1.0) of the page, top-left origin (same convention as
Surya's bbox / bbox_norm).

Handles rotation: confirmed empirically (a single page rotated 90 degrees with qpdf) that
`pdfinfo`'s own "Page N size" line reports the PDF's raw, UN-rotated MediaBox -- it stays e.g.
607x807pts regardless of a 90/270 rotation -- while `pdftoppm`'s rendered PNG dimensions (and its
-x/-y/-W/-H crop box, which operates in that same rendered pixel space) ARE swapped at rot 90/270.
So this script swaps the pdfinfo-reported W_pts/H_pts before converting bbox_norm to pixels
whenever rot is 90 or 270 -- skipping this step silently crops the wrong region on any rotated
landscape sheet (a real document class in this pipeline). If poppler's behavior here ever needs
re-confirming, re-run pdfinfo and pdftoppm side by side on a rot=90 single-page PDF and compare
reported vs. rendered dimensions, the way this script's logic was derived.
"""

import argparse
import re
import subprocess
import sys

PAGE_SIZE_RE = re.compile(r"Page\s+\d+\s+size:\s+([\d.]+)\s*x\s*([\d.]+)\s*pts")
PAGE_ROT_RE = re.compile(r"Page\s+\d+\s+rot:\s+(\d+)")

# Floor padding in points so a tiny region (a single glyph, a checkbox) still gets enough
# surrounding context to be legible, even when --pad's fraction-of-box-size would round to ~0.
MIN_PAD_PTS = 15.0


def page_geometry(pdf_path, page):
    out = subprocess.run(
        ["pdfinfo", "-f", str(page), "-l", str(page), pdf_path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    size_m = PAGE_SIZE_RE.search(out)
    rot_m = PAGE_ROT_RE.search(out)
    if not size_m:
        raise SystemExit(f"[OCR] crop failed: could not parse page size from pdfinfo for page {page}")
    w_pts, h_pts = float(size_m.group(1)), float(size_m.group(2))
    rot = int(rot_m.group(1)) if rot_m else 0
    if rot in (90, 270):
        w_pts, h_pts = h_pts, w_pts
    return w_pts, h_pts


def crop_box_px(x0, y0, x1, y1, w_pts, h_pts, dpi, pad):
    bw, bh = max(x1 - x0, 0.0), max(y1 - y0, 0.0)
    min_pad_norm_x = (MIN_PAD_PTS / 72.0) / w_pts
    min_pad_norm_y = (MIN_PAD_PTS / 72.0) / h_pts
    pad_x = max(bw * pad, min_pad_norm_x)
    pad_y = max(bh * pad, min_pad_norm_y)
    x0, x1 = max(0.0, x0 - pad_x), min(1.0, x1 + pad_x)
    y0, y1 = max(0.0, y0 - pad_y), min(1.0, y1 + pad_y)

    px_w = w_pts / 72.0 * dpi
    px_h = h_pts / 72.0 * dpi
    x_px = int(round(x0 * px_w))
    y_px = int(round(y0 * px_h))
    w_px = max(1, int(round((x1 - x0) * px_w)))
    h_px = max(1, int(round((y1 - y0) * px_h)))
    return x_px, y_px, w_px, h_px


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("page", type=int)
    parser.add_argument("x0", type=float)
    parser.add_argument("y0", type=float)
    parser.add_argument("x1", type=float)
    parser.add_argument("y1", type=float)
    parser.add_argument("out_png")
    parser.add_argument("--dpi", type=int, default=400)
    parser.add_argument("--pad", type=float, default=0.15)
    args = parser.parse_args()

    w_pts, h_pts = page_geometry(args.pdf, args.page)
    x_px, y_px, w_px, h_px = crop_box_px(
        args.x0, args.y0, args.x1, args.y1, w_pts, h_pts, args.dpi, args.pad
    )

    out_prefix = args.out_png[:-4] if args.out_png.lower().endswith(".png") else args.out_png
    cmd = [
        "pdftoppm",
        "-f", str(args.page), "-l", str(args.page),
        "-r", str(args.dpi),
        "-x", str(x_px), "-y", str(y_px), "-W", str(w_px), "-H", str(h_px),
        "-singlefile", "-png",
        args.pdf, out_prefix,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"[OCR] crop failed: {e.stderr}")

    print(f"[OCR] crop done -> {args.out_png}", file=sys.stderr)


if __name__ == "__main__":
    main()
