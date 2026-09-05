---
name: satellite-imagery
description: Fetch a free satellite image of a place on a given date, auto-selecting the best free source (NASA GIBS, EOX Sentinel-2 cloudless, AWS Earth Search Sentinel-2/Landsat, or Copernicus Data Space) by date specificity, resolution, and true-color vs. thermal/fire need
allowed-tools: Bash, AskUserQuestion, Read
---

# Satellite Imagery Lookup

Given a **location** and a **datetime** (plus optional intent), fetch the best available *free* satellite image, save it as a PNG, and view it. Useful for seeing a facility on the day of an incident (flare, plume, flood, fire), documenting a smoke event, or grabbing a clean recent basemap for a comment letter or map.

No source here costs money. Three are fully keyless (NASA GIBS, EOX Sentinel-2 cloudless, AWS Earth Search); one (Copernicus Data Space) uses a **free** account for true 10 m date-specific crops.

## Tools available in this environment

- `curl` and `python3` (stdlib only — `json`, `csv`, `math`, `subprocess`). Invoke them by name off `PATH`; if `command -v` comes up empty (a non-interactive shell's `PATH` often omits Homebrew), probe `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` as fallbacks rather than hardcoding one prefix.
- **`gdal` is not installed.** The primary paths need only curl + python3. A gdal `/vsicurl/` crop is offered as an *optional* enhancement only if the user has installed gdal.

## Step 0: Parse arguments

- **Location** — one of:
  - a `lat,lon` pair (e.g. `29.9989,-90.4062`) — use directly;
  - an address or place name — geocode with Nominatim (Step 1);
  - a **facility name** (e.g. "Shell Norco", "ExxonMobil Baton Rouge") — prefer `bayou:facility-coordinates` to resolve lat/lon, then continue here.
- **Datetime** — a date `YYYY-MM-DD` (optionally with a time; time matters only for day-vs-night thermal layers). If the user gives a fuzzy date ("late December 2025"), pick a center date and search a window.
- **Intent** (optional keywords, default `truecolor`):
  - `truecolor` — natural-color image on/near the date;
  - `thermal` / `fire` / `flare` / `night` — thermal-anomaly + nighttime layers;
  - `backdrop` / `clean` — a cloud-free basemap where the exact date does not matter;
  - `hires` / `10m` — insist on 10 m detail (Sentinel-2/Landsat).
- **Radius / zoom** (optional) — default a ~0.05° box (~5 km) around the point. Use a larger box (0.2–0.5°) for regional context (wide smoke plumes, floods).

If the place name is ambiguous or no state/city is given, **ask** before fetching — a wrong match silently produces a confident-looking wrong image.

## Step 1: Resolve location → lat/lon and build a BBOX

Skip geocoding if the user already gave `lat,lon`. For an address or place name, use OpenStreetMap Nominatim (free, no key; descriptive `User-Agent`, ~1 req/sec):

```bash
curl -s --get "https://nominatim.openstreetmap.org/search" \
  --data-urlencode "q=Shell Norco, Norco, LA" \
  --data-urlencode "format=json" \
  --data-urlencode "limit=3" \
  -H "User-Agent: bayou-satellite-imagery/1.0 (research lookup)" | python3 -m json.tool
```

Then build a bounding box from the point and a half-box size `H` (degrees):

```bash
python3 -c "
lat, lon, H = 29.9989, -90.4062, 0.05
minx, maxx = lon - H, lon + H
miny, maxy = lat - H, lat + H
print(f'minlon={minx} minlat={miny} maxlon={maxx} maxlat={maxy}')
"
```

Keep both axis orders straight — different APIs disagree:
- **WMS 1.3.0 + EPSG:4326** BBOX is **lat,lon** order → `BBOX=miny,minx,maxy,maxx`.
- **STAC / GeoJSON** bbox is **lon,lat** order → `[minlon,minlat,maxlon,maxlat]`.

## Step 2: Choose the source ("what's best")

| Need | Source | Resolution | Date-specific? | Key? |
|---|---|---|---|---|
| Thermal / fire / flare / night | **GIBS** thermal + Day-Night-Band | 375–750 m | Yes (daily) | No |
| Clean backdrop, date irrelevant | **EOX** s2cloudless mosaic | 10 m | No (annual composite) | No |
| True color, wide area / any date to ~2000, 250 m OK | **GIBS** MODIS/VIIRS true color | 250 m | Yes (daily) | No |
| True color, need 10 m on/near a date | **AWS Earth Search** (find scene) → **Copernicus** (render crop) | 10–30 m | Yes | STAC no / Copernicus free key |

Tell the user which source you picked and the tradeoff (e.g. "GIBS is date-exact but 250 m; Sentinel-2 is 10 m but the nearest low-cloud pass is 3 days off"). Let them override.

## Step 3A: GIBS true color (keyless, date-specific, ~250 m)

Single GetMap call. `TIME` is the acquisition date; MODIS goes back to 2000, VIIRS to ~2012/2018.

```bash
# BBOX is lat,lon order for WMS 1.3.0 EPSG:4326: miny,minx,maxy,maxx
curl -s "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&LAYERS=VIIRS_SNPP_CorrectedReflectance_TrueColor&CRS=EPSG:4326&BBOX=29.9489,-90.4562,30.0489,-90.3562&WIDTH=1024&HEIGHT=1024&TIME=2025-12-21" \
  -o sat_gibs_29.9989_-90.4062_2025-12-21.png
```

True-color layer options (try VIIRS first — 250 m, most recent sensors):
`VIIRS_NOAA20_CorrectedReflectance_TrueColor`, `VIIRS_SNPP_CorrectedReflectance_TrueColor`, `MODIS_Terra_CorrectedReflectance_TrueColor`, `MODIS_Aqua_CorrectedReflectance_TrueColor`.

Discover all layers / valid date ranges:
```bash
curl -s "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities" | head -c 4000
```

**Always sanity-check the output isn't a blank/error tile** (see Step 5). A near-empty file usually means no swath covered that lat/lon on that date — nudge `TIME` ±1 day or switch sensor.

## Step 3B: GIBS thermal / fire / flare / night (keyless, date-specific)

For a flare or fire signature, request the thermal-anomaly layer (transparent points) and, separately, a nighttime layer for after-dark glow. Compose over a true-color or Blue Marble base.

```bash
# Daytime/overpass thermal anomalies (fire detections), transparent PNG over a base
BBOX="29.9489,-90.4562,30.0489,-90.3562"; DATE="2025-12-21"
curl -s "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&LAYERS=VIIRS_SNPP_Thermal_Anomalies_375m_All,VIIRS_NOAA20_Thermal_Anomalies_375m_All&CRS=EPSG:4326&BBOX=${BBOX}&WIDTH=1024&HEIGHT=1024&TIME=${DATE}" \
  -o sat_gibs_thermal_2025-12-21.png

# Nighttime lights / flare glow (Day-Night Band)
curl -s "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&LAYERS=VIIRS_SNPP_DayNightBand_ENCC&CRS=EPSG:4326&BBOX=${BBOX}&WIDTH=1024&HEIGHT=1024&TIME=${DATE}" \
  -o sat_gibs_dnb_2025-12-21.png
```

Other thermal/night layers: `MODIS_Combined_Thermal_Anomalies_All`, `VIIRS_NOAA20_DayNightBand_ENCC`, `VIIRS_Black_Marble`.

**Caveat to always state:** these detect a **thermal anomaly** at 375–750 m per pixel — a hot pixel, not a resolved flame. Absence of a detection does not prove the flare was cold (it may fall between overpasses or below the detection threshold); a detection is strong corroboration of a heat source at that time.

## Step 3C: EOX Sentinel-2 cloudless backdrop (keyless, 10 m, not date-specific)

A cloud-free annual mosaic — great clean basemap, but it is a **composite over a whole year**, not that day.

```bash
curl -s "https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&LAYERS=s2cloudless-2023&CRS=EPSG:4326&BBOX=29.9489,-90.4562,30.0489,-90.3562&WIDTH=1024&HEIGHT=1024" \
  -o sat_eox_cloudless_2023.png
```

Probe the newest available `s2cloudless-YYYY` layer:
```bash
curl -s "https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities" | grep -o "s2cloudless-[0-9]*" | sort -u
```

## Step 3D: 10 m date-specific — find the scene (AWS Earth Search STAC, keyless)

Search for the lowest-cloud Sentinel-2 / Landsat scene within a window around the target date (widen the window if nothing clears the cloud threshold):

```bash
curl -s -X POST "https://earth-search.aws.element84.com/v1/search" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["sentinel-2-l2a", "landsat-c2-l2"],
    "bbox": [-90.4562, 29.9489, -90.3562, 30.0489],
    "datetime": "2025-12-11T00:00:00Z/2025-12-31T23:59:59Z",
    "query": {"eo:cloud_cover": {"lt": 40}},
    "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
    "limit": 10
  }' | python3 -c "
import sys, json
d = json.load(sys.stdin)
feats = d.get('features', [])
print(f'{\"date\":<20} {\"cloud%\":>6}  {\"collection\":<16} id')
for f in feats:
    p = f.get('properties', {})
    print(f\"{p.get('datetime','')[:19]:<20} {p.get('eo:cloud_cover',0):>6.1f}  {f.get('collection',''):<16} {f.get('id','')}\")
    a = f.get('assets', {})
    thumb = (a.get('thumbnail') or a.get('rendered_preview') or {}).get('href','')
    vis = (a.get('visual') or {}).get('href','')
    if thumb: print('    thumbnail:', thumb)
    if vis:   print('    visual COG:', vis)
"
```

Pick the best scene (lowest cloud, closest date). Then either render a real crop (Step 3E, if Copernicus creds) or grab the preview:

```bash
# Keyless fallback: fetch the whole-tile browse preview of the chosen scene
curl -s "PASTE_THUMBNAIL_HREF_HERE" -o sat_s2_preview_2025-12-19.png
```

The thumbnail is a preview of the **entire ~100 km tile**, not a zoom to the facility. For a true crop to the BBOX you need Step 3E (Copernicus) or gdal:

```bash
# OPTIONAL — only if the user installed gdal (`brew install gdal`):
# gdal_translate -projwin minlon maxlat maxlon minlat \
#   /vsicurl/PASTE_VISUAL_COG_HREF_HERE crop.tif && gdal_translate -of PNG crop.tif sat_s2_crop.png
```

## Step 3E: 10 m date-specific crop — Copernicus Data Space (free key)

Renders an exact true-color PNG cropped to the BBOX for a given date. Needs a free Copernicus account.

**Credentials:** Read `~/.claude/bayou-credentials.md` for `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`.
- If absent, tell the user: create a free account at `https://dataspace.copernicus.eu`, then in the dashboard (User Settings → OAuth clients) register a **client-credentials** OAuth client and share the client id + secret. Offer to append a section to `~/.claude/bayou-credentials.md`:
  ```
  ## Copernicus Data Space (dataspace.copernicus.eu)
  CDSE_CLIENT_ID: <id>
  CDSE_CLIENT_SECRET: <secret>
  ```
- Until provided, fall back to Step 3D (keyless STAC thumbnail).

```bash
CDSE_CLIENT_ID="..."; CDSE_CLIENT_SECRET="..."   # from ~/.claude/bayou-credentials.md

TOKEN=$(curl -s -X POST "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CDSE_CLIENT_ID}" \
  -d "client_secret=${CDSE_CLIENT_SECRET}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST "https://sh.dataspace.copernicus.eu/api/v1/process" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "bounds": {"bbox": [-90.4562, 29.9489, -90.3562, 30.0489],
                 "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
      "data": [{
        "type": "sentinel-2-l2a",
        "dataFilter": {"timeRange": {"from": "2025-12-19T00:00:00Z", "to": "2025-12-19T23:59:59Z"},
                       "maxCloudCoverage": 60}
      }]
    },
    "output": {"width": 1024, "height": 1024,
               "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
    "evalscript": "//VERSION=3\nfunction setup(){return{input:[\"B02\",\"B03\",\"B04\"],output:{bands:3}};}\nfunction evaluatePixel(s){return [2.5*s.B04, 2.5*s.B03, 2.5*s.B02];}"
  }' -o sat_copernicus_2025-12-19.png
```

Widen `timeRange` (e.g. a ±5-day window) if a single day returns an empty/black image — Sentinel-2 revisits every ~5 days.

## Step 4: View and report

```bash
ls -la sat_*.png   # confirm a non-trivial file size (a valid PNG is usually >10 KB)
```

Then **Read the saved PNG** to view it inline, and report:
- **Source** and layer/scene id (e.g. "GIBS VIIRS_SNPP_CorrectedReflectance_TrueColor" or "Sentinel-2 L2A scene S2B_...").
- **Capture date** and whether it is exact (GIBS/Sentinel scene) or a composite (EOX).
- **Resolution** (250 m / 375 m / 10 m / 30 m) and **cloud cover** if known.
- **BBOX** and the saved filename (in the current working directory; note it can be moved/renamed).
- Caveats: thermal = anomaly not flame; cloudless = annual composite not the exact day; Nominatim/ECHO coordinate precision (~10–500 m); GIBS gaps between satellite overpasses.

## Step 5: Handle empty / blank results

Free imagery frequently returns a blank, black, or error tile — no swath that day, all cloud, or a bad layer/date. Detect and recover:

```bash
python3 -c "
import os,sys
f=sys.argv[1]
sz=os.path.getsize(f)
print(f'{f}: {sz} bytes')
if sz < 2000: print('  -> likely empty/error tile; try +/-1 day, another sensor, or a wider window')
" sat_gibs_29.9989_-90.4062_2025-12-21.png
```

Recovery order: nudge `TIME` ±1–3 days → switch sensor (VIIRS↔MODIS, SNPP↔NOAA20) → widen the BBOX → for 10 m, widen the STAC date window / raise the cloud threshold. If GIBS returns an XML `ServiceException` instead of an image, the file will be small and start with `<?xml` — open it to read the error.

## Notes & limits

- All endpoints are public, shared government/community services — be polite, avoid batch hammering, retry 5xx with backoff.
- GIBS is best for **date-exact regional context** and **thermal/fire**; EOX for **clean 10 m backdrops**; Sentinel-2/Landsat (STAC + Copernicus) for **10 m detail on a specific date**.
- Straight optical imagery cannot see through clouds; for cloud-penetrating radar on a specific date, the Earth Search `sentinel-1-grd` collection (keyless) is available but needs different (backscatter) rendering — offer it only if asked.

$ARGUMENTS
