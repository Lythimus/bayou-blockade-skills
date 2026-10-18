---
name: epa-campd-search
description: Use only when explicitly asked to search EPA Clean Air Markets Program Data (CAMPD) for facility emissions, unit-level compliance history, excess emissions, and allowance accounts across CAA programs (ARP, CSAPR, NOx Budget) — requires an API key.
allowed-tools: Bash, AskUserQuestion
---

# EPA Clean Air Markets Program Data (CAMPD) Search

Search the EPA's CAMPD / EASEY API for emissions reporting, compliance history, and allowance accounts for facilities regulated under the Clean Air Act's market-based programs — Acid Rain Program (ARP), Cross-State Air Pollution Rule (CSAPR), NOx Budget Trading Program, and others. Best for documenting a **pattern of compliance failures** across a utility's fleet.

## System reference

| Field | Value |
|---|---|
| API base URL | `https://api.epa.gov/easey` |
| Swagger (facilities) | `https://api.epa.gov/easey/facilities-mgmt/swagger` |
| Swagger (compliance) | `https://api.epa.gov/easey/compliance-mgmt/swagger` |
| Swagger (emissions) | `https://api.epa.gov/easey/emissions-mgmt/swagger` |
| Swagger (accounts) | `https://api.epa.gov/easey/account-mgmt/swagger` |
| CAMPD web portal | `https://campd.epa.gov/` |
| API key registration | `https://api.data.gov/signup/` |

---

## Authentication

Read `~/.claude/bayou-credentials.md` for the `CAMPD_API_KEY` value.

If `CAMPD_API_KEY` is not yet in that file:
1. Tell the user: "A free API key is required. Register at https://api.data.gov/signup/ and share the key so I can save it."
2. In the meantime, substitute `DEMO_KEY` — this works for up to 30 requests/hour per IP (sufficient for a single research session).
3. Once the user provides a key, add it to `~/.claude/bayou-credentials.md` under a `## EPA CAMPD (api.data.gov)` section as `CAMPD_API_KEY: KEY_VALUE`.

All curl commands below use `$CAMPD_KEY` — set it before running:
```bash
CAMPD_KEY="DEMO_KEY"   # or real key from credentials file
```

---

## Step 1: Parse the user's query

Identify:
- **Owner/operator name** (e.g., "Entergy Louisiana", "Entergy Services") — most useful for fleet-wide compliance picture
- **Facility name or ORISPL** (e.g., "Little Gypsy", ORISPL `6096`) — for a single plant
- **State** (e.g., `LA`)
- **Program** — ARP (SO2 acid rain), CSAPR SO2, CSAPR NOx, NOx Budget, or "all"
- **Year range** — defaults to last 5 years if not specified
- **Data type** — compliance violations, emissions trends, allowance accounts, or all

If the query is ambiguous (e.g., just "Entergy Louisiana compliance"), proceed with fleet-wide annual compliance for the last 5 years.

---

## Step 2: Find facilities

### By owner/operator name (best for Entergy Louisiana fleet)

```bash
curl -s "https://api.epa.gov/easey/facilities-mgmt/facilities?ownerOperator=Entergy+Louisiana&stateCode=LA&page=1&perPage=100&api_key=$CAMPD_KEY" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for f in data:
    print(f\"{f['facilityId']:6}  {f['facilityName'][:40]:40}  {f.get('countyName','')[:20]:20}  {f.get('primaryFuelInfo','')}\")
print(f'--- {len(data)} facilities ---')
"
```

### By facility name or state

```bash
curl -s "https://api.epa.gov/easey/facilities-mgmt/facilities?facilityName=QUERY&stateCode=LA&page=1&perPage=50&api_key=$CAMPD_KEY" \
  | python3 -m json.tool
```

### Key facility response fields

| Field | Description |
|---|---|
| `facilityId` | ORISPL plant ID (use in all downstream queries) |
| `facilityName` | Plant name |
| `stateCode` | State |
| `countyName` | County |
| `latitude`, `longitude` | Coordinates |
| `primaryFuelInfo` | Fuel type(s) |
| `programCodeInfo` | Programs the facility is enrolled in |

### Known Entergy Louisiana ORISPL codes

| ORISPL | Facility | Parish |
|---|---|---|
| 6096 | Little Gypsy | St. Charles |
| 6097 | Michoud | Orleans |
| 6098 | Nelson | Calcasieu |
| 6099 | Ninemile Point | Jefferson |
| 6139 | Waterford | St. Charles |

