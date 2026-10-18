#!/usr/bin/env python3
"""EPA Risk Management Program (CAA 112(r)) data for a facility: regulated substances and quantities by
process, program levels, prevention program, emergency response, executive summary, accident history.

Source: the Data Liberation Project's FOIA'd copy of EPA's RMP database, published as static JSON
(https://data-liberation-project.github.io/epa-rmp-viewer/). CC BY-SA 4.0. EPA itself no longer
publishes RMP data online. Off-site consequence analysis (worst-case / alternative scenarios) and
facility emergency-contact names are not in this data.

Run with: uv run -q --no-project python -I rmp.py <command> ...
Cache: ~/.cache/bayou/epa-rmp-lookup/ (state lists, facility indexes, lookups: 7 days; submissions:
kept, since a validated submission never changes).

  rmp.py health                                       sources up, data vintage
  rmp.py search "<name>" [--state LA] [--city X]      facilities by current or previous name
  rmp.py near <lat> <lon> --radius-km N [--state LA]  facilities by distance from a point
  rmp.py facility <EPAFacilityID> [--submission ID]   chemicals, processes, prevention, ER, accidents
  rmp.py accidents <EPAFacilityID> [--csv out.csv]    every accident across all submissions, deduped
  rmp.py summary <EPAFacilityID|submission ID>        executive summary text
  rmp.py crosswalk <EPAFacilityID>                    FRS registry ID and other program IDs
  rmp.py oca                                          how to see worst-case scenario data (not online)
"""
import argparse
import csv
import datetime
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

CACHE = os.path.expanduser("~/.cache/bayou/epa-rmp-lookup")
TTL = 7 * 24 * 3600
UA = "Mozilla/5.0 (bayou-epa-rmp-lookup)"
BASE = "https://data-liberation-project.github.io/epa-rmp-viewer/data/"
VIEWER = "https://data-liberation-project.github.io/epa-rmp-viewer/#/"
CHANGES = "https://api.github.com/repos/data-liberation-project/epa-rmp-spreadsheets/contents/data/changes"
FRS = "https://data.epa.gov/efservice/FRS_PROGRAM_FACILITY/"
ATTRIB = "EPA RMP database via the Data Liberation Project (FOIA), CC BY-SA 4.0"
# Territories east of the antimeridian legitimately carry positive longitudes.
EAST_LON_STATES = {"GU", "MP"}
NOT_IN_DATA = ("Not in this data: off-site consequence analysis (worst-case and alternative release "
               "scenarios; federal reading rooms only, see `oca`) and facility emergency-contact names, "
               "titles and 24-hour phones (only the coordinating response agency and LEPC are present).")
ACC_NOTE = ("Each RMP submission lists only accidents in the 5 years before it, so the all-time list is built "
            "from every submission; accidents on the same day are treated as one event and the newest "
            "submission's version is kept (the Data Liberation Project's rule). A facility listing none is "
            "'none reported', not 'none occurred'. RMP accident criteria (on-site deaths, injuries or significant "
            "property damage; known off-site deaths, injuries, evacuations, sheltering in place, property or "
            "environmental damage) are far narrower than NRC reportable-quantity releases.")


class SourceDown(Exception):
    pass


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- HTTP and cache

def _get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SourceDown("%s: HTTP %s" % (url, e.code))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceDown("%s: %s" % (url, e))


def fetch_json(rel, ttl=TTL, refresh=False):
    """JSON at BASE+rel, or None when the file does not exist (unknown ID)."""
    path = os.path.join(CACHE, rel)
    fresh = os.path.exists(path) and (ttl is None or time.time() - os.path.getmtime(path) < ttl)
    if fresh and not refresh:
        with open(path) as fh:
            return json.load(fh)
    try:
        body = _get(BASE + rel)
    except SourceDown:
        if os.path.exists(path):
            print("note: %s unreachable; using cached copy" % (BASE + rel), file=sys.stderr)
            with open(path) as fh:
                return json.load(fh)
        raise
    if body is None:
        return None
    data = json.loads(body)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "wb") as fh:
        fh.write(body)
    os.replace(path + ".part", path)
    return data


_lookups = None


def lookups(refresh=False):
    global _lookups
    if _lookups is None:
        _lookups = fetch_json("lookups/lookups.json", refresh=refresh) or {}
    return _lookups


def decode(kind, code):
    if code is None:
        return None
    return lookups().get(kind, {}).get(str(code), str(code))


def submission(sid, refresh=False):
    return fetch_json("submissions/%s.json" % sid, ttl=None, refresh=refresh)


def detail(fid, refresh=False):
    d = fetch_json("facilities/detail/%s.json" % fid, refresh=refresh)
    if d is None:
        die("EPAFacilityID %s not found in the RMP data (vintage: see `health`)" % fid, 3)
    return d


