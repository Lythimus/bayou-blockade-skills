---
name: usace-408-permits
description: Search USACE Section 408 permissions and Corps regulatory permits via the ORM-Public portal
allowed-tools: WebFetch, Bash, AskUserQuestion, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__javascript_tool, mcp__claude-in-chrome__tabs_context_mcp
---

# USACE Section 408 & Regulatory Permit Search

Search the U.S. Army Corps of Engineers public permit database for Section 408 permissions (alterations to Corps civil works projects) and Section 404/10 regulatory permits (dredge/fill, navigable waters). Uses the USACE ORM-Public portal.

## Portal

```
https://permits.ops.usace.army.mil/orm-public
```

## Section 408 vs Regulatory permits

- **Section 408 permissions**: Required for any work that alters, modifies, or affects a USACE civil works project (levees, flood control structures, navigation channels). Critical for anything near levee systems.
- **Section 404/10 permits**: Required for discharge of fill material into waters of the U.S. or work in navigable waters. Standard wetland/waterway construction permits.

---

## How to search

The ORM-Public portal is a JavaScript-based SPA hosted on S3. Use WebFetch to load the portal and navigate to the search interface, then parse the results.

### Step 1: Load and browse the portal

```
WebFetch url="https://permits.ops.usace.army.mil/orm-public" prompt="What search options are available? List any visible search fields, filters, or tabs for finding Section 408 permissions or regulatory permits."
```

### Step 2: Direct permit lookups by permit number

If you know a permit number (e.g., `MVN-2023-00123`), use WebFetch:
```
WebFetch url="https://permits.ops.usace.army.mil/orm-public/permit/MVN-2023-00123" prompt="Extract all permit details: applicant, location, activity description, dates, status, conditions."
```

### Step 3: Search by applicant or project name

Use Bash to query if the portal exposes an API endpoint:
```bash
curl -s "https://permits.ops.usace.army.mil/orm-public/api/search?q=QUERY&district=MVN&type=408" \
  -H "Accept: application/json" 2>/dev/null | python3 -m json.tool
```

Common districts for Louisiana:
- `MVN` — New Orleans District (covers southeast Louisiana, including levee systems)
- `SWG` — Galveston District (southwest Louisiana)

---

## USACE district contacts and portals

If the ORM-Public portal doesn't return results for Section 408, check the district-specific pages (for MVN, the browser recipe under "New Orleans District public notices" below; WebFetch gets 403 there):

- **New Orleans District (MVN)** — primary for Louisiana levee/flood control work:
  `https://www.mvn.usace.army.mil/Missions/Regulatory/USACE-Permits_Permissions/`

- **Section 408 National tracker**: The Corps maintains a Section 408 national database at:
  `https://www.usace.army.mil/Missions/Civil-Works/Section408/`

### MVN Section 408 search

```
WebFetch url="https://www.mvn.usace.army.mil/Missions/Regulatory/USACE-Permits_Permissions/" prompt="Find any links to Section 408 permit databases, searchable records, or permit listings. What information is available about permits in Louisiana?"
```

---

## New Orleans District public notices (MVN)

For southeast Louisiana, the district's own public-notice pages are usually faster than
ORM-Public. `curl` and WebFetch get **403** from `www.mvn.usace.army.mil`. A same-origin
`fetch()` from a real browser tab on that site works: use `mcp__claude-in-chrome__navigate`
to open any MVN page, then run `mcp__claude-in-chrome__javascript_tool` in that tab.

| What | Path (on `https://www.mvn.usace.army.mil`) |
|---|---|
| Regulatory notices by year (about 10 per page) | `/Missions/Regulatory/Public-Notices/Year/{yyyy}/?Page={n}` |
| One notice | `/Missions/Regulatory/Public-Notices/Article/{id}/...` |
| Section 408 notices | `/Missions/Section-408/Public-Notices/` |

