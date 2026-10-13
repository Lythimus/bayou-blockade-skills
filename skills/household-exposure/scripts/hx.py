"""Household air-exposure assessment CLI.

  hx.py prepare --out DIR --at LAT,LON --member 'A:1998-03-01..2010-06-30,2015..' [--birth A=1990]
                [--label TEXT] [--address TEXT] [--radius-km 50]
                [--proposed DIR --proposed-name NAME --op-start YEAR --op-years N]
                [--stay operating_end | --stay A=2045]
                [--facilities] [--yes]
  hx.py prepare --out DIR [--facilities] [--yes]      re-validate an edited assessment.json

  hx.py screen  --out DIR [--years 1998-2014] [--no-airtox | --block GEOID] [--rsei-dir DIR] [--yes]

  hx.py model   --check-build
  hx.py model   --out DIR [--proposed NAME] [--home-xy X,Y | --utm-zone N --datum NAD83]
                [--applicant-plot CAS=FILE ...] [--applicant-inp FILE] [--applicant-out FILE]
                [--sfc FILE --pfl FILE] [--profbase-m M] [--home-elev M]

  hx.py report  --out DIR [--public] [--formats print,social]

`prepare` writes DIR/assessment.json and prints what later steps would download. With
--facilities it also lists TRI facilities within the radius and the years each reported,
which needs the network. DIR holds a home location, so it must sit outside the plugin.

`screen` is the historical tier: EPA's RSEI modeled concentration at the home's grid cell
for each facility, chemical and year lived there, turned into cancer risk and hazard
quotients, plus AirToxScreen's 2020 figure for the home's census block as separate context.
It writes DIR/screening.json and DIR/screen.csv. Each RSEI year is a 1-22 GB stream.

`model` is the dispersion tier for a proposed facility: the concentration at the home per
gram per second from each emission point, from the applicant's own AERMOD files where they
exist, scaled by each chemical's permitted rate. It writes DIR/model.json, model.csv and
model-gaps.md. Where an input is missing it gives no number and lists what to request.
references/aermod-inputs.md describes the files it reads.

`report` turns whatever `screen` and `model` wrote into DIR/REPORT.md, exposure.csv,
results.json, manifest.json and charts/. With --public it writes the same set to DIR/public/
with the address, coordinates, grid cell, census block and distances left out.

Exit status 3 means a download over 100 MB is waiting on the user's confirmation (--yes).
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "skills", "tri-release-report", "scripts"))
import proposed_emissions as pe  # noqa: E402
import tri_fetch as tf  # noqa: E402

sys.path.insert(0, HERE)
import aermod_io  # noqa: E402
import airtox  # noqa: E402
import downloads  # noqa: E402
import exposure  # noqa: E402
import rsei  # noqa: E402
import toxvalues  # noqa: E402

SCHEMA_VERSION = 1
KM_PER_MILE = 1.609344
# AERMOD is a near-field model and RSEI stops at 49 km; beyond this neither tier applies.
MAX_RADIUS_KM = 50.0
MEMBER_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
# Envelope used only to warn; the meteorology and file choices assume a Louisiana home.
LA_BBOX = tf.STATE_BBOX["LA"]
# projected_end value meaning "stays for as long as the proposed facility operates".
STAY_FOR_HORIZON = "operating_end"


def inside_plugin(path):
    """True when path resolves to somewhere under the plugin root, through symlinks too."""
    root = os.path.realpath(PLUGIN_ROOT)
    target = os.path.realpath(path)
    return os.path.commonpath([root, target]) == root


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "home"


# ------------------------------------------------------------ assessment.json

def parse_member(spec):
    """'A:1998-03-01..2010-06-30,2015..' -> member dict. A blank end means still there."""
    if ":" not in spec:
        raise ValueError(f"--member needs ID:START..END, got {spec!r}")
    mid, rest = spec.split(":", 1)
    periods = []
    for part in rest.split(","):
        if ".." not in part:
            raise ValueError(f"residence period needs START..END (END may be blank), got {part!r}")
        start, end = (x.strip() for x in part.split("..", 1))
        periods.append({"start": start, "end": end or None})
    return {"id": mid.strip(), "birth_year": None, "projected_end": None, "residence": periods}


def validate(a, today=None):
    """Returns (errors, warnings). Errors block every later step."""
    today = today or dt.date.today()
    err, warn = [], []
    if a.get("schema_version") != SCHEMA_VERSION:
        err.append(f"schema_version must be {SCHEMA_VERSION}")
    home = a.get("home") or {}
    try:
        lat, lon = float(home["lat"]), float(home["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            err.append("home lat/lon out of range")
        else:
            s, n, w, e = LA_BBOX
            if not (s <= lat <= n and w <= lon <= e):
                warn.append("home is outside Louisiana; data-source choices assume Louisiana")
    except (KeyError, TypeError, ValueError):
        err.append("home.lat and home.lon are required numbers")
    try:
        radius = float(a.get("radius_km"))
        if not 0 < radius <= MAX_RADIUS_KM:
            err.append(f"radius_km must be above 0 and at most {MAX_RADIUS_KM:g}")
    except (TypeError, ValueError):
        err.append("radius_km is required")
    try:
        as_of = exposure.parse_date(a.get("as_of"))
    except (TypeError, ValueError):
        err.append("as_of must be an ISO date")
        as_of = today
    members = a.get("members") or []
    if not members:
        err.append("at least one member is required")
    seen = set()
    for m in members:
        mid = str(m.get("id", ""))
        if not MEMBER_ID.match(mid):
            err.append(f"member id {mid!r}: use a short pseudonym (letters, digits, - or _)")
        if mid in seen:
            err.append(f"member id {mid!r} is repeated")
        seen.add(mid)
        by = m.get("birth_year")
        if by is not None and not (isinstance(by, int) and 1900 <= by <= today.year):
            err.append(f"member {mid}: birth_year must be a year or null")
        if not m.get("residence"):
            err.append(f"member {mid}: at least one residence period is required")
            continue
        try:
            ivals = exposure.intervals(m["residence"], as_of)
        except (KeyError, TypeError, ValueError) as e:
            err.append(f"member {mid}: {e}")
            continue
        if isinstance(by, int) and not exposure.clip(ivals, lo=exposure.birth_date(by)):
            err.append(f"member {mid}: every residence period ends before birth year {by}")
        elif by is None:
            warn.append(f"member {mid}: no birth year; early-life cancer factors will not be applied")
        stay = m.get("projected_end")
        still_there = any(not p.get("end") for p in m["residence"])
        if stay not in (None, STAY_FOR_HORIZON):
            try:
                if exposure.parse_date(stay, end=True) < as_of:
                    err.append(f"member {mid}: projected_end is before as_of")
            except (TypeError, ValueError):
                err.append(f"member {mid}: projected_end must be a date, a year or {STAY_FOR_HORIZON!r}")
        # Without it an open residence would stop today, and a plant that starts later would
        # show zero exposure for everyone, which reads as a clean result.
        if still_there and a.get("proposed") and stay is None:
            err.append(f"member {mid}: projected_end is required when a proposed facility is "
                       f"assessed (a date, a year or {STAY_FOR_HORIZON!r})")
    for p in a.get("proposed") or []:
        name = p.get("name") or "proposed facility"
        start, years = p.get("operating_start"), p.get("operating_years")
        # A future exposure has no defined length without these, so there is no default.
        if not isinstance(start, int) or not isinstance(years, (int, float)) or years <= 0:
            err.append(f"{name}: operating_start (year) and operating_years (> 0) are required")
        if not p.get("dir") or not os.path.isdir(p["dir"]):
            err.append(f"{name}: dir {p.get('dir')!r} is not a directory")
    return err, warn


def proposed_inputs(p):
    """Which of the proposed facility's input files exist. Absent ones are gaps, not errors."""
    found = {}
    for key, cands in (("proposed_emissions", ("verification/proposed-emissions.csv", "proposed-emissions.csv")),
                       ("source_inventory", ("verification/source-inventory.csv", "source-inventory.csv")),
                       ("source_emissions", ("verification/source-emissions.csv", "source-emissions.csv"))):
        found[key] = next((os.path.join(p["dir"], c) for c in cands
                           if os.path.exists(os.path.join(p["dir"], c))), None)
    return found


def residence_span(a):
    """(first year, last year) over all members, closing open periods at as_of."""
    ivals = [iv for m in a["members"] for iv in exposure.intervals(m["residence"], a["as_of"])]
    return min(s for s, _ in ivals).year, max(e - dt.timedelta(days=1) for _, e in ivals).year


def operating_window(p):
    """(first day, last day) of a proposed facility's operating horizon."""
    start = dt.date(p["operating_start"], 1, 1)
    whole, part = int(p["operating_years"]), p["operating_years"] % 1
    end = start.replace(year=start.year + whole) + dt.timedelta(days=round(part * 365.25) - 1)
    return start, end


def open_end(a, member, proposed=None):
    """Last day an open-ended residence counts for.

    History stops at as_of: nothing after today has happened. A proposed-facility scenario
    runs to the member's projected_end, which is an assumption and is reported as one.
    """
    if proposed is None:
        return exposure.parse_date(a["as_of"])
    stay = member.get("projected_end")
    if stay == STAY_FOR_HORIZON:
        return operating_window(proposed)[1]
    return exposure.parse_date(stay, end=True)


def load_assessment(out):
    path = os.path.join(out, "assessment.json")
    if not os.path.exists(path):
        sys.exit(f"{path} not found; run `hx.py prepare` first")
    with open(path, encoding="utf-8") as f:
        a = json.load(f)
    err, _ = validate(a)
    if err:
        sys.exit("assessment.json is not usable:\n  " + "\n  ".join(err))
    return a


def write_assessment(out, a):
    # The file names a home location; keep it readable by its owner only.
    os.makedirs(out, mode=0o700, exist_ok=True)
    path = os.path.join(out, "assessment.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(a, f, indent=2)
        f.write("\n")
    return path


# ------------------------------------------------------------ facility discovery

def year_ranges(years):
    """[1990, 1991, 1992, 1995] -> '1990-1992, 1995'."""
    out, run = [], []
    for y in sorted(set(years)):
        if run and y == run[-1] + 1:
            run.append(y)
        else:
            if run:
                out.append(run)
            run = [y]
    if run:
        out.append(run)
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in out)


