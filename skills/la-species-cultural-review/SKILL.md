---
name: la-species-cultural-review
description: Check Louisiana rare/threatened/endangered species tracking lists, draft an LDWF Wildlife Diversity project-review request, and search the National Register of Historic Places near a project site — the NEPA/ESA/Section 106 review bundle
allowed-tools: Bash, AskUserQuestion
---

# Louisiana Species & Cultural Resource Review

Bundles the three data sources typically needed for an ESA / NEPA / Section 106 review of a Louisiana project or facility: LDWF's statewide rare-species tracking lists, the LDWF Wildlife Diversity Program's formal project-review request process, and the National Register of Historic Places (NRHP) via a live NPS spatial layer.

**Correction to the original bookmark list**: the Louisiana Division of Historic Preservation's own historic-property database is unreachable (connection fails outright). Use the **NPS National Register of Historic Places ArcGIS layer** instead (Step 3 below) — it's the authoritative national dataset LDHP itself feeds into, live-verified, no key required. Also, LDWF's rare-species data is **not** organized as one PDF per parish as the bookmark description assumed — it's four statewide tracking-list PDFs (animals, plants, natural communities, combined) plus a formal data-request process for parcel-specific results.

## Parsing arguments

The user may provide:
- A **project location** (facility name, address, or lat/lon) — for the NRHP proximity search
- A **species or taxon** of interest — to check against the LDWF tracking lists
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

---

## Presenting the results

1. **Species check**: state plainly whether this was a tracking-list lookup (general listing status) or an actual site-specific LDWF review (Step 2, requires the formal request) — don't imply the tracking list alone confirms presence/absence at a site.
2. **NRHP table**: Property Name | Address/City | County | NRIS Ref # | Listed Date | Status | link
3. If drafting the LDWF request letter: present it as ready-to-send text, and flag the $30/quad fee and the need for the user to actually send it (no auto-submission).
4. State retrieval date for both the LDWF PDF and the NPS query.

### Citation format

> **National Register of Historic Places**, NRIS Ref. 73002132, "Destrehan Plantation," Destrehan, St. Charles Parish, LA, listed 03/20/1973, source: [NPS Cultural Resources GIS](https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer) (retrieved 2026-07-21).
>
> **LDWF Rare Species and Natural Communities Tracking List** (2022), source: [LDWF Wildlife Diversity](https://www.wlf.louisiana.gov/page/rare-species-and-natural-communities-by-parish) (retrieved 2026-07-21).

$ARGUMENTS
