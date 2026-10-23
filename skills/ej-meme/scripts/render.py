#!/usr/bin/env python3
"""Render meme CSV rows to PNGs plus a manifest.json.

CSV schema (same as the old petro-meme-gen sheets, so they render unchanged):
    Meme_Title, Template_ID, Caption1 .. CaptionN [, Backend] [, Source] [, Point] [, Footer]
    [, Overlay] [, Overlay_Source]

Overlay puts photos in a memegen template's photo slots, "|"-separated in slot order. A plain
https URL goes to memegen's style parameter; a local path (relative to the CSV's folder or
the cwd), or a URL with a query string, is composited locally with Pillow under the
captions, so private photos never leave the machine.

Template_ID routing, per row:
    memegen slug (e.g. "drake")           -> memegen.link /images
    numeric imgflip id (e.g. 148909805)   -> imgflip caption_image if credentials exist,
                                             else the memegen twin from templates.json, if it
                                             has slots for every caption,
                                             else memegen /images/custom on the imgflip blank
                                             (only templates marked custom_ok: text top/bottom),
                                             else the row fails rather than misplace captions
A Backend column, or --backend, forces one path (--backend imgflip never falls back).

Credentials come only from ~/.claude/bayou-credentials.md:
    IMGFLIP_USERNAME: ...   IMGFLIP_PASSWORD: ...   MEMEGEN_API_KEY: ... (optional)

Usage:
    render.py memes.csv --out DIR [--backend memegen|imgflip] [--mode standalone|in-post]
              [--footer "Pelican Bayou ammonia plant"] [--only TITLE,TITLE]
"""
import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import templates as tpls  # noqa: E402

TEMPLATES_JSON = os.path.join(HERE, "..", "references", "templates.json")
CREDS = os.path.expanduser("~/.claude/bayou-credentials.md")
UA = {"User-Agent": "bayou-ej-meme/1.0"}


