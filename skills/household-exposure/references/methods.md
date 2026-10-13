# Methods

How the skill turns annual concentrations at a home into exposure and risk figures. The code
is `scripts/exposure.py`; the two examples at the end were worked by hand and
`scripts/selfcheck.py` holds the code to them.

## What is being measured

The quantity is the **modeled outdoor air concentration at the home**, in micrograms per cubic
metre (µg/m³), as an annual average, for one chemical from one source. It is not a measured
concentration, not an indoor concentration and not an absorbed dose. Time away from home,
indoor air, water, soil and food are outside the calculation.

## Time at the home

Each household member has one or more residence periods with a start date and an end date.
A bare year means the whole year. A missing end date means the person still lives there and
the period closes on the assessment's `as_of` date.

Time is counted in days and expressed as a fraction of each calendar year: days at home in
year Y divided by the days in Y. A leap year has 366 days and still counts as one year.

A source that runs for a fixed span (a proposed facility with an operating horizon) has an
operating window. Days at home outside the window are counted as known zero exposure from
that source. Historical RSEI values are not windowed, because each annual value already
reflects the months the facility operated.

**History stops today; the future is an assumption.** For past exposure an open-ended
residence closes on `as_of`. A proposed facility has not started, so assessing it needs a
stated assumption about how long each person stays: `projected_end`, either a date or
`operating_end` (for as long as the facility runs). It is required whenever a proposed
facility is assessed and is printed in the report as an assumption. Without it a plant that
opens next year would show zero exposure for everyone living there now.

## Unknown years

A year with no concentration is **unknown**. It is never set to zero and never filled from a
neighboring year. Three consequences:

- The **residence integral** sums only the years with evidence: Σ concentration × years at
  home, in µg/m³·yr.
- The **period average** divides that integral by the years with evidence, not by all
  residence years. Dividing by all years would treat every unknown year as clean air.
- The **evidence fraction** is years with evidence ÷ residence years. Any risk figure with an
  evidence fraction below 1 is a floor for the years covered, not an estimate for the whole
  residence.

When several facilities emit the same chemical, their annual values are added. A year in
which some facilities have a value and others do not is kept as the sum of the known ones and
flagged partial.

**Screening tier: what a missing RSEI row means.** RSEI has a row only where a facility
reported an air release to TRI. For a year that was read, a facility that appears in other
years and has no row is:

- a **known zero** when the TRI file for that year shows it filed a full report (Form R) for
  the chemical with no release to air;
- **unknown** when it filed nothing for the chemical, since a plant below TRI's reporting
  threshold still emits, or when the TRI file is not on hand (`prepare --facilities` fetches
  them);
- **unknown** when it filed an air release that RSEI did not model.

A year RSEI does not cover (before 1988, after 2022) or that was left out of a run is
unknown for every source.

**The grid.** RSEI's concentration is for an 810 m cell, not a point. The value for the
home's cell is used; the lowest and highest of the nine cells around it are kept in
`screen.csv` to show how much the figure depends on which side of a cell edge the home is.

## Cancer risk

    risk = unit risk × (residence integral ÷ 70 years)

The unit risk is EPA's inhalation unit risk estimate, the upper-bound excess lifetime cancer
risk per µg/m³ breathed continuously for a 70-year lifetime. The result is an upper-bound
probability attributable to the modeled sources. It is not a prediction that a person will or
will not develop cancer.

**Early-life adjustment.** For chemicals EPA marks as acting by a mutagenic mode of action
(`M` or `m-rpf` in Table 1), exposure before age 16 counts more: a factor of 10 from birth to
the second birthday and 3 from the second to the sixteenth birthday (EPA 2005 Supplemental
Guidance). Each day at home is weighted by the factor for the person's age that day:

    adjusted risk = unit risk × (Σ concentration × years × age factor) ÷ 70

- The adjustment is applied only when a birth year is given. Without one, the unadjusted
  figure is reported with a note that it understates risk for anyone who was under 16.
- Only the birth year is collected. The birthday is taken as 1 July of that year, which puts
  the age thresholds within six months of the truth.
- **Trichloroethylene:** the factors apply only to the kidney-cancer share of the unit risk
  (1.0 × 10⁻⁶ of 4.1 × 10⁻⁶ per µg/m³), per EPA's Table 1 note 2. For constant exposure over
  a full lifetime this reproduces EPA's stated adjusted value of 4.8 × 10⁻⁶.
- EPA's notes page prints that 4.8 × 10⁻⁶ figure, and the vinyl chloride adult value below,
  as "per mg/m³". They match Table 1 only as per µg/m³, the unit of the table's column, and
  the code treats them that way.
- **Vinyl chloride:** not flagged, because the table's value already covers exposure from
  birth (Table 1 note 13). For exposure that began in adulthood it overstates risk by up to a
  factor of two; the report says so.

## Noncancer hazard

    hazard quotient = average concentration while exposed ÷ reference concentration

The average is taken over the time the source was running and the person was home, with
evidence. Years at the home before a plant opened or after it closed are left out: counting
them would let a long residence dilute a real exceedance (two years at twice the reference
value inside a 40-year residence is a hazard quotient of 2, not 0.1). Cancer risk is treated
the other way on purpose, spread over a 70-year lifetime. The highest single year's quotient
is reported beside it.

The reference concentration is EPA's chronic inhalation value from Table 1, converted from
mg/m³ to µg/m³ in one place (`toxvalues.py`). A hazard quotient is a ratio. It is not a
probability, and a value of 2 does not mean twice the chance of harm. Below 1, effects are
not expected; above 1, the margin built into the reference value is being used up.

