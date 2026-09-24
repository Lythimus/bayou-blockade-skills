# Pre-filing QA checklist

Run every item against the finished draft. These are the failures that survive careful
writing — do not skip on the theory that the draft was written carefully.

Report results to the user, including anything flagged that was deliberately left unchanged,
and why.

---

## Blocking — do not file until these pass

- [ ] **Deadline confirmed from the public notice itself**, not from memory or a secondary
      summary. Date, time, and time zone.
- [ ] **The posture is right, and the letter stays inside it.** The posture was named or
      inferred and confirmed, and its file was read. Under rulemaking or financing, grep for
      `2050.21`, `aggrieved`, `permit writer`, `Response Summary`, and `PER`. Each hit is either
      deliberate (quoting the underlying permit record) or a leak from the permit posture that
      costs credibility with this reader.
- [ ] **Standing or interest is stated** in its own section, under the heading and test the
      posture file names. Where standing is a gate, the connection to the covered area is one a
      hostile reader would accept, and if residence is outside the covered area, the connection
      that carries standing is explicit. Where interest is the test, distance is conceded and
      the interest is tied to what the action actually does.
- [ ] **Written notice of the final decision is requested**, with a correct mailing address,
      plus notice of whatever event starts the posture's clock (e.g. the notice of sale under
      the financing posture).
- [ ] **Contact details match the profile** — address and email — and match prior filings.
- [ ] **Every identifier the posture file lists appears in the RE block**, verbatim from the
      notice. Permit: applicant, AI, permit, activity/PER. Rulemaking: docket, RIN, Fed. Reg.
      cite. Financing: bond series as noticed, hearing date, SBC docket.
- [ ] **No fabricated citations.** Every case, statute, regulation, study, and document number
      either traces to a source that was actually read, or is removed.
- [ ] **No citation points to a pipeline artifact.** Grep the draft for `` `:[0-9]+` `` or
      `file:line` patterns, and for `ocr_txt/`, `verification/`, or `FINDINGS-FOR-REPORT.md`.
      Every record citation must resolve to a page number printed in the actual noticed
      document — never a line number or file path from a working OCR transcript that only the
      drafter can open.
- [ ] **No narrated processing methodology.** Grep for `DPI`, `OCR`, `text layer`, `page image`,
      `transcription`, `edit distance`, `cross-reader`. The letter states findings ("these
      figures do not reconcile," "I have retained copies of pp. X and Y") — never the technique
      used to extract or verify them from the scanned record. A regulator doesn't need to know
      how the sausage was made, and a sentence describing OCR/rendering/fuzzy-matching mechanics
      reads as insider tooling talk, not as an individual's plain reading of the record.
- [ ] **Every authority checked against `references/louisiana-hooks.md` or
      `references/federal-hooks.md`.** No authority described from memory or copied from a
      research memo unchecked. Nothing described as a win that was a loss. Every clock cites
      the statute that actually sets it, and names the event that starts it.

## Substance

- [ ] **Every criticism ends in the posture's endpoint.** Scan each numbered comment. Could
      the decision-maker's drafter implement it as written? That means a permit condition, a
      rule-text/scope/record edit, or a disclosure required before the vote. If not, rewrite
      it.
- [ ] **Comments are numbered**, numbering is continuous, and no number is reused.
- [ ] **Itemized response is requested** in the relief section. Where the posture owes no
      response, transmittal to the next venue is requested instead.
- [ ] **Tier 1 findings lead.** The first substantive part is the strongest legal defect, not
      the most emotionally compelling section.
- [ ] **Every relief item traces to a numbered comment** above it, and every Tier 1 comment
      appears in the relief list.
- [ ] **Record facts carry document number and page.** Outside facts name the source (no
      retrieval date by default).
- [ ] **Absence claims are quantified without a search-term list** — scope of what was
      searched and what was returned, not the literal keywords queried — rather than asserted.
- [ ] **Concessions are present** where the record cuts against the argument, stated plainly
      rather than buried.
- [ ] **Candor section exists** and states unresolved items as open questions, not facts.
- [ ] **Nothing from Tier 4** survives: no out-of-jurisdiction arguments, no unsourceable
      claims, no undisambiguated attributions, no general opposition without a cite.

## Voice

- [ ] **Reads as a concerned resident, not an opponent of industry.** Would this reader (the
      permit writer, rule staff, or an underwriter-minded board) classify it as substantive or
      as emotional opposition?
- [ ] **None of the phrasings listed under "avoid" in the profile appear**, in any variation.
- [ ] **Health content follows the posture file.** Where a section applies, it is mechanism,
      not just status, and is confined to that section. Under financing, health appears only
      as financed-asset or reputational risk.
- [ ] **Personal details are consistent with prior filings.** Cross-check names, conditions,
      distances, and relationships against the profile — inconsistency across public filings is
      free ammunition for opposing counsel.
- [ ] **The profile is not reproduced.** Only what this permit's pollutants and impacts
      actually bear on.

## Mechanics

- [ ] Submission address and method taken from the notice, and stated back to the user.
- [ ] Any attachment or exhibit referenced in the text actually exists and is named.
- [ ] Internal cross-references ("Part XI below," "the section quoted above") resolve to real
      sections after the last round of edits.
- [ ] If rendered to PDF: the PDF was generated from the final markdown, and the markdown
      remains the source of truth.
- [ ] **The RE/letterhead block and the closing signature block each end every line but the
      last in a trailing `\`.** Without it, single newlines between these short lines are just
      word spaces to pandoc, and the whole block silently collapses into one run-on paragraph
      in the rendered PDF — it still reads fine in the raw markdown, so this only shows up on
      inspection of an actual render. Check both blocks after any edit that touches them.
