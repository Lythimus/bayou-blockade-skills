"""Shared fetch, cache, guard, docket and PDF helpers for the la-court-opinions scripts.

Standard library only, plus the `pdftotext` binary from poppler.
"""
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# The First Circuit's CivicLive host returns 403 to non-browser user agents.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
DEFAULT_CACHE = os.path.expanduser("~/.cache/bayou/la-court-opinions")
# Opinion PDFs run 0.1-5 MB; these limits only trip on bulk fetches.
GUARD_MAX_FILES = 25
GUARD_MAX_MB = 100

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class GuardStop(Exception):
    pass


def fetch(url, data=None, headers=None, timeout=60):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_text(url, **kw):
    return fetch(url, **kw).decode("utf-8", errors="replace")


def head_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except (urllib.error.URLError, ValueError, OSError):
        return 0


def sub_dir(cache, sub):
    d = os.path.join(cache, sub)
    os.makedirs(d, exist_ok=True)
    return d


def fresh(path, ttl_days):
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_days * 86400


def write_atomic(path, data):
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path + ".part", mode) as fh:
        fh.write(data)
    os.replace(path + ".part", path)


def cached_text(url, cache, sub, name, ttl_days):
    path = os.path.join(sub_dir(cache, sub), name)
    if not fresh(path, ttl_days):
        write_atomic(path, fetch_text(url))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def pdf_path(cache, url):
    # First Circuit links are GetFile.ashx?key=..., so the URL path carries no usable file name.
    return os.path.join(sub_dir(cache, "pdf"), hashlib.sha1(url.encode()).hexdigest()[:16] + ".pdf")


def guard_pdfs(urls, cache, yes):
    """Refuse to start a large uncached download without --yes. Prints the estimate either way."""
    todo = [u for u in dict.fromkeys(urls) if not os.path.exists(pdf_path(cache, u))]
    if not todo:
        return
    mb = sum(head_size(u) for u in todo) / 1e6
    free_mb = shutil.disk_usage(os.path.expanduser("~")).free / 1e6
    msg = "download estimate: %d uncached PDF(s), ~%.1f MB (free disk ~%.0f MB, cache %s)" % (len(todo), mb, free_mb, cache)
    if not yes and (len(todo) > GUARD_MAX_FILES or mb > GUARD_MAX_MB):
        raise GuardStop(msg + " -- over the %d-file / %d MB limit; narrow the request or rerun with --yes"
                        % (GUARD_MAX_FILES, GUARD_MAX_MB))
    print(msg, file=sys.stderr)


def get_pdf(url, cache, meta=None):
    """Download once; `meta` is stored beside the PDF so `grep --cached` can name the case."""
    path = pdf_path(cache, url)
    if not os.path.exists(path):
        write_atomic(path, fetch(url, timeout=120))
    if meta:
        write_atomic(path + ".json", json.dumps(dict(meta, url=url)))
    return path


