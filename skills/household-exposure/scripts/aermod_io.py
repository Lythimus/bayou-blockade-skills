"""Read and write AERMOD files, and run the pinned local build.

Three jobs, all for one receptor at a home:
  - read an applicant's plot file and say whether it holds a long-term average at all;
  - turn an applicant's input file into a unit-rate rerun whose result scales linearly with
    each source's emission rate;
  - build a run from a stack inventory when no applicant input exists.

An applicant's files are untrusted. Nothing here lets a filed input choose where AERMOD
writes: every output and restart keyword is dropped and the run's own outputs go in the run
directory.
"""
import math
import os
import re
import shutil
import subprocess

VERSION = "v26135"
CACHE = os.path.join(os.environ.get("BAYOU_AERMOD_DIR")
                     or os.path.join(os.path.expanduser("~"), ".cache", "bayou", "aermod"), VERSION)
EXE = os.path.join(CACHE, "aermod")

PATHWAYS = ("CO", "SO", "RE", "ME", "OU", "EV")
LONG_TERM = {"PERIOD", "ANNUAL"}

# AERMOD prints concentrations with five decimals. A 1 g/s source 30 km away gives a few
# thousandths of a ug/m3, which would keep one or two digits; a kilogram per second keeps five.
UNIT_RATE_G_S = 1000.0

G_S = {"POINT", "POINTCAP", "POINTHOR", "VOLUME"}
G_S_M2 = {"AREA", "AREACIRC", "AREAPOLY", "OPENPIT", "LINE"}
# Emission terms whose layout was not checked here; a source of these types gets no number.
UNSUPPORTED = {"RLINE", "RLINEXT", "BUOYLINE", "SWPOINT"}
TWO_POINT = {"LINE", "RLINE", "BUOYLINE"}

# Options that make the result depend on something other than rate x dispersion, or that ask
# for an output other than concentration.
DROP_MODELOPT = {"DEPOS", "DDEP", "WDEP", "DRYDPLT", "WETDPLT", "AREADPLT", "OLM", "PVMRM",
                 "ARM2", "GRSM", "TTRM", "TTRM2", "PSDCREDIT", "SCREEN", "SCIM", "TOXICS"}
KEEP_CO = {"TITLEONE", "TITLETWO", "MODELOPT", "URBANOPT", "FLAGPOLE", "LOW_WIND",
           "AWMADWNW", "ORD_DWNW"}
KEEP_SO = {"ELEVUNIT", "LOCATION", "SRCPARAM", "BUILDHGT", "BUILDWID", "BUILDLEN", "XBADJ",
           "YBADJ", "AREAVERT", "URBANSRC"}
PER_SOURCE = KEEP_SO - {"ELEVUNIT"}
KEEP_ME = {"SURFFILE", "PROFFILE", "SURFDATA", "UAIRDATA", "SITEDATA", "PROFBASE", "STARTEND",
           "DAYRANGE", "WDROTATE", "WINDCATS", "NUMYEARS"}
# Each run opens one plot file per source; this stays well under the default limit of 256
# open files per process on macOS.
BATCH = 150
FT = 0.3048


class InputError(ValueError):
    """An input file that cannot be used, with a message fit to show the user."""


def num(s):
    """A Fortran-style number: 1.0D0 and 0.1674E+08 both occur in filed inputs."""
    return float(s.upper().replace("D", "E"))


def tokens(line):
    return [t.strip('"') for t in re.findall(r'"[^"]*"|\S+', line)]


def inside(path, root):
    root, path = os.path.realpath(root), os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


