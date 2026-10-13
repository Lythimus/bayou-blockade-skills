"""Offline self-check for household-exposure. No network, no AERMOD binary.

The AERMOD checks read EPA sample files vendored in references/aermod-samples/; whether the
local build reproduces EPA's results is a separate, networked check: `hx.py model --check-build`.

  uv run --no-project --with matplotlib python -I selfcheck.py

Exits non-zero if any check fails. The expected figures for the two worked examples are the
hand-calculated ones printed in references/methods.md; a check below fails if that document
stops showing them, so the doc and the code cannot drift apart unnoticed.
"""
import argparse
import datetime as dt
import gzip
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aermod_io as am  # noqa: E402
import airtox  # noqa: E402
import downloads  # noqa: E402
import exposure as ex  # noqa: E402
import hx  # noqa: E402
import rsei  # noqa: E402
import toxvalues  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if not cond:
        FAILS.append(f"{name}: {detail}" if detail else name)


def close(a, b, rel=1e-6):
    return a is not None and math.isclose(a, b, rel_tol=rel, abs_tol=1e-15)


def P(start, end=None):
    return [{"start": start, "end": end}]


AS_OF = "2026-10-11"


def overlap():
    e = ex.exposure({2012: 1.0}, P("2012-01-01", "2012-12-31"), AS_OF)
    check("leap year is one year", close(e["residence_years"], 1.0), e["residence_years"])
    e = ex.exposure({2010: 1.0}, P("2010-07-01", "2010-12-31"), AS_OF)
    check("partial year by days", close(e["residence_years"], 184 / 365), e["residence_years"])
    e = ex.exposure({2011: 1.0, 2012: 1.0}, P("2011", "2012"), AS_OF)
    check("bare years span whole years", close(e["integral"], 2.0), e["integral"])
    twice = [{"start": "2011", "end": "2012"}, {"start": "2012-06-01", "end": "2013"}]
    e = ex.exposure({}, twice, AS_OF)
    check("overlapping periods are not double-counted", close(e["residence_years"], 3.0),
          e["residence_years"])
    e = ex.exposure({}, P("2026-01-01"), AS_OF)
    check("open period closes at as_of", close(e["residence_years"], 284 / 365), e["residence_years"])
    try:
        ex.intervals(P("2012", "2011"), AS_OF)
        check("reversed period rejected", False)
    except ValueError:
        check("reversed period rejected", True)


def windows():
    res, flat = P("2010", "2014"), {y: 2.0 for y in range(2000, 2030)}
    e = ex.exposure(flat, res, AS_OF, window=("2012-07-01", None))
    check("source starts inside residence", close(e["integral"], 2.0 * (184 / 366 + 2)), e["integral"])
    check("pre-start years are known zeros", close(e["evidence_fraction"], 1.0))
    e = ex.exposure(flat, res, AS_OF, window=("2000", "2011-06-30"))
    check("source closes inside residence", close(e["integral"], 2.0 * (1 + 181 / 365)), e["integral"])
    e = ex.exposure(flat, res, AS_OF, window=("2020", "2025"))
    check("source outside residence adds nothing", e["integral"] == 0.0 and e["max_annual"] is None)
    check("source outside residence is evidence, not a gap", close(e["known_years"], 5.0))
    e = ex.exposure(flat, P("2012-01-01", "2012-06-30"), AS_OF, window=("2012-07-01", "2012-12-31"))
    check("same year, disjoint halves", e["integral"] == 0.0, e["integral"])
    check("no exposed time gives no exposed average", e["exposed_average"] is None)
    # Two years at twice a reference value of 1.0 inside a 40-year residence.
    e = ex.exposure(flat, P("1980", "2019"), AS_OF, window=("2000", "2001"))
    check("long residence does not dilute the hazard quotient",
          close(ex.hazard_quotient(e["exposed_average"], 1.0), 2.0) and close(e["period_average"], 0.1),
          (e["exposed_average"], e["period_average"]))
    check("lifetime average still spreads over 70 years", close(e["lifetime_average"], 4.0 / 70))
    e = ex.exposure({2010: 1.0}, P("2010", "2011"), AS_OF)
    check("exposed average ignores unknown years", close(e["exposed_average"], 1.0))


def unknowns():
    res = P("2010", "2012")
    e = ex.exposure({2010: 1.0, 2011: None, 2012: 1.0}, res, AS_OF)
    check("None year excluded from integral", close(e["integral"], 2.0))
    check("None year listed unknown", e["unknown"] == [2011])
    check("evidence fraction drops", close(e["evidence_fraction"], 2 / 3))
    check("average is over known years", close(e["period_average"], 1.0))
    e = ex.exposure({2010: 1.0, 2012: 1.0}, res, AS_OF)
    check("absent year is unknown, not zero", e["unknown"] == [2011] and close(e["known_years"], 2.0))
    e = ex.exposure({2010: 1.0, 2011: 0.0, 2012: 1.0}, res, AS_OF)
    check("reported zero is known", e["unknown"] == [] and close(e["period_average"], 2 / 3))
    e = ex.exposure({}, res, AS_OF)
    check("no evidence gives no average", e["period_average"] is None and e["evidence_fraction"] == 0.0)
    check("no unit risk gives no risk", ex.cancer_risk(e, None) is None)
    check("no reference value gives no quotient", ex.hazard_quotient(1.0, None) is None)
    s, partial = ex.combine([{2010: 1.0, 2011: None}, {2010: 2.0, 2011: 3.0}, {2012: None}])
    check("combine sums known", s == {2010: 3.0, 2011: 3.0, 2012: None}, s)
    check("combine flags partial years", partial == [2010, 2011], partial)


def tox():
    t = toxvalues.load()
    check("tox row count", len(t) == 227, len(t))
    b = toxvalues.lookup(t, "71-43-2")
    check("mg/m3 converted to ug/m3 once", close(b["rfc_ug_m3"], 30.0), b["rfc_ug_m3"])
    check("unit risk untouched", close(b["ure_per_ug_m3"], 7.8e-6))
    check("CAS spellings agree", toxvalues.lookup(t, "0000071432") is b and toxvalues.lookup(t, "71432") is b)
    check("unknown CAS is None", toxvalues.lookup(t, "1-23-4") is None)
    acetamide = toxvalues.lookup(t, "60-35-5")
    check("zero in table means no value", acetamide["rfc_ug_m3"] is None and acetamide["ure_per_ug_m3"] == 2e-5)
    check("mutagenic count", sum(r["mutagenic"] for r in t.values()) == 33)
    check("chloroprene and ethylene oxide flagged",
          toxvalues.lookup(t, "126-99-8")["mutagenic"] and toxvalues.lookup(t, "75-21-8")["mutagenic"])
    vc = toxvalues.lookup(t, "75-01-4")
    check("vinyl chloride not age-adjusted, carries a note", not vc["mutagenic"] and vc["note"])
    tce = toxvalues.lookup(t, "79-01-6")
    whole_life = ex.exposure({y: 1.0 for y in range(1950, 2021)}, P("1950-07-01", "2020-06-30"),
                             AS_OF, birth_year=1950)
    r = ex.cancer_risk(whole_life, tce["ure_per_ug_m3"], tce["mutagenic"], tce["adaf_share"])
    check("TCE lifetime value matches EPA's 4.8e-6", round(r["risk"] * 1e6, 1) == 4.8, r["risk"])
    return t


def methods_text():
    with open(os.path.join(os.path.dirname(HERE), "references", "methods.md"), encoding="utf-8") as f:
        return f.read()


