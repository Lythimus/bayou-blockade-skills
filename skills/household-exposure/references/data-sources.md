# Data sources

What each source provides, where it lives, how large it is, and what it cannot support.
Sizes matter here: several of these are hundreds of megabytes to tens of gigabytes. The CLI
prints the size of every fetch over 100 MB, checks free disk space, and waits for the user's
confirmation before starting. Nothing in this list is downloaded silently.

Checked 2026-10-11. Recheck file names and sizes before relying on them; EPA reissues these.

## RSEI Geographic Microdata (historical screening)

Disaggregated grid-cell microdata hold one row per release × 810 m grid cell: modeled
concentration in µg/m³ for a single facility, chemical and medium. That is the only public
national dataset that attributes a concentration at a location to a named facility.

One model version is pinned per year (`RSEI_SOURCES` in `scripts/downloads.py`). EPA reissues
every year under each new version, so the same year exists in several; mixing them is what
EPA warns against.

| Years | Version | Location | Partition | Size |
|---|---|---|---|---|
| 1988–2014 | v2.3.4 | `s3://epa-rsei-pds/v234/microdata/state/la/v234_micro_state_la_<year>.csv.gz` (public HTTPS, no credentials) | per state, per year | 0.8–1.1 GB per year |
| 2015–2017 | v2.3.7 | `https://gaftp.epa.gov/rsei/Older_Versions/Version237_RY2017/Disaggregated_Microdata/micro2017_<year>.csv.gz` | national only | 21–22 GB per year |
| 2018–2019 | v2.3.10 | `.../Older_Versions/Version2310_RY2020/Disaggregated_Grid_Cell_Microdata/micro2020_<year>.csv.gz` | national only | 21–22 GB per year |
| 2020–2022 | v2.3.12 | `.../Current_Version/V2312_RY2022/Disaggregated_Grid_Cell/micro2022_<year>.csv.gz` | national only | 22 GB per year |

v2.3.6 (2009–2016), v2.3.9 (2017–2019) and v2.3.11 (2019–2021) also exist and are not used.
v2.3.8 is skipped: its directory holds a superseded "not current" release and a version
warning. Nothing after 2022 is published; those years are unknown.

- **Stream, do not store.** The files are grouped by release, not by cell, so finding one cell
  means reading the whole file. `rsei.py` decompresses the transfer as it arrives and keeps
  only rows for the home's cell and its eight neighbors, cached under `raw/rsei/` (a few
  kilobytes). A dropped connection resumes at the byte reached.
- **Transfer time.** The S3 bucket served 30 MB/s, so a Louisiana year through 2014 takes
  about a minute. EPA's FTP site is far slower: the full 2022 file (22.1 GB) took
  7 hours 48 minutes on 2026-10-12, about 0.8 MB/s, and a short sample the same night ran
  at 1.2 MB/s. Allow about eight hours for each national year from 2015 on. `screen --years`
  limits a run.
- **Grid cell from latitude and longitude.** Albers equal-area conic on GRS80, standard
  parallels 29.5° and 45.5°, origin 23°N 96°W; cell index = nearest whole multiple of 810 m
  in each axis (cells are centered on the multiples, so round, do not floor). Checked against
  the X,Y that EPA's v2.3.4 facility table gives for all 58,022 conterminous facilities:
  every one matched. Grid code 14 is the conterminous US, the only grid supported.
- **State files are partitioned by the cell's state, not the facility's.** The Louisiana 2014
  file opens with rows from a Greenville, Mississippi facility whose cells stop at latitude
  33.006°, the Louisiana–Arkansas line. One Louisiana file therefore holds every modeled
  source reaching a Louisiana home, including plants across a state line.
- **Layouts.** Through v2.3.11: 13 columns, no header, no year column (the year is only in
  the file name): `GridCode, X, Y, ReleaseNumber, ChemicalNumber, FacilityNumber, Media, Conc,
  ToxConc, Score, CTConc, NCTConc, Pop`. v2.3.12 adds a header row and a leading `Year`
  column. `Conc` is µg/m³. The layout is detected from the first line.
- **Media 6, 750 and 754** are transfers to a treatment works or incinerator. For those rows
  `FacilityNumber` is a row of the off-site table, not the facility table; joining them to
  the facility table names the wrong plant.
