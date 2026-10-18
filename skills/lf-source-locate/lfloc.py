#!/usr/bin/env python3
"""Statistical and single-site bearing inference for low-frequency tonals, and a regional arrival-time locator
for impulsive events, from the public EarthScope archive and ASOS surface wind. Every output is inference with
an uncertainty arc or credible region, never a location.

Run with: uv run -q --no-project --with obspy --with numpy --with scipy python -I lfloc.py <command> ...
Reuses lf-acoustic-baselines (lfab.py) for waveforms, responses, the download gate and the cache.

  lfloc.py health                                             EarthScope, ComCat, IEM ASOS up
  lfloc.py features <NSLC> --freqs f0[,f1] --start D [--end D --days N --hours 00-04] [--csv out.csv]
  lfloc.py bearing <NET.STA> --freqs f0[,f1] --start D [--end D --days N]   pressure x horizontal ground
  lfloc.py wind-scan (<NSLC> --start D ... | --features in.csv) --freq f0 [--asos MSY]
                     [--candidates eric.json] [--candidate name,lat,lon ...]
  lfloc.py tdoa --start T --end T [--band 2-5] [--truth lat,lon] [--picks in.csv | --csv out.csv]
                                                              impulsive events, TA ring 2011-03..2012-12
"""
import argparse
import csv
import datetime
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lf-acoustic-baselines"))
import lfab as L  # noqa: E402

ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NST = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/nexrad_storm_attrs.py"
HORIZ = ("BHN", "BHE", "BH1", "BH2", "HHN", "HHE", "HH1", "HH2")
KT = 0.514444
FEATURE_COLS = ["time_utc", "hz", "level_db", "prominence_db", "lat", "lon"]
# Set True only after `bearing` lands within ±20° of known directions on at least 3 events (SKILL.md, Validation).
BEARING_VALIDATED = False
TDOA_VALIDATED = False


# ---------------------------------------------------------------- features (the one seam for other data)

def pick_bin(freqs, power, f0, width=2):
    """Strongest bin within ±width of f0: tonals drift by a bin or two between hours."""
    import numpy as np
    i = int(np.argmin(abs(freqs - f0)))
    lo, hi = max(0, i - width), min(len(freqs), i + width + 1)
    return lo + int(np.nanargmax(power[lo:hi]))


def epoch_notes(nslc, wins, refresh, allow):
    eps = L.epochs_for(*nslc, wins[0][0], wins[-1][1], refresh)
    if not eps:
        raise L.NoData("%s has no epoch in %s..%s" % (".".join(nslc), L.iso(wins[0][0]), L.iso(wins[-1][1])))
    desc = sorted({(e["loc"], e["sensor"], e["sps"]) for e in eps})
    notes = []
    if len(desc) > 1:
        if not allow:
            L.die("%s changes instrument or sample rate inside the window: %s\nA level change across an "
                  "instrument swap would be read as a wind effect. Split the window, or pass "
                  "--allow-epoch-change." % (".".join(nslc), desc))
        notes.append("Window spans an instrument/epoch change (--allow-epoch-change).")
    if any(t0.year == 2018 or t1.year == 2018 for t0, t1 in wins) and nslc[:2] == ("N4", "545B"):
        notes.append("2018 N4.545B.EP.BDF levels sit 16-41 dB below 2015 at 6-16 Hz with no metadata change "
                     "(lf-acoustic-baselines SKILL.md). Do not pool 2018 with other years.")
    return eps, notes


def features_from_archive(nslc, wins, freqs_req, yes, refresh=False, allow_epoch_change=False):
    """Hourly level and prominence at each requested frequency. Values are rounded to CSV precision here so the
    archive path and a --features CSV of the same rows fit identical numbers."""
    net, sta, loc, cha = nslc
    eps, notes = epoch_notes(nslc, wins, refresh, allow_epoch_change)
    lat, lon = eps[0]["lat"], eps[0]["lon"]
    L.gate(L.mseed_plan(nslc, wins, refresh), yes)
    rows, expected = [], 0
    for t0, t1 in wins:
        expected += int((t1 - t0).total_seconds() // L.CHUNK_S)
        chunks, sps, _ = L.mseed_chunks(net, sta, loc, cha, t0, t1, refresh)
        for k, x in chunks:
            f, db = L.welch_db(x, sps)
            t = t0 + datetime.timedelta(seconds=k * L.CHUNK_S)
            for f0 in freqs_req:
                if f0 >= f[-1]:
                    L.die("%g Hz is above the %g Hz Nyquist of %s" % (f0, f[-1], ".".join(nslc)))
                j = pick_bin(f, db, f0)
                rows.append({"time_utc": L.iso(t), "hz": f0, "level_db": round(float(db[j]), 3),
                             "prominence_db": round(L.prominence_at(f, db, j), 3),
                             "lat": round(lat, 5), "lon": round(lon, 5)})
    if not rows:
        raise L.NoData("no gap-free hours for %s in these windows" % ".".join(nslc))
    return rows, expected, notes


def write_features(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FEATURE_COLS)
        for r in rows:
            w.writerow([r["time_utc"], "%g" % r["hz"], "%.3f" % r["level_db"], "%.3f" % r["prominence_db"],
                        "%.5f" % r["lat"], "%.5f" % r["lon"]])


def read_features(path):
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in FEATURE_COLS if c not in (rd.fieldnames or [])]
        if missing:
            L.die("%s lacks columns %s (schema: %s)" % (path, missing, ",".join(FEATURE_COLS)))
        out = []
        for r in rd:
            out.append({"time_utc": r["time_utc"][:19], "hz": float(r["hz"]), "level_db": float(r["level_db"]),
                        "prominence_db": float(r["prominence_db"]), "lat": float(r["lat"]),
                        "lon": float(r["lon"])})
    return out


def windows_from(a):
    days = L.sample_days(L.parse_day(a.start), L.parse_day(a.end) if a.end else None, a.days)
    return days, L.windows(days, a.hours, a.utc)


def parse_freqs(s):
    return [float(x) for x in s.split(",") if x.strip()]


def cmd_features(a):
    nslc = L.split_nslc(a.nslc)
    days, wins = windows_from(a)
    rows, expected, notes = features_from_archive(nslc, wins, parse_freqs(a.freqs), a.yes, a.refresh,
                                                  a.allow_epoch_change)
    if a.csv:
        write_features(a.csv, rows)
    return {"nslc": ".".join(nslc), "hours": a.hours, "tz": "UTC" if a.utc else L.LOCAL_TZ,
            "days": [d.isoformat() for d in days], "expected_hours": expected, "rows": rows, "csv": a.csv,
            "notes": notes, "retrieved": L.today()}


# ---------------------------------------------------------------- bearing (pressure x horizontal ground motion)

def pick_channels(net, sta, wins, refresh):
    """One infrasound channel and one horizontal pair (same location code and band) for the whole span."""
    rows, _ = L.channel_rows(refresh, net=net, sta=sta, cha=",".join(L.INFRA + HORIZ),
                             starttime=L.iso(wins[0][0]), endtime=L.iso(wins[-1][1]))
    overlaps = lambda r, t0, t1: r["start"] <= t1.date().isoformat() and (
        r["end"] is None or r["end"] >= t0.date().isoformat())
    chosen = set()
    for t0, t1 in wins:
        live = [r for r in rows if overlaps(r, t0, t1)]
        infra = [r for r in live if r["cha"] in L.INFRA]
        groups = {}
        for r in live:
            if r["cha"] in HORIZ:
                groups.setdefault((r["loc"], r["cha"][:2]), {})[r["cha"][2]] = r
        pairs = [g for g in groups.values() if {"N", "E"} <= set(g) or {"1", "2"} <= set(g)]
        if not infra or not pairs:
            L.die("%s.%s has no infrasound channel plus horizontal pair around %s." % (net, sta, L.iso(t0)), 3)
        i = max(infra, key=lambda r: r["sps"])
        g = max(pairs, key=lambda g: max(r["sps"] for r in g.values()))
        h1, h2 = (g["N"], g["E"]) if "N" in g else (g["1"], g["2"])
        chosen.add(((i["loc"], i["cha"], i["sps"]), (h1["loc"], h1["cha"], h2["cha"], h1["sps"])))
    if len(chosen) > 1:
        L.die("The channel set changes inside the window (e.g. N4.545B moved from --.HHN/HHE to 00.HH1/HH2 on "
              "2019-03-01): %s. Split the window at the change." % sorted(chosen), 2)
    return chosen.pop()


def horiz_azimuths(net, sta, loc, c1, c2, t0, t1, refresh):
    out = []
    for cha in (c1, c2):
        inv = L.inventory(net, sta, loc, cha, t0, t1, refresh)
        ch = [c for n in inv for s in n for c in s][0]
        out.append(float(ch.azimuth))
    return out


