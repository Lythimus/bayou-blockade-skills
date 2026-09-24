---
name: public-comment
description: Turn research findings plus the private Bayou Blockade profile into a filed-ready public comment for any decision-maker — a permit or license (LDEQ, USACE, LADENR/OCM, LDOTD, FAA), a rulemaking (federal NPRM, Louisiana Register), or a public financing approval (LPFA/TEFRA bond hearing, State Bond Commission). Selects a posture that sets standing, what each numbered request ends in, the leverage tiers, and the terminal clock; produces a standing/interest statement, numbered requests, an enumerated relief list, and a candor section — then optionally renders a styled PDF. Use after /bayou:permit-analysis, or after any research memo, when it is time to write the actual comment.
argument-hint: <findings-or-memo-path> [more paths...] [--posture <permit|rulemaking|financing>] [--agency <ldeq|usace|ladenr|faa|lpfa|other>] [--revise <existing-draft>] [--deadline <date>] [--slug <name>] [--render] [--no-profile]
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, AskUserQuestion, Skill, WebSearch, WebFetch
---

# bayou:public-comment — findings to filed comment

`bayou:permit-analysis` ends at `verification/FINDINGS-FOR-REPORT.md`: an evidentiary
backbone, one bullet per finding, written for whoever drafts the comment. Not every fight runs
through that pipeline. A rulemaking or a bond hearing usually starts from a research memo and
the noticed document itself. This skill is the drafter for all of them. It converts findings
into a document the decision-maker has to deal with.

**The craft is shared; the posture is not.** Citation discipline, voice, the candor section,
revise mode, QA and rendering are the same for every comment. What changes with the kind of
decision — who the real reader is, whether standing is a gate, what each numbered request ends
in, how findings rank, what response is owed, and which clock ends the fight — lives in one
posture file per decision type.

Bundled in this skill's directory:

- `postures/README.md` — what a posture is and the table of them. Then exactly one of:
  - `postures/permit.md` — permit or license decisions (LDEQ, USACE, OCM, Class VI, FAA
    license).
  - `postures/rulemaking.md` — rules of general applicability (APA NPRM, La. Register).
  - `postures/financing.md` — public financing approvals (TEFRA hearing, conduit issuer, State
    Bond Commission).
- `references/leverage.md` — **what actually changes a decision**: the principle, the shared
  Tier 4 cut list, and the structural multipliers. The posture file carries Tiers 1–3.
- `references/louisiana-hooks.md` — Louisiana authorities with current status and the trap
  attached to each. Contains at least one case that reads as helpful and is not.
- `references/federal-hooks.md` — federal authorities outside a state permit (APA, enabling
  statutes with conditions, tax-exempt bond law), same format.
- `references/agencies.md` — per-agency submission mechanics, deadlines, what the agency
  produces in response.
- `templates/comment.md` — the letter skeleton.
- `templates/qa-checklist.md` — the pre-filing pass.

Real comments in this style, all filed (paths under `~/Documents/personal/petro/`): Waterford 5
& 6 (Entergy, Part 70/PSD/Acid Rain), River Birch Avondale (solid waste major mod), Air
Products Clean Ammonia / LCEC (Part 70 + PSD), ExxonMobil Pipeline statewide flaring (minor
source), Hyundai-POSCO (LDEQ Part 70/PSD), FAA-2026-8614 (rulemaking), and the LPFA TEFRA
hearing for Hyundai-POSCO (financing). Waterford supplies the structure; River Birch supplies
the opening move; Air Products supplies the health-mechanism section and also the three
phrasings this skill refuses to reproduce; FAA shows interest-without-standing; LPFA shows the
translation into underwriter terms. Each posture file names its own worked example.

## Parsing arguments

Positional arguments are paths to the evidence. Any of these is acceptable:
- **A findings report.** Normally `verification/FINDINGS-FOR-REPORT.md`, optionally with
  `RESEARCH-TODO.md` (which feeds the candor section) and any section files worth reading in
  full.