def collapse(facs, aliases=None):
    """Merge records that are one plant under several TRI IDs.

    facs     {trifid: {"frs_id", "name", "lat", "lon", "years": set, "last_year": int}}
    aliases  {trifid: canonical trifid} from assessment.json, for pairs EPA has not linked.
    Records sharing an FRS registry ID are merged too. The ID with the most recent report
    becomes the canonical one; a plant counted twice would double its modeled concentration.
    """
    aliases = aliases or {}

    def key(fid):
        fid = aliases.get(fid, fid)
        frs = facs[fid].get("frs_id") if fid in facs else None
        return "frs:" + frs if frs else fid

    groups = {}
    for fid, f in facs.items():
        groups.setdefault(key(fid), []).append((fid, f))
    out = {}
    for members in groups.values():
        members.sort(key=lambda m: (m[1]["last_year"], m[0]))
        fid, newest = members[-1]
        merged = dict(newest)
        merged["years"] = set().union(*(m[1]["years"] for m in members))
        merged["also"] = sorted(m[0] for m in members[:-1])
        out[fid] = merged
    return out


def discover(a, out, yes):
    """TRI facilities within the radius, with the years each filed. Returns rows or None."""
    lat, lon = a["home"]["lat"], a["home"]["lon"]
    radius_mi = a["radius_km"] / KM_PER_MILE
    states = tf.states_for(lat, lon, radius_mi, [])
    first, last = residence_span(a)
    last = min(last, dt.date.today().year - 1)
    raw = os.path.join(out, "raw", "tri")
    os.makedirs(raw, exist_ok=True)
    have = {(y, st) for y in range(first, last + 1) for st in states
            if os.path.exists(os.path.join(raw, f"{y}_{st}.csv"))}
    if not downloads.gate(downloads.tri_plan(first, last, states, have), out, yes, "Facility discovery"):
        return None
    facs, missing = {}, []
    for year in range(max(first, downloads.TRI_FIRST), last + 1):
        for st in states:
            try:
                path = tf.fetch_state_year(raw, year, st)
            except (urllib.error.URLError, OSError) as e:
                missing.append(f"{year} {st} ({e})")
                continue
            if not path:
                missing.append(f"{year} {st} (no file published)")
                continue
            for r in tf.load_rows(path):
                try:
                    flat, flon = float(r["12"]), float(r["13"])
                except ValueError:
                    continue
                km = tf.haversine_miles(lat, lon, flat, flon) * KM_PER_MILE
                if km > a["radius_km"]:
                    continue
                f = facs.setdefault(r["2"], {"frs_id": r["3"].strip(), "years": set(), "last_year": 0})
                f["years"].add(year)
                if year >= f["last_year"]:
                    f.update(name=r["4"], lat=flat, lon=flon, distance_km=round(km, 2), last_year=year)
    facs = collapse(facs, a.get("facility_aliases"))
    span = set(range(max(first, downloads.TRI_FIRST), last + 1))
    rows = []
    for fid, f in sorted(facs.items(), key=lambda kv: kv[1]["distance_km"]):
        rows.append({"trifid": fid, "also_reported_as": ";".join(f["also"]), "frs_id": f["frs_id"],
                     "name": f["name"], "lat": f["lat"], "lon": f["lon"],
                     "distance_km": f["distance_km"],
                     "years_reported": year_ranges(f["years"] & span),
                     "residence_years_without_report": year_ranges(span - f["years"])})
    with open(os.path.join(out, "facilities.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["trifid"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nTRI facilities within {a['radius_km']:g} km, {min(span)}-{max(span)}: {len(rows)}"
          f"  -> {os.path.join(out, 'facilities.csv')}")
    for r in rows[:15]:
        print(f"  {r['distance_km']:6.1f} km  {r['name'][:44]:44}  {r['years_reported']}")
    if len(rows) > 15:
        print(f"  ... {len(rows) - 15} more in facilities.csv")
    if first < downloads.TRI_FIRST:
        print(f"  {first}-{downloads.TRI_FIRST - 1}: before TRI reporting began; no facility data exists")
    if missing:
        print("  not retrieved, so these years are unknown rather than empty:\n    " + "\n    ".join(missing))
    # A year with no TRI form is not a year with no emissions: the plant may have been
    # below the reporting threshold, exempt, or not yet covered by the program.
    print("  A year without a report is unknown, not zero.")
    return rows


# ------------------------------------------------------------ prepare

def cmd_prepare(args):
    out = args.out or f"./household-exposure-{slug(args.label or 'home')}"
    if inside_plugin(out):
        sys.exit(f"{out} is inside the plugin directory. Household data must not be stored "
                 "there; choose a path outside it.")
    path = os.path.join(out, "assessment.json")
    today = dt.date.today()
    if args.at:
        if os.path.exists(path) and not args.overwrite:
            sys.exit(f"{path} exists. Edit it and rerun without --at, or pass --overwrite.")
        try:
            lat, lon = (float(x) for x in args.at.split(","))
            members = [parse_member(m) for m in args.member or []]
            births = dict(b.split("=", 1) for b in args.birth or [])
            stays = dict(x.split("=", 1) if "=" in x else ("*", x) for x in args.stay or [])
            for m in members:
                if m["id"] in births:
                    m["birth_year"] = int(births.pop(m["id"]))
                m["projected_end"] = stays.get(m["id"], stays.get("*"))
        except ValueError as e:
            sys.exit(f"bad argument: {e}")
        if births:
            sys.exit(f"--birth names unknown member(s): {', '.join(births)}")
        proposed = []
        if args.proposed:
            proposed.append({"name": args.proposed_name or os.path.basename(os.path.abspath(args.proposed)),
                             "dir": os.path.abspath(args.proposed),
                             "operating_start": args.op_start, "operating_years": args.op_years})
        a = {"schema_version": SCHEMA_VERSION, "label": args.label or "home",
             "created": today.isoformat(), "as_of": today.isoformat(),
             "home": {"lat": lat, "lon": lon, "address": args.address},
             "radius_km": args.radius_km, "members": members, "proposed": proposed,
             "facility_aliases": {}}
    elif os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
    else:
        sys.exit("--at LAT,LON is required to create a new assessment")
    err, warn = validate(a, today)
    if err:
        sys.exit("Assessment not written:\n  " + "\n  ".join(err))
    if args.at:
        write_assessment(out, a)
    print(f"Assessment: {path}")
    for w in warn:
        print(f"  note: {w}")
    first, last = residence_span(a)
    print(f"Residence years covered: {first}-{last}")
    for p in a.get("proposed") or []:
        w0, w1 = operating_window(p)
        found = proposed_inputs(p)
        print(f"Proposed: {p['name']}, operating {w0} to {w1}")
        for key, label in (("proposed_emissions", "proposed-emissions.csv"),
                           ("source_inventory", "source-inventory.csv"),
                           ("source_emissions", "source-emissions.csv")):
            print(f"  {label}: {found[key] or 'not found (used by `model`)'}")
        for m in a["members"]:
            if any(not r.get("end") for r in m["residence"]):
                print(f"  assumption: member {m['id']} stays through {open_end(a, m, p)}")
    plan = downloads.rsei_plan(first, min(last, today.year))
    plan += downloads.airtox_plan()
    print("\nWhat `screen` would download for these years (approximate; nothing fetched now):")
    print(downloads.describe(plan, out))
    versions = list(dict.fromkeys(i["version"] for i in plan if i.get("version")))
    if len(versions) > 1:
        print(f"  The years span RSEI model versions {', '.join(versions)}; each is reported as "
              "its own series and they are not joined into one trend.")
    if args.facilities and discover(a, out, args.yes) is None:
        # Distinct status so a caller can tell "needs the user's go-ahead" from a failure.
        sys.exit(3)


# ------------------------------------------------------------ screen

def parse_years(spec):
    """'2010-2014' or '2012' -> (first, last)."""
    a, _, b = spec.partition("-")
    first, last = int(a), int(b or a)
    if last < first:
        raise ValueError(f"--years {spec!r} runs backwards")
    return first, last


def progress_printer(label):
    """Prints at each tenth of a transfer; a 22 GB stream is silent for too long otherwise."""
    state = {"tenth": -1}

    def show(done, total):
        if not total:
            return
        tenth = int(10 * done / total)
        if tenth > state["tenth"]:
            state["tenth"] = tenth
            print(f"  {label}: {min(100, tenth * 10)}% of {downloads.fmt_size(total)}", flush=True)
    return show


def tri_air_reports(raw, years, states, tox, catmap):
    """{year: {(TRI facility id, chemical key): pounds to air}} from TRI files already cached.

    Only full Form R filings count. A Form A certifies low releases without stating them, so
    it cannot show a zero. A year missing any state's file is left out entirely: half a
    year's filings would make every absent plant look like a non-reporter.
    """
    out = {}
    for year in years:
        paths = [os.path.join(raw, f"{year}_{st}.csv") for st in states]
        if not all(os.path.exists(p) for p in paths):
            continue
        filed = out.setdefault(year, {})
        for path in paths:
            for r in tf.load_rows(path):
                if r["49"].strip().upper() == "A":
                    continue
                key = toxvalues.resolve(tox, catmap, r["39"])[1]
                try:
                    air = float(r["51"] or 0) + float(r["52"] or 0)
                except ValueError:
                    continue
                filed[(r["2"], key)] = filed.get((r["2"], key), 0.0) + air
    return out


def source_identity(kind, number, tables, home):
    """(stable id, description) for a microdata source. Facility numbers are internal to one
    RSEI version, so the TRI facility ID is the identity that survives across versions."""
    rec = tables["offsite" if kind == "offsite" else "facility"].get(number) or {}
    if kind == "facility" and rec.get("trifid"):
        sid = rec["trifid"]
    else:
        sid = f"{kind}:{rec.get('name') or number}"
    d = None
    if rec.get("lat") is not None and rec.get("lon") is not None:
        d = round(tf.haversine_miles(home[0], home[1], rec["lat"], rec["lon"]) * KM_PER_MILE, 2)
    return sid, {"kind": "off-site incinerator or treatment works receiving TRI waste"
                 if kind == "offsite" else "TRI facility",
                 "name": rec.get("name") or f"RSEI {kind} {number}", "city": rec.get("city"),
                 "state": rec.get("state"), "lat": rec.get("lat"), "lon": rec.get("lon"),
                 "frs_id": rec.get("frs_id"), "distance_km": d}


def build_series(by_year, tables_by_version, versions, home, tox, catmap, filed):
    """Turn each scanned year's rows into per-source, per-chemical annual series.

    by_year  {year: rows from rsei.fetch_year}; a year absent from it was not read.
    filed    tri_air_reports() result.
    Returns (pairs, sources, chemicals):
      pairs      {(source id, chemical key): {year: {"conc", "lo", "hi", "status"}}}
      sources    {source id: description}
      chemicals  {chemical key: {"record", "basis", "note", "rsei_names"}}

    A year RSEI was read for, in which a source that appears in other years has no row, is:
      zero_reported        the facility filed a TRI form for the chemical stating no air
                           release: a known zero;
      reported_not_modeled it filed an air release that RSEI did not model: unknown;
      no_report            it filed nothing for the chemical: unknown, since a plant below
                           the reporting threshold still emits.
    """
    xy = rsei.cell(*home)
    pairs, sources, chemicals = {}, {}, {}
    for year, rows in sorted(by_year.items()):
        tables = tables_by_version[versions[year]]
        for (kind, number, chem), v in rsei.annual(rows, xy).items():
            sid, desc = source_identity(kind, number, tables, home)
            sources.setdefault(sid, desc)
            c = tables["chemical"].get(chem) or {"id": f"rsei-chemical-{chem}", "name": f"RSEI chemical {chem}"}
            rec, key, basis, note = toxvalues.resolve(tox, catmap, c["id"])
            info = chemicals.setdefault(key, {"record": rec, "basis": basis, "note": note, "rsei_names": []})
            if c["name"] not in info["rsei_names"]:
                info["rsei_names"].append(c["name"])
            cur = pairs.setdefault((sid, key), {}).get(year)
            val = {"conc": v["conc"], "lo": v["lo"], "hi": v["hi"], "status": "modeled"}
            if cur and cur["conc"] is not None:
                # Two RSEI chemicals on one Table 1 row (lead and lead compounds) add up.
                val = {"conc": cur["conc"] + val["conc"], "lo": cur["lo"] + val["lo"],
                       "hi": cur["hi"] + val["hi"], "status": "modeled"}
            pairs[(sid, key)][year] = val
    for (sid, key), series in pairs.items():
        for year in by_year:
            if year in series:
                continue
            air = filed.get(year, {}).get((sid, key))
            if air is None:
                status, conc = "no_report", None
            elif air == 0:
                status, conc = "zero_reported", 0.0
            else:
                status, conc = "reported_not_modeled", None
            series[year] = {"conc": conc, "lo": conc, "hi": conc, "status": status}
    return pairs, sources, chemicals


def member_results(a, member, pairs, chemicals, organs, proposed=None):
    """Per-chemical exposure, cancer risk and hazard quotient for one member, plus totals.

    With `proposed`, the series are a proposed facility's constant modeled concentrations:
    they count only inside its operating window and the residence runs to projected_end.
    """
    end, rows = open_end(a, member, proposed), []
    window = operating_window(proposed) if proposed else None
    for key, info in sorted(chemicals.items()):
        per_source = {sid: {y: v["conc"] for y, v in s.items()} for (sid, k), s in pairs.items() if k == key}
        series, partial = exposure.combine(list(per_source.values()))
        e = exposure.exposure(series, member["residence"], end, member.get("birth_year"), window)
        # A chemical with no figure in any year this member lived there says nothing about
        # them; listing it would bury the ones that do.
        if not e["known_years"]:
            continue
        rec = info["record"] or {}
        risk = exposure.cancer_risk(e, rec.get("ure_per_ug_m3"), rec.get("mutagenic", False),
                                    rec.get("adaf_share", 1.0))
        shares = {sid: exposure.exposure(s, member["residence"], end, member.get("birth_year"), window)["integral"]
                  for sid, s in per_source.items()}
        home_years = {r["year"] for r in e["by_year"]}
        rows.append({
            "cas": key, "chemical": rec.get("chemical") or info["rsei_names"][0],
            "reported_as": info["rsei_names"], "basis": info["basis"],
            "note": "; ".join(n for n in (info["note"], rec.get("note"), risk and risk["note"]) if n) or None,
            "residence_years": e["residence_years"], "evidence_fraction": e["evidence_fraction"],
            "unknown_years": e["unknown"],
            # A floor for that year: at least one source that reports this chemical in
            # other years has no figure.
            "partial_years": sorted(set(partial) & home_years),
            "integral_ug_m3_yr": e["integral"], "exposed_average_ug_m3": e["exposed_average"],
            "max_annual_ug_m3": e["max_annual"],
            "risk": risk["risk"] if risk else None,
            "unadjusted_risk": risk["unadjusted_risk"] if risk else None,
            "age_adjusted": bool(risk and risk["age_adjusted"]),
            "hq": exposure.hazard_quotient(e["exposed_average"], rec.get("rfc_ug_m3")),
            "hq_max_year": exposure.hazard_quotient(e["max_annual"], rec.get("rfc_ug_m3")),
            "by_source_integral": dict(sorted(((k, v) for k, v in shares.items() if v), key=lambda kv: -kv[1])),
        })
    return {"rows": rows, "totals": exposure.totals(rows, organs)}


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def cmd_screen(args):
    out = args.out
    if inside_plugin(out):
        sys.exit(f"{out} is inside the plugin directory; household data must not be stored there.")
    a = load_assessment(out)
    home = (a["home"]["lat"], a["home"]["lon"])
    try:
        xy = rsei.cell(*home)
    except ValueError as e:
        sys.exit(f"screen: {e}")
    first, last = residence_span(a)
    if args.years:
        try:
            lo, hi = parse_years(args.years)
        except ValueError as e:
            sys.exit(f"bad argument: {e}")
        first, last = max(first, lo), min(last, hi)
    plan = downloads.rsei_plan(first, last) if first <= last else []
    covered = [i for i in plan if i.get("url")]
    raw = os.path.join(out, "raw", "rsei")
    todo = [i for i in covered if not rsei.have_year(i, xy, raw, args.rsei_dir)]
    fetch = [i for i in todo if not (args.rsei_dir and os.path.exists(
        os.path.join(args.rsei_dir, os.path.basename(i["url"]))))]
    versions = {i["year"]: i["version"] for i in covered}
    for v in sorted(set(versions.values())):
        if not rsei.tables_cached(v):
            fetch.append({"what": f"RSEI {v} lookup tables", "bytes": downloads.RSEI_TABLE_BYTES,
                          "stored": True, "url": None, "note": "cached under ~/.cache/bayou/rsei"})
    atx_path = os.path.join(out, "raw", "airtox", "block.json")
    want_airtox = not args.no_airtox
    if want_airtox and not os.path.exists(atx_path):
        fetch += downloads.airtox_plan()
    if not downloads.gate(fetch, out, args.yes, "Screening"):
        print("To transfer less: --years FIRST-LAST limits the RSEI years, --no-airtox skips "
              "AirToxScreen. Years left out stay unknown.")
        sys.exit(3)

    tox, catmap, organs = toxvalues.load(), toxvalues.load_category_map(), toxvalues.load_organs()
    gaps, tables = [], {}
    for v in sorted(set(versions.values())):
        try:
            rsei.fetch_tables(v)
            tables[v] = rsei.load_tables(v)
        except (urllib.error.URLError, OSError, KeyError, zipfile.BadZipFile) as e:
            gaps.append(f"RSEI {v} lookup tables not retrieved ({e}); its years are unknown")
    by_year = {}
    for i in covered:
        if i["version"] not in tables:
            continue
        try:
            by_year[i["year"]] = rsei.fetch_year(i, xy, raw, args.rsei_dir,
                                                 progress_printer(f"RSEI {i['year']}"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            gaps.append(f"RSEI {i['year']} not retrieved ({e}); the year is unknown")
    states = tf.states_for(home[0], home[1], a["radius_km"] / KM_PER_MILE, [])
    filed = tri_air_reports(os.path.join(out, "raw", "tri"), sorted(by_year), states, tox, catmap)
    pairs, sources, chemicals = build_series(by_year, tables, versions, home, tox, catmap, filed)

    atx = {"skipped": "--no-airtox"}
    if want_airtox:
        atx = screen_airtox(args, home, atx_path)

    r0, r1 = residence_span(a)
    span = list(range(r0, r1 + 1))
    result = {
        "schema_version": SCHEMA_VERSION, "generated": dt.date.today().isoformat(),
        "tier": "screening (RSEI Geographic Microdata)",
        "grid_cell": {"grid": rsei.GRID_CONUS, "x": xy[0], "y": xy[1], "size_m": rsei.CELL_M},
        "years": {"residence": [span[0], span[-1]], "read": sorted(by_year),
                  "outside_rsei_coverage": [y for y in span if not (downloads.RSEI_FIRST <= y <= downloads.RSEI_LAST)],
                  "not_requested": [y for y in span if downloads.RSEI_FIRST <= y <= downloads.RSEI_LAST
                                    and not (first <= y <= last)],
                  "tri_filings_checked": sorted(filed)},
        "model_versions": {v: year_ranges(y for y, vv in versions.items() if vv == v and y in by_year)
                           for v in dict.fromkeys(versions.values())},
        "gaps": gaps,
        "sources": sources,
        "chemicals": {k: {"chemical": (c["record"] or {}).get("chemical") or c["rsei_names"][0],
                          "reported_as": c["rsei_names"], "basis": c["basis"], "note": c["note"],
                          "ure_per_ug_m3": (c["record"] or {}).get("ure_per_ug_m3"),
                          "rfc_ug_m3": (c["record"] or {}).get("rfc_ug_m3"),
                          "mutagenic": (c["record"] or {}).get("mutagenic", False),
                          "target_organs": organs.get(k)} for k, c in chemicals.items()},
        "members": {m["id"]: member_results(a, m, pairs, chemicals, organs) for m in a["members"]},
        "airtoxscreen": atx,
        "limitations": [rsei.LIMITATION,
                        "Only releases reported to TRI are included. Facilities below the reporting "
                        "threshold, vehicles, and every non-TRI source are absent, so each figure is "
                        "a floor for industrial sources, not a total for the air at the home.",
                        "Years come from more than one RSEI model version, which EPA says cannot be "
                        "combined into a trend. Sums over a residence are reported; year-to-year "
                        "changes across a version boundary are not evidence of a real change."
                        if len({versions[y] for y in by_year}) > 1 else None],
        "provenance": {"toxicity": toxvalues.provenance(),
                       "rsei": {str(i["year"]): {"version": i["version"], "url": i["url"]}
                                for i in covered if i["year"] in by_year}},
    }
    result["limitations"] = [x for x in result["limitations"] if x]
    write_private(os.path.join(out, "screening.json"), json.dumps(result, indent=2) + "\n")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["chemical", "cas_or_id", "source_id", "source", "distance_km", "year", "rsei_version",
                "conc_ug_m3", "conc_min_3x3", "conc_max_3x3", "status"])
    for (sid, key), series in sorted(pairs.items(), key=lambda kv: (result["chemicals"][kv[0][1]]["chemical"], kv[0][0])):
        for year, v in sorted(series.items()):
            w.writerow([result["chemicals"][key]["chemical"], key, sid, sources[sid]["name"],
                        sources[sid]["distance_km"], year, versions[year],
                        *("" if v[k] is None else f"{v[k]:.6g}" for k in ("conc", "lo", "hi")), v["status"]])
    write_private(os.path.join(out, "screen.csv"), buf.getvalue())
    print_screen(result, out)


def screen_airtox(args, home, path):
    """AirToxScreen record for the home's block, or a dict saying why there is none."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    try:
        geoid = args.block or airtox.block_geoid(*home)
        if not geoid:
            return {"skipped": "the Census geocoder returned no block for the home"}
        if geoid[:2] not in airtox.REGION_6A:
            return {"skipped": f"block {geoid} is outside the states this skill reads AirToxScreen for"}
        rec = airtox.read_block(geoid, progress=progress_printer("AirToxScreen"))
    except (urllib.error.URLError, OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        return {"skipped": f"not retrieved ({e})"}
    if rec is None:
        return {"skipped": f"block {geoid} is not listed in AirToxScreen 2020 (unpopulated blocks are omitted)"}
    rec["block_source"] = "given with --block" if args.block else "Census Bureau geocoder (home coordinates were sent to it)"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_private(path, json.dumps(rec, indent=2) + "\n")
    return rec


def sci(v):
    return "none" if v is None else f"{v:.2g}"


def print_screen(r, out):
    y = r["years"]
    print(f"\nScreening written: {os.path.join(out, 'screening.json')}, screen.csv")
    print(f"RSEI grid cell {r['grid_cell']['x']},{r['grid_cell']['y']}; years read: "
          f"{year_ranges(y['read']) or 'none'}")
    for v, yrs in r["model_versions"].items():
        if yrs:
            print(f"  {v}: {yrs}")
    for label, key in (("after RSEI's last year or before its first (unknown)", "outside_rsei_coverage"),
                       ("left out with --years (unknown)", "not_requested")):
        if y[key]:
            print(f"  {label}: {year_ranges(y[key])}")
    for g in r["gaps"]:
        print(f"  gap: {g}")
    if set(y["read"]) - set(y["tri_filings_checked"]):
        print("  TRI filings not on hand for "
              f"{year_ranges(set(y['read']) - set(y['tri_filings_checked']))}: a source with no figure "
              "in those years is unknown, never zero. `prepare --facilities` fetches them.")
    print(f"Sources with a modeled concentration at the home: {len(r['sources'])}; "
          f"chemicals: {len(r['chemicals'])}")
    for mid, m in r["members"].items():
        t = m["totals"]
        print(f"\nMember {mid}")
        if not m["rows"]:
            print("  no RSEI figure for any year lived at the home")
            continue
        ry = m["rows"][0]["residence_years"]
        print(f"  years at home: {ry:.2f}")
        known = max((x["residence_years"] * x["evidence_fraction"] for x in m["rows"]), default=0.0)
        print(f"  cancer risk from reported industrial air releases, summed over "
              f"{t['cancer_chemicals']} chemicals: {sci(t['cancer_risk'])}"
              + (f" (about {t['cancer_risk'] * 1e6:.3g} in a million)" if t["cancer_risk"] else ""))
        if known < ry - 1e-9:
            # Unknown years add nothing to the sum, so it understates a longer residence.
            print(f"  that is a floor: it covers at most {known:.2f} of the {ry:.2f} years; "
                  "the rest have no figure")
        for row in sorted((x for x in m["rows"] if x["risk"]), key=lambda x: -x["risk"])[:6]:
            top = next(iter(row["by_source_integral"]), None)
            print(f"    {row['chemical'][:34]:34} {sci(row['risk'])}  evidence {row['evidence_fraction']:.0%}"
                  + (f"  mostly {r['sources'][top]['name'][:30]}" if top else ""))
        if t["hazard_index"]:
            hi = sorted(t["hazard_index"].items(), key=lambda kv: -kv[1])[:4]
            print("  hazard index by target organ: "
                  + ", ".join(f"{toxvalues.ORGAN_NAMES.get(o, o)} {sci(v)}" for o, v in hi))
        print(f"  no cancer value: {len(t['unquantified_cancer'])} chemicals; "
              f"no noncancer value: {len(t['unquantified_noncancer'])}")
    atx = r["airtoxscreen"]
    if atx.get("skipped"):
        print(f"\nAirToxScreen 2020: skipped: {atx['skipped']}")
    else:
        print(f"\nAirToxScreen 2020, census block {atx['block']} (all source types, separate from the "
              f"figures above): {atx['total_per_million']:.3g} in a million")
        for k, v in list(atx["by_source_per_million"].items())[:4]:
            print(f"    {k[:44]:44} {v:.3g}")
    print("\nA year with no figure is unknown, not zero. These are modeled outdoor concentrations, "
          "not measurements and not doses.")


# ------------------------------------------------------------ dispersion tier

G_PER_LB = 453.59237
SECONDS_PER_YEAR = 8760 * 3600.0
PERMITTED_BASIS = {"pte", "allowable", "permitted", "potential", "potential to emit"}
EXPECTED_BASIS = {"expected", "actual", "projected"}
LENGTH_M = {"m": 1.0, "ft": 0.3048, "in": 0.0254}
VELOCITY_M_S = {"m/s": 1.0, "ft/s": 0.3048, "ft/sec": 0.3048, "ft/min": 0.3048 / 60, "fpm": 0.3048 / 60}
INVENTORY_COLUMNS = ["source_id", "description", "lat", "lon", "utm_zone", "utm_e_m", "utm_n_m", "datum",
                     "height", "height_unit", "diameter", "diameter_unit", "temp", "temp_unit",
                     "velocity", "velocity_unit", "source_doc", "page", "ocr_verified"]
EMISSION_COLUMNS = ["source_id", "chemical", "cas", "amount", "unit", "hours", "basis", "assumption",
                    "status", "source_doc", "page", "ocr_verified"]
# A filed receptor this close to the home stands in for it. Applicants space receptors 25 to
# 100 m apart near the fence line and 250 m to 1 km apart farther out, where the nearest one
# can sit in a different part of the plume.
MAX_RECEPTOR_M = 100.0
# Terrain heights change slowly here; a filed receptor within this distance lends its own.
BORROW_TERRAIN_M = 500.0
MODEL_LIMITATIONS = [
    "The concentration is a long-term average outdoors at the home from the proposed facility "
    "alone. Other facilities, traffic and background air are not in it.",
    "Rates are annual totals spread evenly over the year. Any operating schedule in the "
    "applicant's model (EMISFACT) is left out, so emissions that happen only at certain hours "
    "are averaged over all weather.",
    "Not covered: short-term peaks from upsets, startups and flaring; chemicals formed in the "
    "air after release; transport beyond 50 km; indoor air; time away from home; water and soil.",
    "A permitted rate is the legal ceiling, not a forecast. A facility that emits less than its "
    "permit allows produces less than these figures.",
]


def read_table(path, columns):
    """Rows of a hand-filled CSV with blank lines and the template's placeholder row dropped."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
        rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]
    return [r for r in rows if any(r.values()) and not r[columns[0]].startswith("<")]


def to_g_s(amount, unit, hours):
    """(grams per second averaged over a year, how it was converted) or (None, why not)."""
    if re.sub(r"\s+", "", unit.lower()) in ("g/s", "g/sec"):
        return amount, "as given"
    v, layer, note = pe.convert(amount, unit, hours)
    if layer == "lb":
        return v * G_PER_LB / SECONDS_PER_YEAR, note
    if layer == "g":
        return v / SECONDS_PER_YEAR, note
    return None, note


def cite(r):
    return f"{r['source_doc']} p. {r['page']}" if r.get("source_doc") and r.get("page") else None


def load_emissions(path, tox, catmap):
    """Per-source, per-chemical rates from source-emissions.csv.

    Returns (rows, problems). A row that cannot be used is left out and named in problems;
    nothing is guessed for it.
    """
    rows, problems = [], []
    for n, r in enumerate(read_table(path, EMISSION_COLUMNS), 2):
        where = f"source-emissions.csv line {n} ({r['source_id']}, {r['chemical']})"
        try:
            amount = float(r["amount"].replace(",", ""))
            hours = float(r["hours"]) if r["hours"] else None
        except ValueError:
            problems.append(f"{where}: amount or hours is not a number")
            continue
        g_s, how = to_g_s(amount, r["unit"], hours)
        basis = r["basis"].lower()
        scenario = "permitted" if basis in PERMITTED_BASIS else "expected" if basis in EXPECTED_BASIS else None
        if g_s is None:
            problems.append(f"{where}: {how}")
        elif scenario is None:
            problems.append(f"{where}: basis {r['basis']!r} is neither a permitted limit nor an expected rate")
        elif scenario == "expected" and not r["assumption"]:
            # An expected rate is only as good as the operating assumption behind it.
            problems.append(f"{where}: an expected rate needs the operating assumption it rests on")
        elif not cite(r):
            problems.append(f"{where}: no source document and page")
        elif r["status"].lower() not in ("", "new", "modified", "removed"):
            problems.append(f"{where}: status {r['status']!r} is not new, modified or removed")
        else:
            rec, key, tox_basis, note = toxvalues.resolve(tox, catmap, r["cas"] or r["chemical"])
            rows.append({"source": r["source_id"].upper(), "chemical": r["chemical"], "key": key,
                         "record": rec, "tox_basis": tox_basis, "tox_note": note, "g_s": g_s,
                         "scenario": scenario,
                         # Equipment the project retires is subtracted, not stacked on top.
                         "sign": -1.0 if r["status"].lower() == "removed" else 1.0,
                         "conversion": how, "assumption": r["assumption"] or None, "cite": cite(r),
                         "ocr_verified": r["ocr_verified"].lower() == "yes"})
    return rows, problems


def load_inventory(path, zone):
    """Stacks from source-inventory.csv in UTM `zone` metres.

    Returns (sources, problems, every source id in the file). Every emission point must be
    complete and cited; a missing stack parameter is never filled with a typical value.
    """
    sources, problems, seen = [], [], set()
    for n, r in enumerate(read_table(path, INVENTORY_COLUMNS), 2):
        sid, bad, s = r["source_id"].upper(), [], {"id": r["source_id"].upper(), "description": r["description"]}
        seen.add(sid)
        try:
            if r["lat"] and r["lon"]:
                s["x"], s["y"] = aermod_io.utm(float(r["lat"]), float(r["lon"]), zone)
            elif r["utm_e_m"] and r["utm_n_m"]:
                if r["datum"].upper().replace(" ", "") not in ("NAD83", "WGS84"):
                    bad.append("datum (NAD83 or WGS84; convert NAD27 coordinates first)")
                elif not r["utm_zone"] or int(r["utm_zone"]) != zone:
                    bad.append(f"utm_zone (the home is in zone {zone}; give lat and lon instead)")
                else:
                    s["x"], s["y"] = float(r["utm_e_m"]), float(r["utm_n_m"])
            else:
                bad.append("coordinates")
        except ValueError:
            bad.append("coordinates")
        for field, table, lo, hi in (("height", LENGTH_M, 0.0, 400.0), ("diameter", LENGTH_M, 0.01, 30.0),
                                     ("velocity", VELOCITY_M_S, 0.001, 150.0)):
            try:
                v = float(r[field]) * table[r[field + "_unit"].lower()]
                if not lo <= v <= hi:
                    raise ValueError
                s[{"height": "height_m", "diameter": "diameter_m", "velocity": "velocity_m_s"}[field]] = v
            except (ValueError, KeyError):
                bad.append(f"{field} (a number with unit {', '.join(table)})")
        try:
            t, u = float(r["temp"]), r["temp_unit"].upper()
            k = t if u == "K" else t + 273.15 if u == "C" else (t - 32) * 5 / 9 + 273.15 if u == "F" else None
            if k is None or not 250.0 <= k <= 2500.0:
                raise ValueError
            s["temp_k"] = k
        except ValueError:
            bad.append("temp (a number with unit K, C or F)")
        if not cite(r):
            bad.append("source_doc and page")
        s["cite"] = cite(r)
        if bad:
            problems.append(f"source-inventory.csv line {n} ({sid or 'no id'}): missing or unusable "
                            + "; ".join(bad))
        else:
            sources.append(s)
    return sources, problems, seen


def pick_proposed(a, name):
    props = a.get("proposed") or []
    if name:
        props = [p for p in props if p.get("name") == name]
    if len(props) != 1:
        sys.exit("model: assessment.json must name the proposed facility to model"
                 + (f"; --proposed {name!r} matches {len(props)}" if name else
                    f" (it lists {len(props)}; choose one with --proposed NAME)"))
    return props[0]


def model_home_xy(args, home):
    """Home in the applicant's coordinate system, or (None, why it is not known)."""
    if args.home_xy:
        try:
            x, y = (float(v) for v in args.home_xy.split(","))
        except ValueError:
            sys.exit("bad argument: --home-xy takes X,Y in the model's coordinates")
        return (x, y), "given with --home-xy in the model's own coordinates"
    if not args.utm_zone or not args.datum:
        return None, ("the applicant's coordinate system: give --utm-zone and --datum from the "
                      "modeling report, or --home-xy")
    if args.datum.upper() not in ("NAD83", "WGS84"):
        # NAD27 sits up to a few hundred metres from NAD83 and needs NOAA's grid shift.
        sys.exit(f"model: {args.datum} coordinates are not converted here. Convert the home to "
                 f"{args.datum} UTM with NOAA's NCAT tool and pass --home-xy X,Y.")
    return (aermod_io.utm(home[0], home[1], args.utm_zone),
            f"home projected to UTM zone {args.utm_zone}, {args.datum.upper()} (stated by the user "
            "from the modeling report; an assumption if the report does not say)")


def read_applicant_plots(specs):
    """[{"cas", "plt"}] for each CAS=FILE; exits on a file that is not a plot file."""
    out = []
    for spec in specs or []:
        cas, _, path = spec.partition("=")
        if not path:
            sys.exit(f"bad argument: --applicant-plot takes CAS=FILE, got {spec!r}")
        try:
            out.append({"cas": cas.strip(), "plt": aermod_io.parse_plt(path)})
        except (OSError, aermod_io.InputError) as e:
            sys.exit(f"model: {e}")
    return out


def read_applicant_inp(path):
    """(parsed input, None, None), or (None, gap, records request) when it cannot be used.

    An unusable input is a gap, not a stop: the applicant's plot files may still give a
    result, and the gap list is what the user takes back to the agency.
    """
    try:
        return aermod_io.parse_inp(path), None, None
    except OSError as e:
        sys.exit(f"model: {e}")
    except aermod_io.InputError as e:
        ask = ("Every file the AERMOD input refers to with INCLUDED (receptor, source and building "
               "files), filed with the application's air quality modeling"
               if "was not supplied" in str(e) else None)
        return None, f"the applicant's modeling input cannot be used: {e}; nothing was rerun from it", ask


def unit_rate_filing(inp):
    """Why the applicant's run looks like a unit-rate run, or None.

    Consultants often model every source at 1 g/s and scale by chemical in a spreadsheet. A
    plot file from such a run is concentration per unit rate, and reading it as a chemical's
    concentration would be wrong by the emission rate, often orders of magnitude. Identical
    equipment filed at identical real rates is refused too; the rerun covers it, and a wrong
    refusal costs nothing while a wrong acceptance is not detectable afterwards.
    """
    rates = {s["params"][0] for s in inp["sources"].values() if s["params"]}
    if len(rates) != 1:
        return None
    rate = next(iter(rates))
    n = sum(1 for s in inp["sources"].values() if s["params"])
    if n > 1:
        return f"all {n} sources carry the same emission rate ({rate:g})"
    return "its one source is set to 1 g/s" if rate == 1.0 else None


def home_terrain(args, inp, plots, xy):
    """(zelev, zhill, note) for the home receptor in an elevated-terrain run, or None."""
    rows = [r for p in plots for r in p["plt"]["rows"]] + [r for r in inp["receptors"] if r["zelev"] is not None]
    if rows:
        r, dist = aermod_io.nearest(rows, *xy)
        if dist <= BORROW_TERRAIN_M:
            return r["zelev"], r["zhill"], (f"terrain height at the home taken from the applicant's "
                                            f"receptor {dist:.0f} m away ({r['zelev']:.1f} m)")
    if args.home_elev is not None:
        return args.home_elev, args.home_elev, f"terrain height at the home given as {args.home_elev:g} m"
    return None


def unit_runs(base, text_for, ids, receptors, sfc, pfl):
    """Run unit-rate batches. Returns ({source id: [ug/m3 per g/s at each receptor]}, runs).

    Raises aermod_io.InputError with AERMOD's own message when a run fails; a failed run
    yields no number.
    """
    chi, runs = {}, []
    for n, batch in enumerate(aermod_io.batches(ids), 1):
        run_dir = os.path.join(base, f"run-{n:02d}")
        text, groups = text_for(batch)
        res = aermod_io.run(run_dir, text, sfc, pfl)
        if not res["ok"]:
            raise aermod_io.InputError(f"AERMOD run failed ({run_dir}/aermod.out): {res['problem']}")
        if res["units"] and not res["units"].upper().startswith("MICROGRAMS/M**3"):
            raise aermod_io.InputError(f"run reports {res['units']}, not micrograms per cubic metre")
        vals = aermod_io.group_values(run_dir, groups, receptors)
        for i in range(len(receptors)):
            total = sum(vals[g][i] for g in groups)
            # Five printed decimals per group bound how closely the parts can add up.
            if abs(total - vals["ALL"][i]) > 1e-5 * len(groups) + 1e-6 * vals["ALL"][i]:
                raise aermod_io.InputError(f"{run_dir}: source groups sum to {total:.5f}, group ALL is "
                                           f"{vals['ALL'][i]:.5f}; the run is not additive")
        for g, sid in groups.items():
            chi[sid] = [v / aermod_io.UNIT_RATE_G_S for v in vals[g]]
        runs.append({"dir": run_dir, "sources": len(batch), "hours": res["hours"],
                     "missing_pct": res["missing_pct"], "warnings": res["warnings"]})
    return chi, runs


def path_applicant_output(plots, xy, limit, tox, catmap):
    """Path 1: the applicant's own long-term result at the receptor nearest the home."""
    values, context, gaps = {}, [], []
    for p in plots:
        plt, name = p["plt"], os.path.basename(p["plt"]["file"])
        row, dist = aermod_io.nearest(plt["rows"], *xy)
        entry = {"file": name, "cas": p["cas"], "averaging": plt["aves"], "groups": plt["groups"],
                 "aermod_version": plt["version"], "nearest_receptor_m": round(dist, 1),
                 "value_at_nearest": row["conc"], "max_value": max(r["conc"] for r in plt["rows"])}
        if not aermod_io.long_term(plt):
            # A design value for one hour or one day says nothing about a year's average.
            entry["used"] = False
            context.append(entry)
            gaps.append(f"{name} holds {', '.join(plt['aves'])} values, not an annual or period "
                        "average; shown as short-term context only")
        elif dist > limit:
            entry["used"] = False
            context.append(entry)
            gaps.append(f"{name}: the nearest filed receptor is {dist:.0f} m from the home, beyond "
                        f"the {limit:.0f} m allowed; not used")
        elif len(plt["groups"]) != 1:
            entry["used"] = False
            context.append(entry)
            gaps.append(f"{name} mixes source groups {', '.join(plt['groups'])}; not used")
        else:
            rec, key, basis, note = toxvalues.resolve(tox, catmap, p["cas"])
            entry["used"] = True
            context.append(entry)
            values[key] = {"conc": row["conc"], "record": rec, "tox_basis": basis, "tox_note": note,
                           "chemical": (rec or {}).get("chemical") or p["cas"],
                           "note": f"applicant's {plt['aves'][0].lower()} result for source group "
                                   f"{plt['groups'][0]} at a receptor {dist:.0f} m from the home ({name})"}
    return values, context, gaps


def cross_check(inp, plots, chi, check_xy):
    """Compare the rerun, scaled by the filed rates, with the applicant's own long-term result.

    A match shows the meteorology, the included files and this AERMOD version reproduce what
    was filed. Returns a list of {"file", "filed", "rerun", "ratio"}.
    """
    out = []
    for p, xy in zip(plots, check_xy):
        plt = p["plt"]
        if xy is None:
            continue
        group = plt["groups"][0]
        members = list(inp["sources"]) if group == "ALL" else inp["groups"].get(group, [])
        if not members or any(m not in chi for m in members):
            continue
        row, _ = aermod_io.nearest(plt["rows"], *xy["xy"])
        rerun = sum(chi[m][xy["index"]] * aermod_io.filed_rate_g_s(inp["sources"][m]) for m in members)
        out.append({"file": os.path.basename(plt["file"]), "group": group, "filed": row["conc"],
                    "rerun": rerun, "ratio": rerun / row["conc"] if row["conc"] else None})
    return out


def find_met(args, inp):
    """(sfc, pfl) paths, from --sfc/--pfl or the names in the applicant's input, else None."""
    if args.sfc or args.pfl:
        # A path typed wrong must not fall back to whatever sits beside the input: the two
        # files are a matched pair from one AERMET run.
        if not (args.sfc and args.pfl):
            sys.exit("bad argument: --sfc and --pfl are given together")
        for path in (args.sfc, args.pfl):
            if not os.path.isfile(path):
                sys.exit(f"model: meteorology file not found: {path}")
        return args.sfc, args.pfl
    if not inp or not inp["surffile"] or not inp["proffile"]:
        return None
    found = []
    for a in (inp["surffile"], inp["proffile"]):
        name = a[0].replace("\\", "/")
        # Filed inputs often carry the modeler's own drive path; the file itself is usually
        # delivered beside the input.
        cands = [os.path.join(inp["dir"], name), os.path.join(inp["dir"], os.path.basename(name))]
        found.append(next((c for c in cands if os.path.isfile(c)), None))
    return tuple(found) if all(found) else None


def cmd_check_build(args):
    cache = os.path.join(aermod_io.CACHE, "testcases")
    members = sorted({m for c in aermod_io.TEST_CASES for m in aermod_io.test_members(c)})
    todo = [m for m in members if not os.path.exists(os.path.join(cache, m))]
    if not os.path.exists(aermod_io.EXE):
        sys.exit(f"AERMOD is not built. Run: bash {os.path.join(HERE, 'aermod_build.sh')}")
    if todo:
        print(f"Reading {len(todo)} test files out of EPA's 489 MB test archive by byte range "
              "(about 15 MB transferred, kept under ~/.cache/bayou/aermod).")
        rf = downloads.RemoteFile(aermod_io.TEST_URL)
        z = zipfile.ZipFile(rf)
        rf.WINDOW = 512 << 10
        for m in todo:
            path = os.path.join(cache, m)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(z.read(aermod_io.TEST_PREFIX + m))
    ok = True
    for case in aermod_io.TEST_CASES:
        with tempfile.TemporaryDirectory() as work:
            r = aermod_io.run_test_case(case, cache, work)
        ok &= r["ok"]
        if not r["run"]["ok"]:
            print(f"{case}: FAILED to run: {r['run']['problem']}")
            continue
        n, bad, rel, groups = r["summary"]
        rows = sum(p[1] for p in r["plots"])
        print(f"{case}: {'matches EPA' if r['ok'] else 'DIFFERS from EPA'}; {r['run']['hours']} hours; "
              f"{rows} plot-file rows, {sum(p[2] for p in r['plots'])} differ; {n} summary lines, "
              f"{bad} differ" + (f" (largest {rel:.1e} of the value, groups {', '.join(groups)})" if bad else ""))
    with tempfile.TemporaryDirectory() as work:
        lin = aermod_io.linearity_check(cache, work)
    ok &= lin["ok"]
    if lin["problem"]:
        print(f"linearity: FAILED to run: {lin['problem']}")
    else:
        print(f"linearity: {'holds' if lin['ok'] else 'FAILS'}; zero rate gives {lin['zero']:g}; "
              f"double rate gives 2 x the concentration to within {lin['ratio']:.1e}")
    print("AERMOD " + aermod_io.VERSION + (" reproduces EPA's published results and scales with "
                                           "emission rate." if ok else
                                           " does NOT pass these checks; do not use it."))
    sys.exit(0 if ok else 1)


def cmd_model(args):
    if args.check_build:
        return cmd_check_build(args)
    out = args.out
    if not out:
        sys.exit("model: --out is required")
    if inside_plugin(out):
        sys.exit(f"{out} is inside the plugin directory; household data must not be stored there.")
    a = load_assessment(out)
    p = pick_proposed(a, args.proposed)
    home = (a["home"]["lat"], a["home"]["lon"])
    tox, catmap, organs = toxvalues.load(), toxvalues.load_category_map(), toxvalues.load_organs()
    found = proposed_inputs(p)
    gaps, requests, assumptions, checks = [], [], [], []
    base = os.path.join(out, "model")

    emissions = []
    if found["source_emissions"]:
        try:
            emissions, problems = load_emissions(found["source_emissions"], tox, catmap)
        except ValueError as e:
            sys.exit(f"model: {e}")
        gaps += problems
    else:
        gaps.append("no source-emissions.csv: per-source, per-chemical emission rates are needed "
                    "to scale the dispersion result (template: templates/source-emissions.csv)")
        requests.append("The emission inventory questionnaire (EIQ) sheets or equivalent table giving "
                        "each emission point's rate for each toxic air pollutant")

    full_year = sorted({f"{e['source']} {e['chemical']}" for e in emissions
                        if "assumes continuous operation" in e["conversion"]})
    if full_year:
        assumptions.append("hourly rates with no stated hours are taken to run all 8,760 hours of "
                           "the year: " + ", ".join(full_year))

    plots = read_applicant_plots(args.applicant_plot)
    inp, why, ask = read_applicant_inp(args.applicant_inp) if args.applicant_inp else (None, None, None)
    if why:
        gaps.append(why)
    if ask:
        requests.append(ask)
    xy, xy_note = (None, None)
    if plots or inp:
        xy, xy_note = model_home_xy(args, home)
        if xy is None:
            gaps.append(f"the applicant's files cannot be used without {xy_note}")
        else:
            assumptions.append(xy_note)

    # Path 1: the applicant's own long-term output.
    direct, context, unit_plots = {}, [], []
    if plots and xy:
        filed_units = None
        if args.applicant_out:
            if not os.path.isfile(args.applicant_out):
                sys.exit(f"model: applicant output file not found: {args.applicant_out}")
            filed_units = aermod_io.parse_out(args.applicant_out)["units"]
        if inp and inp["nondefault_units"]:
            gaps.append("the applicant's input sets its own units (" + "; ".join(inp["nondefault_units"])
                        + "); its plot files are not read as micrograms per cubic metre")
        elif filed_units and not filed_units.upper().startswith("MICROGRAMS/M**3"):
            gaps.append(f"the applicant's output reports {filed_units}; its plot files are not read "
                        "as micrograms per cubic metre")
        elif inp and unit_rate_filing(inp):
            gaps.append(f"the applicant's input looks like a unit-rate run ({unit_rate_filing(inp)}), so "
                        "its plot files are concentration per unit of emission, not a chemical's "
                        "concentration; they are not used directly")
            unit_plots = [pl["cas"] for pl in plots]
        else:
            direct, context, g1 = path_applicant_output(plots, xy, args.max_receptor_m, tox, catmap)
            gaps += g1
            if direct and not inp and not filed_units:
                assumptions.append("the applicant's plot files are taken to be in micrograms per cubic "
                                   "metre, AERMOD's default; no input file was given and no output "
                                   "file stating its units")
            if direct and not inp:
                assumptions.append("each applicant plot file is taken to come from a run at that "
                                   "chemical's own emission rates, not a unit-rate run; without the "
                                   "input file this rests on the modeling report")

    # Paths 2 and 3: concentration per unit rate from each emission point.
    chi, sources, path, runs = {}, {}, None, []
    met = find_met(args, inp)
    if inp and xy:
        ids, refused = aermod_io.usable_sources(inp)
        gaps += [f"applicant source {sid}: {why}; no number for it" for sid, why in refused.items()]
        far = [sid for sid in ids if math.hypot(inp["sources"][sid]["xy"][0] - xy[0],
                                                inp["sources"][sid]["xy"][1] - xy[1]) > MAX_RADIUS_KM * 1000]
        receptor = {"x": xy[0], "y": xy[1]}
        terrain = None if aermod_io.is_flat(inp) else home_terrain(args, inp, plots, xy)
        if far:
            gaps.append(f"the home is over {MAX_RADIUS_KM:g} km from {len(far)} of the applicant's sources "
                        "in the coordinates given: either the zone or datum is wrong or the home is "
                        "beyond AERMOD's range; nothing was run")
        elif met is None:
            gaps.append("the meteorology files named in the applicant's input (" +
                        ", ".join(x[0] for x in (inp["surffile"], inp["proffile"]) if x) +
                        ") were not found; give them with --sfc and --pfl")
            requests.append("The AERMOD-ready surface (.SFC) and profile (.PFL) meteorology files used "
                            "in the application's air quality modeling")
        elif not aermod_io.is_flat(inp) and terrain is None:
            gaps.append("the applicant modeled elevated terrain and no filed receptor lies within "
                        f"{BORROW_TERRAIN_M:.0f} m of the home; give the home's ground elevation with --home-elev")
        elif ids:
            if terrain:
                receptor.update(zelev=terrain[0], zhill=terrain[1])
                assumptions.append(terrain[2])
            receptors, check_xy = [receptor], []
            for pl in plots:
                if aermod_io.long_term(pl["plt"]) and len(pl["plt"]["groups"]) == 1:
                    r, _ = aermod_io.nearest(pl["plt"]["rows"], *xy)
                    receptors.append({"x": r["x"], "y": r["y"], "zelev": r["zelev"], "zhill": r["zhill"]})
                    check_xy.append({"xy": (r["x"], r["y"]), "index": len(receptors) - 1})
                else:
                    check_xy.append(None)
            dropped = []

            def text_for(batch):
                text, groups, d = aermod_io.rerun_text(inp, batch, receptors)
                dropped.extend(d)
                return text, groups
            try:
                chi, runs = unit_runs(base, text_for, ids, receptors, *met)
                path = "applicant input, rerun"
            except (aermod_io.InputError, OSError) as e:
                gaps.append(str(e))
            if chi:
                for sid in ids:
                    s = inp["sources"][sid]
                    sources[sid] = {"type": s["type"], "distance_km": round(math.hypot(
                        s["xy"][0] - xy[0], s["xy"][1] - xy[1]) / 1000, 2), "filed_rate_g_s": aermod_io.filed_rate_g_s(s)}
                checks = cross_check(inp, plots, chi, check_xy)
                if not checks:
                    assumptions.append("the rerun was not checked against a result the applicant filed: "
                                       "no annual or period plot file was given")
                if dropped:
                    assumptions.append("left out of the applicant's input for the rerun: "
                                       + ", ".join(sorted(set(dropped))))
                if inp["emisfact"]:
                    assumptions.append("the applicant's operating-schedule factors (EMISFACT) are not "
                                       "applied; annual totals are spread evenly over the year")
                assumptions.append(f"receptor height above ground: {inp['flagpole'] or 0:g} m, as the applicant set it")
                if inp["background"]:
                    assumptions.append("the applicant's background concentration is left out; this is "
                                       "the facility's contribution alone")
    elif not inp and found["source_inventory"]:
        zone = aermod_io.utm_zone(home[1])
        try:
            inv, problems, named = load_inventory(found["source_inventory"], zone)
        except ValueError as e:
            sys.exit(f"model: {e}")
        problems += [f"source-emissions.csv names {sid}, which source-inventory.csv does not describe"
                     for sid in sorted({e["source"] for e in emissions} - named)]
        hx, hy = aermod_io.utm(home[0], home[1], zone)
        if problems:
            # One incomplete stack makes the facility total wrong by an unknown amount, so
            # the inventory is modeled whole or not at all.
            gaps += problems
            gaps.append("source-inventory.csv is incomplete; no dispersion run was built from it")
            requests.append("Stack height, inside diameter, exit temperature, exit velocity and "
                            "coordinates for each emission point (EIQ sheets), and the air quality "
                            "modeling input files")
        elif not inv:
            gaps.append("source-inventory.csv lists no emission points")
        elif met is None or args.profbase_m is None:
            gaps.append("a run from the inventory needs --sfc, --pfl and --profbase-m (the base "
                        "elevation of the meteorological tower, from the modeling protocol)")
            requests.append("The AERMOD-ready surface (.SFC) and profile (.PFL) meteorology files LDEQ "
                            "approved for this facility's modeling, with the station base elevation")
        elif any(math.hypot(s["x"] - hx, s["y"] - hy) > MAX_RADIUS_KM * 1000 for s in inv):
            gaps.append(f"an emission point is over {MAX_RADIUS_KM:g} km from the home; nothing was run")
        else:
            try:
                head = aermod_io.sfc_header(met[0])
                head["profbase_m"] = args.profbase_m
                by_id = {s["id"]: s for s in inv}

                def text_for(batch):
                    text, groups = aermod_io.inventory_text([by_id[i] for i in batch], {"x": hx, "y": hy},
                                                            head, f"{p['name']} unit-rate run", args.urban_pop)
                    return text, {g: batch[i] for i, g in enumerate(groups)}
                chi, runs = unit_runs(base, text_for, list(by_id), [{"x": hx, "y": hy}], *met)
                path = "built from source-inventory.csv"
                for s in inv:
                    sources[s["id"]] = {"type": "POINT", "cite": s["cite"], "distance_km": round(
                        math.hypot(s["x"] - hx, s["y"] - hy) / 1000, 2)}
                assumptions += [
                    "no building downwash: the inventory carries no building dimensions, which can "
                    "understate concentrations within a few hundred metres of a stack",
                    "flat terrain and " + ("urban" if args.urban_pop else "rural") + " dispersion",
                    f"meteorology from station {head['sf_id']} ({head['location']}), starting {head['year']}, "
                    "supplied by the user; whether it represents the site is not checked here",
                    "sources placed in UTM zone %d on NAD83" % zone]
            except (aermod_io.InputError, OSError) as e:
                gaps.append(str(e))
    elif not inp and not args.applicant_inp:
        gaps.append("no applicant modeling input and no source-inventory.csv: there is nothing to "
                    "run a dispersion model on")
        requests.append("The air quality modeling files filed with the application: AERMOD input "
                        "(.inp or .ami), output and plot files, BPIP files and meteorology (.SFC, .PFL)")

    # Chemicals: path 1 where the applicant modeled the chemical itself, else rate x unit result.
    scenarios = {}
    for scen in ("permitted", "expected"):
        chems = {}
        for e in emissions:
            if e["scenario"] != scen:
                continue
            c = chems.setdefault(e["key"], {"chemical": (e["record"] or {}).get("chemical") or e["chemical"],
                                            "record": e["record"], "tox_basis": e["tox_basis"],
                                            "tox_note": e["tox_note"], "conc": 0.0, "g_s": 0.0,
                                            "by_source": {}, "missing_sources": [], "notes": []})
            c["g_s"] += e["sign"] * e["g_s"]
            if e["source"] in chi:
                v = e["sign"] * e["g_s"] * chi[e["source"]][0]
                c["conc"] += v
                c["by_source"][e["source"]] = c["by_source"].get(e["source"], 0.0) + v
            else:
                c["missing_sources"].append(e["source"])
            if e["assumption"]:
                c["notes"].append(e["assumption"])
        for key, c in chems.items():
            c["path"] = path if c["by_source"] else None
            if c["missing_sources"]:
                # A partial sum would read as the facility's total; give none.
                c["rerun_conc"], c["conc"], c["path"] = None, None, None
                if path:
                    gaps.append(f"{c['chemical']} ({scen}): no dispersion result for "
                                f"{', '.join(sorted(set(c['missing_sources'])))}; no number given")
            else:
                c["rerun_conc"] = c["conc"]
        if scen == "permitted":
            for key, d in direct.items():
                c = chems.setdefault(key, {"chemical": d["chemical"], "record": d["record"],
                                           "tox_basis": d["tox_basis"], "tox_note": d["tox_note"],
                                           "g_s": None, "by_source": {}, "missing_sources": [],
                                           "notes": [], "rerun_conc": None})
                c.update(conc=d["conc"], path="applicant output")
                c["notes"].append(d["note"])
                alt = c["rerun_conc"]
                if alt is not None and not 0.8 <= (alt / d["conc"] if d["conc"] else 0) <= 1.25:
                    # Both are shown; the applicant's own run is used because its rates
                    # are the ones the agency reviewed.
                    gaps.append(f"{c['chemical']}: the applicant's own result at the home is {d['conc']:.3g} "
                                f"ug/m3, but source-emissions.csv rates times the rerun give {alt:.3g}; "
                                "the rates entered do not match what the applicant modeled")
        if chems:
            scenarios[scen] = chems

    for cas in unit_plots:
        rec, key, _, _ = toxvalues.resolve(tox, catmap, cas)
        if not any(key in s for s in scenarios.values()):
            gaps.append(f"{(rec or {}).get('chemical') or cas}: the filed plot is from a unit-rate run and "
                        "source-emissions.csv gives no per-source rates for it; no number")

    # A facility-wide total with no per-source split cannot be placed on any stack.
    if found["proposed_emissions"]:
        try:
            for r in read_table(found["proposed_emissions"], pe.COLUMNS):
                _, key, _, _ = toxvalues.resolve(tox, catmap, r["cas"] or r["chemical"])
                if not any(key in s for s in scenarios.values()):
                    gaps.append(f"{r['chemical']}: proposed-emissions.csv gives a facility-wide total only; "
                                "no number without its split by emission point")
        except ValueError as e:
            gaps.append(str(e))

    w0, w1 = operating_window(p)
    result_scen = {}
    for scen, chems in scenarios.items():
        usable = {k: c for k, c in chems.items() if c["conc"] is not None}
        pairs = {(p["name"], k): {y: {"conc": c["conc"]} for y in range(w0.year, w1.year + 1)}
                 for k, c in usable.items()}
        info = {k: {"record": c["record"], "rsei_names": [c["chemical"]], "basis": c["tox_basis"],
                    "note": c["tox_note"]} for k, c in usable.items()}
        result_scen[scen] = {
            "chemicals": {k: {"chemical": c["chemical"], "conc_ug_m3": c["conc"], "path": c["path"],
                              "rate_g_s": c["g_s"], "rerun_conc_ug_m3": c["rerun_conc"],
                              "by_source_ug_m3": dict(sorted(c["by_source"].items(), key=lambda kv: -abs(kv[1]))),
                              "ure_per_ug_m3": (c["record"] or {}).get("ure_per_ug_m3"),
                              "rfc_ug_m3": (c["record"] or {}).get("rfc_ug_m3"),
                              "target_organs": organs.get(k), "notes": sorted(set(c["notes"]))}
                          for k, c in chems.items()},
            "members": {m["id"]: member_results(a, m, pairs, info, organs, proposed=p) for m in a["members"]},
        }
    build = os.path.join(aermod_io.CACHE, "BUILD.txt")
    result = {
        "schema_version": SCHEMA_VERSION, "generated": dt.date.today().isoformat(), "label": a["label"],
        "proposed": {"name": p["name"], "operating_start": w0.isoformat(), "operating_end": w1.isoformat()},
        "dispersion_path": path,
        "home_in_model_coordinates": {"x": round(xy[0], 1), "y": round(xy[1], 1)} if xy else None,
        "sources": {sid: {**s, "ug_m3_per_g_s": chi[sid][0]} for sid, s in sources.items()},
        "scenarios": result_scen,
        "applicant_files": context,
        "checks": checks, "runs": runs, "assumptions": assumptions,
        "stays": {m["id"]: open_end(a, m, p).isoformat() for m in a["members"]},
        "gaps": gaps, "records_to_request": list(dict.fromkeys(requests)),
        "limitations": MODEL_LIMITATIONS,
        # For the report's manifest: the files this result was computed from.
        "inputs": [{"role": role, "path": os.path.abspath(path)} for role, path in
                   [("source-emissions.csv", found["source_emissions"]),
                    ("source-inventory.csv", found["source_inventory"]),
                    ("proposed-emissions.csv", found["proposed_emissions"]),
                    ("applicant AERMOD input", args.applicant_inp),
                    ("applicant AERMOD output", args.applicant_out),
                    ("surface meteorology", met and met[0]), ("profile meteorology", met and met[1])]
                   + [("applicant plot file", spec.split("=", 1)[1]) for spec in args.applicant_plot or []]
                   if path and os.path.isfile(path)],
        "provenance": {"toxicity": toxvalues.provenance(),
                       "aermod": {"version": aermod_io.VERSION,
                                  "build": open(build).read().splitlines() if os.path.exists(build) else None,
                                  "applicant_version": next((c["aermod_version"] for c in context
                                                             if c["aermod_version"]), None)}},
    }
    write_private(os.path.join(out, "model.json"), json.dumps(result, indent=2) + "\n")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["scenario", "chemical", "cas_or_id", "source_id", "distance_km", "ug_m3_per_g_s",
                "conc_ug_m3", "path"])
    for scen, s in result_scen.items():
        for key, c in sorted(s["chemicals"].items(), key=lambda kv: kv[1]["chemical"]):
            for sid, v in c["by_source_ug_m3"].items():
                w.writerow([scen, c["chemical"], key, sid, sources[sid]["distance_km"],
                            f"{chi[sid][0]:.6g}", f"{v:.6g}", path])
            w.writerow([scen, c["chemical"], key, "TOTAL", "", "",
                        "" if c["conc_ug_m3"] is None else f"{c['conc_ug_m3']:.6g}", c["path"] or "no number"])
    write_private(os.path.join(out, "model.csv"), buf.getvalue())
    write_private(os.path.join(out, "model-gaps.md"), gaps_text(result))
    print_model(result, out)


