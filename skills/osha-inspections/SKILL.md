---
name: osha-inspections
description: Use only when explicitly asked to search OSHA inspection records, violations, and citations via the DOL API.
allowed-tools: Bash, Read, AskUserQuestion
---

# OSHA Inspection & Violation Search

Search the Department of Labor's OSHA enforcement data for inspection records, citations, and violations. Requires a **free API key** from `https://dataportal.dol.gov/registration` (name + email, instant).

## Authentication

Pass your API key in every request header:
```
X-API-KEY: YOUR_DOL_API_KEY
```

Read `~/.claude/bayou-credentials.md` to get the `DOL_API_KEY`. If it shows "(add when available)", tell the user: "The DOL API key hasn't been added yet. Register at https://dataportal.dol.gov/registration (just an email, takes about a minute), then share the key and I'll add it to the credentials file."

## Base URL format

```
https://apiprod.dol.gov/v4/get/{agency}/{endpoint}/json?X-API-KEY=KEY&PARAMS
```

The API key is passed as a **query parameter** (`X-API-KEY`), not a header.

## Available OSHA datasets

| Endpoint path | Description |
|---|---|
| `osha/inspection` | Inspection case detail — why conducted, type, dates |
| `osha/violation` | Citation records with standards violated and penalties |
| `osha/accident` | Fatality/catastrophe investigations |
| `osha/accident_injury` | Injuries tied to accidents |

---

## Inspection Search

```bash
curl -s "https://apiprod.dol.gov/v4/get/osha/inspection/json?X-API-KEY=YOUR_KEY&PARAMS" \
  2>/dev/null | python3 -m json.tool
```

### Query parameters

**Filter syntax (verified 2026-06-08).** `filter_object` is a JSON object using a top-level `and`/`or` array of condition objects, each with `field`, `operator`, `value` keys (all keywords lowercase). The older `"site_state":"LA"` / `"field eq 'LA'"` shorthands return **HTTP 500** ("server error querying the dataset"). Correct form:

```json
{"and":[{"field":"site_state","operator":"eq","value":"LA"},
        {"field":"estab_name","operator":"like","value":"%ENTERGY%"}]}
```

- `{"field":"site_state","operator":"eq","value":"LA"}` — inspections in Louisiana
- `{"field":"estab_name","operator":"like","value":"%ENTERGY%"}` — establishment name (partial match; wildcard `%`)
- `{"field":"open_date","operator":"ge","value":"2020-01-01"}` — opened since date
- `{"field":"insp_type","operator":"eq","value":"A"}` — type: `A`=accident, `C`=complaint, `E`=referral, `J`=planned, `S`=unprogrammed
- `{"field":"tot_pens","operator":"gt","value":"0"}` — only cases with penalties

Other parameters:
- `limit=100` — max records (note: bare `limit`, not `$limit`)
- `offset=N` — pagination offset
- `sort_by=open_date&sort=desc` — sort (note: `sort_by`/`sort`, not `$orderby`)

**Rate limiting:** the API returns HTTP 429 readily, especially on the `osha/accident` endpoint. Pace requests (e.g. 8–35 s between calls) and retry with backoff; a burst of inspection+violation calls can exhaust the budget for a following accident call.

### Key inspection fields

| Field | Description |
|---|---|
| `activity_nr` | Unique inspection ID (links to violations) |
| `estab_name` | Establishment name |
| `site_address`, `site_city`, `site_state`, `site_zip` | Location |
| `naics_code` | Industry code |
| `insp_type` | Inspection type code |
| `open_date` | Date inspection opened |
| `close_case_date` | Date case closed |
| `case_mod_date` | Date last modified |
| `tot_pens` | Total penalties assessed |
| `nr_in_estab` | Number of employees at site |
| `insp_scope` | `A`=complete, `P`=partial, `R`=records only |

### Example: Find OSHA inspections for a facility

```bash
KEY="YOUR_KEY"
curl -s "https://apiprod.dol.gov/v4/get/osha/inspection/json?X-API-KEY=${KEY}&filter_object=%7B%22site_state%22%3A%22LA%22%2C%22estab_name%22%3A%22Entergy%22%7D&sort_by=open_date&sort=desc&limit=50" \
  2>/dev/null | python3 -m json.tool
```

