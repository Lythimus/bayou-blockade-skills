---
name: hearing-prep
description: Prepare for and debrief in-person engagements in a campaign — open houses, public hearings, TEFRA hearings, parish council meetings. Three modes — --questions (short, memorizable questions grouped by the staffer likely to field them, keyed to findings), --oral (a 2–3 minute spoken version of a filed comment, pitched to the room), and --debrief (turn a meeting recording's transcript into a status-keyed record of what was asked, answered, committed, and where the oral account diverges from the written record). Use before or after any meeting where the campaign talks to people rather than files paper.
argument-hint: --questions <findings-or-memo> [--event <description>] | --oral <filed-comment.md> [--minutes <n>] | --debrief <transcript(s)> [--questions <prep-file>] [--record <findings-or-memo>] [--out <path>]
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, AskUserQuestion, Skill
---

# bayou:hearing-prep: the spoken side of a campaign

`bayou:public-comment` produces the filed document. Campaigns also involve rooms: an applicant's
open house, an agency's public hearing, a bond issuer's TEFRA hearing, a parish council meeting.
These call for different artifacts. You need questions you can hold in your head, a statement
you can say in three minutes, and afterward a record of what people actually said, checked
against what they filed.

**The filed comment is the record.** At most meetings nothing said enters the administrative
record: open houses, LDEQ public *meetings* as distinct from hearings, and most TEFRA hearings.
Every mode here serves the written record. Questions surface facts for the comment. The oral
statement points to the filing. The debrief feeds the comment's candor section and its
follow-ups.

Worked examples in `~/Documents/personal/petro/`:

| Mode | Model artifact |
|---|---|
| `--questions` | `high-west/OPEN-HOUSE-QUESTIONS.md` (prep), grouped by staffer, keyed to `verification/` question IDs |
| `--oral` | `hyundai-posco/loans/LPFA-TEFRA-TALKING-POINTS-2026-09-14.md` |
| `--debrief` | `high-west/meetings/2026-08-27-open-house-notes.md` (full record) and `high-west/OPEN-HOUSE-QUESTIONS-CURATED.md` (campaign view keyed to the prep file) |

Run exactly one mode per invocation. If none is given, ask which one.

---

## Shared rules

- **The same honesty rules as `public-comment` apply to anything said aloud**, from
  `skills/public-comment/SKILL.md` Step 6:
  - no unsourced numbers;
  - no case law characterized from memory;
  - no Tier 4 material;
  - no narrated OCR or pipeline methodology;
  - no file paths or line numbers.
- **Read the posture file** (`skills/public-comment/postures/<posture>.md`) for the audience
  model when the meeting has a decision-maker in the room: a hearing officer, a bond board, a
  council. What persuades an underwriter board is not what persuades a permit writer, and
  neither is what persuades a council member facing re-election.
- **Profile.** When the output names the speaker or their family, read
  `~/.claude/bayou-profile.md`, the same fixed path and the same rules as `public-comment`
  Step 2. Never invent a personal detail. Honor the profile's "avoid" phrasings and its
  wording for faith and congregation.
- **Write output next to the campaign's other files. Never write into `verification/`.**
  `FINDINGS-FOR-REPORT.md` and `RESEARCH-TODO.md` belong to `bayou:permit-analysis`.

---

## Mode `--questions`: what to ask, and whom

**Input:** a findings report or research memo, and a description of the event (`--event`). If
the event description is absent, ask for the format, because it decides everything below:
- **Poster-station open house:** one-on-one conversations with staff at stations.
- **Hearing with a comment period:** a queue at a microphone, time-limited.
- **Q&A after a presentation.**

**Step 1 — Pick the questions from the evidence.** Good candidates:
- findings the record could not resolve (`🟡 PARTIAL`, `⬜ OPEN`, `⛔ BLOCKED`);
- redactions;
- places where the application is vague about something a staffer would know offhand, such as
  route, schedule, or who holds the money;
- anything whose spoken answer could be compared later with the filing.

Skip findings that are already established from the record. Asking only invites a rehearsed
denial.

**Step 2 — Group by who will field it** (open house), or order by priority (hearing).
- Open-house staffing usually runs community relations / PR, then technical floaters (geologist,
  engineer), then safety and emergency response. Legal, finance, or corporate staff are rare.
  Order the groups **least to most technical**, and put a one-line note under each group
  heading on what that staffer is likely to be candid about.
- Include a short **Strategy** section:
  - open with easy questions to gauge the room;
  - don't spend the one shot at an engineer on a PR question;
  - note any question to ask twice, to different people, to compare answers.

**Step 3 — Write each question to be said, not read.**
- One sentence, conversational, and memorizable. Carry one specific fact that shows you read
  the file ("Fault 8 sits about half a mile from the wells…"). A staffer who realizes you know
  the file gives a more candid answer than one fielding a generic question.
- Never lead with an accusation. Ask what they are doing about X, not why they are hiding X.
- **Key every question to its source** in an italic trailing note, e.g. *(Q17: recreational
  use never addressed)*. That key is what lets `--debrief` reconcile answers afterward.
- **Mark the highest-value questions in bold.** Two to four at most.

**Output:** `<EVENT>-QUESTIONS.md` with a header recording the date compiled and the source
file, then the Strategy section, then the grouped questions. Keep it short enough to reread in
the parking lot, about 80 lines for an open house.

---

## Mode `--oral`: the filed comment, spoken

**Input:** a finished (ideally filed) comment letter. **Never draft oral remarks from findings
directly.** The spoken version must say nothing the written version does not support.

**Length:** default 3 minutes, about 400 words at speaking pace, plus bracketed emphasis cues.
Honor `--minutes`. If the event sets a time limit (often 2–3 minutes per speaker), fit under
it with 15 seconds to spare.

**Structure:**
1. **Header block (not read aloud):**
   - event, date, time, and place;
   - where the written version was or will be submitted, with an instruction to submit it in
     writing regardless of whether anyone speaks;
   - the target length.
2. **Who I am (two sentences).** Name, where you live, the one connection that matters to this
   room, and "I have no financial interest" where relevant, e.g. in a financing posture. Say
   that written comments were also submitted.
3. **Three points, maximum, each opening with a bold one-line frame for this room.**
   - Take them from the letter's Tier 1 material. Recast each in the room's vocabulary, from
     the posture file's audience model. The LPFA model: **"First — this is not an
     environmental comment, it's a bond question."**
   - One number per point, said the way a person says it ("three point six million tons a
     year," not "3.6 Mt/yr").
   - No citations read aloud beyond a short-form statute or agency name. The filing carries the
     cites.
4. **The ask.** The letter's top one or two requests, in one sentence each.
5. **Close.** Point to the written filing, and thank them.

**Voice:** first person, plain, and spoken. Contractions are fine. Remarks spoken at a hearing
are recorded, and sometimes transcribed into the record, so the Tier 4 cut list applies in
full.

**Output:** `<SLUG>-TALKING-POINTS.md` next to the letter. For an audio proofread, suggest
`bayou:public-comment-tts` on it.

---

## Mode `--debrief`: what was said, checked against what was filed

**Input:**
- One or more transcripts of a recording, e.g. Whisper output from raw and enhanced audio.
- The prep file (`--questions`), if one exists.
- The findings or memo (`--record`) for the written record.

If there is no prep file, reconstruct the question list from the transcript.

**Step 1 — Establish reliability before content.** Open the output with a **source and
reliability** block covering:
- which transcript files exist, and **what span of the event each covers**. They often cover
  different spans; a cleaned pass may stop partway;
- that quotes are **paraphrase-grade**, tagged by source pass (`[raw]`, `[enh]`), with bracketed
  reconstructions of garbled words;
- that speaker attribution is inference from context, and surnames are phonetic and unverified;
- that **the original audio is the verification path.** Give timestamps, or the transcript
  markers needed to find a passage, so any line can be checked by listening before it is
  quoted or attributed outside this file.

**Nothing in the debrief is a citable source on its own.**

**Step 2 — Status every prepared question.** Use this key, and one subsection per question:

| Key | Meaning |
|---|---|
| ✅ | Answered |
| 🟡 | Partially answered, or answered a narrower question than was asked |
| ⚪ | Acknowledged, not answered |
| ❌ | Not asked |

Under each question: who answered (role, then first name if known), the paraphrase-grade
quotes with source tags, and a line on what the answer changes for the comment.

**Flag "answered a different question" explicitly.** The High West pattern: every question about
the pressure front was answered with a claim about the plume, three times. A pattern like that is
often the most useful output of the evening.

**Step 3 — Capture everything else that bears on the record.**
- **Who was there:** roles and first names, and whether counsel or corporate staff attended.
- **Project status as described:** often earlier-stage than the filing implies.
- **Commitments and offers made:** a numbered table with who made each. These are oral and
  appear in no application, so they are what a follow-up email can hold people to.
- **Where the oral account and the written record diverge:** one numbered list, and the most
  useful section in the file. Include divergences that cut **against** the campaign, where the
  spoken account is more careful than the filing. They go in so no one builds an argument a
  quoted nuance can dismantle.
- **Claims to check:** any number or legal assertion made aloud (a fee share, a statute, a
  distance). Check it against the statute or filing before it goes anywhere. Record the result
  in place: confirmed, contradicted (with the source), or still open.

**Step 4 — Hand off; do not merge.**
- Finish with **Open threads** and **Highest-value follow-ups, in order**.
- Where the evidence is a `verification/` set, write a **proposed** block of new or updated
  `RESEARCH-TODO.md` items at the end of the debrief, and ask the user before anyone applies it.
- Tag divergences and admissions that belong in the letter as **comment candidates** or
  **candor candidates**. `public-comment` Step 7 reads this file for its candor section.

**Output:** `meetings/<date>-<event>-notes.md`, the full record. If a prep file exists,
optionally also write a campaign view of the prep file with status keys and a summary table,
modeled on `OPEN-HOUSE-QUESTIONS-CURATED.md`. **Never overwrite the prep file itself.** Write the
curated view to a new filename.

**Hard rules for debrief:**
- **Never upgrade a paraphrase to a quote**, and never attribute a line to a named person
  outside this file, until it has been checked against the audio.
- **Never treat a spoken number as a fact.** Check it against the filing or the statute first.
- **Record what was not asked** as plainly as what was answered. An unasked question is still
  open, and the next meeting's prep starts from it.