Verify with the API — these may change if units are retired or ownership transferred.

---

## Step 3: Get units for a facility

```bash
curl -s "https://api.epa.gov/easey/facilities-mgmt/facilities/ORISPL/units?api_key=$CAMPD_KEY" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for u in data:
    print(f\"  Unit {u['unitId']:10}  type:{u.get('unitTypeDescription','')[:25]:25}  fuel:{u.get('primaryFuelInfo','')[:20]:20}  status:{u.get('operatingStatus','')}\")
"
```

This returns each boiler/turbine unit's ID, type, fuel, capacity (MW), operating status, and program enrollments. Note unit IDs — they're needed for unit-level compliance and emissions queries.

---

## Step 4: Annual compliance history

This is the primary tool for documenting compliance failures. Returns one record per unit per year per program.

### For a single facility

```bash
curl -s "https://api.epa.gov/easey/compliance-mgmt/compliance/account/annual?facilityId=ORISPL&year=2019,2020,2021,2022,2023&page=1&perPage=500&api_key=$CAMPD_KEY" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
violations = [r for r in data if not r.get('inCompliance', True)]
print(f'Total records: {len(data)}, Violations: {len(violations)}')
print()
for r in violations:
    print(f\"{r['year']}  {r['facilityName'][:30]:30}  Unit:{r['unitId']:8}  Prog:{r['programCode']:10}  ExcessHrs:{r.get('excessEmissionsHours',0)}  ExcessMass:{r.get('exceedanceEmissions','N/A')}\")
"
```

### Fleet-wide — loop over all Entergy Louisiana ORISPLs

```bash
for ORISPL in 6096 6097 6098 6099 6139; do
  echo "=== ORISPL $ORISPL ==="
  curl -s "https://api.epa.gov/easey/compliance-mgmt/compliance/account/annual?facilityId=$ORISPL&year=2019,2020,2021,2022,2023&page=1&perPage=500&api_key=$CAMPD_KEY" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
violations = [r for r in data if not r.get('inCompliance', True)]
if violations:
    for r in violations:
        print(f\"  VIOLATION {r['year']} {r.get('facilityName','')[:25]:25} Unit:{r['unitId']:8} {r['programCode']:12} excessHrs:{r.get('excessEmissionsHours',0)}\")
else:
    print(f'  No violations found in {len(data)} records')
"
done
```

### Annual compliance key fields

| Field | Description |
|---|---|
| `facilityId` | ORISPL |
| `facilityName` | Plant name |
| `unitId` | Unit identifier |
| `year` | Compliance year |
| `programCode` | Program (ARP, CSAPRSO2, CSNOXOS, NBTP, etc.) |
| `inCompliance` | `true` / `false` |
| `excessEmissionsHours` | Hours unit emitted above its emission rate limit |
| `exceedanceEmissions` | Mass of excess emissions (tons) |
| `avgPlanActual` | Average plan vs. actual comparison |
| `deviationHours` | Hours with monitoring plan deviations |
| `missingDataSubRate` | % of operating hours with substituted (missing) data |

---

## Step 5: Quarterly compliance and excess emissions

Finer-grained than annual — useful for identifying specific quarters with violations.

```bash
curl -s "https://api.epa.gov/easey/compliance-mgmt/compliance/account/quarterly?facilityId=ORISPL&year=YEAR&quarter=1&api_key=$CAMPD_KEY" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data:
    status = 'VIOLATION' if not r.get('inCompliance', True) else 'ok'
    print(f\"  {status}  Q{r.get('quarter','')} {r['year']}  Unit:{r['unitId']:8}  {r['programCode']:12}  excessHrs:{r.get('excessEmissionsHours',0)}  devHrs:{r.get('deviationHours',0)}\")
"
```

---

## Step 6: Unit-level emissions data

Returns actual reported SO2, NOx, and CO2 mass and rates by unit by year. Useful for trends and identifying units with high emission rates.

```bash
curl -s "https://api.epa.gov/easey/emissions-mgmt/emissions/apmd/unit-data?facilityId=ORISPL&year=YEAR&page=1&perPage=100&api_key=$CAMPD_KEY" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data:
    print(f\"  Unit:{r.get('unitId',''):8}  {r.get('year','')}  SO2:{r.get('so2Mass','?'):>8} tons  NOx:{r.get('noxMass','?'):>8} tons  CO2:{r.get('co2Mass','?'):>10} tons  OpHrs:{r.get('operatingTime','?')}\")
"
```

