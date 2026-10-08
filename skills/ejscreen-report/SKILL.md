---
name: ejscreen-report
description: Pull EPA EJScreen environmental-justice indicators (demographics, pollution burden, proximity scores) for a point or radius, from a live community-hosted mirror of the official dataset, and corroborate a facility's demographics against EPA ECHO's official ACS profile
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

Also list the **per-block-group values**, not just the weighted average. A whole-block-group buffer can mix a small, heavily burdened fenceline pocket with larger low-burden neighborhoods, and the average hides the pocket (see the worked example in Step 3).

## Step 3: Official-record corroboration via EPA ECHO

EJScreen's mirror is genuine EPA data, but it isn't hosted by EPA, and an agency or applicant can use that to dismiss it. For the **demographic** half of the report there is still an official, EPA-hosted source. ECHO's Detailed Facility Report (DFR) carries an ACS demographic profile for a 1-mile radius around each regulated facility. Use EJScreen to find areas of concern, then cite ECHO as the official record for the demographic facts.

Use this step whenever the report centers on a regulated facility. Get its FRS RegistryID from `bayou:epa-echo-search` or `bayou:epa-frs-crosswalk`.

```bash
REGISTRY_ID=110071940897   # Shell Norco refinery

curl -s "https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?output=JSON&p_id=${REGISTRY_ID}" 2>/dev/null | python3 -c "
import sys, json
r = json.load(sys.stdin).get('Results', {})
if r.get('Error'):
    sys.exit(f'ECHO error: {r[\"Error\"]}')
# Newest vintage first; ECHO keeps the prior year alongside it.
for block in ('ACS2024Demographics', 'ACS2023Demographics'):
    d = r.get(block)
    if d:
        print(block)
        for k in ('Radius','CenterLatitude','CenterLongitude','ACSPopulation','PercentPeopleOfColor',
                  'PercentBelowLowIncomeLevel','PercentBelowPovertyLevel','AfricanAmerican','HispanicOrigin',
                  'Minors','Seniors','Less9thGrade','Grades9to12','IncomeLess15k'):
            print(f'  {k}: {d.get(k)}')
        break
else:
    print('No ACS demographics block in DFR')
"
```

What ECHO gives you, and what it doesn't (verified live 2026-10-07):
- **The radius is fixed at 1 mile.** `p_radius`, `p_dist`, and `radius` are silently ignored. For 3- or 5-mile radii, EJScreen is the only source.
- **It is anchored to the facility.** It centers on ECHO's own facility coordinate (`CenterLatitude`/`CenterLongitude`, usually the entrance point), not on an arbitrary lat/lon. For a proposed site that has no RegistryID yet, EJScreen is the only source.
- **It has raw counts and percents only.** It has no national percentiles, no EJ indexes, and no pollution or proximity indicators. The ≥80th-percentile screening threshold and every environmental indicator still come from EJScreen.
- The demographic fields in ECHO's facility *search* (`FacPercentMinority`, `PercentPeopleOfColor`, `PercentBelowLowincome3mile`, `AcsPopulationDensity`) are still listed in the metadata but come back null. Use the DFR.

