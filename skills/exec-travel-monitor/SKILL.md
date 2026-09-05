---
name: exec-travel-monitor
description: Monitor a watchlist of company/executive aircraft for arrivals at political and regulatory centers (e.g. state capitals) and surface trips that no public event explains — undisclosed lobbying/business travel — via public FAA + ADS-B data, on demand or on a recurring schedule.
allowed-tools: Bash, Read, Write, WebFetch, WebSearch, AskUserQuestion
---

# Executive Travel Monitor

Track a **watchlist** of companies and their known aircraft for arrivals at
**political/regulatory centers** (state capitals, DC) or a project region, and
classify each visit as **EXPLAINED** (a public hearing, meeting, or filing
accounts for it) or **UNEXPLAINED — quiet** (no public event found). Flights
are the *primary* signal; the public-event calendar is a *subtraction filter*
applied on top of them. This is generic to any company — not tied to one
investigation — and is designed to run both **on demand** and as a
**recurring background monitor** that only notifies on new unexplained hits.

The premise: a scheduled public hearing already tells you executives are
coming — that's not interesting. What's interesting is the jet landing near
the capitol with **no** public event on the calendar — that's the trip nobody
announced.

## When to use vs. other skills

- **bayou:aircraft-registry-lookup** — resolve a company/owner name to a tail
  number and ICAO24 hex when adding a new company to the watchlist.
- **bayou:adsb-flight-search** — this skill's engine for actual flight legs
  (Mode A: known aircraft history; Mode B: airport-window discovery). Read
  that skill's SKILL.md for the OpenSky auth/timezone/chunking details instead
  of duplicating them here.
- **This skill** — the watchlist, the destination-weighting, the
  EXPLAINED/UNEXPLAINED classification, and the recurring cron wrapper around
  those two skills.

## Step 1: Load / extend the watchlist

The watchlist is per-investigation data — real company names, tail numbers, and
your own research notes — so it lives **outside this repo**, the same way
`bayou-credentials.md` and `bayou-profile.md` do:

- **Public template (committed to the plugin):** `watchlist.example.json` in
  this skill's directory — schema only, safe to share.
- **Private real data (never committed):** `~/.claude/bayou-exec-travel-watchlist.json`.

```bash
WATCHLIST="$HOME/.claude/bayou-exec-travel-watchlist.json"
cat "$WATCHLIST"
```

**If it doesn't exist, stop** and tell the user: copy `watchlist.example.json`
to `~/.claude/bayou-exec-travel-watchlist.json` and fill it in, then re-run.

Schema:

```json
{
  "companies": [
    {
      "name": "Company or fund name",
      "parents": ["Parent entity 1", "Parent entity 2"],
      "aircraft": [
        {"tail": "N12345", "icao24": "a1b2c3", "type": "Make/Model",
         "owner": "Registered LLC/owner name", "confidence": "high|medium-repeat-visitor|low-single-hop"}
      ]
    }
  ],
  "watched_airports": [
    {"icao": "KBTR", "label": "why this airport matters", "weight": 1-3}
  ],
  "home_bases_ignore": ["KXYZ"]
}
```

**To add a new company:** hand its name (and plausible parent/subsidiary
names) to `bayou:aircraft-registry-lookup`. If it has no titled jet, note that
— the company may charter, or a repeat-visitor pattern may need to be
discovered via Step 2's Mode B instead (e.g. two jets titled to an
unrelated-sounding finance/leasing LLC turn out, on repeat-visitor analysis, to
belong to the same corporate parent — not every aircraft is titled in the
company's own name).

`weight` on a watched airport should reflect political/regulatory sensitivity:
**3** = state capital or DC (direct access to officials), **2** = project
region/main airport, **1** = secondary project-area airport. Add
`home_bases_ignore` entries for airports where the aircraft is simply based —
routine returns-to-base legs there are not meaningful arrivals.

## Step 2: Backfill / scan — flights are the primary signal

For each aircraft on the watchlist, run **`bayou:adsb-flight-search` Mode A**
over the requested date range. **The OpenSky aircraft endpoint enforces the
same 2-UTC-day-partition limit as the airport endpoints** — for any range
longer than ~2 days you must loop in day-aligned chunks (see that skill's
Notes section for the chunking snippet) and concatenate/dedupe results by
`(icao24, firstSeen)`.

Keep every leg whose `estArrivalAirport` or `estDepartureAirport` matches a
`watched_airports` entry (skip legs touching only a `home_bases_ignore`
airport on both ends).

