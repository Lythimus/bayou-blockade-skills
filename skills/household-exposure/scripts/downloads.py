"""Download planning and the large-download gate shared by every fetching subcommand.

Several inputs to this skill run from hundreds of megabytes to tens of gigabytes. Nothing over
THRESHOLD is fetched until the plan has been printed with sizes and free disk space and the
caller has passed --yes. The sizes here are approximate, measured 2026-10-11; they exist to
warn, and fetch code should still trust the server's Content-Length over them.
"""
import shutil
import time
import urllib.error
import urllib.request

THRESHOLD = 100 * 1024 ** 2
GB = 1024 ** 3
MB = 1024 ** 2

RSEI_FIRST, RSEI_LAST = 1988, 2022

# One pinned model version per year: (first year, last year, version, scope, bytes per
# year, URL). EPA reissues every year under each new version and says results from different
# versions cannot be combined, so the choice is fixed here rather than left to whichever
# file is found first. v2.3.8 is skipped: EPA marks part of it as superseded.
_FTP = "https://gaftp.epa.gov/rsei/"
RSEI_SOURCES = [
    (1988, 2014, "v2.3.4", "Louisiana", 1.0 * GB,
     "https://epa-rsei-pds.s3.amazonaws.com/v234/microdata/state/la/v234_micro_state_la_{year}.csv.gz"),
    (2015, 2017, "v2.3.7", "national", 22.0 * GB,
     _FTP + "Older_Versions/Version237_RY2017/Disaggregated_Microdata/micro2017_{year}.csv.gz"),
    (2018, 2019, "v2.3.10", "national", 21.5 * GB,
     _FTP + "Older_Versions/Version2310_RY2020/Disaggregated_Grid_Cell_Microdata/micro2020_{year}.csv.gz"),
    (2020, 2022, "v2.3.12", "national", 22.0 * GB,
     _FTP + "Current_Version/V2312_RY2022/Disaggregated_Grid_Cell/micro2022_{year}.csv.gz"),
]
# EPA's FTP site served about 0.8 MB/s over a whole national year (the S3 bucket, 30 MB/s),
# which sets how long a national year takes far more than its size on disk does.
SLOW_NOTE = "; about 8 hours per year at the 0.8 MB/s EPA's server gave when measured"
# Size assumed for a year whose file nobody has measured, so the total errs high.
RSEI_UNMEASURED = 22.0 * GB

# Chemical, facility and off-site lookup tables. Read out of EPA's release archive by byte
# range, so only these members are transferred, not the 300-430 MB archive.
RSEI_TABLE_BYTES = 15 * MB

# The Region 6a workbook (Arkansas, Louisiana, New Mexico, Oklahoma, part of Texas). It is
# read as a stream up to the home's census block and not kept.
AIRTOX_URL = ("https://gaftp.epa.gov/rtrmodeling_public/AirToxScreen/2020/Cancer/BySource/"
              "Region6a_CancerRisk_by_block_srcgrp.xlsx")
AIRTOX_BYTES = 124 * MB

# TRI basic state-year files. Unlisted states get the Texas figure, the largest seen.
TRI_BYTES = {"LA": 2.4 * MB, "TX": 7.5 * MB, "MS": 2.0 * MB, "AR": 2.0 * MB, "AL": 3.0 * MB}
TRI_FIRST = 1987


def fmt_size(n):
    if n is None:
        return "unmeasured"
    for unit, size in (("GB", GB), ("MB", MB)):
        if n >= size:
            return f"{n / size:,.1f} {unit}"
    return f"{n / 1024:,.0f} KB"


def free_bytes(path):
    return shutil.disk_usage(path).free


def rsei_plan(first, last):
    """One item per calendar year in [first, last]; years RSEI does not cover say so."""
    items = []
    for year in range(first, last + 1):
        src = next((s for s in RSEI_SOURCES if s[0] <= year <= s[1]), None)
        if src is None:
            items.append({"what": f"RSEI {year}", "bytes": 0, "stored": False, "url": None,
                          "note": "outside RSEI microdata coverage; year stays unknown"})
            continue
        _, _, version, scope, size, url = src
        items.append({"what": f"RSEI {year} ({version}, {scope})",
                      "bytes": RSEI_UNMEASURED if size is None else size,
                      "measured": size is not None, "stored": False,
                      "url": url.format(year=year), "version": version, "year": year,
                      "group": f"RSEI {version} ({scope})",
                      "note": "streamed and filtered to the home's grid cells; not kept"
                              + (SLOW_NOTE if scope == "national" else "")})
    return items


def airtox_plan():
    return [{"what": "AirToxScreen 2020, cancer risk by census block (EPA Region 6a)",
             "bytes": AIRTOX_BYTES, "stored": False, "url": AIRTOX_URL,
             "note": "streamed up to the home's block; not kept"}]


def tri_plan(first, last, states, have=()):
    """`have` holds (year, state) pairs already cached."""
    return [{"what": f"TRI {year} {st}", "bytes": TRI_BYTES.get(st, TRI_BYTES["TX"]),
             "stored": True, "url": None, "note": "cached under raw/tri"}
            for year in range(max(first, TRI_FIRST), last + 1) for st in states
            if (year, st) not in have]


