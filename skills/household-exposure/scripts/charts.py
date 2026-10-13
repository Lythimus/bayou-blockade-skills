"""Charts for the household report, drawn from report.build()'s results dict only.

Layout, presets and colors are tri-release-report's, so a household chart sits beside a TRI
chart without looking like a different publication. Bars are linear on purpose: when one
chemical is nearly all of the risk, that is the finding, and a log axis would hide it.
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tri-release-report", "scripts"))
from tri_charts import (BASELINE, GRID, INK2, MUTED, PRESETS, PROPOSED_FILL, PROPOSED_HATCH,  # noqa: E402
                        SLOT, SURFACE, bar_height, canvas, hbar_layout, legend, plt, save, short_name, wrap)

sys.path.insert(0, HERE)
from report import num, per_million  # noqa: E402

FOOT_HISTORY = ("Source: EPA RSEI Geographic Microdata (810 m grid) and EPA OAQPS Table 1 toxicity values. "
                "Modeled outdoor air from releases reported to TRI; other sources are not counted. "
                "Not a measurement and not a dose.")
FOOT_PROPOSED = ("Source: EPA AERMOD run on the applicant's modeling inputs and permitted emission rates; "
                 "EPA OAQPS Table 1 toxicity values. Permitted maximum, not a forecast. Modeled outdoor air; "
                 "not a measurement and not a dose.")


def bars(preset, title, sub, foot, labels, values, texts, color, hatch=None, ref=None):
    """Horizontal bars with the label above each bar and the value at its tip."""
    p = PRESETS[preset]
    fig, ax = canvas(preset, title, hero_sub=subtitle(sub, preset), foot=foot, bars=len(labels))
    h = bar_height(len(labels), preset)
    ax.barh(range(len(labels)), values, height=h, color=color, edgecolor=hatch or SURFACE,
            hatch="///" if hatch else None, linewidth=1)
    hbar_layout(ax, labels, preset, h)
    ax.xaxis.set_major_formatter(lambda x, _: num(x))
    xmax = max(values + [ref or 0]) or 1
    for i, (v, t) in enumerate(zip(values, texts)):
        ax.text(v + xmax * 0.01, i, t, va="center", fontsize=p["base"] - 1, color=INK2)
    ax.set_xlim(0, xmax * 1.3)
    if ref:
        ax.axvline(ref, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(ref, -0.8, " EPA reference level (1)", fontsize=p["base"] - 1, color=MUTED, va="center")
    return fig


def subtitle(text, preset):
    # canvas() wraps the title and the footer but not the line under the title.
    return wrap(text, 108 if preset == "print" else 56)


def who(r, mid):
    """Prefix naming the member, only when the household has more than one."""
    return f"Member {mid}: " if len(r["members"]) > 1 else ""


def clip(name, n=44):
    # tri_charts.short_name drops a parenthesis first, which here is often the owner's name.
    return name if len(name) <= n else name[: n - 1] + "…"


def years(n):
    return f"{n:.3g} year" + ("" if n == 1 else "s")


def history_charts(r, out, presets):
    paths = []
    for mid, m in r["history"]["members"].items():
        w = who(r, mid)
        floor = " A floor: some years have no figure." if m["is_floor"] else ""
        for preset in presets:
            n = PRESETS[preset]["top_n"]
            chems = [c for c in m["chemicals"] if c["cancer_risk"]][:n]
            if chems:
                fig = bars(preset, "Cancer risk by chemical",
                           f"{w}{per_million(m['cancer_risk'])} in a million over {years(m['years_with_a_figure'])} "
                           f"with data, from reported industrial releases.{floor}",
                           FOOT_HISTORY, [short_name(c["chemical"], 44) for c in chems],
                           [c["cancer_risk"] * 1e6 for c in chems],
                           [f"{per_million(c['cancer_risk'])} in a million" for c in chems], SLOT[0])
                paths += save(fig, out, f"past-cancer-by-chemical-{mid}", preset)
            facs = m["facilities"][:n]
            if facs:
                fig = bars(preset, "Cancer risk by source",
                           f"{w}Largest contributors to {per_million(m['cancer_risk'])} in a million.{floor}",
                           FOOT_HISTORY, [clip(f["source"]) for f in facs],
                           [f["cancer_risk"] * 1e6 for f in facs],
                           [f"{per_million(f['cancer_risk'])}  ({f['largest_chemical'].lower()})" for f in facs], SLOT[0])
                paths += save(fig, out, f"past-cancer-by-source-{mid}", preset)
            hi = m["hazard_index"][:n]
            if hi:
                fig = bars(preset, "Hazard index by organ",
                           f"{w}Sum of each chemical's ratio to EPA's reference level. A ratio, not a probability.",
                           FOOT_HISTORY, [f"{x['organ'].capitalize()}  ·  {(x['largest_chemical'] or '').lower()}" for x in hi],
                           [x["hazard_index"] for x in hi], [num(x["hazard_index"]) for x in hi], SLOT[0], ref=1.0)
                paths += save(fig, out, f"past-hazard-index-{mid}", preset)
    for preset in presets:
        paths += coverage_chart(r, out, preset)
    return paths


def coverage_chart(r, out, preset):
    """One row per member, one cell per year at the home. A year with no figure is drawn as
    an empty hatched cell so it cannot be read as a year of clean air."""
    members = r["history"]["members"]
    years = sorted({y["year"] for m in members.values() for y in m["years"]})
    if not years:
        return []
    p = PRESETS[preset]
    known = sum(1 for m in members.values() for y in m["years"] if y["status"] == "figure")
    total = sum(len(m["years"]) for m in members.values())
    fig, ax = canvas(preset, "Which years at the home have a figure",
                     hero_sub=subtitle(f"{known} of {total} person-years have RSEI data. The rest are unknown, "
                                       "not zero.", preset),
                     foot=FOOT_HISTORY, legend_rows=1)
    for i, (mid, m) in enumerate(members.items()):
        for y in m["years"]:
            x = years.index(y["year"])
            if y["status"] == "figure":
                ax.barh(i, 0.9, left=x + 0.05, height=0.5, color=SLOT[0], edgecolor=SURFACE, linewidth=1)
            else:
                ax.barh(i, 0.9, left=x + 0.05, height=0.5, color=SURFACE, edgecolor=BASELINE, hatch="///", linewidth=1)
    ax.set_yticks(range(len(members)))
    ax.set_yticklabels([f"Member {mid}" for mid in members], fontsize=p["base"], color=INK2)
    ax.set_ylim(len(members) - 0.4, -0.6)
    step = -(-len(years) // (16 if preset == "print" else 8))
    ax.set_xticks([i + 0.5 for i in range(0, len(years), step)])
    ax.set_xticklabels([str(years[i]) for i in range(0, len(years), step)], fontsize=p["base"])
    ax.set_xlim(0, max(len(years), 6))
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0)
    legend(ax, [plt.Rectangle((0, 0), 1, 1, color=SLOT[0], label="Has a figure"),
                plt.Rectangle((0, 0), 1, 1, facecolor=SURFACE, edgecolor=BASELINE, hatch="///", label="No figure (unknown)")],
           preset, ncol=2)
    # Member labels sit left of the axes; widen the left margin to hold them.
    box = ax.get_position()
    shift = (0.75 if preset == "print" else 1.5) / fig.get_figwidth()
    ax.set_position([box.x0 + shift, box.y0, box.width - shift, box.height])
    return save(fig, out, "past-years-covered", preset)


def proposed_charts(r, out, presets):
    p, paths = r["proposed"], []
    s = p["scenarios"].get("permitted")
    if not s:
        return paths
    for mid, m in s["members"].items():
        chems = [c for c in m["chemicals"] if c["cancer_risk"]]
        if not chems:
            continue
        for preset in presets:
            top = chems[:PRESETS[preset]["top_n"]]
            fig = bars(preset, f"What {short_name(p['name'], 26)} could add",
                       f"{who(r, mid)}{per_million(m['cancer_risk'])} in a million at the permitted maximum, "
                       f"{p['operating_start'][:4]}-{p['operating_end'][:4]}, staying until {m['stays_to'][:4]}.",
                       FOOT_PROPOSED, [short_name(c["chemical"], 44) for c in top],
                       [c["cancer_risk"] * 1e6 for c in top],
                       [f"{per_million(c['cancer_risk'])} in a million" for c in top], PROPOSED_FILL, hatch=PROPOSED_HATCH)
            paths += save(fig, out, f"proposed-cancer-by-chemical-{mid}", preset)
    return paths


def render(r, out, formats):
    # Matplotlib stamps PDFs with the clock time unless told otherwise, and the manifest
    # hashes them: the same inputs on the same day must give the same files.
    day = dt.date.fromisoformat(r["generated"])
    os.environ["SOURCE_DATE_EPOCH"] = str(int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()))
    presets = [k for k in PRESETS if any(k == f or k.startswith(f + "-") for f in formats)]
    paths = []
    if r["history"]:
        paths += history_charts(r, out, presets)
    if r["proposed"]:
        paths += proposed_charts(r, out, presets)
    return paths