def axis_of(v):
    """Principal horizontal axis (degrees, 0-180) of a complex 2-vector [S_pN, S_pE] and its linearity."""
    import numpy as np
    m = np.outer(v.real, v.real) + np.outer(v.imag, v.imag)
    w, vec = np.linalg.eigh(m)
    n, e = vec[:, 1]
    lin = float(w[1] / (w[0] + w[1])) if w.sum() > 0 else float("nan")
    return (math.degrees(math.atan2(e, n)) + 180) % 180, lin


def multi_coh(spp, snn, see, spn, spe, sne):
    """Multiple coherence of pressure on (N, E). scipy csd(a, b) = E[conj(A) B]."""
    import numpy as np
    s = np.array([spn, spe])
    r = np.array([[snn, np.conj(sne)], [sne, see]])
    try:
        return float(np.real(np.conj(s) @ np.linalg.solve(r, s)) / np.real(spp))
    except np.linalg.LinAlgError:
        return float("nan")


def axial_stats(angles):
    """Mean axis and circular spread of axial data (0-180°), on doubled angles."""
    if not angles:
        return None, None, 0.0
    c = sum(math.cos(math.radians(2 * x)) for x in angles) / len(angles)
    s = sum(math.sin(math.radians(2 * x)) for x in angles) / len(angles)
    rbar = math.hypot(c, s)
    mean = (math.degrees(math.atan2(s, c)) / 2) % 180
    sd = math.degrees(math.sqrt(-2 * math.log(rbar)) / 2) if rbar > 0 else float("inf")
    return mean, sd, rbar


def signed_azimuth(v):
    """Azimuth (0-360) of the in-phase part of [S_pN, S_pE], and the share of |v|² that is in phase. Tilt and
    compliance couple pressure to horizontal acceleration with a near-real transfer, so the in-phase part keeps
    the side; which side it points to (toward or away from the source) is fixed by validation, not theory."""
    re = v.real
    tot = float((abs(v) ** 2).sum())
    return (math.degrees(math.atan2(re[1], re[0])) + 360) % 360, float((re ** 2).sum() / tot) if tot else float("nan")


