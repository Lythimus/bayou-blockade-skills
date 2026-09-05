---
name: la-class-vi
description: Track Louisiana's Class VI carbon-sequestration/CO2-injection permit program — application status, issued permits, and the associated Class V stratigraphic test wells, cross-checked against EPA UIC data and Federal Register notices, no CAPTCHA session required
argument-hint: [operator or project name] [parish]
allowed-tools: Bash, AskUserQuestion
---

# Louisiana Class VI / Carbon Sequestration Tracker

Louisiana took UIC Class VI primacy from EPA in **early 2024**, making the state (not EPA
Region 6) the permitting authority for CO2 injection/carbon-sequestration wells. This
skill tracks that program's status — who's applied, what's been issued, what's pending or
paused — using **CAPTCHA-free sources only**, so it works even with no `bayou:sonris-session`
established. It's the natural first stop for any CCS project (like the High West/Spoonbill
case) before pulling individual documents via `bayou:sonris-doc-search`.

> **Program status carries a real caveat as of the last verified check (2026-08-15):**
> Gov. Landry's **October 15, 2025 executive order paused new Class VI permit review**
> statewide. Only two permits have been issued to date: **Hackberry (Cameron Parish)** and
> **Strategic Biofuels Green Fuels (Caldwell Parish, issued June 2026)**. Re-verify this —
> it's exactly the kind of fast-moving executive/regulatory status that goes stale between
> runs — via `bayou:federal-register-search` and a fresh fetch of the sources below rather
> than repeating this note as if it were still current.

## Step 1 — DCE Class VI / Class V tracking page

```bash
curl -s "https://www.dce.louisiana.gov/page/class-vi-permits-and-applications" \
  -H "User-Agent: bayou-la-class-vi/1.0 (public-records research)" 2>/dev/null
```

Confirmed CAPTCHA-free 2026-08-15 (returns real content, no reCAPTCHA). This page's own
"Page Last Updated" stamp is the authoritative freshness signal — read and report it, and
treat the page as stale rather than current if that date is old relative to the request.
It carries two distinct tables worth pulling separately:
- **Class V stratigraphic test wells** associated with potential Class VI projects — the
  early-stage wells (like Lapis's Simoneaux Strat Well, serial `976229`, St. Charles
  Parish) that usually precede an actual Class VI application. Columns: project name,
  operator, parish, well serial number, status (Issued / Pending / Withdrawn / Permit
  Expired).
- **Class VI applications** themselves, with the current confidentiality/redaction
  caveats the page states directly — read those caveats and pass them through rather than
  presenting the table as more complete than the source claims it is.

The HTML content on this page changes; extract with a plain-text read (WebFetch or a
`python3 -c` HTML strip) rather than assuming a fixed table structure survives across
requests.

## Step 2 — SONRIS's own Class VI applications report

```bash
curl -s "https://sonlite.dnr.state.la.us/ords/r/sonris_pub/ucm_customsearches/class-vi-applications?p10_full_screen=1" \
  -H "User-Agent: bayou-la-class-vi/1.0 (public-records research)" 2>/dev/null
```

**Confirmed CAPTCHA-free 2026-08-15** — an ORDS path on the same domain as the gated
document search, but this specific app (`ucm_customsearches`, not `document_access`)
returns real content without a session cookie. If a future run finds this now redirects
to `SHOW_CAPTCHA_apex`, don't silently fall back — flag it, since the whole point of this
skill is not needing `bayou:sonris-session` for the common case, and that stops being true
if this changes.

This is the direct SONRIS-side view (may include fields/detail the DCE page summarizes
away) — cross-reference the two rather than treating either as sufficient alone.

## Step 3 — cross-check EPA UIC and Federal Register

- `bayou:epa-echo-search` — SDWA/UIC compliance history if the project also shows up in
  EPA's own tracking (less likely post-primacy, but worth checking for the transition
  period record).
- `bayou:federal-register-search` — search `conditions[term]=Class VI Louisiana` or the
  specific operator/project name, agencies `environmental-protection-agency`, to catch any
  federal notices (e.g. residual EPA actions from before primacy transferred, or
  UIC-program-related rulemaking).

## Step 4 — operator/project-specific detail

Once a project of interest is identified from Steps 1-2, resolve its full document set
via `bayou:sonris-operator-lookup` → `bayou:sonris-doc-search` (this does need a session)
for the actual application/order/permit PDFs, not just the tracking-table summary.

## Presenting results

1. **Program status headline**: primacy date, current pause/moratorium status (re-verified,
   not assumed from this file's notes), count of issued permits.
2. **Table**: Project | Operator | Parish | Well Serial (if any) | Status | Source
   (DCE page / SONRIS report) — merge the two sources, flag any disagreement between them
   rather than silently picking one.
3. If the user's project of interest isn't in either table, say so plainly — it may be too
   early-stage to have a public tracking entry yet, which is itself a data point (contrast
   against `bayou:sonris-doc-search`, which may show application documents filed before a
   project reaches this tracker).

### Citation format

> Louisiana Class VI/Class V tracking, source: [DCE Class VI Permits and Applications](https://www.dce.louisiana.gov/page/class-vi-permits-and-applications)
> (page last updated <date from page>, retrieved 2026-08-15) and
> [SONRIS Class VI Applications report](https://sonlite.dnr.state.la.us/ords/r/sonris_pub/ucm_customsearches/class-vi-applications?p10_full_screen=1)
> (retrieved 2026-08-15).

$ARGUMENTS
