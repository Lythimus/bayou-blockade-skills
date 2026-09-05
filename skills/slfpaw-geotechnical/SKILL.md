---
name: slfpaw-geotechnical
description: Search SLFPA-W geotechnical records (soil borings, cross-sections, piezometers, site visit reports) for the New Orleans West Bank levee system via the USACE National Levee Database
allowed-tools: Bash, WebFetch, AskUserQuestion
---

# SLFPA-W Geotechnical Records Search

Search geotechnical records for the Southeast Louisiana Flood Protection Authority – West (SLFPA-W) levee system. All geotechnical data is held in the **USACE National Levee Database (NLD)** under the New Orleans West Bank system. SLFPA-W itself has no public-facing geotechnical database — for records not in NLD, submit a public records request at slfpaw.org/public-information-requests.

## System reference

| Field | Value |
|---|---|
| NLD system name | New Orleans West Bank |
| NLD system ID | `4405000557` |
| API base URL | `https://levees.sec.usace.army.mil/api-local` |
| NLD web viewer | `https://levees.sec.usace.army.mil/levees/4405000557` |
| Managed by | SLFPA-W, Lafourche Basin LD, Plaquemines LD, St. Charles Parish |
| USACE oversight | New Orleans District (MVN) |
| Coverage | 80+ miles of levees/floodwalls across Jefferson, Orleans, St. Charles, and Plaquemines parishes |

## Levee segments

| Segment ID | Name | Parishes |
|---|---|---|
| `4404000511` | West Jefferson LD – New Orleans West Bank | Jefferson |
| `4404000513` | Algiers LD – West Side Algiers Canal | Orleans, Plaquemines |
| `4404000514` | Algiers LD – East Side Algiers Canal | Orleans, Plaquemines |
| `4404000515` | Plaquemines LD – New Orleans West Bank | Plaquemines |
| `4404000555` | Lafourche Basin LD – New Orleans West Bank | Jefferson, Lafourche |
| `4404000572` | St. Charles Parish – New Orleans West Bank | St. Charles |
| `4404000576` | Plaquemines LD – West Side Algiers Canal | Plaquemines |

---

## Step 1: Determine what the user is searching for

Parse the user's query to identify:
- **Record type**: soil borings / boreholes, cross-sections, piezometers, inspection/site visit reports, or system overview
- **Location filter**: segment name, parish, or levee station range (e.g., "Station 837+69")
- **Date filter**: boring completion year, survey date, or inspection year
- **Soil type / keyword**: soil classification (e.g., "fat clay", "sand"), or boring name pattern

If ambiguous, ask via AskUserQuestion before querying.

---

## Step 2: Soil borings (boreholes)

There are **~1,500 soil boring records** in NLD for this system.

### List all borings for the system

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/boreholes?system_id=4405000557" \
  | python3 -m json.tool
```

### List borings for a specific segment

Replace `SEGMENT_ID` with a value from the segments table above:
```bash
curl -s "https://levees.sec.usace.army.mil/api-local/boreholes?system_id=4405000557" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
seg = SEGMENT_ID  # e.g. 4404000511
results = [b for b in data if b.get('segmentId') == seg]
print(json.dumps(results, indent=2))
"
```

### Filter by keyword (soil type, name, station)

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/boreholes?system_id=4405000557" \
  | python3 -c "
import sys, json
keyword = 'KEYWORD'  # e.g. 'clay', 'sand', '837+69', 'WHCVBB'
data = json.load(sys.stdin)
results = [b for b in data if keyword.lower() in json.dumps(b).lower()]
print(json.dumps(results[:20], indent=2))
print(f'--- {len(results)} matches ---')
"
```

### Get detail for a specific borehole

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/boreholes/BOREHOLE_ID" \
  | python3 -m json.tool
```

### Get boreholes as GeoJSON (with coordinates) for a segment

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/boreholes-SEGMENT_ID.geojson" \
  | python3 -m json.tool
```

Note: The GeoJSON coordinates are in EPSG:3857 (Web Mercator). To convert to lat/lon, divide x by 6378137, multiply by (180/π); for y use atan(sinh(y/6378137)) × (180/π).

### Borehole fields

| Field | Description |
|---|---|
| `id` | NLD borehole ID |
| `name` | Boring identifier (e.g., "98-05__(WHCVBB-19)") |
| `leveeStationCode` | Station along the levee alignment |
| `completionDate` | Date boring was completed |
| `groundSurfaceElevation` | Elevation at top of boring (ft NAVD88) |
| `totalDepth` | Boring depth in feet |
| `type` | USCS soil classification at boring location |
| `boreMethod` | Drilling method (e.g., "Shelby Tube", "Auger") |
| `segmentId` | Which levee segment this boring is on |

---

## Step 3: Cross-sections

There are **~284 cross-section survey records** in NLD for this system.

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/cross-sections?system_id=4405000557" \
  | python3 -m json.tool
