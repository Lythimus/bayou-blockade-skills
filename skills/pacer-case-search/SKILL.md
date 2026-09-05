---
name: pacer-case-search
description: Search federal court cases by party name, case title, or case number — tries free CourtListener/RECAP search first, only falls back to paid PACER (with cost confirmation) if the free source comes up short
allowed-tools: Bash, Read, AskUserQuestion
---

# Federal Court Case Search (free-first, PACER fallback)

Search federal civil, criminal, and bankruptcy cases. **Always try the free source first** — CourtListener's RECAP Archive, a nonprofit-run mirror of PACER dockets with full-text and party search, no account or key required. Only escalate to paid PACER (below) if CourtListener doesn't have the case or the docket entries needed.

## Step 1 (always do this first): CourtListener / RECAP free search

No API key required.

```bash
curl -s --get "https://www.courtlistener.com/api/rest/v4/search/" \
  --data-urlencode "type=r" \
  --data-urlencode "party_name=Shell Chemical" \
  --data-urlencode "court=laed" \
  2>/dev/null | python3 -m json.tool
```

Key parameters: `q` (free-text, matches case name/docket text), `party_name`, `case_name`, `court` (e.g. `laed`, `lawd`, `lamd`, `ca5` — same court IDs as PACER), `filed_after`/`filed_before` (`YYYY-MM-DD`), `docket_number`. Omit `type=r` params you don't need; combine any subset.

Each result includes: `caseName`, `docketNumber`, `dateFiled`, `court`, `assignedTo`, `cause`, `suitNature`, `party` (list of all party names), `docket_absolute_url` (a free, human-readable CourtListener docket page — hand this to the user directly), `pacer_case_id` (useful if you do need to fall back to PACER), and `recap_documents` — the actual docket entries, each with `short_description`, `entry_date_filed`, and `is_available` (`true` means the underlying PDF is already in RECAP's free public archive and directly downloadable via CourtListener; `false` means only the docket-entry metadata is free and the PDF itself would require a PACER pull).

**This is genuinely free** — no per-page charges, no PACER account, unlike everything below.

### When to fall back to PACER

Only proceed to Step 2 if:
- CourtListener returns zero results for a case you have other reason to believe exists, or
- The specific document(s) needed have `is_available: false` in RECAP and there's no free alternative, or
- The user needs a real-time PACER Case Locator search across all districts/nature-of-suit codes at once (CourtListener's coverage, while extensive, is not a guaranteed-complete PACER mirror)

State plainly which of these applies before moving to Step 2.

---

# Step 2 (fallback only): PACER Case Locator (PCL) Search

Search the federal court system's PACER Case Locator directly. Requires a valid PACER account. **Only use this after Step 1 has been tried and found insufficient.**

## Billing model — explain this before every action

PACER charges **$0.10 per page** for both searches and document retrieval, with a **$3.00 cap per document**. Fees are **waived entirely if your quarterly total stays under $30**.

Typical costs:
- A PCL case or party search: **$0.10–$0.30** (1–3 pages of results)
- A docket sheet: **$0.10–$1.00** depending on length
- A single PDF document: **$0.10–$3.00** depending on page count
- Light research sessions (under ~300 pages/quarter): **$0 net** (waived)

## MANDATORY pre-action confirmation

Before **every** search or document retrieval, you must:

1. Describe the exact query you're about to run
2. State the estimated cost (use the ranges above)
3. Use `AskUserQuestion` to confirm: "This PACER action will cost approximately [estimate]. Proceed?"
4. Only proceed if the user confirms

If the user says no, stop and offer alternatives (narrow the query, try a different search, etc.).

---

## Authentication

### Get auth token

Read `~/.claude/bayou-credentials.md` to get the PACER username and password. Do not ask the user for credentials unless the file is missing or the login fails.

```bash
curl -s -X POST "https://pacer.login.uscourts.gov/services/cso-auth" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"loginId": "YOUR_USERNAME", "password": "YOUR_PASSWORD", "redactFlag": "1"}' \
  2>/dev/null
```

Extract `nextGenCSO` from the response — this is the auth token. Reuse it for the entire session. Check response headers for a refreshed `X-NEXT-GEN-CSO` token on each response and use the new value if present.

---

## Case Search

Searches by case number, title, filing dates, court, or nature of suit.

```bash
curl -s -X POST "https://pcl.uscourts.gov/pcl-public-api/rest/cases/find?page=0" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-NEXT-GEN-CSO: TOKEN" \
  -d 'BODY' 2>/dev/null
```

### Body examples

By case title (partial match):
```json
{"caseTitle": "Entergy"}
```

By full case number:
```json
{"caseNumberFull": "2:22-cv-01234"}
```

By court and date range:
```json
{"courtId": "laed", "dateFiledFrom": "2020-01-01", "dateFiledTo": "2026-12-31"}
```

By nature of suit:
```json
{"natureOfSuit": "893", "dateFiledFrom": "2018-01-01"}
```

---

## Party Search

Searches by party name. Best for finding all cases involving a company.

```bash
curl -s -X POST "https://pcl.uscourts.gov/pcl-public-api/rest/parties/find?page=0" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-NEXT-GEN-CSO: TOKEN" \
  -d 'BODY' 2>/dev/null
```

### Body examples

By organization name (use `lastName` for companies):
```json
{"lastName": "Entergy"}
```

With date filter:
```json
{"lastName": "Entergy", "courtCase": {"dateFiledFrom": "2015-01-01"}}
```

---

## Key response fields

| Field | Description |
|---|---|
| `courtId` | Court (e.g., `laed`, `lawd`, `ca5`) |
| `caseNumberFull` | Full case number |
| `caseTitle` | Case title |
| `caseType` | `cv` civil, `cr` criminal, `bk` bankruptcy, `ap` appellate |
| `dateFiled` | Date filed |
| `effectiveDateClosed` | Date closed (null = open) |
| `natureOfSuit` | NOS code |
| `caseLink` | Direct ECF docket URL |

Pagination: 54 results per page. Use `?page=N` (0-indexed). `pageInfo.totalPages` shows total.

---

## Presenting results

1. **State which source produced the results** — CourtListener/RECAP (free) or PACER (paid) — don't blend them without labeling.
2. **Results table**: Date Filed | Case Number | Title | Court | Type | Status
3. Flag open cases (**OPEN**) vs closed
4. Link each case — `docket_absolute_url` for CourtListener results, `caseLink` for PACER results
5. For CourtListener results, note which docket entries have `is_available: true` (free PDF) vs `false` (would require a PACER pull)
6. Before retrieving more PACER pages (each page ~$0.10), confirm with user
7. Before pulling any PACER document, confirm with user and state page count / cost estimate

### Louisiana court IDs:
- `laed` — Eastern District (New Orleans)
- `lawd` — Western District (Lafayette)  
- `lamd` — Middle District (Baton Rouge)
- `ca5` — Fifth Circuit (appellate)

### Common nature of suit codes:
- `893` — Environmental matters
- `890` — Other statutory actions
- `791` — ERISA / labor
- `110` — Insurance

### Citation format

> **CourtListener/RECAP**, *Pillette v. ITG Brands, LLC*, No. 2:25-cv-01730 (E.D. La. filed Aug. 22, 2025), source: [CourtListener](https://www.courtlistener.com/docket/71178905/pillette-v-itg-brands-llc/) (retrieved 2026-07-21).
>
> **PACER**, *[Case Name]*, No. [case number] ([court], filed [date]), source: PACER Case Locator (retrieved [date]).

$ARGUMENTS
