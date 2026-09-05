# Bayou Blockade Profile (TEMPLATE)

Copy this file to `~/.claude/bayou-profile.md` and fill in real values. **The real file
lives outside this repo, at `~/.claude/bayou-profile.md`.** `bayou:nextdoor-campaign`
reads it from that absolute path. Do not move it into the plugin repo — keeping it
outside the working tree means a stray `git add -A` cannot commit it. This template is
the only profile file that belongs under version control.

This holds the personal-narrative material that makes a Nextdoor post read as a real
neighbor's voice rather than a generic advocacy blast: family health conditions,
geographic exposure, ancestral/cultural connection, and the argumentative angles you're
personally comfortable putting in front of your community. Treat it with the same care
as an API credential — it is more sensitive, not less, since it's about people, not a
service account.

Every section is optional. The skill uses only what's here; leave a section blank
(or delete it) if it doesn't apply, rather than inventing something to fill it in.

---

## Core Identity

Where you live (town/parish — not a street address): <e.g. "Norco, St. Charles Parish">
How long you/your family have lived here: <e.g. "three generations">
Your relationship to the community (resident, parent, business owner, etc.): <placeholder>

---

## Health Vulnerabilities

Personal or family health conditions you're comfortable citing publicly (e.g. asthma,
cancer history, a family member's condition): <placeholder — real posts have named a
specific family member's cancer history; only include what you'd say to a neighbor's
face>

---

## Geographic & Environmental Exposure

Specific facilities, waterways, or hazards near your home that you can speak to
firsthand (what you can see, smell, or hear from your property): <placeholder>

---

## Ancestral & Cultural Connection

Family or community history tying you to this specific place (multi-generational
residence, historic sites, cultural practices like fishing/hunting grounds):
<placeholder>

---

## Faith & Congregation

Presence, affiliation, and household affiliation are kept as separate fields on purpose — they
carry different weight in a filed comment, and only one of them is a claim about *your own*
beliefs. Leave any of these blank rather than invent a value; do not upgrade "attend" into
"member," and never guess which congregation if more than one shares a name.

Congregation name and town/parish: <placeholder>
Your own affiliation — member, attend but not a member, none: <placeholder — attending is not
membership; state which one this actually is>
Household members' affiliation (e.g. spouse is a member) and how long: <placeholder>
How often you are physically present, and roughly how long each time: <placeholder>
Family members interred in its cemetery or a nearby cemetery: <placeholder>
Approximate distance from the congregation, and that cemetery, to the facilities this campaign
names: <placeholder>
What you're comfortable being called publicly — "a member," "someone who attends," "my wife's
parish," or nothing at all: <placeholder>

---

## Opposition Targets

Companies, agencies, or officials this campaign is likely to name, and any personal
history with them worth noting (a town hall you attended, a statement you heard
firsthand): <placeholder>

---

## Argumentative Angles

Angles you're personally willing to make publicly (health, property value, safety,
environmental justice, wildlife/heritage, fiscal) — and any you'd rather this skill
avoid even if the research supports them: <placeholder>

---

## Notes

- Keep the real file private and outside version control.
- This skill pulls only the narrative angles meant for a public Nextdoor post — it will
  not echo this file's full content verbatim into a generated campaign file.
- If you're not comfortable with a detail appearing in a public post even in
  paraphrased form, don't put it in this file.