## Totals

- **Chemicals are never added by mass.** A microgram of ethylene oxide and a microgram of
  toluene are not the same exposure.
- **Total cancer risk** is the sum of the per-chemical risks, EPA's default for screening.
- **Hazard index** is the sum of hazard quotients for chemicals that affect the same target
  organ. Table 1 carries no organ assignments; they come from EPA's AirToxScreen 2020
  pollutant list (`references/airtoxscreen-2020-target-organs.csv`). A chemical flagged for
  two organs counts in both. A chemical with a reference concentration and no organ flag is
  listed as unassigned and is in no index.
- A chemical with no unit risk or no reference concentration is listed as **unquantified**.
  It is not counted as zero.

## Toxicity values

EPA OAQPS Table 1, "Prioritized Chronic Dose-Response Values," dated 2021-09-29, vendored as
`references/oaqps-table1-2021-09-29.csv` (227 chemicals). A zero in EPA's spreadsheet means
no value was derived and is stored as blank. Source and notes URLs are in `toxvalues.py` and
are written to each run's manifest.

**Metals and chemical groups.** TRI reports many metals as categories ("lead compounds").
Table 1 files most of them under the element's CAS number, and
`references/tri-category-map.csv` records each pairing with its reason. Two carry an
assumption that the report states: mercury compounds take the elemental mercury value, and
RSEI's chromium concentration is taken to be the hexavalent share RSEI estimates from the
facility's industry, so it takes the chromium (VI) values as it stands. Groups with no single
Table 1 value (polycyclic aromatic compounds, diisocyanates, glycol ethers) are unquantified.

## Worked example 1: benzene, a partial year and an unknown year

One person lives at the home from 1 July 2010 through 31 December 2012. Modeled benzene is
0.4 µg/m³ in 2010, has no value for 2011, and is 0.6 µg/m³ in 2012. No birth year is given.
Benzene: unit risk 7.8 × 10⁻⁶ per µg/m³, reference concentration 0.03 mg/m³ = 30 µg/m³, not
flagged mutagenic.

| Year | Days at home | Fraction of year | Concentration | Contribution |
|---|---|---|---|---|
| 2010 | 184 of 365 | 0.5041 | 0.4 | 0.2016 |
| 2011 | 365 of 365 | 1.0000 | unknown | none |
| 2012 | 366 of 366 | 1.0000 | 0.6 | 0.6000 |

- Residence years: 0.5041 + 1 + 1 = 2.5041
- Years with evidence: 0.5041 + 1 = 1.5041
- Evidence fraction: 1.5041 ÷ 2.5041 = 0.601
- Residence integral: 0.2016 + 0.6000 = 0.8016 µg/m³·yr
- Period average: 0.8016 ÷ 1.5041 = 0.5330 µg/m³
- Cancer risk: 7.8 × 10⁻⁶ × 0.8016 ÷ 70 = 8.93 × 10⁻⁸ (about 0.09 in a million), a floor
  because 2011 is unknown
- Hazard quotient: 0.5330 ÷ 30 = 0.0178 (highest year: 0.6 ÷ 30 = 0.02)

## Worked example 2: chloroprene across both age thresholds

A child born in 2010 (birthday taken as 1 July 2010) lives at the home from 1 January 2011
through 31 December 2027. Modeled chloroprene is 0.2 µg/m³ every year. Chloroprene: unit risk
3 × 10⁻⁴ per µg/m³, flagged `M`, reference concentration 0.02 mg/m³ = 20 µg/m³.

The second birthday is 1 July 2012 and the sixteenth is 1 July 2026.

| Age band | Dates | Years | Factor | Years × factor |
|---|---|---|---|---|
| Under 2 | 1 Jan 2011 to 30 Jun 2012 | 1 + 182/366 = 1.4973 | 10 | 14.9727 |
| 2 to 16 | 1 Jul 2012 to 30 Jun 2026 | 184/366 + 13 + 181/365 = 13.9986 | 3 | 41.9959 |
| 16 and over | 1 Jul 2026 to 31 Dec 2027 | 184/365 + 1 = 1.5041 | 1 | 1.5041 |
| Total | | 17.0000 | | 58.4727 |

- Residence integral: 0.2 × 17.0000 = 3.4000 µg/m³·yr
- Age-weighted integral: 0.2 × 58.4727 = 11.6945 µg/m³·yr
- Unadjusted cancer risk: 3 × 10⁻⁴ × 3.4000 ÷ 70 = 1.46 × 10⁻⁵ (about 15 in a million)
- Age-adjusted cancer risk: 3 × 10⁻⁴ × 11.6945 ÷ 70 = 5.01 × 10⁻⁵ (about 50 in a million)
- Hazard quotient: 0.2 ÷ 20 = 0.0100

The same exposure with no birth year on file reports the unadjusted figure and a note that
early-life factors were not applied.

## Sources

- EPA, Dose-Response Assessment for Assessing Health Risks Associated With Exposure to
  Hazardous Air Pollutants: `https://www.epa.gov/fera/dose-response-assessment-tables`
- EPA, Additional Information, Adjustments and Special Cases for Dose-Response Values in
  Tables 1 and 2 (notes 2, 3 and 13):
  `https://www.epa.gov/fera/additional-information-adjustments-and-special-cases-dose-response-values-tables-1-and-2`
- EPA (2005), Supplemental Guidance for Assessing Susceptibility from Early-Life Exposure to
  Carcinogens, EPA/630/R-03/003F.
