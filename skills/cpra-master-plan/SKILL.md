---
name: cpra-master-plan
description: Search CPRA 2023 Coastal Master Plan for restoration/protection projects, land change projections, and flood risk data by parish, project name, or region
allowed-tools: Bash, WebFetch, AskUserQuestion
---

# CPRA Coastal Master Plan Search

Search Louisiana's Coastal Protection and Restoration Authority (CPRA) 2023 Coastal Master Plan data for restoration and structural risk reduction projects, implementation timelines, and links to flood/land change projection data.

## Data Sources

| Source | What it covers | Access method |
|---|---|---|
| ArcGIS REST (cimsgeo3) | Project locations, names, parishes, timelines | `curl` queries below |
| MP-DAP (mpdap.coastal.la.gov) | Downloadable modeling outputs: land change, vegetation, flood depth, salinity, water level, damages | Web portal — link users there |
| MPDV (mpdv.coastal.la.gov) | Interactive map viewer, scenario comparison (with/without plan, 50-yr projections) | Web portal — link users there |
| GIS Download (cims.coastal.louisiana.gov/masterplan/GISDownload/) | Shapefiles/GeoTIFF for 2012/2017/2023 plans | Web download |

## Parsing arguments

The user may provide:
- A **parish name** (e.g., "St. Charles", "Plaquemines", "Terrebonne")
- A **project name** or keyword (e.g., "Mid-Barataria", "diversion", "marsh creation")
- A **project type** (diversion, marsh creation, hydrologic restoration, shoreline protection, structural)
- A **region** (Barataria, Pontchartrain, Terrebonne, Atchafalaya, Chenier Plain)
- A request for **projection data** (land change, flood depth, sea level rise scenarios)
- A request about **implementation timeline** or **costs**

If the query is about modeling outputs (land change projections, flood depth, vegetation scenarios) rather than specific projects, skip directly to Step 4 — point the user to the data portals.

## Step 1: Query restoration projects (polygons) by parish or name

```bash
curl -s "http://cimsgeo3.coastal.louisiana.gov/arcgis/rest/services/mp/MasterPlan2023_RP/MapServer/2/query?where=ENCODED_WHERE&outFields=ProjectName,Project_Description,ProjectTypeCode,ElementName,Parish,Region,ImplementationPeriod,StartYear_FWOA,DurationConstruction,FS_URL&f=json&returnGeometry=false&resultRecordCount=50" 2>/dev/null
```

### WHERE clause examples

| User query | WHERE clause (URL-encode before inserting) |
|---|---|
| By parish | `Parish LIKE '%St. Charles%'` |
| By project name keyword | `ProjectName LIKE '%diversion%'` |
| By project type | `ProjectTypeCode = 'DI'` |
| By region | `Region = 'Barataria'` |
| Combine | `Parish LIKE '%Plaquemines%' AND ProjectTypeCode = 'MC'` |

URL-encode the where clause: replace spaces with `+`, `'` with `%27`, `%` with `%25`, `=` with `%3D`, `LIKE` stays as-is.

### ProjectTypeCode values

| Code | Type |
|---|---|
| `DI` | Diversion (freshwater/sediment) |
| `MC` | Marsh Creation |
| `HR` | Hydrologic Restoration |
| `SP` | Shoreline Protection |
| `OY` | Oyster Reef |
| `BR` | Barrier Island/Headland Restoration |
| `NN` | Non-Structural Risk Reduction |

## Step 2: Query structural risk reduction projects

```bash
curl -s "http://cimsgeo3.coastal.louisiana.gov/arcgis/rest/services/mp/MasterPlan2023_SRR/MapServer/0/query?where=ENCODED_WHERE&outFields=ProjectName,Parish,Region&f=json&returnGeometry=false&resultRecordCount=50" 2>/dev/null
```

Use same WHERE logic as Step 1. Structural projects (levees, floodgates, etc.) are in this separate service.

## Step 3: Parse and present results

From each result in `features[].attributes`:

| Field | Description |
|---|---|
| `ProjectName` | Full project name |
| `Project_Description` | Summary of project purpose |
| `ProjectTypeCode` | Type abbreviation (see table above) |
| `Parish` | Parish(es) affected (may be semicolon-separated) |
| `Region` | Planning region (Barataria, Pontchartrain, etc.) |
| `ImplementationPeriod` | 1 = Years 1–10, 2 = Years 11–30, 3 = Years 31–50 |
| `StartYear_FWOA` | Approximate start year relative to plan (2023 baseline) |
| `DurationConstruction` | Construction duration in years |
| `FS_URL` | URL to project fact sheet PDF — always include this link |

### Presentation format

1. **Summary**: "Found N restoration projects / M structural projects in [location]"
2. **Table**: Project Name | Type | Parish | Region | Implementation Period | Fact Sheet
3. For `ImplementationPeriod`, translate: 1 → "Near-term (0–10 yrs)", 2 → "Mid-term (11–30 yrs)", 3 → "Long-term (31–50 yrs)"
4. Always link fact sheets: the `FS_URL` field contains a direct PDF link — include it for each project
5. If no results, try broadening the WHERE clause (e.g., drop the project type filter, use a broader parish name)

## Step 4: Land change and flood projection data

If the user asks about **future land change**, **flood depths**, **sea level rise scenarios**, **vegetation projections**, **salinity**, or **expected damages** — these are modeling outputs, not queryable via the REST API. Direct them to:

- **Master Plan Data Viewer**: https://mpdv.coastal.la.gov — interactive scenario comparison (with/without plan, years 2023–2073, multiple SLR scenarios)
- **Master Plan Data Access Portal**: https://mpdap.coastal.la.gov — download NetCDF/GeoTIFF for land change, vegetation type, flood depth, salinity, water level, expected annual damage (EADD)
- **GIS Download**: https://cims.coastal.louisiana.gov/masterplan/GISDownload/ — shapefiles for all three master plan years (2012, 2017, 2023)

Available projection variables in MP-DAP:
- Land change (future land/water extent)
- Vegetation type (FFIBS classification, vegetation community types)
- Flood depth (annual average)
- Expected annual storm surge damage (EADD, EASD)
- Salinity
- Water level
- Total suspended solids

Scenarios in the 2023 plan:
- **FWOA** = Future Without Action (baseline, no plan projects)
- **FWA** = Future With Action (full plan implemented)
- Sea level rise: Low, Medium (NOAA Intermediate), High
- Planning horizons: 2023, 2033, 2043, 2053, 2073

## Step 5: Fetch a fact sheet (optional)

If the user wants details on a specific project and a `FS_URL` is available:

```bash
# Use WebFetch on the FS_URL from the query results
```

Fetch the fact sheet PDF link and summarize: project purpose, location, acreage/mileage, estimated cost, implementation period, and expected benefits (land built, habitat restored, flood damage reduced).

## Notes for Waterford 5 & 6 context

- Waterford Steam Electric Station is in **St. Charles Parish**, **Barataria region**
- Relevant search: parish = "St. Charles" or region = "Barataria"
- Key nearby projects to check: Upper Basin Diversion Program – Barataria (DI), any Atchafalaya/Barataria marsh creation in St. Charles Parish
- For flood/storm surge risk at the facility, use MP-DAP to check Expected Annual Damage data for the Norco/Killona area

$ARGUMENTS
