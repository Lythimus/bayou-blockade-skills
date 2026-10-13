"""Exposure arithmetic for household-exposure. Pure functions, standard library only.

Inputs are annual-average outdoor concentrations at the home (ug/m3) keyed by calendar year,
and the dates a household member lived there. Nothing here fetches data or knows where a
concentration came from. Formulas and two worked examples: references/methods.md.

A concentration of None means "no evidence for that year". It is never treated as zero and
never filled from a neighboring year; it only lowers the evidence fraction.
"""
import datetime as dt

LIFETIME_YEARS = 70.0

# EPA 2005 Supplemental Guidance: (age from, age to, factor). Age 16 and over is 1.
ADAF_BANDS = ((0, 2, 10.0), (2, 16, 3.0))

# Only a birth year is collected, so the birthday is unknown to within a year. Mid-year
# keeps the error under six months in either direction.
BIRTH_MONTH_DAY = (7, 1)


def parse_date(s, end=False):
    """ISO date, or a bare year meaning Jan 1 (or Dec 31 when it closes a period)."""
    if isinstance(s, dt.date):
        return s
    s = str(s).strip()
    if len(s) == 4 and s.isdigit():
        return dt.date(int(s), 12, 31) if end else dt.date(int(s), 1, 1)
    return dt.date.fromisoformat(s)


def intervals(periods, open_end):
    """Residence periods as merged half-open [start, end) date pairs.

    `end` in a period is the last day lived there, so one day is added. A missing end means
    still living there; `open_end` (a date, inclusive) closes it.
    """
    out = []
    for p in periods:
        start = parse_date(p["start"])
        last = parse_date(p["end"], end=True) if p.get("end") else parse_date(open_end, end=True)
        if last < start:
            raise ValueError(f"residence period ends before it starts: {p}")
        out.append((start, last + dt.timedelta(days=1)))
    out.sort()
    merged = []
    for s, e in out:
        # Overlapping entries for one person would double-count the shared days.
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def clip(ivals, lo=None, hi=None):
    out = []
    for s, e in ivals:
        s2 = max(s, lo) if lo else s
        e2 = min(e, hi) if hi else e
        if s2 < e2:
            out.append((s2, e2))
    return out


def days(ivals):
    return sum((e - s).days for s, e in ivals)


def birth_date(birth_year):
    return dt.date(int(birth_year), *BIRTH_MONTH_DAY)


def age_bands(birth_year):
    """[(from date, to date or None, factor)] covering birth onward."""
    b = birth_date(birth_year)
    out = [(b.replace(year=b.year + lo), b.replace(year=b.year + hi), f) for lo, hi, f in ADAF_BANDS]
    out.append((out[-1][1], None, 1.0))
    return out


def exposure(series, periods, open_end, birth_year=None, window=None):
    """Integrate one concentration series over one member's residence.

    series   {year: ug/m3 or None}. A residence year missing from it is unknown.
    window   (start, end) dates, end inclusive or None: when the source operates. Use it for
             a constant modeled concentration that applies only while the source runs; time
             at home outside the window is a known zero. Leave it None for a series whose
             annual values already reflect start-up and closure (RSEI).

    Years are counted as the fraction of each calendar year, by days, so a leap year is
    366 days and still one year.
    """
    res = intervals(periods, open_end)
    bands = None
    if birth_year is not None:
        bands = age_bands(birth_year)
        # Nobody is exposed before they are born; a household-wide period may start earlier.
        res = clip(res, lo=bands[0][0])
    if window:
        w_lo = parse_date(window[0])
        w_hi = parse_date(window[1], end=True) + dt.timedelta(days=1) if window[1] else None
    out = {"residence_years": 0.0, "known_years": 0.0, "exposed_years": 0.0, "integral": 0.0,
           "adaf_integral": 0.0 if bands else None, "max_annual": None,
           "unknown": [], "by_year": []}
    if not res:
        return _finish(out)
    for year in range(res[0][0].year, res[-1][1].year + 1):
        y_lo, y_hi = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        n = (y_hi - y_lo).days
        at_home = clip(res, y_lo, y_hi)
        if not at_home:
            continue
        exposed = clip(at_home, w_lo, w_hi) if window else at_home
        home_f, exp_f = days(at_home) / n, days(exposed) / n
        conc = series.get(year)
        row = {"year": year, "home_fraction": home_f, "exposed_fraction": exp_f, "conc": conc}
        out["residence_years"] += home_f
        if conc is None and exp_f > 0:
            out["known_years"] += home_f - exp_f
            out["unknown"].append(year)
        else:
            out["known_years"] += home_f
            c = conc or 0.0
            out["integral"] += c * exp_f
            out["exposed_years"] += exp_f
            if exp_f > 0:
                out["max_annual"] = c if out["max_annual"] is None else max(out["max_annual"], c)
            if bands:
                weighted = sum(days(clip(exposed, lo, hi)) * f for lo, hi, f in bands) / n
                row["adaf_fraction"] = weighted
                out["adaf_integral"] += c * weighted
        out["by_year"].append(row)
    return _finish(out)


