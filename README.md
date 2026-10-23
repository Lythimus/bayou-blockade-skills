# Bayou Blockade — Claude Code Plugin

A Claude Code plugin for **environmental-justice research and permit-application
interrogation** in Louisiana and at the federal level.

It bundles two things:

1. **`/bayou:permit-analysis`** — a multi-step pipeline that reads OCRed permit
   applications, interrogates them against a curated question bank, and produces a
   provenance-cited findings report you can build a public comment on top of.
2. **60+ research skills** — thin, documented wrappers over the public data sources
   that fenceline-community work actually depends on: LDEQ EDMS, EPA ECHO/TRI/CAMPD,
   PACER/CourtListener, OSHA, PHMSA, USACE, FEMA, CPRA, NASA FIRMS, USGS/NOAA water
   data, the Federal Register, FAA/ADS-B flight records, and more.

Each skill exists because the underlying portal is hostile to research — CAPTCHAs,
undocumented ArcGIS endpoints, decommissioned domains with live backing services,
scanned image-only PDFs. The `SKILL.md` files record what actually works, including
the dead ends.

**This is not legal advice, and no output here is filing-ready on its own.**
`permit-analysis` and `public-comment` produce drafts with provenance citations —
every citation still needs to be checked against the source document, and every
draft against your own judgment, before anything is submitted to a regulator.

## Requirements & compatibility

Built and tested against **Claude Code only**. Almost every skill here declares
`Bash` in its tool permissions because it shells out to `curl`/`python` for direct
API calls, and several depend on Claude-Code-specific primitives that a chat
interface doesn't expose: headful Playwright browser automation for CAPTCHA-gated
portals (`ldeq-edms-download`, `sonris-session`), SSH to a separate OCR box or a
local `conda` environment (`document-ocr`), and cron-based recurring jobs
(`exec-travel-monitor`). Claude Code itself requires a Claude subscription (Pro or
higher) or Claude Developer Platform (API) billing.

Claude.ai has its own, separate Agent Skills feature (Pro/Max/Team/Enterprise —
not available on the Free plan) using the same `SKILL.md` format, but its hosted
skill-execution sandbox doesn't give a skill the same shell-plus-network access
Claude Code's Bash tool does. Because of that, none of the skills in this repo are
turnkey-portable to Claude.ai as-is — the exceptions are the two writing-style
skills, `toxic-truth-teller-style` and `ej-comment-style`, which have no tool
requirements and work anywhere Agent Skills are supported. (`ej-comment-style`
cross-references a few other skills in this repo for source-gathering and citation
checking; those pointers go dead off Claude Code, but the style guidance itself
does not depend on them.) If you want data-lookup skills that run natively as MCP
servers instead (Claude.ai, Claude Code, or any MCP client), see the "Overlapping
MCP servers" note under Skills below.

## Install

This repo is itself a plugin marketplace. From inside Claude Code:

```
/plugin marketplace add Lythimus/bayou-blockade-skills
/plugin install bayou@bayou
```

### Alternative: local directory (for development on the plugin itself)

In `~/.claude/settings.json`:

```json
{
  "enabledPlugins": { "bayou@local": true },
  "extraKnownMarketplaces": {
    "local": { "source": { "source": "directory", "path": "/Users/you/.claude/plugins" } }
  }
}
```

Clone this repo to `~/.claude/plugins/bayou` (the directory name must be `bayou`, to
match `name` in [.claude-plugin/plugin.json](.claude-plugin/plugin.json)), then restart
Claude Code.

Some skills need per-machine setup that is **deliberately not in this repo**:

- **API keys** live in `~/.claude/bayou-credentials.md` — deliberately *outside* this
  repo, so a stray `git add -A` cannot commit them. Copy
  [bayou-credentials.example.md](bayou-credentials.example.md) there and fill it in.
  Every entry is optional; skills that need a key say so and fail with a clear message
  when it is missing, and most skills need no credentials at all.
