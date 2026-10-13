"""Turn screening.json and model.json into the household report.

build() makes one results dict. REPORT.md, exposure.csv, results.json, manifest.json and
the charts are all rendered from that dict and from nothing else. A public report is the
same renderers fed a dict that was built without the home's location, so no renderer can
print what it was never handed.
"""
import csv
import datetime as dt
import hashlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exposure  # noqa: E402
import toxvalues  # noqa: E402

RESULTS_VERSION = 1
TOP_CHEMICALS = 15
TOP_FACILITIES = 10
TOP_ORGANS = 6
SCRIPTS = ("hx.py", "report.py", "charts.py", "exposure.py", "toxvalues.py", "rsei.py", "airtox.py",
           "aermod_io.py", "downloads.py", "aermod_build.sh")

OWN_CELL = ("RSEI places every facility at the center of its 810 m grid cell. Inside that cell the "
            "figure is interpolated from 441 modeled points within a kilometre; farther out the "
            "model computes a point only every 5 km and fills the cells between by interpolation. "
            "A home beside a plant, or in the plant's own cell, gets a cell-wide average that does "
            "not know which side of the fence it is on.")
TRI_ONLY = ("Only releases that facilities reported to EPA's Toxics Release Inventory are counted. "
            "Plants below the reporting threshold, vehicles, ships, trains and every other source "
            "are absent, so each figure is a floor for industrial sources and not a total for the "
            "air at the home.")
AIRTOX_ROUNDING = ("EPA publishes the total rounded to one significant figure, so it does not equal "
                   "the sum of the source groups listed under it.")
LAC_5112 = ("Louisiana's toxic air pollutant standards (LAC 33:III.5112, Table 51.2) are annual "
            "averages for benzene, ethylene oxide, formaldehyde, 1,3-butadiene and vinyl chloride, "
            "among others, and 8-hour averages for chloroprene, ammonia, hydrogen cyanide and "
            "toluene, among others. An applicant's annual run can be read as a long-term "
            "concentration at the home. A run made for an 8-hour standard is a short-term peak and "
            "is listed as context only.")
NOT_COMBINED = ("The past and proposed figures are not added together. The past figures are a floor: "
                "reported releases only, on an 810 m grid, for the years with data. The proposed "
                "figures are a ceiling: the permitted maximum, at the home's own point, for years "
                "that have not happened. A sum of a floor and a ceiling is neither.")
BENCHMARK = ("For scale: EPA's air toxics program aims to keep lifetime cancer risk from a source "
             "category near 1 in a million for as many people as possible, and treats about 100 in "
             "a million as the upper limit of what it accepts (Benzene NESHAP, 54 FR 38044, 1989).")
WORDING = ("Every concentration here is a modeled outdoor concentration at the home. None is a "
           "measurement, an indoor level or an amount absorbed. A cancer risk is an upper-bound "
           "added lifetime chance attributed to the modeled sources, not a prediction for any "
           "person. A hazard quotient is a ratio to EPA's reference level, not a probability: 2 "
           "does not mean twice the chance of harm.")
NOT_ASSESSED = [
    "Drinking water. Nothing here estimates it, and distance to a discharge says nothing about "
    "what comes out of a tap. To follow up, find out: whether the home is on a public supplier or "
    "a private well; where the supplier's intake or wellfield is; what treatment it applies; and "
    "what its measured results show (the supplier's annual Consumer Confidence Report, or a "
    "certified lab test for a private well).",
    "Indoor air, and time spent away from the home. Everyone is treated as breathing outdoor air "
    "at the home all day, every day they lived there.",
    "Short-term peaks: accidents, upsets, startups, shutdowns and flaring.",
    "Chemicals formed in the air after release (ozone, secondary particles, secondary formaldehyde).",
    "Sources more than 50 km away.",
    "Soil, dust, food and skin contact.",
]
PUBLIC_RESIDUAL = ("This public version leaves out the address, coordinates, grid cell, census block "
                   "and every distance, and rounds figures to two significant digits. The figures "
                   "still depend on where the home is: someone with EPA's full RSEI microdata could "
                   "match them to an 810 m cell.")


PUBLIC_PATH_1 = (" Where a proposed-facility figure is marked \"applicant output\", it is the value the "
                 "applicant filed at a receptor within 100 m of the home, and the applicant's receptor "
                 "file is a public record.")


# ------------------------------------------------------------ formatting

def num(v):
    """Two significant figures in plain decimals; exponent form only below a millionth."""
    if v is None:
        return "no figure"
    if v == 0:
        return "0"
    if abs(v) < 1e-6:
        return f"{v:.1e}"
    s = f"{v:.2g}"
    if "e" in s:
        s = f"{float(s):,.0f}" if abs(v) >= 1 else f"{float(s):.8f}".rstrip("0")
    return s


def per_million(risk):
    if risk is None:
        return "no figure"
    return "under 0.001" if 0 < risk * 1e6 < 0.001 else num(risk * 1e6)


def pct(f):
    if f is None:
        return "none"
    return "under 1%" if 0 < f < 0.005 else f"{100 * f:.0f}%"