def worked_examples(t):
    doc = methods_text()

    def shown(name, text):
        check(f"methods.md shows {name} = {text}", text in doc)

    # Example 1: benzene, partial first year, one year without evidence.
    benzene = toxvalues.lookup(t, "71-43-2")
    e = ex.exposure({2010: 0.4, 2011: None, 2012: 0.6}, P("2010-07-01", "2012-12-31"), AS_OF)
    r = ex.cancer_risk(e, benzene["ure_per_ug_m3"], benzene["mutagenic"])
    hq = ex.hazard_quotient(e["exposed_average"], benzene["rfc_ug_m3"])
    for name, got, want, text in (
            ("ex1 residence years", e["residence_years"], 2.504110, "2.5041"),
            ("ex1 known years", e["known_years"], 1.504110, "1.5041"),
            ("ex1 evidence fraction", e["evidence_fraction"], 0.600657, "0.601"),
            ("ex1 integral", e["integral"], 0.801644, "0.8016"),
            ("ex1 period average", e["period_average"], 0.532969, "0.5330"),
            ("ex1 risk", r["risk"], 8.9326e-8, "8.93 × 10⁻⁸"),
            ("ex1 hazard quotient", hq, 0.0177656, "0.0178")):
        check(name, close(got, want, rel=2e-5), got)
        shown(name, text)
    check("ex1 not age-adjusted", r["age_adjusted"] is False and r["note"] is None)

    # Example 2: chloroprene from age 6 months to 17.5, crossing both age thresholds.
    chl = toxvalues.lookup(t, "126-99-8")
    series = {y: 0.2 for y in range(2011, 2028)}
    e = ex.exposure(series, P("2011-01-01", "2027-12-31"), AS_OF, birth_year=2010)
    r = ex.cancer_risk(e, chl["ure_per_ug_m3"], chl["mutagenic"], chl["adaf_share"])
    for name, got, want, text in (
            ("ex2 residence years", e["residence_years"], 17.0, "17.0000"),
            ("ex2 integral", e["integral"], 3.4, "3.4000"),
            ("ex2 weighted integral", e["adaf_integral"], 11.694531, "11.6945"),
            ("ex2 unadjusted risk", r["unadjusted_risk"], 1.457143e-5, "1.46 × 10⁻⁵"),
            ("ex2 adjusted risk", r["risk"], 5.011942e-5, "5.01 × 10⁻⁵"),
            ("ex2 hazard quotient", ex.hazard_quotient(e["exposed_average"], chl["rfc_ug_m3"]), 0.01, "0.0100")):
        check(name, close(got, want, rel=2e-5), got)
        shown(name, text)
    no_birth = ex.cancer_risk(ex.exposure(series, P("2011-01-01", "2027-12-31"), AS_OF),
                              chl["ure_per_ug_m3"], chl["mutagenic"])
    check("mutagen without birth year is unadjusted and says so",
          close(no_birth["risk"], 1.457143e-5, rel=2e-5) and not no_birth["age_adjusted"] and no_birth["note"])
    born_later = ex.exposure(series, P("2005", "2012"), AS_OF, birth_year=2010)
    check("time before birth is not exposure", close(born_later["residence_years"], 184 / 365 + 2),
          born_later["residence_years"])


def household_totals():
    rows = [{"cas": "71-43-2", "chemical": "Benzene", "risk": 1e-6, "hq": 0.1},
            {"cas": "126-99-8", "chemical": "Chloroprene", "risk": 2e-6, "hq": 0.2},
            {"cas": "108-88-3", "chemical": "Toluene", "risk": None, "hq": 0.3},
            {"cas": "0", "chemical": "Mystery", "risk": None, "hq": None}]
    tot = ex.totals(rows)
    check("cancer risks add", close(tot["cancer_risk"], 3e-6))
    check("no-value chemicals are listed, not zeroed",
          tot["unquantified_cancer"] == ["Toluene", "Mystery"] and tot["unquantified_noncancer"] == ["Mystery"])
    check("no hazard index without organ data", tot["hazard_index"] is None and tot["hazard_index_reason"])
    tot = ex.totals(rows, {"71-43-2": ["immune"], "126-99-8": ["respiratory"], "108-88-3": ["respiratory", "neurological"]})
    check("hazard index adds within an organ only",
          close(tot["hazard_index"]["respiratory"], 0.5) and close(tot["hazard_index"]["immune"], 0.1)
          and close(tot["hazard_index"]["neurological"], 0.3), tot["hazard_index"])
    check("all-unquantified total is None, not zero", ex.totals(rows[2:])["cancer_risk"] is None)


def assessment():
    check("plugin path refused", hx.inside_plugin(os.path.join(hx.PLUGIN_ROOT, "skills", "x", "out")))
    check("plugin root itself refused", hx.inside_plugin(hx.PLUGIN_ROOT))
    with tempfile.TemporaryDirectory() as tmp:
        check("outside path allowed", not hx.inside_plugin(os.path.join(tmp, "out")))
        link = os.path.join(tmp, "link")
        os.symlink(hx.PLUGIN_ROOT, link)
        check("symlink into plugin refused", hx.inside_plugin(os.path.join(link, "out")))
        m = hx.parse_member("A:1998-03-01..2010-06-30,2015..")
        check("member parsing", m["id"] == "A" and m["residence"][1] == {"start": "2015", "end": None}, m)
        good = {"schema_version": 1, "as_of": AS_OF, "home": {"lat": 30.0, "lon": -90.5},
                "radius_km": 50, "members": [dict(m, birth_year=1990)], "proposed": []}
        today = dt.date(2026, 10, 11)
        err, warn = hx.validate(good, today)
        check("valid assessment passes", not err and not warn, err + warn)
        check("residence span", hx.residence_span(good) == (1998, 2026), hx.residence_span(good))

        def errs(**change):
            return " ".join(hx.validate(dict(good, **change), today)[0])

        check("no members is an error", "member" in errs(members=[]))
        check("radius over 50 km is an error", "radius_km" in errs(radius_km=60))
        check("residence wholly before birth is an error",
              "before birth" in errs(members=[dict(m, birth_year=2020, residence=P("2000", "2010"))]))
        check("name-like member id rejected", "pseudonym" in errs(members=[dict(m, id="Jane Q. Public")]))
        check("proposed facility needs an operating horizon",
              "operating_start" in errs(proposed=[{"name": "X", "dir": tmp}]))
        check("missing birth year warns",
              any("birth year" in w for w in hx.validate(dict(good, members=[m]), today)[1]))
        check("outside Louisiana warns",
              any("Louisiana" in w for w in hx.validate(dict(good, home={"lat": 41.0, "lon": -87.0}), today)[1]))
        # A current resident and a plant that has not started yet.
        plant = {"name": "X", "dir": tmp, "operating_start": 2028, "operating_years": 30}
        child = {"id": "C", "birth_year": 2019, "projected_end": None, "residence": P("2020")}
        future = dict(good, members=[child], proposed=[plant])
        check("proposed scenario requires a projected stay",
              "projected_end is required" in " ".join(hx.validate(future, today)[0]))
        child["projected_end"] = "2020"
        check("projected stay cannot be in the past", "before as_of" in " ".join(hx.validate(future, today)[0]))
        child["projected_end"] = hx.STAY_FOR_HORIZON
        check("projected stay accepted", not hx.validate(future, today)[0], hx.validate(future, today)[0])
        window, flat = hx.operating_window(plant), {y: 1.0 for y in range(2020, 2060)}
        e = ex.exposure(flat, child["residence"], hx.open_end(future, child), birth_year=2019, window=window)
        check("history stops today, so a future plant adds nothing to it", e["integral"] == 0.0)
        e = ex.exposure(flat, child["residence"], hx.open_end(future, child, plant), birth_year=2019, window=window)
        check("projected stay overlaps the operating horizon", close(e["integral"], 30.0), e["integral"])
        check("age factors start at the age the plant starts",
              close(e["adaf_integral"], 3 * (7 + 181 / 365) + 184 / 365 + 22), e["adaf_integral"])
        child["projected_end"] = "2030"
        e = ex.exposure(flat, child["residence"], hx.open_end(future, child, plant), birth_year=2019, window=window)
        check("a dated projected stay ends the exposure", close(e["integral"], 3.0), e["integral"])
        path = hx.write_assessment(os.path.join(tmp, "out"), good)
        check("assessment file is owner-only", os.stat(path).st_mode & 0o077 == 0)
    check("operating window, whole years",
          hx.operating_window({"operating_start": 2028, "operating_years": 30}) == (dt.date(2028, 1, 1), dt.date(2057, 12, 31)))
    check("year ranges", hx.year_ranges([1995, 1990, 1991, 1992]) == "1990-1992, 1995")
    check("50 km in miles", close(50 / hx.KM_PER_MILE, 31.0686, rel=1e-5))


