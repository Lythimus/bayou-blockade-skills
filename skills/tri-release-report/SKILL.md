---
name: tri-release-report
description: TRI release reports and campaign charts — a multi-year release history for one facility (permit renewal), or a cumulative-burden table for every TRI facility within a radius with a proposed facility's permitted emissions layered on; outputs REPORT.md plus social (1080×1080, 1080×1350) and print (6.5 in, 300 dpi PNG + PDF) charts
allowed-tools: Bash, Read, AskUserQuestion
---

# TRI Release Report + Charts

Turns EPA Toxics Release Inventory data into tables and images that can go into a public
comment, a Nextdoor post, or a Kit email. There are two modes:

- **Facility mode** (permit renewal or reissuance): one facility's on-site releases year by
  year, split by medium. Also covers its top chemicals, carcinogen/PBT/PFAS subtotals,
  production ratios, and single-year jumps.
- **Radius mode** (new facility): every TRI facility within N miles (default 2), totaled
  by facility and by chemical. Optionally adds the proposed facility's permitted emissions
  as its own layer.

This skill reads EPA's **TRI basic data files**: one CSV per state per year, holding every
facility and chemical. Each pull is one request, not thousands of per-form Envirofacts calls.
For per-form detail (transfers, range codes, the Form R behind a number), use
`bayou:epa-tri-search`.

## Running the scripts

Every script runs through `uv` so matplotlib comes from a throwaway environment and nothing
depends on a local conda env. `--no-project` stops uv from adopting (and syncing) whatever
`pyproject.toml` sits above the working directory. `-I` keeps Python from importing anything
out of the downloaded-data directory.

```bash
TRI=${CLAUDE_PLUGIN_ROOT}/skills/tri-release-report/scripts
uv run --no-project --with matplotlib python -I $TRI/tri_fetch.py  <mode> ... --out <OUT>
uv run --no-project --with matplotlib python -I $TRI/tri_charts.py <OUT> [--formats social,print]
```

