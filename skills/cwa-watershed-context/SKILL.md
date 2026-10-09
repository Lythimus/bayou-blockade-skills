---
name: cwa-watershed-context
description: Receiving-water context for an NPDES/LPDES discharge permit — the facility's HUC12/HUC8 watersheds, the 303(d)-listed assessment units it discharges to and their causes, TMDLs and whether the permit holds a wasteload allocation, every other discharger in the watershed ranked by EPA-calculated loads and effluent exceedances, and the applicant's own limits, exceedances and multi-year DMR vs TRI loads
allowed-tools: Bash, AskUserQuestion
---

# CWA Watershed Context

Put a water discharge permit in the context of the water it discharges to. The questions are:
- Is the receiving water already impaired, and for what?
- Is there a TMDL, and does the permit hold an allocation under it?
- Who else discharges into the same watershed, and how much?
- Does the applicant exceed its own limits?

This is the data behind the `water-lpdes` and `water-401` questions in `bayou:permit-analysis` (see "Mapping to permit-analysis questions" below).

All sources are EPA or USGS, and only one needs a key:
- **ECHO Detailed Facility Report (DFR).** Gives the facility's watersheds and the assessment units it is linked to.
- **ECHO Water Pollutant Loading Tool** (`dmr_rest_services`). Gives calculated loads, exceedances, and permit limits.
- **ECHO effluent charts** (`eff_rest_services`). Give DMR values against limits.
- **ECHO CWA facility search** (`cwa_rest_services`). Gives watershed violation rollups.
- **EPA ATTAINS.** Gives 303(d) assessments and TMDLs. This is the one that needs an api.data.gov key.
- **USGS Watershed Boundary Dataset (WBD).** Turns a point into a HUC12.

This skill replaces EDGI's ECHO-Watershed notebook. That notebook depends on EDGI's token-gated Stony Brook database and is fixed to 2022 data. This skill runs the same workflow (place → watershed → dischargers → violators → pollutants) on EPA's live services, then adds impairment and TMDL context.

## Parsing arguments

The user may provide:
- An **NPDES/LPDES permit ID** (e.g. `LA0003522`). This is the best input.
- An **FRS registry ID** (12 digits, e.g. `110013831201`).
- A **facility name**. Resolve it first with `bayou:epa-frs-crosswalk` (program `NPDES`), confirm by street address, then continue with the permit ID.
- A **lat/lon** for a proposed outfall or a site with no permit yet. This uses the WBD path in Step 1b.
- An optional **year** for loads (default: the last complete DMR year, currently `2024`).

## Step 0: ATTAINS key

```bash
KEY=$(rg '^ATTAINS_API_KEY:' ~/.claude/bayou-credentials.md 2>/dev/null | cut -d' ' -f2); KEY=${KEY:-DEMO_KEY}
```

ATTAINS moved behind api.data.gov:
- The old host `attains.epa.gov/attains-public/api/...` returns **401**. The working base URL is `https://api.epa.gov/attains/`.
- `DEMO_KEY` throttled after about five calls in testing. A registered key reported `x-ratelimit-remaining: 999`, i.e. about 1,000/hr (verified live 2026-10-08).
- Any api.data.gov key works. The `CAMPD_API_KEY` returned 200 on ATTAINS too.
- If the user has neither key, tell them to register at https://api.data.gov/signup/ (instant, free) and add the key as `ATTAINS_API_KEY` in `~/.claude/bayou-credentials.md` (template: `bayou-credentials.example.md`).

**Every snippet below that calls ATTAINS needs this line run first in the same shell.**

## Step 1a: Facility → receiving waters (DFR)

The DFR takes either the permit ID or the registry ID as `p_id`. It gives two things ECHO has already joined:
- **every HUC12 the facility is tied to**;
- **the assessment units (AUs) it is linked to.**

Use it instead of a point-in-polygon lookup whenever there is a facility. Shell Norco (`LA0003522`) is tied to **two** HUC12s in **two** HUC8s:
- `080901000101` Mississippi River–Bonnet Carré Spillway (HUC8 `08090100`)
- `080902030101` Bayou La Branche–Frontal Lake Pontchartrain (HUC8 `08090203`)

Its coordinates fall in only the second (verified live 2026-10-08).