def facilities():
    def f(frs, last, years):
        return {"frs_id": frs, "name": f"plant {last}", "lat": 30.0, "lon": -90.0,
                "distance_km": 1.0, "years": set(years), "last_year": last}

    facs = {"OLD": f("110000001", 1999, range(1990, 2000)), "NEW": f("110000001", 2020, range(2000, 2021)),
            "LONE": f("", 2005, [2005]), "RENAMED": f("", 1995, [1994, 1995])}
    out = hx.collapse(facs)
    check("shared FRS ID collapses to the newest TRI ID",
          set(out) == {"NEW", "LONE", "RENAMED"} and out["NEW"]["also"] == ["OLD"], sorted(out))
    check("collapsed years are the union", out["NEW"]["years"] == set(range(1990, 2021)))
    out = hx.collapse(facs, {"RENAMED": "LONE"})
    check("alias collapses unlinked IDs", set(out) == {"NEW", "LONE"} and out["LONE"]["years"] == {1994, 1995, 2005},
          sorted(out))
    out = hx.collapse(facs, {"RENAMED": "NEW"})
    check("alias onto an FRS-linked plant joins its group",
          set(out) == {"NEW", "LONE"} and out["NEW"]["also"] == ["OLD", "RENAMED"], out.get("NEW", {}).get("also"))
    check("blank FRS IDs do not merge with each other", "LONE" in hx.collapse(facs) and "RENAMED" in hx.collapse(facs))


def download_gate():
    plan = downloads.rsei_plan(1986, 2023)
    by = {i["what"].split()[1]: i for i in plan}
    check("years outside RSEI are stated, not fetched", by["1986"]["bytes"] == 0 and by["2023"]["bytes"] == 0)
    check("state file for 1988-2014", "state/la/v234_micro_state_la_2014" in by["2014"]["url"])
    check("2020 comes from the current version only", by["2020"]["version"] == "v2.3.12")
    check("2015-2017 pinned to one version", {by[y]["version"] for y in ("2015", "2016", "2017")} == {"v2.3.7"})
    check("national years are sized in the tens of GB", by["2016"]["bytes"] >= 20 * downloads.GB)
    check("every year maps to exactly one version",
          all(sum(a <= y <= b for a, b, *_ in downloads.RSEI_SOURCES) == 1
              for y in range(downloads.RSEI_FIRST, downloads.RSEI_LAST + 1)))
    check("AirToxScreen alone trips the gate", downloads.airtox_plan()[0]["bytes"] >= downloads.THRESHOLD)
    quiet = open(os.devnull, "w")
    old, sys.stdout = sys.stdout, quiet
    try:
        with tempfile.TemporaryDirectory() as tmp:
            check("large download refused without --yes", downloads.gate(plan, tmp, False, "t") is False)
            check("large streamed download allowed with --yes", downloads.gate(plan, tmp, True, "t") is True)
            too_big = [{"what": "x", "bytes": 10 ** 18, "stored": True, "note": ""}]
            check("download that cannot fit is refused even with --yes", downloads.gate(too_big, tmp, True, "t") is False)
            small = downloads.tri_plan(2020, 2022, ["LA"])
            check("small download needs no confirmation", downloads.gate(small, tmp, False, "t") is True)
            check("cached TRI files are not re-counted", len(downloads.tri_plan(2020, 2022, ["LA"], {(2021, "LA")})) == 2)
            check("TRI plan starts at 1987", len(downloads.tri_plan(1980, 1988, ["LA"])) == 2)
    finally:
        sys.stdout = old
        quiet.close()


def chunked(data, n):
    return [data[i:i + n] for i in range(0, len(data), n)]


# Rows in the two layouts EPA has used. The home cell in these fixtures is 650,976.
OLD_LAYOUT = (b"14,650,976,1,51,100,1,1.0E-03,2.0E+00,0,0,0,0\n"      # benzene, fugitive
              b"14,650,976,2,51,100,2,2.0E-03,4.0E+00,0,0,0,0\n"      # benzene, stack
              b"14,651,976,2,51,100,2,5.0E-03,1.0E+01,0,0,0,0\n"      # neighbor cell
              b"14,6500,976,3,51,100,1,9.9E+00,0,0,0,0,0\n"           # X only shares a prefix
              b"24,650,976,4,51,100,1,9.9E+00,0,0,0,0,0\n"            # Alaska grid
              b"14,650,9760,5,51,100,1,9.9E+00,0,0,0,0,0\n"           # Y only shares a prefix
              b"14,900,900,6,51,100,1,9.9E+00,0,0,0,0,0\n"            # elsewhere
              b"14,650,976,7,153,100,2,1.0E-02,0,0,0,0,0\n"           # chromium compounds
              b"14,650,976,8,347,100,2,1.0E-04,0,0,0,0,0\n"           # lead compounds
              b"14,650,976,9,346,100,2,2.0E-04,0,0,0,0,0\n"           # lead
              b"14,650,976,10,51,7,750,4.0E-04,0,0,0,0,0")            # off-site incinerator, no newline
NEW_LAYOUT = (b"Year,GridCode,X,Y,ReleaseNumber,ChemicalNumber,FacilityNumber,Media,Conc,ToxConc,Score,CConc,NCConc,Pop\n"
              b"2022,14,650,976,1,51,100,1,1.5E-03,0,0,0,0,0\n"
              b"2022,24,650,976,1,51,100,1,9.9E+00,0,0,0,0,0\n"
              b"2022,14,650,977,1,51,100,1,2.5E-03,0,0,0,0,0\n")
TABLES = {
    "chemical": {"51": {"id": "71432", "name": "Benzene"},
                 "153": {"id": "N090", "name": "Chromium compounds"},
                 "347": {"id": "N420", "name": "Lead compounds"},
                 "346": {"id": "7439921", "name": "Lead"},
                 "999": {"id": "N590", "name": "Polycyclic aromatic compounds"}},
    "facility": {"100": {"trifid": "70084PLANT1", "frs_id": "1", "name": "Plant One", "city": "Reserve",
                         "state": "LA", "lat": 30.05, "lon": -90.54},
                 "7": {"trifid": "WRONGPLANT", "frs_id": "2", "name": "Wrong Plant", "city": "X",
                       "state": "LA", "lat": 30.0, "lon": -90.0}},
    "offsite": {"7": {"name": "Incinerator Seven", "city": "Y", "state": "LA", "lat": 30.1, "lon": -90.6}},
}


