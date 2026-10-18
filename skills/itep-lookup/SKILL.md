---
name: itep-lookup
description: Louisiana economic-development incentives for a company or facility — Industrial Tax Exemption (ITEP), Quality Jobs (QJ), Enterprise Zone (EZ) and Restoration Tax Abatement (RTA) — from LED's FastLane public report and Board of Commerce & Industry (BCI) agendas and transcripts. Gives each project's rule set, status, board dates, promised investment, jobs and payroll, and what the company later reported (affidavit of final cost, renewal jobs, QJ compliance), plus the BCI renewal compliance codes (CP/NC/NCL), 2018-rules non-compliance tables (required against actual jobs, each local body's recommendation), Local ITEP Committee decisions, cancellations and "opt out" amendments, and verbatim board discussion and votes. Use for the incentive stack and the economic-benefit side of a comment, alongside la-bond-dockets for the financing.
argument-hint: <company or facility> [parish] | <project ID, e.g. 20190099-ITE>
allowed-tools: Bash, Read, WebFetch, WebSearch, AskUserQuestion
---

# Louisiana incentives lookup (ITEP, QJ, EZ, RTA)

A large industrial project in Louisiana usually stacks several incentives: an ITEP property-tax exemption, a Quality Jobs payroll rebate, sometimes an Enterprise Zone rebate, plus conduit bonds (`bayou:la-bond-dockets`). Each incentive was granted against promised investment, jobs and payroll. The Board of Commerce & Industry (BCI) approves the contracts, and LED's FastLane system holds the filings.

This skill retrieves what was promised and what the company later reported. Those facts support the economic-benefit side of the *Save Ourselves* balancing test: the agency must weigh environmental cost against claimed benefit, and the incentive record shows how solid that benefit claim is. The argument itself belongs in `skills/public-comment/postures/financing.md` (financing stack) or the permit posture.

## Scripts

Standard library, plus `pdftotext` (`brew install poppler`) for the BCI PDFs. Both scripts accept `--json`.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/itep-lookup"

# FastLane public report (live API, nothing cached)
python3 "$S/fastlane.py" search Valero --parish "St. Charles"            # one row per project
python3 "$S/fastlane.py" search Shell --parish "St. Charles" --program ITE --csv shell.csv
python3 "$S/fastlane.py" search --program QJ --approved-from 2026-01-01   # board-approved in a window
python3 "$S/fastlane.py" project 20190099-ITE                             # promised vs actual, dates, history
python3 "$S/fastlane.py" compare Valero --parish "St. Charles"            # promised-vs-reported table

# BCI agendas, approval lists and transcripts (cached under ~/.cache/bayou/itep-lookup/bci/)
python3 "$S/bci_board.py" meetings --year 2026
python3 "$S/bci_board.py" search Valero --from 2024-01-01
python3 "$S/bci_board.py" search 20190099-ITE
python3 "$S/bci_board.py" renewals --noncompliant --from 2026-01-01
python3 "$S/bci_board.py" noncompliance --from 2025-01-01
python3 "$S/bci_board.py" minutes 06/24/2026 --grep Valero 20180370
```

**Guards.** `fastlane.py` counts matches before fetching. Above 500 records it exits with code 3 and prints the count and an estimated size, at about 35 KB per record (a statewide ITEP pull is 12,919 records and about 450 MB). `bci_board.py` estimates uncached PDFs and exits 3 above 25 files or 50 MB. Full agendas run 5–8 MB, so a year of them is about 30 MB. `search`, `renewals` and `noncompliance` default to the last 12 months. Relay the estimate to the user and ask before rerunning with `--yes` (a global flag: `bci_board.py --yes search ...`), or narrow the query.

## Workflow

1. **Find every project.** Run `fastlane.py search` on the company, then on its name variants, affiliates and site names. FastLane files projects under the legal entity: "Valero Refining-New Orleans, LLC", "Valero Services Inc.", "Equilon Enterprises LLC dba Shell Oil Products US". Add `--parish` once you know the parish. Search matches project IDs as well as names.
2. **Pull promised against reported.** Run `compare` on the company and `project` on the IDs that matter. Each record splits into two parts:
   - **Promised (as filed):** the application's estimated investment, existing, new and construction jobs, payroll, LED's estimated benefit, product and description. For QJ there is also the payroll schedule filed with the application.
   - **Actual (as reported by company):** the affidavit of final cost (`afc_investment`); for ITEP renewals, `prior_jobs`, `current_jobs` and `jobs_reduction_reason`; for QJ renewals, `qj_has_company_complied`; for RTA, the AFC's actual jobs and payroll.
   It also gives board dates, contract and renewal dates, the status history, and external review (Revenue, the Workforce Commission and, under the 2025 rules, the Local ITEP Committee).
3. **Read the board record.** Run `bci_board.py search` on the company and on each project ID. Agenda rows give the BCI's own numbers for each meeting:
   - QJ: 10-year rebate, jobs and salaries;
   - EZ: state and local rebates, investment credit and jobs;
   - ITEP: first-year exemption, 20% collected, LIC decision, NAICS, and a late-filing flag.
   The same search covers the special-request pages: contract terminations, cancellations ("did not meet the program requirements"), transfers and **"opt out" amendments**.
4. **Check compliance.** `renewals --noncompliant` lists ITEP renewals whose four-year compliance summary includes NC or NCL, with jobs at the first year of exemption against current jobs. `noncompliance` lists 2018-rules contracts the board took up as non-compliant: required against actual jobs and salaries for the reporting year, and the recommendation from the parish, school board, sheriff and municipality.
5. **Quote the discussion.** Use `minutes <date> --grep <company> <project number>`. Minutes are court-reporter transcripts; the script splits the two-column pages and returns line-numbered passages (page:line). Cite them that way. Read far enough to reach the motion and the vote.
6. **Add the local layer.** For parcels, owner of record and assessed value, use `bayou:parish-assessor-gis` (St. Charles, Ascension, St. James). An exempt facility's assessed value shows what is still on the roll, and its parcel numbers are what an assessor records request should cite. Ascension values date from 2016. For local votes, run `bayou:parish-council-agendas alerts <parish> --category financing-incentive` (St. Charles, Ascension, St. James, East Baton Rouge, Plaquemines, St. Bernard, Assumption) for parish council ITEP, PILOT and cooperative endeavor items (East Baton Rouge also posts its Local ITEP Committee agendas), and search the web for school board and sheriff resolutions on the project. Under the 2018 rules those bodies approved or denied each exemption; under the 2025 rules they act through the Local ITEP Committee.
7. **Find audits and reports.** Search the web for Legislative Auditor performance audits of ITEP, QJ and EZ (site:lla.la.gov), LED's annual incentive reports, and Louisiana Budget Project or Together Louisiana analyses. Record what each covers (program, years, whether it names companies) rather than lifting single numbers out of context.

## Output

**Incentive stack:** one row per project, every row cited to a FastLane ID and a BCI PDF URL.

| Program | ID | Rule set | Entity (as filed) | Parish | Board date | Status | Est. investment | Est. new jobs / payroll | Benefit (LED est.) | Source |
|---|---|---|---|---|---|---|---|---|---|---|

**Promised against reported:** say what each "reported" number is: the AFC, the renewal application, or a BCI table.

| ID | Est. existing + new jobs | Reported current jobs (date, form) | Δ | Est. investment | AFC investment | BCI compliance codes | Board action on non-compliance | Source |
|---|---|---|---|---|---|---|---|---|

## Honesty limits

- **Every number is self-reported.** Application figures are the company's estimates, and FastLane's renewal jobs are labelled "as reported by company", as are the BCI renewal tables. LED's `estimatedBenefits` is LED's own fee calculation, not an audited figure. Say "the company reported" or "LED estimated", never "the project created".
- **A zero is not always a zero.** Every FastLane record carries every program's sub-blocks, filled with defaults; ITEP records, for example, carry a QJ `hasCompanyComplied: false`. Records migrated from the old system (`migrated_record: true`) carry 0 payroll and 0001-01-01 dates. The scripts print these as "not reported" or `-`. Never write them as "0 jobs" or "non-compliant". For a migrated project, check the BCI agenda or the original contract before stating a figure.
- **A 2025-rules project shows no jobs because the rules don't ask for them.** The 2025 Project Application has no jobs or payroll section, and 2017- and 2018-rules contracts can "opt out" of jobs, payroll and compliance by amendment. Their absence is a policy fact worth stating; it is not a data gap.
- **The QJ payroll schedule is a projection.** The schedule printed for QJ projects (`qj_payroll_schedule_as_filed`) is the year-by-year payroll filed with the application, and it runs into future years. It is not reported payroll. The public report holds no QJ actuals beyond the renewal's yes/no compliance answers.
- **Missing from FastLane does not mean no incentive.** Confidential projects are withheld, some pre-migration records never came over, and EZ and RTA coverage of older years is thin. Write "not found in the FastLane public report", not "received no incentives".
- **Parser coverage of BCI PDFs.** The BCI page links agendas back to 2015. Agendas from October 2024 to September 2026 parse cleanly: 876 rows, none unlabelled. Older agendas use other layouts. A row the parser cannot fit to its table's header keeps its raw text and is flagged `unlabelled`; read the PDF before citing it. Minutes from before about 2023 may be summaries, not transcripts, and `minutes` says so when it finds no line-numbered pages.
- **The transcript has typos.** Copy them as printed, e.g. "a motion ... to improve without penalty", and mark them [sic] when quoting.
- **No personal data.** FastLane records hold names, emails, phones and signatures of company contacts and consultants. `fastlane.py` prints only an allowlist of project fields. Never go around it, by curling the API directly or otherwise, to name an individual. BCI transcripts name speakers on the record, and those may be quoted.

## Key facts

**ITEP** (La. Const. art. VII, §21(F); rules at LAC 13:I, Ch. 5). Rule sets on FastLane: Pre Executive Order, 2017, 2018, 2024 Emergency and 2025. The 2025 rules (LR 51:365, March 2025), from LED's 2025 one-pager and the final rule:

- **Exemption and term:** an 80% ad valorem exemption for an initial 5-year term, with a 5-year renewal. The company pays the other 20%, which appears in agendas as "20% taxes collected".
- **Mega-projects:** an expansion or addition of at least $500 million in capital expenditure may get 93–100%, with Local ITEP Committee input, BCI approval and the Governor's approval. `RE*` in an agenda means "recommending approval as a mega project with an increased exemption of 93% per §549(D)".
- **Excluded:** miscellaneous capital additions and land.
- **Local ITEP Committee (§549):** one voting member each from the parish governing authority, school board, sheriff and, where applicable, the mayor. It has 45 days to act. If it does not act, the application is **"deemed accepted"** (`DA`), and DA is the most common LIC code on 2025–2026 agendas. Its **recommendations "are not dispositive and do not bind the governor or the board"** (§549(E)). Under the 2018 rules, each local body approved or denied its own share of the exemption. Any committee meeting on an application is public business under the Open Meetings Law (§549(C)(2)).
- **Late filing:** a late application loses one year of term for each year or part of a year it is late (§503). A late renewal loses one year for each month or part of a month it is late (§529(D)).
- **Opt out:** 2017- and 2018-rules contracts may amend Exhibit A to zero jobs and zero payroll, which drops the jobs and compliance components.

**Quality Jobs** (R.S. 51:2451 et seq.)

- **Rebate:** the benefit rate times gross payroll of new direct jobs, capped at 80% of that payroll for contracts on or after July 1, 2015 (R.S. 51:2455).
- **Benefit rate** (R.S. 51:2453(1)): 4% for jobs paying at least $18.00 an hour, 6% for jobs paying at least $21.66 an hour.
- BCI agendas show a ten-year payroll rebate, plus a sales/use tax or project-facility-expense rebate.

**Enterprise Zone** (R.S. 51:1781 et seq.)

- **Contracts:** up to five years, offering a state and local sales and use tax rebate or a refundable investment income tax credit of 1.5% of qualified expenditures, plus a jobs tax credit (R.S. 51:1787).
- A rebate of local sales tax needs the local governing authority's approval.

**Restoration Tax Abatement** (R.S. 47:4311 et seq.; La. Const. art. VII, §21(H))

- **Scope:** abatement of ad valorem taxes on the expansion, restoration or improvement of existing commercial structures and owner-occupied residences in downtown, historic and economic-development districts.
- **Local hearing:** before approving, the local governing authority must hold a public hearing, with notice published twice in the official journal (R.S. 47:4314(B)). That hearing is a comment opportunity.

Confirm statute text with `bayou:la-rs-search` before quoting it; these cites were checked 2026-10-16.

## Gaps and where they go

| Need | Route |
|---|---|
| Full board packet: Exhibit A, annual compliance reports, LIC resolutions | Email `LEDBoardPacketRequest@la.gov`, or use `bayou:la-public-records-request` addressed to LED |
| A project's bonds, PILOT and cooperative endeavor agreements | `bayou:la-bond-dockets` |
| Matching a FastLane site address to an EPA/LDEQ facility | `bayou:epa-frs-crosswalk` |
| Parcels and assessed value of an exempt facility | `bayou:parish-assessor-gis` |
| Local ITEP Committee members for a parish | The "Local ITEP Committee Contact Info" PDF linked from LED's ITEP page |
| Board action before the online agendas, or on confidential projects | `bayou:la-public-records-request` |
| Statute text | `bayou:la-rs-search` |

## Sources

- **FastLane NextGen public report:** https://fastlaneng.louisianaeconomicdevelopment.com/public/reports. The script POSTs to the report's DataTables endpoint at `api.fastlaneng.louisianaeconomicdevelopment.com/api/report/publicReport/datatables/list`. Cite the public-report page and the project ID.
- **BCI page:** https://www.opportunitylouisiana.gov/about-led/advisory-boards/louisiana-board-of-commerce-and-industry. It links agendas, transcripts and "Application Approvals" lists. Cite the PDF URL that `bci_board.py` prints.
- **ITEP rules:** LED's ITEP page links the 2018 rules, the May 2024 emergency rule, the March 2025 final rule and the 2025 one-pager.

If the BCI page or the FastLane API changes shape, the scripts fail loudly. Fix the parser; never report "no records".

## Worked example: Valero, St. Charles Parish

| Step | Command | Finding |
|---|---|---|
| Stack | `fastlane.py compare Valero --parish "St. Charles"` | 25 projects: 22 ITEP under Valero Refining-New Orleans, LLC (filed under two spellings) and 3 QJ under Valero Services Inc. (2 jointly with the refinery). 20180370-ITE (2018 rules) estimated 951 existing and 9 new jobs on $314,817,097; its renewal reports 955 current jobs. |
| Board record | `bci_board.py noncompliance --from 2025-01-01` | 20180370-ITE came up as non-compliant twice. On the 2025-04-23 agenda (reporting years 2022 and 2023) and the 2026-06-24 agenda (reporting year 2024), each year shows 9 jobs required and 0 actual, and the parish, school board and sheriff each answered `TNA` (take no action). The 2026 table adds $1,200,000 payroll required and $0 actual. |
| Discussion and vote | `bci_board.py minutes 06/24/2026 --grep 20180370` | p. 28:15–29:3: staff reads the item, and the parish, school board and sheriff's joint letter urging the board "to take no action and not penalize the company". p. 31:20–32:2: Valero's representative says the issue arose in 2022, 2023 and 2024. p. 36:17–21: "a motion, Mr. Willis, to improve [sic] without penalty", seconded by Mr. Callais. |
| New applications and amendments | `bci_board.py search Valero --from 2024-06-01` | Three 2024-emergency-rules applications: 20240087-ITE in June 2025, 20240196-ITE in Aug 2025, 20240073-ITE in Apr 2026. Two 2025-rules projects: 20250523-ITE, $16,500,000, LIC `DA`, Oct 2025; and 20260146-ITE, $10,900,000, LIC `RE`, Sept 2026. Neither 2025-rules project lists jobs. On 2025-04-23, contract 20180502 opted out of jobs, payroll and compliance. |

$ARGUMENTS
