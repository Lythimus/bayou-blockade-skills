---
name: la-species-cultural-review
description: Check Louisiana rare/threatened/endangered species tracking lists, draft an LDWF Wildlife Diversity project-review request, list the federally listed species NMFS and FWS map at a point (Section 7 consultation areas, IPaC, critical habitat), find surveyed colonial waterbird nesting colonies near a coastal site with nest counts and aerial imagery (Gulfwide Avian Colony Monitoring), search the National Register of Historic Places near a project site, and list the tribes with a Section 106 consultation interest in the parish — the NEPA/ESA/Section 106 review bundle
allowed-tools: Bash, AskUserQuestion
---

# Louisiana Species & Cultural Resource Review

Bundles the data sources typically needed for an ESA / NEPA / Section 106 review of a Louisiana project or facility: LDWF's statewide rare-species tracking lists, the LDWF Wildlife Diversity Program's formal project-review request process, the federal Services' own maps of listed species at a point (NMFS Section 7 consultation areas and FWS IPaC), surveyed colonial waterbird nesting colonies along the coast (Gulfwide Avian Colony Monitoring), the National Register of Historic Places (NRHP) via a live NPS spatial layer, and HUD's directory of tribes with a consultation interest in each parish.

**Correction to the original bookmark list**: the Louisiana Division of Historic Preservation's own historic-property database is unreachable (connection fails outright). Use the **NPS National Register of Historic Places ArcGIS layer** instead (Step 3 below) — it's the authoritative national dataset LDHP itself feeds into, live-verified, no key required. Also, LDWF's rare-species data is **not** organized as one PDF per parish as the bookmark description assumed — it's four statewide tracking-list PDFs (animals, plants, natural communities, combined) plus a formal data-request process for parcel-specific results.

## Parsing arguments

The user may provide:
- A **project location** (facility name, address, or lat/lon) — for the federal ESA check (Step 2b), the waterbird colony search (Step 2c) and the NRHP proximity search
- A **species or taxon** of interest — to check against the LDWF tracking lists
- A **parish** — for the tribal consultation list (Step 4)
- A request to **draft a Wildlife Diversity Project Review request** — this produces a ready-to-send letter/email, it does not submit anything automatically (LDWF requires a $30/quad fee and processes requests manually)

## Step 1: LDWF rare species and natural communities — statewide tracking lists

```bash
curl -s -L "https://www.wlf.louisiana.gov/assets/Conservation/Protecting_Wildlife_Diversity/Files/rare_animals_plants_natural_communities_tracking_list_2022.pdf" -o /tmp/la-rare-species-2022.pdf 2>/dev/null
pdftotext -layout /tmp/la-rare-species-2022.pdf - 2>/dev/null | rg -i "<search term>"
```

