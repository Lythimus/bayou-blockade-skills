---
name: la-power-map
description: Map who lobbies for and gives money on behalf of a Louisiana permit applicant — registered lobbyists and campaign contributions from the Louisiana Ethics Administration, plus ownership from an OpenCorporates first pass (status, registered agent, former names, home-state entity) and the manual path for Secretary of State business filings (officers and managers)
allowed-tools: Bash, Read, WebSearch, AskUserQuestion
---

# Louisiana Power Map

Answers three questions about a company seeking a permit, a tax exemption, or a rule change in Louisiana:

1. **Who lobbies for it?** Louisiana Ethics Administration lobbyist registrations (scripted).
2. **Who has it given money to?** Louisiana Ethics Administration e-filed campaign contributions (scripted).
3. **Who owns and runs it?** OpenCorporates' mirror of the Louisiana business registry first (scripted), then the Secretary of State filings themselves (manual: the search is reCAPTCHA-gated).

For the tax exemption itself (the ITEP, Quality Jobs or Enterprise Zone contract, the board vote, local recommendations), use `bayou:itep-lookup`.

This skill retrieves records. It does not conclude that a contribution bought a vote or that a lobbyist caused a decision. Report what was filed, by whom, and when, and let the user draw the line between a contribution and an official act.

## Parsing arguments