```bash
ID="LA0003522"   # NPDES permit ID or FRS registry ID
curl -s "https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?output=JSON&p_id=${ID}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'):
    sys.exit('ERROR: %s' % r['Error'])
print('Registry ID:', r.get('RegistryID'))
print('CWA permits:', [(p.get('SourceID'), p.get('FacilityStatus')) for p in r.get('Permits', []) if p.get('Statute') == 'CWA'])
for w in (r.get('Watersheds') or {}).get('WBD12s', []):
    print('HUC12', w['WBD12'], '(HUC8', w['WBD12'][:8] + ')', w['WBD12Name'])
    print('   ICIS receiving water:', w.get('ICISWaterBodyNames'))
    print('   ECHO possible impairing params:', w.get('PossibleImpairingParameters'))
    print('   ...of which E90 (exceedance) params:', w.get('E90PossibleImpairingParameters'))
    print('   ESA-listed aquatic species in HUC12:', w.get('EsaAquaticSpeciesFlg'))
for a in (r.get('AssessedWaters') or {}).get('AssessmentUnits', []):
    print('AU', a['AssessmentUnitIdentifier'], '|', a['AssessmentUnitName'], '|', a['WaterCondition'],
          '|', a.get('CauseGroupsImpaired'), '| cycle', a.get('ReportingCycle'), '|', a.get('AUURL'))
"
```

**`PossibleImpairingParameters` is ECHO's screening match, not a finding.** It lists the facility's DMR parameters that ECHO associates with impairments in its watersheds, and `E90PossibleImpairingParameters` is the subset with effluent exceedances.
- For Norco it lists Hexachlorobenzene. The linked AU `LA070301_00` (Mississippi River) is 303(d)-listed for HEXACHLOROBENZENE.
- Present this as "ECHO flags X as possibly contributing to impairment". Never present it as "X causes the impairment".

The DFR lists **every** CWA permit at the site, including general-permit coverages (e.g. `LAG480897`) and expired ones. Carry all of them into Step 2's WLA check.

## Step 1b: Lat/lon → HUC12 (no facility yet)

```bash
LAT=30.28; LON=-90.55
curl -s "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/6/query?geometry=${LON},${LAT}&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=huc12,name&returnGeometry=false&f=json" | python3 -I -c "
import json, sys
f = json.load(sys.stdin).get('features', [])
if not f:
    sys.exit('NOT FOUND: point is outside the WBD (offshore or bad coordinates)')
for x in f:
    a = x['attributes']; print('HUC12', a['huc12'], '(HUC8', a['huc12'][:8] + ')', a['name'])
"
```

- Layer 6 is HUC12. Its fields are `huc12` and `name`.
- Example: `30.28,-90.55` → `080702040400` Lake Maurepas (verified live 2026-10-08).
- The HUC8 is the first 8 digits.
- With no DFR there is no AU linkage. Take the AU list from ATTAINS `huc12summary` in Step 2.
  - That list covers every AU in the HUC12, not just the one the outfall reaches.
  - Ask the user which waterbody the outfall discharges to, or read it from the application (`bayou:ldeq-edms-search`).

## Step 2: Impairments, TMDLs and wasteload allocations (ATTAINS)

This script runs for each HUC12 and each AU. It prints:
- the HUC12 summary;
- each AU's causes and the TMDL actions linked to them;
- each TMDL's allocated pollutants, its document link, and whether any of the applicant's permit IDs holds a wasteload allocation (WLA).

