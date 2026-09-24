# Posture: permit or license decision

An agency deciding whether to issue, modify, or renew a specific permit or license for a
specific facility or activity: LDEQ air/water/solid-waste permits, USACE Section 404/10,
LADENR/OCM Coastal Use Permits, LADENR Class VI, LDOTD, an FAA site or operator license.

Worked examples in `~/Documents/personal/petro/`:
- `hyundai-posco/PUBLIC-COMMENT.md` (LDEQ Part 70/PSD, tiered)
- `exxonmobil-pipeline-flare/PUBLIC-COMMENT-v3.md` (LDEQ statewide flaring, standing on the
  covered-parish list)

---

## Audience

Two readers:
1. **The permit writer**, who must produce a response-to-comments document.
2. **A reviewing judge**, reading the administrative record later to decide whether issuance was
   arbitrary and capricious.

Write for the second one. The permit writer's cheapest path should be to adopt the condition
you drafted.

**What each agency actually weighs is already encoded in the `permit-analysis` question bank.**
Use the group that matches the agency as the lens for ordering and framing arguments, instead
of re-deriving it:

| Agency | Question-bank group(s) that carry its decision standard |
|---|---|
| LDEQ | `eas-it-questions` (the *Save Ourselves* IT factors: avoidance, cost-benefit, alternatives), the air/water/waste groups for the program, and `public-process` |
| USACE | `usace-public-interest` (public-interest balancing) and `wetlands-404` (404(b)(1) practicable alternatives) |
| LADENR/OCM | `coastal-cup` (coastal-use guidelines and consistency with the state coastal program) |
| LADENR/DCE Class VI | `class-vi-uic` and `financial-assurance` |
| FAA (license) | the `FAA` rows in `local-infrastructure` and `applicant-history` |

## Standing

**Standing is a hard gate wherever the agency's decision carries an aggrieved-person appeal.**
For LDEQ that is La. R.S. 30:2050.21: only an aggrieved person may appeal a final permit action,
to the 19th JDC, within 30 days of notice. A comment with no stated interest can be answered
without reaching the merits and leaves nothing to appeal.

Cross-check the permit's covered parishes (or the facility location) against the profile's
parish-reach table. That comparison produces the standing statement. If the profile shows
**no** connection to the covered area, stop and tell the user. Never invent proximity.

Section heading: **"Commenter and standing."**

For USACE, OCM and FAA licenses the appeal route differs (see `references/agencies.md`), but
the rule is the same: state a concrete, particularized interest tied to the permit's own
footprint.

## What each numbered comment ends in

**A draftable permit condition**: text a permit writer could paste into the permit.

- "Add an exit-velocity condition consistent with 40 C.F.R. § 60.18(c)(4)" is actionable.
- "Require quarterly fenceline benzene monitoring under Method 325A/B, with results posted
  within 30 days" is actionable.
- "This permit is inadequate" is not.

The other acceptable endpoints are a specific record demand (native modeling files, a legible
copy of a page) and denial.

## Leverage tiers

The posture-neutral principle and the Tier 4 cut list are in `references/leverage.md`. The
permit-specific tiers follow.

### Tier 1: changes the permit

These findings create legal exposure for the agency itself. Fixing them is cheaper than defending
them, which is exactly why they work.

| Finding type | Why it lands |
|---|---|
| **A mandatory application element is missing** | The application should not have been deemed complete. Cite the regulation that requires the element and note the completeness determination date. This forces either a waiver on the record or a remand. |
| **A permit condition cannot be complied with as written** | Examples: an undefined baseline, an undefined term, a cross-reference to something that does not exist. An unenforceable condition is an appeal issue the agency created for itself. |
| **The permit cites a regulatory subsection whose predicate is not satisfied** | Example: a relocation provision that presupposes an already-approved location, where no approved location exists. Either the citation is wrong or the permit is, and both are the agency's problem. |
| **A limit the agency relied on exists only in narrative** | If the tonnage basis, throughput, or control assumption appears in a briefing sheet or spreadsheet but not in enforceable conditions, the demonstration rests on nothing. |
| **Internal contradiction that changes an applicability determination** | Examples: two throughput figures, two hours bases, a speciation that exceeds its own cap. This is especially potent where a number sits just under a major-source, MACT, or PSD trigger. |
| **Monitoring cannot verify the limit it is attached to** | Opacity does not measure benzene. Annual averages cannot constrain hourly exposure. Name the limit, name the monitoring, and show the gap. |
| **The agency's own staff raised the problem in writing and it was not resolved** | An unresolved internal technical objection in the record is the strongest single item a comment can carry. Quote it exactly. |

**Drafting rule:** each Tier 1 finding ends in the specific condition that cures it.

### Tier 2: builds the record

These may not change this permit. They preserve the issue, constrain the next permit, and create
the appeal.

- **Issue preservation.** An issue not raised in comments generally cannot be raised on appeal.
  Every colorable objection goes in, even briefly.
- **The agency's own prior regulation, decision, or practice, used against this action.** A
  regulation the agency wrote for this exact activity and is now bypassing. A prior denial on
  facts that have since gotten worse. A per-event mechanism the applicant used for years and
  then abandoned.
- **Documented compliance and enforcement history against a blank or minimal disclosure.** The
  gap between the enforcement record and what the application discloses is the finding.
- **Requests to place specific documents in the record.** Native modeling files, a legible copy,
  a referenced worksheet that is not in the docket.
- **Public-notice defects.** Misclassification, inconsistent permit numbers, the permit missing
  from the agency's own tracker.

### Tier 3: moves discretion

- **Standing and affected-person narrative.**
- **Hearing request with an actual showing.** Argue population, parishes, and permit duration;
  do not just ask.
- **Health mechanism tied to the permit's named pollutants** (see below).
- **Cumulative burden and environmental-justice data.** Strongest when a gap in the record makes
  the analysis impossible.
- **Alternatives that were never evaluated.** Name specific, commercially available ones.

## Health-mechanism section

**Applies** wherever the permit's pollutants bear on the household. One bounded section: what
the pollutant does inside a body, then who is standing in front of it.

## Identifiers (RE block and `\filingid`)

Applicant legal name · AI number · permit number · activity/PER number · permit type as stated
in the notice. For USACE: the permit application number (MVN-…). For OCM: the CUP number
(P2…).

## Relief-authority line

"Under the authority of the Louisiana Environmental Quality Act, La. Const. art. IX § 1, and
[the federal program statute]…"

List the relief in this order:
1. Hearing (with the showing).
2. Denial.
3. In the alternative, the drafted conditions.
4. Itemized response to each numbered comment.
5. Written notice of the final decision.

## Response owed and terminal clock

- LDEQ produces a **Basis for Decision** and a **Public Comments Response Summary**. Numbered
  comments make a skipped one visible.
- **Clock:** 30 days from notice of the final action (R.S. 30:2050.21), which is why the letter
  requests written notice.

## Posture-specific QA

- Every identifier from the notice (AI, permit, activity/PER) is in the RE block.
- Every criticism ends in a condition a permit writer could paste into the permit.
- Standing ties to the permit's covered area in a way a hostile reader would accept.
