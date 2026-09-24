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

## Adding a posture

Add a file only after a real campaign has produced a filed document in that posture, and name
that document at the top as the worked example. Every posture file carries the same sections,
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

The petro campaigns have produced these, but no comment-shaped filing has come out of them yet:
- **Local land use / ordinance:** parish council rezoning or a future land-use map amendment
  (IMTT, UBE C1), or an ordinance (scp-prr-fees). The oral side of this is covered by
  `bayou:hearing-prep`.
- **Enforcement petition:** an EPA/DOJ consent-decree complaint or a CAA § 304 60-day notice
  (shell-norco-26-flare). Standing here is Article III injury, and the request is enforcement,
  not a condition.
- **Corporate grievance:** an OECD National Contact Point submission (lotte-oecp-report).
- **Utility rate case:** an LPSC docket (Waterford ratepayer material).
