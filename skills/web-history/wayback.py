#!/usr/bin/env python3
"""Reconstruct what a website said, and when, from the Wayback Machine.

    wayback.py captures <url> [--from YYYY] [--to YYYY] [--match-prefix] [--limit N]
    wayback.py text <timestamp> <url>
    wayback.py diff <url> <timestamp1> <timestamp2>
    wayback.py grep <url> <regex> [--from YYYY] [--to YYYY] [--match-prefix] [--max 40]

captures prints CSV on stdout; text and diff print plain text. Notes go to stderr.
Read-only: nothing here asks the Wayback Machine to save a page. Standard library only.
"""
import argparse
import csv
import difflib
import html.parser
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CDX = "https://web.archive.org/cdx/search/cdx"
UA = {"User-Agent": "BayouResearch (web-history skill)"}
# The archive throttles bursts with 429 and sometimes drops connections instead;
# a fixed pause between requests avoids most of both.
PAUSE = 1.5


def note(msg):
    print(msg, file=sys.stderr)


def fetch(url, timeout=90):
    delay = 10
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                body = r.read()
                charset = r.headers.get_content_charset() or "utf-8"
            time.sleep(PAUSE)
            return body.decode(charset, "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 4:
                note(f"HTTP {e.code}; waiting {delay}s before retry")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 4:
                note(f"{e}; waiting {delay}s before retry")
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def captures(url, start=None, end=None, prefix=False, limit=None):
    params = {
        "url": url,
        "output": "json",
        # collapse=digest drops consecutive captures with identical bytes, leaving one row per change.
        "collapse": "digest",
        "filter": "statuscode:200",
        "fl": "timestamp,original,digest,length,mimetype",
    }
    if start:
        params["from"] = str(start)
    if end:
        params["to"] = str(end)
    if prefix:
        params["matchType"] = "prefix"
    if limit:
        params["limit"] = str(limit)
    body = fetch(f"{CDX}?{urllib.parse.urlencode(params)}")
    rows = json.loads(body) if body.strip() else []
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:]]


class TextExtractor(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article",
             "header", "footer", "nav", "main", "aside", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "pre", "dd", "dt", "figcaption", "title", "option"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_text(timestamp, url):
    # The id_ suffix returns the page as archived, without the Wayback toolbar or rewritten links.
    raw = fetch(f"https://web.archive.org/web/{timestamp}id_/{url}")
    p = TextExtractor()
    p.feed(raw)
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line)


def cmd_captures(args):
    rows = captures(args.url, args.start, args.end, args.match_prefix, args.limit)
    w = csv.writer(sys.stdout)
    w.writerow(["timestamp", "date", "original", "digest", "length", "mimetype", "snapshot_url"])
    for r in rows:
        ts = r["timestamp"]
        w.writerow([ts, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", r["original"], r["digest"], r["length"],
                    r.get("mimetype", ""), f"https://web.archive.org/web/{ts}/{r['original']}"])
    note(f"{len(rows)} distinct version(s) of {args.url}"
         + (" and pages under it" if args.match_prefix else ""))
    if not rows:
        note("No captures. Try with and without 'www.', with and without a trailing slash, "
             "or --match-prefix on the domain. An empty result can also mean the site is excluded from the archive.")


def cmd_text(args):
    print(page_text(args.timestamp, args.url))


def cmd_diff(args):
    a = page_text(args.ts1, args.url).splitlines()
    b = page_text(args.ts2, args.url).splitlines()
    out = list(difflib.unified_diff(a, b, f"{args.url} @ {args.ts1}", f"{args.url} @ {args.ts2}",
                                    n=args.context, lineterm=""))
    print("\n".join(out) if out else "No text differences (the HTML changed but the visible text did not).")


def cmd_grep(args):
    pattern = re.compile(args.regex, re.I)
    rows = [r for r in captures(args.url, args.start, args.end, args.match_prefix)
            if "html" in r.get("mimetype", "html")]
    if len(rows) > args.max:
        # Spread the sample over the whole period instead of taking only the earliest versions.
        step = len(rows) / args.max
        sampled = [rows[int(i * step)] for i in range(args.max)]
        note(f"{len(rows)} versions; sampling {args.max} spread across the range (raise --max to read more)")
        rows = sampled
    hits = 0
    for r in rows:
        ts, url = r["timestamp"], r["original"]
        try:
            text = page_text(ts, url)
        except Exception as e:
            note(f"{ts} {url}: fetch failed ({e})")
            continue
        found = [text[max(0, m.start() - args.context): m.end() + args.context].replace("\n", " | ")
                 for m in pattern.finditer(text)]
        status = f"{len(found)} match(es)" if found else "no match"
        print(f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts} {url}: {status}")
        for f in found[:args.per_page]:
            print(f"    ...{f}...")
        hits += bool(found)
    note(f"{hits} of {len(rows)} version(s) matched /{args.regex}/")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("captures", help="one row per distinct archived version")
    c.add_argument("url")
    c.add_argument("--from", dest="start", type=int)
    c.add_argument("--to", dest="end", type=int)
    c.add_argument("--match-prefix", action="store_true", help="every page under this path")
    c.add_argument("--limit", type=int)
    c.set_defaults(func=cmd_captures)

    t = sub.add_parser("text", help="visible text of one archived version")
    t.add_argument("timestamp")
    t.add_argument("url")
    t.set_defaults(func=cmd_text)

    d = sub.add_parser("diff", help="unified diff of the visible text of two versions")
    d.add_argument("url")
    d.add_argument("ts1")
    d.add_argument("ts2")
    d.add_argument("--context", type=int, default=2)
    d.set_defaults(func=cmd_diff)

    g = sub.add_parser("grep", help="track a phrase or number across versions")
    g.add_argument("url")
    g.add_argument("regex")
    g.add_argument("--from", dest="start", type=int)
    g.add_argument("--to", dest="end", type=int)
    g.add_argument("--match-prefix", action="store_true")
    g.add_argument("--max", type=int, default=40, help="most versions to fetch")
    g.add_argument("--context", type=int, default=80, help="characters around each match")
    g.add_argument("--per-page", type=int, default=3, help="matches shown per version")
    g.set_defaults(func=cmd_grep)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