def screening(t):
    home = (30.0569, -90.5226)
    check("grid cell of a known Louisiana facility", rsei.cell(30.05073, -90.53908) == (649, 975))
    check("grid cell of a known Mississippi facility", rsei.cell(33.39955, -91.067216) == (562, 1432))
    check("grid cell of the test point", rsei.cell(30.0569, -90.5226) == (651, 976))
    try:
        rsei.cell(18.38, -67.18)
        check("Puerto Rico is refused, not mapped onto the mainland grid", False)
    except ValueError:
        check("Puerto Rico is refused, not mapped onto the mainland grid", True)
    # The fixtures below sit in the cell one west of the test point.
    home = (30.0569, -90.5290)
    check("fixture home is in the fixture cell", rsei.cell(*home) == (650, 976), rsei.cell(*home))
    check("nine cells in a neighborhood", len(set(rsei.neighborhood((650, 976)))) == 9)

    check("13 columns: no header, no year", rsei.layout(OLD_LAYOUT.split(b"\n")[0]) == (False, False))
    check("header row detected", rsei.layout(NEW_LAYOUT.split(b"\n")[0]) == (True, True))
    check("14 columns of data: year first", rsei.layout(NEW_LAYOUT.split(b"\n")[1]) == (False, True))
    try:
        rsei.layout(b"1,2,3")
        check("unknown layout is an error", False)
    except ValueError:
        check("unknown layout is an error", True)

    cells = rsei.neighborhood((650, 976))
    whole = rsei.scan([OLD_LAYOUT], cells, 2014)
    check("only the neighborhood's rows are kept", len(whole) == 7, len(whole))
    check("look-alike coordinates are not matched", all(r["conc"] < 1 for r in whole))
    check("a last line with no newline is kept", any(r["media"] == 750 for r in whole))
    for n in (1, 7, 64):
        check(f"rows survive {n}-byte chunks", rsei.scan(chunked(OLD_LAYOUT, n), cells, 2014) == whole)
    new = rsei.scan(chunked(NEW_LAYOUT, 13), cells, 2022)
    check("year-first layout parsed", [r["conc"] for r in new] == [1.5e-3, 2.5e-3], new)
    check("a file for another year matches nothing", rsei.scan([NEW_LAYOUT], cells, 2021) == [])

    gz = gzip.compress(OLD_LAYOUT)
    check("gzip stream in small chunks", b"".join(rsei.gunzip(chunked(gz, 11))) == OLD_LAYOUT)
    check("gzip members laid end to end", b"".join(rsei.gunzip(chunked(gz + gz, 50))) == OLD_LAYOUT * 2)
    try:
        b"".join(rsei.gunzip([gz[:-20]]))
        check("a cut-off download is an error, not a short year", False)
    except OSError:
        check("a cut-off download is an error, not a short year", True)

    with tempfile.TemporaryDirectory() as tmp:
        item = {"version": "v2.3.4", "year": 2014, "url": "https://example.invalid/f_2014.csv.gz"}
        local = os.path.join(tmp, "in")
        os.makedirs(local)
        with open(os.path.join(local, "f_2014.csv.gz"), "wb") as f:
            f.write(gz)
        raw = os.path.join(tmp, "raw")
        check("year not on hand before reading", not rsei.have_year(item, (650, 976), raw))
        check("a supplied file counts as on hand", rsei.have_year(item, (650, 976), raw, local))
        got = rsei.fetch_year(item, (650, 976), raw, local)
        os.remove(os.path.join(local, "f_2014.csv.gz"))
        check("filtered rows are cached and reread", rsei.fetch_year(item, (650, 976), raw) == got == whole)
        check("another cell does not reuse the cache", not rsei.have_year(item, (651, 976), raw))

    ann = rsei.annual(whole, (650, 976))
    b = ann[("facility", "100", "51")]
    check("fugitive and stack releases add", close(b["conc"], 3e-3), b)
    check("neighborhood range", close(b["hi"], 5e-3) and b["lo"] == 0.0, b)
    check("incinerator rows are kept apart from the facility table", ("offsite", "7", "51") in ann)

    catmap = toxvalues.load_category_map()
    check("every mapped category points at a Table 1 row",
          all(toxvalues.lookup(t, m["cas"]) for m in catmap.values()))
    rec, key, basis, _ = toxvalues.resolve(t, catmap, "N420")
    check("lead compounds resolve to the lead row", key == "7439921" and rec["rfc_ug_m3"] and basis == "direct")
    check("TRI's zero-padded ids resolve", toxvalues.resolve(t, catmap, "0000071432")[1] == "71432")
    check("PAH category has no single value", toxvalues.resolve(t, catmap, "N590")[0] is None)
    cr6 = toxvalues.resolve(t, catmap, "N090")
    check("chromium takes the chromium (VI) row, flagged as an assumption",
          cr6[1] == "18540299" and cr6[2] == "assumed" and "ASSUMPTION" in cr6[3])
    organs = toxvalues.load_organs()
    check("target organs loaded", organs.get("126998") == ["resp"] and len(organs) > 100, len(organs))
    check("organ names cover every code", {o for v in organs.values() for o in v} <= set(toxvalues.ORGAN_NAMES))

    # 2014 has every row above; 2013 was read and has only benzene from the plant.
    y2013 = rsei.scan([b"14,650,976,1,51,100,1,2.0E-03,0,0,0,0,0\n"], cells, 2013)
    by_year = {2014: whole, 2013: y2013, 2012: []}
    versions = {2012: "v2.3.4", 2013: "v2.3.4", 2014: "v2.3.4"}
    filed = {2013: {("70084PLANT1", "7439921"): 0.0, ("70084PLANT1", "18540299"): 12.0}}
    pairs, sources, chems = hx.build_series(by_year, {"v2.3.4": TABLES}, versions, home, t, catmap, filed)
    check("facility identified by TRI id", "70084PLANT1" in sources and sources["70084PLANT1"]["distance_km"] < 3)
    check("incinerator named from the off-site table, not the facility table",
          sources.get("offsite:Incinerator Seven", {}).get("name") == "Incinerator Seven" and "WRONGPLANT" not in sources)
    cr = pairs[("70084PLANT1", "18540299")]
    check("RSEI's chromium figure is used as it stands", close(cr[2014]["conc"], 1e-2), cr[2014])
    pb = pairs[("70084PLANT1", "7439921")]
    check("lead and lead compounds add on one row", close(pb[2014]["conc"], 3e-4), pb[2014])
    check("filed with no air release: known zero", pb[2013]["conc"] == 0.0 and pb[2013]["status"] == "zero_reported")
    check("filed an air release RSEI did not model: unknown",
          cr[2013]["conc"] is None and cr[2013]["status"] == "reported_not_modeled")
    check("no filing on hand: unknown, not zero", pb[2012]["conc"] is None and pb[2012]["status"] == "no_report")
    bz = pairs[("70084PLANT1", "71432")]
    check("benzene series", close(bz[2014]["conc"], 3e-3) and close(bz[2013]["conc"], 2e-3) and bz[2012]["conc"] is None)

    a = {"as_of": AS_OF}
    member = {"id": "A", "birth_year": None, "residence": P("2012", "2014")}
    res = hx.member_results(a, member, pairs, chems, organs)
    rows = {r["cas"]: r for r in res["rows"]}
    integral = 2e-3 + 3e-3 + 4e-4
    check("sources of one chemical add", close(rows["71432"]["integral_ug_m3_yr"], integral), rows["71432"])
    check("risk from the summed series", close(rows["71432"]["risk"], t["71432"]["ure_per_ug_m3"] * integral / 70))
    check("unread year stays unknown", rows["71432"]["unknown_years"] == [2012])
    check("year where one source has no figure is partial", rows["71432"]["partial_years"] == [2013])
    check("largest contributor listed first", next(iter(rows["71432"]["by_source_integral"])) == "70084PLANT1")
    check("hazard quotient averages exposed time", close(rows["71432"]["hq"], integral / 2 / t["71432"]["rfc_ug_m3"]))
    check("hazard index grouped by organ", res["totals"]["hazard_index"] and
          all(o in toxvalues.ORGAN_NAMES for o in res["totals"]["hazard_index"]), res["totals"])
    check("total risk sums the quantified chemicals",
          close(res["totals"]["cancer_risk"], sum(r["risk"] for r in res["rows"] if r["risk"] is not None)))
    away = {"id": "B", "birth_year": None, "residence": P("2012", "2012")}
    check("member with no read year gets no rows", hx.member_results(a, away, pairs, chems, organs)["rows"] == [])

    with tempfile.TemporaryDirectory() as tmp:
        cols = {"2": "70084PLANT1", "39": "N420", "49": "R", "51": "0", "52": "0"}
        head = ",".join(f"{k}. X" for k in cols)
        lines = [head, ",".join(cols.values()), "70084PLANT1,0000071432,R,5,7", "70084PLANT1,0000071432,A,,"]
        with open(os.path.join(tmp, "2013_LA.csv"), "w") as f:
            f.write("\n".join(lines) + "\n")
        rep = hx.tri_air_reports(tmp, [2012, 2013], ["LA"], t, catmap)
        check("year without a cached TRI file is left out", 2012 not in rep)
        check("zero-air filing recorded under the Table 1 key", rep[2013][("70084PLANT1", "7439921")] == 0.0)
        check("air pounds summed; Form A ignored", rep[2013][("70084PLANT1", "71432")] == 12.0)
        check("needing a second state's file leaves the year out",
              hx.tri_air_reports(tmp, [2013], ["LA", "MS"], t, catmap) == {})

    check("--years range", hx.parse_years("2010-2014") == (2010, 2014) and hx.parse_years("2012") == (2012, 2012))

    strings = ["State", "Block", "Population", "Total Cancer Risk (per million)",
               "PT-StationaryPoint Cancer Risk (per million)", "BACKGROUND Cancer Risk (per million)",
               "LA", "220950708001001", "220950708001002"]
    def row(n, block, vals):
        cells_xml = f'<c r="A{n}" s="2" t="s"><v>6</v></c><c r="E{n}" s="2" t="s"><v>{block}</v></c>'
        cells_xml += "".join(f'<c r="{c}{n}" s="2"><v>{v}</v></c>' for c, v in zip("FGHI", vals))
        return f'<row r="{n}" spans="1:9">{cells_xml}</row>'
    header = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="E1" t="s"><v>1</v></c><c r="F1" t="s"><v>2</v></c>'
              '<c r="G1" t="s"><v>3</v></c><c r="H1" t="s"><v>4</v></c><c r="I1" t="s"><v>5</v></c></row>')
    # Population 8 in the first row: a numeric cell equal to the wanted string index.
    xml = ("<worksheet><sheetData>" + header + row(2, 7, (8, 50.0, 30.0, 0)) + row(3, 8, (120, 61.5, 41.25, 0))
           + "</sheetData></worksheet>").encode()
    for n in (len(xml), 37, 200):
        h, r = airtox.find_row(chunked(xml, n), 8)
        rec = airtox.record(airtox.parse_cells(h, strings), airtox.parse_cells(r, strings), "u") if r else {}
        check(f"block row found in {n}-byte chunks", rec.get("block") == "220950708001002" and rec.get("total_per_million") == 61.5, rec)
    check("source groups listed, zero groups dropped", rec["by_source_per_million"] == {"PT-StationaryPoint": 41.25})
    check("absent block gives no row", airtox.find_row(chunked(xml, 64), 99)[1] is None)
    check("shared strings parsed", airtox.shared_strings(b"<sst><si><t>a &amp; b</t></si><si><r><t>c</t></r><r><t>d</t></r></si></sst>") == ["a & b", "cd"])


