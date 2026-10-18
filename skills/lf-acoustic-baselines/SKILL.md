---
name: lf-acoustic-baselines
description: Public low-frequency acoustic and seismic baselines near a point — EarthScope (IRIS) infrasound microbarometers (BDF), barometers and vertical seismometers with epochs, sample rates and instrument changes; hourly MUSTANG seismic PSDs; response-corrected Welch PSDs computed from archived miniSEED; season-matched before/after spectral comparisons that list new narrowband peaks; infrasound-to-seismic coherence at co-located stations; and USGS ComCat events (earthquakes, explosions, quarry blasts) to rule out non-industrial transients. Use for a historical low-frequency noise baseline before and after a plant expansion, to check whether a tonal near a refinery was present in archived records, or to prepare reference spectra for fenceline infrasound recordings. Retrieval and spectra only; it does not attribute sources.
argument-hint: stations <lat> <lon> | psd <NET.STA.LOC.CHA> --start D [--end D --days N --hours 00-04] | compare <NSLC> --before A..B --after C..D | coherence <NET.STA> --start D | events <lat> <lon> --start D --end D
allowed-tools: Bash, Read
---

# Low-frequency acoustic and seismic baselines

Public archives that record the sound field below 20 Hz near the River Parishes:

- **Infrasound microbarometers** (channel `BDF`, 40 samples/s, pascals). They come from the EarthScope USArray Transportable Array (TA) and its successor, the Central and Eastern US Network (N4).
- **Vertical seismometers** (`HHZ` at 100 sps, `BHZ` at 40 or 20 sps). They record infrasound through air-to-ground coupling, and ground-borne vibration from machinery directly.
- **USGS ComCat** catalogues earthquakes and, sometimes, explosions and quarry blasts.

All of it is open, with no key. Services:

- `service.earthscope.org/fdsnws/station` for inventory and responses;
- `.../fdsnws/dataselect` for miniSEED waveforms;
- `.../mustang/noise-psd` for precomputed hourly seismic PSDs;
- `earthquake.usgs.gov/fdsnws/event/1`.

## Script

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/lf-acoustic-baselines"
L() { uv run -q --no-project --with obspy --with numpy --with scipy python -I "$S/lfab.py" "$@"; }