```bash
KEY=$(rg '^ATTAINS_API_KEY:' ~/.claude/bayou-credentials.md 2>/dev/null | cut -d' ' -f2); KEY=${KEY:-DEMO_KEY}
HUC12S="080901000101,080902030101"        # from Step 1
AUS="LA041202_00,LA070301_00"             # DFR AUs; leave empty to use every AU in the HUC12s
PERMITS="LA0003522,LAG480897,LA0109606,LAJ650098,LAG480000"   # all site permits + general-permit master IDs
python3 -I - "$KEY" "$HUC12S" "$AUS" "$PERMITS" <<'PY'
import json, re, sys, time, urllib.request, urllib.parse
key, hucs, aus, permits = sys.argv[1], sys.argv[2].split(','), [a for a in sys.argv[3].split(',') if a], set(sys.argv[4].split(','))
B = 'https://api.epa.gov/attains/'
def get(ep, **q):
    q['api_key'] = key
    for attempt in range(3):
        try:
            with urllib.request.urlopen(B + ep + '?' + urllib.parse.urlencode(q), timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2: time.sleep(5); continue
            sys.exit('ATTAINS %s HTTP %s (429 = key throttled; DEMO_KEY hits this fast)' % (ep, e.code))
# The same water appears as LA-041201 and LA041201_00 inside one TMDL record.
norm = lambda s: re.sub(r'[^A-Z0-9]', '', s.upper().split('_')[0])
au_set = list(aus)
for h in hucs:
    it = (get('huc12summary', huc=h).get('items') or [{}])[0]
    print('== HUC12 %s: %s AUs, %.0f%% of catchment in impaired waters, %.0f%% in waters with a restoration plan'
          % (h, it.get('assessmentUnitCount'), it.get('containImpairedWatersCatchmentAreaPercent') or 0, it.get('containRestorationCatchmentAreaPercent') or 0))
    for p in it.get('summaryByParameterImpairments', []):
        print('   impaired for %-40s %5.1f%% of catchment, %s AU(s)' % (p['parameterGroupName'], p['catchmentSizePercent'], p['assessmentUnitCount']))
    if not aus:
        au_set += [a['assessmentUnitId'] for a in it.get('assessmentUnits', [])]
actions = {}
for au in dict.fromkeys(au_set):
    meta = (get('assessmentUnits', assessmentUnitIdentifier=au).get('items') or [{}])[0]
    org = meta.get('organizationIdentifier')
    if not org:
        print('AU %s: NOT FOUND in ATTAINS' % au); continue
    u = meta['assessmentUnits'][0]
    a = next(iter(x for i in get('assessments', organizationId=org, assessmentUnitIdentifier=au).get('items', []) for x in i.get('assessments', [])), None)
    print('\nAU %s (%s) %s, %s %s' % (au, org, u['assessmentUnitName'], u['waterTypes'][0]['waterSizeNumber'], u['waterTypes'][0]['unitsCode']))
    if not a:
        print('   no assessment record (unassessed is not the same as unimpaired)')
    else:
        print('   IR category %s, overall %s' % (a.get('epaIRCategory'), a.get('overallStatus')))
        for p in a.get('parameters', []):
            ids = [x['associatedActionIdentifier'] for x in p.get('associatedActions', [])]
            uses = '; '.join('%s: %s' % (x['associatedUseName'], x['parameterAttainmentCode']) for x in p.get('associatedUses', []))
            print('   %-8s %-45s %s %s' % (p['parameterStatusName'], p['parameterName'], uses, ('TMDL/action ' + ','.join(ids)) if ids else '| no linked action'))
            for i in ids: actions.setdefault(i, org)
    # Actions tied to the AU but not to a current cause (e.g. a TMDL for a delisted cause) only show up here.
    for i in get('actions', organizationId=org, assessmentUnitIdentifier=au).get('items', []):
        for x in i.get('actions', []):
            if x['actionIdentifier'] not in actions:
                print('   AU-level action %s %s (not linked to a current cause)' % (x['actionIdentifier'], x['actionTypeCode']))
            actions.setdefault(x['actionIdentifier'], org)
for aid, org in actions.items():
    x = next(iter(y for i in get('actions', organizationId=org, actionIdentifier=aid).get('items', []) for y in i.get('actions', [])), None)
    if not x:
        print('\nACTION %s: NOT FOUND' % aid); continue
    print('\nACTION %s %s %s (%s, %s)' % (aid, x['actionTypeCode'], x['actionName'], x['actionStatusCode'], x.get('completionDate')))
    for d in x.get('documents', []):
        print('   doc:', d.get('documentURL'))
    hit = False
    for w in x['associatedWaters']['specificWaters']:
        print('   water %s (key %s): %s' % (w['assessmentUnitIdentifier'], norm(w['assessmentUnitIdentifier']), ', '.join(sorted({p['pollutantName'] for p in w.get('associatedPollutants', [])}))))
        for p in w.get('associatedPollutants', []):
            for s in p.get('permits', []):
                if s['NPDESIdentifier'] in permits:
                    hit = True
                    for d in s.get('details', []):
                        print('   ** WLA %s %s: %s %s' % (s['NPDESIdentifier'], p['pollutantName'], d['wasteLoadAllocationNumeric'], d['wasteLoadAllocationUnitsText']))
    if not hit:
        print('   no WLA found under IDs %s' % ','.join(sorted(permits)))
PY
```

Verified live 2026-10-08 for Norco:
- HUC12 `080902030101` has 9 AUs, and 100% of its catchment is in impaired waters. Pathogens account for 100%, organic enrichment/oxygen depletion for 68%, and nutrients for 35%.
- `LA041202_00` (Bayou Trepagnier, Norco to Bayou LaBranche) is category 5. Causes are DISSOLVED OXYGEN and ENTEROCOCCUS, **with no linked TMDL**.
- `LA070301_00` (Mississippi River) is listed for HEXACHLOROBENZENE, also with no linked action.
- Neighboring `LA041201_00` (Bayou LaBranche) links to TMDL action `41667`, the 2012 DO TMDL.
  - That TMDL allocates CBOD, nitrogen, ammonia and phosphorus.
  - It carries WLAs for `LAR041032` (CBOD 60.3 lb/day) and `LAG530000`.

