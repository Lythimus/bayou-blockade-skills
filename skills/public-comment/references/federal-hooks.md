# Federal legal hooks: status and traps

Federal authorities used outside a state permit: rulemaking procedure, enabling statutes that
carry conditions, and the tax law behind conduit bonds. The same rules apply as in
`louisiana-hooks.md`:
- check every entry here before citing it;
- **never characterize an authority from memory**;
- add new entries only after verifying them against primary text (Cornell LII, govinfo.gov,
  eCFR, uscode.house.gov), with the date.

Federal provisions applied *through* a state permit (40 C.F.R. § 60.18 and similar) stay in
`louisiana-hooks.md`.

---

## Rulemaking procedure (`postures/rulemaking.md`)

### 5 U.S.C. 553(c): notice-and-comment participation
**Status: live. Verified at Cornell LII, 2026-09-24.** "After notice required by this section,
the agency shall give interested persons an opportunity to participate in the rule making
through submission of written data, views, or arguments…" The same subsection requires the
agency to incorporate in the adopted rule "a concise general statement of their basis and
purpose."

**Use:** this is the authority line for relief in a federal rulemaking comment. It is also the
footing for asking the agency to respond to each numbered comment.

**The trap:** 553(c) does not itself say "respond to every comment." The duty to answer
*significant* comments comes from arbitrary-and-capricious review of the final rule. Cite it as
a duty the agency owes significant comments, not as a statutory right to an itemized reply.

### 5 U.S.C. 553(e): petition to amend or repeal
**Status: live. Verified at Cornell LII, 2026-09-24.** "Each agency shall give an interested
person the right to petition for the issuance, amendment, or repeal of a rule."

**Use:** a door that stays open after the final rule, whatever the challenge window. Mention it
in the report to the user, not in the letter.

### 51 U.S.C. 50905(b)(2)(C): commercial space waiver authority
**Status: quoted from the statute in FAA-2026-8614 comment, 2026-08.** The Secretary may
prescribe that a requirement of law is not a requirement for a license or permit "if the
Secretary, after consulting with the head of the appropriate executive agency, decides the
requirement is not necessary to protect the public health and safety, safety of property, and
national security and foreign policy interests of the United States."

**Use:** the pattern generalizes. **When an enabling statute conditions an action on a finding,
check whether the preamble actually makes that finding.** "Decides… is not necessary" is not
satisfied by "may not be necessary in some or all circumstances." This was the FAA letter's lead
argument.

---

## Tax-exempt bond law (`postures/financing.md`)

All entries below were verified against full text pulled to
`petro/hyundai-posco/loans/sources/` on 2026-09-11. Re-verify if the provision has been amended
since.

### 26 U.S.C. 147(f): TEFRA public approval
**Status: live. Verified at Cornell LII, 2026-09-24.** A private activity bond is not a
qualified bond unless the issue is approved by the issuing governmental unit and by each unit
with jurisdiction over the facility's location. Approval must come "by the applicable elected
representative … after a public hearing following reasonable public notice," or by voter
referendum.

**The trap:** the statute requires a hearing and approval, and **no response to comments**. The
hearing record is a paper trail, not a docket the issuer must answer. Ask for transmittal to
the next venue instead.

**An open question worth asking:** who the "applicable elected representative" is for a given
issue. For a statewide conduit issuer it is often an elected state official, not the board.

### 26 U.S.C. 142(a)(6): solid waste disposal facilities
**Status: live.** This is the exempt-facility category and its definition, elaborated in Treas.
Reg. § 1.142(a)(6)-1 below.

### 26 U.S.C. 146(a): volume cap ⚠️ **the mis-citation to check on every TEFRA notice**
**Status: live.** § 146 is titled "Volume cap." § 146(a) says a private activity bond meets "the
requirements of this section" if the aggregate face amount does not exceed the issuing
authority's volume cap. **It defines no facility type.** The phrase "solid waste disposal
facilities" appears in § 146 only in the heading of subsection (h).

**The trap, in the notice rather than in the commenter:** issuers' notices sometimes describe
the financed property as "solid waste disposal facilities within the meaning of Section 146(a)."
That cites the volume-cap rule as if it were the definition. Point it out, and ask Bond Counsel
to state which provision it actually relies on.

### 26 U.S.C. 146(g) and (h): exceptions from the volume cap
**Status: live.**
- **§ 146(g)** excludes bonds described in listed paragraphs of § 142(a), such as airports and
  docks. **§ 142(a)(6) solid-waste bonds are not among them**, so they are subject to the volume
  cap by default.
- **§ 146(h)** carries a government-owned solid-waste exception. It applies only "if all of the
  property to be financed by the net proceeds of such issue is to be owned by a governmental
  unit." Leased property can qualify through the § 142(b)(1)(B) safe harbor, which requires all
  three of the following:
  - an irrevocable lessee election not to claim depreciation or an investment credit;
  - a lease term capped at 20 years, or 80% of economic life;
  - no purchase option except at fair market value.

**The trap:** research summaries sometimes say exempt-facility bonds "bypass" volume caps. That
is wrong for § 142(a)(6). Check the State Bond Commission agenda caption; the LPFA/HPLS bond was
captioned "(Volume Cap)."

### Treas. Reg. § 1.142(a)(6)-1: what counts as a solid waste disposal facility
**Status: live. Full text verified from govinfo.gov.** These are the tests that decide whether
specific financed assets qualify:
- **§ (c)(2)(i), the virgin-material exclusion.** Solid waste excludes material that has "not
  been processed into an agricultural, commercial, consumer, governmental, or industrial
  product," including material "grown, harvested, mined, or otherwise extracted from its
  naturally occurring location." Example 3 (logs) illustrates it. **Qualifier:** the exclusion
  opens "Except to the extent that virgin material constitutes an input to a final disposal
  process or residual material." State it accurately, because bond counsel will.
- **§ (d)(3)(i), where the recycling process ends.** It "ends at the point of completion of
  production of the first useful product from the solid waste."
- **§ (e), the first useful product.** Operational constraints can move the cut-off point, but
  costs of extracting, storing, and transporting to market count "only … if the product is not
  to be used as part of an integrated manufacturing or industrial process in the same location."
  Example 8 (paper pulp vs. industrial rolls vs. retail towels) illustrates it.
  **Pin-cite trap:** the cut-off rule is in (d)(3)(i). (e) is the definition. A draft of the
  LPFA letter cited (e) for the cut-off.
- **§ (g)(2), mixed inputs.** The eligible cost is capped at the actual percentage of solid
  waste by weight or volume. The exception is when that percentage is at least 65% "for each
  year that the issue is outstanding," which makes the whole cost eligible. The requirement
  covers every year, not just one.
