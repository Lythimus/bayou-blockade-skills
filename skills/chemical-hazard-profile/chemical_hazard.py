#!/usr/bin/env python3
"""Hazard profile for one or more chemicals, from PubChem and (with a key) EPA CompTox.

    chemical_hazard.py 71-43-2 chloroprene "ethylene oxide"
    chemical_hazard.py --file chemicals.txt          # one CAS number or name per line
    chemical_hazard.py --tri-csv tri_basic.csv       # EPA TRI basic data file
    chemical_hazard.py --all-sources 126-99-8        # every GHS source, not only the first
    chemical_hazard.py --json 71-43-2                # machine-readable, always every source

Set CTX_API_KEY in the environment to add EPA cancer calls and IRIS values.
Standard library only.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound"
CTX = "https://comptox.epa.gov/ctx-api"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
# EU harmonised classification is a regulator's decision; the other GHS entries on a
# PubChem record are company notifications or national lists and can disagree with it.
HARMONISED = "Regulation (EC) No 1272/2008"


def get_json(url, headers=None):
    # PubChem asks for no more than five requests per second.
    time.sleep(0.25)
    req = urllib.request.Request(url, headers=dict({"User-Agent": "bayou-chemical-hazard-profile"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def resolve(term):
    data = get_json("%s/compound/name/%s/cids/JSON" % (PUG, urllib.parse.quote(term, safe="")))
    cids = (data or {}).get("IdentifierList", {}).get("CID", [])
    return cids[0] if cids else None


def cas_of(cid):
    data = get_json("%s/compound/cid/%d/synonyms/JSON" % (PUG, cid)) or {}
    info = data.get("InformationList", {}).get("Information", [{}])[0]
    return next((s for s in info.get("Synonym", []) if CAS_RE.match(s)), None)


def title_of(cid):
    data = get_json("%s/compound/cid/%d/property/Title,MolecularFormula/JSON" % (PUG, cid)) or {}
    props = data.get("PropertyTable", {}).get("Properties", [{}])[0]
    return props.get("Title"), props.get("MolecularFormula")


def information(record):
    """Flatten every Information item under a PUG View record."""
    stack, items = [record], []
    while stack:
        node = stack.pop()
        items.extend(node.get("Information", []))
        stack.extend(node.get("Section", []))
    return items


def strings(item):
    return [m.get("String", "").strip() for m in item.get("Value", {}).get("StringWithMarkup", [])]


def ghs(cid):
    data = get_json("%s/%d/JSON?heading=GHS+Classification" % (VIEW, cid))
    if not data:
        return []
    record = data["Record"]
    sources = {r["ReferenceNumber"]: r.get("SourceName", "") for r in record.get("Reference", [])}
    by_ref = {}
    for item in information(record):
        entry = by_ref.setdefault(item.get("ReferenceNumber"), {"signal": None, "pictograms": [], "statements": [], "note": None})
        name = item.get("Name")
        if name == "Signal":
            entry["signal"] = (strings(item) or [None])[0]
        elif name == "Pictogram(s)":
            # The text of this item is blank; the pictogram names are in the markup.
            for part in item.get("Value", {}).get("StringWithMarkup", []):
                entry["pictograms"] += [m.get("Extra") for m in part.get("Markup", []) if m.get("Type") == "Icon"]
        elif name == "GHS Hazard Statements":
            entry["statements"] = strings(item)
        elif name == "Note":
            entry["note"] = " ".join(strings(item))
    out = [dict(entry, source=sources.get(ref, "unknown"), reference=ref) for ref, entry in by_ref.items() if entry["statements"]]
    out.sort(key=lambda e: (not e["source"].startswith(HARMONISED), e["source"]))
    return out


def iarc(cid):
    data = get_json("%s/%d/JSON?heading=Carcinogen+Classification" % (VIEW, cid))
    if not data:
        return None
    record = data["Record"]
    refs = [r["ReferenceNumber"] for r in record.get("Reference", []) if "IARC" in r.get("SourceName", "")]
    for item in information(record):
        if item.get("ReferenceNumber") in refs and item.get("Name") == "IARC Carcinogenic Classes":
            return "; ".join(strings(item))
    return None


def comptox(cas_or_name, key):
    headers = {"x-api-key": key, "Accept": "application/json"}
    hits = get_json("%s/chemical/search/equal/%s" % (CTX, urllib.parse.quote(cas_or_name, safe="")), headers)
    if not hits:
        return None
    dtxsid = hits[0].get("dtxsid")
    cancer = get_json("%s/hazard/cancer-summary/search/by-dtxsid/%s" % (CTX, dtxsid), headers) or []
    iris_rows = get_json("%s/hazard/iris/search/by-dtxsid/%s" % (CTX, dtxsid), headers) or []
    return {
        "dtxsid": dtxsid,
        "dashboard": "https://comptox.epa.gov/dashboard/chemical/details/" + dtxsid,
        "cancer_calls": [{k: c.get(k) for k in ("source", "exposureRoute", "cancerCall", "url")} for c in cancer],
        "iris": [{k: r.get(k) for k in ("rfdChronic", "rfcChronic", "criticalEffectsSystems", "tumorSite",
                                         "lastSignificantRevision", "irisUrl")} for r in iris_rows],
    }


def profile(term, key, fallback=None):
    """Look up `term`; `fallback` is the chemical's name when `term` is a CAS number PubChem lacks."""
    term = term.strip()
    cid = resolve(term)
    if cid is None and fallback:
        cid = resolve(fallback)
    if cid is None:
        return {"query": "%s (%s)" % (fallback, term) if fallback else term, "found": False}
    title, formula = title_of(cid)
    cas = term if CAS_RE.match(term) else cas_of(cid)
    result = {
        "query": term, "found": True, "cid": cid, "name": title, "formula": formula, "cas": cas,
        "pubchem": "https://pubchem.ncbi.nlm.nih.gov/compound/%d#section=GHS-Classification" % cid,
        "ghs": ghs(cid), "iarc": iarc(cid),
    }
    if key:
        try:
            result["comptox"] = comptox(cas or title, key)
        except urllib.error.HTTPError as err:
            result["comptox_error"] = "HTTP %d from CompTox (401 or 403 means the key was rejected)" % err.code
    return result


