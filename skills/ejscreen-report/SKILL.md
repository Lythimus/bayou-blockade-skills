---
name: ejscreen-report
description: Pull EPA EJScreen environmental-justice indicators (demographics, pollution burden, proximity scores) for a point or radius, from a live community-hosted mirror of the official dataset
allowed-tools: Bash, AskUserQuestion
---

# EJScreen Environmental Justice Report

EPA's official EJScreen tool (`ejscreen.epa.gov`) and its 2025 replacement (`screeningtool.geoplatform.gov`) are both **dead** — confirmed via DNS resolution failure (`curl` exit 6, "Could not resolve host") against both domains, while control domains (google.com, census.gov, api.census.gov) resolve fine from the same environment. This is a real decommission, not a local network restriction.

This skill instead queries the ArcGIS FeatureServer that actually backs EPA's own **Public Environmental Data Portal (PEDP)** EJScreen-replacement web app — found by reading that app's client-side `config.js`, which points at a community-hosted ArcGIS Online layer serving the real EJScreen v2.32 block-group dataset:

```
https://services2.arcgis.com/w4yiQqB14ZaAGzJq/arcgis/rest/services/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view/FeatureServer/0/query
```

Verified live, no API key required. This is genuine EPA EJScreen v2.32 data (2023 vintage ACS/pollution inputs), not a reconstruction — but it is a third-party mirror of a dataset EPA itself no longer serves at an official URL, so **always disclose the source explicitly** as noted below; do not present it as if pulled from `ejscreen.epa.gov`.

## Parsing arguments

The user may provide:
- A **facility name/address** or **lat/lon** to center the report on
- A **radius** (default to 1 mile, matching EPA's original "Standard Report" methodology, if not specified)
- A request for a **specific indicator** only (e.g. "just PM2.5 and diesel PM near Shell Norco") vs. a full report

If only a facility name is given, resolve coordinates first (reuse `bayou:facility-coordinates` or the geocoding approach in `bayou:geo-distance`).

## Step 1: Point query — which block group(s) contain the location

```bash
LAT=29.9976
LON=-90.4113

curl -s --get "https://services2.arcgis.com/w4yiQqB14ZaAGzJq/arcgis/rest/services/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view/FeatureServer/0/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "outFields=ID,STATE_NAME,CNTY_NAME,ACSTOTPOP,PEOPCOLORPCT,LOWINCPCT,LESSHSPCT,LINGISOPCT,UNEMPPCT,PM25,OZONE,DSLPM,PTRAF,PNPL,PRMP,PTSDF,UST,PWDIS,NO2,DEMOGIDX_2,P_PM25,P_OZONE,P_DSLPM,P_PTRAF,P_PNPL,P_PRMP,P_PTSDF,P_UST,P_PWDIS,P_NO2,P_DEMOGIDX_2" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null | python3 -m json.tool
```

`ID` is the 12-digit Census block group FIPS. This gives the single block group the point falls inside — fine for "what does EJScreen say at this exact address" but not EPA's radius-based Standard Report methodology. (Note: the field is `LINGISOPCT`, not `LINGISPCT` — verified live 2026-07-21; a bad field name anywhere in `outFields` makes the whole query fail with a generic "Invalid query parameters" 400, not a per-field error, so double-check spelling against the field reference below if a query fails.)

## Step 2: Radius (buffer) query — matches EPA's Standard Report approach

The service accepts `distance`/`units` buffer parameters on the same point geometry:

```bash
curl -s --get "https://services2.arcgis.com/w4yiQqB14ZaAGzJq/arcgis/rest/services/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view/FeatureServer/0/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "distance=1" \
  --data-urlencode "units=esriSRUnit_StatuteMile" \
  --data-urlencode "outFields=ID,STATE_NAME,CNTY_NAME,ACSTOTPOP,PEOPCOLORPCT,LOWINCPCT,PM25,DSLPM,PTSDF,PNPL,DEMOGIDX_2,P_PM25,P_DSLPM,P_PTSDF,P_PNPL,P_DEMOGIDX_2" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null
```

This returns **every block group whose boundary intersects the buffer** — usually several. EPA's actual Standard Report does a population-weighted average across the block groups that fall inside (or are clipped by) the radius, using each block group's population as the weight. Approximate that here:

```bash
python3 -c "
import json

# Paste the 'features' list from the buffer query response
records = [
    # {'attributes': {'ID': '...', 'ACSTOTPOP': 1234, 'PM25': 9.1, 'P_PM25': 62, ...}},
]

fields = ['PEOPCOLORPCT','LOWINCPCT','PM25','DSLPM','PTSDF','PNPL','DEMOGIDX_2',
          'P_PM25','P_DSLPM','P_PTSDF','P_PNPL','P_DEMOGIDX_2']

total_pop = sum(r['attributes'].get('ACSTOTPOP') or 0 for r in records)
print(f'{len(records)} block groups intersecting buffer, total pop {total_pop}')
for f in fields:
    weighted = sum((r['attributes'].get(f) or 0) * (r['attributes'].get('ACSTOTPOP') or 0) for r in records)
    avg = weighted / total_pop if total_pop else None
    print(f'{f}: {avg:.1f}' if avg is not None else f'{f}: n/a')
"
```

State plainly that this is an **approximation** of EPA's exact buffer methodology (EPA's original tool clips block-group polygons to the exact circle and area-weights sub-polygon population; this pulls whole intersecting block groups and population-weights them) — close enough for a fenceline-community argument, not exact enough to cite as an official EJScreen Standard Report figure.

