---
name: facility-coordinates
description: Look up GPS coordinates (lat/lon) for a petrochemical, O&G, utility, or industrial facility by name and approximate location using EPA ECHO
allowed-tools: Bash, AskUserQuestion
---

# Facility GPS Coordinate Lookup

Resolve the GPS coordinates (WGS84 decimal degrees) for a named industrial facility using the EPA ECHO Facility Registry. Useful as a first step before geographic queries in other bayou skills (e.g., `bayou:phmsa-npms-search` needs lat/lon as input).

## Parsing arguments

The user may provide:
- A **facility name** (e.g., "Waterford 3", "ExxonMobil Baton Rouge Refinery", "Nucor Steel")
- A **state** abbreviation (e.g., `LA`) — required if name is ambiguous
- A **city**, **parish/county**, or **zip code** — optional but helps narrow results

If both state and city are missing and the name could match multiple facilities, ask for the state.

## How to look up coordinates

ECHO splits coordinates across two response formats from the same query session. Both requests use the same QID obtained from the initial name search.

### Step 1: Search by name → get QID

```bash
NAME="FACILITY NAME HERE"
STATE="LA"
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_facilities?output=json&p_fn=${NAME}&p_st=${STATE}&p_rows=25" 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('Results', {})
print('QID:', r.get('QueryID'), '  Rows:', r.get('QueryRows'))
"
```

Save the `QID` for steps 2 and 3.

If `QueryRows` is 0, try a shorter name fragment. If it is very high (>200), add `p_city` or `p_zip` to narrow.

### Step 2: Get latitude (JSON) + facility list

```bash
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_qid?output=json&qid=QID&pageno=1&p_rows=25" 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
print('RegistryID | FacName | FacLat | FacCity | FacState | FacMapIcon')
for f in d.get('Results', {}).get('Facilities', []):
    print(f.get('RegistryID'), '|',
          f.get('FacName'), '|',
          f.get('FacLat'), '|',
          f.get('FacCity'), '|',
          f.get('FacState'), '|',
          f.get('FacMapIcon'))
"
```

Facilities with `FacMapIcon` containing `no_ll` do not have georeferenced coordinates in ECHO.

### Step 3: Get longitude (CSV download)

```bash
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_download?output=csv&qid=QID" 2>/dev/null | \
  python3 -c "
import sys, csv
print('RegistryID | FacName | FacLong | FacStreet | FacCity')
for row in csv.DictReader(sys.stdin):
    print(row.get('RegistryID'), '|',
          row.get('FacName'), '|',
          row.get('FacLong'), '|',
          row.get('FacStreet'), '|',
          row.get('FacCity'))
"
```

### Step 4: Combine by RegistryID

```bash
# Single command to get both lat and lon for all facilities in a QID
curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_qid?output=json&qid=QID&pageno=1&p_rows=25" 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
lats = {}
for f in d.get('Results', {}).get('Facilities', []):
    lats[f.get('RegistryID')] = (f.get('FacName'), f.get('FacLat'), f.get('FacCity'), f.get('FacState'), f.get('FacMapIcon'))
import json; [print(r) for r in lats.items()]
" > /tmp/echo_lats.txt

curl -s "https://echodata.epa.gov/echo/echo_rest_services.get_download?output=csv&qid=QID" 2>/dev/null | \
  python3 -c "
import sys, csv
lons = {}
for row in csv.DictReader(sys.stdin):
    lons[row.get('RegistryID')] = row.get('FacLong')
import json; [print(r) for r in lons.items()]
" > /tmp/echo_lons.txt
```

Or as a single combined script:

```bash
QID=YOUR_QID

python3 - <<'EOF'
import subprocess, json, csv, io

lat_resp = subprocess.run([
    'curl', '-s',
    f'https://echodata.epa.gov/echo/echo_rest_services.get_qid?output=json&qid={QID}&pageno=1&p_rows=50'
], capture_output=True, text=True).stdout
lats = {}
for f in json.loads(lat_resp).get('Results', {}).get('Facilities', []):
    lats[f['RegistryID']] = {'name': f.get('FacName'), 'lat': f.get('FacLat'),
                              'city': f.get('FacCity'), 'state': f.get('FacState'),
                              'no_coords': 'no_ll' in (f.get('FacMapIcon') or '')}

lon_resp = subprocess.run([
    'curl', '-s',
    f'https://echodata.epa.gov/echo/echo_rest_services.get_download?output=csv&qid={QID}'
], capture_output=True, text=True).stdout
lons = {r['RegistryID']: r.get('FacLong') for r in csv.DictReader(io.StringIO(lon_resp))}

print(f"{'RegistryID':<15} {'Latitude':>10} {'Longitude':>11}  {'Name'}")
print('-' * 80)
for rid, info in lats.items():
    lat = info['lat'] or '(none)'
    lon = lons.get(rid) or '(none)'
    flag = ' [no coords in ECHO]' if info['no_coords'] else ''
    print(f"{rid:<15} {lat:>10} {lon:>11}  {info['name']}{flag}")
EOF
```

Replace `YOUR_QID` with the QID from step 1.

---

## If ECHO has no coordinates for the facility

Some facilities (especially small or inactive ones) have `no_ll` in their map icon, meaning ECHO lacks georeferenced coordinates. In that case:

1. **Use the street address** from `FacStreet`, `FacCity`, `FacState`, `FacZip` to geocode manually
2. **Cross-reference NRC ADAMS** (`bayou:nrc-adams-search`) for nuclear facilities — site coordinates appear in license documents
3. **Search Google Maps / OpenStreetMap** with the address for visual verification

---

## How to present results

Show a clean coordinate table:

| Facility | RegistryID | Latitude | Longitude | Address |
|---|---|---|---|---|
| Waterford 3 Steam Electric Station | 110002042414 | 29.9952 | -90.4656 | 17265 River Rd, Killona, LA |

- Include the ECHO detail link: `https://echo.epa.gov/facilities/facility-search/facility?fid=REGISTRY_ID`
- If coordinates are missing, show the address and note that ECHO lacks georeferenced data
- If multiple matches exist, show all and ask the user to confirm which facility is correct
- Note the source: "Coordinates from EPA ECHO Facility Registry"

---

## Coordinate precision note

ECHO coordinates are typically accurate to ~100–500 meters for large industrial sites. For precise site boundary work (e.g., setback calculations, fence-line monitoring), verify against USGS topographic maps or the facility's NRC/FERC license documents.

Cross-link `bayou:epa-frs-crosswalk` for full program-ID resolution on the same `RegistryID` — TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP `E-GGRT`, and LDEQ's `LA-TEMPO` ID.

$ARGUMENTS
