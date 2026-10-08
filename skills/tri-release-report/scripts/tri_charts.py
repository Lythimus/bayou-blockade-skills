"""Render charts and REPORT.md from a tri_fetch.py summary.json.

Usage: tri_charts.py OUT_DIR [--formats social,print]

Writes OUT_DIR/charts/<chart>-<preset>.png (+ .pdf for print) and OUT_DIR/REPORT.md.
Static images cannot follow a viewer's theme, so everything renders on the
light surface; colors are the dataviz reference palette, validated for these
slot counts (5 adjacent for media, 2 all-pairs for existing vs proposed).
"""
import argparse
import json
import os
import re
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
# Darker step of the orange ramp so the hatch reads on its own fill.
PROPOSED_FILL = "#f6b394"
PROPOSED_HATCH = "#b8461a"
PROPOSED_LABEL = "Permitted maximum (proposed)"

MEDIA = [("air_stack", "Stack air"), ("air_fugitive", "Fugitive air"), ("water", "Water"),
         ("land", "Land"), ("uic", "Underground injection")]
MEDIA_COLOR = dict(zip([m for m, _ in MEDIA], SLOT))

PRESETS = {
    "social-square": dict(size=(10.8, 10.8), dpi=100, base=17, title=30, hero=68, foot=12.5,
                          top_n=5, wrap=62, twrap=40),
    "social-portrait": dict(size=(10.8, 13.5), dpi=100, base=17, title=30, hero=72, foot=12.5,
                            top_n=7, wrap=62, twrap=40),
    "print": dict(size=(6.5, 4.4), dpi=300, base=7.5, title=10, hero=None, foot=6,
                  top_n=10, wrap=118, twrap=78),
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK2,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "hatch.linewidth": 1.2,
    "pdf.fonttype": 42,
})


def fmt(x):
    return f"{x:,.0f}"


def compact(x, _=None):
    a = abs(x)
    if a >= 1e6:
        return f"{x / 1e6:.1f}M".replace(".0M", "M")
    if a >= 1e3:
        return f"{x / 1e3:.0f}K"
    return f"{x:,.0f}"


KEEP_UPPER = {"LLC", "LP", "LLP", "II", "III", "IV", "USA", "US", "SMR", "CII", "DBA", "TRI", "PVC"}


def short_name(s, n=34):
    s = " ".join(s.split())
    if len(s) > n and " (" in s:
        s = s.split(" (")[0]
    if s.isupper():
        # EPA facility names are all caps; title-case them but keep corporate suffixes.
        s = re.sub(r"(?<![0-9A-Za-z])[A-Za-z]+(?![0-9A-Za-z])", lambda m: m.group(0) if m.group(0) in KEEP_UPPER
                   else m.group(0).capitalize(), s)
    return s if len(s) <= n else s[: n - 1] + "…"


def wrap(s, width):
    return "\n".join(textwrap.wrap(s, width, break_long_words=False, break_on_hyphens=False))


def canvas(preset, title, hero=None, hero_sub=None, foot="", legend_rows=0, bars=0, yaxis=False):
    """Returns (fig, ax). Social presets stack title, hero number, plot, footer.

    Print figures grow with the bar count (`bars`) so labels never collide; social
    sizes are fixed by the platforms, which is why their top_n is smaller.
    """
    p = PRESETS[preset]
    title = wrap(title, p["twrap"])
    W, H = p["size"]
    if preset == "print" and bars:
        H = max(H, 2.1 + 0.3 * bars)
    # Print figures sit on a white PDF page, where the off-white surface would show as a box.
    bg = "#ffffff" if preset == "print" else SURFACE
    fig = plt.figure(figsize=(W, H), dpi=p["dpi"], facecolor=bg)
    pad = 0.6 / W if preset != "print" else 0.15 / W
    y = 1 - (0.55 / H if preset != "print" else 0.12 / H)
    fig.text(pad, y, title, fontsize=p["title"], weight="bold", color=INK, va="top")
    y -= (p["title"] * 1.6 / 72) / H * (title.count("\n") + 1)
    if hero is not None and p["hero"]:
        y -= 0.15 / H
        fig.text(pad, y, hero, fontsize=p["hero"], weight="bold", color=INK, va="top")
        y -= (p["hero"] * 1.15 / 72) / H
        if hero_sub:
            fig.text(pad, y, hero_sub, fontsize=p["base"] + 2, color=INK2, va="top")
            y -= ((p["base"] + 2) * 1.5 / 72) / H * (hero_sub.count("\n") + 1)
    elif hero_sub:
        fig.text(pad, y, hero_sub, fontsize=p["base"], color=INK2, va="top")
        y -= (p["base"] * 1.5 / 72) / H * (hero_sub.count("\n") + 1)
    foot = wrap(foot, p["wrap"])
    fig.text(pad, 0.12 / H if preset == "print" else 0.4 / H, foot, fontsize=p["foot"],
             color=MUTED, va="bottom", linespacing=1.35)
    foot_h = (p["foot"] * 1.35 / 72) * (foot.count("\n") + 1) + (0.3 if preset == "print" else 0.75)
    bottom = foot_h / H
    top = y - (0.12 if preset == "print" else 0.45) / H
    top -= legend_rows * (p["base"] * (1.9 if preset != "print" else 1.5) / 72) / H
    # Tick labels on a left value axis render outside the axes box.
    left = pad + ((0.35 if preset == "print" else 0.55) / W if yaxis else 0)
    ax = fig.add_axes([left, bottom, 1 - pad - left, max(0.15, top - bottom)])
    ax.set_facecolor(bg)
    ax.tick_params(labelsize=p["base"], length=0)
    return fig, ax


