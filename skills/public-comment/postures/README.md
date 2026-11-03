# Postures

A **posture** is the kind of decision a comment is aimed at. It decides these things:
- who the real reader is;
- whether standing is a gate;
- what each numbered request ends in;
- how findings rank;
- what the decision-maker owes in response;
- which clock ends the fight.

The **agency** (`references/agencies.md`) only decides where and how the comment is filed. The
same agency can act in more than one posture. FAA licenses launch sites (permit) and waives
statutes by regulation (rulemaking).

| File | Decision | Standing | Each request ends in |
|---|---|---|---|
| `permit.md` | issue, modify, or renew a specific permit or license | a hard gate where an aggrieved-person appeal exists | a draftable permit condition |
| `rulemaking.md` | adopt a rule of general applicability | an interest, not a gate | a rule-text, scope, or record edit |
| `financing.md` | approve public financing for a private project | an interest, not a gate; never an appeal statute | a record disclosure, a Bond Counsel statement, deferral, or transmittal |
| `land-use.md` | a parish or municipal rezoning, plat, variance, or land-use ordinance | an interest at the hearing, not a gate; the test for a later suit differs by instrument | a corrected step, a record item, a stated finding, a plat outcome, deferral, or denial |

## Adding a posture

Add a file only after a real filing in that posture exists, or, if none does, say at the top that the
file comes from primary sources and mark what isn't established. Don't name a private filing or its
location in the file. Every posture file carries the same sections,
so `SKILL.md` can point at them generically:

1. **Audience.** Who decides, what vocabulary they evaluate in, and how things actually fail
   in this forum. Point to the `permit-analysis` question-bank group that encodes the decision
   standard, where one exists.
2. **Standing / interest.** Say whether it is a gate. Give the section heading, and say what
   must never be cited.
3. **What each numbered request ends in.** Include two or more worked examples.
4. **Leverage tiers.** Tiers 1–3 for this posture, plus any Tier 4 additions to the shared
   list in `references/leverage.md`.
5. **Health-mechanism section.** Say whether it applies, and in what form.
6. **Identifiers.** Say what goes in the RE block and in `\filingid`.
7. **Relief-authority line.** Give the order of relief.
8. **Response owed and terminal clock.** Verify the clock against primary text before writing
   it down.
9. **Posture-specific QA.**

## Candidates not yet built

- **Enforcement petition:** an EPA/DOJ consent-decree complaint or a CAA § 304 60-day notice.
  Standing here is Article III injury, and the request is enforcement, not a condition.
- **Corporate grievance:** an OECD National Contact Point submission.
- **Utility rate case:** an LPSC docket.