### Emissions key fields

| Field | Description |
|---|---|
| `unitId` | Unit identifier |
| `year` | Reporting year |
| `so2Mass` | Total SO2 mass (short tons) |
| `so2Rate` | SO2 lb/mmBtu |
| `noxMass` | Total NOx mass (short tons) |
| `noxRate` | NOx lb/mmBtu |
| `co2Mass` | Total CO2 mass (short tons) |
| `heatInput` | Heat input (mmBtu) |
| `grossLoad` | Gross electrical load (MWh) |
| `operatingTime` | Operating hours |


---

## Step 6b: Hourly operations (start-ups, shutdowns, load)

Use this to line up a unit's on/off state and load with an hour of interest: a noise or infrasound recording, an odor complaint, a flaring event. The endpoint is `emissions-mgmt/emissions/apportioned/hourly`, with one row per unit-hour.

- **Paging.** `page` and `perPage` are required (`perPage` at most 500; leaving them out returns 400). `x-total-count` is not sent on every response, so page until a batch comes back shorter than `perPage`.
- **Volume.** A month for a 3-unit plant is 2,232 rows (5 pages). DEMO_KEY is rate-limited, so use `CAMPD_KEY` for multi-month pulls.
- **Response shape.** It arrives as `{"items": [...]}`. The script also accepts a bare list.
- **Time.** `date` and `hour` are the hour beginning, in **local standard time**, all year. Part 75 does not shift for daylight saving. Convert before matching to a CDT recording.

Field names, verified live on 2026-10-17 (ORISPL 8056 Waterford, 6055 Big Cajun 2):

| Field | Meaning |
|---|---|
| `unitId`, `unitType` | Unit and type (`Combustion turbine`, `Dry bottom wall-fired boiler`, …) |
| `date`, `hour` | Hour beginning, local standard time |
| `opTime` | Fraction of the hour operating, from 0 to 1. A value strictly between 0 and 1 marks a start-up or shutdown hour. |
| `grossLoad` | Gross load, MW. Null when not operating. |
| `steamLoad` | Steam load, 1000 lb/h (cogeneration units) |
| `heatInput` | Heat input, mmBtu |
| `so2Mass`, `noxMass`, `co2Mass` | Hourly mass, with `*MeasureFlg` giving measured or substituted |

Note that this endpoint uses `opTime`, not `operatingTime` (the annual `unit-data` field in Step 6).

```bash
python3 - <<'PY'
import json, os, urllib.request
ORISPL, BEGIN, END = 8056, "2023-07-01", "2023-07-31"   # dates inclusive, local standard time
KEY = os.environ.get("CAMPD_KEY") or "DEMO_KEY"
SHOW_ALL = False                                          # True prints every hour, not only transitions
rows, page = [], 1
while True:
    url = ("https://api.epa.gov/easey/emissions-mgmt/emissions/apportioned/hourly?facilityId=%s&beginDate=%s"
           "&endDate=%s&page=%d&perPage=500&api_key=%s" % (ORISPL, BEGIN, END, page, KEY))
    with urllib.request.urlopen(url, timeout=120) as r:
        body = json.load(r)
    batch = body["items"] if isinstance(body, dict) else body
    rows += batch
    # x-total-count is not sent on every response; a short page is the reliable end signal.
    if len(batch) < 500:
        break
    page += 1
print("ORISPL %s, %s..%s: %d unit-hours" % (ORISPL, BEGIN, END, len(rows)))
by = {}
for r in rows:
    by.setdefault(r["unitId"], []).append(r)
for unit, rs in sorted(by.items()):
    rs.sort(key=lambda r: (r["date"], r["hour"]))
    on_hours = sum(r["opTime"] or 0 for r in rs)
    loads = [r["grossLoad"] for r in rs if r["grossLoad"]]
    print("\nUnit %s (%s): %.1f operating hours of %d; gross load max %s MW" % (
        unit, rs[0].get("unitType"), on_hours, len(rs), max(loads) if loads else "-"))
    prev = None
    for r in rs:
        on = (r["opTime"] or 0) > 0
        flag = ""
        if prev is not None and on != prev:
            flag = "START-UP" if on else "SHUTDOWN"
        # 0 < opTime < 1 marks the hour a unit came on or went off line.
        if on and r["opTime"] < 1:
            flag += " (partial %.2f h)" % r["opTime"]
        if SHOW_ALL or flag:
            print("  %s %02d:00  opTime %-5s grossLoad %-6s MW  heatInput %-8s mmBtu  %s" % (
                r["date"], r["hour"], r["opTime"], r["grossLoad"], r["heatInput"], flag))
        prev = on
PY
```

