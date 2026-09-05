---
name: permit-analysis
description: Analyze 1-4 OCRed permit application documents (LDEQ, USACE, LADENR/OCM, LDOTD, FAA, etc.) against the Bayou Blockade question bank. Selects applicable question groups by permit type and process, drafts bespoke project-specific questions modeled on prior campaigns, pauses for user review, then produces a provenance-cited findings report for public-comment work.
argument-hint: <permit-doc-path> [more doc paths, up to 4] [--project-info <path>] [--skip-bespoke] [--no-review] [--single-pass]
allowed-tools: Read, Bash, Grep, Glob, Write, Edit, AskUserQuestion, Skill, WebSearch, WebFetch, Agent
---

# bayou:permit-analysis — permit application interrogation

Analyze 1–4 permit application documents against a curated question bank, generate project-specific questions, and produce a findings report with document-level provenance. The report feeds the downstream Bayou Blockade steps: informational website, social campaign, and the public comment itself.

Bundled data (in this skill's directory):
- `questions/question-bank.csv` — the reusable bank. Columns: `id, question, tier, group, process, level, regulators, permit_types`. Tier `generic` applies by permit type/regulator; tier `process` applies only when the project involves that process (`landfill`, `CCS`, `gas-power`, …).
- `questions/exemplars.csv` — real project-specific questions from prior campaigns (River Birch, Waterford 5 & 6). These are **style exemplars** for Step 3, not questions to ask of new projects.
- `questions/sections.csv` — maps each bank `group` to a default `section_title` + `scope` string, used to render the selected groups as numbered Waterford-style sections.
- `templates/section.md`, `templates/00-INDEX.md`, `templates/FINDINGS-FOR-REPORT.md`, `templates/RESEARCH-TODO.md` — scaffolds for the `verification/` artifact set produced by Steps 5–6.
- `templates/FOLLOWUP-PLAN.md` — scaffold for a next-pass plan when Step 6 surfaces work for later; see Step 6 below.

## Parsing arguments

Arguments are 1–4 paths to OCRed permit documents (PDF, .txt, or .md), plus optionally `--project-info <path>` pointing to a project background file. If no document paths are given, ask the user which files to analyze and whether a project-info file exists.

Flags:
- `--skip-bespoke` — skip Step 3 (bank questions only)
- `--no-review` — skip the Step 4 review gate and proceed straight to analysis
- `--single-pass` — skip dispatching Haiku `bayou:permit-extractor` subagents in Step 5a; do the `rg` retrieval sweeps inline and verify in the same pass. Useful for small document sets where subagent dispatch overhead isn't worth it.

## Step 1 — Classify the project

Skim the opening pages of each document (`Read` with `limit`, don't read whole files yet) and the project-info file to determine:

1. **Regulator(s) and permit type(s)** for each document — e.g. LDEQ Air (minor/PSD/Part 70), LDEQ Solid Waste, LPDES, USACE 404/Section 10, Coastal Use Permit, 401 WQC.
2. **Process type(s)**: `landfill`, `CCS`, `gas-power`, `portable-source`, or none. If the project involves a process not yet in the bank (LNG, ammonia, data center, …), note it — bespoke questions in Step 3 will have to carry that weight, and it is a candidate for a new process group later.

   Select `portable-source` whenever the permit authorizes a source with **no fixed location** — portable or temporary equipment, "any location along" a right-of-way or system, or a standing authorization replacing case-by-case variances. This is easy to miss because such permits are usually small on paper (minor source, low tonnage) while being unusually weak: with no coordinates there can be no dispersion modeling, no ambient-standard demonstration, no EJ screening, and no setback, and siting conditions tend to be circular. The `portable-source-siting` group exists to interrogate exactly that.
3. **Applicant identity** (legal entity, parent company) and **facility location** (parish, nearby communities).

State the classification to the user in one short paragraph before continuing.

## Step 2 — Select applicable bank questions

Load `questions/question-bank.csv` and select rows:

- **By permit type/regulator**: rows whose `permit_types`/`regulators` match the documents under review (blank `permit_types` means the row is scoped by its group, not a specific permit).
- **By process**: all `process` rows matching the process types from Step 1.
- **Always include** these cross-cutting groups regardless of permit type:
  - `applicant-history`, `ej-cumulative`, `public-process`, `emergency-safety`, `climate-resilience`, `cultural-sacred-resources`
  - `eas-it-questions` for any LDEQ permit action requiring an Environmental Assessment Statement
  - `usace-public-interest` when any document is a USACE action
- **Exclude** groups with no plausible relevance (e.g. `wetlands-404` for a project with no earthwork) — but when unsure, keep the group; an "Unanswered" finding is itself useful in a comment.
- **Always-include admits the group, not every row in it.** A row inside an always-included group still filters on its own non-blank `permit_types` — e.g. `ej-cumulative` is always-included, but `EJ-008` (`Air`) and `EJ-009` (`Air / EAS`) only fire on an air permit; `cultural-sacred-resources` is always-included, but its solid-waste buffer question (`CSR-003`) only fires on a Solid Waste permit and its §106 questions (`CSR-005`, `CSR-006`, `CSR-010`) only fire on a USACE 404/Section 10 action. `permit_types` is the eligibility filter; `regulators` on a group-scoped row (blank `permit_types`) just names which agency the question addresses and does not itself gate whether the row fires — a row like `CSR-001` (`regulators` LDEQ/USACE, `permit_types` blank) still runs on every permit type the always-included group reaches, an LDOTD or FAA action included.

Once the group set is settled, look up each selected group's `section_title` and `scope` in `questions/sections.csv` — these become the section headings once the question set is finalized in Step 4. Don't assign section numbers or scaffold files yet; the user's edits at the review gate can still add, drop, or move questions between groups.

## Step 3 — Generate bespoke project-specific questions

This is where the strongest comment material comes from. Read `questions/exemplars.csv` first and match its style: every bespoke question **pins the applicant or agency to a specific, checkable fact**. The exemplar patterns:

- **Cite the exact source**: EDMS document number and page, letter date and author, attachment number, Fact Sheet section ("EDMS 14829297, page 271", "the LDOTD letter dated 10/17/2025 (Bao Long Le, P.E.)").
- **Surface internal contradictions**: numbers that disagree between the application's own documents, or between the application and the applicant's other permits.
- **Contrast public statements with the application text** (spokesman quotes, press coverage vs. what is actually requested).
- **Use the site's regulatory history**: prior denials, old objections, enforcement actions — and ask what has materially changed.
- **Quantify the delta**: current permitted level vs. requested level, study date vs. developments since.

To find this material: `rg -in` over the OCR text for numbers, dates, "EDMS", attachment references, named consultants, tonnage/emission figures; compare figures that should agree across documents. Pull in prior findings with the bayou skills where useful (`bayou:ldeq-edms-search` for the docket, `bayou:epa-echo-search` for compliance history, `bayou:itep-lookup` for subsidies, `bayou:pacer-case-search` for litigation, `bayou:la-species-cultural-review` for NRHP proximity and `bayou:unmarked-burial-screen` for a R.S. 8:671 documentary screen when `cultural-sacred-resources` questions are in play).

Write the combined output to `permit-questions-proposed.csv` in the current working directory, same columns as the bank plus a `source` column (`bank` or `bespoke`; bespoke ids use a project prefix, e.g. `PROJ-001`).

## Step 4 — Review gate

Stop. Tell the user how many bank and bespoke questions were selected, list the bespoke ones in the reply, and ask them to prune/edit `permit-questions-proposed.csv`. Confirm with AskUserQuestion (proceed / re-generate bespoke / cancel) before analyzing. Re-read the CSV after confirmation — the user may have edited it.

**Finalize sections and scaffold `verification/`.** From the confirmed CSV, derive the final section list: only groups with at least one surviving question become a section. Assign section numbers `01, 02, …` in a sensible reading order (emissions/technical groups first, cumulative/EJ next, resource-specific groups, then compliance/history, EAS/need, and public-process last — follow the Waterford precedent when in doubt), and number questions `Q1..Qn` sequentially across all sections in that order. This numbering is fixed once assigned and carries through Steps 5–6.

Create the `verification/` directory in the current working directory:
- `verification/00-INDEX.md` from `templates/00-INDEX.md` — one row per section, status `TODO`, model/date blank.
- `verification/NN-<slug>.md` from `templates/section.md` for each section — fill in the header (title, scope from `sections.csv`, status `TODO`) and repeat the per-question block once for each confirmed question in that section (its `## Q<n>. <text>` heading plus the four empty role-owned blocks). `<slug>` is the section title, kebab-cased.

  **Substitute `{{n}}` in the anchor comments with the actual question number** — each block carries one (`<!-- HAIKU:Q7 -->`, `<!-- OPUS-VERIFIED:Q7 -->`, `<!-- OPUS-SKILL:Q7 -->`, `<!-- WEBSEARCH:Q7 -->`). This is load-bearing, not decoration. The subagents hold `Edit` rather than `Write` so a whole-file overwrite cannot destroy another role's blocks, and `Edit` demands a unique `old_string`; without per-question anchors the block markers repeat identically under every question and every subagent edit fails. Scaffolding is mechanical — generate these files with a short script rather than by hand, and confirm anchor uniqueness before dispatching: `rg -o 'Q[0-9]+ -->' <file> | sort | uniq -d` should print nothing.

## Step 5 — Analyze the documents (Haiku claims → Opus verifies → research sweep)

This step is a **verification loop**, not a single pass: a cheap model claims candidate evidence with citations, then the orchestrator (you, running as the advanced model) re-checks every claim before it counts as a finding. Never skip straight to writing a flag without having actually looked at the cited line yourself.

It is also three steps, not two, and the boundary between them matters. An earlier run of this skill bundled citation verification and SKILL/WEBSEARCH follow-up research into one step (5b); verification consumed the available context first, so follow-ups got logged "for later" and 15 of 19 were never attempted — even though closing the ones that *did* get attempted later produced two of the campaign's three strongest findings. **5c exists so the research sweep has its own turn, instead of losing a context race it didn't need to run.**

```
5a  Claim          Haiku subagents, parallel, context isolated
5b  Verify         main thread; needs the section in view
    ↓ CHECKPOINT: every Qn past 🔍; every SKILL/WEBSEARCH follow-up
      logged to RESEARCH-TODO with its query. Safe to compact.
5c  Research sweep run every logged follow-up; write to OPUS-SKILL:Qn
    ↓ CHECKPOINT: every R-item is ✅/🟡/⛔ with a written finding or a
      recorded blocker (exact endpoint + error). "Not yet attempted"
      is NOT a terminal state. Safe to compact.
6   Report         needs the whole corpus in view — do NOT compact mid-step
```

Each checkpoint states a **disk condition**, not a vibe — the reason it's safe to discard the conversation there is that everything needed to resume lives in uniquely-addressable `OPUS-VERIFIED:Qn` / `OPUS-SKILL:Qn` anchors in the section files, plus `RESEARCH-TODO.md`'s status vocabulary (`✅`/`🟡`/`⛔`/`⬜`), which lets a fresh context tell "attempted and blocked" apart from "never tried." A fresh session resuming at 5c needs to read only `RESEARCH-TODO.md` (for the query list) and the specific `Qn` anchors it's about to write to — not the full section files. That property, not the step number, is what makes a boundary compactable; if you restructure this step further, preserve it.

### 5a — Claim (Haiku subagents, parallel)

For each section, dispatch a `bayou:permit-extractor` subagent (Agent tool, the custom agent bundled with this skill's plugin — it always runs on Haiku regardless of your own model) with: the section's file path, its list of questions, the relevant document path(s), and the list of available `bayou:*` skills to propose as follow-ups. Dispatch independent sections in parallel — each subagent's context is isolated and discarded on return, so raw OCR text never enters your context, only the `Claimed references` bullets it writes to the section file.

Under `--single-pass`, skip subagent dispatch: do the `rg -in` retrieval sweeps yourself, inline, and write the `Claimed references` block directly — then continue straight into 5b for that section without a separate pass.

### 5b — Verify (you, main thread)

Before working any section, run `/bayou:ocr-validate <work-dir> --doc <stem> [--doc <stem> ...]`
once for this run's document set (not per section) — one `--doc` per `.txt` this `permit-analysis`
invocation was actually given (its own signature caps at 4). Don't omit `--doc` and let it default
to every `canonical/*.json` in `<work-dir>`: `$WORK` can hold OCR output from a larger campaign
than this particular run's document set, and an unscoped sweep would flag documents nobody asked
about here. `<work-dir>` is the OCR pipeline's `$WORK` dir: default `./.ocr-work` next to where the
OCR run was launched, otherwise a sibling of the `.txt` files' own directory, otherwise ask rather
than guess. Treat the resulting `OCR-FLAGS.md` as a pre-seeded 🔍 TODO list layered on top of each
section's own questions — a flagged arithmetic/plausibility/format issue is worth resolving with
its `verify_cmd` even if no question in the bank happens to ask about that field directly.

For each section file, work question by question:

1. **Re-read every claimed citation yourself.** Open the cited `file:line` with `Read` (a small window around the line) and check the claim against the actual text. `.txt` carries a `=== PAGE <n> ===` marker line at every page boundary (including blank pages) — that's structure, not content; recover a page number by scanning backward to the nearest one, never by treating a marker line itself as a citation.
   - **Never write "blank," "empty," "illegible," or "cannot be determined" into a finding, and
     never assert that the same field disagrees across citations, without a `/bayou:ocr-verify`
     block pasted under Verified citations.** A `.txt` line alone — or a silent visual re-read of
     the source PDF — is not sufficient evidence for either claim; see
     `ocr-verify/references/failure-cases.md` for the two real incidents (a collapsed checkbox
     glyph misread as "illegible," a repeated-digit permit number misread as a genuine
     cross-document discrepancy) that motivate this rule. Run:
     ```
     /bayou:ocr-verify <work-dir> <stem|file.txt> <"snippet"|file.txt:LINE|page:x0,y0,x1,y1> [--tally]
     ```
     and paste its fixed `VALUE/STATUS/CITATION/EVIDENCE/NOTE` output block verbatim. `--tally` is
     required whenever the claim is a cross-citation disagreement, especially when the two readings
     are near-identical strings (a repeated-digit count off by one, a transposed digit). Reserve
     `ESCALATE-TO-USER` (put the rendered crop in front of the user rather than resolving it
     yourself) for citations that are load-bearing for a `🔴` finding, not merely `⚪ PARKED`
     context — most contested cells resolve inside `ocr-verify` itself and don't need it.
2. Write the result under **Verified citations** (respecting the `<!-- ROLES -->` protocol — never touch the `Claimed references` line above it):
   - If the citation and characterization are accurate, mark it `✅` and paste the exact quote.
   - If the line number or characterization is off but you can locate the real citation, mark it `⚠️ CORRECTED`, give the corrected `file:line`, and explain what changed.
   - If you cannot locate or confirm the claim at all, mark it `❌ UNVERIFIED` — never guess a citation into existence.
   - Reserve `🔍 TODO` for a citation you haven't gotten to yet (should be rare — resolve before closing the section).
   - Alongside accuracy, assign relevance: `🔴 REPORT-RELEVANT` (supports a finding worth including in the report) or `⚪ PARKED` (verified but not report-worthy on its own — context, negative results, or too minor).
3. **Do not run SKILL/WEBSEARCH follow-ups here — log them.** For every `SKILL (bayou:xxx): <query>` and `WEBSEARCH: <query>` follow-up Haiku proposed, append an entry to `verification/RESEARCH-TODO.md` with status `⬜ OPEN`: the question anchor (`Qn`), the exact query, and which mechanism (SKILL name, or WEBSEARCH). This is the only action 5b takes on a follow-up — running it is 5c's job. Logging is cheap and can't saturate context the way running every follow-up inline does, which is the whole point of the split.
4. Update `verification/00-INDEX.md`: section status to `DONE`, model `Opus`, today's date — once every question in the section has moved past `🔍 TODO`. (`DONE` here describes citation verification, not the research sweep — 5c can still have open items against a `DONE` section.)

`❌ UNVERIFIED` and `⚪ PARKED` items still matter (an unanswered or contradicted question is itself a finding) but only `✅`/`⚠️` × `🔴` items graduate to the report in Step 6.

### 5c — Research sweep (every logged follow-up gets a terminal state)

Work through every `⬜ OPEN` item in `RESEARCH-TODO.md`. The exit condition for this step is not "the highest-value items are done" — it's that **every item is `✅ RESOLVED`, `🟡 PARTIAL`, or `⛔ BLOCKED`**, each with either a written finding (spliced into the question's `OPUS-SKILL:Qn` or `WEBSEARCH:Qn` anchor) or a recorded blocker (the exact endpoint and error). `⬜ OPEN`/"not yet attempted" is not a terminal state for an item this step touches — an item can end `⛔ BLOCKED`, but not untouched.

- **For a SKILL item**: run the skill yourself, write the result under **SKILL findings** with `🔴`/`⚪` relevance, and update the item's status in `RESEARCH-TODO.md`. If the skill call fails (API error, rate limit, auth gate), that failure — endpoint, exact error, date — *is* the terminal state (`⛔ BLOCKED`); do not leave it `⬜` and do not guess at what the result would have been.
  - `cultural-sacred-resources` questions default to two follow-ups even if Haiku didn't propose them in 5a: `bayou:la-species-cultural-review` (NRHP proximity via the NPS ArcGIS layer) and `bayou:unmarked-burial-screen` (the R.S. 8:671 documentary screen). Log and run both whenever the section has surviving questions, the same way `OCR-FLAGS.md` items are treated as a pre-seeded TODO layered on top of the section's own questions.
- **For a WEBSEARCH item**: dispatch a `bayou:permit-websearch` subagent (Agent tool, runs on Sonnet) with the query and question context — **including the question number**, which it needs to find its `<!-- WEBSEARCH:Qn -->` anchor. It writes the Answer/Findings/Gaps/Suggested-relevance block under **Web research (WEBSEARCH)**. Treat its suggested relevance as a proposal — override it in `FINDINGS-FOR-REPORT.md` if the evidence warrants a different call.

  A websearch subagent that cannot complete its edit is instructed to return the finished block verbatim in its final message rather than force a write. That message is the only channel you have to its work, so **capture the block when the completion notification arrives and splice it in yourself** — don't re-dispatch and don't let it drop.

  Read its **Gaps / caveats** as carefully as its Findings. A caveat that undercuts the legal theory behind a bespoke question is more valuable than a confirmation, and it is your job — not the subagent's — to narrow or drop the finding in `FINDINGS-FOR-REPORT.md` when that happens. Say so explicitly in the file rather than quietly softening the wording, so the comment letter's author knows which arguments are safe to plead.

**Principles for this sweep** — each one traces to a specific failure observed in a prior run, kept here so a future pass applies the rule rather than needing a human to notice the same thing again:

- **Ordering is for sequencing, not stopping.** If you rank the open items (by expected value, by blocking-status, by anything), the ranking may decide what you do *first* — it must never decide what you skip. In the run that motivated this rule, the items ranked 6th and 11th of 14 produced the two strongest findings of the campaign, while items ranked 3rd and 4th produced only incremental confirmation of what was already known. A ranked list whose tail never gets attempted is not a prioritization, it's a silent scope cut — and 5c's exit condition above exists specifically to make that impossible.
- **Fan out proven access patterns; run first-of-kind lookups inline.** Parallel dispatch is safe once a skill/endpoint's behavior on this project is known-good. The first call to a new skill, or a query shape not tried before, should run inline, because several "independent read-only lookups" in past runs turned out to be diagnosis in disguise (an inert filter parameter, a reCAPTCHA gate) — the correct output was a *characterized blocker*, and a fanned-out subagent tends to paper over that by reporting "no results" instead of "this endpoint doesn't work the way we assumed."
- **Verify that a filter filtered.** Before reporting any filtered API result set as authoritative, re-run the same query with the filter removed and compare the totals. Equal totals mean the filter was silently ignored — the result set is the unfiltered one, not what it claims to be. This is not hypothetical: both `bayou:ldeq-edms-search`'s `keywords` parameter and `bayou:epa-echo-search`'s `p_county` parameter were found to be completely inert this way, and both failed silently (full unfiltered results, no error) rather than raising anything that would prompt a second look.
- **Check what an aggregate field actually aggregates before citing it.** A rollup, total, or average may sum across a broader scope than its name implies (`bayou:epa-echo-search`'s `TotalPenalties` is all-program, not per-program — confirmed $4.9M all-program against $1.6M CAA-only for the same parish, both correct at their own scope). Confirm the scope before putting a number in a finding.
- **Aggregating across a heterogeneous area dilutes the signal.** When screening an area the permit doesn't fix to one site (parish-wide, corridor-wide, a right-of-way with no fixed location), a single population-weighted average pulls the result toward the largest low-burden subarea and can hide a severely affected pocket. Report **per-subarea values plus the share of the population above the relevant threshold**, and state the method used. (This is why an EJScreen sweep should default to a per-parish or per-block-group breakdown, not a single flattened average, when the permitted activity spans multiple areas.)

## Step 6 — Report

This step needs the whole corpus in view at once — every section file, `FINDINGS-FOR-REPORT.md`, and `RESEARCH-TODO.md` — because synthesizing the report means cross-checking findings against each other, not just transcribing them one at a time. **Do not compact mid-step.** If context runs out partway through, finish the current file's edits and stop at a section boundary rather than losing the cross-file view partway through a comparison.

Synthesize the downstream artifacts from the completed `verification/` files:

1. **`verification/FINDINGS-FOR-REPORT.md`** (from `templates/FINDINGS-FOR-REPORT.md`) — every `✅` or `⚠️` finding flagged `🔴 REPORT-RELEVANT`, grouped by section, one bullet per finding: question id, one-to-two sentence statement, citation, flags. This is the report's evidentiary backbone.
2. **Downgrade re-check.** Before adding new findings, re-read the *existing* `FINDINGS-FOR-REPORT.md` bullets against everything 5c resolved since they were written. Research doesn't only add support — it can undercut an earlier finding (establish that a legal theory is unavailable, that a number was wrong at a different scope, that a caveat narrows a claim). When it does, narrow or drop the finding and **say so explicitly in the file** (what changed, and why) rather than quietly softening the wording or leaving stale text next to newer contradicting evidence. (Worked example from a prior campaign: research established that a planned "missing EAS" pleading argument was legally unavailable because the record's exemption made the absence of that document lawful — the value of that research was recording the settled negative, not finding a new violation.)
3. **`verification/RESEARCH-TODO.md`** (populated during 5b, closed out during 5c) — finalize it: every item should already carry a terminal status from 5c; write up any that are `⛔ BLOCKED` with enough detail (exact endpoint, error, suggested next step) that a follow-up pass can pick it up without re-deriving context.
4. **Follow-up plan for anything still open.** If `RESEARCH-TODO.md` or the downgrade re-check surfaces work that belongs in a later pass (a blocked item worth a different approach, a new-process bank candidate that needs its own research), sketch it using `templates/FOLLOWUP-PLAN.md` — its per-phase header block (Reads/Writes/Context/Parallel/Checkpoint/Resume cost) is the same structure this skill's own Step 5 split follows, so model, parallelism, and compaction-safety decisions get made explicitly instead of improvised in the moment.
5. **Bank promotion candidates** — bespoke questions from this project that are actually reusable (for the process type or permit type generally). Report these directly in your reply (not a file): suggest the generalized wording and target group/tier. The user decides whether to add them to `question-bank.csv` — this is the feedback loop that grows the bank.

In your reply: summarize the 5–10 strongest findings from `FINDINGS-FOR-REPORT.md` (ordered by strength, not by section), note how many `RESEARCH-TODO` items remain open, note anything the downgrade re-check changed, and point at both file paths.

## Maintaining the bank

When there appears to be relevant questions to add/edit: edit `question-bank.csv` directly, keep ids stable (never renumber existing rows; append with the next number in the prefix), and add new process types as new `process` values with their own id prefix. After a campaign concludes, its bespoke questions belong in `exemplars.csv` with a project column value.