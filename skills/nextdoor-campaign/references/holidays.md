# Holiday reference for campaign pacing

Used by `bayou:nextdoor-campaign` Step 5. The goal: never schedule a post on or
immediately beside a major holiday without either shifting the date or having the post
acknowledge it. Nobody wants to read about an ammonia plant on Christmas Eve.

## Fixed-date holidays (safe to check directly — same calendar date every year)

- January 1 — New Year's Day
- July 4 — Independence Day
- December 24 — Christmas Eve (not federal, but a real dead zone for engagement)
- December 25 — Christmas Day
- December 31 — New Year's Eve

## Movable holidays — DO NOT compute or recall these from memory

These shift every year. Confirm the actual date for the campaign's specific year using
Bash `date` arithmetic (if the anchor date is known, e.g. Thanksgiving is always the
4th Thursday of November) or a `WebSearch` for the exact date — never assert a movable
holiday's date from training-data recall, the same discipline as day-of-week
computation.

- **Mardi Gras / Fat Tuesday** — 47 days before Easter. Especially relevant for a
  Louisiana audience even though it isn't a federal holiday — the days immediately
  around it (the Carnival season, roughly the two weeks prior) also see depressed local
  social media engagement, not just the day itself.
- **Easter Sunday**
- **Thanksgiving** — 4th Thursday of November (computable directly: find the first
  Thursday of November via `date`, add 3 weeks).
- **Memorial Day** — last Monday of May.
- **Labor Day** — 1st Monday of September.

## Applying this in Step 5

1. For each candidate post date, first check it against the fixed-date list above —
   no external lookup needed.
2. Then check whether it falls within a movable-holiday's confirmed window for that
   specific year (confirmed via `date` arithmetic or WebSearch, not recall).
3. If it lands on or immediately adjacent to a holiday from either list:
   - Shift the post to an adjacent day, if the posting window has slack.
   - If the window is too tight to shift (e.g. right before the deadline), keep the
     date but have the post's opening line briefly acknowledge the holiday rather than
     ignoring it — e.g. "Over the holiday weekend, while most of us were with family,
     the comment period on [X] kept ticking."
4. Report any date that got shifted or flagged, in the calendar summary presented to
   the user.