- **A research memo.** For example, `context-and-precedent.md` from the FAA campaign, or a
  verification report like `LPFA-TEFRA-COMMENT-VERIFICATION-….md`.
- **The noticed document itself.** For example, the NPRM, or the bond hearing notice.

If nothing is passed, look for `verification/FINDINGS-FOR-REPORT.md`, then for any `*.md` memo
next to the notice, and ask before proceeding.

Flags:

- `--posture <permit|rulemaking|financing>` — the kind of decision. **If absent, infer it from
  the notice:**
  - a docket number, RIN, "proposed rule," or a La. Register notice of intent → `rulemaking`;
  - TEFRA, "public hearing" on bonds, a conduit issuer, or a State Bond Commission docket →
    `financing`;
  - otherwise → `permit`.

  State the inference to the user in one line. **Ask if it is ambiguous.** A permit and a
  rulemaking by the same agency look alike at a glance, and they are argued differently.

- `--revise <path>` — an existing comment draft to improve rather than replace. Switches the
  skill into revise mode (Step 5R below). **This is the common case once a draft exists** —
  drafting from findings alone discards synthesis work the findings file does not contain.
- `--deadline <date>` — the comment deadline. If absent, look for it in the findings doc or
  the project `CLAUDE.md`; if still absent, **stop and ask.** Never guess a deadline.
- `--agency <ldeq|usace|ladenr|faa|lpfa|other>` — who receives the comment. It selects only the
  submission-mechanics block in `references/agencies.md`. Defaults to `ldeq` under the permit
  posture. Under any other posture there is no default: take it from the notice.
- `--slug <name>` — output basename. Defaults to `PUBLIC-COMMENT`.
- `--render` — after the markdown is final, run Step 9 to produce a styled PDF.
- `--no-profile` — draft without the private profile. **This forfeits the standing/interest
  section.** Only honor it if the user confirms they are filing anonymously or on someone
  else's behalf.

## Step 1 — Confirm you have what you need

Before drafting, you need all of these:
- the evidence;
- a confirmed deadline, or hearing date;
- a posture;
- a named agency or issuer;
- a readable profile.

If any is missing, stop and ask. A wrong deadline or an invented personal detail is worse than
a delay.

**Read the posture file now, in full.** Every later step defers to it on standing, ask
endpoints, tiers, identifiers, and the clock.

Read the evidence in full. Read `RESEARCH-TODO.md` if present. Do not start writing from a
partial read. This skill's whole value is cross-checking findings against each other, and that
needs the whole corpus in view at once.

**The inputs have distinct roles and are never merged.**

| Input | Role | Owner |
|---|---|---|
| `FINDINGS-FOR-REPORT.md` or a research memo | Evidentiary backbone: what is true, with citations | `bayou:permit-analysis`, or whoever wrote the memo |
| `RESEARCH-TODO.md`, or the memo's own open-items / caveats section | Unresolved items. Feeds the candor section | `bayou:permit-analysis`, or the memo's author |
| The noticed document | The record the comment cites by its own printed page | the agency |
| `--revise <draft>` | Prose synthesis: how it was argued | this skill |

