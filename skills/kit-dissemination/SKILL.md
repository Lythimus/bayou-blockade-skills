---
name: kit-dissemination
description: Use only when explicitly asked to draft or manage a Kit.com (formerly ConvertKit) email broadcast for a campaign — pushing a case-status update, calling for community testimony/experience reports, or similar dissemination to an existing subscriber list. Always creates DRAFT broadcasts; sending is a separate, explicitly-confirmed action. Requires an API key.
allowed-tools: Bash, Read, AskUserQuestion
---

# Kit.com Email Dissemination

Draft (and, only on separate explicit confirmation, send) email broadcasts through a Kit
creator account. Built for pushing campaign updates and soliciting community
testimony/experience reports from an existing list — e.g. "tell me what you experienced
during the flaring event" outreach that feeds a neighbor-impact log.

This is the **most other-visible** skill in the bayou toolkit: a completed send reaches
every real subscriber and can't be recalled. Treat "draft a campaign" and "send the
campaign" as two different requests, never one.

## System reference

| Field | Value |
|---|---|
| API base | `https://api.kit.com/v4` |
| Auth header | `X-Kit-Api-Key: <key>` |
| Docs index | `https://developers.kit.com/llms.txt` |
| Broadcasts | `POST/GET https://api.kit.com/v4/broadcasts`, `GET/PUT /v4/broadcasts/{id}` |
| Tags | `GET/POST https://api.kit.com/v4/tags` |
| Subscribers | `GET https://api.kit.com/v4/subscribers` |

An official Kit MCP connector also exists (`claude.ai Kit.com` in Claude's connector
list) and is the preferred path when available — it's scoped/OAuth-based rather than a
raw key. It currently gates most calls behind a paid Kit plan; on a free-plan account,
fall back to direct API calls as documented here. Re-check the MCP connector first if
it's connected — prefer it over raw `curl` when it actually works.

---

## Authentication

Read `~/.claude/bayou-credentials.md` for `KIT_API_KEY`.

If it's not there yet:
1. Tell the user a Kit API key is needed — Kit dashboard → Settings → Developer →
   API Keys (v4 keys look like `kit_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`).
2. Once provided, save it to `~/.claude/bayou-credentials.md` under a
   `## Kit.com (api.kit.com/v4)` section as `KIT_API_KEY: <value>`, matching the pattern
   of every other credential in that file. That file lives outside the plugin repo
   specifically so it never gets committed.
3. If a key arrives pasted directly into chat, still offer to save it to the
   credentials file (better than it only existing in transcript history) — but don't
   insist if the user says they're not worried about the exposure; it's their account.

Verify a key works with a cheap read before drafting anything:
```bash
curl -s --request GET --url https://api.kit.com/v4/account --header "X-Kit-Api-Key: $KIT_API_KEY"
```

---

## Hard rule: draft-only unless sending is explicitly requested and re-confirmed

Every broadcast this skill creates or updates must have `send_at: null` and
`public: false` unless the user has, in the same request, unambiguously asked for it to
go out (not "make a campaign," not "go ahead" following a draft-creation ask — those
mean *create the draft*). If there's any doubt which one is meant, ask.

Sending is covered at the bottom of this file as a distinct, separately-gated step. Do
not fold it into drafting even when asked to do both — confirm the copy and audience
scope after the draft exists, before flipping it to send.

---

## Step 1: Discover the audience and existing voice

```bash
curl -s --request GET --url https://api.kit.com/v4/account --header "X-Kit-Api-Key: $KIT_API_KEY"
curl -s --request GET --url https://api.kit.com/v4/tags --header "X-Kit-Api-Key: $KIT_API_KEY"
curl -s --request GET --url 'https://api.kit.com/v4/broadcasts?per_page=5' --header "X-Kit-Api-Key: $KIT_API_KEY"
curl -s --request GET --url 'https://api.kit.com/v4/email_templates?per_page=100' --header "X-Kit-Api-Key: $KIT_API_KEY"
```

- `account` gives the sending address and plan (free plan caps at 10,000 subscribers).
- `tags` shows whether prior campaigns got their own tag (this account tags per-issue,
  e.g. a petition-specific tag) — a pattern worth continuing if this is an ongoing
  thread rather than a one-off.
