---
name: fema-flood
description: Query FEMA openFEMA API for NFIP flood insurance claims, policies, and disaster declarations
allowed-tools: Bash, AskUserQuestion
---

# FEMA openFEMA Data Search

Query FEMA's public openFEMA API for flood insurance data (NFIP claims and policies), disaster declarations, and flood hazard information. No API key required.

## Base URL

```
https://www.fema.gov/api/open/v2/
```

## General query syntax

```bash
curl -s "https://www.fema.gov/api/open/v2/DATASET?PARAMS" 2>/dev/null
```

Query parameters (OData-style):
- `$filter` — filter expression (e.g., `state eq 'LA'`)
- `$select` — comma-separated field list
- `$orderby` — sort field and direction
- `$top` — max records (default 1000, max 10000)
- `$skip` — offset for pagination
- `$format=json` — explicitly request JSON

---

## Available datasets

### NFIP Flood Insurance Claims
`FimaNfipClaims` — Individual flood insurance claim records

```bash
curl -s "https://www.fema.gov/api/open/v2/FimaNfipClaims?\$filter=state+eq+'LA'&\$top=100&\$orderby=dateOfLoss+desc" 2>/dev/null | python3 -m json.tool
```

Key fields: `state`, `reportedCity`, `reportedZipCode`, `countyCode`, `dateOfLoss`, `yearOfLoss`, `ratedFloodZone`, `floodZoneCurrent`, `amountPaidOnBuildingClaim`, `amountPaidOnContentsClaim`, `totalBuildingInsuranceCoverage`, `occupancyType`, `latitude`, `longitude`

Filter examples:
- By state: `state eq 'LA'`
- By year: `yearOfLoss eq 2020`
- By flood zone: `ratedFloodZone eq 'AE'`
- By zip: `reportedZipCode eq '70094'`
- Combined: `state eq 'LA' and yearOfLoss ge 2020`

### NFIP Flood Insurance Policies
`FimaNfipPolicies` — Active and historical NFIP policy records

```bash
curl -s "https://www.fema.gov/api/open/v2/FimaNfipPolicies?\$filter=propertyState+eq+'LA'&\$top=100" 2>/dev/null | python3 -m json.tool
```

Key fields: `propertyState`, `countyCode`, `reportedZipCode`, `floodZone`, `originalNBDate`, `policyTerminationDate`, `totalBuildingInsuranceCoverage`, `totalContentsInsuranceCoverage`, `occupancyType`

### Disaster Declarations
`DisasterDeclarationsSummaries` — FEMA disaster declarations

```bash
curl -s "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?\$filter=state+eq+'LA'&\$orderby=declarationDate+desc&\$top=20" 2>/dev/null | python3 -m json.tool
```

Key fields: `disasterNumber`, `state`, `declarationTitle`, `declarationType`, `incidentType`, `declarationDate`, `incidentBeginDate`, `incidentEndDate`, `designatedArea`

Filter by incident type: `incidentType eq 'Flood'`

### Public Assistance Grants
`PublicAssistanceApplicants` — Recipients of FEMA public assistance funding

```bash
curl -s "https://www.fema.gov/api/open/v2/PublicAssistanceApplicants?\$filter=state+eq+'LA'&\$top=50" 2>/dev/null | python3 -m json.tool
```

---

## Common use cases

### Flood claims near a facility (by county or zip)
```bash
curl -s "https://www.fema.gov/api/open/v2/FimaNfipClaims?\$filter=state+eq+'LA'+and+countyCode+eq+'071'&\$top=1000&\$select=dateOfLoss,ratedFloodZone,amountPaidOnBuildingClaim,reportedCity,reportedZipCode,latitude,longitude" 2>/dev/null
```

### Check flood zone distribution in an area
```bash
curl -s "https://www.fema.gov/api/open/v2/FimaNfipClaims?\$filter=reportedZipCode+eq+'70094'&\$select=ratedFloodZone,amountPaidOnBuildingClaim,yearOfLoss&\$top=1000" 2>/dev/null
```