def tri_chemicals(path):
    """Unique (lookup term, name) pairs from a TRI basic data file, whose headers are numbered."""
    seen, terms = set(), []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        col = lambda suffix: next((f for f in reader.fieldnames if f.strip().upper().endswith(suffix)), None)
        name_col, cas_col = col("CHEMICAL"), col("CAS#")
        if not name_col:
            sys.exit("no CHEMICAL column in %s" % path)
        for row in reader:
            name, cas = row[name_col].strip(), (row.get(cas_col) or "").strip()
            if name in seen:
                continue
            seen.add(name)
            # TRI stores CAS numbers without hyphens, and category codes (N010) in the same column.
            if cas.isdigit() and len(cas) > 4:
                cas = "%s-%s-%s" % (cas[:-3].lstrip("0"), cas[-3:-1], cas[-1])
            # Some CAS numbers TRI uses for mixtures (1330-20-7, mixed xylenes) have no
            # PubChem compound, so the name is kept as a second attempt.
            terms.append((cas, name) if CAS_RE.match(cas) else (name, None))
    return terms


def render(p, all_sources=False):
    if not p["found"]:
        return "## %s\n\nNot found in PubChem. TRI categories and mixtures (\"Certain glycol ethers\", \"Xylene (mixed isomers)\", \"Lead and lead compounds\") are groups, not single compounds; look up a member compound by CAS number.\n" % p["query"]
    lines = ["## %s (CAS %s, %s)" % (p["name"], p["cas"] or "not listed", p["formula"]), "",
             "IARC: %s" % (p["iarc"] or "no IARC classification on the PubChem record"), ""]
    if not p["ghs"]:
        lines.append("No GHS classification on the PubChem record.")
    shown = p["ghs"] if all_sources else p["ghs"][:1]
    for entry in shown:
        tag = " (EU harmonised classification)" if entry["source"].startswith(HARMONISED) else ""
        lines.append("**%s**%s: %s; pictograms: %s" % (entry["source"], tag, entry["signal"] or "no signal word",
                                                      ", ".join(entry["pictograms"]) or "none"))
        lines += ["- " + s for s in entry["statements"]]
        if entry["note"]:
            lines.append("- Note: " + entry["note"])
        lines.append("")
    hidden = len(p["ghs"]) - len(shown)
    if hidden:
        # Sources differ most on the cancer statement, so the spread is shown even when
        # the other classifications are not.
        cancer = sorted({s.split(":")[0].split(" ")[0] for e in p["ghs"] for s in e["statements"] if s.startswith(("H350", "H351"))})
        lines += ["%d other GHS source(s) on the record (--all-sources lists them). Cancer statements across all sources: %s."
                  % (hidden, ", ".join(cancer) or "none"), ""]
    ctx = p.get("comptox")
    if ctx:
        lines.append("**EPA CompTox** (%s)" % ctx["dtxsid"])
        lines += ["- Cancer call: %s, %s route (%s)" % (c["cancerCall"], c["exposureRoute"], c["source"]) for c in ctx["cancer_calls"]]
        for r in ctx["iris"]:
            lines.append("- IRIS: chronic RfD %s, chronic RfC %s; critical effects: %s; tumor site: %s (%s)" % (
                r["rfdChronic"], r["rfcChronic"], r["criticalEffectsSystems"], r["tumorSite"], r["irisUrl"]))
        lines.append("")
    elif "comptox_error" in p:
        lines += ["EPA CompTox: " + p["comptox_error"], ""]
    lines.append("Source: %s" % p["pubchem"])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chemicals", nargs="*", help="CAS numbers or names")
    ap.add_argument("--file", help="text file, one CAS number or name per line")
    ap.add_argument("--tri-csv", help="EPA TRI basic data file (uses its CHEMICAL and CAS# columns)")
    ap.add_argument("--all-sources", action="store_true", help="print every GHS source, not only the first")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    terms = [(t, None) for t in args.chemicals]
    if args.file:
        terms += [(line.strip(), None) for line in open(args.file, encoding="utf-8") if line.strip()]
    if args.tri_csv:
        terms += tri_chemicals(args.tri_csv)
    if not terms:
        ap.error("give at least one chemical, --file, or --tri-csv")
    key = os.environ.get("CTX_API_KEY")
    profiles = [profile(t, key, name) for t, name in terms]
    if args.json:
        json.dump(profiles, sys.stdout, indent=2)
    else:
        if not key:
            print("_EPA CompTox section skipped: CTX_API_KEY is not set._\n")
        print("\n".join(render(p, args.all_sources) for p in profiles))


if __name__ == "__main__":
    main()
