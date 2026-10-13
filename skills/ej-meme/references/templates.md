# Template guide: pick by the move, not the meme

Start from what the meme has to *do* (the rhetorical move), then pick the template whose
picture already does that emotionally. The caption should only have to supply the facts.
The picture carries the feeling: the side-eye, the smirk, the sweating.

The entries below are the ones checked so far. They are **a starting point, not the menu.**
Before settling, search for something fresher or more exact (see "Finding other templates").
The old campaign CSVs leaned on the same dozen formats until they stopped landing.

Box roles were checked by rendering `BOX 1..N` on each memegen template. Swapped panels
are the most common silent failure (the old Running Away Balloon rows), so follow the role
order exactly. `scripts/templates.py show <id>` prints the roles for any entry here.

**Backends.**
- `memegen`: renders free with no account.
- `memegen-custom`: the imgflip blank image used as a memegen background, with top/bottom
  text. Works only where the entry says custom-ok.
- `imgflip`: needs `IMGFLIP_USERNAME` / `IMGFLIP_PASSWORD` in `~/.claude/bayou-credentials.md`.

**Recognizability.** Nextdoor skews older and local. A format a 60-year-old has seen on
Facebook beats a sharper one from last month. Every entry is rated high or medium. Use
medium only when the picture explains itself without knowing the meme.

---

## Finding other templates

```bash
scripts/templates.py search fire smoke       # curated + memegen (~200) + imgflip top 100
scripts/templates.py search ''               # browse everything
scripts/templates.py move bum-deal           # curated entries for one move
scripts/templates.py show 309868304          # box count, roles, blank image
```

imgflip's list is its current top 100 by usage, which is a decent proxy for what people
recognize this year. memegen's keywords are sparse, so search by the picture ("dog",
"button", "bus") as well as the feeling.

**Before using a template that isn't below:**
1. **Recognizable?** Would a neighbor in their 60s have seen it? If you have to explain the
   meme, pick another.
2. **Does the picture match the move?** The emotion in the image (smug, oblivious,
   panicked, betrayed) should be the emotion you want about the company.
