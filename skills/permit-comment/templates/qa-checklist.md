# Pre-filing QA checklist

Run every item against the finished draft. These are the failures that survive careful
writing — do not skip on the theory that the draft was written carefully.

Report results to the user, including anything flagged that was deliberately left unchanged,
and why.

---

## Blocking — do not file until these pass

- [ ] **Deadline confirmed from the public notice itself**, not from memory or a secondary
      summary. Date, time, and time zone.
- [ ] **Standing is stated** in its own section: who the commenter is, and a connection to the
      permit's covered area that a hostile reader would accept. If residence is outside the
      covered area, the connection that carries standing is explicit.
- [ ] **Written notice of the final decision is requested**, with a correct mailing address.
- [ ] **Contact details match the profile** — address and email — and match prior filings.
- [ ] **Every permit identifier from the notice appears in the RE block**: applicant name, AI
      number, permit number, activity/PER number.
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
- [ ] **Every case characterization checked against `references/louisiana-hooks.md`.** No
      authority described from memory. Nothing described as a win that was a loss.

## Substance

- [ ] **Every criticism ends in a draftable condition.** Scan each numbered comment: could a
      permit writer paste the request into the permit? If not, rewrite it.
- [ ] **Comments are numbered**, numbering is continuous, and no number is reused.
- [ ] **Itemized response is requested** in the relief section.
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

- [ ] **Reads as a concerned resident, not an opponent of industry.** Would a permit writer
      classify this as substantive or as emotional opposition?
- [ ] **None of the phrasings listed under "avoid" in the profile appear**, in any variation.
- [ ] **Health content is mechanism, not just status**, and is confined to its own section
      rather than diffused through the document.
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