- **Personal profile** for `nextdoor-campaign`, `public-comment`, and `hearing-prep` lives at
  `~/.claude/bayou-profile.md` — same reasoning as credentials, but for personal narrative
  material (health, exposure, ancestral ties, parish reach) instead of API keys. Copy
  [skills/nextdoor-campaign/profile.example.md](skills/nextdoor-campaign/profile.example.md)
  there and fill it in. `public-comment` uses it to establish standing or interest. For a
  permit it is a **standing gate**: family presence inside the permit's covered parishes is
  what makes the commenter an "aggrieved person" under La. R.S. 30:2050.21, and therefore what
  preserves the right to appeal. For a rulemaking or a bond hearing, it supplies an interest
  statement instead, and the LDEQ appeal statute is never cited.
- **Watchlist** for `exec-travel-monitor` lives at
  `~/.claude/bayou-exec-travel-watchlist.json` — same reasoning again, since a real
  watchlist is per-investigation data (real companies, tail numbers, research notes).
  Copy [skills/exec-travel-monitor/watchlist.example.json](skills/exec-travel-monitor/watchlist.example.json)
  there and fill it in.
- **Node dependencies** — `skills/ldeq-permit-status/`, `skills/ldeq-edms-download/` and
  `skills/epa-webfire-reports/` each need `npm install` (Playwright).
- **Bulk datasets** — `skills/aircraft-registry-lookup/` downloads the FAA releasable
  registry into its own `cache/` on first use.