def state_facilities(state, refresh=False):
    st = fetch_json("facilities/by-state/%s.json" % state.upper(), refresh=refresh)
    if st is None:
        die("no RMP state file for %r (use a two-letter code)" % state, 3)
    out = []
    for c in st.get("counties", []):
        for f in c.get("facilities", []):
            f = dict(f)
            f["county"] = c.get("name")
            f["state"] = state.upper()
            out.append(f)
    return out


def fix_lon(lat, lon, state):
    """Longitude with a dropped minus sign restored; second value says whether it was flipped."""
    if lon is None:
        return lon, False
    if lon > 0 and state not in EAST_LON_STATES:
        return -lon, True
    return lon, False


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def vintage(facs):
    dates = [f["sub_last"]["date_val"] for f in facs if f.get("sub_last", {}).get("date_val")]
    return max(dates) if dates else None


def src(rel):
    return {"source": BASE + rel, "attribution": ATTRIB, "retrieved": today()}


def yes_flags(rec, prefix):
    """Names of Yes-valued flags with a prefix, plus any free-text 'Other' entry."""
    out = []
    for k, v in rec.items():
        if not k.startswith(prefix):
            continue
        if v == "Yes" and not k.endswith(("None", "NoneRequired")):
            out.append(k[len(prefix):])
        elif "Other" in k and v not in (None, "", "No", "Yes"):
            out.append("other: %s" % v)
    return out


def d10(s):
    return s[:10] if isinstance(s, str) else s


# ---------------------------------------------------------------- commands

def cmd_health(a):
    res = {"retrieved": today(), "checks": []}
    states = fetch_json("facilities/states.json", refresh=a.refresh)
    res["checks"].append({"what": "states.json", "ok": bool(states),
                          "facilities": sum(s["count"] for s in states or []), "states": len(states or [])})
    la = state_facilities("LA", a.refresh)
    res["checks"].append({"what": "by-state/LA.json", "ok": bool(la), "facilities": len(la),
                          "active": sum(1 for f in la if not f["sub_last"].get("date_dereg")),
                          "latest_validation": vintage(la)})
    lk = lookups(a.refresh)
    res["checks"].append({"what": "lookups.json", "ok": bool(lk), "chemicals": len(lk.get("ChemicalID", {}))})
    try:
        ch = json.loads(_get(CHANGES) or b"[]")
        months = sorted(x["name"] for x in ch if x.get("type") == "dir")
        res["checks"].append({"what": "DLP data updates (epa-rmp-spreadsheets/data/changes)", "ok": bool(months),
                              "latest_update": months[-1] if months else None})
    except (SourceDown, ValueError) as e:
        res["checks"].append({"what": "DLP data updates", "ok": False, "error": str(e)})
    return res


def cmd_search(a):
    q = norm(a.name)
    words = q.split()
    states = [s.strip().upper() for s in a.state.split(",")]
    hits, allf = [], []
    for st in states:
        facs = state_facilities(st, a.refresh)
        allf += facs
        for f in facs:
            names = [f["name"]] + f.get("names_prev", [])
            hay = " | ".join(norm(n) for n in names) + " | " + norm(f.get("address")) + " | " + norm(f.get("city"))
            if not all(w in hay for w in words):
                continue
            if a.city and norm(a.city) not in norm(f.get("city")):
                continue
            if f["sub_last"].get("date_dereg") and not a.include_dereg:
                continue
            hits.append(row(f))
    hits.sort(key=lambda r: (r["deregistered"] is not None, r["name"]))
    out = {"query": a.name, "states": states, "results": hits, "data_through": vintage(allf)}
    out.update(src("facilities/by-state/"))
    if not hits:
        out["hint"] = ("no match; RMP names are the operator's own (e.g. 'Equilon Enterprises LLC dba Shell-NORCO'), "
                       "so search a distinctive word, add --include-dereg, or use `near`")
    return out


def row(f, extra=None):
    s = f["sub_last"]
    lon, flipped = fix_lon(s.get("lat_sub"), s.get("lon_sub"), f.get("state"))
    r = {"EPAFacilityID": f["EPAFacilityID"], "name": f["name"], "names_prev": f.get("names_prev", []),
         "address": f.get("address"), "city": f.get("city"), "county": f.get("county"),
         "latest_submission": s.get("id"), "validated": s.get("date_val"), "deregistered": s.get("date_dereg"),
         "lat": s.get("lat_sub"), "lon": lon, "lon_sign_fixed": flipped,
         "accidents_latest_sub": s.get("num_accidents"), "latest_accident": s.get("latest_accident")}
    if extra:
        r.update(extra)
    return r


