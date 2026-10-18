---
name: la-public-records-request
description: Draft (never send) a Louisiana Public Records Act request under R.S. 44:1 et seq. to LDEQ, the Department of Conservation and Energy, a parish, or another state or local custodian — scoped to specific records, with the statutory response deadlines and fee provisions quoted from the current statute text
allowed-tools: Bash, Read, Write, WebSearch, WebFetch, AskUserQuestion
---

# Louisiana Public Records Request

Drafts a request letter or email under the Louisiana Public Records Act for records that are not already online: correspondence between an agency and an applicant, inspection field notes, modeling files, draft permits, meeting calendars, contracts.

**It drafts. It never sends, and it never fills in or submits an agency's web form.** The user sends the request under their own name.

This is for Louisiana state and local bodies only. A federal agency (EPA Region 6, the Corps' New Orleans District, PHMSA) is reached through the federal Freedom of Information Act, which has different deadlines, fee categories, and appeal steps; see "External skills and MCP servers" in the bayou README for a FOIA drafting skill.

## Parsing arguments

- **Custodian**: the agency or body holding the records.
- **Subject**: facility, permit or AI number, applicant, project, and a date range.
- **Record types wanted**, if the user knows.
- **Purpose**, only if the user wants a fee reduction (Step 4). The statute does not require a reason, and the draft gives none otherwise.

Ask for whatever is missing. A request with no date range or no named record type invites a "please narrow" reply that restarts the clock.

## Step 1: Check that the records are not already public

A request for something already posted wastes the response period. Check first:

| Records | Look here before requesting |
|---|---|
| LDEQ permits, applications, inspections, enforcement, correspondence | `/bayou:ldeq-edms-search`, `/bayou:ldeq-edms-download` |
| Oil and gas, injection wells, Class VI, coastal use permits | `/bayou:sonris-doc-search`, `/bayou:la-class-vi`, `/bayou:la-coastal-use-permits` |
| Public water systems: LDH sample results, violations, sanitary surveys, well and intake locations | `/bayou:ldh-drinking-water` (request the LDEQ SWAP source water assessment report and DCE water-well registrations; those are not posted) |
| Utility dockets | `/bayou:lpsc-dockets` |
| FERC pipeline and LNG dockets (federal records; the Louisiana Public Records Act does not reach them) | `/bayou:ferc-elibrary`, which lists the CEII and FOIA routes for restricted filings |
| Industrial tax exemptions, Quality Jobs, Enterprise Zone, RTA (FastLane and BCI agendas) | `/bayou:itep-lookup` |

Say in the letter what was already found ("EDMS holds the permit application, document 12345678; this request is for records not in EDMS"). It shows the custodian the request is specific and removes the easiest non-answer.

## Step 2: Pull the current statute text

Do not quote the Act from memory. It was amended in 2022, 2023 and 2024, and the day counts differ by section. Run `/bayou:la-rs-search` (Method A, Title 44) for each section the letter will cite, and quote from what comes back:

| Section | What it covers | Text as retrieved 2026-10-11 (re-verify) |
|---|---|---|
| R.S. 44:1 | Definitions of "public body" and "public records" | not summarized here; pull it |
| R.S. 44:31 | Right to inspect and copy | Any person of the age of majority may inspect, copy, or reproduce a public record; the burden of proving a record is not subject to inspection rests with the custodian |
| R.S. 44:32(A) | Custodian's duty; no questions asked | The custodian "shall make no inquiry" of the requester except age and identification, but may ask about the specificity of the records sought. Access may be denied as substantially disruptive only after reasonable attempts to narrow the request with the requester |
| R.S. 44:32(C)(2)(a) | Copy fees, state agencies | Fees follow the uniform schedule adopted by the commissioner of administration. Copies may be free or reduced for indigent citizens or for persons whose use "will be limited to a public purpose, including but not limited to use in a hearing before any governmental regulatory commission" |
| R.S. 44:32(C)(1)(a) | Copy fees, parishes and other non-state bodies | Reasonable fees under a posted schedule; payment may be required in advance |
| R.S. 44:32(C)(3) | Inspection | No fee to examine or review a record |
| R.S. 44:32(D) | Written denial | If the custodian questions whether a record is public, it must notify the requester in writing within five days (excluding Saturdays, Sundays, and legal public holidays) with its reasons and the legal basis for any exemption |
| R.S. 44:33(B)(1) | Availability | A record not in active use "shall be immediately presented"; if in active use, the custodian certifies that in writing and fixes a day and hour within three days (same exclusions) |
| R.S. 44:35 | Enforcement | After a denial, or five days (same exclusions) without a written determination or a time estimate, the requester may sue for mandamus in the district court of the parish where the custodian's office is located. A prevailing requester is awarded attorney fees; civil penalties up to $100 per day are possible for an arbitrary failure to respond |

Exemptions are scattered (R.S. 44:3, 44:4, 44:4.1 and agency statutes such as the confidentiality provision for trade secrets in LDEQ filings). Do not predict in the letter which exemption the custodian will claim. If the user expects a trade-secret claim, pull the specific provision with `/bayou:la-rs-search` and ask for the redacted version plus the written basis that R.S. 44:32(D) requires.

## Step 3: Identify the custodian and how it takes requests

Confirm every address on the agency's own site on the day of drafting. Agencies reorganize and staff change.

- **LDEQ.** Verified 2026-10-11 from `https://www.deq.louisiana.gov/page/edms`: requests for records not in EDMS go through the online Public Records Request Form at `https://edms.deq.louisiana.gov/edmsv2/create-my-request`. The Public Records team is `publicrecords@la.gov`, (225) 219-5337, option 3, and takes appointments to view records in person, 8:00 to 4:30 on weekdays. Draft the text so the user can paste it into the form, and keep a dated copy.
- **Department of Conservation and Energy** (the former Department of Energy and Natural Resources, renamed 1 October 2025; includes the Office of Conservation and the Office of Coastal Management). Its site was still in transition when this was written and no records-request page was found at `dce.louisiana.gov`. Search for the current custodian and address; do not reuse a DENR or DNR address without confirming it.
- **Parish governments, parish councils, port commissions, levee districts, school boards.** The custodian is the head of the body or a designated records custodian. Find the name on the body's website or by phone. Address the request to the named custodian, with a copy to the parish attorney if the body has ignored earlier requests. Before requesting agendas, minutes or packets, check `bayou:parish-council-agendas` for what is already online. Its parish table lists the gaps that need a request, such as Ascension council minutes and the St. James packets.
- **LED Board of Commerce & Industry packets** (Exhibit A, annual compliance reports, Local ITEP Committee resolutions): email `LEDBoardPacketRequest@la.gov`, naming the project IDs and meeting dates found with `bayou:itep-lookup`.
- **Other state agencies** (LDH, LED, the Public Service Commission, the Division of Administration): search "<agency> public records request" and use the method the agency publishes.

If the custodian cannot be identified, leave a bracketed placeholder in the draft and say so in the hand-back. Do not guess an email address.

## Step 4: Draft the request

Write it to a file (`records-request-<custodian>-<YYYY-MM-DD>.md`) headed **DRAFT ONLY — NOT SENT**, with sender name, address, email and phone as placeholders unless the user supplied them.

Contents, in order:

1. **Date, custodian's name and title, delivery method.**
2. **One opening sentence** invoking the Public Records Act, R.S. 44:1 et seq., and asking to inspect or receive copies.
3. **The records**, as a numbered list. Each item names a record type, the facility or permit (AI number, permit number), and a date range. Good items:
   - "All correspondence, including email and attachments, between LDEQ Air Permits Division staff and [applicant] or its consultants concerning permit application [number], from [date] to the date of this request."
   - "Inspection reports, field notes, and photographs from any inspection of AI [number] between [date] and [date] that are not posted in EDMS."
   - "Air dispersion modeling input and output files submitted with or prepared for [application], in their native electronic format."
   
   Avoid "any and all records relating to [company]". It is the request most likely to be called unduly burdensome under R.S. 44:32(A)(2).
4. **Format**: electronic copies by email or download link where the records exist electronically.
5. **Fees**: ask for a written estimate before any charge is incurred, and name a ceiling above which the custodian must ask first. If the user will use the records in a permit hearing or comment, and the custodian is a state agency, ask for the reduction R.S. 44:32(C)(2)(a) allows for public-purpose use and state that purpose in one sentence. Offer inspection in person as the no-fee alternative.
6. **Segregation**: if any part of a record is withheld, ask for the rest, and for the written determination and legal basis required by R.S. 44:32(D).
7. **Response**: ask for the records, or a written determination or time estimate, within the five days (excluding Saturdays, Sundays, and legal public holidays) that R.S. 44:35(A) sets, and give the calendar date that period ends ("by [date]"). Word it as a request. Section 44:35(A) is the point after which a requester may go to court, not a stated duty to produce by that day; the custodian's duties are in 44:32(D) and 44:33(B)(1). For the date, pull the list of legal holidays from R.S. 1:55 with `/bayou:la-rs-search` rather than recalling it.
8. **Contact line and signature block.**

Keep it to one page. Courteous and exact works better than combative: the custodian's staff decide how hard to look.

Do not add: a statement of why the user wants the records (other than the fee sentence), threats of suit in a first request, or legal argument about exemptions nobody has raised.

## Step 5: Hand back

Give the user:

- The draft file path.
- Where and how to send it (form URL, email, or mail), and whether the address was confirmed today or left as a placeholder.
- The date the five-day period runs, and a suggestion to put it on a calendar.
- What to do if nothing arrives: a short follow-up citing the original date, then, if still nothing, the mandamus route in R.S. 44:35, which needs a lawyer. This skill does not draft pleadings.

## Limits

- This is not legal advice, and the draft is not checked by a lawyer.
- The day counts and fee language in Step 2 are a snapshot. If `/bayou:la-rs-search` returns different text, the statute wins, and this file should be corrected.
- A request can alert an applicant: agencies sometimes tell a permittee who asked for its file. Tell the user this if they have said timing or confidentiality matters.

$ARGUMENTS