SAMPLES = os.path.join(os.path.dirname(HERE), "references", "aermod-samples")


def write(d, name, text):
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


SYNTHETIC_INP = """CO STARTING
   TITLEONE applicant run
   MODELOPT DFAULT CONC OLM
   AVERTIME 1 ANNUAL
   POLLUTID NO2
   OZONEFIL C:\\met\\ozone.dat
   SAVEFILE /etc/overwrite.me
   RUNORNOT RUN
CO FINISHED
SO STARTING
   LOCATION S1 POINT 100. 200. 3.0
   LOCATION s2 AREA 0. 0. 0.
   location P1 AREAPOLY 0. 0. 0.
   LOCATION C1 AREACIRC 0. 0. 0.
   LOCATION L1 LINE 300. 800. 900. 200. 0.
   LOCATION O1 OPENPIT 0. 0. 0.
   LOCATION H1 POINT 5. 5. 0.
   LOCATION R1 RLINEXT 0. 0. 1. 0. 50. 1. 0.
   SRCPARAM S1 2.5 30. 400. 10. 1.5
SO SRCPARAM S2 1.0D-3 1. 20. 10.
   SRCPARAM P1 0.001 1. 8
   AREAVERT P1 0.0 0.0 10.0 0.0 10.0 10.0 0.0 10.0 0.0 20.0
   AREAVERT P1 -10.0 20.0 -10.0 10.0 -10.0 0.0
   SRCPARAM C1 0.1 10. 20.
   SRCPARAM L1 0.001 1. 20.
   SRCPARAM O1 1.0E-5 0. 1829. 183. 0.1674E+08
   SRCPARAM H1 1. 10. 300. 1. 1.
   SRCPARAM R1 1. 0. 3.6 2.
   HOUREMIS hourly.dat H1
   EMISFACT S1 SEASON 1. 1. 1. 1.
   BACKGRND ANNUAL 12.
   URBANSRC S1 H1
   SRCGROUP ALL
SO FINISHED
RE STARTING
   DISCCART 1000. 0.
RE FINISHED
ME STARTING
   SURFFILE "C:\\met files\\site.sfc" FREE
   PROFFILE site.pfl
   SURFDATA 12916 2018
   UAIRDATA 3937 2018
   PROFBASE 3.0 METERS
ME FINISHED
OU STARTING
   PLOTFILE ANNUAL ALL ../../escape.plt
   POSTFILE 1 ALL PLOT /tmp/escape.pst
OU FINISHED
"""

OUT_OK = """ *** AERMOD - VERSION 26135  ***   *** test ***
                 Output Units   = MICROGRAMS/M**3
 *** Message Summary : AERMOD Model Execution ***
 A Total of            0 Fatal Error Message(s)
 A Total of            5 Warning Message(s)
 A Total of         8784 Hours Were Processed
 A Total of          161 Missing Hours Identified (  1.83 Percent)
    ******** FATAL ERROR MESSAGES ********
               ***  NONE  ***

    ********   WARNING MESSAGES   ********
 CO W361      15       COCARD: something
    *** AERMOD Finishes Successfully ***
"""
OUT_FATAL = OUT_OK.replace("0 Fatal", "2 Fatal").replace(
    "               ***  NONE  ***", " MX E510       1       METDAT: Fatal Error Occurs During Reading").replace(
    "Finishes Successfully", "Finishes UN-successfully")


