---
name: firms-active-fire
description: Query NASA FIRMS for satellite active-fire detections (VIIRS 375 m / MODIS 1 km) over a location and date range, returning fire radiative power (FRP), brightness, confidence, and per-overpass UTC timestamps as a table plus a saved CSV
allowed-tools: Bash, AskUserQuestion, Read
---

# NASA FIRMS Active-Fire Lookup

Given a **location** and a **date range**, query the NASA FIRMS Area API for satellite
active-fire / thermal-anomaly detections and report them as a ranked table (with **fire
radiative power**, brightness temperature, confidence, and per-overpass **UTC** timestamps),
saving the raw CSV.

This is the objective heat-signature companion to `bayou:satellite-imagery`: optical true-color
imagery can't distinguish steam from combustion, quantify heat, or timestamp an event — FIRMS
detects the actual hot pixels. Useful for flares, industrial fires, wildfires, and confirming a
heat source over a facility during an incident window.

Free, but needs a **FIRMS map key** (instant self-serve signup — see Step 2).

## Tools available in this environment

- `curl` and `python3`, invoked by name off `PATH` (stdlib only — `csv`, `json`, `math`,
  `datetime`). No gdal, no third-party packages. Invoke them by name; if `command -v` comes up
  empty (a non-interactive shell's `PATH` often omits Homebrew), probe `/opt/homebrew/bin`,
  `/usr/local/bin`, `/usr/bin` as fallbacks rather than hardcoding one prefix.

## Step 0: Parse arguments

- **Location** — one of:
  - a `lat,lon` pair (e.g. `29.9989,-90.4062`) — use directly;
  - an address or place name — geocode with Nominatim (Step 1);
  - a **facility name** (e.g. "Shell Norco") — prefer `bayou:facility-coordinates` to resolve
    lat/lon, then continue here.
- **Date range** — a single date `YYYY-MM-DD`, or a start/end range (e.g.
  `2025-12-21..2026-01-15`). A single date is treated as a short window forward from that date.
- **Radius** (optional) — default a ~0.05° box (~5 km) around the point. Use a larger box
  (0.2–1.0°) for regional fire context (wildfire fronts, wide smoke events).
- **Sensors** (optional) — default **all VIIRS 375 m** (`SNPP` + `NOAA20` + `NOAA21`): finest
  resolution and the most daily overpasses. Add MODIS 1 km only if asked or for pre-2012 dates.

If a place name is ambiguous or missing a state/city, **ask** before querying — a wrong match
silently produces confident-looking wrong detections.

## Step 1: Resolve location → lat/lon and build a BBOX

Skip geocoding if the user already gave `lat,lon`. Otherwise use OpenStreetMap Nominatim (free,
no key; descriptive `User-Agent`, ~1 req/sec):

```bash
curl -s --get "https://nominatim.openstreetmap.org/search" \
  --data-urlencode "q=Shell Norco, Norco, LA" \
  --data-urlencode "format=json" \
  --data-urlencode "limit=3" \
  -H "User-Agent: bayou-firms-active-fire/1.0 (research lookup)" | python3 -m json.tool
```

Build a bounding box from the point and a half-box size `H` (degrees). **FIRMS wants
`west,south,east,north` = `minlon,minlat,maxlon,maxlat`:**

```bash
python3 -c "
lat, lon, H = 29.9989, -90.4062, 0.05
minlon, maxlon = lon - H, lon + H
minlat, maxlat = lat - H, lat + H
print(f'{minlon},{minlat},{maxlon},{maxlat}')   # FIRMS AREA order: W,S,E,N
"
```

## Step 2: Get the FIRMS map key

Read `~/.claude/bayou-credentials.md` and use the `FIRMS_MAP_KEY` value if present.

**If it is absent**, tell the user how to get one (free, instant) and offer to save it:

> Get a free FIRMS map key at **https://firms.modaps.eosdis.nasa.gov/api/map_key/** — enter your
> email and the key is issued on the page (also emailed). It's instant, no approval wait. Limit is
> 5000 transactions per 10-minute window. Paste the key here and I'll store it.

When the user pastes a key, **verify it** before saving (this also proves the limit isn't
exhausted):

```bash
curl -s "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=PASTE_KEY" | python3 -m json.tool
```

A valid key returns a JSON status with the current/allowed transaction counts; an invalid one
returns an error. On success, append this section to `~/.claude/bayou-credentials.md` (keep the
file private, never commit it):

```
## NASA FIRMS (firms.modaps.eosdis.nasa.gov)

Free instant map key. Request at https://firms.modaps.eosdis.nasa.gov/api/map_key/
(enter email; key issued on the page / by email). Limit 5000 transactions / 10 min.
Check status: https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=<key>

FIRMS_MAP_KEY: <key>
```

## Step 3: Pick NRT vs archive (SP) and query

FIRMS splits data into **NRT** (near-real-time, roughly the last ~2 months) and **SP** (standard
processing / archive, older). Choose by how old the date is; confirm the exact cutoffs and valid
date ranges per source from the data-availability endpoint:

```bash
curl -s "https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/PASTE_KEY/all"
```

- Recent dates (within the NRT window) → `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`,
  `VIIRS_NOAA21_NRT`, `MODIS_NRT`.
- Older dates → `VIIRS_SNPP_SP`, `VIIRS_NOAA20_SP`, `MODIS_SP` (NOAA21 SP may lag — check
  availability). If a date falls right at the NRT/SP boundary, try both and merge.

**Area API shape** (`DAY_RANGE` is 1–5 days; `DATE` is the window start):

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[W,S,E,N]/[DAY_RANGE]/[DATE]
```

Loop the requested range in ≤5-day windows, once per selected source, and concatenate the CSV
(keeping only the first header). Example driver:

```bash
FIRMS_MAP_KEY="..."                  # from ~/.claude/bayou-credentials.md
AREA="-90.4562,29.9489,-90.3562,30.0489"   # W,S,E,N
SOURCES="VIIRS_SNPP_SP VIIRS_NOAA20_SP"    # SP because the flare window is >2 months old
START="2025-12-20"; END="2026-01-19"
OUT="firms_29.9989_-90.4062_${START}_${END}.csv"

python3 - "$FIRMS_MAP_KEY" "$AREA" "$START" "$END" "$OUT" $SOURCES <<'PY'
import sys, subprocess, datetime as dt
key, area, start, end, out = sys.argv[1:6]
sources = sys.argv[6:]
d0 = dt.date.fromisoformat(start); d1 = dt.date.fromisoformat(end)
rows, header = [], None
cur = d0
while cur <= d1:
    span = min(5, (d1 - cur).days + 1)          # FIRMS max 5-day window per call
    for src in sources:
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
               f"{key}/{src}/{area}/{span}/{cur.isoformat()}")
        txt = subprocess.run(["curl", "-s", url], capture_output=True, text=True).stdout
        lines = [l for l in txt.splitlines() if l.strip()]
        if not lines:
            continue
        if not lines[0].lower().startswith("latitude") and "," not in lines[0]:
            print(f"  ! {src} {cur}: {txt.strip()[:200]}", file=sys.stderr)   # error string
            continue
        header = header or lines[0]
        rows.extend(lines[1:])
    cur += dt.timedelta(days=span)