Field correspondence (EJScreen raw `*PCT` fields are **fractions 0–1**; ECHO's are formatted strings like `"16%"`):

| ECHO DFR | EJScreen |
|---|---|
| `ACSPopulation` | `ACSTOTPOP` (summed across block groups) |
| `PercentPeopleOfColor` | `PEOPCOLORPCT` |
| `PercentBelowLowIncomeLevel` | `LOWINCPCT` |

**Expect the two sources to disagree, and report both side by side without reconciling them.** They use different ACS vintages (EJScreen v2.32 uses the 2018–2022 ACS 5-year; ECHO labels its block by a later release year). They also use different geometry: ECHO clips an exact circle, while Step 2 takes whole intersecting block groups. And they can use different center points.

Worked example: Shell Norco, at ECHO's center point 29.99435, −90.40726, checked 2026-10-07.

| | ECHO DFR (1-mi circle) | EJScreen Step 2 (6 whole block groups) |
|---|---|---|
| Population | 1,391 | 7,294 |
| People of color | 16% | 28% (weighted) |
| Low-income | 39% | 26% (weighted) |

One of those block groups, 220890627001, is 67% people of color and at the 83rd national demographic percentile. ECHO's circle captures little of it, and EJScreen's weighted average dilutes it to 39th. Neither number is wrong. Each answers a different question, which is why the per-block-group listing from Step 2 matters.

## Field reference

Raw indicators (facility/area's actual values):
- **Demographic**: `PEOPCOLORPCT` (people of color %), `LOWINCPCT` (low-income %), `LESSHSPCT` (less than HS education %), `LINGISOPCT` (linguistic isolation %), `UNEMPPCT`, `UNDER5PCT`, `OVER64PCT`, `DEMOGIDX_2` (average of people-of-color% + low-income%, EPA's core demographic index)
- **Environmental**: `PM25` (µg/m³), `OZONE` (ppb), `DSLPM` (diesel PM, µg/m³), `PTRAF` (traffic proximity/volume score), `PNPL` (Superfund/NPL proximity score), `PRMP` (RMP facility proximity score), `PTSDF` (hazardous waste TSDF proximity score), `UST` (underground storage tank count/density), `PWDIS` (wastewater discharge indicator), `NO2` (ppb)

National percentile fields — prefix `P_` on any of the above (e.g. `P_PM25`) — are the number that actually matters for an environmental-justice argument: "this block group is at the Nth percentile nationally," 0–100. `P_DEMOGIDX_2` above 80 is EPA's own rule-of-thumb screening threshold for an EJ area of potential concern.

`ACSTOTPOP` is total population (ACS 5-year estimate) — required for the buffer weighting above; also useful standalone to state how many people live in the affected area.

Other prefixes present on the service, not requested by default above: `D2_`/`D5_` (raw distance-2/distance-5 weighted EJ index scores, not percentiles — do not present these as 0–100 rankings), `P_D2_`/`P_D5_` (the actual national percentiles for those combined EJ indexes), `B_` (1–10 percentile bin), `T_` (pre-formatted "N %ile" text). Prefer the plain `P_` fields for single-indicator percentiles and `P_DEMOGIDX_2`/`P_D2_...` for combined-index percentiles.

---

## Presenting the results

1. **Source disclosure, first line, unavoidable**: "Data from EPA's EJScreen v2.32 dataset (2023 ACS/pollution vintage), served via a community-hosted ArcGIS mirror of EPA's Public Environmental Data Portal — EPA's own `ejscreen.epa.gov` and `screeningtool.geoplatform.gov` are no longer live as of this writing. Retrieved [date]."
2. **Location**: point coordinates, block group ID(s), county/state, and (for a radius report) the radius used and number of block groups included.
3. **Table**: Indicator | Raw Value | National Percentile — demographic indicators first, then environmental/proximity indicators. If Step 3 ran, add an **"ECHO official (ACS, 1 mi)"** column, filled for the demographic rows only.
4. **Flag any percentile ≥ 80** explicitly in prose — that's EPA's own screening threshold for elevated EJ concern.
5. State population covered (`ACSTOTPOP` sum for a radius report).
6. If a radius report: disclose the population-weighting approximation caveat from Step 2.
7. **Splitting citations for a filed comment.** Cite demographic facts (population, people of color, low-income) to ECHO first, because ECHO is the EPA-hosted record. Cite percentile rankings, the ≥80th-percentile threshold, and environmental indicators to EJScreen, since ECHO has no equivalent. Both sources are cited openly. Never word an ECHO figure as though it confirms an EJScreen percentile.
8. Cross-link: `bayou:epa-echo-search` for compliance history of specific facilities identified nearby, as well as the DFR demographics in Step 3. Use `bayou:epa-tri-search` for their actual reported releases (the `PNPL`/`PTSDF`/`PTRAF` proximity scores are generic distance-based scores, not facility-specific release data).

### Citation format

> **EJScreen v2.32 (2023 vintage) via ArcGIS mirror of EPA Public Environmental Data Portal**, block group [ID], [County], LA, source: [services2.arcgis.com FeatureServer](https://services2.arcgis.com/w4yiQqB14ZaAGzJq/arcgis/rest/services/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view/FeatureServer/0) (retrieved 2026-07-21) — not EPA's official `ejscreen.epa.gov` (offline). PM2.5: [X] µg/m³ ([Y]th percentile nationally). Demographic Index: [Z]th percentile.

> **EPA ECHO Detailed Facility Report**, [Facility Name] (FRS [RegistryID]), ACS demographic profile, 1-mile radius, [ACS block label, e.g. ACS2024], source: [echo.epa.gov](https://echo.epa.gov/detailed-facility-report?fid=[RegistryID]) (retrieved [date]). Population [N]; people of color [X]%; below low-income level [Y]%.

$ARGUMENTS
