#!/usr/bin/env python3
"""Search and verify meme templates across memegen.link and imgflip.

    templates.py search <words...>   # any template, ranked; curated entries flagged
                                     # --photo: only templates with photo slots ("+1 photo")
    templates.py imgflip <words...>  # imgflip's full catalog by name, not just its top 100
    templates.py kym [--pages N] [--new]
                                     # Know Your Meme exploitables, most-viewed first,
                                     # each matched to a renderable imgflip template
    templates.py recent              # which templates past meme sets already used
    templates.py move <move>         # curated templates for a rhetorical move (see templates.md)
    templates.py show <id-or-slug>   # box count, roles if curated, blank image URL, photo slots
    templates.py refresh             # re-verify templates.json against live catalogs

    --history DIR (search, imgflip, kym, recent): where to look for past sets
    (memes/*/manifest.json or memes.csv, recursively). Default: the current directory.

The curated list in templates.json is a starting point, not the menu. memegen has ~200
templates (searchable by name and keywords) and imgflip's get_memes returns its current
top 100 by usage. Both lean on the same classics, which is why sets kept repeating; the
imgflip and kym commands reach past them, and "used Nx" marks show what to rotate out.
Catalogs and scraped pages are cached for 7 days under ~/.cache/bayou/ej-meme/.
"""
import csv
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_JSON = os.path.join(HERE, "..", "references", "templates.json")
CACHE = os.path.expanduser("~/.cache/bayou/ej-meme")
UA = {"User-Agent": "bayou-ej-meme/1.0"}
TTL = 7 * 86400


def fetch(url):
    return json.loads(fetch_text(url))