The output for July 2023 at Waterford (ORISPL 8056):
- Unit 2 shut down 2023-07-04 02:00.
- It started up 2023-07-17 15:00, with 0.88 h of operation and 0 MW in the first hour.
- It shut down again 2023-07-20 19:00.
- Units 1 and 4 did not run.

A start-up hour reports heat input with zero gross load, because the unit is firing before it syncs to the grid.

To set these hours against archived infrasound or seismic spectra, use `bayou:lf-acoustic-baselines` (`psd`/`compare` with matching `--hours`). Convert local standard time to the CDT/CST `--hours` it expects.

---

## Step 7: Allowance accounts and transactions

Checks if the facility has a compliance account and whether it has run a deficit (more emissions than allowances held).

### Holdings (current allowance inventory)

```bash
curl -s "https://api.epa.gov/easey/account-mgmt/allowance-holdings?facilityId=ORISPL&api_key=$CAMPD_KEY" \
  | python3 -m json.tool
```

### Transactions (allowance purchases/transfers)

```bash
curl -s "https://api.epa.gov/easey/account-mgmt/allowance-transactions?facilityId=ORISPL&api_key=$CAMPD_KEY" \
  | python3 -m json.tool
```

A large volume of allowance purchases or end-of-period shortfalls indicates the facility has consistently emitted at or near its cap — a sign of compliance pressure even without formal violations.

---

## Step 8: How to present results

### For a compliance pattern analysis

1. **Fleet summary table**: Facility | Parish | Units | Programs | Years with Violations | Total Excess Emission Hours | Total Excess Tons
2. **Violation detail table**: Year | Quarter | Facility | Unit | Program | Excess Hours | Excess Mass (tons)
3. For each violation, note the program (SO2-ARP = acid rain; CSAPR = interstate transport)
4. Highlight any `missingDataSubRate` > 5% — high substitution rates can mask actual emissions
5. Emissions trend chart (text table): show SO2 and NOx mass per facility per year to show whether emissions are declining or persistent
6. Provide the CAMPD data detail link: `https://campd.epa.gov/data/emissions/facility/ORISPL`

### Compliance status interpretation

| Signal | What it means |
|---|---|
| `inCompliance: false` | Formal violation — unit emitted above its allowance limit |
| `excessEmissionsHours > 0` | Hours emitted above emission rate limit |
| `deviationHours > 0` | Monitoring plan not followed (data quality issue) |
| `missingDataSubRate > 5%` | High fraction of hours with substituted data — emissions may be underreported |
| Large allowance purchases | Near-limit operation — buying compliance rather than reducing emissions |

### Key program codes

| Code | Program | Pollutant |
|---|---|---|
| `ARP` | Acid Rain Program | SO2 |
| `CSAPRSO2G` | CSAPR SO2 Group 1 (ozone season) | SO2 |
| `CSAPRSO2GS` | CSAPR SO2 Group 2 | SO2 |
| `CSNOXOS` | CSAPR NOx Ozone Season | NOx |
| `CSNOXAN` | CSAPR NOx Annual | NOx |
| `NBTP` | NOx Budget Trading Program | NOx |

---

## Notes for Waterford 5 & 6 context

- **Waterford 1 & 2** (ORISPL 6139, St. Charles Parish) were coal/oil steam units operated by Entergy Louisiana; retired ca. 2016. Their CAMPD records document decades of SO2 and NOx compliance history at the Waterford site.
- **Waterford 3** (nuclear) does not report to CAMPD — nuclear units have no CAA market obligations.
- **Waterford 5 & 6** are proposed nuclear units and will not appear in CAMPD.
- **Little Gypsy** (ORISPL 6096, Killona, LA) is in the same St. Charles Parish as Waterford and is the most relevant active fossil unit for demonstrating Entergy Louisiana's current air compliance posture.
- For FSAR / COL intervenor filings, CAMPD data supports arguments about cumulative air quality impacts and operator compliance culture — particularly useful in 10 CFR 51 NEPA environmental review comments.
- Pair CAMPD results with `bayou:epa-echo-search` (CAA enforcement and inspections) for a complete compliance narrative.

$ARGUMENTS