## Field reference

Raw indicators (facility/area's actual values):
- **Demographic**: `PEOPCOLORPCT` (people of color %), `LOWINCPCT` (low-income %), `LESSHSPCT` (less than HS education %), `LINGISPCT` (linguistic isolation %), `UNEMPPCT`, `UNDER5PCT`, `OVER64PCT`, `DEMOGIDX_2` (average of people-of-color% + low-income%, EPA's core demographic index)
- **Environmental**: `PM25` (µg/m³), `OZONE` (ppb), `DSLPM` (diesel PM, µg/m³), `PTRAF` (traffic proximity/volume score), `PNPL` (Superfund/NPL proximity score), `PRMP` (RMP facility proximity score), `PTSDF` (hazardous waste TSDF proximity score), `UST` (underground storage tank count/density), `PWDIS` (wastewater discharge indicator), `NO2` (ppb)

National percentile fields — prefix `P_` on any of the above (e.g. `P_PM25`) — are the number that actually matters for an environmental-justice argument: "this block group is at the Nth percentile nationally," 0–100. `P_DEMOGIDX_2` above 80 is EPA's own rule-of-thumb screening threshold for an EJ area of potential concern.

`ACSTOTPOP` is total population (ACS 5-year estimate) — required for the buffer weighting above; also useful standalone to state how many people live in the affected area.

Other prefixes present on the service, not requested by default above: `D2_`/`D5_` (raw distance-2/distance-5 weighted EJ index scores, not percentiles — do not present these as 0–100 rankings), `P_D2_`/`P_D5_` (the actual national percentiles for those combined EJ indexes), `B_` (1–10 percentile bin), `T_` (pre-formatted "N %ile" text). Prefer the plain `P_` fields for single-indicator percentiles and `P_DEMOGIDX_2`/`P_D2_...` for combined-index percentiles.

---

## Presenting the results

1. **Source disclosure, first line, unavoidable**: "Data from EPA's EJScreen v2.32 dataset (2023 ACS/pollution vintage), served via a community-hosted ArcGIS mirror of EPA's Public Environmental Data Portal — EPA's own `ejscreen.epa.gov` and `screeningtool.geoplatform.gov` are no longer live as of this writing. Retrieved [date]."
2. **Location**: point coordinates, block group ID(s), county/state, and (for a radius report) the radius used and number of block groups included.
3. **Table**: Indicator | Raw Value | National Percentile — demographic indicators first, then environmental/proximity indicators.
4. **Flag any percentile ≥ 80** explicitly in prose — that's EPA's own screening threshold for elevated EJ concern.
5. State population covered (`ACSTOTPOP` sum for a radius report).
6. If a radius report: disclose the population-weighting approximation caveat from Step 2.
7. Cross-link: `bayou:epa-echo-search` for compliance history of specific facilities identified nearby, `bayou:epa-tri-search` for their actual reported releases (the `PNPL`/`PTSDF`/`PTRAF` proximity scores are generic distance-based scores, not facility-specific release data).

### Citation format

> **EJScreen v2.32 (2023 vintage) via ArcGIS mirror of EPA Public Environmental Data Portal**, block group [ID], [County], LA, source: [services2.arcgis.com FeatureServer](https://services2.arcgis.com/w4yiQqB14ZaAGzJq/arcgis/rest/services/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view/FeatureServer/0) (retrieved 2026-07-21) — not EPA's official `ejscreen.epa.gov` (offline). PM2.5: [X] µg/m³ ([Y]th percentile nationally). Demographic Index: [Z]th percentile.

$ARGUMENTS