def read_cards(path, root=None, pathway=None, depth=0):
    """Flatten an input file and the files it includes into a list of cards.

    A line may leave out the pathway and take it from the line above; keywords are not case
    sensitive; `**` starts a comment. An INCLUDED file must sit under `root` (default: the
    input file's directory), because the path comes from the applicant.
    """
    root = root or os.path.dirname(os.path.abspath(path))
    if depth > 4:
        raise InputError(f"{path}: INCLUDED files nest too deeply")
    cards = []
    with open(path, encoding="latin-1") as f:
        for n, line in enumerate(f, 1):
            if not line.strip() or line.lstrip().startswith("**"):
                continue
            t = tokens(line)
            if t[0].upper() in PATHWAYS:
                pathway, t = t[0].upper(), t[1:]
            if not t:
                continue
            if pathway is None:
                raise InputError(f"{path}:{n}: keyword before any pathway")
            kw, args = t[0].upper(), t[1:]
            if kw == "INCLUDED":
                if not args:
                    raise InputError(f"{path}:{n}: INCLUDED names no file")
                inc = os.path.join(os.path.dirname(os.path.abspath(path)), args[0].replace("\\", "/"))
                if not inside(inc, root):
                    raise InputError(f"{path}:{n}: INCLUDED file {args[0]!r} is outside the case directory")
                if not os.path.exists(inc):
                    raise InputError(f"{path}:{n}: INCLUDED file {args[0]!r} was not supplied")
                cards += read_cards(inc, root, pathway, depth + 1)
                continue
            cards.append({"path": pathway, "kw": kw, "args": args, "file": path, "line": n})
    return cards


def polygon_area(v):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(v, v[1:] + v[:1]))) / 2.0


def source_area(s):
    """Emitting area in m2 for the source types whose rate is per unit area."""
    t, p = s["type"], s["params"]
    if t in ("AREA", "OPENPIT"):
        # AREA's y side defaults to the x side; OPENPIT requires both.
        return p[2] * (p[3] if len(p) > 3 else p[2])
    if t == "AREACIRC":
        return math.pi * p[2] ** 2
    if t == "AREAPOLY":
        if len(s["verts"]) != int(p[2]):
            raise InputError(f"source {s['id']}: {len(s['verts'])} vertices given, {int(p[2])} declared")
        return polygon_area(s["verts"])
    if t == "LINE":
        x1, y1, x2, y2 = s["loc"][:4]
        return math.hypot(x2 - x1, y2 - y1) * p[2]
    raise InputError(f"source {s['id']}: no area rule for type {t}")


def unit_rate(s):
    """Emission-rate field that makes the source emit UNIT_RATE_G_S in total."""
    if s["type"] in G_S:
        return UNIT_RATE_G_S
    area = source_area(s)
    if area <= 0:
        raise InputError(f"source {s['id']}: emitting area is zero")
    return UNIT_RATE_G_S / area


def filed_rate_g_s(s):
    """The source's total emission rate as filed, in g/s."""
    return s["params"][0] * (1.0 if s["type"] in G_S else source_area(s))


