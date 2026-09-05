---
name: usgs-historic-topo-lidar
description: Pull georeferenced historic USGS topographic quads and 3DEP 1-meter lidar for a site, crop to a footprint, and render visual-read images and a hillshade — for "what was here before" questions (burial grounds, wetlands loss, structure/community erasure, encroachment history)
argument-hint: <lat,lon> [radius or bbox] [output-dir]
allowed-tools: Bash
---

# USGS Historic Topo + Lidar Screen

Builds a time-series of historic topographic maps plus a modern lidar hillshade over a project footprint, so you can visually read what stood on a parcel decades before a facility, and check for surviving micro-topography a later fill/grading pass didn't fully erase. Used this way for a Louisiana Unmarked Human Burial Sites Preservation Act (R.S. 8:671) documentary screen (see `bayou:unmarked-burial-screen`), but the same pull is useful for wetlands-loss arguments, "this was a community before the plant" claims, or any other before/after siting question.

**This produces images for you to look at, not a machine answer.** The output is a set of PNGs — read them with the `Read` tool and describe what's actually on them (cemetery symbols, structure clusters, marsh vegetation, plantation-name labels, a feature present on one edition and gone on the next). Don't skip the visual-read step and summarize from filenames alone.

## Prerequisites

**GDAL is required and is not installed by default.** Check first:

```bash
command -v gdalwarp gdal_translate gdaldem gdalinfo 2>/dev/null || echo "MISSING"
```