### ATTAINS traps
- **`assessments` and `actions` require `organizationId`** (Louisiana: `LADEQWPD`). Without it, `assessments` returns `"validation error: Please check the assessment query parameters"`. The script reads the org from `assessmentUnits`, which works without it.
- **Find actions two ways.** Use the `associatedActions` on each cause, and also `actions?assessmentUnitIdentifier=AU`. Both returned `41667` for `LA041201_00`. The script runs both, because a TMDL for a cause that has since been delisted only shows up in the AU query.
- **The restoration percentages in `huc12summary` can't be traced to records.**
  - `summaryRestorationPlans` was empty for both test HUC12s.
  - For Lake Maurepas (`080702040400`), `containRestorationCatchmentAreaPercent` was 98%, yet neither the cause links nor the AU actions query returned any action for its AUs.
  - Treat the percentage as a prompt to check LDEQ's TMDL list, not as evidence a TMDL exists. Never read "no TMDL" from an empty `summaryRestorationPlans`.
- **AU IDs appear in two forms inside one TMDL record** (`LA-041201` and `LA041201_00`). Compare on the normalized key the script prints.
- **WLAs may be listed under a general-permit master ID** (e.g. `LAG530000`), not the individual coverage number. Include the master ID of every general permit the site holds in `PERMITS`.
  - A miss means **"no WLA found under these IDs"**, never "the permit has no allocation".
  - The TMDL PDF (the `doc:` link) is authoritative.
- The TMDL `doc:` links (`api.epa.gov/attains/documents/...`) download the PDF without a key. Action 41667 is a 1.1 MB PDF (verified 2026-10-08).
- ATTAINS AU IDs for Louisiana are LDEQ subsegment numbers (e.g. `LA041202_00` ↔ subsegment 041202). Use them to cross-reference the LAC 33:IX Chapter 11 water-quality standards tables.

## Step 3: Who else discharges into the watershed (Loading Tool)

Run once per HUC12 and once per distinct HUC8 from Step 1. `p_huc` takes either length on these endpoints.

```bash
YEAR=2024
# Literal list, not a $VAR: zsh does not word-split unquoted variables in a for loop.
for H in 080902030101 08090203 080901000101 08090100; do
curl -s "https://echodata.epa.gov/echo/dmr_rest_services.get_dmr_loadings?output=JSON&p_year=${YEAR}&p_huc=${H}" > "$TMPDIR/load_all.json"
curl -s "https://echodata.epa.gov/echo/dmr_rest_services.get_dmr_loadings?output=JSON&p_year=${YEAR}&p_huc=${H}&p_imp_poll=Y" > "$TMPDIR/load_imp.json"
python3 -I - "$H" "$TMPDIR/load_all.json" "$TMPDIR/load_imp.json" <<'PY'
import json, sys
h = sys.argv[1]
for label, path in (('ALL dischargers', sys.argv[2]), ('discharging a pollutant ECHO links to the impairment (p_imp_poll=Y)', sys.argv[3])):
    r = json.load(open(path))['Results']
    if r.get('Error'):
        print(h, 'ERROR', r['Error']); continue
    c = r['FacilityCounts']
    print('\n== %s %s: %s facilities (%s major), %s with DMR data' % (h, label, c['AllFacs'], c['AllMajor'], c['WithPermitData']))
    for p in r.get('TopPollutantPounds', []):
        print('   %-45s %12s lb  over-limit %8s lb  QC %s' % (p['PollutantDesc'], p['TotalPounds'], p['LoadOverLimit'], p.get('QcFlag')))
    for f in r.get('TopFacilityPounds', []):
        print('   %s %-45s %-40s %12s lb  exceed %s  QC %s' % (f['ExternalPermitNmbr'], f['FacilityName'][:45], f['PollutantDesc'][:40], f['TotalPounds'], f['ExceedanceFlag'], f.get('QcFlag')))
PY
done
```

Verified live 2026-10-08, year 2024:
- **HUC12 `080902030101`:** 55 facilities in total, 19 with `p_imp_poll=Y`.
  - The top facility-pollutant row is Valero St. Charles `LA0052051` COD at 1,580,220 lb.
- **HUC8 `08090203`:** 463 facilities in total, 84 with `p_imp_poll=Y`.
- **Filter traps:**
  - `p_imp_poll=Y` really does filter: 19 vs 55, compared against the unfiltered run.
  - `p_imp_water=Y` (discharges *to* impaired water) is a different, broader filter. Use it only for the "how much of the load goes into impaired water" framing.
  - `p_poll_name` **did not filter**: plain names returned the unfiltered 463, and the exact DMR name returned nothing. For one pollutant, use `get_multiyear_loading` per permit (Step 4), or the ECHO web Loading Tool.
