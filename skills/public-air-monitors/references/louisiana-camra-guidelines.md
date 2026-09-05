# Louisiana CAMRA Guidelines for Public Air Monitor Data

**This is not legal advice.** It is a practical usage discipline distilled from the statutory
text, written so that `bayou:public-air-monitors` output stays in a defensible, lawful lane by
default. Consult an attorney before any enforcement-adjacent use of this data.

## What the law is

The **Community Air Monitoring Reliability Act (CAMRA)** — SB 275 / **Act 411 of 2024** —
codified at **La. R.S. 30:2383.1 et seq.** (Chapter 16-A of Title 30). Passed in response to the
spread of low-cost community sensor networks (PurpleAir, AirBeam/AirCasting, industry-funded
"fenceline" networks) being used to allege pollution violations against Louisiana facilities.

Key provisions:

- **R.S. 30:2383.5** — A "community air monitoring program" that wants its data to be legally
  usable must use EPA **Federal Reference Method (FRM) / Federal Equivalent Method (FEM)**
  instruments per **40 CFR Parts 50 and 58** for criteria pollutants (the NAAQS pollutants: PM2.5,
  PM10, ozone, NO₂, SO₂, CO, Pb), and EPA-approved test methods for air toxics. PurpleAir,
  AirBeam, and similar low-cost optical sensors **do not meet this bar** — they are not FRM/FEM
  instruments.
- **R.S. 30:2383.9** — Any release or public communication of monitoring data must include
  "clear explanations of data interpretation, appropriate context, … applicable or comparable
  ambient air standard, data limitations, and relevant uncertainties." This is an affirmative
  disclosure duty, not just a nice-to-have.
- **R.S. 30:2383.10** — Data from a non-compliant monitor **"cannot be used by itself to
  demonstrate that a stationary source is in violation"** of environmental law or a permit, and
  cannot serve as the basis for an enforcement action or a citizen suit under the Louisiana
  Environmental Quality Act.
- **Trigger**: the restrictions attach when data is collected or used **"for the purpose of
  alleging a violation or noncompliance"** by a specific regulated source. Purely informational,
  research, or investigative use — not framed as a violation allegation — is the intended lawful
  space this skill operates in.
- **Penalties**: up to **$32,500 per day** of noncompliance ($1,000,000/day for intentional
  violations) — assessed against whoever operates the non-compliant "community air monitoring
  program," not against a one-off researcher pulling public API data, but the exposure scales
  with how the data is *used and represented*, so treat the trigger language as the operative
  line regardless of who's asking.
- **Status**: a federal First Amendment lawsuit (Public Citizen / Environmental Integrity
  Project et al. v. Louisiana officials, filed 2024) challenging CAMRA is **pending, no
  injunction as of early 2026** — the statute is live and should be treated as binding until
  that changes. Check `bayou:la-rs-search R.S. 30:2383` for the current statutory text and
  `bayou:pacer-case-search` / `bayou:doj-sec-search` for litigation status if it matters to the
  task at hand.

## Green / Yellow / Red usage lanes

| Lane | Use | Examples |
|---|---|---|
| **🟢 Green — do freely** | Investigative / lead-generation use that doesn't allege a specific violation | Find which public sensors exist near a facility; reconstruct an incident timeline (when did PM rise, relative to a reported release); corroborate plume direction/timing using the forensic stack (`wind-history`, `firms-active-fire`, `satellite-imagery`); identify **monitoring gaps** (no public sensor near a fenceline community — itself a finding worth raising); inform the public, journalism, or academic research; use the data to build a case for **asking LDEQ or EPA to deploy or check their own FRM/FEM monitors** or open an investigation. |
| **🟡 Yellow — allowed, with mandatory context (R.S. 30:2383.9)** | Publishing the actual numbers, or comparing them to an ambient standard, **as context** rather than a legal conclusion | Publishing a chart of corrected PM2.5 readings with the uncertainty/correction/method stated; saying "this reading, if accurate, would exceed the 24-hr PM2.5 NAAQS of 35 µg/m³" **framed as a comparison, with the low-cost-sensor caveat attached** — not as an assertion that the facility is in violation. |
| **🔴 Red — do not do this** | Anything that uses non-FRM/FEM data **by itself** as proof of a violation, or as the evidentiary basis of enforcement | Stating or implying "[Facility] violated its permit / the Clean Air Act / the NAAQS" based on PurpleAir/OpenAQ data alone; using this data as the cited basis for a citizen suit filing or a formal enforcement complaint; omitting the uncertainty/correction/limitations disclosure when presenting numbers publicly. |

**Rule of thumb this skill follows:** frame every finding as "this data supports asking someone
with a real monitor to look" rather than "this data proves what happened." If the user wants to
move from the Yellow lane toward anything enforcement-adjacent, flag that explicitly and suggest
they get counsel and/or a real FRM/FEM reading (AirNow, or ask LDEQ to deploy one) before relying
on this data as an assertion of fact.

## Required disclosure block

Append this (verbatim or lightly adapted to the specific output) to **every**
`bayou:public-air-monitors` result that discusses a specific facility, sensor reading, or
event:

> **Data source & limitations:** Reading(s) sourced from [PurpleAir / OpenAQ / AirNow], a
> [community-operated low-cost sensor / aggregator / EPA reference monitor], retrieved
> [date]. [If PurpleAir/low-cost: "EPA correction (Barkjohn et al. 2021) applied to raw
> readings; corrected values still carry meaningfully higher uncertainty than a reference
> monitor."] This sensor is **not** an EPA Federal Reference Method or Federal Equivalent Method
> instrument under 40 CFR Parts 50/58, except where explicitly sourced from AirNow. Under
> Louisiana's Community Air Monitoring Reliability Act (La. R.S. 30:2383.1 et seq.), data from
> non-FRM/FEM monitors cannot by itself demonstrate that a stationary source is in violation of
> environmental law or a permit, and is not offered here as such. This information is provided
> for public awareness, investigative, and research purposes, and to support a request for
> official monitoring or investigation by LDEQ/EPA — not as a legal conclusion.

## Notes on secondary networks

If `references/networks.md`'s secondary networks (AirBeam/AirCasting, Sensor.Community, WAQI)
are ever used, the same lanes and disclosure apply — CAMRA's restriction is about the
**instrument's certification status**, not the specific vendor. Worth noting: **HabitatMap**
(AirBeam/AirCasting's operator) is itself a plaintiff in the pending First Amendment challenge
to CAMRA, which is useful context if the user is researching the law's reception, but doesn't
change the usage discipline above.
