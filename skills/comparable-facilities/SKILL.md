---
name: comparable-facilities
description: Peer-facility emissions benchmark for a repermit — reads a facility's SIC/NAICS codes from EPA ECHO, finds active facilities with the same codes (same state first, widening to EPA region, then national), sizes them by GHGRP CO2e plus web-sourced stated capacity, and compares NEI criteria/HAP and GHGRP emissions, with the draft permit's proposed limits layered on; outputs REPORT.md, comparables.csv, and social/print charts
allowed-tools: Bash, Read, AskUserQuestion, WebSearch, WebFetch
---

# Comparable Facilities: Peer Emissions Benchmark

For a permit renewal, one of the strongest comment arguments is "plants that make the same thing at the
same scale emit far less." This skill builds that comparison. It takes a target facility, reads its
industry codes, finds active peers with the same codes, ranks them by size, and compares reported
emissions pollutant by pollutant. When `bayou:permit-analysis` has extracted the draft permit's proposed
limits, it compares those as well.

Data sources:
- **ECHO REST** (`echodata.epa.gov`): facility search by SIC/NAICS, and the per-program codes in the
  Detailed Facility Report.
- **ECHO combined air emissions file**
  (`https://echo.epa.gov/files/echodownloads/POLL_RPT_COMBINED_EMISSIONS.zip`, about 150 MB, refreshed weekly).
  It carries NEI (`EIS`), GHGRP (`E-GGRT`), TRI (`TRIS`), and CAMD (`CAMDBS`) annual emissions per
  Registry ID. One download covers every facility, so peers cost no extra API calls.
- **Web search** (by Claude): stated production capacity for the target and the shortlist. No
  federal dataset holds capacity across industries.

## Running the scripts

```bash
CF=${CLAUDE_PLUGIN_ROOT}/skills/comparable-facilities/scripts
uv run --no-project --with matplotlib python -I $CF/comparables.py <codes|candidates|emissions> ... --out "$OUT"
uv run --no-project --with matplotlib python -I $CF/comparables_charts.py "$OUT" [--proposed <dir|csv>] [--hours N]
```

The charts script imports styling and unit conversion from `bayou:tri-release-report`, which must be
installed alongside this skill. `<OUT>` holds:
- `raw/`: cached ECHO responses and the filtered emissions rows;
- `summary.json`, `comparables.csv`, `charts/`, `REPORT.md`;
- `capacities.csv`, which you write in Step 5.

The emissions zip is cached in `~/.cache/bayou/echo/`. It is re-downloaded only when the server's
`Last-Modified` changes, and scanning it takes about 15 s. If `uv` is missing, ask the user to install it
(`brew install uv`).

**ECHO limits.** ECHO allows 300 requests/hour and 1,500/day, and a 429 means the quota is spent until
the next day. Each SIC or NAICS code costs 2 requests: one national query, filtered by state afterward.
Only if ECHO refuses the national query as too large does the script fall back to 2 requests per state.
ECHO REST often goes down for maintenance around midnight Central, sometimes for hours. During an outage it
returns HTTP 503 (an Apache "maintenance downtime or capacity problems" page) or times out. That is not
throttling: a spent quota returns **429** with a message pointing to the bulk downloads. The script retries
503s with backoff and stops on 429. Either way, re-run later; cached responses under `raw/` are reused.
The bulk emissions zip (`echo.epa.gov`) can be unreachable during the same window. The script then uses the
cached copy in `~/.cache/bayou/echo/` if there is one.

## Parsing arguments

- A facility name with city and state, or an ECHO Registry ID.
- Optional: `--sic` / `--ncs` codes to force, `--state` override, `--proposed <permit-analysis dir>`,
  `--hours N` (operating hours for lb/hr limits), `--top N` (shortlist size, default 5),
  `--band X` (size band, default 3, meaning 1/3× to 3×), `--min N` (peers needed before widening, default 5).
- `--out <dir>`. Default: `./comparables-<slug>`.

## Step 1: Resolve the target

