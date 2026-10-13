# Plain language for meme captions

A meme gets about one second of attention in a scrolling feed. If the reader has to decode
a word, the joke is gone and so is the point. Write for a neighbor who has never heard of
the project, the permit or the company.

## The two modes

### Standalone (default)

Assume the image gets screenshotted and passed around with no post attached, which is
what happens to every meme that works.

- **Name the place and the thing in plain words.** "The ammonia plant planned for Pelican Bayou",
  not "AAF". "The tank farm in Pelican Bayou", not the company's initials. "The carbon
  dioxide wells under Lake Heron", not "the Class VI project".
- **Name the company only when the name itself carries weight** (a well-known brand, or a
  name residents already say out loud). Otherwise describe what it is.
- **Agencies get described, not abbreviated.** "The state environmental agency", "the state
  regulators", "the parish council". EPA is the one agency most people know by initials.
- **Use the footer** when the captions can't fit the place: `render.py --footer "Proposed
  ammonia plant, Pelican Bayou LA"` adds a plain strip under the image. The footer is a label,
  not a second caption: place + project, under 8 words.

### In-post

The meme sits under a Nextdoor post that already explains the background (see
`bayou:nextdoor-campaign`). Captions may lean on it:

- Locally known names the post has introduced (a plant's initials like AAF, the parish name)
  are fine. Pass them to lint with `--allow AAF`.
- Still one point, still no jargon. "Minor source", "Title V", "PSD", "Class VI",
  "mitigation bank", "USDW" are jargon even in-post, so translate them.
- The meme should still make sense to someone who scrolls past the post text and only sees
  the image. If the joke needs the post, it's an illustration, not a meme.

Most of the user's chosen calibration memes are in-post memes: they use the companies'
initials because they ran under posts about those facilities. See tone-and-boundaries.md for the
standalone rewrites.

## Numbers

- **Every number needs a source** in the CSV's `Source` column (doc + page/section). Lint
  fails a caption with digits and no source.
- **Round, and make it relatable.** "$90K fine" or "a $90,000 fine", not "$90,412.50".
  "3 fires in 3 years". "900 feet from homes". Keep the exact figure in `Source`.
- **Percentages over 100% are hard to picture.** Convert them, and recompute every time:
  "X% above" a limit means (1 + X/100) times the limit. 4,900% above = **50 times** the
  limit, not 49 and not 5. When unsure, say "dozens of times the limit" and keep the
  exact figure in the source.
- **"8x more" is ambiguous** (8 times as much, or 9?). Prefer "8 times as much".
- **Spell out units** a neighbor wouldn't know: "tons a year", not "tpy"; "parts per
  billion", or better, compare it to the safe limit.
- **Keep the source's hedges.** "Permitted to release up to", "could", "estimated". A meme
  that drops a hedge turns a true claim into a false one.

## Word budgets

Calibrated on the memes the user actually chose to post (12–22 words total) and on rejected
ones (25–37 words). Lint warns over the target and fails over the hard cap.

| | Target | Hard cap |
|---|---|---|
| Per box (multi-box template) | 6, or the template's `target_words` in templates.json | max(12, target + 4) |
| Single-box reaction (Monkey Puppet, Harold, Disaster Girl) | 14 | 20 |
| Total, multi-box | 15 | 24 |

Shorter is almost always funnier. The target is where the jokes land; the cap is where
the image starts shrinking text into a wall.

## Word swaps

| Instead of | Write |
|---|---|
| emissions / releases | pollution, what comes out of the stacks |
| facility | plant, tank farm, refinery (say which) |
| permit modification | asking to pollute more |
| minor source | (explain the trick: "split into two permits so neither counts as big") |
| fugitive emissions | leaks |
| mitigation | (say what they're paying instead of protecting) |
| sequestration / Class VI | pumping carbon dioxide underground |
| economic development | jobs (and say how many) |
| community engagement | a meeting / a mailer |
| non-attainment | air that already fails federal standards |

## Acronym allowlist

`lint.py` reads the backticked tokens in this section. Anything else in caps that isn't an
ordinary English word fails lint in standalone mode. Add to this list only acronyms an
average adult reads without thinking.

`EPA` `CO2` `US` `USA` `LA` `TV` `CEO` `CEOs` `OK` `DIY` `ER` `ICU` `PM` `AM` `HOA` `FAQ` `NASA` `IRS` `ATM` `NFL` `LSU`

Not on the list, on purpose: `LDEQ` (say "state environmental agency"), `DNR` / `SONRIS`,
`USACE` ("the Army Corps"), `TRI`, `NOx`, `VOC` ("chemicals"), `PM2.5` ("soot"), `ESG`, `HB`
plus a number ("the new state law"), `AI`.
