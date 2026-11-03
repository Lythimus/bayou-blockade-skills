---
name: eclerks-land-index
description: Search Louisiana parish Clerk of Court indexes (land conveyances and mortgages, civil suits) through eClerks LA's statewide portal — every act naming a company, LLC or person, filtered by parish, date range and document type, as structured rows. Use to find options, sales, servitudes, utility rights of way, option terminations and resubdivisions on a site's lots, the hidden counterparty on an amendment or assignment, or a utility's right-of-way campaign in a parish. Runs inside the user's signed-in browser tab; reading the acts themselves needs a paid per-parish subscription.
argument-hint: <party name> [--parish "St. Charles"] [--from YYYY-MM-DD --to YYYY-MM-DD] [land|civil]
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# eClerks LA land index

eClerks LA (`https://www.eclerksla.com`) is run by the Louisiana Clerks' Remote Access Authority, and most parish Clerks of Court publish their indexes through it. The statewide index is free but needs an account login. Document images need a paid per-parish subscription.

Use this skill to answer "who has recorded what with whom, and when" in a parish. It covers:
- options, rights of first refusal and their terminations;
- sales and in-kind transfers between family LLCs;
- resubdivisions (which create new lot numbers);
- servitudes to pipeline companies;
- rights of way to the utility;
- mortgages, and the bank behind a project.

It gives index rows, not the acts.

## Access rules

- **The user signs in, in their own browser tab.** Never type their password, and never store it outside `~/.claude/bayou-credentials.md` (the template has an `ECLERKS_*` entry). If the tab is signed out, ask the user to sign in.
- **Images cost money.** As of 2026-11-01, St. Charles offers 24 hours for $20, 1 month for $50, 3 months for $150, 6 months for $300, and 1 year for $600. Never buy. Tell the user the item and the price. If they buy access, give them a reading list (instrument numbers) so the window is used fully. Purchasing and payment entry are theirs to do. Per-page downloads cost $1 a page plus a flat $1.50 fee per order (a 22-page act was $23.50; two items totalling 11 pages showed $12.50). Confirm item and total with the user before adding anything to the cart; checkout ("Buy now") is theirs.
- **No script outside the browser.** The endpoint authenticates with the session cookie and an anti-forgery token. Do not copy either out of the page into curl. Call the endpoint from the page with `javascript_tool`.

## The endpoint

The statewide portal's results grid is an ExtJS store that POSTs JSON to `/eclerks/statewideportal?handler=search`. Calling it directly replaces filling the form and scraping the table, and returns up to 500 rows per call with facets.

1. Open `https://www.eclerksla.com/eclerks/statewideportal` in the signed-in tab, using `claude-in-chrome`.
2. Define the helper once per page load:

```js
const tok = document.querySelector('input[name=__RequestVerificationToken]').value;
window._ec = async function (name, from, to, filters, start = 0, limit = 500) {
  const body = {
    searchParty1: true, searchParty2: true, lastName: name, firstName: '',
    fromDate: from, toDate: to, searchType: '0',            // '0' = begins with
    page: Math.floor(start / limit) + 1, start, limit,
    sort: JSON.stringify([{property: 'recordedDate', direction: 'ASC'}, {property: 'registryNumber', direction: 'ASC'}]),
    filter: JSON.stringify(filters),
  };
  const r = await fetch('/eclerks/statewideportal?handler=search', {method: 'POST',
    headers: {'RequestVerificationToken': tok, 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    body: JSON.stringify(body)});
  return r.json();
};
const nm = a => (a || []).map(p => [p.lastName, p.firstName].filter(Boolean).join(', ')).join('; ');
window._fmt = d => [d.recordedDate.slice(0, 10), d.registryNumber, d.docType, nm(d.party1), nm(d.party2), (d.description || '').slice(0, 160)].join(' | ');
'ok'
```

3. Query, keep the rows in a page variable, and return only formatted strings:

```js
const j = await window._ec('EXAMPLE LAND', '2024-01-01', '2026-11-01',
  [{property: 'Facet_DocumentSet', value: ['1']}, {property: 'Facet_ParticipantId', value: ['45']}]);
window._r = j.documents;
j.totalRows + '\n' + j.documents.slice(0, 8).map(window._fmt).join('\n')
```

Then read `window._r` in slices of about 8 rows. Tool output is cut at roughly 1,000 characters.

**Filters** (each `value` is an array of strings):

| Facet | Values |
|---|---|
| `Facet_DocumentSet` | `1` land (conveyance and mortgage), `2` marriage, `3` civil (docket numbers); checked 2026-11-01 |
| `Facet_ParticipantId` | parish id. St. Charles `45`, St. James `47`, St. John the Baptist `48`. List them all with `Ext.data.StoreManager.get('ParticipantStore').getRange().map(r => r.get('participantName') + '=' + r.get('id'))`. The same store gives each parish's index start and end dates (`conveyanceMin/Max`, `mortgageMin/Max`). |
| `Facet_DocType` | e.g. `RIGHT OF WAY`, `SERVITUDE`, `SALE`, `OPTION`, `TERMINATION`, `RESUBDIVISION` |
| `Facet_RecordType`, `Facet_Cancellation` | record type code; cancelled yes or no |

**Response.** The fields are `totalRows`, `documents[]` and `metaData.facetBuckets[]`. Each bucket is `{name, facets: [{key, docCount}]}`, so a `limit: 1` call profiles a party by parish and document type cheaply.

