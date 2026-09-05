---
name: public-comment-tts
description: Convert a finished permit-comment Markdown letter into a TTS-clean plain-text file for auditory proofreading (e.g. piping into chatterbox TTS) — disables pandoc's smart-quote injection, expands unicode typographic and scientific-unit characters (em dash, µg/m³, §, etc.) into spoken-safe text via a data-driven substitution table, strips bracket-citation shorthand, and rewrites markdown tables and dash dividers into labeled spoken sentences instead of column-mashed noise. Produces a normalized `<basename>.tts.txt` only — it does not synthesize audio. Use once a bayou:permit-comment draft is finalized and before an audio proofread pass.
argument-hint: <comment-doc-path.md> [--out <path>] [--keep-brackets] [--keep-tables] [--table <path>]
allowed-tools: Bash, Read, Grep, Edit
---

# bayou:public-comment-tts — TTS-clean export for auditory proofreading

Piping a `pandoc -t plain` export straight into a TTS engine surfaces three problems. First, pandoc's
default `smart` extension silently injects curly quotes/apostrophes that may not even exist in the
source Markdown. Second, the typographic and scientific-unit unicode that survives even a clean
pandoc pass (em dashes, `µg/m³`, `§`, …) reads badly or is mispronounced outright. Third, pandoc
renders markdown tables and thematic breaks as fixed-width dash rules and column-aligned text —
harmless on a page, but pure noise once read aloud, and the column alignment itself carries
information (which number belongs to which header) that's lost the moment it's read as a flat run of
numbers. This skill fixes all three, deterministically, and reports exactly what it changed so the
output can be trusted before it's used for a proofread pass.

Bundled in this skill's directory:

- `references/tts-substitutions.json` — the substitution table (phrase patterns, bracket rules,
  single-char rules). Data-driven and meant to grow — see Step 5.
- `scripts/normalize_for_tts.py` — applies the table deterministically and reports exact counts.

This skill produces text only. It never invokes chatterbox or any other TTS engine itself.

## Parsing arguments

Positional argument is the path to a finished comment-letter Markdown file (normally the output of
`bayou:permit-comment`, e.g. `PUBLIC-COMMENT.md`).

Flags:

- `--out <path>` — output path for the TTS export. Defaults to `<basename>.tts.txt` alongside the
  source (e.g. `PUBLIC-COMMENT.md` → `PUBLIC-COMMENT.tts.txt`).
- `--keep-brackets` — don't strip `[SOB]`/`[App]`-style bracket-citation shorthand; leave brackets in
  place. Use this only if the letter's brackets carry meaning that must survive (rare).
- `--keep-tables` — don't linearize markdown tables into "Header: value." sentences; leave pandoc's
  column-aligned plain-text rendering as-is (dash dividers are still stripped regardless). Use this
  only if a table's linearized form reads worse than the raw columns for some specific letter.
- `--table <path>` — use an alternate substitution table instead of the bundled
  `references/tts-substitutions.json`.

## Step 1 — Locate and confirm the source

Confirm the path exists and is readable. If the user hasn't indicated the letter is finished (e.g.
they're mid-revision), ask before proceeding — this is meant to run against a settled draft, not a
moving target, since the substitution counts in the final report are only meaningful against a fixed
input.

## Step 2 — Pre-flight structural scan (source Markdown, before pandoc runs)

Two cheap greps against the *source* file, reported to the user as FYI before continuing:

```bash
grep -cE '^\s*\|.*\|\s*$' "$SRC"                              # markdown table rows
grep -oE '\[[A-Za-z][A-Za-z ]{1,30}\]' "$SRC" | sort | uniq -c | sort -rn   # bracket-citation shorthand
```

Report the counts as FYI — Step 4's `normalize_for_tts.py` handles both automatically (tables get
linearized into sentences, bracket shorthand gets unwrapped), so this is a preview of what's coming,
not a limitation to warn about.

## Step 3 — Run pandoc

```bash
SRC="<source path>"
SLUG="$(basename "${SRC%.*}")"
TMP="/tmp/${SLUG}-pandoc-plain.txt"

pandoc "$SRC" -f markdown-smart --wrap=none --strip-comments -t plain -o "$TMP"
```

- `-f markdown-smart`, never `markdown_strict` — disables only the `smart` (curly-quote-injection)
  extension while keeping every other reader extension active, including `fenced_divs` and
  `pipe_tables`. `markdown_strict` would also disable those, causing `::: comment` divs and pipe
  tables to leak as literal `:::`/`|` text instead of rendering cleanly.
- `--wrap=none` — no hard-wrap at column 72; irrelevant/harmful when piping to TTS.
- `--strip-comments` — strips stray `<!-- -->` HTML comments before they can leak into spoken output.

Sanity-check immediately: confirm `$TMP` is non-empty and its word count (`wc -w`) is the same order
of magnitude as the source. A partial or empty pandoc output should be caught here, not discovered
after normalization.

## Step 4 — Normalize

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/public-comment-tts/scripts/normalize_for_tts.py \
  "$TMP" -o "<out-path>" [--table <path>] [--keep-brackets] [--keep-tables]
```

The script's first pass (before any character substitution) detects pandoc's plain-text table
rendering — bordered or borderless, pandoc omits the top/bottom dash rules for some tables — and
rewrites each row as a sentence: `Header: value. Header: value.` A column with no header (a row-name
column) contributes just `value.` with no label. Cells that are empty or contain only a dash
placeholder (pandoc's rendering of an empty markdown table cell) are dropped from the sentence rather
than read aloud as a stray comma. Leftover markdown thematic-break lines (the `---` dividers between
major sections) are dropped entirely — the heading text right after each one already signals the
section change. A table the parser can't confidently make sense of is left as raw column-aligned text
rather than guessed at, and counted as skipped in the summary.

Capture the full stderr summary — it's the basis for Step 6's report.

## Step 5 — Handle unknown/uncatalogued characters, if any

If the script's summary reports any `UNKNOWN` characters, show each to the user with its codepoint,
name, occurrence count, and surrounding-context snippet (all included in the script's output). Ask
before adding a new rule — `tts-substitutions.json` is a shared reference every future run of this
skill depends on, so a bad or overly narrow rule added silently would affect other letters later.

If the user approves an addition: use `Edit` to add it to `references/tts-substitutions.json` —
phrase tier (`patterns`) if it's a multi-character unit/legal shorthand (like `§§` was), char tier
(`chars`) otherwise. Preserve the existing ordering discipline documented in the table's own `notes`
field. Then re-run Step 4 once against the updated table.

Never invent a spoken form and add it without asking. Never leave a reported unknown character out of
the final report to the user, even if it's minor.

If the summary's `tables_skipped` count is non-zero, tell the user which table(s) the linearizer
couldn't confidently parse (grep the output for the surviving segmented-dash line to locate it) — that
section still has raw column-aligned text in the final output and is worth a manual rewrite if it's
number-heavy.

## Step 6 — Report

Relay to the user:

- The output path.
- Tables linearized, rows produced, border/divider lines dropped, and any tables skipped (from Step 4).
- The full substitution summary by category (phrase patterns, bracket strips, single-char
  substitutions with per-character counts, NFKD fallback transliterations).
- The Step 2 bracket-shorthand preview count.
- Any unknown-character decisions made in Step 5.
- An explicit reminder that this produces text only — running the result through chatterbox (or any
  other TTS engine) for the actual auditory pass is the user's next, separate step.

$ARGUMENTS