1. Collect the article links. Stop at the first page with no `Public-Notices/Article/` links:
   ```js
   window.__links = {};
   for (const y of [2026, 2025]) {
     for (let p = 1; p <= 12; p++) {
       const r = await fetch(`/Missions/Regulatory/Public-Notices/Year/${y}/?Page=${p}`);
       if (!r.ok) break;
       const d = new DOMParser().parseFromString(await r.text(), 'text/html');
       const a = [...d.querySelectorAll('a')].filter((a) => /Public-Notices\/Article\/\d+/.test(a.href));
       if (!a.length) break;
       a.forEach((x) => (window.__links[x.href] = x.textContent.trim()));
     }
   }
   Object.keys(window.__links).length;
   ```
2. Fetch each article and keyword-filter **only the article body**. The site navigation on
   every page contains "LPV", "HSDRRS" and similar terms, so matching the whole page makes
   every notice a hit. As of 2026-10-07 the notice text is in `.adetail` (title, dates and body;
   `.body` holds the body alone); `.article-content` does not exist. Check the selector on one
   article before you trust a zero-hit run.
   Fetch one article at a time with a short pause, not in parallel bursts. The loop over about
   100 notices runs past the javascript tool's 45 s timeout. Start it without `await`
   (`window.__p = run()`), then poll a progress counter. Return plain text: the tool blocks
   output that looks like URLs or `key=value` pairs.
   Each notice's text includes `Expiration date: m/d/yyyy`. Compare it with today's date to
   find comment periods that are still open:
   ```js
   const re = /destrehan|st\.? charles|airline/i; // the user's place names and terms
   window.__hits = [];
   for (const u of Object.keys(window.__links)) {
     const d = new DOMParser().parseFromString(await (await fetch(u)).text(), 'text/html');
     // Chained ||, not one comma selector: querySelector('a,b') returns the first match in
     // document order, and the nav comes before the article.
     const body = d.querySelector('.adetail') || d.querySelector('main') || d.body;
     const t = body.textContent.replace(/\s+/g, ' ');
     const m = t.match(re);
     if (m) window.__hits.push({ u, title: window.__links[u], ctx: t.slice(Math.max(0, m.index - 200), m.index + 400) });
     await new Promise((r) => setTimeout(r, 1000 + Math.random() * 1000));
   }
   window.__hits;
   ```

**A miss is not evidence of no permit.** The Corps publishes notices only for **individual
permits**. Work under nationwide or general permits, which covers most small utility,
pipeline and road jobs, gets no public notice. When nothing turns up, check the state coastal
use permit (`bayou:sonris-doc-search`, CUP recipe) before concluding there's no federal
authorization.

---

## Regulatory Permit Search (ORDS/ORM)

The Corps's Regulatory Request System also has a public-facing search:

```
WebFetch url="https://rrs.usace.army.mil/rrs/home/permitting" prompt="What search options exist for finding regulatory permits? How do I search by applicant name, location, or permit type?"
```

---

## Common permit activity descriptions to search for

When searching for nuclear facility–related USACE permits:
- "intake structure" — cooling water intake modifications
- "discharge" — thermal discharge or outfall structures
- "levee alteration" — any work affecting levees (requires Section 408)
- "transmission line" — crossing waterways
- "dredge" — channel maintenance
- "fill" — wetland fill for facility expansion

---

## What Section 408 permits look like

A typical Section 408 permission includes:
- **Permittee**: Entity requesting to alter the civil works project
- **Project location**: Description of the civil works project affected (e.g., "Mississippi River Levee, Left Descending Bank, Station 123+00")
- **Proposed alteration**: What change is being made
- **Conditions**: Requirements to protect the project's authorized purpose
- **Status**: Pending review, approved, denied, withdrawn

---

## How to present results

1. List permits found with: Permit # | Applicant | Location | Activity | Status | Date
2. For Section 408: highlight which civil works project is being altered and whether it's a levee
3. Flag any pending permits (review in progress)
4. Note the reviewing district and contact info for follow-up
5. Link to the full permit record in ORM-Public or the district's Regulatory page

$ARGUMENTS