def count(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def years_text(years):
    """[1990, 1991, 1992, 1995] -> '1990-1992, 1995'."""
    out, run = [], []
    for y in sorted(set(years)) + [None]:
        if run and y == run[-1] + 1:
            run.append(y)
            continue
        if run:
            out.append(str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}")
        run = [y]
    return ", ".join(out)


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def organ(o):
    return toxvalues.ORGAN_NAMES.get(o, o)


def title_case(name):
    """EPA facility names arrive in capitals."""
    return name.title().replace("Llc", "LLC").replace("Lp", "LP").replace(" Na ", " NA ") if name.isupper() else name


def rounded(o):
    """Every float two significant figures. Full-precision concentrations are a fingerprint
    of the home's grid cell, so a public results file must not carry them."""
    if isinstance(o, float):
        return float(f"{o:.2g}")
    if isinstance(o, dict):
        return {k: rounded(v) for k, v in o.items()}
    if isinstance(o, list):
        return [rounded(v) for v in o]
    return o


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------ results

def member_years(a, m, scr):
    """Each calendar year a member lived at the home, and whether RSEI gave it a figure."""
    y = scr["years"]
    out = []
    for row in exposure.exposure({}, m["residence"], exposure.parse_date(a["as_of"]), m.get("birth_year"))["by_year"]:
        year = row["year"]
        if year in y["read"]:
            status = "figure"
        elif year in y["outside_rsei_coverage"]:
            status = "outside the years RSEI covers"
        elif year in y["not_requested"]:
            status = "left out of the screening run"
        else:
            status = "not retrieved"
        out.append({"year": year, "status": status, "home_fraction": row["home_fraction"]})
    return out


def no_value_split(rows, tox):
    """Why a chemical has no cancer figure: EPA's table omits it, or lists it without a unit
    risk. The second group includes known carcinogens, so the two must not read alike."""
    absent, group, no_ure, no_rfc = [], [], [], []
    for r in rows:
        rec = tox.get(r["cas"])
        if r["risk"] is None:
            # A key that is not a CAS number is a TRI category (dioxins, polycyclic aromatics)
            # with no single row to map to. EPA's table does list members of those groups,
            # some with very large unit risks, so "not in the table" would be false.
            (no_ure if rec is not None else absent if r["cas"].isdigit() else group).append(r["chemical"])
        if r["hq"] is None and rec is not None:
            no_rfc.append(r["chemical"])
    return {"not_in_epa_table": sorted(absent), "reported_as_a_group": sorted(group),
            "no_unit_risk": sorted(no_ure), "no_reference_concentration": sorted(no_rfc)}


def history(a, scr, tox, public):
    src = scr["sources"]

    def name(sid):
        s = src.get(sid) or {}
        return title_case(s.get("name") or sid) + (f", {s['city'].title()}" if s.get("city") else "")

    members, used = {}, set()
    for m in a["members"]:
        res = scr["members"].get(m["id"]) or {"rows": [], "totals": {}}
        rows, t = res["rows"], res["totals"]
        years = member_years(a, m, scr)
        at_home = sum(y["home_fraction"] for y in years)
        known = max((r["residence_years"] * r["evidence_fraction"] for r in rows), default=0.0)
        by_fac, top_chem = {}, {}
        for r in rows:
            total = sum(r["by_source_integral"].values())
            if not r["risk"] or not total:
                continue
            for sid, v in r["by_source_integral"].items():
                share = r["risk"] * v / total
                by_fac[sid] = by_fac.get(sid, 0.0) + share
                if share > top_chem.get(sid, ("", 0.0))[1]:
                    top_chem[sid] = (r["chemical"], share)
        facilities = sorted(by_fac.items(), key=lambda kv: -kv[1])[:TOP_FACILITIES]
        chems = sorted(rows, key=lambda r: (-(r["risk"] or 0), -(r["hq"] or 0)))
        # Rank by either measure: a chemical with no cancer value can still drive a hazard index.
        keep = {r["cas"] for r in chems[:TOP_CHEMICALS]} | {
            r["cas"] for r in sorted(rows, key=lambda r: -(r["hq"] or 0))[:5] if r["hq"]}
        index = []
        for o, v in sorted((t.get("hazard_index") or {}).items(), key=lambda kv: -kv[1]):
            lead = max((r for r in rows if r["hq"] and o in (scr["chemicals"][r["cas"]]["target_organs"] or [])),
                       key=lambda r: r["hq"], default=None)
            top = next(iter(lead["by_source_integral"]), None) if lead else None
            used.add(top)
            index.append({"organ": organ(o), "hazard_index": v, "largest_chemical": lead and lead["chemical"],
                          "largest_hq": lead and lead["hq"], "largest_source": top and name(top)})
        out_rows = []
        for r in chems:
            if r["cas"] not in keep:
                continue
            top = next(iter(r["by_source_integral"]), None)
            used.add(top)
            out_rows.append({
                "chemical": r["chemical"], "cas": r["cas"], "average_ug_m3": r["exposed_average_ug_m3"],
                "highest_year_ug_m3": r["max_annual_ug_m3"], "integral_ug_m3_yr": r["integral_ug_m3_yr"],
                "cancer_risk": r["risk"], "age_adjusted": r["age_adjusted"], "hazard_quotient": r["hq"],
                "hazard_quotient_highest_year": r["hq_max_year"], "evidence_fraction": r["evidence_fraction"],
                "floor_years": r["partial_years"], "note": r["note"],
                "sources": len(r["by_source_integral"]), "largest_source": top and name(top)})
        used.update(sid for sid, _ in facilities)
        members[m["id"]] = {
            "years_at_home": at_home, "years_with_a_figure": known, "is_floor": known < at_home - 1e-9,
            "years": years,
            "cancer_risk": t.get("cancer_risk"), "cancer_chemicals": t.get("cancer_chemicals", 0),
            "hazard_index": index, "chemicals": out_rows, "chemicals_with_a_figure": len(rows),
            "facilities": [{"source": name(sid), "id": sid, "cancer_risk": v,
                            "share": v / t["cancer_risk"] if t.get("cancer_risk") else None,
                            "largest_chemical": top_chem[sid][0],
                            **({} if public else {"distance_km": src[sid]["distance_km"]})}
                           for sid, v in facilities],
            "no_value": no_value_split(rows, tox),
            "hazard_index_unassigned": t.get("hazard_index_unassigned") or [],
            "notes": sorted({scr["chemicals"][r["cas"]]["note"].replace("ASSUMPTION: ", "") + "."
                             for r in rows if scr["chemicals"][r["cas"]]["note"] and (r["risk"] or r["hq"])}),
        }
    y = scr["years"]
    out = {
        "tier": scr["tier"], "years": y, "model_versions": scr["model_versions"], "gaps": scr["gaps"],
        "tri_filings_missing": sorted(set(y["read"]) - set(y["tri_filings_checked"])),
        "chemicals_modeled": len(scr["chemicals"]), "members": members,
        "limitations": scr["limitations"] + [OWN_CELL],
        "provenance": scr["provenance"]["rsei"],
    }
    if public:
        # Which facilities fall inside the 50 km search circle bounds where its center is,
        # so a public report names only the ones it discusses and never counts the rest.
        out["sources"] = {sid: {"name": name(sid), "kind": src[sid]["kind"]} for sid in sorted(used - {None})}
    else:
        out["sources_modeled"] = len(src)
        out["sources"] = {sid: {"name": name(sid), "kind": s["kind"], "distance_km": s["distance_km"],
                                "lat": s["lat"], "lon": s["lon"]} for sid, s in src.items()}
    return out


def context(scr, public):
    atx = scr["airtoxscreen"]
    if atx.get("skipped"):
        return {"skipped": atx["skipped"]}
    groups = sorted(atx["by_source_per_million"].items(), key=lambda kv: -kv[1])
    out = {"year": atx["year"], "total_per_million": atx["total_per_million"],
           "county": atx.get("county"), "state": atx.get("state"), "rounding": AIRTOX_ROUNDING}
    # The source-group figures are published per block; a handful of them picks one block
    # out of a tract, so a public report carries only EPA's rounded total.
    if not public:
        out.update(block=atx["block"], block_source=atx.get("block_source"),
                   largest_groups_per_million=dict(groups[:6]),
                   stationary_point_per_million=atx["by_source_per_million"].get("PT-StationaryPoint"))
    return out


def model_note(text, public):
    """A line of text from `model`. A public one loses anything measured from the home: the
    applicant's receptor grid is a public record, so a distance to a receptor, or the exact
    value filed at it, places the home beside that receptor."""
    if text.startswith("given with --home-xy"):
        return "the home's position was " + text
    if not public:
        return text
    if text.startswith("terrain height at the home"):
        return "terrain height at the home taken from the applicant's nearest receptor or supplied by the user"
    if "the applicant's own result at the home is" in text:
        return (text.split(":")[0] + ": the applicant's own result at the home and source-emissions.csv rates "
                "times the rerun disagree; the rates entered do not match what the applicant modeled")
    text = re.sub(r" at a receptor [\d.,]+ m from the home", " at the filed receptor nearest the home", text)
    text = re.sub(r"is [\d.,]+ m from the home, beyond", "is farther from the home than", text)
    return re.sub(r"[\d.,]+ m (away|from the home)", "near the home", text)


def proposed(a, mod, public):
    scenarios = {}
    for scen, s in mod["scenarios"].items():
        chems = []
        for k, c in sorted(s["chemicals"].items(), key=lambda kv: -(kv[1]["conc_ug_m3"] or 0)):
            row = {"chemical": c["chemical"], "cas": k, "conc_ug_m3": c["conc_ug_m3"], "path": c["path"],
                   "rate_g_s": c["rate_g_s"], "rate_times_rerun_ug_m3": c["rerun_conc_ug_m3"],
                   "notes": [model_note(x, public) for x in c["notes"]],
                   # Both figures are reported when they differ: the applicant's is used, and
                   # the mismatch means the rates entered are not the ones it modeled.
                   "disagrees": bool(c["path"] == "applicant output" and c["rerun_conc_ug_m3"] is not None
                                     and c["conc_ug_m3"]
                                     and not 0.8 <= c["rerun_conc_ug_m3"] / c["conc_ug_m3"] <= 1.25)}
            if not public:
                row["by_source_ug_m3"] = c["by_source_ug_m3"]
            chems.append(row)
        members = {}
        for mid, m in s["members"].items():
            t = m["totals"]
            members[mid] = {
                "stays_to": mod["stays"][mid], "at_home_while_operating": any(x["exposed_average_ug_m3"] is not None for x in m["rows"]),
                "cancer_risk": t.get("cancer_risk"), "cancer_chemicals": t.get("cancer_chemicals", 0),
                "hazard_index": [{"organ": organ(o), "hazard_index": v} for o, v in
                                 sorted((t.get("hazard_index") or {}).items(), key=lambda kv: -kv[1])],
                "chemicals": [{"chemical": r["chemical"], "cas": r["cas"], "cancer_risk": r["risk"],
                               "age_adjusted": r["age_adjusted"], "hazard_quotient": r["hq"],
                               "integral_ug_m3_yr": r["integral_ug_m3_yr"], "note": r["note"]}
                              for r in sorted(m["rows"], key=lambda r: -(r["risk"] or 0))]}
        scenarios[scen] = {"chemicals": chems, "members": members,
                           "chemicals_with_a_figure": sum(1 for c in chems if c["conc_ug_m3"] is not None)}
    out = {
        "name": mod["proposed"]["name"], "operating_start": mod["proposed"]["operating_start"],
        "operating_end": mod["proposed"]["operating_end"], "dispersion_path": mod["dispersion_path"],
        "scenarios": scenarios,
        "checks": [{"file": c["file"], "group": c["group"], "ratio": c["ratio"],
                    **({} if public else {"filed": c["filed"], "rerun": c["rerun"]})} for c in mod["checks"]],
        "applicant_files": [{"file": f["file"], "averaging": f["averaging"], "used": f["used"],
                             **({} if public else {"nearest_receptor_m": f["nearest_receptor_m"]})}
                            for f in mod["applicant_files"]],
        "uses_applicant_output": any(c["path"] == "applicant output" for s in mod["scenarios"].values()
                                     for c in s["chemicals"].values()),
        "runs": [{"sources": r["sources"], "hours": r["hours"], "missing_pct": r["missing_pct"]} for r in mod["runs"]],
        "assumptions": [model_note(x, public) for x in mod["assumptions"]],
        "gaps": [model_note(g, public) if public else g for g in mod["gaps"]], "records_to_request": mod["records_to_request"],
        "limitations": mod["limitations"], "aermod": mod["provenance"]["aermod"],
    }
    if not public:
        out.update(sources=mod["sources"], home_in_model_coordinates=mod["home_in_model_coordinates"])
    return out


def build(a, scr, mod, public, tox=None):
    """The one dict every output is rendered from. scr or mod may be None (step not run)."""
    tox = tox or toxvalues.load()
    r = {"results_version": RESULTS_VERSION, "generated": dt.date.today().isoformat(),
         "public": public, "as_of": a["as_of"],
         "title": "Household air-exposure assessment" + ("" if public else f": {a['label']}")}
    atx = (scr or {}).get("airtoxscreen") or {}
    if public:
        r["location"] = ({"census_tract": atx["block"][:11], "county": atx.get("county"), "state": atx.get("state")}
                         if atx.get("block") else {"census_tract": None})
    else:
        r["location"] = {**a["home"], "grid_cell": scr and scr["grid_cell"], "census_block": atx.get("block")}
    r["members"] = []
    for m in a["members"]:
        periods = [{"start": p["start"][:4] if public else p["start"],
                    "end": (p["end"] or "")[:4] if public else p["end"]} for p in m["residence"]]
        row = {"id": m["id"], "residence": periods, "birth_year_given": m.get("birth_year") is not None}
        if not public:
            row.update(birth_year=m.get("birth_year"), projected_end=m.get("projected_end"))
        r["members"].append(row)
    r["history"] = history(a, scr, tox, public) if scr else None
    r["context"] = context(scr, public) if scr else None
    r["proposed"] = proposed(a, mod, public) if mod else None
    r["not_run"] = ([] if scr else ["screen (past exposure from reported releases)"]) + \
                   ([] if mod else (["model (the proposed facility's contribution)"] if a.get("proposed") else []))
    r["assumptions"] = assumptions(a, r)
    r["improve"] = improve(a, r)
    r["not_assessed"] = NOT_ASSESSED
    if not public:
        return r
    for m in (r["history"] or {"members": {}})["members"].values():
        for y in m["years"]:
            # A part-year gives away the month someone moved in.
            del y["home_fraction"]
    return rounded(r)


def assumptions(a, r):
    out = ["Each person is taken to be at the home, breathing outdoor air, every day of each residence period."]
    for m in a["members"]:
        if m.get("birth_year") is None:
            out.append(f"Member {m['id']}: no birth year was given, so EPA's early-life factors for "
                       "mutagenic carcinogens (10 times before age 2, 3 times from 2 to 16) are not "
                       "applied. If this person was under 16 at the home, their cancer figure is too low.")
    h, p = r["history"], r["proposed"]
    if h:
        out.append("A year with no RSEI figure is unknown. It is not counted as zero and not filled "
                   "from another year, so a total that covers only some years is a floor.")
        for mm in h["members"].values():
            out += [n[0].upper() + n[1:] for n in mm["notes"] if n[0].upper() + n[1:] not in out]
        if any("vinyl chloride" in c["chemical"].lower() for mm in h["members"].values() for c in mm["chemicals"]):
            out.append("Vinyl chloride: EPA's unit risk already covers exposure from birth. For "
                       "someone first exposed as an adult it overstates risk by up to a factor of two.")
    if p:
        for mid, end in sorted({(mid, m["stays_to"]) for s in p["scenarios"].values() for mid, m in s["members"].items()}):
            out.append(f"Member {mid} is assumed to stay at the home until {end}.")
        out.append(f"{p['name']} is assumed to operate from {p['operating_start']} to {p['operating_end']} "
                   "at the same rate every year. A permit's expiry date is not a closure date.")
        out += [x[0].upper() + x[1:] + "." for x in p["assumptions"]]
    return out


def improve(a, r):
    out = []
    h, p = r["history"], r["proposed"]
    if h:
        y = h["years"]
        if y["not_requested"]:
            out.append(f"Run `screen` for {years_text(y['not_requested'])}, which were left out of this run.")
        if h["tri_filings_missing"]:
            out.append(f"Fetch the TRI filings for {years_text(h['tri_filings_missing'])} (`prepare --facilities`), "
                       "so that a facility's missing year can be told apart from a reported zero.")
        if y["outside_rsei_coverage"]:
            out.append(f"No RSEI data exist for {years_text(y['outside_rsei_coverage'])}. For those years, "
                       "the facilities' own emission inventories (LDEQ ERIC) and any ambient monitoring "
                       "records are the only evidence.")
        out += [f"Screening gap: {g}." for g in h["gaps"]]
    elif not r["public"]:
        out.append("Run `screen` to estimate past exposure from reported releases.")
    if p:
        out += p["records_to_request"]
        if not p["checks"] and p["dispersion_path"]:
            out.append("An annual or period plot file from the applicant's own modeling, to check the "
                       "rerun against a result the agency reviewed.")
    elif a.get("proposed"):
        out.append("The proposed facility's air quality modeling files and per-source emission rates, "
                   "then run `model`.")
    if any(m.get("birth_year") is None for m in a["members"]):
        out.append("A birth year for each household member who was under 16 at the home.")
    out.append("Measured air concentrations at or near the home (an LDEQ ambient monitoring site, or "
               "canister sampling) are the only check on a modeled figure.")
    return out


# ------------------------------------------------------------ exposure.csv

EXPOSURE_COLUMNS = ["tier", "scenario", "chemical", "cas_or_id", "source_id", "source", "distance_km",
                    "years", "conc_ug_m3", "conc_min_3x3", "conc_max_3x3", "status"]


def exposure_rows(r, screen_rows, mod):
    """chemical x facility x year. A public file sums over facilities and drops distances and
    the neighbouring-cell range, each of which narrows down where the home is."""
    public, out = r["public"], []
    if r["history"] and public:
        total = {}
        for row in screen_rows:
            key = (row["chemical"], row["cas_or_id"], row["year"])
            cur = total.setdefault(key, [None, False])
            if row["conc_ug_m3"]:
                cur[0] = (cur[0] or 0.0) + float(row["conc_ug_m3"])
            else:
                cur[1] = cur[1] or row["status"] != "zero_reported"
        for (chem, cas, year), (v, missing) in sorted(total.items()):
            out.append(["screening (RSEI)", "reported", chem, cas, "", "all reported sources", "", year,
                        "" if v is None else f"{v:.2g}", "", "",
                        "unknown" if v is None else ("floor" if missing else "modeled")])
    elif r["history"]:
        for row in screen_rows:
            out.append(["screening (RSEI)", "reported", row["chemical"], row["cas_or_id"], row["source_id"],
                        row["source"], row["distance_km"], row["year"], row["conc_ug_m3"],
                        row["conc_min_3x3"], row["conc_max_3x3"], row["status"]])
    p = r["proposed"]
    if p:
        span = f"{p['operating_start'][:4]}-{p['operating_end'][:4]}"
        for scen, s in p["scenarios"].items():
            for c in s["chemicals"]:
                if not public:
                    for sid, v in c["by_source_ug_m3"].items():
                        out.append(["dispersion (AERMOD)", scen, c["chemical"], c["cas"], sid, p["name"],
                                    mod["sources"][sid]["distance_km"], span, f"{v:.6g}", "", "", "modeled"])
                v = c["conc_ug_m3"]
                out.append(["dispersion (AERMOD)", scen, c["chemical"], c["cas"], "TOTAL", p["name"], "", span,
                            "" if v is None else (f"{v:.2g}" if public else f"{v:.6g}"), "", "",
                            "no number" if v is None else c["path"]])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPOSURE_COLUMNS)
    w.writerows(out)
    return buf.getvalue()