```

Filter by segment:
```bash
curl -s "https://levees.sec.usace.army.mil/api-local/cross-sections?system_id=4405000557" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
seg = SEGMENT_ID
results = [c for c in data if c.get('segmentId') == seg]
print(json.dumps(results, indent=2))
"
```

Get GeoJSON for a segment:
```bash
curl -s "https://levees.sec.usace.army.mil/api-local/cross-sections-SEGMENT_ID.geojson" \
  | python3 -m json.tool
```

### Cross-section fields

| Field | Description |
|---|---|
| `id` | NLD cross-section ID |
| `leveeStationCode` | Station along levee alignment |
| `surveyDate` | Survey date |
| `coordinateCapture` | Method (e.g., "LIDAR") |

---

## Step 4: Piezometers

There are **4 piezometer records** in NLD for this system.

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/piezometers?system_id=4405000557" \
  | python3 -m json.tool
```

### Piezometer fields

| Field | Description |
|---|---|
| `name` | Piezometer ID (e.g., "P005") |
| `installationDate` | Date installed |
| `tipElevation` | Tip elevation in feet |
| `topElevation` | Top elevation in feet |
| `surveyDate` | Most recent survey date |
| `statusId` | Current operational status |

---

## Step 5: Inspection reports and attached documents

There are **14 attached documents** in NLD (site visit reports and system summary). These include USACE New Orleans District site visit reports for each segment (2024).

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/attachments?system_id=4405000557" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for a in data:
    seg = a.get('segmentId', 'system-wide')
    print(f\"ID {a['id']:6}  [{a['contClass']:20}]  seg:{seg}  {a['name']}\")
"
```

### Download a specific attachment

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/download/attachments/ATTACHMENT_ID" \
  -L -o "attachment_ATTACHMENT_ID.pdf"
```

Or use WebFetch to fetch and summarize:
```
WebFetch url="https://levees.sec.usace.army.mil/api-local/download/attachments/ATTACHMENT_ID" prompt="Summarize this levee site visit or inspection report: what deficiencies were noted, what geotechnical concerns were flagged, and what corrective actions are recommended?"
```

### Known attachment IDs

| Attachment ID | Document | Type |
|---|---|---|
| 217276 | New Orleans West Bank Levee System Summary | System Summary |
| 233022 | CEMVN_WJL1_Site_Visit_2024 (West Jefferson) | Site Visit |
| 232006 | CEMVN-ALD1_Site_Visit_2024 (Algiers West Side) | Site Visit |
| 232015 | CEMVN-ALD2_Site_Visit_2024 (Algiers East Side) | Site Visit |
| 232263 | CEMVN-PLQ7_Site_Visit_2024 (Plaquemines West) | Site Visit |

---

## Step 6: System overview and inspection ratings

```bash
curl -s "https://levees.sec.usace.army.mil/api-local/system/4405000557/detail" \
  | python3 -m json.tool
```

Key fields: `inspectionRatingName`, `inspectionRatingDescription`, `inspectionDate`, `leveeLengthInMiles`, `floodwallLengthInMiles`, `sponsors`.

For per-segment inspection history:
```bash
curl -s "https://levees.sec.usace.army.mil/api-local/segments?system_id=4405000557" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for s in data:
    print(f\"{s['id']}  {s['name'][:50]:50}  last_inspection:{s.get('lastInspectionDate','N/A')[:10]}  rating:{s.get('lastPeriodicInspectionRating','?')}\")
"
```

---

## Step 7: How to present results

1. **Borings**: "Found N borings on [segment]. Sorted by station:"
   - Table: Name | Station | Completion Date | Depth (ft) | Elevation (ft) | Soil Type | Bore Method
2. **Cross-sections**: Table with Station | Survey Date | Segment
3. **Piezometers**: Table with Name | Install Date | Tip Elevation | Top Elevation | Status
4. **Documents**: List with document name, type, and download link
5. For any record with a levee station code, note the segment and direction (higher station = downstream)
6. If results are large (>20 records), group by segment and summarize counts per segment before listing details

---

## Step 8: Records not in NLD — public records request

For geotechnical reports, slope stability analyses, seepage analyses, or internal design documents not in NLD:

- **SLFPA-W Public Records Request**: https://slfpaw.org/public-information-requests/
  - Phone: 504.340.0318
  - Email: info@slfpaw.org
  - Address: 7001 River Road, Marrero, LA 70072
  - Fee: $0.25/page duplication, $10 surcharge per 100 pages

- **USACE FOIA** (for MVN-held design documents): https://www.mvn.usace.army.mil/Contact/FOIA/

---

## Notes for Waterford 5 & 6 context

- Waterford Steam Electric Station is in **St. Charles Parish** on the west bank of the Mississippi River
- The **St. Charles Parish – New Orleans West Bank** segment (ID `4404000572`) is most directly relevant
- Geotechnical conditions near Waterford include saturated alluvial clays typical of the Mississippi River floodplain — borings showing `CH: FAT CLAY` are characteristic of the region
- Levee integrity near the facility affects both flood protection and emergency planning (FSAR Chapter 2 site geology and hydrology)
- The West Jefferson LD segment (ID `4404000511`) has the highest boring density and the most recent site visit reports

$ARGUMENTS