### Recent Louisiana disaster declarations
```bash
curl -s "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?\$filter=state+eq+'LA'+and+incidentType+eq+'Flood'&\$orderby=declarationDate+desc&\$top=20&\$select=disasterNumber,declarationTitle,declarationDate,incidentBeginDate,incidentEndDate,designatedArea" 2>/dev/null
```

---

## Flood hazard layer (FIRM/NFHL) — live spatial zone lookup

The National Flood Hazard Layer is a separate ArcGIS REST service from openFEMA, and answers the question openFEMA can't: **what flood zone does this specific point fall in right now.** No key required.

```
https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
```

Relevant layers (confirmed live 2026-07-21): `28` Flood Hazard Zones, `3` FIRM Panels, `16` Base Flood Elevations, `0` NFHL Availability (which counties/parishes are actually in this digital mosaic — check this first, see caveat below).

### Point query — flood zone at a location

```bash
LAT=29.9511
LON=-90.0715

curl -s --get "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "distance=0.1" \
  --data-urlencode "units=esriSRUnit_StatuteMile" \
  --data-urlencode "outFields=DFIRM_ID,FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,V_DATUM,SOURCE_CIT" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null | python3 -m json.tool
```

`FLD_ZONE` is the zone letter (`A`, `AE`, `VE`, `X`, etc.); `ZONE_SUBTY` carries qualifiers like "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE" or "FLOODWAY"; `SFHA_TF` = `T`/`F` for whether it's inside a Special Flood Hazard Area; `STATIC_BFE` is the base flood elevation in feet (`-9999` means not applicable/not studied, not zero); `DFIRM_ID` is `<state FIPS><parish/county FIPS>C` (e.g. `22089C` = St. Charles Parish, LA).

### FIRM panel for a location

```bash
curl -s --get "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/3/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "distance=0.1" \
  --data-urlencode "units=esriSRUnit_StatuteMile" \
  --data-urlencode "outFields=FIRM_PAN,PANEL_TYP,EFF_DATE,PRE_DATE" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null | python3 -m json.tool
```

`FIRM_PAN` is the panel number to cite; `EFF_DATE` is the current effective date of that panel.

### Important caveat — not every parish is in this digital mosaic

**Live-confirmed 2026-07-21: St. Charles Parish, LA (FIPS 22089, DFIRM_ID `22089C`) — where Norco sits — returns zero features from layers 0, 3, and 28, at any radius.** Jefferson Parish (`22051C`) and St. John the Baptist Parish (`22095C`) both return normally. This means St. Charles Parish's FIRM has not been loaded into FEMA's digital NFHL mosaic — it is likely still on an older paper/non-digitized FIRM.

**Before reporting "no flood zone data" for any point, always check layer `0` (NFHL Availability) at that location first:**

```bash
curl -s --get "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/0/query" \
  --data-urlencode "geometry=${LON},${LAT}" \
  --data-urlencode "geometryType=esriGeometryPoint" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "outFields=STUDY_ID" \
  --data-urlencode "returnGeometry=false" \
  --data-urlencode "f=json" 2>/dev/null | python3 -m json.tool
```

If this also returns `"features": []`, **do not** conclude the point is unmapped or outside a flood zone — say plainly that the parish is not in FEMA's digital NFHL mosaic, and direct the user to the FEMA Map Service Center (`https://msc.fema.gov/portal/search`, enter the address) for the paper/legacy FIRM determination instead.

Note also that the `ratedFloodZone` field in openFEMA's NFIP claims data (above) reflects the zone at the time of the claim, not necessarily the current effective NFHL zone.

---

## Pagination

Default returns up to 1000 records. For large datasets:
```bash
curl -s "https://www.fema.gov/api/open/v2/FimaNfipClaims?\$filter=state+eq+'LA'&\$skip=1000&\$top=1000" 2>/dev/null
```

Check `metadata.count` in the response to see total records available.

## How to present results

- Summarize: "Found N flood claims in [area]"
- Aggregate stats where useful: total payout, distribution by flood zone, peak loss year
- For disaster declarations: chronological list with declaration dates and affected areas
- Flag anything in Zone A or AE (high-risk Special Flood Hazard Areas)
- Note Louisiana parish FIPS codes: St. Charles = 071, St. John = 095, St. James = 093, Orleans = 071

$ARGUMENTS