def fetch_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def memo(name, key, compute):
    """Cache a scraped result under key in CACHE/name, so repeated kym runs don't
    re-hit dozens of pages."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    try:
        with open(path, encoding="utf-8") as f:
            store = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        store = {}
    hit = store.get(key)
    if hit and time.time() - hit["t"] < TTL:
        return hit["v"]
    v = compute()
    store[key] = {"t": time.time(), "v": v}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f)
    return v


def cached(name, url, force=False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = fetch(url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def memegen_catalog(force=False):
    # Some slugs appear twice with different line counts; keep the larger so lint never
    # rejects a box the template actually has.
    out = {}
    for t in cached("memegen.json", "https://api.memegen.link/templates/", force):
        prev = out.get(t["id"])
        if not prev or t["lines"] > prev["lines"]:
            out[t["id"]] = t
    return out


def imgflip_catalog(force=False):
    data = cached("imgflip.json", "https://api.imgflip.com/get_memes", force)
    return {str(m["id"]): m for m in data["data"]["memes"]}


def imgflip_search(query):
    """imgflip's own template search, in its ranking order. Reaches the whole catalog;
    the get_memes API only returns the top 100. Many hits are user re-uploads of the
    same picture, so the first hit for a name is usually the canonical one."""
    def compute():
        page = fetch_text("https://imgflip.com/memesearch?q=" + urllib.parse.quote_plus(query))
        out, seen = [], set()
        for iid, slug in re.findall(r'href="/meme/(\d+)/([^"/]+)"', page):
            if iid not in seen:
                seen.add(iid)
                out.append([iid, urllib.parse.unquote(slug).replace("-", " ")])
        return out
    return memo("imgflip-search.json", query.lower(), compute)


def imgflip_template(iid):
    """Blank URL and size from imgflip's template page. imgflip doesn't publish box
    counts outside get_memes, so a template found this way needs a BOX 1..N test render."""
    def compute():
        page = fetch_text(f"https://imgflip.com/memetemplate/{iid}")
        blank = re.search(r"//i\.imgflip\.com/[a-z0-9]+\.(?:jpg|png|gif)", page)
        dims = re.search(r"Dimensions:\s*(\d+)x(\d+)", page)
        title = re.search(r'<h1[^>]*>([^<]*?)\s*Template', page)
        return {
            "id": iid,
            "name": html.unescape(title.group(1)).strip() if title else None,
            "blank_url": "https:" + blank.group(0) if blank else None,
            "width": int(dims.group(1)) if dims else None,
            "height": int(dims.group(2)) if dims else None,
            "box_count": None,
        }
    return memo("imgflip-templates.json", iid, compute)


# Know Your Meme's exploitables include crude, cruel and national-political formats that
# break tone-and-boundaries.md. KYM's own /sensitive/ path catches most crude ones; these
# catch the rest. "loss" is a webcomic about a miscarriage; "groyper" is a white-nationalist
# mascot; "zamn" is a joke about a minor. Views-sorted pages still need a human read:
# this list only catches what has shown up so far.
KYM_BLOCK = re.compile(
    r"\b(trump|biden|obama|clinton|hillary|bush|putin|maga|lock.em.up|hitler|nazi|isis|9/11|"
    r"saddam|brazzers|titty|porn|sex|nsfw|gooner|shit|fuck|nut|cum|loss|kill|suicide|"
    r"pepe|groyper|zamn|she.?s 12|political|undress|nazi|racist)\b", re.I)


def kym_exploitables(page):
    """One page of KYM's exploitable (reusable-template) memes, sorted by views. Views
    favor formats that have been around long enough for an older audience to know."""
    def compute():
        src = fetch_text(f"https://knowyourmeme.com/types/exploitable/page/{page}?sort=views")
        out = []
        for tag in re.findall(r'<a class="item"[^>]*>', src):
            a = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
            href, title = a.get("href", ""), html.unescape(a.get("data-title", "")).strip()
            if not href.startswith(("/memes/", "/sensitive/")) or not title:
                continue
            out.append({"title": title, "url": "https://knowyourmeme.com" + href,
                        "sensitive": href.startswith("/sensitive/"),
                        "about": html.unescape(a.get("alt", "")).strip()})
        return out
    return memo("kym-exploitable.json", str(page), compute)


def history(root):
    """Template ids used by past meme sets under root, as {id: [set names]}. A set is a
    rendered folder (manifest.json) or any CSV in the meme schema (Meme_Title +
    Template_ID columns), which also picks up the old campaign sheets like memes_imtt.csv."""
    used = {}
    root = os.path.abspath(root)
    sets = []
    # os.walk without followlinks: project trees here contain symlink loops, which a
    # recursive glob follows forever.
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
        rendered = "manifest.json" in files
        if rendered:
            try:
                with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
                rows = m if isinstance(m, list) else m.get("memes", [])
                sets.append((os.path.relpath(d, root),
                             [str(r.get("template_id") or "") for r in rows if isinstance(r, dict)]))
            except (json.JSONDecodeError, OSError, AttributeError):
                rendered = False
        for fn in files:
            # The CSV a manifest was rendered from is the same set; don't count it twice.
            if not fn.lower().endswith(".csv") or (rendered and fn == "memes.csv"):
                continue
            try:
                with open(os.path.join(d, fn), newline="", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    if not {"Meme_Title", "Template_ID"} <= set(reader.fieldnames or []):
                        continue
                    ids = [(r.get("Template_ID") or "").strip() for r in reader]
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
            sets.append((os.path.relpath(os.path.join(d, fn), root), ids))
    for name, ids in sets:
        for i in filter(None, ids):
            for alias in aliases(i):
                used.setdefault(alias, [])
                if name not in used[alias]:
                    used[alias].append(name)
    return used


def aliases(tid):
    """A template's memegen slug and imgflip id are the same picture; count use under both."""
    _, t = curated_lookup(tid)
    if not t:
        return {tid}
    return {x for x in (tid, t.get("memegen"), str(t.get("imgflip") or "")) if x}


def used_mark(tid, used):
    n = len(used.get(tid, []))
    return f"   (used in {n} past set{'s' if n > 1 else ''})" if n else ""


def curated():
    with open(TEMPLATES_JSON, encoding="utf-8") as f:
        return json.load(f)


def curated_lookup(tid, cur=None):
    cur = cur or curated()
    for key, t in cur["templates"].items():
        if tid in (key, t.get("memegen"), str(t.get("imgflip") or "")):
            return key, t
    return None, None


def memegen_slug(tid):
    """The memegen template that renders tid: tid itself if it's a slug, else the curated
    twin of an imgflip id. None for imgflip-only templates."""
    if not tid.isdigit():
        return tid
    _, t = curated_lookup(tid)
    return (t or {}).get("memegen")


def overlay_slots(slug):
    """How many photos a memegen template can hold (0 if none, or unknown)."""
    try:
        return (memegen_catalog().get(slug) or {}).get("overlays") or 0
    except Exception:
        return 0


