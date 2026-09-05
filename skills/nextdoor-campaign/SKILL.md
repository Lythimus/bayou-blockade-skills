---
name: nextdoor-campaign
description: Turn permit/campaign research plus the Bayou Blockade profile into a dated series of Nextdoor social media posts, each pitched at a specific audience archetype (homeowner, parent, hunter, EJ advocate, etc.) and paced against a comment/hearing deadline. Applies the toxic-truth-teller-style writing voice by default. Use when research or a comment letter for a permit fight is done and it's time to turn it into a local social media push.
argument-hint: <research-doc-path> [more doc paths...] --deadline <date> [--posts <n>] [--audiences <list>] [--no-style] [--slug <name>] [--cta <auto|hearing|comment>]
allowed-tools: Read, Write, Glob, Grep, Bash, AskUserQuestion, Skill, WebSearch
---

# bayou:nextdoor-campaign — local social media campaign generator

Turn a finished piece of permit/campaign research into a dated series of Nextdoor
posts, each pitched at a specific audience archetype, escalating toward a comment or
hearing deadline. This is the last step in the Bayou Blockade pipeline — research
(`bayou:permit-analysis` or equivalent) produces the facts, this skill turns them into
the local social push that gets neighbors to actually submit comments.

Bundled in this skill's directory:
- `archetypes.md` — the default audience-archetype menu (starting point, not exhaustive)
- `templates/campaign.md` — the output skeleton (header + per-post block)
- `profile.example.md` — **placeholder-only** personal-profile questionnaire (see Step 3 — never put real personal data here)
- `references/holidays.md` — US/Louisiana holiday reference for calendar pacing (see Step 5)
- `scripts/preview_subject_line.py` — simulates Nextdoor's email-subject truncation of a post's opening line (see Step 7)

Real campaigns in this style: GNOTS Reserve Barge Fleet / IMTT Luling, IMTT renewal and
discharge permits, Union Carbide Part 70, Lapis Well, Waterford 5 open house and LDEQ
permit. The GNOTS campaign is the structural model this skill follows: 7 posts over 3
weeks, opening with a broad-alarm post, moving through health → money/property → safety
→ wildlife/waterways → environmental-justice/history/labor, and closing with a 48-hour
final push carrying a copy/paste comment template.

## Parsing arguments

Required:
- At least one research doc path (a findings report, comment letter draft,
  `verification/FINDINGS-FOR-REPORT.md`, or similar).
- `--deadline <date>` — the comment/hearing deadline. If omitted, look for one stated in
  the research doc; if found, confirm it with `AskUserQuestion` before proceeding rather
  than assuming it's right. If neither is available, ask for it — the whole calendar in
  Step 5 depends on it.

Optional:
- `--posts <n>` — exact post count. If omitted, infer in Step 5.
- `--audiences <list>` — override archetype selection; otherwise choose from
  `archetypes.md` (or campaign-specific archetypes not in that file) per post in Step 6.
- `--slug <name>` — filename slug. Default: derive a short kebab-case slug from the
  research doc's campaign/facility name.
