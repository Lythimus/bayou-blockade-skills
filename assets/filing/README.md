# Bayou Blockade filing style

Shared LaTeX styling for regulatory filings — public comments, complaint letters, analysis
reports. Used by `bayou:permit-comment` Step 9, and available to any hand-written filing that
wants to match.

Three files:

| File | Role |
|---|---|
| `bayou-filing.tex` | The style. A pandoc `--include-in-header` fragment, not a standalone preamble. |
| `bayou-filing.lua` | Maps fenced divs in the markdown onto the callout environments. |
| `README.md` | This file. |

## Rendering

Write a per-campaign identifier file, `<slug>-id.tex`, beside the markdown:

```latex
\def\filingkind{<filing type — e.g. Public Comment and Request for Public Hearing>}
\def\filingid{<AI / permit / activity numbers, as printed in the notice>}
\def\filingagency{<full agency name>}
\def\filingshort{<short campaign label for the running head>}
\def\filingauthorline{<commenter name(s)> · <town, parish>}
```

When `bayou:permit-comment` drives this, `\filingauthorline` is taken from the private profile
at `~/.claude/bayou-profile.md` (its Core Identity section), never typed from memory. Keep the
street address out of it — the mailing address for notice belongs in the signature block, where
the agency looks for it.

Then:

```bash
BAYOU=~/.claude/plugins/bayou/assets/filing

pandoc letter.md -o letter.pdf \
  --pdf-engine=xelatex \
  --lua-filter="$BAYOU/bayou-filing.lua" \
  --include-in-header=letter-id.tex \
  --include-in-header="$BAYOU/bayou-filing.tex"
```

All five `\def`s are optional; unset fields drop out of the letterhead rather than leaving an
empty line. The letterhead itself renders from the markdown's `title:` and `date:` front
matter — pandoc only emits `\maketitle` when `title:` is present, so front matter is the switch
that turns the letterhead on.

### Two traps worth knowing

**Identifiers must go in `<slug>-id.tex`, not in the markdown's YAML `header-includes`.**
`--include-in-header` sets the pandoc *variable* `header-includes`, and a variable shadows the
metadata field of the same name. Put `\def`s in YAML alongside a `-H` flag and they are dropped
with no warning and no error — the document just renders with the defaults. Multiple `-H` files
concatenate in the order given, which is why the id file goes first: its `\def` wins over the
`\providecommand` fallbacks in the style.

**Order inside `bayou-filing.tex` is load-bearing.** pandoc 3.x emits `$header-includes$`
*before* it loads hyperref, so the file cannot call `\hypersetup` directly — link colors are set
in an `\AtBeginDocument` hook instead. xcolor, geometry, and fontspec are all loaded before the
hook, so those are safe to use directly.

## Markdown vocabulary

Three fenced divs, via the Lua filter:

```markdown
::: comment
**Comment 4.** LDEQ should condition the permit on …
:::

::: recordquote
Flaring is limited to upset, startup, shutdown, and emergency conditions.

— Doc 15072324, Section 4.2, p. 18
:::

::: alert
Under La. R.S. 30:2050.21 only an aggrieved person may appeal.
:::
```

`::: comment` gets a heavy blue left rule, `::: recordquote` a thin gray one plus italics,
`::: alert` a shaded box. All three break across pages.

Ordinary `>` blockquotes are left as ordinary quotations — deliberately. A filing quotes the
agency's own record constantly, so `>` has to keep meaning "quotation"; overloading it to also
mean "requested permit condition" would erase the distinction in the one document where it
matters most. Non-LaTeX output passes the divs through untouched, so the markdown remains
filable by email or portal paste.

## Why the numbered comments get a callout

LDEQ builds its Public Comments Response Summary by walking the numbered comments. A comment
that a permit writer cannot find is a comment that does not get answered, and an unanswered
comment is one that was not preserved. The blue rule exists so that flipping a 40-page PDF
surfaces every requested condition without reading the prose.

## Engine

xelatex or lualatex. Under pdflatex the font block is skipped and the document falls back to
the class default face; everything else still applies. TeX Gyre Pagella is loaded **by filename
rather than family name** — it ships with TeX Live but is not registered with fontconfig on
macOS, so `\setmainfont{TeX Gyre Pagella}` fails while the file-based form resolves through
kpathsea.

## On branding

There is deliberately no logo, wordmark, or organizational letterhead here.

Standing under La. R.S. 30:2050.21 runs to an **aggrieved person**, not to a group. A masthead
for an unincorporated group invites the agency to address its response to an entity that has
shown no interest of its own, and gives an easy argument that the commenter is an advocacy
outfit rather than a resident of the affected parish. Branded filings also tend to get triaged
as campaign mail.

This is also the profile's own instruction, not just a style preference. `bayou-profile.md`
records that "Bayou Blockade" is an informal campaign name rather than a nonprofit or formal
entity, and that filings must not be signed as though it were an organization. `\filingauthorline`
therefore takes the commenter's name, not the campaign's.

What the style aims at instead is the register of the hand-written filings this was derived
from: a person who knows the record, typeset well.
