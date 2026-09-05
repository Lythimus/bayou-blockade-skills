---
name: aircraft-registry-lookup
description: Resolve a company/owner name to candidate aircraft (tail number, ICAO24 hex, type, registered owner) via the FAA releasable aircraft registry and public registration databases; also handles foreign registries and owner-versus-operator gaps.
allowed-tools: Bash, WebFetch, AskUserQuestion
---

# Aircraft Registry Lookup

Resolve a company, fund, or individual name to candidate **US-registered aircraft**
(N-number, ICAO24/Mode-S hex, aircraft type) via the FAA's public **Releasable
Aircraft Registry**, with fallbacks for foreign-registered aircraft (common for
non-US owners, funds, and charter operators).

Use this to answer "what jet does [company] use/own" and to hand off an ICAO24
hex to `bayou:adsb-flight-search` for flight history.

## When to use vs. other skills

- **This skill** — owner-name → aircraft identity (tail/ICAO24/type). Static
  registry data, not flight tracking.
- **bayou:adsb-flight-search** — once you have an ICAO24 (or want to discover
  aircraft by *where they flew*, e.g. "what bizjets landed at KMSY last week"),
  use that skill for actual flight history.

## Step 1: FAA releasable registry (primary, US-registered aircraft)

The FAA publishes a monthly ZIP of the full releasable registry. Download it
**once** into this skill's local cache and reuse it across runs (re-download if
the cache is missing or looks stale — check the `Last-Modified`/file dates).

```bash
CACHE_DIR="$HOME/.claude/plugins/bayou/skills/aircraft-registry-lookup/cache"
mkdir -p "$CACHE_DIR"
if [ ! -f "$CACHE_DIR/MASTER.txt" ] || [ ! -f "$CACHE_DIR/ACFTREF.txt" ]; then
  curl -s -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
    -o /tmp/faa_registry.zip "https://registry.faa.gov/database/ReleasableAircraft.zip"
  unzip -o -j /tmp/faa_registry.zip MASTER.txt ACFTREF.txt -d "$CACHE_DIR"
  rm -f /tmp/faa_registry.zip
fi
```

> **Important:** the FAA registry server (Akamai) returns `403`/`503` to
> requests without a browser-like `User-Agent` header — always send one, as
> above. Retry once or twice on `503` (transient).

### Confirmed schema (verified against the live file — do not re-derive)

`MASTER.txt` columns (comma-separated, header row present, trailing empty
column, fixed-width padded values — strip whitespace):

```
N-NUMBER, SERIAL NUMBER, MFR MDL CODE, ENG MFR MDL, YEAR MFR, TYPE REGISTRANT,
NAME, STREET, STREET2, CITY, STATE, ZIP CODE, REGION, COUNTY, COUNTRY,
LAST ACTION DATE, CERT ISSUE DATE, CERTIFICATION, TYPE AIRCRAFT, TYPE ENGINE,
STATUS CODE, MODE S CODE, FRACT OWNER, AIR WORTH DATE, OTHER NAMES(1..5),
EXPIRATION DATE, UNIQUE ID, KIT MFR, KIT MODEL, MODE S CODE HEX
```

Key fields: `NAME` (registered owner — search this), `MODE S CODE HEX` (ICAO24,
already in the correct lowercase-hex-equivalent format used by ADS-B — FAA
stores it uppercase, lowercase it for OpenSky/ADSB-X queries), `MFR MDL CODE`
(join key into `ACFTREF.txt`), `TYPE AIRCRAFT` (1 Glider, 2 Balloon, 3 Blimp,
4 Fixed-wing single-engine, 5 Fixed-wing multi-engine, 6 Rotorcraft, 7
Weight-shift-control, 8 Powered parachute, 9 Gyroplane), `STATUS CODE` (`V` =
valid/active — filter to this for current ownership).

`ACFTREF.txt` columns:

```
CODE, MFR, MODEL, TYPE-ACFT, TYPE-ENG, AC-CAT, BUILD-CERT-IND, NO-ENG,
NO-SEATS, AC-WEIGHT, SPEED, TC-DATA-SHEET, TC-DATA-HOLDER
```

`TYPE-ENG`: 0 None, 1 Reciprocating, 2 Turbo-prop, 3 Turbo-shaft, **4
Turbo-jet, 5 Turbo-fan** (4/5 = the engine types virtually all business jets
use), 6 Ramjet, 9 Unknown, 10 Electric.

### Query — search by owner name

