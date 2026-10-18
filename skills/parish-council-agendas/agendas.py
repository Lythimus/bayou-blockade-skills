#!/usr/bin/env python3
"""Parish council and planning/zoning agendas, minutes and keyword alerts, one adapter per platform:
Legistar (St. Charles), CivicClerk (Ascension), CivicPlus AgendaCenter with OCR (St. James).

Run with: uv run -q --no-project python -I agendas.py <command> ...
Listings are cached for 6 hours (--refresh forces a re-fetch); OCR text is cached by file id and PDF hash.
Cache: ~/.cache/bayou/parish-council-agendas/.

  agendas.py parishes                              registry: platform and status per parish
  agendas.py health [parish ...]                   each verified adapter answers; CivicClerk paging has no gaps
  agendas.py bodies <parish>                       councils, commissions and boards on the platform
  agendas.py meetings <parish> [--body B] [--since D] [--until D] [--all-bodies]
  agendas.py items <parish> <meeting-id> [--minutes]   agenda lines (or minutes, scanned parishes)
  agendas.py alerts [parish ...] [--since D] [--until D] [--category C ...] [--term REGEX ...] [--all-bodies] [--yes]
  agendas.py track <parish> <text> [--since D] [--yes]     follow a case, applicant, place or matter file across meetings
  agendas.py get <parish> <meeting-id> [--what agenda|packet|minutes] [--out DIR] [--yes]

A keyword hit is a lead to read, not a finding: titles name streets and lots, and many matches are routine.
Exit codes: 2 bad arguments or a download over the size limit without --yes; 3 parish unprobed, meeting or
text not found; 5 the platform is unavailable or returned something other than the expected format.
"""
import argparse
import concurrent.futures
import datetime
import glob
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/bayou/parish-council-agendas")
TTL = 6 * 3600
UA = "Mozilla/5.0 (bayou-parish-council-agendas)"
BIG_BYTES = 25 * 1024 * 1024
# A meeting this many days past no longer gets its agenda replaced, so its extracted text is reused as is.
SETTLED_DAYS = 14
REFRESH = False
JSON_OUT = False


class Upstream(Exception):
    pass


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- plumbing

def load(name):
    with open(os.path.join(HERE, name)) as f:
        return json.load(f)


def parish_cfg(key):
    reg = load("parishes.json")["parishes"]
    if key not in reg:
        raise SystemExit(f"unknown parish '{key}'. Known: {', '.join(reg)}")
    cfg = dict(reg[key], key=key)
    if cfg.get("status") != "verified":
        raise NotFound(f"{cfg['name']} is {cfg.get('status')}: no adapter yet. " + " ".join(cfg.get("notes", []))
                       + " See 'Adding a parish' in SKILL.md.")
    return cfg


def cache_path(url, data=None):
    key = hashlib.sha256((url + "|" + (urllib.parse.urlencode(data) if data else "")).encode()).hexdigest()
    return os.path.join(CACHE, "http", key[:2], key)


def is_cached(url, data=None, ttl=TTL):
    path = cache_path(url, data)
    return bool(ttl) and not REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl


def fetch(url, data=None, ttl=TTL, binary=False, timeout=90):
    """GET (or POST form data) with a disk cache. Returns bytes if binary else str."""
    path = cache_path(url, data)
    if is_cached(url, data, ttl):
        with open(path, "rb") as f:
            body = f.read()
        return body if binary else body.decode("utf-8", "replace")
    body = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers={"User-Agent": UA, "Accept": "*/*",
                                                  # brla.gov's AgendaCenter answers its year listing with 400 without it
                                                  "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(f"404 {url}")
            if attempt == 3:
                raise Upstream(f"HTTP {e.code} {url}")
        except Exception as e:  # gateway resets are routine on Legistar's API
            if attempt == 3:
                raise Upstream(f"{e} {url}")
        time.sleep(2 * (attempt + 1))
    if ttl:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
    return body if binary else body.decode("utf-8", "replace")


def fetch_json(url, params=None, ttl=TTL):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    text = fetch(url, ttl=ttl)
    try:
        return json.loads(text)
    except ValueError:
        raise Upstream(f"not JSON from {url}: {text[:120]!r}")


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return " ".join(s.replace("​", "").split())


def day(s):
    return datetime.date.fromisoformat(s)


def emit(rows, render):
    if JSON_OUT:
        print(json.dumps(rows, indent=1, default=str))
    else:
        render(rows)


# ---------------------------------------------------------------- Legistar (St. Charles)

CEREMONY = re.compile(r"^(CALL TO ORDER|PLEDGE|PRAYER|ROLL CALL|ATTENDANCE|INVOCATION|ADJOURN)", re.I)
HEARING_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\w+ \d{1,2}, \d{4}")


class Legistar:
    def __init__(self, cfg):
        self.cfg, self.api = cfg, cfg["api"]

    def get(self, path, params=None, ttl=TTL):
        return fetch_json(f"{self.api}/{path}", params, ttl)

    def bodies(self):
        return [{"id": b["BodyId"], "name": b["BodyName"].strip(), "type": b["BodyTypeName"],
                 "active": bool(b["BodyActiveFlag"])} for b in self.get("bodies")]

    def meetings(self, since, until):
        flt = f"EventDate ge datetime'{since}' and EventDate le datetime'{until}'"
        out, skip = [], 0
        while True:
            page = self.get("events", {"$filter": flt, "$orderby": "EventDate", "$top": 1000, "$skip": skip})
            out += page
            if len(page) < 1000:
                break
            skip += 1000
        return [{
            "id": str(e["EventId"]), "date": e["EventDate"][:10], "time": e["EventTime"] or "",
            "body": (e["EventBodyName"] or "").strip(), "location": e["EventLocation"] or "",
            "agenda": e["EventAgendaFile"] or "", "agenda_status": e["EventAgendaStatusName"] or "",
            "minutes": e["EventMinutesFile"] or "", "minutes_status": e["EventMinutesStatusName"] or "",
            "packet": "", "url": e["EventInSiteURL"] or "",
        } for e in out]

    def meeting(self, mid):
        try:
            e = self.get(f"events/{mid}")
        except NotFound:
            raise NotFound(f"St. Charles Legistar has no event {mid}")
        return {"id": str(e["EventId"]), "date": e["EventDate"][:10], "time": e["EventTime"] or "",
                "body": (e["EventBodyName"] or "").strip(), "agenda": e["EventAgendaFile"] or "",
                "minutes": e["EventMinutesFile"] or "", "packet": "", "url": e["EventInSiteURL"] or "",
                "minutes_status": e["EventMinutesStatusName"] or ""}

    def attachment_url(self, a):
        # The API's hyperlink carries another client's path and returns 404; the stored file name is right.
        fn = a.get("MatterAttachmentFileName")
        return self.cfg["attachments"] + fn if fn else a.get("MatterAttachmentHyperlink") or ""

    def items(self, mid, minutes=False):
        m = self.meeting(mid)
        raw = self.get(f"events/{mid}/eventitems", {"AgendaNote": 1, "MinutesNote": 1, "Attachments": 1})
        agenda = sorted((i for i in raw if i["EventItemAgendaSequence"] is not None),
                        key=lambda i: i["EventItemAgendaSequence"])
        # Rows with no agenda sequence are the minutes side: the action actually taken on a matter.
        outcomes = {}
        for i in raw:
            if i["EventItemAgendaSequence"] is None and i["EventItemMatterFile"] and i["EventItemActionName"]:
                outcomes.setdefault(i["EventItemMatterFile"], []).append(
                    " ".join(x for x in (i["EventItemActionName"], i["EventItemPassedFlagName"]) if x))
        rows, section, hearing = [], "", ""
        for i in agenda:
            title = clean(i["EventItemTitle"])
            if not title or title.lower() == "page break":
                continue
            if HEARING_RE.match(title):
                hearing = title
                continue
            if not i["EventItemMatterFile"] and title.startswith("IN ACCORDANCE"):
                # The charter notice that heads the ordinances introduced tonight for a later hearing.
                section, hearing = "ORDINANCES INTRODUCED (PUBLIC HEARING AT A LATER MEETING)", ""
                continue
            if not i["EventItemMatterFile"] and title.isupper():
                section, hearing = ("" if CEREMONY.match(title) else title), ""
                continue
            action = i["EventItemActionName"] or ""
            rows.append({
                "parish": self.cfg["key"], "meeting_id": m["id"], "date": m["date"], "body": m["body"],
                "section": section, "item_no": i["EventItemAgendaNumber"] or "", "title": title,
                "matter_file": i["EventItemMatterFile"] or "", "matter_type": i["EventItemMatterType"] or "",
                "action": action, "outcome": "; ".join(outcomes.get(i["EventItemMatterFile"], [])),
                "hearing_date": hearing if "public hearing" in action.lower() else "",
                "attachments": [{"name": a["MatterAttachmentName"], "url": self.attachment_url(a)}
                                for a in i.get("EventItemMatterAttachments") or []],
                "url": (self.cfg["matter_link"] + str(i["EventItemMatterId"])) if i["EventItemMatterId"] else m["url"],
            })
        return m, rows

    def matter(self, mf):
        ms = self.get("matters", {"$filter": f"MatterFile eq '{mf}'"})
        if not ms:
            raise NotFound(f"no matter {mf}")
        m = ms[0]
        hist = self.get(f"matters/{m['MatterId']}/histories")
        att = self.get(f"matters/{m['MatterId']}/attachments")
        return {
            "matter_file": m["MatterFile"], "type": m["MatterTypeName"], "status": m["MatterStatusName"],
            "intro_date": (m["MatterIntroDate"] or "")[:10], "passed_date": (m["MatterPassedDate"] or "")[:10],
            "enactment_no": m["MatterEnactmentNumber"] or "", "title": clean(m["MatterTitle"]),
            "url": self.cfg["matter_link"] + str(m["MatterId"]),
            "history": [{"date": (h["MatterHistoryActionDate"] or "")[:10], "body": h["MatterHistoryActionBodyName"],
                         "action": h["MatterHistoryActionName"], "passed": h["MatterHistoryPassedFlagName"] or "",
                         "event_id": h["MatterHistoryEventId"]} for h in hist],
            "attachments": [{"name": a["MatterAttachmentName"], "url": self.attachment_url(a)} for a in att],
            "hearing_date": self.hearing_for(m["MatterFile"], hist),
        }

    def hearing_for(self, mf, hist):
        """The hearing date announced when the ordinance was introduced, if it has not been heard yet."""
        if any("hearing requirements satisfied" in (h["MatterHistoryActionName"] or "").lower() for h in hist):
            return ""
        for h in reversed(hist):
            if "public hearing" in (h["MatterHistoryActionName"] or "").lower() and h["MatterHistoryEventId"]:
                _, rows = self.items(h["MatterHistoryEventId"])
                return next((r["hearing_date"] for r in rows if r["matter_file"] == mf and r["hearing_date"]), "")
        return ""

    def search_matters(self, text, since):
        esc = text.replace("'", "''")
        flt = f"MatterIntroDate ge datetime'{since}' and substringof('{esc}',MatterTitle)"
        return self.get("matters", {"$filter": flt, "$orderby": "MatterIntroDate", "$top": 1000})

    def files(self, mid):
        m = self.meeting(mid)
        return {k: m[k] for k in ("agenda", "minutes") if m[k]}


# ---------------------------------------------------------------- CivicClerk (Ascension)

DATE_IN_NAME = re.compile(r"\s*[-–]?\s*(?:\d{1,2}\s?[A-Za-z]{3,9}\s?\d{2,4}|[A-Z][a-z]+ \d{1,2},? \d{4})\s*$")


def cc_body(name):
    """Event names embed the date ('Planning Commission Meeting 12Aug2026'); strip it for grouping."""
    n = re.sub(r"^(?:Cancell?ation(?: Notice)?(?: of)?\s*[-–]?\s*)", "", (name or "").strip(), flags=re.I)
    n = DATE_IN_NAME.sub("", n)
    n = re.sub(r"\s+(Meeting|Mtg)(\s+Agenda)?$", "", n, flags=re.I)
    return n.strip() or (name or "").strip()


class CivicClerk:
    def __init__(self, cfg):
        self.cfg, self.api = cfg, cfg["api"]

    def events(self, since, until):
        # The server returns 15 rows a page whatever $top says, and pages by @odata.nextLink.
        flt = f"startDateTime ge {since}T00:00:00Z and startDateTime le {until}T23:59:59Z"
        url = f"{self.api}/Events?" + urllib.parse.urlencode({"$filter": flt, "$orderby": "startDateTime"},
                                                              quote_via=urllib.parse.quote)
        out, seen = [], set()
        while url:
            d = fetch_json(url)
            if "value" not in d:
                raise Upstream(f"CivicClerk returned no 'value': {str(d)[:120]}")
            for e in d["value"]:
                if e["id"] not in seen:
                    seen.add(e["id"])
                    out.append(e)
            url = d.get("@odata.nextLink")
        return out

    def bodies(self):
        today = datetime.date.today()
        evs = self.events((today - datetime.timedelta(days=400)).isoformat(), (today + datetime.timedelta(days=90)).isoformat())
        names = {}
        for e in evs:
            names.setdefault(cc_body(e["eventName"]), []).append(e["startDateTime"][:10])
        return [{"id": "", "name": n, "type": "", "active": True, "meetings": len(d), "last": max(d)}
                for n, d in sorted(names.items())]

    def _row(self, e):
        files = {}
        for f in e.get("publishedFiles") or []:
            files.setdefault(f["type"], f["fileId"])
        stream = f"{self.api}/Meetings/GetMeetingFileStream(fileId=%s,plainText=false)"
        # CivicClerk stamps local wall-clock time with a Z; 6 pm council meetings read T18:00:00Z.
        t = e["startDateTime"][11:16]
        return {
            "id": str(e.get("agendaId") or ""), "event_id": e["id"], "date": e["startDateTime"][:10],
            "time": datetime.datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0") if t else "",
            "body": cc_body(e["eventName"]), "title": (e["eventName"] or "").strip(),
            "location": (e.get("eventLocation") or {}).get("address1", "") if isinstance(e.get("eventLocation"), dict) else "",
            "agenda": stream % files["Agenda"] if "Agenda" in files else "",
            "packet": stream % files["Agenda Packet"] if "Agenda Packet" in files else "",
            "minutes": stream % files["Minutes"] if "Minutes" in files else "",
            "notice": stream % files["Notice"] if "Notice" in files else "",
            "agenda_status": "Cancelled" if re.match(r"cancel", e["eventName"] or "", re.I) else "", "minutes_status": "",
            "url": f"{self.cfg['web']}event/{e['id']}/overview",
            "file_ids": files,
        }

    def meetings(self, since, until):
        return [self._row(e) for e in self.events(since, until)]

    def items(self, mid, minutes=False):
        try:
            d = fetch_json(f"{self.api}/Meetings/{mid}")
        except NotFound:
            raise NotFound(f"Ascension CivicClerk has no agenda {mid} (use the id column from 'meetings')")
        ev = self.event_for_agenda(mid)
        meta = self._row(ev) if ev else {"id": str(mid), "date": "", "body": "", "url": ""}
        rows = []

        def walk(items, section):
            for it in items:
                name = it.get("agendaObjectItemName") or ""
                title = clean(name)
                kids = it.get("childItems") or []
                pulled = "<s>" in name or "pulled from the agenda" in title.lower()
                if kids and not it.get("attachmentsList"):
                    # A numbered heading ("8 Introduction of Ordinances") whose lettered children are the items.
                    walk(kids, title if title != "Agenda Items" else section)
                    continue
                if title and title != "Agenda Items":
                    rows.append({
                        "parish": self.cfg["key"], "meeting_id": str(mid), "date": meta["date"], "body": meta["body"],
                        "section": section, "item_no": it.get("agendaObjectItemOutlineNumber") or "", "title": title,
                        "matter_file": it.get("ordinanceFormattedNumber") or it.get("resolutionFormattedNumber") or "",
                        "matter_type": "", "action": "pulled" if pulled else "",
                        "outcome": "", "hearing_date": "",
                        "attachments": [{"name": a.get("fileName"), "url": a.get("pdfVersionFullPath") or ""}
                                        for a in it.get("attachmentsList") or []],
                        "url": meta["url"],
                    })
                if kids:
                    walk(kids, title)

        walk(d.get("items") or [], "")
        return meta, rows

    def event_for_agenda(self, mid):
        d = fetch_json(f"{self.api}/Events?" + urllib.parse.urlencode({"$filter": f"agendaId eq {int(mid)}"},
                                                                       quote_via=urllib.parse.quote))
        return (d.get("value") or [None])[0]

    def files(self, mid):
        meta, _ = self.items(mid)
        return {k: meta[k] for k in ("agenda", "packet", "minutes", "notice") if meta.get(k)}

    def text(self, url):
        return fetch(url.replace("plainText=false", "plainText=true"))


# ---------------------------------------------------------------- CivicPlus AgendaCenter (St. James, scanned)

ROW_RE = re.compile(r'<tr[^>]*catAgendaRow.*?</tr>', re.S)


class CivicPlus:
    def __init__(self, cfg):
        self.cfg, self.base = cfg, cfg["base"]

    def bodies(self):
        return [{"id": k, "name": v, "type": "AgendaCenter category", "active": True}
                for k, v in self.cfg["categories"].items()]

    def _rows(self, cat, year):
        page = fetch(f"{self.base}/AgendaCenter/UpdateCategoryList",
                     {"year": year, "catID": cat, "startDate": "", "endDate": "", "term": "", "prevVersionScreen": "false"})
        out = []
        for r in ROW_RE.findall(page):
            a = re.search(r'href="/AgendaCenter/ViewFile/Agenda/(_(\d{2})(\d{2})(\d{4})-(\d+))"[^>]*>\s*(.*?)\s*</a>', r, re.S)
            if not a:
                continue
            fid, mm, dd, yyyy, num, title = a.groups()
            posted = re.search(r"Posted\s*(.*?)\s*</h3>", r, re.S)
            mins = re.search(r'href="(/AgendaCenter/ViewFile/Minutes/_[\d-]+)"', r)
            out.append({
                "id": num, "file_id": fid, "date": f"{yyyy}-{mm}-{dd}", "time": "",
                "body": self.cfg["categories"][str(cat)], "title": clean(title),
                "posted": clean(posted.group(1)) if posted else "",
                "agenda": f"{self.base}/AgendaCenter/ViewFile/Agenda/{fid}",
                "packet": f"{self.base}/AgendaCenter/ViewFile/Agenda/{fid}?packet=true" if "packet=true" in r else "",
                "minutes": self.base + mins.group(1) if mins else "",
                "agenda_status": "", "minutes_status": "", "url": f"{self.cfg['web']}#{fid}",
            })
        return out

    def meetings(self, since, until):
        out = []
        for cat in self.cfg["categories"]:
            for y in range(day(since).year, day(until).year + 1):
                out += [r for r in self._rows(cat, y) if since <= r["date"] <= until]
        return sorted(out, key=lambda r: (r["date"], r["body"]))

    def find(self, mid):
        # File ids are global across categories; the date in the id narrows the year to search.
        for m in self._all_recent():
            if m["id"] == str(mid):
                return m
        raise NotFound(f"St. James AgendaCenter has no meeting {mid} in the last three years")

    def _all_recent(self):
        y = datetime.date.today().year
        return [r for cat in self.cfg["categories"] for yr in (y, y - 1, y - 2) for r in self._rows(cat, yr)]

    def _text_args(self, m, minutes=False):
        settled = m["date"] < (datetime.date.today() - datetime.timedelta(days=SETTLED_DAYS)).isoformat()
        # File ids count per site, so two parishes can both have "_06022026-494".
        return (f"{self.cfg['key']}-{'min' if minutes else 'agd'}-{m['file_id']}", not minutes,
                4, self.cfg.get("layout", {}).get("agenda_end"), settled)

    def pending_download(self, m, minutes=False):
        """URL of the PDF that items() would have to download for this meeting, or None if cached."""
        url = m["minutes"] if minutes else m["agenda"]
        if not url or is_cached(url):
            return None
        key, agenda, _, end, settled = self._text_args(m, minutes)
        return None if settled and settled_text(key, agenda, end) else url

    def items(self, mid, minutes=False):
        m = mid if isinstance(mid, dict) else self.find(mid)
        url = m["minutes"] if minutes else m["agenda"]
        if not url:
            raise NotFound(f"meeting {m['id']} has no {'minutes' if minutes else 'agenda'} posted")
        lay = self.cfg.get("layout", {})
        text = ocr_pdf(url, *self._text_args(m, minutes))
        rows = []
        split = split_paragraphs if minutes else lambda t: split_numbered(t, lay.get("item_start"), lay.get("ignore"),
                                                                           lay.get("section"))
        matter_re = re.compile(lay["matter"]) if lay.get("matter") else None
        for no, title, section, docket in split(text):
            mf = matter_re.search(title) if matter_re else None
            if mf and mf.start() == 0 and mf.group(0) == mf.group(1):
                title = title[mf.end():].strip()  # the number leads the title; it is printed as matter_file
            rows.append({"parish": self.cfg["key"], "meeting_id": m["id"], "date": m["date"], "body": m["body"],
                         "section": section, "item_no": no, "title": title,
                         "matter_file": mf.group(1) if mf else (no if docket else ""),
                         "matter_type": "",
                         "action": "", "outcome": "", "hearing_date": "", "attachments": [], "url": url,
                         "ocr": bool(self.cfg.get("scanned"))})
        return m, rows

    def files(self, mid):
        m = self.find(mid)
        return {k: m[k] for k in ("agenda", "packet", "minutes") if m[k]}


# The last line of an agenda proper. St. James and St. Bernard bind the packet (resolutions, prior minutes,
# plats) into the same PDF after it, so reading stops there. "XIU." is OCR for "XII.".
END_LINE = re.compile(r"^\s*(?:(?:[IVXLivxlUumMn]{1,5}|\d{1,2})[.,)]?\s+)?(?:motion to\s+)?adjourn(?:ment)?\.?\s*$", re.I)


def agenda_end(lines, end=None):
    """Index of the line that closes the agenda, or None. A public-hearing preamble has its own adjourn
    with the regular agenda still to come, so the end is an adjourn line with no numbered item after it."""
    extra = re.compile(end) if end else None
    ends = [j for j, ln in enumerate(lines) if END_LINE.match(ln) or (extra and extra.search(ln))]
    if ends and not any(NUM_LINE.match(ln) for ln in lines[ends[-1] + 1:]):
        return ends[-1]
    return None


def text_suffix(agenda, end):
    return "-head" + hashlib.sha256(f"{END_LINE.pattern}|{end}".encode()).hexdigest()[:6] if agenda else ""


def settled_text(key, agenda=False, end=None):
    """Path of text already extracted for this file under any PDF hash, or None. Only for settled
    meetings: without it each lapse of the http TTL re-downloads the PDF just to hash it, about
    80 MB for a year of St. Bernard agendas."""
    if REFRESH:
        return None
    found = glob.glob(os.path.join(CACHE, "ocr", f"{key}-{'[0-9a-f]' * 16}{text_suffix(agenda, end)}.txt"))
    return max(found, key=os.path.getmtime) if found else None


def ocr_pdf(url, key, agenda=False, max_pages=4, end=None, settled=False):
    """Text of a PDF: its text layer if it has one, else tesseract OCR. Cached by key and PDF hash.
    agenda=True keeps only the pages up to the agenda's closing line; a scan is OCR'd for at most
    max_pages, since each page costs about 1.5 s. end is an extra closing-line regex for the parish."""
    old = settled_text(key, agenda, end) if settled else None
    if old:
        return open(old).read()
    pdf = fetch(url, binary=True, ttl=TTL)
    if not pdf.startswith(b"%PDF"):
        raise Upstream(f"not a PDF: {url}")
    digest = hashlib.sha256(pdf).hexdigest()[:16] + text_suffix(agenda, end)
    path = os.path.join(CACHE, "ocr", f"{key}-{digest}.txt")
    if os.path.exists(path):
        return open(path).read()
    for tool in ("pdftotext", "pdftoppm", "pdfinfo", "tesseract"):
        if not shutil.which(tool):
            raise Upstream(f"{tool} not found (brew install poppler tesseract)")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        open(src, "wb").write(pdf)
        text = subprocess.run(["pdftotext", "-layout", src, "-"], capture_output=True, text=True).stdout
        if len(text.strip()) >= 200:
            pages = text.split("\f")
        else:  # a copier scan's text layer is empty or a few stray glyphs
            info = subprocess.run(["pdfinfo", src], capture_output=True, text=True).stdout
            npages = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 1])[1])
            pages = []
            for i in range(1, (min(npages, max_pages) if agenda else npages) + 1):
                subprocess.run(["pdftoppm", "-r", "300", "-gray", "-f", str(i), "-l", str(i), "-singlefile",
                                src, os.path.join(tmp, "p")], check=True)
                pages.append(subprocess.run(["tesseract", os.path.join(tmp, "p.pgm"), "-", "--psm", "4"],
                                            capture_output=True, text=True).stdout)
                if agenda and agenda_end(pages[-1].splitlines(), end) is not None:
                    break
        if agenda:
            kept = []
            for pg in pages:
                lines = pg.splitlines()
                stop = agenda_end(lines, end)
                kept.append("\n".join(lines if stop is None else lines[:stop + 1]))
                if stop is not None:
                    break
            pages = kept
        text = "\n\f".join(pages)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return text