def cmd_near(a):
    states = [s.strip().upper() for s in a.state.split(",")]
    hits, allf = [], []
    for st in states:
        facs = state_facilities(st, a.refresh)
        allf += facs
        for f in facs:
            s = f["sub_last"]
            if s.get("lat_sub") is None or s.get("lon_sub") is None:
                continue
            lon, _ = fix_lon(s["lat_sub"], s["lon_sub"], st)
            d = haversine_km(a.lat, a.lon, s["lat_sub"], lon)
            if d <= a.radius_km and (a.include_dereg or not s.get("date_dereg")):
                hits.append(row(f, {"distance_km": round(d, 3)}))
    hits.sort(key=lambda r: r["distance_km"])
    out = {"point": [a.lat, a.lon], "radius_km": a.radius_km, "states": states, "results": hits,
           "data_through": vintage(allf),
           "note": ("Distances use the coordinate in the latest RMP submission (often an office or process "
                    "unit, self-reported); check `facility` for FRS_Lat/FRS_Long and the location method.")}
    out.update(src("facilities/by-state/"))
    return out


def chem_rows(proc):
    out = []
    for c in proc.get("_chemicals", []):
        r = {"chemical": decode("ChemicalID", c.get("ChemicalID")), "chemical_id": c.get("ChemicalID"),
             "quantity_lb": c.get("Quantity"), "cbi": c.get("CBI_Flag")}
        mix = [decode("ChemicalID", m.get("ChemicalID")) for m in c.get("_flam_mix_chemicals", [])]
        if mix:
            r["mixture_components"] = mix
        out.append(r)
    return out


def prevention(proc):
    out = []
    for n in proc.get("_naics", []):
        for key, lvl in (("_prev_prog_3", 3), ("_prev_prog_2", 2)):
            for p in n.get(key, []):
                out.append({
                    "naics": n.get("NAICSCode"), "program": lvl,
                    "pha_date": d10(p.get("PHA_Date")),
                    # The expected date for resolving the PHA's recommendations, so it can be in the future.
                    "pha_changes_complete_by": d10(p.get("PHACompletionDate")),
                    "pha_techniques": [k[4:] for k in p if k.startswith("PHA_") and p[k] == "Yes"],
                    "hazards": yes_flags(p, "MH_"), "process_controls": yes_flags(p, "PC_"),
                    "mitigation": yes_flags(p, "MS_"), "detection": yes_flags(p, "MD_"),
                    "changes_since_pha": yes_flags(p, "CH_"),
                    "compliance_audit": d10(p.get("ComplianceAuditDate")),
                    "incident_investigation": d10(p.get("IncidentInvestigationDate")),
                    "safety_review": d10(p.get("SafetyReviewDate"))})
    return out


def accident_row(acc, sub_id):
    chems = []
    for c in acc.get("_chemicals", []):
        chems.append({"chemical": decode("ChemicalID", c.get("ChemicalID")), "quantity_lb": c.get("QuantityReleased"),
                      "percent_weight": c.get("PercentWeight"),
                      "mixture_components": [decode("ChemicalID", m.get("ChemicalID"))
                                             for m in c.get("_flam_mix_chemicals", [])] or None})
    num = lambda k: acc.get(k) or 0
    return {
        "date": d10(acc.get("AccidentDate")), "time": acc.get("AccidentTime"), "from_submission": sub_id,
        "duration_min": acc.get("AccidentReleaseDuration"), "naics": acc.get("NAICSCode"),
        "chemicals": chems, "release_events": yes_flags(acc, "RE_"), "release_sources": yes_flags(acc, "RS_"),
        "deaths": {"workers": num("DeathsWorkers"), "public_responders": num("DeathsPublicResponders"),
                   "public": num("DeathsPublic"), "offsite": num("OffsiteDeaths")},
        "injuries": {"workers": num("InjuriesWorkers"), "public_responders": num("InjuriesPublicResponders"),
                     "public": num("InjuriesPublic")},
        "offsite": {"hospitalization": num("Hospitalization"), "medical_treatment": num("MedicalTreatment"),
                    "evacuated": num("Evacuated"), "sheltered_in_place": num("ShelteredInPlace"),
                    "property_damage_usd": num("OffsitePropertyDamage")},
        "onsite_property_damage_usd": num("OnsitePropertyDamage"),
        "environmental_damage": yes_flags(acc, "ED_"),
        "initiating_event": decode("InitiatingEvent", acc.get("InitiatingEvent")),
        "contributing_factors": yes_flags(acc, "CF_"), "changes_made": yes_flags(acc, "CI_"),
        "offsite_responders": acc.get("OffsiteRespondersNotify"),
        "weather": {"wind_speed": acc.get("WindSpeed"), "wind_dir": acc.get("WindDirection"),
                    "temp_f": acc.get("Temperature"), "stability": acc.get("StabilityClass")},
    }


