---
name: lpsc-dockets
description: Louisiana Public Service Commission dockets. Gets docket metadata, lists every filing with its files, downloads public filings (testimony, briefs, orders) and greps their text, by docketId with no browser. Use for Entergy, Cleco or SWEPCO certification, rate, large-load and IRP dockets.
allowed-tools: WebFetch, Bash, AskUserQuestion
---

# LPSC Docket Search

Search the Louisiana Public Service Commission (LPSC) public portal for dockets, orders, and filings. The LPSC regulates electric utilities (Entergy Louisiana, Cleco, SWEPCO), gas utilities, and telecommunications.

Wholesale power, transmission and interconnection (ER/EL dockets), and interstate gas pipelines and LNG terminals (CP dockets), are FERC's jurisdiction, not the LPSC's. Search those with `bayou:ferc-elibrary`. For whether a plant in a certification docket holds a MISO interconnection queue position or an ERAS fast-track request, and what else is queued at its substation, use the `miso_queue.py` script in `bayou:ferc-elibrary`. The certification application itself usually says which MISO route the plant is taking (regular queue, ERAS, or the replacement-generator process), and that route decides where to look.

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

Each file is served directly, with no session cookie (verified 2026-11-01):

```
https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/ViewFile?fileId=<FileId, URL-encoded>
```

`FileId` comes from the docket's document list (next section). It is base64-like, for example `hsljNiQroZw=`, so URL-encode the `=` and `/`. Download with curl or `lpsc_docket.py download`; WebFetch handles large exhibit PDFs poorly.

---

## Direct docket detail pages (most reliable path — use this first)

> **⚠️ Verified 2026-06-09.** The POST search endpoints (`DocketSearch`, `DocumentSearch`, `OrderSearch`) currently return a server-side error — **"Value cannot be null. Parameter name: source"** — regardless of session cookie or form fields. Treat them as broken and go straight to the `DocketDetails` page below when you know (or can find) the docket's numeric `docketId`.

If you know a docket's numeric **docketId**, use WebFetch to load the docket detail page:

```
https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/DocketDetails?docketId=DOCKET_ID
```

> **Use `docketId=N`, NOT `id=MATTER_ID`** (the older `?id=` form does not resolve). `DocketDetails?docketId=N` reliably returns **docket-level metadata** — docket number (e.g. U-XXXXX), description/title, date opened, and applicant.
>
> **Filings are retrievable without a browser (verified 2026-11-01).** The Documents grid on this page renders client-side, so WebFetch sees "No items to display". The grid's data endpoint, though, answers a plain POST with no cookie:
>
> ```bash
> curl -s -X POST "https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/Docket_Documents" \
>   -H "X-Requested-With: XMLHttpRequest" -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" \
>   --data "docketId=32689&sort=&page=1&pageSize=2000&group=&filter="
> ```
>
> It returns `{"Data":[{DocumentId, DocumentType, DateFiled:"/Date(ms)/", FiledBy, Description, Files:[{FileId, FileName, FileSize}]}], "Total": n}`. The parameter is `docketId`; `id` returns the "Value cannot be null" error page. The script wraps this:
>
> ```bash
> S="/Users/josephcoco/.claude/plugins/bayou/skills/lpsc-dockets/lpsc_docket.py"
> python3 -I "$S" info 32689                                   # docket number, dates, synopsis, parties
> python3 -I "$S" docs 32689 --grep "brief|testimony" --public  # filings and their files, sealed files dropped
> python3 -I "$S" download 32689 --out DIR --match "Pre-Hearing Brief" --public
> python3 -I "$S" grep DIR "St\.? Charles|large load|data cent"  # pdftotext once, hits by page
> ```
>
> - **Download guard.** `download` stops above 25 files or 100 MB unless given `--yes`. Testimony with exhibits runs 10–35 MB a file; all of U-37853's public files total 266 MB. Narrow with `--match` first.
> - **What `--public` drops.** It drops files whose names say Confidential, Under Seal, Highly Sensitive or HSPM. Sealed testimony often has a "Public Version" filed separately, sometimes weeks later.
> - **What `grep` can't search.** It flags scanned PDFs with no text layer, which need `bayou:document-ocr` before a miss means anything.
> - **Briefs map the docket.** Intervenor and Staff pre-hearing briefs are the quickest way to see the issues, and they cite related dockets by number (U-37853's briefs cite U-37425 and U-37882).
>
> The Service List grid uses `Docket_ServiceList` the same way (untested).
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
