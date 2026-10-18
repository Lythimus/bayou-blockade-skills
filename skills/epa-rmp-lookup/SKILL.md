---
name: epa-rmp-lookup
description: EPA Risk Management Program (Clean Air Act 112(r)) records for a facility — the regulated toxic and flammable substances it holds and how much, by process; program levels; prevention-program details (PHA dates and techniques, hazards, controls, mitigation, detection); emergency-response setup and coordinating agency; the executive summary; every submission since 1999; and an all-time, deduplicated accident history (deaths, injuries, evacuations, shelter-in-place, damage, causes). Also finds RMP facilities by name or within a radius of a home or school, and bridges an RMP facility to its FRS registry and other program IDs. States plainly that worst-case scenario (OCA) data is reading-room only. Use for siting and emergency-safety comments, "no significant risk" rebuttals, chemical inventories near receptors, and comparing self-reported accidents against NRC and CSB records.
argument-hint: search "<name>" [--state LA] | near <lat> <lon> --radius-km N | facility <EPAFacilityID> | accidents <EPAFacilityID> | summary <id> | crosswalk <EPAFacilityID> | oca | health
allowed-tools: Bash, Read, WebFetch, WebSearch
---

# EPA RMP lookup

A facility that holds more than a threshold quantity of a listed toxic or flammable substance in one process must file a Risk Management Plan with EPA (40 CFR Part 68) and update it at least every 5 years. In Louisiana, LDEQ runs the delegated program under LAC 33:III Chapter 59.

