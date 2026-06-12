# 0010 — Rename product NAI → KAI

Date: 2026-06-03
Status: locked (transition window open; legacy NAI paths still serve for 30 days)

## Why

- Original name derived from a personal source (girlfriend's name). Future
  third-party-claim risk if relationship sours.
- "KAI" reads as a clean given name (better for the "your AGI companion"
  positioning); "NAI" reads as an acronym (more institutional, less personal).
- Pre-launch is the cheapest moment ever to rename: 1 paying customer
  (refunded), 0 published marketing, ~0 inbound links.

## Scope renamed (user-facing)

- All HTML/CSS/JS in `backend/app/static/nai/` — page titles, H1 brand, copy
- Stripe product names (via API): NarAI Pro/Max/Ultra → KAI Pro/Max/Ultra
  (price IDs unchanged — `STRIPE_PRICE_*` env vars stable)
- Chat router system prompt (`services/nai_brain/system_prompt.py`):
  "You are NAI" → "You are KAI"
- Launch blog post: `outputs/marketing/launch/nai_launch_founder_origin.md`
  → `kai_launch_founder_origin.md`, all body content sed'd
- New canonical domain `kai.wheellsverse.com` (Cloudflare DNS CNAME → same tunnel)
- New canonical UI path `/kai-ui/` (mounted alongside `/nai-ui/`)
- New canonical API prefix `/kai/` (router dual-mounted with `/nai/`)
- CORS_ORIGINS includes both domains
- STRIPE_SUCCESS_URL / CANCEL_URL / BILLING_PUBLIC_UPGRADE_URL repointed to kai.*

## Scope NOT renamed (internal)

Refactor risk > benefit during launch window:

- `routers/nai.py` filename — module name only, no user impact
- `services/nai_brain/` filename — same
- `services/router/spend_tracker.py` env var names `NAI_MAX_*` — operational
- launchd plist `com.wheellsverse.nai` — daemon ID, rename risks broken restart
- log paths `~/Library/Logs/wheellsverse/nai.*.log` — operational
- Database schema — no `nai_*` tables exist; nothing to do
- Static dir filename `backend/app/static/nai/` — served at both `/kai-ui/`
  and `/nai-ui/`, dir name is invisible to users
- Git branch `feat/kdp-fillers` — name is operational

## Transition mechanics

| Surface | Old | New | Bridge |
|---|---|---|---|
| Domain | nai.wheellsverse.com | kai.wheellsverse.com | Cloudflare Page Rule 301 (created, currently DISABLED until cloudflared reloads with new ingress) |
| UI path | /nai-ui/ | /kai-ui/ | Both mounted; same files |
| API path | /nai/ | /kai/ | Router dual-mounted under both prefixes |
| CORS | nai origin | kai origin | Both whitelisted |
| Stripe products | NarAI Pro/Max/Ultra | KAI Pro/Max/Ultra | Same price IDs (no env change needed) |
| Chat persona | "I am NAI" | "I am KAI" | Hard cutover at restart |

Both `nai.*` and `kai.*` resolve to the same backend during the transition.
Drop nai support after 30+ days of clean redirect logs.

## Operator follow-ups (not autonomous)

1. **`sudo launchctl kickstart -k system/com.cloudflare.cloudflared`** — picks
   up the new ingress so `kai.wheellsverse.com` actually serves
2. After step 1, re-enable Page Rule
   `d46101e355c672be924fce57d8dbcb0f` via API (atomic, ~1s):
   `PATCH /zones/{ZID}/pagerules/{ID}  {"status":"active"}`
3. Supabase dashboard → Auth → Email Templates → replace NAI with KAI in:
   Confirm signup, Magic link, Reset password
4. Stranger-on-phone test (STEP 11 of the Stage 8 runbook)

## Proof / verification

- 157/157 backend tests still pass after dual-mount + sed (Stage 8 didn't
  touch test surface)
- Local endpoints: `/kai-ui/pricing.html` 200 with title "KAI", `/nai-ui/`
  still 200 (transition compat), `/kai/conversations` 401, `/nai/conversations`
  401
- CORS preflight: kai origin → ACAO=kai, nai origin → ACAO=nai, evil →
  no ACAO header
- Stripe API verify: `prod_ULrJJvqbrwk8Yn = 'KAI Pro'`, `prod_ULrJw8YFLL87mI
  = 'KAI Max'`, `prod_ULrJ6GwNtaY0cS = 'KAI Ultra'`
- 0 NAI brand strings in `backend/app/static/nai/*.html|.js|.css`
- 0 NAI strings in `outputs/marketing/launch/kai_launch_founder_origin.md`

## Out of scope (future)

- Internal Python module renames (routers/nai.py → routers/kai.py): big diff
  for zero user impact. Schedule when no other launch pressure.
- Buying a dedicated TLD (kai.ai etc): post-revenue.
- Renaming launchd plist + log paths: cosmetic; do during a planned
  daemon-down window.