def aermod_files():
    """Parsers and the rerun writer against EPA's sample files and a synthetic applicant input."""
    inp = am.parse_inp(os.path.join(SAMPLES, "aertest.inp"))
    s = inp["sources"].get("STACK1", {})
    check("pathway carried from the line above", s.get("type") == "POINT" and s.get("params") == [500.0, 65.0, 425.0, 15.0, 5.0], s)
    check("comment lines skipped", inp["title"].startswith("A Simple Example"), inp["title"])
    check("flat terrain recognized", am.is_flat(inp))
    check("filed outputs seen", [kw for kw, _ in inp["outputs"]] == ["RECTABLE", "MAXTABLE", "SUMMFILE", "PLOTFILE", "POSTFILE"])
    lov = am.parse_inp(os.path.join(SAMPLES, "flatelev.inp"))
    check("INCLUDED receptor file read", len(lov["receptors"]) == 11 and close(lov["receptors"][0]["zelev"], 237.48), lov["receptors"][:1])
    check("FLAT with ELEV is elevated terrain", not am.is_flat(lov))

    plt = am.parse_plt(os.path.join(SAMPLES, "AERTEST_01H.PLT"))
    check("1-hour plot file parsed", len(plt["rows"]) == 144 and plt["aves"] == ["1-HR"] and plt["version"] == "26135", plt["aves"])
    check("1-hour plot file is not a long-term average", not am.long_term(plt))
    values, context, gaps = hx.path_applicant_output([{"cas": "71-43-2", "plt": plt}], (30.0, 172.0), 100.0,
                                                     toxvalues.load(), toxvalues.load_category_map())
    check("1-hour output rejected as annual concentration", values == {} and context[0]["used"] is False
          and "1-HR" in gaps[0], gaps)
    per = am.parse_plt(os.path.join(SAMPLES, "LVTAN_ELEV.PLT"))
    check("period plot file accepted", am.long_term(per) and per["groups"] == ["ELEV_STK"] and len(per["rows"]) == 11)
    row, dist = am.nearest(per["rows"], 4800.0, 70750.0)
    check("nearest receptor and its distance", close(row["conc"], 3.14146) and close(dist, math.hypot(20, 50)), (row, dist))
    tox, cm = toxvalues.load(), toxvalues.load_category_map()
    values, context, gaps = hx.path_applicant_output([{"cas": "71-43-2", "plt": per}], (4800.0, 70750.0), 100.0, tox, cm)
    check("period value read at the nearest receptor", close(values["71432"]["conc"], 3.14146) and not gaps, values)
    values, context, gaps = hx.path_applicant_output([{"cas": "71-43-2", "plt": per}], (4800.0, 70950.0), 100.0, tox, cm)
    check("far receptor is not the home", values == {} and "beyond" in gaps[0], gaps)

    with tempfile.TemporaryDirectory() as d:
        case = os.path.join(d, "case")
        os.makedirs(case)
        inp = am.parse_inp(write(case, "a.inp", SYNTHETIC_INP))
        src = inp["sources"]
        check("keywords and ids are case-insensitive", "S2" in src and "P1" in src, list(src))
        check("Fortran D exponent read", close(src["S2"]["params"][0], 1e-3))
        check("area: rectangle", close(am.source_area(src["S2"]), 200.0))
        check("area: polygon from AREAVERT", close(am.source_area(src["P1"]), 300.0), am.source_area(src["P1"]))
        check("area: circle", close(am.source_area(src["C1"]), math.pi * 400))
        check("area: line is length x width", close(am.source_area(src["L1"]), math.hypot(600, 600) * 20))
        check("area: open pit", close(am.source_area(src["O1"]), 1829.0 * 183.0))
        check("point rate is the unit rate", am.unit_rate(src["S1"]) == am.UNIT_RATE_G_S)
        check("area rate is the unit rate per m2", close(am.unit_rate(src["S2"]), am.UNIT_RATE_G_S / 200))
        check("filed total rate for an area source", close(am.filed_rate_g_s(src["S2"]), 0.2))
        ids, refused = am.usable_sources(inp)
        check("hourly-emission source refused", "HOUREMIS" in refused.get("H1", ""), refused)
        check("unhandled source type refused", "RLINEXT" in refused.get("R1", ""), refused)
        check("other sources usable", ids == ["S1", "S2", "P1", "C1", "L1", "O1"], ids)
        text, groups, dropped = am.rerun_text(inp, ids, [{"x": 1.0, "y": 2.0, "zelev": 3.0, "zhill": 4.0}])
        check("rerun writes nowhere the applicant chose", not any(x in text for x in ("escape", "/etc/", "/tmp/", "..", "SAVEFILE")), text)
        check("rerun is a period run of an unnamed pollutant", "AVERTIME  PERIOD" in text and "POLLUTID  OTHER" in text
              and "NO2" not in text and "ANNUAL" not in text.replace("PERIOD", ""))
        check("chemistry and background stripped", not any(x in text for x in ("OLM", "OZONEFIL", "BACKGRND", "HOUREMIS", "EMISFACT")))
        check("stripped keywords reported", {"MODELOPT OLM", "CO OZONEFIL", "CO SAVEFILE", "SO BACKGRND", "SO EMISFACT"} <= set(dropped), dropped)
        check("refused sources left out", " H1 " not in text and " R1 " not in text and "URBANSRC  S1" in text, text)
        check("one group per source plus ALL", len(groups) == 6 and text.count("SRCGROUP") == 7 and text.count("PLOTFILE") == 7)
        check("met files given local names", "SURFFILE  met.sfc FREE" in text and "PROFFILE  met.pfl" in text)
        check("elevated receptor carries terrain", "DISCCART  1.00  2.00  3.00  4.00" in text)
        check("background noted", inp["background"] and inp["emisfact"] == {"S1"})
        for name, body, word in (("out.inp", "RE STARTING\n   INCLUDED ../outside.dat\nRE FINISHED\n", "outside"),
                                 ("gone.inp", "RE STARTING\n   INCLUDED missing.dat\nRE FINISHED\n", "not supplied")):
            write(d, "outside.dat", "   DISCCART 0. 0.\n")
            try:
                am.parse_inp(write(case, name, body))
                check(f"INCLUDED {word} refused", False)
            except am.InputError as e:
                check(f"INCLUDED {word} refused", word in str(e), e)
        ok = am.parse_out(write(d, "ok.out", OUT_OK))
        check("finished run read", ok["ok"] and ok["hours"] == 8784 and ok["missing_pct"] == 1.83 and ok["units"] == "MICROGRAMS/M**3", ok)
        bad = am.parse_out(write(d, "bad.out", OUT_FATAL))
        check("fatal error is a failure whatever the exit code", not bad["ok"] and bad["fatal"] == 2 and "E510" in bad["problem"], bad)
        cut = am.parse_out(write(d, "cut.out", OUT_OK.split(" *** Message")[0]))
        check("output with no summary is a failure", not cut["ok"] and "summary" in cut["problem"])
        check("missing output is a failure", not am.parse_out(os.path.join(d, "none.out"))["ok"])
        h = am.sfc_header(write(d, "m.sfc", "   29.993N   90.251W          UA_ID: 00003937  SF_ID: 12916     OS_ID:              VERSION: 23132\n18  1  1   1  1   -9.1\n"))
        check("surface file header", h["sf_id"] == "12916" and h["ua_id"] == "3937" and h["year"] == 2018, h)

    e, n = am.utm(43.642567, -79.387139, 17)
    check("UTM of a published point", abs(e - 630084) < 1 and abs(n - 4833438) < 1, (e, n))
    e, n = am.utm(0.0, -93.0, 15)
    check("UTM central meridian", close(e, 500000.0) and abs(n) < 1e-6, (e, n))
    check("UTM zones either side of 90 W", am.utm_zone(-90.38) == 15 and am.utm_zone(-89.9) == 16)
    check("batches bound open files", [len(b) for b in am.batches(list(range(320)))] == [150, 150, 20])


