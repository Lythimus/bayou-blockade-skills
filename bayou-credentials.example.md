# Bayou Skills — Service Credentials (TEMPLATE)

Copy this file to `~/.claude/bayou-credentials.md` and fill in real values.

**The real file lives outside this repo, at `~/.claude/bayou-credentials.md`.** Skills read
it from that absolute path with the Read tool. Do not move it into the repo — keeping it
outside the working tree means a stray `git add -A` cannot commit it. This template is the
only credential file that belongs under version control.

Every entry below is optional. Skills that need a key say so and fail with a clear message
if the entry is missing; the rest work with no credentials at all.

---

## NRC ADAMS Public Search API

Used by `bayou:nrc-adams-search`. Free account.

1. Go to the NRC API portal and sign in
2. Products → "ADAMS Public Search API (ADAMS APS API)" → view subscription key

Registration email: <email>
Password: <password>

NRC_ADAMS_KEY: <subscription-key>

---

## PACER (Public Access to Court Electronic Records)

Used by `bayou:pacer-case-search` **only as a paid fallback** — free CourtListener/RECAP
search runs first. Billable at $0.10/page (waived under $30/quarter). The skill confirms
cost with the user before any billable call.

Auth endpoint: https://pacer.login.uscourts.gov/services/cso-auth
PCL API base: https://pcl.uscourts.gov

Username: <username>
Password: <password>

---

## OSHA / DOL Data Portal API Key

Used by `bayou:osha-inspections`. Free. Register at https://dataportal.dol.gov/

Base URL pattern: https://apiprod.dol.gov/v4/get/{agency}/{endpoint}/json?X-API-KEY=KEY&PARAMS

DOL_API_KEY: <key>

---

## EPA CAMPD (api.data.gov)

Used by `bayou:epa-campd-search`. Register at https://api.data.gov/signup/ (free, instant).
`DEMO_KEY` works for up to 30 req/hour without registration.

CAMPD_API_KEY: <key>

---

## OpenSky Network API

Used by `bayou:adsb-flight-search` and `bayou:exec-travel-monitor`. Free account.
OAuth2 client-credentials grant (HTTP Basic auth is deprecated).

Token endpoint:
https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token

Rate limit: 4,000 credits/day (daily allowance, not remaining balance). Live remaining
count comes back in the rate-limit response header.

OPENSKY_CLIENT_ID: <client-id>
OPENSKY_CLIENT_SECRET: <client-secret>

---

## ADSB Exchange (RapidAPI) — paid fallback

Used by `bayou:adsb-flight-search` when OpenSky has gaps or the aircraft is owner-blocked.
Billable per call — confirm with the user before use, same as PACER.
Subscribe at https://rapidapi.com/ (ADSB Exchange, paid tiers), then copy the
`X-RapidAPI-Key` value.

RAPIDAPI_KEY: <key>

---

## Copernicus Data Space (dataspace.copernicus.eu)

Used by `bayou:satellite-imagery` for true 10 m date-specific Sentinel-2/Sentinel-1 crops
via the Sentinel Hub Process API. Free account, OAuth2 client-credentials grant.

Token endpoint:
https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
Process API: https://sh.dataspace.copernicus.eu/api/v1/process

CDSE_CLIENT_ID: <client-id>
CDSE_CLIENT_SECRET: <client-secret>

---

## NASA FIRMS (firms.modaps.eosdis.nasa.gov)

Used by `bayou:firms-active-fire` for satellite active-fire / thermal-anomaly detections
(VIIRS 375 m / MODIS 1 km) with fire radiative power. Free instant map key.

Request at https://firms.modaps.eosdis.nasa.gov/api/map_key/ (enter email; key issued on
the page and by email). Limit 5,000 transactions / 10 min.
Check status: https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=<key>

FIRMS_MAP_KEY: <key>

---

## PurpleAir (api.purpleair.com)

Used by `bayou:public-air-monitors` for community PM1/2.5/10 sensor readings. Free
self-serve key. **Forensic/investigative use only** — see
`skills/public-air-monitors/references/louisiana-camra-guidelines.md` before citing this
data as evidence of anything (Louisiana CAMRA restricts non-FRM/FEM monitor data).

Issued at https://develop.purpleair.com/

PURPLEAIR_API_KEY: <key>

---

## OpenAQ (api.openaq.org, v3)

Used by `bayou:public-air-monitors` as a secondary/cross-check network aggregating
low-cost + reference monitor PM/gas data. Free self-serve key.
v1/v2 retired 2025-01-31 — v3 only.

Register at https://explore.openaq.org/register

OPENAQ_API_KEY: <key>

---

## AirNow (airnowapi.org)

Used by `bayou:public-air-monitors` for EPA regulatory-grade FRM/FEM reference-monitor
data — the Louisiana-CAMRA-permitted data class. Free self-serve key.

Register at https://docs.airnowapi.org/account/request/

AIRNOW_API_KEY: <key>

---

## OCR Server (SSH)

Used by `bayou:document-ocr` as the default backend (`OCR_BACKEND=remote`, or `auto` falling
through to it) — Surya geometry runs locally, but the olmOCR 2 / Chandra 2 readers run on a
separate GPU box over SSH so the pipeline never needs local model weights for that tier. Provision
the box per `skills/document-ocr/references/remote-setup.md`; `lib/probe.sh` checks it's ready
before each run.

`OCR_SSH_HOST` is an `~/.ssh/config` `Host` alias, not a raw hostname/user/key path — that lets
`~/.ssh/config` carry the identity file and any jump host, and keeps key material out of this
markdown file.

OCR_SSH_HOST: <ssh-config-host-alias>
OCR_REMOTE_ROOT: /home/<user>/ocr

---

## Azure Document Intelligence

Used by `bayou:document-ocr --azure` as an opt-in escalation — `prebuilt-layout` is the only real
per-word-confidence and checkbox-state source in the whole OCR stack. Billable (~$10/1000 pages);
the skill confirms page count and estimated cost with the user before submitting anything.

Create the resource (`az cognitiveservices account create ... --kind FormRecognizer --sku S0`),
then list its keys — see `skills/document-ocr/SKILL.md`'s `--azure` section for the exact `az`
commands.

AZURE_DOCINTEL_ENDPOINT: https://<name>.cognitiveservices.azure.com/
AZURE_DOCINTEL_KEY: <key>

---

## Kit.com (api.kit.com/v4)

Used by `bayou:kit-dissemination` to draft (and, only on separate explicit
confirmation, send) email broadcasts to an existing subscriber list. Free plan works
for direct API calls. Get a key from the Kit dashboard: Settings → Developer →
API Keys.

KIT_API_KEY: <key>

---

## Notes

- Keep the real file private and outside version control.
- Rotate any key that has been pasted into a shared transcript, issue, or chat log.
- PACER, ADSB Exchange, and Azure Document Intelligence are the only billable services here; all
  three require explicit user confirmation before a call is made.
- Kit broadcasts are not billable but are the one credential here that can send
  externally-visible communication — `bayou:kit-dissemination` gates sending behind a
  separate explicit confirmation, same discipline as the billable ones.