# ------------------------------------------------------------ REPORT.md

def summary(r):
    out = []
    h, p = r["history"], r["proposed"]
    for m in r["members"]:
        mid = m["id"]
        lines = []
        if h:
            mm = h["members"][mid]
            if mm["cancer_risk"] is None:
                lines.append(f"Past: no figure for any of the {mm['years_at_home']:.3g} years lived at the home.")
            else:
                top = mm["chemicals"][0]
                s = (f"Past, from industrial releases reported to EPA: added lifetime cancer risk of "
                     f"**{per_million(mm['cancer_risk'])} in a million**, summed over "
                     f"{count(mm['cancer_chemicals'], 'chemical')}. The largest is {top['chemical'].lower()}"
                     + (f", mostly from {top['largest_source']}" if top["largest_source"] else "") + ".")
                if mm["is_floor"]:
                    s += (f" **This is a floor.** It covers {mm['years_with_a_figure']:.3g} of the "
                          f"{mm['years_at_home']:.3g} years lived there; the other years have no figure.")
                lines.append(s)
                if mm["hazard_index"]:
                    hi = mm["hazard_index"][0]
                    lines.append(f"Past, noncancer: the highest hazard index is {num(hi['hazard_index'])} "
                                 f"({hi['organ']}), driven by {(hi['largest_chemical'] or 'no single chemical').lower()}"
                                 + (f" from {hi['largest_source']}" if hi["largest_source"] else "")
                                 + (". It is above 1, EPA's reference level." if hi["hazard_index"] > 1
                                    else ". It is below 1, EPA's reference level."))
        if p:
            for scen, s in p["scenarios"].items():
                pm = s["members"].get(mid)
                if pm is None:
                    continue
                label = "permitted maximum" if scen == "permitted" else "expected operation"
                if not s["chemicals_with_a_figure"]:
                    lines.append(f"{p['name']} ({label}): **no figure.** The inputs a dispersion model "
                                 "needs were missing; they are listed below. Nothing was estimated in their place.")
                elif not pm["at_home_while_operating"]:
                    lines.append(f"{p['name']} ({label}): not at the home while it operates.")
                elif pm["cancer_risk"] is None:
                    lines.append(f"{p['name']} ({label}): no cancer figure; see the gaps below.")
                else:
                    lines.append(f"{p['name']} ({label}) would add **{per_million(pm['cancer_risk'])} in a "
                                 f"million** over {count(pm['cancer_chemicals'], 'chemical')}, if this person "
                                 f"stays until {pm['stays_to']}."
                                 + (f" Highest hazard index {num(pm['hazard_index'][0]['hazard_index'])} "
                                    f"({pm['hazard_index'][0]['organ']})." if pm["hazard_index"] else ""))
                clash = [c["chemical"].lower() for c in s["chemicals"] if c["disagrees"]]
                if clash and pm["at_home_while_operating"]:
                    lines.append(f"Check before relying on the {label} figure: for {', '.join(clash)} the "
                                 "applicant's own result and the emission rates entered disagree. The "
                                 "applicant's result is the one used; both are shown below.")
            if not p["scenarios"]:
                lines.append(f"{p['name']}: **no figure.** The inputs a dispersion model needs were not "
                             "available; the gaps are listed below.")
        out.append(f"**Member {mid}**\n\n" + "\n".join(f"- {x}" for x in lines or ["No figure."]))
    return "\n\n".join(out)


