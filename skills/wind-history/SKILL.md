---
name: wind-history
description: Look up historical (forensic) wind direction and speed at a specific date/time and place, and state whether wind carried a plume from a facility toward a specific receptor
allowed-tools: Bash, AskUserQuestion
---

# Historical Wind Lookup (Forensic)

Pull actual recorded wind observations for a past date/time window from the Iowa Environmental Mesonet's ASOS/AWOS archive — a mirror of NWS surface station observations going back decades. No API key required.

This is **forensic** wind history — what the wind actually did at a specific hour on a specific day — not a current-conditions tool like Wind Finder. Use it to support or rebut a claim that emissions from an incident traveled toward (or away from) a specific receptor (school, neighborhood, monitor).

Cross-links: `bayou:firms-active-fire` and `bayou:satellite-imagery` for independent visual confirmation of plume direction on the same day; `bayou:geo-distance` for the underlying coordinate math.

## Parsing arguments

The user needs to supply, or you need to ask for:
- A **facility or origin point** (name, address, or lat/lon)
- A **date**, and ideally a **time window** (if only a date is given, pull the whole day)
- Optionally a **receptor** (a second place — school, neighborhood, monitor) to test whether wind carried toward it

If no station or origin coordinates are given, ask, or use `bayou:facility-coordinates` / `bayou:geo-distance`'s geocoding step first.

## Step 1: Pick the nearest ASOS/AWOS station

Fetch the Louisiana station network and compute distance to each station from the origin point (haversine, same formula as `bayou:geo-distance`):

```bash
curl -s "https://mesonet.agron.iastate.edu/geojson/network.php?network=LA_ASOS" 2>/dev/null | python3 -c "
import json, sys, math

ORIGIN_LAT, ORIGIN_LON = 29.9976, -90.4113  # replace with the origin point

def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

d = json.load(sys.stdin)
rows = []
for f in d['features']:
    lon, lat = f['geometry']['coordinates']
    dist = haversine_miles(ORIGIN_LAT, ORIGIN_LON, lat, lon)
    rows.append((dist, f['properties']['sid'], f['properties']['sname']))
rows.sort()
for dist, sid, name in rows[:8]:
    print(f'{dist:5.1f} mi  {sid}  {name}')
"
```

For the river corridor (St. Charles/St. John/Jefferson/Orleans parishes), **MSY (New Orleans/Moisant)** is usually the closest full-service ASOS with a long, reliable record; **BTR** (Baton Rouge) and **HUM** (Houma) are the next-best alternates upriver/downriver. Smaller AWOS fields (e.g. `APS` Reserve) may be geographically closer but have thinner or less consistent historical records — prefer the full ASOS station unless the smaller field is materially closer and you've confirmed it has data for the target date.

## Step 2: Pull the observation window

```bash
STATION="MSY"
Y1=2025; M1=12; D1=21
Y2=2025; M2=12; D2=23   # NOT day1+1 — see timezone gotcha below

curl -s "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=${STATION}&data=drct&data=sknt&data=gust&data=tmpf&data=relh&year1=${Y1}&month1=${M1}&day1=${D1}&year2=${Y2}&month2=${M2}&day2=${D2}&tz=UTC&format=onlycomma&latlon=no&missing=M&trace=T&direct=no&report_type=3&report_type=4" 2>/dev/null
```

**Timezone gotcha, confirmed live 2026-07-21:** the `day2` bound is exclusive — it returns UTC observations only up through `23:59` on `day2 - 1`, nothing from `day2` itself. That means `day2 = day1 + 1` only captures a full UTC calendar day, **not** a full *local* (Central) calendar day, since CST/CDT evening hours (18:00–23:59 local) fall in the *next* UTC calendar date. Live-verified against the actual GO-1 flare event: Shell's incident report timestamps the release at **12/21/2025 21:30 CST = 2025-12-22 03:30 UTC** — a `day2` of `2025-12-22` would silently miss it. Always set `day2` to `day1 + 2` when working from a local incident date/time, or better, convert the local start/end times to UTC first and set `day1`/`day2` to bracket that UTC range exactly.

Fields returned: `station`, `valid` (UTC timestamp), `drct` (wind direction in degrees, **the direction the wind is blowing FROM**, meteorological convention; `0` with `sknt=0` denotes calm/variable, not a due-north wind), `sknt` (sustained speed, knots), `gust` (knots, `M` if none), `tmpf`, `relh`.

