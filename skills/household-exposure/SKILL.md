---
name: household-exposure
description: Household air-exposure assessment for one Louisiana home — past exposure to industrial air toxics from EPA RSEI modeled concentrations over each person's years at the address, plus what a proposed facility could add, from an AERMOD run on the applicant's own modeling files and permitted rates; reports screening cancer risk and hazard index by organ, with a shareable version that withholds the address. Outputs REPORT.md, exposure.csv, charts and a reproducibility manifest. Needs `uv`; the proposed-facility tier needs `gfortran`
allowed-tools: Bash, Read, Write, AskUserQuestion, Skill
---

# Household Air-Exposure Assessment

Estimates what one household has been breathing from nearby industry, year by year, and what
a proposed facility would add. Inhalation only, one home per assessment, Louisiana.

There are two tiers, and a report can hold either or both:

- **Past** (`screen`): EPA's RSEI modeled concentration at the home's 810 m grid cell for
  every TRI facility and chemical within 50 km, for each year a person lived there
  (1988-2022), with EPA's AirToxScreen 2020 figure for the block as separate context.
- **Proposed** (`model`): the proposed facility's long-term concentration at the home, from
  EPA's AERMOD run on the applicant's modeling files and scaled by permitted emission rates.

The result is a **modeled outdoor concentration at the home**. It is not a measurement, not a
dose, and not proof that a facility made anyone sick. Read `references/limitations.md`
before quoting any figure, and keep the limit attached to the number.

## Running the scripts

```bash
HX=${CLAUDE_PLUGIN_ROOT}/skills/household-exposure/scripts
uv run -q --no-project --with matplotlib python -I $HX/hx.py <prepare|screen|model|report> --out <OUT> ...
```

- `<OUT>` holds a home's location. It **must be outside the plugin directory**; every
  subcommand refuses a path inside it. Files there are written owner-readable only,
  except the `public/` set.
- The examples below write `hx.py ...` for the full `uv run ... $HX/hx.py ...` line.
- **Exit status 3 means a download over 100 MB is waiting.** The command has printed each
  file, its size and the free disk space. Show that list to the user with AskUserQuestion,
  and rerun with `--yes` only if they agree. Never pass `--yes` on your own.
- If `uv` is missing, ask the user to install it (`brew install uv`). Do not fall back to
  system Python.

## Step 1: What to ask the household

Ask only for what the calculation uses:

- The home's address or coordinates.
- For each person, the dates they lived there. Use a short pseudonym (`A`, `B`, `kid1`), not
  a name.
- Optionally each person's **birth year**. It is used for one thing: EPA's early-life factors
  for mutagenic carcinogens (10 times before age 2, 3 times from 2 to 16). Without it, a
  child's cancer figure is too low and the report says so.
- For a proposed facility: the `bayou:permit-analysis` output directory, the year it would
  start, how many years to assume it runs, and how long each person expects to stay.

Do not ask for names, medical history or birth dates.

Geocode an address with `bayou:geo-distance` Step 1. Tell the user that this sends the
address to a geocoding service, and that `screen` later sends the coordinates to the Census
Bureau's geocoder to find the census block unless `--block GEOID` or `--no-airtox` is given.

In St. Charles, Ascension or St. James, confirm the home with `bayou:parish-assessor-gis`.
`parcels.py address "<address>"` snaps to the parish address point and names the parcel; use
those coordinates. For the distance to the facility's property line, as opposed to its stack
or centroid, build the facility with `parcels.py footprint`. Then run `receptors --footprint
… --private`; it lists this home's edge-to-edge distance among the nearest homes. The
`address` output (it names the owner) and the `--private` output are for the household only,
so keep both out of the public report.

## Step 2: `prepare`

```bash
hx.py prepare --out "$OUT" --at 29.9647,-90.3840 --label "short label" \
    --member 'A:1998-03-01..2010-06-30,2015..' --birth A=1990 \
    --member 'B:2015..' \
    [--proposed <permit-analysis dir> --proposed-name "Plant name" --op-start 2028 --op-years 30 \
     --stay operating_end | --stay A=2045] \
    --facilities
```

A blank end date means the person still lives there. `--stay` is required with a proposed
facility: `operating_end` (for as long as it runs), a year, or a date, optionally per member.
It is an assumption and the report prints it.

`--facilities` lists the TRI facilities within 50 km and the years each reported, and caches
the TRI files `screen` uses to tell a reported zero from a missing year. `prepare` also
prints what `screen` would download. To change the assessment later, edit
`<OUT>/assessment.json` and rerun `prepare --out "$OUT"`.

## Step 3: `screen` (past exposure)

```bash
hx.py screen --out "$OUT" [--years 2005-2014] [--block GEOID | --no-airtox] [--rsei-dir DIR]
```

Sizes decide how to run this, so tell the user before starting:

| Years lived there | Download per year | Time |
|---|---|---|
| 1988-2014 | about 1 GB (Louisiana file) | about a minute |
| 2015-2022 | about 22 GB (national file) | about 8 hours from EPA's server |
| before 1988, after 2022 | none exists | those years are unknown |