def where(r):
    loc = r["location"]
    if r["public"]:
        if loc.get("census_tract"):
            return (f"A home in census tract {loc['census_tract']}"
                    + (f" ({loc['county']} Parish, {loc['state']})" if loc.get("county") else "")
                    + ". The address and coordinates are withheld.")
        return "A home in Louisiana. The address, coordinates and census tract are withheld."
    s = f"{loc['lat']}, {loc['lon']}" + (f" ({loc['address']})" if loc.get("address") else "")
    if loc.get("grid_cell"):
        s += f"; RSEI grid cell {loc['grid_cell']['x']},{loc['grid_cell']['y']}"
    if loc.get("census_block"):
        s += f"; census block {loc['census_block']}"
    return s + "."


def history_md(r):
    h = r["history"]
    y = h["years"]
    L = ["## Past exposure: releases reported to EPA", "",
         "Source: EPA's RSEI Geographic Microdata, which models each facility's reported air releases "
         "onto an 810 m grid. The figure for the home's cell is used.", "",
         f"- Years read: {years_text(y['read']) or 'none'}"
         + "".join(f" ({v}: {yrs})" for v, yrs in h["model_versions"].items() if yrs)]
    if y["outside_rsei_coverage"]:
        L.append(f"- No RSEI data exist (unknown): {years_text(y['outside_rsei_coverage'])}")
    if y["not_requested"]:
        L.append(f"- Left out of this run (unknown): {years_text(y['not_requested'])}")
    if h["tri_filings_missing"]:
        L.append(f"- TRI filings not on hand for {years_text(h['tri_filings_missing'])}: a facility with no "
                 "figure in those years is unknown, never zero")
    L += [f"- Gap: {g}" for g in h["gaps"]]
    if "sources_modeled" in h:
        L.append(f"- Sources with a figure at the home: {h['sources_modeled']}; chemicals: {h['chemicals_modeled']}")
    for mid, m in h["members"].items():
        L += ["", f"### Member {mid}", "",
              f"Years at the home: {m['years_at_home']:.3g}. Years with a figure: {m['years_with_a_figure']:.3g}."]
        if not m["chemicals"]:
            L += ["", "No RSEI figure for any year lived at the home. That is unknown, not clean air."]
            continue
        L += ["", f"Added lifetime cancer risk, summed over {count(m['cancer_chemicals'], 'chemical')}: "
              f"**{per_million(m['cancer_risk'])} in a million**"
              + (" (a floor: some years have no figure)." if m["is_floor"] else "."), "",
              table(["Chemical", "Average, µg/m³", "Highest year, µg/m³", "Cancer risk, in a million",
                     "Hazard quotient", "Highest-year quotient", "Years with a figure", "Largest source"],
                    [[c["chemical"] + ("*" if c["floor_years"] else ""), num(c["average_ug_m3"]),
                      num(c["highest_year_ug_m3"]),
                      per_million(c["cancer_risk"]) + (" (age-adjusted)" if c["age_adjusted"] else ""),
                      num(c["hazard_quotient"]), num(c["hazard_quotient_highest_year"]),
                      pct(c["evidence_fraction"]), c["largest_source"] or ""] for c in m["chemicals"]]),
              "", f"Showing {len(m['chemicals'])} of {m['chemicals_with_a_figure']} chemicals; the rest are in "
              "`exposure.csv`. \"No figure\" in a risk column means EPA has no value for that effect, not that "
              "there is none."]
        if any(c["floor_years"] for c in m["chemicals"]):
            L.append("\\* In at least one year a facility that reports this chemical in other years has no "
                     "figure, so that year's value is a floor.")
        if m["facilities"]:
            head = ["Source", "Cancer risk, in a million", "Share", "Largest chemical"]
            rows = [[f["source"], per_million(f["cancer_risk"]), pct(f["share"]), f["largest_chemical"]]
                    for f in m["facilities"]]
            if not r["public"]:
                head.append("Distance, km")
                rows = [row + [f["distance_km"]] for row, f in zip(rows, m["facilities"])]
            L += ["", "Largest contributors to the cancer figure:", "", table(head, rows)]
            if any(c["age_adjusted"] for c in m["chemicals"]):
                L += ["", "Shares follow each source's part of the concentration and are approximate for "
                      "age-adjusted chemicals."]
        if m["hazard_index"]:
            L += ["", "Hazard index by target organ (hazard quotients add only within an organ):", "",
                  table(["Target organ", "Hazard index", "Largest chemical", "Its quotient", "Its largest source"],
                        [[x["organ"], num(x["hazard_index"]), x["largest_chemical"] or "", num(x["largest_hq"]),
                          x["largest_source"] or ""] for x in m["hazard_index"][:TOP_ORGANS]])]
            if len(m["hazard_index"]) > TOP_ORGANS:
                L += ["", f"{len(m['hazard_index']) - TOP_ORGANS} more organs, all lower, are in `results.json`."]
        nv = m["no_value"]
        first = next(iter(h["members"]))
        if mid != first and nv == h["members"][first]["no_value"]:
            L += ["", f"Chemicals with a concentration and no cancer figure: the same as for member {first}."]
            continue
        L += ["", "Chemicals with a concentration and no cancer figure:"]
        if nv["no_unit_risk"]:
            nickel = any("nickel" in c.lower() for c in nv["no_unit_risk"])
            L.append(f"- In EPA's table with no inhalation unit risk ({len(nv['no_unit_risk'])}): "
                     + ", ".join(nv["no_unit_risk"]) + ". This is not a finding that they do not cause cancer."
                     + (" Nickel compounds are a known human carcinogen; EPA's table gives no unit risk "
                        "for the compound group, so nickel adds nothing to the sum." if nickel else ""))
        if nv["reported_as_a_group"]:
            potent = [c for c in nv["reported_as_a_group"] if "dioxin" in c.lower() or "polycyclic" in c.lower()]
            L.append(f"- Reported to TRI as a group ({len(nv['reported_as_a_group'])}): "
                     + ", ".join(nv["reported_as_a_group"]) + ". EPA gives values for individual members of "
                     "these groups, not for the group, and the report does not say which members were "
                     "released, so no value applies."
                     + (f" {' and '.join(potent)} include some of the most potent carcinogens EPA lists; "
                        "leaving them out makes the cancer figure too low by an unknown amount." if potent else ""))
        if nv["not_in_epa_table"]:
            L.append(f"- No value in the EPA table this report uses ({len(nv['not_in_epa_table'])}): "
                     + ", ".join(nv["not_in_epa_table"]) + "."
                     + (" Asbestos is assessed by fiber count, not weight, so a per-microgram value cannot "
                        "be applied to it." if any("asbestos" in c.lower() for c in nv["not_in_epa_table"]) else ""))
        if not (nv["no_unit_risk"] or nv["not_in_epa_table"] or nv["reported_as_a_group"]):
            L.append("- None.")
        if nv["no_reference_concentration"]:
            L.append(f"- In EPA's table with no reference concentration, so no hazard quotient "
                     f"({len(nv['no_reference_concentration'])}): " + ", ".join(nv["no_reference_concentration"]) + ".")
        if m["hazard_index_unassigned"]:
            L.append("- With a hazard quotient and no target organ assigned, so in no hazard index: "
                     + ", ".join(m["hazard_index_unassigned"]) + ".")
    L += ["", "### Limits of this tier", ""] + [f"- {x}" for x in h["limitations"]]
    if TRI_ONLY not in h["limitations"] and not any("reported to TRI" in x for x in h["limitations"]):
        L.append(f"- {TRI_ONLY}")
    return L