- **Lookup tables** (chemical, facility, off-site) must come from the same version as the
  microdata: chemical numbers are regrouped between versions (346 is "lead and lead
  compounds" in v2.3.4 and "lead" in v2.3.12). v2.3.4's are single files under
  `v234/data_tables/` on S3. Later versions ship them inside a 300–430 MB
  `Public_Release_Data` archive; `rsei.py` reads just those three members by HTTP byte range
  (about 15 MB) and caches trimmed copies in `~/.cache/bayou/rsei/<version>/`.
- **RSEI's own toxicity columns are not used.** Its unit risks are per mg/m³ and its weights
  are a scoring scheme; toxicity values come only from Table 1.
- **TRI categories.** RSEI reports metals and some groups as TRI categories (`N420`, lead
  compounds). `references/tri-category-map.csv` maps those Table 1 files under an element's
  CAS number. **Chromium:** in the microdata, `ToxConc / Conc` for chromium equals RSEI's
  chromium (VI) toxicity weight exactly at every facility, whatever its `ChromHexPercent`
  (checked on the 2014 Louisiana file). RSEI's method models only the share of a chromium
  release it takes to be hexavalent, set by the facility's industry, so `Conc` is read as
  that hexavalent share and given the chromium (VI) values with no further scaling. If
  `Conc` were total chromium instead, the figure would overstate; the report flags it as an
  assumption either way.
  Polycyclic aromatic compounds, diisocyanates, glycol ethers and antimony compounds have no
  single Table 1 value and stay unquantified.
- **How a cell gets its value** (RSEI methodology v2.3.7, section 5.3). RSEI runs AERMOD
  with the source placed at the center of the facility's cell, so a plant's position inside
  its 810 m cell is lost; fugitive releases are a 10 m square at ground level. The
  facility's own cell is interpolated from 441 receptors within a kilometre of that center.
  Farther out, concentrations are calculated only at receptors every 5 km, each taken at
  the point of its cell nearest the facility, and the cells between are interpolated. Two
  consequences: a home in the same cell as a plant gets a cell-wide average that says
  nothing about which side of the fence it is on, and a figure for a home several
  kilometres out is an interpolation between sparse points, not a modeled value for that
  cell.
- **Zero or unknown.** No row for a facility and chemical in a year that was read means RSEI
  modeled no air release. It is a known zero only when the TRI basic file cached by
  `prepare --facilities` shows the facility filed a Form R for that chemical with no air
  release. With no filing, or no TRI file on hand, the year is unknown for that source.
- **Checked against AirToxScreen** (live run, 2026-10-12, one St. Charles Parish home). RSEI
  2022 (v2.3.12, header layout) gave 69 sources and 108 chemicals within 50 km, with stack,
  fugitive and off-site rows all present. The year's concentrations times EPA's unit risks sum
  to about 12 in a million on a lifetime basis; AirToxScreen 2020 puts stationary point
  sources at 14.5 in a million for the same census block. The two use different years and
  inventories, so agreement within a factor of two is a check on units and columns, nothing
  more.
- **Do not splice versions into one trend.** Each year's version is recorded and printed.
  Sums over a residence cross versions; a change across a version boundary is not evidence.
- **Limitation, quoted in every screening report:** the microdata "cannot solely be used to
  determine actual on-the-ground exposures or health risks at any given point."
- `--rsei-dir` reads files the user already has, by EPA's file name.

## TRI basic data files (facility discovery)

`prepare --facilities` reads one file per state per year from
`https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/<year>_<ST>/csv`, the same
files `bayou:tri-release-report` uses. Louisiana is 1.5–2.4 MB per year and Texas 7.5 MB. A
30-year residence near a state line is 60 files and passes 100 MB in total, so the download
gate applies to the batch, not only to single files. Reporting began in 1987.

Two plants at one fence line can hold separate FRS registry IDs and both report in the same
years (Denka Performance Elastomer and DuPont Pontchartrain Works in LaPlace). Those are not
duplicates and are not merged; only records sharing an FRS ID, or paired by hand in
`facility_aliases`, are.

## AirToxScreen (neighborhood context)

Latest assessment year is 2020. Files are under
`https://gaftp.epa.gov/rtrmodeling_public/AirToxScreen/2020/`. One year only, every source
type at once; it is context, shown in its own section and never added to RSEI or AERMOD
figures.

- Results are published by **census block** (2020 blocks), not tract, and only as Excel
  workbooks: `Cancer/BySource/Region6a_CancerRisk_by_block_srcgrp.xlsx` is 124 MB and holds
  Arkansas, Louisiana, New Mexico, Oklahoma and part of Texas. `Region6b` is Texas only.
- Columns: `State, EPA Region, County, FIPS, Block, Population, Total Cancer Risk (per
  million)`, then 39 source groups (`PT-StationaryPoint`, on-road and non-road groups,
  non-point groups, `FIRE`, `BIOGENICS`, `SECONDARY`, `BACKGROUND`). No coordinates.
- The sheet is 911 MB of XML inside the workbook. `airtox.py` reads the string table at the
  end of the file by byte range to find the block, then decompresses the sheet as a stream
  and stops at the block's row. Up to 124 MB is transferred and only the row is kept. That directory served
  0.12 MB/s when measured (2026-10-12), about 17 minutes for the whole workbook.
- The home's block comes from the Census Bureau geocoder, which means **sending the home's
  coordinates to that service**. `screen --block GEOID` avoids it; `--no-airtox` skips it.
- By-pollutant workbooks (249 MB) and ambient concentrations (417 MB) are not read in v1.

## Toxicity values

EPA OAQPS Table 1, "Prioritized Chronic Dose-Response Values," as a spreadsheet:
`https://www.epa.gov/system/files/documents/2021-09/chronicfinaloutput_9_29_2021-12-46-18-pm.xlsx`
(37 KB, dated 2021-09-29, linked from `https://www.epa.gov/fera/dose-response-assessment-tables`).

- One sheet, header on the fifth row, 227 chemicals. Vendored as
  `references/oaqps-table1-2021-09-29.csv` (inhalation columns only) so runs need no network
  and no spreadsheet reader; `toxvalues.py` records the source URL, date and file hash. Columns used: `CHEMICAL NAME`, `CAS NO.`,
  inhalation noncancer value in **mg/m³** with its source, EPA weight of evidence, inhalation
  unit risk in **per µg/m³** with its source, and `EPA MOA`.
- A zero in a value column means no value, not a value of zero.
- `EPA MOA` is `M` (mutagenic) or `m-rpf` for the chemicals that take age-dependent adjustment
  factors below age 16. Chloroprene and ethylene oxide both carry `M`.
- The table's footnotes are on a separate page,
  `https://www.epa.gov/fera/additional-information-adjustments-and-special-cases-dose-response-values-tables-1-and-2`.
  Two change the arithmetic: for trichloroethylene the age factors apply only to the
  kidney-cancer share of the unit risk (note 2), and vinyl chloride is unflagged because its
  listed value already covers exposure from birth (note 13). Both are encoded in
  `toxvalues.py`. Listed unit risks are otherwise unadjusted.
- The noncancer value is in mg/m³ and modeled concentrations are in µg/m³: convert once, in
  one place.
- The table has no target-organ column. Organ assignments come from
  `2020AirToxScreenPollutants.xlsx` in EPA's AirToxScreen 2020 supplemental data archive
  (`https://www.epa.gov/system/files/other-files/2024-06/2020-airtoxscreen-supplemental-data-files.zip`,
  35 MB; the workbook is 88 KB). It flags 14 organ systems for 135 pollutant codes. Vendored
  as `references/airtoxscreen-2020-target-organs.csv`; only the organ flags are taken, never
  that workbook's toxicity values. A chemical with a reference concentration and no organ
  flag is listed as unassigned and left out of every hazard index.

- **Nickel, cobalt and lead compounds have no unit risk in Table 1** (rows re-read from EPA's
  spreadsheet on 2026-10-12; the file's hash matches the vendored copy). Table 1 gives unit
  risks only for nickel refinery dust and nickel subsulfide. So TRI "nickel compounds"
  appears in the hazard figures and is listed as unquantified for cancer, although EPA
  classes it a human carcinogen. The report must say this where it lists unquantified
  chemicals.

## AERMOD

Source: `https://gaftp.epa.gov/Air/aqmg/SCRAM/models/preferred/aermod/aermod_source.zip`
(675 KB). Release v26135; the archive unpacks to `aermod_source_v26135/`.

**Build** (`scripts/aermod_build.sh`, about 50 seconds):

- Installs to `~/.cache/bayou/aermod/v26135/aermod` (`BAYOU_AERMOD_DIR` moves the cache). A
  `BUILD.txt` beside it records the release, source hash, compiler and flags; the build is
  skipped when that stamp already matches, and `model.json` copies it into its provenance.
- EPA's URL carries no version and is replaced in place at each release, so the release is
  pinned by SHA-256 (`5092c1d6...1cd8ed`, in the script). On a mismatch the script builds
  nothing and exits 4: EPA has published a release this skill was not checked against.
- Homebrew gfortran (16.1.0 when checked) with EPA's own flags
  (`-fbounds-check -Wuninitialized -O2`) and compile order from `gfortran-aermod.bat`, without
  `-static`, which macOS cannot link. No errors, 35 warnings. Without gfortran the script
  exits 2 and names `brew install gcc`; it installs nothing itself.
- EPA's archive marks its top directory read-only, so the script makes the unpacked copy
  writable before compiling.

**Behaviour to rely on:**

- **AERMOD exits with status 0 even when it fails.** Success is read from the message summary
  at the end of the output file (`A Total of N Fatal Error Message(s)`, the hours processed
  and the "Finishes Successfully" line), never from the exit code.
- It reads `aermod.inp` from the working directory and writes `aermod.out` there.
- A run fails at setup if a directory named in an output path does not exist.
- Concentrations are printed to five decimals. Unit-rate runs therefore use 1,000 g/s and
  divide the result by 1,000; at 1 g/s a source tens of kilometres away would keep one or
  two significant digits.

**Verification** (`hx.py model --check-build`, checked 2026-10-12, exit 0):

EPA's `aermod_test_cases.zip` is 489 MB. The server honors HTTP range requests, so the files
for three cases are read out of the archive by byte range (about 15 MB transferred) and kept
under `~/.cache/bayou/aermod/v26135/testcases/`. Nothing over 100 MB is fetched.

| Case | Covers | Result against EPA's published files |
|---|---|---|
| `aertest` | one stack with building downwash, flat terrain | 144 plot-file rows identical; summary identical |
| `flatelev` | stacks in flat and elevated terrain, period averages | 44 plot-file rows identical; summary identical |
| `allsrcs` | every source type | 234 summary lines; 9 differ, by at most 1.7e-4 of the value |
| linearity | `aertest` at zero and double rate | zero gives 0; double gives 2× to within 1.9e-5 |

The nine differing lines are all in source groups `RLINEBA` and `RLINEDE`: `RLINEXT` sources
with the experimental barrier and depressed-roadway options. The skill refuses those source
types. Every other group must match to within `TEST_TOLERANCE` (5e-4 of the value, which
covers the rounding of a five-decimal printout); a difference outside those two groups, or
any larger one, fails the check.

Separately, a unit-rate rerun multiplied by the filed rate reproduced EPA's period maxima for
`POINT`, `VOLUME`, `AREA`, `AREACIRC`, `AREAPOLY`, `OPENPIT` and `LINE` sources to 2.1e-5 or
better, which is the method `model` uses.

Not verified: any real LDEQ application's modeling files. The tests use EPA's cases as
stand-in applicants. Inputs written by commercial front ends (BREEZE, Lakes AERMOD View) use
the same keywords but may use ones the rerun's keep-list has not met; anything not kept is
named in the run's assumptions.

How `model` uses the build is in `aermod-inputs.md`.

## Meteorology

No public download of AERMOD-ready surface and profile files for Louisiana was found. LDEQ
publishes modeling procedures but not processed meteorology, unlike Mississippi, Iowa and
Minnesota. In order of preference:

1. The `.SFC` and `.PFL` files filed with the applicant's own modeling.
2. A public records request to LDEQ's Air Quality Assessment Division for the files the agency
   approved in the modeling protocol (`bayou:la-public-records-request`).
3. Processing National Weather Service data with AERMET and AERSURFACE. Not automated here.

Wind observations from `bayou:wind-history` are not a substitute: AERMOD needs boundary-layer
parameters that a wind record does not contain.

## Report outputs and the public version

`report` reads only what `screen` and `model` wrote (`screening.json`, `screen.csv`,
`model.json`); it fetches nothing.

- **One results dict.** `report.build()` produces it; REPORT.md, exposure.csv, results.json,
  manifest.json and the charts are rendered from it alone. The public dict is built without
  the address, coordinates, grid cell, census block, per-source distances, the home's model
  coordinates and terrain height, birth years, and the facilities that are not named in a
  table.
- **Why the facility list is cut.** Which facilities fall inside a 50 km circle bounds where
  its center is, and distances to several known facilities fix it outright.
- **Why figures are rounded.** Full-precision RSEI concentrations for a set of facilities
  identify the 810 m cell. Two significant digits and sums over facilities make that harder,
  not impossible; `limitations.md` says so.
- **Why the public manifest hashes less.** A hash of `assessment.json`, `screening.json` or
  a cached cell extract can be tested against candidate locations. The public manifest
  hashes only public records: TRI state files, the applicant's files and the emission tables.
- **Lookups through public datasets.** Two things were dropped from the public dict because
  they can be matched against files anyone can download: AirToxScreen's per-block source
  group figures (six of them pick one block out of a tract), and the distance to, and filed
  value at, the applicant's nearest receptor. The public report keeps EPA's rounded block
  total and the cross-check ratio.
- **Reproducibility.** Two runs on the same day from the same cache give byte-identical
  outputs, PDFs included (`SOURCE_DATE_EPOCH` is set from the report date). Checked
  2026-10-12.
- **Not combined.** RSEI history and the AERMOD increment are shown side by side with no
  sum: one is a floor on a grid, the other a ceiling at a point.