3. **Know the boxes.** Render it once with `BOX 1`, `BOX 2`… and look at where each lands
   before writing captions. Note any text already printed on the image (Trade Offer's
   "i receive:", UNO's "or draw 25") so captions don't repeat it.
4. **Phone test.** Run qa.py on it. Some templates put text in tiny bubbles (Boardroom,
   Gru) that crush anything over 5 words.
5. **Punching direction.** The person in the photo stands in for the company or agency,
   never for residents or workers.

If it earns repeat use, add it to templates.json and this file, then run
`templates.py refresh`.

---

## Shrugs off a resident's lived harm

The strongest pattern in the memes the user chose. A real, sensory harm, and the company's
awkward non-reaction. Single box, almost no setup.

### Monkey Puppet (side-eye): `imgflip 148909805` (memegen-custom ok) · high
- **Box 1:** "<Company> when residents mention <specific harm>". Target ≤14 words.
- **Good:** "Acme Tanks when residents mention they wake up to chemical smells in the middle of the night"
- **Bad:** "Acme Tanks when residents cite AP-42 emission factor underestimates for floating-roof tanks".
  The harm has to be felt, not audited.

### Hide the Pain Harold: `harold` · imgflip 27813981 · high
- **Box 1:** the promise or claim. **Box 2:** the painful reality (optional).
- **Good:** "When Acme Tanks says they're installing air monitors but they only detect 20% of the pollution"
- **Bad:** a Harold where Harold is the resident. Harold is the company smiling through it.

## Causes the disaster and looks pleased

### Disaster Girl: `disastergirl` · imgflip 97984 · high
- **Box 1:** who, and the disaster ("<Company> after their 4th fire in 2 years").
  **Box 2:** optional, short.
- **Good:** "When you destroy 240 acres of wetlands while calling yourself environmentally friendly"
- **Bad:** using it for a hypothetical. The disaster should be real and sourced.

## Escalating alarm

### Panik Kalm Panik: `panik-kalm-panik` · imgflip 226297822 · medium
- **Boxes:** panik (the lived symptom) → kalm (the official explanation) → panik (why the
  explanation is worse). ≤8 words each.
- **Good:** "Chemical smell in your bedroom" / "It's just Acme Tanks venting tanks" / "IT'S ACME TANKS VENTING TANKS"
- **Bad:** three separate facts. Box 3 has to flip box 2.

## The bum deal, literally

### Trade Offer: `imgflip 309868304` (imgflip only) · medium
- **Box 1:** what the company gets. **Box 2:** what the community gets stuck with. The
  image already prints "i receive:" and "you receive:" above them, so don't repeat the
  labels. ≤8 words each. Box 3 sits at the bottom over the man's face; leave it blank.
- **Good:** "<$X> in tax breaks" / "an ammonia plant next door"
- **Bad:** abstract trades ("You receive: externalities"). The community's side must be
  something you can smell, see or pay.

### Two Guys on a Bus: `bus` · imgflip 354700819 · medium
- **Box 1:** left, the sad guy facing the rock wall: the fenceline residents' view.
  **Box 2:** right, the happy guy facing the scenery: the company's or shareholders' view.
- **Good:** "Living <sourced distance> from the tanks" / "Living in another state from the tanks"
- **Bad:** reversing the sides. The sad window is always the community.

## False choice

### Two Buttons: `ds` · imgflip 87743020 · high
- **Box 1:** left button, the cheap or self-serving option. **Box 2:** right button, the
  responsible option. **Box 3:** sweating guy, who is choosing (optional). ≤7 words a button.
- **Good:** "Pay the $90K fine" / "Fix the safety violations"
- **Bad:** buttons over 8 words. memegen rotates and shrinks button text, and long buttons
  became unreadable in the old renders.

### UNO Draw 25: `imgflip 217743513` (imgflip only) · medium
- **Box 1:** the card: just the reasonable fix (the card already prints "or draw 25"). **Box 2:** the guy holding a huge
  hand: the company.
- **Good:** "Put the monitor where people live" / "Acme Tanks"

### Drake: `drake` · imgflip 181913649 · high
- **Box 1:** top, rejected: the sensible option. **Box 2:** bottom, approved: what the
  company chose.
- **Bad:** making the sensible option long and the punchline short. Keep them parallel.

## Plan undermines itself

### Gru's Plan: `gru` · imgflip 131940431 · high
- **Boxes:** step 1 the promise → step 2 sounds fine → step 3 the catch → step 4 the catch
  repeated (Gru rereads it). ≤7 words each; the panels are small.
- **Good:** "Promise community monitoring" / "Show the gold-standard monitor" / "Install the
  cheap one" / "Install the cheap one"

### Boardroom Meeting: `imgflip 1035805` (imgflip only; 4 boxes) · high
- **Box 1:** the boss's question. **Boxes 2–3:** the answers the boss likes: what the
  company actually does (tiny bubbles: ≤3 words or they
  shrink past readable). **Box 4:** the honest suggestion; this
  speaker gets thrown out the window in the last panels, which take no text.
- **Bad:** 5 captions. imgflip has 4 boxes and silently dropped the fifth in an old render.

## Loophole logic

### Roll Safe: `rollsafe` · imgflip 89370399 · high
- **Box 1:** the problem that magically disappears. **Box 2:** the dodge.
- **Good:** "Can't have evacuation problems" / "If you don't acknowledge the neighborhood exists"

## Outrage vs. indifference

### Woman Yelling at Cat: `woman-cat` · imgflip 188390779 · high
- **Box 1:** the woman, left: the outraged fact. **Box 2:** the cat, right: the company's
  shrug.
- **Good:** "When you learn the neighborhood was locked behind gates every night into the
  1940s" / "The ammonia plant builds next door anyway". This row was filed as "Rick Dalton" but used
  this template's ID.

### But That's None of My Business (Kermit): `kermit` · imgflip 16464531 · high
- **Box 1:** the uncomfortable fact, deadpan. **Box 2:** "but that's none of my business"
  or a sarcastic aside.
- **Good:** "30% higher infertility in this corridor, but let's add more chemical plants"

## Escalating absurdity

### Galaxy Brain: `gb` · imgflip 93895088 · high
- **Boxes:** reasonable-sounding → worse → worse still → the company's actual claim,
  presented as "enlightened". ≤6–8 words each.
- **Good:** "Build on the hurricane coast" / "Destroy the wetlands that stop flooding" /
  "Increase pump capacity 5 times" / "Claim 'very minimal' flood impact"

## Betrayed priorities

### Distracted Boyfriend: `db` · imgflip 112126428 · high
- **Box 1:** the woman in red, left: what the company is chasing. **Box 2:** the
  boyfriend: the company or agency. **Box 3:** the girlfriend: what it's supposed to
  protect. 1–5 words each.
- **Good:** "profits" / "Acme Ammonia" / "community health"
- **Bad:** sentences on the labels. It's a labeling meme.

### Left Exit 12: `exit` · imgflip 124822590 · high
- **Box 1:** straight ahead, the responsible path. **Box 2:** the exit ramp, the swerve.
  **Box 3:** the car, who swerves.
- **Bad:** the old Exit_Ramp rows used the Change My Mind ID (129242436), which has 2
  boxes, so two captions vanished. Check the ID matches the name.

## Ignoring a crisis

### This Is Fine: `fine` · imgflip 55311130 · high
- **Box 1:** the crisis, concretely. **Box 2:** the reassurance (default "this is fine").
- **Bad:** a 16-word top box. The old ratepayer version rendered at 7px tall on a phone.

### Mother Ignoring Kid Drowning: `pool` · imgflip 252758727 · medium
- **Boxes:** the girl on her shoulders, what gets attention → the drowning kid, what's
  neglected → the mother, who's ignoring.

## Greenwash / mislabeling

### They're the Same Picture: `same` · imgflip 180190441 · high
- **Box 1:** left picture, the new green label. **Box 2:** right picture, the old dirty
  thing. **Box 3:** Pam (usually blank; the template already says the line).
- **Good:** "Acme Tanks' 'separate' permit" / "Acme Ammonia's permit"

### Scooby Doo Reveal: `reveal` · imgflip 145139900 · high
- **Boxes:** the mask (what it claims to be) → Fred (who's unmasking) → the real face
  (what it is) → Fred's reaction.
- **Good:** "Clean hydrogen" / "Neighbors reading the permit" / "Natural gas plant" / "I knew it"

### Is This a Pigeon?: `pigeon` · imgflip 100777631 · high
- **Box 1:** the guy, who's mislabeling. **Box 2:** the butterfly, the real thing.
  **Box 3:** "Is this <flattering label>?"

## Then vs. now / promise vs. reality

### Buff Doge vs. Cheems: `imgflip 247375501` (imgflip only) · medium
- **Box 1:** buff doge, the strong "then" or the ideal. **Box 2:** Cheems, the weak "now"
  or the reality. memegen's `cheems` is Cheems alone, not this.
- **Good:** "The state agency's job: protect communities" / "The state agency: calls
  residents' concerns 'unacceptable'"

### Waiting Skeleton: `imgflip 4087833` (memegen-custom ok) · high
- **Box 1:** "Waiting for <the promised thing>".

### Anakin and Padme: `right` · imgflip 322841258 · high
- **Boxes:** Anakin label → Padme label → Anakin's plan → Padme "…for <good thing>,
  right?" → Padme repeats "…right?"

## Collusion / blame

### Epic Handshake: `handshake` · imgflip 135256802 · high
- **Box 1:** left arm, party one. **Box 2:** right arm, party two. **Box 3:** the center,
  what they agree on.

### Spider-Man Pointing: `spiderman` · imgflip 110133729 · high
- **Boxes:** two parties, each saying the other is responsible.

## Plain assertion

### Change My Mind: `cmm` · imgflip 129242436 · high
- **Box 1:** the sign, one sentence. Use sparingly. It's an argument, not a joke.

---

## Templates to avoid for this audience

- **Surprised Pikachu** (155067746) was used ~10 times in the old CSVs, and the setup
  almost always needed background ("doesn't acknowledge X in permit applications"). It
  works only when both lines are concrete and the consequence is obvious.
- Anything relying on a specific TV quote the audience may not know (Weekend Update,
  Squidward window, 10 Guy).
- Political-figure templates (sad-biden, trump, etc.). They pull the thread into national
  politics, which Nextdoor restricts in the main feed (see tone-and-boundaries.md).