def parse_inp(path):
    """Structure of an applicant's input file. Raises InputError when it cannot be read."""
    cards = read_cards(path)
    d = {"file": path, "dir": os.path.dirname(os.path.abspath(path)), "cards": cards,
         "title": None, "modelopt": [], "avertime": [], "pollutid": None, "flagpole": None,
         "elevunit": {"SO": "METERS", "RE": "METERS"}, "sources": {}, "groups": {},
         "receptors": [], "surffile": None, "proffile": None, "outputs": [], "hourly": set(),
         "emisfact": set(), "nondefault_units": [], "background": False}
    params, verts = {}, {}
    for c in cards:
        p, kw, a = c["path"], c["kw"], c["args"]
        if p == "CO":
            if kw == "TITLEONE":
                d["title"] = " ".join(a)
            elif kw == "MODELOPT":
                d["modelopt"] += [x.upper() for x in a]
            elif kw == "AVERTIME":
                d["avertime"] += [x.upper() for x in a]
            elif kw == "POLLUTID" and a:
                d["pollutid"] = a[0].upper()
            elif kw == "FLAGPOLE":
                d["flagpole"] = num(a[0]) if a else 0.0
        elif p == "SO":
            sid = a[0].upper() if a else None
            if kw == "ELEVUNIT" and a:
                d["elevunit"]["SO"] = a[0].upper()
            elif kw == "LOCATION" and len(a) >= 4:
                d["sources"][sid] = {"id": sid, "type": a[1].upper(), "loc_args": a[2:]}
            elif kw == "SRCPARAM":
                params.setdefault(sid, []).extend(a[1:])
            elif kw == "AREAVERT":
                verts.setdefault(sid, []).extend(a[1:])
            elif kw == "SRCGROUP" and a:
                d["groups"].setdefault(sid, []).extend(x.upper() for x in a[1:])
            elif kw == "HOUREMIS":
                d["hourly"].update(x.upper() for x in a[1:])
            elif kw == "EMISFACT":
                d["emisfact"].add(sid)
            elif kw in ("EMISUNIT", "CONCUNIT"):
                d["nondefault_units"].append(f"{kw} {' '.join(a)}")
            elif kw == "BACKGRND":
                d["background"] = True
        elif p == "RE":
            if kw == "ELEVUNIT" and a:
                d["elevunit"]["RE"] = a[0].upper()
            elif kw == "DISCCART" and len(a) >= 2:
                try:
                    v = [num(x) for x in a[:5]]
                except ValueError:
                    continue
                k = FT if d["elevunit"]["RE"] == "FEET" else 1.0
                d["receptors"].append({"x": v[0], "y": v[1],
                                       "zelev": v[2] * k if len(v) >= 4 else None,
                                       "zhill": v[3] * k if len(v) >= 4 else None})
        elif p == "ME":
            if kw == "SURFFILE" and a:
                d["surffile"] = a
            elif kw == "PROFFILE" and a:
                d["proffile"] = a
        elif p == "OU" and kw not in ("STARTING", "FINISHED"):
            d["outputs"].append((kw, a))
    for sid, s in d["sources"].items():
        la = s["loc_args"]
        try:
            n = 6 if s["type"] == "RLINEXT" else 4 if s["type"] in TWO_POINT else 2
            s["loc"] = [num(x) for x in la[:n]]
            s["params"] = [num(x) for x in params.get(sid, [])]
            v = [num(x) for x in verts.get(sid, [])]
        except ValueError as e:
            raise InputError(f"source {sid}: {e}") from None
        s["verts"] = list(zip(v[0::2], v[1::2]))
        if s["type"] == "RLINEXT":
            s["xy"] = ((s["loc"][0] + s["loc"][3]) / 2, (s["loc"][1] + s["loc"][4]) / 2)
        elif s["type"] in TWO_POINT:
            s["xy"] = ((s["loc"][0] + s["loc"][2]) / 2, (s["loc"][1] + s["loc"][3]) / 2)
        else:
            s["xy"] = (s["loc"][0], s["loc"][1])
    return d


def is_flat(inp):
    """True when receptor elevations are ignored. AERMOD's default is elevated terrain."""
    return "FLAT" in inp["modelopt"] and "ELEV" not in inp["modelopt"]


def usable_sources(inp):
    """(ids that can be rerun at a unit rate, {id: reason} for the rest)."""
    ok, refused = [], {}
    for sid, s in inp["sources"].items():
        if s["type"] in UNSUPPORTED or s["type"] not in G_S | G_S_M2:
            refused[sid] = f"source type {s['type']} is not handled"
        elif sid in inp["hourly"]:
            # An hourly emission file replaces the rate (and often the exit temperature and
            # velocity) hour by hour, so one unit-rate result cannot be scaled to it.
            refused[sid] = "emissions come from an hourly file (HOUREMIS)"
        elif not s["params"]:
            refused[sid] = "no SRCPARAM line"
        else:
            try:
                unit_rate(s)
                ok.append(sid)
            except (InputError, IndexError) as e:
                refused[sid] = str(e)
    return ok, refused


def _fmt(x):
    return f"{x:.4f}".rstrip("0").rstrip(".") if abs(x) >= 0.001 or x == 0 else f"{x:.8E}"


def receptor_line(r, flat):
    if flat:
        return f"   DISCCART  {r['x']:.2f}  {r['y']:.2f}"
    return f"   DISCCART  {r['x']:.2f}  {r['y']:.2f}  {r['zelev']:.2f}  {r['zhill']:.2f}"


