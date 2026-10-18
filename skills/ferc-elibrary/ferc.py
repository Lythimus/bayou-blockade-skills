#!/usr/bin/env python3
"""FERC eLibrary: docket filings, EIS/EA documents, orders, notices, intervention movants, and public file
downloads, through the anonymous JSON API behind the eLibrary web app (no login, no browser).

Run with: uv run -q --no-project python -I ferc.py <command> ...
Searches and the class/type vocabulary are cached for a day (--refresh forces a re-fetch).
Cache: ~/.cache/bayou/ferc-elibrary/.

  ferc.py health                                   API up, vocabulary loads, CP22-21 totalHits == unique rows paged
  ferc.py docket <CP22-21[-001]> [--class C [--type T]] [--since D --until D --date-type filed|issued|posted]
                 [--text Q] [--limit N | --all]    filings on a docket, with availability and co-listed dockets
  ferc.py eis <docket>                             EA / EIS / scoping / environmental-report documents
  ferc.py orders <docket>                          Commission and delegated orders (certificate, rehearing, stay)
  ferc.py notices <docket>                         notices, with deadlines parsed from the descriptions
  ferc.py movants <docket>                         who moved to intervene, grouped by filer (movants, not parties)
  ferc.py files <accession|documentId>             transmittal files with sizes and per-file availability
  ferc.py get <accession> [--file N ...] [--out DIR] [--yes]   download the public files of one accession
  ferc.py search <text> [--fulltext] [--docket D] [--since D --until D] [--limit N]
  ferc.py classes [text]                           valid Class / Type pairs for --class/--type
"""
import argparse
import collections
import datetime
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

CACHE = os.path.expanduser("~/.cache/bayou/ferc-elibrary")
TTL = 24 * 3600
UA = "Mozilla/5.0 (bayou-ferc-elibrary)"
SITE = "https://elibrary.ferc.gov/eLibrary/"
CONFIG = SITE + "assets/config/app-settings.json"
API = "https://elibrary.ferc.gov/eLibraryWebAPI/api/"
DOC_LINK = SITE + "filelist?accession_number=%s"
SERVICE_LIST = "https://ferconline.ferc.gov/eServiceList.aspx"
HEALTH_DOCKET = "CP22-21"
PER_PAGE = 200
PAUSE = 0.5
BIG_BYTES = 25 * 1024 * 1024
BIG_FILES = 10

DATE_TYPES = {"filed": "filed_date", "issued": "issued_date", "posted": "posted_date"}
AVAIL = {"P": "public", "C": "CEII", "N": "non-public (privileged)"}
RESTRICTED_ROUTE = {
    "C": "CEII (18 CFR 388.113). A movant or intervenor can ask the filer directly with an executed protective "
         "agreement, due in 5 business days absent objection (g)(4); a landowner near the project can get "
         "alignment sheets from staff with proof of property interest (g)(3); anyone else files a request "
         "with FERC's CEII Coordinator, with a non-disclosure agreement (g)(5).",
    "N": "Privileged (18 CFR 388.112): parties can usually get it under the proceeding's protective agreement; "
         "anyone else files a FOIA request with the Director, Office of External Affairs (18 CFR 388.108).",
}

EIS_TYPES = [("FERC Report/Study", "Environmental Assessment (EA) and Environmental Impact Statement (EIS)"),
             ("FERC Report/Study", "Scoping Document"),
             ("FERC Report/Study", "Environmental Report")]
ORDER_TYPES = [("Order/Opinion", "Commission Order/Opinion"), ("Order/Opinion", "Delegated Order")]
INTERVENTION_CLASS = "Intervention"

# Ordered most specific first: "Final Supplemental" must win over "Final Environmental Impact".
EIS_KIND = [(r"final\s+supplemental", "FSEIS"), (r"draft\s+supplemental", "DSEIS"),
            (r"supplemental\s+(draft|environmental impact)", "SEIS"),
            (r"final\s+environmental\s+impact", "FEIS"), (r"draft\s+environmental\s+impact", "DEIS"),
            (r"environmental\s+assessment", "EA"), (r"scoping", "scoping"),
            (r"environmental\s+impact\s+statement", "EIS")]
ORDER_FLAG = [(r"rehearing", "rehearing"), (r"\bstay\b", "stay"), (r"remand", "remand"),
              (r"certificate|authoriz|granting\s+(section|authority)|section\s+[37]", "authorization"),
              (r"extension\s+of\s+time", "extension"),
              (r"notice\s+to\s+proceed|variance|commence|request\s+to\s+(construct|modify|use)", "construction")]

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = r"(\d{1,2}/\d{1,2}/\d{2,4}|(?:%s)\.?\s+\d{1,2},?\s+\d{4})" % MONTHS
DEADLINE_RE = re.compile(
    r"((?:comments?|interventions?|protests?|motions? to intervene|scoping|responses?|answers?)[^.;]{0,80}?"
    r"(?:due|date|deadline|on or before|by|until|no later than)[^.;]{0,40}?" + DATE_RE + r")", re.I)
