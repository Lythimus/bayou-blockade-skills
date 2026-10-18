---
name: parish-council-agendas
description: Parish council and planning/zoning commission agendas, minutes and keyword alerts for St. Charles (Legistar), Ascension (CivicClerk), and East Baton Rouge (Metro Council), Plaquemines, St. Bernard, St. James and Assumption (CivicPlus AgendaCenter; St. James and Assumption are scanned PDFs read by OCR). Flags rezonings, special/conditional uses, variances, industrial uses (M-2, HIDF, data centers, pipelines, LNG and plant construction permits), road and servitude revocations and property transfers, financing and incentives (inducement, PILOT, cooperative endeavors, ITEP), and land-use code changes. Follows a case from the commission to the council ordinance and its hearing date. Use before a parish meeting, to find when a rezoning or servitude revocation for a project will be heard, or to track an ordinance through introduction, hearing and vote.
argument-hint: alerts [parish ...] [--yes] | meetings|bodies <parish> | items <parish> <meeting-id> | track <parish> "<case, applicant or matter>" [--yes] | get <parish> <meeting-id>
allowed-tools: Bash, Read, WebFetch, WebSearch
---

# Parish council agendas

One script, one adapter per platform. The registry is `parishes.json`; alert categories are in `keywords.json`.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/parish-council-agendas"
A() { uv run -q --no-project python -I "$S/agendas.py" "$@"; }