def context_md(r):
    c = r["context"]
    L = ["## Neighborhood context: AirToxScreen 2020", ""]
    if c.get("skipped"):
        return L + [f"Not included: {c['skipped']}."]
    place = f"census block {c['block']}" if c.get("block") else "the home's census block"
    L += [f"EPA's AirToxScreen estimates lifetime cancer risk from every kind of source at once, for one "
          f"year (2020). For {place} it gives **{num(c['total_per_million'])} in a million** if 2020's air "
          f"were breathed for a lifetime."]
    if "largest_groups_per_million" in c:
        L += ["", c["rounding"], "", table(["Source group (EPA's label)", "In a million"],
                                           [[k, num(v)] for k, v in c["largest_groups_per_million"].items()])]
    else:
        L += ["", "EPA's breakdown by source group is left out of this public version because it would "
              "identify the block."]
    L += ["",
          "This is a different model, a different year and a full 70-year lifetime. It is shown for "
          "context and is not added to any figure above."]
    return L


def proposed_md(r):
    p = r["proposed"]
    L = [f"## Proposed facility: {p['name']}", "",
         f"Assumed to operate {p['operating_start']} to {p['operating_end']}. "
         f"Dispersion: {p['dispersion_path'] or '**no run**'}"
         + (" with EPA's AERMOD " + p["aermod"]["version"] if p["dispersion_path"] else "") + ".", ""]
    for run in p["runs"]:
        L.append(f"- Run: {run['sources']} sources, {run['hours']} hours of meteorology"
                 + (f", {run['missing_pct']:g}% missing" if run["missing_pct"] else ""))
    for f in p["applicant_files"]:
        L.append(f"- Applicant file {f['file']}: {', '.join(f['averaging'])}; "
                 + (f"nearest filed receptor {f['nearest_receptor_m']:.0f} m from the home; "
                    if "nearest_receptor_m" in f else "") + ("used" if f["used"] else "context only"))
    for c in p["checks"]:
        L.append(f"- Check against the applicant's {c['file']} ({c['group']}): "
                 + (f"applicant {c['filed']:.4g}, this rerun at the filed rates {c['rerun']:.4g}, "
                    if "filed" in c else "this rerun at the filed rates over the applicant's own result, ")
                 + (f"ratio {c['ratio']:.3f}" if c["ratio"] is not None else "no ratio"))
    if p["dispersion_path"] and not p["checks"]:
        L.append("- The rerun was not checked against any result the applicant filed.")
    labels = {"permitted": "Permitted maximum", "expected": "Expected operation (applicant's stated assumption)"}
    for scen, s in p["scenarios"].items():
        L += ["", f"### {labels.get(scen, scen)}", "",
              table(["Chemical", "Concentration at the home, µg/m³", "From", "Rate, g/s", "Notes"],
                    [[c["chemical"], num(c["conc_ug_m3"]) if c["conc_ug_m3"] is not None else "**no number**",
                      c["path"] or "", num(c["rate_g_s"]) if c["rate_g_s"] is not None else "",
                      "; ".join(c["notes"]
                                + ([f"rate × rerun gives {num(c['rate_times_rerun_ug_m3'])}"]
                                   if c["path"] == "applicant output" and c["rate_times_rerun_ug_m3"] is not None
                                   else []))] for c in s["chemicals"]])]
        for mid, m in s["members"].items() if s["chemicals_with_a_figure"] else ():
            if not m["at_home_while_operating"]:
                L += ["", f"Member {mid}: not at the home while the facility operates (stays to {m['stays_to']})."]
                continue
            L += ["", f"Member {mid}, assumed to stay until {m['stays_to']}: added lifetime cancer risk "
                  f"**{per_million(m['cancer_risk'])} in a million** over {count(m['cancer_chemicals'], 'chemical')}."
                  + (" Hazard index: " + ", ".join(f"{x['organ']} {num(x['hazard_index'])}" for x in m["hazard_index"][:4]) + "."
                     if m["hazard_index"] else "")]
            if m["chemicals"]:
                L += ["", table(["Chemical", "Cancer risk, in a million", "Hazard quotient"],
                                [[c["chemical"], per_million(c["cancer_risk"]) + (" (age-adjusted)" if c["age_adjusted"] else ""),
                                  num(c["hazard_quotient"])] for c in m["chemicals"]])]
    if not any(s["chemicals_with_a_figure"] for s in p["scenarios"].values()):
        L += ["", "**No concentration and no exposure figure.** Nothing was estimated in place of the missing inputs."]
    if "permitted" in p["scenarios"] and "expected" not in p["scenarios"]:
        L += ["", "No expected-operation figure: the application documents no operating assumption to base one on."]
    if p["gaps"]:
        L += ["", "### Missing inputs", "", "Each line is something the model did not have. No figure was "
              "estimated in its place.", ""] + [f"- {g}" for g in p["gaps"]]
    if p["records_to_request"]:
        L += ["", "### Records to request", ""] + [f"{i}. {x}" for i, x in enumerate(p["records_to_request"], 1)]
    L += ["", "### Reading the applicant's own modeling", "", LAC_5112,
          "", "### Limits of this tier", ""] + [f"- {x}" for x in p["limitations"]]
    return L


