---
name: environmental-data-audit
description: Assess whether existing environmental datasets, agency documents, or research outputs support a specific claim or research question. Use when an audit is requested or a material data limitation could change a finding; routine lookups do not require an audit.
argument-hint: <files-or-URLs...> [claim or research question]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion, Skill, WebSearch, WebFetch
---

# bayou:environmental-data-audit — evidence fit for a claim

Evaluate the supplied evidence against the actual claim, with a concise, cited assessment
of what it supports and what remains unresolved. This is a conditional research aid, not a
mandatory pipeline stage or a numerical “justice score.” No new dependencies are required.

## Establish the question and evidence

Accept dataset files, agency documents, URLs, or existing research outputs, together with
the claim or question. Infer the question from the supplied work when clear and state it
in the assessment. Ask only if ambiguity would materially change the audit's scope.

Start with existing case files, cached inputs, and their provenance. Use the relevant Bayou
retrieval skill when additional evidence is needed, rather than rebuilding its download or
search workflow. For example, use `bayou:epa-tri-search` for TRI records,
`bayou:ejscreen-report` for screening indicators, `bayou:epa-frs-crosswalk` for program IDs,
`bayou:ldeq-edms-search` / `bayou:ldeq-edms-download` for agency documents,
`bayou:ldeq-eric-emissions` for Louisiana's state emissions inventory,
`bayou:ldeq-lelap-labs` for whether the lab behind analytical data was LELAP-accredited for
that method on the sample date, and
`bayou:csb-nrc-hazmat` for National Response Center release reports and CSB records.

When ERIC is part of the evidence, check four things:
- **Value type.** Its values are self-reported certified estimates.
- **Coverage.** Facilities below the LAC 33:III.919 and 5107 thresholds do not report, and a blank cell
  means not reported.
- **Comparability.** TEMPO permitted rates are current-permit maximums, never summed across statistical
  basis or group.
- **Geography and time.** Coordinates are often wrong, revisions arrive all year, and Baseline PM10 is TSP.

`eric.py reconcile` tests whether a release-point figure agrees with the annual file.

Consult authoritative methodology, field definitions, and reporting documentation for the
data version being evaluated. Cite the relevant sections and version, not just a current
landing page. If documentation or an input cannot be obtained, identify what is unavailable
and which conclusion it prevents; do not silently substitute another vintage's rules.

## Check only issues that could affect the answer

Select the relevant checks below. Follow material discrepancies far enough to narrow the
claim or identify a targeted next step; do not manufacture objections or run every check
against every dataset.

| Issue | Check against the claim |
|---|---|
| Coverage | Reporting thresholds, excluded facilities or pollutants, missing periods, search filters, pagination, and inaccessible records. A missing record is not itself a zero or proof that an event did not occur. |
| Value type | Distinguish measured, modeled, estimated, and self-reported values; these categories may overlap. Use the documented treatment of nondetects, zeros, missing values, and flags rather than silently substituting one for another. |
| Geography and time | Compare boundaries, demographic vintages, observation periods, averaging periods, and aggregation methods. Determine whether aggregation conceals variation relevant to the question. |
| Comparability | Check units, denominators, facility/program identifiers, duplicates, and transformations. Separate permitted maximums from reported releases; label differing quantities rather than presenting them as equivalent observations. |
| Meaning | Determine whether the indicator addresses the question. Emissions mass alone does not establish exposure, and recorded compliance alone does not establish absence of harm. State what additional evidence the broader inference would need. |

Treat EDMS incident reports as agency-held documents: identify each report's author,
document ID, date, event period, and reporting limitations where available. Agency custody
does not make every statement an agency finding. Do not assume resident intake, add an
incident-intake workflow, or interpret no retrieved reports as no incidents. Describe the
search actually completed and any gaps in it.

National Response Center reports are a caller's initial account, which NRC describes as "not
validated or investigated by a federal/state response agency". Count follow-up and correction
reports separately from first reports, and treat "unknown amount" as missing, not zero. Facility
matching rests on name, parish and address, because the reports carry no facility ID. Report the
alias set and the call years searched as part of the coverage.

Separate **demonstrated problems** (with evidence of the mismatch or error) from
**unresolved questions** (what has not been established). A possible limitation is not a
demonstrated flaw. Compatible, well-supported data should receive a short affirmative
assessment bounded by the question assessed.

## Retain enough evidence to reproduce consequential findings

Reference existing case files and cached inputs first. For the inputs supporting the
finding, record the source URL or document ID, retrieval date, data vintage, query/filter
parameters, and transformations (including joins, exclusions, unit conversions, and
aggregation when used). Mark unknown metadata as unknown rather than inventing it.

For a consequential finding based on a mutable response, retain the relevant response or
extract alongside the case's research inputs, with enough metadata to identify its source
and reproduce the calculation. Preserve the scope and fields needed to understand the
extract. Reuse an existing saved input when it suffices; do not duplicate a bulk download.
If no case directory exists, use a small local evidence file and report its path.

If the original input is unavailable, say so. A fresh retrieval has its own retrieval date
and must not be described as the historical version. Do not introduce bulk database
mirroring, scheduled backups, automatic public archiving, or a separate preservation process.

## Return the assessment

Use these elements, combining them into a short paragraph when the evidence is straightforward:

- **Claim evaluated:** the exact claim or question and relevant population, place, and period.
- **Supporting evidence:** what the data establish, with source citations and local evidence
  paths or document/page references where available.
- **Material limitations:** demonstrated problems separately from unresolved questions, and
  how each affects the claim. If none is identified within scope, say so briefly.
- **Defensible wording:** a usable sentence that stays within the evidence.
- **Targeted next steps:** only the retrieval, clarification, or recalculation needed to
  resolve material uncertainty; no extra research list when none is needed.

Include provenance compactly beside the evidence or in a small source table. Return the
assessment in the conversation by default. In an established case directory, also save
`environmental-data-audit.md` alongside its research outputs (for example, in `verification/`
when that is where the findings live), and report the path. Inspect any existing audit
before writing: update it only for the same question and scope; otherwise use a descriptive
claim suffix or date plus suffix to avoid overwriting an unrelated audit.

When called from permit analysis, return the supported wording and material limitations
to the relevant finding, preserving that workflow's citation and research-status conventions.