def gaps_text(r):
    """The missing-input checklist and the items for a records request, as Markdown."""
    lines = [f"# Dispersion modeling gaps: {r['proposed']['name']}", "",
             "Each line is an input the model did not have. No figure was estimated in its place.", ""]
    lines += [f"- [ ] {g}" for g in r["gaps"]] or ["Nothing is missing."]
    if r["records_to_request"]:
        lines += ["", "## Records to request", "",
                  "Ask LDEQ (Public Records Center, or the Air Permits Division permit writer) for:", ""]
        lines += [f"{i}. {x}" for i, x in enumerate(r["records_to_request"], 1)]
        lines += ["", "Application files are also in EDMS under the facility's Agency Interest "
                      "number; modeling files are often attached as a separate compressed archive "
                      "or held on disc and listed in the document index."]
    return "\n".join(lines) + "\n"


def print_model(r, out):
    print(f"\nModel written: {os.path.join(out, 'model.json')}, model.csv, model-gaps.md")
    print(f"Proposed: {r['proposed']['name']}, operating {r['proposed']['operating_start']} to "
          f"{r['proposed']['operating_end']}")
    print(f"Dispersion: {r['dispersion_path'] or 'no run'}; sources with a result: {len(r['sources'])}")
    for run in r["runs"]:
        print(f"  {run['sources']} sources, {run['hours']} hours of meteorology"
              + (f", {run['missing_pct']:g}% missing" if run["missing_pct"] else ""))
    for c in r["checks"]:
        print(f"  check against {c['file']} (group {c['group']}): applicant {c['filed']:.5g}, "
              f"rerun x filed rates {c['rerun']:.5g}"
              + (f", ratio {c['ratio']:.3f}" if c["ratio"] is not None else ""))
    for f in r["applicant_files"]:
        print(f"  {f['file']}: {', '.join(f['averaging'])}, nearest receptor {f['nearest_receptor_m']:.0f} m, "
              + ("used" if f["used"] else "context only"))
    for x in r["assumptions"]:
        print(f"  assumption: {x}")
    for scen, s in r["scenarios"].items():
        got = {k: c for k, c in s["chemicals"].items() if c["conc_ug_m3"] is not None}
        print(f"\nScenario: {scen}; chemicals with a concentration at the home: {len(got)} of {len(s['chemicals'])}")
        for k, c in sorted(got.items(), key=lambda kv: -abs(kv[1]["conc_ug_m3"]))[:8]:
            print(f"    {c['chemical'][:34]:34} {c['conc_ug_m3']:.3g} ug/m3  ({c['path']})")
        if not got:
            print("  no concentration, so no exposure figure for anyone")
            continue
        for mid, m in s["members"].items():
            t = m["totals"]
            if not m["rows"]:
                print(f"  Member {mid}: not at the home while the facility operates (stays to {r['stays'][mid]})")
                continue
            print(f"  Member {mid} (assumed to stay to {r['stays'][mid]}): cancer risk {sci(t['cancer_risk'])}"
                  + (f" (about {t['cancer_risk'] * 1e6:.3g} in a million)" if t["cancer_risk"] else "")
                  + f" over {t['cancer_chemicals']} chemicals")
            if t["hazard_index"]:
                hi = sorted(t["hazard_index"].items(), key=lambda kv: -kv[1])[:4]
                print("    hazard index by target organ: "
                      + ", ".join(f"{toxvalues.ORGAN_NAMES.get(o, o)} {sci(v)}" for o, v in hi))
    if r["gaps"]:
        print(f"\nMissing inputs ({len(r['gaps'])}); see model-gaps.md:")
        for g in r["gaps"][:12]:
            print(f"  - {g}")
    print("\nThese are modeled outdoor concentrations from the proposed facility alone, not "
          "measurements and not doses.")


