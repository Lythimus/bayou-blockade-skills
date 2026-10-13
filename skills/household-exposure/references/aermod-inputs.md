# Dispersion inputs for `hx.py model`

What to collect from a Louisiana air permit application, how to hand it to `model`, and what
`model` does with each piece. `model` never fills a missing input with a typical value: it
writes the gap to `model-gaps.md` and gives no number for whatever depended on it.

## Before the first run

```
bash $HX/aermod_build.sh          # builds EPA's AERMOD v26135; needs gfortran (brew install gcc)
uv run -q --no-project --with matplotlib python -I $HX/hx.py model --check-build
```

`--check-build` reruns three of EPA's published test cases and a zero-rate and double-rate
check. Do not use a build that fails it. Details are in `data-sources.md`.

## Files to look for in the application

Search EDMS under the facility's Agency Interest number (`bayou:ldeq-edms-search`,
`bayou:ldeq-edms-download`). Modeling files are usually a compressed archive attached to the
application or to the modeling report, or sit on a disc named in the document index.

| File | Often named | Used for |
|---|---|---|
| AERMOD input | `.inp`, `.ami`, `.adi`, `.dta` | `--applicant-inp`: sources, buildings, receptors, options |
| Files it includes | `.rou`, `.sou`, `.dat`, `.rec` | Read automatically when they sit in the input's directory |
| Surface and profile meteorology | `.sfc`, `.pfl` | `--sfc`, `--pfl`, or found beside the input by name |
| Plot files | `.plt`, `.pst`, `.grf` | `--applicant-plot CAS=FILE` |
| Main output | `.out`, `.lst`, `.amo`, `.ado` | `--applicant-out`: states the output units |
| Building downwash (BPIP) | `.bpi`, `.pro`, `.sum` | Not read; the downwash values are already in the input |
| Modeling report or protocol | PDF | Coordinate zone and datum, tower base elevation, which run covers which pollutant |
| Emission inventory questionnaire sheets | PDF | Stack parameters and per-source rates for the two tables below |

Extensions depend on the software the consultant used; identify a file by its content. An
input starts with `CO STARTING`; a plot file's header starts with `* AERMOD`.

Keep the applicant's files in their own directory outside the plugin. They are read as data
and never executed; an include that points outside the input's directory is refused.

If a file was not filed electronically, `model-gaps.md` ends with a "Records to request" list
worded for `bayou:la-public-records-request`.

## The two tables

Both live in the proposed facility's directory named in `assessment.json`, or in its
`verification/` subdirectory. Copy them from `templates/`. Rows whose first cell starts with
`<` are the template's placeholders and are ignored. Every row needs `source_doc` and `page`;
a row without them is refused. Run scanned tables through `bayou:document-ocr`, read the
numbers against the page image, and set `ocr_verified` to `yes` only after that.

### `source-emissions.csv`: one row per emission point per chemical

| Column | Rule |
|---|---|
| `source_id` | The emission point's ID. For a rerun it must equal the source ID in the applicant's AERMOD input; for an inventory run, the ID in `source-inventory.csv`. Case is ignored. |
| `chemical`, `cas` | CAS number preferred; the name is used when `cas` is blank. |
| `amount`, `unit` | `tpy`, `lb/yr`, `lb/hr`, `g/s` and the other units `permit-analysis`'s `proposed-emissions.csv` accepts. An unknown unit is refused. |
| `hours` | Hours per year for a `lb/hr` rate, when the application states them. Blank means 8,760, which is listed as an assumption. |
| `basis` | `PTE`, `allowable`, `permitted` or `potential` put the row in the **permitted** scenario. `expected`, `actual` or `projected` put it in the **expected** scenario. Anything else is refused. |
| `assumption` | Required for an expected rate: the operating assumption it rests on, with where the application states it. |
| `status` | `new`, `modified`, `removed` or blank. A `removed` row is subtracted, so a modification is the change, not the new unit stacked on the old one. |

A chemical that appears only in `proposed-emissions.csv` as a facility-wide total gets no
number: nothing says which stack it leaves from. Enter a split only if the application
documents one.

### `source-inventory.csv`: one row per stack (inventory runs only)

