---
name: unmarked-burial-screen
description: Documentary-research screen for Louisiana's Unmarked Human Burial Sites Preservation Act (R.S. 8:671-681) — checks the local case file first, then runs historic maps/lidar, newspaper archives, and NRHP proximity against a project site, and drafts (never sends) records requests to the state archaeologist, SHPO, USACE, and local archives
argument-hint: <site name or facility> <lat,lon> [known adjacent community]
allowed-tools: Bash, AskUserQuestion
---

# Unmarked Burial Site Documentary Screen

Runs the "documentary research" a Louisiana Unmarked Human Burial Sites Preservation Act permit
turns on: whether a project area **"may have human remains present"** or is **"located
immediately adjacent to a property known to have burials"** (R.S. 8:671–681). Neither trigger
requires proof — the bar is *may* — so the deliverable of this screen is honestly, and usually,
**"elevated probability, survey warranted,"** not a confirmed finding either way. Treat that as a
sufficient and successful output, not an unsatisfying one.

This composes three other things rather than reinventing them: `bayou:usgs-historic-topo-lidar`
(map/lidar time series), `bayou:historic-newspaper-search` (documentary sweep), and
`bayou:la-species-cultural-review`'s NRHP step (proximity to listed historic properties). Use
`bayou:geo-distance` for any point-to-point distance in the writeup rather than reimplementing
haversine math inline.

## Step 0 — check the local case file before doing anything else

**Do this before any external research call. It is the single highest-value step in this entire
skill.** If there is an existing project directory, permit-comment archive, or prior research
(a `regulatory/`, `air permit/comments/`, or similar folder), grep it first:

```bash
rg -il -e "archaeolog" -e "cultural resource" -e "cemetery" -e "burial" -e "SHPO" \
   -e "historic preservation" -e "phase i" .
```

On the one run this skill was built from, this single command surfaced a public comment letter
— already sitting in the working directory — from a professional historic preservationist who
had personally visited the site, photographed a named cemetery, and disputed the applicant's own
Phase I cultural-resources survey as inadequate. That letter did more of the actual documentary
work than a from-scratch digital screen could have reconstructed independently, and it took
seconds to find. **If a project has any public-comment history, litigation history, or prior
consultant reports anywhere on disk, read those in full before concluding anything is unknown.**
A grep hit deep in a large combined PDF-derived `.txt` file is easy to skim past — when you find
one, read the surrounding pages, not just the matched line.

If existing material like this exists, this screen's job shifts from "generate new findings" to
"verify, extend, and independently cross-check what's already been asserted" — which is a
different and usually faster task. Say so explicitly in the output rather than presenting
synthesis of someone else's prior work as if it were new research.

## Step 1 — site framing

Get from the user or the case file: the project footprint (address + lat/lon, ideally the actual
parcel boundary, not just a single reference point — see the proximity note below), the name of
any adjacent historic community, plantation, or settlement, and the permit or docket number this
screen is in service of. If any of this is missing and the project has a public notice on file
(USACE, LDEQ), pull it from there rather than asking the user to restate what's already
documented.

## Step 2 — historic maps and lidar

Run `bayou:usgs-historic-topo-lidar` against the footprint. Read every edition for: a cemetery
symbol, isolated structure clusters (especially at the rear of a French-arpent long-lot, which
runs perpendicular to the river — the classic siting for marginal land, including burial
grounds, on both plantations and the freedom colonies that sometimes succeeded them), a named
plantation or community label, and — the single most informative pattern across a time series —
**a feature present on an earlier edition that is gone on a later one**, which can indicate a
burial ground or structure cleared and built over.

## Step 3 — documentary sweep

Run `bayou:historic-newspaper-search` for: the plantation name, any adjacent community/settlement
name, any named founder or prominent resident, and the county/parish's general place-names (to
sanity-check corpus coverage per that skill's own guidance). Also check:

- **NRHP proximity** via `bayou:la-species-cultural-review`'s Step 3 (NPS ArcGIS layer) — but
  remember unmarked burial grounds are close to definitionally *absent* from NRHP by design; a
  clean NRHP search is not evidence of anything and shouldn't be reported as if it were.