Or use Python for easier filter construction (recommended — handles encoding + retry/backoff):
```python
import requests, time
KEY = "YOUR_KEY"
def get(endpoint, fo, limit=100, tries=6):
    for t in range(tries):
        r = requests.get(f"https://apiprod.dol.gov/v4/get/osha/{endpoint}/json",
                         params={"X-API-KEY": KEY, "filter_object": fo, "limit": str(limit)}, timeout=60)
        if r.status_code == 200: return r.json().get("data", [])
        if r.status_code == 429: time.sleep(12 * (t + 1)); continue   # rate-limited; back off
        r.raise_for_status()
    return []

fo = '{"and":[{"field":"site_state","operator":"eq","value":"LA"},{"field":"estab_name","operator":"like","value":"%ENTERGY%"}]}'
data = get("inspection", fo, 200)
```

### Example: Inspections with penalties in Louisiana

```bash
KEY="YOUR_KEY"
FO='{"and":[{"field":"site_state","operator":"eq","value":"LA"},{"field":"tot_pens","operator":"gt","value":"0"}]}'
curl -s "https://apiprod.dol.gov/v4/get/osha/inspection/json?X-API-KEY=${KEY}&sort_by=tot_pens&sort=desc&limit=100" \
  --data-urlencode "filter_object=${FO}" -G \
  2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print(x['estab_name'], x['open_date'], x['tot_pens']) for x in d.get('data',[]) if x.get('tot_pens')]"
```

---

## Violation Search

```bash
KEY="YOUR_KEY"
FO='{"and":[{"field":"activity_nr","operator":"eq","value":"INSPECTION_ID"}]}'
curl -s -G "https://apiprod.dol.gov/v4/get/osha/violation/json?X-API-KEY=${KEY}&limit=100" \
  --data-urlencode "filter_object=${FO}" \
  2>/dev/null | python3 -m json.tool
```

### Key violation fields

| Field | Description |
|---|---|
| `activity_nr` | Inspection ID (foreign key to inspection) |
| `viol_type` | Type: `S`=serious, `W`=willful, `R`=repeat, `O`=other |
| `issuance_date` | Date citation issued |
| `abate_date` | Abatement deadline |
| `current_penalty` | Current penalty amount |
| `initial_penalty` | Original penalty before negotiation |
| `final_order_date` | Date penalty finalized |
| `viol_nr` | Violation number |
| `standard` | OSHA standard violated (e.g., `1910.119` = PSM) |
| `emphasis` | Related emphasis program |

---

## Accident/Fatality Search

```bash
KEY="YOUR_KEY"
FO='{"and":[{"field":"site_state","operator":"eq","value":"LA"}]}'
curl -s -G "https://apiprod.dol.gov/v4/get/osha/accident/json?X-API-KEY=${KEY}&sort_by=event_date&sort=desc&limit=50" \
  --data-urlencode "filter_object=${FO}" \
  2>/dev/null | python3 -m json.tool
```

> **Note:** `osha/accident` is the most aggressively rate-limited endpoint — it frequently returns HTTP 429 even after the inspection/violation calls succeed. Query it first/alone, or wait 30–60 s between attempts.

---

## Workflow for a facility lookup

1. Read credentials from `~/.claude/bayou-credentials.md` to get `DOL_API_KEY`
2. Search inspections by establishment name and/or state
3. Note `activity_nr` values for cases with penalties
4. For each inspection of interest, pull violations using that `activity_nr`
5. Link results to the public OSHA inspection page: `https://www.osha.gov/ords/imis/establishment.inspection_detail?id=ACTIVITY_NR`

---

## How to present results

- **Inspection summary table**: Date Opened | Establishment | City | Type | Penalties | Status
- Flag serious cases: any `tot_pens > $5,000` or `insp_type = 'A'` (accident)
- For violations: group by `viol_type` and list standards violated
- Note repeat/willful violations — these carry elevated penalties and signal systemic issues
- Link to OSHA public page for full inspection detail

$ARGUMENTS