def render_md(r, charts=()):
    L = [f"# {r['title']}", "",
         f"Generated {r['generated']}; history counted to {r['as_of']}. {where(r)}", ""]
    for m in r["members"]:
        L.append(f"- Member {m['id']}: at the home "
                 + ", ".join(f"{p['start']} to {p['end'] or 'now'}" for p in m["residence"])
                 + ("; birth year on file" if m["birth_year_given"] else "; no birth year on file"))
    L.append("")
    if r["public"]:
        L += [PUBLIC_RESIDUAL + (PUBLIC_PATH_1 if (r["proposed"] or {}).get("uses_applicant_output") else ""), ""]
    L += ["## Summary", "", summary(r), ""]
    if r["not_run"]:
        L += ["Not run, so absent from this report: " + "; ".join(r["not_run"]) + ".", ""]
    if r["history"] and r["proposed"] and any(s["chemicals_with_a_figure"] for s in r["proposed"]["scenarios"].values()):
        L += [NOT_COMBINED, ""]
    L += [BENCHMARK, "", WORDING, ""]
    if r["history"]:
        L += history_md(r) + [""]
    if r["context"]:
        L += context_md(r) + [""]
    if r["proposed"]:
        L += proposed_md(r) + [""]
    L += ["## Assumptions that most affect these figures", ""] + [f"- {x}" for x in r["assumptions"]]
    L += ["", "## What would improve confidence", ""] + [f"- {x}" for x in r["improve"]]
    L += ["", "## Not assessed", ""] + [f"- {x}" for x in r["not_assessed"]]
    if charts:
        stems = list(dict.fromkeys(c.rsplit(".", 1)[0].replace("-social-square", "").replace("-social-portrait", "")
                                   .replace("-print", "") for c in charts))
        sizes = sorted({x for c in charts for x in ("print", "social-square", "social-portrait") if f"-{x}." in c})
        L += ["", "## Charts", "", f"Each as {', '.join(sizes)}:", ""] + [f"- `{c}`" for c in stems]
    L += ["", "## Method and files", "",
          "- `exposure.csv`: every concentration behind the tables; `results.json`: this report as data; "
          "`manifest.json`: data sources, versions, file hashes and assumptions.",
          "- Toxicity values: EPA OAQPS Table 1, Prioritized Chronic Dose-Response Values, "
          f"{toxvalues.TABLE_DATE}. Target organs: EPA AirToxScreen 2020 pollutant list.",
          "- Calculations: `references/methods.md` in the `household-exposure` skill. Limits: `references/limitations.md`."]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------ manifest.json

