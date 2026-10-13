"""RSEI Geographic Microdata: modeled air concentration at one grid cell, by facility and chemical.

EPA's disaggregated microdata hold one row per TRI release per 810 m grid cell. Finding one
home's cell means reading a whole year file (1 GB for a Louisiana year through 2014, about
22 GB for a national year after), so a year is read as a stream, only the rows for the
home's cell and its eight neighbors are kept, and those few kilobytes are cached. The file
itself is never stored. Sources, layouts and limits: references/data-sources.md.
"""
import csv
import gzip
import io
import itertools
import math
import os
import re
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import downloads  # noqa: E402

GRID_CONUS = 14
CELL_M = 810.0
# For these media the microdata's FacilityNumber is a row of the off-site table (the
# incinerator or treatment works that received the waste), not of the facility table.
OFFSITE_MEDIA = {6, 750, 754}

TABLE_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "bayou", "rsei")
_S3 = "https://epa-rsei-pds.s3.amazonaws.com/v234/data_tables/"
_FTP = "https://gaftp.epa.gov/rsei/"
# Lookup tables must come from the same model version as the microdata: chemical numbers
# are regrouped between versions (346 is "lead and lead compounds" in one, "lead" in another).
TABLE_SOURCES = {
    "v2.3.4": {"chemical": _S3 + "chemical.csv", "facility": _S3 + "facility.csv.gz",
               "offsite": _S3 + "offsite.csv.gz"},
    "v2.3.7": {"zip": _FTP + "Older_Versions/Version237_RY2017/Public_Release_Data/"
                      "RSEIv237_Public_Release_Data.zip"},
    "v2.3.10": {"zip": _FTP + "Older_Versions/Version2310_RY2020/Public_Release_Data/"
                       "RSEIv2310_Public_Release_Data.zip"},
    "v2.3.12": {"zip": _FTP + "Current_Version/V2312_RY2022/Public_Release_Data/"
                       "RSEIv2312_Public_Release_Data.zip"},
}
TABLE_COLUMNS = {
    "chemical": ("ChemicalNumber", "CASNumber", "CASStandard", "Chemical"),
    "facility": ("FacilityNumber", "FacilityID", "FRSID", "FacilityName", "City", "State",
                 "Latitude", "Longitude"),
    "offsite": ("FacilityNumber", "OffsiteID", "Name", "City", "State", "Latitude", "Longitude"),
}

LIMITATION = ("RSEI microdata \"cannot solely be used to determine actual on-the-ground "
              "exposures or health risks at any given point\" (EPA). The figures are modeled "
              "from releases facilities reported to TRI, on an 810 m grid, with generic stack "
              "assumptions where facility data were missing.")


# ------------------------------------------------------------ grid