def all_accidents(det, refresh=False):
    """Accidents from every submission; same-day reports collapse to the newest submission's version."""
    subs = sorted(det.get("submissions", []), key=lambda s: (s.get("date_val") or "", s["id"]), reverse=True)
    seen, out, per_sub = set(), [], []
    for s in subs:
        sub = submission(s["id"], refresh) or {}
        accs = sub.get("_accidents", [])
        per_sub.append({"submission": s["id"], "validated": s.get("date_val"), "listed": len(accs),
                        "NoAccidents_flag": sub.get("NoAccidents")})
        within = set()
        for acc in accs:
            day = d10(acc.get("AccidentDate"))
            # Two accidents in one submission on the same day are distinct events (DLP rule).
            if day in seen and day not in within:
                continue
            within.add(day)
            out.append(accident_row(acc, s["id"]))
        seen |= within
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out, per_sub


def cmd_facility(a):
    det = detail(a.id, a.refresh)
    subs = det.get("submissions", [])
    sid = a.submission or (subs[0]["id"] if subs else None)
    sub = submission(sid, a.refresh) if sid else None
    if not sub:
        die("submission %s not found" % sid, 3)
    lon, flipped = fix_lon(sub.get("FacilityLatDecDegs"), sub.get("FacilityLongDecDegs"), sub.get("FacilityState"))
    procs = [{"process": p.get("AltID"), "program_level": p.get("ProgramLevel"),
              "naics": [n.get("NAICSCode") for n in p.get("_naics", [])],
              "naics_desc": [decode("NAICSCode", n.get("NAICSCode")) for n in p.get("_naics", [])],
              "chemicals": chem_rows(p), "prevention": prevention(p)} for p in sub.get("_processes", [])]
    by_chem = {}
    for p in procs:
        for c in p["chemicals"]:
            b = by_chem.setdefault(c["chemical"], {"chemical": c["chemical"], "processes": 0, "max_in_one_process_lb": 0})
            b["processes"] += 1
            b["max_in_one_process_lb"] = max(b["max_in_one_process_lb"], c["quantity_lb"] or 0)
    er = sub.get("_emerg_resp") or {}
    accs, per_sub = all_accidents(det, a.refresh)
    res = {
        "EPAFacilityID": det["EPAFacilityID"], "name": det["name"], "submission": sid,
        "submission_type": sub.get("SubmissionType"),
        "submission_reason": decode("RMPSubmissionReasonCode", sub.get("RMPSubmissionReasonCode")),
        "received": d10(sub.get("ReceiptDate")), "validated": next((s.get("date_val") for s in subs if s["id"] == sid), None),
        "anniversary_due": d10(sub.get("AnniversaryDate")),
        "deregistered": d10(sub.get("DeRegistrationDate")),
        "dereg_reason": decode("DeregistrationReasonCode", sub.get("DeregistrationReasonCode")),
        "dereg_other": sub.get("DeregistrationReasonOtherText"),
        "address": ", ".join(x for x in (sub.get("FacilityStr1"), sub.get("FacilityStr2"), sub.get("FacilityCity"),
                                          sub.get("FacilityState"), sub.get("FacilityZipCode")) if x),
        "county_fips": sub.get("FacilityCountyFIPS"), "lepc": sub.get("LEPC"),
        "lat": sub.get("FacilityLatDecDegs"), "lon": lon, "lon_sign_fixed": flipped,
        "latlon_method": decode("LatLongMethod", sub.get("LatLongMethod")),
        "latlon_describes": decode("LatLongDescription", sub.get("LatLongDescription")),
        "frs_lat": sub.get("FRS_Lat"), "frs_lon": sub.get("FRS_Long"),
        "parent": sub.get("ParentCompanyName"), "parent_2": sub.get("Company2Name"), "operator": sub.get("OperatorName"),
        "fte": sub.get("FTE"), "osha_psm": sub.get("OSHA_PSM"), "epcra_302": sub.get("EPCRA_302"),
        "title_v": sub.get("CAA_TitleV"), "title_v_permit": sub.get("ClearAirOpPermitID"),
        "last_safety_inspection": d10(sub.get("SafetyInspectionDate")), "inspected_by": sub.get("SafetyInspectionBy"),
        "other_epa_id": sub.get("OtherEPAFacilityID"), "duns": sub.get("FacilityDUNS"),
        "processes": procs, "chemicals_summary": sorted(by_chem.values(), key=lambda c: -c["max_in_one_process_lb"]),
        "emergency_response": {
            "community_plan": er.get("ER_CommunityPlan"), "facility_plan": er.get("ER_FacilityPlan"),
            "response_actions": er.get("ER_ResponseActions"), "public_info_procedures": er.get("ER_PublicInfoProcedures"),
            "emergency_health_care": er.get("ER_EmergencyHealthCare"), "plan_review": d10(er.get("ER_ReviewDate")),
            "training": d10(er.get("ERTrainingDate")),
            "coordinating_agency": er.get("CoordinatingAgencyName"), "coordinating_agency_phone": er.get("CoordinatingAgencyPhone"),
            "other_regulations": yes_flags(er, "FR_"),
            "exercise_plan": [er.get("ExercisePlan"), d10(er.get("ExercisePlanDate"))],
            "notification_drill": [er.get("NotificationDrill"), d10(er.get("NotificationDrillDate"))],
            "tabletop": [er.get("TabletopExercise"), d10(er.get("TabletopExerciseDate"))],
            "lepc_coordination": [er.get("LEPCCoordination"), d10(er.get("LEPCCoordinationDate")), er.get("LEPCCoordinationReason")],
            "local_agency_coordination": [er.get("LocalResponseAgencyCoordination"),
                                          d10(er.get("LocalResponseAgencyCoordinationDate")),
                                          er.get("LocalResponseAgencyCoordinationReason")],
            "responds_itself": er.get("StationarySource")} if er else None,
        "submissions": [{"id": s["id"], "received": s.get("date_rec"), "validated": s.get("date_val"),
                         "deregistered": s.get("date_dereg"), "name": s.get("name"), "operator": s.get("operator"),
                         "accidents_listed": s.get("num_accidents")} for s in subs],
        "accidents": accs, "accidents_per_submission": per_sub,
        "exec_summary_chars": sum(len(x.get("SummaryText") or "") for x in sub.get("_exec_summary", [])),
        "not_in_data": NOT_IN_DATA, "accident_note": ACC_NOTE,
        "viewer": VIEWER + "submission:%s" % sid,
    }
    res.update(src("submissions/%s.json" % sid))
    return res