- `TopFacilityPounds` and `TopPollutantPounds` each return only the top 10.

Per-HUC12 totals and the full facility roster:

```bash
YEAR=2024; HUC8=08090203; HUC12=080902030101
curl -s "https://echodata.epa.gov/echo/dmr_rest_services.get_watershed_stats?output=JSON&p_huc=${HUC8}&p_year=${YEAR}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
for w in r['Watersheds']:
    mark = '  <==' if w['Huc12Code'] == '${HUC12}' else ''
    print(w['Huc12Code'], w['Huc12Name'][:45].ljust(45), 'DMR facs', w['DmrFacCount'].rjust(3), '| lb', w['DmrLby'].rjust(11), '| TWPE', w['DmrTwpe'].rjust(8), '| N lb', w['DmrTotalNLby'].rjust(10), '| P lb', w['DmrTotalPLby'].rjust(9), mark)
"
curl -s "https://echodata.epa.gov/echo/dmr_rest_services.get_watershed_facilities?output=JSON&p_huc=${HUC12}&p_year=${YEAR}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
rows = next(v for v in r.values() if isinstance(v, list))
print(len(rows), 'facilities')
for f in rows: print(f.get('NPDESIDs'), '|', f.get('FacilityName'), '|', f.get('MajorMinor'), '|', f.get('SicCode'), '|', f.get('Latitude'), f.get('Longitude'))
"
```

Verified 2026-10-08:
- HUC8 `08090203` returns 20 HUC12 rows. `080902030101` has 25 DMR facilities and 4,285,941 lb.
- HUC8 `08090100` returns 13 rows. `080901000101` has 21 DMR facilities and 11,291,475 lb, of which 4.5M lb is nitrogen, nearly all from POTWs.
- **`get_watershed_stats` carries no `QcFlag`, and it can return impossible totals.** For 2024, `080902030103` (Metairie Canal) showed **60,288,237,621 lb**. That is almost certainly a units error in one facility's DMR.
  - Before citing any HUC12 total, sanity-check it against `get_dmr_loadings` for that HUC12, which does carry `QcFlag`.
  - Never quote a total that is out of scale with its neighbors.
- **`get_watershed_facilities` `MajorMinor` can disagree with the per-permit flag.** It lists Norco as "Minor", while the effluent chart's `CWPMajorMinorStatusFlag` for `LA0003522` is `M`. Use the per-permit value.
- **`LAS…` IDs are MS4 stormwater permits.** Their calculated loads can dominate a HUC8: in 2024, `LAS000301` (Sewerage & Water Board, East Bank) reported 97M lb TDS in `08090203`. Report MS4 loads separately from process and sanitary dischargers.

Watershed violators (effluent exceedances), plus the CWA compliance rollup:

```bash
HUC=080902030101; START=2022; END=2024
curl -s "https://echodata.epa.gov/echo/dmr_rest_services.get_eff_exceedances?output=JSON&p_huc=${HUC}&p_start_year=${START}&p_end_year=${END}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
rows = r.get('FacilityExceedances', [])
print(r.get('QueryRows'), 'facilities with exceedances; page holds', len(rows))
for f in sorted(rows, key=lambda f: -int(f.get('FacTotalE90') or 0)):
    print(f['ExternalPermitNmbr'], f['FacilityName'][:45].ljust(45), 'E90', (f.get('FacTotalE90') or '0').rjust(4), '| over-limit lb', f.get('LoadOverLimit'), '| SNC qtrs', f.get('QrtsSNC'), '|', f.get('PermitStatus'), 'exp', f.get('ExpirationDate'))
"
# 12-digit HUC → p_wbd. A 12-digit p_huc is silently ignored here and runs nationwide.
curl -s "https://echodata.epa.gov/echo/cwa_rest_services.get_facilities?output=JSON&p_wbd=${HUC}&p_act=Y" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
print('active CWA facilities', r['QueryRows'], '| in significant violation', r['SVRows'], '| violation in last 4 qtrs', r['VioLast4QRows'], '| penalties (all programs)', r['TotalPenalties'])
"
```

- `get_eff_exceedances` accepts a 12-digit `p_huc`. `080902030101` returned 16 facilities for 2022–2024, against 80 for HUC8 `08090203`, led by Bunge `LA0036455` (36 E90, 5 SNC quarters). The whole result came back on one page.
- `cwa_rest_services.get_facilities` takes **`p_wbd`** for a HUC12 and `p_huc` for a HUC8.
  - A 12-digit `p_huc` there is silently ignored, and the query runs against all 543,872 facilities. Always compare the counts.
  - Verified 2026-10-08: `p_wbd=080902030101` returned 53 active, 3 in significant violation (SV), 13 with a violation in the last 4 quarters, and $6,125 in penalties. `p_huc=08090203` returned 418 active and 48 SV.