def save(fig, out, name, preset):
    os.makedirs(out, exist_ok=True)
    base = os.path.join(out, f"{name}-{preset}")
    fig.savefig(base + ".png", facecolor=fig.get_facecolor())
    paths = [base + ".png"]
    if preset == "print":
        fig.savefig(base + ".pdf", facecolor=fig.get_facecolor())
        paths.append(base + ".pdf")
    plt.close(fig)
    return paths


def legend(ax, handles, preset, ncol):
    p = PRESETS[preset]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol,
              frameon=False, fontsize=p["base"], handlelength=1.0, handleheight=1.0,
              borderaxespad=0.3, columnspacing=1.2, labelcolor=INK2)


def hbar_layout(ax, labels, preset, h):
    """Category label sits above its bar so long facility names never clip at the edge."""
    p = PRESETS[preset]
    ax.set_yticks([])
    for i, lbl in enumerate(labels):
        ax.text(0, i - h / 2 - 0.06, lbl, va="bottom", ha="left", fontsize=p["base"], color=INK2)
    ax.set_ylim(len(labels) - 0.5, -0.95)
    ax.xaxis.set_major_formatter(FuncFormatter(compact))
    ax.grid(axis="x", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)


def bar_height(n, preset):
    # Thin bars leave room for the label above each; few bars must not become slabs.
    return 0.42 if n >= 5 else 0.3


def tip_labels(ax, values, preset, extra=None):
    p = PRESETS[preset]
    xmax = max(values) if values else 1
    for i, v in enumerate(values):
        s = fmt(v)
        if extra and extra[i]:
            s += "  " + extra[i]
        ax.text(v + xmax * 0.01, i, s, va="center", fontsize=p["base"] - 1, color=INK2)
    ax.set_xlim(0, xmax * (1.45 if extra and any(extra) else 1.25))


# ---------------------------------------------------------------- facility charts