Run `bayou:epa-echo-search` Step 1 (`p_fn` + `p_st`) to get the Registry ID. Large plants commonly hold
several Registry IDs. Shell Norco has nine, including a separate West Site. List every ID at the address
and ask the user which ones make up the facility being repermitted. Confirm the name and street
address before going on. The chosen IDs are the `--target` values.

## Step 2: Industry codes

```bash
uv run --no-project --with matplotlib python -I $CF/comparables.py codes --id 110013831201 --out "$OUT"
```

This prints every SIC/NAICS code with the EPA program that recorded it. The suggested match set is the
**ICIS-Air SIC** codes, which belong to the air permit, plus the 6-digit NAICS codes from ICIS-Air, TRI, and GHGRP. EIS codes are printed
but left out of the suggestion because they are often stale: Shell Norco's EIS record lists NAICS 311812,
commercial bakeries. Drop any suggested code that does not describe the plant.

**Multi-industry complexes.** A refinery with a chemical plant on site lists 2911, 2869, and 2819. Ask
the user which unit the permit covers and match on that code. The emissions totals still cover the whole
complex, and REPORT.md says so. Never present a refinery-plus-chemicals complex against standalone
refineries without that caveat.

## Step 3: Candidates

```bash
uv run --no-project --with matplotlib python -I $CF/comparables.py candidates \
    --target 110013831201 --sic 2911 --ncs 324110 --state LA --out "$OUT"
```

`--scopes` defaults to `state,region,national`, and all three are fetched up front. Step 4 picks the
narrowest scope that yields enough peers. Use `--scopes state,region` to cap the search, for example
when national peers would draw a "different regulatory regime" objection.

The script makes one `get_facilities` call and one `get_download` CSV per code and scope, so no paging is
needed. It then:
- keeps active facilities that hold an air, EIS, GHGRP, or CAMD program ID;
- **clusters Registry IDs into physical sites**. Two IDs join the same site when they share any air, TRI,
  GHGRP, EIS, or CAMD program ID, or when they sit within 0.5 mi of each other under the same leading
  name word. A plant often files GHGRP under one Registry ID and NEI under another, so a comparison by
  raw ID would miss half its emissions. Distance alone is not enough, because neighboring plants of
  different companies are legitimate peers;
- merges into the target site any ID that clusters with the user's picks, and prints those IDs. Show
  the user the auto-merged IDs and confirm they belong to the plant.

## Step 4: Emissions and shortlist

```bash
uv run --no-project --with matplotlib python -I $CF/comparables.py emissions --out "$OUT" [--exclude RID ...] [--include RID ...]
```

- **Years.** The target's latest NEI year (NEI is triennial, and 2020 is the latest in the file), latest GHGRP
  year, and latest TRI year. A peer without the same NEI year uses its nearest year, which is flagged in the
  table and the CSV. A peer whose nearest NEI year is more than 3 years off (2008 against 2020) gets no NEI
  comparison at all: it describes an older plant configuration and control era.
- **No linked NEI.** Some large plants have no EIS record linked to any of their Registry IDs in ECHO
  (ExxonMobil Baton Rouge Refinery, Valero St. Charles, and Lake Charles Manufacturing Complex as of the
  2026-10 file). Their NEI rows may sit under a neighboring Registry ID of the same company, with no shared
  program ID to prove it. When the target has NEI data, such peers are flagged "no NEI record linked in
  ECHO" and kept off the shortlist. Do not attach a neighbor's EIS record to them by guesswork.
- **Partial NEI.** ECHO can list a plant's main EIS ID while the combined file holds rows only for a minor
  one (Ponca City Refinery shows 1 tpy NOx from a side unit; its main EIS IDs have no rows). EIS numbers
  its records in sequence, so a site where a listed EIS ID **older** than every ID present is missing is
  flagged "partial NEI" and kept off the shortlist. A missing newer ID is usually a record added after the
  last NEI and is ignored. This is a heuristic: if a shortlisted peer's totals still look implausibly
  small for its GHGRP size, drop it with `--exclude` and say why.
- **Per site.** Rows are de-duplicated on (program, program ID, year, pollutant), so an ID listed under two
  Registry IDs counts once. Then every EIS ID at the site is summed.
