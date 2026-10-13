#!/usr/bin/env python3
"""Search and verify meme templates across memegen.link and imgflip.

    templates.py search <words...>   # any template, ranked; curated entries flagged
    templates.py move <move>         # curated templates for a rhetorical move (see templates.md)
    templates.py show <id-or-slug>   # box count, roles if curated, blank image URL
    templates.py refresh             # re-verify templates.json against live catalogs

The curated list in templates.json is a starting point, not the menu. memegen has ~200
templates (searchable by name and keywords) and imgflip's get_memes returns its current
top 100 by usage, which tracks what people actually recognize right now.
Catalogs are cached for 7 days under ~/.cache/bayou/ej-meme/.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_JSON = os.path.join(HERE, "..", "references", "templates.json")
CACHE = os.path.expanduser("~/.cache/bayou/ej-meme")
UA = {"User-Agent": "bayou-ej-meme/1.0"}
TTL = 7 * 86400


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


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


def curated():
    with open(TEMPLATES_JSON, encoding="utf-8") as f:
        return json.load(f)


def curated_lookup(tid, cur=None):
    cur = cur or curated()
    for key, t in cur["templates"].items():
        if tid in (key, t.get("memegen"), str(t.get("imgflip") or "")):
            return key, t
    return None, None


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


def cmd_search(words):
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
    rows.sort(key=lambda r: -r[0])
    if not rows:
        print("no matches; try broader words, or browse: templates.py search ''")
    for _, src, tid, name, boxes, move in rows[:40]:
        print(f"{src:15} {tid:12} {boxes} box  {name}" + (f"   [{move}]" if move else ""))


def cmd_browse():
    """Everything, when a search term would be too narrow."""
    for slug, t in sorted(memegen_catalog().items()):
        print(f"memegen         {slug:22} {t['lines']} box  {t['name']}")
    for iid, m in imgflip_catalog().items():
        print(f"imgflip-top100  {iid:22} {m['box_count']} box  {m['name']}")


def cmd_move(move):
    for key, t in curated()["templates"].items():
        if move.lower() in t["move"]:
            print(f"{key:22} {t.get('memegen') or '-':18} {t['imgflip']:<11} {t['recognizability']:6}  {t['name']}")


def cmd_show(tid):
    key, t = curated_lookup(tid)
    if t:
        print(json.dumps({key: t}, indent=2))
        return
    if tid.isdigit():
        m = imgflip_catalog().get(tid)
        print(json.dumps(m, indent=2) if m else "not in imgflip top 100 (may still exist; render to check)")
    else:
        m = memegen_catalog().get(tid)
        if m:
            print(json.dumps({k: m[k] for k in ("id", "name", "lines", "keywords", "blank", "example")}, indent=2))
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


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "search":
        cmd_browse() if not "".join(rest).strip() else cmd_search(rest)
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
