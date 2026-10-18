---
name: ldh-drinking-water
description: Louisiana public drinking water near a proposed injection well, outfall or other source. It finds the public-supply wells within reach of a point or inside a Class VI area of review, and tests each against the LDEQ Source Water Assessment Program (SWAP) default protection radius. It finds the surface-water intakes downstream of a discharge using a USGS NLDI flow trace, with flow distance, the SWAP 5-mile critical area, the Mississippi River corridor rule, and the Bayou Lafourche intakes fed from the river at Donaldsonville. It also gives each water system's record: the LDH Drinking Water Viewer header, unresolved-violation and deficiency status and next sanitary survey; federal SDWIS violations with the health-based flag; lead and copper 90th percentiles; sellers, buyers and the population served. LDH's own chemical and coliform results, state violations (boil advisories) and sanitary surveys sit behind a reCAPTCHA; a helper runs those searches in a visible browser and records what loads, and a person clicks the "I'm not a robot" checkbox if Google shows one. Use when someone asks which water supplies an injection well, outfall or spill could reach, whether an outfall is upstream of a drinking-water intake, whether wells draw from the aquifer near a Class VI site (CVI-008), about boil advisories, MCL violations or lead results for a Louisiana water system, or which system serves a parish.
argument-hint: near <lat> <lon> [--radius M] | near --aor aor.geojson | downstream <lat> <lon> [--mississippi] | systems "<name>" | systems --parish P | system <PWSID> | violations <PWSID> | samples <PWSID> [--analyte X] [--exceed] | visits <PWSID> | captured
allowed-tools: Bash, Read, WebFetch, WebSearch, AskUserQuestion
---

# Louisiana public drinking water (LDH, SWAP, SDWIS)

The Louisiana Department of Health (LDH) regulates public water systems under the Safe Drinking Water Act. Its public record is the **Drinking Water Viewer** at `https://sdw.ldh.la.gov/`, which replaced the old Drinking Water Watch (`/DWW/` URLs open the same app). Its data comes from LDH's SDWIS database. EPA receives a subset as federal SDWIS, a quarter or more later.

LDEQ ran the **Source Water Assessment Program** (SWAP, 1999–2003). It delineated a source water protection area (SWPA) for every public-supply well and intake and inventoried the potential sources of contamination in each. No public map layer of those SWPAs exists. This skill rebuilds them from the delineation rules in the SWAP document (`https://deq.louisiana.gov/assets/docs/Water/SWAPdocument.pdf`):

| SWAP section | Source | SWPA |
|---|---|---|
| 4.1 | Well, community or non-transient non-community (NTNC) | 1-mile radius. This is the default and the maximum. Wells screened below 1,000 ft and completed before LDOTD's construction rules (1985-11-01) got ½ mile |
| 4.1 | Well, transient non-community (TNC) | 1,000 ft. TNC wells in the Terrace Aquifer got ½ mile |
| 4.1.1 | Confined or unconfined aquifer | Confined at most ½ mile, unconfined 1 mile; a recharge area within 1 mile is included |
| 4.2 | Surface intake | The entire upstream watershed. The **critical area** is the 5 miles upstream of the intake |
| 5.4.2 | Mississippi River intake | The river corridor upstream of the intake to the state line. Any point upstream on the river is inside that SWPA |

## What the script reads, and what it does not

| Source | Used for | Access |
|---|---|---|
| LDH Drinking Water Viewer | system header (population, federal type, source mix), the Violations and Deficiencies status gauges, next sanitary survey due date, code lookups | `GET /` sets an `XSRF-TOKEN` cookie; each `/sdwis/` call echoes it in an `X-XSRF-TOKEN` header |
| `facilities.json` (in this skill) | every LDH well (WL) and intake (IN) statewide with LDH's coordinates: 5,388 rows, 5,268 with coordinates | snapshot of the viewer's FacilityList, pulled 2026-10-17 |
| EPA Envirofacts (`data.epa.gov/efservice`) | system search, federal facility list, sellers and buyers, violations (`VIOLATION`), lead and copper (`LCR_SAMPLE_RESULT`) | open REST API |
| USGS NLDI | the NHDPlus flowline at a point, plus downstream-mainstem (DM) and with-diversions (DD) traces | open REST API |

**The viewer's search, violations, sample, site-visit and facility grids are not scripted.** For anonymous users the viewer sends a one-time reCAPTCHA token with each of those requests. LDH's Azure gateway tolerates a few requests without one, then blocks the IP with HTTP 403. `dww.py` only calls what the viewer itself calls without a token. It never retries a gateway 403, because each retry can extend the block. Behind a shared VPN or office egress IP, the block can also fall on everyone else using that IP.

### Capturing the gated grids (a person at the screen)

