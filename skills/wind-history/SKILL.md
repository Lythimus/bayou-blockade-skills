---
name: wind-history
description: Look up historical (forensic) wind direction and speed at a specific date/time and place, and state whether wind carried a plume from a facility toward a specific receptor. Optionally screen the vertical temperature/wind profile (KSIL radiosonde, Open-Meteo model levels) for downward- or upward-refracting sound propagation toward a receptor, for low-frequency noise questions
allowed-tools: Bash, AskUserQuestion
---

# Historical Wind Lookup (Forensic)

Pull actual recorded wind observations for a past date/time window from the Iowa Environmental Mesonet's ASOS/AWOS archive — a mirror of NWS surface station observations going back decades. No API key required.

This is **forensic** wind history — what the wind actually did at a specific hour on a specific day — not a current-conditions tool like Wind Finder. Use it to support or rebut a claim that emissions from an incident traveled toward (or away from) a specific receptor (school, neighborhood, monitor).

Cross-links: `bayou:firms-active-fire` and `bayou:satellite-imagery` for independent visual confirmation of plume direction on the same day; `bayou:geo-distance` for the underlying coordinate math. For the incident time, `bayou:csb-nrc-hazmat nrc-report <SEQNOS>` gives the incident date and time the NRC caller gave, and when NRC received the call. The data does not state a time zone, so confirm the time against the facility's LDEQ written report before setting the UTC window. When the caller gave weather, it also has `WIND_DIRECTION`, `WIND_SPEED` and `WEATHER_CONDITIONS`, a second self-reported reading to set beside the station record (step 6 below).

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


## Step 4 (optional): Vertical profile and sound refraction

Use this for low-frequency noise or infrasound questions: whether sound from a source was bent down toward a receptor (ducted) or up and away from it (a shadow zone). Surface wind alone cannot answer this. The answer depends on how temperature and wind change over the lowest few hundred metres.

**Sources, by date.** Probed 2026-10-17 at 30.0, −90.41.

- **IEM radiosonde archive, `KSIL` (Slidell, ~60 km ENE of Norco).** 00Z and 12Z only, i.e. about 18:00–19:00 and 06:00–07:00 local, from decades back.
  - The ID is `KSIL`; `KLIX` returns empty profiles. `KLCH` (Lake Charles) is the western alternative.
  - `hght` is metres above sea level. Levels arrive unsorted and with nulls.
  - Newer soundings report wind and temperature on separate levels.
  - This is the only temperature profile before 2021-03-23.
- **Open-Meteo `historical-forecast-api`, `models=best_match`.**
  - `temperature_80m` and the 1000/975/950 hPa pressure levels start 2021-03-23.
  - 120 m starts by 2022-09, and 180 m by 2022-12.
  - Before 2021-03-23 there is only 2 m temperature and 10/80 m wind, so the thermal gradient is unknown.
  - Always pass `wind_speed_unit=ms`. `models=gfs_hrrr` returns no height-level temperatures.
- **Open-Meteo archive (ERA5).** Wind at 10/100 m (and 80/120 m) back to 1940, but **no temperature above 2 m**. It gives wind shear only.

**Effective sound speed** along the source→receptor bearing θ:

c_eff(z) = 331.3·√(1 + T/273.15) + u(z)·cos(θ_toward(z) − θ), with **θ_toward = drct + 180°**

Both IEM and Open-Meteo give `drct` as the direction the wind blows **from**. Using `drct` directly flips the sign of the wind term.

**Reading the result:**
- If c_eff increases with height (Δc_eff > 0 between the lowest level and ~100–200 m), the profile is downward-refracting. Sound bends back toward the ground, so a receptor can hear a distant source louder than spherical spreading predicts. This is typical on clear, calm nights (surface inversion) and downwind.
- Δc_eff < 0 is upward-refracting. A shadow zone can form, typical of sunny afternoons and upwind.

