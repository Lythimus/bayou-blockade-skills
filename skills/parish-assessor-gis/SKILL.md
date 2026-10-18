---
name: parish-assessor-gis
description: Parcel facts from Louisiana parish GIS — the parcel polygon at a point or address, owner of record (with the source's authority and vintage), every zoning district the parcel touches, a merged project footprint as GeoJSON, and the nearest occupied homes and residentially zoned parcels measured edge to edge from the fenceline. Registry of public ArcGIS REST layers for St. Charles, Ascension and St. James (others stubbed). Use to frame a site for unmarked-burial-screen, to confirm a home's parcel and fenceline distance for household-exposure, to measure parcel-boundary distances instead of point-to-point, or to find who owns the land next to a plant.
argument-hint: at <lat> <lon> | address "<street, city, LA>" | footprint --owner "<NAME|ALIAS>" --near <lat> <lon> | receptors --footprint <file>
allowed-tools: Bash, Read, WebFetch, WebSearch, AskUserQuestion
---

# Parish assessor and zoning GIS

Most Louisiana parishes publish their assessor parcels and their zoning as ArcGIS REST layers behind the parish map viewer. This skill keeps a registry of those layers in `parishes.json` and queries them directly. That replaces point-to-point guesses ("the plant is about a mile from the church") with measurements from the actual property line, and puts the owner of record next to the source it came from.

## Script

Standard library only. It caches HTTP responses for a day under `~/.cache/bayou/parish-assessor-gis/` and accepts `--json` (before or after the subcommand).

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/parish-assessor-gis"

python3 "$S/parcels.py" health                                   # which layers are up, record counts, currency
python3 "$S/parcels.py" at 29.985128 -90.452429                  # parcel, owner, zoning at a point
python3 "$S/parcels.py" address "15045 River Rd, Hahnville, LA 70057"
python3 "$S/parcels.py" parcel 2026400 --parish ascension        # by parcel number; prints the assessor link
python3 "$S/parcels.py" owner "BASF" --near 30.20 -90.98 --radius-mi 2
python3 "$S/parcels.py" footprint --owner "UNION CARBIDE|DOW " --near 29.985 -90.452 --out site.geojson
python3 "$S/parcels.py" footprint --pins 3429500,3429600 --parish ascension --out site.geojson
python3 "$S/parcels.py" receptors --footprint site.geojson --radius-mi 1
python3 "$S/parcels.py" receptors --point 30.03 -90.85 --radius-mi 0.5   # point origin when no footprint exists
```

The parish is detected from the point through the Census TIGERweb counties layer. Pass `--parish st-charles|ascension|st-james|…` to override. Parishes still marked `unprobed` stop with exit code 4 and a pointer to [Adding a parish](#adding-a-parish).

## Workflow

1. **`at` the facility's location** (or `address`). This gives the parcel under the point, its owner, and the zoning. Read the owner's source line before you rely on the name (see [Source authority and vintage](#source-authority-and-vintage)).
2. **`footprint`** builds the site. Use `--owner` with every name the company files under, `|`-separated (subsidiaries, predecessors, "UNION CARBIDE|DOW "). Parcels within `--gap-ft` (default 150 ft, enough to bridge a road or ditch) form one site, and the group containing or nearest `--near` is kept. Check the printed parcel list against the permit's site description. If the permit names parcels, use `--pins` instead.

   A parcel number can cover several polygons. When the kept group includes any of them, the footprint takes them all and lists the ones that sit apart under `detached_parts`. For example, Dow's 160100000930 includes a 57.7 ac tract 857 ft from the plant, and including it changes the Taft count of homes within 1 mi from 207 to 431. Decide whether such a tract is part of the facility. If it is not, rerun with `--polygons-only`, and say which choice you made when you report distances. The GeoJSON is a MultiPolygon of the member parcels; internal lot lines stay, which does not affect distances.
3. **`receptors --footprint`** returns two separate lists, both measured edge to edge from the footprint:
   - **(a) occupied residential structures, whatever their zoning:** St. Charles building footprints, St. James assessor buildings with a residential class code, and Ascension residential address points.
   - **(b) residentially zoned parcels,** together with the distance to the nearest residential zoning district.

   Each comes with distance bands and the five nearest distances. Structures the footprint owner itself owns move to "other".
4. Feed the outputs on:
   - the GeoJSON goes to `unmarked-burial-screen` (Step 1 site framing) and `geo-distance`;
   - the distances go to `household-exposure` and comment drafting;
   - the owner and parcel numbers go to `la-public-records-request` (for the conveyance record) and to `la-bond-dockets` (to match the borrower name).
   - Going the other way: when `parish-council-agendas` turns up a rezoning or land-use case, look up the lots it names here to get the parcel, the owner of record and the current zoning (St. Charles, Ascension and St. James only; the other agenda parishes have no layer here yet).

## Zoning is not occupancy

On the river corridor, homes often stand on land zoned or planned industrial; the older communities predate the zoning. List (b) alone understates exposure. Take the St. James test case, the NuStar parcel at 30.03, −90.85:
- **68 assessor-coded homes** lie within 0.25 mi of the parcel line.
- The nearest residential land-use area is **0.49 mi** away, and the nearest parcel inside one is 0.59 mi away.

Always report list (a), and say what it is built from:
- **St. Charles** publishes no building-use code, so "likely dwelling" means a non-demolished footprint under 6,000 sq ft. Two kinds of owner are excluded: exempt public owners (parish, school board, port, fire, drainage, highways, hospital, cemeteries) and the footprint owner itself. Exempt housing authorities, churches and individuals stay in. The count still catches some sheds and small shops.
- **Ascension** address points leave about a quarter of `USETYPE` blank, so its count is a floor.

## Source authority and vintage

Every row carries `source_url`, `authority` and a vintage line. Report them with the fact.

| Parish | Owner source | Authority | Currency |
|---|---|---|---|
| St. Charles | `maps.scpgis.com` Planning/0 | parish | edited daily (`last_edited_date` = today on 2026-10-16) |
| Ascension | Westwood `Ascension_Parish_Tax_Parcels` | consultant-copy | **2016** (`LAST_REVIS` max 2016-02) |
| St. James | `gisviewer.stjamesla.com` AssInfo/3 | parish | 322 transfers recorded in the last 12 months |

**Ascension:**
- The parcel geometry (`LiveParcelsView`) and zoning are current parish layers. The owner is not.
- The parish's own owner layer at `geo.apgov.us` was down when this was built. The script tries it first and falls back with a note.
- Treat any Ascension owner name as "owner as of 2016". Before citing it, confirm the project parcel on Beacon using the printed `assessor:` link. Beacon blocks scripts, so open it with `anthropic-skills:chrome-browser`, or request the assessment roll through `la-public-records-request`. Check only the parcels you will cite; Beacon is not for bulk lookups.

**Zoning:**
- **St. Charles:** the parcel layer's own `zoning` attribute is often blank or stale. The script reads the zoning polygon layer and reports every district intersecting the parcel, with the share of the parcel each district covers.
- **St. James publishes no parish zoning.** The registry carries two layers:
  - Gramercy's municipal zoning;
  - an `unofficial` land-use map. It was posted by an ArcGIS Online user and has no stated provenance, so do not cite it as zoning. Cite the parish land-use plan itself, or ask Planning.

Run `health` at the start of a session that depends on these layers. Layers move without notice, and the Ascension Web Adaptor reports an outage as an HTML page with HTTP 200, which the script treats as down.

## Privacy rule

`at`, `address` and `parcel` print the owner and mailing address of whatever parcel they hit. On a home, that is a resident's name; treat it as household-only output, just like `--private`.

By default `receptors` returns counts, distance bands and distances only, with no names or addresses. `--private` adds the address and owner of the nearest homes, **for the household's own use** (for example, `household-exposure` confirming that its own home is the 135 ft one). Never put resident names or home addresses into campaign outputs (`nextdoor-campaign`, `ej-meme`, `kit-dissemination`, public comments): write "a home 135 ft from the fenceline", not the family's name. Corporate owners of industrial parcels are public-interest facts and can be named.

## Honesty limits

- **Assessor data is not title.** The owner of record is whoever the assessor bills, sometimes care of a tax agent such as "RYAN, LLC - C/O". The conveyance record (book, page, instrument) is at the Clerk of Court. St. James prints book/page; cite the instrument from the Clerk's index, not from GIS.
- **A parcel layer is not a survey.** Tax-map lines can be off by tens of feet, and distances under about 50 ft are within that error. Say "about".
- **An absent structure is not proof that nobody lives there.** Footprint layers lag new construction and miss trailers. Address-point use codes are incomplete. A community with no residential zoning can still be full of homes.
- **Acreage** is computed from the GIS polygon and will not match the assessor's deeded acreage.
- **No parcel is not no owner.** Lakes, bays and navigable bayous are usually unparcelled state water bottoms, and WMAs may be state land. Check them with `bayou:la-state-lands at <lat> <lon>`. For a Class VI AoR, `la-state-lands overlap` splits the acreage into state-claimed, CCS-agreement and other land, and the other land is what this skill resolves to owners.
- **The Ascension parcel numbers** in the 2016 owner copy that are missing from the current layer (because of splits or renumbering) keep their 2016 shape. The footprint output says so when it happens.

## Adding a parish

Registry stubs exist for St. John, Iberville, East Baton Rouge, West Baton Rouge, Calcasieu, Plaquemines and Cameron. To fill one:

1. **Find the viewer's layers.**
   - **ArcGIS Online:** `https://www.arcgis.com/sharing/rest/search?q=<parish> parcels&f=json`, plus the same with "zoning". Prefer items owned by the parish's own org. Note who owns each layer; it decides the `authority` value.
   - **Geocortex or Web AppBuilder viewer:** the `app=<id>` in the viewer URL is an item. Read `https://www.arcgis.com/sharing/rest/content/items/<id>/data?f=json` to get the web map id, then read that map's `/data` for `operationalLayers[].url`. This is how the St. Charles layers were found.
   - **Custom viewer:** fetch the page's JavaScript bundles and search them for `rest/services`. This is how the St. James layers were found, in `scripts/global.js`.
2. **Probe each layer.** `<layer>?f=json` gives the fields and `maxRecordCount`. `query?where=1=1&returnCountOnly=true` gives the record count. A point query with `outFields=*` on a known plant parcel shows the field contents.
3. **Test currency, not just the edit date.** Republishing resets `dataLastEditDate`. Count transfers dated in the last 12 months, or compare owners on a sample of parcels against a second source.
4. **Add the entry** to `parishes.json`: field map, residential rules, authority, `max_records`, `vintage_check`. Set `status: "verified"`, then run `health <key>` and `at` on a known parcel.
5. If no public layer exists, use the assessor's own site: open a known parcel with `anthropic-skills:chrome-browser` to check what it shows. Fall back to a public-records request for the parcel shapefile and assessment roll (`la-public-records-request`).