Each document has these fields:
- `recordedDate`
- `registryNumber`: the instrument number to cite and to read
- `docType`
- `documentSet`
- `recordType`
- `participantId`: the parish
- `description`: subdivision, lot and section/township/range text
- `cancellation`
- `party1[]` and `party2[]`: each `{lastName, firstName, ...}`
- `docketNumber`: civil only
- `documentLink` and `imageLink`

## Gotchas

- **Never return whole documents.** `documentLink`/`imageLink` carry query strings, and the tool blocks the whole result (`[BLOCKED: Cookie/query string data]`). Return formatted fields only.
- **Name match is "begins with"**, on either party. `ENTERGY LOUISIANA` catches `ENTERGY LOUISIANA, LLC` and `ENTERGY LOUISIANA INC`. Run spelling variants (`L L C`, `LLC`, `INVESTMETNS`): the index carries clerk typos.
- **Party order is not grantor/grantee.** The index often lists both parties on both sides of an act of the parish's Department of Planning & Zoning, such as a resubdivision. Read `docType` and the description.
- **Each parish's index has its own start and end dates.** St. Charles conveyances ran through 2026-10-28 when checked on 11/1. A gap after the end date is indexing lag, not absence.
- **Pattern-of-filings questions** (a right-of-way campaign, a buyout): count by quarter, and by township and range parsed from `description` (`/TWN: (\d+) SOUTH RANGE: (\d+)/`). Plot the sections with the BLM PLSS layer before claiming the filings reach a given site. A parish-wide spike can belong to a different project.

## Output

Write the rows to a dated markdown table in the campaign folder (date | instrument | type | party 1 | party 2 | description). Say "index row" for anything not read from the act.

Any act worth reading goes on a numbered list with its instrument number. The user can view it with a subscription, at the courthouse, or through a records request to the Clerk using `bayou:la-public-records-request`.

Feed new parties into `bayou:la-power-map`'s `ENTITIES.md`. Feed lot numbers into `bayou:parish-assessor-gis` to get a parcel and map.

## Fallback

If the endpoint changes, the search form still works. Set the fields with `form_input` (coordinate clicks miss because the layout shifts), click Search, and scrape `table tbody tr` into a page variable. Then fix this skill: hook `Ext.Ajax.on('beforerequest', ...)` before clicking Search to capture the new body. Never report "no records" from a broken call.

## Reading act images in the viewer (needs a pass)

Tested 2026-11-01 with a 24-hour St. Charles pass. The pages are scans watermarked UNOFFICIAL with no text layer, so reading is by screenshot (write notes as you go; save only diagrams and plats, not text pages).

1. Search tab (`/Subscriptions/Search/stcharles`): `form_input` the Instrument # field, click Search (re-click by coordinate if results do not change), wait 3 s, `find` the result cell and click it. A detail tab opens with the index fields, related instruments (amendments, partial releases) and the page count.
2. On the detail tab, click "View Image (N Pages)" (top right of the card, about (950,232)). The first click or two are often ignored and the Image viewer tab appears after a delay; click again and check the tab list.
3. In the viewer, click Next (about (571,210)). The first click on a fresh viewer is often ignored, so check the page box. **Scroll up at (1150,500) before every Next click**, or the page scrolls instead of advancing. Read each page with a screenshot, then scroll down 7 at (600,600) and screenshot the lower half. Page 1 is the clerk's recording page (parties, date, book and page). A "Fetching image data" dialog may appear; wait 3–5 s. Jump to a page by triple-clicking the page box, typing the number and pressing Return. The cart icon is in the toolbar.
4. Use `browser_batch` (items are `{"name":"computer","input":{...}}`; wait is capped at 10 s) and scale screenshots to 0.7–0.8. Tool output lists every open tab each call, so close finished detail and viewer tabs.
5. Read the detail page's "References" table first: amendments and releases (for example 457648 and 485626 for the 2006 Declaration 318366) change what the act means.
6. Save diagrams with `save_to_disk: true`, then copy them next to the notes. Note the pages worth buying (page numbers) in each notes file.

## Cart (per-page purchase)

Tested 2026-11-01. In the viewer, click the cart icon (about (860,209); the first click on a fresh viewer is often ignored, so click again until the "Purchase Document; Instrument: N" dialog appears). The dialog has Full Document, Certified Document and **Custom Pages** (for example `4,8-10`); type the pages and click Add to Cart. Each act is a separate cart line at $1 a page. Check the cart at `/subscriptions/purchasingcart/stcharles` (lists instrument, pages, fees, total; "Buy now" is the user's). Download links expire 72 hours after purchase. Because bought pages come back as PDFs, run tesseract or surya on them instead of reading screenshots: it keeps page images out of context, which the viewer cannot do (a screenshot is always returned to the model, and `save_to_disk` saves the same scaled image).
- Opening an act: if the "View Image" click does not open the viewer, use `find` to get the link ref and click by ref, then wait 8–10 s and re-list tabs.
- The Search button needs two clicks after the form changes; coordinates shift after the first result renders.
- **After checkout:** the user downloads the PDFs (named however the site names them; one PDF per cart line, pages in the order bought). They are scans with no text layer. Move them to `<acts folder>/pages-bought/<instrument>-pp<pages>.pdf`, run `pdftoppm -r 300 -png` and `tesseract <png> - --psm 4` per page, and write `<same name>.txt` next to the PDF with `=== PAGE n ===` markers using the original act's page numbers. Tesseract reads typed text well but not plats or handwriting. Check the OCR against the notes taken by eye before relying on either.