def pdf_text(path, layout=False):
    """Text via pdftotext, cached beside the PDF. Pages are separated by form feeds."""
    if shutil.which("pdftotext") is None:
        sys.exit("pdftotext not found; install poppler (brew install poppler)")
    out = path + (".layout.txt" if layout else ".txt")
    if not os.path.exists(out):
        subprocess.run(["pdftotext"] + (["-layout"] if layout else []) + [path, out], check=True, capture_output=True)
    with open(out, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def clean(s):
    return " ".join(html.unescape(html.unescape(s or "")).replace("\xa0", " ").split())


# ---------------------------------------------------------------- dockets

CIRCUIT_DOMAINS = {"la-fcca.org": 1, "lafcca.hosted2.civiclive.com": 1, "la2nd.org": 2, "la3circuit.org": 3,
                   "la4th.org": 4, "fifthcircuit.org": 5, "lasc.org": 0}
LASC_TYPES = {"C", "CC", "K", "KK", "KP", "KH", "KD", "KA", "CA", "CD", "CJ", "OB", "B", "D", "J", "U", "Z", "CI"}


def circuit_from_url(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    for dom, c in CIRCUIT_DOMAINS.items():
        if host.endswith(dom):
            return c
    return None


def _yr(y):
    y = int(y)
    if y >= 100:
        return y
    return 1900 + y if y > 50 else 2000 + y


def parse_docket(s, court=None, url=None, circuit=None):
    """Normalize a Louisiana appellate docket number.

    Returns {court, circuit, year, type, number, key, text} or None. `circuit` is 0 for the Supreme
    Court. `court` ("la"/"lactapp") and `url` break ties between formats several courts share:
    LASC and the Fourth Circuit both write 2024-CA-0286, LASC and the Fifth both write 95-C-2127.
    `circuit` (0-5, from a citation's court parenthetical) also unlocks the uniform-citation form
    without case-type letters ("2023-0578"); its `type` is "" and only `loose` keys can match it.
    """
    if not s:
        return None
    t = clean(s).upper()
    t = re.sub(r"^(?:NOS?\.?|NUMBERS?|DOCKET(?: NO\.?)?)\s*", "", t)
    hint = circuit_from_url(url)
    if court == "la":
        hint = 0
    if circuit is not None:
        hint = circuit
    m = re.search(r"\b(\d{2}),(\d{3})-([A-Z]{2,3})\b", t)
    if m:
        c, y, ty, n = 2, None, m.group(3), int(m.group(1) + m.group(2))
    else:
        m = re.search(r"\b(\d{4}|\d{2}) ([A-Z]{1,3}) (\d{3,4})\b", t)
        if m:
            c, y, ty, n = 1, _yr(m.group(1)), m.group(2), int(m.group(3))
        else:
            m = re.search(r"\b([A-Z]{1,3}) ?(\d{2})-(\d{1,5})\b", t)
            if m and m.group(1) not in ("NO",):
                c, y, ty, n = 3, _yr(m.group(2)), m.group(1), int(m.group(3))
            else:
                m = re.search(r"\b(\d{4}|\d{2})-([A-Z]{1,3})-(\d{1,5})\b", t)
                if not m:
                    u = re.search(r"\b(\d{4}|\d{2})-(\d{1,5})\b", t) if circuit is not None else None
                    if u:
                        c = circuit
                    else:
                        # CourtListener files Third Circuit dockets bare ("18-279").
                        u = re.fullmatch(r"\s*(\d{2})-(\d{1,4})\s*", t) if court == "lactapp" else None
                        if not u:
                            return None
                        c = 3
                    y, ty, n = _yr(u.group(1)), "", int(u.group(2))
                    crt = "la" if c == 0 else "lactapp"
                    return {"court": crt, "circuit": c, "year": y, "type": ty, "number": n, "text": clean(s),
                            "key": "%s:%s:%s::%s" % (crt, c, y, n), "loose": "%s:%s:%s:%s" % (crt, c, y, n)}
                y, ty, num = _yr(m.group(1)), m.group(2), m.group(3)
                n = int(num)
                if hint is not None and hint in (0, 4, 5):
                    c = hint
                elif court == "lactapp":
                    c = 4 if len(m.group(1)) == 4 else 5
                elif len(num) == 5 or (ty in LASC_TYPES and len(ty) == 1 and len(num) == 4 and len(m.group(1)) == 2):
                    c = 0
                else:
                    c = 4 if len(m.group(1)) == 4 else 5
    if hint is not None and hint != c and c != 2:
        # A domain is stronger evidence than a format several courts share.
        c = hint
    crt = "la" if c == 0 else "lactapp"
    key = "%s:%s:%s:%s:%s" % (crt, c, y or "", ty, n)
    return {"court": crt, "circuit": c, "year": y, "type": ty, "number": n, "key": key, "text": clean(s),
            "loose": "%s:%s:%s:%s" % (crt, c, y or "", n)}


def court_label(circuit):
    return "La." if circuit == 0 else ("La. App. %d Cir." % circuit if circuit else "La. App.")


def docket_display(d):
    """The docket the way the court itself writes it."""
    c, y, ty, n = d["circuit"], d["year"], d["type"], d["number"]
    if not ty:
        return uniform_docket(d)
    if c == 1:
        # The First Circuit wrote two-digit years until 1999.
        return ("%d %s %04d" if y >= 1999 else "%02d %s %04d") % (y if y >= 1999 else y % 100, ty, n)
    if c == 2:
        return "%d,%03d-%s" % (n // 1000, n % 1000, ty)
    if c == 3:
        return ("%s %02d-%d" % (ty, y % 100, n)) if ty else "%02d-%d" % (y % 100, n)
    if c == 4:
        return "%d-%s-%04d" % (y, ty, n)
    if c == 5:
        return "%02d-%s-%d" % (y % 100, ty, n)
    # LASC widened its serial to five digits in 2019 and wrote two-digit years before 1999.
    if y >= 2019:
        return "%d-%s-%05d" % (y, ty, n)
    return ("%d-%s-%04d" % (y, ty, n)) if y >= 1999 else ("%02d-%s-%04d" % (y % 100, ty, n))


# ---------------------------------------------------------------- opinion text

def parse_mdy(s):
    """'JAN 19 2024', 'January 19, 2024', '1/19/24' -> date or None."""
    s = s.strip()
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        try:
            return datetime.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        try:
            return datetime.date(_yr(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


DECRETAL = re.compile(r"\b(AFFIRMED|REVERSED|VACATED|REMANDED|DISMISSED|GRANTED|DENIED|AMENDED|RENDERED|REINSTATED)\b")
DATE_RX = r"[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}"


def _caps(line):
    s = line.strip()
    return bool(s) and s.upper() == s and re.search(r"[A-Z]{3}", s) is not None


def opinion_meta(text):
    """Decision date, disposition, panel and page count from an opinion's -layout text.

    Rehearing and writ actions are one-page forms with a date stamp and no "JUDGMENT RENDERED"
    line; they are reported as `kind: action` with each application and its result.
    """
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    head = "\n".join(" ".join(l.split()) for l in "\n".join(pages[:3]).splitlines())
    out = {"kind": "opinion", "pages": len(pages), "decision_date": None, "decision_date_line": None,
           "disposition": None, "panel": None, "actions": [], "text_layer": len(re.sub(r"\s", "", text)) > 200}
    m = re.search(r"(JUDGMENT RENDERED|DECIDED|DATE OF JUDGMENT|OPINION (?:FILED|RENDERED))\s*[:.]?\s*(" + DATE_RX + ")", head, re.I)
    if m:
        out["decision_date_line"] = m.group(0)
        d = parse_mdy(m.group(2))
        out["decision_date"] = d.isoformat() if d else None
    for m in re.finditer(r"Application for (Rehearing|Writ[^\n]*?) filed on ([^\n]*?) by ([^\n]+)\n(.*?)(?=Application for|\Z)",
                         "\n".join(" ".join(l.split()) for l in text.splitlines()), re.S | re.I):
        res = re.search(r"\b(DENIED|GRANTED|DISMISSED|NOT CONSIDERED)\b", m.group(4))
        stamp = re.search(r"^\s*(" + DATE_RX + r")\s*$", m.group(4), re.M)
        d = parse_mdy(stamp.group(1)) if stamp else None
        out["actions"].append({"application": m.group(1), "filed": m.group(2), "by": m.group(3).strip(),
                               "result": res.group(1) if res else "unreadable (OCR); read the PDF",
                               "date": d.isoformat() if d else None})
    if out["actions"] and not out["decision_date"]:
        out["kind"] = "action"
        dates = sorted({x["date"] for x in out["actions"] if x["date"]})
        out["decision_date"] = dates[-1] if dates else None
    # The disposition is the last all-caps decretal block, usually on the final page.
    lines = "\n".join(pages[-2:]).splitlines() if pages else []
    for i in range(len(lines) - 1, -1, -1):
        if _caps(lines[i]) and DECRETAL.search(lines[i]):
            a = b = i
            while a > 0 and _caps(lines[a - 1]) and not re.fullmatch(r"\s*\d+\s*", lines[a - 1]):
                a -= 1
            while b + 1 < len(lines) and _caps(lines[b + 1]):
                b += 1
            block = " ".join(" ".join(l.split()) for l in lines[a:b + 1])
            out["disposition"] = block
            break
    m = re.search(r"BEFORE\s*:?\s*(.{5,200}?JJ?\.)", head, re.S)
    if m:
        out["panel"] = clean(m.group(1))
    return out


def page_of(text, regex):
    """1-based page numbers (form-feed pages) where `regex` matches."""
    rx = re.compile(regex, re.I)
    return [i + 1 for i, p in enumerate(text.split("\f")) if rx.search(p)]


def uniform_docket(d):
    """Docket as the uniform citation rule writes it: year and serial, no case-type letters."""
    c, y, n = d["circuit"], d["year"], d["number"]
    if c == 2:
        return "%d,%03d" % (n // 1000, n % 1000)
    if y is None:
        return str(n)
    if c in (3, 5) or y < 2000:
        return "%02d-%d" % (y % 100, n) if c in (3, 5) else "%02d-%04d" % (y % 100, n)
    return "%d-%04d" % (y, n) if c != 0 or y < 2019 else "%d-%05d" % (y, n)


def format_cite(caption, docket, decision_date, reporter=None):
    """Louisiana uniform citation: Caption, 2023-0578 (La. App. 1 Cir. M/D/YY), Reporter.

    Only a decision date belongs here -- never a site upload date.
    """
    when = ""
    if decision_date:
        d = datetime.date.fromisoformat(decision_date[:10])
        when = "%d/%d/%02d" % (d.month, d.day, d.year % 100)
    parts = "%s, %s (%s %s)" % (caption, uniform_docket(docket) if docket else "", court_label(docket["circuit"]) if docket else "", when)
    return parts + (", " + reporter if reporter else "")


def emit(obj, as_json, render):
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        render(obj)