def rerun_text(inp, source_ids, receptors, sfc_name="met.sfc", pfl_name="met.pfl"):
    """Input text for a unit-rate PERIOD run of `source_ids` at `receptors`.

    Returns (text, {group id: source id}, dropped) where dropped lists the applicant's
    keywords left out. Each source is its own group so that results can be scaled by that
    source's rate for each chemical; group ALL is kept to check that the groups add up.
    """
    keep, flat = set(source_ids), is_flat(inp)
    groups = {f"G{i:04d}": sid for i, sid in enumerate(source_ids, 1)}
    dropped, out = [], {p: [] for p in ("CO", "SO", "ME")}
    opts = [o for o in dict.fromkeys(inp["modelopt"]) if o not in DROP_MODELOPT]
    dropped += sorted({f"MODELOPT {o}" for o in inp["modelopt"] if o in DROP_MODELOPT})
    if "CONC" not in opts:
        opts.insert(0, "CONC")
    for c in inp["cards"]:
        p, kw, a = c["path"], c["kw"], c["args"]
        if kw in ("STARTING", "FINISHED") or p in ("RE", "OU", "EV"):
            continue
        if p == "CO":
            if kw == "MODELOPT":
                continue
            if kw not in KEEP_CO:
                if kw not in ("AVERTIME", "POLLUTID", "RUNORNOT"):
                    dropped.append(f"CO {kw}")
                continue
            out["CO"].append(f"   {kw:<8}  {' '.join(a)}")
        elif p == "SO":
            if kw not in KEEP_SO:
                if kw != "SRCGROUP":
                    dropped.append(f"SO {kw}")
                continue
            sid = a[0].upper() if a else ""
            if kw == "URBANSRC":
                # The list may name sources left out of this run; AERMOD rejects unknown ids.
                a = [x for x in a if x.upper() not in inp["sources"] or x.upper() in keep]
                if not any(x.upper() in keep or x.upper() == "ALL" or "-" in x for x in a):
                    continue
            elif kw in PER_SOURCE and sid not in keep:
                continue
            if kw == "SRCPARAM":
                s = inp["sources"][sid]
                if s.get("_written"):
                    continue
                s["_written"] = True
                a = [sid, f"{unit_rate(s):.8E}"] + [_fmt(x) for x in s["params"][1:]]
            out["SO"].append(f"   {kw:<8}  {' '.join(a)}")
        elif p == "ME":
            if kw not in KEEP_ME:
                dropped.append(f"ME {kw}")
                continue
            if kw == "SURFFILE":
                a = [sfc_name] + a[1:]
            elif kw == "PROFFILE":
                a = [pfl_name] + a[1:]
            out["ME"].append(f"   {kw:<8}  {' '.join(a)}")
    for s in inp["sources"].values():
        s.pop("_written", None)
    lines = ["CO STARTING", *out["CO"], f"   MODELOPT  {' '.join(opts)}", "   AVERTIME  PERIOD",
             # OTHER switches off the averaging and decay rules AERMOD applies by pollutant
             # name (SO2, NO2, PM2.5), none of which belong to an air toxic.
             "   POLLUTID  OTHER", "   RUNORNOT  RUN", "CO FINISHED", "",
             "SO STARTING", *out["SO"]]
    lines += [f"   SRCGROUP  {g}  {sid}" for g, sid in groups.items()]
    lines += ["   SRCGROUP  ALL", "SO FINISHED", "", "RE STARTING", "   ELEVUNIT  METERS"]
    lines += [receptor_line(r, flat) for r in receptors]
    lines += ["RE FINISHED", "", "ME STARTING", *out["ME"], "ME FINISHED", "", "OU STARTING"]
    lines += [f"   PLOTFILE  PERIOD  {g}  {g.lower()}.plt" for g in list(groups) + ["ALL"]]
    lines += ["OU FINISHED", ""]
    return "\n".join(lines), groups, sorted(set(dropped))


