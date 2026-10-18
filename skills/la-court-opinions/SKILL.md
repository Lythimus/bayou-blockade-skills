---
name: la-court-opinions
description: Louisiana state appellate case law. Searches Louisiana Supreme Court and Court of Appeal opinions (First Circuit first, since LDEQ permit appeals from the 19th JDC go there), downloads opinions and reads the decision date, disposition, panel, and rehearing actions, finds the page a pin cite points to, and verifies a citation — reporter cite, court, date, docket, LASC writ history, citing opinions — reporting found / conflicting / not found with the coverage gaps stated. Also lists LDEQ/DCE/DENR matters on the Division of Administrative Law hearing docket and searches DAL's Ethics decisions. Use before citing any Louisiana case in a comment, to find appeals of an LDEQ permit, or to check what happened to a permit challenge on appeal.
argument-hint: <party or case name> | verify-cite "<citation>" | --docket <2023 CA 0578>
allowed-tools: Bash, Read, WebFetch, WebSearch, AskUserQuestion
---

# Louisiana court opinions

A permit challenge in Louisiana runs from LDEQ to the 19th Judicial District Court (East Baton Rouge) on a petition for judicial review under R.S. 30:2050.21, then to the First Circuit Court of Appeal, then by writ application to the Louisiana Supreme Court. This skill covers the two appellate levels, which is where the published law is, and the Division of Administrative Law (DAL), which hears adjudications the applicant or respondent requests.

Its first job is verifying the case law in `skills/public-comment/references/louisiana-hooks.md` and any case a draft comment cites. A citation is not ready to use until `verify-cite` finds it **and** someone has read the pin page.

## Scripts

Standard library plus `pdftotext` (`brew install poppler`). Cache: `~/.cache/bayou/la-court-opinions/`. Every command takes `--json`.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/la-court-opinions"