def facility_charts(d, out, presets):
    fac = d["facility"]
    years = d["years"]
    by = d["by_year"]
    last = d["latest_year"]
    name = short_name(fac["name"], 60)
    src = (f"Source: EPA Toxics Release Inventory basic data files ({d['source']}), "
           f"reporting years {years[0]}–{years[-1]}, retrieved {d['retrieved']}. "
           f"TRI ID {fac['trifd']}. On-site releases in pounds as reported by the facility; "
           f"pound totals are not weighted for toxicity (see EPA RSEI).")
    if d["grams_rows"]:
        src += " Dioxins are reported in grams and excluded from pound totals."
    short = (f"Source: EPA Toxics Release Inventory, data.epa.gov/efservice/downloads/tri "
             f"(retrieved {d['retrieved']}). {fac['trifd']}, {years[0]}–{years[-1]}. "
             f"Self-reported on-site pounds; not toxicity-weighted.")
    media = [(m, l) for m, l in MEDIA if any(by[str(y)][m] > 0 for y in years)]
    paths = []
    for preset in presets:
        p = PRESETS[preset]
        foot = src if preset == "print" else short
        total = by[str(last)]["total_lb"]
        fig, ax = canvas(
            preset,
            f"Toxic releases at {name}" if preset != "print" else
            f"On-site toxic releases by medium, {name}, {years[0]}–{years[-1]}",
            hero=f"{fmt(total)} lb",
            hero_sub=(f"released on site in {last}" if preset != "print" else
                      f"{last}: {fmt(total)} lb on site"),
            foot=foot, legend_rows=1 if preset == "print" else -(-len(media) // 3), yaxis=True)
        bottom = [0.0] * len(years)
        handles = []
        for m, label in media:
            vals = [by[str(y)][m] for y in years]
            h = ax.bar(range(len(years)), vals, bottom=bottom, width=0.6, color=MEDIA_COLOR[m],
                       edgecolor=SURFACE, linewidth=1.5 if preset == "print" else 2, label=label)
            handles.append(h)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_xticks(range(len(years)))
        ax.set_xticklabels([str(y) if preset == "print" or i % 2 == (len(years) - 1) % 2 else ""
                            for i, y in enumerate(years)], fontsize=p["base"])
        ax.yaxis.set_major_formatter(FuncFormatter(compact))
        ax.grid(axis="y", color=GRID, linewidth=0.5)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        ax.text(len(years) - 1, bottom[-1], " " + compact(bottom[-1]), ha="center", va="bottom",
                fontsize=p["base"] - 1, color=INK2)
        legend(ax, handles, preset, ncol=len(handles) if preset == "print" else min(3, len(handles)))
        paths += save(fig, out, "facility-trend", preset)

        chems = d["top_chemicals"][: p["top_n"]]
        carc_total = by[str(last)]["carcinogen_lb"]
        fig, ax = canvas(
            preset,
            f"Top chemicals released at {name}" if preset != "print" else
            f"Top {len(chems)} chemicals by on-site release, {name}, {last}",
            hero=f"{fmt(carc_total)} lb",
            hero_sub=(f"of EPA-listed carcinogens released on site in {last}" if preset != "print"
                      else f"Carcinogens (EPA TRI flag): {fmt(carc_total)} lb on site in {last}"),
            foot=foot, legend_rows=1, bars=len(chems))
        vals = [c["latest_lb"] for c in chems]
        colors = [SLOT[1] if c["carcinogen"] else SLOT[0] for c in chems]
        h = bar_height(len(chems), preset)
        ax.barh(range(len(chems)), vals, height=h, color=colors, edgecolor=SURFACE, linewidth=1)
        hbar_layout(ax, [short_name(c["chemical"], 40 if preset != "print" else 60) for c in chems],
                    preset, h)
        tip_labels(ax, vals, preset, ["carcinogen" if c["carcinogen"] else "" for c in chems])
        handles = [plt.Rectangle((0, 0), 1, 1, color=SLOT[1], label="EPA carcinogen"),
                   plt.Rectangle((0, 0), 1, 1, color=SLOT[0], label="Other TRI chemical")]
        legend(ax, handles, preset, ncol=2)
        paths += save(fig, out, "facility-top-chemicals", preset)
    return paths


# ---------------------------------------------------------------- radius charts

def radius_charts(d, out, presets):
    R = d["radius_mi"]
    yr = d["year"]
    tot = d["totals"]
    prop = d.get("proposed")
    center = d["center"]["label"]
    src = (f"Source: EPA Toxics Release Inventory basic data files ({d['source']}), reporting year "
           f"{yr}, retrieved {d['retrieved']}. Facilities within {R:g} mi of {center}. "
           f"On-site releases in pounds; not weighted for toxicity (see EPA RSEI).")
    if tot["onsite_g"]:
        src += f" Dioxins ({tot['onsite_g']:.3g} g) are reported in grams and excluded from pound totals."
    if prop:
        docs = sorted({r["source_doc"] for r in prop["rows"] if r["source_doc"]})
        src += (f" Proposed = {PROPOSED_LABEL.lower()} from {'; '.join(docs)}, converted to lb/yr; "
                f"a permit limit, not a measured release. Criteria pollutants are not TRI-reportable "
                f"and are not included.")
    short = (f"Source: EPA Toxics Release Inventory, data.epa.gov/efservice/downloads/tri, "
             f"reporting year {yr} (retrieved {d['retrieved']}). Within {R:g} mi of "
             f"{short_name(center, 60)}. Self-reported on-site pounds; not toxicity-weighted."
             + (" Proposed = permit maximum, not a measured release." if prop else ""))
    paths = []
    for preset in presets:
        p = PRESETS[preset]
        n = p["top_n"]
        foot = src if preset == "print" else short
        facs = d["facilities"]
        items = [(short_name(f["name"], 40 if preset != "print" else 60), f["onsite_lb"], False)
                 for f in facs[:n]]
        if prop and prop["totals"]["lb_yr"] > 0:
            items.append(("Proposed facility", prop["totals"]["lb_yr"], True))
            items.sort(key=lambda t: -t[1])
        # The "other" bucket stays last whatever its size; ranking it would read as one facility.
        rest = facs[n:]
        if rest:
            items.append((f"{len(rest)} other facilities", sum(f["onsite_lb"] for f in rest), False))
        fig, ax = canvas(
            preset,
            f"Toxic releases within {R:g} miles" if preset != "print" else
            f"On-site TRI releases by facility within {R:g} mi, {yr}",
            hero=f"{fmt(tot['onsite_lb'])} lb",
            hero_sub=(f"released on site by {tot['n_facilities']} facilities in {yr}" if preset != "print"
                      else f"{tot['n_facilities']} facilities, {fmt(tot['onsite_lb'])} lb on site in {yr}"),
            foot=foot, legend_rows=1 if prop else 0, bars=len(items))
        vals = [v for _, v, _ in items]
        h = bar_height(len(items), preset)
        for i, (_, v, is_prop) in enumerate(items):
            if is_prop:
                ax.barh(i, v, height=h, color=PROPOSED_FILL, edgecolor=PROPOSED_HATCH, hatch="//",
                        linewidth=0)
            else:
                ax.barh(i, v, height=h, color=SLOT[0], edgecolor=SURFACE, linewidth=1)
        hbar_layout(ax, [lbl for lbl, _, _ in items], preset, h)
        tip_labels(ax, vals, preset, ["proposed max" if ip else "" for _, _, ip in items])
        if prop:
            handles = [plt.Rectangle((0, 0), 1, 1, color=SLOT[0], label=f"Reported, {yr}"),
                       plt.Rectangle((0, 0), 1, 1, facecolor=PROPOSED_FILL, edgecolor=PROPOSED_HATCH,
                                     hatch="//", linewidth=0, label=PROPOSED_LABEL)]
            legend(ax, handles, preset, ncol=2)
        paths += save(fig, out, "radius-facilities", preset)

        carc = [c for c in d["chemicals"] if c["carcinogen"]]
        pc = {}
        if prop:
            for r in prop["rows"]:
                if r["carcinogen"] and r["layer"] == "lb" and r["bucket"].startswith("tri"):
                    key = r["tri_chem_id"]
                    pc[key] = pc.get(key, 0.0) + r["value"]
        names = {c["tri_chem_id"]: c["chemical"] for c in carc}
        if prop:
            for r in prop["rows"]:
                if r["tri_chem_id"] in pc and r["tri_chem_id"] not in names:
                    names[r["tri_chem_id"]] = r["tri_name"]
        existing = {c["tri_chem_id"]: c["onsite_lb"] for c in carc}
        ids = sorted(names, key=lambda k: -(existing.get(k, 0) + pc.get(k, 0)))[:n]
        if not ids:
            continue
        ex_total = tot["carcinogen_lb"]
        pr_total = prop["totals"]["carcinogen_lb_yr"] if prop else 0
        if prop and pr_total:
            hero = f"+{fmt(pr_total)} lb"
            sub = (f"of carcinogens proposed, on top of {fmt(ex_total)} lb\nreleased within {R:g} mi in {yr}"
                   if preset != "print" else
                   f"Reported {yr}: {fmt(ex_total)} lb; proposed permitted maximum adds {fmt(pr_total)} lb/yr")
        else:
            hero = f"{fmt(ex_total)} lb"
            sub = (f"of EPA-listed carcinogens released within {R:g} mi in {yr}" if preset != "print"
                   else f"{fmt(ex_total)} lb of carcinogens released on site within {R:g} mi in {yr}")
        fig, ax = canvas(
            preset,
            f"EPA-listed carcinogens within {R:g} miles" if preset != "print" else
            f"Carcinogen releases within {R:g} mi: reported {yr}" + (" + proposed" if prop else ""),
            hero=hero, hero_sub=sub, foot=foot, legend_rows=1 if prop else 0, bars=min(n, len(names)))
        h = bar_height(len(ids), preset)
        ev = [existing.get(k, 0.0) for k in ids]
        pv = [pc.get(k, 0.0) for k in ids]
        ax.barh(range(len(ids)), ev, height=h, color=SLOT[0], edgecolor=SURFACE, linewidth=1)
        if prop:
            ax.barh(range(len(ids)), pv, left=ev, height=h, color=PROPOSED_FILL,
                    edgecolor=PROPOSED_HATCH, hatch="//", linewidth=0)
        hbar_layout(ax, [short_name(names[k], 40 if preset != "print" else 60)
                         + (f"  (+{fmt(q)} lb proposed)" if q else "") for k, q in zip(ids, pv)],
                    preset, h)
        tip_labels(ax, [e + q for e, q in zip(ev, pv)], preset)
        if prop:
            handles = [plt.Rectangle((0, 0), 1, 1, color=SLOT[0], label=f"Reported, {yr}"),
                       plt.Rectangle((0, 0), 1, 1, facecolor=PROPOSED_FILL, edgecolor=PROPOSED_HATCH,
                                     hatch="//", linewidth=0, label=PROPOSED_LABEL)]
            legend(ax, handles, preset, ncol=2)
        paths += save(fig, out, "radius-carcinogens", preset)
    return paths


# ---------------------------------------------------------------- REPORT.md

CAVEATS = [
    "**On-site releases** (TRI col. 65: air, water, land, underground injection at the facility) "
    "are used for local exposure. `TOTAL RELEASES` (col. 107) adds off-site transfers and is shown "
    "only as context.",
    "**Mass is not toxicity.** Pound totals are not hazard-weighted; a pound of ethylene oxide "
    "and a pound of propylene are not equivalent. For risk-weighted comparisons see EPA RSEI "
    "(https://www.epa.gov/rsei).",
    "**Self-reported.** TRI figures are the facility's own estimates under EPCRA §313, not "
    "monitored concentrations.",
    "**Range codes.** Small releases may be reported as a range (A: 1–10, B: 11–499, C: 500–999 lb). "
    "The basic data files substitute the midpoint (5 / 250 / 750) with no flag, so an exact 5, 250, "
    "or 750 may be a midpoint, not a measurement.",
    "**Dioxins** are reported in grams and are never added to pound totals.",
    "**Form A** filers certify a chemical's reportable amount is ≤ 500 lb (non-PBT) and disclose no "
    "quantity. The bulk file shows those rows as 0.000; they are listed separately, never counted as "
    "zero, and not included in totals.",
]


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def chart_list(paths, out):
    pngs = [p for p in paths if p.endswith(".png")]
    return "\n".join(f"- ![{os.path.basename(p)}]({os.path.relpath(p, out)}) "
                     f"`{os.path.relpath(p, out)}`" for p in pngs)


def report_facility(d, paths, out):
    f = d["facility"]
    by = d["by_year"]
    L = [f"# TRI release report: {f['name']}", "",
         f"- **TRI facility ID:** `{f['trifd']}`",
         f"- **Address:** {f['address']}, {f['city']}, {f['state']}",
         f"- **Parent company:** {f['parent']}",
         f"- **Reporting years:** {d['years'][0]}–{d['years'][-1]}"
         + (f" (no file for {d['missing_years']})" if d["missing_years"] else ""),
         f"- **Source:** EPA TRI basic data files, {d['source']} (retrieved {d['retrieved']})", "",
         "## On-site releases by year (pounds)", ""]
    rows = []
    for y in d["years"]:
        v = by[str(y)]
        rows.append([y, fmt(v["air_fugitive"]), fmt(v["air_stack"]), fmt(v["water"]), fmt(v["land"]),
                     fmt(v["uic"]), f"**{fmt(v['total_lb'])}**", fmt(v["carcinogen_lb"]),
                     fmt(v["pbt_lb"]), fmt(v["pfas_lb"]), fmt(v["offsite_lb"]), v["n_chemicals"],
                     len(v.get("form_a", []))])
    L.append(table(["Year", "Fugitive air", "Stack air", "Water", "Land", "UIC", "On-site total",
                    "Carcinogens", "PBT", "PFAS", "Off-site (context)", "Chemicals (Form R)",
                    "Form A"], rows))
    fa = d["by_year"][str(d["latest_year"])].get("form_a", [])
    if fa:
        L += ["", f"Form A chemicals in {d['latest_year']} (≤ 500 lb each, quantity not disclosed, "
                  f"not in totals): {', '.join(sorted(set(fa)))}."]
    flagged = [y for y in d["years"] if by[str(y)]["range_midpoint_rows"]]
    if flagged:
        L += ["", f"Years with chemical rows containing an exact 5/250/750 lb value (possible range-code "
                  f"midpoint): {', '.join(map(str, flagged))}. Confirm against Envirofacts "
                  f"`tri_release_qty` (`bayou:epa-tri-search` Step 3) before quoting those figures."]
    if d.get("jumps"):
        L += ["", f"## Large increases, {d['latest_year'] - 1} → {d['latest_year']}", "",
              "At least 3× the prior year and ≥ 1,000 lb. Check the Form R (Envirofacts "
              "`tri_release_qty`, or the facility's revision history) before citing: a jump is either a "
              "real event or a reporting error.", ""]
        L.append(table(["Chemical", "Carcinogen", f"{d['latest_year'] - 1} lb", f"{d['latest_year']} lb"],
                       [[j["chemical"], "yes" if j["carcinogen"] else "", fmt(j["prior_lb"]),
                         fmt(j["latest_lb"])] for j in d["jumps"]]))
    L += ["", f"## Top chemicals, {d['latest_year']} (pounds on site)", ""]
    rows = [[c["chemical"], c["cas"], "yes" if c["carcinogen"] else "", "yes" if c["pbt"] else "",
             fmt(c["latest_lb"]), fmt(c["period_lb"]),
             "" if c["prod_ratio_latest"] is None else f"{c['prod_ratio_latest']:g}"]
            for c in d["top_chemicals"]]
    L.append(table(["Chemical", "CAS", "Carcinogen", "PBT", f"{d['latest_year']} lb",
                    f"{d['years'][0]}–{d['years'][-1]} lb", "Production ratio"], rows))
    L += ["", "*Production ratio* is the facility's own ratio of this year's activity to the prior "
              "year's (Form R §8.9). Releases rising faster than this ratio suggest the increase is not "
              "explained by output alone; it is a rough indicator, not proof."]
    if d["grams_rows"]:
        L += ["", "## Dioxin and dioxin-like compounds (grams, not included above)", ""]
        L.append(table(["Year", "Chemical", "On-site g", "Air g"],
                       [[g["year"], g["chemical"], f"{g['onsite_g']:.4g}", f"{g['air_g']:.4g}"]
                        for g in d["grams_rows"] if g["onsite_g"]] or [["—", "none > 0", "", ""]]))
    return L


def report_radius(d, paths, out):
    t = d["totals"]
    prop = d.get("proposed")
    L = [f"# Cumulative TRI releases within {d['radius_mi']:g} mi of {d['center']['label']}", "",
         f"- **Center:** {d['center']['lat']:.5f}, {d['center']['lon']:.5f}",
         f"- **Reporting year:** {d['year']} · **States searched:** {', '.join(d['states'])}",
         f"- **Facilities:** {t['n_facilities']} · **On-site releases:** {fmt(t['onsite_lb'])} lb · "
         f"**Carcinogens:** {fmt(t['carcinogen_lb'])} lb"
         + (f" · **Dioxins:** {t['onsite_g']:.4g} g" if t["onsite_g"] else ""),
         f"- **Source:** EPA TRI basic data files, {d['source']} (retrieved {d['retrieved']})", "",
         "## Facilities", ""]
    L.append(table(["Facility", "TRI ID", "City", "Distance (mi)", "Parent company", "On-site lb",
                    "Air lb", "Carcinogen lb", "Dioxin g", "Form A chemicals"],
                   [[f["name"], f"`{f['trifd']}`", f["city"], f"{f['distance_mi']:.2f}", f["parent"] or "",
                     fmt(f["onsite_lb"]), fmt(f["air_lb"]), fmt(f["carcinogen_lb"]),
                     f"{f['onsite_g']:.4g}" if f["onsite_g"] else "", f.get("form_a") or ""]
                    for f in d["facilities"]]))
    pc = {}
    if prop:
        for r in prop["rows"]:
            if r["layer"] == "lb" and r["bucket"].startswith("tri"):
                pc[r["tri_chem_id"]] = pc.get(r["tri_chem_id"], 0.0) + r["value"]
    L += ["", "## Chemicals, cumulative (pounds on site)", ""]
    head = ["Chemical", "CAS", "Carcinogen", "Facilities", f"Reported {d['year']} lb", "Air lb"]
    if prop:
        head += ["Proposed max lb/yr", "Reported + proposed"]
    rows = []
    for c in d["chemicals"]:
        nfa = c.get("n_form_a", 0)
        quantified = c["n_facilities"] > 0
        r = [c["chemical"], c["cas"], "yes" if c["carcinogen"] else "",
             f"{c['n_facilities']}" + (f" (+{nfa} Form A)" if nfa else ""),
             fmt(c["onsite_lb"]) if quantified else "Form A only (≤ 500 lb each, not quantified)",
             fmt(c["air_lb"]) if quantified else ""]
        if prop:
            q = pc.pop(c["tri_chem_id"], 0.0)
            r += [fmt(q) if q else "", fmt(c["onsite_lb"] + q) if q else ""]
        rows.append(r)
    if prop:
        for r in prop["rows"]:
            if r["tri_chem_id"] in pc:
                q = pc.pop(r["tri_chem_id"])
                rows.append([f"{r['tri_name']} *(no nearby reporter)*", r["cas"],
                             "yes" if r["carcinogen"] else "", 0, "0", "0", fmt(q), fmt(q)])
    L.append(table(head, rows))
    if prop:
        L += ["", "## Proposed emissions", "",
              f"From `{prop['path']}`. Permit figures are **permitted maximums (PTE/allowable)**, "
              "not measured releases; they are compared to actual TRI-reported pounds only as an "
              "upper bound of what the permit would allow.", ""]
        labels = {"tri_nearby": "TRI chemical, reported nearby",
                  "tri_not_nearby": "TRI chemical, no nearby reporter",
                  "not_tri": "Not TRI-reportable (criteria pollutant / GHG) — not summed",
                  "unmatched": "CAS not on TRI list — not summed, check the CAS",
                  "unconvertible": "Unit not recognized — not summed"}
        L.append(table(["Chemical", "CAS", "As permitted", "Basis", "lb/yr", "Conversion", "Status",
                        "Source", "OCR verified"],
                       [[r["chemical"], r["cas"], f"{r['amount']:g} {r['unit']}" if r["amount"] is not None
                         else r["unit"], r["basis"], fmt(r["value"]) if r["value"] is not None else "",
                         r["conversion"], labels[r["bucket"]]
                         + (" (matched by exact name; add the CAS)" if r.get("matched_by") == "name" else ""),
                         f"{r['source_doc']} p. {r['page']}", "yes" if r["ocr_verified"] else "**no**"]
                        for r in prop["rows"]]))
        tp = prop["totals"]
        L += ["", f"Proposed TRI chemicals: {fmt(tp['lb_yr'])} lb/yr, of which carcinogens "
                  f"{fmt(tp['carcinogen_lb_yr'])} lb/yr."]
        if tp["n_unverified"]:
            L.append(f"**{tp['n_unverified']} proposed row(s) are not OCR-verified.** Run "
                     "`bayou:ocr-verify` on those pages before citing the figures.")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--formats", default="social,print")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    with open(os.path.join(out, "summary.json")) as f:
        d = json.load(f)
    fm = {s.strip() for s in a.formats.split(",")}
    presets = ([p for p in ("social-square", "social-portrait") if "social" in fm]
               + (["print"] if "print" in fm else []))
    charts = os.path.join(out, "charts")
    if d["mode"] == "facility":
        paths = facility_charts(d, charts, presets)
        L = report_facility(d, paths, out)
    else:
        paths = radius_charts(d, charts, presets)
        L = report_radius(d, paths, out)
    L += ["", "## Caveats", ""] + [f"- {c}" for c in CAVEATS]
    L += ["", "## Charts", "",
          "Social presets are 1080×1080 and 1080×1350 px. Print figures are 6.5 in wide at 300 dpi "
          "(PNG + PDF) for embedding in a public comment. Kit and Nextdoor have no image-upload API; "
          "upload these by hand.", "", chart_list(paths, out)]
    with open(os.path.join(out, "REPORT.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print(os.path.join(out, "REPORT.md"))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
