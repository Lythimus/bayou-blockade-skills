# Follow-up plan — {{project name}}

> Written at the end of Step 6, when `RESEARCH-TODO.md` or the downgrade re-check surfaces work
> that belongs in a later pass rather than the current one. One phase per unit of work that has
> its own reads/writes/context shape — not one phase per calendar session.

Each phase gets the header block below, filled in before any work starts on that phase. The point
of the block is to make explicit, in writing, the decisions that would otherwise get improvised
mid-task: what has to be in context at once, whether work can be parallelized, and — critically —
where it is safe to discard the conversation and resume cold. A phase whose `Checkpoint` line can't
be written yet is not ready to start.

**Model choice is a consequence of `Context`, not a separate decision.** Don't name a model
directly in the phase — say what the phase needs (narrow and disposable vs. broad and
simultaneous) and let the model follow from that. A plan that says "use the cheap model here"
goes stale the day the model lineup changes; a plan that says "this phase only ever needs one
section file in view" doesn't.

**Phases belong in one plan, not one plan per phase or per model.** A phase's `Reads` line is
usually a downstream phase's `Writes` line from an earlier phase — that dependency graph is what
Step 6's synthesis (and any retrospective on the run) actually needs to see. Splitting phases into
separate files breaks that graph for no benefit; a single plan with explicit handoff contracts
between phases is easier to resume from and easier to review as a whole.

---

## Phase N — <name>

**Reads:**       <what must be in view — specific files/anchors, not "the codebase">
**Writes:**      <durable artifacts this phase produces, by anchor where applicable>
**Context:**     high-churn/disposable | needs-breadth-simultaneously
**Parallel:**    independent? proven pattern vs. first-of-kind
**Checkpoint:**  what must be true on disk to safely discard the conversation after this phase
**Resume cost:** what a fresh session must re-read to continue from the checkpoint

<1–3 sentences: what this phase does and why it's a separate phase rather than folded into an
adjacent one.>

---

### Worked example, from the AI 41475 campaign's Step 5 split

## Phase 1 — Research sweep (5c)

**Reads:**       `verification/RESEARCH-TODO.md` (the full `⬜ OPEN` list); the specific `Qn`
                 section file only for the item currently being resolved — not the whole corpus.
**Writes:**      `OPUS-SKILL:Qn` / `WEBSEARCH:Qn` anchors for each resolved item; status updates
                 in `RESEARCH-TODO.md` (`✅`/`🟡`/`⛔`, never left `⬜` once touched).
**Context:**     high-churn/disposable — each item is independent once logged; nothing from one
                 item's resolution needs to stay in context for the next.
**Parallel:**    SKILL calls against a skill already exercised earlier in the run: fan out.
                 The first call to a not-yet-used skill, or an unfamiliar query shape: run inline,
                 since it may turn out to be a blocker (inert filter, auth gate) rather than a
                 clean result, and a fanned-out subagent tends to report "no results" instead of
                 diagnosing why.
**Checkpoint:**  Every `RESEARCH-TODO.md` item is `✅`/`🟡`/`⛔` with a written finding or a
                 recorded blocker (exact endpoint + error). No item is still `⬜ OPEN`.
**Resume cost:** A fresh session reads `RESEARCH-TODO.md` for the remaining item list and opens
                 only the anchors it's about to write to — not the section files' other questions.

This phase exists as its own unit because an earlier version of this campaign folded it into
citation verification (5b), which consumed context first and left most of this phase's items
never attempted. Once `RESEARCH-TODO.md` carries a query, an anchor, and a status field, resolving
it doesn't require re-deriving why it was logged — which is what makes it safe to run as a
separately-scheduled phase, days or a compaction later, without re-reading the whole campaign.