**Observation cadence is not fixed at 5 minutes.** `report_type=3` (routine METAR) gives hourly obs; `report_type=4` (SPECI) adds extra observations whenever conditions change significantly (wind shift, ceiling/visibility change) — so during an active event you often get multiple observations per hour, but it is not a guaranteed fixed interval. State the actual observation count and cadence for the window pulled, don't claim "5-minute data" unless the returned timestamps actually show that spacing.

Always state the UTC window explicitly and also convert to local time (Central: UTC-6 CST / UTC-5 CDT) when presenting, since incident reports are typically in local time.

## Step 3: Compute dominant bearing and (optionally) plume-vs-receptor bearing

```bash
python3 -c "
import math

# Paste the (valid, drct, sknt) rows for the window here
obs = [
    ('2025-12-21 12:53', 150, 6),
    ('2025-12-21 13:53', 160, 7),
    # ...
]

# Circular mean of wind direction, weighted by speed (calm/0-knot obs excluded)
sin_sum = cos_sum = 0.0
for _, drct, sknt in obs:
    if sknt and sknt > 0:
        rad = math.radians(drct)
        sin_sum += math.sin(rad) * sknt
        cos_sum += math.cos(rad) * sknt
mean_from = math.degrees(math.atan2(sin_sum, cos_sum)) % 360
mean_toward = (mean_from + 180) % 360
print(f'Dominant direction wind blew FROM: {mean_from:.0f} deg')
print(f'Dominant direction wind blew TOWARD (plume direction): {mean_toward:.0f} deg')

# Optional: bearing from facility to receptor, to compare against plume direction
FAC_LAT, FAC_LON = 29.9976, -90.4113
RCP_LAT, RCP_LON = 29.9850, -90.3800  # replace with receptor coordinates

phi1, phi2 = math.radians(FAC_LAT), math.radians(RCP_LAT)
dlambda = math.radians(RCP_LON - FAC_LON)
x = math.sin(dlambda) * math.cos(phi2)
y = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
bearing_to_receptor = math.degrees(math.atan2(x, y)) % 360
print(f'Bearing from facility to receptor: {bearing_to_receptor:.0f} deg')

diff = min(abs(mean_toward - bearing_to_receptor), 360 - abs(mean_toward - bearing_to_receptor))
print(f'Angular difference: {diff:.0f} deg', '-> plausible plume path toward receptor' if diff <= 45 else '-> wind was NOT carrying toward receptor')
"
```

`drct` is where the wind comes **FROM**; add 180° to get where it's blowing **TOWARD**. A ±45° window (one compass octant) around that toward-bearing is a reasonable "plausibly carried toward" threshold for prose claims — narrower (±22.5°, one compass point) for a stronger claim. State the exact angular difference so the reader can judge the threshold themselves.

---

## Presenting the results

1. **Station and window**: station ID, name, distance from origin, UTC window and local-time equivalent, number of observations, cadence.
2. **Observation table**: Time (local) | Direction (deg, compass point) | Speed (kt) | Gust
3. **Dominant/mean bearing** (speed-weighted circular mean) with the caveat that a simple mean can be misleading if the wind shifted substantially during the window — show the range, not just the mean, if direction varied by more than ~60° during the window.
4. If a receptor was given: state the bearing from origin to receptor and the angular difference from the plume direction, and give a plain-language verdict with the numeric basis shown, not just an assertion.
5. Always disclose: this is straight-line surface wind at a point station some distance from the actual origin — not a dispersion model. Terrain, local turbulence, and the vertical release height of the actual emission source (e.g., a tall flare vs. ground-level fugitive leak) all affect real plume travel; state this as a limitation on any air quality/exposure conclusion drawn from it.
6. If the facility or agency's own incident report includes a self-reported field wind observation (common in LDEQ release reports — e.g. "SE Wind @ 3 MPH"), pull the nearest-in-time MSY/BTR/HUM observation and state both figures side by side as an independent cross-check, rather than silently preferring one over the other. Exact agreement isn't expected — the ASOS station is miles from the facility and self-reported field readings are coarse/rounded — but the two should be in the same compass octant and rough speed range; a large mismatch is itself worth flagging.

### Citation format

> **MSY (New Orleans/Moisant), 2025-12-22 03:53 UTC** (21:53 CST 12/21), 5 kt sustained from 150° (SSE), source: [Iowa Environmental Mesonet ASOS/AWOS archive](https://mesonet.agron.iastate.edu/request/download.phtml) (retrieved 2026-07-21). Cross-check: Shell Chemical LP's release report for the same incident (LSP Case #25-04485) self-reports "SE Wind @ 3 MPH" at 21:30 CST — consistent in direction (SE/SSE) and comparable in magnitude (~3.5 mph vs. MSY's ~5.75 mph) with the independent station record.

$ARGUMENTS