def model_inputs():
    """Emission and inventory tables: units, citations and refusals."""
    v, _ = hx.to_g_s(1.0, "tpy", None)
    check("1 ton per year in g/s", close(v, 2000 * 453.59237 / (8760 * 3600)), v)
    v, _ = hx.to_g_s(2.0, "lb/hr", 4000.0)
    check("lb/hr uses stated hours once", close(v, 8000 * 453.59237 / (8760 * 3600)), v)
    check("g/s passes through", hx.to_g_s(0.5, "g/s", None)[0] == 0.5)
    check("unknown unit gives no rate", hx.to_g_s(1.0, "furlongs", None)[0] is None)
    tox, cm = toxvalues.load(), toxvalues.load_category_map()
    head = ",".join(hx.EMISSION_COLUMNS) + "\n"
    with tempfile.TemporaryDirectory() as d:
        rows, problems = hx.load_emissions(write(d, "e.csv", head
            + "<same ID>,Benzene,71-43-2,0.00,tpy,,PTE,,new,<file>,<page>,no\n"
            + "ep-1,Benzene,71-43-2,10,tpy,,PTE,,new,app.pdf,12,yes\n"
            + "EP-1,Benzene,71-43-2,4,tpy,,allowable,,removed,app.pdf,12,no\n"
            + "EP-1,Toluene,108-88-3,1,tpy,,expected,,new,app.pdf,12,no\n"
            + "EP-1,Toluene,108-88-3,1,tpy,,expected,3000 h/yr,new,app.pdf,12,no\n"
            + "EP-1,Xylene,1330-20-7,1,tpy,,PTE,,new,,,no\n"
            + "EP-1,Xylene,1330-20-7,1,tpy,,guess,,new,app.pdf,3,no\n"), tox, cm)
        check("blank hours on an hourly rate is recorded as full-year",
              "assumes continuous operation" in hx.load_emissions(write(d, "h.csv", head
                  + "EP-1,Benzene,71-43-2,2,lb/hr,,PTE,,new,app.pdf,12,no\n"), tox, cm)[0][0]["conversion"])
        check("template placeholder row ignored", len(rows) == 3, len(rows))
        check("source ids upper-cased", rows[0]["source"] == "EP-1" and rows[0]["key"] == "71432")
        check("removed equipment is negative", rows[1]["sign"] == -1.0 and rows[1]["scenario"] == "permitted")
        check("expected rate needs its assumption", rows[2]["scenario"] == "expected" and any("assumption" in p for p in problems), problems)
        check("uncited rate refused", any("no source document" in p for p in problems), problems)
        check("unknown basis refused", any("'guess'" in p for p in problems), problems)
        head = ",".join(hx.INVENTORY_COLUMNS) + "\n"
        inv, problems, seen = hx.load_inventory(write(d, "i.csv", head
            + "EP-1,stack,,,15,752123.45,3317901.42,NAD83,114.8294,ft,7.87402,ft,317.93,F,38.38583,ft/s,app.pdf,5,no\n"
            + "EP-2,stack,29.9647,-90.3840,,,,,35,m,2.4,m,432,K,11.7,m/s,app.pdf,5,no\n"
            + "EP-3,stack,,,15,752123.45,3317901.42,NAD27,35,m,2.4,m,432,K,11.7,m/s,app.pdf,5,no\n"
            + "EP-4,stack,29.9647,-90.3840,,,,,,m,2.4,m,432,,11.7,m/s,,,no\n"), 15)
        s = inv[0]
        check("English stack units converted", close(s["height_m"], 35.0, 1e-5) and close(s["diameter_m"], 2.4, 1e-5)
              and close(s["temp_k"], 432.0, 1e-4) and close(s["velocity_m_s"], 11.7, 1e-5), s)
        check("lat/lon stack projected to the home's zone", len(inv) == 2 and abs(inv[1]["x"] - 752440.66) < 0.01, inv[1:])
        check("NAD27 stack refused", any("EP-3" in p and "datum" in p for p in problems), problems)
        check("missing stack parameters named, not filled", any("EP-4" in p and "height" in p and "temp" in p and "source_doc" in p for p in problems), problems)
        check("every inventory id reported", seen == {"EP-1", "EP-2", "EP-3", "EP-4"})
        # flatelev.inp pulls its receptors from lovett_rec.dat with INCLUDED.
        shutil.copy(os.path.join(SAMPLES, "flatelev.inp"), d)
        inp, why, ask = hx.read_applicant_inp(os.path.join(d, "flatelev.inp"))
        check("input missing an included file is a gap, not a stop",
              inp is None and "lovett_rec.dat" in why and "INCLUDED" in ask, (why, ask))
        shutil.copy(os.path.join(SAMPLES, "lovett_rec.dat"), d)
        inp, why, ask = hx.read_applicant_inp(os.path.join(d, "flatelev.inp"))
        check("complete input parses", inp is not None and why is None and ask is None, why)
        unit = "CO STARTING\nCO FINISHED\nSO STARTING\n" + "".join(
            f"   LOCATION {i} POINT 0. 0. 0.\n   SRCPARAM {i} 1.0 30. 400. 10. 1.5\n" for i in ("A", "B")) + "SO FINISHED\n"
        check("every source at one rate is a unit-rate filing",
              "same emission rate" in (hx.unit_rate_filing(am.parse_inp(write(d, "unit.inp", unit))) or ""))
        one = unit.replace("   LOCATION B POINT 0. 0. 0.\n   SRCPARAM B 1.0 30. 400. 10. 1.5\n", "")
        check("a single source at 1 g/s is a unit-rate filing",
              "1 g/s" in (hx.unit_rate_filing(am.parse_inp(write(d, "one.inp", one))) or ""))
        check("sources at different rates are not a unit-rate filing",
              hx.unit_rate_filing(am.parse_inp(write(d, "two.inp", unit.replace("B 1.0 30.", "B 0.2 30.")))) is None)
        check("a single source at its own rate is not",
              hx.unit_rate_filing(am.parse_inp(write(d, "own.inp", one.replace(" 1.0 30.", " 0.37 30.")))) is None)
        grams = am.parse_out(write(d, "g.out", OUT_OK.replace("MICROGRAMS/M**3", "GRAMS/M**3")))
        check("filed output units are read, not assumed", grams["units"] == "GRAMS/M**3"
              and am.parse_out(os.path.join(d, "ok2.out"))["units"] is None, grams["units"])
        check("met files absent gives none", hx.find_met(argparse.Namespace(sfc=None, pfl=None), inp) is None)
        sfc, pfl = write(d, "lovett.sfc", "x\n"), write(d, "lovett.pfl", "x\n")
        check("met files beside the input are found by name",
              hx.find_met(argparse.Namespace(sfc=None, pfl=None), inp) == (sfc, pfl))
        for label, ns in (("half a met pair refused", argparse.Namespace(sfc=sfc, pfl=None)),
                          ("mistyped met path refused", argparse.Namespace(sfc=sfc, pfl=os.path.join(d, "no.pfl")))):
            try:
                hx.find_met(ns, inp)
                check(label, False)
            except SystemExit as e:
                check(label, "--sfc" in str(e) or "not found" in str(e), e)