def split_paragraphs(text):
    """Split prose minutes into (p<N>, paragraph, section): St. James minutes have headings, not item numbers."""
    out, section, buf = [], "", []

    def flush():
        para = " ".join(" ".join(buf).split())
        if len(para) >= 40:
            out.append((f"p{len(out) + 1}", para, section, False))
        buf.clear()

    for line in text.replace("\f", "\n").splitlines():
        h = heading(line)
        # Minutes print each resolution's title in capitals, wrapping over lines; that is the paragraph's
        # text, not a section.
        if h and len(h) <= 50 and not re.match(r"(?:RESOLUTION|ORDINANCE)\b", h):
            flush()
            section = h
        elif line.strip():
            buf.append(line.strip())
        else:
            flush()
    flush()
    return out


# Agendas nest numbers and letters ("7." > "a)" > "1."); a single letter counts as an item number too.
NUM_LINE = re.compile(r"^\s*(\d{1,2}|[a-zA-Z])[.)]\s+(\S.*)$")
DIGIT_LINE = re.compile(r"^\s*\d{1,2}[.)]\s+\S")
# OCR reads Roman numerals unreliably (II -> "I", VII -> "VU", III -> "mi"), so a heading is any short
# line that starts with a numeral-like token and is mostly capitals.
# A numbered heading may run on into lowercase text ("IV. PUBLIC COMMENT on any agenda item ..."); only the
# capitals are the section name, and the period after the numeral is then required.
HEAD_LINE = re.compile(r"^\s*(?:[IVXLivxlUumMn1]{1,5}[.,]?\s+([A-Z][A-Z ,&’'/()–—-]{3,})"
                       r"|[IVXLivxlUumMn1]{1,5}[.,]\s+([A-Z]{2,}(?: [A-Z][A-Z,&’'/()–—-]*)+)(?= [a-z]).*)\s*$")
