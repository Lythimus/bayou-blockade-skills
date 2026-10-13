---
name: ej-meme
description: Turn finished permit/campaign research into a small set of environmental-justice memes for Nextdoor and similar local feeds. Each meme makes one sourced point, funny first, then the "bum deal" the community is being handed. Plain language, standalone or in-post mode, template choice by rhetorical move (searching beyond the usual formats), pre-render lint, a user review pause, and automated legibility QA (text too small or clipped at phone width). Also re-renders and QAs old meme CSVs. Use when research is done and the campaign needs images, or when the user asks for memes about a facility, permit or agency decision.
argument-hint: <research-doc-or-csv> [more...] [--mode standalone|in-post] [--count <n>] [--slug <name>] [--backend memegen|imgflip] [--post <text-or-path>] [--footer <text>] [--render-only <csv>]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Skill
---

# bayou:ej-meme: environmental-justice memes that survive the scroll

A meme gets one second in a feed. In that second it should get a laugh, then leave one
thought behind: **what the community is giving up, and what the company gets for it.**
One idea per meme. It doesn't have to tell the whole story. The post, the comment letter
and the hearing do that.

The old campaign sheets generated about 250 memes, and only a handful were worth posting.
What went wrong is written up in `references/tone-and-boundaries.md` (calibration and
before/after rewrites). In short: walls of text, unexplained acronyms, invented facts,
swapped panels, and setups that only made sense to someone who'd read the permit.

Bundled in this skill's directory (`S=${CLAUDE_PLUGIN_ROOT}/skills/ej-meme`):
- `references/templates.md`: rhetorical move → template, box roles, good/bad examples,
  and how to find templates beyond the curated list
- `references/templates.json`: machine-readable roles and word targets (read by the scripts)
- `references/plain-language.md`: the standalone/in-post rules, numbers, word budgets,
  and the acronym allowlist
- `references/tone-and-boundaries.md`: purpose, punching up, truth rules, off-limits,
  Nextdoor rules, calibration examples
- `scripts/templates.py`: search memegen (~200) + imgflip top 100; show/verify templates
- `scripts/lint.py`: pre-render checks
- `scripts/render.py`: CSV → PNGs + `manifest.json` (memegen by default, imgflip optional)
- `scripts/qa.py`: legibility QA via tesseract at phone-feed width

Requirements: `python3` with Pillow; `tesseract` for QA (`brew install tesseract`). memegen
needs no account. imgflip-only templates (Boardroom, Buff Doge, …) need
`IMGFLIP_USERNAME` / `IMGFLIP_PASSWORD` in `~/.claude/bayou-credentials.md` (template:
`bayou-credentials.example.md`). Never put credentials in a CSV, a script or this repo.

When using privately supplied community information, personal experiences, sensitive
locations, or claims to represent a community position, read the shared
[community-information guidance](../../references/community-information.md)
(at `${CLAUDE_PLUGIN_ROOT}/references/community-information.md`). Apply it only to
the affected material; public-record-only drafting proceeds normally.

## Parsing arguments

- **Inputs:** one or more research docs (`FINDINGS-FOR-REPORT.md`, a comment letter, a
  fact sheet, a nextdoor-campaign draft). A `.csv` input in the meme schema means "start
  from these drafts": skip to Step 5.
- `--mode standalone|in-post`: default `standalone`. See `references/plain-language.md`.
  In-post with no `--post`: ask for the post text, or ask whether to switch to standalone.
- `--count <n>`: default 5. Make fewer if the research doesn't hold that many distinct
  sourced points. Never pad.
- `--slug <name>`: output folder name. Default: kebab-case facility/campaign name from the
  research doc.
- `--backend memegen|imgflip`: forces one backend. By default each row routes by its
  Template_ID (slug → memegen; numeric → imgflip if credentials exist, else memegen on the
  imgflip blank where that works).
- `--post <text-or-path>`: in-post mode. The post the meme will run under. Names the post
  explains can go in captions; pass them to lint as `--allow`.
- `--footer <text>`: standalone mode. A plain strip under each image naming place and
  project ("Proposed ammonia plant, Pelican Bayou LA"). Offer it when the captions don't fit
  the place.