if header:
    open(out, "w").write("\n".join([header] + rows) + "\n")
    print(f"Wrote {len(rows)} rows to {out}")
else:
    print("No CSV returned (no detections, or all calls errored).")
PY
```

Adjust `SOURCES`, `AREA`, and the date range per the request. Re-check `mapkey_status` if you're
running many windows (each call is ≥1 transaction against the 5000/10-min limit).

## Step 4: Parse, filter, and report

FIRMS returns detections whose **pixel center** falls in the box (and it can return a slightly
padded set) — filter to the exact BBOX, normalize VIIRS vs MODIS column names, sort by time, and
group by overpass:

```bash
python3 - "$OUT" -90.4562 29.9489 -90.3562 30.0489 <<'PY'
import sys, csv
path = sys.argv[1]
minlon, minlat, maxlon, maxlat = map(float, sys.argv[2:6])
rows = list(csv.DictReader(open(path)))
def num(r, *keys):
    for k in keys:
        if k in r and r[k] not in ("", None):
            try: return float(r[k])
            except ValueError: return r[k]
    return ""
kept = []
for r in rows:
    lat, lon = float(r["latitude"]), float(r["longitude"])
    if not (minlat <= lat <= maxlat and minlon <= lon <= maxlon):
        continue
    kept.append({
        "date": r.get("acq_date",""), "time": r.get("acq_time","").zfill(4),
        "sat": r.get("satellite",""), "inst": r.get("instrument",""),
        "lat": lat, "lon": lon,
        "bright_K": num(r, "bright_ti4", "brightness"),
        "frp": num(r, "frp"), "conf": r.get("confidence",""),
        "dn": r.get("daynight",""),
    })