```bash
python3 - <<'PY'
import json, math, urllib.request

SRC_LAT, SRC_LON = 29.9976, -90.4113   # source (facility)
RCP_LAT, RCP_LON = 29.9850, -90.3800   # receptor
WHEN = "2016-06-01T12:00:00Z"          # UTC; KSIL launches at 00Z and 12Z
TOP_M = 200                            # upper level for the gradient, m above ground

def bearing(a, b, c, d):
    p1, p2, dl = math.radians(a), math.radians(c), math.radians(d - b)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                   math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360

def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bayou-wind-history"}), timeout=60))

theta = bearing(SRC_LAT, SRC_LON, RCP_LAT, RCP_LON)

def ceff(z, t_c, drct, u):
    # drct is where the wind blows FROM; the along-path component uses the TOWARD direction.
    along = u * math.cos(math.radians((drct + 180) - theta))
    return 331.3 * math.sqrt(1 + t_c / 273.15) + along, along

profiles = {}
# IEM radiosonde. Levels arrive unsorted and with nulls; hght is metres above sea level.
r = get("https://mesonet.agron.iastate.edu/json/raob.py?ts=%s&station=KSIL" % WHEN)
lv = [l for p in r["profiles"] for l in p["profile"] if l.get("hght") is not None]
tl = sorted((l["hght"], l["tmpc"]) for l in lv if l.get("tmpc") is not None)
# Newer soundings report wind on separate levels from temperature; carry wind onto the
# temperature heights as linearly interpolated u/v components (u/v avoid the 359->1 deg wrap).
wl = sorted((l["hght"], -l["sknt"] * 0.514444 * math.sin(math.radians(l["drct"])),
             -l["sknt"] * 0.514444 * math.cos(math.radians(l["drct"])))
            for l in lv if l.get("drct") is not None and l.get("sknt") is not None)

def wind_at(z):
    if not wl or z < wl[0][0] or z > wl[-1][0]:
        return None
    for (za, ua, va), (zb, ub, vb) in zip(wl, wl[1:] + [wl[-1]]):
        if za <= z <= zb:
            if zb - za > 300 and z not in (za, zb):
                return None   # too far from any wind level to interpolate honestly
            f = 0 if zb == za else (z - za) / (zb - za)
            u, v = ua + f * (ub - ua), va + f * (vb - va)
            return (math.degrees(math.atan2(-u, -v)) % 360, math.hypot(u, v))

if tl:
    z0 = tl[0][0]
    rows = [(z - z0, t) + (wind_at(z) or (None, None)) for z, t in tl if z - z0 <= 500]
    if sum(r[2] is not None for r in rows) < 2:
        # Temperature alone still gives the sign of the thermal gradient; wind shear is unknown.
        print("KSIL: under two wind levels below 500 m; temperature-only c_eff (wind set to 0)")
        rows = [(z, t, 0.0, 0.0) for z, t, _, _ in rows]
    else:
        rows = [r for r in rows if r[2] is not None]
    if len(rows) >= 2:
        profiles["KSIL raob"] = rows
# Open-Meteo model levels (from 2021-03-23; 120 m from 2022-09 and 180 m from 2022-12). Missing levels are null.
day = WHEN[:10]
H = [2, 80, 120, 180]
W = [10, 80, 120, 180]
v = ",".join(["temperature_%dm" % h for h in H] + ["wind_speed_%dm" % h for h in W] + ["wind_direction_%dm" % h for h in W])
try:
    m = get("https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f&start_date=%s"
            "&end_date=%s&hourly=%s&wind_speed_unit=ms&models=best_match&timezone=GMT" % (SRC_LAT, SRC_LON, day, day, v))
    i = m["hourly"]["time"].index(WHEN[:13] + ":00")
    h = m["hourly"]
    rows = []
    for z in (10, 80, 120, 180):
        # 10 m wind pairs with 2 m temperature: the model has no 10 m temperature.
        t = h["temperature_%dm" % (2 if z == 10 else z)][i]
        s, d = h["wind_speed_%dm" % z][i], h["wind_direction_%dm" % z][i]
        if None not in (t, s, d):
            rows.append((z, t, d, s))
    if len(rows) >= 2:
        profiles["Open-Meteo best_match"] = rows
except Exception as e:
    print("Open-Meteo:", e)

print("Source -> receptor bearing %.0f deg; %s" % (theta, WHEN))
for name, rows in profiles.items():
    print("\n" + name)
    print("  z(m)   T(C)  from  u(m/s)  along  c_eff")
    out = []
    for z, t, d, u in rows:
        c, al = ceff(z, t, d, u)
        out.append((z, c))
        print("  %5.0f  %5.1f  %4.0f  %5.1f  %+5.1f  %6.1f" % (z, t, d, u, al, c))
    top = min((x for x in out if x[0] > 0), key=lambda x: abs(x[0] - TOP_M), default=None)
    if top:
        dc = top[1] - out[0][1]
        print("  delta c_eff %.0f m -> %.0f m: %+.1f m/s -> %s" % (out[0][0], top[0], dc,
              "downward-refracting (duct toward receptor)" if dc > 0 else "upward-refracting (possible shadow zone)"))
PY
```

**Verified:**
- **2016-06-01 12Z KSIL** (06:00 CDT), receptor bearing 115°: the surface inversion goes from 20.1 °C at the surface to 24.6 °C at 115 m, and the wind blows from 254° (toward 74°, 41° off the path). Δc_eff is +5.0 m/s up to 153 m: downward-refracting, as expected for a nocturnal inversion.
- **2023-06-01 12Z** is a caution:
  - KSIL had no wind levels below 500 m, so the snippet falls back to temperature only (+2.3 m/s, inversion).
  - Open-Meteo shows an almost isothermal model profile (22.3 → 21.9 °C) and gives −3.8 m/s.
  - Models smooth out shallow nocturnal inversions. Where both exist for the same hour, prefer the sounding for the temperature gradient, and say so when they disagree.

For archived infrasound and seismic spectra for the same hours, use `bayou:lf-acoustic-baselines`. `ldeq-eric-emissions sources` gives the candidate sources and their stack heights.

**Present this as a screening indicator, not a propagation model.** Give:
- the source and its distance and time offset from the hour of interest;
- the levels used;
- Δc_eff and its sign.

KSIL is 60 km away and launches at most twice a day. Model levels are gridded forecasts, not observations. Terrain, the river valley and the source height also matter. Ray tracing or a parabolic-equation model would be needed for an actual level prediction.

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
