---
name: la-bond-dockets
description: Louisiana public-financing docket facts for a project — State Bond Commission agenda items (docket number, agenda item, conduit issuer, project caption, par amount, bond type, Volume Cap caption, meeting date) and what the SBC minutes record for each (approved, conditionally approved, deferred, withdrawn, motion, recusals, who spoke), plus LPFA TEFRA hearing notices and board agendas, Port of South Louisiana / Port of New Orleans / Port of Greater Baton Rouge commission agendas, and the Ascension Parish Industrial Development Board's agendas. Use to fill the SBC docket and the financing stack in a TEFRA/financing comment, to get the earliest notice that a bond is moving, or to find out how the SBC disposed of an item.
argument-hint: <project, company, or issuer name> | --docket <S26-027> | --meeting <MM/DD/YYYY>
allowed-tools: Bash, Read, WebFetch, WebSearch, AskUserQuestion
---

# Louisiana bond dockets

A conduit bond for a private industrial project goes through public bodies in a fixed order: an inducement or authorizing resolution at the issuer (LPFA, a port, a parish Industrial Development Board), a TEFRA hearing under IRC § 147(f), State Bond Commission approval under La. R.S. 9:2347(H), and then a notice of sale. Each step leaves an agenda line or a notice. This skill retrieves them so a financing comment can cite the docket exactly and catch the bond early.

The argument these facts feed lives in `skills/public-comment/postures/financing.md`. That covers the RE block and `\filingid`, the request to transmit the letter to the SBC before its vote, the financing-stack section, and the notice-of-sale clock.

## Scripts

Both scripts use the standard library plus `pdftotext` (`brew install poppler`). They cache PDFs and text under `~/.cache/bayou/la-bond-dockets/` and accept `--json`.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/la-bond-dockets"

# State Bond Commission
python3 "$S/sbc_dockets.py" meetings --year 2026            # schedule + which agenda/minutes PDFs exist
python3 "$S/sbc_dockets.py" search Hyundai "Port of South Louisiana" --from 2026-01-01
python3 "$S/sbc_dockets.py" search --docket S26-027
python3 "$S/sbc_dockets.py" agenda next                     # newest agenda for the next meeting, if posted
python3 "$S/sbc_dockets.py" agenda 09/17/2026 --stage preliminary
python3 "$S/sbc_dockets.py" outcome 09/17/2026              # minutes → outcome for every agenda item