def albers(lat, lon):
    """Metres in the grid's projection: Albers equal-area conic, GRS80, standard parallels
    29.5 and 45.5, origin 23 N 96 W. Reproduces the grid cell of every one of the 58,022
    conterminous facilities in EPA's v2.3.4 facility table."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = 2 * f - f * f
    e = math.sqrt(e2)

    def q(p):
        s = math.sin(p)
        return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))

    def m(p):
        return math.cos(p) / math.sqrt(1 - e2 * math.sin(p) ** 2)

    p1, p2, p0, p = (math.radians(v) for v in (29.5, 45.5, 23.0, lat))
    n = (m(p1) ** 2 - m(p2) ** 2) / (q(p2) - q(p1))
    c = m(p1) ** 2 + n * q(p1)
    rho, rho0 = a * math.sqrt(c - n * q(p)) / n, a * math.sqrt(c - n * q(p0)) / n
    th = n * math.radians(lon + 96.0)
    return rho * math.sin(th), rho0 - rho * math.cos(th)


def cell(lat, lon):
    """(X, Y) of the conterminous-US grid cell holding the point. Cells are centered on
    multiples of 810 m, so the index is the nearest multiple, not the floor."""
    if not (24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0):
        raise ValueError("only the conterminous-US RSEI grid is supported")
    x, y = albers(lat, lon)
    return round(x / CELL_M), round(y / CELL_M)


def neighborhood(xy):
    """The cell and its eight neighbors. The neighbors give the spread across roughly
    2.4 km, a guard against reading too much into which side of a cell edge a home is."""
    x, y = xy
    return [(x + dx, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


# ------------------------------------------------------------ microdata scan

def layout(first_line):
    """(has header row, has leading year column) from a file's first line.

    Through v2.3.11 the files have 13 columns and no header, with the year only in the file
    name. v2.3.12 adds a header and a leading year column.
    """
    fields = first_line.strip().split(b",")
    header = not fields[0].strip(b'"').lstrip(b"-").isdigit()
    if len(fields) not in (13, 14):
        raise ValueError(f"unrecognized microdata layout: {len(fields)} columns")
    return header, len(fields) == 14


def parse_row(line, has_year):
    f = line.split(b",")
    if has_year:
        f = f[1:]
    return {"x": int(f[1]), "y": int(f[2]), "release": int(f[3]), "chemical": f[4].decode(),
            "number": f[5].decode(), "media": int(f[6]), "conc": float(f[7]), "toxconc": float(f[8])}


def scan(chunks, cells, year):
    """Rows for `cells` from decompressed microdata, given as an iterable of byte chunks."""
    rows, tail, pat, has_year = [], b"\n", None, False
    # The closing newline makes a final line with no terminator complete like the rest.
    for chunk in itertools.chain(chunks, [b"\n"]):
        buf = tail + chunk
        cut = buf.rfind(b"\n")
        if cut <= 0:
            tail = buf
            continue
        if pat is None:
            _, has_year = layout(buf[1:buf.index(b"\n", 1)])
            lead = f"{year}," if has_year else ""
            pairs = "|".join(f"{x},{y}" for x, y in cells)
            # The literal prefix lets the regex engine skip from line to line; a header line
            # can never match it.
            pat = re.compile(f"\n{lead}{GRID_CONUS},(?:{pairs}),[^\n]*".encode())
        # Only complete lines are searched; the unfinished last line waits for more data.
        for m in pat.finditer(buf, 0, cut):
            rows.append(parse_row(m.group(0)[1:], has_year))
        tail = buf[cut:]
    return rows


def gunzip(chunks):
    d, fresh = zlib.decompressobj(31), True
    for chunk in chunks:
        while chunk:
            out = d.decompress(chunk)
            fresh = False
            if out:
                yield out
            if not d.eof:
                break
            # A gzip file may be several members laid end to end.
            chunk, d, fresh = d.unused_data, zlib.decompressobj(31), True
    # A dropped transfer must not pass for a short year: its missing rows would read as
    # facilities that did not report.
    if not fresh:
        raise OSError("compressed stream ended early")


def local_chunks(path):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(downloads.CHUNK)
            if not chunk:
                return
            yield chunk


CACHE_FIELDS = ("x", "y", "release", "chemical", "number", "media", "conc", "toxconc")


def cache_path(raw, item, xy):
    # The cell is in the name so a changed home location cannot reuse another cell's rows.
    return os.path.join(raw, f"{item['version']}_{item['year']}_{xy[0]}_{xy[1]}.csv")


def load_cached(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{"x": int(r["x"]), "y": int(r["y"]), "release": int(r["release"]),
                 "chemical": r["chemical"], "number": r["number"], "media": int(r["media"]),
                 "conc": float(r["conc"]), "toxconc": float(r["toxconc"])} for r in csv.DictReader(f)]


def fetch_year(item, xy, raw, local_dir=None, progress=None):
    """Rows for one year at the home's neighborhood, from the cache or a full stream.

    The cache file is written only after the whole stream has been read, so its existence
    means the year is complete; an empty one means the year was read and held no rows.
    """
    path = cache_path(raw, item, xy)
    if os.path.exists(path):
        return load_cached(path)
    local = os.path.join(local_dir, os.path.basename(item["url"])) if local_dir else None
    src = local_chunks(local) if local and os.path.exists(local) else downloads.stream(item["url"], progress=progress)
    rows = scan(gunzip(src), neighborhood(xy), item["year"])
    os.makedirs(raw, exist_ok=True)
    with open(path + ".part", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(path + ".part", path)
    return rows


def have_year(item, xy, raw, local_dir=None):
    return os.path.exists(cache_path(raw, item, xy)) or bool(
        local_dir and os.path.exists(os.path.join(local_dir, os.path.basename(item["url"]))))


# ------------------------------------------------------------ lookup tables

def _trim(text_stream, kind, dest):
    reader = csv.DictReader(text_stream)
    cols = [c for c in TABLE_COLUMNS[kind] if c in (reader.fieldnames or [])]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest + ".part", "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in reader:
            w.writerow(r)
    os.replace(dest + ".part", dest)


def _text(raw_bytes):
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")


def tables_cached(version, cache=TABLE_CACHE):
    return all(os.path.exists(os.path.join(cache, version, k + ".csv")) for k in TABLE_COLUMNS)


def fetch_tables(version, cache=TABLE_CACHE):
    """Download one version's chemical, facility and off-site tables, trimmed to the columns
    used. They hold no household data, so they are cached per user, outside any assessment."""
    src = TABLE_SOURCES[version]
    z = zipfile.ZipFile(downloads.RemoteFile(src["zip"])) if "zip" in src else None
    for kind in TABLE_COLUMNS:
        dest = os.path.join(cache, version, kind + ".csv")
        if os.path.exists(dest):
            continue
        if z:
            names = [n for n in z.namelist() if os.path.basename(n).lower().startswith(kind + "_")]
            if not names:
                raise OSError(f"{src['zip']}: no {kind} table found")
            # Member names vary by version (offsite_data_..., offsite_rsei_...), and one
            # version ships a second, longer-named copy of the facility table.
            data = z.read(min(names, key=len))
        else:
            data = b"".join(downloads.stream(src[kind]))
            if src[kind].endswith(".gz"):
                data = gzip.decompress(data)
        _trim(io.StringIO(_text(data), newline=""), kind, dest)


def _float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_tables(version, cache=TABLE_CACHE):
    """{"chemical": {number: {...}}, "facility": {...}, "offsite": {...}} for one version."""
    out = {}
    for kind in TABLE_COLUMNS:
        with open(os.path.join(cache, version, kind + ".csv"), newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if kind == "chemical":
            out[kind] = {r["ChemicalNumber"]: {"id": r["CASNumber"].strip(), "name": r["Chemical"].strip()}
                         for r in rows}
        elif kind == "facility":
            out[kind] = {}
            for r in rows:
                out[kind][r["FacilityNumber"]] = {
                    "trifid": r["FacilityID"].strip(), "frs_id": (r.get("FRSID") or "").strip(),
                    "name": r["FacilityName"].strip(), "city": r.get("City", "").strip(),
                    "state": r.get("State", "").strip(), "lat": _float(r["Latitude"]),
                    "lon": _float(r["Longitude"])}
        else:
            out[kind] = {(r.get("FacilityNumber") or r.get("OffsiteID") or "").strip(): {
                "name": (r.get("Name") or "").strip(), "city": (r.get("City") or "").strip(),
                "state": (r.get("State") or "").strip(), "lat": _float(r.get("Latitude")),
                "lon": _float(r.get("Longitude"))} for r in rows}
    return out


# ------------------------------------------------------------ rows -> annual values

def annual(rows, xy):
    """{(source kind, number, chemical number): {"conc", "lo", "hi", "toxconc"}} for one year.

    A facility's fugitive and stack releases of one chemical are separate rows and are
    summed. lo and hi are the lowest and highest of the nine neighborhood cells.
    """
    cells = {}
    for r in rows:
        kind = "offsite" if r["media"] in OFFSITE_MEDIA else "facility"
        key = (kind, r["number"], r["chemical"])
        c = cells.setdefault(key, {})
        at = c.setdefault((r["x"], r["y"]), [0.0, 0.0])
        at[0] += r["conc"]
        at[1] += r["toxconc"]
    out = {}
    for key, c in cells.items():
        # A neighbor with no row is past the edge of what RSEI modeled for that release,
        # which is a concentration it treats as zero.
        vals = [c.get(n, [0.0, 0.0])[0] for n in neighborhood(xy)]
        home = c.get(tuple(xy), [0.0, 0.0])
        out[key] = {"conc": home[0], "toxconc": home[1], "lo": min(vals), "hi": max(vals)}
    return out