def overlay_geometry(slug):
    """Slot placement from the template's config.yml in the memegen repo: center_x,
    center_y and scale as fractions of the image, angle in degrees. The API reports only
    the slot count, so the local compositor reads the same file memegen itself does."""
    def compute():
        y = fetch_text(f"https://raw.githubusercontent.com/jacebrowning/memegen/main/templates/{slug}/config.yml")
        m = re.search(r"^overlay:\s*\n((?:[ \t-].*(?:\n|$))*)", y, re.M)
        if not m:
            return []
        slots = []
        for item in re.split(r"^\s*-\s", m.group(1), flags=re.M)[1:]:
            d = dict(re.findall(r"(\w+):\s*(-?[\d.]+)", item))
            slots.append({k: float(d.get(k, dflt)) for k, dflt in
                          (("center_x", 0.5), ("center_y", 0.5), ("angle", 0.0), ("scale", 0.25))})
        return slots
    return memo("overlay-geometry.json", slug, compute)


def overlay_items(row):
    """The row's Overlay column as a list, one photo per slot, in slot order."""
    return [p.strip() for p in (row.get("Overlay") or "").split("|") if p.strip()]


def is_url(p):
    return p.lower().startswith(("http://", "https://"))


def style_safe(p):
    """True if memegen can take this URL in its style parameter. memegen puts the URL
    in the returned link unencoded and splits style on commas, so a query string or comma
    gets cut short; those are downloaded and composited locally instead."""
    return p.startswith("https://") and not re.search(r"[?&#,]", p)


def resolve_local(p, base_dir):
    """A local overlay path as written, or relative to the CSV's folder."""
    p = os.path.expanduser(p)
    if os.path.isabs(p) or os.path.exists(p):
        return p
    return os.path.join(base_dir, p)


def box_limit(tid):
    """(min, max) boxes for a template id or slug, or None if unknown anywhere."""
    _, t = curated_lookup(tid)
    if t:
        return t.get("min_boxes", 1), max(t.get("boxes", 1), t.get("max_boxes", 0))
    try:
        if tid.isdigit():
            m = imgflip_catalog().get(tid)
            return (1, m["box_count"]) if m else None
        m = memegen_catalog().get(tid)
        return (1, m["lines"]) if m else None
    except Exception:
        return None


def score(query_words, *fields):
    text = " ".join(f for f in fields if f).lower()
    return sum(2 if re.search(rf"\b{re.escape(w)}\b", text) else (1 if w in text else 0) for w in query_words)


def photo_mark(slug):
    n = overlay_slots(slug) if slug else 0
    return f" +{n} photo" if n else ""


def cmd_search(words, used, photo=False):
    q = [w.lower() for w in words]
    cur = curated()
    curated_ids = {}
    for key, t in cur["templates"].items():
        for i in (t.get("memegen"), str(t.get("imgflip") or "")):
            if i:
                curated_ids[i] = key
    rows = []
    for key, t in cur["templates"].items():
        s = score(q, key, t["name"], t["move"], " ".join(t["roles"]), t.get("notes", ""))
        if s:
            rows.append((s + 1, "curated", t.get("memegen") or str(t["imgflip"]), t["name"], t["boxes"], t["move"]))
    for slug, t in memegen_catalog().items():
        if slug in curated_ids:
            continue
        s = score(q, slug, t["name"], " ".join(t.get("keywords") or []))
        if s:
            rows.append((s, "memegen", slug, t["name"], t["lines"], ""))
    for iid, m in imgflip_catalog().items():
        if iid in curated_ids:
            continue
        s = score(q, m["name"])
        if s:
            rows.append((s, "imgflip-top100", iid, m["name"], m["box_count"], ""))
    if photo:
        rows = [r for r in rows if overlay_slots(memegen_slug(r[2]))]
    rows.sort(key=lambda r: -r[0])
    if not rows:
        print("no matches; try broader words, or browse: templates.py search ''")
    for _, src, tid, name, boxes, move in rows[:40]:
        print(f"{src:15} {tid:12} {boxes} box{photo_mark(memegen_slug(tid))}  {name}"
              + (f"   [{move}]" if move else "") + used_mark(tid, used))
    print("\nnot here? templates.py imgflip <words> searches imgflip's whole catalog")