python3 "$S/la_opinions.py" search "Rise St. James" --court 1 --from 2023 --to 2024
python3 "$S/la_opinions.py" search "Environmental Quality" --court 1            # every LDEQ appeal, last five years
python3 "$S/la_opinions.py" search Formosa --court la --fulltext                # LASC opinions that mention it
python3 "$S/la_opinions.py" docket "2023 CA 0578"                               # every document under one docket
python3 "$S/la_opinions.py" fetch "2023 CA 0578" --find "environmental justice" # date, disposition, panel, pages
python3 "$S/la_opinions.py" grep "Save Ourselves" --docket "2023 CA 0578"       # page-numbered hits in downloaded text
python3 "$S/la_opinions.py" verify-cite "Browning-Ferris Industries Petit Bois Landfill, 657 So. 2d 633 (La. App. 1 Cir. 1992)"
python3 "$S/la_opinions.py" dal-docket --agency DEQ DCE DENR                    # add --grep <company>
python3 "$S/la_opinions.py" dal-ethics "campaign finance"
```

`--court` takes `la` (Supreme Court), `1`–`5` (a circuit), or `all`. `--from`/`--to` are decision years; the default is the last five.

**Download guard.** `fetch` estimates uncached PDFs and stops (exit 3) above 25 files or 100 MB. A First Circuit `search` stops when it needs more than six uncached year indexes; each is ~1.6 MB of JSON, and a 1988–2026 sweep is ~34 MB. Relay the estimate to the user and ask before rerunning with `--yes`. Year indexes are cached for 1 day (current and prior year) or 30 days (older).

**Rate limit.** CourtListener allows 5 anonymous requests a minute and 50 an hour. The script spaces calls 13 s apart, waits out a short 429, and caches every response for a day. When the hourly limit is hit it exits 4 with the time until reset; tell the user rather than retrying in a loop. `verify-cite` makes three or four calls (30–60 s), so an hour's budget covers about a dozen citations. A token lifts both limits: set `COURTLISTENER_TOKEN`, or add a line `CourtListener token: <token>` to `~/.claude/bayou-credentials.md` (free account at courtlistener.com → Profile → API).

## Workflow

1. **Citation check** (the usual job). Run `verify-cite` with the citation exactly as the draft gives it. It matches on the reporter cite first, then the docket, then the caption, and reports:
   - **status** — `found`, `conflicting` (the record's year, court or reporter differs from the citation; each conflict is listed), `ambiguous` (several cases match a caption; rerun with the docket), or `not found in either source`;
   - **later history** — LASC opinions naming the same parties after the decision date (name matches only, so confirm the writ names this docket) and how many Louisiana opinions on CourtListener cite it;
   - **gaps** — what neither source could check. Carry these into the draft's notes; never turn a gap into "no subsequent history".
2. **Read the pin page.** `verify-cite` proves the case exists; it does not prove the case says what the draft says it says. `fetch <docket> --find "<phrase>"` prints the pages a phrase appears on. Check the printed page number at the foot of the page before equating it with the PDF page; in 2023 CA 0578 they match, so "Op. at 46" is PDF page 46. Then read that page in the `.layout.txt` file `fetch` prints.
3. **Permit-appeal research.** `search Environment --court 1` lists LDEQ appeals by caption; use "Environment", not "Environmental Quality", because some captions read "Department of Environment Quality" (2026 CW 0556). They are few: five LDEQ dockets (seven documents) in the 2020–2026 folders. Captions name the agency in full, so add the facility or company name to narrow it. A caption search finds only the appeal's parties; an intervenor such as Formosa (FG LA LLC) is not in the RISE caption, so search the community group, then confirm with `fetch`.
4. **DAL.** `dal-docket --agency DEQ` lists scheduled LDEQ adjudications (enforcement appeals, permit hearings the applicant requested). Older matters can carry the suffix `EQ` instead of `DEQ` (e.g. `94-219-EQ`); add it to `--agency` when completeness matters. To get a DAL decision in a DEQ, DCE or DENR matter, draft a request with `bayou:la-public-records-request`.

## Citation format

Louisiana's uniform citation (La. Sup. Ct. Gen. Admin. R. Part G § 8) uses the docket and the decision date, then the reporter cite when there is one:

```
RISE St. James v. La. Dep't of Envtl. Quality, 2023-0578 (La. App. 1 Cir. 1/19/24), 383 So. 3d 956 (reporter cite unverified)
Save Ourselves, Inc. v. La. Envtl. Control Comm'n, 452 So. 2d 1152 (La. 1984)
In re Browning-Ferris Indus. Petit Bois Landfill, 93-2050 (La. App. 1 Cir. 6/23/95), 657 So. 2d 633, writ ___, 95-2127 (La. 11/27/95), 663 So. 2d 742
```

`fetch` prints a "cite as" line in this form; the caption still needs abbreviating by hand. The date is always the decision date from the opinion ("JUDGMENT RENDERED") or CourtListener's `dateFiled`, never the court site's upload date. Before writing "writ denied" or "writ granted", read the LASC action: `verify-cite` finds writ actions by name, and the disposition is in the action itself.

## Coverage and gaps

| Source / court | Covered | Not covered — say so |
|---|---|---|
| **First Circuit** | The court's own index at la-fcca.org (one CivicLive folder per docket year), 2006 to today, ~1,200–1,300 documents a year. CourtListener through 2018. | The court site holds only 35 documents for 1988–2005, so older First Circuit cases come from CourtListener. Full-text search runs only over opinions already downloaded (`grep --cached`); the site's own full-text search needs JavaScript. |
| **Supreme Court** (`la`) | CourtListener, including 2026 opinions from lasc.org. | One-line writ grants and denials are often missing: the Sept. 4, 2024 denial of writs in RISE St. James (2023 CA 0578) is not there. `verify-cite` reports a missing writ as a gap. Search lasc.org and the web (`"<caption>" writ denied`) for the action, and cite the LASC action itself, not a secondary report. |
| **Second and Fourth Circuits** | CourtListener, current (la2nd.org and la4th.org scrapers). | — |
| **Third and Fifth Circuits** | CourtListener through 2018 (newest Third Circuit opinion found: Sept. 2018). | Nothing after 2018 is on CourtListener and this skill has no index for their sites. Use WebSearch with `site:la3circuit.org` or `site:fifthcircuit.org`, and say the result is unverified. |
| **19th JDC** (and every district court) | Not covered. | Trial-court dockets and judgments need a subscription (the clerk's remote access) or a records request. Say "not checked — 19th JDC records are subscription-only", never "no district court ruling". The First Circuit opinion usually recites the district court's judgment, docket number and date. |
| **DAL** | `docket.html` (scheduled hearings, current only); Ethics and Board of Ethics decisions (`dal-ethics`). | DAL publishes no LDEQ, DCE or DENR decisions, and calls its docket "non-exhaustive". Route decisions to `bayou:la-public-records-request`. Under R.S. 30:2024 an adjudicatory hearing is requested by the applicant or respondent, so a community challenge to a permit goes to the 19th JDC, not DAL. |
| **Federal courts** | — | `bayou:pacer-case-search`. |

## Traps

- **A party-name match is not a case match.** "RISE St. James" on the LASC in 2026 returns *Alexander v. St. James Parish*, 2025-C-00866 (La. 3/6/26), a parish land-use ordinance case. It is not history of the Formosa permit appeal. Confirm the docket and the agency before calling anything subsequent history.
- **Upload dates are not decision dates.** The First Circuit's 2024 folder was uploaded in April 2025. The script leaves the decision date blank until `fetch` reads it from the PDF.
- **Folders are by docket year.** 2023 CA 0578 was decided in January 2024 and sits in the 2023 folder. `search` reads one year further back than `--from` for that reason.
- **One docket, several documents.** A "(2)" document is usually the rehearing or writ action, not a second opinion. For 2023 CA 0578 it is three rehearing actions dated Feb. 15, 2024, on applications by Beverly Alexander, LDEQ and the RISE plaintiffs; two read DENIED and OCR garbled the third. `fetch` lists each application, who filed it and the result; a result the OCR garbled is flagged for reading, not guessed.
- **Docket formats differ by court** and two collide: `2024-CA-0286` is a Fourth Circuit docket and also the form LASC uses (`2001-CA-0009`); `95-C-2127` is LASC but `16-CA-387` is the Fifth Circuit. Pass `--court la` or `--court lactapp` when a bare docket is ambiguous. First Circuit: `2023 CA 0578` (two-digit years before 1999: `93 CA 2050`). Second: `56,154-CW`. Third, as CourtListener stores it: bare `18-279`. Citations in the uniform form (`2023-0578`) carry no case-type letters; `verify-cite` takes the court from the citation's parenthetical to read them.
- **Scanned PDFs.** `fetch` reports `text layer: NO`. Run `bayou:document-ocr` before quoting.

## Sources

- CourtListener REST v4 search: https://www.courtlistener.com/api/rest/v4/search/ (`type=o`, `court=la` or `lactapp`)
- First Circuit opinion index: https://www.la-fcca.org/decisions → year pages on `lafcca.hosted2.civiclive.com`, read through `/portal/svc/ContentItemSvc.asmx/GetItemList`
- Louisiana Supreme Court: https://www.lasc.org/opinions (PDFs need https; http returns 522)
- DAL docket: https://www.adminlaw.la.gov/docket.html; Ethics decisions: https://www.adminlaw.la.gov/ethics-decisions/

If the First Circuit decisions page stops listing year links, the script exits with a "layout may have changed" error rather than returning nothing. Fix the parser; never report "no opinions".

$ARGUMENTS