Never write prose into the findings file, the memo, or the TODO file, and never fold them into
the letter wholesale. The `verification/` set has its own role-ownership and flag conventions
(see the campaign's `CLAUDE.md`); merging a draft into it breaks the pipeline that regenerates
it. Findings supply the evidence; the draft supplies the architecture; the letter is the third
artifact, not a merge of the first two.

## Step 2 — Read the private profile, and establish standing or interest

Read `~/.claude/bayou-profile.md` with `Read`. If it does not exist, **stop** and tell the
user to fill in `../nextdoor-campaign/profile.example.md` and save it there. Do not read
profile content from any other path — not an old draft, not another project directory, not a
prior filed comment — even if you know one exists. The fixed path is the point.

Then do the thing this skill exists for:

**Cross-check what the action reaches against the profile's parish-reach table.** For a
permit, that is the covered parishes or the facility's location. For a rule, it is the
provisions it changes and where they apply. For a financing, it is the host parish and the
state fisc. That comparison produces the commenter section. **The posture file's "Standing /
interest" section governs what the comparison must show and what the section is called.**

- **Where the posture makes standing a gate** (permit decisions carrying an aggrieved-person
  appeal, such as La. R.S. 30:2050.21 for LDEQ), a comment with no stated interest can be
  answered without reaching the merits, and it leaves nothing to appeal. If the profile shows
  **no** connection to the covered area, say so plainly to the user and ask how they want to
  proceed. Do not invent proximity, and do not quietly file without standing.
- **Where the posture makes interest the test, not a gate** (rulemaking, financing), do not
  stop for lack of proximity. Concede distance plainly, then tie the interest to what the
  action actually does. The FAA letter is the model: "I don't live in Vermilion Parish…" and
  then the coastal-zone and general-conformity provisions that reach the commenter's own
  parish.
- **Never import one posture's standing statute into another.** An LDEQ appeal statute cited to
  a bond board or in a rulemaking is a visible error that costs the whole letter.

Pull only what the action's actual pollutants and impacts bear on. A flare permit emitting
carcinogens calls for the cancer histories; a discharge permit does not. A bond board calls for
the taxpayer and family-in-parish facts, and none of the medical history. Never echo the whole
profile into the letter.

**If the profile carries a `Faith & Congregation` section** and the named congregation or its
cemetery lies within the action's affected area, treat **recurring physical presence** there as
a proximity and exposure fact for the standing statement, on the same footing as residence and
family health history. "I am present at [congregation], N miles from the proposed site and
inside the modeled impact area, most weeks" is a concrete, particularized interest; under the
permit posture it is an aggrieved-person allegation under La. R.S. 30:2050.21. An affiliation
alone is neither. Use the profile's own "what
you're comfortable being called publicly" field for the wording, verbatim in substance.

**Hard constraint on voice: never assert the commenter's religious affiliation beyond what the
profile's own-affiliation field states.** If that field says "attend, not a member," the letter
says the commenter attends — it does not say the commenter is Catholic (or any other faith),
and it does not write in the first person about religious belief. This is the same rule this
Step already applies to every other invented personal detail; it is called out separately here
because faith language drifts toward profession of belief more easily than most.

## Step 3 — Rank the findings by leverage

Read `references/leverage.md` for the principle and the shared Tier 4 list. Then sort every
finding using **the posture file's tier tables**. This governs the letter's architecture:

- **Tier 1 findings lead.** They create legal exposure for the decision-maker itself: a defect in
  a permit, a rule's statutory predicate that is not met, a classification Bond Counsel cannot
  opine on.
- Tier 2 findings build the record and preserve issues for the next venue.
- Tier 3 findings move discretion: the hearing, deferral, the scrutiny level.
- **Tier 4 material is cut**, even when true, because it costs more than it earns. Some posture
  files add to the shared list.

Under the financing posture, a finding that cannot be translated into risk to the financed
asset, or to the tax exemption, is Tier 4 for that letter, however strong it is in the permit
fight.

Report the ranking to the user before drafting if there are more than ~8 findings, so they can
override. Their judgment on what matters locally beats the tier table.

## Step 4 — Check every legal authority against the hooks files

Check any statute, regulation, or case against `references/louisiana-hooks.md` or
`references/federal-hooks.md` before citing it. Those files record current status and the
specific trap attached to each authority. At least one Louisiana case in this area reads as
favorable and is not: it reversed in the applicant's favor, and citing it as a win has already
happened once in a filed comment. At least one bond-law clock has already been stated with the
wrong statute and the wrong trigger in a draft.

If an authority is not in either file, verify it live before citing it. Use
`bayou:la-rs-search` or `bayou:lac33-search` for Louisiana, and Cornell LII, govinfo, eCFR, or
WebSearch for federal law. Then add it to the right file with its status and date. **Never
characterize a case or statute from memory, and never copy one from a research memo or AI
research report without checking the primary text.**

## Step 5 — Build the skeleton

Follow `templates/comment.md`. The order is deliberate:

1. **Letterhead.** Date, RE line, and every identifier the posture file lists: AI, permit,
   and activity numbers for a permit; docket, RIN, and Fed. Reg. cite for a rule; bond series,
   hearing date, and SBC docket for a financing.
2. **Statement of comment and relief requested.** What you want, in the first 150 words.
   Decision-makers triage by this paragraph. Under the financing posture this becomes a
   numbered "Requested relief" block at the top, each item pointing to its section.
3. **Commenter and standing / interest.** Use the heading the posture file names. Cover who you
   are, who is affected, where they are relative to what the action reaches, and the request
   for written notice of the decision. Where the profile carries a `Faith & Congregation`
   section that reaches the affected area, recurring physical presence goes in here (Step 2).
   This is also the only place a single sentence of moral framing may appear (see the capped
   allowance below), never in a numbered comment.
4. **Summary of the argument.** The two or three facts that add up to the central objection.
5. **Numbered substantive parts.** Tier 1 first. Each part ends in a numbered **Comment N**
   stating what is requested, in the form the posture file's "ends in" section requires.
6. **Relief requested.** Enumerated, with the posture's authority line in the lead sentence.
   Under the financing posture the enumerated list already sits at item 2, so this becomes the
   closing: transmittal to the next venue, the clock, and the request for notice.
7. **Limits of the present record.** The candor section (Step 7).
8. **Signature.** Name, address, and email from the profile.

**Moral framing is capped at one sentence, and only here.** When the profile names a
congregation the user is willing to have named, a single sentence drawing on *Laudato Si'* or
the ITC's *Caring for Our Common Home* (Sept 2, 2026) — including its reframing of ecological
sin as "sin against creation and against the Creator" — may appear once, in the standing
section (item 3) or the closing paragraph before the signature, and nowhere else. **Frame it as
teaching held by the affected congregation or stated by the diocese, never as the commenter's
own profession of faith**: "The parish I attend with my family holds…" or "The Diocese of
[name] has said…" — never "As a Catholic, I believe…". Leading with theology, or repeating it,
invites the agency to characterize the entire filing as non-substantive sentiment rather than a
comment it must answer on the merits — that is the whole reason for the cap.

**Letterhead and signature are stacked short lines, not prose** — each needs a trailing `\`
(pandoc hard line break) at the end of every line but the last in the block. A plain single
newline is just a word space in markdown, so without it `templates/comment.md`'s own RE block
or the closing signature run together into one paragraph in the rendered PDF (Step 9) — easy
to miss because the `.md` still reads fine unrendered, and it only shows up after a full
pandoc pass. Check both blocks specifically when reviewing a rendered PDF.

## Step 5R — Revise mode (`--revise`)

Replaces Step 5 when an existing draft is supplied. **Improve the draft; do not regenerate
it.** A prior draft encodes decisions the findings file does not record — which findings
compound into the central objection, which concessions were made and where, the citation
convention, the register. Rebuilding from findings discards all of it and usually lands
somewhere worse.

Read the existing draft **in full, before** doing anything else, then:

1. **Preserve unless there is a reason.** Argument architecture, section order, prose voice,
   worked concessions, and the record-vs-outside citation convention stay as they are. The
   burden is on changing them, not on keeping them.
2. **Diff against the findings.** Two directions, both matter:
   - findings not represented in the draft — candidates to add, ranked by tier;
   - claims in the draft not supported by the findings — verify or cut. A claim that survived
     an earlier pass is not thereby verified.
3. **Apply the structural additions** the draft is likely missing. A from-scratch skeleton
   supplies these and an organically grown draft usually lacks them. **Take them from the
   posture file, not by habit**:
   - the standing or interest section;
   - the health-mechanism section, only where the posture calls for one;
   - the candor section;
   - the authority line in the relief list;
   - the explicit request for an itemized response, or, where no response is owed, for
     transmittal to the next venue.
4. **Run every authority through the hooks files** (Step 4). Revise mode is where miscited case
   law and wrong clocks get caught, because the draft was written before the reference file
   existed. **Also grep for authorities imported from the wrong posture**, such as
   `2050.21`, "aggrieved," "permit writer," or "Response Summary" in a rulemaking or financing
   letter.
5. **Re-order only on a material tier violation.** If a Tier 1 finding is buried behind Tier 3
   material, move it and say so. Otherwise leave the order alone — reshuffling a working
   argument to match a table is how a good draft gets worse.
6. **Never silently soften or drop a finding.** If research has undercut something, narrow it
   and state what changed and why, in the letter or the report-back. Stale text sitting next
   to newer contradicting evidence is the one failure mode worse than an unaddressed gap.
7. **Grep the existing draft for leaked pipeline artifacts.** An organically grown draft is
   where these accumulate — a findings bullet pasted in wholesale, or an earlier pass that
   skipped the page-resolution step. Search for `` `:[0-9]+` ``, `file:line` patterns, and any
   mention of `ocr_txt/`, `verification/`, or `FINDINGS-FOR-REPORT.md`. Resolve each to the real
   page (see Step 6) rather than deleting the citation outright — the underlying fact is usually
   still good, only its pointer is unusable to the public.
8. **Then grep for narrated processing methodology — a different leak.** A pointer leak (#7)
   names a *location*; this one names a *technique*: OCR passes, image DPI, "text layer" vs.
   "page image" comparisons, structure-aware transcription, cross-reader/cross-model agreement,
   edit-distance or fuzzy-matching scans. Search for `DPI`, `OCR`, `text layer`, `page image`,
   `transcription`, `edit distance`, `cross-reader`. Unlike #7 there is usually no page to
   resolve to — this is content to cut, not a pointer to fix. Keep only the finding the sentence
   was supporting, restated as a plain fact with no method attached.

**Write to a new file** rather than overwriting the draft — `<slug>-vN.md` or the `--slug`
value — so the prior version survives for comparison.

Report back as a **changelog, not a document**: what was added, what was cut and why, what was
re-ordered, what was corrected, and what was left alone deliberately. On a 500-line letter the
user needs to review deltas, not re-read the whole thing.

## Step 6 — Write each substantive part

Every part follows the same internal shape: **what the record says → why it fails → what to
do about it.**

Rules that are not negotiable:

- **Every criticism terminates in something the decision-maker can do, in the form the
  posture file's "ends in" section names.** Examples of what counts:
  - **Permit:** a draftable permit condition. "Add an exit-velocity condition consistent with
    40 C.F.R. § 60.18(c)(4)."
  - **Rulemaking:** a rule-text or scope edit. "Delete 'including, but not limited to' from the
    description of the class," or "limit § 400.3(a) to federal launch sites."
  - **Financing:** a record disclosure or Bond Counsel statement before the vote. "Require the
    Company to disclose the percentage of Melt Shop throughput that will be scrap rather than
    DRI from virgin ore."

  What does not count: "this permit is inadequate," "this rule is bad policy," "this project
  is not in the public interest." A request the decision-maker's own drafter can implement is a
  request that gets implemented.
- **A numbered comment may never rest on a religious or moral premise.** Theology cannot
  generate a draftable condition, rule edit, or disclosure, so it cannot satisfy the rule
  above. Where a congregation, cemetery, or burial ground is the subject, make the argument as church-as-receptor,
  NHPA §106 consulting-party status, LDEQ's church buffer zone, or the Unmarked Human Burial
  Sites Preservation Act instead — each of those *can* end in a condition. The one sentence of
  moral framing this skill permits belongs only in the standing section or the closing
  paragraph (Step 5), never inside a numbered **Comment N**.
- **Every factual assertion carries a citation, and record facts are visibly distinguished
  from outside facts.** Record: document number, page, section. Outside: name the source
  (EPA ECHO, EJScreen, SEC EDGAR, court dockets) — no retrieval date by default; the letter
  speaks as of its own date, and a retrieval date per outside fact is noise unless the user
  asks for one. This distinction is the single most credibility-preserving habit available
  and most filed comments lack it.
- **A citation must point at something the reader can actually open.** "Page" means the page
  number printed in the noticed document itself — the EDMS-stamped page, or the page number the
  document's own front matter uses (e.g. "Preliminary Determination Summary p. 55") — never an
  OCR pipeline artifact. `bayou:permit-analysis` cites internally as `file:line` into a working
  `.txt` transcript (`ocr_txt/*.txt`, `verification/*.md`) — that convention exists for the
  orchestrator's own verification loop and must never survive into the letter. If a finding
  arrives as a `file:line` pointer or a bare line number, resolve it to the real page before
  writing the sentence: open the cited line, scan backward to the nearest `=== PAGE <n> ===`
  marker, and cite that page — the same recovery `permit-analysis` itself uses when it needs a
  page rather than a line. No sentence in the letter should name a filename, a directory path, a
  line number, or any other artifact that exists only in this project's working files — a member
  of the public reading the actual notice package has no way to resolve it, and a citation they
  cannot follow is worse than none, because it looks verified and is not.
- **Never narrate the document-processing pipeline itself.** This is a different leak from the
  one above — that rule is about citation *pointers* (a stray file path or line number); this one
  is about citation *methodology*. The letter reports what the record says and what that means,
  never how the drafter got the text out of a scanned PDF to read it. Cut any sentence describing
  OCR passes, image rendering or DPI, "text layer" vs. "page image" comparisons, cross-reader or
  cross-model agreement, structure-aware transcription, or fuzzy-matching/edit-distance checks
  used to catch typos. An individual commenter doesn't run any of that by hand, so a sentence that
  reads like a tooling changelog is the tell. Keep only the finding it was supporting, restated as
  a plain fact — "these three figures do not reconcile," "I have retained copies of pp. 12 and 55
  and will provide them to LDEQ on request" — never the technique that produced it. If in doubt
  whether a sentence crosses this line, ask: would a person who read paper copies at a library
  have said this? If not, cut it.
- **Number the comments.** Where the decision-maker owes a response (LDEQ's Public Comments
  Response Summary, a final rule's preamble), numbered comments force an itemized response and
  make a skipped one visible. Where it owes none (a TEFRA hearing), numbering still lets the
  next venue see which questions went unanswered.
- **Concede what cuts against you, early and explicitly.** A conceded point costs one sentence
  and buys the reader's trust for the rest. An unconceded weakness gets found and discredits
  everything near it.
- **Quantify absence, but don't log the search.** Name the scope — which documents, how many
  pages, what subject — and say what turned up: "A search of the five noticed documents turns up
  no discussion of emission-control alternatives" is evidence; so is "I searched the docket and
  couldn't find an amended protocol." Don't enumerate the literal keywords or query strings tried
  ("for the terms 'vapor recovery,' 'thermal oxidizer,' 'pump-down,' and 'nitrogen displacement'")
  — that reads like a database query log, not something a person who read paper copies at a
  library would say (same test as the OCR-methodology rule above). "No alternatives were
  considered" is a bare assertion with nothing behind it.

### Voice

Formal does not mean clinical. Write first person, direct and plain — contractions are fine
("I'm not saying," "I can't find one," "here's the limit of what I checked"). Cut
throat-clearing and self-conscious meta-sentences that announce a rhetorical move before making
it ("stated plainly," "I frame this carefully," "stated before the numbers, because the numbers
are the evidence and not the argument") — just make the move. Prefer the plain verb over the
legal-flavored one where nothing is lost: "add up to" over "compound into," "I'm arguing" over
"I plead," "I'm not claiming" over "I do not assert."

**What voice never touches:** tables, citations, EDMS references, statutory and case cites,
dates, the `::: comment` blocks, and the enumerated relief request. Above all, never touch the
*content* of a candor or limits sentence — "I do not assert X," "that is a sample of four, not
a survey," "I therefore do not rely on it." That sentence is not decoration; it is what earns
the letter its credibility with a hearing officer. Its wrapper can be loosened without ever
cutting the fact or hedge it exists to state — loosening tone and dropping content are two
different edits, and only the first is voice work. Concretely: if a sentence exists to name a
specific limit on the record (a page count, a document count, what couldn't be searched, what
wasn't found), that specific fact must survive the rewrite word-for-word or number-for-number,
even as the sentence around it gets more direct. After any voice pass on a draft with
cross-referenced facts, grep for the specific numbers you touched to confirm every other mention
of them still matches — a tone edit that quietly drops a fact one section relies on is worse
than leaving the clinical version in place.

### The health-mechanism section

**Whether this section exists at all is the posture file's call.** Permit posture: yes, where
the pollutants bear on the household. Rulemaking: only when the rule itself governs exposure;
otherwise health is the reason the commenter tracks a provision, stated in the interest
section. Financing: never as a section; health enters only through its translation into
financed-asset or reputational risk.

Where the section applies and the pollutants bear on the household, include one bounded section that states
**what the pollutant does inside a body**, then names who is standing in front of it. Mechanism
is what converts a personal fact into a technical comment the agency must answer; status alone
reads as sympathy and gets a sympathetic non-answer.

Keep it to one section. Do not diffuse family health through the whole document, and do not
reach for the phrasings listed under "avoid" in the profile — the underlying points survive
without them, and the wording is what gets a filing classified as emotional opposition.

Only assert a mechanism that is actually established. IARC/EPA carcinogen classifications and
target-organ findings are citable as such. If a specific claim needs a study, find one or drop
the claim — do not invent a citation.

## Step 7 — Write the candor section

Title it "Limits of the present record" or similar. List what could not be resolved from
public sources, stated as open questions rather than as facts, each framed as something the
agency is better positioned to answer than the public.

Source it from `RESEARCH-TODO.md`: items still `🟡 PARTIAL`, `⛔ BLOCKED`, or `⬜ OPEN`, plus
anything the findings doc flags as unverified. Where the evidence is a research memo, use its
open-items, caveats, or "could not verify" passages instead. A `bayou:hearing-prep --debrief`
file's divergences and unanswered questions are also candidates. Include the honest negatives too: research that
established a theory was *unavailable* belongs here, because it stops a later reader from
re-litigating it.

This section costs nothing and does two things: it preserves the issues without asserting
unverified facts, and it demonstrates that everything *else* in the letter was checked.

## Step 8 — QA pass

Run `templates/qa-checklist.md` against the finished draft. Do not skip it on the theory that
the draft was written carefully; the checklist catches the failures that survive careful
writing — an unnumbered comment, a criticism with no requested condition, a personal detail
that contradicts a prior filing, an authority cited from memory.

Report the results to the user with the file path. Note anything the checklist flagged that
you chose not to change, and why.

## Step 9 — Optional styled render (`--render`)

Only after the markdown is final. Content is the deliverable; the PDF is presentation.

Render with pandoc to PDF via LaTeX, using the shared filing style in
`${CLAUDE_PLUGIN_ROOT}/assets/filing/`. Keep the markdown as the source of truth — never edit
the `.tex` or PDF directly, or the two drift and the filed version stops matching the reviewed
one.

**First** write a one-per-campaign identifier file, `<slug>-id.tex`, next to the markdown:

```latex
\def\filingkind{<filing type — e.g. Public Comment and Request for Public Hearing>}
\def\filingid{<the posture file's identifier set, as printed in the notice>}
\def\filingagency{<full agency name>}
\def\filingshort{<short campaign label for the running head>}
\def\filingauthorline{<commenter name(s)> · <town, parish>}
```

Examples of `\filingid` by posture, all taken verbatim from the notice:
- **Permit:** `AI 12345 · Permit 2560-00123-V0 · PER20260001`
- **Rulemaking:** `Docket FAA-2026-8614 · RIN 2120-AM51`
- **Financing:** `LPFA $900,000,000 Exempt Facility Revenue Bonds (… Project) · SBC S26-027`

`\filingid` prints in the footer of **every** page. That is deliberate: agencies scan filings
into document-management systems where pages get separated from their cover, and an unlabelled
page 14 is an orphan. Fill in the real numbers from the notice — never leave placeholders.

**`\filingauthorline` comes from the profile you already read in Step 2** — its Core Identity
section carries the name and contact line for filings, and the town/parish. Do not type a name
from memory, from an earlier draft, or from this file; the fixed-path profile is the only
source, for the same reason Step 2 gives. If the profile names more than one person and the
filing is joint, list both; if it names a campaign, **do not** put the campaign name here.

That last point is the profile's own instruction, not a style preference: it records that
"Bayou Blockade" is an informal campaign name and not a nonprofit or formal entity, and that
filings must not be signed as though it were an organization. Standing and interest run to a
*person*, whether as an aggrieved person under a permit-appeal statute, an interested person
under 5 U.S.C. 553(c), or a person in interest under La. R.S. 9:2347(H). So the letterhead names
people. Keep the street
address out of `\filingauthorline` — the mailing address for notice belongs in the signature
block (Step 5, item 8), where the agency looks for it.

**Then** render:

```bash
pandoc <slug>.md -o <slug>.pdf \
  --pdf-engine=xelatex \
  --lua-filter="${CLAUDE_PLUGIN_ROOT}/assets/filing/bayou-filing.lua" \
  --include-in-header=<slug>-id.tex \
  --include-in-header="${CLAUDE_PLUGIN_ROOT}/assets/filing/bayou-filing.tex"
```

Order matters — the id file must come first, and **the identifiers cannot go in the markdown's
YAML `header-includes` instead.** `--include-in-header` sets a pandoc *variable*, which shadows
the metadata field of the same name, so YAML overrides are dropped silently. The letterhead
itself comes from the markdown's `title:` and `date:` front matter, which the template already
carries.

Three fenced divs are available and map to styled callouts (`assets/filing/README.md` has the
full vocabulary):

- `::: comment` — the numbered request (condition, rule edit, or disclosure). Use it for every
  **Comment N**.
- `::: recordquote` — verbatim material from the agency's record.
- `::: alert` — a boxed point that must not be skimmed past.

Ordinary `>` blockquotes stay ordinary quotations; the divs are what carry the argument's
structure. Non-LaTeX output passes them through untouched, so the markdown stays filable as-is.

If pandoc or a LaTeX engine is missing, say so and leave the markdown — do not install a
toolchain unasked. The style deliberately matches the hand-maintained `.tex` filings from
earlier campaigns in this repo family (Palatino/TeX Gyre Pagella, the same blue-and-red
palette); if a campaign has its own `.tex`, reconcile it toward this shared style rather than
introducing a third.

## Step 10 — Report

In your reply, give:
- the output path;
- **the posture used**, and whether it was inferred;
- the standing or interest basis you used;
- the Tier 1 findings that lead the letter;
- anything from the evidence you dropped, and why;
- any authority you had to verify live;
- the QA results.

Then state the deadline and the submission address from `references/agencies.md`. The last
thing the user needs is the mechanics of actually filing. Finish with the posture's terminal
clock and the event that starts it, so the user knows what to watch for after filing.

If the user will also speak at a hearing, offer `bayou:hearing-prep --oral` on the finished
letter.

Do not submit anything. This skill drafts; filing is the user's action, always.
