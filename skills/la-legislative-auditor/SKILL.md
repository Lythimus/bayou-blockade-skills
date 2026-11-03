---
name: la-legislative-auditor
description: Search the Louisiana Legislative Auditor's public audit reports by entity, parish or words in the report's name — performance audits, investigative reports, state financial audits, and the CPA audits and sworn financial statements that local bodies (parish councils, school boards, levee and drainage districts, industrial development boards, ports, fire districts) file with the auditor. Returns title, date, type, entity, period, report number and link. Use to find a local body's audited financials, a program audit such as ITEP's, or what the auditor has released lately. No browser or key.
argument-hint: search "<words in the report's name>" | parish "<parish>" | agency "<exact name>" | agencies "<words>" | new
allowed-tools: Bash, Read, WebSearch, AskUserQuestion
---

# Louisiana Legislative Auditor reports

The Louisiana Legislative Auditor (LLA) publishes its own audits and the audits and sworn statements local bodies must file with it. This skill finds reports and links to them. It reads no report text and draws no conclusion from a report. Read the PDF before relying on what a report says.

## Commands

Standard library only. `S` is this skill's directory.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/la-legislative-auditor"

python3 -I "$S/lla_reports.py" search "Industrial Tax Exemption"
python3 -I "$S/lla_reports.py" search "public facilities authority" --type Performance
python3 -I "$S/lla_reports.py" parish Ascension --grep "Industrial|Port" --year 2026
python3 -I "$S/lla_reports.py" agencies "public facilities"
python3 -I "$S/lla_reports.py" agency "Louisiana Public Facilities Authority"
python3 -I "$S/lla_reports.py" new --type Performance
```

Every command takes `--limit N` (default 50 newest, `0` for all) and `--json`. `search`, `parish`, `agency` and `new` also take `--type`, `--year` and `--month`. `parish`, `agency` and `new` take `--grep`, a regex on the published name.

Exit codes: `0` rows found; `1` the site answered and nothing matched; `2` the site could not be read. Keep `1` and `2` apart in anything you write: `1` is "not found in this search", `2` is "not checked".

## Which command

| You have | Use | Note |
|---|---|---|
| A body's exact name | `agency` | Complete for that name. A body may have been renamed, so run `agencies` on one word too |
| Part of a body's name | `agencies`, then `agency` | `agency` needs the exact name, case aside |
| A parish | `parish`, narrowed with `--grep` or `--year` | Local bodies only; see below |
| A topic or program | `search`, with several wordings | Names only; see below |
| "What just came out" | `new` | The auditor's recent-releases feed |

## What the results can't tell you (checked 2026-11-03)

- **`search` does not read reports.** It requires every word to appear in a names field the auditor keeps for each report. `ITEP` and `payment in lieu` each return 0, while `Industrial Tax Exemption` finds the program audit. Try full names and synonyms, and treat 0 as "not in the names field". That field can hold more than the printed name, so a hit may show no search word.
- **Words match loosely.** `St. Charles` also returned a Lake Charles school, and `public facilities authority` returned 28 performance reports, most about something else. Read the names, and use `parish` for a parish or `agency` for a body.
- **`parish` is not everything that touches a parish.** The St. Charles list held only `Contracted` and `Investigative` rows: no statewide performance audits or state financial audits. Run `search` as well for a program or state agency.
- **The date is a posting date.** Reports loaded in bulk carry the load date: the March 2000 LPFA audit shows 2005-02-18, and many older rows show 2004. Cite the date printed on the report, and use `period` for the years covered.
- **There is no separate title field.** `title` is the published name, usually `Entity - Title` or only the entity. `entity` is the text before the first ` - `, which is sometimes wrong: "Jefferson Parish Volunteer Fire Department No. 1 - Marrero Estelle" gives the department without its location.
- **Types.** `--type` takes the auditor's categories: Actuarial, Advisory, Contracted, Data Analytics Medicaid, Executive, Financial, Investigative, Performance, Recovery. `Contracted` appears to mean work by outside CPAs, going by the rows seen, not by a definition from the auditor. The second part of a printed type (`Contracted / Audit`) comes from the feed as is. Some are bare codes such as `A`, `C` or `L`, whose meaning isn't established.
- **A missing report doesn't mean no audit was done.** It may not be posted yet, or may sit under another name. Say "not found in LLA reports as of <date>", never "no audit exists".
- **An audit reports what its scope covered.** An outside CPA's audit of a local body is not a finding by the Legislative Auditor. Name who did the work, as the report states it. For an old finding, ask about current practice, as `public-comment/postures/financing.md` does.

## When the site is down or changed

The script retries three times, then exits 2 and says so. It also exits 2 if a feed stops returning JSON, which is what a site redesign would look like. Then:

1. Open https://lla.la.gov/reports/audit-reports in a browser. It has All Reports, By Agency and By Parish tabs.
2. Run `WebSearch` limited to `lla.la.gov` for the entity or topic. This finds indexed PDFs only.
3. Try `bayou:web-history` on the report page if a known page has gone missing.
4. Ask the auditor directly for a specific report, using the contact details on its site. `bayou:la-public-records-request` drafts a request; the user sends it.
5. In the output, mark the search as not checked, with the date. Never report a failed search as no results.

If the script's feeds have changed, the report pages call them from their JavaScript. The three that matter, as of 2026-11-03: `publicreports.nsf/searchReportsJSON-V1.20`, `vwPRByParishJSON`, `vwPRByAgencyJSON`, all on `app.lla.la.gov`. The site's `robots.txt` didn't restrict them on that date. If a replacement needs a CAPTCHA or a login, stop and tell the user; don't try to get around it.

## Reading a report

`link` opens a short redirect page leading to the PDF, so `curl -L` alone saves the HTML page. Open the link in a browser, or follow the `href` in that page. `summary` links, where present, go to the auditor's short summary. Sizes vary: the 87-page LPFA audit is about 3.5 MB. Cite the report number and the page printed in the PDF. Use `bayou:document-ocr` if a report has no text layer.

## Related skills

- `bayou:itep-lookup` gives company-level incentive records. This skill finds the auditor's reviews of those programs.
- `bayou:la-bond-dockets` covers State Bond Commission and conduit-issuer dockets. Audits of an issuer or a parish Industrial Development Board come from here.
- `bayou:public-comment` takes these as outside facts. Name the auditor's report and page.