- `--no-style` — skip Step 2 (don't apply the writing-style skill).
- `--cta <auto|hearing|comment>` — override the call-to-action decision in Step 7.
  Default `auto`. `hearing` means: always make the CTA "attend the public hearing" in
  every post, for as long as the hearing hasn't happened yet — useful when the user
  says something like "prefer a hearing-attendance CTA if the hearing hasn't happened
  already." `comment` forces every post to a comment-submission CTA even if a hearing
  is scheduled. See Step 7 for the full decision logic.

## Step 1: Confirm inputs are complete

Before doing any drafting, make sure you have: the research doc(s), a confirmed
deadline, and (per Step 3 below) a readable private profile. If any of these are
missing, stop and ask rather than guessing — a wrong deadline or a fabricated profile
detail is worse than a delay.

## Step 2: Apply the writing voice

Unless `--no-style` was passed, invoke `Skill(bayou:toxic-truth-teller-style)` by name
before drafting. That skill is opt-in only and requires being explicitly requested by
name elsewhere in the toolkit — naming it here, in this skill's own instructions,
satisfies that requirement. It shapes the sensory/framing conventions used in Step 7;
it does not replace the fact-sourcing discipline of Steps 3–4.

## Step 3: Read the private Bayou Blockade profile — treat it like a credential, not bundled data

The profile holds Joseph's personal narrative material: family health conditions,
geographic/environmental exposure, ancestral or cultural connection to the area,
opposition targets, and argumentative angles he's comfortable using in public posts.
This is sensitive personal data, so it follows the same public/private split
`bayou:kit-dissemination` uses for API keys:

- **Public template (committed to the plugin):** `profile.example.md` in this skill's
  directory — section headers with placeholder instructional text, safe to share.
- **Private real data (never committed, lives outside this repo):** read it from
  `~/.claude/bayou-profile.md`.

Read `~/.claude/bayou-profile.md` with the `Read` tool. **If it doesn't exist, stop**
and tell the user: copy `profile.example.md` to `~/.claude/bayou-profile.md` and fill it
in, then re-run. Do not fall back to guessing personal details, and do not read profile
content from any other path (old drafts, other project directories, etc.) even if you
know one exists — the point of the fixed path is that it's the one place this skill is
allowed to trust.

Hard rule: never read from or write to any path *inside* `~/.claude/plugins/bayou/` (this
repo) for the real profile, and never echo the full profile content into the generated
campaign file or any other output — pull only the narrative angles actually meant for a
public Nextdoor post (the same judgment call the user already makes writing these by
hand), not the raw source material verbatim.

## Step 4: Read the research doc(s)

Read every supplied research doc for: campaign-specific facts, stats, and quotes; the
actual comment-submission mechanics (portal URL, email address, permit or docket
reference number); anything that supports a specific audience angle (health,
money/property, safety, wildlife, environmental justice/history/labor); and — this
feeds the CTA decision in Step 7 — **whether a public hearing exists at all, and if so
its status**: not yet requested, requested but not yet scheduled, or scheduled with a
specific date/time/location. Note whether the comment period and any hearing date
overlap or are sequential (a hearing is sometimes mid-comment-period, sometimes after
it closes).

If the research doc is itself a markdown summary (e.g. `FINDINGS-FOR-REPORT.md`), any
hard factual claim you use in a post should be traceable through that doc's own
citations back to a source record — this skill doesn't re-verify against PDFs itself,
but don't invent a fact that isn't actually present in the supplied research.

## Step 5: Compute the posting calendar — deterministically, not from memory

LLMs are unreliable at figuring out what day of the week a given date falls on, and a
campaign that lands a post on a major holiday reads badly (nobody wants to read about
an ammonia plant on Christmas Eve). So:

- **Use the `date` command via Bash for every day-of-week and date-arithmetic
  computation.** Never state a day-of-week without having actually run something like:
  ```bash
  date -j -f "%Y-%m-%d" "2026-08-11" "+%A, %B %d, %Y"
  ```
  (macOS `date` syntax — this environment is Darwin.) To add/subtract days:
  ```bash
  date -j -v+3d -f "%Y-%m-%d" "2026-08-11" "+%Y-%m-%d"
  ```
- The window runs from today (known from context) to the confirmed deadline. Pick a
  post count: use `--posts` if given, else infer — roughly one post every 2–4 days,
  5–9 posts total (GNOTS used 7 over 3 weeks), with the **last post landing 24–48 hours
  before the deadline** as the final push.
- Check every candidate date against `references/holidays.md`. It distinguishes
  fixed-date holidays (safe to check directly) from movable ones (Easter, Mardi
  Gras/Fat Tuesday, Thanksgiving, Memorial Day, Labor Day) that shift year to year —
  **confirm movable holidays for the actual campaign year using `date` arithmetic or a
  WebSearch, never from trained-data memory.** Mardi Gras in particular matters for a
  Louisiana audience even though it isn't a federal holiday.
- If a candidate date lands on or immediately next to a major holiday, shift that post
  to an adjacent day if the window allows it. If the window is too tight to shift, keep
  the date but have that post briefly acknowledge the holiday rather than ignoring it.
- **Present the full computed calendar in your reply** (date, computed day-of-week, any
  holiday flag) before or alongside the generated file, so a bad computation is easy for
  the user to catch.

## Step 6: Assign one audience/theme per post

Follow the GNOTS emotional arc, compressed or extended to fit the actual post count:
broad alarm opener → personal/health → money/property → safety → wildlife/nature/
waterways → environmental-justice/history/labor → final push (everyone). Pick
archetypes from `archetypes.md` — or campaign-specific ones the research doc actually
supports — for each post's theme line. Don't force an angle the research can't back up;
better to compress the arc than to invent a claim to fit an audience slot.

## Step 7: Draft each post

Each post gets:
- A dated heading (`Post N — Day, Month Date`, using Step 5's computed calendar).
- An italicized theme/audience line (`*Theme. Emotional hook. Audience archetypes.*`).
- A hook opener, then a body blending one profile angle (Step 3) with campaign-specific
  facts (Step 4) — grounded, not invented; every hard claim traces back to the research.
- A bracketed image-suggestion line describing what photo/graphic would pair with the
  post (text description only — this skill does not generate images).
- A CTA block — every post must end with a concrete call to action, never a vague
  "get involved." Decide which kind per the logic below.

### Cold opens — the opening line is an invisible subject line

Nextdoor emails a post out to subscribers using the post's own opening text as the
email subject line, truncated to roughly the first 70 characters (Nextdoor's own
stated limit for sponsored/business content; ordinary posts appear to follow the same
ceiling in practice). That means **the first ~9–12 words of every post do the same job
a subject line does** — most people decide whether to open/engage before reading past
it. Two consequences for drafting:

1. **Cold open, no throat-clearing.** Don't spend the opening sentence setting a scene
   or narrating what the post is about ("I wanted to share something important about
   the barge fleet permit..."). Jump straight into the content itself — the fact, the
   image, the claim — the way GNOTS Post 1 opens with "My mother-in-law lives in
   Luling" rather than "I wanted to talk about my mother-in-law."
2. **Front-load the evocative part.** Whatever makes this post worth opening — the
   person, the number, the threat — needs to land inside that first ~70 characters,
   not after it. It should be evocative and clear; sensational is fine when the
   underlying fact actually warrants it (an armed robbery, an all-caps safety warning),
   but don't manufacture sensationalism the research doesn't support.

The truncation itself is mechanical and does no cleanup: it never cuts mid-word (it
snaps back to the last complete word boundary), it preserves casing/emoji/punctuation
verbatim, and it appends a plain three-period `...` directly with no space — never a
single `…` glyph. Don't try to write "around" the cut by pre-formatting for it; just
write the real opening line and check where it would actually land.

**Check every post's opening line against `scripts/preview_subject_line.py`** before
finalizing — this is a mechanical, programmatic check, not a judgment call:

```bash
python3 skills/nextdoor-campaign/scripts/preview_subject_line.py "Opening line of the post goes here."
```

(Path is relative to the plugin root — use the absolute path to this skill's `scripts/`
directory when invoking.) It reports whether the line would be truncated, how many
characters survive, and flags (non-zero exit + WARNING) when fewer than 20 characters
would survive truncation — a sign the point comes too late and the opening needs to be
reordered or tightened, not just shortened. A truncated line is not itself a problem
(several real examples truncate and still work); an opening line where the *point*
doesn't survive truncation is the actual failure mode to catch.

### Deciding the CTA: hearing attendance vs. comment submission

Every campaign needs *a* clear ask, but which one depends on what Step 4 found and on
`--cta`:

- **`--cta comment`** — always CTA to submit a written comment (portal/email,
  reference number), regardless of hearing status. If a hearing exists, still mention
  it as a secondary "and consider attending" line, but the primary ask is the comment.
- **`--cta hearing`** — always CTA to attend the hearing, for as long as it hasn't
  happened yet (check the hearing date against today via the same `date` mechanism as
  Step 5). Once the hearing date has passed, fall back to `auto` logic for any
  remaining posts in the run (e.g. a hearing early in the window followed by posts
  closer to a later comment deadline).
- **`--cta auto` (default)** — decide from what the research doc actually established:
  - No hearing requested/scheduled yet → CTA is submitting a comment, and (matching the
    GNOTS model) the comment itself can ask the agency to hold a hearing.
  - Hearing requested but not yet scheduled → CTA is still the comment submission; note
    in the post that a hearing has been requested and is pending.
  - Hearing scheduled and still upcoming → CTA is attending the hearing (date, time,
    location) as the primary ask; if the comment period is still open concurrently,
    add submitting a comment as a secondary ask rather than dropping it.
  - Hearing already happened → CTA reverts to comment submission (if the comment period
    is still open) — never tell people to attend an event that's already passed.
- Regardless of mode, source the actual mechanics (portal URL, email, reference number,
  or hearing date/time/location) from Step 4 — never invent submission details or a
  hearing time that wasn't in the research.

The final post additionally includes a copy/paste, personalizable action template
matching whichever CTA Step 7 selected (a comment-language template, or an RSVP-style
hearing reminder if the CTA is hearing attendance), plus a closing "share this" line.

## Step 8: Assemble the file

Combine the header (title, deadline, "N posts • date range" summary) and the drafted
posts using `templates/campaign.md`'s skeleton.

## Step 9: Write output

Write to `notes/<slug>-nextdoor-posts.md` relative to the current working directory if
a `notes/` directory exists there; otherwise write `<slug>-nextdoor-posts.md` directly
in the CWD. Report the path back to the user.

## Step 10: Hand back for review — do not proceed further unasked

This produces a draft for human review. There is no posting integration (Nextdoor has
no API) and none should be improvised. Report the file path and the computed calendar,
and stop.

$ARGUMENTS
