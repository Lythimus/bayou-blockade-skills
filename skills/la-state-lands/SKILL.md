---
name: la-state-lands
description: Louisiana state lands and state mineral contracts from the public SONRIS GIS (no login). Covers State Land Office water-bottom claims (state claimed, dual claimed, judgment or compromise against the state, title-file index), state-owned and agency land, WMAs and refuges, and Office of State Resources (formerly OMR) mineral leases, operating agreements and State Agency Leases. It also covers the State Mineral and Energy Board's carbon dioxide storage (CCS) operating agreements, with operator, resolution and acreage for every CS number, the current SMEB agenda's acreage-under-contract and legal items, and nominated tracts and lease-sale history. Use when a Class VI area of review or pressure front may reach state water bottoms or land the operator does not control (la-class-vi question CVI-002), when asking who holds the state pore-space or mineral lease under a lake, bayou or WMA, whether a water body is state-claimed, what a CS/SL/A/SAL number is, or when the SMEB will take up a sequestration agreement and its parish hearing.
argument-hint: at <lat> <lon> [--radius M] | overlap <aor.geojson> | overlap --point <lat> <lon> --radius M | ccs [--parish P] | lease <SL 344|CS05A|SAL 18542> | search "<name>" | smeb | get <CS05>
allowed-tools: Bash, Read, WebFetch, WebSearch
---

# Louisiana state lands and state mineral contracts

The Department of Conservation and Energy (DCE, formerly DNR/DENR) runs a public ArcGIS server, `https://sonris-gis.dnr.la.gov/arcgis/rest/services/DNRSvc/`, with no login and no CAPTCHA. It carries:

- the water-bottom claims of the State Land Office, which is in the Division of Administration (R.S. 41:1). Navigable water bottoms belong to the state under the public trust (R.S. 41:1701).
- the leases of DCE's Office of State Resources (OSTR, formerly the Office of Mineral Resources).

The script reads:

| Key | Layer | What it holds |
|---|---|---|
| `leases` | OMR/0 Active Leases | about 1,080 rows. `SL` state mineral leases (lessee, royalty, acreage, sale date); `A####` operating agreements (oil and gas, gas storage); `WL`/`WE`; and the `CS…` carbon dioxide storage operating agreements |
| `sal`, `blease` | OMR/15, OMR/16 | State Agency Leases (agency land leased through the Board); B leases (small unleased acreage inside units) |
| `legal` | OMR/7 Legal Areas | partial state interest, lawsuits, judgments, compromises, no-leasing areas |
| `tracts`, `archive` | OMR/1, OMR/2 | tracts nominated for the coming sales; every nomination, bid and award since 2001 (about 12,000 rows) |
| `claimed` | COMMON/17 State Claimed Water Bodies | the State Land Office's published claim map, coded by `WEB_STATUS` |
| `waterbodies` | COMMON/20 State Water Bodies | title-file index: `STATECLAIM`, title number, court case |
| `stateland`, `wma`, `refuge` | COMMON/18, 19, 24 | state-owned and leased surface (SLABS), WMAs, refuges |
| `landsale`, `major`, `parish` | COMMON/29, 21, 11 | land sales with minerals reserved to the state; major inland water-body outlines; parishes |

The legal hooks:

- The State Mineral and Energy Board (SMEB) alone contracts for CO2 storage beneath state land and water bottoms. Under **R.S. 30:209(4)(e)** it needs:
  - a two-thirds vote of its members;
  - notice to the governing authority of each affected parish;
  - a public hearing in each affected parish, held by a hearing officer under R.S. 30:6.
- The Board's **Carbon Dioxide Sequestration Operating Agreement Procurement Guidelines** (approved 2025-05-14) set the sequence for new agreements:
  - registration and pre-nomination title research;
  - nomination and advertisement;
  - proposals and a technical briefing;
  - **Conditional Approval**;
  - parish notice and public hearing (§10; the operator may respond within 10 days of the hearing);
  - final approval by two-thirds vote by the sixth Board meeting after Conditional Approval (§11).

  The guidelines' sample timeline puts a first round's Conditional Approval at the November 2026 meeting and hearings from November 2026 to May 2027. The guidelines say those dates are illustrative.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/la-state-lands"