Coordinates are either `lat` and `lon` in decimal degrees, or `utm_zone`, `utm_e_m`, `utm_n_m`
with `datum` NAD83 or WGS84 in the same zone as the home. NAD27 coordinates are refused;
convert them with NOAA's NCAT tool first. Height and diameter take `m`, `ft` or `in`;
temperature `K`, `C` or `F`; velocity `m/s`, `ft/s` or `ft/min`. A blank or implausible value
is named in the gap list.

Only stacks (AERMOD point sources) can be entered. If one emission point is incomplete, or
`source-emissions.csv` names a point the inventory lacks, no run is built: a facility total
missing one stack is wrong by an unknown amount.

## Which path runs

`model` uses the first of these that its inputs support, chemical by chemical.

1. **Applicant's output.** `--applicant-plot CAS=FILE` names a plot file from a run in which
   the applicant modeled that chemical at its own rates. It is used only if all three hold:
   it has `ANNUAL` or `PERIOD` averaging, it covers a single source group, and a receptor in
   it lies within 100 m of the home (`--max-receptor-m`). A 1-hour, 8-hour or 24-hour file is
   listed as short-term context and never enters the exposure figures.
   Look first in the application's toxic air pollutant modeling. Louisiana's ambient air
   standards (LAC 33:III.5112, Table 51.2) are annual averages for about a third of the
   listed pollutants, among them benzene, ethylene oxide, formaldehyde, 1,3-butadiene and
   vinyl chloride, so an applicant showing compliance for one of those files an annual run.
   The rest have 8-hour standards (chloroprene, ammonia, hydrogen cyanide, toluene and
   others), and their filed runs cannot be used here; neither can the 1-hour and 24-hour
   runs filed for criteria pollutants.
   **Confirm from the modeling report that the run used that chemical's own emission rates.**
   Consultants often model every source at 1 g/s and scale by chemical in a spreadsheet; a
   plot file from such a run is not a concentration of anything. When the input is also
   given, `model` treats every source carrying one identical rate (or a lone source at
   1 g/s) as such a run and does not use the plot files directly; rates times the rerun
   apply instead. With the plot file alone it cannot tell, and says so in the assumptions.
2. **Applicant's input, rerun.** `--applicant-inp FILE`. The input is rewritten to give each
   source a unit emission rate and its own source group, with one receptor at the home, and run
   for the whole meteorological record. Each chemical's concentration is the sum over sources
   of its rate times that source's unit result.
3. **Built from `source-inventory.csv`.** Used when no applicant input is given (or the one
   given cannot be read) and the inventory is complete. Needs `--sfc`, `--pfl` and
   `--profbase-m`. Flat terrain, no building downwash, rural dispersion unless `--urban-pop`.
4. **No number.** `model.json`, `model.csv` and `model-gaps.md` are still written, with the
   gaps and the records to request.

When a chemical has both a path 1 result and a rate-times-rerun result and they differ by more
than 25%, the applicant's result is used and a gap line reports both: the rates entered are
not the ones the applicant modeled.

## Flags

| Flag | When it is needed |
|---|---|
| `--out DIR` | Always. The directory `prepare` wrote; never inside the plugin. |
| `--proposed NAME` | When `assessment.json` lists more than one proposed facility. |
| `--applicant-plot CAS=FILE` | Path 1, and the check on path 2. Repeatable. |
| `--applicant-inp FILE` | Path 2. |
| `--applicant-out FILE` | Confirms the applicant's plot files are in µg/m³ when no input is given. A file stating other units blocks path 1. |
| `--utm-zone N --datum NAD83` | Whenever applicant files are used: the zone and datum of the applicant's coordinates, from the modeling report. The home is projected into them. Louisiana is zone 15 west of 90° W and zone 16 east of it; an applicant near the line may use either. |
| `--home-xy X,Y` | Instead of zone and datum, when the applicant used NAD27 or a local grid and the home has been converted by hand. |
| `--home-elev M` | Path 2 with elevated terrain, when no filed receptor lies within 500 m of the home to lend its terrain height. |
| `--sfc FILE --pfl FILE` | Meteorology. Always given as a pair; a path that does not exist stops the run. |
| `--profbase-m M` | Path 3: base elevation of the meteorological tower, from the modeling protocol. |
| `--urban-pop N` | Path 3, only if the application's modeling used the urban option. |
| `--max-receptor-m M` | To change the 100 m limit in path 1. State the reason in the report. |
| `--check-build` | Verifies the local AERMOD and exits. |