A health                                   # each verified parish answers; CivicClerk paging has no gaps
A alerts                                   # all verified parishes, 14 days back to 45 ahead
A alerts st-charles ascension --category rezoning --category industrial
A alerts ascension --term "data cent" --since 2026-01-01
A meetings st-charles --body "Planning"    # date, time, meeting id, what is posted
A items st-charles 1989                    # agenda lines: matter, action, outcome, public-hearing date
A items st-james 662 --minutes             # scanned parish: OCR the minutes
A items plaquemines 690                    # nested items numbered 7.a.4; parish permits and LNG items
A track st-charles 2026-12-R               # P&Z case -> council ordinance, history, attachments, hearing
A track ascension "ZT-26.01"               # every agenda the case appeared on
A track east-baton-rouge "Case 30-26"      # Planning Commission -> Metro Council introduction -> hearing
A track st-bernard Z-2026-006              # docket through P&Z, introduction, hearing and each tabling
A get ascension 1702 --what packet --out ./agendas
```

- `--json` and `--refresh` work on every command. Listings and PDFs are cached 6 hours under `~/.cache/bayou/parish-council-agendas/`, extracted text by file id and PDF hash. For a meeting more than 14 days past, the extracted text is reused without fetching the PDF again.
- `get` stops before any single file over 25 MB. `track` and `alerts` add up the agenda PDFs not yet cached and stop if the total is over 25 MB, saying how much and from which body. Rerun with `--yes`, or narrow with `--since` (or `--body` for `alerts`). The first `track` in St. Bernard trips this: a year of council agendas is about 80 MB.
- Exit codes: 2 bad arguments or a download over 25 MB without `--yes`; 3 unprobed parish, unknown meeting, or nothing found; 5 the platform is down or returned the wrong format.
- **A keyword hit is a lead, not a finding.** Read the item and its attachments before citing it.

## Parishes

| Parish | Platform | What is online | Gaps |
|---|---|---|---|
| St. Charles | Legistar API | Council items with matter file, action, vote; P&Z, ZBA, CZAC, Industrial and Economic Development agendas; matter histories and attachments (staff report, P&Z minutes, maps) | P&Z minutes stay "Draft"; the P&Z vote is in the council matter's history |
| Ascension | CivicClerk API | Item tree for every board; agenda, packet and minutes files (plain text available); minutes for P&Z, Zoning Commission, BOA, drainage boards, committees | **No council minutes and no vote fields.** Council outcomes need the video or a records request |
| St. James | CivicPlus AgendaCenter | Council, Planning Commission, Coastal Zone, Economic Development agendas and council minutes | Copier scans; OCR typos. The agenda PDF also holds the packet (draft resolutions, prior minutes, plats); only the agenda pages are read, so packet text is not searched (`get --what agenda` and read it) |
| East Baton Rouge | CivicPlus AgendaCenter (brla.gov) | Metro Council (city-parish), Planning Commission, Board of Adjustment, Local ITEP Committee, Capitol House EDD; council minutes | Several files per meeting date: `meetings` shows each file's title (regular agenda, public notice, administrative matters). Public notices are one-page scans with no items |
| Plaquemines | CivicPlus AgendaCenter | Council (parish construction permits by application number, Business Occupancy Certificates, zoning ordinances with a plain-language DIGEST), Port, Development Board; council minutes | Planning commission agendas are not posted separately; zoning comes to the council |
| St. Bernard | CivicPlus AgendaCenter | Council (ordinances by Summary No. with their history: P&Z recommendation, introduction, hearing, tablings), Planning Commission and BZA by docket | Council minutes are posted for some meetings only. The council PDF carries the packet (up to about 8 MB; a year of agendas is about 80 MB); reading stops at the "Approved by:" line |
| Assumption | CivicPlus AgendaCenter | Police jury and its committees; minutes for most meetings | Copier scans (OCR). No separate planning or zoning body posts here |

Other parishes in `parishes.json` are `unprobed` or `probed-unusable`, with what the probe found (stale since 2020, Cloudflare bot wall, a CivicClerk account with nothing published, PDFs on a parish CMS). The error message for one prints that note.

## Reading the output

- **St. Charles ordinances** are introduced at one meeting and heard at a later one. `items` copies the announced hearing date onto each introduced ordinance. A rezoning's council title does not cite the P&Z case number; `track` links them through the applicant name in the P&Z line.
- **Ascension** lists each ordinance three times at its hearing (Reading, Public Hearing, Ordinance). When `track` finds the public hearing on more than one agenda, it was not finally acted on at the earlier one. Confirm from the minutes or video.
- **CivicPlus agendas are PDFs split into items by text layout**, so numbering follows the document: dotted numbers for nested lists (`9.a.2`), letters for lettered lists, and the docket for St. Bernard's commission items. A line in capitals is a section heading unless it hangs under the open item (an ordinance title in capitals, a wrapped sponsor name). Parish-specific rules are under `layout` in `parishes.json`. An item can still swallow a heading or a page footer; check the PDF before quoting.
- **East Baton Rouge** Planning Commission cases (`Case 36-26` rezoning, `PA-8-26` land use plan amendment, `PUD`/`ISPUD`/`CUP` numbers) go to the Metro Council under "PLANNING AND ZONING INTRODUCTIONS" and are heard at a later meeting with the same case number, so `track "Case NN-YY"` follows them. Council items carry a matter number (`26-01218`).
- **Plaquemines** approves parish construction permits itself (`Application No. 2026-856`). These are the parish permits for terminals, plant work and wells, separate from the state coastal use permit (`la-coastal-use-permits`). Deferred items list every earlier date: "(DEFERRED & CARRIED OVER FROM 9-10-26, 9-24-26 & 10-8-26)".
- **St. Bernard** council titles print the item's history above the ordinance ("Planning Commission recommended DENIAL on 7/28/26 ... Tabled on 9/15/26 until 10/20/26"). The AgendaCenter date can be the posting date, not the meeting date; the file title says which ("agenda for July 28th").
- **St. James and Assumption** agenda items are split at numbered lines of OCR text. OCR stops at the page with the ADJOURN line, at most 4 pages; a longer agenda is cut short. `--minutes` returns paragraphs (`p1`, `p2`, ...) under the minutes' headings, since the minutes are prose: each resolution's number, title and vote is one paragraph. Check the PDF before quoting.

## Adding a parish

Probe in this order and record what each probe finds in the parish's `parishes.json` entry, even when it fails:

1. **Legistar:** `https://webapi.legistar.com/v1/<client>/bodies`. The client name is in the parish's `<client>.legistar.com` calendar link. A client that answers but has few recent events is not where the council works now (New Orleans `cityofno`).
2. **CivicClerk:** `https://<tenant>.api.civicclerk.com/v1/Events`; the tenant is in the `<tenant>.portal.civicclerk.com` link. Check that recent events carry `publishedFiles` and that `Meetings/{agendaId}` has items (Iberia's tenant has neither).
3. **CivicPlus AgendaCenter:** `https://<parish site>/AgendaCenter`. Category ids are the `id="catN"` headings. POST `year` and `catID` to `/AgendaCenter/UpdateCategoryList` and check the newest file date (West Baton Rouge's stops in 2020). Then check one agenda PDF for a text layer (`pdftotext -l 2`); set `"scanned": true` if it has none.

A CivicPlus parish needs only a registry entry. Run `items` on two or three agendas per body. If headers, item numbers or headings split wrongly, add `layout` rules (`item_start`, `ignore`, `section`, `agenda_end`, `matter`; see the existing entries) instead of changing the shared splitter. Then add case-number `terms` and run `health` and `alerts`.

## Related skills

- `hearing-prep`: questions and oral comments for the meeting `alerts` finds.
- `la-comment-calendar`: add hearing dates.
- `parish-assessor-gis`: the parcel, owner and zoning for a rezoning's lots.
- `la-bond-dockets`, `itep-lookup`: the state side of an inducement, PILOT or ITEP item.
- `la-coastal-use-permits`: the state coastal use permit for a project whose parish construction permit is on a Plaquemines or St. Bernard agenda.
- `la-public-records-request`: Ascension council minutes, St. James packets.
- `public-comment`: a written comment on a rezoning or land-use ordinance this skill tracks.
- `permit-analysis`: local-approval questions (land use, letter of no objection) for a state or federal permit.
- `la-class-vi`: the state Class VI record for a carbon storage project a parish is acting on.
- `scp-master-drainage-plan` (user-level, St. Charles): whether a rezoned site touches a planned drainage improvement.