`dww_capture.js` opens the viewer's pages for one system in a visible Chromium window. The viewer's own page gets its reCAPTCHA token from Google, and when Google is unsure it shows the "I'm not a robot" checkbox, which the person clicks. After a pass LDH lets that browser call the grids without a token for 20 minutes, and the script asks for the requested date windows from inside the page during that pass, the way the viewer does. It never solves, requests, reads or replays a reCAPTCHA token or the pass cookies, and it reads only the anti-forgery cookie the viewer itself echoes. This is the same arrangement as `bayou:ldeq-edms-download`: the person answers the CAPTCHA and the script does the rest.

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/ldh-drinking-water"
cd "$S" && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install    # once, about 18 MB; Playwright pinned to 1.61.1
node "$S/dww_capture.js" --pws LA1089001                      # chem, micro, violations, visits; last 10 years
node "$S/dww_capture.js" --pws LA1089001 --pages violations --since 2016-01-01 --until 2026-10-17
```

- **Browser:** the pinned Playwright drives its own Chromium build (`chromium-1228`). If that build is not in `~/Library/Caches/ms-playwright`, `npx playwright install chromium` fetches it, about 150 MB; state the size and confirm before running it.
- **Before running it, ask the user.** A reCAPTCHA checkbox may need them, and while one is showing the script waits up to `--timeout` (default 30 minutes). Don't start it when nobody is at the screen.
- **What the script does:** it opens each grid so the viewer makes its own first call (keeping that default window too), then requests `--since` (default 10 years back) to `--until` (default today) from inside the page. The chemical and coliform grids go one calendar year per search, newest first. Requests are about 8 seconds apart, and it closes the browser by itself when every window is complete.
- **LDH's limits:**
  - **5,000 results per search.** LDH stops a search at 5,000 result rows (each analyte result in a sample counts) before sorting, and its row count then describes only the cut-off set. A 10-year chemical search for LA1089001 came back as 564 "complete" samples with none from 2026. The script therefore splits any window near that total.
  - **1,000 rows per page.** The viewer pages through at most 1,000 rows, so the script never asks for more and splits a fuller window instead.
  - **Gateway refusals.** LDH's gateway refused a quick run of 1,000-row requests within a valid pass. What triggered it (volume, pace or paging) is unknown. When it happens the script stops (exit 5); wait hours before running again.
- **What the person does:** nothing, unless the terminal prints `>>> ... Click "I'm not a robot"`. Then they click the checkbox (and finish any image challenge), and the capture carries on. When the 20-minute pass ends mid-run, the script reopens the page for a fresh check rather than retrying. If a grid can't be finished automatically, the terminal lists it and leaves the browser open for the person to finish that search and close the window.
- **Pages:** `chem` (Chemical Results, with the Lead & Copper tab), `micro` (Microbial Results), `violations` (Violations & Enforcements), `visits` (Site Visits).
- **Checkbox frequency:** after one passed check LDH sets a 20-minute skip cookie (`gRSkip`, plus a `grValue` flag) in the browser profile (`.pw-profile/`, git-ignored), so the other tabs usually load without another check. The cookie stays in the browser; `dww.py` does not use it.
- **Recorded:** only the sample, violation and site-visit grids. The viewer's contact lists (staff names, phones, emails) are never written.
- **Output:** `~/.cache/bayou/ldh-drinking-water/captured/<PWSID>/`, one file per search, with its date window, rows per page and the grid's count. `samples`, `violations` and `visits` read these files. Each prints the window searched. A search with pages left unloaded is flagged `INCOMPLETE`, and one near LDH's 5,000-result limit `CUT OFF`; either is marked covered once complete shorter windows span its dates. A window that starts after `violations --since` gets a warning. Nothing outside a captured window is implied.
- **Exit codes:** 0 every grid complete, 1 script error, 3 some grid not finished automatically (run `dww.py captured` to see which windows are `INCOMPLETE`), 4 nothing saved, 5 LDH's gateway refused the viewer's own untokened calls (stop, wait hours).
- **Never** pass captured cookies or tokens to `dww.py` or any script, and never ask for a solving service.

Grid contents:

| Grid | Fields |
|---|---|
| Chemical | each analyte with result, `<` flag, MCL and exceedance flag, method and lab id (`samples` parses these; `--analyte`, `--exceed`) |
| Coliform | total coliform and E. coli presence or absence per sample, plus chlorine residual (`samples` counts the samples tested and lists only the positives) |
| Lead and copper | lead and copper 90th percentiles, samples taken and samples above the action level, by monitoring period (flat rows, shown field by field) |
| Violations | state violation type and name, analyte, period, determination date, RTC status (includes boil advisories) |
| Site visits | visit date, reason, severity |

`--exceed` keeps every result whose `ExceedsMCL` is not a plain no. Only "N/A" has been seen live, so check any hit against the MCL column.

The `facilities.json` snapshot does not refresh itself. FacilityList is a gated grid of about 194 pages, far more requests than LDH's gateway tolerates, so `health` reports the snapshot's age instead. LDH adds and retires wells slowly. For a decision record, confirm a specific well on the system page.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/ldh-drinking-water"
T() { uv run -q --no-project python -I "$S/dww.py" "$@"; }

T health                                  # LDH session, Envirofacts, NLDI, Mississippi reference trace, index integrity
T near 30.21 -91.05 --radius 3219         # wells/intakes within 2 miles; SWAP default radius test per well
T near --aor aor.geojson                  # CVI-008: wells inside the AoR, and wells whose 1-mile SWPA reaches it
T downstream 29.995 -90.41                # Norco outfall: every Mississippi intake below it, flow km, critical area
T downstream 30.44 -91.19 --mississippi   # bank-side point that NHDPlus drains elsewhere; force the river trace
T downstream 30.69 -91.745 --km 300       # off the Mississippi: DM trace plus DD diversion branches
T systems --parish "st charles"           # active systems serving a parish (--inactive for all)
T systems "baton rouge water"             # name contains
T system LA1089001                        # LDH header, gauges, wells/intakes with coordinates, sellers, buyers
T violations LA1089001 --since 2016-01-01 # federal violations (two tables unioned), LDH gauge, captured state record
T samples LA1089001                       # lead/copper 90th percentiles, plus captured LDH chemical/coliform grids
T samples LA1089001 --analyte lead --exceed
T visits LA1089001                        # captured sanitary surveys; deficiency gauge; next survey due
T captured                                # every capture on disk: system, grid, date window, INCOMPLETE flags
```

