---
name: ldeq-permit-status
description: Check the current status and permit history of an LDEQ-regulated facility by AI number or company name — permit type, activity number, issued/effective/expiration dates
allowed-tools: Bash, AskUserQuestion
---

# LDEQ Permit Status Check

Wraps LDEQ's "Check Permit Status" online service (`internet.deq.louisiana.gov/portal/ONLINESERVICES/CHECK-PERMIT-STATUS`) — a legacy DNN/OWS filter grid, not a REST API. It has **no CAPTCHA** (unlike `bayou:ldeq-edms-download`), so this runs fully headless and non-interactively via Playwright.

This gives the permit-type/status/date summary across a facility's whole history in one call — cross-reference the `Activity #` column into `bayou:ldeq-edms-search` (search by AI number) to pull the actual documents for a specific permit action.

## Prerequisites

One-time setup, from this skill's directory:

```bash
cd ~/.claude/plugins/bayou/skills/ldeq-permit-status
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

Reuses whatever Chromium build Playwright already has cached (`~/Library/Caches/ms-playwright/`). If `node -e "require.resolve('playwright')"` run from this directory succeeds, setup is done.

## Parsing arguments

The user may provide:
- An **AI number** (LDEQ's facility ID, e.g. `26336` for Shell Norco East Site) — exact match, preferred when known
- A **company/facility name or partial name** — this is a **literal substring match** against the "AI Name" field, not fuzzy: `"Shell Norco"` will match nothing (the field reads "Shell Chemical LP - Norco Chemical Plant"), but `"Norco"` or `"Shell"` alone will. Prefer a single distinctive word over a multi-word guess.

If the user gives a full facility name and it's uncertain whether it'll match literally, try the single most distinctive word first (e.g. "Norco" not "Shell Norco Chemical Plant").

## Running the check

```bash
node ~/.claude/plugins/bayou/skills/ldeq-permit-status/permit_status.js --ai 26336
```

or

```bash
node ~/.claude/plugins/bayou/skills/ldeq-permit-status/permit_status.js --coname Norco
```

Only one of `--ai` / `--coname` is required; both can be passed together to AND-filter. Output is JSON: `{count, header, records: [...]}`, one record per permit action — `AI`, `AI Name`, `Media` (Air/Water/Solid Waste/Haz Waste/Biosolids), `Parish`, `Permit Type - No.`, `Activity #`, `Received Date`, `Status - Date` (status + the date it took that status, e.g. "Issued - 05/06/1977"), `Writer` (LDEQ staff assigned), `Effective Date`, `Expiration Date`, `Eff Flag` (`Y`/`N` — whether this permit action is currently in effect).

If `count` is 0, the AI number doesn't exist or the name substring matched nothing — double check against `bayou:ldeq-edms-search` (which resolves AI numbers from a facility name search) before concluding the facility has no LDEQ permit history.

---

## Presenting the results

1. **Facility identification**: AI number, full AI Name as LDEQ has it on file, parish.
2. **Permit history table**: sorted by Received/Effective Date, most recent first — Permit Type | Activity # | Status - Date | Effective | Expiration | Currently Effective?
3. Flag any permit with `Eff Flag = Y` and a near-term or past `Expiration Date` — an expired-but-still-flagged-effective permit, or one expiring soon, is often directly relevant to an enforcement argument.
4. Cross-link: "For the underlying permit documents on Activity # [N], see `bayou:ldeq-edms-search` (search by AI [number])."
5. Cross-link `bayou:epa-frs-crosswalk` — its `LA-TEMPO` program ID is LDEQ's federal↔state bridge, useful for finding this AI number starting from a federal program ID (TRI, NPDES, RCRAInfo, GHGRP) instead of a company name.

### Citation format

> **LDEQ AI 26336** (Shell Chemical LP - Norco Chemical Plant – East Site), source: [LDEQ Check Permit Status](https://internet.deq.louisiana.gov/portal/ONLINESERVICES/CHECK-PERMIT-STATUS) (retrieved 2026-07-21): Activity PER19770001, PSD Permit Initial - PSD-LA-8, issued 05/06/1977, effective 5/6/1977–9/30/2006.

$ARGUMENTS