CAPS_LINE = re.compile(r"^\s*((?=[^a-z]*$)[0-9:. ]*[A-Z][A-Z0-9 .,&’'/()–—-]{7,})\s*$")


def heading(line):
    h = HEAD_LINE.match(line) or CAPS_LINE.match(line)
    return h and not DIGIT_LINE.match(line) and next(g for g in h.groups() if g).strip(" –—-")


def continues(prev, line, item_indent):
    """A capitals line inside an open item that is the item's own text: an ordinance title printed in
    capitals (St. Bernard) or a sponsor name wrapped onto its own line ("... COUNCIL" / "MEMBER EDWARDS").
    Section headings sit at or left of the item numbers; item text hangs to their right."""
    if len(line) - len(line.lstrip()) > item_indent + 2:
        return True
    prev = prev.strip()
    if not prev:
        return False
    if SPONSOR_LINE.match(line):
        return True
    return len(line.strip()) > 60 or bool(re.search(r"\b[A-Z]{2,}[,;-]?$", prev))


SPONSOR_LINE = re.compile(r"^\s*(?:COUNCIL\s*)?(?:WO)?MEMBERS?\s+[A-Z][A-Z' .-]+$")


def nest(stack, line, label):
    """Dotted item number ("7.a.4"). Plaquemines nests "1." > "a)" > "1." with indents that drift, so the
    sequence decides first: "j" after an open "i" is its sibling, and "1"/"a" opens a sub-list under an
    open item of the other kind or a shallower indent. Only otherwise does indent decide (within 2 columns counts as equal; OCR shifts it)."""
    if not (label.isdigit() or (label.isalpha() and len(label) == 1)):
        return label  # a docket number (St. Bernard "S-2026-020") names the item itself
    indent = len(line) - len(line.lstrip())
    kind = "a" if label.isalpha() else "1"
    pred = str(int(label) - 1) if kind == "1" else chr(ord(label) - 1)
    sib = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][1] == kind and stack[i][2] == pred), None)
    if sib is not None:
        del stack[sib:]
    elif label in ("1", "a", "A"):
        # A list restarting at its own level (Assumption numbers each committee's items from 1 with no
        # capitals heading between) is not a sub-list.
        while stack and (stack[-1][0] > indent + 2 or (abs(stack[-1][0] - indent) <= 2 and stack[-1][1] == kind)):
            stack.pop()
    else:
        while stack:
            top_indent, top_kind, _ = stack[-1]
            if top_indent > indent + 2 or (abs(top_indent - indent) <= 2 and (top_kind == kind or kind == "1")):
                stack.pop()
            else:
                break
    stack.append((indent, kind, label))
    return ".".join(lbl for _, _, lbl in stack)