# ------------------------------------------------------------ report

def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_shared(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def cmd_report(args):
    # Imported here: charts needs matplotlib, which the other subcommands do not.
    import charts
    import report
    out = args.out
    if inside_plugin(out):
        sys.exit(f"{out} is inside the plugin directory; household data must not be stored there.")
    a = load_assessment(out)
    scr, mod = read_json(os.path.join(out, "screening.json")), read_json(os.path.join(out, "model.json"))
    if scr is None and mod is None:
        sys.exit("report: neither screening.json nor model.json exists; run `screen` or `model` first")
    screen_rows = []
    if scr:
        with open(os.path.join(out, "screen.csv"), newline="", encoding="utf-8") as f:
            screen_rows = list(csv.DictReader(f))
    r = report.build(a, scr, mod, args.public)
    dest = os.path.join(out, "public") if args.public else out
    os.makedirs(dest, exist_ok=True)
    # A private report names the home; a public one is meant to be handed out.
    put = write_shared if args.public else write_private
    paths = charts.render(r, os.path.join(dest, "charts"), args.formats.split(","))
    files = {"REPORT.md": report.render_md(r, [os.path.relpath(p, dest) for p in paths]),
             "exposure.csv": report.exposure_rows(r, screen_rows, mod),
             "results.json": json.dumps(r, indent=2) + "\n"}
    for name, text in files.items():
        put(os.path.join(dest, name), text)
    written = [os.path.join(dest, n) for n in files] + paths
    put(os.path.join(dest, "manifest.json"),
        json.dumps(report.manifest(r, out, scr, mod, written, dest), indent=2) + "\n")
    print(f"Report written: {os.path.join(dest, 'REPORT.md')}, exposure.csv, results.json, manifest.json, "
          f"{len(paths)} chart files")
    if r["not_run"]:
        print("  not run, so absent: " + "; ".join(r["not_run"]))
    if args.public:
        print("  public version: no address, coordinates, grid cell, census block or distances. "
              "Read it before sharing.")
    else:
        print("  this version names the home; use --public for one that can be shared")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--out")
    s.add_argument("--label")
    s.add_argument("--at", help="home LAT,LON")
    s.add_argument("--address")
    s.add_argument("--member", action="append", help="ID:START..END[,START..END]; blank END = still there")
    s.add_argument("--birth", action="append", help="ID=YEAR")
    s.add_argument("--radius-km", type=float, default=MAX_RADIUS_KM)
    s.add_argument("--proposed", help="permit-analysis output directory for a proposed facility")
    s.add_argument("--proposed-name")
    s.add_argument("--op-start", type=int)
    s.add_argument("--op-years", type=float)
    s.add_argument("--stay", action="append",
                   help="how long members stay, for proposed scenarios: operating_end, a date or "
                        "a year; prefix with ID= for one member")
    s.add_argument("--facilities", action="store_true", help="list TRI facilities in the radius (network)")
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--yes", action="store_true", help="the user has confirmed any large download")
    s.set_defaults(func=cmd_prepare)
    s = sub.add_parser("screen")
    s.add_argument("--out", required=True)
    s.add_argument("--years", help="FIRST-LAST: read only these RSEI years; the rest stay unknown")
    s.add_argument("--no-airtox", action="store_true", help="skip the AirToxScreen block lookup")
    s.add_argument("--block", help="2020 census block GEOID of the home, to avoid sending its "
                                   "coordinates to the Census geocoder")
    s.add_argument("--rsei-dir", help="directory of RSEI microdata files already downloaded")
    s.add_argument("--yes", action="store_true", help="the user has confirmed any large download")
    s.set_defaults(func=cmd_screen)
    s = sub.add_parser("model")
    s.add_argument("--out")
    s.add_argument("--check-build", action="store_true",
                   help="rerun EPA's published AERMOD test cases with the local build and exit")
    s.add_argument("--proposed", help="name of the proposed facility in assessment.json")
    s.add_argument("--applicant-plot", action="append", metavar="CAS=FILE",
                   help="a plot file from the applicant's modeling of that chemical; repeatable")
    s.add_argument("--applicant-inp", help="the applicant's AERMOD input file")
    s.add_argument("--applicant-out", help="the applicant's AERMOD output file, to confirm units")
    s.add_argument("--sfc", help="AERMOD surface meteorology file")
    s.add_argument("--pfl", help="AERMOD profile meteorology file")
    s.add_argument("--profbase-m", type=float, help="base elevation of the met tower, metres")
    s.add_argument("--utm-zone", type=int, help="UTM zone of the applicant's coordinates")
    s.add_argument("--datum", help="datum of the applicant's coordinates (NAD83 or WGS84)")
    s.add_argument("--home-xy", help="the home as X,Y in the applicant's coordinates")
    s.add_argument("--home-elev", type=float, help="ground elevation at the home, metres")
    s.add_argument("--max-receptor-m", type=float, default=MAX_RECEPTOR_M,
                   help="how far a filed receptor may be from the home and still stand in for it")
    s.add_argument("--urban-pop", type=int, help="urban population, for a run built from the inventory")
    s.set_defaults(func=cmd_model)
    s = sub.add_parser("report")
    s.add_argument("--out", required=True)
    s.add_argument("--public", action="store_true",
                   help="write a version without the home's location to DIR/public/")
    s.add_argument("--formats", default="print", help="chart presets: print, social or both")
    s.set_defaults(func=cmd_report)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
