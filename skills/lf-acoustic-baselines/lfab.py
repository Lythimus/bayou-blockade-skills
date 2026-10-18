#!/usr/bin/env python3
"""Public low-frequency acoustic and seismic baselines: EarthScope (IRIS) infrasound, barometer and
seismometer archives, MUSTANG PSDs, and USGS ComCat events. Retrieval and spectra only — no source
attribution.

Run with: uv run -q --no-project --with obspy --with numpy --with scipy python -I lfab.py <command> ...
Cache: ~/.cache/bayou/lf-acoustic-baselines/ (station inventory 1 day; archived waveforms and PSDs kept).

  lfab.py health                                          station, dataselect, MUSTANG, ComCat up
  lfab.py stations <lat> <lon> [--radius-km 100]          infrasound/barometer/seismic channels, epochs
  lfab.py psd <NET.STA.LOC.CHA> --start D [--end D] [--days N] [--hours 00-04]
  lfab.py compare <NSLC> --before A..B --after C..D [--band 1-20]
  lfab.py coherence <NET.STA> --start D [--end D] [--days N] [--hours 00-04]   BDF<->Z coherence
  lfab.py events <lat> <lon> --start D --end D [--radius-km 150]              ComCat, all event types
"""
import argparse
import datetime
import hashlib
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE = os.path.expanduser("~/.cache/bayou/lf-acoustic-baselines")
TTL = 24 * 3600
UA = "Mozilla/5.0 (bayou-lf-acoustic-baselines)"
FDSN = "https://service.earthscope.org/fdsnws/"
MUSTANG = "https://service.earthscope.org/mustang/noise-psd/1/query"
COMCAT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
INFRA = ("BDF", "HDF", "LDF")
BARO = ("BDO", "LDO")
SEIS = ("BHZ", "HHZ", "EHZ", "SHZ")
CHANNELS = INFRA + BARO + SEIS
# From a 60 s N4.545B.EP.BDF pull: 8192 bytes for 2400 samples. Steim compression varies with
# signal, so this is an estimate, not a quote.
BYTES_PER_SAMPLE = 3.5
GATE_MB = 50
SEG_S = 100        # Welch segment: 0.01 Hz resolution, enough to separate microbaroms and tonals
CHUNK_S = 3600     # one spectrum per hour, matching MUSTANG's hourly PSDs
LOCAL_TZ = "America/Chicago"
UNITS = {"pressure": "dB re 1 Pa²/Hz", "seismic": "dB re 1 (m/s²)²/Hz"}


class SourceDown(Exception):
    pass


