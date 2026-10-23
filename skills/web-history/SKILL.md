---
name: web-history
description: Reconstruct what a company's or project's website said, and when, from the Wayback Machine — list every distinct archived version of a page or a whole site section, extract the visible text of a version, diff two versions, and track a phrase or number (jobs, investment, emissions, "carbon capture", a project or owner name) across years. Use to date when a project page first appeared relative to an announcement or permit filing, to catch promises that changed, or to recover pages a company removed. Read-only; preserving a live page is a separate, outward-facing step.
argument-hint: <url or domain> [phrase to track] [--from YYYY --to YYYY]
allowed-tools: Bash, Read, WebSearch, AskUserQuestion
---

# Web History

Companies change their websites without notice: a project page goes up before the permit is filed, a job count shrinks after the tax exemption is granted, "zero emissions" becomes "lower emissions", an owner's name appears in the footer after a sale. The Wayback Machine has usually captured the old versions. This skill finds them, pulls their text, and lines them up so the change can be quoted and dated.

It retrieves and compares archived pages. It does not establish why a page changed or what the company knew at the time.

## When to use

- **When did the project first appear?** Compare the first capture of a project page, or of the first page under `/projects/`, with the public announcement and the permit application date. A page captured months before a "speculative" land purchase or a notice of intent was filed is a dated public record of the plan.
- **Promises that changed**: jobs, capital investment, tonnage, emissions, capture rates, "no ammonia", water use. `grep` across versions shows each value and the first version that carried it.
- **Ownership changes**: a new parent's name in the footer or the About page (IMTT's footer adds "Riverstone, LLC" in captures from January 2021, after the December 2020 sale). Feed what you find into `bayou:la-power-map`'s `ENTITIES.md` as a `press only` row citing the archived page.
- **Removed pages**: a page that stops being captured, or a site section that disappears from `--match-prefix` listings.

## Parsing arguments

- **URL or domain** (required). If the user gives only a company name, find the official site with WebSearch first, and confirm it with the user if more than one domain comes back (local project LLCs often have a one-page site separate from the parent's).
- **Phrase or number to track** (optional), turned into a case-insensitive regex. Keep it loose enough to catch rewording: `(\d[\d,]*)\s+(permanent\s+)?jobs`, `carbon capture|CCS|sequest`.
- **Date range** (optional), as years.

## Workflow

### 1. List the versions

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/web-history/wayback.py" captures imtt.com/ --from 2020 --to 2021
python3 "${CLAUDE_PLUGIN_ROOT}/skills/web-history/wayback.py" captures example.com/projects/ --match-prefix
```

CSV: `timestamp, date, original, digest, length, mimetype, snapshot_url`. One row per *change*: consecutive captures with identical content are collapsed, so 19 rows over two years means the page changed about 19 times, not that it was crawled 19 times. A jump in `length` (29 KB to 110 KB for imtt.com in November 2020) marks a redesign. `--match-prefix` lists every page under a path, which is how to see when a project page first appeared and last appeared.

If nothing comes back, try with and without `www.`, with and without the trailing slash, and `--match-prefix` on the bare domain.

### 2. Read and compare the versions around a change

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/web-history/wayback.py" text 20201027124345 https://www.imtt.com/
python3 "${CLAUDE_PLUGIN_ROOT}/skills/web-history/wayback.py" diff https://www.imtt.com/ 20201027124345 20210126025451
```

`text` prints the page's visible text without scripts, styles, or the Wayback toolbar. `diff` is a unified diff of two versions' text: `-` lines were removed, `+` lines added. Use the `timestamp` and `original` columns from step 1 exactly as printed.

### 3. Track a claim across all versions

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/web-history/wayback.py" grep imtt.com/ "Macquarie|Riverstone" --from 2019 --to 2022 --max 20
```

Prints each version's date and the text around every match, or `no match`. When there are more versions than `--max`, it samples evenly across the range; once a change is bracketed between two sampled dates, narrow `--from`/`--to` and rerun to find the exact version. Each version is a separate download, so 40 versions take a few minutes.

## Limits, stated in any write-up that relies on this

- **A capture date is when the crawler visited, not when the content was published.** The honest claim is "the page said X no later than <capture date>", and for a change, "between <last version without it> and <first version with it>".
- **A gap in captures is not proof the page was absent.** Lightly linked pages are crawled rarely.
- **JavaScript-rendered sites can archive as empty shells.** If `text` returns little more than navigation, check `length` in step 1 and look for the content through `--match-prefix` on `/wp-json/`, `/sitemap.xml`, or the site's PDF uploads directory.
- **A site owner can exclude a domain from the archive**, retroactively hiding every version. No captures for a well-known company's site is a reason to note the exclusion, not to conclude anything about the content.
- **The archived copy is the archive's record, not the company's.** Cite it as such (format below).

## Preserving current pages

This skill never asks the archive to save anything. To preserve a live page before it changes (a project page cited in a comment letter, say), use the Save Page Now step in `bayou:public-comment` (Step 8b). Saving publishes the request to an outside service, so ask the user once before doing it.

## Dead ends

- **`archive.org/wayback/available`** (the "closest snapshot" API) returned HTTP 429 on 2026-10-22 while the CDX API answered. The script uses CDX only.
- **Snapshot URLs without `id_`.** `web.archive.org/web/<ts>/<url>` injects the Wayback toolbar and rewrites every link, which pollutes text extraction and diffs. The script fetches `<ts>id_/` for text and prints the plain form for citation.
- **The `internet-archive` MCP** (listed in the README) fetches single snapshots. Use it if it is installed and only one page is needed; it does not list versions or compare them.

## Presenting the results

1. The URL checked, the date range, and the number of distinct versions found.
2. A timeline of the changes that matter: date of the last version before the change, date of the first version after it, and the old and new text quoted exactly.
3. For a phrase tracked with `grep`: date | value or wording as it appeared | snapshot link.
4. The limits above that apply, in one or two sentences.

### Citation format

Give both the original URL and the archived snapshot:

> **IMTT (International-Matex Tank Terminals), company website home page**, https://www.imtt.com/, as archived by the Internet Archive Wayback Machine on 2021-01-27, footer reads "Riverstone, LLC"; earlier versions through 2019-11-13 do not name Riverstone or Macquarie. Source: [Wayback Machine snapshot](https://web.archive.org/web/20210127141213/https://www.imtt.com/) (retrieved 2026-10-22).

$ARGUMENTS