def cmd_accidents(a):
    det = detail(a.id, a.refresh)
    accs, per_sub = all_accidents(det, a.refresh)
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["EPAFacilityID", "facility", "date", "time", "from_submission", "chemical", "quantity_lb",
                        "deaths_total", "injuries_total", "offsite_evacuated", "offsite_sheltered",
                        "onsite_damage_usd", "offsite_damage_usd", "initiating_event", "contributing_factors"])
            for r in accs:
                for c in r["chemicals"] or [{}]:
                    w.writerow([det["EPAFacilityID"], det["name"], r["date"], r["time"], r["from_submission"],
                                c.get("chemical"), c.get("quantity_lb"), sum(r["deaths"].values()),
                                sum(r["injuries"].values()), r["offsite"]["evacuated"], r["offsite"]["sheltered_in_place"],
                                r["onsite_property_damage_usd"], r["offsite"]["property_damage_usd"],
                                r["initiating_event"], "; ".join(r["contributing_factors"])])
    res = {"EPAFacilityID": det["EPAFacilityID"], "name": det["name"], "accidents": accs,
           "accidents_per_submission": per_sub, "accident_note": ACC_NOTE, "csv": a.csv}
    res.update(src("submissions/"))
    return res


def cmd_summary(a):
    sid = a.id
    if len(str(a.id)) == 12 and str(a.id).startswith("1000"):
        det = detail(a.id, a.refresh)
        sid = det["submissions"][0]["id"]
    sub = submission(sid, a.refresh)
    if not sub:
        die("submission %s not found" % sid, 3)
    parts = sorted(sub.get("_exec_summary", []), key=lambda x: x.get("ESSeqNum") or 0)
    res = {"EPAFacilityID": sub.get("EPAFacilityID"), "name": sub.get("FacilityName"), "submission": sid,
           "text": "".join(p.get("SummaryText") or "" for p in parts),
           "note": ("The executive summary is the facility's own narrative. Any worst-case or alternative "
                    "scenario it describes is the operator's summary, not the OCA data, which is reading-room only.")}
    res.update(src("submissions/%s.json" % sid))
    return res


def frs(path):
    body = _get(FRS + path + "/JSON", timeout=120)
    return json.loads(body) if body else []


