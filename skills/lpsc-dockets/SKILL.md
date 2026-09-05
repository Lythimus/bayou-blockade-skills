---
name: lpsc-dockets
description: Search LPSC dockets and orders from the Louisiana Public Service Commission
allowed-tools: WebFetch, Bash, AskUserQuestion
---

# LPSC Docket Search

Search the Louisiana Public Service Commission (LPSC) public portal for dockets, orders, and filings. The LPSC regulates electric utilities (Entergy Louisiana, Cleco, SWEPCO), gas utilities, and telecommunications.

## Portal base URL

```
https://lpscpubvalence.lpsc.louisiana.gov/
```

## Search approach

The LPSC portal uses a Kendo Grid web application. There is no clean REST API for search — use `Bash` with `curl` for direct API calls, or `WebFetch` for full-page lookups.

### Session setup (required for all requests)

First obtain a session cookie:

```bash
COOKIE_JAR=$(mktemp)
curl -s -c "$COOKIE_JAR" "https://lpscpubvalence.lpsc.louisiana.gov/" -o /dev/null 2>/dev/null
```

Then reuse `$COOKIE_JAR` in all subsequent requests with `-b "$COOKIE_JAR"`.

---

## Docket Search

```bash
curl -s -b "$COOKIE_JAR" \
  -X POST "https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/DocketSearch" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://lpscpubvalence.lpsc.louisiana.gov/" \
  --data-urlencode "paramSet[DocketNumber]=DOCKET_NUM" \
  --data-urlencode "paramSet[CompanyName]=COMPANY_NAME" \
  --data-urlencode "paramSet[StartDate]=" \
  --data-urlencode "paramSet[EndDate]=" \
  -d "sort%5B0%5D.Member=DateFiled&sort%5B0%5D.SortDirection=Descending&page=1&pageSize=20&take=20&skip=0" \
  2>/dev/null | python3 -m json.tool
```

Leave unused fields empty. The response is JSON with:
- `Total` — total matching dockets
- `Data[]` — array of docket records with fields: `MatterId`, `MatterNumber` (docket number), `DateFiled`, `Description`

**Note**: If the search endpoint returns an HTML error page, the portal may require session-specific form tokens. In that case, use WebFetch to navigate to the portal and guide the user to perform the search manually, or fall back to the Document Search endpoint below.

---

## Document Search (more reliable)

```bash
curl -s -b "$COOKIE_JAR" \
  -X POST "https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/DocumentSearch" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://lpscpubvalence.lpsc.louisiana.gov/" \
  --data-urlencode "paramSet[FullTextSearch]=SEARCH_TERMS" \
  --data-urlencode "paramSet[DocketNumber]=DOCKET_NUM" \
  --data-urlencode "paramSet[CompanyName]=" \
  -d "sort%5B0%5D.Member=DateFiled&sort%5B0%5D.SortDirection=Descending&page=1&pageSize=20&take=20&skip=0" \
  2>/dev/null | python3 -m json.tool
```

---

## Order Search

```bash
curl -s -b "$COOKIE_JAR" \
  -X POST "https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/OrderSearch" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://lpscpubvalence.lpsc.louisiana.gov/" \
  --data-urlencode "paramSet[FullTextSearch]=SEARCH_TERMS" \
  --data-urlencode "paramSet[DocketNumber]=DOCKET_NUM" \
  -d "sort%5B0%5D.Member=DateFiled&sort%5B0%5D.SortDirection=Descending&page=1&pageSize=20&take=20&skip=0" \
  2>/dev/null | python3 -m json.tool
```

---

## Viewing a document

Documents can be retrieved directly using their secure file ID:

```
https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/ViewFile?fileId=FILE_ID_SECURED
```

The `fileId` appears in document search results as `docIDSecured` or similar. Use WebFetch to retrieve and read the document.

---

## Direct docket detail pages (most reliable path — use this first)

> **⚠️ Verified 2026-06-09.** The POST search endpoints (`DocketSearch`, `DocumentSearch`, `OrderSearch`) currently return a server-side error — **"Value cannot be null. Parameter name: source"** — regardless of session cookie or form fields. Treat them as broken and go straight to the `DocketDetails` page below when you know (or can find) the docket's numeric `docketId`.

If you know a docket's numeric **docketId**, use WebFetch to load the docket detail page:

```
https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/DocketDetails?docketId=DOCKET_ID
```

> **Use `docketId=N`, NOT `id=MATTER_ID`** (the older `?id=` form does not resolve). `DocketDetails?docketId=N` reliably returns **docket-level metadata** — docket number (e.g. U-XXXXX), description/title, date opened, and applicant.
>
> **Limitation:** the Documents grid, Service List, and Orders on this page are rendered **client-side (Kendo Grid via JavaScript)**, so they show "No items to display" to curl/WebFetch. **Filing-level text is NOT retrievable** this way — only docket-level metadata. For the contents of individual filings/orders, the human must use the portal UI in a browser.
>
> **Finding a docketId without the broken search:** docketIds often appear in third-party citations, news, or prior research notes (e.g. an LPSC link of the form `…DocketDetails?docketId=32689`). **Confirmed docketIds:** U-37425 = `32146` (Meta single-customer generation/transmission settlement); U-37853 = `32689` ("construct Waterford 6 + Westlake Power Station, cost recovery," Entergy LA, opened 02/24/2026).

---

## Common LPSC docket number formats

- `U-XXXXX` — general utility dockets (largest category)
- `R-XXXXX` — rulemaking dockets
- `T-XXXXX` — telecommunications dockets
- `C-XXXXX` — complaints

Example LPSC dockets relevant to utility/energy regulation:
- Entergy Louisiana rate cases: search company name "Entergy Louisiana"
- IRP (Integrated Resource Planning) proceedings: search "integrated resource plan"
- Grid modernization filings: search "grid modernization"

---

## Fallback: WebFetch portal navigation

If curl-based search fails, use WebFetch to load the portal and parse the visible results:

```
WebFetch url="https://lpscpubvalence.lpsc.louisiana.gov/" prompt="Find the docket search form and locate dockets related to [TOPIC]. List docket numbers, dates, and descriptions visible on the page."
```

$ARGUMENTS