- **Criteria pollutants.** These use the NEI names exactly: NOx, SO2, CO, VOC, PM2.5 and PM10
  (filterables + condensibles), NH3, and lead. The "portion" rows (`OTH`, filterable-only,
  condensible-only) are subsets and are never added.
- **HAPs.** Each HAP is compared on its own: benzene, 1,3-butadiene, ethylene oxide, chloroprene, formaldehyde,
  HCl, and H2S, plus any HAP in the proposed layer. NEI lists groups alongside their members (PAH and naphthalene),
  so there is **no HAP total**.
- **Size proxy.** The proxy is GHGRP total CO2e. A site without GHGRP falls back to NEI CO2 converted to
  metric tonnes, and that ratio is not computed against a GHGRP target. A site with neither is "size
  unknown." Peers outside the band (default 1/3× to 3×) are listed in the CSV but not shortlisted.
- **Industry match.** ECHO's facility-level SIC/NAICS lists merge every program's codes, so a refinery
  with an ammonia unit lists 2873. The script also reads the **air permit's own codes** (ECHO `CAASICs`,
  `CAANAICS`). A peer matching on its air-permit codes ranks first. A peer with no air-permit codes on
  record ranks next, on its facility codes. A peer whose air permit names a different industry
  (Chevron Pascagoula, a refinery; a chemical plant whose air permit says warehousing) is **set aside**:
  its whole-facility emissions belong to another industry. It stays in the CSV and off the shortlist.
  Air-permit codes are sometimes wrong (Marathon's Robinson, IL refinery is coded SIC 1422, crushed
  limestone), so the script prints every in-band set-aside. Review that list and re-run with
  `--include RID` for any that is plainly the same industry.
- **Ranking.** Within those tiers, by size closeness (|log ratio|), then by geography.
- **Widening.** If fewer than `--min` peers within the state have both emissions data and an in-band size,
  the region is added, then the nation. The printout shows the count at each scope.

The output is the shortlist (top `--top`), with every candidate in `comparables.csv`.

**Too few same-size peers.** A very large or very small plant can have fewer than `--min` peers within
the band even nationally (CF Donaldsonville, the largest US ammonia complex, has two within 3×). The
script then says so. Size-unknown peers fill the shortlist only when the band's floor is under the
GHGRP reporting threshold (25,000 t CO2e); above it, a peer that files no GHGRP report is known to be
below the band and is labeled that way. Tell the user, and offer a wider `--band`. Say in the report that the band was widened and why: "no comparable
plant of this size" is itself a finding.

## Step 5: Stated capacity (you, not the script)

For the target and each shortlisted peer, web-search for stated production capacity:
- **Refineries:** the EIA Refinery Capacity Report (barrels per calendar day).
- **Power plants:** EIA-860 nameplate MW.
- **Chemical and fertilizer plants:** company 10-Ks, press releases, trade press (ICIS, Hydrocarbon Processing,
  Fertilizer Week), or the facility's own permit application.

Write `<OUT>/capacities.csv`:

```
registry_id,capacity,unit,product,source_url,retrieved
110013831201,227000,bbl/cd,crude distillation,https://www.eia.gov/petroleum/refinerycapacity/,2026-10-08
```

- Use any one of the site's Registry IDs.
- Use the **same unit string** for comparable plants. Per-capacity ratios are computed only between
  rows that share the target's unit.
- **Leave a facility out rather than estimate.** A guessed capacity is worse than none.

Show the user the capacities next to the CO2e proxy. When capacity shows a shortlisted plant is a poor
size match (CO2e is circular, because an inefficient plant looks big), drop it with `emissions --exclude RID`
and re-run. Each re-run takes about 15 s and makes no ECHO calls.

## Step 6: Charts and report

```bash
uv run --no-project --with matplotlib python -I $CF/comparables_charts.py "$OUT" \
    [--proposed <permit-analysis dir | proposed-emissions.csv>] [--hours 8000]
```

### Proposed limits (`--proposed`)

The input is `verification/proposed-emissions.csv` from `bayou:permit-analysis` Step 6, or a hand-filled copy of
`${CLAUDE_PLUGIN_ROOT}/skills/permit-analysis/templates/proposed-emissions.csv`. **If it is missing, stop**
and ask the user to run that step. Never scrape limits from OCR text here.

