---
name: adsb-flight-search
description: Find historical flights of a known aircraft (ICAO24/tail) or arrivals/departures at an airport (e.g. KMSY) in a time window via OpenSky (free) with ADSB Exchange fallback — supports "did this jet fly into MSY" and geofenced arrival monitoring.
allowed-tools: Bash, Read, WebFetch, AskUserQuestion
---

# ADS-B Flight Search

Find historical flight legs via the **OpenSky Network** REST API (free,
primary), with **ADSB Exchange** (via RapidAPI, paid) as a fallback for
owner-blocked aircraft or gaps in OpenSky coverage.

Two modes:
- **Mode A — known aircraft:** given an ICAO24 hex (from
  `bayou:aircraft-registry-lookup`) or tail number, list its flight legs in a
  window and flag any that touch a target airport (e.g. KMSY).
- **Mode B — airport window (discovery):** given an airport + time window,
  list all arrivals/departures, then resolve each `icao24` to an owner/type via
  `bayou:aircraft-registry-lookup` and filter to business jets. This is the
  "what jets flew into MSY in this window" monitoring mode.

## When to use vs. other skills

- **bayou:aircraft-registry-lookup** — run *before* Mode A (to get an ICAO24
  from a company name) and *during* Mode B (to identify each arrival's owner
  and aircraft type).
- **This skill** — actual flight legs and times, from ADS-B track data.

## Credentials

Read `~/.claude/bayou-credentials.md` for the `## OpenSky Network API` and
`## ADSB Exchange` sections. Do not ask the user for keys inline — if a
section says "not yet configured," tell them how to get one (link is in that
section) and proceed with whichever source is available.

**OpenSky is a client-credentials OAuth2 flow (Basic auth is deprecated).**
Get a bearer token first, then use it for every request in the session (tokens
are short-lived — refetch if you get a 401):

```bash
CREDS=$(cat ~/.claude/bayou-credentials.md)
CLIENT_ID=$(echo "$CREDS" | grep '^OPENSKY_CLIENT_ID:' | cut -d' ' -f2)
CLIENT_SECRET=$(echo "$CREDS" | grep '^OPENSKY_CLIENT_SECRET:' | cut -d' ' -f2)

TOKEN=$(curl -s -X POST "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Rate limit: 4,000 credits/day (shared daily allowance, not a remaining-balance
counter). Check `X-Rate-Limit-Remaining` on responses if you're running many
queries in one session, and stop/ask before burning through it on a huge
backfill.

**Confirmed live — historical queries cost far more than 1 credit each:**
two independent exhaustion events observed `X-Rate-Limit-Remaining` starting
around ~3,970 and hitting `429` after **~130-150** `/flights/aircraft` calls —
implying each historical query costs roughly **~30 credits**, not 1. Budget a
backfill accordingly: treat the practical daily ceiling as **~130 historical
queries**, i.e. **~260 days of 2-day-chunked single-tail history**, not the
nominal "4,000 credits ≈ 4,000 calls" a naive reading of the credits doc
suggests. For a 10-12 month backfill of 2+ tails, expect to need **multiple
separate sessions/days** — plan and communicate that up front rather than
discovering it mid-backfill.

Also confirmed: the retry-after window is **not a fixed daily reset** — it
appeared as ~13.5h in one exhaustion and ~4.5h in another (same account,
different total consumption), consistent with a **rolling window** where
credits "age out" and become available again individually, not all at once at
UTC midnight. Re-check `X-Rate-Limit-Remaining`/retry-after empirically each
time rather than assuming a fixed wait.

**What quota exhaustion looks like:** once the daily
allowance is used up, every request (regardless of endpoint or aircraft)
returns `HTTP 429` with a plain-text body `Too many requests`, and an
`x-rate-limit-retry-after-seconds` header giving the wait time — observed at
~48,670s (~13.5h) in a real exhaustion, i.e. it does **not** reset at a fixed
UTC-midnight boundary, it's a rolling window from first use. **This is not a
transient per-request throttle** — retrying immediately or backing off a few
seconds will not help; every subsequent call fails identically until the
window clears. When a chunked backfill loop hits a 429:

- Stop the loop immediately (don't burn remaining chunks on guaranteed-429 calls).
- Surface the `x-rate-limit-retry-after-seconds` value to the user as a wall-clock
  wait time, and report exactly how much of the range was actually covered
  before the cutoff (don't silently present a partial result as complete).
- Do not loop/retry/sleep-and-poll for 13+ hours in one session — tell the
  user when it'll be available and let them (or a separately scheduled task)
  resume later.

## Timezone handling (always do this first)

Users give times in **local New Orleans time**. Convert to UTC unix
timestamps, and check DST for the specific date — do not assume:

```bash
python3 -c '
import datetime, zoneinfo
tz = zoneinfo.ZoneInfo("America/Chicago")
local = datetime.datetime(2024, 9, 26, 18, 0, 0, tzinfo=tz)  # edit date/time
print(local, "->", int(local.timestamp()), "UTC:", local.astimezone(datetime.timezone.utc))
'
```

(6PM CDT, e.g. late Sep, is UTC-5 -> 23:00Z same day; 6PM CST, e.g. mid-Feb, is
UTC-6 -> 00:00Z the *next* day. Always compute it, don't hardcode the offset.)

## Mode A: known aircraft -> flight history

```bash
BEGIN=<unix ts>   # e.g. 48h before the target cutoff
END=<unix ts>     # target cutoff, converted to UTC
ICAO24=<lowercase hex, e.g. a05c8f>

curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://opensky-network.org/api/flights/aircraft?icao24=${ICAO24}&begin=${BEGIN}&end=${END}" \
| python3 -c '
import sys, json, datetime
for leg in json.load(sys.stdin):
    dep = leg.get("estDepartureAirport") or "?"
    arr = leg.get("estArrivalAirport") or "?"
    fs = datetime.datetime.fromtimestamp(leg["firstSeen"], datetime.timezone.utc)
    ls = datetime.datetime.fromtimestamp(leg["lastSeen"], datetime.timezone.utc)
    flag = " <-- KMSY" if arr == "KMSY" or dep == "KMSY" else ""
    callsign = leg["callsign"].strip()
    print(f"{callsign:10} {dep:6} -> {arr:6} | dep {fs} | arr {ls}{flag}")
'
```

**Important — OpenSky query-window limit is stricter than "48 hours":** `begin`
and `end` must fall within **2 UTC calendar-day partitions**. A naive
`now - 172800` can span parts of 3 UTC dates and the API returns
`HTTP 400: "You can only query across 2 partitions (days)."` **This applies to
`/api/flights/aircraft` just as much as the airport endpoints** — confirmed
live: a 30-day window against `/flights/aircraft` 400s exactly the same way.
Any backfill longer than ~2 days (e.g. a 12-month history for one tail) must
chunk into day-aligned windows. Align `begin` to a UTC day boundary (midnight)
when building a ~2-day window, e.g.:

```bash
BEGIN=$(python3 -c "import datetime; print(int(datetime.datetime.combine((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).date(), datetime.time.min, datetime.timezone.utc).timestamp()))")
```

For a query window wider than 2 days, chunk it into consecutive 2-day (or
smaller, day-aligned) ranges and concatenate results, deduping by
`(icao24, firstSeen)`. Reusable chunking loop for a long backfill against
`/flights/aircraft` (same pattern applies to the airport endpoints — just swap
the URL):

```bash
ICAO24=<lowercase hex>
RANGE_START=<unix ts, day-aligned, e.g. 12 months ago>
RANGE_END=<unix ts, day-aligned, e.g. today midnight UTC>
CHUNK=$((2*86400))

python3 -c '
import subprocess, json

icao24 = "'"$ICAO24"'"
token = "'"$TOKEN"'"
start = '"$RANGE_START"'
end = '"$RANGE_END"'
chunk = '"$CHUNK"'
all_legs = []
seen = set()

t = start
while t < end:
    win_end = min(t + chunk, end)
    url = f"https://opensky-network.org/api/flights/aircraft?icao24={icao24}&begin={t}&end={win_end}"
    out = subprocess.run(["curl", "-s", "-H", f"Authorization: Bearer {token}", url], capture_output=True, text=True).stdout
    try:
        legs = json.loads(out)
    except json.JSONDecodeError:
        legs = []
    if isinstance(legs, list):
        for leg in legs:
            key = (leg["icao24"], leg["firstSeen"])
            if key not in seen:
                seen.add(key)
                all_legs.append(leg)
    t = win_end