- `TotalPenalties` covers all programs at those facilities, not only CWA.

## Step 4: The applicant's own record

```bash
P=LA0003522; YEAR=2024
D="https://echodata.epa.gov/echo/dmr_rest_services"
curl -s "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?p_id=${P}&output=JSON" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
print(r['CWPName'], '|', r['CWPPermitTypeDesc'], '| status', r['CWPPermitStatusDesc'], '| major/minor', r['CWPMajorMinorStatusFlag'], '| current SNC', r.get('CWPCurrentSNCStatus'), '| window', r['StartDate'], '-', r['EndDate'])
for f in r.get('PermFeatures', []):
    for p in f['Parameters']:
        ex = [m for m in p['DischargeMonitoringReports'] if m.get('ExceedencePct')]
        if ex:
            print('  outfall', f['PermFeatureNmbr'], p['ParameterDesc'], '-', len(ex), 'exceedances, e.g.',
                  ', '.join('%s %s' % (m['MonitoringPeriodEndDate'], m['ExceedencePct']) for m in ex[:3]))
"
curl -s "${D}.get_permit_limits?output=JSON&p_permit_id=${P}&p_year=${YEAR}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
for l in r.get('PermitLimits', []):
    print('outfall', l['PermFeatureNmbr'], '|', l['PollutantDesc'], '|', l['LimitQuantity1'], l['LimitQuantity1Basis'], '/', l['LimitQuantity2'], l['LimitQuantity2Basis'], '| conc', l['LimitConc1'], '/', l['LimitConc2'], '|', l['MonitoringFrequency'], '| until', l['EndMonitoringDate'])
"
curl -s "${D}.get_multiyear_loading?output=JSON&p_permit_id=${P}&p_start_year=2010&p_end_year=${YEAR}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
for g in r.get('ChemicalGroups', []):
    print(g['ChemicalGroupName'], '(TRI-covered: %s)' % g['CoveredByTRI'])
    for y in g['ChemicalGroupDischarges']:
        print('   ', y['ReportingYear'], 'DMR lb', (y['DmrPounds'] or '--').rjust(10), '| TRI direct lb', (y['TriDirectPounds'] or '--').rjust(10), '| QC', y['QcFlag'])
"
curl -s "${D}.get_eff_exceedances?output=JSON&p_permit_id=${P}&p_start_year=$((YEAR-2))&p_end_year=${YEAR}" | python3 -I -c "
import json, sys
r = json.load(sys.stdin)['Results']
if r.get('Error'): sys.exit('ERROR: %s' % r['Error'])
for f in r.get('FacilityExceedances', []):
    print(f['ExternalPermitNmbr'], 'E90 total', f['FacTotalE90'], '| over-limit lb', f['LoadOverLimit'], '| SNC qtrs', f['QrtsSNC'], '| last inspection', f['DateLastInsp'], '| last formal action', f['DateLastFea'])
    for y in f.get('ExceedanceYears', []): print('   ', y['Year'], y['ViolationCount'], 'exceedances, over-limit lb', y['LoadOverLimit'])
"
```

Verified live 2026-10-08 for `LA0003522`:
- **Permit status.** The status is "Admin Continued": the permit expired 10/31/2025 and has not been renewed, so the old permit remains in force. Flag this, because the repermit is the comment opportunity.
- **Limits.** 32 limit rows, e.g. outfall 002 Ammonia as N at 287 lb/d average and 623 lb/d maximum.
- **Exceedances.** 23 E90 exceedances in 2022–2024 (7, 8 and 8 per year), with 5,404 lb over the limit in 2022.
  - On the effluent chart (07/2023–10/2026), outfall 002 exceeded for BOD (5), TSS (4), sulfide (7), and pH excursions.
  - `ExceedencePct` is either a percentage string such as `23%`, or the literal `LIMIT VIOLATION`.
- **Linked pollutants.** Outfall 002 carries a **Hexachlorobenzene** limit (0.1952 lb/d average). The DFR-linked AU `LA070301_00` (Mississippi River) is 303(d)-listed for HEXACHLOROBENZENE (Drinking Water Supply use).
  - BOD, which has exceedances, is an oxygen-demanding parameter. Bayou Trepagnier (`LA041202_00`) is listed for dissolved oxygen.
  - This is the worked example of the linkage step below.
