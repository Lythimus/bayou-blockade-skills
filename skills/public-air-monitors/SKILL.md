---
name: public-air-monitors
description: Pull historical particulate (PM1/2.5/10) readings from public community air sensors (PurpleAir, OpenAQ, AirNow) near a facility or receptor during an incident window, to help reconstruct a poorly-documented event — forensic/investigative use only, never as violation evidence (Louisiana CAMRA guardrails apply)
allowed-tools: Bash, AskUserQuestion, Read
---

# Public Air Monitor Lookup (Forensic)

Given a **location** (facility or receptor) and a **date/time window**, pull particulate
readings from public, community-run and regulatory air-quality networks — **PurpleAir**
(low-cost community sensors), **OpenAQ** (aggregator of low-cost + reference monitors), and
**AirNow** (EPA regulatory-grade reference monitors) — and report them as a time series, so a
measured PM spike at a receptor can be lined up against a reported incident.

This is the **air-side companion** to `bayou:wind-history` and `bayou:firms-active-fire`: those
tools establish that a plume *could have* traveled toward a receptor and *when* a heat source
was active; this skill looks for **independent, measured evidence that particulate matter
actually arrived there.** It is most valuable for reconstructing events that are poorly recorded
in official channels — sparse LDEQ release reports, delayed self-reporting, no monitor listed in
the incident record — where a nearby public sensor may have caught something the paperwork
didn't.

**Before producing any output that characterizes a specific facility, source, or event, read
`references/louisiana-camra-guidelines.md`.** Louisiana's Community Air Monitoring Reliability
Act (CAMRA, La. R.S. 30:2383.1 et seq.) restricts how data from non-EPA-method sensors can be
used or communicated — this skill is designed to stay in the lawful "investigative /
lead-generation" lane by default, and every output must end with the disclosure block from that
file. Do not phrase any result as proof that a source violated a permit, the NAAQS, or the Clean
Air Act.

**Critical limitation, state it every time:** PurpleAir and most low-cost community sensors
measure **particulate matter only (PM1/PM2.5/PM10)**. They do **not** detect ammonia (NH₃),
SO₂, NO₂, H₂S, or VOCs — the pollutants most relevant to an ammonia plant or most petrochemical
releases. A PM spike is evidence *something* combustion- or dust-related reached the sensor
(e.g., a flare, a fire, fugitive dust) — it is not evidence of an ammonia or toxic-gas release
by itself. AirNow reference monitors sometimes carry additional criteria pollutants (O₃, NO₂,
SO₂, CO) at a given site — check what's actually reported at the nearest AirNow site rather than
assuming PM-only.

Cross-links: `bayou:wind-history` (did wind carry the plume toward this sensor at the observed
time?), `bayou:firms-active-fire` + `bayou:satellite-imagery` (independent heat/optical
confirmation for the same window), `bayou:facility-coordinates` / `bayou:geo-distance` (resolve
facility lat/lon and distance to each sensor), `bayou:csb-nrc-hazmat` + `bayou:epa-echo-search`
(the incident record this data is corroborating), `bayou:la-rs-search R.S. 30:2383` (pull the
live CAMRA statute text).

## Tools available in this environment