print(f"{len(all_legs)} unique legs across the full range")
json.dump(all_legs, open("/tmp/adsb_backfill.json", "w"))
'
```

Each iteration is one OpenSky credit — a 12-month backfill in 2-day chunks is
~183 calls per tail, well within the 4,000/day budget, but check
`X-Rate-Limit-Remaining` if running this for several tails in one session.

## Mode B: airport window -> business-jet arrivals (discovery / monitoring)

```bash
AIRPORT=KMSY
BEGIN=<unix ts, day-aligned>
END=<unix ts>

curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://opensky-network.org/api/flights/arrival?airport=${AIRPORT}&begin=${BEGIN}&end=${END}" \
  > /tmp/adsb_arrivals.json

# same call with /departure instead of /arrival for outbound legs

python3 -c '
import json
rows = json.load(open("/tmp/adsb_arrivals.json"))
seen = set()
for r in rows:
    key = (r["icao24"], r["firstSeen"] // 86400)  # dedupe key: (icao24, day)
    if key in seen:
        continue
    seen.add(key)
    print(r["icao24"], r["callsign"].strip(), r.get("estDepartureAirport"), "->", r.get("estArrivalAirport"), r["lastSeen"])
'
```

Confirmed response fields (verified live): `icao24`, `firstSeen`,
`estDepartureAirport`, `lastSeen`, `estArrivalAirport`, `callsign`,
`estDepartureAirportHorizDistance`, `estDepartureAirportVertDistance`,
`estArrivalAirportHorizDistance`, `estArrivalAirportVertDistance`,
`departureAirportCandidatesCount`, `arrivalAirportCandidatesCount`. The
horiz/vert distance fields are OpenSky's confidence that the ADS-B track
actually terminated at this airport (vs. a nearby one) — treat large
horizontal distances (>5km) as low-confidence arrival attribution and note it.

**Then resolve each `icao24`** through `bayou:aircraft-registry-lookup`
(reverse lookup by `MODE S CODE HEX` instead of by name — same MASTER.txt,
filter on that column) to get owner + type, and keep only business-jet types
(`TYPE-ENG` 4 or 5, i.e. turbo-jet/turbo-fan, and typically `NO-SEATS` < 19).
This turns a raw arrivals list (which includes airliners, cargo, GA piston
traffic) into the relevant subset for "who's flying private jets into MSY."

Arrivals data is **batch-updated** — very recent (same-day, last few hours)
windows may return incomplete results; for "did something land in the last
hour" use live state vectors instead (`/api/states/all`), not this endpoint.

## ADSB Exchange fallback (paid, RapidAPI)

Use only when OpenSky returns nothing for a known-important window (owner may
have opted out of ADS-B position sharing / OpenSky specifically, which ADSB
Exchange's unfiltered feed sometimes still captures), or when the credentials
file shows `RAPIDAPI_KEY` configured. **Confirm cost with the user before
calling** — same billing-confirmation pattern as `bayou:pacer-case-search`.

```bash
RAPIDAPI_KEY=$(grep '^RAPIDAPI_KEY:' ~/.claude/bayou-credentials.md | cut -d' ' -f2)
curl -s --request GET \
  --url "https://adsbexchange-com1.p.rapidapi.com/v2/icao/${ICAO24}/" \
  --header "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  --header "X-RapidAPI-Host: adsbexchange-com1.p.rapidapi.com"
```

(Confirm the exact endpoint path against current RapidAPI docs at call time —
ADSB Exchange's RapidAPI surface changes more often than OpenSky's.)

## Present results

Table: `icao24 | callsign | dep -> arr | arrival time (local America/Chicago +
UTC) | horiz/vert distance confidence | source (OpenSky/ADSBX)`. Always state:

- Not all aircraft transmit ADS-B (owner opt-out, older avionics) — absence of
  a hit is not proof an aircraft didn't fly.
- Low-altitude ADS-B coverage near smaller airports can be patchy depending on
  ground-station density.
- `estArrivalAirport` is inferred from the last received position, not a
  confirmed landing — cross-check horiz/vert distance fields, and treat a
  flight that merely *overflew* near an airport as a weaker signal than one
  with tight distances.

## Notes & limits

- OpenSky historical data query windows: **max 2 UTC-day partitions per
  request** — chunk and concatenate for longer ranges.
- OpenSky arrivals/departures are backfilled with a delay; don't rely on them
  for "right now."
- For a repeat-visitor investigation (e.g. suspected undisclosed lobbying
  across two known dates), run Mode B for each date's window separately, then
  intersect the resulting `icao24` sets — a jet appearing at the target
  airport before *both* dates is a much stronger signal than either alone.

$ARGUMENTS
