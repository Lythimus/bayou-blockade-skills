# Bayou Blockade — Claude Code Plugin

A Claude Code plugin for **environmental-justice research and permit-application
interrogation** in Louisiana and at the federal level.

It bundles two things:

1. **`/bayou:permit-analysis`** — a multi-step pipeline that reads OCRed permit
   applications, interrogates them against a curated question bank, and produces a
   provenance-cited findings report you can build a public comment on top of.
2. **~38 research skills** — thin, documented wrappers over the public data sources
   that fenceline-community work actually depends on: LDEQ EDMS, EPA ECHO/TRI/CAMPD,
   PACER/CourtListener, OSHA, PHMSA, USACE, FEMA, CPRA, NASA FIRMS, USGS/NOAA water
   data, the Federal Register, FAA/ADS-B flight records, and more.

Each skill exists because the underlying portal is hostile to research — CAPTCHAs,
undocumented ArcGIS endpoints, decommissioned domains with live backing services,
scanned image-only PDFs. The `SKILL.md` files record what actually works, including
the dead ends.

**This is not legal advice, and no output here is filing-ready on its own.**
`permit-analysis` and `permit-comment` produce drafts with provenance citations —
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
turnkey-portable to Claude.ai as-is — the one exception is `toxic-truth-teller-style`,
a pure writing-style skill with no tool requirements, which works anywhere Agent
Skills are supported. If you want data-lookup skills that run natively as MCP
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
- **Personal profile** for `nextdoor-campaign` and `permit-comment` lives at
  `~/.claude/bayou-profile.md` — same reasoning as credentials, but for personal narrative
  material (health, exposure, ancestral ties, parish reach) instead of API keys. Copy
  [skills/nextdoor-campaign/profile.example.md](skills/nextdoor-campaign/profile.example.md)
  there and fill it in. `permit-comment` treats it as a **standing gate**: family presence
  inside a permit's covered parishes is what makes the commenter an "aggrieved person"
  under La. R.S. 30:2050.21, and therefore what preserves the right to appeal.
- **Watchlist** for `exec-travel-monitor` lives at
  `~/.claude/bayou-exec-travel-watchlist.json` — same reasoning again, since a real
  watchlist is per-investigation data (real companies, tail numbers, research notes).
  Copy [skills/exec-travel-monitor/watchlist.example.json](skills/exec-travel-monitor/watchlist.example.json)
  there and fill it in.
- **Node dependencies** — `skills/ldeq-permit-status/` and `skills/ldeq-edms-download/`
  each need `npm install` (Playwright).
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
(`<file>.txt:<line>`), a findings report, and a research to-do list.

Feed it machine-readable text. Raw agency PDFs are usually scanned images — run
`/bayou:document-ocr <in-dir> <out-dir>` first.

## Skills

**Overlapping MCP servers.** A couple of these skills cover ground that a
general-purpose MCP server already serves, if you'd rather connect to a
standing server than install this whole plugin: [`envirofacts-mcp`][envirofacts-mcp]
(marked ¹ below) wraps the same EPA Envirofacts tables — ECHO, TRI, RCRAInfo,
and others; [`nepa-mcp`][nepa-mcp] (marked ²) is a much broader NEPA-screening
toolkit spanning ~13 federal agencies' GIS/data layers, including USACE, USGS,
USFWS, and NIFC. Neither does the Louisiana-agency-specific portal navigation
(CAPTCHA handling, undocumented endpoints), the OCR-to-verified-citation
pipeline, or the comment-drafting half of what's here — they're a substitute
for the individual federal data-lookup skills only, not for the pipeline.

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
| `itep-lookup` | Industrial Tax Exemption Program awards and applications |
| `cpra-master-plan` | CPRA 2023 Coastal Master Plan projects, land-change and flood-risk data |
| `la-species-cultural-review` | LDWF rare/T&E species lists, project-review request, NRHP search — the ESA/Section 106 bundle ² |
| `slfpaw-geotechnical` | SLFPA-W soil borings, piezometers, cross-sections via the USACE National Levee Database ² |
| `sonris-session` | Establish/check the SONRIS CAPTCHA session cookie other sonris-* skills need (headful solve, ~7-day validity) |
| `sonris-operator-lookup` | Company name → SONRIS operator code (wells, injection, coastal, mineral-lease filings — not just O&G) |
| `sonris-well-lookup` | Find a well by serial/name/field or by parish/section-township-range/lat-lon |
| `sonris-doc-search` | Search and bulk-download SONRIS documents (permits, orders, applications) by operator/well/parish/doctype |
| `la-class-vi` | Louisiana Class VI/CCS program tracker — application status, issued permits, no CAPTCHA session needed |