kept.sort(key=lambda x: (x["date"], x["time"]))
if not kept:
    print("No active-fire detections inside the exact BBOX for this window.")
else:
    print(f"{'date':<11}{'UTC':<6}{'sat':<5}{'inst':<7}{'lat':>9}{'lon':>10}"
          f"{'brightK':>9}{'FRP_MW':>8}{'conf':>6}{'d/n':>5}")
    for k in kept:
        frp = f"{k['frp']:.1f}" if isinstance(k['frp'], float) else "-"
        bk  = f"{k['bright_K']:.1f}" if isinstance(k['bright_K'], float) else "-"
        t   = f"{k['time'][:2]}:{k['time'][2:]}"
        print(f"{k['date']:<11}{t:<6}{k['sat']:<5}{k['inst']:<7}{k['lat']:>9.4f}"
              f"{k['lon']:>10.4f}{bk:>9}{frp:>8}{str(k['conf']):>6}{k['dn']:>5}")
    frps = [k['frp'] for k in kept if isinstance(k['frp'], float)]
    overpasses = sorted({(k['date'], k['time']) for k in kept})
    span = f"{kept[0]['date']} → {kept[-1]['date']}"
    print(f"\n{len(kept)} detection(s) across {len(overpasses)} overpass(es), {span}."
          + (f" Peak FRP {max(frps):.1f} MW." if frps else ""))
PY
```

Report to the user:
- The **table** above (date, UTC time, satellite/instrument, lat/lon, brightness K, **FRP in MW**,
  confidence, day/night).
- **Summary**: detection count, number of distinct overpasses, date span, peak FRP.
- The **saved CSV path** (in the CWD; note it can be moved/renamed).
- **Caveats — always state these:**
  - A detection is a **hot pixel** at **375 m (VIIRS) / 1 km (MODIS)** — not a resolved flame and
    not tied to a specific stack or unit; several nearby sources blur into one pixel.
  - **FRP** is instantaneous fire radiative power (MW) at the moment of overpass, **not** total
    emitted mass or duration.
  - **Absence of detections is not proof of no fire.** The satellite may have passed between
    detections, the scene may be cloud-obscured, or the heat may fall below the detection
    threshold — and a small **elevated flare can read cooler** to the sensor than a broad wildfire
    face. Combine with the overpass timing and the optical imagery.
  - Times are **UTC** (convert to local for the narrative — Norco/CST is UTC−6, CDT UTC−5).
  - **Confidence encodings differ:** VIIRS uses `l`/`n`/`h` (low/nominal/high); MODIS uses a
    numeric 0–100.

## Step 5: Empty / error handling

- **Header-only or empty CSV** → no detections in the window. Report the "absence ≠ no fire"
  caveat and suggest widening the box/date range or adding MODIS. This is a normal result, not a
  failure.
- **Plaintext (non-CSV) response** → an API error. Common cases:
  - `Invalid MAP_KEY` / auth error → re-check `mapkey_status`; the key may be wrong or the
    5000/10-min limit exhausted (wait and retry).
  - Date out of range for the source → switch NRT↔SP per the `data_availability` output.
  - Malformed area/params → recheck the `W,S,E,N` order and value ranges.
  The driver in Step 3 prints any such error line to stderr (`! SOURCE date: ...`).

## Notes & limits

- FIRMS is a free, shared NASA service — be polite: batch into ≤5-day windows, don't hammer, and
  watch the 5000-transaction / 10-minute budget (`mapkey_status`).
- Sensors & resolution: **VIIRS 375 m** (SNPP, NOAA-20, NOAA-21) is preferred for small/industrial
  sources; **MODIS 1 km** (Terra/Aqua) extends coverage back to ~2000 for historical events.
- Pair with `bayou:satellite-imagery` (optical true color / thermal-anomaly imagery) for the same
  location+date to combine a visual plume with the hot-pixel/FRP evidence.

$ARGUMENTS