If missing, install via Homebrew: `brew install gdal` (this can take several minutes — the dependency tree is large; run it in the background and continue other setup while it builds). **Do not use `conda create -n <env> gdal` in this environment** — it has been observed to fail with `CondaSSLError: ... self-signed certificate in certificate chain`, apparently because conda's bundled certifi store doesn't trust a certificate the network path here presents, even though the system trust store (and therefore `curl`, and therefore Homebrew's own fetches) is fine with it. If Homebrew isn't available either, resolving that SSL/proxy mismatch is a prerequisite in its own right — don't just retry conda.

Resolve `gdalwarp`/`gdal_translate`/`gdaldem` off `PATH` first, then fall back to `/opt/homebrew/bin/<tool>` (this machine's non-interactive shells don't inherit Homebrew's `PATH`).

## Step 1: Find available historic topo editions over the site

```bash
LAT=29.959211
LON=-90.332609
# a box roughly 0.03° (~3km) around the point is a reasonable starting search radius
curl -s --compressed \
  "https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Historical%20Topographic%20Maps&bbox=$(python3 -c "print(f'{$LON-0.03},{$LAT-0.03},{$LON+0.03},{$LAT+0.03}')")&max=60&outputFormat=JSON" \
  -o topo_products.json
python3 -c "
import json
d = json.load(open('topo_products.json'))
print('total:', d['total'])
for item in d['items']:
    bbox = item.get('boundingBox', {})
    print(item.get('publicationDate'), '|', item.get('title'), '|', item.get('sourceId'), '|', bbox)
" | sort
```

**The API's own `bbox` filter is a loose spatial intersection, not a guarantee every returned item actually covers your point.** Each item's `boundingBox` field in the response is the ground truth — check it against your lat/lon before downloading, don't assume the query did that for you.

**Duplicate `sourceId`s with an identical title, year, and bbox are normal** — they're different scans/print states of the same map sheet (state archive copy vs. USGS copy, etc.). Pick any one; downloading all of them wastes bandwidth for no benefit.

Pick one edition roughly every 10–20 years across the available range, favoring the largest scale (smallest denominator, e.g. 1:24,000 over 1:62,500) available for a given era, and bracketing any known construction/disturbance date (e.g., an edition just before and just after a facility was first built nearby).

For lidar, swap the dataset: `datasets=Digital%20Elevation%20Model%20(DEM)%201%20meter`. Lidar tiles are large (~450MB for a 1°×1° USGS 1m DEM project tile) — `curl -sI` the `downloadURL` first to check `Content-Length`, and download in the background (`run_in_background: true`) rather than blocking on it.

## Step 2: Download

```bash
curl -s -o "<descriptive-name>_geo.pdf" "<downloadURL from topo_products.json>"
file "<descriptive-name>_geo.pdf"   # confirm it's actually a PDF, not an HTML error page
```

Historic topo quads download as **GeoPDFs** — ordinary PDFs with embedded georeferencing (`gdalinfo` will show a `PROJCRS`/coordinate system block; usually NAD27 for pre-1980s editions). Lidar tiles download as GeoTIFF.

## Step 3: Crop each sheet to the footprint

```bash
LAT=29.959211
LON=-90.332609
DLAT=0.011   # ~1.2km half-height — adjust to the footprint's actual size
DLON=0.013   # ~1.2km half-width at this latitude

gdalwarp -q -overwrite -t_srs EPSG:4326 -r cubic \
  -te $(python3 -c "print($LON-$DLON, $LAT-$DLAT, $LON+$DLON, $LAT+$DLAT)") \
  -ts 1600 0 \
  "<descriptive-name>_geo.pdf" "crop_<descriptive-name>.tif"
gdal_translate -q -of PNG "crop_<descriptive-name>.tif" "crop_<descriptive-name>.png"
rm -f "crop_<descriptive-name>.tif" "crop_<descriptive-name>.tif.aux.xml"
```

`-ts 1600 0` fixes width to 1600px and lets height follow the aspect ratio automatically. The `Read` tool cannot view GeoTIFF — always convert to PNG.

**Your first guess at a crop window is often wrong** — a feature you're looking for (a cemetery label, a town name) may fall just outside it. If a first crop misses the feature, don't fight with pixel math: widen the crop, re-read, then narrow it once you can see roughly where the feature sits. Two iterations is normal, not a sign of doing it wrong.

**To convert a map position back to lat/lon** (e.g., you spotted a labeled feature and want its approximate coordinates): note the crop's bbox and output image dimensions, then linearly interpolate the feature's pixel position — `lon = min_lon + (x/width)*(max_lon-min_lon)`, `lat = max_lat - (y/height)*(max_lat-min_lat)` (image y increases downward, latitude decreases downward — mind the sign). This is a hand-eye pixel pick, not a geocode: state the result as approximate with an explicit error margin (a mis-click of even 30px at typical crop scales can be 100–300m), and don't round-trip it as if it were survey-grade.

## Step 4: Lidar hillshade

```bash
gdalwarp -q -overwrite -t_srs EPSG:4326 -r bilinear \
  -te <minlon> <minlat> <maxlon> <maxlat> \
  "<lidar-tile>.tif" "footprint_dem_wgs84.tif"
gdaldem hillshade -z 5 -az 315 -alt 30 footprint_dem_wgs84.tif hillshade.tif -q
gdal_translate -q -of PNG hillshade.tif hillshade.png
rm -f hillshade.tif hillshade.tif.aux.xml footprint_dem_wgs84.tif.aux.xml
```

`-z 5` exaggerates vertical relief 5×, which is what makes subtle ditches, old field boundaries, and building pads visible in flat Louisiana terrain — at true 1:1 relief almost nothing shows.

**Read the hillshade for what it is, not what you're hoping for.** USGS 3DEP lidar is typically flown post-2010 — it shows *current* micro-topography, which is only informative about a pre-disturbance landscape if nothing has graded or filled the area since. It also cannot resolve individual grave shafts at 1m resolution unless they're part of a plotted, formally-arranged cemetery with a visible rectilinear layout. If you see a geometrically regular but unexplained feature (a clean rectangle, an enclosure), report it as exactly that — "anomalous, warrants field verification" — and do not characterize it as graves, foundations, or anything else you can't actually confirm from the DEM alone.

## Presenting results

For each edition: year, scale, sourceId, and — as prose, from actually reading the image — what's visible at/near the footprint (structures, vegetation/marsh symbols, named features, and anything present on one edition but gone on a later one, which is often the most informative single observation in the whole series). State the retrieval date and note if a feature's absence from a map is being used as evidence (it usually is weaker evidence than presence, since maps of this era don't reliably show unmarked/informal features regardless of location).

### Citation format

> **USGS 1:24,000 Historical Topographic Quadrangle, "Luling, LA," 1967**, source: [USGS TNM Access](https://tnmaccess.nationalmap.gov/api/v1/products) (retrieved 2026-07-22).
>
> **USGS 3DEP 1-meter DEM**, project `LA_UpperDeltaPlain_2017`, source: [USGS TNM Access](https://tnmaccess.nationalmap.gov/api/v1/products) (retrieved 2026-07-22).

$ARGUMENTS