- **DMR vs TRI.** `get_multiyear_loading` returns 23 chemical groups for 2010–2024. Ammonia DMR pounds run about 10× TRI direct-release pounds (2015: 18,771 vs 1,912).
  - When DMR and TRI disagree like that, say so. Both are self-reported, but DMR loads are calculated from outfall monitoring, while TRI allows estimation methods.
  - Never silently pick one.
- **A calculated load of 0 lb is not zero discharge.** `get_multiyear_loading` shows Norco BOD as 0 lb for 2024 and ammonia as 0 lb for 2021 and 2024. But the effluent chart shows BOD limit exceedances at outfall 002 in 2024.
  - A 0 in a year when the permit carried limits means the Loading Tool did not compute a load (missing DMRs, NODI codes, or a reporting gap).
  - Report it as "no calculated load", and check the effluent chart.
- **Effluent chart window.** It covers about three years by default (`StartDate`/`EndDate`). For older DMR detail, use `get_monitoring_data_csv` (`p_npdes_id`, `p_start_date`, `p_end_date`).

## Step 5: Compliance history older than five years

ECHO REST compliance rollups cover recent years only. For older quarterly noncompliance, stream `NPDES_QNCR_HISTORY.csv` from the ECHO bulk `npdes_downloads.zip` on `NPDES_ID`. Use the "Full history: ECHO bulk downloads" section of `bayou:epa-echo-search`. That section also covers the cache path and the `YEARQTR` format.

## Linking pollutants to impairment causes

This is the core analytic step. **Do not match by string.** ATTAINS causes and DMR parameters use different vocabularies:
- Many causes are *conditions*, not pollutants (DISSOLVED OXYGEN, PH LOW, ENTEROCOCCUS, TURBIDITY).
- DMR names differ (`BOD, 5-day, 20 deg. C`, `Nitrogen, ammonia total [as N]`).
- A string match finds almost nothing and makes the report read falsely clean.

Bridge them with EPA's own linkages, and label every one as **screening**:
1. **TMDL `associatedPollutants`** (Step 2). This is the agency's statement of which pollutants drive a cause. Example: the Bayou LaBranche DO TMDL lists CBOD, BOD, ammonia, nitrogen and phosphorus. A permit with BOD or ammonia limits that discharges to a DO-impaired AU covered by that TMDL is a linked pollutant.
2. **DFR `PossibleImpairingParameters`** and the Loading Tool's **`p_imp_poll=Y`** (Steps 1a and 3). These are ECHO's mapping from DMR parameters to impairments.
3. When a cause is a condition and **no TMDL names its pollutants** (e.g. `LA041202_00` DO), write **"no pollutant-level linkage available in ATTAINS"**, never "no match".
   - It is reasonable to note that oxygen-demanding parameters (BOD, COD, ammonia) are the conventional drivers of low DO.
   - Present that as general knowledge, and point to the TMDL or the LDEQ water-quality assessment for confirmation.

**Regulatory screening flags.** Raise a flag when the discharge goes to an AU that is 303(d)-listed (IR category 5) and carries a pollutant linked to that listing by (1) or (2). Which provision to name depends on what the applicant is. Classify the applicant from the application or fact sheet. Every flag reads "...; needs legal review". These flags are for counsel. They are not legal conclusions and must not go into a public comment as one.

| Applicant | Flag | What this skill supplies |
|---|---|---|
| **New source or new discharger** (as defined in 40 CFR 122.2) | "possible **40 CFR 122.4(i)** issue (new discharger to impaired water)" | 122.4(i) requires a new discharger into a water that has a load allocation for the pollutant to show there is remaining allocation. The Step 2 TMDL/WLA output is that data. |
| **Existing discharger, renewal** (e.g. Norco, Admin Continued) | "check **40 CFR 122.44(d)(1)(i)** reasonable potential for a water-quality-based limit on [pollutant]" | The linked pollutant, plus the applicant's calculated loads and exceedances. |
| **Existing discharger with a WLA** (Step 2 hit) | "check consistency with the WLA, **40 CFR 122.44(d)(1)(vii)(B)**" | The permit limit (Step 4) beside the WLA, with units converted to match. |
| **Expansion** (increased limits or a new outfall at an existing discharger) | "check **antidegradation** (40 CFR 131.12; Louisiana's implementation in LAC 33:IX Chapter 11)" | Impairment status and cumulative watershed load. |

122.4(i) applies only to new sources and new dischargers. Do not cite it for a renewal or an expansion.

## How to present results

1. **Receiving water.** Give:
   - the HUC12(s) and HUC8(s) with names;
   - the ICIS receiving-water name;
   - each linked AU with its IR category and causes, plus its How's My Waterway link (`AUURL`).