def letter_in_sequence(stack, label):
    """A lone letter starts an item only if it opens a list or follows the open one ("j" after "i");
    otherwise it is an initial wrapped to the start of a line ("S. Teegarden, A Louisiana ...")."""
    if not (label.isalpha() and len(label) == 1):
        return True
    return label in "aA" or any(k == "a" and lbl == chr(ord(label) - 1) for _, k, lbl in stack)


def split_numbered(text, item_start=None, ignore=None, section_re=None):
    """Split agenda text into (number, title, section, docket) at numbered lines. item_start is an extra regex
    whose group 1 is the item number and group 2 its text (St. Bernard's "S-2026-020  Requesting ...");
    docket is true for items it started, whose number is then the case number rather than a list position;
    ignore drops repeated page headers before they can read as section headings. section_re marks
    mixed-case headings (Assumption's "Finance Committee Meeting"); its group 1 is the section name."""
    starts = [NUM_LINE] + ([re.compile(item_start)] if item_start else [])
    skip = re.compile(ignore) if ignore else None
    sec = re.compile(section_re) if section_re else None
    out, cur, section, prev, stack = [], None, "", "", []
    for line in text.splitlines():
        if skip and skip.search(line):
            continue
        h = heading(line)
        if h and cur and not HEAD_LINE.match(line) and continues(prev, line, cur[3]):
            h = None
        if not h and sec and sec.match(line):
            h = sec.match(line).group(1).strip()
        n = None if h else next((m for m in (r.match(line) for r in starts) if m), None)
        if n and not letter_in_sequence(stack, n.group(1)):
            n = None
        if h:
            if cur:
                out.append(cur)
                cur = None
            section, stack = h, []
        elif n:
            if cur:
                out.append(cur)
            cur = [nest(stack, line, n.group(1)), n.group(2).strip(), section, len(line) - len(line.lstrip()),
                   n.re is not NUM_LINE]
        elif cur and line.strip():
            cur[1] += " " + line.strip()
        elif cur and not line.strip() and len(cur[1]) > 400:
            out.append(cur)
            cur = None
        prev = line
    if cur:
        out.append(cur)
    return [(a, " ".join(b.split()), c, d) for a, b, c, _, d in out]