def load_creds():
    out = {}
    try:
        with open(CREDS, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*(IMGFLIP_USERNAME|IMGFLIP_PASSWORD|MEMEGEN_API_KEY)\s*:\s*(\S.*?)\s*$", line)
                # Template placeholders like <username> are not real values.
                if m and not m.group(2).startswith("<"):
                    out[m.group(1)] = m.group(2)
    except FileNotFoundError:
        pass
    return out


def load_templates():
    try:
        with open(TEMPLATES_JSON, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"templates": {}}


def find_template(tid, catalog):
    """Return the templates.json entry whose memegen slug or imgflip id equals tid."""
    for key, t in catalog.get("templates", {}).items():
        if tid == key or tid == t.get("memegen") or tid == str(t.get("imgflip") or ""):
            return t
    return None


def http_json(url, data=None, headers=None, form=False):
    h = dict(UA)
    h.update(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def download(url, path, headers=None):
    h = dict(UA)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=90) as r, open(path, "wb") as f:
        f.write(r.read())


def memegen_text(captions):
    # The POST API escapes text into the image path itself: "" becomes the path's blank
    # ("_"), while a literal "_" becomes "__", which memegen draws as an underscore.
    return [c if c.strip() else "" for c in captions]


def render_memegen(slug, captions, path, creds, style=None):
    headers = {"X-API-KEY": creds["MEMEGEN_API_KEY"]} if creds.get("MEMEGEN_API_KEY") else {}
    body = {"template_id": slug, "text": memegen_text(captions), "extension": "png"}
    if style:
        body["style"] = style
    res = http_json("https://api.memegen.link/images", body, headers)
    download(res["url"], path, headers)
    return res["url"]


def render_with_photos(slug, captions, photos, path, creds, csv_dir):
    """Photo overlays on a memegen template. Plain https URLs go to memegen as-is; anything
    else (a local file, or a URL memegen would truncate) is composited here so the photo
    never has to be put online."""
    if all(tpls.style_safe(p) for p in photos):
        return render_memegen(slug, captions, path, creds, style=photos), "memegen+photo"
    try:
        from PIL import Image, ImageChops, ImageOps
    except ImportError:
        raise RuntimeError("local photo overlays need Pillow (pip install Pillow)")
    slots = tpls.overlay_geometry(slug)
    if len(photos) > len(slots):
        raise ValueError(f"{len(photos)} photos, {slug} has {len(slots)} photo slot(s)")
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, p in enumerate(photos):
            if tpls.is_url(p):
                local = os.path.join(tmp, f"photo{i}")
                download(p, local)
            else:
                local = tpls.resolve_local(p, csv_dir)
                if not os.path.exists(local):
                    raise ValueError(f"photo not found: {p}")
            files.append(local)
        blank_path = os.path.join(tmp, "blank.png")
        render_memegen(slug, captions, path, creds)
        render_memegen(slug, [""] * max(1, len(captions)), blank_path, creds)
        text = Image.open(path).convert("RGB")
        blank = Image.open(blank_path).convert("RGB")
        if text.size != blank.size:
            raise RuntimeError("memegen returned different sizes for the text and blank renders")
        W, H = blank.size
        out = blank.copy()
        for f, s in zip(files, slots):
            # Same placement as memegen's own overlay: fit inside a square whose side is
            # scale × the shorter image side, centered on (center_x, center_y).
            side = min(int(W * s["scale"]), int(H * s["scale"]))
            chip = ImageOps.contain(ImageOps.exif_transpose(Image.open(f)).convert("RGBA"), (side, side))
            if s["angle"]:
                chip = chip.rotate(s["angle"], expand=True)
            out.paste(chip, (int(W * s["center_x"] - chip.width / 2), int(H * s["center_y"] - chip.height / 2)), chip)
        # memegen draws captions over the photo. The two renders are identical except where
        # captions are, so those pixels go back on top. Any difference counts: a white outline
        # on an off-white panel differs by only a few levels. A caption fill that exactly
        # matches the background under a photo can't be told apart and lets the photo show
        # through the letters; the visual QA step catches that.
        out.paste(text, mask=ImageChops.difference(text, blank).convert("L").point(lambda v: 255 if v else 0))
        out.save(path)
    # The memegen link shows the captions without the photo, so there's no URL for the result.
    return None, "memegen+photo-local"


def render_memegen_custom(background, captions, path, creds):
    headers = {"X-API-KEY": creds["MEMEGEN_API_KEY"]} if creds.get("MEMEGEN_API_KEY") else {}
    res = http_json("https://api.memegen.link/images/custom",
                    {"background": background, "text": memegen_text(captions), "extension": "png"},
                    headers)
    download(res["url"], path, headers)
    return res["url"]


def render_imgflip(tid, captions, path, creds):
    data = {"template_id": tid, "username": creds["IMGFLIP_USERNAME"],
            "password": creds["IMGFLIP_PASSWORD"]}
    for i, c in enumerate(captions):
        data[f"boxes[{i}][text]"] = c
    res = http_json("https://api.imgflip.com/caption_image", data, form=True)
    if not res.get("success"):
        raise RuntimeError(f"imgflip: {res.get('error_message')}")
    url = res["data"]["url"]
    download(url, path)
    return url


def add_footer(path, text):
    """Append a plain strip under the image so a reshared standalone meme still names the place."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  footer skipped: Pillow not installed", file=sys.stderr)
        return
    im = Image.open(path).convert("RGB")
    w, h = im.size
    size = max(14, w // 28)
    font = None
    for cand in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/Library/Fonts/Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(cand):
            font = ImageFont.truetype(cand, size)
            break
    font = font or ImageFont.load_default()
    pad = size // 2
    out = Image.new("RGB", (w, h + size + 2 * pad), "white")
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    tw = d.textlength(text, font=font)
    d.text(((w - tw) / 2, h + pad), text, fill="black", font=font)
    out.save(path)


def twin_ok(tpl, caps):
    """A memegen twin of an imgflip template only takes the row if its slots can hold the
    captions; otherwise captions land on the wrong panels (the swapped-balloon failure)."""
    return bool(tpl and tpl.get("memegen")) and len(caps) <= (tpl.get("memegen_lines") or tpl.get("boxes", 0))


def safe_name(title):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("_") or "meme"


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        cap_cols = sorted([c for c in cols if re.fullmatch(r"Caption\d+", c or "")],
                          key=lambda c: int(c[7:]))
        for row in reader:
            caps = [(row.get(c) or "").strip() for c in cap_cols]
            while caps and not caps[-1]:
                caps.pop()
            yield row, caps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["memegen", "imgflip"])
    ap.add_argument("--mode", choices=["standalone", "in-post"], default="standalone")
    ap.add_argument("--footer", help="caption strip appended under every image (standalone mode)")
    ap.add_argument("--only", help="comma-separated Meme_Title values to render")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    creds = load_creds()
    catalog = load_templates()
    only = set(args.only.split(",")) if args.only else None
    manifest, failures = [], 0

    for row, caps in read_rows(args.csv):
        title = (row.get("Meme_Title") or "").strip()
        tid = (row.get("Template_ID") or "").strip()
        if not title or (only and title not in only):
            continue
        entry = {"title": title, "template_id": tid, "captions": caps, "mode": args.mode,
                 "source": (row.get("Source") or "").strip(), "point": (row.get("Point") or "").strip()}
        path = os.path.join(args.out, safe_name(title) + ".png")
        backend = (args.backend or (row.get("Backend") or "").strip().lower()
                   or ("imgflip" if tid.isdigit() else "memegen"))
        tpl = find_template(tid, catalog)
        photos = tpls.overlay_items(row)
        try:
            if not tid or not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
                raise ValueError(f"unusable Template_ID {tid!r}")
            if photos:
                # Only memegen places photos. Routing a photo row anywhere else would render
                # the captions and silently drop the picture.
                slug = tpls.memegen_slug(tid)
                if args.backend == "imgflip" or (row.get("Backend") or "").strip().lower() == "imgflip":
                    raise ValueError("photo overlays render only through memegen; drop the imgflip backend")
                if not slug or (tid.isdigit() and not twin_ok(tpl, caps)):
                    raise ValueError(f"{tid} has no memegen version with matching boxes; photos need a memegen template")
                slots = tpls.overlay_slots(slug)
                if len(photos) > slots:
                    raise ValueError(f"{len(photos)} photos, {slug} has {slots} photo slot(s)")
                url, entry["backend"] = render_with_photos(slug, caps, photos, path, creds,
                                                           os.path.dirname(os.path.abspath(args.csv)))
                entry["overlays"] = photos
                entry["overlay_source"] = (row.get("Overlay_Source") or "").strip()
            elif backend == "memegen" and tid.isdigit():
                # An imgflip id routed to memegen: use the memegen twin if one exists,
                # otherwise the imgflip blank as a custom background.
                if twin_ok(tpl, caps):
                    url = render_memegen(tpl["memegen"], caps, path, creds)
                    entry["backend"] = "memegen"
                elif tpl and tpl.get("blank_url") and tpl.get("custom_ok"):
                    url = render_memegen_custom(tpl["blank_url"], caps, path, creds)
                    entry["backend"] = "memegen-custom"
                else:
                    raise ValueError("no memegen equivalent with matching boxes; render with imgflip credentials")
            elif backend == "imgflip":
                imgflip_id = tid if tid.isdigit() else str((tpl or {}).get("imgflip") or "")
                if not imgflip_id:
                    raise ValueError(f"no imgflip id known for {tid!r}")
                if creds.get("IMGFLIP_USERNAME") and creds.get("IMGFLIP_PASSWORD"):
                    url = render_imgflip(imgflip_id, caps, path, creds)
                    entry["backend"] = "imgflip"
                elif twin_ok(tpl, caps) and not args.backend:
                    url = render_memegen(tpl["memegen"], caps, path, creds)
                    entry["backend"] = "memegen"
                elif tpl and tpl.get("blank_url") and tpl.get("custom_ok") and not args.backend:
                    url = render_memegen_custom(tpl["blank_url"], caps, path, creds)
                    entry["backend"] = "memegen-custom"
                else:
                    raise ValueError("imgflip needs IMGFLIP_USERNAME / IMGFLIP_PASSWORD in "
                                     "~/.claude/bayou-credentials.md (see bayou-credentials.example.md)")
            else:
                url = render_memegen(tid, caps, path, creds)
                entry["backend"] = "memegen"
            footer = (row.get("Footer") or "").strip() or args.footer
            if footer:
                add_footer(path, footer)
                entry["footer"] = footer
            entry.update({"file": os.path.basename(path), "url": url})
            print(f"ok    {title}  [{entry['backend']}]")
        except (OSError, ValueError, RuntimeError, KeyError) as e:
            detail = e.read().decode(errors="replace")[:200] if isinstance(e, urllib.error.HTTPError) else ""
            entry["error"] = f"{e} {detail}".strip()
            failures += 1
            print(f"FAIL  {title}: {entry['error']}", file=sys.stderr)
        manifest.append(entry)
        time.sleep(0.3)

    manifest_path = os.path.join(args.out, "manifest.json")
    if only and os.path.exists(manifest_path):
        # A partial re-render replaces its own rows and keeps the rest, so qa.py still sees the whole set.
        with open(manifest_path, encoding="utf-8") as f:
            old = json.load(f)
        fresh = {e["title"]: e for e in manifest}
        merged = [fresh.pop(e["title"], e) for e in old]
        manifest_out = merged + list(fresh.values())
    else:
        manifest_out = manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_out, f, indent=2, ensure_ascii=False)
    print(f"\n{len(manifest) - failures} rendered, {failures} failed -> {args.out}/manifest.json")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