Add `--json` for machine-readable output and `--refresh` to bypass the cache. Exit codes: 2 bad arguments, 3 not found (an unknown PWSID lists near ids), 5 source down. That includes an empty or non-JSON answer, which is never read as zero rows, and a gateway block.

### Reading `near`

- **Default:** active facilities only (`--all-status` adds inactive and proposed). Distance is from the point to LDH's coordinates.
- **Well tags:**
  - `point inside SWAP default (1 mile)`: the point lies inside that well's SWAP default SWPA.
  - `TNC 1,000 ft`: the radius used for a transient non-community well (federal type `TNCWS`).
  - With `--aor`: `IN AoR`, or `SWAP default … reaches AoR` when the well is within its radius of the boundary.
- **Missing coordinates:** facilities of the same systems that have no coordinates are listed at the end. Their location is unknown and could be near.
- **Population and type:** these come from federal SDWIS (`WATER_SYSTEM`).

### Reading `downstream`

- **Order and route:** intakes are ordered by flow km along NHDPlus from the point's projection onto the flowline. The start reach is clipped, so intakes upstream of the point on the same reach are excluded.
- **`SWAP CRITICAL AREA (<5 mi)`:** the point is within 5 miles upstream of the intake (§4.2).
- **`Mississippi corridor SWPA`:** the point is on the mainstem above the intake (§5.4.2).
- **`watershed SWPA`:** any other mainstem intake, since §4.2 makes the whole upstream watershed the SWPA.
- **Mississippi detection:** the point's COMID is in a cached reference trace of the mainstem, from near Lake Providence (32.80, −91.12) to Southwest Pass. On the mainstem the trace runs to the Gulf and `--km` is ignored. The lowest intake is Port Sulphur's Boothville-Venice intake (1075006-002), below the Port Sulphur intake that the 2001 SWAP document called the lowest.
- **Bank-side points:** a point within 1 km of the river that NHDPlus drains to another flowline prints a warning. Rerun with `--mississippi` if the outfall discharges to the river.
- **`diverging branch`:** an intake on a DD branch (a distributary, canal or lock connection) that the DM mainstem does not follow, such as the GIWW at Port Allen, Morgan City or the Teche. No flow km is given. A lock connection carries little flow, so treat these as possible pathways and check the hydraulics.
- **`Bayou Lafourche (pumped diversion)`:** the point is on the Mississippi above Donaldsonville. The Bayou Lafourche Fresh Water District pumps river water into the bayou there, and NHDPlus does not connect the two. These intakes come from a DD trace from the bayou's head; through Bayou Terrebonne and the GIWW that trace also reaches Schriever and Houma.
- **Population:** totals count each system once, including the buyers found through federal `WATER_SYSTEM_FACILITY.SELLER_PWSID`. Belle Chasse, for example, both owns an intake and buys water.
- **Buffer:** the default is 1,500 m. Mississippi intakes sit 150–800 m from the NHDPlus line, because LDH's intake coordinates are often at the plant.

## Limits and traps