def cmd_crosswalk(a):
    det = detail(a.id, a.refresh)
    sid = det["submissions"][0]["id"]
    sub = submission(sid, a.refresh) or {}
    other = (sub.get("OtherEPAFacilityID") or "").strip()
    res = {"EPAFacilityID": det["EPAFacilityID"], "name": det["name"], "other_epa_id": other or None,
           "frs_lat": sub.get("FRS_Lat"), "frs_lon": sub.get("FRS_Long"), "registries": [],
           "note": ("FRS carries no RMP program records, so the bridge is the OtherEPAFacilityID the facility "
                    "entered in its RMP (usually its RCRA handler ID or TRI facility ID). One ID can map to more than one registry "
                    "(e.g. a SEMS site record); pick the registry whose programs and address fit."),
           "retrieved": today()}
    if not other:
        res["hint"] = "no OtherEPAFacilityID in the RMP; resolve by name and address with epa-frs-crosswalk"
        return res
    rows = frs("PGM_SYS_ID/%s" % other)
    for rid in sorted({r["registry_id"] for r in rows}):
        progs = frs("REGISTRY_ID/%s" % rid)
        res["registries"].append({
            "registry_id": rid, "matched_as": sorted({r["pgm_sys_acrnm"] for r in rows if r["registry_id"] == rid}),
            "primary_name": next((r.get("primary_name") for r in progs), None),
            "programs": sorted({(r["pgm_sys_acrnm"], r["pgm_sys_id"]) for r in progs})})
    res["registries"].sort(key=lambda r: -len(r["programs"]))
    if not res["registries"]:
        res["hint"] = "%s not found in FRS; resolve by name and address with epa-frs-crosswalk" % other
    return res


def cmd_oca(a):
    return {"retrieved": today(), "checked_any_data": False, "routes": [
        "Off-site consequence analysis (OCA: worst-case and alternative release scenarios, distance to "
        "endpoint, residential population and public receptors within it) is kept off the internet under "
        "CAA 112(r)(7)(H) and 40 CFR Part 1400. It is NOT in the FOIA'd data this skill reads, and nothing in "
        "this skill's output reflects it.",
        "Federal Reading Rooms (epa.gov/rmp/federal-reading-rooms-risk-management-plans-rmp): read and take "
        "notes on OCA, no copying, for up to 10 facilities a calendar month anywhere (government photo ID, "
        "signed certification), plus every facility located in or potentially affecting the LEPC jurisdiction "
        "where you live or work (bring proof of address). 'By appointment' rooms need several days' notice and "
        "the facility list in advance; call walk-in rooms ahead too. Reading rooms also give the current non-OCA "
        "RMP on request, which may postdate this skill's FOIA copy.",
        "Vulnerable Zone Indicator System (epa.gov/rmp/forms/vulnerable-zone-indicator-system): enter a street "
        "address or lat/lon and EPA answers by e-mail whether it may lie within the vulnerable zone of one or "
        "more RMP facilities; also through the RMP Reporting Center, 703-227-7650, RMPRC@epacdx.net. No PO "
        "boxes. Use it to show a home is inside a zone, and to qualify for the local reading-room allowance.",
        "State and local government officials receive OCA for official use (40 CFR 1400.9), so parish emergency "
        "managers may hold it. Ask the parish LEPC or emergency "
        "management office (the `lepc` field in `facility`).",
        "FOIA through EPA's PAL for non-OCA RMP records. EPA's online RMP Public Data Tool is offline pending "
        "the Common Sense Approach proposal (91 FR 8970, Feb. 24, 2026, docket EPA-HQ-OLEM-2025-0313).",
        "The 2024 rule's 40 CFR 68.210(d)-(h) duty to give residents within 6 miles hazard information on "
        "request has a compliance date of May 10, 2028, and the 2026 proposal may change it, so it cannot be "
        "invoked yet. Check ecfr.gov before citing it.",
    ]}


# ---------------------------------------------------------------- output

def fmt_n(x):
    return "{:,}".format(x) if isinstance(x, (int, float)) else str(x)