T() { uv run -q --no-project python -I "$S/statelands.py" "$@"; }

T health                                    # each layer's count == unique ids; all CS numbers in the crosswalk (~10 s)
T at 30.25 -90.50                           # Lake Maurepas: claim status (layer 17 vs 20), CS01B, parish
T at 29.995 -90.41 --radius 800             # a point on a bank: widen to reach the channel
T overlap aor.geojson                       # CVI-002: AoR acres on CCS OAs, state-claimed bottoms, state land, leases
T overlap --point 29.85 -90.27 --radius 3000 --samples 8000
T ccs                                       # every CS agreement: operator, resolution, stated vs GIS acres, parishes
T ccs --parish "st charles"
T lease "SL 344"                            # also: 22159 (number alone), CS05A, "SAL 18542", B1021
T search "venture global|high west"         # lessee, bidder, applicant, agency; CCS operators from the crosswalk
T search "merlin oil" --layer archive       # 2001-present nominations, bids and awards
T search "cataouatche" --layer claimed --layer waterbodies
T smeb                                      # this month's agenda: acres under contract, legal items, CCS mentions
T get CS05 --out ./ccs                      # the executed agreement scans (CS05A/B/C, ~14 MB)
```

- `--json` and `--refresh` go before or after the subcommand. Responses are cached for one day under `~/.cache/bayou/la-state-lands/`.
- `overlap` takes a GeoJSON Polygon or MultiPolygon in EPSG:4326. For a Class VI well, use the AoR or pressure-front figure from the permit application, digitized, or a circle around the injection well.
- Area is estimated from a grid of sample points (default 4,000). The output prints acres per sample, so the error is about one sample's acreage at each boundary. Raise `--samples` for a small AoR or a thin sliver.
- Exit codes:
  - 2: bad arguments; a point outside Louisiana; `get` above 25 MB without `--yes` (size printed); `smeb` without `pdftotext`.
  - 3: no such lease, CS number, parish or search match. Near lease numbers are printed.
  - 5: the GIS server or DCE site is down, returned HTML instead of JSON (Cloudflare challenge or outage), or Cloudflare's WAF rejected the query (HTTP 403). `health` also exits 5 if a count check fails.

## Workflow

1. **Locate.** Get the well or AoR coordinates from `la-class-vi` (the EPA/DCE permit record) or `facility-coordinates`. Run `at <lat> <lon>` at the injection well to see whether it sits inside a CS operating agreement, and on which water body.
2. **Answer CVI-002.** Run `overlap` on the AoR, then again on the pressure front if it is larger. Read the summary lines:
   - *inside a CCS operating agreement*: state pore space the operator, or another operator, holds by contract. The crosswalk names the operator. A different operator's CS polygon inside the AoR is a conflict to raise.
   - *state-claimed bottom or state-owned surface, outside every CCS OA*: state acreage with no storage contract. Injecting under it needs an SMEB agreement, with its parish hearing.
   - *in neither the state layers nor a CCS OA*: presumptively private surface or water bottom. Find the owners with `parish-assessor-gis`. This data cannot show who owns pore space there.
   - *under a state mineral lease*: an SL lessee whose mineral rights the plume may affect. `lease` gives the lessee and the SONRIS record.
   - *dual claimed (DC)* and *JAC*: contested ownership. Cite the claim code, not "state-owned".
3. **Identify the agreement.** `ccs` and `lease CS…` give the operator, SMEB resolution and date, and the agreement PDF. `get` downloads the executed scans; run `document-ocr` before searching them. The posted agreement texts (`text` in `ccs_agreements.json`) already have a text layer.
4. **Check the Board.** `smeb` reads the current month's agenda. Look at the Lease Review Report figures, the Legal & Title Controversy items, and any line mentioning sequestration, Conditional Approval or a storage operating agreement. A new agreement must have a parish hearing before final approval. Put it on `la-comment-calendar` when the parish notice appears.

## Reading the claim codes

Layer 17 (`WEB_STATUS`) is the State Land Office's public claim map:

- `Y`: state claimed.
- `DC`: claimed by both the state and the adjoining landowner. The map says "enter at your own risk".
- `JAC`: a judgment, agreement or compromise against state ownership.
- `PA`: publicly accessible. This is an access status, not an ownership claim.

Layer 20 (`STATECLAIM`) indexes title files:

- `Y`: the state claims the bottom.
- `N`: the state does not claim it.
- `PARTIAL`: the state claims part of it.
- `UN`: no published legend.
- `NO TITLE FILE`: no title file has been reviewed. This is **not** a finding that the state doesn't claim the bottom.

**The two layers disagree often.** Lake Maurepas, Lake Cataouatche and the Mississippi River at Norco are all `Y` in layer 17 and `NO TITLE FILE` in layer 20. `at` prints both and flags any disagreement. Cite layer 17 for the claim and layer 20 for the title number or court case.

## CCS operating agreements

GIS carries 10 CS polygons under 6 agreements. They have no operator, acreage or parish attributes and `SHAPE.AREA` = 0. `ccs_agreements.json` maps each CS number to its source:

- operator names from the agency's [agreements page](https://www.denr.louisiana.gov/page/carbon-capture-and-wind-energy-agreements);
- resolution, date and acreage from OCR of each executed agreement's resolution and first pages.

Checked 2026-10-17:

| Agreement | Operator | SMEB resolution | Stated acres | GIS acres | Where |
|---|---|---|---|---|---|
| CS01A/B/C | Air Products Blue Energy, LLC | 21-10-051, 2021-10-13 | 33,146 / 57,100 / 32,209 | 32,857 / 59,085 / 34,015 | Maurepas Swamp WMA, St. James (A); Lake Maurepas (B); Sabine Lake, Cameron (C) |
| CS02A/B | Capio Sequestration, LLC | 21-10-052, 2021-10-13 | 32,711 / 11,800 | — / 12,914 | Maurepas Swamp WMA (A, **not on the GIS layer**); Sherburne WMA (B) |
| CS003 | Venture Global CCS Plaquemines, LLC | 22-09-009, 2022-09-14 | 9,101.13 | 9,103 | Barataria Bay, T20S R25E |
| CS004 | Venture Global CCS Cameron, LLC | 22-09-010, 2022-09-14 | 18,022.95 | 18,025 | state waters off Cameron |
| CS05A/B/C | High West Sequestration, LLC | 23-08-013, 2023-08-09 | 21,079.18 total | 21,084 | Lake Cataouatche / Salvador WMA, St. Charles and Jefferson |
| CS006 | Castex Carbon Solutions, LLC | 23-08-014, 2023-08-09 | 24,181 | 24,199 | state waters off Cameron |

- **CS05 is not new.** The three St. Charles polygons first appear on the layer dated 2026-10 with `CD_SOURCE` "(New)". The agreement was approved in August 2023, after hearings in St. Charles and Jefferson (docket OMR 23-01). Treat "(New)" as the mapping date.
- **The totals don't reconcile.** The Oct 14, 2026 Lease Review Report counts **4 CCS OAs, about 361,705 acres**. The executed agreements state 239,350 acres across six agreements, and GIS computes about 211,300. The report comes from the SONRIS lease database. Quote each figure with its source; don't substitute one for another.
- **Adding to the crosswalk.** `health` flags any CS number on GIS that has no crosswalk entry. Add one only with a source: the agency agreements page, a resolution, or the agreement text. Never infer the operator from location or date.

## Records and gated documents

- Lease detail (`state-lease-information`) and lease documents (`finddocuments?idx=xstateleasenum`) are SONRIS pages behind reCAPTCHA. `lease` prints both URLs and the `sonris-session` command line for them (`sonris_get.js --url … --throttle 2500`). Batch several leases into one run with `--url-file`.
- State Agency Lease rows still carry pre-2020 `sundown`/`ucmwww` links. They redirect to the same CAPTCHA, so the script prints the current `ucmsearch` URL instead.
- Executed CCS agreements are scanned PDFs on `www.denr.louisiana.gov/assets/OMR/media/forms_pubs/CS…pdf`. That archived DENR site still serves files that `dnr.louisiana.gov` links now redirect away from.
- SMEB agendas:
  - Only the current month's "Notice, Agenda and Reports" PDF is linked from [the Board page](https://www.dce.louisiana.gov/state-mineral-and-energy-board). Earlier months return 404 at the same URL pattern, so save a copy at the time, or ask OSTR under `la-public-records-request`.
  - The Board-presentation files (`.docx`, `.xlsx`) are listed with their meeting dates.
  - Tracts are advertised on the [Notice of Publication](https://www.dce.louisiana.gov/page/mineral-and-energy-board-notice-of-publication) page about 50 days before a sale.

## Limits and traps

- **Empty is not private.** A point on a bank, or in a small bayou, canal or accreted marsh, often hits no water-body polygon. The Norco point at 29.995 returns nothing, while 29.990 hits the river. The script says "not in these layers", never "not state-claimed". Widen with `--radius` and check the channel.
- **Layer 20's `PARISH`** is the title record's parish, not the point's. The Mississippi River at Norco (St. Charles) reads `PLAQUEMINE`. Use the `parish` layer.
- **Lessee names are original lessees.** Assignments and current record title are on SONRIS. The Legal & Title items show current owners, such as ELP on SL 22299.
- **Layer 0 is active contracts only.** Expired or released leases drop off. `lease <number>` then falls back to the tract archive. The former operating agreement A0392 is gone, though the October 2026 agenda still discusses its well.
- **The GIS mapping lags the contracts.** CS02A is executed and listed by the agency, but it isn't drawn. CS05 was drawn three years after approval. A missing polygon is not proof that no agreement exists: check `ccs` and the agency page.
- **Cloudflare.** la.gov's WAF rejects some SQL-looking `where` clauses with HTTP 403. One example is `LIKE` combined with `IS NULL`. The script sends only equality, IN, one LIKE, or `1=1`, and filters on the client.
- **Layer 30** (Land Sale Minerals Data) failed every spatial query when checked, so `landsale` uses layer 29 instead. Layer 29 has the same 5,450 rows but no tax-debtor or vendee names.
- **This data has no private pore-space ownership.** Private storage agreements are in parish conveyance records. Unitization orders (R.S. 30:1104) and expropriation of subsurface rights (R.S. 30:1108) are in conservation records. None of them is in these layers.

## Related skills

- `la-class-vi`: the Class VI permit, AoR and pressure front. CVI-002 (pore-space control) is answered by `overlap` here.
- `ldh-drinking-water`: public-supply wells inside the same AoR and their SWAP protection radii (`near --aor`, CVI-008).
- `parish-assessor-gis`: surface owners for the AoR acreage outside the state layers.
- `sonris-session`, `sonris-doc-search`: lease records and documents behind the SONRIS CAPTCHA (`xstateleasenum`).
- `la-comment-calendar`: SMEB parish hearings on new sequestration agreements, and lease-sale dates.
- `la-coastal-use-permits`: CUPs over state water bottoms. The State Land Office comments on them.
- `usace-408-permits`: Corps permissions for the same pipelines and wells in state waters.
- `la-rs-search`: R.S. 30:209 (SMEB operating agreements), 30:6 (hearings), 30:1104 and 30:1108 (storage unitization and expropriation), 41:1 and 41:1701 (State Land Office, public-trust water bottoms).
- `la-public-records-request`: earlier SMEB agendas and minutes, title files behind layer 20, and lease files.
- `document-ocr`: the executed agreement scans.
- `public-comment`: comments at an SMEB parish hearing.