def inventory_text(sources, receptor, met, title, urban_pop=None):
    """Input text for a run built from a stack inventory: flat terrain, no building downwash.

    sources  [{"id", "x", "y", "height_m", "temp_k", "velocity_m_s", "diameter_m"}]
    met      {"sf_id", "ua_id", "year", "profbase_m"}
    """
    groups = {f"G{i:04d}": s["id"] for i, s in enumerate(sources, 1)}
    lines = ["CO STARTING", f"   TITLEONE  {title[:68]}",
             "   MODELOPT  CONC  FLAT", "   AVERTIME  PERIOD", "   POLLUTID  OTHER"]
    if urban_pop:
        lines.append(f"   URBANOPT  {int(urban_pop)}")
    lines += ["   RUNORNOT  RUN", "CO FINISHED", "", "SO STARTING", "   ELEVUNIT  METERS"]
    for g, s in zip(groups, sources):
        lines.append(f"   LOCATION  {g}  POINT  {s['x']:.2f}  {s['y']:.2f}  0.0")
        lines.append(f"   SRCPARAM  {g}  {UNIT_RATE_G_S:.1f}  {s['height_m']:.3f}  {s['temp_k']:.2f}  "
                     f"{s['velocity_m_s']:.3f}  {s['diameter_m']:.3f}")
    if urban_pop:
        lines.append("   URBANSRC  ALL")
    lines += [f"   SRCGROUP  {g}  {g}" for g in groups]
    lines += ["   SRCGROUP  ALL", "SO FINISHED", "", "RE STARTING",
              receptor_line(receptor, True), "RE FINISHED", "", "ME STARTING",
              "   SURFFILE  met.sfc", "   PROFFILE  met.pfl",
              f"   SURFDATA  {met['sf_id']}  {met['year']}", f"   UAIRDATA  {met['ua_id']}  {met['year']}",
              f"   PROFBASE  {met['profbase_m']:.2f}  METERS", "ME FINISHED", "", "OU STARTING"]
    lines += [f"   PLOTFILE  PERIOD  {g}  {g.lower()}.plt" for g in list(groups) + ["ALL"]]
    lines += ["OU FINISHED", ""]
    return "\n".join(lines), groups


def sfc_header(path):
    """Station ids and first year from an AERMET surface file."""
    with open(path, encoding="latin-1") as f:
        head, first = f.readline(), f.readline().split()
    ids = dict(re.findall(r"(UA_ID|SF_ID|OS_ID|VERSION):\s*(\S+)", head))
    if "SF_ID" not in ids or "UA_ID" not in ids or not first:
        raise InputError(f"{path} does not look like an AERMET surface file")
    year = int(first[0])
    # Older AERMET wrote two-digit years.
    year += 0 if year > 99 else 1900 if year >= 50 else 2000
    loc = head.split()[:2]
    return {"sf_id": ids["SF_ID"].lstrip("0") or "0", "ua_id": ids["UA_ID"].lstrip("0") or "0",
            "aermet_version": ids.get("VERSION"), "year": year, "location": " ".join(loc)}


def parse_plt(path):
    """Rows of an AERMOD plot file.

    Returns {"version", "aves", "groups", "rows"}; each row has x, y, conc, zelev, zhill,
    zflag, ave, group. The averaging period is read from the rows themselves, not the file
    name: a 1-hour design-value file must never be taken for an annual average.
    """
    version, rows = None, []
    with open(path, encoding="latin-1") as f:
        for line in f:
            if line.startswith("*"):
                m = re.match(r"\*\s*AERMOD\s*\(\s*(\S+?)\s*\)", line)
                if m:
                    version = m.group(1)
                continue
            t = line.split()
            if len(t) < 8:
                continue
            try:
                v = [float(x) for x in t[:6]]
            except ValueError:
                continue
            rows.append({"x": v[0], "y": v[1], "conc": v[2], "zelev": v[3], "zhill": v[4],
                         "zflag": v[5], "ave": t[6].upper(), "group": t[7].upper(), "text": t[:6]})
    if not rows:
        raise InputError(f"{path} holds no plot-file rows")
    return {"file": path, "version": version, "aves": sorted({r["ave"] for r in rows}),
            "groups": sorted({r["group"] for r in rows}), "rows": rows}


def long_term(plt):
    """True only when every row is a PERIOD or ANNUAL average."""
    return set(plt["aves"]) <= LONG_TERM


def nearest(rows, x, y):
    r = min(rows, key=lambda r: (r["x"] - x) ** 2 + (r["y"] - y) ** 2)
    return r, math.hypot(r["x"] - x, r["y"] - y)