def describe(items, dest):
    """Human-readable plan: every item at or over THRESHOLD, plus totals and free space."""
    total = sum(i["bytes"] for i in items)
    stored = sum(i["bytes"] for i in items if i["stored"])
    lines = []
    # Consecutive years from one source read as one line; thirty near-identical lines bury
    # the total.
    groups = []
    for i in items:
        if i["bytes"] < THRESHOLD:
            continue
        key = (i.get("group"), i["bytes"], i["note"])
        if i.get("group") and groups and groups[-1][0] == key:
            groups[-1][1].append(i)
        else:
            groups.append((key, [i]))
    for _, members in groups:
        i = members[0]
        if len(members) == 1:
            head = f"{i['what']}: about {fmt_size(i['bytes'])}"
        else:
            head = (f"{i['group']} {i['year']}-{members[-1]['year']}: {len(members)} files, about "
                    f"{fmt_size(i['bytes'])} each, {fmt_size(i['bytes'] * len(members))} in all")
        lines.append(f"  {head}" + ("" if i.get("measured", True) else " (unmeasured; assumed)")
                     + f" - {i['note']}")
    small = [i for i in items if 0 < i["bytes"] < THRESHOLD]
    if small:
        lines.append(f"  {len(small)} smaller file(s): about {fmt_size(sum(i['bytes'] for i in small))}")
    uncovered = [i for i in items if not i["bytes"]]
    for note in dict.fromkeys(i["note"] for i in uncovered):
        whats = [i["what"] for i in uncovered if i["note"] == note]
        lines.append(f"  {whats[0]}" + (f" to {whats[-1]}" if len(whats) > 1 else "") + f": {note}")
    lines.append(f"  total transfer: about {fmt_size(total)}; kept on disk: about {fmt_size(stored)}")
    lines.append(f"  free disk at {dest}: {fmt_size(free_bytes(dest))}")
    return "\n".join(lines)


def gate(items, dest, yes, label):
    """True when the fetch may start. Prints the plan whenever it is refused or large.

    Refuses without --yes when the total transfer reaches THRESHOLD, and refuses regardless
    of --yes when what would be kept does not fit on the disk.
    """
    total = sum(i["bytes"] for i in items)
    stored = sum(i["bytes"] for i in items if i["stored"])
    if total < THRESHOLD:
        return True
    print(f"{label}: large download\n{describe(items, dest)}")
    if stored >= free_bytes(dest):
        print("Not enough free disk space for the files that would be kept. Nothing fetched.")
        return False
    if not yes:
        print("Nothing fetched. Confirm with the user, then rerun with --yes.")
        return False
    return True


# ------------------------------------------------------------ transfer plumbing

UA = {"User-Agent": "bayou-household-exposure"}
CHUNK = 1 << 20


def stream(url, start=0, retries=8, progress=None):
    """Yield a URL's bytes from `start`, reconnecting at the byte reached if the link drops.

    A national RSEI year is over 20 GB and takes long enough that one dropped connection is
    likely; restarting from zero each time would never finish.
    """
    pos, fails, total = start, 0, 0
    while True:
        req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={pos}-"} if pos else UA)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if pos and r.status != 206:
                    raise OSError("server ignored the byte range; cannot resume")
                total = pos + int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    pos += len(chunk)
                    fails = 0
                    if progress:
                        progress(pos, total)
                    yield chunk
            if not total or pos >= total:
                return
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError):
            pass
        fails += 1
        if fails > retries:
            raise OSError(f"gave up on {url} at byte {pos:,} after {retries} retries")
        time.sleep(min(60, 2 ** fails))


class RemoteFile:
    """Seekable read-only view of a URL through byte ranges, enough for `zipfile`.

    Lets one member be read out of a large remote archive without transferring the rest.
    """

    WINDOW = 4 << 20

    def __init__(self, url):
        self.url, self.pos, self.cache, self.fetched = url, 0, None, 0
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status != 206:
                raise OSError(f"{url}: server does not honor byte ranges")
            self.size = int(r.headers["Content-Range"].rsplit("/", 1)[1])

    def seekable(self):
        return True

    def readable(self):
        return True

    def close(self):
        pass

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        c = self.cache
        if not c or not (c[0] <= self.pos and self.pos + n <= c[0] + len(c[1])):
            # Near the end of the file, back the window up so the zip directory and the
            # small members beside it arrive in one request.
            start = self.pos if n > self.WINDOW else max(0, min(self.pos, self.size - self.WINDOW))
            end = min(max(start + self.WINDOW, self.pos + n), self.size) - 1
            data = b"".join(_range(self.url, start, end))
            self.fetched += len(data)
            c = self.cache = (start, data)
        o = self.pos - c[0]
        data = c[1][o:o + n]
        self.pos += len(data)
        return data


def _range(url, start, end):
    req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return [r.read()]
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
