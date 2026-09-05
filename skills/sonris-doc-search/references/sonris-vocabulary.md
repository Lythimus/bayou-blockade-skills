# SONRIS URL and metadata vocabulary

Working notes on how `sonlite.dnr.state.la.us` is actually put together, kept here because
`sonris-doc-search`, `sonris-well-lookup`, `sonris-operator-lookup`, and `la-class-vi` all
depend on it. Every entry is dated and marked **confirmed** (verified against a live
response) or **hypothesized** (inferred from naming convention or a single user-supplied
example, not yet independently verified). Treat hypothesized entries as a starting guess
to test, not as documented fact — and when a skill run confirms or kills one, edit this
file in place rather than letting the finding evaporate.

## The gate

- Every path under `/ords/` on `sonlite.dnr.state.la.us` redirects an un-cookied request
  to `SONRIS_CAPTCHA_PKG.SHOW_CAPTCHA_apex?p_session_id=<n>` — **confirmed 2026-08-15**,
  live probing across multiple distinct paths.
- reCAPTCHA Enterprise, sitekey `6Lf-V7csAAAAAJ5YNCdZoypudNqW53ZRP3iPZwnl`; verify endpoint
  `/ords/cart_prod/sonris_captcha_pkg.verify_recaptcha` (`p_remoteip`, `p_url`,
  `p_recaptcha`, `p_app=1004:22`) — **confirmed 2026-08-15**.
- Solving it sets `SONRIS_CAPTCHA2.0=<token>; max-age=604800; path=/` — **confirmed
  2026-08-15**. Site-wide, 7 days.
- **Two known exceptions that return real content with no cookie at all** — see
  "CAPTCHA-free hosts" below. Both are ORDS apps under the same domain, so the gate is
  applied per-app, not truly site-wide; don't assume a new `/ords/r/<app>/...` path is
  gated or ungated without checking.

## URL forms for documents

