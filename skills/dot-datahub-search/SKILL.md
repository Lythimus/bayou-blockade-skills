---
name: dot-datahub-search
description: Search and query USDOT datahub.transportation.gov (Socrata) datasets via the catalog + SODA APIs
allowed-tools: Bash, AskUserQuestion
---

# USDOT datahub.transportation.gov (Socrata) Search

Discover and query datasets on the U.S. DOT open-data portal
`https://datahub.transportation.gov`, which runs on **Socrata**. Two public APIs,
no key required for read access:

1. **Catalog / discovery API** — find datasets by keyword:
   `https://datahub.transportation.gov/api/catalog/v1`
2. **SODA resource API** — query rows of a hosted dataset:
   `https://datahub.transportation.gov/resource/{dataset-id}.json`

Useful for FMCSA carrier-safety census, NHTSA crash/recall data, BTS transportation
statistics, transit, and aviation datasets. **For PHMSA pipeline incident/enforcement
data, use `bayou:phmsa-npms-search` instead** — those entries on this portal are
external-link redirects, not queryable here (see the critical note below).

## CRITICAL: `dataset` vs `href` — what is actually queryable

The catalog federates results from many Socrata domains and also lists external
links. Only entries with **`resource.type == "dataset"` that are hosted on
`datahub.transportation.gov`** are queryable via the SODA `/resource/{id}.json`
endpoint. Two traps:

- **`type: "href"`** — an external-link/redirect tile (e.g. *"Pipeline Incident
  Flagged Files"*, *"NPMS Map Tool"*, *"Pipeline Enforcement Transparency Portal"*
  are all `href`). SODA returns **HTTP 404 `dataset.missing`** — they live on
  PHMSA's own portals, not here.
- **federated `dataset` from another domain** — a catalog search without a domain
  filter returns hits from other cities/agencies (e.g. "NOPD Incidents"). Their
  IDs 404 on `datahub.transportation.gov/resource/...` because they're hosted
  elsewhere.

**Always scope the catalog to this domain** to avoid both traps:
```
&domains=datahub.transportation.gov&search_context=datahub.transportation.gov
```
Then confirm `resource.type == "dataset"` before attempting a SODA query.

## Step 1: Discover datasets

```bash
curl -s "https://datahub.transportation.gov/api/catalog/v1?\
domains=datahub.transportation.gov&search_context=datahub.transportation.gov&\
q=carrier%20safety&only=dataset&limit=10" \
| python3 -c '
import sys,json
d=json.load(sys.stdin)
print("matches:",d.get("resultSetSize"))
for r in d.get("results",[]):
    res=r.get("resource",{})
    print(res.get("id"),"|",res.get("type"),"|",(res.get("name") or "")[:60])
'
```
- `only=dataset` filters out `href`/`story`/`map` tiles up front.
- Drop `q=` to browse; add `&offset=N` to page.

## Step 2: Inspect a dataset's columns

```bash
curl -s "https://datahub.transportation.gov/resource/{id}.json?\$limit=1" | python3 -m json.tool
```
The JSON keys are the SODA field names you filter on. For full metadata/types:
`https://datahub.transportation.gov/api/views/{id}.json`.

## Step 3: Query rows with SoQL (SODA)

SODA query params (URL-encode the `$`):
- `$select=col1,col2` — projection
- `$where=...` — filter, e.g. `$where=phy_state='LA'` or
  `$where=add_date > '2024-01-01'`; combine with `AND`/`OR`; `like`/`upper()` supported
- `$q=keyword` — full-text search across the row
- `$order=col DESC`, `$limit=N` (default 1000, max 50000), `$offset=N`
- `$group=col&$select=col,count(1)` — aggregation

```bash
# Example: FMCSA carrier census (az4n-8mr2) — Louisiana corporations, first 5
curl -s -G "https://datahub.transportation.gov/resource/az4n-8mr2.json" \
  --data-urlencode "\$where=phy_state='LA'" \
  --data-urlencode "\$select=dot_number,legal_name,phy_city,carrier_operation" \
  --data-urlencode "\$limit=5" \
| python3 -m json.tool
```

If a dataset legitimately requires auth you may get **HTTP 403** ("must be logged
in" / "no row or column access to non-tabular tables") — that dataset is gated;
note it and fall back to the source agency's own portal.

## Step 4: Present results

- State the dataset name + id + last-updated, and the filter applied.
- Summarize counts/aggregates; show a compact table of the most relevant rows.
- Link the dataset page: `https://datahub.transportation.gov/d/{id}`.
- Note data vintage and that Socrata snapshots may lag the source agency.

## Notes & limits

- Public, anonymous read; be polite to the shared endpoint. Intermittent 5xx →
  retry with backoff.
- Rate limits are looser with an app token (`$$app_token=`), but none is required
  for modest use.
- **Pipeline data**: the PHMSA tiles here are `href` redirects — route pipeline
  incident/enforcement/mapping questions to `bayou:phmsa-npms-search`, and
  pipeline *geometry/distance* to `bayou:dot-geo-search` (geo.dot.gov BTS layers).

$ARGUMENTS
