---
name: ferc-elibrary
description: FERC eLibrary docket research. Covers interstate gas pipeline and compressor-station certificates (CP), LNG terminal authorizations (CP, NGA §3/§7), NEPA pre-filing (PF), gas and electric rate cases (RP, ER) and hydro projects (P-). It lists filings on a docket, the draft/final EIS and EA documents, Commission and delegated orders (certificate, rehearing, stay, construction clearances), notices that open scoping, comment or intervention periods, and who moved to intervene. It also finds a docket from a project or company name and downloads public PDFs. Use when a facility is FERC-jurisdictional (an interstate pipeline flagged by phmsa-npms-search, an LNG export terminal), when someone asks about a FERC docket, EIS, motion to intervene, intervenors, rehearing, or a petition for review of a FERC order, or to find CEII or privileged filings and the route to request them.
argument-hint: docket <CP22-21[-001]> [--all] | eis|orders|notices|movants <docket> | search "<project or company>" | files|get <accession>
allowed-tools: Bash, Read, WebFetch, WebSearch
---

# FERC eLibrary

[eLibrary](https://elibrary.ferc.gov/eLibrary/search) is FERC's record of every filing and issuance, organized by docket. The web page is an Angular app over a JSON API (`https://elibrary.ferc.gov/eLibraryWebAPI/api/`). The API answers anonymous requests, with no login, no CAPTCHA and no browser session. Each document has:

- an **accession number**: `YYYYMMDD-NNNN`. In observed data (not documented by FERC), 3000s serials are FERC issuances, 5000s are e-filings and 0000s are paper filings;
- one or more **Class / Type** labels;
- an **availability** code: `P` public, `C` CEII, `N` non-public (privileged);
- the dockets it was filed under, its filer and agent affiliations, and its transmittal files.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/ferc-elibrary"
F() { uv run -q --no-project python -I "$S/ferc.py" "$@"; }

F health                                   # API up; CP22-21 totalHits == unique rows paged (~20 s)
F search "Commonwealth LNG"                # find the docket: description search, dockets tallied
F search "Monkey Island" --fulltext        # also searches document text (broad; relevance-ordered)
F docket CP22-21                           # newest 50 filings, availability counts, co-listed dockets
F docket CP22-21 --all --json              # the whole docket (1,114 filings, ~6 pages of 200)
F docket CP22-21-001                       # one sub-docket (-000 is the original application)
F docket CP22-21 --class Intervention --type "Motion/Notice of Intervention"
F docket CP22-21 --since 2025-01-01 --until 2025-06-30 --date-type issued
F docket CP22-21 --text "Monkey Island"    # filings on the docket mentioning a place
F eis CP22-21                              # DEIS / FEIS / supplemental / EA, with volume sizes
F orders CP22-21                           # Commission orders first, then staff delegated letters
F notices CP22-21                          # what each notice opens (scoping, DEIS comments, interventions)
F movants CP22-21                          # intervention motions grouped by filer, oppositions, late grants
F classes environmental                    # valid --class/--type strings
F files 20230728-3008                      # transmittal files, sizes, per-file availability
F get 20261016-5151 --out ./ferc           # public files -> ./ferc/20261016-5151/
F get 20230728-3008 --file 1 --out ./ferc  # one volume of a large set
```

- `--json` and `--refresh` go before or after the subcommand.
- Searches, file lists and the class vocabulary are cached for one day under `~/.cache/bayou/ferc-elibrary/`.
- Exit codes:
  - 2: bad arguments, or `get` above 25 MB or 10 files without `--yes`. The file list and total size are printed.
  - 3: the docket has no filings, the accession is unknown, or the Class/Type is not in eLibrary's vocabulary. Near matches are printed.
  - 5: eLibrary is unavailable, or a Cloudflare or F5 page came back instead of JSON.

## Workflow

1. **Find the docket.** Run `search "<project or company>"`. The output tallies the dockets among the hits. Pipeline operators in `phmsa-npms-search` results use their legal names, which also work here. Federal Register notices of FERC actions cite the docket too (`federal-register-search`).
2. **Find the pre-filing docket.** Pre-filing review in a `PF` docket is mandatory for LNG terminals and their related pipelines, and optional for other gas projects (18 CFR 157.21(a), (b)). It comes before the `CP` application. `docket <CP>` lists **co-listed dockets**. For CP22-21 (CP2 LNG), PF21-1 appears because scoping comments and early motions were filed under both. Scoping comments filed in the PF docket are part of the NEPA record.
3. **Timeline.** `docket <CP> --all --json` returns the whole record. The milestones are:
   - the application;
   - the notice of application, which sets the intervention deadline;
   - the NOI and scoping;
   - the DEIS, then the FEIS (or EA);
   - the certificate order;
   - rehearing requests and rehearing orders;
   - construction clearances (delegated letters).
4. **Environmental documents.** `eis` lists each EIS volume and its size. Volume I is usually the analysis; the appendices hold alignment sheets, wetland and habitat surveys and air modeling. `notices` shows which notices opened a comment period. **The deadline is printed in the notice, not in eLibrary's description.** Run `get` on the notice and read it. Supplemental EISs (DSEIS/FSEIS) reopen comment, as they did on CP22-21 in 2025.
5. **Who is in the case.** Run `movants`. See [Movants versus parties](#movants-versus-parties) before calling anyone a party.
6. **Read the documents.** `get` fetches only public files. Large EIS sets need `--yes` or `--file N`; announce the size first. Check for a text layer with `pdftotext -l 2 file.pdf - | head`. Send only scanned PDFs to `document-ocr`.

## Docket prefixes

| Prefix | What it is |
|---|---|
| `CP` | Natural Gas Act certificates: interstate pipelines and compressor stations (§7), and LNG import/export terminals (§3). Sub-dockets `-001`, `-002` are amendments, variances or later phases. |
| `PF` | NEPA pre-filing review, before the CP application. No certificate issues here, but scoping happens here. |
| `RP` | Interstate gas pipeline rates and tariffs. |
| `ER` / `EL` | Electric rates, interconnections and complaints (Federal Power Act). |
| `P-` | Hydropower licenses (for example `P-1494`). |

LNG **export** also needs Department of Energy authorization (DOE Office of Fossil Energy and Carbon Management, FE dockets). That record is not in eLibrary. Intrastate pipelines are outside FERC's certificate jurisdiction and have no eLibrary docket. Louisiana utility rate cases are at the LPSC (`lpsc-dockets`), not FERC.

## Movants versus parties

`movants` shows who *moved* to intervene. It takes eLibrary's `Intervention` class and adds motions filed under other classes (joint "comments and motion to intervene", for example). Filer names are grouped after folding case, punctuation and plurals, so "Fisherman/Fishermen Involved in Sustaining Our Heritage" becomes one filer; the variants are shown. Party status is a separate legal question:

- **18 CFR 385.214(c)(1).** A timely motion with no answer in opposition within 15 days makes the movant a party at day 15.
- **385.214(c)(2).** If an answer in opposition is filed within 15 days of a timely motion, or the motion is late, the movant becomes a party only when the motion is expressly granted. An answer filed after day 15 does not undo party status already gained. `movants` lists the **answers** to interventions and the **Commission notices granting late interventions** for this reason. Compare each answer's date with the motion's date.
- **385.214(a)(2).** State agencies and the other listed entities become parties by a timely *notice* of intervention.
- **18 CFR 380.10(a)(1)(i).** A motion to intervene filed within the DEIS comment period is deemed timely. A "Motion/Notice of Intervention" filed a year after the notice-of-application deadline may still be timely.
- The "late motion" label reflects only eLibrary's type and the filer's own wording.

Party status matters downstream. Under Natural Gas Act §19, only a party can seek rehearing, and only a party aggrieved by the order on rehearing can petition for review. Petitions go to the D.C. Circuit, or to the circuit where the natural-gas company is located or has its principal place of business. For a Louisiana project, check the D.C. Circuit and the 5th Circuit (`pacer-case-search`).

**Service list.** FERC Online's [eService list](https://ferconline.ferc.gov/eServiceList.aspx) is the official list of intervenors and their contacts. Its F5 firewall rejects scripted requests ("Request Rejected"). If the user needs it, open it in a browser (Claude in Chrome): enter the docket (`CP22-21-000`), then read the table. It includes personal emails and phone numbers; summarize organizations, and do not republish individuals' contact details.

## Restricted documents

`get` never downloads `C` or `N` files. It lists them with the route to request them:

- **CEII (`C`, 18 CFR 388.113).**
  - A movant or intervenor can request the complete document from the filer with an executed protective agreement. It is due within five business days if no one objects (§388.113(g)(4)).
  - A landowner crossed by or near the project can get alignment sheets from FERC staff with proof of property interest (§388.113(g)(3)).
  - Anyone else files a request with FERC's CEII Coordinator, with a non-disclosure agreement (§388.113(g)(5)).
- **Privileged (`N`, filed under 18 CFR 388.112).** Parties can usually get it under the proceeding's protective agreement. Anyone else files a FOIA request with FERC's Director, Office of External Affairs (18 CFR 388.108).
- One accession can mix public and CEII files: a public cover letter with CEII attachments. `files` shows availability for each file.
- On CP22-21, 198 of 1,114 documents are CEII and 75 are non-public. Most of the CEII documents (176) are construction compliance reports: implementation-plan volumes.

## Limits and traps

- **Silent zeros.** eLibrary returns `success:true` with 0 hits for a misspelled Class/Type or an unknown date type. The script checks every Class/Type against `GetClassTypes` and exits 3 with near matches. It allows only the `filed`, `issued` and `posted` date types. When a valid filter matches nothing, it reports the docket's total, so "0 EIS on a docket with 1,114 filings" is distinguishable from a wrong docket number.
- **Class filters miss things.** Joint motions, answers and late-intervention grants are classed under Pleading/Motion, Comment or Notice. `movants` adds a description search for that reason; for other questions, use `docket --text`.
- **Descriptions are summaries.** eLibrary's one-line description is staff-written. Deadlines, conditions and the Commission's reasoning are in the PDF.
- **Ordering.** Docket listings are newest first. `search` and `docket --text` rank by relevance and show the top N.
- **Omnibus filings.** Service-list updates and rulemaking comments are filed under dozens of dockets. They inflate co-listed docket counts; read the description.

## Related skills

- `phmsa-npms-search`: pipeline location and operator. An interstate gas line there has a CP certificate here.
- `federal-register-search`: FERC NOIs, notices of availability and certificate orders also appear in the Federal Register, with the comment date.
- `la-comment-calendar`: put FERC scoping and DEIS comment deadlines (from `notices` plus the notice PDF) on the calendar.
- `public-comment`: draft scoping, DEIS or intervention comments. A motion to intervene must state the movant's interest and position (385.214(b)).
- `la-coastal-use-permits`, `usace-408-permits`: the state coastal-use and Corps permits that the same pipeline or terminal needs.
- `document-ocr`: scanned PDFs only.
- `pacer-case-search`: petitions for review of FERC orders (D.C. Circuit, 5th Circuit).
- `lpsc-dockets`: Louisiana utility dockets, for state-jurisdictional matters.