def show(cmd, r):
    p = print
    if cmd == "health":
        for c in r["checks"]:
            p("%-4s %s  %s" % ("ok" if c.get("ok") else "FAIL", c["what"],
                               ", ".join("%s=%s" % (k, v) for k, v in c.items() if k not in ("what", "ok"))))
        p("retrieved %s" % r["retrieved"])
        return
    if cmd in ("search", "near"):
        p("%d facilities%s (data through %s)" % (len(r["results"]),
                                                 " within %s km of %s" % (r["radius_km"], r["point"]) if cmd == "near" else
                                                 " matching %r in %s" % (r["query"], ",".join(r["states"])), r["data_through"]))
        for f in r["results"]:
            p("  %s  %s%s" % (f["EPAFacilityID"], f["name"],
                              "  [%.2f km]" % f["distance_km"] if "distance_km" in f else ""))
            p("      %s, %s (%s); latest sub %s validated %s%s" % (
                f["address"], f["city"], f["county"], f["latest_submission"], f["validated"],
                "; DEREGISTERED %s" % f["deregistered"] if f["deregistered"] else ""))
            if f["names_prev"]:
                p("      previously: %s" % "; ".join(f["names_prev"]))
            if f["latest_accident"]:
                p("      latest submission lists %s accident(s), latest %s" % (f["accidents_latest_sub"], f["latest_accident"]))
            if f["lon_sign_fixed"]:
                p("      (longitude sign restored from the RMP's positive value)")
        if r.get("hint"):
            p(r["hint"])
        if r.get("note"):
            p("note: " + r["note"])
        p("Source: %s; %s; retrieved %s" % (r["source"], r["attribution"], r["retrieved"]))
        return
    if cmd == "facility":
        p("%s  (EPAFacilityID %s)" % (r["name"], r["EPAFacilityID"]))
        p("  %s; LEPC: %s" % (r["address"], r["lepc"]))
        p("  parent %s | operator %s | FTE %s" % (r["parent"], r["operator"], r["fte"]))
        p("  submission %s (%s, %s) received %s, validated %s; 5-year update due %s" % (
            r["submission"], r["submission_type"], r["submission_reason"], r["received"], r["validated"], r["anniversary_due"]))
        if r["deregistered"]:
            p("  DEREGISTERED %s: %s %s" % (r["deregistered"], r["dereg_reason"], r["dereg_other"] or ""))
        p("  OSHA PSM %s | EPCRA 302 %s | Title V %s (%s) | last safety inspection %s by %s" % (
            r["osha_psm"], r["epcra_302"], r["title_v"], r["title_v_permit"], r["last_safety_inspection"], r["inspected_by"]))
        p("  location %s, %s (%s; %s)%s | FRS %s, %s | other EPA ID %s" % (
            r["lat"], r["lon"], r["latlon_method"], r["latlon_describes"],
            " [lon sign restored]" if r["lon_sign_fixed"] else "", r["frs_lat"], r["frs_lon"], r["other_epa_id"]))
        p("\nRegulated substances (largest quantity held in any one process; RMP quantities are per process, "
          "so they are not summed):")
        for c in r["chemicals_summary"]:
            p("  %15s lb  %s  (%d process%s)" % (fmt_n(c["max_in_one_process_lb"]), c["chemical"], c["processes"],
                                                 "" if c["processes"] == 1 else "es"))
        p("\nProcesses:")
        for pr in r["processes"]:
            p("  [P%s] %s  NAICS %s" % (pr["program_level"], pr["process"], ", ".join(map(str, pr["naics"]))))
            for c in pr["chemicals"]:
                p("        %13s lb  %s%s" % (fmt_n(c["quantity_lb"]), c["chemical"],
                                            " (mixture: %s)" % ", ".join(c["mixture_components"]) if c.get("mixture_components") else ""))
            for pv in pr["prevention"]:
                p("        program %s: PHA %s (%s), its changes due %s; audit %s; hazards: %s" % (
                    pv["program"], pv["pha_date"], ", ".join(pv["pha_techniques"]) or "-", pv["pha_changes_complete_by"],
                    pv["compliance_audit"], ", ".join(pv["hazards"]) or "-"))
        er = r["emergency_response"]
        if er:
            p("\nEmergency response: coordinating agency %s (%s); facility responds itself: %s" % (
                er["coordinating_agency"], er["coordinating_agency_phone"], er["responds_itself"]))
            p("  community plan %s | facility plan %s | plan review %s | training %s" % (
                er["community_plan"], er["facility_plan"], er["plan_review"], er["training"]))
            p("  exercise plan %s | notification drill %s | tabletop %s | LEPC coordination %s" % (
                er["exercise_plan"], er["notification_drill"], er["tabletop"], er["lepc_coordination"]))
        p("\nSubmission history:")
        for s in r["submissions"]:
            p("  %s received %s validated %s%s  %s / %s%s" % (
                s["id"], s["received"], s["validated"], " dereg %s" % s["deregistered"] if s["deregistered"] else "",
                s["name"], s["operator"], "  [%s accident(s)]" % s["accidents_listed"] if s["accidents_listed"] else ""))
        show_accidents(r)
        p("\nExecutive summary: %s characters (`summary %s`)" % (r["exec_summary_chars"], r["EPAFacilityID"]))
        p(r["not_in_data"])
        p("Viewer: %s" % r["viewer"])
        p("Source: %s; %s; retrieved %s" % (r["source"], r["attribution"], r["retrieved"]))
        return
    if cmd == "accidents":
        p("%s  (EPAFacilityID %s)" % (r["name"], r["EPAFacilityID"]))
        show_accidents(r, full=True)
        if r.get("csv"):
            p("wrote %s" % r["csv"])
        p("Source: %s; %s; retrieved %s" % (r["source"], r["attribution"], r["retrieved"]))
        return
    if cmd == "summary":
        p("%s  submission %s\n" % (r["name"], r["submission"]))
        p(r["text"])
        p("\nnote: " + r["note"])
        p("Source: %s; %s; retrieved %s" % (r["source"], r["attribution"], r["retrieved"]))
        return
    if cmd == "crosswalk":
        p("%s  (EPAFacilityID %s); OtherEPAFacilityID %s; FRS point %s, %s" % (
            r["name"], r["EPAFacilityID"], r["other_epa_id"], r["frs_lat"], r["frs_lon"]))
        for g in r["registries"]:
            p("  registry %s  %s  (matched as %s)" % (g["registry_id"], g["primary_name"], ", ".join(g["matched_as"])))
            for acr, pid in g["programs"]:
                p("      %-10s %s" % (acr, pid))
        if r.get("hint"):
            p(r["hint"])
        p("note: " + r["note"])
        p("Source: %s (Envirofacts); retrieved %s" % (FRS, r["retrieved"]))
        return
    if cmd == "oca":
        for x in r["routes"]:
            p("- " + x)