def cmd_browse(used, photo=False):
    """Everything, when a search term would be too narrow."""
    for slug, t in sorted(memegen_catalog().items()):
        if photo and not t.get("overlays"):
            continue
        print(f"memegen         {slug:22} {t['lines']} box{photo_mark(slug)}  {t['name']}{used_mark(slug, used)}")
    if photo:
        return
    for iid, m in imgflip_catalog().items():
        print(f"imgflip-top100  {iid:22} {m['box_count']} box  {m['name']}{used_mark(iid, used)}")


def known_ids():
    """Ids already reachable through search/browse, so kym --new can skip them."""
    ids = set(memegen_catalog()) | set(imgflip_catalog())
    for t in curated()["templates"].values():
        ids |= {x for x in (t.get("memegen"), str(t.get("imgflip") or "")) if x}
    return ids


def cmd_imgflip(words, used):
    q = " ".join(words)
    top = imgflip_catalog()
    hits = imgflip_search(q)
    if not hits:
        print(f"no imgflip templates for {q!r}")
    for iid, name in hits[:15]:
        tag = "imgflip-top100" if iid in top else "imgflip"
        print(f"{tag:15} {iid:12} {name}{used_mark(iid, used)}")
    print("\nfirst hit is usually the canonical upload; later ones are often re-uploads."
          "\nOutside the top 100 the box count is unknown: show <id>, then render BOX 1..N.")


def norm(name):
    name = re.sub(r"[^a-z0-9 ]+", " ", html.unescape(name).lower())
    return " ".join(w for w in name.split() if w not in ("the", "a", "meme", "template", "blank"))


def known_names():
    """Normalized name -> (id, name) for every template search/browse already reaches."""
    out = {}
    for iid, m in imgflip_catalog().items():
        out.setdefault(norm(m["name"]), (iid, m["name"]))
    for slug, t in memegen_catalog().items():
        out.setdefault(norm(t["name"]), (slug, t["name"]))
    for key, t in curated()["templates"].items():
        tid = t.get("memegen") or str(t.get("imgflip"))
        for n in (t["name"], key.replace("-", " ")):
            out.setdefault(norm(n), (tid, t["name"]))
    return out


def match_known(title, names):
    """KYM titles and catalog names differ in small ways ("Awkward Look Monkey Puppet" vs
    "Monkey Puppet"); match whole-name or containment either way."""
    t = norm(title)
    if t in names:
        return names[t]
    for n, v in names.items():
        if len(n) > 5 and (n in t or t in n):
            return v
    return None


def best_hit(title, hits, known):
    """imgflip search returns re-uploads alongside the canonical template. Prefer a hit
    already in a known catalog, then the closest name, then imgflip's own first pick."""
    for iid, name in hits[:10]:
        if iid in known:
            return iid, name
    t = norm(title)
    for iid, name in hits[:10]:
        if norm(name) == t:
            return iid, name
    return hits[0]


def cmd_kym(pages, only_new, used):
    known = known_ids()
    names = known_names()
    shown = 0
    for page in range(1, pages + 1):
        try:
            entries = kym_exploitables(page)
        except Exception as e:
            print(f"! KYM page {page}: {e}", file=sys.stderr)
            break
        for e in entries:
            if e["sensitive"] or KYM_BLOCK.search(e["title"] + " " + e["about"]):
                continue
            if norm(e["title"]) in ("", "memes"):
                # KYM's catch-all "Memes" entry, not a format.
                continue
            match = match_known(e["title"], names)
            if match:
                iid, name = match
            else:
                try:
                    hits = imgflip_search(e["title"])
                except Exception:
                    hits = []
                if not hits:
                    # Some KYM entries are reaction images or video formats with no caption
                    # template; nothing to render.
                    continue
                iid, name = best_hit(e["title"], hits, known)
            if only_new and iid in known:
                continue
            tag = "new" if iid not in known else "known"
            print(f"{tag:6} {iid:12} {e['title']}  (imgflip: {name}){used_mark(iid, used)}")
            if e["about"] and e["about"].lower() != e["title"].lower():
                print(f"       {e['about'][:90]}")
            print(f"       {e['url']}")
            shown += 1
            time.sleep(0.5)
    print(f"\n{shown} formats. Most-viewed first; still apply templates.md's five checks."
          "\nThe imgflip match is by name: confirm the picture with show <id> before using it.")