ADAPTERS = {"legistar": Legistar, "civicclerk": CivicClerk, "civicplus": CivicPlus}


def adapter(key):
    cfg = parish_cfg(key)
    return ADAPTERS[cfg["platform"]](cfg)


# ---------------------------------------------------------------- keyword alerts

def patterns(cfg, only=None, extra=None):
    cats = {k: list(v) for k, v in load("keywords.json")["categories"].items()}
    for k, v in (cfg.get("terms") or {}).items():
        cats.setdefault(k, []).extend(v)
    if only:
        cats = {k: v for k, v in cats.items() if k in only}
    if extra:
        cats["custom"] = list(extra)
    return {k: re.compile("|".join(f"(?:{p})" for p in v), re.I) for k, v in cats.items() if v}


def classify(title, pats):
    hits = {}
    for k, rx in pats.items():
        m = rx.search(title)
        if m:
            hits[k] = m.group(0)
    return hits


def in_scope(m, cfg, body, all_bodies):
    if body:
        return body.lower() in m["body"].lower()
    return all_bodies or m["body"] not in (cfg.get("skip_bodies") or [])


# ---------------------------------------------------------------- download size check

def head_size(url):
    """Content-Length from a HEAD request; -1 if the server does not say."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or -1)
    except Exception:
        return -1


def confirm_downloads(work, cmd, yes):
    """Stop before a run whose uncached agenda PDFs total over BIG_BYTES, unless --yes. work is
    [(parish key, adapter, meeting)]; only AgendaCenter parishes download PDFs, and a St. Bernard
    council agenda carries its packet (about 7 MB)."""
    todo = [(k, m, u) for k, ad, m in work if isinstance(ad, CivicPlus) for u in [ad.pending_download(m)] if u]
    if yes or not todo:
        return
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(head_size, [u for _, _, u in todo]))
    total = sum(x for x in sizes if x > 0)
    if total <= BIG_BYTES:
        return
    by = {}
    for (k, m, _), x in zip(todo, sizes):
        by[f"{k} {m['body']}"] = by.get(f"{k} {m['body']}", 0) + max(x, 0)
    top, top_bytes = max(by.items(), key=lambda kv: kv[1])
    unknown = sum(1 for x in sizes if x < 0)
    print(f"{cmd} would download {len(todo)} agenda PDFs, {total / 1e6:.0f} MB"
          + (f" plus {unknown} of unknown size" if unknown else "")
          + f" (largest share: {top}, {top_bytes / 1e6:.0f} MB). Rerun with --yes, or narrow with --since"
          + (" or --body." if cmd == "alerts" else "."),
          file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- commands

def cmd_parishes(a):
    reg = load("parishes.json")["parishes"]
    rows = [{"key": k, "name": v["name"], "status": v["status"], "platform": v.get("platform") or "",
             "web": v.get("web", "")} for k, v in reg.items()]
    emit(rows, lambda rs: [print(f"{r['key']:22} {r['status']:9} {r['platform']:11} {r['name']}  {r['web']}") for r in rs])


def cmd_health(a):
    keys = a.parishes or [k for k, v in load("parishes.json")["parishes"].items() if v["status"] == "verified"]
    bad = 0
    for k in keys:
        t0 = time.time()
        try:
            ad = adapter(k)
            today = datetime.date.today()
            ms = ad.meetings((today - datetime.timedelta(days=120)).isoformat(), today.isoformat())
            if not ms:
                raise Upstream("no meetings in the last 120 days")
            note = f"{len(ms)} meetings in 120 days"
            if isinstance(ad, CivicClerk):
                ids = [m["event_id"] for m in ms]
                if len(ids) != len(set(ids)) or len(ids) <= 15:
                    raise Upstream(f"paging suspect: {len(ids)} rows, {len(set(ids))} unique")
                note += f", paged past 15 ({len(ids)} unique)"
            if not (isinstance(ad, CivicPlus) and ad.cfg.get("scanned")):
                # The newest file can be a one-page notice with no items (East Baton Rouge), so try a few.
                for m in [m for m in reversed(ms) if m["agenda"]][:3]:
                    _, its = ad.items(m if isinstance(ad, CivicPlus) else m["id"])
                    if its:
                        note += f"; {m['date']} {m['body']}: {len(its)} items"
                        break
                else:
                    raise Upstream("the three newest agendas split into no items")
            print(f"ok   {k:12} {note}  ({time.time() - t0:.1f}s)")
        except (Upstream, NotFound) as e:
            bad += 1
            print(f"FAIL {k:12} {e}")
    if bad:
        sys.exit(5)


def cmd_bodies(a):
    rows = adapter(a.parish).bodies()
    emit(rows, lambda rs: [print(f"{str(r.get('id')):>5}  {r['name']}" + (f"  ({r['meetings']} meetings, last {r['last']})" if 'meetings' in r else "")) for r in rs])


def default_window(a, back=14, ahead=45):
    today = datetime.date.today()
    since = a.since or (today - datetime.timedelta(days=back)).isoformat()
    until = a.until or (today + datetime.timedelta(days=ahead)).isoformat()
    return since, until


def cmd_meetings(a):
    ad = adapter(a.parish)
    since, until = default_window(a, 30, 60)
    rows = [m for m in ad.meetings(since, until) if in_scope(m, ad.cfg, a.body, a.all_bodies)]
    rows = [{k: v for k, v in m.items() if k != "file_ids"} for m in rows]

    def render(rs):
        for m in rs:
            have = ",".join(k for k in ("agenda", "packet", "minutes") if m.get(k)) or "nothing posted"
            st = f" [{m['agenda_status']}]" if m.get("agenda_status") and m["agenda_status"] != "Final" else ""
            # AgendaCenter posts several files per meeting (regular agenda, public notice, addendum);
            # its title says which.
            title = f" | {m['title']}" if m.get("title") and m["title"] != m["body"] else ""
            print(f"{m['date']} {m['time']:>8}  id {m['id']:>6}  {m['body']}{st}{title}  ({have})"
                  + (f"  posted {m['posted']}" if m.get("posted") else ""))
        print(f"{len(rs)} meetings {since}..{until}", file=sys.stderr)
    emit(rows, render)


def print_items(meta, rows, pats=None):
    print(f"== {meta.get('date')} {meta.get('body')}  (meeting {meta.get('id')})  {meta.get('url', '')}")
    sec = None
    for r in rows:
        if r["section"] != sec:
            sec = r["section"]
            print(f"\n  [{sec}]" if sec else "")
        tags = classify(f"{r['matter_file']} {r['title']}", pats) if pats else {}
        mark = f"  <{', '.join(tags)}>" if tags else ""
        mf = f" {r['matter_file']}" if r["matter_file"] and r["matter_file"] != r["item_no"] else ""
        print(f"  {r['item_no'] or '-':>6}{mf}  {r['title'][:300]}{mark}")
        extra = [x for x in (r["action"] and f"action: {r['action']}", r["outcome"] and f"outcome: {r['outcome']}",
                             r["hearing_date"] and f"public hearing: {r['hearing_date']}",
                             r["attachments"] and f"{len(r['attachments'])} attachments") if x]
        if extra:
            print("        " + " | ".join(extra))
    if rows and rows[0].get("ocr"):
        print("\n  (OCR text from a scanned PDF: check the PDF before quoting)")


def cmd_items(a):
    ad = adapter(a.parish)
    meta, rows = ad.items(a.meeting, minutes=a.minutes) if isinstance(ad, CivicPlus) else ad.items(a.meeting)
    if not rows:
        raise NotFound(f"meeting {a.meeting} has no agenda items online")
    pats = patterns(ad.cfg)
    if a.parish == "ascension" and "council" in (meta.get("body") or "").lower() and not meta.get("minutes"):
        print("note: Ascension posts no council minutes; outcomes are not online (see SKILL.md).", file=sys.stderr)
    emit({"meeting": {k: v for k, v in meta.items() if k != "file_ids"}, "items": rows},
         lambda d: print_items(d["meeting"], d["items"], pats))


def cmd_alerts(a):
    keys = a.parishes or [k for k, v in load("parishes.json")["parishes"].items() if v["status"] == "verified"]
    since, until = default_window(a)
    hits, gaps, work = [], [], []
    for k in keys:
        ad = adapter(k)
        for m in ad.meetings(since, until):
            if not in_scope(m, ad.cfg, a.body, a.all_bodies):
                continue
            if m["agenda"]:
                work.append((k, ad, m))
            else:
                gaps.append(f"{k} {m['date']} {m['body']}: no agenda posted yet")
    confirm_downloads(work, "alerts", a.yes)
    pats = {}
    for k, ad, m in work:
        if k not in pats:
            pats[k] = patterns(ad.cfg, a.category, a.term)
        try:
            _, rows = ad.items(m if isinstance(ad, CivicPlus) else m["id"])
        except (NotFound, Upstream) as e:
            gaps.append(f"{k} {m['date']} {m['body']}: {e}")
            continue
        for r in rows:
            tags = classify(f"{r['matter_file']} {r['title']}", pats[k])
            if tags:
                hits.append(dict(r, categories=tags))

    def render(hs):
        for h in sorted(hs, key=lambda h: (h["date"], h["parish"], h["body"])):
            mf = f" {h['matter_file']}" if h["matter_file"] and h["matter_file"] != h["item_no"] else ""
            print(f"{h['date']} {h['parish']:16} {h['body'][:34]:34} {h['item_no'] or '-':>6}{mf}  "
                  f"<{', '.join(h['categories'])}>\n    {h['title'][:400]}")
            for x in (h["action"] and f"action: {h['action']}", h["outcome"] and f"outcome: {h['outcome']}",
                      h["hearing_date"] and f"public hearing: {h['hearing_date']}"):
                if x:
                    print(f"    {x}")
            print(f"    {h['url']}")
        for g in gaps:
            print(f"gap: {g}", file=sys.stderr)
        print(f"{len(hs)} hits {since}..{until}. A hit is a lead to read, not a finding.", file=sys.stderr)
    emit(hits, render)


def distinctive(text):
    """Search keys for a case title: case numbers and company names (Capitalized Words, LLC)."""
    keys = re.findall(r"\b\d{4}-\d+-[A-Z]{1,4}\b|\bPZ-\d+\.\d+\b|\b(?:DC|ZT)-\d+\.\d+\b|\b\d{4}-\d{4}\b", text)
    keys += re.findall(r"((?:[A-Z][\w&'-]*\.? ){1,5}?[A-Z][\w&'-]*),? (?:LLC|L\.L\.C\.|Inc\.?|Corporation|Company)\b", text)
    return list(dict.fromkeys(keys)) or [text]


def cmd_track(a):
    ad = adapter(a.parish)
    since = a.since or (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    until = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
    keys = [k.lower() for k in distinctive(a.text)] + [a.text.lower()]
    found = {"query": a.text, "keys": keys, "matters": [], "items": []}
    # Agenda lines first: in St. Charles a P&Z case line names the applicant that the council title uses.
    # Legistar council lines are matters, searched below with their full history.
    work = [(a.parish, ad, m) for m in ad.meetings(since, until) if m["agenda"] and in_scope(m, ad.cfg, None, False)
            and not (isinstance(ad, Legistar) and m["body"] == "Parish Council")]
    confirm_downloads(work, "track", a.yes)
    for _, _, m in work:
        try:
            _, rows = ad.items(m if isinstance(ad, CivicPlus) else m["id"])
        except (NotFound, Upstream):
            continue
        for r in rows:
            t = f"{r['matter_file']} {r['title']}".lower()
            if any(k in t for k in keys):
                found["items"].append(r)
    if isinstance(ad, Legistar):
        names = distinctive(a.text) + [n for r in found["items"] for n in distinctive(r["title"])]
        files = [n for n in names if re.fullmatch(r"\d{4}-\d{4}", n)]
        names = [n for n in dict.fromkeys(names) if not re.fullmatch(r"\d{4}-\d+-[A-Z]{1,4}|\d{4}-\d{4}", n)]
        seen = set()
        for mf in files:
            seen.add(mf)
            found["matters"].append(ad.matter(mf))
        for key in names:
            for m in ad.search_matters(key, since):
                if m["MatterFile"] not in seen:
                    seen.add(m["MatterFile"])
                    found["matters"].append(ad.matter(m["MatterFile"]))
    if not found["matters"] and not found["items"]:
        raise NotFound(f"'{a.text}' not found in {ad.cfg['name']} matters or agenda lines since {since}")

    def render(d):
        for m in d["matters"]:
            print(f"== matter {m['matter_file']}  {m['type']}  {m['status']}  enactment {m['enactment_no'] or '-'}\n   {m['title']}\n   {m['url']}")
            if m.get("hearing_date"):
                print(f"   public hearing: {m['hearing_date']}")
            for h in m["history"]:
                print(f"   {h['date']}  {h['body']}: {h['action']} {h['passed']}")
            for at in m["attachments"]:
                print(f"   attachment: {at['name']}  {at['url']}")
        if d["items"]:
            print("== agenda lines")
        for r in sorted(d["items"], key=lambda r: r["date"]):
            print(f"   {r['date']} {r['body']}  {r['item_no']}  {r['title'][:300]}" + (f"  [{r['action']}]" if r["action"] else ""))
        if any(r.get("ocr") for r in d["items"]):
            print("   (OCR text: check the PDF before quoting)")
        heard = sorted({r["date"] for r in d["items"] if re.match(r"public hearing", r["title"], re.I)})
        if len(heard) > 1:
            print(f"   public hearing on {len(heard)} agendas ({', '.join(heard)}): not finally acted on before "
                  f"{heard[-1]} (deferred, continued or re-noticed). Confirm from minutes or video.")
    emit(found, render)


def cmd_get(a):
    ad = adapter(a.parish)
    files = ad.files(a.meeting)
    want = a.what or ["agenda"]
    os.makedirs(a.out, exist_ok=True)
    for w in want:
        url = files.get(w)
        if not url:
            print(f"meeting {a.meeting}: no {w} posted (have: {', '.join(files) or 'nothing'})", file=sys.stderr)
            continue
        size = head_size(url)
        if size > BIG_BYTES and not a.yes:
            print(f"{w}: {size / 1e6:.0f} MB at {url}; rerun with --yes to download", file=sys.stderr)
            sys.exit(2)
        body = fetch(url, binary=True, ttl=0, timeout=300)
        dest = os.path.join(a.out, f"{a.parish}-{a.meeting}-{w}.pdf")
        open(dest, "wb").write(body)
        print(f"{w}: {len(body) / 1e6:.1f} MB -> {dest}")


def main():
    global REFRESH, JSON_OUT
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--refresh", action="store_true")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parishes", parents=[common])
    p = sub.add_parser("health", parents=[common]); p.add_argument("parishes", nargs="*")
    p = sub.add_parser("bodies", parents=[common]); p.add_argument("parish")
    for name in ("meetings", "alerts"):
        p = sub.add_parser(name, parents=[common])
        if name == "meetings":
            p.add_argument("parish")
        else:
            p.add_argument("parishes", nargs="*")
            p.add_argument("--category", action="append", help="limit to these keywords.json categories")
            p.add_argument("--term", action="append", help="extra regex, reported as category 'custom'")
            p.add_argument("--yes", action="store_true", help="download even if the agenda PDFs total over 25 MB")
        p.add_argument("--body", help="substring of the body name (overrides skip_bodies)")
        p.add_argument("--since"); p.add_argument("--until")
        p.add_argument("--all-bodies", action="store_true")
    p = sub.add_parser("items", parents=[common]); p.add_argument("parish"); p.add_argument("meeting")
    p.add_argument("--minutes", action="store_true", help="scanned parishes: OCR the minutes instead of the agenda")
    p = sub.add_parser("track", parents=[common]); p.add_argument("parish"); p.add_argument("text"); p.add_argument("--since")
    p.add_argument("--yes", action="store_true", help="download even if the agenda PDFs total over 25 MB")
    p = sub.add_parser("get", parents=[common]); p.add_argument("parish"); p.add_argument("meeting")
    p.add_argument("--what", action="append", choices=["agenda", "packet", "minutes", "notice"])
    p.add_argument("--out", default="."); p.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    REFRESH, JSON_OUT = a.refresh, a.json
    try:
        for d in ("since", "until"):
            if getattr(a, d, None):
                day(getattr(a, d))
    except ValueError:
        ap.error("dates are YYYY-MM-DD")
    try:
        globals()["cmd_" + a.cmd](a)
    except NotFound as e:
        print(e, file=sys.stderr)
        sys.exit(3)
    except Upstream as e:
        print(f"upstream: {e}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
