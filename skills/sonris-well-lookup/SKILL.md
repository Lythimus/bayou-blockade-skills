---
name: sonris-well-lookup
description: Find a Louisiana well by serial number, name, or field, or find wells within a parish/section-township-range/lat-lon area — surfaces well documents now, with a documented path to full well-metadata and GIS location search once that endpoint is confirmed live
argument-hint: <well serial | well name | field name> or <parish | section-township-range | lat,lon>
allowed-tools: Bash, AskUserQuestion
---

# SONRIS Well Lookup

Two lookup directions on the same underlying well: **by identity** (serial number, name,
or field) and **by location** (parish, Section-Township-Range, or lat/lon). Both are
useful for a permit report — "what has SONRIS filed about this specific well" and "what
wells exist near this site" are different questions that come up separately.

**What's confirmed and working today (2026-08-15) vs. what still needs a live discovery
pass** — be upfront about the difference rather than presenting a hypothesized endpoint as
settled:

## What works now: well documents via sonris-doc-search

The document-search `idx`/`val` form (see `bayou:sonris-doc-search` and
`skills/sonris-doc-search/references/sonris-vocabulary.md`) accepts a well serial number
as a search field:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_get.js \
  --url "https://sonlite.dnr.state.la.us/ords/r/sonris/ucmsearch/finddocuments?idx=xWellSerialNumber&val=976229" \
  --throttle 2500
```

This surfaces **documents about the well** (applications, permits, orders, inspections) —
often exactly what a permit report needs — but not structured well metadata (status,
spud/completion dates, total depth, operator history, LUW code) as discrete fields. Same
approach works for a well name (`idx=xWellName`, hypothesized field name — verify) or
field code/name (`idx=xFieldCode`/`xFieldName`, hypothesized).

For **Class VI / CCS wells specifically**, cross-check `bayou:la-class-vi`'s source
(the DCE tracking page) first — it already lists serial number, operator, parish, and
status in one table, no session needed. Serial `976229` (Lapis's "Simoneaux Strat Well",
St. Charles Parish, status Issued) is confirmed against that page as of 2026-08-15.

## Parish-level location search: works, coarse

`idx=xParishCode&val=<code>` (see the vocabulary reference for confirmed/unconfirmed
parish codes — only `45` = St. Charles is confirmed so far) returns documents tagged to
that parish, which surfaces well/operator names active there — coarser than a true
GIS proximity search, but usable today.

## What still needs a live discovery pass: full well metadata, S-T-R, lat/lon

SONRIS almost certainly has a dedicated well-data/"Wellbore" report and a GIS well map
separate from the UCM document search used above — neither has been confirmed live in
this build. **Don't guess a URL for these.** The fastest legitimate way to find them:

1. Find SONRIS's own user guide — it's normally a CAPTCHA-free static PDF (prior guides
   were seen under `denr.louisiana.gov/assets/IT/SONRIS/`, but the agency has since moved
   to `dce.louisiana.gov` — search rather than assume the old path still resolves):
   ```
   WebSearch: SONRIS well search user guide site:dce.louisiana.gov OR site:denr.louisiana.gov filetype:pdf
   ```
   These guides typically document the exact page name/URL and field list for the well
   and section-township-range searches, straight from the source — far more reliable than
   inferring it from the document-search app's naming pattern.
2. If the guide doesn't resolve it, use a **live session** (`bayou:sonris-session`) to
   open SONRIS's main navigation (`https://sonlite.dnr.state.la.us/ords/r/sonris/` or
   similar app root) and look for a "Wells"/"Wellbore"/"Injection & Mining" section —
   note the real page URL and, once confirmed, write it into this file and the vocabulary
   reference with today's date so this stops being exploratory.
3. For lat/lon proximity once well coordinates are obtainable (from whichever source #1/#2
   surfaces): delegate the actual distance math to `bayou:geo-distance` rather than
   reimplementing haversine here.

## Cross-links

- `bayou:facility-coordinates` and `bayou:epa-echo-search` cover the non-SONRIS,
  EPA-registered side of a facility — useful alongside a well lookup when the site is also
  an LDEQ-permitted facility (e.g. a petrochemical plant with an on-site Class I well).
- `bayou:geo-distance` for any point-to-point distance once coordinates are in hand.

## Presenting results

- **Identity search**: well name, serial number, operator (code + name), field, parish,
  status if known, and the list of documents found (dDocname/title/doctype/date).
- **Location search**: table of wells with serial, operator, status, and how each was
  found (parish-tag search vs. a confirmed GIS query once that exists).
- Be explicit in the output about which parts of the answer came from a confirmed source
  (DCE table, document search) vs. which would need the not-yet-built full well-data
  query — don't present a partial document-search result as if it were a complete well
  record.

### Citation format

> **SONRIS Well Serial 976229** ("Simoneaux Strat Well", Lapis Energy (LA Development) LP,
> St. Charles Parish), source: [DCE Class VI tracking page](https://www.dce.louisiana.gov/page/class-vi-permits-and-applications)
> (retrieved 2026-08-15) [and/or SONRIS document search, retrieved <date>].

$ARGUMENTS