class NoData(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def note(msg):
    print(msg, file=sys.stderr)


def today():
    return datetime.date.today().isoformat()


def kind_of(cha):
    return "pressure" if cha in INFRA or cha in BARO else "seismic"


# ---------------------------------------------------------------- HTTP

def _get(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # FDSN services answer 204 when the query is valid but nothing matches.
            if r.status == 204:
                raise NoData(url)
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (204, 404):
            raise NoData(url)
        raise SourceDown("%s: HTTP %s" % (url, e.code))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceDown("%s: %s" % (url, e))


def cached(url, ext, ttl=None, refresh=False):
    """Body of url, cached. ttl=None keeps the file forever (archived data does not change)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:24] + "." + ext)
    nodata = path + ".nodata"
    fresh = lambda p: os.path.exists(p) and (ttl is None or time.time() - os.path.getmtime(p) < ttl)
    if not refresh:
        if fresh(path):
            with open(path, "rb") as fh:
                return fh.read()
        if fresh(nodata):
            raise NoData(url)
    try:
        body = _get(url)
    except NoData:
        open(nodata, "w").close()
        raise
    with open(path, "wb") as fh:
        fh.write(body)
    return body


def is_cached(url, ext):
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:24] + "." + ext)
    return os.path.exists(path) or os.path.exists(path + ".nodata")


def q(base, **kw):
    return base + "?" + urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


# ---------------------------------------------------------------- geometry and time

def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def parse_day(s):
    s = s.strip()
    if len(s) == 7:
        s += "-01"
    return datetime.date.fromisoformat(s)


def parse_span(s):
    """'A..B' with YYYY-MM or YYYY-MM-DD ends; a YYYY-MM end means through the end of that month."""
    a, sep, b = s.partition("..")
    if not sep:
        die("expected A..B, got %r" % s)
    lo = parse_day(a)
    hi = parse_day(b)
    if len(b.strip()) == 7:
        hi = (hi.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    return lo, hi


def sample_days(start, end, n):
    """n days spread evenly across [start, end], or n consecutive days from start when end is None."""
    if end is None:
        return [start + datetime.timedelta(days=i) for i in range(n)]
    span = (end - start).days
    if span < 0:
        die("--end is before --start")
    if span + 1 <= n:
        return [start + datetime.timedelta(days=i) for i in range(span + 1)]
    step = span / (n - 1) if n > 1 else 0
    return sorted({start + datetime.timedelta(days=round(i * step)) for i in range(n)})


def windows(days, hours, utc):
    """UTC (t0, t1) per day for the hour range; '22-02' wraps past midnight."""
    h0, h1 = (int(x) for x in hours.split("-"))
    if not utc:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(LOCAL_TZ)
    out = []
    for d in days:
        t0 = datetime.datetime(d.year, d.month, d.day, h0)
        t1 = datetime.datetime(d.year, d.month, d.day, 0) + datetime.timedelta(hours=h1 + (24 if h1 <= h0 else 0))
        if not utc:
            t0 = t0.replace(tzinfo=tz).astimezone(datetime.timezone.utc).replace(tzinfo=None)
            t1 = t1.replace(tzinfo=tz).astimezone(datetime.timezone.utc).replace(tzinfo=None)
        out.append((t0, t1))
    return out


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- station inventory

def split_nslc(s):
    parts = s.split(".")
    if len(parts) != 4:
        die("expected NET.STA.LOC.CHA (empty location as NET.STA..CHA), got %r" % s)
    net, sta, loc, cha = parts
    return net.upper(), sta.upper(), ("" if loc in ("", "--") else loc.upper()), cha.upper()


def channel_rows(refresh=False, **kw):
    url = q(FDSN + "station/1/query", level="channel", format="text", **kw)
    try:
        body = cached(url, "txt", TTL, refresh)
    except NoData:
        return [], url
    rows = []
    for line in body.decode("utf-8", "replace").splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        rows.append({"net": f[0], "sta": f[1], "loc": f[2], "cha": f[3], "lat": float(f[4]), "lon": float(f[5]),
                     "elev": float(f[6] or 0), "sensor": f[10], "units": f[13], "sps": float(f[14] or 0),
                     "start": f[15][:10], "end": (f[16][:10] if f[16] else None)})
    return rows, url


def epochs_for(net, sta, loc, cha, t0, t1, refresh=False):
    rows, _ = channel_rows(refresh, net=net, sta=sta, loc=loc or "--", cha=cha,
                           starttime=iso(t0), endtime=iso(t1))
    return rows


def inventory(net, sta, loc, cha, t0, t1, refresh=False):
    from obspy import read_inventory
    url = q(FDSN + "station/1/query", net=net, sta=sta, loc=loc or "--", cha=cha, level="response",
            format="xml", starttime=iso(t0), endtime=iso(t1))
    try:
        body = cached(url, "xml", None, refresh)
    except NoData:
        raise NoData("no response metadata for %s.%s.%s.%s %s..%s" % (net, sta, loc, cha, iso(t0), iso(t1)))
    return read_inventory(io.BytesIO(body))


def cmd_stations(a):
    deg = a.radius_km / 111.195
    rows, url = channel_rows(a.refresh, latitude=a.lat, longitude=a.lon, maxradius="%.4f" % deg,
                             channel=",".join(CHANNELS), starttime=a.since, endtime=a.until)
    if not rows:
        die("No %s channels within %g km of %.4f, %.4f%s." % (",".join(CHANNELS), a.radius_km, a.lat, a.lon,
                                                            " in that date range" if a.since or a.until else ""), 3)
    by = {}
    for r in rows:
        by.setdefault((r["net"], r["sta"]), []).append(r)
    end_of = lambda c: c["end"] or "9999-12-31"
    stations = []
    for (net, sta), raw in by.items():
        lat, lon = raw[0]["lat"], raw[0]["lon"]
        # Metadata revisions split one unchanged instrument into several epochs; merge those back.
        chans = []
        for r in sorted(raw, key=lambda r: (r["cha"], r["loc"], r["start"])):
            p = chans[-1] if chans else None
            if p and (p["cha"], p["loc"], p["sensor"], p["sps"]) == (r["cha"], r["loc"], r["sensor"], r["sps"]) \
                    and r["start"] <= end_of(p):
                p["end"] = None if not r["end"] or not p["end"] else max(p["end"], r["end"])
                continue
            chans.append(dict(r))
        flags = []
        # A location-code or sensor change splits a record into instruments that must not be compared blind.
        # Codes that start together (LDO 30 and 31) are parallel channels, not a change.
        for cha in sorted({c["cha"] for c in chans}):
            eps = sorted((c for c in chans if c["cha"] == cha), key=lambda c: c["start"])
            for p, n in zip(eps, eps[1:]):
                if n["start"] <= p["start"] or end_of(n) <= end_of(p):
                    continue
                if p["loc"] != n["loc"]:
                    flags.append("%s location code %r -> %r at %s" % (cha, p["loc"], n["loc"], n["start"]))
                if p["sensor"] != n["sensor"]:
                    flags.append("%s sensor %r -> %r at %s" % (cha, p["sensor"], n["sensor"], n["start"]))
        coloc = []
        for i in (c for c in chans if c["cha"] in ("BDF", "HDF")):
            for s in (c for c in chans if c["cha"] in SEIS):
                lo, hi = max(i["start"], s["start"]), min(end_of(i), end_of(s))
                if lo < hi:
                    coloc.append({"infra": "%s.%s" % (i["loc"] or "--", i["cha"]),
                                  "seismic": "%s.%s" % (s["loc"] or "--", s["cha"]),
                                  "from": lo, "to": None if hi == "9999-12-31" else hi})
        stations.append({"net": net, "sta": sta, "lat": lat, "lon": lon,
                         "km": round(haversine_km(a.lat, a.lon, lat, lon), 1),
                         "bearing": round(bearing(a.lat, a.lon, lat, lon)),
                         "channels": [{"nslc": "%s.%s.%s.%s" % (net, sta, c["loc"], c["cha"]), "kind":
                                       "infrasound" if c["cha"] in INFRA else "barometer" if c["cha"] in BARO
                                       else "seismic", "sps": c["sps"], "nyquist": c["sps"] / 2,
                                       "sensor": c["sensor"], "units": c["units"], "start": c["start"],
                                       "end": c["end"]} for c in chans],
                         "flags": flags, "colocated": coloc})
    stations.sort(key=lambda s: s["km"])
    return {"center": [a.lat, a.lon], "radius_km": a.radius_km, "stations": stations, "source": url,
            "retrieved": today()}


# ---------------------------------------------------------------- spectra

def est_bytes(sps, seconds):
    return sps * seconds * BYTES_PER_SAMPLE


def dataselect_url(net, sta, loc, cha, t0, t1):
    return q(FDSN + "dataselect/1/query", net=net, sta=sta, loc=loc or "--", cha=cha,
             starttime=iso(t0), endtime=iso(t1), nodata=404)


_approved_mb = 0.0


def gate(plan, yes):
    """plan: list of (url, sps, seconds). Prints the estimate; refuses above GATE_MB without --yes.
    The total accumulates across calls, so a command that fetches in two batches (compare's before
    and after) cannot pass 2 x GATE_MB unasked."""
    global _approved_mb
    todo = [(u, sps, s) for u, sps, s in plan if not is_cached(u, "mseed")]
    mb = sum(est_bytes(sps, s) for _, sps, s in todo) / 1e6
    if todo:
        note("miniSEED: %d of %d windows not cached, about %.0f MB to download (estimate)." % (len(todo), len(plan), mb))
    if _approved_mb + mb > GATE_MB and not yes:
        die("Refusing a %.0f MB download without --yes. Narrow --hours or --days, or pass --yes."
            % (_approved_mb + mb), 4)
    _approved_mb += mb


def mseed_plan(nslc, wins, refresh=False):
    net, sta, loc, cha = nslc
    eps = epochs_for(net, sta, loc, cha, wins[0][0], wins[-1][1], refresh)
    if not eps:
        raise NoData("%s has no epoch in %s..%s" % (".".join(nslc), iso(wins[0][0]), iso(wins[-1][1])))
    rate = max(e["sps"] for e in eps)
    return [(dataselect_url(net, sta, loc, cha, t0, t1), rate, (t1 - t0).total_seconds()) for t0, t1 in wins]


def welch_db(x, sps):
    import numpy as np
    from scipy.signal import welch
    f, p = welch(x, fs=sps, window="hann", nperseg=int(SEG_S * sps), noverlap=int(SEG_S * sps) // 2,
                 detrend="linear")
    with np.errstate(divide="ignore"):
        return f, 10 * np.log10(p)


def mseed_chunks(net, sta, loc, cha, t0, t1, refresh=False):
    """Response-corrected, gap-free hourly chunks as (hour index from t0, numpy array), the sample rate,
    and sensor descriptions. Chunks sit on a fixed grid from t0 so two channels pair by index."""
    from obspy import UTCDateTime, read
    try:
        body = cached(dataselect_url(net, sta, loc, cha, t0, t1), "mseed", None, refresh)
    except NoData:
        return [], None, None
    st = read(io.BytesIO(body))
    st.merge(method=1, fill_value=None)
    st = st.split()
    if not len(st):
        return [], None, None
    inv = inventory(net, sta, loc, cha, t0, t1, refresh)
    sps = st[0].stats.sampling_rate
    nyq = sps / 2
    out = []
    base = UTCDateTime(iso(t0))
    n = int(CHUNK_S * sps)
    for tr in st:
        if tr.stats.npts < n:
            continue
        tr.detrend("linear")
        # Pre-filter keeps deconvolution from amplifying noise at the band edges.
        tr.remove_response(inventory=inv, output="DEF" if kind_of(cha) == "pressure" else "ACC",
                           pre_filt=(0.005, 0.01, 0.85 * nyq, 0.95 * nyq), water_level=None)
        # Archived records start and end a few samples off the hour, so allow 1 s slack at each edge.
        k = max(0, math.ceil((tr.stats.starttime - base - 1.0) / CHUNK_S))
        while base + (k + 1) * CHUNK_S <= tr.stats.endtime + 1.0:
            i = max(0, int(round((base + k * CHUNK_S - tr.stats.starttime) * sps)))
            seg = tr.data[i:i + n]
            if len(seg) >= n - sps:
                out.append((k, seg))
            k += 1
    sensors = sorted({c.sensor.description for n_ in inv for s in n_ for c in s if c.sensor})
    return out, sps, sensors


def mustang_blocks(net, sta, loc, cha, t0, t1, refresh=False):
    """MUSTANG hourly PSDs whose hour lies inside [t0, t1]: list of (freqs, dB)."""
    url = q(MUSTANG, target="%s.%s.%s.%s.*" % (net, sta, loc, cha), starttime=iso(t0), endtime=iso(t1),
            format="text")
    body = cached(url, "txt", None, refresh)
    blocks, cur, start = [], None, None
    for line in body.decode("utf-8", "replace").splitlines():
        if line.startswith("start:"):
            start = datetime.datetime.fromisoformat(line.split(":", 1)[1].strip()[:19])
            cur = ([], [])
            blocks.append((start, cur))
        elif cur is not None and line[:1].isdigit():
            f, v = line.split(",")
            cur[0].append(float(f))
            cur[1].append(float(v))
    keep = [(fr, db) for s, (fr, db) in blocks if s >= t0 and s + datetime.timedelta(hours=1) <= t1]
    return keep, url


def spectra(nslc, wins, source, yes, refresh=False, gated=False):
    """Per-window spectra on one frequency grid. Returns dict with freqs, list of dB arrays, metadata."""
    import numpy as np
    net, sta, loc, cha = nslc
    kind = kind_of(cha)
    if source == "auto":
        source = "mustang" if kind == "seismic" else "mseed"
    specs, sources, sensors, freqs, sps = [], [], set(), None, None
    if source == "mustang":
        for t0, t1 in wins:
            try:
                blocks, url = mustang_blocks(net, sta, loc, cha, t0, t1, refresh)
            except NoData:
                continue
            sources.append(url)
            for fr, db in blocks:
                fr = np.array(fr)
                if freqs is None:
                    freqs = fr
                if len(fr) == len(freqs):
                    specs.append(np.array(db))
        if not specs:
            note("MUSTANG has no PSDs for %s in these windows; computing from miniSEED." % ".".join(nslc))
            source = "mseed"
    if source == "mseed":
        if not gated:
            gate(mseed_plan(nslc, wins, refresh), yes)
        for t0, t1 in wins:
            chunks, sps_, sens = mseed_chunks(net, sta, loc, cha, t0, t1, refresh)
            if not chunks:
                continue
            sps = sps_
            sensors.update(sens)
            sources.append(dataselect_url(net, sta, loc, cha, t0, t1))
            for _, c in chunks:
                f, db = welch_db(c, sps)
                if freqs is None:
                    freqs = f
                if len(f) == len(freqs):
                    specs.append(db)
    if not specs:
        raise NoData("no data for %s in the requested windows" % ".".join(nslc))
    # MUSTANG hours overlap by half, so only the miniSEED path has a clean expected count.
    expected = sum(int((t1 - t0).total_seconds() // CHUNK_S) for t0, t1 in wins) if source == "mseed" else None
    return {"freqs": freqs, "specs": np.vstack(specs), "source": source, "urls": sources, "sps": sps,
            "expected": expected,
            "sensors": sorted(sensors), "kind": kind, "units": UNITS[kind]}


def summarize(sp):
    import numpy as np
    s = sp["specs"]
    s = np.where(np.isfinite(s), s, np.nan)
    return {"median": np.nanmedian(s, axis=0), "p10": np.nanpercentile(s, 10, axis=0),
            "p90": np.nanpercentile(s, 90, axis=0)}


def prominence(freqs, db, octave=1 / 3):
    """dB above a running median over +/- `octave` in log frequency: a tonal sticks out, broadband does not."""
    import numpy as np
    out = np.full(len(db), np.nan)
    for i, f in enumerate(freqs):
        if f <= 0 or not np.isfinite(db[i]):
            continue
        m = (freqs >= f / 2 ** octave) & (freqs <= f * 2 ** octave) & np.isfinite(db)
        out[i] = db[i] - np.median(db[m])
    return out


def prominence_at(freqs, db, i, octave=1 / 3):
    import numpy as np
    f = freqs[i]
    if f <= 0 or not np.isfinite(db[i]):
        return float("nan")
    m = (freqs >= f / 2 ** octave) & (freqs <= f * 2 ** octave) & np.isfinite(db)
    return float(db[i] - np.median(db[m]))


def peaks(freqs, db, band, min_db):
    import numpy as np
    pr = prominence(freqs, db)
    res = []
    for i in range(1, len(db) - 1):
        f = freqs[i]
        if not (band[0] <= f <= band[1]) or not np.isfinite(pr[i]):
            continue
        if db[i] >= db[i - 1] and db[i] >= db[i + 1] and pr[i] >= min_db:
            # A tonal spread over a few bins yields several local maxima; keep the strongest.
            if res and i - res[-1]["i"] <= 3:
                if pr[i] > res[-1]["prominence_db"]:
                    res[-1] = {"i": i, "hz": float(f), "db": float(db[i]), "prominence_db": float(pr[i])}
                continue
            res.append({"i": i, "hz": float(f), "db": float(db[i]), "prominence_db": float(pr[i])})
    return res


def display_grid(freqs, band, per_octave=3):
    import numpy as np
    lo = max(band[0], freqs[freqs > 0][0])
    hi = min(band[1], freqs[-1])
    targets = 2 ** np.arange(math.log2(lo), math.log2(hi) + 1e-9, 1 / per_octave)
    return sorted({int(np.argmin(abs(freqs - t))) for t in targets})


def parse_band(s):
    lo, hi = (float(x) for x in s.split("-"))
    return lo, hi


def window_meta(wins):
    return {"windows": len(wins), "first": iso(wins[0][0]), "last": iso(wins[-1][1])}


def cmd_psd(a):
    nslc = split_nslc(a.nslc)
    days = sample_days(parse_day(a.start), parse_day(a.end) if a.end else None, a.days)
    wins = windows(days, a.hours, a.utc)
    sp = spectra(nslc, wins, a.source, a.yes, a.refresh)
    sm = summarize(sp)
    nyq = (sp["sps"] / 2) if sp["sps"] else float(sp["freqs"][-1])
    band = parse_band(a.band) if a.band else (float(sp["freqs"][sp["freqs"] > 0][0]), nyq)
    idx = display_grid(sp["freqs"], band)
    res = {"nslc": ".".join(nslc), "source": sp["source"], "units": sp["units"], "sensors": sp["sensors"],
           "hours": a.hours, "tz": "UTC" if a.utc else LOCAL_TZ, "days": [d.isoformat() for d in days],
           "spectra": int(sp["specs"].shape[0]), "expected_hours": sp["expected"], "nyquist": nyq,
           "table": [{"hz": float(sp["freqs"][i]), "median": float(sm["median"][i]), "p10": float(sm["p10"][i]),
                      "p90": float(sm["p90"][i])} for i in idx],
           "peaks": peaks(sp["freqs"], sm["median"], band, a.min_prominence),
           "urls": sp["urls"], "retrieved": today()}
    res.update(window_meta(wins))
    if sp["kind"] == "pressure":
        f, m = sp["freqs"], sm["median"]
        mb = (f >= 0.15) & (f <= 0.4)
        hi = (f >= 0.6) & (f <= 1.0)
        lo = (f >= 0.05) & (f <= 0.1)
        if mb.any() and hi.any() and lo.any():
            import numpy as np
            # A microbarom bump stands above both neighbours. Above 0.6-1 Hz alone, any red spectrum
            # (including one from a wrong response) passes, so report both sides and call it a bump only
            # when both are positive. This is an indicator, not a validation of the response removal.
            res["microbarom_db"] = {"over_0.6-1Hz": float(m[mb].max() - np.median(m[hi])),
                                    "over_0.05-0.1Hz": float(m[mb].max() - np.median(m[lo]))}
    if a.csv:
        write_csv(a.csv, sp["freqs"], {"median": sm["median"], "p10": sm["p10"], "p90": sm["p90"]})
        res["csv"] = a.csv
    for p in res["peaks"]:
        p.pop("i")
    return res


def write_csv(path, freqs, cols):
    import csv
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["hz"] + list(cols))
        for i, f in enumerate(freqs):
            w.writerow(["%.6g" % f] + ["%.3f" % cols[k][i] for k in cols])


def months(lo, hi):
    out, d = set(), lo
    while d <= hi:
        out.add(d.month)
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return out


def cmd_compare(a):
    import numpy as np
    nslc_b = split_nslc(a.nslc)
    nslc_a = split_nslc(a.after_nslc) if a.after_nslc else nslc_b
    (b0, b1), (c0, c1) = parse_span(a.before), parse_span(a.after)
    wb = windows(sample_days(b0, b1, a.days), a.hours, a.utc)
    wa = windows(sample_days(c0, c1, a.days), a.hours, a.utc)
    notes = []
    eb = epochs_for(*nslc_b, wb[0][0], wb[-1][1], a.refresh)
    ea = epochs_for(*nslc_a, wa[0][0], wa[-1][1], a.refresh)
    if not eb or not ea:
        raise NoData("%s has no epoch in the %s window" % (".".join(nslc_b if not eb else nslc_a),
                                                          "before" if not eb else "after"))
    desc = lambda eps: sorted({(e["loc"], e["sensor"], e["sps"]) for e in eps})
    changed = nslc_a != nslc_b or desc(eb) != desc(ea) or len(desc(eb)) > 1 or len(desc(ea)) > 1
    if changed and not a.allow_epoch_change:
        die("Instrument or location code differs between or within the windows:\n  before: %s\n  after:  %s\n"
            "A level change across an instrument swap is not evidence of a new source. Pass --allow-epoch-change "
            "to compare anyway." % (desc(eb), desc(ea)))
    if changed:
        notes.append("Compared across an instrument/epoch change (--allow-epoch-change): differences may be "
                     "instrumental.")
    if not months(b0, b1) & months(c0, c1):
        notes.append("The before and after windows share no calendar month. Wind, microbarom and traffic "
                     "levels are seasonal; prefer the same months in each year.")
    source = a.source
    if source == "auto":
        source = "mustang" if kind_of(nslc_b[3]) == "seismic" else "mseed"
    gated = source == "mseed"
    if gated:
        gate(mseed_plan(nslc_b, wb, a.refresh) + mseed_plan(nslc_a, wa, a.refresh), a.yes)
    sb = spectra(nslc_b, wb, source, a.yes, a.refresh, gated)
    sa = spectra(nslc_a, wa, sb["source"], a.yes, a.refresh, gated)
    if len(sb["freqs"]) != len(sa["freqs"]) or not np.allclose(sb["freqs"], sa["freqs"]):
        die("The two windows came back on different frequency grids (sample rate or source changed); "
            "pass --source mseed with matching channels.")
    f = sb["freqs"]
    mb, ma = summarize(sb)["median"], summarize(sa)["median"]
    nyq = min((sb["sps"] or max(e["sps"] for e in eb)) / 2, float(f[-1]))
    band = parse_band(a.band) if a.band else (1.0, nyq)
    before_peaks = peaks(f, mb, band, a.min_prominence / 2)
    found = []
    for p in peaks(f, ma, band, a.min_prominence):
        i = p["i"]
        near = [q_ for q_ in before_peaks if abs(q_["i"] - i) <= 2]
        delta = float(ma[i] - mb[i])
        # Persistence: share of individual after-window spectra that show the peak on their own.
        per = [prominence_at(f, s, i) for s in sa["specs"]]
        persist = float(np.mean([x >= a.min_prominence / 2 for x in per if np.isfinite(x)]))
        if near or delta < a.min_change:
            continue
        found.append({"hz": p["hz"], "after_db": p["db"], "before_db": float(mb[i]), "change_db": delta,
                      "prominence_db": p["prominence_db"], "persistence": persist,
                      "persistent": persist >= 0.5})
    idx = display_grid(f, band)
    for label, sp in (("before", sb), ("after", sa)):
        if sp["expected"] and sp["specs"].shape[0] < 0.5 * sp["expected"]:
            notes.append("%s window: only %d of %d hours had gap-free data; its median rests on few spectra."
                         % (label, sp["specs"].shape[0], sp["expected"]))
    big = [r for r in (float(ma[i] - mb[i]) for i in display_grid(f, band)) if abs(r) >= 20]
    if big:
        notes.append("Broadband change of %d dB or more across the band. A shift this large and smooth usually "
                     "means the sensor, its inlet or wind filter, or the site changed, even within one metadata "
                     "epoch. Check the station's data-quality reports before reading it as a sound-field change."
                     % min(abs(x) for x in big))
    return {"before": {"nslc": ".".join(nslc_b), "span": a.before, "epochs": desc(eb), "spectra":
                       int(sb["specs"].shape[0]), "expected_hours": sb["expected"], **window_meta(wb)},
            "after": {"nslc": ".".join(nslc_a), "span": a.after, "epochs": desc(ea), "spectra":
                      int(sa["specs"].shape[0]), "expected_hours": sa["expected"], **window_meta(wa)},
            "source": sb["source"], "units": sb["units"], "band": band, "hours": a.hours,
            "tz": "UTC" if a.utc else LOCAL_TZ,
            "table": [{"hz": float(f[i]), "before": float(mb[i]), "after": float(ma[i]),
                       "change": float(ma[i] - mb[i])} for i in idx],
            "new_peaks": found, "notes": notes, "urls": sb["urls"][:3] + sa["urls"][:3], "retrieved": today()}


def cmd_coherence(a):
    import numpy as np
    from scipy.signal import csd, resample_poly, welch
    net, _, sta = a.station.upper().partition(".")
    if not sta:
        die("expected NET.STA, e.g. N4.545B")
    days = sample_days(parse_day(a.start), parse_day(a.end) if a.end else None, a.days)
    wins = windows(days, a.hours, a.utc)
    rows, _ = channel_rows(a.refresh, net=net, sta=sta, cha=",".join(INFRA + SEIS),
                           starttime=iso(wins[0][0]), endtime=iso(wins[-1][1]))
    infra = [r for r in rows if r["cha"] in INFRA]
    seis = [r for r in rows if r["cha"] in SEIS]
    if not infra or not seis:
        die("%s.%s has no co-located infrasound and vertical seismic channels in %s..%s."
            % (net, sta, iso(wins[0][0]), iso(wins[-1][1])), 3)
    # Prefer the highest-rate vertical; the infrasound rate caps the common band anyway.
    i_ch = max(infra, key=lambda r: r["sps"])
    s_ch = max(seis, key=lambda r: r["sps"])
    plan = []
    for t0, t1 in wins:
        for ch in (i_ch, s_ch):
            plan.append((dataselect_url(net, sta, ch["loc"], ch["cha"], t0, t1), ch["sps"], (t1 - t0).total_seconds()))
    gate(plan, a.yes)
    sxy = sxx = syy = None
    n_chunks = 0
    for t0, t1 in wins:
        ci, ri, _ = mseed_chunks(net, sta, i_ch["loc"], i_ch["cha"], t0, t1, a.refresh)
        cs, rs, _ = mseed_chunks(net, sta, s_ch["loc"], s_ch["cha"], t0, t1, a.refresh)
        if not ci or not cs:
            continue
        g = math.gcd(int(ri), int(rs))
        ys = dict(cs)
        for k, x in ci:
            if k not in ys:
                continue
            y = ys[k]
            if rs != ri:
                y = resample_poly(y, int(ri) // g, int(rs) // g)
            n = min(len(x), len(y))
            kw = dict(fs=ri, window="hann", nperseg=int(SEG_S * ri), noverlap=int(SEG_S * ri) // 2)
            f, pxy = csd(x[:n], y[:n], **kw)
            _, pxx = welch(x[:n], **kw)
            _, pyy = welch(y[:n], **kw)
            sxy = pxy if sxy is None else sxy + pxy
            sxx = pxx if sxx is None else sxx + pxx
            syy = pyy if syy is None else syy + pyy
            n_chunks += 1
    if not n_chunks:
        raise NoData("no overlapping data for %s.%s in these windows" % (net, sta))
    coh = np.abs(sxy) ** 2 / (sxx * syy)
    band = parse_band(a.band) if a.band else (0.05, ri / 2)
    idx = display_grid(f, band, per_octave=4)
    picks = []
    for hz in (float(x) for x in (a.freqs.split(",") if a.freqs else [])):
        i = int(np.argmin(abs(f - hz)))
        picks.append({"hz": float(f[i]), "coherence": float(coh[i])})
    return {"station": "%s.%s" % (net, sta), "infra": "%s.%s" % (i_ch["loc"] or "--", i_ch["cha"]),
            "seismic": "%s.%s" % (s_ch["loc"] or "--", s_ch["cha"]), "hours": a.hours,
            "tz": "UTC" if a.utc else LOCAL_TZ, "days": [d.isoformat() for d in days], "chunks": n_chunks,
            "table": [{"hz": float(f[i]), "coherence": float(coh[i])} for i in idx], "at": picks,
            "retrieved": today()}


def cmd_events(a):
    url = q(COMCAT, format="geojson", latitude=a.lat, longitude=a.lon, maxradiuskm=a.radius_km,
            starttime=a.start, endtime=a.end, eventtype=None, orderby="time-asc")
    body = cached(url, "json", TTL, a.refresh)
    j = json.loads(body)
    ev = []
    for f in j["features"]:
        p, g = f["properties"], f["geometry"]["coordinates"]
        ev.append({"time": datetime.datetime.fromtimestamp(p["time"] / 1000, datetime.timezone.utc)
                   .strftime("%Y-%m-%d %H:%M:%SZ"), "type": p["type"], "mag": p["mag"], "magType": p["magType"],
                   "place": p["place"], "km": round(haversine_km(a.lat, a.lon, g[1], g[0]), 1),
                   "depth_km": g[2], "id": f["id"], "url": p["url"]})
    return {"center": [a.lat, a.lon], "radius_km": a.radius_km, "start": a.start, "end": a.end, "events": ev,
            "source": url, "retrieved": today()}


def cmd_health(a):
    checks = [
        ("station", q(FDSN + "station/1/query", net="N4", sta="545B", cha="BDF", level="channel", format="text")),
        ("dataselect", q(FDSN + "dataselect/1/query", net="N4", sta="545B", loc="EP", cha="BDF",
                         starttime="2016-06-01T06:00:00", endtime="2016-06-01T06:01:00")),
        ("mustang", q(MUSTANG, target="N4.545B..HHZ.*", starttime="2016-06-01T06:00:00",
                      endtime="2016-06-01T07:00:00", format="text")),
        ("comcat", q(COMCAT.replace("/query", "/count"), latitude=30.0, longitude=-90.4, maxradiuskm=150,
                     starttime="2010-01-01")),
    ]
    out = []
    for name, url in checks:
        try:
            body = _get(url, timeout=60)
            out.append({"service": name, "up": True, "bytes": len(body), "url": url})
        except (SourceDown, NoData) as e:
            out.append({"service": name, "up": False, "error": str(e), "url": url})
    return {"checks": out, "retrieved": today()}


# ---------------------------------------------------------------- text output

def show(cmd, res):
    p = print
    if cmd == "health":
        for c in res["checks"]:
            p("%-4s %-10s %s" % ("up" if c["up"] else "DOWN", c["service"],
                                 "%d bytes" % c["bytes"] if c["up"] else c["error"]))
        return
    if cmd == "stations":
        p("Channels %s within %g km of %.4f, %.4f" % (",".join(CHANNELS), res["radius_km"], *res["center"]))
        for s in res["stations"]:
            p()
            p("%s.%s  %.4f, %.4f  %.1f km at %d°" % (s["net"], s["sta"], s["lat"], s["lon"], s["km"], s["bearing"]))
            for c in s["channels"]:
                p("  %-20s %-10s %6g sps (Nyquist %g Hz)  %s .. %s  %s" % (
                    c["nslc"], c["kind"], c["sps"], c["nyquist"], c["start"], c["end"] or "open",
                    c["sensor"][:48]))
            for f in s["flags"]:
                p("  ** " + f)
            for c in s["colocated"]:
                p("  co-located %s + %s  %s .. %s" % (c["infra"], c["seismic"], c["from"], c["to"] or "open"))
        p()
        p("Source: %s; retrieved %s" % (res["source"], res["retrieved"]))
        return
    if cmd == "psd":
        p("%s  %s  %s  (%s)" % (res["nslc"], res["source"], res["units"], ", ".join(res["sensors"]) or "sensor n/a"))
        p("  %d spectra%s from %d windows, %s %s each day, %s .. %s" % (
            res["spectra"], " of %d hours (rest had gaps)" % res["expected_hours"]
            if res["expected_hours"] and res["spectra"] < res["expected_hours"] else "", res["windows"], res["hours"],
            res["tz"], res["days"][0], res["days"][-1]))
        if res["source"] == "mustang":
            p("  MUSTANG PSDs are 1/8-octave smoothed: tonals appear broadened. Use --source mseed for 0.01 Hz bins.")
        p("  %10s  %8s  %8s  %8s" % ("Hz", "median", "p10", "p90"))
        for r in res["table"]:
            p("  %10.3f  %8.1f  %8.1f  %8.1f" % (r["hz"], r["median"], r["p10"], r["p90"]))
        if "microbarom_db" in res:
            hi, lo = res["microbarom_db"]["over_0.6-1Hz"], res["microbarom_db"]["over_0.05-0.1Hz"]
            p("  microbarom band 0.15-0.4 Hz: %+.1f dB over 0.6-1 Hz, %+.1f dB over 0.05-0.1 Hz -> %s" % (
                hi, lo, "bump present" if hi > 0 and lo > 0 else "no bump (red spectrum: wind or long-period "
                "pressure noise dominates)"))
        p("  peaks (prominence over a 2/3-octave running median):" if res["peaks"] else "  no narrowband peaks")
        for k in res["peaks"]:
            p("    %8.3f Hz  %7.1f dB  +%.1f dB" % (k["hz"], k["db"], k["prominence_db"]))
        if res.get("csv"):
            p("  wrote %s" % res["csv"])
        p("Source: %s (%d requests, first: %s); retrieved %s" % (
            "EarthScope MUSTANG noise-psd" if res["source"] == "mustang" else "EarthScope fdsnws dataselect + station "
            "response", len(res["urls"]), res["urls"][0] if res["urls"] else "-", res["retrieved"]))
        return
    if cmd == "compare":
        b, a = res["before"], res["after"]
        p("%s vs %s  %s  %s, %s %s" % (b["nslc"], a["nslc"], res["source"], res["units"], res["hours"], res["tz"]))
        p("  before %s: %d spectra; epochs %s" % (b["span"], b["spectra"], b["epochs"]))
        p("  after  %s: %d spectra; epochs %s" % (a["span"], a["spectra"], a["epochs"]))
        for n in res["notes"]:
            p("  note: " + n)
        p("  %10s  %8s  %8s  %7s" % ("Hz", "before", "after", "change"))
        for r in res["table"]:
            p("  %10.3f  %8.1f  %8.1f  %+7.1f" % (r["hz"], r["before"], r["after"], r["change"]))
        if not res["new_peaks"]:
            p("  no narrowband peaks in %g-%g Hz that are new in the after window" % tuple(res["band"]))
        for k in res["new_peaks"]:
            p("  new peak %8.3f Hz  %+.1f dB  (after %.1f, before %.1f)  in %.0f%% of after spectra%s" % (
                k["hz"], k["change_db"], k["after_db"], k["before_db"], 100 * k["persistence"],
                "" if k["persistent"] else "  [intermittent]"))
        p("Peaks are retrieved spectral features. Naming a source for one is a separate judgment.")
        p("Source: EarthScope (%s), e.g. %s; retrieved %s" % (res["source"], res["urls"][0] if res["urls"] else "-",
                                                              res["retrieved"]))
        return
    if cmd == "coherence":
        p("%s  %s <-> %s  magnitude-squared coherence, %d hour chunks, %s %s, %s .. %s" % (
            res["station"], res["infra"], res["seismic"], res["chunks"], res["hours"], res["tz"], res["days"][0],
            res["days"][-1]))
        for r in res["table"]:
            p("  %10.3f Hz  %.2f" % (r["hz"], r["coherence"]))
        for r in res["at"]:
            p("  at %8.3f Hz  %.2f" % (r["hz"], r["coherence"]))
        p("High coherence: the seismometer is recording the same pressure field (air-to-ground coupling). "
          "Low coherence at a seismic peak: ground-borne vibration or a source the microphone does not see.")
        p("Source: EarthScope fdsnws dataselect + station response; retrieved %s" % res["retrieved"])
        return
    if cmd == "events":
        p("ComCat events within %g km of %.4f, %.4f, %s .. %s: %d" % (res["radius_km"], *res["center"], res["start"],
                                                                     res["end"], len(res["events"])))
        for e in res["events"]:
            p("  %s  %-14s M%-4s %-4s %6.1f km  %s  %s" % (e["time"], e["type"], e["mag"], e["magType"] or "",
                                                          e["km"], e["place"], e["id"]))
        p("Absence here is not absence of an event: ComCat lists few non-earthquake events in Louisiana.")
        p("Source: %s; retrieved %s" % (res["source"], res["retrieved"]))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="bypass the cache")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    win = argparse.ArgumentParser(add_help=False)
    win.add_argument("--hours", default="00-04", help="hour range each day, end exclusive (default 00-04 local)")
    win.add_argument("--utc", action="store_true", help="--hours are UTC, not %s" % LOCAL_TZ)
    win.add_argument("--yes", action="store_true", help="allow a miniSEED download over %d MB" % GATE_MB)
    win.add_argument("--band", help="lo-hi Hz for peaks and the table")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *x, **k: _add(*x, parents=[common] + k.pop("extra", []), **k)

    sub.add_parser("health")

    s = sub.add_parser("stations")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--radius-km", type=float, default=100)
    s.add_argument("--since")
    s.add_argument("--until")

    s = sub.add_parser("psd", extra=[win])
    s.add_argument("nslc")
    s.add_argument("--start", required=True)
    s.add_argument("--end", help="spread --days across start..end instead of consecutive days")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--source", choices=["auto", "mustang", "mseed"], default="auto")
    s.add_argument("--min-prominence", type=float, default=6.0)
    s.add_argument("--csv")

    s = sub.add_parser("compare", extra=[win])
    s.add_argument("nslc")
    s.add_argument("--before", required=True, help="A..B (YYYY-MM or YYYY-MM-DD)")
    s.add_argument("--after", required=True)
    s.add_argument("--after-nslc", help="different channel for the after window (needs --allow-epoch-change)")
    s.add_argument("--days", type=int, default=10, help="days sampled across each span")
    s.add_argument("--source", choices=["auto", "mustang", "mseed"], default="auto")
    s.add_argument("--min-prominence", type=float, default=6.0)
    s.add_argument("--min-change", type=float, default=3.0, help="dB the after peak must exceed before")
    s.add_argument("--allow-epoch-change", action="store_true")

    s = sub.add_parser("coherence", extra=[win])
    s.add_argument("station", help="NET.STA")
    s.add_argument("--start", required=True)
    s.add_argument("--end")
    s.add_argument("--days", type=int, default=1)
    s.add_argument("--freqs", help="comma-separated Hz to report exactly")

    s = sub.add_parser("events")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--radius-km", type=float, default=150)

    args = ap.parse_args()
    fn = {"health": cmd_health, "stations": cmd_stations, "psd": cmd_psd, "compare": cmd_compare,
          "coherence": cmd_coherence, "events": cmd_events}[args.cmd]
    try:
        res = fn(args)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    except NoData as e:
        die("no data: %s" % e, 3)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