L health                                                   # station, dataselect, MUSTANG, ComCat
L stations 29.9976 -90.4113 --radius-km 20                 # channels, epochs, loc-code/sensor changes
L psd N4.545B..HHZ --start 2016-06-01 --days 7 --hours 00-04            # MUSTANG path (seismic)
L psd N4.545B.EP.BDF --start 2016-06-01 --end 2016-08-31 --days 10 --hours 00-04   # miniSEED path
L psd N4.545B..HHZ --start 2016-06-01 --days 3 --source mseed --band 5-50          # 0.01 Hz bins
L compare N4.545B..HHZ --before 2015-01..2015-03 --after 2018-01..2018-03 --hours 01-04
L coherence N4.545B --start 2016-06-01 --hours 00-04 --freqs 7.39,14.78
L events 29.9976 -90.4113 --start 2014-01-01 --end 2022-03-01 --radius-km 150
```

Every command takes `--json` and `--refresh`.

**Exit codes:**
- 2: usage error, or an instrument-change refusal from `compare`.
- 3: no data or no stations.
- 4: download refused by the size gate.
- 5: source unavailable.

**Location codes:** pass an empty one as `NET.STA..CHA` (or `--`).

**Hours:** `--hours` uses local time (America/Chicago, so DST is handled), and the end hour is exclusive. Add `--utc` to give UTC hours instead. `22-02` wraps past midnight.

**Day sampling:**
- `--days N` with only `--start` takes N consecutive days.
- With `--end` as well, it takes N days spread evenly across the span.

Sampling the same night hours across many days gives a baseline at a fraction of the cost of a continuous pull.

**Cache:** `~/.cache/bayou/lf-acoustic-baselines/`. Station inventory is kept for one day. Archived waveforms, responses and PSDs are kept indefinitely, because they do not change.

### Download gate

The size estimate is based on 3.5 bytes per sample, measured from a 60 s `N4.545B.EP.BDF` pull (8,192 bytes):
- BDF at 40 sps: about 12 MB per channel-day.
- HHZ at 100 sps: about 30 MB per channel-day.

`psd`, `compare` and `coherence` print the estimate for the windows not already cached before downloading anything. They refuse anything over 50 MB without `--yes` (exit 4). `compare` gates its before and after windows as one total.

**Before passing `--yes`, tell the user the size and get their go-ahead.** Shrinking `--hours` or `--days` is usually enough. A 30-day, 24-hour BDF pull is about 360 MB.

The MUSTANG path downloads only small text PSDs and is not gated.

## What exists near Norco / the River Parishes

Probed 2026-10-17, from `stations 29.9976 -90.4113` at 100 km and 200 km.

| Station | Where | Channels | Dates | Notes |
|---|---|---|---|---|
| **TA.545A** | 30.0441, −90.4894 (St. Charles Parish, ~9 km NW of Norco) | EP.BDF 40 sps, BHZ 40 sps | 2011-03-11 to 2012-12-09 | Transportable Array. BHZ sensor changed 2011-11-23. |
| **N4.545B** | same site | EP.BDF and ..HHZ / ..BHZ: 2014-01-21 to 2019-03-17. 32.BDF and 00.HHZ: 2019-03-01 to 2022-02-24 | 2014 to 2022 | TA.545A adopted into N4. **Location code and sensor metadata change at 2019-03-01.** |
| TA.645A, 646A, 546A, 544A, 445A, 444A | 63–86 km | BDF + BHZ | 2011–2013 | Regional TA only. |
| GS.LA01–10, YC.LA10–21, XW.ESG* | Bayou Corne sinkhole, ~70 km W | BHZ/HHZ/EHZ up to 200 sps | 2012–2017 | Sinkhole monitoring. Dominated by local microseismicity. |
| LI.LTL | LIGO Livingston, 69 km NNW | BHZ, HHZ | metadata 2000 onward | **Waveforms are not served by EarthScope** (dataselect returns 404 for 2015 and 2025). |
| **N4.346B** | Big Creek, Hattiesburg MS, ~179 km NNE | 32.BDF 40 sps, 00.HHZ 100 sps | 2019 to present | Only live public microbarometer within 200 km. Use it as a remote reference for the regional field (microbaroms, weather), never for local tonals. |

**Date limits:**
- There are **no public microbarometers near Norco after 2022-02-24**, and no public seismometer serving waveforms near Norco after that date.
- The local record runs 2011-03 to 2012-12, then 2014-01 to 2022-02.
- 2013 is a gap at this site.

## Reading the results

- **Retrieval vs judgment.** Spectra, peaks, coherence values and event lists are retrieved, and computed from public data. Saying which source made a peak (a flare, a compressor, cooling-tower fans, river traffic, the interstate) is judgment, and has to be labeled that way, with the evidence for it: operating records, wind direction, permit data.
- **Different instruments, different places.** An M23 fenceline recording and an archived BDF trace come from different sensors at different sites:
  - BDF uses a Hyperion or similar microbarometer with a wind-noise filter.
  - The M23 is a measurement microphone.
  - The archive is about 9 km from Norco.

  An archived baseline describes the regional low-frequency sound field at that site in those years. It does not give the level at a fenceline or a home, and the two absolute levels are not directly comparable.
- **Seismometers hear sound and ground.** A peak on HHZ can be airborne sound coupled into the ground, or ground-borne vibration (rotating machinery, pile driving, trains). A seismic peak alone cannot tell them apart.
  - Where BDF and HHZ are co-located (TA.545A 2011–12; N4.545B 2014–22), `coherence` at the peak frequency is the test. High coherence (roughly above 0.5) means the two sensors see the same pressure field. Low coherence means ground-borne vibration, or wind noise on one sensor.
  - Expect near-zero coherence at the 0.2 Hz microbarom peak. The seismometer there is dominated by ocean microseisms, not air pressure.
- **Nyquist limits.**
  - BDF at 40 sps stops at 20 Hz, below many cooling-tower blade-pass and large-fan frequencies.
  - HHZ at 100 sps reaches 50 Hz.
  - LDF/LDO at 1 sps resolve only below 0.5 Hz.
- **MUSTANG vs miniSEED.**
  - MUSTANG PSDs are hourly and smoothed over 1/8 octave, so a tonal is broadened and lowered.
  - `--source mseed` computes 100 s Welch segments (0.01 Hz bins) from the waveform after removing the instrument response.
  - MUSTANG has **no infrasound PSDs**: noise-psd returns 404 for every BDF target tried. BDF always takes the miniSEED path.
- **Validation of the miniSEED path.** For N4.545B..HHZ, 2016-06-01..03, 06–10 local, the miniSEED Welch medians agree with MUSTANG within 2 dB from 0.2 to 5 Hz. This confirms the response removal and the density scaling, and the BDF path shares that code.
  - From about 10 Hz to 43 Hz, the miniSEED path reads 4–6 dB lower. The cause has not been found; 1/8-octave averaging does not explain it.
  - So treat absolute levels above 10 Hz as uncertain by ±6 dB between the two paths. Never set a MUSTANG spectrum against a miniSEED one. `compare` uses one path for both windows.
- **Microbarom indicator.** `psd` prints the 0.15–0.4 Hz band against 0.6–1 Hz and against 0.05–0.1 Hz. It reports a bump only when the band stands above both.
  - On N4.545B.EP.BDF, 2016-06-01 00–02 local, it was +10.6 dB and −3.0 dB: no bump. The spectrum is red, with long-period pressure noise dominating.
  - The indicator describes the spectrum. It does not validate the response, since a wrong response could also produce a red slope.
  - The archived BDF response is flat from 0.1 to 19.5 Hz. Energy that rises toward 20 Hz is in the recorded data (local sources, or aliasing), not created by the deconvolution.
- **Data gaps.** Only gap-free hours become spectra. `psd` and `compare` print how many of the expected hours survived. `compare` flags a window where fewer than half did.
- **Instrument continuity.** `compare` refuses to compare across a location-code or sensor change unless `--allow-epoch-change` is passed. A level step at an instrument swap is not evidence of a new source. At N4.545B, 2019-03-01 is such a boundary (EP→32 BDF, blank→00 HHZ). Even with the flag, state that the comparison crosses instruments.
  - **Unchanged metadata does not prove an unchanged instrument.** N4.545B.EP.BDF is one metadata epoch from 2014 to 2019. Yet June 2018 nights fall 16–41 dB below June 2015 from 6 to 16 Hz (3 sampled nights each), a smooth broadband drop that looks like an inlet, wind-filter or sensor change, not a quieter neighborhood. `compare` notes any change of 20 dB or more. Check the station's data-quality history (MUSTANG metrics, EarthScope station logs) before reporting such a change as a change in the sound field.
- **Seasons and wind.** Wind noise, microbarom strength and traffic vary by season and time of day. Use the same calendar months in each year (`compare` notes it when the windows share none), and night hours.
  - Daytime wind noise swamps a BDF below about 1 Hz.
  - Check `wind-history` for the hours sampled.
- **Peaks.** A peak is a local maximum standing at least `--min-prominence` dB (default 6) above a running median over ±1/3 octave.
  - `compare` lists the after-window peaks that have no before-window peak within 2 bins and gained at least `--min-change` dB (default 3).
  - **Persistence** is the share of individual hourly after-spectra that show the peak on their own. A peak under 50% is marked intermittent.
- **ComCat** rarely lists non-earthquake events in Louisiana: one event within 150 km of Norco from 2010 to 2026. An empty list does not rule out a blast or a boom.

## Citation format

```
EarthScope Consortium, FDSN dataselect and station web services, N4.545B.EP.BDF, 2016-06-01 05:00–07:00 UTC
  (https://service.earthscope.org/fdsnws/dataselect/1/query?net=N4&sta=545B&loc=EP&cha=BDF&...), retrieved 2026-10-17.
  PSD computed by bayou lf-acoustic-baselines: response removed (StationXML), 100 s Hann Welch, hourly medians.
EarthScope MUSTANG noise-psd, N4.545B..HHZ, 2016-06-01..03 06:00–10:00 CDT, retrieved 2026-10-17.
USGS ComCat (https://earthquake.usgs.gov/fdsnws/event/1/query?...), retrieved 2026-10-17.
```

Network citations (DOIs resolve to the FDSN network pages; checked 2026-10-17):
- TA: "USArray Transportable Array (2003), International Federation of Digital Seismograph Networks, doi:10.7914/SN/TA".
- N4: "Central and Eastern US Network (2013), doi:10.7914/SN/N4".

## Related skills

- `lf-source-locate` asks which direction a tonal found here comes from: `wind-scan` gives a wind-conditioned bearing arc with ERIC candidates. It is inference and lives outside this skill's retrieval-only charter.
- `wind-history` covers surface wind for the sampled hours and the vertical profile and refraction screen (Step 4).
- `ldeq-eric-emissions sources` lists candidate low-frequency sources: flares, engines, turbines, compressors, cooling towers.
- `epa-campd-search` gives hourly unit operation for the windows compared.
- `ldeq-edms-search` holds incident reports for transient events.

$ARGUMENTS