- **Company name** (required). Ask for the exact legal name on the permit application and any known parent, subsidiary, or former name. Run each as its own search: the applicant on an LDEQ permit is often an LLC whose name differs from the parent that hires the lobbyists (the registered client for Denka's LaPlace plant is "Denka Performance Elastomer (DPE)"). If the user has no former names to offer, run the Step 3 first pass before Steps 1 and 2: its `Previous Names` and `Branch` fields supply them (Luling Exchange LLC is now IMTT Luling LLC), and each one is another search term for lobbyists and contributions. The land itself is often held by a further entity. `bayou:parish-assessor-gis` (`at` on the site, or `owner` near it) gives the owner of record of the site parcels; search that name too. A tax agent printed "C/O" is not the owner.
- **Date range** (optional) for contributions, as `MM/DD/YYYY`.
- **Officials of interest** (optional): legislators, parish council members, or statewide officials whose filings should be picked out of the contribution results.

## Step 1: Registered lobbyists

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-power-map/ethics_search.py" lobbyists "Denka"
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-power-map/ethics_search.py" lobbyists "Denka" --past
```

Returns CSV: `company, paid, branch, lobbyist, dates_represented`. The match is a substring of the company name as the lobbyist typed it on the registration. `--past` adds representations that have ended. `branch` says where the lobbyist is registered to work: Legislative, Executive (state agencies, which includes LDEQ and the Department of Conservation and Energy), or Local.

Then, for each lobbyist found, search the lobbyist's other clients in the browser at `https://ethics.la.gov/LobbyistData/SearchByLobbyist.aspx`. A lobbyist shared with a trade association or with another applicant in the same parish is often the more useful finding.

What the registration does not show: how much the company pays the lobbyist, or which bill or permit was discussed. Lobbyist expenditure reports (`SearchByFinancialDisclosure.aspx`) list spending *on officials* such as meals and events, not fees received.

## Step 2: Campaign contributions

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/la-power-map/ethics_search.py" contributions "Entergy" --from 01/01/2026 > contributions.csv
```

Returns the portal's own CSV export: filer (the candidate or committee that *received* the money), report number, contributor name and address, contribution type, date, and amount. The total number of matching records and the number inside the date range are printed to stderr.

Read the results before reporting them:

- **The match is a substring, and it is loose.** A search for "Denka" returns MLADENKA and GUDENKAUF and no Denka contributions at all. A search for "Entergy" returns "ATMOS ENTERGY CORPORATION" (a filer's misspelling of Atmos Energy) and an unrelated "TCHEFUNCTE ENTERGY LLC". Filter the CSV to rows whose `ContributorName` is the company, its PAC, or a named officer, and say how many rows were dropped.
- **Most corporate money moves through a PAC.** Search the PAC by its own name ("ENPAC" for Entergy). The Ethics Administration's PAC list is at `https://ethics.la.gov/CampaignFinanceSearch/PACLists.aspx`. Contributor names are typed by each recipient's treasurer, so one PAC appears under several spellings; group them by address.
- **Executives give in their own names.** Search officers found in Step 3 individually, and match on address or employer before attributing a gift to the company. A common surname alone is not a match.
- **Zero rows is not zero giving.** Only electronically filed reports are searchable. Older and some local filings exist only as scanned PDFs (`SearchScanned.aspx`).
- `ContributionType` values other than `CONTRIB` (for example `OTHER`, a utility refund to a campaign) are not political gifts. Drop them or label them.

To see every contribution a specific official received, use the browser form at `https://www.ethics.la.gov/CampaignFinanceSearch/SearchEfilingContributors.aspx` and pick the filer.

## Step 3: Ownership and officers

### First pass: OpenCorporates mirror (scripted)

OpenCorporates republishes the Louisiana Secretary of State registry and serves it without a CAPTCHA or a login. Search by name, then read the detail page of each entity that is the applicant:

```bash
curl -sS -L --get --data-urlencode "q=Luling Exchange" https://opencorporates.com/companies/us_la \
  | grep -oE "Found [0-9,]+ companies|/companies/us_la/[^\"]+\" title=\"[^\"]*\""

curl -sS -L https://opencorporates.com/companies/us_la/45557942Q | python3 -c '
import html, re, sys
page = sys.stdin.read()
text = lambda s: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())
for dt, dd in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S):
    print(text(dt) + ": " + text(dd))'
```

The search prints the hit count and one line per entity with its company number and name. `Found 0 companies` and nothing else means no match. The search matches former names as well as current ones, which is how "Luling Exchange" finds IMTT LULING LLC, and it is loose: "Entergy" returns 82 entities, among them ADT Security Services. Only the first 30 are shown, so when the count is higher, search a longer piece of the legal name instead of paging.

What the detail page gives without a login:

- **Company Number**: the number to search by in the manual step below. Check that it is the charter number shown on the Secretary of State page before citing it as one.
- **Status** and **Company Type**. "(Non-Louisiana)" in the type marks a foreign entity.
- **Branch**: for a foreign entity, the home-state entity it is registered as a branch of, for example `Branch of LULING EXCHANGE LLC (Delaware (US))`. This names the entity and the state to look in for owners.
- **Registered Address**, **Agent Name**, and **Agent Address**.
- **Previous Names**. Feed each one back into Steps 1 and 2.
- **Directors / Officers**: the count only.

What it withholds (`Please log in to see this data`): officer and manager names, the incorporation date, and the date the record was last refreshed from the state. Because the refresh date is hidden, there is no way to tell how stale the mirror is. Treat status and agent as leads, and confirm them against the Secretary of State before they go into a comment letter.

Keep to one search page and one detail page per entity. The site's `robots.txt` disallows paged results (`?page=`) and the `/officers` and `/search` paths.

### Secretary of State (manual)

The Secretary of State's business search at `https://coraweb.sos.la.gov/commercialsearch/commercialsearch.aspx` sits behind Google reCAPTCHA. Do not try to script it. It is the only source here for officer and manager names, and the record that confirms what the first pass returned. Give the user this path and ask them to paste back or screenshot the detail page:

1. Open the URL, search by entity name or by the company number from the first pass, and solve the CAPTCHA.
2. Open the entity's detail page and record: charter number, entity type, status (Active / Not in good standing), domicile or home state, registered agent, and every officer or manager with an address.
3. For a foreign (out-of-state) LLC the Louisiana filing names only managers and an agent. The owners are on file, if anywhere, in the home state (often Delaware, which does not publish them). The first pass's `Branch` field names that home-state entity.

Other routes to the parent, all scriptable or already in this plugin:

- `/bayou:epa-tri-search`: each TRI facility record carries `parent_co_name`.
- `/bayou:doj-sec-search`: SEC EDGAR full-text search. A publicly traded parent lists its subsidiaries in Exhibit 21 of its 10-K, so searching the LLC's name there finds the parent.

## Dead ends

- **`ResultsByCompRep.aspx?SearchParams=RepName.{Name},` as a direct link.** The lobbyist form redirects to this URL, which looks bookmarkable. Requested without the session that made the search, it returns every registration on file (600+ pages) instead of the filtered set, with no error. `ethics_search.py` posts the form and exits with a message if it sees the unfiltered list.
- **Date boxes on the contribution form.** They are Telerik widgets whose state is assembled in the browser; posting the date text alone is ignored. The script applies the date range to the exported CSV instead.
- **Campaign-finance search page size.** The search page embeds every filer name and weighs about 2.5 MB with a 1.4 MB ViewState that must be posted back. A search takes 20 to 60 seconds. This is slow, not blocked.
- **OpenCorporates API without a token.** `https://api.opencorporates.com/v0.4/companies/search` returns 401 `Invalid Api Token` for an anonymous request (confirmed 2026-10-12). The website pages in Step 3 need no token.
- **Officer names from OpenCorporates.** The detail page shows how many officers are on file and puts the names behind a login. The Secretary of State page is the route to them.
- **Federal giving is not here.** Contributions to congressional candidates are filed with the FEC (`https://www.fec.gov/data/`), and federal lobbying with the Senate (`https://lda.senate.gov/`). Neither is wrapped by this skill.

## Presenting the results

1. **Lobbyists**: Company as registered | Lobbyist | Branch | Dates. Note which searches included past representations.
2. **Contributions**: Recipient | Contributor as written | Date | Amount | Report number, with a total per recipient. State the search terms, the date range, and how many returned rows were excluded as non-matches.
3. **Ownership**: the OpenCorporates fields, labeled as a mirror of the state registry, and separately what the user retrieved from the Secretary of State, or a statement that the state record was not retrieved. Say which fields were confirmed against the state record and which rest on the mirror alone.
4. Retrieval date for each source.

### Citation format

> **Louisiana Board of Ethics, Lobbyist Registration**, Denka Performance Elastomer (DPE), lobbyist Donelson T. Caffery III, Legislative and Executive, registered 03/21/2024 to present, source: [Lobbyist Data Search](https://ethics.la.gov/LobbyistData/SearchByCompRep.aspx) (retrieved 2026-10-11).
>
> **Louisiana Board of Ethics, Campaign Finance Report** LA-133486 (Form 202), New Orleans Hospitality Coalition PAC, contribution of $104.00 from Entergy Corporation dated 03/13/2026, source: [Campaign Finance Search](https://www.ethics.la.gov/CampaignFinanceSearch/SearchEfilingContributors.aspx) (retrieved 2026-10-11).
>
> **OpenCorporates, mirror of the Louisiana Secretary of State business registry**, IMTT Luling LLC (formerly Luling Exchange LLC), company number 45557942Q, Limited Liability Company (Non-Louisiana), Active In Good Standing, branch of Luling Exchange LLC (Delaware), registered agent C T Corporation System, source: [OpenCorporates](https://opencorporates.com/companies/us_la/45557942Q) (retrieved 2026-10-12; not confirmed against the Secretary of State record).

$ARGUMENTS