EPA no longer publishes RMP data online: its RMP Public Data Tool is offline pending the 2026 rulemaking. This skill reads the **Data Liberation Project's FOIA'd copy of the full EPA RMP database**, which DLP publishes as static JSON at [data-liberation-project.github.io/epa-rmp-viewer](https://data-liberation-project.github.io/epa-rmp-viewer/). No key, login, or bulk download is needed.

- **Coverage.** All 21,814 facilities that have ever filed, in 56 states and territories, and every submission from 1999 on. Louisiana has 540 facilities, 310 of them not deregistered.
- **Vintage.** DLP refreshes the data when EPA answers its FOIA requests: 2023-07, 2023-11, 2024-01, 2024-04, 2024-07, 2025-01, 2025-04 and 2026-01. The newest validation date in the Louisiana file is 2025-12-30. A facility that first registered, or a submission validated, after EPA's last release is **missing**. `health` prints the current vintage; cite it.
- **License.** CC BY-SA 4.0. Credit "EPA RMP database via the Data Liberation Project (FOIA)".

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/epa-rmp-lookup"
R() { uv run -q --no-project python -I "$S/rmp.py" "$@"; }

R health                                         # sources up, data vintage
R search "Norco"                                 # name, previous names, address, city
R search "Shell" --state LA,TX --include-dereg   # deregistered facilities too
R near 29.9955 -90.4099 --radius-km 5            # facilities around a home or school
R facility 100000026009                          # the full profile from the latest submission
R facility 100000026009 --submission 1000038236  # a past submission
R accidents 100000026009 --csv shell_rmp_acc.csv # every accident, all submissions
R summary 100000026009                           # executive summary text
R crosswalk 100000026009                         # FRS registry and every program ID
R oca                                            # how to reach worst-case scenario data
```

- `--json` goes before or after the subcommand, and `--refresh` bypasses the cache.
- The cache lives under `~/.cache/bayou/epa-rmp-lookup/`. State files, facility indexes and code lookups are kept 7 days. Submissions are kept indefinitely, because a validated submission never changes.
- Exit codes: 3 means the ID was not found; 5 means a source is unavailable.

## Workflow

1. **Find the facility.**
   - `search` matches every word against the current name, previous names, address and city.
   - RMP names are the operator's own and change with owners: Shell's Norco refinery is "Equilon Enterprises LLC dba Shell-NORCO LA REFINER", formerly four Motiva names. Search a distinctive word.
   - One industrial complex often files several RMPs: Shell Norco has a refinery plus East and West chemical plant sites. List all of them with `near` on the complex's coordinates.
   - For a proposed facility there is no RMP yet. Use `near` to list the existing RMP facilities around the site or the receptors.
2. **`facility <EPAFacilityID>`.** Read it in this order:
   - **Header.**
     - Submission type and reason, and the 5-year update due date. An overdue update is itself a compliance lead.
     - Deregistration date and reason.
     - OSHA PSM, EPCRA 302 and Title V status, and the last safety inspection with the inspecting agency.
     - Location method and what the point describes, e.g. "Plant Entrance (Personnel)". The RMP coordinate is often a gate or office.
     - `FRS_Lat/Long`, a second point.
   - **Regulated substances.** Each chemical shows the largest quantity held in any single process and how many processes hold it.
     - RMP quantities are per-process maxima, and processes can share inventory, so **never sum them** into a facility total.
     - "Flammable Mixture" rows list their components. The quantity is the whole mixture.
   - **Processes.**
     - **Program level 3** means the process is subject to OSHA PSM or is in a listed NAICS code, with a full prevention program. Level 1 means no public receptor lies within the worst-case distance and no accident with off-site consequences in 5 years.
     - **PHA** is the process hazard analysis. `its changes due` is the expected date for resolving the PHA's recommendations, so it can be in the future.
     - **Hazards** are those the PHA identified. Hurricanes, floods and tornadoes marked `No` in coastal Louisiana are worth quoting.
   - **Emergency response.**
     - Whether the facility responds to releases itself or relies on public responders, the coordinating agency and its phone, and plan review and training dates.
     - Exercise, drill, tabletop and LEPC-coordination answers. `No` with no date is common in older submissions.
   - **Submission history.** Names and operators over time; it shows ownership changes.
   - **Accident history.** See [Accidents](#accidents).
3. **`accidents`** prints full detail for each accident:
   - release type and source, duration, weather;
   - deaths and injuries by category, and off-site hospitalizations, evacuations and sheltering in place;
   - property and environmental damage;
   - initiating event, contributing factors, changes made, and whether off-site responders were notified.

   `--csv` writes one row per accident and chemical.
4. **`summary`** prints the executive summary. It is the facility's own narrative: its description of worst-case scenarios, prevention and accident history is advocacy, not data. Quote it only to contrast it with the structured fields or with NRC and CSB records.
5. **`crosswalk`** links the facility to everything else. See [Crosswalk](#crosswalk-to-frs-and-other-programs).

## Accidents

- **Each submission covers only the 5 years before it.** The latest submission alone hides older accidents: Shell Norco's 2023 RMP lists none, but its 2015 RMP lists a 2010-01-22 fire and its 1999 and 2004 RMPs list six more back to 1993. The script reads **every** submission and keeps each event once. Accidents on the same day count as one event, keeping the newest submission's version; two accidents in one submission on the same day stay separate. This is the Data Liberation Project's deduplication rule. Each row shows the submission it came from.
- **`NoAccidents` is unreliable.** Shell's four latest submissions set `NoAccidents=No` and list no accidents. Count rows; the script flags the mismatch.
- **Rows can be incomplete.** Shell's 2002-10-08 accident (50 people evacuated off-site) lists no chemical in the RMP itself. The script prints "(no chemical listed in the RMP)".
- **Narrow criteria.** An accident goes in the RMP only if it involved a covered process and caused one of the following:
  - on-site deaths, injuries or significant property damage;
  - known off-site deaths, injuries, evacuations, sheltering in place, or property or environmental damage.

  Most NRC reportable-quantity releases and flaring events never qualify. **More NRC reports than RMP accidents is expected, not proof of under-reporting.** A specific NRC or CSB event that clearly meets the criteria (an evacuation, an injury) and is missing from the next RMP is a lead worth raising in a comment or a records request. It is not a finding until the facility's or EPA's file confirms it.
- **"None reported" is not "none occurred."** Say "the facility's RMPs list no accidents" and give the years covered.

## What this data does not contain

- **Off-site consequence analysis (OCA):** worst-case and alternative release scenarios, distances to endpoints, and the population and public receptors inside them. These are kept off the internet by law (CAA 112(r)(7)(H), 40 CFR Part 1400), and they are **not in the FOIA'd data**. Never write that a facility's worst case "was checked" or "is X miles" from this skill.

  `oca` prints the routes, verified against EPA's pages on 2026-10-16:
  - **Federal Reading Rooms.** 10 facilities a month anywhere, plus every facility affecting the LEPC jurisdiction where you live or work. Take notes only; bring photo ID and proof of address.
  - **The Vulnerable Zone Indicator System.** The e-mail form at epa.gov/rmp/forms/vulnerable-zone-indicator-system, or the RMP Reporting Center at 703-227-7650 / RMPRC@epacdx.net. It says whether an address may be inside a facility's vulnerable zone. The old `cdxapps.epa.gov/vzis/` link now just redirects to CDX.
  - **The parish LEPC.**
- **Facility emergency contacts.** The FOIA'd data has no contact names, titles or 24-hour phones. It has only the coordinating response agency, its phone, and the LEPC. Do not imply a contact was looked up.
- **Anything after the vintage.** For a current RMP, ask a reading room for the non-OCA RMP, FOIA EPA through PAL, or request it from LDEQ (`la-public-records-request`).
- **The 2024 rule's information-availability duty** (40 CFR 68.210(d)–(h): hazard information on request for residents within 6 miles). Its compliance date is May 10, 2028, and EPA's Common Sense Approach proposal (91 FR 8970, Feb. 24, 2026, docket EPA-HQ-OLEM-2025-0313) may change it. Do not cite it as a current right; check ecfr.gov first.

## Coordinates

- **Sign errors.** Some RMP longitudes drop the minus sign (e.g. 92.508333 for a Louisiana gas plant). The script restores it and marks the row. Guam and the Northern Marianas legitimately have positive longitudes.
- **Accuracy.** `near` uses the latest submission's self-reported point, so distances are point-to-point and approximate. For fenceline-to-home distances use `parish-assessor-gis` and `geo-distance`. Use `FRS_Lat/Long` in `facility` as a cross-check.

## Crosswalk to FRS and other programs

FRS (Envirofacts `FRS_PROGRAM_FACILITY`) carries **no RMP program records**: neither an EPAFacilityID lookup nor an `RMP` acronym query returns anything. The bridge is `OtherEPAFacilityID`, the other EPA ID the facility entered in its RMP:
- usually its RCRA handler ID (Shell Norco: LAD008186579);
- sometimes its TRI facility ID (Hexion Norco: 70079RSLTN16122).

`crosswalk` looks that ID up in FRS and lists every program ID at each matching registry. One ID can match more than one registry: Shell's RCRA ID also matches a SEMS site record. Pick the registry whose programs and address fit; the one with the most programs is listed first.

Shell's registry 110013831201 carries LA-TEMPO 1406 and 26336, which are LDEQ AIs. Those feed `ldeq-eric-emissions`, `ldeq-permit-status` and `ldeq-edms-search`. It also carries TRIS 70079SHLLL1205R, which feeds `epa-tri-search`. When the RMP has no other ID, resolve the facility by name and address with `epa-frs-crosswalk`.

## Using it with other skills

- **`csb-nrc-hazmat`.** `hazmat.py nrc --county <parish> --company "<alias|alias>"` lists NRC release reports, and `csb-releases` lists 40 CFR 1604 events (death, inpatient hospitalization or ≥ $1M damage, 2020 on) for the same facility. Line up their dates against `accidents`. The strongest lead is a 1604 event involving a regulated substance from a covered process that is missing from the next RMP. A death, an inpatient hospitalization or $1M+ damage from such a release would ordinarily meet RMP's accident-history criteria, so ask why it is absent.
- **`osha-inspections`.** PSM citations for the same processes; RMP program level 3 means OSHA PSM applies.
- **`chemical-hazard-profile`.** GHS and IARC profiles of the listed substances.
- **`ejscreen-report`.** The RMP proximity indicator (`PRMP`) is a score; `near` names the facilities behind it.
- **`household-exposure`.** Context for a home: which RMP facilities and substances lie within a few km. RMP covers accidental releases, not routine emissions, so keep it separate from RSEI or AERMOD numbers.
- **`permit-analysis`.** Questions SAF-009, SAF-010 and SAF-014 (risk assessment, worst-case modeling, RMP applicability). For an existing facility, compare the permit application's hazard claims against its RMP. For a new one, the RMP comes later, so ask whether one will be required and when.

## Citation format

> EPA Risk Management Plan, Equilon Enterprises LLC dba Shell-NORCO LA REFINER (EPAFacilityID 100000026009), submission 1000108470, validated 2023-12-13: Logistics process (Program 3), flammable mixture 30,000,000 lb. EPA RMP database via the Data Liberation Project (FOIA, data through 2025-12-30), CC BY-SA 4.0; https://data-liberation-project.github.io/epa-rmp-viewer/#/submission:1000108470. Retrieved 2026-10-16.

> Accident of 2002-10-08 (50 persons evacuated off-site), reported in RMP submission 29570 (validated 2004-02-18), EPAFacilityID 100000026009. [same source line]

Every command prints its source, the attribution, and the retrieval date. `search` and `near` also print the data vintage. Carry all of them into the citation.