- **OCR** — `/bayou:document-ocr` runs Surya locally (`surya_ocr` on `PATH`, or a `conda` env) for
  geometry, plus one of two independent VLM readers for cross-checked reading order:
  `OCR_BACKEND=remote` (default) runs the readers on a separate GPU box over SSH — set
  `OCR_SSH_HOST`/`OCR_REMOTE_ROOT` in `~/.claude/bayou-credentials.md` and provision it per
  `skills/document-ocr/references/remote-setup.md`; `OCR_BACKEND=local` runs
  [MinerU](https://github.com/opendatalab/MinerU) in its own `conda` env on the same machine as
  Surya instead. Optional `--azure` escalation needs an Azure Document Intelligence key (see
  `bayou-credentials.example.md`) and bills per page.

## The permit-analysis pipeline

`/bayou:permit-analysis <doc.txt> [up to 4 docs] [--project-info <path>]`

1. **Classify** the project — regulator, permit type, process (`landfill`, `CCS`,
   `gas-power`, …), applicant, location.
2. **Select** applicable questions from `questions/question-bank.csv`, plus the
   cross-cutting groups (applicant history, EJ/cumulative impact, public process,
   emergency/safety, climate resilience) that always apply.
3. **Draft bespoke questions** for this specific project, modeled on the real
   questions from prior campaigns in `questions/exemplars.csv` (River Birch,
   Waterford 5 & 6).
4. **Review gate** — you approve the question set before any analysis runs.
5. **Extract** — Haiku `bayou:permit-extractor` subagents sweep the documents and
   return claimed citations, explicitly marked *unverified*. `bayou:permit-websearch`
   subagents chase down external follow-ups.
6. **Verify** — the orchestrator checks every claimed citation against the source text
   and assigns accuracy/relevance flags. Extraction and judgment are separated on
   purpose: the retrieval agents are forbidden from drawing conclusions.

Output is a numbered section set under `verification/` with document-level provenance
(`<file>.txt:<line>`), a findings report, and a research to-do list. For an air permit it
also writes `verification/proposed-emissions.csv`, which `/bayou:tri-release-report`
layers onto the existing TRI releases within a radius to chart cumulative burden, and
`/bayou:comparable-facilities` sets against the reported emissions of industry peers.

Feed it machine-readable text. Raw agency PDFs are usually scanned images — run
`/bayou:document-ocr <in-dir> <out-dir>` first.

## Skills

**Overlapping MCP servers.** A few of these skills cover ground that a general-purpose MCP
server already serves: [`envirofacts-mcp`][envirofacts-mcp] (marked ¹ below) wraps the same EPA
Envirofacts tables, and [`nepa-mcp`][nepa-mcp] (marked ²) is a broader NEPA-screening toolkit
across federal GIS layers. Neither does the Louisiana portal navigation, the
OCR-to-verified-citation pipeline, or the comment drafting. When to use them, and how to
install them, is under [External skills and MCP servers](#external-skills-and-mcp-servers).

[envirofacts-mcp]: https://github.com/zachegner/envirofacts-mcp
[nepa-mcp]: https://github.com/pnnl/nepa-mcp

**Louisiana agencies**
| Skill | What it does |
|---|---|
| `ldeq-ai-lookup` | Company name → LDEQ EDMS Agency Interest (AI) number |
| `ldeq-edms-search` | Search EDMS documents by AI number, with filtering |
| `ldeq-edms-download` | Actually download EDMS files — drives a headful browser so you can solve the CAPTCHA |
| `ldeq-permit-status` | Current permit type, activity number, issued/effective/expiration dates |
| `la-comment-calendar` | Open LDEQ draft-permit comment periods and Louisiana Register rulemaking notices |
| `lac33-search` | Louisiana Administrative Code Title 33 by section or keyword |
| `la-rs-search` | Louisiana Revised Statutes by R.S. number or keyword |
| `lpsc-dockets` | Louisiana Public Service Commission dockets and orders |
| `itep-lookup` | LED incentives (ITEP, Quality Jobs, Enterprise Zone, Restoration Tax Abatement) from the FastLane public report and Board of Commerce & Industry agendas and transcripts; promised against reported jobs, payroll and investment; compliance and board votes |
| `la-bond-dockets` | State Bond Commission agenda dockets (docket, item, issuer, par, Volume Cap) and minutes outcomes; LPFA TEFRA notices and board agendas; Port of South Louisiana, Port NOLA, Port of Greater Baton Rouge, and Ascension Parish IDB agendas |
| `la-court-opinions` | Louisiana Supreme Court and Court of Appeal opinions (First Circuit index for LDEQ permit appeals, CourtListener for the rest): search, decision date/disposition/rehearing actions from the PDF, pin-page lookup, citation verification with writ history and stated coverage gaps; DAL hearing docket (DEQ/DCE/DENR) and Ethics decisions |
| `parish-assessor-gis` | Parish parcel at a point or address, owner of record with source vintage, zoning districts, merged project footprint (GeoJSON), and nearest homes and residentially zoned parcels measured from the fenceline (St. Charles, Ascension, St. James) |
| `ldeq-eric-emissions` | LDEQ ERIC state emissions inventory by AI: annual certified criteria pollutants and LAC 33:III Ch. 51 toxic air pollutants 1991–present, release-point actual emissions with stack parameters, current TEMPO permitted rates, parish totals, Louisiana same-NAICS peer rankings |
| `ferc-elibrary` | FERC eLibrary dockets (CP pipeline and LNG certificates, PF pre-filing, RP/ER rates, P- hydro): filings, EIS/EA volumes, Commission and delegated orders, notices opening comment or intervention periods, intervention movants with oppositions and late grants, public PDF download with CEII/privileged request routes |
| `ldeq-lelap-labs` | LDEQ LELAP lab accreditation (LAC 33:I Subpart 3): current scopes by lab, matrix, method and analyte; which labs hold a method; whether a lab was accredited for an analysis on a past sample date, from its EDMS certificates, amendments and suspension notices |
| `parish-council-agendas` | Parish council and planning/zoning commission agendas and minutes, with keyword alerts for rezonings, special and conditional uses, variances, industrial uses, road/servitude and property actions, and inducement/PILOT/CEA/ITEP items; case tracking from P&Z to council ordinance with hearing dates (St. Charles Legistar, Ascension CivicClerk; East Baton Rouge, Plaquemines, St. Bernard CivicPlus; St. James and Assumption scanned PDFs via OCR) |
| `la-state-lands` | State Land Office water-bottom claims (state claimed, dual claimed, judgment against the state, title-file index), state-owned land, WMAs and refuges; OSTR (formerly OMR) mineral leases, operating agreements, State Agency Leases and lease-sale history; every SMEB CO2 storage operating agreement (CS number → operator, resolution, stated vs mapped acres, parishes); Class VI AoR overlap with state pore space (CVI-002); current SMEB agenda figures and sequestration items (public SONRIS GIS, no login) |
| `ldh-drinking-water` | Louisiana public drinking water near an injection well or outfall: public-supply wells near a point or inside a Class VI AoR with the LDEQ SWAP default protection radius (CVI-008); surface intakes downstream of a discharge by USGS NLDI flow trace, with flow km, the SWAP 5-mile critical area, the Mississippi corridor rule and the Bayou Lafourche diversion intakes, and population served including buyers; per-system LDH status (unresolved violations and deficiencies, next sanitary survey), federal SDWIS violations (both Envirofacts tables) and lead/copper 90th percentiles; LDH chemical/coliform/lead-copper results, state violations (boil advisories) and sanitary surveys captured from a visible browser after a user-solved reCAPTCHA, year by year to stay under LDH's 5,000-result cut-off (`dww_capture.js`) |
| `cpra-master-plan` | CPRA 2023 Coastal Master Plan projects, land-change and flood-risk data |
| `la-species-cultural-review` | LDWF rare/T&E species lists, project-review request, NMFS/FWS listed species at a point, coastal waterbird nesting colonies (nest counts, aerial imagery), NRHP search, tribes with a consultation interest in the parish — the ESA/Section 106 bundle ² |
| `slfpaw-geotechnical` | SLFPA-W soil borings, piezometers, cross-sections via the USACE National Levee Database ² |
| `sonris-session` | Establish/check the SONRIS CAPTCHA session cookie other sonris-* skills need (headful solve, ~7-day validity) |
| `sonris-operator-lookup` | Company name → SONRIS operator code (wells, injection, coastal, mineral-lease filings — not just O&G) |
| `sonris-well-lookup` | Find a well by serial/name/field or by parish/section-township-range/lat-lon |
| `sonris-doc-search` | Search and bulk-download SONRIS documents (permits, orders, applications) by operator/well/parish/doctype |
| `la-class-vi` | Louisiana Class VI/CCS program tracker — application status, issued permits, no CAPTCHA session needed |
| `la-public-records-request` | Draft (never send) a Louisiana Public Records Act request to LDEQ, a parish, or another custodian, with deadlines and fee language quoted from the current statute |
| `la-power-map` | Who lobbies for and gives money on behalf of an applicant — Louisiana Ethics lobbyist registrations and campaign contributions; OpenCorporates first pass on ownership, GLEIF and SEC Exhibit 21 parent/subsidiary resolution, then the manual path for Secretary of State filings; writes a sourced per-case `ENTITIES.md` ownership map |
| `web-history` | What a company or project website said, and when — every distinct Wayback Machine version of a page or site section, text extraction, diffs between versions, and a phrase or number (jobs, emissions, owner name) tracked across years. Read-only |
| `la-coastal-use-permits` | Coastal use permits by parish/applicant from OCM status reports, current OCM notices, and St. Charles LCP legals; CUP number → site via SONRIS |

**Federal environmental & enforcement**
| Skill | What it does |
|---|---|
| `epa-echo-search` | Facility compliance/enforcement history (CAA, CWA, RCRA, SDWA) ¹ |
| `cwa-watershed-context` | Receiving-water context for an NPDES/LPDES permit — HUC12/HUC8, 303(d) causes, TMDLs and wasteload allocations (ATTAINS, needs API key), watershed dischargers ranked by calculated load and exceedances, the applicant's limits and multi-year loads |
| `epa-tri-search` | Toxics Release Inventory — year-over-year releases by medium and carcinogen status ¹ |
| `chemical-hazard-profile` | CAS number, name, or TRI chemical list → GHS hazard statements and IARC cancer group (PubChem), plus EPA cancer calls and IRIS values (CompTox, optional key) |
| `tri-release-report` | TRI release reports and campaign charts — one facility's multi-year history (permit renewal), or every facility within a radius plus a proposed facility's permitted emissions; social (1080×1080, 1080×1350) and print PNG/PDF charts. Needs `uv` |
| `comparable-facilities` | Peer benchmark for a repermit — finds active facilities with the same SIC/NAICS codes (state, then EPA region, then national), sizes them by GHGRP CO2e plus stated capacity, and compares NEI/GHGRP emissions and the proposed permit limits; REPORT.md, CSV, and social/print charts. Needs `uv` |
| `household-exposure` | One Louisiana home's exposure to industrial air toxics — EPA RSEI modeled concentrations over each person's years at the address (screening cancer risk, hazard index by organ), plus what a proposed facility could add from an AERMOD run on the applicant's own modeling files; private and address-withheld public REPORT.md, CSV, charts and manifest. Needs `uv`; the proposed-facility tier needs `gfortran`. Large downloads (1–22 GB per year, streamed) are confirmed first |
| `epa-frs-crosswalk` | Resolve a facility to its FRS registry ID and every program ID it holds (TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP, LA-TEMPO) |
| `epa-webfire-reports` | NESHAP/NSPS compliance reports filed through CEDRI and published in WebFIRE — periodic/excess-emissions reports (flare root-cause analyses, LDAR, PRD releases), performance tests, NOCS |
| `epa-ghgrp-search` | Greenhouse Gas Reporting Program — facility CO2e emissions by subpart and gas |
| `epa-rcra-waste` | RCRA Biennial Report — self-reported hazardous waste generation tonnage by cycle and waste type ¹ |
| `epa-campd-search` | Clean Air Markets emissions, unit compliance, allowances (needs API key) |
| `ejscreen-report` | EJScreen indicators, via the ArcGIS layer still backing EPA's own portal |
| `federal-register-search` | Notices, proposed rules, open comment deadlines; regulations.gov dockets, documents and comments (MARAD deepwater ports, USCG waterway suitability assessments) |
| `csb-nrc-hazmat` | USCG National Response Center spill and release reports from the yearly FOIA workbooks (1990 to date; by parish, company aliases, material or radius; per-report detail and summaries), CSB investigations with every recommendation and its status, and CSB Accidental Release Events under 40 CFR 1604 (2020 on) with incident-report PDFs. Confirms before multi-file NRC downloads. Needs `uv` |
| `epa-rmp-lookup` | EPA Risk Management Plans (CAA 112(r)) from the Data Liberation Project's FOIA'd copy: regulated substances and quantities by process, program levels, prevention program, emergency response, executive summary, and an all-time deduplicated accident history; facilities by name or radius; FRS crosswalk. Worst-case (OCA) data is reading-room only and stated as such. Needs `uv` |
| `osha-inspections` | OSHA inspections, violations, citations |
| `doj-sec-search` | DOJ ENRD press releases + SEC EDGAR full-text (investor-disclosed liabilities) |
| `pacer-case-search` | Free CourtListener/RECAP first, paid PACER only on confirmation |
| `nrc-adams-search` | Nuclear Regulatory Commission ADAMS documents |
| `usace-408-permits` | Section 408 permissions and Corps regulatory permits (ORM-Public, MVN public notices via a browser tab) ² |
| `phmsa-npms-search` | Pipelines near a facility, plus incident and enforcement history |
| `fema-flood` | openFEMA NFIP claims, policies, disaster declarations |

**Geospatial, environmental & forensic**
| Skill | What it does |
|---|---|
| `facility-coordinates` | Facility name → lat/lon via EPA ECHO |
| `geo-distance` | Straight-line distance between addresses, place names, or coordinates |
| `satellite-imagery` | Free imagery for a place and date, auto-selecting the best source |
| `firms-active-fire` | NASA FIRMS active-fire detections with fire radiative power and overpass timestamps ² |
| `wind-history` | Forensic wind direction/speed — did the plume reach this receptor? Optional vertical profile (KSIL radiosonde, Open-Meteo levels) for a sound-refraction screen |
| `lf-acoustic-baselines` | Archived infrasound (BDF) and seismic spectra near a point from EarthScope: station epochs and instrument changes, MUSTANG and miniSEED PSDs, season-matched before/after peak comparison, infrasound↔seismic coherence, ComCat events |
| `lf-source-locate` | Bearing inference for a low-frequency tonal at one infrasound site: wind-conditioned bearing posterior and arc with permutation test, ERIC release points ranked against it, hourly features CSV seam; 2011–12 TA arrival-time locator for impulsive events with picks CSV seam (cross-spectral bearing and `tdoa` failed validation, diagnostic only) |
| `usgs-water-data` | Nearby gauges, discharge/gage-height/water-quality, NOAA flood forecast ² |
| `dot-geo-search` | USDOT ArcGIS layers — pipelines, airports, railroads |
| `dot-datahub-search` | USDOT Socrata catalog + SODA queries |

**Aviation / accountability**
| Skill | What it does |
|---|---|
| `aircraft-registry-lookup` | Owner name → tail number, ICAO24 hex, type (FAA registry + foreign fallbacks) |
| `adsb-flight-search` | Historical flights for an aircraft or airport window (OpenSky, ADSB Exchange fallback) |
| `exec-travel-monitor` | Watchlist of company aircraft → arrivals at capitals, flagged EXPLAINED vs. unexplained |

**Utilities**
| Skill | What it does |
|---|---|
| `permit-analysis` | The pipeline above |
| [`environmental-data-audit`](skills/environmental-data-audit/SKILL.md) | Assess whether existing environmental data support a claim; cited limitations, defensible wording, targeted next steps, and proportional evidence retention. Runs on request or when a material limitation could change a finding; not a mandatory lookup or pipeline stage |
| `public-comment` | Findings report or research memo + profile → a filed-ready public comment. Covers three postures: a permit or license, a rulemaking, and a public financing approval such as a TEFRA bond hearing. Includes standing/interest, numbered requests, a candor section, and an optional styled PDF. *Renamed from `permit-comment` in 1.9.0: use `/bayou:public-comment`.* |
| `hearing-prep` | In-person engagements. Three modes: questions grouped by the staffer likely to field them, a 2–3 minute oral version of a filed comment, and a debrief of a meeting transcript against the written record |
| `document-ocr` | Multi-backend OCR (Surya geometry + olmOCR/Chandra/MinerU readers, optional Azure) for a folder or single scanned PDF, with per-line confidence and cross-reader agreement |
| `ocr-verify` | Resolve one OCR-contested value with evidence — every backend's opinion, a cross-package tally, a rendered crop when needed |
| `ocr-validate` | Cheap mechanical pre-pass over an OCRed permit package — flags unit/subtotal/plausibility/date issues, each pointing at a runnable `ocr-verify` command |
| `toxic-truth-teller-style` | Writing style for fenceline-community campaign material (invoke by name) |
| `ej-comment-style` | Writing style for the filed administrative comment itself — register, structure, and the argumentative moves from four successful Louisiana permit comments, with verbatim samples (invoke by name) |
| `kit-dissemination` | Draft (never auto-send) Kit.com email broadcasts — case updates, calls for community testimony |
| `nextdoor-campaign` | Research + profile → dated Nextdoor post series, one audience archetype per post, paced to a comment/hearing deadline |
| `ej-meme` | Research → a few sourced, plain-language memes (one "bum deal" each), template picked by rhetorical move, with pre-render lint, a review pause, and phone-width legibility QA; also re-renders old meme CSVs |

## External skills and MCP servers

Some work this plugin does not do is already done well by third-party tools. They are not
bundled and not installed by this plugin. This section says when each is worth reaching for
and gives an install command Claude Code can run.

**Rules for an agent reading this:**

1. Check whether the tool is already present before suggesting it: `claude mcp list` for MCP
   servers, the session's skill list for skills.
2. These are third-party and unaudited by this project. Ask the user before installing
   anything, and say what will be installed and from where.
3. If the user agrees and a shell is available, run `install`. Otherwise print the command for
   the user to run.
4. If `user_action` is set, stop and give the user that instruction first. It covers things an
   agent cannot or should not do alone: obtaining an API key, cloning and starting a server.
5. Install one named skill at a time (`--skill <name>`), never a whole repository. The
   journalism repository below holds about 60 skills, including one that tells the agent to
   invoke it before every response.
6. After installing, tell the user to restart Claude Code; new skills and servers load at
   startup.

| Tool | Use it when |
|---|---|
| `web-archiving` skill | Saving many cited web pages to the Wayback Machine and Archive.today before filing or publishing. `public-comment` handles the single-page case itself |
| `internet-archive` MCP | An agency page or dataset was removed and an earlier capture is needed (read-only: finds and fetches snapshots, does not save new ones). Optional: `web-history` lists, extracts and diffs archived versions without it |
| `foia-requests` skill | Drafting a *federal* FOIA request (EPA, the Corps, PHMSA), tracking it, or appealing a denial. Its template is written for a reporter: replace the outlet and "representative of the news media" language unless the requester is one, and keep the public-interest fee waiver. Louisiana requests use `la-public-records-request` |
| `pubchem` MCP | Chemical properties and identifiers beyond the hazard statements `chemical-hazard-profile` returns |
| `comptox` MCP | Exploring EPA toxicity values, exposure and bioactivity data in depth. `chemical-hazard-profile` covers the cancer call and IRIS values |
| `envirofacts-mcp` | A standing server for the EPA lookups marked ¹, in a client where this plugin's Bash-based skills cannot run |
| `nepa-mcp` | NEPA screening across federal GIS layers; overlaps the skills marked ² |

```json
[
  {
    "id": "web-archiving",
    "kind": "skill",
    "source": "https://github.com/jamditis/claude-skills-journalism",
    "license": "MIT",
    "install": "npx -y skills@latest add jamditis/claude-skills-journalism --skill web-archiving --agent claude-code -g -y",
    "user_action": null
  },
  {
    "id": "foia-requests",
    "kind": "skill",
    "source": "https://github.com/jamditis/claude-skills-journalism",
    "license": "MIT",
    "install": "npx -y skills@latest add jamditis/claude-skills-journalism --skill foia-requests --agent claude-code -g -y",
    "user_action": null
  },
  {
    "id": "internet-archive",
    "kind": "mcp",
    "source": "https://github.com/cyanheads/internet-archive-mcp-server",
    "license": "Apache-2.0",
    "install": "claude mcp add -s user internet-archive -e MCP_TRANSPORT_TYPE=stdio -- npx -y @cyanheads/internet-archive-mcp-server@latest",
    "user_action": null
  },
  {
    "id": "pubchem",
    "kind": "mcp",
    "source": "https://github.com/cyanheads/pubchem-mcp-server",
    "license": "Apache-2.0",
    "install": "claude mcp add -s user pubchem -e MCP_TRANSPORT_TYPE=stdio -- npx -y @cyanheads/pubchem-mcp-server@latest",
    "user_action": null
  },
  {
    "id": "comptox",
    "kind": "mcp",
    "source": "https://github.com/ToxMCP/comptox-mcp",
    "license": "Apache-2.0",
    "install": "claude mcp add -s user --transport http comptox http://localhost:8000/mcp",
    "user_action": "Get a free API key by emailing ccte_api@epa.gov. Then: git clone https://github.com/ToxMCP/comptox-mcp.git && cd comptox-mcp && pip install -e . && cp .env.example .env, set CTX_API_KEY in .env, and start the server with: uvicorn epacomp_tox.transport.websocket:app --host 127.0.0.1 --port 8000. The server must be running whenever the tool is used."
  },
  {
    "id": "envirofacts-mcp",
    "kind": "mcp",
    "source": "https://github.com/zachegner/envirofacts-mcp",
    "license": "MIT",
    "install": "claude mcp add -s user epa-envirofacts -- uv --directory <ABSOLUTE_PATH_TO_CLONE> run python server.py",
    "user_action": "Not published as a package. Install uv, then: git clone https://github.com/zachegner/envirofacts-mcp && cd envirofacts-mcp && uv sync. Substitute the clone's absolute path in the install command."
  },
  {
    "id": "nepa-mcp",
    "kind": "mcp",
    "source": "https://github.com/pnnl/nepa-mcp",
    "license": "BSD-3-Clause",
    "install": "pipx install nepa-mcp && nepa-mcp doctor && nepa-mcp configure claude",
    "user_action": "Needs pipx and Python 3.12 or newer. `configure claude` writes the server entries into the current directory's project configuration, so run it from the project where the tools are wanted."
  }
]
```

Commands were checked against each project's README and the `skills` and `claude mcp` command
help on 2026-10-11; none was installed or run as part of writing this section. Not listed, by
decision: a LittleSis MCP server (unmaintained since 2025, and unverified), and FracFocus and
EJScreen wrappers with one or two users each.

## Layout

```
.claude-plugin/plugin.json   plugin manifest
agents/                      permit-extractor, permit-websearch (subagents)
skills/<name>/SKILL.md       one skill per directory; bundled data alongside
```

## Conventions

- A skill's `SKILL.md` is the contract. Document the endpoint, the auth requirement,
  the argument parsing, and the failure modes — including sources you tried that are
  dead, and why you concluded they were dead rather than blocked locally.
- Before writing a new skill, check whether one already exists. Search
  [claudemarketplaces.com](https://claudemarketplaces.com) (skills, plugins, and MCP
  servers; `https://claudemarketplaces.com/search?q=<term>` is server-rendered, so `curl`
  works, but matching is fuzzy and rare terms return unrelated listings) and run
  `npx skills find <term>`.
- Keep retrieval separate from judgment. Extractor agents cite; the orchestrator rules.
- Never commit credentials, browser profiles, or bulk downloaded datasets.