- **The regulatory file itself** for the project (LDEQ EDMS via `bayou:ldeq-edms-search`, USACE
  via `bayou:usace-408-permits`) for any cultural-resources survey referenced but not attached,
  or SHPO correspondence that exists in citation only. **A survey's existence, characterized only
  by the applicant's one-line summary of its own conclusion, is not the same as having reviewed
  the survey** — track down the actual document (see Step 5) rather than treating the applicant's
  paraphrase as the finding.

## Step 4 — the two statutory triggers, assessed separately

Write these up as two distinct questions, not one blended impression:

1. **"May have human remains present"** — what does the documentary/cartographic record show
   about the footprint *itself*? Historic maps showing sustained undisturbed marsh/marginal land
   is weak-to-moderate evidence either way (informal/unmarked burial grounds don't reliably show
   up on topographic surveys regardless of whether they exist). A map showing an actual
   disappearing structure or cemetery symbol is much stronger.
2. **"Immediately adjacent to a property known to have burials"** — is there a *known* (marked
   or documented) cemetery or burial ground on a neighboring parcel? This is the trigger most
   likely to be resolvable from documentary sources alone, especially site-visit letters,
   historical markers, or a labeled "Cem" symbol on a topo sheet. **Compute proximity from the
   actual parcel boundary if you have it — a reference-point-to-point distance will overstate
   true separation for any footprint larger than a few acres**, and a project's own permit
   drawings (site plans, "residential offset" exhibits) often already show the real boundary if
   you look for it rather than assuming a single lat/lon is the whole story.

State the conclusion as a probability judgment against these two triggers, not as a yes/no. If
the honest answer is "elevated probability, survey warranted" — which is the statutory bar, and
was the outcome the one run of this skill produced — say exactly that.

## Step 5 — draft records requests (draft only — never send, never auto-submit)

Standard recipients, adjust names/contacts per parish and confirm current before sending:

- **LA Division of Archaeology / State Archaeologist** — `archaeology@crt.la.gov`, (225) 342-8200.
  Site-file/recorded-cemetery check, and — if a Phase I survey exists but hasn't been obtained —
  request the actual report by name, not just confirmation it exists.
- **LA State Historic Preservation Office** (same parent office, Division of Historic
  Preservation) — Section 106 consultation posture, determination-of-eligibility correspondence.
- **The relevant federal permitting district** (USACE, etc.) — the cultural-resources portion of
  the administrative file, and the full-resolution version of any site/area map exhibit that a
  public comment cites for a proximity claim you couldn't independently confirm at the resolution
  you had.
- **Archdiocese/diocesan archives** (if Catholic sacramental record jurisdiction is plausible) —
  ask which parish church held jurisdiction before requesting specific registers.
- **Local historical/genealogical society** and **parish Clerk of Court** (Original
  Acts/conveyance records, succession/probate) — the chain-of-title and named-individual sources
  that stay genuinely offline; state plainly that these requests may require in-person or fee-
  based research and don't promise a turnaround time you don't actually know.

Mark every letter **DRAFT ONLY — NOT SENT** at the top, and leave sender/contact fields as
placeholders for the user to fill in and review before anything goes out.

## Handling — non-negotiable, regardless of what the findings turn out to be

- **Keep full coordinates and precise site locations in local working files only.** Redact
  precise burial-site coordinates from anything drafted for publication, public comment, or press
  — describe proximity and probability qualitatively there instead. This mirrors why Louisiana's
  own archaeological site-file database is itself withheld from public request by design (to
  deter looting) — treat that as a model to follow, not an obstacle to route around.
- **Descendant communities and the State Archaeologist see findings before anything goes public.**
  This research supports a community's claim to its own history; it does not make that claim on
  their behalf, and — per Step 0 — the community has very often already documented and asserted
  it far more thoroughly than an outside digital screen can.
- **Don't fabricate or round out names.** If a name, date, or fact can't be traced to a specific
  retrieved source, it does not go in the memo. A hallucinated ancestor's name in a filing is
  uniquely destructive — it discredits the entire effort and the community that may come to rely
  on it.

## Presenting results

Structure the final memo as: site framing → what already existed in the record before this
screen ran (if anything) → each source consulted and what it did and didn't show → the two
triggers assessed separately with an explicit probability judgment → open questions that need
physical/offline follow-up (parish Clerk of Court, succession records, actual parcel plats) →
the drafted requests. Every factual claim carries its source and retrieval date, in the citation
formats used by `bayou:usgs-historic-topo-lidar` and `bayou:historic-newspaper-search`.

$ARGUMENTS
