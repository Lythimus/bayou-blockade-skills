---
name: phmsa-npms-search
description: Search PHMSA NPMS pipeline mapping for gas, hazardous liquid, and crude oil pipelines near a facility or by operator — supports geographic queries, incident/accident history, and enforcement actions
allowed-tools: Bash, WebFetch, AskUserQuestion
---

# PHMSA NPMS Pipeline Mapping Search

Search for pipelines near a facility, by operator name, or by state. Pulls from two sources: the **DOT BTS ArcGIS service** for geographic queries (fully open REST API) and the **NPMS Public Viewer** + **PRIMIS** for incident history and enforcement.

## Context: why this matters

The NPMS restricts the full shapefile data (post-9/11 security), but the DOT Bureau of Transportation Statistics publishes EIA-derived pipeline data as queryable ArcGIS MapServer layers — no authentication required. These cover major transmission pipelines (gas, HGL, crude oil). Incident and enforcement records are available through the NPMS viewer and PHMSA PRIMIS.

---

## Parsing arguments

The user may provide:
- A **facility name or location** (e.g., "Waterford Nuclear", "St. Charles Parish", "Hahnville LA")
- **Coordinates** (lat/lon) and optional **radius** (miles)
- An **operator name** (e.g., "Tennessee Gas Pipeline", "Gulf South")
- A **commodity type**: natural gas, crude oil, hazardous gas liquids (HGL), or all
- A request for **incidents**, **accidents**, or **enforcement actions**

If only a facility name is given, use known coordinates or ask for a general location to build the bounding box.

**Waterford Nuclear (29.9985° N, 90.4791° W)** is the primary site for this project. Default to a 50-mile bounding box (~0.75° lat/lon padding each direction) unless the user specifies otherwise.

---

## Source 1: DOT BTS ArcGIS — Geographic Pipeline Queries

Base URL pattern:
```
https://geo.dot.gov/server/rest/services/BTS/{LAYER}/MapServer/0/query
```

Available layers:

| Layer | Commodity | Fields |
|---|---|---|
| `NaturalGas_Pipelines_US_202001` | Natural gas (interstate, intrastate, gathering) | `Operator`, `TYPEPIPE`, `Status` |
| `HGL_Pipelines_US_202001` | Hazardous gas liquids (NGL, propane, ethylene) | `Opername`, `Pipename` |
| `CrudeOil_Pipelines_US_202001` | Crude oil and petroleum products | `Opername`, `Pipename` |

Data vintage: January 2020 (EIA-compiled). Suitable for identifying major operators and corridors; does not reflect every small-diameter or recently approved pipeline.

### Step 1: Query by geographic bounding box

```bash
# Natural gas pipelines within bounding box (WGS84)
# Replace xmin/ymin/xmax/ymax with your coordinates
XMIN=-91.5; YMIN=29.0; XMAX=-89.5; YMAX=31.0
curl -s "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0/query?f=json&where=1%3D1&outFields=Operator%2CTYPEPIPE%2CStatus&geometryType=esriGeometryEnvelope&geometry=%7B%22xmin%22%3A${XMIN}%2C%22ymin%22%3A${YMIN}%2C%22xmax%22%3A${XMAX}%2C%22ymax%22%3A${YMAX}%2C%22spatialReference%22%3A%7B%22wkid%22%3A4326%7D%7D&inSR=4326&spatialRel=esriSpatialRelIntersects&returnGeometry=false&returnDistinctValues=true&resultRecordCount=500" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
seen = set()
for f in d.get('features', []):
    a = f['attributes']
    key = (a.get('Operator','') or a.get('Opername',''), a.get('TYPEPIPE',''), a.get('Status',''))
    seen.add(key)
for row in sorted(seen):
    print(' | '.join(str(x) for x in row))
print(f'--- {len(seen)} unique pipeline entries ---')
"
```

Run this query for each commodity layer (`NaturalGas_Pipelines_US_202001`, `HGL_Pipelines_US_202001`, `CrudeOil_Pipelines_US_202001`). For HGL and crude oil, use `Opername%2CPipename` in `outFields`.

### Step 2: Query by operator name (attribute filter)

```bash
OP="Gulf South"   # partial match
curl -s "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0/query?f=json&where=Operator+LIKE+%27%25${OP}%25%27&outFields=Operator%2CTYPEPIPE%2CStatus&returnGeometry=false&returnDistinctValues=true&resultRecordCount=200" \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
seen = set()
for f in d.get('features', []):
    a = f['attributes']
    seen.add((a.get('Operator'), a.get('TYPEPIPE'), a.get('Status')))
for r in sorted(seen):
    print(r)
"
```

### Step 3: Get pipeline segment geometry (optional, for proximity analysis)

Add `returnGeometry=true&outSR=4326` to retrieve path coordinates as `[lon, lat]` pairs:

```bash
# Returns polyline paths — each feature has geometry.paths[][point_index][lon, lat]
curl -s "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0/query?f=json&where=1%3D1&outFields=Operator%2CTYPEPIPE&geometryType=esriGeometryEnvelope&geometry=...&inSR=4326&spatialRel=esriSpatialRelIntersects&returnGeometry=true&outSR=4326&resultRecordCount=50" \
  2>/dev/null | python3 -c "
import sys, json, math
d = json.load(sys.stdin)
site_lat, site_lon = 29.9985, -90.4791   # Waterford Nuclear

def dist_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2-lat1); dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

results = []
for f in d.get('features', []):
    a = f['attributes']
    paths = f.get('geometry', {}).get('paths', [])
    min_dist = float('inf')
    for path in paths:
        for pt in path:
            d2 = dist_miles(site_lat, site_lon, pt[1], pt[0])
            min_dist = min(min_dist, d2)
    results.append((min_dist, a.get('Operator'), a.get('TYPEPIPE')))

for dist, op, typ in sorted(results):
    if dist < 30:
        print(f'{dist:.1f} mi | {op} | {typ}')
"
```