Files are streamed and only the home's rows are kept, so disk use stays small. A rerun reads
the cached rows and takes seconds. `--years` limits the run; years left out stay unknown and
the report says so. `--rsei-dir` uses microdata files already on disk.

Read the printed summary to the user as it is: which years have a figure, and that any total
covering only some years is a floor.

## Step 4: `model` (a proposed facility)

Read `references/aermod-inputs.md` first. It lists the files to collect from the application,
the two tables to fill in (`templates/source-emissions.csv`, `templates/source-inventory.csv`),
every flag, and what each dispersion path does.

In outline:

1. Build AERMOD once and check it: `bash $HX/aermod_build.sh`, then `hx.py model --check-build`.
   Do not use a build that fails the check.
2. Find the applicant's modeling files: `bayou:ldeq-edms-search` and
   `bayou:ldeq-edms-download` under the facility's AI number; `bayou:document-ocr` for
   scanned emission tables. Look in the toxic air pollutant modeling first: Louisiana's
   annual-average standards (benzene, ethylene oxide, formaldehyde, 1,3-butadiene, vinyl
   chloride) are the runs that can be read as long-term concentrations.
   `bayou:ldeq-eric-emissions` `eric.py points <AI> --permitted` lists the facility's release points
   with stack parameters, actual emissions and current permitted rates. Use it only to
   **cross-check** what you transcribe from the application, never as a source for the two
   tables: rows there need the application's `source_doc` and `page`, the permitted sheet
   excludes pending applications, and LDEQ says ERIC coordinates are often wrong.
3. Fill `source-emissions.csv` (per emission point, per chemical, with page citations).
4. Run `hx.py model --out "$OUT" --applicant-inp ... --applicant-plot CAS=FILE ... --utm-zone N --datum NAD83`,
   with the zone and datum taken from the modeling report (Louisiana spans zones 15 and 16).

When an input is missing, `model` gives **no number** for whatever depended on it and writes
`model-gaps.md` with a records-request list. Do not fill the gap with a typical stack height,
a nearby station's weather, or a distance-based estimate. Offer
`bayou:la-public-records-request` with the list instead.

## Step 5: `report`

```bash
hx.py report --out "$OUT"                              # private: names the home
hx.py report --out "$OUT" --public [--formats print,social]   # writes <OUT>/public/
```

Each writes `REPORT.md`, `exposure.csv`, `results.json`, `manifest.json` and `charts/`. It
works with whichever of `screen` and `model` has run and names the one that has not.

The private report is for the household. The **public** one leaves out the address,
coordinates, grid cell, census block, distances and birth years, names only the census tract,
and rounds to two significant digits. Before anything is shared:

- Read the public `REPORT.md` and open every PNG. Check that the label, member IDs and
  facility name give nothing away; the tool cannot judge those.
- Tell the user the remaining limit: the figures still depend on the location, and someone
  with EPA's full RSEI microdata could match `exposure.csv` to an 810 m cell. Sharing the
  summary and charts without the data files avoids that.

Social-size charts (`--formats print,social`) are for the public version only.

## Presenting the results

The report leads with what the user asked for: one cancer figure summed across chemicals
and one hazard index per target organ, for each person, then the chemicals and facilities
behind them, then what the proposed facility would add. When you summarize it:

- Say "modeled outdoor concentration at the home". Never "absorbed", "dose" or "body burden".
- Give risk as "N in a million", and say "floor" whenever years are missing.
- Do not add the past figure to the proposed one. The first is a floor for reported releases;
  the second is a ceiling at permitted rates. The report explains this; repeat it if asked
  for a single total.
- Do not add chemicals together by weight, and do not turn a hazard quotient into a chance of
  illness.
- A chemical with no cancer figure is unquantified, not safe. Nickel, cobalt and lead
  compounds are in that group.
- If the report flags that the applicant's result and the entered emission rates disagree,
  resolve that before the proposed figure is used anywhere.
- Water is not assessed. The report's "Not assessed" section has the follow-up checklist.

For a public comment, pair this with `bayou:tri-release-report` (what the same facilities
reported releasing) and `bayou:chemical-hazard-profile` (what the leading chemicals do).
For accidental-release context, `bayou:epa-rmp-lookup near <lat> <lon> --radius-km 5` lists the
RMP facilities, substances and past accidents around the home. `bayou:csb-nrc-hazmat nrc --near
<lat> <lon> --radius-km 5` adds National Response Center release reports that carry coordinates
(the filter runs locally on cached files). Most plant reports have no coordinates, so also search
those facilities by parish and company name. Keep both separate from these routine-emission figures.

## Checks

`uv run -q --no-project --with matplotlib python -I $HX/selfcheck.py` runs the offline checks
(no network, no AERMOD). `hx.py model --check-build` checks the AERMOD build against EPA's
published results.

## References

- `references/methods.md`: the calculations, with two hand-worked examples.
- `references/limitations.md`: what the figures cannot support.
- `references/data-sources.md`: where each dataset comes from, sizes, versions.
- `references/aermod-inputs.md`: the dispersion tier's inputs and flags.
