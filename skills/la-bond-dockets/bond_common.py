"""Shared fetch, cache, download-guard and PDF-text helpers for the la-bond-dockets scripts.

Standard library only, plus the `pdftotext` binary from poppler.
"""
import datetime
import html
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (bayou-la-bond-dockets)"
DEFAULT_CACHE = os.path.expanduser("~/.cache/bayou/la-bond-dockets")
# Agendas run 1-2 MB each, so these limits only trip on multi-year sweeps.
GUARD_MAX_FILES = 25
GUARD_MAX_MB = 100

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


class GuardStop(Exception):
    pass


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_text(url):
    return fetch(url).decode("utf-8", errors="replace")


def head_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except (urllib.error.URLError, ValueError, OSError):
        return 0


def cache_path(cache, url, sub):
    parts = urllib.parse.urlparse(url)
    name = urllib.parse.unquote(os.path.basename(parts.path)) or "index"
    # Different issuers reuse generic names like "Port-Commission-Meeting-1.pdf".
    host = (parts.netloc.split(".")[-2:-1] or ["x"])[0]
    d = os.path.join(cache, sub)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s__%s" % (host, name))


def guard(urls, cache, sub, yes):
    """Refuse to start a large uncached download without --yes.

    Prints the estimate to stderr either way so the caller can relay it.
    """
    todo = [u for u in dict.fromkeys(urls) if not os.path.exists(cache_path(cache, u, sub))]
    if not todo:
        return
    total = sum(head_size(u) for u in todo)
    mb = total / 1e6
    free_mb = shutil.disk_usage(os.path.expanduser("~")).free / 1e6
    msg = "download estimate: %d uncached PDF(s), ~%.1f MB (free disk ~%.0f MB, cache %s)" % (len(todo), mb, free_mb, cache)
    if not yes and (len(todo) > GUARD_MAX_FILES or mb > GUARD_MAX_MB):
        raise GuardStop(msg + " -- over the %d-file / %d MB limit; narrow the date range or rerun with --yes"
                        % (GUARD_MAX_FILES, GUARD_MAX_MB))
    print(msg, file=sys.stderr)


def get_pdf(url, cache, sub):
    path = cache_path(cache, url, sub)
    if not os.path.exists(path):
        data = fetch(url, timeout=90)
        with open(path + ".part", "wb") as fh:
            fh.write(data)
        os.replace(path + ".part", path)
    return path


def pdf_text(path, layout=True):
    """Text of a PDF via pdftotext, cached next to it. Pages are separated by form feeds."""
    if shutil.which("pdftotext") is None:
        sys.exit("pdftotext not found; install poppler (brew install poppler)")
    out = path + (".layout.txt" if layout else ".raw.txt")
    if not os.path.exists(out):
        cmd = ["pdftotext"] + (["-layout"] if layout else []) + [path, out]
        subprocess.run(cmd, check=True, capture_output=True)
    with open(out, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def has_text_layer(text):
    return len(re.sub(r"\s", "", text)) > 200


def links(page_html, base):
    """(absolute href, visible text) for every anchor, de-duplicated, in page order."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page_html, flags=re.S | re.I)
    seen, out = set(), []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S | re.I):
        href = urllib.parse.urljoin(base, html.unescape(m.group(1)))
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        if (href, text) in seen:
            continue
        seen.add((href, text))
        out.append((href, text))
    return out


def parse_date(s):
    """Best-effort date from link text or a filename. Returns a date or None."""
    if not s:
        return None
    t = s.replace("_", " ").replace("%20", " ")
    m = re.search(r"\b(20\d\d)[-_ ](\d{1,2})[-_ ](\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d\d|\d\d)\b", t)
    if m:
        y = int(m.group(3))
        return _mk(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*[-_ .,]*(\d{1,2})?(?:st|nd|rd|th)?[-_ ,]*(20\d\d)\b", t, re.I)
    if m:
        return _mk(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2) or 1))
    return None


def _mk(y, mo, d):
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def arg_date(s):
    d = parse_date(s)
    if d is None:
        raise ValueError("unrecognised date: %r (use YYYY-MM-DD or MM/DD/YYYY)" % s)
    return d


def norm(s):
    return " ".join(s.replace("­", "-").replace("’", "'").split())