---

## Source 2: NPMS Public Viewer — Incidents & Accidents

The NPMS viewer (pvnpms.phmsa.dot.gov) has incident/accident query tools for 2002–present. These require WebFetch since the underlying REST API is session-protected.

### Gas pipeline incidents (2002–present)

```
WebFetch url="https://pvnpms.phmsa.dot.gov/PublicViewer/" prompt="Navigate to the Query menu and select 'Query Incidents (Gas)'. Search for incidents in Louisiana (state = LA). List all results including: date, operator name, commodity, cause, location (city/county/state), fatalities, injuries, and property damage. Return the full table."
```

### Liquid pipeline accidents (2002–present)

```
WebFetch url="https://pvnpms.phmsa.dot.gov/PublicViewer/" prompt="Navigate to the Query menu and select 'Query Accidents (Liquid)'. Filter by state: Louisiana. Return all results including: date, operator, system name, cause, barrels released, fatalities, injuries, and property damage."
```

### Pipeline operator search

```
WebFetch url="https://pvnpms.phmsa.dot.gov/PublicViewer/" prompt="Use the 'Search by Operator' function to find pipelines for operator [OPERATOR_NAME]. List all pipeline systems returned, including their NPMS operator ID, pipeline name, commodity type, and operating state(s)."
```

---

## Source 3: PHMSA PRIMIS — Enforcement Actions

PRIMIS (primis.phmsa.dot.gov) is the Pipeline Safety Stakeholder Communications system. It tracks enforcement actions, compliance orders, and penalty assessments against pipeline operators.

```
WebFetch url="https://primis.phmsa.dot.gov/enforcement-data/" prompt="Search for enforcement actions against [OPERATOR_NAME]. List all actions found including: case number (CPF number), operator name, violation type, enforcement type (notice of probable violation, compliance order, civil penalty, etc.), penalty amount, and case status. Also note the date of each action."
```

For operator-specific detail:
```
WebFetch url="https://primis.phmsa.dot.gov/enforcement-data/comm/reports/operator/OperatorIL.html?opid=OPERATOR_ID" prompt="Extract the full operator information including: safety record, inspection history, incidents, compliance status, and any enforcement actions listed."
```

---

## Workflow for a facility proximity search

1. **Identify the bounding box** — use the facility coordinates to define ±0.75° (~50 mi) box
2. **Query all three BTS layers** — natural gas, HGL, crude oil — for pipelines in the box
3. **Deduplicate by operator** — note interstate vs. intrastate, commodity, and status
4. **For key operators found**, query NPMS viewer for incidents and PRIMIS for enforcement actions
5. **Optional**: request geometry to compute closest approach distance to the facility

**Waterford Nuclear bounding box (50-mile radius)**:
- xmin = -91.5, ymin = 29.0, xmax = -89.5, ymax = 31.0 (WGS84)

---

## How to present results

### Pipeline table

| Operator | Type | Commodity | Status | Pipe Name (if avail.) |
|---|---|---|---|---|
| Tennessee Gas Pipeline | Interstate | Natural Gas | Operating | — |
| Gulf South Pipeline Co | Interstate | Natural Gas | Operating | — |
| Enterprise Products | — | HGL | Operating | Dixie |

- Flag **interstate gas pipelines** — these are subject to FERC jurisdiction and PHMSA federal inspection
- Note when a pipeline is within **1 mile** of the facility (high proximity risk)
- Separate by commodity: gas transmission (highest consequence if near facility), HGL, crude

### Incident/accident summary

- Table: Date | Operator | System | Cause | Injuries | Fatalities | Damage ($)
- Flag any incidents within 25 miles of the facility
- Note repeat incidents by the same operator

### Enforcement summary

- Flag operators with active or recent enforcement actions
- Note civil penalty amounts and compliance order status
- Link to PRIMIS case detail

### NPMS data caveat

The BTS geographic data is EIA-sourced as of January 2020. It covers **major transmission pipelines** (typically > 4" diameter on transmission systems) and may omit smaller gathering lines, recently constructed pipelines, and some intrastate lines not reported to EIA. The NPMS full dataset held by PHMSA is restricted to government agencies under post-9/11 security rules. Use WebFetch to the public viewer for the most current mapping.

---

## Key reference URLs

- NPMS Public Viewer: `https://pvnpms.phmsa.dot.gov/PublicViewer/`
- PRIMIS Enforcement: `https://primis.phmsa.dot.gov/enforcement-data/`
- PHMSA Pipeline Safety Data: `https://www.phmsa.dot.gov/data-and-statistics/pipeline`
- BTS NatGas MapServer: `https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer`
- BTS HGL MapServer: `https://geo.dot.gov/server/rest/services/BTS/HGL_Pipelines_US_202001/MapServer`
- BTS Crude Oil MapServer: `https://geo.dot.gov/server/rest/services/BTS/CrudeOil_Pipelines_US_202001/MapServer`

$ARGUMENTS
