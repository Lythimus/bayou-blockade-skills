---
name: usgs-water-data
description: Find USGS stream/groundwater gauges near a location, pull real-time or historical discharge/gage-height/water-quality data, and get NOAA flood-stage forecast context
allowed-tools: Bash, AskUserQuestion
---

# USGS/NOAA Water Data

Combines three related lookups into one skill: finding gauges near a facility or area (replaces the NWIS Mapper bookmark), pulling instantaneous/daily values from them (replaces "USGS current water data"), and getting NOAA flood-stage/forecast context for the same gauge (replaces "NOAA National Water Prediction Services"). No API key required for either service.

## Parsing arguments

The user may provide:
- A **location** (facility name/address, parish, or lat/lon/bbox) to find nearby gauges
- A **known USGS site number** (8-15 digit, e.g. `07374000`) to pull data directly
- A **date/event window** for historical discharge or gage height during a specific incident
- A request framed around **flooding risk** or **flood stage** — pull NOAA NWPS forecast context in addition to raw USGS data

## Step 1: Find gauges near a location

`waterservices.usgs.gov/nwis/site/` accepts exactly **one** "major filter" per request — `stateCd`, `countyCd`, `bBox`, `huc`, or `sites`. Combining two (e.g. `stateCd` + `countyCd`) returns an HTTP 400. Pick one:

```bash
# By county (Louisiana parish FIPS, e.g. St. Charles = 22089)
curl -s "https://waterservices.usgs.gov/nwis/site/?format=rdb&countyCd=22089&siteType=ST,GW,SP&siteStatus=all" 2>/dev/null

# By bounding box (west,south,east,north in decimal degrees)
curl -s "https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&bBox=-90.6,29.8,-90.2,30.2" 2>/dev/null
```

`siteType` values: `ST` (stream), `GW` (groundwater well), `SP` (spring), `LK` (lake), `WE` (wetland). Comma-separate to combine. Louisiana parish FIPS codes used elsewhere in this project: St. Charles = 22089, St. John the Baptist = 22095, St. James = 22093, Orleans = 22071.

Output columns: `site_no`, `station_nm`, `site_tp_cd`, `dec_lat_va`, `dec_long_va`, `huc_cd`. **A site appearing in this list does not guarantee it has active data** — many are historical, project-specific, or COE-operated with no current telemetry. Verify with Step 2's catalog check before relying on a specific gauge.

## Step 2: Check what data a site actually has

```bash
curl -s "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=07374000&seriesCatalogOutput=true" 2>/dev/null
```

This lists every parameter code (`parm_cd`) the site has ever reported, with `begin_date`/`end_date`/`count_nu`. Common parameter codes: `00060` discharge (cfs), `00065` gage height (ft), `00010` water temp, `00095` specific conductance, `00300` dissolved oxygen, `72019` groundwater level below land surface.

## Step 3: Pull the data

Instantaneous values (real-time, 15-min typical interval, ~120 days retained):
```bash
curl -s "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=07374000&period=P7D" 2>/dev/null
```

Daily values (long historical record, one value/day):
```bash
curl -s "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=07374000&startDT=2020-01-01&endDT=2020-12-31&parameterCd=00060" 2>/dev/null
```

For a specific past event window, use `startDT`/`endDT` (ISO date) instead of `period`. Both endpoints accept a comma-separated `sites` list for multiple gauges in one call.

Parse the nested `value.timeSeries[].values[0].value[]` array; each entry has `value` and `dateTime`. If `timeSeries` is an empty list, the site has no data for that parameter/window — try `seriesCatalogOutput` (Step 2) to confirm what actually exists before assuming a request error.

## Step 4 (optional): NOAA flood-stage / forecast context

NOAA's National Water Prediction Service wraps many of the same USGS gauges with flood-category thresholds and forecasts. Cross-reference by USGS site number:

```bash
curl -s "https://api.water.noaa.gov/nwps/v1/gauges/07374000" 2>/dev/null
curl -s "https://api.water.noaa.gov/nwps/v1/gauges/07374000/stageflow" 2>/dev/null
```

The first call returns `status.observed.primary` (current stage, ft) and flood categories; the second returns a time series (`data[]`, ~15-min interval) of `primary` (stage) / `secondary` (flow, kcfs). **The bbox-based gauge search on this API (`/gauges?bbox=...`) does not accept a working bbox parameter format as of this writing** (returns a parsing error regardless of format tried) — find gauges via the USGS NWIS site search (Step 1) instead, and only use NOAA's endpoint for the flood-stage/forecast layer on a gauge you already have the ID for. Not every USGS site has a NOAA NWPS counterpart (`lid`); a 404 means NOAA doesn't forecast that gauge.

---

## Presenting the results

1. **Gauge identification**: site number, name, coordinates, distance/relation to the location of interest, site type.
2. **Data table**: Date/Time | Parameter | Value | Unit
3. If flood context was pulled: current stage vs. flood category thresholds, in plain language ("X ft, below/at/above [category] stage").
4. State the retrieval window and whether values are provisional (USGS IV data is explicitly provisional/unreviewed — say so) vs. approved DV data.
5. Cross-link: `bayou:fema-flood` for NFIP claims/policy history and NFHL flood-zone designation at a specific point.

### Citation format

> **USGS Site 07374000** (Mississippi River at Baton Rouge, LA), source: [USGS NWIS](https://waterservices.usgs.gov/) (retrieved 2026-07-21): discharge [X] cfs on [date] (provisional).

$ARGUMENTS