- Pulling a couple of recent `broadcasts` (add `?include=content` for one, sparingly —
  it's the full HTML body) tells you the account's actual voice/format before you
  improvise a new one. Match it rather than inventing a house style from scratch.
- `email_templates` returns each template's `id`, `name`, `is_default`, `category`.
  **The category matters and gates what you can do via the API — see the hard rule
  below before picking one.** For the Bayou Blockade account: "Story Basic" (id
  `4210942`, category "Starting point") is the visual style actually used for real
  sends; "Text only" (id `4210768`, category "Classic", the account default) is what
  API-drafted content ends up using in practice, for the reason below.

### Hard rule: "Starting point" templates reject explicit `content`

Confirmed directly: `POST`/`PUT /v4/broadcasts` with a `"Starting point"`-category
`email_template_id` (e.g. Story Basic) **and** a non-empty `content` field fails with
`"Starting-point email template cannot be combined with explicit content."` Those
templates are meant to be filled in through Kit's visual block editor in the browser —
the API can select them, but only when you're *not* also pushing your own HTML.

What actually works, and is how every hand-authored broadcast in this skill's history
was built: **keep `email_template_id` on a `"Classic"`-category template (e.g. "Text
only") and write content HTML that copies the target visual style yourself** —
color-blocked sections, serif `<h2>` headlines, an `<a class="email-button">` CTA. Pull
a real, already-sent Story Basic broadcast's content via `GET /v4/broadcasts/{id}`
first and copy its actual markup/CSS rather than guessing — the block structure is
`<div class="ck-section">` → centered `<table max-width:640px>` → colored `<td
bgcolor="...">` → `<div class="ck-inner-section">` → your content. It renders
identically to a real Story Basic email; Kit's dashboard will just label the template
"Text only" rather than "Story Basic," since that label reflects what's *selectable*
via API, not what the email visually is.

**No image/asset upload endpoint exists in the v4 API** (checked the full docs index —
nothing under templates, broadcasts, or any other resource). Every image in this
account's real broadcasts lives on `embed.filekitcdn.com`, reachable only via the web
editor's drag-and-drop uploader. If a campaign should include a specific image (a
satellite photo, an incident photo, etc.), the content can be built and drafted
end-to-end via API with an `<img>` block left for later, but actually inserting a new
image requires the user to drop it into Kit's browser editor — say so plainly, and
don't try to work around it with a `file://` path or a giant base64 data URI (email
clients unreliably support data URIs, and it bloats the HTML).

## Step 2 (optional): Create a campaign tag

If this is the start of an ongoing thread (not a single blast), consider tagging it so
replies/interested subscribers can be segmented for follow-ups later:

```bash
curl -s --request POST --url https://api.kit.com/v4/tags \
  --header "X-Kit-Api-Key: $KIT_API_KEY" --header 'Content-Type: application/json' \
  --data '{"name": "Campaign Name Here"}'
```

Skip this for a single general update — it adds bookkeeping only worth the ongoing case.

## Step 3: Draft the copy

- Ground every factual claim in verifiable, already-public material. Don't narrate
  private conversations, agency-internal negotiation details, or unverified case
  theory — an email blast is a bigger, more permanent disclosure than a social-media
  reply. If the working repo has a source-document policy (check its `CLAUDE.md`), the
  same discipline applies here even though this is marketing copy, not a filing.