def manifest(r, out, scr, mod, outputs, written_to):
    """What the report was made from. A public manifest hashes only files that are public
    records: a hash of anything computed from the home's coordinates can be matched against
    candidate locations."""
    public = r["public"]

    def entry(path, name=None):
        return {"file": name or (os.path.basename(path) if public else path),
                "sha256": sha256(path), "bytes": os.path.getsize(path)}
    inputs = []
    tri = os.path.join(out, "raw", "tri")
    if os.path.isdir(tri):
        inputs += [entry(os.path.join(tri, f), f"raw/tri/{f}") for f in sorted(os.listdir(tri))]
    for f in (mod or {}).get("inputs") or []:
        if os.path.exists(f["path"]):
            inputs.append({"role": f["role"], **entry(f["path"])})
    if not public:
        for rel in ("assessment.json", "screening.json", "screen.csv", "model.json", "model.csv", "facilities.csv"):
            if os.path.exists(os.path.join(out, rel)):
                inputs.append(entry(os.path.join(out, rel), rel))
        for sub in ("rsei", "airtox"):
            d = os.path.join(out, "raw", sub)
            if os.path.isdir(d):
                inputs += [entry(os.path.join(d, f), f"raw/{sub}/{f}") for f in sorted(os.listdir(d))
                           if os.path.isfile(os.path.join(d, f))]
    return {
        "generated": r["generated"], "public": public, "skill": "bayou:household-exposure",
        "scripts": {f: sha256(os.path.join(HERE, f)) for f in SCRIPTS if os.path.exists(os.path.join(HERE, f))},
        "data_sources": {
            "toxicity": toxvalues.provenance(),
            "rsei": (scr or {}).get("provenance", {}).get("rsei"),
            "tri": "https://data.epa.gov/efservice/downloads/tri/ (basic data files, one per state and year)",
            "airtoxscreen": None if not scr or scr["airtoxscreen"].get("skipped") else
            {"year": 2020, "file": "Region6a_CancerRisk_by_block_srcgrp.xlsx",
             "url": "https://gaftp.epa.gov/rtrmodeling_public/AirToxScreen/2020/"},
            "aermod": (mod or {}).get("provenance", {}).get("aermod"),
        },
        "inputs": inputs,
        "outputs": [{"file": os.path.relpath(p, written_to), "sha256": sha256(p)} for p in outputs],
        "assumptions": r["assumptions"],
    }