1. **`idx`/`val` search** — no checksum, hand-constructible, and the form Louisiana
   publishes on its own DCE site:
   ```
   https://sonlite.dnr.state.la.us/ords/r/sonris/ucmsearch/finddocuments?idx=<field>&val=<value>
   ```
   - Path resolves and is accepted by the endpoint (doesn't error) with
     `idx=xwellserialnumber&val=976229` — **confirmed the path/param shape works
     2026-08-15**; the actual filtered result content was not independently verified at
     that time because the response was CAPTCHA-gated (no session held during that probe).
   - **Live-session re-check done 2026-08-31: the filter is real, not a fixed shell.**
     With a working session, `idx=xParishCode&val=45` returned a genuine Interactive
     Report with 56 rows (real document metadata — Content Id, Field Name, Operator Name,
     etc. — not a placeholder). A non-matching query (`idx=xFieldName&val=PECAN ISLAND`)
     returned the IR's own `"No documents found matching search criteria."` empty-state
     text rather than an error or a default/unfiltered page, and different `val=`s on the
     same `idx` produced different row counts (`EXXON` → 51, `EXXONMOBIL` → 0, `EXXON
     MOBIL` → 1) — three separate signals ruling out "always 200, filter ignored." Matching
     appears to be exact/case-sensitive-ish substring on the stored field, not fuzzy —
     `EXXONMOBIL` (no space) and `EXXON MOBIL` (space) returned completely different
     results, so try the obvious spacing/punctuation variants of a name before concluding
     a true negative. The full response HTML renders server-side on first load (no
     separate `wwv_flow.ajax` call needed to see page-1 results), which simplifies scraping
     — the `ajaxIdentifier`/`DR_IR_report_id` markers in the page are for
     sort/paginate/search-within-report interactions, not required just to read what's
     already there. Pagination past the first ~20 rows does need that AJAX call and was
     not reverse-engineered this session.
   - **Open question, not yet resolved: does this form support more than one `idx`/`val`
     pair per request** (e.g. operator + parish + doctype together, matching what the
     user's own example search does)? Louisiana's published examples are all single-field.
     Until this is confirmed, `sonris-doc-search` should treat `idx`/`val` as **single-
     field per request** and do multi-condition searches by running one request per
     condition and intersecting the results client-side (e.g. `xDocname` values common to
     both an operator search and a parish search) — that degrades gracefully whether or
     not multi-param actually works. If a later run confirms repeated `idx=`/`val=` pairs
     (or `idx=a,b&val=x,y`) work as an AND filter, update this file and simplify.
2. **`p22_query` form** — the shape of the user's original example links:
   ```
   https://sonlite.dnr.state.la.us/ords/r/sonris_pub/document_access/findalldocumentsresults?p22_query=<raw SQL WHERE fragment>&p22_doctype=<doctype>&p22_sortfield=&clear=RR,22&cs=<checksum>
   ```
   `p22_query` is a **raw SQL predicate string**, e.g.
   `1=1 and UPPER(xOperatorCode) = 'H1166' and UPPER(xParishCode) = '45'` — this is the
   richest query surface (arbitrary AND conditions, in principle arbitrary WHERE-clause
   SQL against UCM metadata) but **`cs=` is an Oracle APEX page checksum that cannot be
   computed outside the app** — confirmed by inspection, not independently derivable from
   `p22_query`+`p22_doctype` alone. **This form only works for URLs the app itself
   generated** (e.g. copied out of a browser after using the SONRIS UI's own document
   search form) — don't try to hand-build one from scratch; use `idx`/`val` instead, or if
   a user pastes a working `p22_query` URL from their own browsing, that specific URL can
   be reused as-is (the checksum is valid for that exact query, not regeneratable for a
   different one).
3. **Direct document bytes**:
   ```
   https://sonlite.dnr.state.la.us/dnrservices/redirectUrl.jsp?dDocname=<ucm-id>&showInline=True
   ```
   `dDocname` is the Oracle UCM content-item ID (what search results list as the
   document's identifier) — **confirmed 2026-08-15** as the correct form for this
   endpoint, from inspecting SONRIS's own generated links; not yet confirmed against a
   live authenticated fetch (needs a session).

## Metadata field vocabulary (Oracle UCM `x`-prefixed)

| Field | Status | Notes |
|---|---|---|
| `xOperatorCode` | **confirmed** | From the user's own example URL: `UPPER(xOperatorCode) = 'H1166'`. `H1166` = High West Sequestration LLC, `L1126` = Lapis Energy (LA Development), LP. |
| `xParishCode` | **confirmed** | From the user's own example URL: `UPPER(xParishCode) = '45'` on a High West (St. Charles/Jefferson) filing. Cross-checked 2026-08-15 against the DCE Class VI page, which independently lists Lapis's Simoneaux Strat Well (serial `976229`) in St. Charles Parish — consistent with `45` = St. Charles. Re-confirmed live via `idx=xParishCode&val=45` on 2026-08-31 (56 real rows). Still only one code known — see the 64-parish table note below, unchanged. |
| `xDocType` | **partially confirmed** | `UIC CLASS VI APPLICATIONS` confirmed from the user's example (`p22_doctype=UIC CLASS VI APPLICATIONS`). The full enumeration is unknown — SONRIS's own search UI almost certainly has a doctype `<select>` with the complete list; read it directly from the live page during a session rather than guessing values, and record what's found here. |
| `xOperatorName` | **confirmed 2026-08-31** | `idx=xOperatorName&val=EXXON` returned 51 real rows (mostly Field Name "DEEP BAYOU", Field Code 3204); `val=EXXON MOBIL` returned 1 (an offshore Main Pass Block 74 commingling order); `val=EXXONMOBIL` (no space) returned 0. Confirms both that the field is real and that matching is a literal/exact-ish string match, not fuzzy — spacing and punctuation variants must be tried separately rather than assumed equivalent. |
| `xFieldName` | **confirmed 2026-08-31** | `idx=xFieldName&val=PECAN ISLAND` and `val=PECAN ISLAND FIELD` both returned the genuine `"No documents found"` empty state (not an error) — the field itself works (see `DEEP BAYOU` hits above under `xOperatorName`), this specific value just has no matches under either spelling tried. |
| `xWellSerialNumber` | **hypothesized** | Naming-convention guess, used as the `idx=` value in `sonris_session.js`'s probe URL. Not independently re-tested 2026-08-31 (only `xParishCode`, `xOperatorName`, `xFieldName` were exercised that session) — still needs its own live-session check. |
| `xWellName`, `xFieldCode` | **hypothesized** | Naming-convention guesses only — not tested. (`xFieldCode` appears as a real *column* in results, e.g. `3204` for Deep Bayou — but that's observed output, not confirmation it also works as an `idx=` input field.) |

### The 64-parish code table

Louisiana has 64 parishes and SONRIS numbers them, but **only one code is confirmed**:
`45 = St. Charles` (see above). Do not invent the rest of the table from memory or
general knowledge of Louisiana parish numbering conventions used elsewhere (e.g. FIPS
codes are a *different* numbering and will not match SONRIS's internal codes) — treat an
unconfirmed parish code as a hard blocker for a parish-based search and either find it in
a live SONRIS parish dropdown/lookup report, or ask the user for a document/URL that
already carries the code for the parish in question, the same way `45` was recovered here.

## CAPTCHA-free hosts (try these before a session is needed)

- `https://www.dce.louisiana.gov/page/class-vi-permits-and-applications` — official Class
  VI / Class V strat-test-well tracking page, includes operator, parish, well serial
  number, and status columns. **Re-confirmed live 2026-08-15**: returns real tabular
  content, no CAPTCHA. Page's own "Last Updated" stamp was 2026-05-13 as of that check —
  always read the stamp at fetch time rather than trusting this note's date.
- `https://sonlite.dnr.state.la.us/ords/r/sonris_pub/ucm_customsearches/class-vi-applications?p10_full_screen=1`
  — **re-confirmed live 2026-08-15**: an ORDS path on the *same domain* as the gated
  document search, but this one returns real content (a Class VI applications table, per
  its own on-page disclaimer text) with no cookie. Confirms the CAPTCHA gate is applied
  per-APEX-app (`sonris_pub`'s `document_access` app vs. its `ucm_customsearches` app),
  not uniformly to the whole `sonris_pub` workspace — don't assume every path sharing a
  domain or even an app prefix is gated the same way.
- `https://sonris-www.dnr.state.la.us/web_post/*.pdf` — static report PDFs, HTTP 200,
  different subdomain entirely (`sonris-www`, not `sonlite`).
- `https://www.denr.louisiana.gov/assets/IT/SONRIS/*.pdf` — official SONRIS user guides
  (useful for understanding report layouts, not for live data).

## Domain migration

The agency has moved its public site twice: `dnr.louisiana.gov` → `denr.louisiana.gov` →
**`dce.louisiana.gov`** (Department of Conservation and Energy, current as of
2026-08-15). Old links found in older filings/comment letters may 404 or redirect; prefer
`dce.louisiana.gov` for new lookups and note when an old-domain link is being cited as a
historical reference rather than a live one. `sonlite.dnr.state.la.us` (the ORDS app
itself) has **not** moved and is a separate hostname from the agency's public marketing
site regardless of which domain generation that site is on.

## Dead ends / things that did not work

- Assuming the `idx`/`val` form is ungated because it lacks a `cs=` checksum — it is
  **not** ungated; it 302s to the same CAPTCHA page as everything else under
  `/ords/r/sonris/...`. The absence of a checksum only means the URL is *constructible*,
  not that it's exempt from the session requirement.

$ARGUMENTS