```bash
CACHE_DIR="$HOME/.claude/plugins/bayou/skills/aircraft-registry-lookup/cache"
python3 -c '
import csv

query = "COPENHAGEN INFRASTRUCTURE"  # substring, case-insensitive — edit per search

# Load aircraft type reference (CODE -> MFR, MODEL, TYPE-ENG)
# NB: FAA files have a UTF-8 BOM on the header row — utf-8-sig strips it,
# otherwise row["CODE"]/row["N-NUMBER"] raise KeyError on the first column.
acftref = {}
with open("'"$CACHE_DIR"'/ACFTREF.txt", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        code = row["CODE"].strip()
        acftref[code] = {
            "mfr": row["MFR"].strip(),
            "model": row["MODEL"].strip(),
            "type_eng": row["TYPE-ENG"].strip(),
        }

with open("'"$CACHE_DIR"'/MASTER.txt", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        name = row["NAME"].strip()
        if query.upper() not in name.upper():
            continue
        code = row["MFR MDL CODE"].strip()
        ref = acftref.get(code, {})
        icao24 = row["MODE S CODE HEX"].strip().lower()
        tail = row["N-NUMBER"].strip()
        mfr = ref.get("mfr", "?")
        model = ref.get("model", "?")
        eng = ref.get("type_eng", "?")
        status = row["STATUS CODE"].strip()
        print(f"N{tail:7} | icao24={icao24:8} | {mfr:20} {model:15} | eng-type={eng} | status={status} | owner={name}")
'
```

Run this once per candidate owner-name variant (the exact company name, likely
parent/subsidiary/DBA names, and any US management/holding entity you suspect
holds title — e.g. `"ST CHARLES CLEAN FUELS"`, `"SUSTAINABLE FUELS GROUP"`,
plausible LLC names). Corporate aircraft are almost always titled to an LLC
with a name that does *not* obviously match the operating company, so a
no-hit here is common and expected, not a failure.

## Step 2: Foreign / no-hit fallback

If the FAA registry has no plausible hit (common for non-US owners — e.g. a
Danish fund like Copenhagen Infrastructure Partners would title a foreign fleet
aircraft, if any, on the Danish `OY-` register, not FAA):

- `WebFetch` general aviation registries/spotting databases for the owner name
  and plausible tail-number prefixes: planespotters.net, jetphotos.com,
  airframes.org, ch-aviation.com.
- `WebFetch`/web search for executive travel photos, local news, or FBO/permit
  hearing coverage mentioning a tail number or aircraft type tied to the
  company's executives or board.
- If a foreign registration prefix is found (e.g. `OY-` for Denmark, `G-` for
  UK), note it; ICAO24 hex allocation blocks are country-specific and can be
  looked up if a specific registration is found, but a full foreign-registry
  bulk search is not available the way the FAA ZIP is — expect single-aircraft
  lookups only.
- It is entirely plausible the answer is "this entity charters aircraft and
  does not own one" — say so explicitly rather than forcing a weak match.

## Step 3: Attribution caveat (always include)

Corporate/business aircraft are usually titled to a single-purpose LLC, trust,
or aircraft-management company (e.g. NetJets, Flexjet, Solairus), not the
operating company by name. A registry hit under a plausible-sounding LLC is
**circumstantial**, not proof of use by a specific executive or company. Always
report:

- Whether the match is a **direct name hit** (company name itself) vs. an
  **inferred LLC** (name similarity, same registered address/city as company
  HQ, etc.) vs. **no hit**.
- That owner (title holder) ≠ operator (who actually flies/charters it) —
  fractional/managed aircraft especially.

## Present results

Table: `Reg/Tail | ICAO24 hex | Type (MFR MODEL) | Registered owner (NAME) |
Likely operator | Confidence | Source`. Confidence tiers: **High** (exact
company/subsidiary name on title), **Medium** (LLC with strong circumstantial
link — shared address, name pattern, news corroboration), **Low**
(speculative — same city/region only). Hand any ICAO24 hex(es) to
`bayou:adsb-flight-search` Mode A for flight history.

## Notes & limits

- FAA data is **releasable registry only** — owners can request their info be
  withheld from the releasable file (this is why some corporate/celebrity
  aircraft show no useful NAME); a no-hit does not mean no aircraft exists.
- The ZIP is refreshed monthly by the FAA; the local cache does not
  auto-expire — delete `cache/MASTER.txt` and `cache/ACFTREF.txt` to force a
  refresh if the data might be stale for a time-sensitive query.
- `STATUS CODE` matters: filter to `V` (valid) for current ownership; other
  codes include deregistered/expired aircraft that are no longer meaningful
  for "does this company currently use this jet."

$ARGUMENTS