def parse_out(path):
    """Outcome of a run, from the message summary at the end of the main output file.

    AERMOD exits with status 0 whether or not it ran, so this is the only success test. A
    file with no summary means the program stopped before finishing.
    """
    r = {"file": path, "ok": False, "finished": False, "fatal": None, "warnings": None,
         "hours": None, "missing_hours": None, "missing_pct": None, "version": None,
         "units": None, "fatal_messages": [], "problem": None}
    if not os.path.exists(path):
        r["problem"] = "AERMOD wrote no output file"
        return r
    with open(path, encoding="latin-1") as f:
        text = f.read()
    m = re.search(r"\*\*\* AERMOD - VERSION\s+(\S+)", text)
    r["version"] = m.group(1) if m else None
    m = re.search(r"Output Units\s*=\s*(\S+)", text)
    r["units"] = m.group(1) if m else None
    tail = text[text.rfind("*** Message Summary"):] if "*** Message Summary" in text else ""
    for key, pat in (("fatal", r"A Total of\s+(\d+) Fatal Error"), ("warnings", r"A Total of\s+(\d+) Warning"),
                     ("hours", r"A Total of\s+(\d+) Hours Were Processed"),
                     ("missing_hours", r"A Total of\s+(\d+) Missing Hours")):
        m = re.search(pat, tail)
        r[key] = int(m.group(1)) if m else None
    m = re.search(r"Missing Hours Identified \(\s*([\d.]+) Percent\)", tail)
    r["missing_pct"] = float(m.group(1)) if m else None
    m = re.search(r"FATAL ERROR MESSAGES \*+\s*\n(.*?)\n\s*\n\s*\*+\s+WARNING MESSAGES", tail, re.S)
    if m:
        r["fatal_messages"] = [x.strip() for x in m.group(1).splitlines()
                               if x.strip() and "NONE" not in x]
    r["finished"] = "AERMOD Finishes Successfully" in tail
    if not tail:
        r["problem"] = "the output has no message summary: AERMOD stopped before finishing"
    elif r["fatal"]:
        r["problem"] = f"{r['fatal']} fatal error(s): " + "; ".join(r["fatal_messages"][:5])
    elif not r["finished"]:
        r["problem"] = "AERMOD did not report a successful finish"
    elif not r["hours"]:
        r["problem"] = "no hours of meteorology were processed"
    r["ok"] = r["problem"] is None
    return r


