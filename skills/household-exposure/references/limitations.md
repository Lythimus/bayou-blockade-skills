# Limitations

What the figures can and cannot support. Read this before quoting a number from a household
report, and carry the relevant limit with the number wherever it goes.

## What every figure is

A **modeled outdoor air concentration at the home**, turned into a screening cancer risk or a
hazard quotient with EPA's chronic toxicity values. It is never:

- a measurement of the air at the home;
- an indoor concentration, or an amount anyone breathed in or absorbed;
- evidence that a facility caused a particular person's illness;
- a prediction that a person will or will not get sick.

A **cancer risk** is an upper-bound added lifetime chance attributed to the modeled sources.
A **hazard quotient** is a ratio to EPA's reference level, not a probability; 2 does not mean
twice the chance of harm. Chemicals are never added together by weight.

Everyone is treated as being at the home, outdoors, every day of each residence period.

## Past exposure (the screening tier, RSEI)

- **EPA's own limit.** RSEI microdata "cannot solely be used to determine actual
  on-the-ground exposures or health risks at any given point." EPA built it for screening
  comparisons and trends. The report quotes this sentence; do not drop it.
- **A floor, not a total.** Only releases reported to the Toxics Release Inventory are in it.
  Plants under the reporting threshold, vehicles, ships, trains, flares outside TRI
  reporting and every non-TRI source are absent.
- **Unknown years stay unknown.** RSEI covers 1988 through 2022. A year outside that range,
  a year left out of a run, or a year in which a facility filed nothing has no figure. It is
  not zero and is not filled from a neighboring year. A total with missing years is a floor
  for the years covered; the report says how many years it covers.
- **The grid is coarse.** Each figure is for an 810 m cell. RSEI puts every facility at the
  center of its own cell, interpolates that cell from 441 points within a kilometre, and
  beyond that calculates a point only every 5 km and interpolates between. A home next to a
  plant can be far from its cell's figure in either direction.
- **Model versions differ.** 1988-2014, 2015-2017, 2018-2019 and 2020-2022 come from four
  RSEI versions. Sums over a residence are reported. A change between two years on either
  side of a version boundary is not evidence of a real change.
- **Chemicals with no cancer figure are not safe by default.** The report lists three groups
  separately. Some are in EPA's table with no inhalation unit risk, and that group includes
  known carcinogens: nickel, cobalt and lead compounds add nothing to the cancer sum. Some
  are reported to TRI as a group (dioxins, polycyclic aromatic compounds, glycol ethers);
  EPA has values for individual members, several of them among its most potent, but the
  group report does not say which were released, so none is applied and the cancer sum is
  too low by an unknown amount. The rest have no value in the table.
- **Metals.** Chromium is taken as the hexavalent share RSEI models; mercury compounds take
  the elemental mercury value. Both are stated as assumptions in the report.

## Neighborhood context (AirToxScreen)

One year (2020), every source type at once, for the home's census block, as if that year's
air were breathed for 70 years. It is a different model with a different purpose. It is
shown beside the RSEI figures and never added to them. EPA rounds the block total to one
significant figure, so it does not equal the sum of its source groups.

## A proposed facility (the dispersion tier, AERMOD)

- **The facility alone.** The figure is the proposed facility's contribution. Existing
  plants, traffic and background air are not in it.
- **Permitted is a ceiling.** The permitted scenario uses the maximum the permit would
  allow. An expected-operation scenario appears only when the application documents the
  operating assumption behind it.
- **No input, no number.** A missing stack parameter, emission rate, meteorology file or
  coordinate system produces a gap line and a records-request item. Nothing is filled in
  with a typical value, and no distance-based shortcut is used.
- **Operating schedule.** Annual totals are spread evenly over the year. Any hourly schedule
  in the applicant's model is left out.
- **The future is assumed.** How long the plant runs and how long each person stays are
  inputs someone chose. They are printed as assumptions. A permit's expiry date is not a
  closure date.
- **Checked against EPA's test cases, not against a Louisiana application.** The local build
  reproduces EPA's published AERMOD results. The rerun path has been exercised only with
  EPA's cases standing in for an applicant's files. Capped and horizontal stacks are
  accepted but unverified.
- **Identical rates look like a unit-rate run.** When every source in an applicant's input
  carries the same emission rate, its plot files are refused as a chemical's concentration
  and the rerun times the entered rates is used instead.
- **Short-term standards.** Louisiana's standards for chloroprene, ammonia, hydrogen cyanide
  and toluene are 8-hour averages. An applicant's run for those is a short-term peak and is
  listed as context only.

## Why past and proposed are not added

The past figure is a floor (reported releases, coarse grid, years with data). The proposed
figure is a ceiling (permitted maximum, at the home's point, years that have not happened).
Their sum is neither, so the report shows them side by side and gives no combined total.

## Not assessed

Drinking water, indoor air, time away from home, accidents and upsets, chemicals formed in
the air after release, sources beyond 50 km, soil, dust, food and skin contact. Distance to
a water discharge says nothing about tap water; the report carries a short checklist for
following that up separately. For that follow-up, find the system that serves the address
(`bayou:ldh-drinking-water` `systems --parish`), then run `violations` and `samples` on its
PWSID, and `downstream` from the discharge to see whether that system's intake is below it.

## The public version

`report --public` leaves out the address, coordinates, grid cell, census block, every
distance, birth years, move-in and move-out dates within a year, the list of facilities
searched, AirToxScreen's breakdown by source group, and the distance to and exact value at
the applicant's nearest receptor. It rounds figures to two significant digits and names the
census tract. Three limits remain:

- The figures still depend on where the home is. Someone holding EPA's full RSEI microdata
  could match a table of chemical concentrations to an 810 m cell. If that matters, share
  the summary and charts and hold back `exposure.csv` and `results.json`.
- A proposed-facility figure marked "applicant output" is the value the applicant filed at
  a receptor within 100 m of the home. The applicant's receptor file is a public record, so
  on a sparse receptor grid that value can point to one receptor. The public report says
  when this path was used.
- The tool cannot see what the household's label, member IDs or the proposed facility's
  name give away. Read the public report before it leaves the household's hands.