# Issuers
python3 "$S/issuer_agendas.py" lpfa-notices --grep hyundai  # TEFRA notices: par, hearing, borrower, IRC section cited
python3 "$S/issuer_agendas.py" agendas lpfa --since 2026-01-01 --grep hyundai
python3 "$S/issuer_agendas.py" agendas portsl --since 2026-06-01        # also portnola, portgbr, ascension-idb
python3 "$S/issuer_agendas.py" agendas ascension-idb --list             # list documents without downloading
```

**Download guard.** Before fetching, each command counts the uncached PDFs and estimates their size. Above 25 files or 100 MB, it exits with code 3 and prints the estimate. Relay the estimate to the user and ask before rerunning with `--yes`, or narrow the range. SBC agendas run 0.1–2.6 MB each. `search` defaults to the current year, which is about 12 files, and adds the 2020–2025 archive only when `--from` reaches back into it.

## Workflow

1. **Name the project the way the issuers do.** Start with the company and the parish, because issuers caption bonds by project ("HYUNDAI-POSCO Louisiana Steel LLC Project") and ports by program ("Hyundai Steel Project/FastSites Program"). Try two or three variants in `search`.
2. **Find the TEFRA notice.** For LPFA, use `lpfa-notices`. It extracts:
   - the par cap;
   - the hearing date, time, and place;
   - the **borrower named in the notice**;
   - the owner statement;
   - the **IRC section the notice cites**. Check it against what the notice describes. The Hyundai notice cites § 146(a), the volume cap, as if it defined a facility. That is a Tier 1 point in the financing posture.

   For other issuers, run `agendas <issuer>`.
3. **Search the SBC agendas** for the same names. The result gives the docket, item, issuer, project caption, par, bond type, and whether the caption says "(Volume Cap)".
4. **For a meeting already held, run `outcome`.** It takes item numbers from the Final agenda, falling back to Posted, and reads the minutes for:
   - the outcome;
   - the motion and seconder;
   - any conditions;
   - recusals;
   - attendance notes, such as the Governor's representative leaving before items 61 and 65;
   - who spoke for and against;
   - roll-call tallies and named objections, where the minutes record them.

   The parser reads both minutes layouts. Through April 2025, the minutes repeat each item under its own heading and end it with "the item was approved". From May 2025 on, they use narrative paragraphs ("Items 3 through 47 were approved").

   Final-agenda stamps such as "WITHDRAWN BEFORE MEETING" go to the item the stamp is drawn over on the page, not the item it sits next to in the text. The two can differ: on 2026-06-18 the stamp falls between items 26 and 27 in the text, but it overlays item 27, and the minutes confirm item 27 was the one withdrawn.
5. **Read the issuer agendas around the same dates.** Look for:
   - authorizing and amending resolutions ("amending and supplementing a prior resolution adopted January 7, 2026, as amended July 15, 2026");
   - lease, PILOT, and cooperative endeavor agreements;
   - **notice of sale** language, which the script prints on its own lines.
6. **Compile the financing stack** as one table. Every row needs a source URL and the agenda stage it came from.

| Piece | Issuer | Docket / item | Project caption | Borrower (as named in a source) | Par | Bond type | Vol. cap | SBC meeting | Outcome | Source |
|---|---|---|---|---|---|---|---|---|---|---|

## Timing

- **When agendas appear.** The SBC meets monthly; `meetings` lists the dates. Applications are due 20 working days before a meeting. The **Preliminary** agenda goes up about one week before, and the **Posted** agenda 24 hours before. The **Final** (labelled "(*SAP)" or "Final") and the **minutes** are posted afterward.
- **When a bond can still be voted.** A bond missing from a meeting's Preliminary agenda is unlikely to be voted at that meeting, though a late addition is possible. Say when the next Preliminary should drop.
- **How the public comments to the SBC.** The agenda's own footer says how. For 9/17/2026, comments went by email to SBC-Application@treasury.la.gov before 5:00 p.m. the day before the meeting, and "all public comment will be included in the record for this meeting." `agenda` prints this paragraph. Quote it from the current agenda, never from memory.
- **The clock.** The R.S. 9:2347(G) contest period runs 30 days from publication of the **notice of sale**, which comes after SBC approval. An LPFA agenda item "ratifying the publication of a Notice of Sale" means that clock has started for that bond, so find the publication date. Confirm the statute text with `bayou:la-rs-search`.

## Honesty limits

- **Absence is not proof of non-submission.** Report "not found in SBC agendas <first>–<last>" rather than "never submitted to the SBC". A missing item may be on a later agenda, filed under a name you didn't search, or never routed to the SBC, and the agendas cannot tell those apart. That question is exactly the dispute over the Ascension IDB bond and the cooperative endeavor agreement.
- **A caption names a project, not a borrower.** Name the borrower only where a source names it, such as the TEFRA notice's "(the 'Company')". If the borrower is unclear, report that as a finding (financing posture, Tier 1). Don't paper over it.
- **Cite the agenda stage.** Preliminary captions can change before the meeting. Prefer Posted or Final, and say which one the fact came from.
- **Minutes summarize; they are not a transcript.** They say a verbatim transcript is held by the Bond Commission. To quote what was said, request it with `bayou:la-public-records-request`.
- **Treat outcome labels as parser output.** "not recorded in minutes" means no sentence in the minutes covered the item, and the skill never assumes it was approved. "discussed, no vote recorded" means the item was presented but the minutes record no vote on it. "motion passed" means a motion other than approval carried (2021-09-16: a motion to reconsider Lines of Credit at the next meeting); the Motion column quotes it. In all three cases, read the minutes PDF before writing a sentence about that item.
- **When the agenda stamp and the minutes disagree, the outcome cell shows both.** For example, on 2024-05-16 the Final agenda stamps items 56 and 57 "WITHDRAWN AT MEETING", but the minutes say they "would be deferred" to June. The minutes are the adopted record, so they come first. Cite the minutes, and mention the stamp if the difference matters, since a deferred item can come back.
- **Withdrawn, voluntarily deferred, and no-action items carry no motion.** The parser doesn't credit them with the vote on the surrounding group. A group vote that excludes an item ("Items 17 through 28, excluding Item 21") leaves that item out.
- **Scanned PDFs.** Some documents have no text layer: LPFA minutes, and most Port of Greater Baton Rouge agendas. `agendas` reports these as scanned, never as having no hits. Run `bayou:document-ocr` on them before relying on them.

## Gaps and where they go

| Need | Route |
|---|---|
| Another parish IDB (no adapter yet) | Search the web for "<parish> Industrial Development Board agenda". Then draft a request with `bayou:la-public-records-request`. Say the result is unverified. |
| SBC verbatim transcript; application packet for a docket | `bayou:la-public-records-request`, addressed to the State Bond Commission |
| ITEP, Quality Jobs, Enterprise Zone and RTA incentives on the same project | `bayou:itep-lookup` |
| The parish council side: inducement or intent-to-issue resolutions, PILOT and cooperative endeavor agreements | `bayou:parish-council-agendas alerts <parish> --category financing-incentive` (St. Charles, Ascension, St. James, East Baton Rouge, Plaquemines, St. Bernard, Assumption) |
| Statute text (R.S. 9:2347, 9:2341, 13:5121) | `bayou:la-rs-search` |
| Bond validation or CEA suits | These are state-court matters. `pacer-case-search` covers federal courts only, so say that rather than report an empty search. Appellate opinions in validation suits are in `bayou:la-court-opinions` (`search "All Taxpayers"` finds the captions issuers use). District-court filings are not covered online. |
| Pre-2020 SBC meetings | Not on the site; use a records request |

## Sources

- **State Bond Commission:** https://www.treasury.la.gov/state-bond-commission (current and next year) and https://treasury.la.gov/bond-commission-meetings-archive (2020–2025, including special meetings). The page is Wix, and its document links are opaque `usrfiles.com/ugd/…pdf` URLs, so always cite the URL the script returns.
- **LPFA:** https://www.lpfa.com/wp-json/wp/v2/posts in the `public-notices` category, and https://www.lpfa.com/about-lpfa/board-meeting-agendas/
- **Port of South Louisiana:** https://portsl.com/meeting-agendas/
- **Port of New Orleans:** https://portnola.com/info/board-and-staff/past-board-meetings
- **Port of Greater Baton Rouge:** https://www.portgbr.com/meetingsminutes (plus the `-25`, `-24` and `-23` pages)
- **Ascension Parish IDB:** https://ascensionedc.com/industrial-development-board/board-meetings

If a listing page changes layout, the script exits with a "layout changed" message rather than returning nothing. Fix the parser; never report "no items".

## Worked example: Hyundai-POSCO (Ascension Parish)

| Piece | Source | Fact |
|---|---|---|
| LPFA TEFRA notice | `lpfa-notices --grep hyundai` | Posted 2026-09-03. Not to exceed $900,000,000. Hearing set for September 14, 2026 at 10:00 a.m. Borrower named: HYUNDAI-POSCO Louisiana Steel LLC (the "Company"). Cites "Section 146(a)". |
| LPFA board | `agendas lpfa --grep hyundai` | 9/9/2026 item 6: a resolution amending the prior resolution of January 7, 2026, as amended July 15, 2026 |
| SBC | `search Hyundai` | 9/17/2026 **item 65, S26-027**: LPFA (HYUNDAI-POSCO Louisiana Steel LLC Project), $900,000,000 Exempt Facility Revenue Bonds **(Volume Cap)**. **Item 61, L26-302**: Port of South Louisiana (Hyundai Steel Project/FastSites Program), $400,000,000 Lease Revenue Bonds (dock, wharfage, conveyor) |
| SBC outcome | `outcome 09/17/2026` | Items 61 and 65 were approved without objection on Representative Brass's motion, seconded by Senator Foil. The Governor's representative left before discussion. Two people spoke in support and seven in opposition, and cards in opposition were read in. |
| Ascension IDB | `agendas ascension-idb --since 2026-03-01` | The 3/24/2026 agenda has a resolution for up to $5,800,000,000 in revenue bonds, with an agreement to lease, a PILOT agreement and a CEA with Hyundai-Posco Louisiana Steel, LLC. Not found on SBC agendas for January through October 2026. |

$ARGUMENTS
