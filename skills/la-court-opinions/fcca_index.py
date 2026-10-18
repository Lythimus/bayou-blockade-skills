"""Louisiana First Circuit Court of Appeal opinion index, read from the court's own CivicLive site.

CourtListener stops carrying First Circuit opinions after 2018, so this is the only searchable
source for recent LDEQ permit appeals. Each year page on la-fcca.org/decisions embeds a
ContentItemListUI widget whose folder the site fills from an open JSON service; this module calls
that service directly.

Folders are grouped by DOCKET year, not decision year: 2023 CA 0578 sits in the 2023 folder
although it was decided in January 2024. Item dates on the site are upload dates.
"""
import datetime
import json
import os
import re
import sys

import court_common as cc

DECISIONS = "https://www.la-fcca.org/decisions"
HOST = "https://lafcca.hosted2.civiclive.com"
SVC = HOST + "/portal/svc/ContentItemSvc.asmx/GetItemList"
# A full year runs ~1.6 MB of JSON; 1988-2005 is one small folder.
YEAR_MB = 1.6
# Six indexes (~10 MB) covers a five-year search; a full sweep (~30 MB) needs --yes.
GUARD_MAX_YEARS = 6


def year_pages(cache):
    """[(first_year, last_year, label, url)] newest first, from the decisions landing page."""
    page = cc.cached_text(DECISIONS, cache, "fcca", "decisions.html", 7)
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        href, label = cc.clean(m.group(1)), cc.clean(re.sub(r"<[^>]+>", "", m.group(2)))
        if "civiclive.com" not in href:
            continue
        y = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", label)
        if y:
            first = int(y.group(1))
            out.append((first, int(y.group(2) or first), label, href))
    if not out:
        raise RuntimeError("no year links found on %s; the page layout may have changed" % DECISIONS)
    return sorted(set(out), reverse=True)


def _ttl(last_year):
    # Recent folders gain opinions daily; older ones still get late uploads, so they expire too.
    return 1 if last_year >= datetime.date.today().year - 1 else 30


def _index_path(cache, label):
    return os.path.join(cc.sub_dir(cache, "fcca"), "index_%s.json" % label.replace(" ", ""))


def _widget(cache, label, url):
    """(folder_id, params_json_string) for a year page; the folder is stable, so cache it long."""
    path = os.path.join(cc.sub_dir(cache, "fcca"), "widget_%s.json" % label.replace(" ", ""))
    if cc.fresh(path, 90):
        with open(path) as fh:
            w = json.load(fh)
        return w["folder"], w["params"]
    page = cc.fetch_text(url)
    m = re.search(r"new ContentItemListUI\('(\d+)', null, '(\[.*?\])', (\{.*?\}), selectMultiSwitch", page)
    if not m:
        raise RuntimeError("no opinion folder widget on %s" % url)
    cc.write_atomic(path, json.dumps({"folder": m.group(1), "params": m.group(3)}))
    return m.group(1), m.group(3)


def needed(pages, y_from, y_to):
    return [p for p in pages if p[1] >= y_from and p[0] <= y_to]


def guard(cache, pages, yes):
    stale = [p for p in pages if not cc.fresh(_index_path(cache, p[2]), _ttl(p[1]))]
    if not stale:
        return
    mb = sum(0.1 if p[0] != p[1] else YEAR_MB for p in stale)
    msg = "First Circuit index: %d year folder(s) to fetch (%s), ~%.0f MB of JSON, cached under %s" % (
        len(stale), ", ".join(p[2] for p in stale), mb, cache)
    if len(stale) > GUARD_MAX_YEARS and not yes:
        raise cc.GuardStop(msg + " -- over the %d-folder limit; narrow --from/--to or rerun with --yes" % GUARD_MAX_YEARS)
    print(msg, file=sys.stderr)


def year_items(cache, page):
    first, last, label, url = page
    path = _index_path(cache, label)
    if not cc.fresh(path, _ttl(last)):
        folder, params = _widget(cache, label, url)
        body = json.dumps({"parentId": int(folder), "Params": params}).encode()
        raw = json.loads(cc.fetch(SVC, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=120))
        items = (raw.get("d") or {}).get("DataObject") or []
        kept = [_slim(x, label) for x in items if x.get("Type") == "content_item"]
        if not kept:
            # An empty year means the folder moved or switched to subfolders, not that no opinions issued.
            raise RuntimeError("First Circuit folder %s returned no documents (%d raw items); the site layout may have "
                               "changed. Do not report this year as having no opinions." % (label, len(items)))
        cc.write_atomic(path, json.dumps(kept))
    with open(path) as fh:
        return json.load(fh)


def _slim(x, label):
    title = cc.clean(x.get("Title") or x.get("Name"))
    return {"title": title, "link": x.get("Link") or x.get("DownloadLink"), "bytes": int(x.get("FileSize") or 0),
            "uploaded": x.get("CreationDateString"), "folder": label}


def record(item):
    title = item["title"]
    d = cc.parse_docket(title, url=HOST)
    caption = title
    if d:
        m = re.match(r"\s*\d{2,4}\s+[A-Z]{1,3}\s+\d{3,4}\s*(?:\(\d+\)|-\s*\d+)?\s*", title)
        caption = title[m.end():] if m else title
    part = re.search(r"\((\d+)\)", title)
    return {
        "source": "la-fcca.org",
        "court_id": "lactapp",
        "circuit": 1,
        "court": "La. App. 1 Cir.",
        "caption": re.sub(r"\s*\(\d+\)\s*$", "", caption).strip(" -"),
        "title": title,
        "docket_raw": d["text"] if d else None,
        "docket": d,
        "key": d["key"] if d else "fcca:" + item["link"],
        "document": int(part.group(1)) if part else 1,
        "decision_date": None,  # only the PDF text carries it; see `fetch`
        "uploaded": item["uploaded"],
        "folder": item["folder"],
        "bytes": item["bytes"],
        "pdf": item["link"],
        "url": item["link"],
    }


def search(cache, terms, y_from, y_to, yes=False):
    """Caption search: every term must appear in the title (case-insensitive)."""
    pages = needed(year_pages(cache), y_from, y_to)
    guard(cache, pages, yes)
    want = [t.lower() for t in terms]
    out = []
    for p in pages:
        for it in year_items(cache, p):
            low = it["title"].lower()
            if all(t in low for t in want):
                out.append(record(it))
    return out


def by_docket(cache, d, yes=False):
    """Every document filed under one docket. The following year's folder is checked too, because
    folders are filled by hand and a misfiled upload would otherwise read as "not found"."""
    y = d["year"]
    pages = needed(year_pages(cache), y, y + 1)
    guard(cache, pages, yes)
    out = []
    for p in pages:
        for it in year_items(cache, p):
            r = record(it)
            if r["docket"] and r["docket"]["key" if d["type"] else "loose"] == d["key" if d["type"] else "loose"]:
                out.append(r)
    return out