**Cache raw legs durably, not just in `/tmp`/scratchpad.** A multi-day gap
between runs can lose scratchpad contents entirely (confirmed: a backfill's
raw JSON vanished between sessions and had to be re-fetched, burning quota
twice). Save each tail's raw leg JSON to
`~/.claude/plugins/bayou/skills/exec-travel-monitor/data/backfill_<tail>.json`
so a re-run can diff/extend instead of re-querying a range already paid for
in OpenSky credits.

**Also run Mode B** (airport-window discovery) on the watched airports for the
same range: pull all business-jet arrivals, resolve owners via
`bayou:aircraft-registry-lookup`, and flag any **tail appearing 2+ times**
that is *not yet* on the watchlist as a candidate addition — this is how new
repeat-visitor patterns get found before a company is explicitly named.

## Step 3: Subtraction filter — classify each watched-airport visit

For every kept arrival (date + watched airport), do a lightweight
**WebSearch** for a public event that would explain it: the company/parent
name + the airport's region + "hearing OR meeting OR public notice OR filing"
within **±3 days** of the arrival date. Follow up with `WebFetch` on the most
relevant result to confirm a real date match (don't classify off a snippet
alone).

- **EXPLAINED** — a public hearing/meeting/filing/notice exists within ±3 days
  that plausibly accounts for the trip. Cite the source.
- **UNEXPLAINED — quiet** — no public event found. This is the flag of
  interest. Rank these by `watched_airport.weight` (capital/DC first), then by
  how often that tail has made quiet trips to that airport.

A single WebSearch miss is not proof of secrecy — say so (see Notes & limits)
— but a *pattern* of repeated quiet arrivals at a capital is a meaningful
signal worth surfacing even with that caveat.

## Step 4: Recurring monitor (on-demand + cron)

This skill supports both invocation modes:

- **On demand:** run Steps 1–3 over whatever range the user asks for (e.g. "12
  months," "since the last hearing").
- **Recurring (cron):** set up a weekly `CronCreate` job that runs Steps 2–3
  over the **trailing ~10 days** (wide enough to catch OpenSky's arrivals-data
  backfill delay, narrow enough to run fast) for every aircraft on the
  watchlist, and fires `PushNotification` when a **new** UNEXPLAINED arrival at
  a `weight >= 3` airport (capital/DC) is found.

  To avoid re-notifying on the same trip every week, persist state in a
  sibling `state.json` (create if missing) keyed by `(icao24, arrival date,
  airport)`, and only notify on keys not previously seen:

  ```bash
  STATE="$HOME/.claude/plugins/bayou/skills/exec-travel-monitor/state.json"
  [ -f "$STATE" ] || echo '{"seen": []}' > "$STATE"
  ```

  After each run, merge newly classified arrivals' keys into `state.seen`
  before writing `state.json` back, so the next run only diffs forward.

  Note the recurring-job caveat: `CronCreate` jobs are session-scoped and
  recurring jobs auto-expire after 7 days — tell the user the monitor will
  need to be re-created weekly (or ask if they want a reminder to do so)
  rather than assuming it survives indefinitely unattended.

## Present results

A **trip timeline table**, most-significant first (UNEXPLAINED + highest
weight at the top):

`Date (local) | Tail | Dep -> Arr (airport label) | EXPLAINED / UNEXPLAINED | Weight | Notes/source`

Always state the attribution limits below alongside the table, not just once
at skill-install time.

## Notes & limits

- A jet arrival is **not proof** a specific executive was aboard, or that they
  met a specific official — owner (title holder) ≠ operator ≠ passenger.
- Not all aircraft transmit ADS-B (owner opt-out, older avionics); a missing
  leg is not proof a flight didn't happen.
- "No public event found" means *not found in public sources during this
  search*, not *confirmed secret* — WebSearch/calendar coverage is incomplete,
  especially for informal meetings that were never public to begin with.
- This is the same evidentiary basis as standard corporate-jet accountability
  journalism (FAA registry + ADS-B cross-referenced against public schedules)
  — useful for raising questions and directing FOIA/records requests, not for
  standalone claims of wrongdoing.
- Do not build a scraper against the LDEQ calendar or similar brittle
  JS-rendered calendar apps for the subtraction filter — WebSearch + WebFetch
  of individual notice/detail pages is the reliable path (confirmed working;
  the calendar's internal `.snip` route throws a template error on direct
  GET).

$ARGUMENTS
