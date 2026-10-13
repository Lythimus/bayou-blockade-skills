"""AirToxScreen 2020: EPA's own modeled cancer risk for the home's census block, by source group.

Context only. AirToxScreen covers one year (2020), every source type at once (industry,
vehicles, background, secondary formation), and is not attributed to named facilities. It is
shown beside the RSEI screening and never added to it.

EPA publishes the block-level results only as large Excel workbooks. The workbook for the
home's region is read by byte range: the string table at its end locates the block, then
the sheet is decompressed as a stream until that block's row appears. Nothing is stored
but the one row.
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import downloads  # noqa: E402

YEAR = 2020
GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
# State FIPS codes held by the Region 6a workbook. Texas is split between 6a and 6b and is
# left out; the skill is scoped to Louisiana homes.
REGION_6A = {"05": "AR", "22": "LA", "35": "NM", "40": "OK"}
SUFFIX = " Cancer Risk (per million)"

LIMITATION = ("AirToxScreen is a screening tool for comparing places, built from the 2020 "
              "emissions inventory. EPA cautions against using it to characterize risk for "
              "an individual or a single census block.")


def block_geoid(lat, lon):
    """2020 census block GEOID for a point, from the Census Bureau's geocoder.

    This sends the coordinates to a federal web service. Callers that must not do that pass
    a block GEOID in by hand instead.
    """
    q = urllib.parse.urlencode({"x": lon, "y": lat, "benchmark": "Public_AR_Current",
                                "vintage": "Census2020_Current", "layers": "10", "format": "json"})
    req = urllib.request.Request(f"{GEOCODER}?{q}", headers=downloads.UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        geos = json.load(r)["result"]["geographies"]
    blocks = next((v for k, v in geos.items() if "Block" in k and v), None)
    return blocks[0]["GEOID"] if blocks else None


def shared_strings(xml_bytes):
    return [html.unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)))
            for si in re.findall(r"<si>(.*?)</si>", xml_bytes.decode("utf-8"), re.S)]


CELL = re.compile(rb'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(?:<v>([^<]*)</v>)?</c>)')


def parse_cells(row_xml, strings):
    """{column letter: value} for one <row>; shared-string cells are resolved to text."""
    out = {}
    for col, attrs, v in CELL.findall(row_xml):
        if not v:
            continue
        out[col.decode()] = strings[int(v)] if b't="s"' in attrs else float(v)
    return out


def find_row(chunks, index, block_col="E"):
    """(header row xml, matching row xml or None) from a sheet's XML given in chunks.

    The block is matched by its shared-string index in the block column, so the 900 MB of
    XML is searched as bytes and never parsed cell by cell.
    """
    pat = re.compile(rb'<c r="%s\d+"[^>]*><v>%d</v></c>' % (block_col.encode(), index))
    header, buf = None, b""
    for chunk in chunks:
        buf += chunk
        if header is None:
            end = buf.find(b"</row>")
            if end < 0:
                continue
            header = buf[buf.find(b"<row "):end]
        m = pat.search(buf)
        if m:
            start = buf.rfind(b"<row ", 0, m.start())
            end = buf.find(b"</row>", m.end())
            if end >= 0:
                return header, buf[start:end]
            # The row straddles this chunk; keep it whole and read on.
            buf = buf[start:]
        else:
            # Longer than any one row, so a row split across chunks is still found.
            buf = buf[-65536:]
    return header, None


def read_block(geoid, url=downloads.AIRTOX_URL, progress=None):
    """AirToxScreen record for one block, or None if the workbook does not list it."""
    remote = downloads.RemoteFile(url)
    z = zipfile.ZipFile(remote)
    strings = shared_strings(z.read("xl/sharedStrings.xml"))
    if geoid not in strings:
        return None
    sheet = z.getinfo("xl/worksheets/sheet1.xml")

    def chunks():
        done = 0
        with z.open(sheet) as f:
            while True:
                chunk = f.read(4 << 20)
                if not chunk:
                    return
                done += len(chunk)
                if progress:
                    progress(done, sheet.file_size)
                yield chunk

    header_xml, row_xml = find_row(chunks(), strings.index(geoid))
    if row_xml is None:
        return None
    return record(parse_cells(header_xml, strings), parse_cells(row_xml, strings), url, remote.fetched)


def record(header, row, url, fetched=0):
    named = {str(header[c]).strip(): row.get(c) for c in header}
    by_source = {k[:-len(SUFFIX)].strip(): v for k, v in named.items()
                 if k.endswith(SUFFIX) and not k.startswith("Total") and v}
    return {"year": YEAR, "block": named.get("Block"), "state": named.get("State"),
            "county": named.get("County"), "population": named.get("Population"),
            "total_per_million": named.get("Total" + SUFFIX),
            "by_source_per_million": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
            "url": url, "bytes_transferred": fetched, "limitation": LIMITATION}
