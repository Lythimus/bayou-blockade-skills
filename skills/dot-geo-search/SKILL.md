---
name: dot-geo-search
description: Query USDOT geo.dot.gov ArcGIS REST layers (pipelines, airports, railroads) near a facility or by attribute
allowed-tools: Bash, AskUserQuestion
---

# USDOT geo.dot.gov Geospatial Search

Query the U.S. Department of Transportation's public ArcGIS REST services at
`https://geo.dot.gov/server/rest/services` for transportation infrastructure
features — interstate/intrastate **pipelines** (natural gas, crude oil, HGL),
**airports**, and **railroads** — near a set of coordinates or matching an
attribute filter (operator, status, type). No authentication or API key
required for the public folders documented below.

Use this to answer questions like "what gas pipelines run within N miles of this
plant," "who operates the nearest crude line," "what is the nearest large-hub
airport," or "is there a Class I railroad / at-grade crossing near the site."

## When to use vs. other skills

- **This skill** — public BTS/FRA infrastructure geometry; distance-to-feature,
  operator, and status. Returns line/point geometry so you can compute distances.
- **bayou:phmsa-npms-search** — PHMSA NPMS pipeline *mapping/incident/enforcement*
  detail (operator pipeline-by-pipeline, accident history). The NPMS layers on
  geo.dot.gov are **security-restricted** (the `NPMS` and `PHMSA_DS` folders return
  an empty service list to anonymous callers); for class-location and incident
  data use the PHMSA skill / PRIMIS instead.
- **bayou:facility-coordinates** — get the lat/lon to feed into this skill first.

## Step 0: Get coordinates

If the user gives a facility name but no coordinates, look them up first
(`bayou:facility-coordinates`) or use known project coordinates. All queries here
are driven by a lon/lat point or a bounding box around it.

## Available public layers

Discover folders/services live with:
```bash
curl -s "https://geo.dot.gov/server/rest/services?f=json"                 # root folders
curl -s "https://geo.dot.gov/server/rest/services/BTS?f=json"             # a folder's services
curl -s "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0?f=json"  # layer 0 schema
```

**BTS pipelines** (folder `BTS`, layer `/0`, `geometryType: esriGeometryPolyline`):
fields `TYPEPIPE`, `Operator`, `Status` (e.g. `Operating`), plus `Shape`.
- `BTS/NaturalGas_Pipelines_US_202001/MapServer/0`
- `BTS/CrudeOil_Pipelines_US_202001/MapServer/0`
- `BTS/HGL_Pipelines_US_202001/MapServer/0` (highly volatile liquids / NGL)

> Note: `TYPEPIPE` distinguishes `Interstate` vs `Intrastate`. **Intrastate** lines
> are regulated by the **state** pipeline-safety program (in Louisiana, the LA DNR/DENR
> Pipeline Safety Program), not federal PHMSA — a material distinction for jurisdiction
> questions.

**BTS airports** (folder `BTS`, layer `/0`, `esriGeometryPoint`): hub layers
`Airports_Large_Hub_2020`, `Airports_Medium_Hub_2020`, `Airports_Small_Hub_2020`,
`Airports_Non_Hub_2020`. Rich FAA fields incl. `Fac_Name`, `Loc_Id`, `City`,
`Owner_Type`, `enplanements`, `Hub_Size`, `Ref_Point_Lat`, `Ref_Point_Lon`.

**FRA railroads** (folder `FRA`): `FRA/Class1s` (Class I railroads),
`FRA/PassengerRail`, `FRA/FRAGradeXing` (grade crossings), `FRA/STRACNET`
(strategic rail network), `FRA/FreightStations`, `FRA/Mileposts`. Inspect each
layer's `/0?f=json` for fields before filtering.

**Other public folders** (probe as needed): `National_Highway_System`,
`ARNOLD_Inventory_HPMS` / `HPMS_Public_Release` (road inventory),
`Administrative_Boundaries`, `FLMA` (federal land management). The `NPMS`,
`NPMS_SDE`, `NPMS_Layouts`, and `PHMSA_DS` folders are **access-restricted** and
list no services to anonymous requests.

