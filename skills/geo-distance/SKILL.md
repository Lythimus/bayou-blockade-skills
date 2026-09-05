---
name: geo-distance
description: Measure the straight-line distance between two places, given as addresses, place names, GPS coordinates, or a mix of both
allowed-tools: Bash, AskUserQuestion
---

# Geographic Distance Lookup

Compute the straight-line ("as the crow flies") distance between two points. Each point can be a street address, a place/facility name, or a `lat,lon` pair — the two inputs don't need to match in type (e.g., a facility's GPS coordinates vs. a school's street address).

Useful for proximity claims in comment letters and outreach material: "how far is the nearest school/hospital/levee from this facility," sanity-checking a claimed setback distance, or following up on `bayou:facility-coordinates` with a second point to compare against.

## Parsing arguments

The user may provide two places in any combination:
- Two addresses or place names (e.g., "Killona Elementary School" and "Waterford 5 and 6, Killona, LA")
- Two `lat,lon` pairs (e.g., `29.985128,-90.452429`)
- One of each

If a place name is ambiguous (multiple matches, or no state/city given), ask which one before geocoding — a wrong match silently produces a confident-looking wrong distance.

## Step 1: Geocode each non-coordinate input

Use OpenStreetMap Nominatim (free, no API key). It requires a descriptive `User-Agent` and a max of ~1 request/second — fine for one-off lookups, not for batch geocoding many addresses.

```bash
geocode() {
  curl -s --get "https://nominatim.openstreetmap.org/search" \
    --data-urlencode "q=$1" \
    --data-urlencode "format=json" \
    --data-urlencode "limit=3" \
    -H "User-Agent: bayou-geo-distance/1.0 (research lookup)"
}

geocode "904 Sugarhouse Rd, Luling, LA 70070" | python3 -m json.tool 2>/dev/null
```

Inspect the results:
- If there's exactly one good match, use its `lat`/`lon`.
- If there are multiple matches (e.g., a common place name in several states), show `display_name` for each and ask the user to confirm, or add more specificity (city, parish, zip) and re-query.
- If there are zero matches, try a shorter/simpler form of the address (drop suite numbers, try just city+street).
- Skip this step entirely for any input already given as `lat,lon`.

## Step 2: Compute the distance

```bash
python3 -c "
import math

def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8  # earth radius, miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

lat1, lon1 = POINT_A_LAT, POINT_A_LON
lat2, lon2 = POINT_B_LAT, POINT_B_LON
miles = haversine_miles(lat1, lon1, lat2, lon2)
print(f'{miles:.2f} miles  ({miles*1.60934:.2f} km,  {miles*5280:.0f} ft)')
"
```

Replace `POINT_A_LAT`/`POINT_A_LON`/`POINT_B_LAT`/`POINT_B_LON` with the geocoded or user-supplied coordinates.

## How to present results

| Point | Input | Resolved coordinates |
|---|---|---|
| A | Waterford 5 & 6 facility | 29.985128, -90.452429 |
| B | Luling Elementary School (904 Sugarhouse Rd) | 29.922951, -90.366448 |

**Distance: 6.70 miles (10.78 km)**

- State this is straight-line ("as the crow flies") distance, not driving distance or downwind plume distance — call that out explicitly if the context is air dispersion or emergency planning, since actual exposure distance depends on wind direction, terrain, and plume modeling, not just radius.
- Note the geocoding source (Nominatim/OpenStreetMap) and that address-level geocoding is typically accurate to within ~10-50 meters for a rooftop match, less precise for a place-name match.
- If one point came from `bayou:facility-coordinates` (EPA ECHO), note that ECHO coordinates are accurate to ~100-500 meters for large industrial sites — compound that into the precision caveat.

$ARGUMENTS
