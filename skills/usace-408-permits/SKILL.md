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
authorization. Jurisdictional determinations also get no notice, but they are listed in the
ORM-Public AJD tab (next section), so check it before sending a FOIA for a JD.

---

## Approved jurisdictional determinations (ORM-Public AJD tab)

An AJD says which features on a tract the Corps treats as waters of the U.S. The ORM-Public
**AJD** tab lists them from 2017 on, with a link to the Corps' basis form (the memorandum for
record). A tract's JD is often in the AJD list even when its permit has no public notice.

1. Open `https://permits.ops.usace.army.mil/orm-public`, click **AJD**, set District to the
   district code (MVN for New Orleans) and Year to a year or "All Years", then **Table View**.
   Page loads and `read_page` work in the Chrome tools. The district dropdown values are the
   three-letter codes.
2. Search the box with the **parish**, not the owner. Entries are titled by the consultant and
   a place, such as "JD Brown, The 130 ac Tract East and Fronting LA 3127 - St Charles", so a
   search for the developer's or landowner's name returns nothing. Every entry ends in the
   parish name, written without periods: search "St Charles", because "St. Charles" returns
   no data. Then match on date, acreage, road names and the Longitude/Latitude columns.
3. Each row's `Document Link` points to
   `https://www.mvn.usace.army.mil/Portals/56/docs/regulatory/BasisForms/{DA number minus MVN-}-BASIS.pdf`.
   `curl` gets 403 there. Open it in the browser tab (it renders in Chrome's PDF viewer,
   `get_page_text` finds no text, so read it with screenshots) or have the user save it
   with the viewer's download button. A script download of the PDF did not work, and the
   viewer's download button did not save anything when driven from the Chrome tools, so
   ask the user for the file.
4. The other tabs search the same way. **Final IP** and **Pending IP** have an Applicant column,
   so search them by owner or project name, then by parish. A DA number needs its
   zero-padded form (`01106`, not `1106`), and search the number without the district prefix.
   Letters of permission appear under Final IP. **214/Other** lists Section 214 and funded
   reviews only. The **AJD** and **Section 408** tabs are separate lists: a search typed after
   a mis-clicked tab runs against the wrong list and reports "no data", so confirm the heading
   above the search box before trusting a miss. Tab positions shift with window width; click
   by `find` or `read_page` ref, not by saved coordinates.
5. In a post-*Sackett* basis form, item 1 lists each feature as jurisdictional or not,
   item 3 gives the review-area acreage and center point, item 8.f gives the acreage and the
   reason for each non-jurisdictional wetland, and item 9 names the consultant and the dates
   of its delineation report. A form with only "N/A" under item 7 means no feature was found
   to be a water of the U.S. The review area is the surveyed tract, not the whole project.
6. Not published on ORM-Public or the district site: nationwide permit verifications,
   pre-construction notices, pre-application records, JDs before 2017, and public notices before
   2021. Those need a FOIA.

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
6. For an LNG terminal or interstate gas pipeline, FERC is the lead NEPA agency, and the Corps'
   404/Section 10 review typically relies on FERC's EIS. Pull the EIS with `bayou:ferc-elibrary
   eis <docket>`
7. For Section 10 or 404 work in a lake, bay or bayou, check the state's claim to the bottom and
   any state lease or CCS operating agreement there with `bayou:la-state-lands at <lat> <lon>
   --radius 100`. A CO2 injection well or pipeline in state waters also needs an SMEB storage
   agreement, which `la-state-lands ccs` lists.
8. For Section 10 or 404 work, list the mapped wetlands and Essential Fish Habitat at the site
   with `bayou:la-species-cultural-review` Step 2d (`wetlands_efh.py --lat --lon`). Work in tidal
   water inside mapped EFH needs an NMFS EFH consultation, so check whether the public notice
   includes an EFH assessment. Compare the NWI codes, and the date of the imagery behind them,
   with the applicant's delineation.

$ARGUMENTS