- **The SWPAs are a reconstruction, not LDEQ's delineation.** LDH data has no screen depth, completion date or aquifer, so the ½-mile and confined-aquifer cases of §4.1 cannot be decided. The script uses the default radius and says so.
  - For the actual SWPA and the potential-source inventory, request the system's **source water assessment report** from the LDEQ Aquifer Evaluation and Protection Unit (`bayou:la-public-records-request`).
  - For the Class VI question, set each well's aquifer and screened interval against the lowermost USDW in the application.
- **Private domestic wells are not public water systems** and are not in this data. They are in the DCE water-well registration records (SONRIS). Ask DCE for registered water wells within the AoR through `bayou:la-public-records-request`.
- **LDH's coordinates are LDH's.** Some are at the treatment plant rather than the well or intake, and about 120 wells have none.
- **Federal SDWIS misses state-only entries.** St. Charles Parish (LA1089001) has no federal violations since 2016. LDH shows a 2018 system-issued boil advisory, still Unresolved, and a 2019 chlorine-residual violation; neither reached EPA. Capture the LDH Violations grid with a window reaching back far enough (or read the page) before saying a system is clean.
- **Neither federal violation table is complete.** Envirofacts `VIOLATION` lacks some older violations that `SDW_VIOL_ENFORCEMENT` keeps (St. Charles's 2010 coliform MCL, Baton Rouge Water's 2012 DBP monitoring), and the enforcement view lacks recent ones. `violations` unions them by id. Rows from the enforcement view carry no compliance status, and their health-based flag comes from the category (MCL, MRDL and TT are health-based). Open violations are listed whatever `--since` says.
- **The LDH Violations gauge rarely discriminates.** The viewer runs it with no age limit, and it read HIGH ("Unresolved Health-Based Violations") for 8 of 8 systems sampled, inactive ones included. It shows that LDH holds some unresolved health-based record, which could be decades old. Don't cite it as current non-compliance.
- **LDH facility status and system status can disagree.** LDH keeps some facilities active after their system was retired or merged. For example, St. Charles WD2's intake is still active under the inactive LA1089002, at the same point as LA1089001's WB intake. `near` and `downstream` omit facilities of systems that SDWIS lists as inactive, name them, and leave them out of the population. `--all-status` shows them.
- **Lab ids are LDH certifications** (for example `LA01134`), not LELAP accreditations. Drinking-water labs are certified by LDH, and LDEQ's LELAP program excludes them (`bayou:ldeq-lelap-labs`, LAC 33:I.4501.E).
- **Federal search quirks.** Parish search uses federal `GEOGRAPHIC_AREA`, which lists a system under its principal parish only. A water district serving several parishes appears under one of them. Name search is a plain substring match on the federal name.
- **Open gaps in the capture helper (as of 2026-10-17):**
  - **The year-by-year in-page capture has not had a clean live run.** Its pieces were each seen working:
    - in-page requests served rows without a token during a pass;
    - the 1,000-row split worked through the UI;
    - the violations, site-visit and lead/copper grids completed.
    The first live run of the full design is its test. After it, check `dww.py captured`: no window should read `CUT OFF`, and every requested window should be complete or covered.
  - **What trips LDH's gateway is unknown.** A quick run of 1,000-row requests was refused within a valid pass. The 8-second spacing and the 1,000-row reach are precautions, not tested limits. After a refusal, wait hours, and don't run captures for many systems back to back.
  - **Captures made before the year-by-year design can be cut off.** LA1089001's test captures include a 2016–2026 chemical window of 564 samples that LDH stopped at 5,000 results (none from 2026), and partial coliform windows. `dww.py` flags them `CUT OFF` or `INCOMPLETE`. Don't draw trends or "worst years" from them. Move the system's `captured/<PWSID>/` folder aside and capture again before relying on its chemical or coliform history.
  - **Single TTHM/HAA5 results over the MCL are not violations.** `--exceed` compares each result with the MCL, but disinfection-byproduct compliance is a locational running annual average. LA1089001 had 24 single results over the MCL between 2016 and 2024 and no DBP violation. Say "results above the MCL", not "MCL violations".

## Related skills

- `bayou:la-class-vi`: run `near --aor` on the area of review for CVI-008, and `near` on each injection well.
- `bayou:cwa-watershed-context`: the receiving water's designated uses. A Drinking Water Supply use plus a `downstream` hit is the core of an intake-risk comment.
- `bayou:epa-echo-search`: ECHO's SDWA view of the same federal data, with enforcement history.
- `bayou:usgs-water-data`: groundwater-level and stream gauges near the site.
- `bayou:household-exposure`: for the drinking-water line of a receptor's exposure profile, run `system`, `violations` and `samples` on the PWSID that serves the address.
- `bayou:la-public-records-request`: the LDEQ SWAP assessment report, DCE water-well registrations, and LDH sanitary survey reports.