def _finish(out):
    ry, ky = out["residence_years"], out["known_years"]
    out["evidence_fraction"] = ky / ry if ry else None
    # Averaged over the years with evidence, not over the whole residence: dividing by all
    # residence years would count every unknown year as clean air.
    out["period_average"] = out["integral"] / ky if ky else None
    # Averaged over the time the source was running. A hazard quotient built on the whole
    # residence would let decades before a plant opened dilute a real exceedance; cancer
    # risk is the opposite and is rightly spread over a lifetime.
    out["exposed_average"] = out["integral"] / out["exposed_years"] if out["exposed_years"] else None
    out["lifetime_average"] = out["integral"] / LIFETIME_YEARS
    return out


def cancer_risk(exp, ure, mutagenic=False, adaf_share=1.0):
    """Lifetime excess cancer risk from the years with evidence.

    ure         unit risk, per ug/m3, or None.
    adaf_share  fraction of the unit risk the age factors apply to (trichloroethylene:
                kidney share only).
    Returns None when there is no unit risk. Unknown years add nothing, so with an evidence
    fraction below 1 the figure is a floor, not an estimate of the whole residence.
    """
    if ure is None:
        return None
    base = ure * exp["integral"] / LIFETIME_YEARS
    out = {"risk": base, "unadjusted_risk": base, "age_adjusted": False, "note": None}
    if mutagenic:
        if exp["adaf_integral"] is None:
            out["note"] = ("mutagenic mode of action; no birth year given, so early-life "
                           "factors were not applied and risk for anyone under 16 is understated")
        else:
            extra = exp["adaf_integral"] - exp["integral"]
            out["risk"] = ure * (exp["integral"] + adaf_share * extra) / LIFETIME_YEARS
            out["age_adjusted"] = True
    return out


def hazard_quotient(conc, rfc):
    """Concentration over reference concentration, both ug/m3. A ratio, not a probability."""
    if conc is None or rfc is None:
        return None
    return conc / rfc


def combine(series_list):
    """Sum several sources' series for one chemical. Returns (series, partial_years).

    A year is None only when no source has a value. When some do and some do not, the sum of
    the known ones is kept and the year is listed as partial: a floor, not a total.
    """
    total, partial = {}, []
    for year in sorted({y for s in series_list for y in s}):
        vals = [s.get(year) for s in series_list]
        known = [v for v in vals if v is not None]
        total[year] = sum(known) if known else None
        if known and len(known) < len(vals):
            partial.append(year)
    return total, partial


def totals(rows, organs=None):
    """Household totals over per-chemical rows for one member.

    rows    [{"cas", "chemical", "risk": float or None, "hq": float or None}]
    organs  {cas: [target organ, ...]} or None.
    Chemicals of unlike toxicity are never added by mass. Cancer risks add (EPA's default
    for screening); hazard quotients add only within a target organ.
    """
    quantified = [r for r in rows if r.get("risk") is not None]
    out = {
        "cancer_risk": sum(r["risk"] for r in quantified) if quantified else None,
        "cancer_chemicals": len(quantified),
        "unquantified_cancer": [r["chemical"] for r in rows if r.get("risk") is None],
        "unquantified_noncancer": [r["chemical"] for r in rows if r.get("hq") is None],
        "hazard_index": None,
        "hazard_index_reason": None,
    }
    if not organs:
        out["hazard_index_reason"] = "no target-organ assignments loaded"
        return out
    hi, unassigned = {}, []
    for r in rows:
        if r.get("hq") is None:
            continue
        targets = organs.get(r["cas"])
        if not targets:
            unassigned.append(r["chemical"])
            continue
        for organ in targets:
            hi[organ] = hi.get(organ, 0.0) + r["hq"]
    out["hazard_index"] = hi
    out["hazard_index_unassigned"] = unassigned
    return out