- If the ask is for community experience reports (e.g. "what did you notice during the
  flare event"), be specific about what to include and honest about the purpose: what
  timeframe, what kind of details, whether medical care was sought, and whether it's
  okay to follow up — and don't imply litigation is happening if none has been filed.
- Keep it at "general update + call to action" altitude, not a legal argument.

## Step 4: Create the broadcast as a draft

```bash
curl -s --request POST --url https://api.kit.com/v4/broadcasts \
  --header "X-Kit-Api-Key: $KIT_API_KEY" --header 'Content-Type: application/json' \
  --data @broadcast.json
```

Write the JSON body to a scratch file first — the HTML content has embedded quotes and
is unwieldy to inline safely in a shell string.

Required/relevant fields:

| Field | Value for a draft |
|---|---|
| `content` | HTML body — see the "Starting point" hard rule above before setting `email_template_id` alongside this |
| `description` | Internal-only label (subscribers never see this). **Undocumented 255-character limit** — over that, the API returns a useless generic `"There has been an error saving your changes."` (HTTP 422) with no field name, so a bad `description` looks identical to a bad `content` or malformed request. If a save fails for no apparent reason, check `description` length first before debugging the HTML. |
| `public` | `false` |
| `published_at` | Any ISO8601 timestamp — the field is required by the API but only meaningful when `public: true` |
| `send_at` | `null` — **this is what keeps it a draft** |
| `preview_text` | Inbox preview line |
| `subject` | Subject line |
| `subscriber_filter` | See below |
| `email_template_id` | Pick a real template from Step 1's `email_templates` call — don't omit this and let it fall back to the account default, which may just be "Text only" |

To change the template on an already-created draft rather than recreating it:
```bash
curl -s --request PUT --url https://api.kit.com/v4/broadcasts/{id} \
  --header "X-Kit-Api-Key: $KIT_API_KEY" --header 'Content-Type: application/json' \
  --data '{"email_template_id": 4210942}'
```
The API re-wraps the existing `content` into the new template's HTML structure — always
re-review the result, since a template swap can change how paragraphs/spacing render.

### `subscriber_filter` gotchas (from direct experience, not just the docs)

- `[]` — targets **all** subscribers; the API confirms it defaults this way when the
  array is empty. This is the simplest form and what a general campaign update usually
  wants.
- `[{"all":[{"type":"tag","ids":[123]}],"any":null,"none":null}]` — scopes to one or
  more tags. Use `any`/`none` for OR/NOT logic. Only a single filter group is supported.
- A `"type": "segment"` filter **requires a non-empty `ids` array** — the API rejects
  `{"type":"segment","ids":[]}` with `` `ids` required for `segment` filter ``. Don't
  reach for `segment` to mean "everyone"; use `[]` instead.

A successful create returns `"status":"draft"` and the assigned `id` — report both back
to the user along with subject, preview text, and audience scope.

## Step 5: Hand back for review — do not proceed further unasked

Tell the user: the broadcast id, that its status is `draft`, that `send_at` is `null`,
and where to review it in the Kit dashboard. Flag anything in the copy that's doing
factual or legal work (a characterization of an agency finding, a causal claim, etc.) so
they specifically check it before anything goes out. Stop there.

---

## Sending — separate, explicit, re-confirmed action only

Only proceed if the user's request to send is unambiguous and given as its own ask
(e.g. after they've had a chance to review the draft). Before doing it:

1. Confirm the copy has actually been reviewed (in the dashboard, not just re-approved
   verbally against a summary).
2. Confirm audience scope explicitly — "all subscribers" vs. a specific tag — and, if
   the account has more than a trivial subscriber count, say the number out loud before
   acting.
3. Check `https://developers.kit.com/api-reference/broadcasts/update-a-broadcast.md`
   for the current update/send mechanism before calling it — this skill was built and
   tested through draft-creation only; the send path hasn't been exercised yet, so
   verify rather than assume the shape.
4. This is irreversible and visible to others exactly like sending a Slack message or
   pushing code others will see — confirm, then act, don't batch it with drafting.

---

## Pairing with other bayou skills

- `bayou:toxic-truth-teller-style` — apply only if the user explicitly asks for that
  voice by name; don't assume it for every campaign.
- Project-level `neighbor-impact-log.md`-style documents (where they exist) are a
  natural destination for experience-report replies this skill solicits — mention that
  connection to the user rather than trying to auto-file replies anywhere.

## Known account context — verify via Step 1, don't trust this blindly

- Don't assume plan tier or subscriber limits; call `get_current_account` (Step 1)
  each time rather than hardcoding a number here.
- Previously-sent campaigns on this account visually use the Story Basic look —
  colored section blocks, serif headlines, inline images, CTA buttons — built through
  the browser editor. Anything drafted through this skill should match that, using
  the Classic-template workaround above, not the bare unstyled paragraph output you
  get by omitting structure.
- Prior campaigns (e.g. a petition effort) got their own tag rather than reusing a
  general list — a pattern worth continuing for ongoing threads.

$ARGUMENTS