Every row is listed in REPORT.md with one of these statuses:

| Status | Meaning |
|---|---|
| Compared | Mapped to a criteria pollutant, CO2e, or an NEI HAP. HAPs are matched by CAS first, then by exact name |
| Not matched | No NEI/GHGRP pollutant to compare against. Check the name and CAS |
| Grams | Dioxin-type limit, not compared |
| Unit not recognized | Not converted |

Criteria pollutants convert to short tons/yr, HAPs and lead to lb/yr, and GHG limits to metric t CO2e.
lb/hr limits are multiplied by `--hours`. Without it, the script assumes 8760 h and says so.

### Charts

| Chart | What it shows |
|---|---|
| `compare-<pollutant>` | NOx, SO2, VOC, PM2.5, CO, and CO2e, plus the two key HAPs where the target stands out most. The target is blue, peers are gray, the proposed maximum is hatched orange, and a dashed tick marks the peer median. The hero number is target ÷ peer median |
| `compare-summary` | Target ÷ peer median for every pollutant on a log scale centered on 1× |

Each chart renders in `social-square` (1080×1080), `social-portrait` (1080×1350), and `print` (6.5 in, 300 dpi, PNG
and PDF). **Read every PNG** before handing them over. Check for clipped labels, legibility at phone size,
and truncated names that hide which plant is which.

## Data rules (the scripts enforce these; keep them when editing)

- **Whole facility, not the unit.** NEI and GHGRP report facility totals. A repermit often covers one unit,
  so the comparison is between plants.
- **Same year.** Compare the same NEI year. Any peer on a different year is flagged.
- **2020 is a COVID year.** Throughput fell. Ratios between facilities stay fair because every facility
  shares the year, but absolute tons understate normal operation. REPORT.md says this whenever NEI is 2020.
- **NEI is partly estimated.** Some values come from state or EPA estimates, not facility reports.
- **Proposed ≠ reported.** Permit limits are allowable maximums, and NEI/GHGRP figures are actual
  estimates. The proposed layer is always labeled "Permitted maximum (proposed)" and drawn hatched.
- **Mass is not toxicity.** Compare each pollutant only to itself. Never sum across pollutants.
- **Thin peer sets.** A ratio against two peers is weak evidence. The table shows the peer count for every
  pollutant. Say so in prose when it is under 3.
- **Codes are self-reported and sometimes wrong.** Check that each shortlisted peer actually makes the same
  product (the name, a web check) before citing it as comparable.

## Step 7: Present

1. The target site: its Registry IDs (including any auto-merged), the codes matched, and the scope used.
2. The shortlist table, with size proxy and capacity side by side, and any flagged NEI years.
3. The headline ratios: the pollutants where the target, or its proposed limit, is well above the peer
   median, with peer counts. Also state plainly where the target is *below* the median. A comment that
   cherry-picks ratios is easy to rebut.
4. Proposed rows that were not compared or not OCR-verified.
5. Paths to `REPORT.md`, `comparables.csv`, and the charts. Kit and Nextdoor have no image-upload API, so the
   user uploads the images by hand. `bayou:public-comment` can embed the `-print.pdf`.
6. Cross-links:
   - `bayou:epa-echo-search`: compliance history of the target and its peers.
   - `bayou:tri-release-report`: the target's multi-year TRI trend.
   - `bayou:epa-ghgrp-search`: GHG by subpart.
   - `bayou:epa-webfire-reports`: flare and excess-emission reports that can explain an outlier.

### Citation format

> EPA National Emissions Inventory 2020, via EPA ECHO combined air emissions file
> (https://echo.epa.gov/files/echodownloads/POLL_RPT_COMBINED_EMISSIONS.zip, retrieved 2026-10-08): Shell
> Norco Manufacturing Complex (Registry ID 110013831201) reported 5,283 tons of NOx, against a median of
> [X] tons for [N] active Louisiana petroleum refineries (SIC 2911) of comparable size (GHGRP 2023 CO2e
> within 0.33–3× of the target's).

$ARGUMENTS
