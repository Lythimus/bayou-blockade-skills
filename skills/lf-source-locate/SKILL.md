---
name: lf-source-locate
description: Bearing inference for low-frequency tonals at one public infrasound site. It uses the EarthScope archive (through lf-acoustic-baselines), IEM ASOS surface wind and NEXRAD storm cells. wind-scan regresses the hourly prominence of a tonal on the along-path wind for every trial back-azimuth. It reports a tempered bearing posterior, a 90% arc and a night-block permutation p-value, then ranks candidate release points from ldeq-eric-emissions against it. bearing is a diagnostic of pressure × horizontal-ground cross-spectra: it failed validation on located thunder, so it gives no bearing. features exports hourly tonal features as a CSV, the one seam for non-archive data. tdoa grid-searches BDF arrival times across the 2011–12 TA ring around 545A for impulsive events (explosions, booms). It is unvalidated: it failed its pre-declared ground-truth tests, and gave a correct direction only once, on one large night-time explosion. Use it to ask whether a tonal near a refinery behaves as if it comes from the plant's direction. Output is inference with an arc, never a location, and cannot pick out a unit inside one facility.
argument-hint: wind-scan <NSLC> --freq f0 --start D --end D [--candidates eric.json] | wind-scan --features f.csv --freq f0 | features <NSLC> --freqs f0 --start D --csv f.csv | bearing <NET.STA> --freqs f0 --start D | validate <NET.STA> --start D --end D | tdoa --start T --end T [--truth lat,lon]
allowed-tools: Bash, Read
---

# Low-frequency source bearing (inference)

Can archived infrasound, weather and propagation physics say where a low-frequency sound comes from? With public data near Norco, mostly not by triangulation:

- **Triangulating continuous tonals is not possible.** After 2012, the only public microbarometer within ~180 km is TA.545A/N4.545B (30.0441, −90.4894, ~9 km NW of Norco). The 2011–12 TA neighbors sit 63–86 km away. At that spacing, coherence at 5–20 Hz is gone, and a sinusoid's cross-correlation is periodic.
- **What one site can give** is a bearing likelihood. It comes from how a tonal's level tracks the wind (`wind-scan`). Every result is an arc with stated assumptions, and it is labeled as inference.
- **Impulsive events** across the 2011–12 TA ring (`tdoa`) can be located in principle from arrival times. In practice it failed its ground-truth tests (below). It ships as a diagnostic.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/lf-source-locate"
F() { uv run -q --no-project --with obspy --with numpy --with scipy python -I "$S/lfloc.py" "$@"; }
E() { uv run -q --no-project --with openpyxl --with xlrd python -I "${CLAUDE_PLUGIN_ROOT}/skills/ldeq-eric-emissions/eric.py" "$@"; }

