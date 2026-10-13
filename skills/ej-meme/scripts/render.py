#!/usr/bin/env python3
"""Render meme CSV rows to PNGs plus a manifest.json.

CSV schema (same as the old petro-meme-gen sheets, so they render unchanged):
    Meme_Title, Template_ID, Caption1 .. CaptionN [, Backend] [, Source] [, Point] [, Footer]

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
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
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
    # memegen treats an empty line as "use template default"; "_" is its explicit blank.
    return [c if c.strip() else "_" for c in captions]


def render_memegen(slug, captions, path, creds):
    headers = {"X-API-KEY": creds["MEMEGEN_API_KEY"]} if creds.get("MEMEGEN_API_KEY") else {}
    res = http_json("https://api.memegen.link/images",
                    {"template_id": slug, "text": memegen_text(captions), "extension": "png"},
                    headers)
    download(res["url"], path, headers)
    return res["url"]


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
        try:
            if not tid or not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
                raise ValueError(f"unusable Template_ID {tid!r}")
            if backend == "memegen" and tid.isdigit():
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
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, RuntimeError, KeyError) as e:
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
