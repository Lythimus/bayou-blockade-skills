---
name: chemical-hazard-profile
description: CAS number or chemical name → GHS hazard statements, signal word, pictograms and IARC cancer group from PubChem, plus EPA cancer calls and IRIS reference values from CompTox when a key is set. Takes a single chemical, a list, or a TRI data file
allowed-tools: Bash, Read, AskUserQuestion
---

# Chemical Hazard Profile

Turns a chemical on a permit or a TRI report into a plain statement of what it does to people: the hazard statements a regulator has assigned, whether it is a known or suspected carcinogen, and (with an EPA key) the reference concentrations EPA uses in risk assessment.

Use it on the TRI basic data file from `/bayou:epa-tri-search` (the same state-year files `/bayou:tri-release-report` caches under its `raw/` directory), or when a permit application names pollutants without saying what they do.

It reports hazard, not risk. A hazard statement says what a chemical can do at some dose. It says nothing about the dose anyone near a facility receives. Do not write "residents are being exposed to a carcinogen at harmful levels" from this output; write that the facility reports releasing a chemical classified as a carcinogen.

## Parsing arguments

- One or more **CAS numbers** (`71-43-2`) or **names** (`chloroprene`). Prefer the CAS number when the permit gives one: names are ambiguous.
- A **text file**, one chemical per line.
- A **TRI basic data file** (the CSV described in `/bayou:epa-tri-search`). The script reads its `CHEMICAL` and `CAS#` columns and looks up each chemical once.

## Step 1: Run the lookup

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/chemical-hazard-profile/chemical_hazard.py" 71-43-2 chloroprene
python3 "${CLAUDE_PLUGIN_ROOT}/skills/chemical-hazard-profile/chemical_hazard.py" --tri-csv tri_basic.csv
python3 "${CLAUDE_PLUGIN_ROOT}/skills/chemical-hazard-profile/chemical_hazard.py" --all-sources 126-99-8
python3 "${CLAUDE_PLUGIN_ROOT}/skills/chemical-hazard-profile/chemical_hazard.py" --json 71-43-2 > benzene.json
```

No key is needed for the PubChem part. Endpoints, for when the script needs repair:

| Purpose | Request |
|---|---|
| Name or CAS → CID | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<term>/cids/JSON` |
| Title and formula | `.../rest/pug/compound/cid/<cid>/property/Title,MolecularFormula/JSON` |
| CAS number (first synonym shaped like one) | `.../rest/pug/compound/cid/<cid>/synonyms/JSON` |
| GHS classification | `https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/<cid>/JSON?heading=GHS+Classification` |
| IARC group | `.../rest/pug_view/data/compound/<cid>/JSON?heading=Carcinogen+Classification` |

PubChem asks for no more than five requests per second; the script paces itself, so a 60-chemical TRI list takes about a minute and a half.

## Step 2: EPA CompTox (optional, needs a key)

Read `~/.claude/bayou-credentials.md`. If it has a `CTX_API_KEY` entry, pass it in the environment:

```bash
CTX_API_KEY="<key>" python3 "${CLAUDE_PLUGIN_ROOT}/skills/chemical-hazard-profile/chemical_hazard.py" 126-99-8
```

This adds EPA's cancer call for each exposure route and the IRIS chronic reference dose and reference concentration. The key is free but issued by hand: email `ccte_api@epa.gov`. Without one, say that the EPA section was skipped and give the user the dashboard link (`https://comptox.epa.gov/dashboard/`, search by CAS number) to read the same values in a browser.

Requests go to `https://comptox.epa.gov/ctx-api` with the key in an `x-api-key` header:

| Purpose | Path |
|---|---|
| CAS or name → DTXSID | `/chemical/search/equal/<term>` |
| Cancer calls | `/hazard/cancer-summary/search/by-dtxsid/<dtxsid>` |
| IRIS values | `/hazard/iris/search/by-dtxsid/<dtxsid>` |
| Every toxicity value on file (large) | `/hazard/toxval/search/by-dtxsid/<dtxsid>` |

