---
name: ldeq-eric-emissions
description: Louisiana's own emissions inventory (LDEQ ERIC) by AI number — annual certified criteria pollutants (tons) and LAC 33:III Chapter 51 toxic air pollutants (lb) for every reporting facility from 1991 to the latest year, release-point actual emissions with stack parameters, current TEMPO permitted rates by statistical basis, parish totals, and same-NAICS Louisiana peer rankings. Use for a facility's emission history and trend, to rank it against Louisiana peers past NEI 2020, to reconcile state TAP figures against TRI, to cross-check a permit application's EIQ sheets, or to list what is emitted near a home or school.
argument-hint: facility <AI> | peers <AI> | points <AI> [--permitted] | radius <lat> <lon> --radius-m N --pollutant X | sources <AI> [--receptor lat,lon] | parish "<name>" --pollutant X --year Y | reconcile <AI> --year Y --pollutant X | search "<name>"
allowed-tools: Bash, Read, WebFetch, WebSearch
---

# LDEQ ERIC emissions inventory

ERIC (Emissions Reporting and Inventory Center) is where Louisiana facilities certify their annual emissions under LAC 33:III.919 (criteria pollutants) and 33:III.5107 (toxic air pollutants). All of it is public, with no login, CAPTCHA or browser needed. There are two ways in:

