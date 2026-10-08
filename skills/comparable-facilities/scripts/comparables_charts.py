"""Charts and REPORT.md for a comparables.py run.

Usage: comparables_charts.py OUT [--proposed <permit-analysis dir | proposed-emissions.csv>]
                                 [--hours N] [--formats social,print]

Reads OUT/summary.json and, if present, OUT/capacities.csv
(registry_id,capacity,unit,product,source_url,retrieved). Chart styling, presets, and the
proposed-layer unit conversion come from tri-release-report so the two skills' images match.
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tri-release-report", "scripts"))
import proposed_emissions as pe  # noqa: E402
from tri_charts import (BASELINE, INK2, PRESETS, PROPOSED_FILL, PROPOSED_HATCH,  # noqa: E402
                        PROPOSED_LABEL, SLOT, SURFACE, bar_height, canvas, chart_list, fmt,
                        hbar_layout, legend, plt, save, short_name, table, wrap)

sys.path.insert(0, HERE)
from comparables import CAPS, KEY_HAPS, LB_TO_T  # noqa: E402

PEER = BASELINE
TARGET = SLOT[0]
MEDIAN = INK2

# Proposed-row name -> pollutant key used in summary.json. Order matters: PM2.5 before PM10
# before bare "PM", which is ambiguous and stays unmapped.
PROPOSED_MAP = [
    (re.compile(r"\b(nox|nitrogen oxides?|nitrogen dioxide|no2)\b", re.I), "NOx"),
    (re.compile(r"\b(so2|sulfur dioxide|sulphur dioxide)\b", re.I), "SO2"),
    (re.compile(r"\b(co|carbon monoxide)\b(?!2)", re.I), "CO"),
    (re.compile(r"\b(vocs?|volatile organic( compounds?)?)\b", re.I), "VOC"),
    (re.compile(r"pm\s*-?\s*2\.5", re.I), "PM2.5"),
    (re.compile(r"pm\s*-?\s*10\b", re.I), "PM10"),
    (re.compile(r"\b(nh3|ammonia)\b", re.I), "NH3"),
    (re.compile(r"\b(co2e|ghgs?|greenhouse gas(es)?)\b", re.I), "CO2e"),
]
# Key HAPs by CAS, so a permit's "Benzene (71-43-2)" lands on the NEI name.
HAP_CAS = {"71432": "Benzene", "106990": "1,3-Butadiene", "75218": "Ethylene oxide", "126998": "Chloroprene",
           "50000": "Formaldehyde", "7647010": "Hydrochloric acid", "7783064": "Hydrogen sulfide",
           "108883": "Toluene", "1330207": "Xylene", "100414": "Ethylbenzene", "110543": "Hexane",
           "91203": "Naphthalene", "75070": "Acetaldehyde", "107028": "Acrolein", "67561": "Methanol",
           "100425": "Styrene", "98828": "Cumene", "75014": "Vinyl chloride", "107062": "1,2-Dichloroethane"}
UNITS = {"NOx": "tpy", "SO2": "tpy", "CO": "tpy", "VOC": "tpy", "PM2.5": "tpy", "PM10": "tpy",
         "NH3": "tpy", "Lead": "lb/yr", "CO2e": "t CO2e/yr"}
CHART_ORDER = ["NOx", "SO2", "VOC", "PM2.5", "CO", "CO2e"]
FULL = {"NOx": "Nitrogen oxides (NOx)", "SO2": "Sulfur dioxide (SO2)", "VOC": "Volatile organic compounds",
        "PM2.5": "Fine particulate matter (PM2.5)", "CO": "Carbon monoxide", "CO2e": "Greenhouse gases",
        "PM10": "PM10", "NH3": "Ammonia", "Lead": "Lead"}


# ---------------------------------------------------------------- values

def value(f, pol):
    """Display units: criteria pollutants in short tons/yr, lead and HAPs in lb/yr, GHG in t CO2e."""
    if pol == "CO2e":
        return f.get("ghg_t_co2e")
    if pol in UNITS:
        v = (f.get("cap_lb") or {}).get(pol)
        if v is None:
            return None
        return v if pol == "Lead" else v / 2000
    return (f.get("hap_lb") or {}).get(pol)


def unit(pol):
    return UNITS.get(pol, "lb/yr")


def year_of(f, pol):
    return f.get("ghg_year") if pol == "CO2e" else f.get("nei_year")


def load_capacities(out, facs):
    path = os.path.join(out, "capacities.csv")
    if not os.path.exists(path):
        return {}
    idx = {r: i for i, f in enumerate(facs) for r in f["registry_ids"]}
    caps = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            i = idx.get((r.get("registry_id") or "").strip())
            try:
                c = float((r.get("capacity") or "").replace(",", ""))
            except ValueError:
                continue
            if i is not None and c > 0:
                caps[i] = {"capacity": c, "unit": (r.get("unit") or "").strip(),
                           "product": (r.get("product") or "").strip(),
                           "source_url": (r.get("source_url") or "").strip(),
                           "retrieved": (r.get("retrieved") or "").strip()}
    return caps


def load_proposed(path, hours, target):
    path = pe.resolve_path(path)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in pe.COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"{path} is missing columns: {', '.join(missing)}")
        raw = [r for r in reader if any((v or "").strip() for v in r.values())]
    known_haps = {h.lower(): h for h in list((target.get("hap_lb") or {})) + KEY_HAPS}
    known_tri = {t.lower(): t for t in (target.get("tri_air_lb") or {})}
    rows = []
    for r in raw:
        name, cas = r["chemical"].strip(), r["cas"].strip()
        try:
            amount = float(r["amount"].replace(",", ""))
        except ValueError:
            amount = None
        lb, layer, note = pe.convert(amount, r["unit"], hours) if amount is not None else (None, None, "amount not numeric")
        pol = None
        for rx, k in PROPOSED_MAP:
            if rx.search(name):
                pol = k
                break
        if not pol and re.search(r"\b(co2|carbon dioxide)\b", name, re.I):
            pol = "CO2e"
        if not pol:
            pol = HAP_CAS.get(pe.norm_id(cas)) or known_haps.get(name.lower()) or known_tri.get(name.lower())
        if layer is None:
            bucket, v = "unconvertible", None
        elif layer == "g":
            bucket, v = "grams", None
        elif not pol:
            bucket, v = "unmatched", None
        elif pol == "CO2e":
            # Permit GHG limits are usually short tons; the NEI/GHGRP side is metric tonnes.
            bucket, v = "mapped", lb * LB_TO_T
        elif pol in UNITS and pol != "Lead":
            bucket, v = "mapped", lb / 2000
        else:
            bucket, v = "mapped", lb
        rows.append({"chemical": name, "cas": cas, "amount": amount, "unit": r["unit"].strip(),
                     "basis": r["basis"].strip(), "source_doc": r["source_doc"].strip(),
                     "page": r["page"].strip(),
                     "ocr_verified": r["ocr_verified"].strip().lower() in ("yes", "y", "true", "1"),
                     "pollutant": pol, "bucket": bucket, "value": v, "conversion": note})
    by = {}
    for r in rows:
        if r["bucket"] == "mapped":
            by[r["pollutant"]] = by.get(r["pollutant"], 0.0) + r["value"]
    return {"path": os.path.abspath(path), "hours": hours, "rows": rows, "by_pollutant": by}


# ---------------------------------------------------------------- comparison

def compare(target, peers, prop, caps):
    pols = [lbl for lbl, _ in CAPS] + ["CO2e"]
    haps = [h for h in KEY_HAPS if value(target, h) is not None]
    haps += sorted(k for k in (prop or {}).get("by_pollutant", {}) if k not in pols and k not in haps)
    out = []
    for pol in pols + haps:
        tv = value(target, pol)
        pv = [value(p, pol) for p in peers]
        have = [v for v in pv if v is not None]
        prop_v = (prop or {}).get("by_pollutant", {}).get(pol)
        if tv is None and prop_v is None:
            continue
        med = statistics.median(have) if have else None
        row = {"pollutant": pol, "unit": unit(pol), "target": tv, "peers": pv, "n_peers": len(have),
               "median": med, "proposed": prop_v,
               "ratio": tv / med if tv is not None and med else None,
               "proposed_ratio": prop_v / med if prop_v is not None and med else None}
        # Intensity per tonne CO2e: a crude normalization for size that shares the proxy's circularity.
        tc = target.get("ghg_t_co2e")
        if pol != "CO2e" and tv is not None and tc:
            ints = [v / p["ghg_t_co2e"] for v, p in zip(pv, peers) if v is not None and p.get("ghg_t_co2e")]
            if ints:
                row["intensity_ratio"] = (tv / tc) / statistics.median(ints)
        # Per capacity unit only when the target and at least one peer report the same unit.
        if 0 in caps and tv is not None:
            u = caps[0]["unit"].lower()
            ints = [v / caps[i + 1]["capacity"] for i, v in enumerate(pv)
                    if v is not None and (i + 1) in caps and caps[i + 1]["unit"].lower() == u]
            if ints:
                row["capacity_ratio"] = (tv / caps[0]["capacity"]) / statistics.median(ints)
        out.append(row)
    return out


def label(f, preset, year):
    n = 32 if preset != "print" else 52
    loc = ", ".join(x for x in (short_name(f.get("city") or "", 20), f.get("state")) if x)
    return f"{short_name(f['name'], n)} — {loc}" + (f" ({year})" if year else "")


def axis_fmt(x, _=None):
    # tri_charts.compact rounds 1,200 and 1,400 both to "1K"; criteria tpy often sit in that range.
    a = abs(x)
    if a >= 1e6:
        return f"{x / 1e6:g}M"
    if a >= 1e3:
        return f"{x / 1e3:g}K"
    return f"{x:g}"


def ratio_text(r):
    return f"{r:.1f}×" if r >= 0.95 else f"{r:.2f}×"


# ---------------------------------------------------------------- charts

def charts(d, cmp_rows, prop, out, presets):
    e = d["emissions"]
    t = e["target"]
    peers = e["shortlist"]
    nei_year, ghg_year = e["nei_year"], e["ghg_year"]
    codes = ", ".join([f"SIC {c}" for c in d["candidates"]["sic"]] + [f"NAICS {c}" for c in d["candidates"]["ncs"]])
    paths = []
    # A plant several times its peers' size emits more of everything for that reason alone, so
    # every hero line carries the size gap; the per-t-CO2e column in the report separates the two.
    sizes = [p["size"] for p in peers if p.get("size") and p["size_source"] == t["size_source"]]
    gap = t["size"] / statistics.median(sizes) if sizes and t.get("size") else None
    gap_txt = (f" This plant is {ratio_text(gap)} the median peer's size ({t['size_source']})."
               if gap and not 2 / 3 <= gap <= 1.5 else "")
    by = {r["pollutant"]: r for r in cmp_rows}
    keys = [k for k in CHART_ORDER if k in by and by[k]["n_peers"]]
    # Key HAPs where the target stands out most against its peers.
    haps = sorted((r for r in cmp_rows if r["pollutant"] not in UNITS and r["pollutant"] != "CO2e"
                   and r["n_peers"] and (r["ratio"] or r["proposed_ratio"])),
                  key=lambda r: -(r["ratio"] or r["proposed_ratio"] or 0))[:2]
    keys += [r["pollutant"] for r in haps]
    for pol in keys:
        r = by[pol]
        is_ghg = pol == "CO2e"
        yr = ghg_year if is_ghg else nei_year
        src_name = "EPA GHGRP" if is_ghg else "EPA National Emissions Inventory"
        for preset in presets:
            items = [(label(t, preset, None) + "  (this permit)", r["target"], "target")] if r["target"] is not None else []
            if r["proposed"] is not None:
                items.append(("Proposed permit maximum", r["proposed"], "proposed"))
            for p, v in zip(peers, r["peers"]):
                if v is not None:
                    py = year_of(p, pol)
                    items.append((label(p, preset, py if py != yr else None), v, "peer"))
            # Target and proposal stay on top so the eye lands on them first.
            head = [i for i in items if i[2] != "peer"]
            tail = sorted((i for i in items if i[2] == "peer"), key=lambda i: -i[1])
            items = head + tail
            ratio = r["ratio"] if r["ratio"] is not None else r["proposed_ratio"]
            subject = "this plant's" if r["ratio"] is not None else "the proposed"
            if ratio is not None:
                hero = ratio_text(ratio)
                sub = (wrap(f"{subject} {pol} vs. the median of {r['n_peers']} comparable plants ({codes})."
                            + gap_txt, 54) if preset != "print" else None)
            else:
                hero, sub = None, None
            title = (f"{FULL.get(pol, pol)}: this plant vs. its industry peers" if preset != "print" else
                     f"{FULL.get(pol, pol)}, {yr}: target vs. {r['n_peers']} comparable facilities ({codes})"
                     + (f"; {ratio_text(ratio)} the peer median" if ratio is not None else ""))
            foot = (f"Source: {src_name}, reporting year {yr}, via EPA ECHO combined air emissions file "
                    f"({e['source']}, file dated {e['file_date']}, retrieved {e['retrieved']}). Whole-facility "
                    f"totals in {r['unit']}. Peers matched on {codes} and sized by GHGRP CO2e (a proxy)."
                    + gap_txt)
            if not is_ghg and nei_year == 2020:
                foot += " 2020 output was reduced by COVID-19, for every facility shown."
            if r["proposed"] is not None:
                foot += f" Proposed = {PROPOSED_LABEL.lower()}, an allowable limit, not a measured release."
            if preset != "print":
                foot = (f"Source: EPA {'GHGRP' if is_ghg else 'NEI'} {yr} via ECHO "
                        f"(retrieved {e['retrieved']}). Whole-facility {r['unit']}; peers matched on {codes}."
                        + (" Proposed = permit maximum, not a measurement." if r["proposed"] is not None else ""))
            ncol = 2 if preset != "print" else 4
            fig, ax = canvas(preset, title, hero=hero, hero_sub=sub, foot=foot,
                             legend_rows=2 if preset != "print" else 1, bars=len(items))
            h = bar_height(len(items), preset)
            for i, (_, v, kind) in enumerate(items):
                if kind == "proposed":
                    ax.barh(i, v, height=h, color=PROPOSED_FILL, edgecolor=PROPOSED_HATCH, hatch="//", linewidth=0)
                else:
                    ax.barh(i, v, height=h, color=TARGET if kind == "target" else PEER,
                            edgecolor=SURFACE, linewidth=1)
            hbar_layout(ax, [lbl for lbl, _, _ in items], preset, h)
            ax.xaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
            vals = [v for _, v, _ in items]
            p = PRESETS[preset]
            xmax = max(vals)
            for i, v in enumerate(vals):
                ax.text(v + xmax * 0.01, i, fmt(v) if v >= 10 else f"{v:.2g}", va="center",
                        fontsize=p["base"] - 1, color=INK2)
            ax.set_xlim(0, xmax * 1.25)
            if r["median"] is not None:
                # Per-row ticks rather than a full-height line, which would strike through the labels.
                ax.vlines([r["median"]] * len(items), [i - h / 2 - 0.08 for i in range(len(items))],
                          [i + h / 2 + 0.08 for i in range(len(items))], color=MEDIAN, linewidth=1.6,
                          linestyles=(0, (2, 1.5)), zorder=3)
            handles = [plt.Rectangle((0, 0), 1, 1, color=TARGET, label=f"This plant, {yr}"),
                       plt.Rectangle((0, 0), 1, 1, color=PEER, label="Comparable plants"),
                       plt.Line2D([0], [0], color=MEDIAN, linestyle=(0, (4, 3)), label="Peer median")]
            if r["proposed"] is not None:
                handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=PROPOSED_FILL, edgecolor=PROPOSED_HATCH,
                                             hatch="//", linewidth=0, label="Proposed max"))
            legend(ax, handles, preset, ncol=ncol)
            slug = re.sub(r"[^a-z0-9]+", "-", pol.lower()).strip("-")
            paths += save(fig, out, f"compare-{slug}", preset)

    # Summary: target ÷ peer median for every pollutant with peers, one image.
    rows = [r for r in cmp_rows if r["ratio"] is not None and r["n_peers"]]
    if len(rows) >= 2:
        rows.sort(key=lambda r: -r["ratio"])
        for preset in presets:
            n = PRESETS[preset]["top_n"] + 3
            # Keep the below-median pollutants in view when trimming; dropping them would
            # turn the image into a cherry-pick that a rebuttal can point to.
            if len(rows) > n:
                below = [r for r in rows if r["ratio"] <= 1]
                k = min(len(below), max(2, n // 3))
                rr = rows[: n - k] + (below[-k:] if k else [])
                rr = sorted({id(r): r for r in rr}.values(), key=lambda r: -r["ratio"])
            else:
                rr = rows
            above = sum(1 for r in rows if r["ratio"] > 1)
            hidden = [r for r in rows if r not in rr]
            more = (f" Not shown: {len(hidden)} more pollutants ({sum(1 for r in hidden if r['ratio'] > 1)} above "
                    f"the median), listed in the report." if hidden else "")
            fig, ax = canvas(
                preset,
                "How this plant compares to its peers" if preset != "print" else
                f"Target emissions as a multiple of the peer median (NEI {nei_year}, GHGRP {ghg_year})",
                hero=f"{above} of {len(rows)}",
                hero_sub=(wrap(f"pollutants above the median of comparable plants ({codes})." + gap_txt, 54)
                          if preset != "print"
                          else f"{above} of {len(rows)} pollutants above the peer median." + gap_txt),
                foot=(f"Source: EPA NEI {nei_year} and GHGRP {ghg_year} via ECHO combined air emissions file, "
                      f"retrieved {e['retrieved']}. Ratio = target facility total ÷ median of "
                      f"{len(peers)} comparable facilities ({codes}). Whole-facility totals; mass is not toxicity."
                      + more),
                legend_rows=0, bars=len(rr))
            h = bar_height(len(rr), preset)
            vals = [r["ratio"] for r in rr]
            p = PRESETS[preset]
            # Log scale centred on 1x: 50x above and 0.02x below the median are the same distance.
            ax.set_xscale("log")
            lo = min(min(vals), 1) / 2.5
            hi = max(max(vals), 1) * 3
            ax.set_xlim(lo, hi)
            ax.barh(range(len(rr)), [v - 1 for v in vals], left=1, height=h,
                    color=[TARGET if v > 1 else PEER for v in vals], edgecolor=SURFACE, linewidth=1)
            ax.set_yticks([])
            for i, r in enumerate(rr):
                ax.text(lo * 1.05, i - h / 2 - 0.06, f"{FULL.get(r['pollutant'], r['pollutant'])} ({r['n_peers']} peers)",
                        va="bottom", ha="left", fontsize=p["base"], color=INK2)
                v = r["ratio"]
                ax.text(v * 1.08 if v > 1 else 1.08, i, ratio_text(v), va="center", ha="left",
                        fontsize=p["base"] - 1, color=INK2)
            ax.set_ylim(len(rr) - 0.5, -0.95)
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:g}×"))
            ax.grid(axis="x", color=BASELINE, linewidth=0.4)
            ax.set_axisbelow(True)
            ax.spines["left"].set_visible(False)
            ax.spines["bottom"].set_visible(False)
            ax.vlines([1] * len(rr), [i - h / 2 - 0.08 for i in range(len(rr))],
                      [i + h / 2 + 0.08 for i in range(len(rr))], color=MEDIAN, linewidth=1.6, zorder=3)
            paths += save(fig, out, "compare-summary", preset)
    return paths


# ---------------------------------------------------------------- REPORT.md

def num(v, pol=None):
    if v is None:
        return "—"
    return fmt(v) if abs(v) >= 100 else f"{v:,.1f}" if abs(v) >= 1 else f"{v:.3g}"


def report(d, cmp_rows, prop, caps, paths, out):
    c, e = d["candidates"], d["emissions"]
    t, peers = e["target"], e["shortlist"]
    codes = ", ".join([f"SIC {x}" for x in c["sic"]] + [f"NAICS {x}" for x in c["ncs"]])
    scope_txt = {"state": f"{c['state']} only", "region": f"EPA Region {c['region']}",
                 "national": "nationwide"}[e["scope"]]
    L = [f"# Comparable-facility emissions: {t['name']}", "",
         f"- **Target site:** {t['name']}, {t['street']}, {t['city']}, {t['state']} — Registry IDs "
         + ", ".join(f"`{r}`" for r in t["registry_ids"]),
         f"- **Matched on:** {codes} · **Peers drawn from:** {scope_txt} · "
         f"**Size band:** {1 / e['band']:.2f}–{e['band']:g}× the target's size proxy",
         f"- **Years compared:** NEI {e['nei_year']} (criteria pollutants, HAPs), GHGRP {e['ghg_year']} "
         f"(greenhouse gases), TRI {e['tri_year']} (context)",
         f"- **Source:** EPA ECHO combined air emissions file, {e['source']} (file dated {e['file_date']}, "
         f"retrieved {e['retrieved']}); facility search via ECHO REST (retrieved {c['retrieved']})",
         f"- **All {len(peers) + len(e['others'])} candidate sites:** `comparables.csv`", ""]
    if t.get("auto_merged"):
        L += [f"> Registry IDs {', '.join(t['auto_merged'])} were merged into the target because they share "
              "a program ID or sit at the same address. Confirm they belong to this plant.", ""]
    in_band = sum(n["in_band"] for n in e["counts"].values())
    if e["band"] > 3:
        L += [f"> **Size band widened to {1 / e['band']:.2f}–{e['band']:g}×.** At the default 1/3×–3× band, too "
              "few same-industry plants were close to the target's size. The target is unusually large or "
              "small for its industry, which is itself worth stating.", ""]
    elif in_band < e["min"]:
        L += [f"> **Only {in_band} same-industry plant(s) within 1/3×–3× of the target's size nationwide.** "
              "Remaining shortlist slots, if any, are plants of unknown size.", ""]
    aside = sum(n.get("other_industry", 0) for n in e["counts"].values())
    if aside:
        L += [f"> {aside} candidate site(s) matched {codes} only through another program's records while their "
              "air permit names a different industry (for example a refinery with an ammonia unit). Their "
              "whole-facility emissions belong to that other industry, so they were set aside; they remain "
              "in `comparables.csv`.", ""]
    # The air permit's codes describe the emitting units; 9999 is "nonclassifiable", not an industry.
    site_sic = [x for x in (t.get("caa_sic") or t["sic"]) if x != "9999"]
    multi = len({x[:3] for x in site_sic}) > 1
    if multi:
        L += [f"> **Multi-industry site.** The target's records list SIC {', '.join(site_sic)}. Its NEI and "
              f"GHGRP totals cover the whole complex, while peers were matched on {codes} only. A complex "
              "with extra process units will look larger than a single-purpose plant for that reason alone.", ""]

    L += ["## Facilities compared", ""]
    head = ["", "Facility", "City, state", "Match", "Size proxy (t CO2e)", "× target", "Stated capacity",
            "NEI year", "Registry IDs"]
    rows = []
    for i, f in enumerate([t] + peers):
        cap = caps.get(i)
        rows.append(["**target**" if i == 0 else str(i), f["name"], f"{f['city']}, {f['state']}",
                     f.get("match", ""), (num(f["size"]) + ("" if f["size_source"] == "GHGRP CO2e" else f" ({f['size_source']})"))
                     if f["size"] else "unknown",
                     "" if i == 0 else (f"{f['size_ratio']:.2f}" if f.get("size_ratio") else "—"),
                     f"{num(cap['capacity'])} {cap['unit']} {cap['product']}".strip() + f" [src]({cap['source_url']})"
                     if cap else "",
                     f"{f.get('nei_year') or '—'}" + (f" ⚠ {f['nei_year_flag']}" if f.get("nei_year_flag") else ""),
                     " ".join(f"`{r}`" for r in f["registry_ids"])])
    L.append(table(head, rows))
    if not caps:
        L += ["", "*No stated capacities recorded (`capacities.csv` absent). Sizes rest on the GHGRP CO2e proxy alone.*"]

    L += ["", "## Emissions comparison", "",
          "Whole-facility annual totals. Ratio = target ÷ median of the peers that report the pollutant.", ""]
    head = ["Pollutant", "Unit", "Target"] + [f"Peer {i}" for i in range(1, len(peers) + 1)] + \
           ["Peer median", "Target ÷ median", "Per t CO2e ÷ median"]
    if any("capacity_ratio" in r for r in cmp_rows):
        head.append("Per capacity ÷ median")
    if prop:
        head += ["Proposed max", "Proposed ÷ median"]
    rows = []
    for r in cmp_rows:
        row = [FULL.get(r["pollutant"], r["pollutant"]), r["unit"], num(r["target"])] + [num(v) for v in r["peers"]]
        row += [num(r["median"]), f"**{ratio_text(r['ratio'])}**" if r["ratio"] else "—",
                ratio_text(r["intensity_ratio"]) if r.get("intensity_ratio") else "—"]
        if "Per capacity ÷ median" in head:
            row.append(ratio_text(r["capacity_ratio"]) if r.get("capacity_ratio") else "—")
        if prop:
            row += [num(r["proposed"]), ratio_text(r["proposed_ratio"]) if r["proposed_ratio"] else "—"]
        rows.append(row)
    L.append(table(head, rows))
    flagged = [f for f in peers if f.get("nei_year_flag")]
    if flagged:
        L += ["", "Peers without NEI " + str(e["nei_year"]) + " data use their nearest NEI year: "
              + "; ".join(f"{f['name']} ({f['nei_year_flag']})" for f in flagged) + "."]

    if prop:
        labels = {"mapped": "Compared", "unmatched": "Not matched to an NEI/GHGRP pollutant — not compared",
                  "grams": "Reported in grams — not compared", "unconvertible": "Unit not recognized — not compared"}
        L += ["", "## Proposed permit limits", "",
              f"From `{prop['path']}`. Permit figures are **permitted maximums (PTE/allowable)**; NEI and "
              "GHGRP figures are actual-emission estimates. A permitted maximum above the peer median says "
              "what the permit would allow, not what the plant will emit.", ""]
        L.append(table(["Chemical", "CAS", "As permitted", "Basis", "Compared as", "Converted", "Conversion",
                        "Status", "Source", "OCR verified"],
                       [[r["chemical"], r["cas"], f"{r['amount']:g} {r['unit']}" if r["amount"] is not None else r["unit"],
                         r["basis"], r["pollutant"] or "", f"{num(r['value'])} {unit(r['pollutant'])}" if r["value"] is not None else "",
                         r["conversion"], labels[r["bucket"]], f"{r['source_doc']} p. {r['page']}",
                         "yes" if r["ocr_verified"] else "**no**"] for r in prop["rows"]]))
        nu = sum(1 for r in prop["rows"] if not r["ocr_verified"])
        if nu:
            L.append(f"\n**{nu} proposed row(s) are not OCR-verified.** Run `bayou:ocr-verify` on those pages "
                     "before citing the figures.")

    L += ["", "## Caveats", ""]
    cav = [
        "**Whole facility, not the permitted unit.** NEI and GHGRP report facility totals. A repermit often "
        "covers one unit, so this compares plants, not units.",
        "**NEI is triennial and partly estimated.** Some NEI values are state- or EPA-estimated rather than "
        "facility-reported. Peers lacking the target's NEI year are shown with their nearest year and flagged.",
        "**The size proxy is circular.** GHGRP CO2e tracks fuel burned, so an inefficient plant looks larger "
        "than it is. Stated capacity, where found, is the better yardstick.",
        "**Proposed ≠ reported.** Permit limits are allowable maximums; NEI/GHGRP are actual estimates.",
        "**Mass is not toxicity.** Tons of NOx and pounds of ethylene oxide are not comparable harms; compare "
        "each pollutant only to itself. For risk weighting see EPA RSEI or AirToxScreen.",
        "**HAPs are compared one by one.** NEI lists pollutant groups alongside their members (e.g., PAH and "
        "naphthalene), so no HAP total is computed.",
    ]
    if e["nei_year"] == 2020:
        cav.insert(2, "**2020 was a COVID-19 year.** Throughput fell at many plants. Ratios between facilities "
                      "remain fair because every facility shares the year, but absolute tons understate typical "
                      "operation.")
    L += [f"- {x}" for x in cav]
    L += ["", "## Charts", "",
          "Social presets are 1080×1080 and 1080×1350 px. Print figures are 6.5 in wide at 300 dpi "
          "(PNG + PDF). Kit and Nextdoor have no image-upload API; upload these by hand.", "",
          chart_list(paths, out)]
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--proposed")
    ap.add_argument("--hours", type=float)
    ap.add_argument("--formats", default="social,print")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    with open(os.path.join(out, "summary.json")) as fh:
        d = json.load(fh)
    if "emissions" not in d:
        sys.exit("Run `comparables.py emissions` first.")
    e = d["emissions"]
    prop = load_proposed(a.proposed, a.hours, e["target"]) if a.proposed else None
    caps = load_capacities(out, [e["target"]] + e["shortlist"])
    cmp_rows = compare(e["target"], e["shortlist"], prop, caps)
    fm = {s.strip() for s in a.formats.split(",")}
    presets = ([p for p in ("social-square", "social-portrait") if "social" in fm]
               + (["print"] if "print" in fm else []))
    paths = charts(d, cmp_rows, prop, os.path.join(out, "charts"), presets)
    L = report(d, cmp_rows, prop, caps, paths, out)
    with open(os.path.join(out, "REPORT.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(os.path.join(out, "REPORT.md"))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