`<OUT>` holds `raw/` (cached state-year CSVs plus the TRI chemical list), `summary.json`,
`charts/`, and `REPORT.md`. Re-running with the same `<OUT>` reuses the cached downloads.
Each state-year file is 2–3 MB, so a 10-year facility pull is about 25 MB and takes 1–2 minutes.
If `uv` is missing, ask the user to install it (`brew install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). Don't fall back to system Python.

## Parsing arguments

- `--facility <TRIFD | "name, city ST">`: facility mode.
- `--at <lat,lon | TRIFD | address> [--radius <mi>]`: radius mode. The radius defaults to 2.
- `--proposed <permit-analysis dir | proposed-emissions.csv>`: radius mode only.
- `--years 2015-2024` (facility) or `--year 2023` (radius). The default is the latest
  available year: the script probes downward from last calendar year. Never assume a year
  exists; EPA publishes each year's data the following autumn.
- `--out <dir>`. Default: `./tri-report-<slug>`.
- `--formats social,print`. Default is both.

If the mode is ambiguous, ask: is this an existing facility up for renewal, or a new
facility being sited?

## Step 1: Resolve the location

**Facility by name.** Run `bayou:epa-tri-search` Step 1 to get the TRI facility ID. The
warning there applies here too: near-identical IDs belong to different companies.
`70079NRCFR15536` in Norco is Enterprise, not Shell. A plant can also have several IDs, such
as Shell's `70079SHLLL1205R` main plant and `70079SHLLL265RI` West Site. Confirm the name and
street address with the user before you pull, and say which site the numbers cover.

**Radius center.**
- Pass `lat,lon` directly.
- Or pass a TRIFD. The script then reads that facility's coordinates from the bulk file,
  because Envirofacts `pref_longitude` is stored unsigned.
- For an address or a proposed site that has no TRI ID yet, geocode with `bayou:geo-distance`
  Step 1 or `bayou:facility-coordinates`, then pass `lat,lon`. Use the application's own site
  coordinates when it gives them.

## Step 2: Fetch and summarize

```bash
# Facility (permit renewal)
uv run --no-project --with matplotlib python -I $TRI/tri_fetch.py facility --trifd 70079SHLLL1205R --years 2015-2024 --out "$OUT"

# Radius (new facility), with the proposed layer
uv run --no-project --with matplotlib python -I $TRI/tri_fetch.py radius --at 29.9957,-90.4101 --radius 2 \
    --proposed <permit-analysis-dir> [--hours 8000] --out "$OUT"
```

Radius mode fetches every state whose envelope the circle touches. Envelopes are built in for
LA, TX, MS, AR, and AL. Over-fetching is harmless because the distance filter discards the
extra rows. Outside those states, pass `--state XX`, repeating it for each neighbor the
radius could reach.

### Proposed emissions (`--proposed`)

The input is `verification/proposed-emissions.csv`, which `bayou:permit-analysis` Step 6
writes, or a hand-filled copy of
`${CLAUDE_PLUGIN_ROOT}/skills/permit-analysis/templates/proposed-emissions.csv`:

```
chemical,cas,amount,unit,basis,source_doc,page,ocr_verified
```

**If the directory has no such file, stop.** Tell the user to run permit-analysis Step 6 or
fill in the template. Do not scrape figures out of OCR text here: every number has to come
from the permit-analysis verify pass, with a page cite.

The script sorts every row into exactly one bucket, and REPORT.md lists all of them:

| Bucket | Meaning | Summed into the proposed layer? |
|---|---|---|
| TRI chemical, reported nearby | CAS on the TRI list, and a neighbor reports it | yes |
| TRI chemical, no nearby reporter | CAS on the TRI list, but no neighbor reports it | yes, as its own row |
| Not TRI-reportable | NOx, SO2, CO, PM, VOC, CO2/GHG | **never** |
| Unmatched | CAS not on the TRI list | no; check the CAS |
| Unconvertible | unit not recognized | no |

Units: tpy and ton/yr are multiplied by 2000, lb/yr is used as-is, and kg/yr is converted.
lb/hr is multiplied by `--hours`; give the application's stated operating hours, or the
script assumes 8760 and says so. g/yr stays in grams. Every conversion is shown in the table.

## Step 3: Charts and report

```bash
uv run --no-project --with matplotlib python -I $TRI/tri_charts.py "$OUT"
```

| Mode | Chart | What it shows |
|---|---|---|
| facility | `facility-trend` | stacked columns of on-site releases by medium, per year |
| facility | `facility-top-chemicals` | top chemicals in the latest year; carcinogens in orange and labeled "carcinogen" |
| radius | `radius-facilities` | facilities ranked by on-site pounds; the proposed facility is a hatched bar |
| radius | `radius-carcinogens` | carcinogens by chemical, reported vs. proposed (hatched segment stacked on) |

Each chart renders in three presets:
- `social-square` (1080×1080 px)
- `social-portrait` (1080×1350 px)
- `print`: 6.5 in wide at 300 dpi, as PNG and PDF, for `public-comment`'s pandoc PDF

Social presets lead with one headline number and end with a short source line. Print carries
the full caption. Every caption names the reporting year, the radius (in radius mode), the
source URL, and the retrieval date.

**Look at every PNG** with Read before handing them over. Check for clipped labels and text
too small to read at phone size. Long facility names are title-cased and truncated with "…",
so make sure the truncation doesn't hide which site is which.

### Data rules (the scripts enforce these; keep them when editing)

- **Use on-site releases (col 65)** for local exposure. Col 107 adds off-site transfers.
  It appears as "Off-site (context)" and never as the headline.
- **Media.** Columns 54/57/61 hold pre-2003 undivided totals, and the lettered sub-columns
  hold the later split. The script sums all of them and asserts that the per-medium sum
  equals col 65 on every row.
- **Never add grams to pounds.** Dioxins (`50. UNIT OF MEASURE = Grams`) get their own table
  and footnote.
- **Mass is not toxicity.** Pound totals are not hazard-weighted. A pound of ethylene oxide
  is not a pound of propylene. Say so, and point to EPA RSEI for risk-weighted comparison.
  Don't build a weighting here.
- **Proposed ≠ reported.** Permit figures are allowable or PTE maximums. TRI figures are
  actual self-reported estimates. The proposed layer is always labeled "Permitted maximum
  (proposed)" and drawn hatched. Don't describe the sum as "what residents will breathe."
  It is "what is reported now plus what the permit would allow."
- **Range codes.** Form R lets small releases be reported as ranges: A (1–10 lb), B
  (11–499), C (500–999). Envirofacts stores these as codes `1`/`2`/`3` with a null quantity.
  The basic data files replace them with the midpoint (5 / 250 / 750) and set no flag.
  Facility mode lists the years with an exact 5/250/750 value. Confirm any such figure
  through `bayou:epa-tri-search` Step 3 before quoting it.
- **Form A.** A Form A certifies the chemical's reportable amount is ≤ 500 lb and discloses
  no quantity. The bulk file fills those rows with `0.000`. The scripts keep them out of every
  total and list them as "Form A (≤ 500 lb, not quantified)". Never report them as zero.
- **"Carcinogen"** is TRI's flag (`46. CARCINOGEN`). It follows OSHA carcinogen criteria, which
  include *possible* human carcinogens such as ethylbenzene and cumene. Say "EPA-listed
  carcinogens" or "chemicals EPA's TRI flags as carcinogens". Don't say "cancer-causing"
  without qualification.
- **Jumps.** Facility mode flags chemicals that grew at least 3× year over year and reached
  at least 1,000 lb. Check the Form R before citing one: a jump is either a real event or a
  reporting error.

## Step 4: Present

Write for the user:
1. The headline numbers. For facility mode: the latest-year on-site total, carcinogens, and
   the trend direction. For radius mode: the facility count, total pounds, and carcinogen
   pounds, plus what the proposed layer adds.
2. Any jumps, possible range-code midpoints, unverified proposed rows, and unmatched or
   not-TRI-reportable rows.
3. The path to `REPORT.md` and the list of charts.
4. **Uploading.** Kit and Nextdoor have no image-upload API, so the user has to upload the
   images by hand. `bayou:nextdoor-campaign` and `bayou:kit-dissemination` can reference the
   chart paths in their image-suggestion lines. `bayou:public-comment` can embed the
   `-print.pdf` or `-print.png` in its pandoc render with
   `![caption](path){width=100%}`.
5. Cross-links: `bayou:epa-echo-search` (compliance), `bayou:ejscreen-report` (demographics
   for the same radius), and `bayou:epa-ghgrp-search` (CO2/CH4, which TRI omits).

### Citation format

> EPA Toxics Release Inventory basic data file, Louisiana, reporting year 2024
> (https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/2024_LA/csv, retrieved
> 2026-10-07): 9 facilities within 2 mi of 29.9957, -90.4101 reported 6,434,360 lb of on-site
> releases, including 119,188 lb of EPA-designated carcinogens.

$ARGUMENTS