- **Statewide annual certifications.** Two xlsx files are linked from [deq.louisiana.gov/page/eric-public-reports](https://deq.louisiana.gov/page/eric-public-reports). They have one row per AI per year:
  - `AnnualCertificationslt2015.xlsx` covers 1991–2014.
  - `AnnualCertificationsgte2015.xlsx` covers 2015 to the latest year.

  LDEQ updates them quarterly.
- **ERIC reports** at `business.deq.louisiana.gov/Eric/EricReports`:
  - The **radius report** gives one row per release point, with stack parameters and the actual emissions for one pollutant. With `--permitted`, it adds the current TEMPO permitted rates.
  - The **parish report** gives parish totals.
  - The web form offers only the latest 5 years plus Baseline, but both endpoints answer for earlier years too. Release-point sums reconcile exactly with the xlsx for 1995, 2000, 2005, 2010, 2015 and 2018 (AI 1406 NOx). 1993 returned "No results". The script accepts any year from 1991 to the newest.

The two ways agree: for each AI, the release-point sum equals the xlsx annual value to the last digit. For 2024 1,3-butadiene, AI 1406 is 2,663.425859 lb in both, and AI 26336 is 21,463.358929 lb in both.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/ldeq-eric-emissions"
E() { uv run -q --no-project --with openpyxl --with xlrd python -I "$S/eric.py" "$@"; }

E health                                               # sources up, years offered, crosswalk drift
E search "Norco"                                       # AI numbers by ERIC name (ldeq-ai-lookup is primary)
E facility 1406                                        # every year, every pollutant reported
E facility 1406 --years 2015-2024 --pollutants "NOx;1,3-Butadiene;Benzene" --csv eric_1406.csv
E peers 1406 --year 2024 --by naics                    # Louisiana same-NAICS facilities, ranked
E points 26336 --year 2024 --pollutants "1,3-Butadiene" --permitted
E points 1406 --year baseline --pollutants NOx
E radius 30.0016 -90.4097 --radius-m 3000 --pollutant "1,3-Butadiene" --year 2024
E sources 1406 --year 2024 --receptor 29.9850,-90.3800 --strouhal   # low-frequency noise candidates
E sources 30.0016 -90.4097 --radius-m 3000 --category flare --category engine
E parish "St. Charles" --pollutant Benzene --year 2024 # or `parish all`
E reconcile 1406 --year 2024 --pollutant "1,3-Butadiene"
E pollutants lead                                      # name, ERIC code, CAS, LAC table
```

- `--json` goes before or after the subcommand.
- `--refresh` bypasses the cache, which lives under `~/.cache/bayou/ldeq-eric-emissions/`:
  - The xlsx files are re-checked once a day and downloaded again only when LDEQ's `Last-Modified` changes. They are 1.4 MB and 2.0 MB.
  - Radius and parish reports are cached for a day.
- A pollutant can be named by its xlsx name (`Benzene`, `Nitrogen Oxides`), its ERIC form text or abbreviation (`NOx`, `PM2.5`), its ERIC code (`002274`) or its CAS number. Matching is exact. A miss prints candidate names rather than guessing.
- Exit codes: 3 means the AI or year was not found; 5 means a source is unavailable.

## Workflow

1. **Get the AI number** from `ldeq-ai-lookup`. `search` is a fallback: ERIC lists only facilities that report, and names change with owners, so search on a distinctive word.
2. **`facility <AI>`** prints the full history. Read the header before the numbers.
   - **Drift.** Lines marked `** changes across years **` show a changed name, parish, NAICS, SIC or coordinates. Name changes usually mean a sale. NAICS changes move the facility between peer groups (Norco refinery: 424690 until 2018, 324110 from 2019). Parish changes are often a coordinate fix: AI 71 is listed in Livingston for 2016 only.
   - **`2017*`: more than one certification in a year.** 222 AI-years have two rows.
     - **Ownership splits (214).** When a facility changes hands mid-year, each owner certifies its own part of the year, and the table shows the sum. The radius report carries both owners' rows, and its sum matches the merged value (verified on AI 302 for 2022 and AI 289 for 2025).
     - **Duplicates (8).** The two rows have identical values, usually one under the old owner's name and one under the new. These are counted once, because the radius report holds the single value (AI 286, 2018 NOx: 1,961.55 tons, not double).
   - **`—` means a blank cell: not reported.** It is never zero. A reported zero prints as `0`.
   - **`n/c` means not collected.** The year falls outside the span in which any Louisiana facility reported that column, or the column is absent from that era's file:
     - Only in the pre-2015 file (31 columns): total suspended particulate (data 1993–2005), `Ammonia - CRI` in tons (1993–2008), and a set of pesticides and Class I/II compounds.
     - Only in the 2015+ file: `Chromium, Total (as Cr)` (data from 2016) and `Polycyclic Organic Matter (POM)` (data from 2025 only).
     - Several TAP columns begin mid-file, e.g. 1,3-propane sultone in 2013 and o-dianisidine in 2011. Before their first year they print `n/c`, not `—`.
3. **`peers <AI>`** ranks Louisiana facilities with the same primary NAICS (or `--by sic`) in one year, for criteria pollutants and the target's five largest TAPs. Each ranking shows how many cohort members did not report the pollutant. Primary codes are self-assigned: the 2024 NAICS 324110 cohort includes a chemical plant and a coke plant. Read the `cohort` list before calling anything a peer. Before about 2011, some NAICS codes are 5 digits (AI 71: `48621` in 2006–2010, `486210` afterward), so a NAICS cohort for an older year can split in two. Use `--by sic` there.
4. **`points <AI>`** gives release points for the pollutants the AI reported that year. By default it queries criteria pollutants first, then TAPs by mass, up to `--max` 12.
   - **Radius.** The query is centered on the AI's xlsx coordinate and starts at 5 km. When the release-point sum falls short of the xlsx value, it widens to 20 km and then 50 km. If nothing is found even at 50 km, the facility has no coordinates in ERIC (LDEQ says about 19% of facilities have none).
   - **Stack parameters** (height, temperature, diameter, velocity, flow) come from the facility's EIQ.
   - **`--permitted`** adds TEMPO permitted rates. See [Never add these together](#never-add-these-together).
5. **`reconcile <AI> --year Y --pollutant X`** checks the xlsx value against the live radius report for that AI and gives one of these verdicts:
   - exact match;
   - no release points within reach (missing or wrong coordinates);
   - short even at 50 km (release points outside the radius, or a revision);
   - over the xlsx value (the live database has a revision newer than the quarterly file).
6. **`sources <AI | lat lon --radius-m N>`** lists low-frequency noise candidates for infrasound or low-frequency complaints. It runs radius reports for NOx, PM10 and VOC, and keeps the union of release points that are:
   - flares, internal combustion engines, cooling towers, furnaces/boilers or incinerators (by ERIC `Source Type`);
   - or compressors, turbines, fans/blowers or process vents/blowdowns (by description keyword).

   Storage-tank breathing vents, separators and fugitive components are left out.

   There is one row per release point (stack). Sources that share a stack are listed under it, such as barge and ship loading routed to a vapor-recovery flare, or two heaters on one stack. Each row gives release-point lat/lon, height, diameter, exit velocity and exit temperature. Add `--receptor lat,lon` for distance and bearing to a home or recorder.

   - **Coordinates are self-reported.** They are often wrong or copied from the facility centroid. Verify them against the permit plot plan, `satellite-imagery` or `parish-assessor-gis` before stating a distance.
   - **Flare defaults.** Flares showing 65.6 ft/s and 1,832 °F carry the standard flare modeling defaults (20 m/s, 1273 K), not measured exit conditions.
   - **`--strouhal` is judgment.** It adds f ≈ 0.2·V_exit/D, the jet-mixing-noise peak, as an order-of-magnitude estimate. It is not given for flares.
   - **Coverage.** A source that emits none of the three pollutants is invisible here: an electric-drive compressor, a fin-fan cooler, a pump.
   - **Verified on AI 1406 for 2024**, counting release points:
     - 5 flares: coker, HCU, RCCU, the West Ops ground flare, and the marine vapor-recovery flare, which carries 2 loading sources;
     - 10 engines;
     - 3 cooling towers;
     - 7 process vents (coke drums, coker blowdown, catalyst hoppers);
     - 22 fired-heater stacks (F-37 and F-38 share one);
     - 2 incinerators.

   For archived infrasound and seismic spectra near these sources, see `lf-acoustic-baselines`.

## What ERIC is, and what it is not

- **ERIC is self-reported, certified actual emissions.** They are not measured at the fenceline and not modeled. Most are emission-factor or engineering estimates in the facility's own EIQ.
- **Not every facility reports.** Facilities that fall below the LAC 33:III.919 or 5107 applicability thresholds do not report, so a missing AI is not a zero.
- **Timing.**
  - Year N appears in the files in mid to late summer of N+1 (LDEQ's stated lag).
  - Revisions arrive all year, so cite the file's `Last-Modified` date.
  - The script treats a year as complete once it has at least 90% of the prior year's facility count. It labels later years provisional and keeps them out of the `peers` default.
- **Coordinates are NAD83 and are often wrong**, as LDEQ itself says. Do not use ERIC coordinates as the location of a source in a model or a distance claim; take locations from the permit's plot plan or `parish-assessor-gis`.
- **Baseline (`--year baseline`, ReportingYear 1900)** is a legacy EIS snapshot and belongs to no single year.
  - In Baseline, PM10 was reported as TSP.
  - It covers only 35 TAPs and few facilities: Baseline benzene has 2 facilities within 50 km of Norco.
  - It cannot be reconciled against the xlsx, and the parish report does not offer it.
- **Permitted (TEMPO) rows** are the limits in current operating permits on the retrieval date.
  - They have no reporting year.
  - They never include pending applications. For a draft permit, use the application's own EIQ sheets.
- **Units.** Criteria pollutants, ethylene, propylene and butenes are in **tons**; TAPs are in **lb**. The radius report uses the same units as the xlsx.

## Never add these together

- **Permitted rates across `Statistical Basis`.** The bases are Annual maximum (tons/yr), Hourly average (lb/hr) and Hourly maximum (lb/hr). They describe the same emission in different units and averaging times. `points` and `radius` group by basis and print no totals.
- **Permitted rates of a group's members and its cap.** `Group memberships` (e.g. `UNF 00000002`, `CRG 00000014`) ties sources to a group cap. Adding members and caps double counts. Report the cap.
- **`Lead - tons` (criteria) and `Lead compounds - lb` (Table 51.3 TAP).** These are separate inventories.
  - `Lead (and compounds)` (002574) is the TAP; it reconciles to `Lead compounds - lb` (2024).
  - `Lead (Pb)` (002573) is the criteria column; it reconciles to `Lead - tons` (AI 3401, 2010). The radius form offers `Lead (Pb)` only before 2021 and in Baseline. No facility reported a positive `Lead - tons` value in 2019 or 2022.
- **`Ammonia - CRI - tons` (pre-2015 criteria-era reporting) and `Ammonia - lb` (TAP).** These are the same two-inventory problem as lead.
- **ERIC and NEI or TRI values for the same facility.** Report them side by side and label the program.

## `pollutants.csv`: the crosswalk

It has one row per xlsx column, plus rows for pollutants that exist only in the radius report: 1-bromopropane, coke oven emissions, HRVOCs, condensable and filterable PM, and others. The columns are:

- **`eric_code` / `eric_code_baseline`.** These are the radius-report codes. Hydrogen fluoride, for example, is `002539` in 2021 and later but `000034` in Baseline. For other years, the script checks that year's dropdown and uses whichever of the two codes it offers. Before 2021, lead and TSP use `002573` and `001810`.
- **`cas` and `lac33_table`.** These come from LAC 33:III Tables 51.1–51.3 (33v03.docx, revised 2026-04-28).
- **`cas_kind`:**
  - `compound`: the CAS number identifies the substance.
  - `element+compounds`: the element's CAS number stands for "X and compounds".
  - `category-representative`: a single CAS number stands for a category: glycol ethers (109-86-4 in 51.1, 112-35-6 in 51.3), PAHs (206-44-0), naphthalene with methylnaphthalenes, lindane (all isomers), and "salts and esters". `--pollutants "Glycol ethers"` is ambiguous on purpose; name the table, as in `Glycol ethers (Table 51_3)`.
- **`match`:**
  - `exact`: the names agree after normalization.
  - `hand`: a known synonym, e.g. 1,3-Dichloropropene ↔ 1,3-Dichloropropylene, Hydrofluoric acid ↔ Hydrogen fluoride, Iodomethane ↔ Methyl iodide, 4-Aminodiphenyl ↔ 4-Aminobiphenyl.
  - `-reconciled`: the release-point sum matched the xlsx exactly. This covers NOx, PM10 and PM2.5 (the "Primary" codes, not "Filterable"), butenes, both glycol-ether rows, lead, lead compounds and 1,3-butadiene.
  - `eric-only`: the pollutant exists only in the radius report.
- **Flagged gaps:**
  - `Ammonia - CRI - tons` (pre-2015) has no radius-report code.
  - `Chromium, Total` and `POM` are not in LAC 33:III Table 51 and carry no CAS number.

`health` compares the live xlsx headers and every year's pollutant dropdown against this file. When it reports drift (POM first appeared in the 2025 dropdown, for example), add the row by hand and take the CAS number from the LAC table, not from memory.

## Comparing with TRI and NEI

- **TRI (`epa-tri-search`, `tri-release-report`).**
  - **Which numbers to compare.** Compare ERIC TAPs with TRI *air* releases only: fugitive (5.1) plus stack (5.2). Use the same year and join on CAS.
  - **Linking the IDs.** Find the TRIFID for an AI through `epa-frs-crosswalk`, using the LA-TEMPO program ID, which equals the AI number (FRS LA-TEMPO 3483 is AI 3483, Air Liquide Norco).
  - **Category rows.** Rows with `cas_kind` = `element+compounds` or `category-representative` cannot be joined on CAS: TRI reports metal compounds and chemical categories under N-codes. Match those by hand against the TRI chemical list.
  - **Gaps are leads, not proof.** The two programs differ in thresholds, chemical lists and estimation methods. A gap is a lead to raise in a comment or records request, never proof of misreporting.
- **NEI (`comparable-facilities`).**
  - NEI is triennial and ends at 2020 in the ECHO file. ERIC is annual through the latest year.
  - Use `peers` and `facility` alongside NEI and never merge the two.
  - LDEQ submits its point-source inventory to NEI, so a large difference for the same year usually points to a revision or to EPA gap-filling. Check both before treating it as a finding.

## Records requests

Some data is not in the public reports:
- release-point detail for years the radius endpoint does not return (before about 1995);
- the EIQ submissions behind a number;
- the facility's emission-estimate calculations.

Request them through `la-public-records-request` using LDEQ's form (https://edms.deq.louisiana.gov/prr/RequestForm.aspx). Name the AI, the years, and "ERIC emissions inventory submittals and supporting calculations". Questions about the data go to ERIC@la.gov.

## Citation format

> LDEQ ERIC, AnnualCertificationsgte2015.xlsx (Last-Modified 2026-06-30), AI 1406, 2024, 1,3-butadiene 2,663.425859 lb. Retrieved 2026-10-16.

> LDEQ ERIC Radius Report (ReportType=Actual, ReportingYear=2024, PollutantCode=002274, 29.99556, −90.40972, radius 5,000 m), AI 26336, 36 release points. Retrieved 2026-10-16.

Every command prints the source file with its `Last-Modified`, or the radius parameters, together with the retrieval date. Carry both into the citation.