def reporting(t):
    """report.py: one results dict, and a public one that cannot locate the home."""
    import json
    import re
    import report
    check("two significant figures, plain decimals", (report.num(0.000012345), report.num(123456.0), report.num(3.14159))
          == ("0.000012", "120,000", "3.1"), (report.num(0.000012345), report.num(123456.0)))
    check("tiny risk is 'under', never a rounded zero", report.per_million(4e-10) == "under 0.001")
    check("year ranges", report.years_text([1990, 1991, 1992, 1995]) == "1990-1992, 1995")
    a = {"label": "Fixture label", "as_of": "2020-12-31",
         "home": {"lat": 29.123456, "lon": -90.654321, "address": "77 Fixture Rd"},
         "members": [{"id": "A", "birth_year": 1987, "projected_end": "operating_end",
                      "residence": [{"start": "2013-03-01", "end": None}]}],
         "proposed": [{"name": "Fixture plant"}]}

    def row(cas, chem, risk, hq, shares):
        return {"cas": cas, "chemical": chem, "note": None, "residence_years": 7.84, "evidence_fraction": 1 / 7.84,
                "unknown_years": [2013], "partial_years": [], "integral_ug_m3_yr": 0.0123456,
                "exposed_average_ug_m3": 0.0123456, "max_annual_ug_m3": 0.0123456, "risk": risk,
                "unadjusted_risk": risk, "age_adjusted": False, "hq": hq, "hq_max_year": hq,
                "by_source_integral": shares}
    rows = [row("75218", "Ethylene oxide", 3.123456e-06, 0.000861234, {"F1": 3.0, "F2": 1.0}),
            row("7440020", "Nickel compounds", None, 0.0231234, {"F2": 1.0}),
            row("999999", "Made-up chemical", None, None, {"F1": 1.0}),
            row("N150", "Dioxin and dioxin-like compounds", None, None, {"F1": 1.0})]
    scr = {"tier": "screening", "grid_cell": {"grid": 14, "x": 7771, "y": 8882, "size_m": 810.0},
           "years": {"residence": [2013, 2020], "read": [2014], "outside_rsei_coverage": [],
                     "not_requested": [2013, 2015, 2016, 2017, 2018, 2019, 2020], "tri_filings_checked": []},
           "model_versions": {"v2.3.4": "2014"}, "gaps": [],
           "sources": {"F1": {"kind": "TRI facility", "name": "FIXTURE ONE LLC", "city": "TAFT", "state": "LA",
                              "lat": 29.9, "lon": -90.4, "distance_km": 3.37},
                       "F2": {"kind": "TRI facility", "name": "FIXTURE TWO", "city": "NORCO", "state": "LA",
                              "lat": 29.8, "lon": -90.3, "distance_km": 12.91},
                       "F3": {"kind": "TRI facility", "name": "NEVER MENTIONED INC", "city": "X", "state": "LA",
                              "lat": 29.7, "lon": -90.2, "distance_km": 48.77}},
           "chemicals": {"75218": {"note": None, "target_organs": ["neuro"]},
                         "7440020": {"note": None, "target_organs": ["immune"]},
                         "999999": {"note": None, "target_organs": None},
                         "N150": {"note": None, "target_organs": None}},
           "members": {"A": {"rows": rows, "totals": ex.totals(rows, {"75218": ["neuro"], "7440020": ["immune"]})}},
           "airtoxscreen": {"year": 2020, "block": "220890623022001", "state": "LA", "county": "St. Charles",
                            "total_per_million": 50.0, "by_source_per_million": {"PT-StationaryPoint": 16.3276, "SECONDARY": 20.7782},
                            "block_source": "geocoder"},
           "limitations": [rsei.LIMITATION], "provenance": {"rsei": {}}}
    prow = {"cas": "71432", "chemical": "Benzene", "risk": 1.23456e-06, "age_adjusted": False, "hq": 0.01234,
            "integral_ug_m3_yr": 1.23456, "exposed_average_ug_m3": 0.123456, "note": None}
    mod = {"proposed": {"name": "Fixture plant", "operating_start": "2028-01-01", "operating_end": "2057-12-31"},
           "dispersion_path": "applicant input, rerun",
           "home_in_model_coordinates": {"x": 123456.7, "y": 7654321.9},
           "sources": {"S1": {"type": "POINT", "distance_km": 1.04, "ug_m3_per_g_s": 0.00179252}},
           "scenarios": {"permitted": {
               "chemicals": {"71432": {"chemical": "Benzene", "conc_ug_m3": 0.123456, "path": "applicant output",
                                       "rate_g_s": 0.4027, "rerun_conc_ug_m3": 0.0007194,
                                       "notes": ["applicant's period result for source group S1 at a "
                                                 "receptor 54 m from the home (FILED.PLT)"],
                                       "by_source_ug_m3": {"S1": 0.0007194}},
                             "108883": {"chemical": "Toluene", "conc_ug_m3": None, "path": None, "rate_g_s": 0.03,
                                        "rerun_conc_ug_m3": None, "notes": [], "by_source_ug_m3": {}}},
               "members": {"A": {"rows": [prow], "totals": ex.totals([prow], {"71432": ["immune"]})}}}},
           "applicant_files": [{"file": "FILED.PLT", "averaging": ["PERIOD"], "used": True,
                                "nearest_receptor_m": 54.3, "aermod_version": "26135"}],
           "checks": [{"file": "FILED.PLT", "group": "S1", "filed": 3.14146, "rerun": 3.141456, "ratio": 0.99999}],
           "runs": [{"dir": "/somewhere/run-01", "sources": 1, "hours": 8784,
                                                          "missing_pct": 1.83}],
           "assumptions": ["given with --home-xy in the model's own coordinates",
                           "terrain height at the home taken from the applicant's receptor 54 m away (324.8 m)"],
           "stays": {"A": "2057-12-31"}, "gaps": ["Toluene (permitted): no dispersion result for S9; no number given",
                                               "OTHER.PLT: the nearest filed receptor is 1332 m from the home, "
                                               "beyond the 100 m allowed; not used",
                                               "Benzene: the applicant's own result at the home is 3.14 ug/m3, but "
                                               "source-emissions.csv rates times the rerun give 0.00657; the rates "
                                               "entered do not match what the applicant modeled"],
           "records_to_request": [], "limitations": hx.MODEL_LIMITATIONS,
           "provenance": {"aermod": {"version": "v26135", "build": None, "applicant_version": None}}}
    screen_rows = [{"chemical": "Ethylene oxide", "cas_or_id": "75218", "source_id": "F1", "source": "FIXTURE ONE LLC",
                    "distance_km": "3.37", "year": "2014", "rsei_version": "v2.3.4", "conc_ug_m3": "0.00925926",
                    "conc_min_3x3": "0.00811111", "conc_max_3x3": "0.0133333", "status": "modeled"},
                   {"chemical": "Ethylene oxide", "cas_or_id": "75218", "source_id": "F2", "source": "FIXTURE TWO",
                    "distance_km": "12.91", "year": "2014", "rsei_version": "v2.3.4", "conc_ug_m3": "",
                    "conc_min_3x3": "", "conc_max_3x3": "", "status": "no_report"}]

    r = report.build(a, scr, mod, False, t)
    m = r["history"]["members"]["A"]
    md = report.render_md(r)
    check("partial coverage is flagged a floor", m["is_floor"] and "**This is a floor.**" in md)
    check("years with no figure are listed as unknown, not zero",
          [y["status"] for y in m["years"]].count("figure") == 1 and len(m["years"]) == 8, m["years"])
    check("source shares of the cancer figure add up to it",
          close(sum(f["cancer_risk"] for f in m["facilities"]), m["cancer_risk"]))
    check("no unit risk is told apart from not in EPA's table",
          m["no_value"]["no_unit_risk"] == ["Nickel compounds"] and m["no_value"]["not_in_epa_table"] == ["Made-up chemical"],
          m["no_value"])
    check("a TRI group is not called absent from EPA's table",
          m["no_value"]["reported_as_a_group"] == ["Dioxin and dioxin-like compounds"]
          and "most potent carcinogens" in md, m["no_value"])
    check("private report keeps the receptor distance and the filed value", "54 m from the home" in md and "3.141" in md)
    check("nickel is named as a carcinogen missing from the sum", "Nickel compounds are a known human carcinogen" in md)
    check("past and proposed are not summed", report.NOT_COMBINED in md and "combined" not in json.dumps(r))
    check("applicant result and entered rates shown when they disagree",
          r["proposed"]["scenarios"]["permitted"]["chemicals"][0]["disagrees"] and "rate × rerun gives" in md)
    check("a chemical with no dispersion result prints no number", "| Toluene | **no number**" in md)
    for text in (rsei.LIMITATION, report.OWN_CELL, report.AIRTOX_ROUNDING, report.LAC_5112, "Drinking water",
                 "not a probability", "modeled outdoor concentration at the home"):
        check(f"report carries: {text[:40]}", text in md)
    check("private report states the home", "29.123456" in md and "7771,8882" in md)

    pub = report.build(a, scr, mod, True, t)
    everything = "\n".join([json.dumps(pub), report.render_md(pub), report.exposure_rows(pub, screen_rows, mod)])
    for secret in ("29.123456", "90.654321", "77 Fixture", "Fixture label", "220890623022001", "7771", "8882",
                   "3.37", "12.91", "48.77", "123456.7", "7654321.9", "324.8", "1987", "NEVER MENTIONED",
                   "Never Mentioned", "1.04", "0.00179", "/somewhere", "0.0081", "0.0133", "2013-03-01",
                   "54 m", "54.3", "3.14", "1332", "0.00657", "16.3", "20.7", "SECONDARY", "StationaryPoint", "home_fraction",
                   "0.83", "0.84"):
        check(f"public report omits {secret}", secret not in everything)
    check("public report keeps the census tract", "22089062302" in everything)
    check("public report says a filed-receptor value was used", report.PUBLIC_PATH_1.strip() in everything)
    check("public report keeps the cross-check ratio", "ratio 1.000" in everything)
    check("public figures carry two significant digits at most",
          not re.search(r"\d\.\d{2,}e|[1-9]\.\d{2,}\d*(?=[,\s}])", json.dumps(pub["history"]["members"]["A"]["chemicals"])),
          json.dumps(pub["history"]["members"]["A"]["chemicals"])[:200])
    check("public exposure.csv sums over sources and flags a floor",
          ",all reported sources,,2014,0.0093,,,floor" in report.exposure_rows(pub, screen_rows, mod))
    with tempfile.TemporaryDirectory() as d:
        for name in ("assessment.json", "screening.json"):
            write(d, name, "{}")
        names = [i["file"] for i in report.manifest(pub, d, scr, mod, [], d)["inputs"]]
        check("public manifest hashes nothing computed from the home", names == [], names)
        names = [i["file"] for i in report.manifest(r, d, scr, mod, [], d)["inputs"]]
        check("private manifest hashes the assessment", "assessment.json" in names, names)

    gone = dict(mod, dispersion_path=None, scenarios={"permitted": {
        "chemicals": {"108883": mod["scenarios"]["permitted"]["chemicals"]["108883"]},
        "members": {"A": {"rows": [], "totals": ex.totals([], {})}}}})
    md = report.render_md(report.build(a, None, gone, False, t))
    check("a model with only gaps reports no figure", "**no figure.**" in md and "**No concentration and no exposure figure.**" in md)
    check("a step that was not run is named", "Not run, so absent from this report: screen" in md)


def main():
    overlap()
    windows()
    unknowns()
    t = tox()
    worked_examples(t)
    household_totals()
    assessment()
    facilities()
    download_gate()
    screening(t)
    aermod_files()
    model_inputs()
    reporting(t)
    if FAILS:
        print(f"{len(FAILS)} of {COUNT[0]} checks FAILED")
        for f in FAILS:
            print("  " + f)
        sys.exit(1)
    print(f"{COUNT[0]} checks passed")


if __name__ == "__main__":
    main()