## Step 1: Query features near a facility (bounding box)

Build an envelope around the facility. ~0.30° ≈ 21 mi of latitude; pick a box wide
enough to catch nearby features, then compute exact distances from geometry.

```bash
# Natural-gas pipelines within a box around Waterford 5&6 (-90.452429, 29.985128)
curl -s -G "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0/query" \
  --data-urlencode "geometry=-90.75,29.75,-90.15,30.20" \
  --data-urlencode "geometryType=esriGeometryEnvelope" \
  --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" \
  --data-urlencode "where=1=1" \
  --data-urlencode "outFields=Operator,Status,TYPEPIPE" \
  --data-urlencode "returnGeometry=true" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=json"
```

Add an attribute filter by replacing `where=1=1`, e.g.
`--data-urlencode "where=Operator LIKE '%ENTERPRISE%' AND Status='Operating'"`.

## Step 2: Compute distance from the facility to each feature

The API returns polyline geometry as arrays of `[lon,lat]` vertices under
`paths`. Compute the minimum great-circle distance from the facility point to any
vertex (good enough for "nearest pipeline" answers; for sub-100 m precision use a
point-to-segment distance):

```bash
curl -s -G "https://geo.dot.gov/server/rest/services/BTS/NaturalGas_Pipelines_US_202001/MapServer/0/query" \
  --data-urlencode "geometry=-90.75,29.75,-90.15,30.20" \
  --data-urlencode "geometryType=esriGeometryEnvelope" --data-urlencode "inSR=4326" \
  --data-urlencode "spatialRel=esriSpatialRelIntersects" --data-urlencode "where=1=1" \
  --data-urlencode "outFields=Operator,Status,TYPEPIPE" \
  --data-urlencode "returnGeometry=true" --data-urlencode "outSR=4326" --data-urlencode "f=json" \
| python3 -c '
import sys,json,math
FAC=(29.985128,-90.452429)  # (lat,lon) of the facility
def haversine(a,b):
    R=3958.7613  # miles
    la1,lo1,la2,lo2=map(math.radians,[a[0],a[1],b[0],b[1]])
    h=math.sin((la2-la1)/2)**2+math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))
d=json.load(sys.stdin)
out=[]
for f in d.get("features",[]):
    attrs=f.get("attributes",{})
    best=min((haversine(FAC,(pt[1],pt[0])) for path in f.get("geometry",{}).get("paths",[]) for pt in path), default=None)
    if best is not None: out.append((best,attrs))
for dist,a in sorted(out)[:15]:
    print(f"{dist:6.2f} mi | {a.get(\"Operator\")} | {a.get(\"TYPEPIPE\")} | {a.get(\"Status\")}")
'
```

For **airports** (point geometry), use `outFields=Fac_Name,Loc_Id,City,Hub_Size,enplanements`
and read `geometry.x`/`geometry.y` (lon/lat) per feature instead of `paths`.

## Step 3: Present results

- Lead with the **nearest** feature(s) and the computed distance in miles.
- For pipelines, always report **Operator + Status + TYPEPIPE (Interstate/Intrastate)**
  — and flag the state-vs-federal regulator implication for intrastate lines.
- De-duplicate by operator/segment where a single line appears as many short vertices.
- Note the data vintage in the layer name (e.g. `_202001` = Jan 2020 snapshot) and
  that these are static BTS snapshots, not live operator data.

## Notes & limits

- Public, anonymous, no key. Be polite; these are shared government endpoints.
- `geo.dot.gov` services can intermittently return HTTP 503/502 under load —
  retry with backoff.
- Class-location, incident, and enforcement detail for pipelines is **not** in
  these BTS layers (the NPMS/PHMSA_DS folders are restricted) — route those to
  `bayou:phmsa-npms-search`.

$ARGUMENTS
