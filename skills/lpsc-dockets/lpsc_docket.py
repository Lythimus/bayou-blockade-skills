#!/usr/bin/env python3
"""LPSC docket filings: list, download and grep, with no browser and no session cookie.

The DocketDetails page renders its Documents grid client-side, but the grid's data
endpoint answers a plain POST, and ViewFile serves the PDFs directly.

  lpsc_docket.py info 32689                       # docket number, dates, synopsis, parties
  lpsc_docket.py docs 32689 [--grep REGEX] [--public]   # one row per filing, with its files
  lpsc_docket.py download 32689 --out DIR [--match REGEX] [--public] [--yes]
  lpsc_docket.py grep DIR REGEX [REGEX ...]        # pdftotext each PDF once, print hits by file

`--public` drops files whose names say confidential, under seal or highly sensitive.
`download` refuses more than 25 files or 100 MB without --yes; filings with exhibits run
to tens of MB each, so narrow with --match first. Stdlib, plus pdftotext for `grep`.
"""
import argparse, datetime as dt, glob, html, json, os, re, subprocess, sys, time
import urllib.parse, urllib.request

BASE = "https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC"
UA = {"User-Agent": "Mozilla/5.0 (bayou-lpsc-dockets)"}
SEALED = re.compile(r"confidential|under seal|highly sensitive|HSPM", re.I)


def http(url, data=None, headers=None):
    h = dict(UA, **(headers or {}))
    if data is not None:
        data = urllib.parse.urlencode(data).encode()
        h.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                  "X-Requested-With": "XMLHttpRequest"})
    return urllib.request.urlopen(urllib.request.Request(url, data, h), timeout=120).read()


def documents(docket_id):
    raw = http(f"{BASE}/Docket_Documents", {"docketId": docket_id, "sort": "", "page": 1,
                                            "pageSize": 2000, "group": "", "filter": ""})
    if not raw.lstrip().startswith(b"{"):
        sys.exit("Docket_Documents did not return JSON; the endpoint or its parameters changed")
    d = json.loads(raw)
    rows = d.get("Data") or []
    if d.get("Total", len(rows)) != len(rows):
        print(f"warning: {d.get('Total')} filings reported, {len(rows)} returned", file=sys.stderr)
    for r in rows:
        m = re.search(r"/Date\((-?\d+)\)/", str(r.get("DateFiled")))
        r["date"] = dt.datetime.fromtimestamp(int(m.group(1)) / 1000, dt.timezone.utc).date().isoformat() if m else "?"
    return sorted(rows, key=lambda r: r["date"])


def files(rows, public=False, match=None):
    rx = re.compile(match, re.I) if match else None
    for r in rows:
        for f in r.get("Files") or []:
            if public and SEALED.search(f["FileName"]):
                continue
            if rx and not rx.search(f"{r.get('Description','')} {f['FileName']}"):
                continue
            yield r, f


def cmd_info(a):
    t = http(f"{BASE}/DocketDetails?docketId={a.docket_id}").decode("utf-8", "replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    keys = ["Docket Number", "Date Opened", "Status", "Date Published", "Description", "Synopsis",
            "Companies Involved"]
    seen = set()
    for i, l in enumerate(lines):
        # The grid headers further down reuse "Description"; keep the first block only.
        if l in keys and l not in seen and i + 1 < len(lines):
            seen.add(l)
            print(f"{l}: {' '.join(lines[i+1].split())}")


def cmd_docs(a):
    rows = documents(a.docket_id)
    rx = re.compile(a.grep, re.I) if a.grep else None
    n = 0
    for r in rows:
        fl = [f for f in r.get("Files") or [] if not (a.public and SEALED.search(f["FileName"]))]
        text = f"{r.get('Description','')} {' '.join(f['FileName'] for f in fl)}"
        if rx and not rx.search(text):
            continue
        n += 1
        print(f"{r['date']}  {r.get('DocumentType','')}: {r.get('Description','')}")
        for f in fl:
            print(f"    {f['FileSize']/1e6:6.1f} MB  {f['FileName']}  fileId={f['FileId']}")
    print(f"-- {n} of {len(rows)} filings. File URL: {BASE}/ViewFile?fileId=<fileId, URL-encoded>")


def cmd_download(a):
    picks = list(files(documents(a.docket_id), a.public, a.match))
    mb = sum(f["FileSize"] for _, f in picks) / 1e6
    print(f"{len(picks)} files, {mb:.1f} MB")
    if (len(picks) > 25 or mb > 100) and not a.yes:
        print("over 25 files or 100 MB: narrow with --match, or rerun with --yes", file=sys.stderr)
        sys.exit(3)
    os.makedirs(a.out, exist_ok=True)
    for r, f in picks:
        name = re.sub(r"[^\w.() -]+", "_", f"{r['date']} {f['FileName']}")[:180]
        path = os.path.join(a.out, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        data = http(f"{BASE}/ViewFile?fileId={urllib.parse.quote(f['FileId'], safe='')}")
        if not data.startswith(b"%PDF") and name.lower().endswith(".pdf"):
            print(f"  not a PDF, skipped: {name}", file=sys.stderr)
            continue
        open(path, "wb").write(data)
        print(f"  {len(data)/1e6:5.1f} MB  {name}")
        time.sleep(1)


def cmd_grep(a):
    rx = re.compile("|".join(a.patterns), re.I)
    for pdf in sorted(glob.glob(os.path.join(a.dir, "*.pdf"))):
        txt = pdf[:-4] + ".txt"
        if not os.path.exists(txt):
            subprocess.run(["pdftotext", "-layout", pdf, txt], stderr=subprocess.DEVNULL)
        if not os.path.exists(txt):
            continue
        body = open(txt, errors="replace").read()
        pages = body.split("\f")
        hits = [(i + 1, l) for i, p in enumerate(pages) for l in p.splitlines() if rx.search(l)]
        if len(body.strip()) < 200:
            print(f"## {os.path.basename(pdf)}: no text layer (scanned); OCR before relying on a miss")
        elif hits:
            print(f"## {os.path.basename(pdf)}: {len(hits)} hits")
            for pg, l in hits[:a.max]:
                print(f"   p{pg}: {' '.join(l.split())[:180]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("info"); p.add_argument("docket_id")
    p = sp.add_parser("docs"); p.add_argument("docket_id"); p.add_argument("--grep"); p.add_argument("--public", action="store_true")
    p = sp.add_parser("download"); p.add_argument("docket_id"); p.add_argument("--out", required=True)
    p.add_argument("--match"); p.add_argument("--public", action="store_true"); p.add_argument("--yes", action="store_true")
    p = sp.add_parser("grep"); p.add_argument("dir"); p.add_argument("patterns", nargs="+"); p.add_argument("--max", type=int, default=15)
    a = ap.parse_args()
    {"info": cmd_info, "docs": cmd_docs, "download": cmd_download, "grep": cmd_grep}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