def cross_hours(net, sta, wins, yes, refresh, keep_series=False):
    """Per gap-free hour: the 6 spectra [Spp, SNN, SEE, SpN, SpE, SNE] on one grid, plus channel metadata
    (and the rotated series (p, N, E) when keep_series)."""
    import numpy as np
    from scipy.signal import csd, resample_poly, welch
    (iloc, icha, isps), (hloc, c1, c2, hsps) = pick_channels(net, sta, wins, refresh)
    plan = []
    for t0, t1 in wins:
        for loc, cha, sps in ((iloc, icha, isps), (hloc, c1, hsps), (hloc, c2, hsps)):
            plan.append((L.dataselect_url(net, sta, loc, cha, t0, t1), sps, (t1 - t0).total_seconds()))
    L.gate(plan, yes)
    per_hour, tot, f, ri, az = [], None, None, None, None
    for t0, t1 in wins:
        cp, ri_, _ = L.mseed_chunks(net, sta, iloc, icha, t0, t1, refresh)
        ch1, rs, _ = L.mseed_chunks(net, sta, hloc, c1, t0, t1, refresh)
        ch2, rs2, _ = L.mseed_chunks(net, sta, hloc, c2, t0, t1, refresh)
        if not cp or not ch1 or not ch2:
            continue
        ri = ri_
        a1, a2 = horiz_azimuths(net, sta, hloc, c1, c2, t0, t1, refresh)
        az = (a1, a2)
        y1, y2 = dict(ch1), dict(ch2)
        g = math.gcd(int(ri), int(rs))
        for k, x in cp:
            if k not in y1 or k not in y2:
                continue
            h1, h2 = y1[k], y2[k]
            if rs != ri:
                h1 = resample_poly(h1, int(ri) // g, int(rs) // g)
                h2 = resample_poly(h2, int(ri) // g, int(rs) // g)
            n = min(len(x), len(h1), len(h2))
            x, h1, h2 = x[:n], h1[:n], h2[:n]
            # Sensor axes in the metadata are rarely exactly 0/90, so rotate every pair, not only 1/2.
            nn = h1 * math.cos(math.radians(a1)) + h2 * math.cos(math.radians(a2))
            ee = h1 * math.sin(math.radians(a1)) + h2 * math.sin(math.radians(a2))
            kw = dict(fs=ri, window="hann", nperseg=int(L.SEG_S * ri), noverlap=int(L.SEG_S * ri) // 2)
            f, spp = welch(x, **kw)
            _, snn = welch(nn, **kw)
            _, see = welch(ee, **kw)
            _, spn = csd(x, nn, **kw)
            _, spe = csd(x, ee, **kw)
            _, sne = csd(nn, ee, **kw)
            sp = np.vstack([spp, snn, see, spn, spe, sne])
            tot = sp if tot is None else tot + sp
            per_hour.append((t0 + datetime.timedelta(seconds=k * L.CHUNK_S), sp) +
                            (((x, nn, ee),) if keep_series else ()))
    if not per_hour:
        raise L.NoData("no hours with gap-free pressure and both horizontals for %s.%s" % (net, sta))
    meta = {"infra": "%s.%s" % (iloc or "--", icha), "horizontals": ["%s.%s" % (hloc or "--", c1),
                                                                     "%s.%s" % (hloc or "--", c2)],
            "azimuths_deg": az}
    return per_hour, tot, f, ri, meta


def cmd_bearing(a):
    import numpy as np
    net, _, sta = a.station.upper().partition(".")
    if not sta:
        L.die("expected NET.STA, e.g. N4.545B")
    days, wins = windows_from(a)
    freqs_req = parse_freqs(a.freqs)
    per_hour, tot, f, ri, meta = cross_hours(net, sta, wins, a.yes, a.refresh)
    band = L.parse_band(a.band) if a.band else (0.05, ri / 2)
    table = []
    for i in L.display_grid(f, band, per_octave=4):
        table.append({"hz": float(f[i]), "multiple_coherence": multi_coh(*tot[:, i])})
    out = []
    for f0 in freqs_req:
        i = pick_bin(f, np.real(tot[0]), f0)
        hours, kept = [], []
        for t, sp in per_hour:
            g2 = multi_coh(*sp[:, i])
            ax, lin = axis_of(sp[3:5, i])
            sg, inph = signed_azimuth(sp[3:5, i])
            hours.append({"time_utc": L.iso(t), "multiple_coherence": round(g2, 4),
                          "coh_pN": round(float(abs(sp[3, i]) ** 2 / np.real(sp[0, i] * sp[1, i])), 4),
                          "coh_pE": round(float(abs(sp[4, i]) ** 2 / np.real(sp[0, i] * sp[2, i])), 4),
                          "axis_deg": round(ax, 1), "linearity": round(lin, 3), "in_phase_deg": round(sg, 1),
                          "in_phase_share": round(inph, 3)})
            if g2 >= a.min_coherence:
                kept.append(ax)
        mean, sd, rbar = axial_stats(kept)
        pooled_ax, pooled_lin = axis_of(tot[3:5, i])
        psg, pinph = signed_azimuth(tot[3:5, i])
        out.append({"hz": float(f[i]), "requested_hz": f0, "pooled_multiple_coherence": multi_coh(*tot[:, i]),
                    "pooled_axis_deg": round(pooled_ax, 1), "pooled_linearity": round(pooled_lin, 3),
                    "pooled_in_phase_deg": round(psg, 1), "pooled_in_phase_share": round(pinph, 3),
                    "hours_total": len(hours), "hours_kept": len(kept),
                    "axis_deg": None if mean is None else round(mean, 1),
                    "axis_sd_deg": None if sd is None else round(sd, 1), "rbar": round(rbar, 3),
                    "back_azimuth_candidates": None if mean is None else [round(mean, 1), round(mean + 180, 1)],
                    "hours": hours})
    return {"station": "%s.%s" % (net, sta), **meta, "hours": a.hours, "tz": "UTC" if a.utc else L.LOCAL_TZ,
            "days": [d.isoformat() for d in days], "chunks": len(per_hour), "min_coherence": a.min_coherence,
            "validated": BEARING_VALIDATED, "coherence_table": table, "at": out, "retrieved": L.today()}


# ---------------------------------------------------------------- bearing validation on located thunder

def storm_cells(radar, d0, d1, refresh=False):
    """NEXRAD storm-cell attributes (Level III NST via IEM), one request per month, cached once settled."""
    rows, urls, d = [], [], d0
    while d <= d1:
        nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        e = min(d1 + datetime.timedelta(days=1), nxt)
        url = L.q(NST, fmt="csv", radar=radar, year1=d.year, month1=d.month, day1=d.day, hour1=0, minute1=0,
                  year2=e.year, month2=e.month, day2=e.day, hour2=0, minute2=0)
        settled = e < datetime.date.today() - datetime.timedelta(days=2)
        try:
            body = L.cached(url, "csv", None if settled else L.TTL, refresh).decode("utf-8", "replace")
        except L.NoData:
            body = ""
        urls.append(url)
        for r in csv.DictReader(body.splitlines()):
            try:
                rows.append({"t": datetime.datetime.strptime(r["VALID"], "%Y%m%d%H%M"), "id": r["STORM_ID"],
                             "dbz": float(r["MAX_DBZ"]), "lat": float(r["LAT"]), "lon": float(r["LON"])})
            except (KeyError, ValueError):
                continue
        d = nxt
    return rows, urls


def circ_mean(degs):
    s = sum(math.sin(math.radians(x)) for x in degs)
    c = sum(math.cos(math.radians(x)) for x in degs)
    return (math.degrees(math.atan2(s, c)) + 360) % 360


def thunder_events(cells, lat, lon, radius_km, min_dbz, max_spread, per_day):
    """UTC hours with strong cells within radius_km all on one side, and no strong cell within 2x radius
    elsewhere: thunder then arrives from a known direction."""
    by_hour = {}
    for c in cells:
        if c["dbz"] < min_dbz:
            continue
        km = L.haversine_km(lat, lon, c["lat"], c["lon"])
        if km > 2 * radius_km:
            continue
        by_hour.setdefault(c["t"].replace(minute=0), []).append((km, L.bearing(lat, lon, c["lat"], c["lon"])))
    ev = []
    for h, cs in sorted(by_hour.items()):
        near = [(km, b) for km, b in cs if 3 <= km <= radius_km]
        if len(near) < 3 or any(km < 3 for km, _ in cs):
            continue
        spread, _, _ = spread_of([b for _, b in cs])
        if spread > max_spread:
            continue
        ev.append({"hour_utc": h, "cells": len(near), "truth_deg": round(circ_mean([b for _, b in near]), 1),
                   "median_km": round(sorted(km for km, _ in near)[len(near) // 2], 1),
                   "spread_deg": round(spread, 1)})
    ev.sort(key=lambda e: (-e["cells"], e["median_km"]))
    out, days = [], {}
    for e in ev:
        d = e["hour_utc"].date()
        if days.get(d, 0) < per_day:
            days[d] = days.get(d, 0) + 1
            out.append(e)
    return out


def loud_spectra(x, nn, ee, sps, band, seg_s, min_ratio, top):
    """Cross-spectra summed over only the short segments whose in-band pressure power is min_ratio times the
    hour's median (at most the loudest `top` share). An hour-long average buries seconds of thunder under
    wind noise; selecting segments keeps the transient."""
    import numpy as np
    n = int(seg_s * sps)
    step = n // 2
    win = np.hanning(n)
    f = np.fft.rfftfreq(n, 1 / sps)
    m = (f >= band[0]) & (f <= band[1])
    segs = []
    for s0 in range(0, len(x) - n + 1, step):
        X, N, E = (np.fft.rfft(win * (z[s0:s0 + n] - z[s0:s0 + n].mean())) for z in (x, nn, ee))
        segs.append((float((abs(X[m]) ** 2).sum()), X, N, E))
    pw = np.array([s[0] for s in segs])
    thr = max(min_ratio * np.median(pw), np.quantile(pw, 1 - top))
    pick = [s for s in segs if s[0] >= thr]
    if not pick:
        return None, f, 0
    sp = np.zeros((6, len(f)), complex)
    for _, X, N, E in pick:
        sp += np.vstack([abs(X) ** 2, abs(N) ** 2, abs(E) ** 2, np.conj(X) * N, np.conj(X) * E, np.conj(N) * E])
    return sp, f, len(pick)


def band_axis(sp, f, band, min_coh):
    """Axis and in-phase azimuth from all bins in band whose multiple coherence passes, each bin weighted
    equally so one loud bin cannot set the answer."""
    import numpy as np
    m = np.zeros((2, 2))
    re = np.zeros(2)
    used = 0
    for i in np.where((f >= band[0]) & (f <= band[1]))[0]:
        if multi_coh(*sp[:, i]) < min_coh:
            continue
        v = sp[3:5, i]
        nv = float((abs(v) ** 2).sum())
        if nv <= 0:
            continue
        m += (np.outer(v.real, v.real) + np.outer(v.imag, v.imag)) / nv
        re += v.real / math.sqrt(nv)
        used += 1
    if not used:
        return None
    w, vec = np.linalg.eigh(m)
    ax = (math.degrees(math.atan2(vec[1, 1], vec[0, 1])) + 180) % 180
    return {"bins": used, "axis_deg": round(ax, 1), "linearity": round(float(w[1] / w.sum()), 3),
            "in_phase_deg": round((math.degrees(math.atan2(re[1], re[0])) + 360) % 360, 1)}


def cmd_validate(a):
    net, _, sta = a.station.upper().partition(".")
    if not sta:
        L.die("expected NET.STA, e.g. N4.545B")
    d0, d1 = L.parse_day(a.start), L.parse_day(a.end)
    rows, _ = L.channel_rows(a.refresh, net=net, sta=sta, cha=",".join(L.INFRA), starttime=d0.isoformat(),
                             endtime=d1.isoformat())
    if not rows:
        L.die("%s.%s has no infrasound channel in %s..%s" % (net, sta, d0, d1), 3)
    lat, lon = rows[0]["lat"], rows[0]["lon"]
    cells, urls = storm_cells(a.radar, d0, d1, a.refresh)
    events = thunder_events(cells, lat, lon, a.radius_km, a.min_dbz, a.max_spread, 2)[:a.max_events]
    if not events:
        L.die("No one-sided storm hours within %g km of %s.%s in %s..%s." % (a.radius_km, net, sta, d0, d1), 3)
    band = L.parse_band(a.band)
    for e in events:
        h = e["hour_utc"]
        try:
            per_hour, _, _, ri, meta = cross_hours(net, sta, [(h, h + datetime.timedelta(hours=1))], a.yes,
                                                   a.refresh, keep_series=True)
        except L.NoData:
            e["result"], e["status"], e["hour_utc"] = None, "no gap-free data", L.iso(h)
            continue
        sp, f, nseg = loud_spectra(*per_hour[0][2], ri, band, a.seg_s, a.min_ratio, a.top)
        e["loud_segments"] = nseg
        # Coherence from fewer than ~8 segments is biased high (it is 1 for a single segment).
        r = band_axis(sp, f, band, a.min_coherence) if nseg >= 8 else None
        if nseg < 8:
            e["status"] = "%d loud segments (< 8)" % nseg
        e["result"] = r
        if r:
            e["axial_error_deg"] = round(min(ang_diff(r["axis_deg"], e["truth_deg"]),
                                             ang_diff(r["axis_deg"] + 180, e["truth_deg"])), 1)
            e["in_phase_minus_truth_deg"] = round((r["in_phase_deg"] - e["truth_deg"] + 180) % 360 - 180, 1)
        e["hour_utc"] = L.iso(h)
    scored = [e for e in events if e.get("result") and e["result"]["bins"] >= a.min_bins]
    hits = [e for e in scored if e["axial_error_deg"] <= 20]
    toward = sum(1 for e in hits if abs(e["in_phase_minus_truth_deg"]) <= 90)
    sign = None
    if hits and toward in (0, len(hits)):
        sign = "toward" if toward else "away"
    return {"station": "%s.%s" % (net, sta), "radar": a.radar, "band": band, "min_coherence": a.min_coherence,
            "events": events, "scored": len(scored), "within_20": len(hits),
            "in_phase_points": sign, "passes": len(hits) >= 3 and sign is not None and len(hits) >= len(scored) / 2,
            "nst_urls": urls[:2], "retrieved": L.today()}


# ---------------------------------------------------------------- surface wind (IEM ASOS)

def asos_hourly(station, d0, d1, refresh=False):
    """Vector-mean wind per UTC hour from METAR + SPECI. Returns {hour datetime: (speed m/s, from-direction°)},
    the URL, and the share of calm hours. day2 is exclusive at IEM, so the end is pushed one day out."""
    d1 = d1 + datetime.timedelta(days=1)
    url = L.q(ASOS, station=station, data="drct", year1=d0.year, month1=d0.month, day1=d0.day, year2=d1.year,
              month2=d1.month, day2=d1.day, tz="UTC", format="onlycomma", latlon="no", missing="M",
              direct="no", report_type="3") + "&data=sknt&report_type=4"
    settled = d1 < datetime.date.today() - datetime.timedelta(days=2)
    body = L.cached(url, "csv", None if settled else L.TTL, refresh).decode("utf-8", "replace")
    acc = {}
    for r in csv.DictReader(body.splitlines()):
        try:
            t = datetime.datetime.strptime(r["valid"][:16], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            continue
        if r.get("sknt") in (None, "M", ""):
            continue
        spd = float(r["sknt"]) * KT
        # drct 0 with sknt 0 is calm; a missing direction with wind is variable (VRB) and adds no vector.
        if spd == 0:
            u = v = 0.0
        elif r.get("drct") in (None, "M", ""):
            continue
        else:
            d = math.radians(float(r["drct"]))
            u, v = spd * math.sin(d), spd * math.cos(d)
        h = t.replace(minute=0)
        s = acc.setdefault(h, [0.0, 0.0, 0])
        s[0] += u
        s[1] += v
        s[2] += 1
    out = {}
    for h, (u, v, n) in acc.items():
        u, v = u / n, v / n
        out[h] = (math.hypot(u, v), (math.degrees(math.atan2(u, v)) + 360) % 360)
    if not out:
        raise L.NoData("IEM ASOS returned no wind for %s %s..%s" % (station, d0, d1))
    return out, url


# ---------------------------------------------------------------- wind-scan

def scan(y, spd, drct):
    """Profile RSS over trial back-azimuths θ (0-359) for prom = a + c·U + b·U·cos(drct − θ), b >= 0.
    Without b >= 0 the fit is symmetric under θ -> θ+180 and cannot name a side."""
    import numpy as np
    X0 = np.column_stack([np.ones_like(y), spd])
    proj = lambda z: z - X0 @ np.linalg.lstsq(X0, z, rcond=None)[0]
    yr = proj(y)
    rss0 = float(yr @ yr)
    ar = proj(spd * np.cos(np.radians(drct)))
    br = proj(spd * np.sin(np.radians(drct)))
    th = np.radians(np.arange(360))
    w = np.outer(np.cos(th), ar) + np.outer(np.sin(th), br)
    wy = w @ yr
    ww = np.einsum("ij,ij->i", w, w)
    b = np.where(ww > 0, wy / np.where(ww > 0, ww, 1), 0)
    rss = np.where(b > 0, rss0 - wy ** 2 / np.where(ww > 0, ww, 1), rss0)
    return rss, rss0, b


def hpd_arcs(post, mass=0.9):
    import numpy as np
    order = np.argsort(post)[::-1]
    keep = np.zeros(360, bool)
    acc = 0.0
    for i in order:
        keep[i] = True
        acc += post[i]
        if acc >= mass:
            break
    arcs, i = [], 0
    if keep.all():
        return [[0, 359]], 360
    start = int(np.argmin(keep))  # begin scanning just after a gap so arcs crossing 0° stay whole
    for k in range(1, 361):
        j = (start + k) % 360
        if keep[j] and (not arcs or arcs[-1][1] != (j - 1) % 360):
            arcs.append([j, j])
        elif keep[j]:
            arcs[-1][1] = j
    return arcs, int(keep.sum())


def ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def spread_of(bearings):
    """Smallest arc (degrees) containing every bearing, and its start and end."""
    if not bearings:
        return 0, None, None
    b = sorted(x % 360 for x in bearings)
    gaps = [((b[(i + 1) % len(b)] - b[i]) % 360 or (360 if len(b) == 1 else 0), i) for i in range(len(b))]
    g, i = max(gaps)
    if len(b) == 1:
        return 0, b[0], b[0]
    return 360 - g, b[(i + 1) % len(b)], b[i]


def load_candidates(a, lat, lon):
    cands = []
    if a.candidates:
        with open(a.candidates) as fh:
            j = json.load(fh)
        for r in (j.get("sources", []) if isinstance(j, dict) else j):
            if isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lon"), (int, float)):
                cands.append({"name": "%s: %s" % (r.get("ai_name") or r.get("ai") or "", r.get("source") or
                                                  r.get("release_point_id") or "?"),
                              "category": r.get("category"), "lat": r["lat"], "lon": r["lon"]})
    for s in a.candidate or []:
        name, la, lo = s.rsplit(",", 2)
        cands.append({"name": name, "category": None, "lat": float(la), "lon": float(lo)})
    for c in cands:
        c["bearing"] = round(L.bearing(lat, lon, c["lat"], c["lon"]), 1)
        c["km"] = round(L.haversine_km(lat, lon, c["lat"], c["lon"]), 2)
    return cands


def day_key(t):
    """Night windows straddle midnight, so group hours by the local day the evening began on."""
    from zoneinfo import ZoneInfo
    loc = t.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo(L.LOCAL_TZ))
    return (loc - datetime.timedelta(hours=12)).date()


def cmd_wind_scan(a):
    import numpy as np
    notes = []
    if a.features:
        rows = read_features(a.features)
        origin = {"features": os.path.abspath(a.features)}
    else:
        if not (a.nslc and a.start):
            L.die("give <NSLC> --start ... or --features <csv>")
        nslc = L.split_nslc(a.nslc)
        _, wins = windows_from(a)
        rows, _, notes = features_from_archive(nslc, wins, [a.freq], a.yes, a.refresh, a.allow_epoch_change)
        origin = {"nslc": ".".join(nslc), "hours": a.hours, "tz": "UTC" if a.utc else L.LOCAL_TZ}
    rows = [r for r in rows if abs(r["hz"] - a.freq) < 1e-6]
    if not rows:
        L.die("no feature rows at %g Hz" % a.freq, 3)
    lat, lon = rows[0]["lat"], rows[0]["lon"]
    times = [datetime.datetime.fromisoformat(r["time_utc"]) for r in rows]
    wind, wurl = asos_hourly(a.asos, min(times).date(), max(times).date(), a.refresh)
    keep = [(t, r["prominence_db"]) for t, r in zip(times, rows) if t in wind]
    if len(keep) < 12:
        L.die("only %d hours have both a feature and ASOS wind; need at least 12." % len(keep), 3)
    t_ok = [t for t, _ in keep]
    y = np.array([p for _, p in keep])
    spd = np.array([wind[t][0] for t in t_ok])
    drct = np.array([wind[t][1] for t in t_ok])
    rss, rss0, b = scan(y, spd, drct)
    n = len(y)
    keys = [day_key(t) for t in t_ok]
    ukeys = sorted(set(keys))
    # Hours within a night are near-duplicates; counting each as independent makes the arc far too narrow.
    # Temper the likelihood to one effective observation per night.
    n_eff = len(ukeys)
    ll = -n_eff / 2 * np.log(rss / n)
    post = np.exp(ll - ll.max())
    post /= post.sum()
    lr = float(n * math.log(rss0 / rss.min()))
    # Nights with unequal hour counts pair short in a permutation, so compare the per-row statistic, not LR.
    stat = math.log(rss0 / rss.min())
    imap = int(np.argmax(post))
    # Wind and prominence are autocorrelated within a night, so permute whole nights, not hours.
    rng = np.random.default_rng(a.seed)
    by_key = {k: [i for i, kk in enumerate(keys) if kk == k] for k in ukeys}
    ge = 0
    for _ in range(a.permutations):
        perm = rng.permutation(len(ukeys))
        src = {ukeys[j]: ukeys[perm[j]] for j in range(len(ukeys))}
        yi, si, di = [], [], []
        for k in ukeys:
            tgt, sk = by_key[k], by_key[src[k]]
            for p, q_ in zip(tgt, sk):
                yi.append(y[p])
                si.append(spd[q_])
                di.append(drct[q_])
        yp = np.array(yi)
        r_, r0_, _ = scan(yp, np.array(si), np.array(di))
        if math.log(r0_ / r_.min()) >= stat:
            ge += 1
    p_value = (ge + 1) / (a.permutations + 1)
    arcs, width = hpd_arcs(post)
    calm = float(np.mean(spd < 0.5))
    cands = load_candidates(a, lat, lon)
    spread, s0, s1 = spread_of([c["bearing"] for c in cands])
    for c in cands:
        i = int(round(c["bearing"])) % 360
        c["relative_density"] = round(float(post[i] / post.max()), 3)
        c["in_90"] = any((i - lo) % 360 <= (hi - lo) % 360 for lo, hi in arcs)
    cands.sort(key=lambda c: -c["relative_density"])
    if cands and spread < max(45, width):
        notes.append("Candidates span only %.0f° (%.0f°..%.0f°) while the 90%% arc covers %d°. Geometry can at "
                     "most separate this cluster from other directions; telling units apart needs operating-time "
                     "or spectral evidence." % (spread, s0, s1, width))
    if p_value >= 0.05:
        notes.append("No significant wind dependence (p = %.2f): the bearing posterior is not informative." % p_value)
    if calm > 0.3:
        notes.append("%.0f%% of hours are calm (< 0.5 m/s) at %s; those hours carry no bearing information."
                     % (100 * calm, a.asos))
    sectors = [{"from": s, "to": s + 30, "mass": round(float(post[s:s + 30].sum()), 3)} for s in range(0, 360, 30)]
    return {**origin, "freq_hz": a.freq, "station_lat": lat, "station_lon": lon, "asos": a.asos,
            "n_hours": n, "n_days": len(ukeys), "calm_fraction": round(calm, 3),
            "map_back_azimuth": imap, "b_db_per_mps_at_map": round(float(b[imap]), 3),
            "lr": round(lr, 3), "p_value": round(p_value, 4), "permutations": a.permutations, "seed": a.seed,
            "arc90": arcs, "arc90_width_deg": width, "sectors": sectors,
            "candidate_spread_deg": round(spread, 1), "candidates": cands, "notes": notes,
            "posterior": [round(float(x), 6) for x in post], "asos_url": wurl, "retrieved": L.today()}


# ---------------------------------------------------------------- tdoa (regional impulsive locator)

PICK_COLS = ["station", "lat", "lon", "time_utc", "weight"]
TA_545A = (30.0441, -90.4894)


def parse_utc(s):
    t = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.astimezone(datetime.timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def bdf_stations(lat, lon, radius_km, t0, t1, refresh):
    rows, url = L.channel_rows(refresh, cha="BDF", latitude=lat, longitude=lon, maxradius=radius_km / 111.195,
                               starttime=L.iso(t0), endtime=L.iso(t1))
    out = {}
    for r in rows:
        if r["sps"] > 0:
            out.setdefault((r["net"], r["sta"], r["loc"]), r)
    return sorted(out.values(), key=lambda r: L.haversine_km(lat, lon, r["lat"], r["lon"])), url


def stalta_picks(st_row, t0, t1, a):
    """Trigger onsets inside t0..t1, strongest first. Each gap-free piece is triggered on its own, so a
    gap edge is never mistaken for an arrival."""
    import numpy as np
    from obspy import UTCDateTime, read
    from obspy.signal.trigger import classic_sta_lta, trigger_onset
    pad = datetime.timedelta(seconds=2 * a.lta)
    try:
        body = L.cached(L.dataselect_url(st_row["net"], st_row["sta"], st_row["loc"], "BDF", t0 - pad, t1),
                        "mseed", None, a.refresh)
    except L.NoData:
        return None
    st = read(io.BytesIO(body))
    st.merge(method=1, fill_value=None)
    lo, hi = L.parse_band(a.band)
    u0, u1 = UTCDateTime(L.iso(t0)), UTCDateTime(L.iso(t1))
    picks = []
    for tr in st.split():
        sps = tr.stats.sampling_rate
        nsta, nlta = int(a.sta * sps), int(a.lta * sps)
        if tr.stats.npts < nlta + nsta or hi >= sps / 2:
            continue
        tr.detrend("demean")
        tr.taper(0.05, max_length=10)
        # Causal filter: a zero-phase filter smears energy ahead of the onset and makes picks early by an
        # amount that depends on the band, not on the source.
        tr.filter("bandpass", freqmin=lo, freqmax=hi, corners=4, zerophase=False)
        cft = classic_sta_lta(tr.data.astype(np.float64), nsta, nlta)
        for i_on, i_off in trigger_onset(cft, a.on, a.off):
            t = tr.stats.starttime + i_on / sps
            if i_on >= nlta and u0 <= t <= u1:
                picks.append((t.datetime, float(cft[i_on:i_off + 1].max())))
    picks.sort(key=lambda p: -p[1])
    return picks[:a.top_k]


def read_picks(path):
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            missing = [c for c in PICK_COLS[:4] if c not in r]
            if missing:
                L.die("%s lacks columns %s (need %s)" % (path, ",".join(missing), ",".join(PICK_COLS)))
            s = out.setdefault(r["station"], {"station": r["station"], "lat": float(r["lat"]),
                                              "lon": float(r["lon"]), "picks": []})
            s["picks"].append((parse_utc(r["time_utc"]), float(r.get("weight") or 1)))
    return list(out.values())


def write_picks(path, stations):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(PICK_COLS)
        for s in stations:
            for t, wt in s["picks"]:
                w.writerow([s["station"], s["lat"], s["lon"], t.isoformat(timespec="milliseconds"), round(wt, 4)])


def km_grid(lat0, lon0, lats, lons):
    import numpy as np
    k = 111.195
    return (lons - lon0) * k * np.cos(np.radians(lat0)), (lats - lat0) * k


def hav_np(lat1, lon1, lat2, lon2):
    import numpy as np
    p1, p2 = np.radians(lat1), np.radians(lat2)
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def locate(stations, ref, a, w_s):
    """Posterior over (lat, lon), marginalized over origin time and celerity.

    Each station's term is a mixture: one of its picks is the arrival (Gaussian pick error), or none is
    (uniform over the pick window, weight eps). That mixture is the association step; a station with no
    picks contributes a constant and no information."""
    import numpy as np
    from scipy.special import ndtr
    lats = np.arange(a.center[0] - a.box_deg, a.center[0] + a.box_deg + 1e-9, a.step_deg)
    lons = np.arange(a.center[1] - a.box_deg, a.center[1] + a.box_deg + 1e-9, a.step_deg)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    la, lo = LA.ravel(), LO.ravel()
    S = len(stations)
    D = np.stack([hav_np(s["lat"], s["lon"], la, lo) for s in stations])          # (S, N) km
    K = max(1, max(len(s["picks"]) for s in stations))
    P = np.full((S, K), np.nan)
    Wt = np.zeros((S, K))
    for i, s in enumerate(stations):
        tot = sum(w for _, w in s["picks"]) or 1
        for j, (t, w) in enumerate(s["picks"]):
            P[i, j] = (t - ref).total_seconds()
            Wt[i, j] = w / tot
    cmin, cmax = a.celerity
    t_lo = -float(D.max()) / cmin
    t0s = np.arange(t_lo, w_s + 1e-9, a.dt)
    floor = a.eps / w_s
    sig = a.sigma
    has = ~np.isnan(P)
    Pz = np.where(has, P, 0.0)
    N = la.size
    chunk = max(1, int(4e7 // (S * len(t0s) * K)))
    if a.celerity_model == "shared":
        cels = np.arange(cmin, cmax + 1e-9, 0.01)
    else:
        cels = [None]
    logm = np.full((len(cels), N), -np.inf)
    best = np.full(N, -np.inf)
    best_t = np.zeros(N)
    best_c = np.zeros(N)
    for ci, c in enumerate(cels):
        for n0 in range(0, N, chunk):
            d = D[:, n0:n0 + chunk]                                               # (S, n)
            r = Pz[:, None, None, :] - t0s[None, None, :, None]                   # (S, 1, T, K)
            if c is not None:
                r = r - (d / c)[:, :, None, None]
                like = np.exp(-0.5 * (r / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
            else:
                # Celerity drawn independently per path, uniform on [cmin, cmax]: travel time is uniform on
                # [d/cmax, d/cmin], convolved with the Gaussian pick error.
                tmin, tmax = (d / cmax)[:, :, None, None], (d / cmin)[:, :, None, None]
                like = (ndtr((r - tmin) / sig) - ndtr((r - tmax) / sig)) / np.maximum(tmax - tmin, 1e-6)
            mix = (1 - a.eps) * np.sum(np.where(has[:, None, None, :], like * Wt[:, None, None, :], 0), axis=3)
            ll = np.sum(np.log(mix + floor), axis=0)                             # (n, T)
            m = ll.max(axis=1)
            logm[ci, n0:n0 + chunk] = m + np.log(np.exp(ll - m[:, None]).sum(axis=1) * a.dt)
            it = ll.argmax(axis=1)
            upd = m > best[n0:n0 + chunk]
            idx = np.arange(n0, n0 + d.shape[1])[upd]
            best[idx] = m[upd]
            best_t[idx] = t0s[it[upd]]
            best_c[idx] = c if c is not None else np.nan
    lm = logm.max(axis=0)
    lmarg = lm + np.log(np.exp(logm - lm).sum(axis=0))
    post = np.exp(lmarg - lmarg.max())
    post /= post.sum()
    return {"lats": lats, "lons": lons, "post": post.reshape(LA.shape), "D": D, "P": P, "Wt": Wt,
            "best_t": best_t.reshape(LA.shape), "best_c": best_c.reshape(LA.shape), "floor": floor}


def region_stats(lats, lons, post, mass, at):
    """HPD region over grid cells, with its extent along and across its long axis in km."""
    import numpy as np
    flat = post.ravel()
    order = np.argsort(flat)[::-1]
    cum = np.cumsum(flat[order])
    keep = order[:int(np.searchsorted(cum, mass)) + 1]
    mask = np.zeros(flat.size, bool)
    mask[keep] = True
    mask = mask.reshape(post.shape)
    I, J = np.nonzero(mask)
    step_lat = float(lats[1] - lats[0])
    step_lon = float(lons[1] - lons[0])
    x, y = km_grid(at[0], at[1], lats[I], lons[J])
    area = float(np.sum((step_lat * 111.195) * (step_lon * 111.195 * np.cos(np.radians(lats[I])))))
    pts = np.stack([x, y])
    if len(I) > 2:
        ev, evec = np.linalg.eigh(np.cov(pts))
        major = evec[:, 1]
    else:
        major = np.array([0.0, 1.0])
    minor = np.array([-major[1], major[0]])
    cell_km = max(step_lat, step_lon) * 111.195
    along = float(np.ptp(major @ pts)) + cell_km
    across = float(np.ptp(minor @ pts)) + cell_km
    axis_az = math.degrees(math.atan2(major[0], major[1])) % 180
    edge = bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any())
    return mask, {"cells": int(len(I)), "area_km2": round(area), "length_km": round(along, 1),
                  "width_km": round(across, 1), "long_axis_deg": round(axis_az, 1), "touches_grid_edge": edge,
                  "lat_range": [round(float(lats[I].min()), 3), round(float(lats[I].max()), 3)],
                  "lon_range": [round(float(lons[J].min()), 3), round(float(lons[J].max()), 3)]}


def cell_of(lats, lons, lat, lon):
    import numpy as np
    if not (lats[0] <= lat <= lats[-1] and lons[0] <= lon <= lons[-1]):
        return None
    return int(np.argmin(abs(lats - lat))), int(np.argmin(abs(lons - lon)))


def region_geojson(path, lats, lons, mask):
    import numpy as np
    hl, ho = (lats[1] - lats[0]) / 2, (lons[1] - lons[0]) / 2
    polys = [[[[float(lons[j] - ho), float(lats[i] - hl)], [float(lons[j] + ho), float(lats[i] - hl)],
               [float(lons[j] + ho), float(lats[i] + hl)], [float(lons[j] - ho), float(lats[i] + hl)],
               [float(lons[j] - ho), float(lats[i] - hl)]]] for i, j in zip(*np.nonzero(mask))]
    with open(path, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
            "name": "90% credible region (inference)"}, "geometry": {"type": "MultiPolygon", "coordinates": polys}}]},
            fh)


def cmd_tdoa(a):
    import numpy as np
    t0, t1 = parse_utc(a.start), parse_utc(a.end)
    if t1 <= t0:
        L.die("--end must be after --start")
    if (t1 - t0).total_seconds() > 6 * 3600:
        L.die("window over 6 h: impulsive location needs a gate of minutes to hours around a suspected event")
    a.center = tuple(float(x) for x in a.center.split(",")) if a.center else TA_545A
    a.celerity = tuple(float(x) for x in a.celerity.split("-"))
    notes, meta = [], {}
    if a.picks:
        stations = read_picks(a.picks)
        meta["picks_file"] = os.path.abspath(a.picks)
        for s in stations:
            s["picks"] = [(t, w) for t, w in s["picks"] if t0 <= t <= t1]
    else:
        rows, surl = bdf_stations(a.center[0], a.center[1], a.radius_km, t0, t1, a.refresh)
        if len(rows) < a.min_stations:
            raise L.NoData("%d BDF stations within %g km active in the window; need %d"
                           % (len(rows), a.radius_km, a.min_stations))
        pad = datetime.timedelta(seconds=2 * a.lta)
        L.gate([(L.dataselect_url(r["net"], r["sta"], r["loc"], "BDF", t0 - pad, t1), r["sps"],
                 (t1 - t0 + pad).total_seconds()) for r in rows], a.yes)
        stations = []
        for r in rows:
            p = stalta_picks(r, t0, t1, a)
            name = "%s.%s.%s.BDF" % (r["net"], r["sta"], r["loc"])
            if p is None:
                notes.append("%s: no data in the window" % name)
                continue
            tot = sum(x for _, x in p) or 1
            # Rounded to CSV precision so a --csv export fed back through --picks reproduces this run exactly.
            stations.append({"station": name, "lat": r["lat"], "lon": r["lon"],
                             "picks": [(t.replace(microsecond=t.microsecond // 1000 * 1000), round(x / tot, 4))
                                       for t, x in p], "peaks": [round(x, 2) for _, x in p]})
        meta["stations_url"] = surl
        if a.csv:
            write_picks(a.csv, stations)
    picked = [s for s in stations if s["picks"]]
    w_s = (t1 - t0).total_seconds()
    res = {**meta, "start": L.iso(t0), "end": L.iso(t1), "band": a.band, "center": a.center,
           "params": {"sta_s": a.sta, "lta_s": a.lta, "on": a.on, "off": a.off, "top_k": a.top_k,
                      "sigma_s": a.sigma, "celerity_kms": a.celerity, "celerity_model": a.celerity_model,
                      "eps": a.eps, "box_deg": a.box_deg, "step_deg": a.step_deg, "dt_s": a.dt,
                      "radius_km": a.radius_km, "min_stations": a.min_stations},
           "stations": [{"station": s["station"], "lat": s["lat"], "lon": s["lon"],
                         "picks": [L.iso(t) + ".%03d" % (t.microsecond // 1000) for t, _ in s["picks"]],
                         "peak_stalta": s.get("peaks")} for s in stations],
           "notes": notes, "validated": TDOA_VALIDATED, "retrieved": L.today()}
    if len(picked) < a.min_stations:
        res.update(status="none", located=False,
                   reason="%d stations have picks; need %d" % (len(picked), a.min_stations))
        return res
    g = locate(picked, t0, a, w_s)
    lats, lons, post = g["lats"], g["lons"], g["post"]
    i, j = np.unravel_index(int(np.argmax(post)), post.shape)
    map_ll = (float(lats[i]), float(lons[j]))
    t_org = t0 + datetime.timedelta(seconds=float(g["best_t"][i, j]))
    n = i * len(lons) + j
    assoc = []
    for si, s in enumerate(picked):
        d = float(g["D"][si, n])
        c = g["best_c"][i, j]
        best = None
        for k, (t, w) in enumerate(s["picks"]):
            tt = (t - t_org).total_seconds()
            pred = d / c if not math.isnan(c) else d / (sum(a.celerity) / 2)
            dens = (1 - a.eps) * w * math.exp(-0.5 * ((tt - pred) / a.sigma) ** 2) / (a.sigma * math.sqrt(2 * math.pi))
            if not math.isnan(c) and dens > g["floor"] and (best is None or dens > best[0]):
                best = (dens, t, tt - pred, tt)
            if math.isnan(c) and d / a.celerity[1] - 2 * a.sigma <= tt <= d / a.celerity[0] + 2 * a.sigma:
                if best is None or w > best[0]:
                    best = (w, t, None, tt)
        assoc.append({"station": s["station"], "km": round(d, 1), "associated": best is not None,
                      "pick": (L.iso(best[1]) if best else None),
                      "apparent_celerity_kms": (round(d / best[3], 3) if best and best[3] > 0 else None),
                      "residual_s": (round(best[2], 1) if best and best[2] is not None else None)})
    n_assoc = sum(x["associated"] for x in assoc)
    mask, reg = region_stats(lats, lons, post, 0.9, map_ll)
    pm = (float((post.sum(axis=1) * lats).sum()), float((post.sum(axis=0) * lons).sum()))
    c_map = None if math.isnan(g["best_c"][i, j]) else round(float(g["best_c"][i, j]), 3)
    res.update(map=[round(map_ll[0], 4), round(map_ll[1], 4)],
               posterior_mean=[round(pm[0], 4), round(pm[1], 4)], origin_time=L.iso(t_org),
               celerity_at_map=c_map, associated_stations=n_assoc, association=assoc, region90=reg)
    lo_lat, lo_lon = a.center
    res["map_from_center"] = {"km": round(L.haversine_km(lo_lat, lo_lon, *map_ll), 1),
                              "bearing_deg": round(L.bearing(lo_lat, lo_lon, *map_ll), 1)}
    # For a source outside the ring, range trades off against celerity and origin time, so the region runs
    # out to the grid edge; its bearing span from the center can still be tight, so report it separately.
    I, J = np.nonzero(mask)
    far = [L.bearing(lo_lat, lo_lon, float(lats[ii]), float(lons[jj])) for ii, jj in zip(I, J)
           if L.haversine_km(lo_lat, lo_lon, float(lats[ii]), float(lons[jj])) > 2 * a.step_deg * 111.195]
    span, b0, b1 = spread_of(far)
    reg["bearing_span_from_center"] = (None if span >= 180 or b0 is None else
                                       {"from": round(b0, 1), "to": round(b1, 1), "width_deg": round(span, 1)})
    bspan = reg["bearing_span_from_center"]
    if n_assoc < a.min_stations:
        status, reason = "none", "only %d stations associate at the most likely point; need %d" % (
            n_assoc, a.min_stations)
    elif not reg["touches_grid_edge"]:
        status, reason = "located", None
    elif bspan and bspan["width_deg"] <= a.max_bearing_span:
        status, reason = "bearing_only", "the 90% region reaches the grid edge; range is unconstrained"
    else:
        status, reason = "none", "the 90%% region reaches the grid edge and spans %s as seen from the center" % (
            "%.0f°" % bspan["width_deg"] if bspan else "all directions")
    res.update(status=status, located=status == "located", reason=reason)
    if reg["touches_grid_edge"]:
        notes.append("The 90% region reaches the grid edge: it is unbounded at this --box-deg; area, length and "
                     "the most likely point are not meaningful.")
    if c_map is not None and min(abs(c_map - a.celerity[0]), abs(c_map - a.celerity[1])) < 1e-6:
        notes.append("Celerity at the most likely point sits on the prior bound (%.2f km/s): range there is set by "
                     "the prior, not the data." % c_map)
    if t0 >= datetime.datetime(2012, 8, 31) and not a.picks and lo_lat == TA_545A[0] and lo_lon == TA_545A[1]:
        notes.append("TA.546A and TA.646A infrasound ends 2012-08-30/31 in the archive, just after Hurricane Isaac's landfall; "
                     "after that the ring has no stations east of 545A.")
    if a.truth:
        tl = tuple(float(x) for x in a.truth.split(","))
        cl = cell_of(lats, lons, *tl)
        inside = bool(cl is not None and mask[cl])
        d_region = 0.0
        if not inside:
            I, J = np.nonzero(mask)
            d_region = float(hav_np(tl[0], tl[1], lats[I], lons[J]).min())
        res["truth"] = {"lat": tl[0], "lon": tl[1], "error_km": round(L.haversine_km(*tl, *map_ll), 1),
                        "bearing_from_center_deg": round(L.bearing(lo_lat, lo_lon, *tl), 1),
                        "bearing_error_deg": round(ang_diff(L.bearing(lo_lat, lo_lon, *tl),
                                                            L.bearing(lo_lat, lo_lon, *map_ll)), 1),
                        "mean_error_km": round(L.haversine_km(*tl, *pm), 1), "in_region90": inside,
                        "km_outside_region90": round(d_region, 1),
                        "containment_informative": not reg["touches_grid_edge"],
                        "relative_density": (round(float(post[cl] / post.max()), 4) if cl else None)}
    cands = load_candidates(a, lo_lat, lo_lon)
    for c in cands:
        cl = cell_of(lats, lons, c["lat"], c["lon"])
        c["relative_density"] = round(float(post[cl] / post.max()), 4) if cl else 0.0
        c["in_90"] = bool(cl is not None and mask[cl])
    cands.sort(key=lambda c: -c["relative_density"])
    res["candidates"] = cands
    if a.geojson:
        region_geojson(a.geojson, lats, lons, mask)
        res["geojson"] = os.path.abspath(a.geojson)
    return res


# ---------------------------------------------------------------- health

def cmd_health(a):
    res = L.cmd_health(a)
    y = datetime.date.today() - datetime.timedelta(days=3)
    z = y + datetime.timedelta(days=1)
    url = L.q(ASOS, station="MSY", data="sknt", year1=y.year, month1=y.month, day1=y.day, year2=z.year,
              month2=z.month, day2=z.day, tz="UTC", format="onlycomma", latlon="no", missing="M")
    try:
        body = L._get(url, timeout=60)
        res["checks"].append({"service": "iem-asos", "up": True, "bytes": len(body), "url": url})
    except (L.SourceDown, L.NoData) as e:
        res["checks"].append({"service": "iem-asos", "up": False, "error": str(e), "url": url})
    return res


# ---------------------------------------------------------------- text output

INFER = "Inference, not a location: a bearing arc from one site, conditional on the model and data in this run."


def show(cmd, res):
    p = print
    if cmd == "health":
        L.show("health", res)
        return
    if cmd == "features":
        p("%s  %d hourly rows (%d hours expected), %s %s, %s .. %s" % (
            res["nslc"], len(res["rows"]), res["expected_hours"], res["hours"], res["tz"], res["days"][0],
            res["days"][-1]))
        for hz in sorted({r["hz"] for r in res["rows"]}):
            pr = sorted(r["prominence_db"] for r in res["rows"] if r["hz"] == hz)
            p("  %8.3f Hz  median prominence %+.1f dB  (p10 %+.1f, p90 %+.1f)" % (
                hz, pr[len(pr) // 2], pr[len(pr) // 10], pr[min(len(pr) - 1, 9 * len(pr) // 10)]))
        for n in res["notes"]:
            p("  note: " + n)
        if res["csv"]:
            p("  wrote %s (columns %s)" % (res["csv"], ",".join(FEATURE_COLS)))
        return
    if cmd == "bearing":
        p("%s  %s x %s (azimuths %s), %d hour chunks, %s %s, %s .. %s" % (
            res["station"], res["infra"], "/".join(res["horizontals"]),
            "/".join("%g°" % x for x in res["azimuths_deg"]), res["chunks"], res["hours"], res["tz"],
            res["days"][0], res["days"][-1]))
        if not res["validated"]:
            p("  UNVALIDATED: this method has not passed the known-direction test (SKILL.md). Axes below are "
              "diagnostics, not bearings.")
        p("  multiple coherence of pressure on (N, E), pooled:")
        for r in res["coherence_table"]:
            p("    %9.3f Hz  %.3f" % (r["hz"], r["multiple_coherence"]))
        for r in res["at"]:
            p("  at %.3f Hz: pooled coherence %.3f; %d of %d hours >= %.2f" % (
                r["hz"], r["pooled_multiple_coherence"], r["hours_kept"], r["hours_total"], res["min_coherence"]))
            if r["axis_deg"] is not None:
                if res["validated"]:
                    p("    axis %.0f° ± %.0f° (axial R %.2f), i.e. %.0f° or %.0f°; 180° ambiguity open" % (
                        r["axis_deg"], r["axis_sd_deg"], r["rbar"], *r["back_azimuth_candidates"]))
                else:
                    p("    axis withheld (unvalidated); per-hour values are in --json for method testing only")
        p("Coherence below ~0.5 means the horizontals are not recording this pressure field; no axis follows.")
        p("Source: EarthScope fdsnws dataselect + station response; retrieved %s" % res["retrieved"])
        return
    if cmd == "validate":
        p("%s bearing validation on thunder from NEXRAD %s storm cells, %g-%g Hz, coherence >= %.2f" % (
            res["station"], res["radar"], *res["band"], res["min_coherence"]))
        for e in res["events"]:
            r = e.get("result")
            p("  %s  %2d cells, %4.1f km at %5.1f° (spread %4.1f°)  %3s seg  %s" % (
                e["hour_utc"], e["cells"], e["median_km"], e["truth_deg"], e["spread_deg"], e.get("loud_segments", "-"),
                e.get("status") or ("no coherent bins" if r is None else "axis %5.1f° (%d bins, lin %.2f) err %4.1f°; in-phase %5.1f° "
                 "(%+.0f° from truth)" % (r["axis_deg"], r["bins"], r["linearity"], e["axial_error_deg"],
                                          r["in_phase_deg"], e["in_phase_minus_truth_deg"]))))
        p("  %d of %d scored events within ±20°; in-phase vector points %s the source; %s" % (
            res["within_20"], res["scored"], {"toward": "toward", "away": "away from"}.get(res["in_phase_points"], "inconsistently relative to"),
            "PASS" if res["passes"] else "FAIL"))
        p("Source: IEM NEXRAD storm attributes (%s); EarthScope dataselect; retrieved %s" % (
            res["nst_urls"][0], res["retrieved"]))
        return
    if cmd == "wind-scan":
        src =res.get("nslc") or res.get("features")
        if res["candidates"]:
            p("Candidates (%d) span %.0f° as seen from %.4f, %.4f." % (
                len(res["candidates"]), res["candidate_spread_deg"], res["station_lat"], res["station_lon"]))
        p("%s  %.3f Hz  prominence vs %s wind, %d hours over %d nights (calm %.0f%%)" % (
            src, res["freq_hz"], res["asos"], res["n_hours"], res["n_days"], 100 * res["calm_fraction"]))
        p("  wind dependence: LR %.1f, permutation p = %.3f (%d night-block permutations, seed %d)" % (
            res["lr"], res["p_value"], res["permutations"], res["seed"]))
        p("  most likely back-azimuth %d°, %+.2f dB per m/s of along-path wind" % (
            res["map_back_azimuth"], res["b_db_per_mps_at_map"]))
        p("  90%% arc (%d°): %s" % (res["arc90_width_deg"], ", ".join(
            "%d°..%d°" % tuple(x) if x[0] != x[1] else "%d°" % x[0] for x in res["arc90"])))
        p("  posterior mass by 30° sector: " + "  ".join("%d:%.2f" % (s["from"], s["mass"]) for s in res["sectors"]))
        for c in res["candidates"][:15]:
            p("    %5.1f°  %5.2f km  density %.2f%s  %s" % (c["bearing"], c["km"], c["relative_density"],
                                                         "  in 90%" if c["in_90"] else "", c["name"][:60]))
        for n in res["notes"]:
            p("  note: " + n)
        p(INFER)
        p("Source: EarthScope archive via lf-acoustic-baselines; IEM ASOS %s; retrieved %s" % (
            res["asos_url"], res["retrieved"]))
        return
    if cmd == "tdoa":
        pr = res["params"]
        p("tdoa %s .. %s UTC, %s Hz, STA/LTA %g/%g s on %g, top %d picks/station; sigma %g s, celerity %g-%g km/s "
          "(%s)" % (res["start"], res["end"], res["band"], pr["sta_s"], pr["lta_s"], pr["on"], pr["top_k"],
                    pr["sigma_s"], *pr["celerity_kms"], pr["celerity_model"]))
        for s in res["stations"]:
            p("  %-18s %8.4f %9.4f  %s" % (s["station"], s["lat"], s["lon"], ", ".join(
                x[11:] + ("" if not s.get("peak_stalta") else " (%.1f)" % s["peak_stalta"][k])
                for k, x in enumerate(s["picks"])) or "no picks"))
        for n in res["notes"]:
            p("  note: " + n)
        if not res["validated"]:
            p("  UNVALIDATED: tdoa failed its pre-declared ground-truth tests (SKILL.md). Treat any region below as "
              "a diagnostic, not a finding.")
        if "map" not in res:
            p("No location: %s." % res["reason"])
            return
        if res["status"] == "none":
            p("No location: %s. The grid result below is shown for diagnosis only." % res["reason"])
        elif res["status"] == "bearing_only":
            p("Direction only: %s. The most likely point below is not a location." % res["reason"])
        r = res["region90"]
        p("  most likely %.4f, %.4f (%.1f km at %.0f° from center), origin %s UTC, celerity %s" % (
            *res["map"], res["map_from_center"]["km"], res["map_from_center"]["bearing_deg"], res["origin_time"],
            "%.2f km/s" % res["celerity_at_map"] if res["celerity_at_map"] else "per path"))
        p("  90%% region: %d km², %.0f km long x %.0f km wide, long axis %.0f°; lat %.2f..%.2f, lon %.2f..%.2f%s" % (
            r["area_km2"], r["length_km"], r["width_km"], r["long_axis_deg"], *r["lat_range"], *r["lon_range"],
            "  (reaches grid edge: unbounded)" if r["touches_grid_edge"] else ""))
        b = r.get("bearing_span_from_center")
        if b:
            p("  90%% region spans %.0f°..%.0f° (%.0f°) as seen from the grid center" % (b["from"], b["to"], b["width_deg"]))
        p("  %d stations associate at the most likely point:" % res["associated_stations"])
        for x in res["association"]:
            p("    %-18s %6.1f km  %s" % (x["station"], x["km"], "pick %s, apparent %.3f km/s%s" % (
                x["pick"][11:], x["apparent_celerity_kms"] or float("nan"),
                "" if x["residual_s"] is None else ", residual %+.1f s" % x["residual_s"]) if x["associated"]
                else "-"))
        if "truth" in res:
            t = res["truth"]
            p("  truth %.4f, %.4f (%.1f° from center): error %.1f km (posterior mean %.1f km), bearing error %.1f°; %s" % (
                t["lat"], t["lon"], t["bearing_from_center_deg"], t["error_km"], t["mean_error_km"],
                t["bearing_error_deg"],
                ("inside the 90% region" if t["in_region90"] else "OUTSIDE the 90%% region by %.1f km" %
                 t["km_outside_region90"]) + ("" if t["containment_informative"] else
                                               " (not informative: the region is unbounded)")))
        for c in res["candidates"][:15]:
            p("    density %.3f%s  %s" % (c["relative_density"], "  in 90%" if c["in_90"] else "", c["name"][:70]))
        if res.get("geojson"):
            p("  wrote %s" % res["geojson"])
        p("Inference, not a location: a credible region conditional on the picks, celerity prior and pick error "
          "in this run.")
        p("Source: EarthScope fdsnws station + dataselect (BDF)%s; retrieved %s" % (
            "" if "stations_url" not in res else " %s" % res["stations_url"], res["retrieved"]))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="bypass the cache")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    win = argparse.ArgumentParser(add_help=False)
    win.add_argument("--start")
    win.add_argument("--end", help="spread --days across start..end instead of consecutive days")
    win.add_argument("--hours", default="00-04", help="hour range each day, end exclusive (default 00-04 local)")
    win.add_argument("--utc", action="store_true", help="--hours are UTC, not %s" % L.LOCAL_TZ)
    win.add_argument("--yes", action="store_true", help="allow a miniSEED download over %d MB" % L.GATE_MB)
    win.add_argument("--allow-epoch-change", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *x, **k: _add(*x, parents=[common] + k.pop("extra", []), **k)

    sub.add_parser("health")

    s = sub.add_parser("features", extra=[win])
    s.add_argument("nslc")
    s.add_argument("--freqs", required=True)
    s.add_argument("--days", type=int, default=3)
    s.add_argument("--csv")

    s = sub.add_parser("bearing", extra=[win])
    s.add_argument("station", help="NET.STA")
    s.add_argument("--freqs", required=True)
    s.add_argument("--days", type=int, default=1)
    s.add_argument("--band", help="lo-hi Hz for the coherence table")
    s.add_argument("--min-coherence", type=float, default=0.5)

    s = sub.add_parser("validate", extra=[win])
    s.add_argument("station", help="NET.STA")
    s.add_argument("--radar", default="LIX", help="NEXRAD id for storm cells (default LIX, Slidell)")
    s.add_argument("--radius-km", type=float, default=25)
    s.add_argument("--min-dbz", type=float, default=50)
    s.add_argument("--max-spread", type=float, default=30, help="max arc (°) of strong cells within 2x radius")
    s.add_argument("--max-events", type=int, default=8)
    s.add_argument("--band", default="1-10")
    s.add_argument("--min-coherence", type=float, default=0.5)
    s.add_argument("--min-bins", type=int, default=5)
    s.add_argument("--seg-s", type=float, default=10, help="segment length for loud-segment selection")
    s.add_argument("--min-ratio", type=float, default=10, help="segment band power over the hour median")
    s.add_argument("--top", type=float, default=0.05, help="max share of segments kept")

    s = sub.add_parser("wind-scan", extra=[win])
    s.add_argument("nslc", nargs="?")
    s.add_argument("--features", help="hourly feature CSV (%s) instead of the archive" % ",".join(FEATURE_COLS))
    s.add_argument("--freq", type=float, required=True)
    s.add_argument("--days", type=int, default=20)
    s.add_argument("--asos", default="MSY", help="IEM ASOS station id (default MSY)")
    s.add_argument("--candidates", help="JSON from `eric.py sources ... --json`")
    s.add_argument("--candidate", action="append", help="name,lat,lon (repeatable)")
    s.add_argument("--permutations", type=int, default=200)
    s.add_argument("--seed", type=int, default=1)

    s = sub.add_parser("tdoa", help="locate an impulsive event from BDF arrival times (TA ring, 2011-03..2012-12)")
    s.add_argument("--start", required=True, help="pick window start, UTC (e.g. 2012-11-16T14:55)")
    s.add_argument("--end", required=True, help="pick window end, UTC; keep it to minutes or hours")
    s.add_argument("--center", help="lat,lon of the station search and grid center (default TA.545A)")
    s.add_argument("--radius-km", type=float, default=100, help="BDF stations within this radius (default 100)")
    s.add_argument("--band", default="2-5", help="bandpass Hz before STA/LTA (default 2-5)")
    s.add_argument("--sta", type=float, default=2, help="STA window s (default 2)")
    s.add_argument("--lta", type=float, default=60, help="LTA window s (default 60)")
    s.add_argument("--on", type=float, default=3.0, help="trigger-on STA/LTA ratio (default 3)")
    s.add_argument("--off", type=float, default=1.5, help="trigger-off ratio (default 1.5)")
    s.add_argument("--top-k", type=int, default=3, help="strongest triggers kept per station (default 3)")
    s.add_argument("--sigma", type=float, default=4, help="pick and path error s (default 4)")
    s.add_argument("--celerity", default="0.28-0.34", help="km/s range (default 0.28-0.34)")
    s.add_argument("--celerity-model", choices=("shared", "independent"), default="shared",
                   help="one celerity for all paths (default), or one per path")
    s.add_argument("--eps", type=float, default=0.1, help="prior probability a station has no true pick")
    s.add_argument("--box-deg", type=float, default=2.0, help="grid half-width in degrees (default 2)")
    s.add_argument("--step-deg", type=float, default=0.05, help="grid spacing in degrees (default 0.05)")
    s.add_argument("--dt", type=float, default=2, help="origin-time step s (default 2)")
    s.add_argument("--min-stations", type=int, default=4)
    s.add_argument("--max-bearing-span", type=float, default=30,
                   help="widest bearing span (°) still reported as direction-only when range is unbounded")
    s.add_argument("--picks", help="arrival picks CSV (%s) instead of the archive" % ",".join(PICK_COLS))
    s.add_argument("--csv", help="write the archive picks to this CSV")
    s.add_argument("--truth", help="lat,lon of a known source: report the error in km")
    s.add_argument("--candidates", help="JSON from `eric.py sources ... --json`")
    s.add_argument("--candidate", action="append", help="name,lat,lon (repeatable)")
    s.add_argument("--geojson", help="write the 90%% region as GeoJSON")
    s.add_argument("--yes", action="store_true", help="allow a miniSEED download over %d MB" % L.GATE_MB)

    args = ap.parse_args()
    if args.cmd in ("features", "bearing", "validate") and not args.start:
        L.die("--start is required")
    fn = {"health": cmd_health, "features": cmd_features, "bearing": cmd_bearing,
          "wind-scan": cmd_wind_scan, "validate": cmd_validate, "tdoa": cmd_tdoa}[args.cmd]
    try:
        res = fn(args)
    except L.SourceDown as e:
        L.die("source unavailable: %s" % e, 5)
    except L.NoData as e:
        L.die("no data: %s" % e, 3)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