Meteorology is looked for in this order: the `--sfc`/`--pfl` pair; the paths on the input's
`SURFFILE` and `PROFFILE` lines, relative to the input's directory; the same file names
directly beside the input (filed inputs often carry the modeler's own drive path). If none is
found, nothing is run.

If the zone or datum is wrong the home lands far from the plant. A home more than 50 km from
any source in the coordinates given stops the run with a gap line.

## What the rerun keeps and changes

Kept from the applicant's input: source locations and parameters, building downwash values,
polygon vertices, urban option and urban source list, flagpole height, the non-default
low-wind and downwash options, the meteorology lines including the date range, and regulatory
or non-regulatory model options not listed below.

Changed or left out:

- Averaging becomes `PERIOD`; the pollutant becomes `OTHER`, which turns off the special
  averaging and chemistry rules AERMOD applies to SO2, NO2 and PM by name.
- Emission rates become 1,000 g/s (1,000 g/s spread over the area for area-type sources).
  Results are divided by 1,000. AERMOD prints five decimals, and at 1 g/s distant sources
  would lose most of their digits.
- Operating-schedule factors (`EMISFACT`) are left out. Rates in `source-emissions.csv` are
  annual totals, and keeping the schedule would scale them a second time. The effect is that
  emissions confined to certain hours are averaged over all hours' weather. This is listed
  as an assumption whenever the applicant's input had such factors.
- Background concentrations, deposition, plume depletion, NO2 chemistry options, and the
  screening and sampling options are left out. Each is named under "left out of the
  applicant's input" in the run's assumptions.
- The applicant's receptors are replaced by the home, plus the nearest receptor of each
  long-term plot file given, which is used for the check below.
- Every output path is replaced. The run writes only inside `<out>/model/run-NN/`.

Sources that get no number, each with a gap line:

- types `RLINE`, `RLINEXT`, `BUOYLINE` and `SWPOINT`, whose inputs were not verified here;
- any source driven by an hourly emission file (`HOUREMIS`), because the file changes the
  rate and often the exit conditions hour by hour;
- a source with no parameter line or a zero emitting area.

A chemical emitted from any such source gets no number at all; a partial sum would read as the
facility's total.

Supported, with the unit-rate method checked against EPA's results: `POINT`, `VOLUME`, `AREA`,
`AREACIRC`, `AREAPOLY`, `OPENPIT`, `LINE`. Capped and horizontal stacks (`POINTCAP`,
`POINTHOR`) are accepted because they take the same parameters as `POINT`, but EPA's test
cases contain none, so they were not checked separately.

## Checking a rerun against what was filed

When a long-term plot file is given along with the input, `model` multiplies the rerun's unit
results by the rates in the applicant's own input and compares the sum with the filed value
at the same receptor. A ratio near 1.000 shows the meteorology, included files and this AERMOD
version reproduce the filing. A ratio far from 1 usually means different meteorology, an
operating schedule in the filed run, or a plot file from a different run than the input.

With no long-term plot file there is no such check, and the assumptions say so. Reproducing a
short-term design value from the applicant's output is not automated; to do it by hand, run
the applicant's input unchanged with the local build and compare the summary tables.

A filed run made with an older AERMOD version is expected to differ slightly from a rerun with
v26135. `model.json` records both versions.

## What comes out

- `model.json`: per scenario, each chemical's concentration at the home in µg/m³, the path
  that produced it, the split by source, and each household member's cancer risk and hazard
  index over the facility's operating window; plus assumptions, checks, gaps, limitations and
  the AERMOD build stamp.
- `model.csv`: scenario × chemical × source.
- `model-gaps.md`: the checklist of missing inputs and the records to request.
- `<out>/model/run-NN/`: the input written, AERMOD's output and the plot files, for review.

`model.json` holds the home's position in the applicant's coordinates and its distance from
each source. Treat it as private.