def cmd_recent(root):
    used = history(root)
    if not used:
        print(f"no past meme sets under {os.path.abspath(root)}")
        return
    names = {}
    for slug, t in memegen_catalog().items():
        names[slug] = t["name"]
    for iid, m in imgflip_catalog().items():
        names.setdefault(iid, m["name"])
    seen = set()
    rows = []
    for tid, sets in used.items():
        key = frozenset(aliases(tid))
        if key in seen:
            continue
        seen.add(key)
        label = next((names[a] for a in sorted(key) if a in names), tid)
        rows.append((len(sets), "/".join(sorted(key)), label, sets))
    for n, ids, label, sets in sorted(rows, key=lambda r: -r[0]):
        print(f"{n:3} sets  {ids:24} {label}")
        print(f"      {', '.join(sets[:4])}" + (" ..." if len(sets) > 4 else ""))


def cmd_move(move):
    for key, t in curated()["templates"].items():
        if move.lower() in t["move"]:
            print(f"{key:22} {t.get('memegen') or '-':18} {t['imgflip']:<11} {t['recognizability']:6}  {t['name']}")


def show_slots(tid):
    slug = memegen_slug(tid)
    if not overlay_slots(slug):
        return
    try:
        print("photo slots (fractions of the image; scale is the side of a square the photo fits in):")
        for i, s in enumerate(overlay_geometry(slug), 1):
            print(f"  {i}: center ({s['center_x']}, {s['center_y']})  scale {s['scale']}  angle {s['angle']}")
    except Exception as e:
        print(f"photo slots: {overlay_slots(slug)} (geometry unavailable: {e})")


def cmd_show(tid):
    key, t = curated_lookup(tid)
    if t:
        print(json.dumps({key: t}, indent=2))
        show_slots(tid)
        return
    if tid.isdigit():
        m = imgflip_catalog().get(tid)
        if m:
            print(json.dumps(m, indent=2))
        else:
            info = imgflip_template(tid)
            print(json.dumps(info, indent=2))
            print("outside imgflip's top 100: box count unknown; render BOX 1..N to find the boxes")
    else:
        m = memegen_catalog().get(tid)
        if m:
            print(json.dumps({k: m[k] for k in ("id", "name", "lines", "overlays", "keywords", "blank", "example")}, indent=2))
            show_slots(tid)
        else:
            print("unknown memegen slug")


def cmd_refresh():
    cur = curated()
    mg, ifl = memegen_catalog(force=True), imgflip_catalog(force=True)
    problems = 0
    for key, t in cur["templates"].items():
        if t.get("memegen"):
            m = mg.get(t["memegen"])
            if not m:
                print(f"! {key}: memegen slug {t['memegen']!r} not in catalog")
                problems += 1
            else:
                t["memegen_lines"] = m["lines"]
                t["overlays"] = m.get("overlays") or 0
        if t.get("imgflip"):
            m = ifl.get(str(t["imgflip"]))
            if m:
                t["imgflip_box_count"] = m["box_count"]
                t["blank_url"] = m["url"]
                t["imgflip_name"] = m["name"]
            elif not t.get("blank_url"):
                # Outside the top 100 the id can still be valid; it just can't be checked here.
                print(f"? {key}: imgflip {t['imgflip']} not in current top 100; keeping as-is")
    cur["verified_at"] = datetime.date.today().isoformat()
    with open(TEMPLATES_JSON, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"refreshed {len(cur['templates'])} templates, {problems} problems")
    sys.exit(1 if problems else 0)


def take_opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
    return default


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    root = take_opt(rest, "--history", ".")
    pages = int(take_opt(rest, "--pages", "4"))
    only_new = "--new" in rest
    photo = "--photo" in rest
    rest = [r for r in rest if r not in ("--new", "--photo")]
    if cmd == "search":
        used = history(root)
        cmd_browse(used, photo) if not "".join(rest).strip() else cmd_search(rest, used, photo)
    elif cmd == "imgflip" and rest:
        cmd_imgflip(rest, history(root))
    elif cmd == "kym":
        cmd_kym(pages, only_new, history(root))
    elif cmd == "recent":
        cmd_recent(root)
    elif cmd == "move" and rest:
        cmd_move(rest[0])
    elif cmd == "show" and rest:
        cmd_show(rest[0])
    elif cmd == "refresh":
        cmd_refresh()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
