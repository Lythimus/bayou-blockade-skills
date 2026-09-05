# Public Air Monitor Networks — Cheat Sheet

Full endpoint/field/key detail for `bayou:public-air-monitors`. The first three are first-class
(keys configured in `~/.claude/bayou-credentials.md`); the rest are secondary networks — not
wired into the default skill flow, but documented so they can be added without a redesign.

## First-class networks

### PurpleAir

- **What it measures**: PM1, PM2.5, PM10 (optical particle counter), plus temperature/humidity/
  pressure on most sensors. **No gas-phase pollutants** (no NH₃, SO₂, NO₂, H₂S, VOCs).
- **Base URL**: `https://api.purpleair.com/v1/`
- **Auth**: header `X-API-Key: <key>`. Two key types exist (read and read+write) — a read key is
  sufficient for this skill.
- **Get a key**: self-serve at **https://develop.purpleair.com/** — sign in, create a key.
  Nearly instant.
- **Core endpoints**:
  - `GET /sensors` — list/search sensors. Filter by bbox (`nwlng`, `nwlat`, `selng`, `selat`) or
    by `sensor_index`/`location_type`. `fields` param controls returned columns (comma-separated,
    e.g. `name,latitude,longitude,pm2.5,pm2.5_60minute,humidity,last_seen`).
  - `GET /sensors/:sensor_index` — single sensor's current reading.
  - `GET /sensors/:sensor_index/history` — historical time series. Params: `start_timestamp`,
    `end_timestamp` (Unix seconds, UTC), `average` (minutes: `0` raw/~2min, `10`, `30`, `60`,
    `360`, `1440`), `fields` (e.g. `pm2.5_cf_1,pm2.5_atm,humidity`).
- **Correction**: raw PurpleAir PM2.5 (`pm2.5_cf_1`) reads high relative to reference monitors.
  Apply the EPA/Barkjohn et al. (2021) correction (used in AirNow's Fire and Smoke Map) before
  presenting a number as "PM2.5":
  - `PM2.5 = 0.52 * pm2.5_cf_1 − 0.086 * RH + 5.75` for `pm2.5_cf_1 ≤ 343 µg/m³`
  - `PM2.5 = 0.46 * pm2.5_cf_1 + 0.000393 * pm2.5_cf_1² + 2.97` above that
- **Rate limits**: generous for a single read key at this scale; no documented hard cap for
  typical research volumes, but avoid tight polling loops.
- **Coverage**: dense in populated/suburban Louisiana river-corridor areas (many are
  privately-owned home sensors); sparse-to-absent in industrial buffer zones and rural areas —
  a coverage gap near a facility is itself worth noting.

### OpenAQ (v3)

- **What it measures**: aggregates many source networks — both low-cost sensors and reference
  monitors — for PM2.5/PM10, O₃, NO₂, SO₂, CO, and more, depending on what each underlying station
  reports. Check each location's `sensors` list for which parameters it actually has.
- **Base URL**: `https://api.openaq.org/v3/` — **v1 and v2 were retired 2025-01-31; v3 only.**
- **Auth**: header `X-API-Key: <key>` (free, required for v3 — unlike the old v1/v2).
- **Get a key**: self-serve at **https://explore.openaq.org/register** (or via the API docs
  sign-up flow at api.openaq.org).
- **Core endpoints**:
  - `GET /locations` — search monitoring locations. `coordinates=lat,lon` + `radius` (meters, max
    25000) for a proximity search; response includes each location's `sensors` array
    (`sensors_id` per parameter).
  - `GET /locations/:id` — single location detail.
  - `GET /sensors/:sensors_id/measurements` — raw/period measurements for one sensor.
    `date_from`/`date_to` (ISO 8601, UTC), `limit`.
  - `GET /locations/:id/latest` — latest reading per sensor at a location, useful for a quick
    "is anything reporting right now" check.
- **Correction**: OpenAQ passes through whatever the source network reports — check each
  location's `provider`/`sensors` metadata to know if a given parameter is low-cost or
  reference-grade before treating it as either.
- **Coverage in Louisiana**: moderate — includes some AirNow reference stations plus assorted
  low-cost networks; less dense than PurpleAir for hyperlocal PM2.5, more likely to have gas
  parameters at a given station.

### AirNow (EPA)

- **What it measures**: **EPA regulatory-grade FRM/FEM data** — the CAMRA-permitted tier.
  Typically PM2.5, PM10, ozone; some sites add NO₂, SO₂, CO.
- **Base URL**: `https://www.airnowapi.org/aq/`
- **Auth**: query param `API_KEY=<key>` (no header).
- **Get a key**: self-serve at **https://docs.airnowapi.org/account/request/** — near-instant
  approval historically.
- **Core endpoints**:
  - `GET observation/latLong/current/` — current AQI/conditions near a lat/lon.
    Params: `format=application/json`, `latitude`, `longitude`, `distance` (miles), `API_KEY`.
  - `GET observation/latLong/historical/` — **one hour per call.** Params: same as above plus
    `date=YYYY-MM-DDTHH-0000` (exact format, hour + literal `-0000`). Loop across the incident
    window.
- **Why it matters for CAMRA**: this is the data class the statute doesn't restrict — where a
  reference monitor is close enough to a facility/receptor to be relevant, an AirNow reading is
  the strongest single data point in a report and can be cited toward an actual violation
  question (subject to normal evidentiary/legal review, not this skill's guardrails).
- **Coverage**: sparse — reference monitors are expensive and few; Louisiana's network is
  concentrated in metro areas (Baton Rouge, New Orleans) with real gaps along much of the
  industrial river corridor. Absence of a nearby AirNow site is common and itself a data point
  (no regulatory-grade monitor exists to check this event against).

## Secondary networks (documented, not wired into the default flow)

### AirBeam / AirCasting (HabitatMap)

- Community-run, EJ-native — many AirCasting sessions are recorded by residents specifically
  documenting fenceline pollution.
- Open API at **`aircasting.habitatmap.org`** (session/measurement search by location and time;
  no key required for read access as of last check — verify live before relying on this).
- Same PM-only limitation as PurpleAir on most sessions (some AirBeam models add other sensors —
  check the session's `sensor_name`/`measurement_type`).
- **Note**: HabitatMap (AirCasting's operator) is a named plaintiff in the pending First
  Amendment challenge to CAMRA — relevant context, not a reason to treat its data differently
  under the guidelines.

### Sensor.Community (formerly Luftdaten)

- Keyless, open data at **`data.sensor.community`** — European-origin citizen-science network,
  **sparse coverage in Louisiana**; check before assuming any local data exists.
- PM-only (SDS011-type optical sensors), no built-in correction — apply the same skepticism as
  raw PurpleAir data if using it.

### WAQI / aqicn.org

- Free-token aggregator (`api.waqi.info`) that re-publishes AirNow, PurpleAir, and other feeds
  behind a simplified API and its own AQI calculation — useful as a quick sanity check or a
  fallback UI, but for this skill's forensic use, prefer pulling directly from the source
  network so the correction/uncertainty provenance is clear rather than going through a
  re-aggregated AQI number.