**Federal environmental & enforcement**
| Skill | What it does |
|---|---|
| `epa-echo-search` | Facility compliance/enforcement history (CAA, CWA, RCRA, SDWA) ¹ |
| `epa-tri-search` | Toxics Release Inventory — year-over-year releases by medium and carcinogen status ¹ |
| `epa-frs-crosswalk` | Resolve a facility to its FRS registry ID and every program ID it holds (TRI, NPDES, RCRAInfo, AIRS/AFS, GHGRP, LA-TEMPO) |
| `epa-ghgrp-search` | Greenhouse Gas Reporting Program — facility CO2e emissions by subpart and gas |
| `epa-rcra-waste` | RCRA Biennial Report — self-reported hazardous waste generation tonnage by cycle and waste type ¹ |
| `epa-campd-search` | Clean Air Markets emissions, unit compliance, allowances (needs API key) |
| `ejscreen-report` | EJScreen indicators, via the ArcGIS layer still backing EPA's own portal |
| `federal-register-search` | Notices, proposed rules, open comment deadlines |
| `csb-nrc-hazmat` | CSB investigations + USCG National Response Center release reports |
| `osha-inspections` | OSHA inspections, violations, citations |
| `doj-sec-search` | DOJ ENRD press releases + SEC EDGAR full-text (investor-disclosed liabilities) |
| `pacer-case-search` | Free CourtListener/RECAP first, paid PACER only on confirmation |
| `nrc-adams-search` | Nuclear Regulatory Commission ADAMS documents |
| `usace-408-permits` | Section 408 permissions and Corps regulatory permits (ORM-Public) ² |
| `phmsa-npms-search` | Pipelines near a facility, plus incident and enforcement history |
| `fema-flood` | openFEMA NFIP claims, policies, disaster declarations |

**Geospatial, environmental & forensic**
| Skill | What it does |
|---|---|
| `facility-coordinates` | Facility name → lat/lon via EPA ECHO |
| `geo-distance` | Straight-line distance between addresses, place names, or coordinates |
| `satellite-imagery` | Free imagery for a place and date, auto-selecting the best source |
| `firms-active-fire` | NASA FIRMS active-fire detections with fire radiative power and overpass timestamps ² |
| `wind-history` | Forensic wind direction/speed — did the plume reach this receptor? |
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
| `permit-comment` | Findings report + profile → filed-ready public comment letter (standing, numbered comments, drafted conditions, candor section, optional styled PDF) |
| `document-ocr` | Multi-backend OCR (Surya geometry + olmOCR/Chandra/MinerU readers, optional Azure) for a folder or single scanned PDF, with per-line confidence and cross-reader agreement |
| `ocr-verify` | Resolve one OCR-contested value with evidence — every backend's opinion, a cross-package tally, a rendered crop when needed |
| `ocr-validate` | Cheap mechanical pre-pass over an OCRed permit package — flags unit/subtotal/plausibility/date issues, each pointing at a runnable `ocr-verify` command |
| `toxic-truth-teller-style` | Writing style for fenceline-community campaign material (invoke by name) |
| `kit-dissemination` | Draft (never auto-send) Kit.com email broadcasts — case updates, calls for community testimony |
| `nextdoor-campaign` | Research + profile → dated Nextdoor post series, one audience archetype per post, paced to a comment/hearing deadline |

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
- Keep retrieval separate from judgment. Extractor agents cite; the orchestrator rules.
- Never commit credentials, browser profiles, or bulk downloaded datasets.