# What a notice starts or records. eLibrary descriptions almost never carry the deadline itself; the
# date is in the notice PDF ("Comment Date: 5:00 pm Eastern Time on ...").
NOTICE_KIND = [(r"intent to prepare|scoping|request for comments", "opens scoping comments"),
               (r"availability of the draft", "opens draft EIS/EA comments"),
               (r"filing of an application|intervention deadline|application", "opens interventions/protests"),
               (r"availability of the (final|environmental assessment)", "final EIS/EA issued"),
               (r"granting late intervention", "late interventions granted"),
               (r"rehearing by operation of law", "rehearing deemed denied"),
               (r"schedule", "review schedule"), (r"technical conference|public (meeting|session)", "meeting")]


class SourceDown(Exception):
    pass


class NotFound(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def iso(mdy):
    try:
        return datetime.datetime.strptime(mdy, "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return mdy or ""


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024


# ---------------------------------------------------------------- HTTP

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _open(url, data=None, headers=None, timeout=180):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Referer": SITE}
    h.update(headers or {})
    try:
        return _opener.open(urllib.request.Request(url, data=data, headers=h), timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        if e.code in (400, 404):
            raise NotFound("%s: HTTP %d %s" % (url, e.code, body.strip()[:160]))
        raise SourceDown("%s: HTTP %d" % (url, e.code))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceDown("%s: %s" % (url, e))


def _json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with _open(url, data, {"Content-Type": "application/json"} if data else None) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    # Cloudflare and the F5 WAF in front of FERC answer blocked requests with a 200 HTML page,
    # which would otherwise surface as a JSON decode error or, worse, as zero results.
    if "json" not in ctype or raw.lstrip()[:1] == b"<":
        title = re.search(rb"<title>(.*?)</title>", raw, re.I | re.S)
        raise SourceDown("%s returned %s instead of JSON (%s)" % (
            url, ctype or "no content type", title.group(1).decode("utf-8", "replace").strip() if title else
            raw[:80].decode("utf-8", "replace")))
    return json.loads(raw)


def cache_path(name):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)


def fresh(path, refresh):
    return not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL


def cached(name, refresh, fetch):
    path = cache_path(name)
    if fresh(path, refresh):
        with open(path) as fh:
            return json.load(fh)
    d = fetch()
    with open(path, "w") as fh:
        json.dump(d, fh)
    return d


# ---------------------------------------------------------------- vocabulary and query building

def class_types(refresh=False):
    rows = cached("classtypes.json", refresh, lambda: _json(API + "Search/GetClassTypes"))
    return sorted({(r["Class"], r["Type"]) for r in rows if r.get("Class") and r.get("Type")})


def resolve_classes(cls, typ, refresh=False):
    """eLibrary returns success with zero hits for a Class/Type pair it does not know, so every pair is
    checked against the published vocabulary before it is sent."""
    if not cls and not typ:
        return []
    vocab = class_types(refresh)
    pairs = [(c, t) for c, t in vocab if (not cls or c.casefold() == cls.casefold())
             and (not typ or t.casefold() == typ.casefold())]
    if pairs:
        return pairs
    words = [w for w in re.findall(r"[a-z]{3,}", ("%s %s" % (cls or "", typ or "")).casefold())]
    score = lambda c, t: ((cls or "").casefold() == c.casefold(),
                          sum(w in ("%s %s" % (c, t)).casefold() for w in words))
    near = sorted((p for p in vocab if score(*p)[0] or score(*p)[1]), key=lambda p: score(*p), reverse=True)[:15]
    raise NotFound("unknown Class/Type %r / %r. eLibrary would silently return 0 hits for it.\nNear matches:\n%s"
                   % (cls, typ, "\n".join("  --class %r --type %r" % p for p in near) or "  (none; run: classes)"))


def parse_docket(s):
    m = re.match(r"^\s*([A-Z]{1,4}\d{2}-\d+|P-\d+)(?:-(\d{3}))?\s*$", (s or "").upper())
    if not m:
        raise ValueError("docket %r is not in the form CP22-21, CP22-21-001 or P-1494" % s)
    return m.group(1), [m.group(2)] if m.group(2) else []


def body(text="*", docket=None, pairs=(), since=None, until=None, date_type="filed", fulltext=True,
         description=True, accession=None):
    b = {"searchText": text or "*", "searchFullText": fulltext, "searchDescription": description,
         "dateSearches": [], "allDates": True, "availability": None, "affiliations": [], "categories": [],
         "libraries": [], "accessionNumber": accession, "eFiling": False, "docketSearches": [],
         "resultsPerPage": PER_PAGE, "curPage": 1,
         "classTypes": [{"documentClass": c, "documentType": t} for c, t in pairs],
         "sortBy": "", "groupBy": "NONE", "idolResultID": ""}
    if docket:
        base, sub = parse_docket(docket)
        b["docketSearches"] = [{"docketNumber": base, "subDocketNumbers": sub}]
    if since or until:
        # An unrecognized dateType also returns success with zero hits, so only the three verified ones go out.
        b["allDates"] = False
        b["dateSearches"] = [{"dateType": DATE_TYPES[date_type], "startDate": since or "1900-01-01",
                              "endDate": until or datetime.date.today().isoformat()}]
    return b


def search(b, limit=None, refresh=False):
    """Page through AdvancedSearch. curPage is 1-based; page 0 silently repeats page 1, so starting there
    double-counts the first page."""
    key = hashlib.sha1(json.dumps([b, limit], sort_keys=True).encode()).hexdigest()[:20]

    def fetch():
        hits, seen, total, page = [], set(), None, 1
        per = min(PER_PAGE, limit) if limit else PER_PAGE
        while True:
            q = dict(b, curPage=page, resultsPerPage=per)
            d = _json(API + "Search/AdvancedSearch", q)
            if d.get("success") is False:
                raise SourceDown("AdvancedSearch error: %s" % d.get("errorMessage"))
            total = d.get("totalHits") or 0
            batch = d.get("searchHits") or []
            for h in batch:
                acc = h.get("acesssionNumber") or h.get("documentId")
                if acc not in seen:
                    seen.add(acc)
                    hits.append(h)
            if not batch or len(hits) >= total or (limit and len(hits) >= limit):
                break
            page += 1
            time.sleep(PAUSE)
        return {"total": total, "hits": hits[:limit] if limit else hits}

    return cached("search_%s.json" % key, refresh, fetch)


def docket_total(docket, refresh=False):
    return search(body(docket=docket), limit=1, refresh=refresh)["total"]


def row(h):
    ct = h.get("classTypes") or [{}]
    tr = h.get("transmittals") or []
    return {"accession": h.get("acesssionNumber"), "document_id": h.get("documentId"),
            "filed": iso(h.get("filedDate")), "issued": iso(h.get("issuedDate")),
            "class": ct[0].get("documentClass"), "type": ct[0].get("documentType"),
            "classes": ["%s / %s" % (c.get("documentClass"), c.get("documentType")) for c in ct],
            "availability": h.get("availCode"), "description": re.sub(r"\s+", " ", h.get("description") or "").strip(),
            "dockets": h.get("docketNumbers") or [],
            "authors": sorted({filer(a) for a in h.get("affiliations") or [] if a.get("afType") == "AUTHOR"} - {""}),
            "files": len(tr), "bytes": sum(t.get("fileSize") or 0 for t in tr),
            "transmittals": [{"file_id": t.get("fileId"), "name": t.get("fileName"), "desc": t.get("fileDesc"),
                              "bytes": t.get("fileSize")} for t in tr],
            "link": DOC_LINK % h.get("acesssionNumber")}


def filer(a):
    org = (a.get("affiliation") or "").strip()
    if org:
        return org
    # Individuals filing on their own have no affiliation, only a name.
    return ("%s, %s" % (a.get("lastName") or "", a.get("firstInitial") or "")).strip(" ,")


def by_date(rows):
    return sorted(rows, key=lambda r: (r["filed"], r["accession"] or ""), reverse=True)


def empty_or_rows(docket, rows, what, refresh):
    """Tell an empty filter apart from an empty (or mistyped) docket."""
    if rows:
        return None
    total = docket_total(docket, refresh)
    if not total:
        raise NotFound("no filings on docket %s in eLibrary (check the number; sub-dockets look like CP22-21-001)"
                       % docket)
    return "0 %s on %s, which has %d filings in all." % (what, docket, total)


# ---------------------------------------------------------------- commands

def cmd_health(a):
    checks = []
    cfg = _json(CONFIG)
    api = json.dumps(cfg)
    checks.append(("config loads and names eLibraryWebAPI", "eLibraryWebAPI" in api, CONFIG))
    vocab = class_types(True)
    checks.append(("GetClassTypes >= 200 Class/Type pairs", len(vocab) >= 200, "%d pairs" % len(vocab)))
    res = search(body(docket=HEALTH_DOCKET), refresh=True)
    uniq = len({h.get("acesssionNumber") for h in res["hits"]})
    checks.append(("%s totalHits == unique accessions paged from page 1" % HEALTH_DOCKET,
                   res["total"] > 0 and uniq == res["total"], "totalHits %d, unique %d" % (res["total"], uniq)))
    for name, ok, note in checks:
        if not ok:
            raise SourceDown("health check failed: %s (%s)" % (name, note))
    return {"checks": [{"check": n, "ok": o, "detail": d} for n, o, d in checks]}


def cmd_docket(a):
    pairs = resolve_classes(a.cls, a.type, a.refresh)
    limit = None if a.all else a.limit
    res = search(body(a.text, a.docket, pairs, a.since, a.until, a.date_type),
                 limit=limit, refresh=a.refresh)
    rows = [row(h) for h in res["hits"]]
    note = empty_or_rows(a.docket, rows, "matching filings", a.refresh)
    base = parse_docket(a.docket)[0]
    related = collections.Counter(b for r in rows for b in {d.rsplit("-", 1)[0] for d in r["dockets"]})
    related.pop(base, None)
    return {"docket": a.docket, "total": res["total"], "shown": len(rows), "note": note,
            "filters": {"class_types": pairs, "since": a.since, "until": a.until, "date_type": a.date_type,
                        "text": a.text},
            "availability": dict(collections.Counter(r["availability"] for r in rows)),
            "co_listed_dockets": related.most_common(12), "rows": by_date(rows)}


def typed(a, pairs, what):
    res = search(body(docket=a.docket, pairs=pairs), refresh=a.refresh)
    rows = by_date([row(h) for h in res["hits"]])
    return res, rows, empty_or_rows(a.docket, rows, what, a.refresh)


def cmd_eis(a):
    res, rows, note = typed(a, resolve_pairs(EIS_TYPES, a.refresh), "environmental documents")
    for r in rows:
        r["kind"] = next((k for p, k in EIS_KIND if re.search(p, r["description"], re.I)), r["type"])
    return {"docket": a.docket, "total": res["total"], "note": note, "rows": rows}


def cmd_orders(a):
    res, rows, note = typed(a, resolve_pairs(ORDER_TYPES, a.refresh), "orders")
    for r in rows:
        r["flags"] = [k for p, k in ORDER_FLAG if re.search(p, r["description"], re.I)]
    # Staff construction clearances (delegated letters) can outnumber Commission orders 10 to 1 on a project
    # under construction, so the Commission's own orders are listed first.
    rows.sort(key=lambda r: r["type"] != "Commission Order/Opinion")
    return {"docket": a.docket, "total": res["total"], "note": note, "rows": rows}


def cmd_notices(a):
    res, rows, note = typed(a, resolve_classes("Notice", None, a.refresh), "notices")
    for r in rows:
        r["kind"] = next((k for p, k in NOTICE_KIND if re.search(p, r["description"], re.I)), "")
        r["deadlines"] = [m.group(1).strip() for m in DEADLINE_RE.finditer(r["description"])]
    return {"docket": a.docket, "total": res["total"], "note": note, "rows": rows,
            "caveat": "The kind label and any deadline come from eLibrary's one-line description. The comment, "
                      "intervention or protest date is printed in the notice itself: get <accession>, then "
                      "pdftotext and look for 'Comment Date' or 'on or before'."}


def resolve_pairs(pairs, refresh):
    out = []
    for c, t in pairs:
        out += resolve_classes(c, t, refresh)
    return out


def fold(name):
    """Fold filer-name variants ("Fisherman" / "Fishermen", "Inc." / "Inc", "The ...") into one key."""
    s = re.sub(r"&", " and ", name.casefold())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    drop = {"the", "inc", "llc", "lp", "llp", "co", "corp", "corporation", "company", "et", "al", "of", "and", "for"}
    out = []
    for w in s.split():
        if w in drop:
            continue
        w = re.sub(r"men$", "man", w)
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def cmd_movants(a):
    vocab_pairs = resolve_classes(INTERVENTION_CLASS, None, a.refresh)
    classed = search(body(docket=a.docket, pairs=vocab_pairs), refresh=a.refresh)["hits"]
    # Joint motions to intervene are often filed as answers, protests or comments and classed that way;
    # a description search catches them where the class filter cannot.
    texted = []
    for word in ("intervene", "intervention"):
        texted += search(body(word, a.docket, fulltext=False, description=True), refresh=a.refresh)["hits"]
    seen, rows, grants, opposed = set(), [], [], []
    for h in classed + texted:
        r = row(h)
        if r["accession"] in seen:
            continue
        seen.add(r["accession"])
        if r["class"] == INTERVENTION_CLASS:
            rows.append(r)
        elif re.match(r"\s*(motion for leave to answer and )?answer", r["description"], re.I) and \
                re.search(r"interven", r["description"], re.I) or \
                re.search(r"oppos\w* (to )?the .{0,80}motions? to intervene", r["description"], re.I):
            # An answer filed within 15 days of a timely motion withholds party status until the motion
            # is granted (385.214(c)(2)), so these are kept next to the movants rather than dropped.
            # "Motion to Intervene and Comments in Response to ..." is a motion, hence the anchoring.
            opposed.append(r)
        elif issued_by_ferc(r):
            # Notices and orders granting or denying late interventions decide party status for out-of-time
            # movants, so they are kept as evidence rather than listed as movants.
            if re.search(r"interven", r["description"], re.I):
                grants.append(r)
        elif (re.search(r"motions? to intervene|notice of intervention|intervene out of time|"
                        r"late intervention|withdraw\w* (of )?(its |their )?intervention", r["description"], re.I)
              ):
            rows.append(r)
    note = empty_or_rows(a.docket, rows, "intervention filings", a.refresh)
    groups = {}
    for r in sorted(rows, key=lambda r: (r["filed"], r["accession"])):
        d, t = r["description"], r["type"] or ""
        kind = ("withdrawal" if re.search(r"withdraw", t + " " + d, re.I) else
                "late motion" if re.search(r"out of time|late interven|untimely", t + " " + d, re.I) else
                "motion" if r["class"] == INTERVENTION_CLASS else "motion (other class)")
        for who in r["authors"] or ["(no AUTHOR affiliation)"]:
            g = groups.setdefault(fold(who) or who, {"names": collections.Counter(), "filings": []})
            g["names"][who] += 1
            g["filings"].append({"accession": r["accession"], "filed": r["filed"], "kind": kind,
                                 "classed_as": None if r["class"] == INTERVENTION_CLASS else
                                 "%s / %s" % (r["class"], r["type"]),
                                 "availability": r["availability"], "description": r["description"]})
    movants = []
    for g in groups.values():
        f = g["filings"]
        kinds = {x["kind"] for x in f}
        movants.append({"filer": g["names"].most_common(1)[0][0], "variants": sorted(g["names"]),
                        "first": f[0]["filed"], "last": f[-1]["filed"],
                        "status": ("withdrew" if "withdrawal" in kinds else
                                   "motion" if kinds & {"motion", "motion (other class)"} else "late motion"),
                        "filings": f})
    movants.sort(key=lambda m: (m["first"], m["filer"].casefold()))
    return {"docket": a.docket, "filings": len(rows), "movants": movants, "note": note,
            "oppositions": [{k: g[k] for k in ("accession", "filed", "authors", "description")}
                            for g in by_date(opposed)],
            "ferc_issuances": [{k: g[k] for k in ("accession", "filed", "class", "type", "description")}
                               for g in by_date(grants)],
            "caveats": [
                "These are movants, not confirmed parties. Under 18 CFR 385.214(c) a timely motion with no "
                "answer in opposition within 15 days confers party status at day 15; an opposed or late motion "
                "does so only when expressly granted, so check the orders (orders <docket>) for late grants.",
                "'motion' versus 'late motion' follows eLibrary's document type and the filer's own wording. "
                "Timeliness turns on the intervention deadline in the notice of application (notices <docket>), "
                "and under 18 CFR 380.10(a)(1)(i) a motion filed within the draft EIS comment period is deemed "
                "timely.",
                "State agencies and others listed in 385.214(a)(2) become parties by a timely notice of "
                "intervention, without a motion.",
                "Grouping folds case, punctuation and plurals in the AUTHOR affiliation; joint filings are listed "
                "under every author. Read the variants column before merging further.",
                "The official service list (%s) is behind an F5 firewall that rejects scripted requests; "
                "open it in a browser." % SERVICE_LIST]}


def issued_by_ferc(r):
    # Observed, not documented: Commission issuances carry accession serials in the 3000s, e-filings 5000s,
    # paper filings 0000s.
    return r["class"] in ("Notice", "Order/Opinion") or bool(re.match(r"^\d{8}-3\d{3}$", r["accession"] or ""))


def lookup(acc, refresh=False):
    if re.match(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$", acc.upper()):
        return None, acc.upper()
    if not re.match(r"^\d{8}-\d{4}$", acc):
        raise ValueError("%r is neither an accession number (20230728-3008) nor a documentId GUID" % acc)
    res = search(body(accession=acc), limit=5, refresh=refresh)
    for h in res["hits"]:
        if h.get("acesssionNumber") == acc:
            return h, h["documentId"]
    raise NotFound("accession %s not found in eLibrary" % acc)


def file_list(doc_id, refresh=False):
    d = cached("files_%s.json" % doc_id, refresh, lambda: _json(API + "File/GetFileListFromP8/" + doc_id))
    out = []
    for f in d.get("DataList") or []:
        out.append({"n": f.get("File_List_Order"), "file_id": f.get("ID"), "name": f.get("Orig_File_Name"),
                    "desc": f.get("FileDescription"), "bytes": f.get("File_Size_Num") or 0,
                    "pages": f.get("Page_Count"), "type": f.get("File_Type_Code"),
                    "availability": f.get("Availability_Mode"), "accession": f.get("Accession_Number")})
    if not out:
        raise NotFound("no files listed for document %s" % doc_id)
    return sorted(out, key=lambda f: f["n"] or 0)


def cmd_files(a):
    h, doc_id = lookup(a.id, a.refresh)
    files = file_list(doc_id, a.refresh)
    return {"accession": files[0]["accession"], "document_id": doc_id,
            "availability": h.get("availCode") if h else None,
            "description": row(h)["description"] if h else None,
            "files": files, "bytes": sum(f["bytes"] for f in files)}


def cmd_get(a):
    if not re.match(r"^\d{8}-\d{4}$", a.accession):
        raise ValueError("get takes an accession number such as 20230728-3008")
    h, doc_id = lookup(a.accession, a.refresh)
    files = file_list(doc_id, a.refresh)
    if a.file:
        want = {str(x) for x in a.file}
        files = [f for f in files if str(f["n"]) in want or (f["file_id"] or "").upper() in {w.upper() for w in want}]
        if not files:
            raise NotFound("none of --file %s matches a file of %s (run: files %s)" % (
                " ".join(a.file), a.accession, a.accession))
    public = [f for f in files if f["availability"] == "P"]
    withheld = [f for f in files if f["availability"] != "P"]
    total = sum(f["bytes"] for f in public)
    plan = {"accession": a.accession, "files": len(public), "bytes": total, "size": human(total),
            "withheld": [dict(f, route=RESTRICTED_ROUTE.get(f["availability"], "")) for f in withheld]}
    if not public:
        plan["saved"] = []
        plan["note"] = "No public files on this accession; nothing downloaded."
        return plan
    if (total > BIG_BYTES or len(public) > BIG_FILES) and not a.yes:
        lines = ["  %3s  %10s  %s" % (f["n"], human(f["bytes"]), f["name"]) for f in public]
        die("%s: %d public files, %s in total. Re-run with --yes to download, or pick files with --file N.\n%s"
            % (a.accession, len(public), human(total), "\n".join(lines)), 2)
    out = os.path.join(os.path.abspath(a.out), a.accession)
    os.makedirs(out, exist_ok=True)
    saved = []
    for f in public:
        req = {"FileType": "", "accession": "", "fileid": 0, "FileIDAll": "", "fileidLst": [f["file_id"]],
               "Islegacy": False}
        with _open(API + "File/DownloadP8File", json.dumps(req).encode(),
                   {"Content-Type": "application/json", "Accept": "*/*"}, timeout=900) as r:
            ctype = r.headers.get("Content-Type", "")
            m = re.search(r'filename="?([^";]+)"?', r.headers.get("Content-Disposition", ""))
            name = os.path.basename(m.group(1) if m else "%s_%s" % (a.accession, f["name"] or f["n"]))
            name = re.sub(r"[\x00-\x1f/\\:]+", "_", name).lstrip(".") or "file_%s" % f["n"]
            path = os.path.join(out, name)
            if os.path.exists(path):
                path = os.path.join(out, "%s_%s" % (f["n"], name))
            first = r.read(512)
            # A WAF page arrives as HTML; .txt/.xml/.htm transmittals legitimately start with "<", so the
            # body sniff applies only where eLibrary lists the file as a PDF.
            if "text/html" in ctype or (f["type"] == "PDF" and not first.startswith(b"%PDF")
                                        and first.lstrip()[:1] == b"<"):
                raise SourceDown("download of %s returned %s instead of the file" % (f["name"], ctype))
            n = len(first)
            with open(path, "wb") as fh:
                fh.write(first)
                for chunk in iter(lambda: r.read(1 << 16), b""):
                    fh.write(chunk)
                    n += len(chunk)
        saved.append({"path": path, "bytes": n, "expected": f["bytes"]})
        time.sleep(PAUSE)
    plan["saved"] = saved
    return plan


def cmd_search(a):
    pairs = resolve_classes(a.cls, a.type, a.refresh)
    res = search(body(a.text, a.docket, pairs, a.since, a.until, a.date_type, fulltext=a.fulltext,
                      description=True), limit=a.limit, refresh=a.refresh)
    rows = [row(h) for h in res["hits"]]
    dockets = collections.Counter(b for r in rows for b in {d.rsplit("-", 1)[0] for d in r["dockets"]})
    return {"text": a.text, "fulltext": a.fulltext, "total": res["total"], "rows": rows,
            "dockets": dockets.most_common(15)}


def cmd_classes(a):
    t = (a.text or "").casefold()
    return {"pairs": [{"class": c, "type": ty} for c, ty in class_types(a.refresh)
                      if not t or t in c.casefold() or t in ty.casefold()]}


# ---------------------------------------------------------------- output

def line(r, extra=""):
    return "%s  %s  %-1s  %-48.48s  %s%s" % (r["filed"], r["accession"], r["availability"] or "?",
                                            "%s / %s" % (r["class"], r["type"]), r["description"][:150], extra)


def show(cmd, r):
    p = print
    if cmd == "health":
        for c in r["checks"]:
            p("ok   %s: %s" % (c["check"], c["detail"]))
        return
    if cmd in ("docket", "eis", "orders", "notices"):
        if r.get("note"):
            p(r["note"])
            return
        if cmd == "docket":
            p("%s: %d filings match; %d shown (newest first). Availability: %s." % (
                r["docket"], r["total"], r["shown"],
                ", ".join("%s %d" % (AVAIL.get(k, k), v) for k, v in sorted(r["availability"].items(), key=str))))
            if r["co_listed_dockets"]:
                p("Co-listed dockets: %s" % ", ".join("%s (%d)" % kv for kv in r["co_listed_dockets"]))
            p("")
        group = None
        for x in r["rows"]:
            if cmd == "orders" and x["type"] != group:
                group = x["type"]
                p("\n== %s (%d)" % (group, sum(y["type"] == group for y in r["rows"])))
            extra = ""
            if cmd == "eis":
                extra = "\n      [%s] %s" % (x["kind"], "; ".join("%s (%s)" % (t["name"], human(t["bytes"]))
                                                          for t in x["transmittals"]))
            elif cmd == "orders" and x["flags"]:
                extra = "\n      [%s]" % ", ".join(x["flags"])
            elif cmd == "notices" and (x["kind"] or x["deadlines"]):
                extra = "\n      [%s]%s" % (x["kind"] or "notice", "  deadline in description: " +
                                            " | ".join(x["deadlines"]) if x["deadlines"] else "")
            elif cmd == "docket":
                extra = "  [%d files, %s]" % (x["files"], human(x["bytes"]))
            p(line(x, extra))
        if cmd == "docket" and r["shown"] < r["total"]:
            p("\n%d more; use --all or --limit N." % (r["total"] - r["shown"]))
        if cmd == "notices":
            p("\n" + r["caveat"])
        p("\nAvailability: P public, C CEII, N non-public. Open: %s" % (DOC_LINK % "<accession>"))
        return
    if cmd == "movants":
        if r.get("note"):
            p(r["note"])
            return
        p("%s: %d intervention filings from %d filer groups (movants, not confirmed parties).\n" % (
            r["docket"], r["filings"], len(r["movants"])))
        for m in r["movants"]:
            p("%-60.60s  %-11s  %s .. %s" % (m["filer"], m["status"], m["first"], m["last"]))
            if len(m["variants"]) > 1:
                p("    also filed as: %s" % "; ".join(v for v in m["variants"] if v != m["filer"]))
            for f in m["filings"]:
                p("    %s  %s  %-11s%s" % (f["filed"], f["accession"], f["kind"],
                                          "  classed as %s" % f["classed_as"] if f["classed_as"] else ""))
        if r["oppositions"]:
            p("\nAnswers to interventions. Under 385.214(c)(2) an answer in opposition filed within 15 days of a "
              "timely motion means party status only on express grant; a later answer does not undo party status "
              "already gained at day 15:")
            for g in r["oppositions"]:
                p("    %s  %s  %s" % (g["filed"], g["accession"], g["description"][:140]))
        if r["ferc_issuances"]:
            p("\nCommission issuances on intervention (late grants/denials decide party status for late movants):")
            for g in r["ferc_issuances"]:
                p("    %s  %s  %s" % (g["filed"], g["accession"], g["description"][:140]))
        p("")
        for c in r["caveats"]:
            p("- " + c)
        return
    if cmd == "files":
        p("%s (%s)%s" % (r["accession"], r["document_id"],
                         "  availability %s" % AVAIL.get(r["availability"], r["availability"])
                         if r["availability"] else ""))
        if r["description"]:
            p(r["description"])
        for f in r["files"]:
            p("  %3s  %-1s  %10s  %5s pp  %s  [%s]" % (f["n"], f["availability"] or "?", human(f["bytes"]),
                                                    f["pages"] or "?", f["name"], f["file_id"]))
        p("Total %s." % human(r["bytes"]))
        return
    if cmd == "get":
        for s in r.get("saved", []):
            p("saved %s (%s%s)" % (s["path"], human(s["bytes"]),
                                  "" if not s["expected"] or s["expected"] == s["bytes"]
                                  else "; eLibrary listed %s" % human(s["expected"])))
        if r.get("note"):
            p(r["note"])
        for f in r["withheld"]:
            p("withheld %s (%s): %s\n    %s" % (f["name"], AVAIL.get(f["availability"], f["availability"]),
                                               human(f["bytes"]), f["route"]))
        return
    if cmd == "search":
        p("%d hits for %r (%s); %d shown." % (r["total"], r["text"],
                                             "full text + description" if r["fulltext"] else "description",
                                             len(r["rows"])))
        if r["dockets"]:
            p("Dockets among shown hits: %s\n" % ", ".join("%s (%d)" % kv for kv in r["dockets"]))
        for x in r["rows"]:
            p(line(x, "  {%s}" % ", ".join(x["dockets"][:4])))
        return
    if cmd == "classes":
        for x in r["pairs"]:
            p("--class %r --type %r" % (x["class"], x["type"]))
        p("\n%d pairs." % len(r["pairs"]))
        return
    p(json.dumps(r, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--refresh", action="store_true", help="bypass the one-day cache")
    # Repeat the globals on each subcommand so they work on either side of it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def dates(s):
        s.add_argument("--since", help="YYYY-MM-DD")
        s.add_argument("--until", help="YYYY-MM-DD")
        s.add_argument("--date-type", choices=sorted(DATE_TYPES), default="filed")

    def classes(s):
        s.add_argument("--class", dest="cls", help="document Class (see: classes)")
        s.add_argument("--type", help="document Type within the class (see: classes)")

    sub.add_parser("health", help="API up, vocabulary loads, totalHits == unique rows paged")

    s = sub.add_parser("docket", help="filings on a docket")
    s.add_argument("docket")
    classes(s)
    dates(s)
    s.add_argument("--text", help="restrict to filings whose text or description matches")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--all", action="store_true", help="every filing on the docket")

    for name, hlp in (("eis", "EA/EIS, scoping and environmental-report documents"),
                      ("orders", "Commission and delegated orders"),
                      ("notices", "notices, with deadlines parsed from descriptions"),
                      ("movants", "intervention movants grouped by filer")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("docket")

    s = sub.add_parser("files", help="transmittal files of an accession or documentId")
    s.add_argument("id")

    s = sub.add_parser("get", help="download the public files of an accession")
    s.add_argument("accession")
    s.add_argument("--file", action="append", help="file number (from: files) or file ID; repeatable")
    s.add_argument("--out", default=".", help="parent directory; files go in <out>/<accession>/")
    s.add_argument("--yes", action="store_true", help="confirm a download over 25 MB or 10 files")

    s = sub.add_parser("search", help="eLibrary-wide search, to find a docket from a project or company")
    s.add_argument("text")
    s.add_argument("--fulltext", action="store_true", help="search document text too, not just descriptions")
    s.add_argument("--docket")
    classes(s)
    dates(s)
    s.add_argument("--limit", type=int, default=25)

    s = sub.add_parser("classes", help="valid Class / Type pairs")
    s.add_argument("text", nargs="?", default="")

    args = ap.parse_args()
    if getattr(args, "limit", 1) is not None and getattr(args, "limit", 1) < 1:
        die("--limit must be at least 1")
    for d in ("since", "until"):
        v = getattr(args, d, None)
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            die("--%s must be YYYY-MM-DD" % d)
    fn = {"health": cmd_health, "docket": cmd_docket, "eis": cmd_eis, "orders": cmd_orders,
          "notices": cmd_notices, "movants": cmd_movants, "files": cmd_files, "get": cmd_get,
          "search": cmd_search, "classes": cmd_classes}[args.cmd]
    try:
        res = fn(args)
    except ValueError as e:
        die(str(e), 2)
    except NotFound as e:
        die(str(e), 3)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