**This branch was written from EPA's published OpenAPI description (`https://comptox.epa.gov/ctx-api/docs/hazard.html`) and has only been run as far as the authentication check.** The first time it runs with a real key, compare one chemical's output against the CompTox dashboard before relying on it. A 401 or 403 means the key was rejected.

## Reading the output

- **GHS sources disagree, and the script shows one by default.** A PubChem record carries classifications from several bodies. The script lists the EU harmonised classification (Regulation (EC) No 1272/2008) first, because it is a regulator's decision; the ECHA entry beneath it is a tally of what companies notified, with the percentage of notifiers in parentheses. Japan's NITE entries often differ: for chloroprene the EU assigns H350 ("may cause cancer") while one NITE entry assigns H351 ("suspected of causing cancer"). The summary line under each chemical reports the spread of cancer statements across all sources. Run `--all-sources` and name the source before quoting a statement.
- **GHS is not a United States classification.** OSHA's Hazard Communication Standard uses the same statements on safety data sheets, but none of the sources above is a US agency finding. For a US finding, cite IARC alongside EPA's IRIS call (Step 2) or the NTP Report on Carcinogens.
- **IARC groups:** 1 carcinogenic to humans, 2A probably, 2B possibly, 3 not classifiable. "No IARC classification" means IARC has not evaluated the chemical, not that it is safe.
- **TRI categories and mixtures do not resolve.** "Certain glycol ethers", "Lead and lead compounds" and the other `N###` category codes are groups of compounds, and mixed xylenes (CAS 1330-20-7) have no single PubChem compound. The script reports them as not found. Look up a named member compound instead and say which one was used.
- **A name can match the wrong compound.** Check that the CAS number in the output matches the one on the permit.

## Endocrine disruption

Neither source above flags endocrine disruptors. Two lists exist, and both are for reading rather than automated lookup:

- **TEDX List of Potential Endocrine Disruptors**: about 1,400 chemicals with at least one peer-reviewed study showing endocrine effects. TEDX closed in 2019 and the list is frozen. Search it at `https://endocrinedisruption.org/interactive-tools/tedx-list-of-potential-endocrine-disruptors/search-the-tedx-list`. It is not bundled here because its reuse terms have not been checked.
- **EPA Endocrine Disruptor Screening Program** chemical universe: `https://comptox.epa.gov/dashboard/chemical-lists/EDSPUOC`. Being on this list means EPA intends to screen the chemical, not that it found an effect.

Describe a TEDX match as "listed as a potential endocrine disruptor on the basis of published studies", never as a regulatory finding.

## Dead ends

- `api-ccte.epa.gov`, the CompTox API's former host, no longer answers. Use `comptox.epa.gov/ctx-api`.
- The `Pictogram(s)` item in PubChem's GHS section has a blank text value; the pictogram names are in each item's `Markup[].Extra`. A parser that reads only `String` reports no pictograms.

## Presenting the results

For one or two chemicals, give the script's output with the source named. For a TRI list, build a table:

| Chemical | CAS | IARC | Cancer statement (source) | Other serious health statements | Source link |

Sort carcinogens first. "Serious" means the H340s (genetic defects), H350s (cancer), H360s (fertility, unborn child) and H370s (organ damage). Leave flammability and aquatic toxicity out of a health summary unless the user asks. State the retrieval date, and state whether the EPA section ran.

### Citation format

> **PubChem**, Compound Summary for CID 31369 (Chloroprene, CAS 126-99-8), GHS Classification, harmonised classification under Regulation (EC) No 1272/2008: H350 "May cause cancer", source: [PubChem](https://pubchem.ncbi.nlm.nih.gov/compound/31369#section=GHS-Classification) (retrieved 2026-10-11).
>
> **IARC Monographs**, Chloroprene, Group 2B (possibly carcinogenic to humans), as reported in PubChem CID 31369 (retrieved 2026-10-11).

$ARGUMENTS