def run(run_dir, text, sfc=None, pfl=None, exe=EXE, timeout=3600):
    """Write `text` as run_dir/aermod.inp, run AERMOD there and return parse_out()'s result."""
    if not os.path.exists(exe):
        raise InputError(f"AERMOD is not built ({exe}); run scripts/aermod_build.sh")
    os.makedirs(run_dir, exist_ok=True)
    for src, name in ((sfc, "met.sfc"), (pfl, "met.pfl")):
        if src:
            dst = os.path.join(run_dir, name)
            if os.path.lexists(dst):
                os.remove(dst)
            # AERMOD limits the length of a path in its input, so the file is given a short
            # local name instead of being referred to where it lies.
            shutil.copyfile(src, dst)
    for stale in ("aermod.out",):
        if os.path.exists(os.path.join(run_dir, stale)):
            os.remove(os.path.join(run_dir, stale))
    with open(os.path.join(run_dir, "aermod.inp"), "w", encoding="latin-1") as f:
        f.write(text)
    with open(os.path.join(run_dir, "console.log"), "w") as log:
        try:
            subprocess.run([exe], cwd=run_dir, stdout=log, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            r = parse_out(os.path.join(run_dir, "no-such-file"))
            r["problem"] = f"AERMOD was stopped after {timeout} seconds"
            return r
    return parse_out(os.path.join(run_dir, "aermod.out"))


def group_values(run_dir, groups, receptors):
    """{group: [concentration at each receptor, in receptor order]} from a run's plot files."""
    out = {}
    for g in list(groups) + ["ALL"]:
        plt = parse_plt(os.path.join(run_dir, f"{g.lower()}.plt"))
        if not long_term(plt):
            raise InputError(f"{g}: run produced {plt['aves']}, not a period average")
        vals = []
        for r in receptors:
            row, dist = nearest(plt["rows"], r["x"], r["y"])
            if dist > 0.02:
                raise InputError(f"{g}: no result at receptor {r['x']:.2f}, {r['y']:.2f}")
            vals.append(row["conc"])
        out[g] = vals
    return out


def batches(ids, size=BATCH):
    return [ids[i:i + size] for i in range(0, len(ids), size)]


# ------------------------------------------------------------ coordinates

def utm_zone(lon):
    return int((lon + 180.0) // 6) + 1


def utm(lat, lon, zone):
    """(easting, northing) in metres on GRS80, which serves NAD83 and WGS84 alike here.

    Krueger's series to fourth order: good to well under a millimetre inside a zone. NAD27
    is a different ellipsoid and a grid shift of up to a few hundred metres; it is not
    converted here.
    """
    a, f = 6378137.0, 1 / 298.257222101
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    al = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180,
          13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
          61 * n ** 3 / 240 - 103 * n ** 4 / 140,
          49561 * n ** 4 / 161280)
    phi, lam = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    e = math.sqrt(f * (2 - f))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi, eta = math.atan2(t, math.cos(lam)), math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(c * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, c in enumerate(al, 1))
    y = xi + sum(c * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, c in enumerate(al, 1))
    return 500000.0 + 0.9996 * A * x, 0.9996 * A * y


# ------------------------------------------------------------ EPA's published test cases

TEST_URL = "https://gaftp.epa.gov/Air/aqmg/SCRAM/models/preferred/aermod/aermod_test_cases.zip"
TEST_PREFIX = "aermet26135_aermod26135/"
# The archive is 489 MB; these members are read out of it by byte range (about 15 MB moved).
# Between them the cases cover point, volume, area, polygon, circle, line and open-pit
# sources, building downwash, flat and elevated terrain, an included receptor file, and both
# 1-hour and period plot files.
TEST_CASES = {
    "aertest": {"needs": ["meteorology/aermet2.sfc", "meteorology/aermet2.pfl"],
                "plots": ["AERTEST_01H.PLT"], "summary": "AERTEST.SUM"},
    "allsrcs": {"needs": ["meteorology/aermet2.sfc", "meteorology/aermet2.pfl"],
                "plots": [], "summary": "ALLSRCS.SUM"},
    "flatelev": {"needs": ["inputs/lovett_rec.dat", "meteorology/lovett.sfc", "meteorology/lovett.pfl"],
                 "plots": ["LVTAN_ELEV.PLT", "LVTAN_FLAT.PLT", "FLATELEV_ELEV_STK_01H.PLT",
                           "FLATELEV_FLAT_STK_01H.PLT"], "summary": "FLATELEV.SUM"},
}

# Measured with gfortran 16.1 on arm64: every plot file and every summary line matches EPA's
# to the last printed digit, except nine lines for two RLINEXT sources with the ALPHA barrier
# and depression options, which differ by at most 1.7e-4 of the value. Those source types are
# refused by usable_sources(), so the difference reaches no result.
TEST_TOLERANCE = 5e-4
INEXACT_GROUPS = {"RLINEBA", "RLINEDE"}


def test_members(case):
    c = TEST_CASES[case]
    return ([f"inputs/{case}.inp"] + c["needs"] + [f"plotfiles/{p}" for p in c["plots"]]
            + [f"Outputs/{c['summary']}"])


def summary_values(path):
    """[(source group, line, value)] for every maximum a summary file reports.

    Headers carry the run's date and clock time, so whole files never compare equal; these
    lines hold everything the run computed that the summary reports.
    """
    vals, group = [], None
    with open(path, encoding="latin-1") as f:
        for line in f:
            m = re.search(r"HIGH(?:EST)? VALUE IS\s+([\d.]+)", line)
            if not m:
                continue
            head = line.split()[0]
            # The group is printed only on the first line of its block.
            if not re.match(r"(HIGH|\d+(ST|ND|RD|TH))$", head):
                group = head
            vals.append((group, " ".join(line.split()), float(m.group(1))))
    return vals


def compare_summaries(ours, published):
    """(lines, lines differing, largest relative difference, groups that differ)."""
    a, b = summary_values(ours), summary_values(published)
    if len(a) != len(b):
        return len(b), max(len(a), len(b)), float("inf"), []
    diff = [(x, y) for x, y in zip(a, b) if x[1] != y[1]]
    rel = max((abs(x[2] - y[2]) / y[2] if y[2] else float("inf") for x, y in diff), default=0.0)
    return len(b), len(diff), rel, sorted({y[0] for _, y in diff})


def compare_plots(ours, published):
    """(rows compared, rows differing, largest difference) between two plot files."""
    a, b = parse_plt(ours)["rows"], parse_plt(published)["rows"]
    if len(a) != len(b):
        return len(b), max(len(a), len(b)), float("inf")
    bad = sum(1 for x, y in zip(a, b) if x["text"] != y["text"] or x["ave"] != y["ave"])
    return len(b), bad, max(abs(x["conc"] - y["conc"]) for x, y in zip(a, b))


def run_test_case(case, src, work, exe=EXE):
    """Run one of EPA's cases from files under `src` and compare with EPA's published results.

    Returns {"case", "ok", "run", "plots": [(name, rows, differing, max difference)],
    "summary": compare_summaries() result}.
    """
    c = TEST_CASES[case]
    for d in ("inputs", "meteorology", "Outputs", "plotfiles", "postfiles"):
        # AERMOD stops at setup when a directory named in an output path is missing.
        os.makedirs(os.path.join(work, d), exist_ok=True)
    for m in c["needs"]:
        shutil.copyfile(os.path.join(src, m), os.path.join(work, m))
    with open(os.path.join(src, "inputs", f"{case}.inp"), encoding="latin-1") as f:
        text = f.read()
    res = run(os.path.join(work, "inputs"), text, exe=exe)
    out = {"case": case, "run": res, "plots": [], "summary": None, "ok": False}
    if not res["ok"]:
        return out
    for p in c["plots"]:
        out["plots"].append((p, *compare_plots(os.path.join(work, "plotfiles", p),
                                               os.path.join(src, "plotfiles", p))))
    out["summary"] = compare_summaries(os.path.join(work, "Outputs", c["summary"]),
                                       os.path.join(src, "Outputs", c["summary"]))
    n, _, rel, groups = out["summary"]
    out["ok"] = (bool(n) and rel <= TEST_TOLERANCE and not set(groups) - INEXACT_GROUPS
                 and all(p[2] == 0 for p in out["plots"]))
    return out


def linearity_check(src, work, exe=EXE):
    """Run EPA's AERTEST stack at zero, one and two times the unit rate.

    The whole method rests on concentration being proportional to emission rate once the
    chemistry and background options are stripped, so the claim is tested on the build in
    use. Returns {"ok", "zero", "ratio", "problem"}; ratio is the largest departure of
    (double rate) / (unit rate) from 2 over the receptors.
    """
    inp = parse_inp(os.path.join(src, "inputs", "aertest.inp"))
    ids, _ = usable_sources(inp)
    recs = [{"x": 433.01, "y": -250.0}, {"x": 0.0, "y": 1000.0}, {"x": -175.0, "y": 0.0}]
    text, groups, _ = rerun_text(inp, ids, recs)
    unit, vals = f"{UNIT_RATE_G_S:.8E}", {}
    for label, factor in (("zero", 0.0), ("one", 1.0), ("two", 2.0)):
        d = os.path.join(work, label)
        res = run(d, text.replace(unit, f"{UNIT_RATE_G_S * factor:.8E}"),
                  os.path.join(src, "meteorology", "aermet2.sfc"),
                  os.path.join(src, "meteorology", "aermet2.pfl"), exe=exe)
        if not res["ok"]:
            return {"ok": False, "zero": None, "ratio": None, "problem": f"{label}: {res['problem']}"}
        vals[label] = group_values(d, groups, recs)["ALL"]
    zero = max(abs(v) for v in vals["zero"])
    if min(vals["one"]) <= 0:
        return {"ok": False, "zero": zero, "ratio": None, "problem": "unit-rate run gave no concentration"}
    ratio = max(abs(b / a - 2.0) for a, b in zip(vals["one"], vals["two"]))
    # Each value is printed to five decimals, which bounds how exact the ratio can look.
    tol = max(3e-5 / a for a in vals["one"])
    return {"ok": zero == 0.0 and ratio <= tol, "zero": zero, "ratio": ratio, "problem": None,
            "values": vals}
