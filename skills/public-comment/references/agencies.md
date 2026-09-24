# Agency submission mechanics

**The permit's own public notice is authoritative.** It states the submission address, the
deadline, and the contact for that specific action. Always read it and prefer it over anything
here. This file covers what the notice usually leaves out — appeal windows, what the agency
produces in response, and how hearings get granted.

---

## LDEQ (Louisiana Department of Environmental Quality)

**Submission**
- Online through the LDEQ Public Notice webpage (`deq.louisiana.gov/public-notices`)
- Email: `DEQ.PUBLICNOTICES@LA.GOV`
- Mail: the address stated in the public notice for that action

**Always include** the company and/or facility name, the **AI number**, and the **activity
tracking number (PER…)**. LDEQ says so explicitly; a comment that cannot be matched to a
docket is a comment that may not reach it.

Customer Service Center: (225) 219-LDEQ.

**Deadlines** are commonly 4:30 p.m. Central on the stated date. Comments filed before the
deadline enter the administrative record. Late comments may not.

**What LDEQ produces in response**
- A **Basis for Decision**
- A **Public Comments Response Summary**

Both are reasons to number comments and to ask for itemized response — a numbered comment that
goes unanswered in the summary is visible on the face of the record.

**Public hearings** are discretionary except where regulation requires one. The usual standard
is that LDEQ finds "a significant degree of public interest," with no defined threshold. Argue
the showing rather than merely requesting: population within the affected area, number of
parishes, permit duration, hearing attendance, volume of correspondence. Note that LDEQ
distinguishes public *hearings* (comments enter the record, formal rules, hearing officer)
from public *meetings* (discussion format, comments do **not** enter the record). Only a
hearing preserves anything.

**Appeal** — La. R.S. 30:2050.21: an aggrieved person petitions the **19th Judicial District
Court** within **30 days** after notice of the action is given. Request written notice of the
final decision in the letter so that clock starts cleanly. Do not confuse this with
La. R.S. 30:2024, which governs the *applicant's* hearing request.

**Known record quirks worth checking every time**
- A permit may be absent from LDEQ's own live public-notices tracker even while its comment
  period is open. Check, and if it is missing, say so — it goes to notice adequacy.
- EDMS is the document system; the listing/search API works, but document *download* is
  reCAPTCHA-gated (`bayou:ldeq-edms-download` drives a real browser for bytes).
- Modeling files sometimes exist in EDMS but "cannot be displayed" through the standard
  interface. Ask for native files to be placed in the record.

---

## USACE (U.S. Army Corps of Engineers)

**Submission** — to the district that issued the public notice; for southeast Louisiana, the
**New Orleans District**. The notice states the file number, the comment address, and the
deadline (commonly 15–30 days, shorter than LDEQ's).

Reference the **permit application number** from the notice in the first line.

**Scope** — Section 404 (dredge/fill) and Section 10 (navigable waters). Section 408 covers
alterations to federally authorized works such as levees, and is a **separate** permission from
404/10; the absence of a 408 review for construction adjacent to a federal levee is its own
comment.

Corps decisions run on a public-interest review balancing test, and NEPA applies — so
alternatives analysis and cumulative-impact arguments have direct statutory purchase here in a
way they do not in a Louisiana minor-source air permit.

---

## LADENR / Office of Coastal Management (LADENR-OCM)

Coastal Use Permits. The notice states the CUP number and deadline. Consistency with the
Louisiana Coastal Resources Program is the operative standard, and the coastal-use guidelines
are the hook. Cross-reference CPRA Coastal Master Plan projects where a proposed activity
conflicts with planned restoration or risk-reduction work.

---

## FAA (Federal Aviation Administration)

FAA acts in two postures, and each takes a different route.

**Rulemaking** (`postures/rulemaking.md`), e.g. FAA-2026-8614:
- Submit through the Federal eRulemaking Portal, `regulations.gov`, under the docket number
  (FAA-YYYY-NNNN). The NPRM also lists mail, hand-delivery, and fax addresses.
- Put the docket number, notice number, and RIN in the first lines.
- The portal returns a **comment tracking number**. Keep it as proof of timely filing; the FAA
  campaign recorded it in its research memo.
- Comments are posted publicly, including anything personal in them.
- The NPRM usually closes with numbered questions. Answer them under their own labels.

**Licensing** (`postures/permit.md`): launch/reentry site and vehicle operator licenses under
14 C.F.R. Parts 420/433/450. Public participation mostly runs through the NEPA document for the
license (an EA or EIS comment period), not the license itself. The notice states the address.
Airspace and obstruction matters (Form 7460-1, Notice of Proposed Construction) run through a
separate aeronautical study process.

---

## LPFA and other Louisiana conduit bond issuers (`postures/financing.md`)

Covers LPFA, parish Industrial Development Boards, LCDA, and ports that issue on behalf of
private borrowers.

**Submission**
- A **written comment to the issuer's President/CEO** (the LPFA notice names the officer and
  gives a phone number), delivered **before** the TEFRA hearing. Ask that it be entered into
  the hearing record.
- Speaking at the hearing is optional. The written letter is what persists. Use
  `bayou:hearing-prep --oral` for a spoken version.
- There is no portal, docket, or tracking number. Keep proof of delivery.

**Put in the RE line** the bond series exactly as noticed and the hearing date. Once the State
Bond Commission publishes its agenda, add the **SBC docket number and item**.

**What the issuer produces:** nothing formal. There is no response summary, and IRC § 147(f)
requires none. Ask for:
- transmittal of the letter to the SBC;
- written notice of the board's action;
- written notice of the notice-of-sale publication date.

**Next venue: the State Bond Commission.**
- La. R.S. 9:2347(H) requires SBC approval for every public-trust bond issue.
- The SBC meets monthly and publishes a preliminary agenda with docket numbers ahead of each
  meeting. Check it; it may carry facts the notice does not, such as a "(Volume Cap)" caption.
- The SBC is chaired by the State Treasurer and made up of elected officials, so it answers to
  public pressure in a way the issuer's board does not.
- The interval between the TEFRA hearing and the SBC vote can be days, as with LPFA/HPLS (three
  days). Ask the issuer to transmit comments before the vote.

**Terminal clock:** La. R.S. 9:2347(G). The bonds become incontestable 30 days after
publication of the **notice of sale**, which comes after SBC approval and at least 7 days before
the sale. See `louisiana-hooks.md`.

---

## General, any agency

1. **Confirm the deadline from the notice itself.** Never from memory, never from a secondary
   summary. Never guess.
2. **Request written notice of the final decision** — it starts the appeal clock and confirms
   the agency has your address.
3. **Keep proof of timely submission** — the email, the portal confirmation, the postmark.
4. **File the whole thing before the deadline.** A brilliant comment filed late is not in the
   record, and nothing else in this skill matters if that happens.