- `--render-only <csv>`: no drafting. Lint (with `--legacy` if there's no `Source` column),
  render and QA an existing or old CSV, then report.

Output goes to `./memes/<slug>/` in the current working directory (not the plugin):
`memes.csv`, the PNGs, `manifest.json`, `qa.json`.

## Step 1: Harvest claims

Read every input doc in full. List candidate facts in a scratch table: the claim in plain
words, the exact figure, and the **source** (doc + page/section/line). Drop anything you
can't source to the docs. No numbers or events from memory, and nothing "everyone knows".

Favor claims that are:
- **Sensory or lived:** smell, noise, flares, fire, flooding, dust on cars, kids, the
  school, the lake people fish.
- **Locally recognizable:** a named neighborhood, road, lake, school or church.
- **A single striking number:** a fine, a count of fires, a distance, a tax break.
- **The company's own words,** quoted exactly ("very minimal impacts").

## Step 2: Pick the bum deal, one per meme

For each meme, choose **one** claim and write the trade in one line:
**what the community gives up → what the company gets.**
If you can't write that line, drop the claim. Rank by concreteness, local recognition and
sensory detail, and make the set varied: not five memes about the same number.

## Step 3: Choose the template by move

Name the move first (shrugs off harm, false choice, plan undermines itself, greenwash,
bum deal…), then pick from `references/templates.md`. **Don't stop at the curated list.**
Once per set, browse the whole catalog (`templates.py search ''`, ~300 lines: memegen
plus imgflip's current top 100) and judge from what each format looks like; keyword
search is thin because memegen's keywords are sparse. Use a new template only if it passes that file's five checks
(recognizable to an older audience, picture matches the move, box positions known, phone
test, punching up). Don't use the same template twice in one set unless the user asks.

```bash
S=${CLAUDE_PLUGIN_ROOT}/skills/ej-meme
python3 $S/scripts/templates.py search smug money
python3 $S/scripts/templates.py show <slug-or-imgflip-id>
```

## Step 4: Draft captions

Write under `references/plain-language.md` (the mode rules, numbers, word budgets) and
`references/tone-and-boundaries.md` (punch up, truth rules, off-limits). Follow the box
roles exactly as listed for the template.

Write `memes/<slug>/memes.csv`:

```
Meme_Title,Template_ID,Caption1,Caption2,Caption3,Caption4,Source,Point,Footer
Two_Buttons_Fine,ds,Pay the $90K fine,Fix the safety violations,,,"Findings §3.2 (EPA consent order p.4)",Cheaper to pay than to fix,
```

- `Template_ID`: the memegen slug whenever one exists; the imgflip numeric ID only for
  imgflip-only templates. Box order is verified by render for every curated template. For
  a template found by search, render it once with `BOX 1`, `BOX 2`, … captions and look
  at it before writing real captions. Also check for text already baked into the image
  (Trade Offer's "i receive:", UNO's "or draw 25") so captions don't repeat it.
- `Source`: required whenever a caption has a digit. Use doc + page/section.
- `Point`: the one-line bum deal from Step 2.
- `Footer` (optional, standalone): overrides `--footer` for that row.

`skills/toxic-truth-teller-style` is **not** applied by default; captions are too short to
need a voice. Invoke it by name only if the user asks.

## Step 5: Lint

```bash
python3 $S/scripts/lint.py memes/<slug>/memes.csv --mode <mode> [--allow AAF] [--legacy]
```

Fix every error (box count over the template, a box over its hard word cap, an acronym
not on the allowlist, a number with no source) and reconsider every warning. Lint is
calibrated so the user's past picks pass with warnings and the walls of text fail.

One check the script cannot make: read the set as a whole. If every meme shows only what is
being done *to* the community, add or swap one that shows what the community is doing or asking
for (the hearing it is packing, the monitors it put up, the condition it wants in the permit).
A feed of pure harm tells neighbors the fight is already lost.

## Step 6: Pause for user review

Stop. Show a table, one row per meme: **title · template (and why) · captions by box ·
the one-line point · source.** Mention any lint warnings left in place and why. Then
confirm with AskUserQuestion: render as is / I'll edit the CSV first / redraft specific
memes / cancel. Re-read `memes.csv` after confirmation; the user may have edited it.

## Step 7: Render

```bash
python3 $S/scripts/render.py memes/<slug>/memes.csv --out memes/<slug> --mode <mode> [--footer "..."]
```

`manifest.json` records each meme's captions, template, backend, source, point and URL. If
a row fails because an imgflip-only template has no credentials, say so, and offer a
memegen alternative from the same move or ask the user to add credentials. Don't silently
swap templates.

## Step 8: Legibility QA

```bash
python3 $S/scripts/qa.py memes/<slug>
```

qa.py OCRs each image at its own resolution and measures text at 400px width (a phone
feed). It reports, per caption:
- **FLAG:** under 35% of the letters recovered (dropped, crushed or tiny), text under 7.5px
  tall at feed width, or a 12+ word caption shrunk under 9px (a wall of text).
- **note:** 35–60% recovered (common for rotated or condensed text), 7.5–9px tall, words
  flush with the border, or a caption whose height couldn't be measured (often tiny text).

These are heuristics. Outlined meme text OCRs badly, so the thresholds were calibrated on
the user's chosen memes (3 of 17 flagged, all visibly small) and on rejected ones (10 of
20 flagged). **qa.py doesn't decide.** Look at every FLAG image and any note you're unsure
about with the Read tool. For a phone-scale view, downscale a copy to 400px wide (Pillow)
and look at that. Then fix: shorten the caption, move words to another box, pick a
template with bigger text areas, or drop the footer. Re-render and re-run QA. Report any
flags you chose to keep, and why.

## Step 9: Cold-read check

For each meme, write one sentence: **what would a neighbor scrolling past with no context
take away?** Compare it to the `Point` column. If they don't match, the meme doesn't make
its point. Revise it, or cut it. In standalone mode, also check: does the image alone say
where and what? If not, add the place to a caption or use the footer.

## Report

List the final memes (file, template, point, source), anything flagged and kept, and any
memes cut and why. Give the output folder path. Don't post anything anywhere. Posting is
the user's call.

## With `bayou:nextdoor-campaign`

Not wired in automatically. After a campaign is drafted, the user can run this skill per
post with `--mode in-post --post <that post's text>`, so each image leans on its post for
names and background and adds the one-second version of the post's point.