def show_accidents(r, full=False):
    p = print
    accs = r["accidents"]
    p("\nAccident history, all submissions: %d event(s)" % len(accs))
    for x in accs:
        chem = "; ".join("%s %s lb" % (c["chemical"], fmt_n(c["quantity_lb"])) for c in x["chemicals"]) or "(no chemical listed in the RMP)"
        p("  %s %s  %s  [from submission %s]" % (x["date"], x["time"] or "", chem, x["from_submission"]))
        p("      deaths %s | injuries %s | offsite: evacuated %s, sheltered %s, hospitalized %s | damage on-site $%s off-site $%s" % (
            sum(x["deaths"].values()), sum(x["injuries"].values()), x["offsite"]["evacuated"],
            x["offsite"]["sheltered_in_place"], x["offsite"]["hospitalization"],
            fmt_n(x["onsite_property_damage_usd"]), fmt_n(x["offsite"]["property_damage_usd"])))
        p("      initiating event: %s; contributing: %s; changes: %s" % (
            x["initiating_event"], ", ".join(x["contributing_factors"]) or "-", ", ".join(x["changes_made"]) or "-"))
        if full:
            p("      release: %s from %s; duration %s min; env. damage: %s; responders: %s; weather %s" % (
                ", ".join(x["release_events"]) or "-", ", ".join(x["release_sources"]) or "-", x["duration_min"],
                ", ".join(x["environmental_damage"]) or "-", x["offsite_responders"], x["weather"]))
    flag = [s for s in r["accidents_per_submission"] if s["NoAccidents_flag"] == "No" and s["listed"] == 0]
    if flag:
        p("  note: submission(s) %s set NoAccidents=No but list no accidents; the flag is unreliable, the rows are what count"
          % ", ".join(str(s["submission"]) for s in flag))
    p("  " + r["accident_note"])


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--refresh", action="store_true", help="bypass the cache")
    # Repeat the globals on each subcommand so they work on either side of it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    sub.add_parser("health", help="sources up, data vintage")
    s = sub.add_parser("search", help="facilities by current or previous name")
    s.add_argument("name")
    s.add_argument("--state", default="LA", help="two-letter code(s), comma-separated")
    s.add_argument("--city")
    s.add_argument("--include-dereg", action="store_true")
    s = sub.add_parser("near", help="facilities within a radius of a point")
    s.add_argument("lat", type=float)
    s.add_argument("lon", type=float)
    s.add_argument("--radius-km", type=float, required=True)
    s.add_argument("--state", default="LA", help="state file(s) to scan, comma-separated")
    s.add_argument("--include-dereg", action="store_true")
    s = sub.add_parser("facility", help="full RMP profile of one facility")
    s.add_argument("id", help="EPAFacilityID (12 digits)")
    s.add_argument("--submission", type=int, help="a past submission instead of the latest")
    s = sub.add_parser("accidents", help="all accidents across submissions")
    s.add_argument("id")
    s.add_argument("--csv")
    s = sub.add_parser("summary", help="executive summary text")
    s.add_argument("id", help="EPAFacilityID or submission ID")
    s = sub.add_parser("crosswalk", help="FRS registry and program IDs")
    s.add_argument("id")
    sub.add_parser("oca", help="how to reach worst-case scenario data")

    args = ap.parse_args()
    fn = {"health": cmd_health, "search": cmd_search, "near": cmd_near, "facility": cmd_facility,
          "accidents": cmd_accidents, "summary": cmd_summary, "crosswalk": cmd_crosswalk, "oca": cmd_oca}[args.cmd]
    try:
        res = fn(args)
    except SourceDown as e:
        die("source unavailable: %s" % e, 5)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        show(args.cmd, res)


if __name__ == "__main__":
    main()