`pdftotext` comes from poppler (`brew install poppler` / `apt install poppler-utils`). If `command -v pdftotext` comes up empty (a non-interactive shell's `PATH` often omits Homebrew), probe `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` as fallbacks rather than hardcoding one prefix.

Individual lists (animals only, plants only, natural communities only) are also available at the same path with `rare_animals_tracking_list_2022.pdf` / `rare_plants_tracking_list_2022.pdf` / `rare_natural_communities_tracking_list_2022.pdf`. These lists are **statewide** — they show a species' state/global rarity rank and federal/state legal status (e.g. `G1`/`S1` = critically imperiled, `LE`/`LT` = federally listed endangered/threatened), not location-specific occurrences. Check the filename year against the live page (`wlf.louisiana.gov/page/rare-species-and-natural-communities-by-parish`) before using — LDWF updates this periodically and the 2022 vintage may be superseded.

**This tells you whether a species is tracked/listed at all — it does not tell you whether it occurs at a specific project site.** For a site-specific answer, LDWF requires the formal request in Step 2; there is no public API or downloadable occurrence database by location.

## Step 2: Draft (not submit) a Wildlife Diversity Project Review request

LDWF's Natural Heritage Program will check a project footprint against their occurrence database for a fee, but only via written request — draft this for the user to send, don't attempt to automate submission:

**Send to:** Carolyn Michon, Assistant Data Manager — `cmichon@wlf.la.gov`, or by mail to LDWF Wildlife Diversity Program, Attn: Carolyn Michon, 200 Dulles Drive, Lafayette, LA 70506.

**Required in the request:**
- Detailed project description
- Map of the exact project location and geographic extent — an Esri shapefile in NAD83 UTM Zone 15 is preferred; a Google Earth KMZ/KML or a USGS 7.5-minute quad map is also accepted
- Latitude/longitude and township/range/section, if known

**Fee:** $30 per USGS quad reviewed. LDWF returns an invoice plus a response letter with findings — turnaround is not published; state that plainly rather than guessing a number.

## Step 2b: Federal ESA location check — NMFS and FWS, always both

Steps 1–2 are state data. This step asks the two federal Services which listed species they map at a specific point. Run it at the coordinates where the effect happens (the outfall, the intake, the fill footprint), not the facility's mailing address; `bayou:cwa-watershed-context` and `bayou:epa-echo-search` return outfall coordinates for NPDES permits.

**The two Services split jurisdiction, so one answer never stands for the other.** A project on the Mississippi River can return nothing from NMFS and an endangered fish from FWS. Never report an NMFS null as "no listed species".

- **NMFS:** marine and tidal species — sea turtles in the water, giant manta ray, whales.
- **FWS:** freshwater and terrestrial species, sea turtles on nesting beaches, manatee, pallid sturgeon.
- **Gulf sturgeon is split by water type and, in estuaries, by which federal agency is acting** (68 FR 13370, 13400, March 19, 2003; 50 CFR 17.95(e) and 226.214):

| Water | Consulting Service |
|---|---|
| Riverine | FWS, always |
| Estuarine | FWS when the action agency is EPA, DOT, the Coast Guard or FEMA. NMFS for the Corps, DOD and every other agency |
| Marine | NMFS, always |
| Project spans both | FWS leads and coordinates with NMFS |

So the same estuarine outfall goes to FWS as an EPA/Clean Water Act discharge matter and to NMFS as a Corps §404 fill. Name the action agency before naming the Service.

### NMFS — Southeast Region Section 7 consultation areas

This is the data behind NMFS's [ESA Section 7 Mapper](https://noaa.maps.arcgis.com/apps/webappviewer/index.html?id=b184635835e34f4d904c6fb741cfb00d). Open ArcGIS service, no key. Layer `8` is a one-row-per-species summary; sweep it over several distances, because the answer usually changes within a few miles of a site and that distance is the finding.

```bash
LAT=29.9395
LON=-90.3105
NMFS="https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/SERO_S7CAs_v2b_for_NOAA_GeoPlatform/FeatureServer"

# Literal list, not a $VAR: zsh does not word-split unquoted variables in a for loop.
for MI in 0 1 3 5 10; do
  curl -s --get "${NMFS}/8/query" \
    --data-urlencode "geometry=${LON},${LAT}" \
    --data-urlencode "geometryType=esriGeometryPoint" \
    --data-urlencode "inSR=4326" \
    --data-urlencode "spatialRel=esriSpatialRelIntersects" \
    --data-urlencode "distance=${MI}" \
    --data-urlencode "units=esriSRUnit_StatuteMile" \
    --data-urlencode "outFields=SPNAME" \
    --data-urlencode "returnGeometry=false" \
    --data-urlencode "f=json" 2>/dev/null | MI=$MI python3 -c "
import json, os, sys
d = json.load(sys.stdin)
if 'error' in d:
    sys.exit('query failed: %s' % d['error'])
names = sorted({f['attributes']['SPNAME'] for f in d.get('features', [])})
print('%2s mi: %s' % (os.environ['MI'], ', '.join(names) or 'no NMFS consultation area'))
"
done
```

When a distance returns species, pull the detail from the per-group layers at that location (`0` whales, `1` conchs, `2` corals, `3` sharks/rays/sawfish, `4` sturgeon and grouper, `5` sea turtles, `9` river critical habitat drawn as polygons). Add the same `distance` and `units` parameters to query around a point that sits outside the polygon. This block reuses `LAT`, `LON` and `NMFS` from the one above:

```bash
for LAYER in 0 1 2 3 4 5 9; do
  curl -s --get "${NMFS}/${LAYER}/query" \
    --data-urlencode "geometry=${LON},${LAT}" \
    --data-urlencode "geometryType=esriGeometryPoint" \
    --data-urlencode "inSR=4326" \
    --data-urlencode "spatialRel=esriSpatialRelIntersects" \
    --data-urlencode "outFields=*" \
    --data-urlencode "returnGeometry=false" \
    --data-urlencode "f=json" 2>/dev/null | LAYER=$LAYER python3 -c "
import json, os, sys
d = json.load(sys.stdin)
if 'error' in d:
    sys.exit('layer %s query failed: %s' % (os.environ['LAYER'], d['error']))
if not d.get('features'):
    print('layer %s: no features' % os.environ['LAYER'])
for f in d.get('features', []):
    a = f['attributes']
    if 'CH_UNIT' in a:
        print('CRITICAL HABITAT | %s | %s | %s' % (a['SPNAME'], a['CH_UNIT'], a.get('CHSTATUS')))
        continue
    print('%s (%s) | %s | %s, %s | %s to %s | %s' % (
        a['SPNAME'], a.get('ESASTATUS'), a.get('LIFESTAGE'), a.get('BEHAVIOR'), a.get('ZONE'),
        a.get('SEASON1BEG'), a.get('SEASON1END'), a.get('FRCIT')))
    if a.get('NOTES'):
        print('    note:', a['NOTES'])
"
done
```

Each row is one species × life stage × behavior, so a species repeats. `SEASON1BEG`/`SEASON1END` are the months the consultation area applies (Gulf sturgeon overwintering is 10/01–04/30); `FRCIT` is the listing rule. Print `NOTES` in full: it is NMFS's own statement of the layer's limits and is quotable.

- **A hit means "NMFS would expect consultation here", not "the species is present".** The notes say the inshore polygons take in saltmarsh and uplands that are not habitat.
- **A null in fresh water means little for Gulf sturgeon.** The notes say the map covers only designated critical-habitat freshwater, is not the full freshwater range, and that FWS handles riverine consultations.
- **A Gulf sturgeon hit does not make NMFS the consulting Service.** The polygons cover estuarine water where the lead depends on the action agency (table above).
- **Region check.** Layer `6` is the Southeast Region service area. Query it with `returnCountOnly=true` when a result is empty: a count of 0 means the point belongs to another NMFS region, not that it is clear.
- **Critical habitat elsewhere.** NMFS's national layers are `maps.fisheries.noaa.gov/server/rest/services/All_NMFS_Critical_Habitat/MapServer/226` (polygons) and `/2` (lines), queried the same way.

### FWS — IPaC location API

IPaC is the system FWS's own official species lists come from. The API takes a polygon, not a point, so build a small box around the coordinates. No key.

```bash
LAT=29.9395
LON=-90.3105
HALF_MI=1   # half-width of the query box

LAT=$LAT LON=$LON HALF_MI=$HALF_MI python3 -c "
import json, math, os
lat, lon, half = (float(os.environ[k]) for k in ('LAT', 'LON', 'HALF_MI'))
dy = half / 69.0
dx = half / (69.0 * math.cos(math.radians(lat)))
ring = [(lon - dx, lat - dy), (lon + dx, lat - dy), (lon + dx, lat + dy), (lon - dx, lat + dy), (lon - dx, lat - dy)]
print(json.dumps({
    'projectLocationWKT': 'POLYGON((%s))' % ','.join('%.5f %.5f' % p for p in ring),
    'timeout': 5, 'apiVersion': '1.0.0',
    'includeOtherFwsResources': False, 'includeCrithabGeometry': False}))
" | curl -s -m 90 -X POST "https://ipac.ecosphere.fws.gov/location/api/resources" \
    -H "Content-Type: application/json" -d @- 2>/dev/null | python3 -c "
import json, sys
r = json.load(sys.stdin)['resources']
for p in sorted(r['populationsBySid'].values(), key=lambda p: p['population']['listingStatusName']):
    s = p['population']
    print('%s | %s | %s | %s | critical habitat in footprint: %s | %s' % (
        s.get('optionalCommonName'), s.get('optionalScientificName'), s['listingStatusName'],
        s['groupName'], p.get('crithabInFootprint'), s.get('speciesProfileUrl')))
print('critical habitat units:', [c.get('criticalHabitatName') or c for c in r.get('crithabs', [])] or 'none')
for o in r.get('fieldOffices', []):
    print('field office: %s, %s' % (o['officeName'], o['formattedPhone']))
"
```

- **IPaC is range-based.** It lists species whose mapped range overlaps the box, so it over-includes (wide-ranging species such as monarch and tricolored bat appear at sites with no particular habitat). It establishes which species the agency had to consider, not that they are at the site.
- **Proposed species count for less.** `Proposed Threatened`/`Proposed Endangered` species get a conference, not a consultation. Keep them in a separate line of the table.
- **This is not an official species list.** That is a dated letter generated from a logged-in IPaC project, and it is the document to look for in the permit file or request from the applicant.
- **Slow.** A response can take tens of seconds, so keep the box small and the curl timeout long. An empty reply is a timeout, not a null result.

### What Step 2b does and does not establish

- **Section 7 needs a federal action.** A Corps §404/§10 permit or federal funding is one. An LDEQ-issued LPDES permit is a state action; the federal role there is EPA's oversight of the state program, so check the fact sheet for whether either Service was sent the draft rather than asserting a consultation duty.
- **A null rules out a species argument only for that Service at that location.** Effects travel: check the outfall, the intake, and the downstream or down-gradient waters, and say which points were checked.
- **Ask the Service.** NMFS's Southeast Regional Office and the FWS Louisiana Ecological Services Field Office (Lafayette, (337) 291-3100) both answer written questions about whether a permit reached them. A reply that says "not ours, it is the other Service's" is a finding about who should have reviewed it.

## Step 2c: Colonial waterbird nesting colonies (Gulfwide Avian Colony Monitoring)

Steps 1–2b cover listed species. The birds most often hit by coastal projects (brown pelican, terns, skimmers, gulls, herons, egrets, ibises, spoonbills) are mostly not ESA-listed, and nothing above places their colonies. This step does. The data is the Deepwater Horizon NRDA colonial waterbird aerial survey, run by The Water Institute and CPRA (portal: `qrco.de/avianmonitor`), published on the AWS Open Data bucket `s3://twi-aviandata` with no credentials and no rate limits.

Use it for **coastal** projects: LNG terminals, port and launch-site construction, dredging and spoil placement, pipeline crossings of the bays, and Class VI wells in the coastal zone. It does little for the inland Mississippi River industrial corridor (see the limits below).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-species-cultural-review/avian_colonies.py" --lat 29.58 --lon -92.35 --radius-mi 15
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-species-cultural-review/avian_colonies.py" --lat 29.58 --lon -92.35 --radius-mi 30 --photos 2 --imagery
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-species-cultural-review/avian_colonies.py" --lat 29.58 --lon -92.35 --json > colonies.json
```

On first run it downloads five small source tables, about 2.5 MB in total, into `~/.cache/bayou/avian-colonies/` and refreshes them after 90 days (`--refresh` forces it). It reports each colony inside the radius plus the `--nearest` N colonies outside it (default 3). For each one it gives the distance, nests by survey year, and peak nests by species with the peak year. `--photos N` adds the best dotted screenshot and source photo URLs for each year. `--imagery` lists the 2024 TIFs without downloading them and also finds 2024 colony folders that are absent from the counted data, locating each from its first frame's world file. That listing takes 20–30 s.

**Nest counts come from the program's curated table, never from summing photo rows.** The 2010–2021 figures are `tblColonyTotals2010-2021MayJune_Combined`, which the ReadMe calls the "final and best estimates". Summing `total_nests` across photos double-counts overlapping frames and ignores the `BestForBPE` selection and the May+June combining. The 2022–2023 summary lists May and June surveys separately, and the script keeps the larger of the two per species, which is a floor rather than the program's own estimate. The program's breeding population estimate is **2 × nests**; quote it as theirs, uncorrected for detection.

### Limits

- **Coverage is the colonies the program flies, not every rookery.** All 190 Louisiana colonies lie between 28.94° and 30.15° N on the coast and barrier islands. Inland heronries and egret rookeries (swamp, chenier ridges, the river parishes) are not surveyed. Never report "no colonies nearby" from a null; report "no surveyed colony within N miles" and name the nearest one.
- **Gaps between survey years.** Counts exist for 2010–2013, 2015, 2018, 2021 and (Louisiana only) 2022–2023. 2024 is imagery that has not been counted. Many colonies were flown only once (e.g. the "Louisiana West" sites, 2010 only). State the last year counted beside every number.
- **A zero is a survey result for that date.** Colonies move between years, so a zero after nesting years is a finding about that year, not proof the site is abandoned.
- **Most of these species are not ESA-listed.** The arguments run through the Migratory Bird Treaty Act, the NEPA affected-environment and cumulative-effects analysis, Louisiana coastal use guidelines, and the LDWF review in Step 2. Federal policy on MBTA incidental take has changed between administrations; check the current position before relying on it. Name the colonies found here in the Step 2 LDWF request.
- **Restoration conflict.** These colonies were monitored under Deepwater Horizon restoration, and several (for example Queen Bess Island) were rebuilt with restoration funds. Cross-check `bayou:cpra-master-plan` for restoration projects at or near a colony; "the permit degrades a publicly funded restoration" is often the stronger argument.

### Imagery (only when it goes in the report or gets analyzed)

The tables carry the findings. Fetch imagery only to put a photo in a comment or exhibit, or to analyze the ground (shoreline, vegetation, birds present in 2024). The `--photos` URLs for 2010–2023 point to JPGs of about 5–8 MB each plus dotted screenshots; download one or two with `curl -O`. 2024 has two kinds of file:

- **Frames** (`<date>_Cam<n>Card<n>_<num>.tif`, 30–55 MB): single oblique photos, LZW-compressed RGB, with a `.tfw` world file (EPSG:4326, about 2 cm pixels). The georeference is approximate: it places the frame, but it is not survey-grade.
- **Base Map mosaics** (`<colony>/Base Map/*_Georeferenced.tif`, 0.2–1.1 GB): georeferenced orthomosaics of a whole colony, tiled 128×128 with external `.ovr` overviews. One mosaic can cover two colonies; Bayou Platte Island South's sits in the North folder.

Don't download a mosaic whole. GDAL reads windows and overview levels over HTTP range requests:

```bash
KEY="avian_monitoring/high_resolution_photos/2024/Vermillion Bay/Bayou Platte Island North/Base Map/2024_BayouPlatteIslandNorthSouth_June_15_Cam3_Georeferenced.tif"
U="/vsicurl/https://twi-aviandata.s3.amazonaws.com/$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$KEY")"
export GDAL_HTTP_MULTIRANGE=YES GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES VSI_CACHE=TRUE

gdalinfo "$U" | rg 'Size is|Upper Left|Lower Right|Overviews'   # extent and overview sizes, ~10 s
# Whole-colony view: ask for an overview size exactly as gdalinfo lists it, ~10 s.
gdal_translate -q -b 1 -b 2 -b 3 -of JPEG -outsize 471 1717 "$U" overview.jpg
# Full-resolution clip of one area: -projwin ulx uly lrx lry in lon/lat, ~6 s.
gdal_translate -q -b 1 -b 2 -b 3 -of JPEG -projwin -91.8945 29.6215 -91.8930 29.6205 "$U" clip.jpg
# For analysis keep a GeoTIFF instead: -of GTiff -co COMPRESS=DEFLATE
```

- **Don't set `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`.** It hides the sibling `.ovr`, and GDAL then decimates the full-resolution file, which took more than 3 minutes for a 471-pixel overview of the 1 GB mosaic instead of 11 seconds.
- **Always pass `-b 1 -b 2 -b 3`.** Mosaics carry an alpha band, and a 4-band JPEG is read back as CMYK.
- `gdal_translate` and `gdalinfo` come from Homebrew `gdal`. Frames are small enough to download whole (`curl -O` on the URL-encoded key); `magick <frame>.tif -resize 1600x preview.jpg` makes a viewable copy.
- Before any bulk download (all frames for a colony can exceed 1 GB), give the total size from `--imagery` and confirm with the user.

## Step 3: National Register of Historic Places — live spatial search

```bash
LAT=29.9976
LON=-90.4113
RADIUS_MI=5

curl -s --get "https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer/0/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "distance=${RADIUS_MI}" \
  --data-urlencode "units=esriSRUnit_StatuteMile" \
  --data-urlencode "outFields=RESNAME,Address,City,County,State,NRIS_Refnum,CertDate,STATUS,MultiName,NARA_URL" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null | python3 -m json.tool
```

Layer `0` is points (individual listed properties); layer `1` (same base URL, `/1/query`) is polygon boundaries for historic districts — query it the same way if a district-level footprint matters more than point locations. `NRIS_Refnum` is the National Register reference number; `NARA_URL` links to the original nomination documents in the National Archives catalog — pull that for the actual nomination narrative if a specific property's significance matters to the argument. `STATUS` is almost always `Listed`; watch for `Removed` (delisted) if it appears.

This dataset is derived from NRIS point coordinates that NPS itself flags as approximate (`BND_TYPE: "Arbitrary point"`, accuracy `+/- 12 meters` at best, sometimes much worse for older/rural listings) — treat proximity results as indicative, not survey-grade, and note this caveat when a result is borderline (e.g. right at the edge of the search radius).

## Step 4: Tribes with a consultation interest in the parish (HUD TDAT)

HUD's Tribal Directory Assessment Tool lists the federally recognized tribes that have told HUD they have a current or ancestral interest in a county or parish, with a contact for each. The web app at `egis.hud.gov/TDAT/` is backed by an open ArcGIS service; table `3` (`TRIBE_CONTACT_COUNTY_VW`) joins tribe, contact, and parish. No key.

```bash
PARISH="St. James"   # no "Parish" suffix; or filter on GEOID (5-digit FIPS, e.g. 22093)

curl -s --get "https://egis.hud.gov/arcgis/rest/services/tdat/TDAT/MapServer/3/query" \
  --data-urlencode "where=STATE_NAME='Louisiana' AND COUNTY_NAME='${PARISH}'" \
  --data-urlencode "outFields=*" \
  --data-urlencode "f=json" 2>/dev/null | python3 -c "
import json, sys, datetime
from collections import defaultdict
rows = [f['attributes'] for f in json.load(sys.stdin).get('features', [])]
tribes = defaultdict(list)
for r in rows:
    tribes[r['TRIBAL_NAME']].append(r)
day = lambda ms: datetime.date.fromtimestamp(ms / 1000).isoformat() if ms else 'unknown'
for name in sorted(tribes):
    print(name)
    # The THPO is the Section 106 contact; the tribal leader is the fallback.
    # An acting THPO carries THPO='N', so the title is checked too.
    is_thpo = lambda c: c.get('THPO') == 'Y' or 'THPO' in (c.get('TITLE') or '')
    for c in sorted(tribes[name], key=lambda c: not is_thpo(c)):
        prefs = {k: v for k, v in c.items() if k.startswith('CNSLTTN_') and v not in (None, '') and not k.endswith('DTTM')}
        print('  %s %s, %s | %s | %s | THPO=%s | contact updated %s' % (
            c.get('FIRST_NAME') or '', c.get('LAST_NAME') or '', c.get('TITLE') or '',
            c.get('EMAIL') or '', c.get('WORK_PHONE') or '', c.get('THPO') or '?',
            day(c.get('CNTCT_LAST_UPD_DTTM'))))
        if prefs:
            print('    consultation preferences:', prefs)
"
```

Rows are one per *contact*, so a tribe appears once for its THPO and again for its chairman or chief; the same person is sometimes listed twice, and a superseded leader can linger beside the current one. An apostrophe in a parish name is doubled in the `where` clause. `CNSLTTN_*` columns hold the tribe's stated consultation preferences (how to be contacted, project types it does not need to see); they are empty for most Louisiana rows. The `CNTCT_LAST_UPD_DTTM` date matters: several Louisiana contacts were last updated in 2023, so confirm the name against the tribe's own website before a letter cites it.

Limits to state when presenting this:
- It is HUD's directory, built for HUD-assisted projects. For a Corps permit or another federal action, the lead agency keeps its own consultation list, and that list controls. Use TDAT to ask *whether these tribes were consulted*, not to assert who must be.
- It covers federally recognized tribes only. State-recognized tribes with ties to the coastal parishes (for example the United Houma Nation and the Pointe-au-Chien Indian Tribe) are absent, and have no Section 106 consultation right as tribes, though they can ask to be consulting parties.
- Section 106 applies only where there is a federal undertaking (a Corps permit, federal funding). A state-only LDEQ permit does not trigger it.

**Dead end:** an ArcGIS Online copy of the same table (`services.arcgis.com/VTyQ9soqVukalItT/.../TDAT_AGOL/FeatureServer/1`) answers queries but was last edited in January 2022. Use the `egis.hud.gov` service.

---

## Presenting the results

1. **Species check**: state plainly whether this was a tracking-list lookup (general listing status) or an actual site-specific LDWF review (Step 2, requires the formal request) — don't imply the tracking list alone confirms presence/absence at a site.
2. **Federal ESA table** (Step 2b): Species | Status | Service (NMFS/FWS) | At the point, or nearest distance | Season / life stage | Critical habitat. State the coordinates queried, list proposed species separately, and never merge the two Services' results into one "none found".
3. **Waterbird colony table** (Step 2c): Colony | Distance (mi) | Last year counted | Nests that year | Peak nests (species, year). State the radius and coordinates, name the nearest surveyed colony when none is inside the radius, and repeat the coverage limit (surveyed coastal colonies only). Embed or link a photo only when it supports a specific point.
4. **NRHP table**: Property Name | Address/City | County | NRIS Ref # | Listed Date | Status | link
5. If drafting the LDWF request letter: present it as ready-to-send text, and flag the $30/quad fee and the need for the user to actually send it (no auto-submission).
6. **Tribal consultation list** (Step 4): Tribe | Section 106 contact | Email / phone | Contact last updated, followed by the three limits listed in that step.
7. For a FERC-jurisdictional project (LNG terminal, interstate gas pipeline), FERC is the lead federal agency for ESA Section 7 and NHPA Section 106. Its EIS, biological assessment, the Services' opinions and the SHPO and tribal correspondence are in the FERC docket (`bayou:ferc-elibrary eis <docket>`; `search "Biological Opinion" --docket <docket>` and `search "Section 106" --docket <docket>` search descriptions). Compare them with what Steps 2b–4 find.
8. State retrieval date for the LDWF PDF, the NMFS and IPaC queries, the avian colony tables, the NPS query, and the TDAT query.

### Citation format

> **National Register of Historic Places**, NRIS Ref. 73002132, "Destrehan Plantation," Destrehan, St. Charles Parish, LA, listed 03/20/1973, source: [NPS Cultural Resources GIS](https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer) (retrieved 2026-07-21).
>
> **NMFS Section 7 consultation areas**: no NMFS consultation area at 29.9395, -90.3105 or within 3 miles; Gulf sturgeon and green, Kemp's ridley and loggerhead sea turtle areas begin within 5 miles. Source: [NOAA Fisheries Southeast Region ESA Section 7 Mapper](https://noaa.maps.arcgis.com/apps/webappviewer/index.html?id=b184635835e34f4d904c6fb741cfb00d) (retrieved 2026-10-13).
>
> **FWS IPaC**: pallid sturgeon (endangered), Gulf sturgeon and West Indian manatee (threatened) have ranges overlapping a 2-mile box centered on 29.9395, -90.3105; no critical habitat. Source: [USFWS IPaC](https://ipac.ecosphere.fws.gov/) location API (retrieved 2026-10-13). Range-based screen, not an official species list.
>
> **Gulfwide Avian Colony Monitoring**: Bayou Platte Island South, 27.6 mi from 29.58, -92.35, held 1,616 nests in 2013 (gull-billed tern 611, black skimmer 518, Forster's tern 355) and 49 in 2021, the last year counted. Source: The Water Institute and CPRA, colonial waterbird colony totals 2010–2021, [s3://twi-aviandata](https://twi-aviandata.s3.amazonaws.com/index.html) (retrieved 2026-10-16). Surveyed coastal colonies only.
>
> **LDWF Rare Species and Natural Communities Tracking List** (2022), source: [LDWF Wildlife Diversity](https://www.wlf.louisiana.gov/page/rare-species-and-natural-communities-by-parish) (retrieved 2026-07-21).

$ARGUMENTS