F health                                                        # EarthScope, ComCat, IEM ASOS
E sources 1406 --year 2024 --receptor 30.0441,-90.4894 --json > norco.json
F wind-scan N4.545B.EP.BDF --freq 14.78 --start 2016-06-01 --end 2016-08-31 --days 20 --candidates norco.json
F features N4.545B.EP.BDF --freqs 14.78 --start 2016-06-01 --end 2016-08-31 --days 20 --csv feat.csv
F wind-scan --features feat.csv --freq 14.78 --candidates norco.json          # same result from the CSV
F bearing N4.545B --start 2016-06-01 --days 3 --hours 00-04 --freqs 7.39,14.78   # diagnostic only
F validate N4.545B --start 2017-05-01 --end 2017-09-30 --band 1-18               # thunder test of `bearing`
F tdoa --start 2012-10-16T04:35 --end 2012-10-16T05:00 --box-deg 4 --step-deg 0.1 --truth 32.58,-93.35 --csv picks.csv
F tdoa --start 2012-10-16T04:35 --end 2012-10-16T05:00 --box-deg 4 --step-deg 0.1 --picks picks.csv   # same result
```

Every command takes `--json` and `--refresh`.

- **Download gate.** Waveform commands share lf-acoustic-baselines' cache and its 50 MB download gate (exit 4). Any larger pull needs `--yes`.
  - BDF costs about 0.5 MB per hour, so the 20-night × 4 h `wind-scan` above is about 40 MB.
  - A `bearing` hour also pulls two 100 sps horizontals, about 3 MB per hour.
  - A 25-minute `tdoa` window over 7 stations is about 2 MB.
  - State the size and get the user's agreement before passing `--yes`.
- **Exit codes:** 2 usage, 3 no data, 4 gate refused, 5 source down.

## `wind-scan`: bearing from the wind dependence of a tonal

**Physics.** Sound carries farther downwind: the wind adds to the effective sound speed along the path and bends rays back toward the ground. So if a tonal comes from back-azimuth θ, its level at the station should rise when the wind blows *from* θ toward the station.

**Model.** One row per hour:

`prominence = a + c·U + b·U·cos(drct − θ) + ε`,  with `b ≥ 0`

- U and drct come from the ASOS station (MSY by default), vector-averaged within each UTC hour from METAR + SPECI reports.
- drct is the direction the wind blows *from*.
- Prominence is the tonal's level above its ±1/3-octave running median. Using prominence rather than level cancels broadband wind noise at the inlet, which also rises with U.
- The `c·U` term absorbs any remaining speed-only effect.
- **Why `b ≥ 0`:** without it, θ and θ+180° fit equally well, so the scan cannot pick a side. A fit with b < 0 is scored as b = 0.

**Statistics.**

- **Scan.** Profile log-likelihood over θ = 0–359°, flat prior, normalized posterior. Output: the most likely back-azimuth, the 90% highest-density arc, and the posterior mass per 30° sector.
- **Tempering.** The likelihood counts **one effective observation per night**, not per hour. Hours within a night are near-duplicates; untempered, the summer-2016 arc below was 21° wide, falsely precise.
- **Significance.** The likelihood ratio against b = 0, tested by permuting whole nights of wind against whole nights of prominence (200 permutations, `--seed 1`). A p-value of 0.05 or more means the posterior is not informative, and the output says so.
- **Calm hours** (under 0.5 m/s) carry no bearing information. Their share is reported.

**Candidates.** `--candidates` reads `eric.py sources --json` (`sources` rows with lat/lon), and `--candidate name,lat,lon` adds points by hand.

- The output prints the candidates' angular spread **first**.
- When the spread is narrower than 45° or the 90% arc, it says that geometry can only separate the cluster from other directions. Telling units apart needs operating-time or spectral evidence (`epa-campd-search`, `ldeq-edms-search`).
- Candidates are ranked by posterior density relative to the peak, and flagged when inside the 90% arc.

**Guards.**

- It refuses a window that crosses an instrument or sample-rate change (`--allow-epoch-change` overrides).
- It warns when N4.545B windows touch 2018. That year's EP.BDF levels sit 16–41 dB below 2015 at 6–16 Hz with no metadata change (lf-acoustic-baselines SKILL.md).

**Not modeled.**

- **Temperature-gradient refraction.** Nocturnal inversions raise levels from every direction alike. That is harmless only if stability is unrelated to wind direction, and it often isn't: Gulf-flow and land-flow nights differ. A stability effect that tracks MSY wind direction folds straight into `b·cos(drct − θ)` and can **mimic a bearing**.
  - **Guard:** run the same windows at off-peak bins and at other tonals (the cache makes this free). A bearing that shows up in noise bins too is weather, not source direction.
  - **Not fitted:** Open-Meteo has no temperature aloft before 2021-03 (SKILL-ROADMAP §13), so no Δc_eff term is fitted.
- Wind is surface wind at MSY, 22 km ESE of the station, not along the path. It is a proxy.
- Source output varies with plant operation. That variance stays in ε unless the windows are chosen around known operating states.

### Worked result (2026-10-17)

`wind-scan N4.545B.EP.BDF --freq 14.78 --start 2016-06-01 --end 2016-08-31 --days 20`, 00–04 local, with ERIC AI 1406 (Shell Norco, 2024 release points):

- **Candidates:** 49 release points spanning 108–124° from the station, 8.8–9.5 km away.
- **Data:** 80 hours over 20 nights; 24% calm at MSY.
- **Wind dependence:** LR 63.7, permutation p = 0.005. Most likely back-azimuth 89°, at +2.15 dB per m/s of along-path wind.
- **Arc:** the 90% arc spans 63–109° (47°). It takes in the Norco release points at 108–109° (relative density 0.20–0.24). The 110–124° points fall just outside it.

- **Negative control, same 80 hours:** the off-peak bins 9.5, 12.0 and 17.0 Hz and the 7.39 Hz tonal all give p = 0.10–0.37 with flat posteriors, so the 14.78 Hz dependence is not generic weather.

How to say it: in summer 2016 nights, the 14.78 Hz tonal at 545B grew louder with wind from the east. That is consistent with a source to the E–ESE. The Norco refinery sits at the edge of that arc; it is not centered in it. This is not an attribution.

## `features`: the data seam

`features` writes the hourly table that `wind-scan` fits, with these columns:

| column | meaning |
|---|---|
| `time_utc` | hour start, `YYYY-MM-DDTHH:MM:SS`, UTC |
| `hz` | requested tonal frequency (the strongest bin within ±0.02 Hz is used) |
| `level_db` | PSD at that bin, dB (archive: dB re 1 Pa²/Hz) |
| `prominence_db` | level above the ±1/3-octave running median, dB |
| `lat`, `lon` | sensor position, decimal degrees |

- `wind-scan --features <csv>` accepts any file with these columns. A personal recorder can feed the same analysis once something converts its audio to this table. Prominence is a relative measure, so an uncalibrated recorder still works.
- Values are rounded to CSV precision before fitting. A CSV export of an archive run therefore reproduces it exactly; checked 2026-10-17, identical JSON.
- Nothing here reads WAV files.

## `bearing`: diagnostic only (failed validation)

**Idea.** A pressure wave tilts and compresses the ground along its propagation direction. At a tonal where the infrasound (BDF) is coherent with the horizontal seismometer components, the cross-spectra `[S_pN, S_pE]` should point along the propagation axis.

**What it computes:**

- It rotates the horizontals by their metadata azimuths, including HH1/HH2.
- It computes the multiple coherence of pressure on (N, E), and keeps hours with coherence ≥ 0.5.
- It reports the axial mean and spread, and the in-phase azimuth.
- It refuses windows that cross N4.545B's 2019-03-01 move from `--.HHN/HHE` to `00.HH1/HH2`.

**Validation (`validate`)** uses thunder with a known direction:

- **Event selection.** It picks UTC hours with NEXRAD LIX storm cells (≥ 50 dBZ) 3–25 km from the station, all within a 30° arc, and no strong cell elsewhere within 50 km.
- **Spectra.** It computes cross-spectra over only the loudest 10 s segments: at least 10× the hour's median in-band pressure power, and at most the top 5%. Hour-long averages bury the thunder: broadband coherence was 0.03–0.08 in those hours.
- **Pass rule.** At least 3 events within ±20°, at least half of the scored events, and a consistent in-phase side.

**Result, 2026-10-17: FAIL.**

| Summer | One-sided storm hours tried | Scored | Within ±20° |
|---|---|---|---|
| 2016 (band 1–10 Hz) | 8 | 2 | 1 |
| 2015 (band 1–18 Hz) | 8 | 0 | — |
| 2017 (band 1–18 Hz) | 8 | 5 | 2 |

Most hours had too few loud segments or no coherent bins. In 2017, every axis fell at 9–19°, whatever the storm's direction (85°, 215°, 354°, 62°). The two "hits" were storms near 354°, which coincide with that fixed axis. This is a station-side bias (wind-driven tilt or vault response, say), not a bearing.

`BEARING_VALIDATED = False` in `lfloc.py`. While it stays False:

- `bearing` prints `UNVALIDATED` and withholds axes from its text output. Per-hour values stay in `--json` for method testing only; never report them.
- `wind-scan` does not combine with it.

Coherence alone does not show direction: some tonals pass the 0.5 gate with a stable axis, and a stable axis is what the 2017 bias also produces. Re-test before changing the flag. Other years, other stations with 3-component sensors plus BDF (2011–12 TA), or a cleaner transient source could all serve.

## `tdoa`: regional locator for impulsive events (2011-03 to 2012-12): unvalidated

**Stations.** Every BDF within `--radius-km` (100) of TA.545A that is active in the window. That is the TA ring: 545A, 544A (65 km), 645A (66 km), 546A (77 km), 445A (78 km), 444A (79 km) and 646A (82 km).

- **Archive gap:** 546A and 646A have no infrasound after 2012-08-30/31, just after Hurricane Isaac's landfall. From September 2012 the ring has no stations east of 545A, and `tdoa` says so.
- Gating is mandatory: windows over 6 h are refused. A 25-minute window costs about 2 MB.

**Method.**

1. **Picks.** Each BDF trace is causally bandpassed, run through classic STA/LTA, and its triggers kept. Each gap-free piece is triggered separately.
2. **Association.** For each grid node, origin time and celerity, one of a station's picks is the arrival (Gaussian error σ) or none is (weight ε, uniform over the window). A station with no picks carries no information.
3. **Celerity.** By default one celerity is shared by every path, gridded and marginalized. `--celerity-model independent` instead draws a celerity per path, uniformly: the travel-time prior is then a uniform on [d/cmax, d/cmin] convolved with σ, which washes out range.
4. **Region.** The output is the 90% highest-density region over latitude and longitude. Its area, length, width and long axis are reported. When it reaches the grid edge, the region is unbounded.
5. **Status:**
   - `located`: a bounded region, with ≥ 4 stations associated at the most likely point;
   - `bearing_only`: the region reaches the edge but spans ≤ `--max-bearing-span` (30°) seen from the center, so it gives a direction with unconstrained range;
   - `none`: anything else.
6. **Notes.** The output adds a note when the fitted celerity sits on a prior bound, since range is then set by the prior.

**Personal-data seam.** `--picks <csv>` takes arrival picks with the columns `station,lat,lon,time_utc[,weight]` in place of the archive. `--csv` writes the archive picks in that format, rounded to CSV precision. Feeding them back gives identical results; checked 2026-10-17 on Camp Minden.

**Validation protocol.** Fixed 2026-10-17, before any run.

- **Defaults:**
  - band 2–5 Hz (TAIRED's band for the test event), with a causal 4-pole bandpass;
  - classic STA/LTA 2 s / 60 s, trigger on 3.0 and off 1.5, keeping the 3 strongest triggers per station, weighted by peak ratio;
  - σ 4 s;
  - one celerity shared by all paths, gridded over 0.28–0.34 km/s in 0.01 km/s steps and marginalized;
  - outlier weight ε 0.1, uniform over the pick window;
  - grid ±2° around TA.545A at 0.05° spacing, origin-time step 2 s;
  - stations: BDF within 100 km, with at least 4 associated at the most likely point.
- **Test event.** The Black Elk Energy West Delta 32 platform explosion of 2012-11-16, "around 9:00 a.m." CST (≈15:00 UTC).
  - Location from BSEE Panel Report 2013-002: 29.12854, −89.69060.
  - TAIRED lists it at 29.10, −90.00, 14:58:50 UTC, about 30 km west of the BSEE position.
  - Scoring is against BSEE.
- **Pass rule.** The BSEE position lies inside the 90% region, and the error is reported in km.
- **Second test.** Added after the Black Elk run, before running it. It is the Camp Minden explosion: TAIRED 2012-10-16 04:26:40 UTC, 32.58, −93.35, 392 km NW of TA.545A.
  - Defaults as above, except `--box-deg 4 --step-deg 0.1` so that the grid contains the source. Window 04:35–05:00 UTC.
  - The source is far outside the ring, so range is expected to be poor.
  - Pass rule: the source lies inside a 90% region that does not reach the grid edge. The back-azimuth error from 545A is reported.
- **Third test.** Declared after the first two, before running it. It is the 2012-05-17 Mw 4.9 earthquake on the Louisiana–Texas border, ISC 15:12:01 UTC, 32.08, −94.46, 441 km from 545A. All 7 ring stations were recording then.
  - The pick window is acoustic arrivals only: 15:28–15:48 UTC, which is 16–36 min after origin, past the seismic arrivals.
  - Defaults, plus `--box-deg 5 --step-deg 0.1`.
  - Pass rule: status `bearing_only` or `located`, with the true bearing from 545A inside the reported bearing span.
  - Caveat: an earthquake radiates infrasound from its whole shaken area, so it is a weaker test than an explosion.
- **Why not ComCat.** ComCat lists no explosions within 250 km of 545A for 2011-03 to 2012-12 (`lfab events`), so the ground truth is TAIRED, BSEE and ISC.
- **Not independent truth.** The AELUMA detections inside the ring were located from the same TA BDF data. Agreement with them is a consistency check only.

**Results, 2026-10-17: FAIL. Direction only, on one event.**

| Test | Stations with data | Status | Truth | Pre-declared rule |
|---|---|---|---|---|
| Black Elk WD-32, 2012-11-16 ≈15:00 UTC (day) | 5 (546A, 646A gone) | `none`: 3 associate | 73 km outside an unbounded region | FAIL |
| Camp Minden, 2012-10-16 04:26 UTC (night) | 5 | `bearing_only`: span 316–319° | 316.8° from 545A (0.3° off); range unbounded, celerity on the 0.34 bound | FAIL (region reaches the edge) |
| Mw 4.9 LA–TX, 2012-05-17 15:12 UTC (day) | 7 | `none`: span 48°, toward 60–108° | 301.9° | FAIL |

**Why it failed:**

- **Daytime wind noise.** At Black Elk, the true onsets show in the predicted windows: 645A 15:04:06 (STA/LTA 11.9), 445A 15:08:25 (27.4), 444A 15:10:07 (12.4). But 645A had stronger noise triggers, so its onset was not among its top 3, and 545A peaked at only 3.0. In the earthquake window, every station had several triggers of 15–25.
- **Geometry.** All three sources lie outside the ring, so range trades off against celerity and origin time. Black Elk was seen only from the side away from it once 546A and 646A were gone.
- **Path-to-path celerity varies by ~0.03 km/s** (Black Elk: 0.30–0.33 km/s against TAIRED's origin). That is about 30 s at 190 km, far above σ = 4 s.

**Post hoc, for the record:**

- On Black Elk, `--top-k 6` and `--celerity-model independent` were tried after the pre-registered run. All three variants stayed unbounded, and "truth inside" was uninformative there.
- `--box-deg 4` for Camp Minden was chosen when that test was declared. The bearing-span output, the three-state status and the containment caveat were added after seeing Camp Minden.

**Status.** `TDOA_VALIDATED = False`. `tdoa` prints `UNVALIDATED`. Report nothing from it as a finding. A `bearing_only` result at night on a large source is the most it has shown, and that once. Before retesting, improve the picking: pair-wise envelope cross-correlation, as AELUMA does, rather than STA/LTA triggers.

**Prior work and catalogs.** The EarthScope infrasound event products cover 2011–15:
- AELUMA automatic detections (de Groot-Hedlin & Hedlin 2015), with about 940 events in 2011–12;
- TAIRED reference events.

Each event is a `meta_data.json` (~120 KB) under `data.earthscope.org/archive/seismology/products/infrasound/events/<year>/`. Its first 3 KB hold the latitude, longitude and `EventId` (the origin epoch). Within 100 km of 545A there are 6 AELUMA detections, for example 2012-10-03 18:08 at 29.83, −89.90. TAIRED holds the reference events used above.

## Reporting

- Say "the tonal's level depends on wind from X–Y°", not "the source is at X".
- Give the arc, p-value, nights, calm share and ASOS station.
- Give the candidate spread before any ranking. A candidate inside the arc is **consistent with** the data. It is not identified by it.
- Cite:

```
EarthScope Consortium, FDSN dataselect and station services, N4.545B.EP.BDF (doi:10.7914/SN/N4), retrieved <date>.
Iowa Environmental Mesonet, ASOS archive (asos.py), station MSY, retrieved <date>.
Iowa Environmental Mesonet, NEXRAD Level III storm attributes (nexrad_storm_attrs.py), radar LIX, retrieved <date>.
LDEQ ERIC emissions inventory release points, AI 1406, 2024 (via ldeq-eric-emissions), retrieved <date>.
Analysis: bayou lf-source-locate wind-scan (tempered profile likelihood, night-block permutation test).
EarthScope Consortium, TA infrasound event products (AELUMA, TAIRED), data.earthscope.org/archive/seismology/products/infrasound/events/, retrieved <date>.
BSEE Panel Report 2013-002 (Black Elk Energy, West Delta 32 Platform E), for ground truth.
```

## Deferred

These are in SKILL-ROADMAP §14:

- Better `tdoa` picking: envelope cross-correlation between station pairs instead of STA/LTA triggers, and night-only windows. AELUMA (de Groot-Hedlin & Hedlin 2015) does this with triads.
- Field-recording tools: WAV ingest to the features schema, a reference-normalized amplitude survey, two-channel same-clock bearings, and a site-geometry planner.

## Related skills

- `lf-acoustic-baselines` finds stations, PSDs and peaks. Use `psd` to find the tonal before scanning it.
- `ldeq-eric-emissions sources --json` gives the candidate release points.
- `wind-history` covers wind conventions, the ASOS details and the vertical-profile refraction screen.
- `epa-campd-search` hourly operations and `ldeq-edms-search` incidents give the operating-time evidence that geometry cannot.

$ARGUMENTS