2. **Impairment × TMDL table.** Columns: AU | cause | status | TMDL (ID, year, PDF) | applicant WLA.
3. **Pollutant linkage.** List the applicant's limited or discharged parameters that link to a cause, and name the linkage source for each.
4. **Watershed burden.** Give:
   - HUC12 and HUC8 totals from `get_watershed_stats`;
   - the top facilities and pollutants by calculated load;
   - the share of load from facilities with `p_imp_poll=Y`;
   - the facilities with the most exceedances;
   - the CWA SNC count.
5. **Applicant.** Give:
   - permit status (call out Admin Continued or expired);
   - limits for the linked pollutants;
   - exceedances by year, with load over limit;
   - multi-year DMR vs TRI trend;
   - bulk QNCR history if pulled.
6. **Flags.** Any regulatory screening flags, using the provision for the applicant's type, worded as above.

### Interpretation rules
- **Loading Tool numbers are "calculated loads".** EPA computes them from DMR concentrations and flows. They are not measured totals, and they are not "emissions".
  - Show `QcFlag` whenever it is set. A flagged value may be a reporting-unit error, so do not lead with it.
- **"Reported exceedances", not "violations found".** E90 counts are permittee-reported DMR values over limits.
- **No exceedance record ≠ compliance.** DMRs can be missing, late, or `NODI`-coded.
- **Compliance ≠ adequate limits.** A permit can be met while the receiving water stays impaired. That gap is often the substance of the comment.
- **Apply the general rules in `bayou:epa-echo-search` "Interpreting ECHO data".**
- **ATTAINS assessments lag.** State the reporting cycle (DFR `ReportingCycle`, e.g. 2026). A water with no listing may simply be **unassessed**. Say "not assessed" if it does not appear in ATTAINS, rather than "not impaired".

### Mapping to permit-analysis questions

| Question | What this skill supplies |
|---|---|
| WTR-007 (discharge composition vs receiving-water criteria) | AU causes, linked pollutants, the applicant's limits and calculated loads |
| WTR-008 (mixing zone, WET, low-flow margin) | Impairment status and cumulative watershed load (a mixing zone in impaired water is a standard comment point). Flow statistics come from `bayou:usgs-water-data` |
| WTR-006 (§316(b) intake) | ESA-species flag (`EsaAquaticSpeciesFlg` in DFR `WBD12s`) and receiving-water identity only. Intake design comes from the application |
| WTR-003, WTR-004 (treatment O&M, hydrostatic test water) | The applicant's exceedance history as evidence about O&M performance |
| WQC-001, WQC-002 (401 certification, LAC 33:IX Ch. 11) | AU IDs = LDEQ subsegments, which is the key into the Chapter 11 criteria tables. 303(d) causes and TMDL status |

### Citation format

> **Receiving water: Bayou Trepagnier (LDEQ subsegment 041202, ATTAINS AU `LA041202_00`)**, IR category 5. Impaired for dissolved oxygen and Enterococcus, no TMDL linked. Source: [EPA ATTAINS](https://www.epa.gov/waterdata/attains), 2026 reporting cycle (retrieved 2026-10-08).
>
> **Calculated loads, HUC12 080902030101 (2024)**: 25 DMR reporters, 4,285,941 lb. Source: [EPA ECHO Water Pollutant Loading Tool](https://echo.epa.gov/trends/loading-tool/) (retrieved 2026-10-08). Loads are EPA estimates calculated from discharge monitoring reports.

## Notes & limits

- **Rate limits.**
  - These calls were not tested for throttling. Assume the general ECHO REST limit applies.
  - A full report is about 15 ECHO calls, plus 3 ATTAINS calls per AU (assessmentUnits, assessments, actions) and 1 per TMDL.
  - For many facilities, use the bulk files instead (`bayou:epa-echo-search`).
- **ESA-listed aquatic species.** The DFR's `EsaAquaticSpeciesFlg` per HUC12 is a screen. Use `bayou:la-species-cultural-review` for the species.
- **Flow and low-flow (7Q10).** These are outside this skill. Use `bayou:usgs-water-data`.
- **LDEQ documents.** The permit itself, the fact sheet, and the water-quality screen come from `bayou:ldeq-edms-search`. ATTAINS and ECHO do not replace the fact sheet's own reasonable-potential analysis.
- Cross-links: `bayou:epa-frs-crosswalk` (resolve IDs), `bayou:epa-echo-search` (compliance, bulk history), `bayou:epa-tri-search` (TRI side of DMR vs TRI), `bayou:ejscreen-report` (demographics), `bayou:permit-analysis`.

$ARGUMENTS
