"""Louisiana Division of Administrative Law: the hearing docket and the Ethics/BOE decision search.

DAL publishes decisions online only for Ethics and Board of Ethics matters. LDEQ, DCE (Conservation
and Energy) and DENR decisions are obtainable only by public records request.
"""
import re
import urllib.parse

import court_common as cc

DOCKET = "https://www.adminlaw.la.gov/docket.html"
ETHICS = "https://www.adminlaw.la.gov/ethics-decisions/"


def docket(cache, agency=None, grep=None):
    page = cc.cached_text(DOCKET, cache, "dal", "docket.html", 1)
    rows = []
    for tr in re.finditer(r"<tr\b([^>]*)>(.*?)</tr>", page, re.S | re.I):
        cells = {m.group(1): cc.clean(re.sub(r"<[^>]+>", " ", m.group(2)))
                 for m in re.finditer(r'<td class="([a-z]+)">(.*?)</td>', tr.group(2), re.S)}
        if "matter" not in cells:
            continue
        matter = cells["matter"]
        suffix = matter.rsplit("-", 1)[-1] if "-" in matter else ""
        date = re.search(r'data-date="([^"]+)"', tr.group(1))
        rows.append({"date": date.group(1) if date else cells.get("date"), "time": cells.get("time"),
                     "matter": matter, "agency": suffix, "case": cells.get("desc"),
                     "event": cells.get("ldesc"), "location": cells.get("location")})
    if agency:
        want = {a.upper() for a in agency}
        rows = [r for r in rows if r["agency"].upper() in want]
    if grep:
        rx = re.compile(grep, re.I)
        rows = [r for r in rows if rx.search(r["case"] or "") or rx.search(r["matter"])]
    return rows


def ethics(terms, page=1):
    """(total, [results]) from DAL's Ethics/BOE decision search, which renders server-side."""
    url = ETHICS + "?" + urllib.parse.urlencode({"id": 6, "search": terms, "_page": page})
    body = cc.fetch_text(url)
    total = re.search(r"([\d,]+) documents? found", body)
    out = []
    for m in re.finditer(r'<div class="search-result">(.*?)(?=<div class="search-result">|</main>|$)', body, re.S):
        a = re.search(r'class="search-result-document" href="([^"]+)"[^>]*>(.*?)</a>', m.group(1), re.S)
        if not a:
            continue
        snip = re.search(r'<p class="snippet">(.*?)</p>', m.group(1), re.S)
        title = cc.clean(a.group(2))
        out.append({"title": title, "matter": title.split(",")[0], "pdf": a.group(1),
                    "snippet": cc.clean(re.sub(r"<[^>]+>", "", snip.group(1)))[:300] if snip else None})
    return int(total.group(1).replace(",", "")) if total else len(out), out