- `curl` and `python3`, invoked by name off `PATH` (stdlib only — `csv`, `json`, `math`,
  `datetime`). No third-party packages. If `command -v` comes up empty (a non-interactive
  shell's `PATH` often omits Homebrew), probe `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`
  as fallbacks rather than hardcoding one prefix.

## Step 0: Parse arguments

- **Location** — one of:
  - a `lat,lon` pair — use directly;
  - an address or place name — geocode with Nominatim (Step 1);
  - a **facility name** — prefer `bayou:facility-coordinates` to resolve lat/lon first.
  - If the goal is "did a specific receptor see a spike," the location is the **receptor**
    (home, school, neighborhood), not the facility — ask which one is meant if ambiguous.
- **Date/time window** — a date, or a start/end range. If only a date is given, pull the whole
  day. Reuse the **UTC vs. local timezone gotcha** from `bayou:wind-history`: incident reports
  are almost always in local (Central) time, but API calls below want UTC — convert explicitly
  and pad the query window by an hour or two on each side so a release near midnight isn't
  clipped.
- **Radius** (optional) — default ~5 km (~0.05°) around the point for a receptor-level check;
  widen to 10–15 km for a regional "which sensors exist near this facility at all" survey.
- **Networks** (optional) — default to trying **all three** (PurpleAir, OpenAQ, AirNow) and
  report which ones actually returned data; ask only if the user wants to restrict to one.

If a place name is ambiguous or missing a state/city, **ask** before querying — a wrong match
silently produces confident-looking wrong data.

## Step 1: Resolve location → lat/lon and bounding box

Skip geocoding if `lat,lon` was already given. Otherwise use Nominatim (free, no key,
descriptive `User-Agent`, ~1 req/sec) — same pattern as `bayou:wind-history` /
`bayou:firms-active-fire`:

```bash
curl -s --get "https://nominatim.openstreetmap.org/search" \
  --data-urlencode "q=Reserve, LA" \
  --data-urlencode "format=json" \
  --data-urlencode "limit=3" \
  -H "User-Agent: bayou-public-air-monitors/1.0 (research lookup)" | python3 -m json.tool
```

```bash
python3 -c "
lat, lon, H = 30.0703, -90.5556, 0.05   # H in degrees, ~5 km
minlon, maxlon = lon - H, lon + H
minlat, maxlat = lat - H, lat + H
print(f'NW: {maxlat},{minlon}   SE: {minlat},{maxlon}')
"
```

## Step 2: API access, keys, and graceful degradation

Read `~/.claude/bayou-credentials.md` first and use whichever of `PURPLEAIR_API_KEY`,
`OPENAQ_API_KEY`, `AIRNOW_API_KEY` are present. **Don't fail outright if one is missing** — try
the networks that have keys, and tell the user plainly which network(s) were skipped and how to
add a free key (all three are free, instant/near-instant self-serve signups). Full endpoint
details, field names, and correction notes are in `references/networks.md` — this section
covers the query shape needed for a location + time window pull.

### PurpleAir

```bash
PURPLEAIR_API_KEY="..."   # from ~/.claude/bayou-credentials.md

# Find sensors in the bbox
curl -s --get "https://api.purpleair.com/v1/sensors" \
  -H "X-API-Key: ${PURPLEAIR_API_KEY}" \
  --data-urlencode "fields=name,latitude,longitude,pm2.5,pm2.5_60minute,humidity,last_seen" \
  --data-urlencode "nwlng=${MINLON}" --data-urlencode "nwlat=${MAXLAT}" \
  --data-urlencode "selng=${MAXLON}" --data-urlencode "selat=${MINLAT}" | python3 -m json.tool
```

Pick the closest sensor(s) to the receptor by index, then pull historical data for the incident
window (`average` in minutes: `0`=raw ~2 min, `10`, `30`, `60`, `360`, `1440`; timestamps are
Unix seconds, UTC):

```bash
curl -s --get "https://api.purpleair.com/v1/sensors/${SENSOR_INDEX}/history" \
  -H "X-API-Key: ${PURPLEAIR_API_KEY}" \
  --data-urlencode "start_timestamp=1734825600" \
  --data-urlencode "end_timestamp=1734847200" \
  --data-urlencode "average=10" \
  --data-urlencode "fields=pm2.5_cf_1,humidity" | python3 -m json.tool
```

### OpenAQ (v3 — v1/v2 retired 2025-01-31)

```bash
OPENAQ_API_KEY="..."   # from ~/.claude/bayou-credentials.md

# Find monitoring locations within a radius (meters) of the point
curl -s --get "https://api.openaq.org/v3/locations" \
  -H "X-API-Key: ${OPENAQ_API_KEY}" \
  --data-urlencode "coordinates=${LAT},${LON}" \
  --data-urlencode "radius=10000" \
  --data-urlencode "limit=25" | python3 -m json.tool
```

Then pull the sensor-level measurements for the window (each location has one or more
parameter-specific `sensors_id`s — find the PM2.5 sensor id from the locations response):

```bash
curl -s --get "https://api.openaq.org/v3/sensors/${SENSORS_ID}/measurements" \
  -H "X-API-Key: ${OPENAQ_API_KEY}" \
  --data-urlencode "date_from=2025-12-21T18:00:00Z" \
  --data-urlencode "date_to=2025-12-22T06:00:00Z" \
  --data-urlencode "limit=500" | python3 -m json.tool
```

### AirNow (EPA regulatory FRM/FEM tier)

```bash
AIRNOW_API_KEY="..."   # from ~/.claude/bayou-credentials.md

# Current conditions at the nearest reference monitor(s)
curl -s --get "https://www.airnowapi.org/aq/observation/latLong/current/" \
  --data-urlencode "format=application/json" \
  --data-urlencode "latitude=${LAT}" \
  --data-urlencode "longitude=${LON}" \
  --data-urlencode "distance=25" \
  --data-urlencode "API_KEY=${AIRNOW_API_KEY}" | python3 -m json.tool

# Historical — one call per hour of interest, date format is exact: YYYY-MM-DDTHH-0000
curl -s --get "https://www.airnowapi.org/aq/observation/latLong/historical/" \
  --data-urlencode "format=application/json" \
  --data-urlencode "latitude=${LAT}" \
  --data-urlencode "longitude=${LON}" \
  --data-urlencode "date=2025-12-21T21-0000" \
  --data-urlencode "distance=25" \
  --data-urlencode "API_KEY=${AIRNOW_API_KEY}" | python3 -m json.tool
```

AirNow's historical endpoint is **one hour per call** — loop it across the incident window
rather than assuming a range parameter exists. **Flag AirNow results explicitly as the
EPA-reference (FRM/FEM) tier** — this is the data class CAMRA doesn't restrict, and if a
reference monitor is close enough to be relevant, it's the strongest single data point in the
report.

## Step 3: Build the time series, apply the PurpleAir correction, save a CSV

Low-cost PurpleAir sensors read **high** relative to reference monitors, especially in humid/
wildfire-smoke conditions. Apply EPA's published correction (Barkjohn et al., 2021 — the same
one behind AirNow's Fire and Smoke Map) to the raw `pm2.5_cf_1` + `humidity` fields before
presenting a number as "PM2.5":

```bash
python3 -c "
def epa_correction(pm_cf1, rh):
    if pm_cf1 <= 343:
        return 0.52 * pm_cf1 - 0.086 * rh + 5.75
    return 0.46 * pm_cf1 + 0.000393 * pm_cf1**2 + 2.97

# Example: paste (timestamp, pm2.5_cf_1, humidity) rows from the history response
rows = [
    ('2025-12-21T21:00:00Z', 42.0, 55),
    ('2025-12-21T21:10:00Z', 118.0, 54),
]
print(f'{\"time\":<22}{\"raw_cf1\":>9}{\"rh\":>5}{\"corrected\":>11}')
for ts, pm, rh in rows:
    corr = epa_correction(pm, rh)
    print(f'{ts:<22}{pm:>9.1f}{rh:>5}{corr:>11.1f}')
"
```

Save the raw pulled JSON/CSV to the scratchpad (mirror `firms-active-fire`'s save pattern) and
note the file path in the report. If OpenAQ/AirNow readings are already reference-grade or
pre-corrected, don't apply the PurpleAir correction to them — state plainly which numbers are
raw low-cost, corrected low-cost, and reference-grade.

## Step 4: Correlate against the incident (the payoff)

Line up the corrected PM time series against:
- The **reported incident time** (from the LDEQ release report, CSB/NRC record, or whatever
  triggered the lookup).
- **`bayou:wind-history`**, if run for the same window — was the wind actually blowing from the
  facility toward this sensor at the time of the spike?
- **`bayou:firms-active-fire`** overpass times, if a fire/flare is part of the narrative.

Report a plain-language, **hedged** read: state the numbers, the timing, and the wind
corroboration (or lack of it) — e.g. "PM2.5 at sensor X (corrected) rose from ~9 to ~140 µg/m³
between 21:10 and 21:40 CST, roughly 25–55 minutes after the reported 21:30 CST release; wind at
MSY during that window was from 150° (SSE), consistent with transport toward the sensor (bearing
162° from the facility, 12° off)." **Never** conclude "the facility exceeded the NAAQS" or "the
facility violated its permit" — that characterization is exactly what CAMRA reserves for
FRM/FEM data (see `references/louisiana-camra-guidelines.md`).

If no sensor exists near the location at all, that is itself a reportable finding: a
**monitoring gap** worth noting as a reason to request formal monitor placement.

## Presenting the results

1. **Location and window**: point coordinates, radius searched, UTC window and local-time
   equivalent, which networks were queried and which returned data.
2. **Sensor table**: Network | Sensor ID/name | Distance from point | Data type (raw low-cost /
   corrected low-cost / EPA reference).
3. **Time series table or summary**: timestamp, raw value, corrected value (if applicable), for
   the window — highlight the peak and when it occurred relative to the incident time.
4. **Correlation section** (Step 4) if an incident time and/or `wind-history` output was
   supplied.
5. **Saved data file path** (scratchpad CSV/JSON).
6. **Mandatory limitations, every time**: point-sensor (not areal) reading; PM-only (state
   explicitly if the pollutant of concern is ammonia/SO₂/H₂S/etc. and that this data cannot
   speak to it); low-cost sensor accuracy even after correction; not a dispersion model; **not**
   an EPA reference/equivalent method unless explicitly sourced from AirNow.
7. **CAMRA disclosure block** — copy the required block from
   `references/louisiana-camra-guidelines.md` verbatim (or lightly adapted) at the end of
   **every** output that discusses a specific facility or event.

### Citation format

> **PurpleAir sensor #123456 ("Reserve - River Rd"), 2025-12-21 21:00–22:00 UTC-6 (CST)**,
> corrected PM2.5 (EPA/Barkjohn 2021 correction applied to raw `pm2.5_cf_1` + humidity), source:
> [api.purpleair.com](https://api.purpleair.com/) (retrieved 2026-07-23). Cross-check: AirNow
> reference monitor "Reserve" (FRM/FEM tier) reported AQI [X] for the same hour, source:
> [airnowapi.org](https://www.airnowapi.org/) (retrieved 2026-07-23). See
> `references/louisiana-camra-guidelines.md` for required use limitations — this data is
> provided for investigative/informational purposes and is not offered as proof of a permit or
> NAAQS violation.

$ARGUMENTS
