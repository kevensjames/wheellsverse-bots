# KAI Omnipresent Holding OS — STAGING DEPLOYMENT RECORD

**Status: DEPLOYED TO ISOLATED STAGING AND HOSTED-VERIFIED. Production UNCHANGED.**

Deployed 2026-09-06 (03:29–03:35 UTC) on operator approval ("deploy all", 2026-09-05 23:27 EDT),
scoped to staging only. The production G3 gate was **not** treated as approved by that instruction and
remains open — see §7.

---

## 1. What was deployed

| Field | Value |
|---|---|
| Source SHA | `45aa5bd10b47cecac1f4faa06c56066486f0626f` (branch `feat/kai-cyber-operations`) |
| Worktree | `/Users/jhonwheeler/wheellsverse-cyberops`, clean at deploy time |
| Railway project | `kai-staging` · `0dcd21ec-1e1d-4236-9ba9-686b2d26a312` (environment `production` of the staging project) |
| App A service | `kai-appA-staging` · build `875ff5e0-7dc6-4e46-be01-b344db087119` · NIXPACKS · `uvicorn core.api:app` |
| App B service | `kai-staging` · build `f6165cad-d576-4e2e-9093-b9b3c91c56b6` · DOCKERFILE |
| App A URL | https://kai-appa-staging-production.up.railway.app |
| App B URL | https://kai-staging-production.up.railway.app |
| Isolation | staging project has its OWN Postgres and Redis; no production secret or customer data was copied |

**Provenance caveat, stated rather than smoothed over:** App A reports `git_sha: "unknown"`. Railway's
`railway up` is a CLI upload, not a git integration, so `RAILWAY_GIT_COMMIT_SHA` is unset and the
start command falls through to `unknown`. The binding evidence for "this is 45aa5bd" is therefore the
build timestamp (`build_time 2026-09-06T03:32:06Z`, `deploy_id 875ff5e0-7d`) plus the uploaded tree
having been a clean checkout of that SHA — **not** a SHA the running service can attest to itself.
Wiring `GIT_SHA` into the service variables would close this; it is not closed today.

## 2. Flag posture at deploy — deployment is not enablement

Exactly ONE flag was changed: `KAI_HOLDING_ENABLED=true` on App B staging.

It was verified **display-only before being set**: its only effects are mounting the read-only holding
router (`backend/app/main.py:211`) and a fail-open context read (`nai_brain/brain.py:63`). Its own
declaration says "when False the router is not mounted at all (zero new surface)". It grants no
execution, autonomy, money, capture or write authority.

Every consequential flag remains UNSET (default `False`) on staging, confirmed after deploy:

`KAI_HOLDING_COMMAND_ENABLED` · `KAI_CAPABILITY_EXECUTION_ENABLED` · `HOLDING_AUTONOMY_ENABLED` ·
`KAI_A2_EXECUTION_ENABLED` · `KAI_HOLDING_CYCLE_ENABLED` · `KAI_PROACTIVE_ENABLED` ·
`KAI_VOICE_ENABLED` · `KAI_CAMERA_ENABLED` · `MONEY_MODE`

(`KAI_CYBER_OPS_ENABLED` was in this list when the run was made. It is REMOVED on
`release/kai-holding-os`: nothing read or enforced it, and Cyber Operations is not shipped there.
Eight authority flags remain, all default `False`.)

Observable consequence, and the correct one: `/admin/holding/voice/capabilities` and
`/gesture/capabilities` return **404** on staging — their command router is genuinely not mounted.
Voice and camera are dark, not merely idle.

## 3. Hosted verification — measured, unauthenticated

| Check | Before deploy | After deploy |
|---|---|---|
| App A `/admin/holding` | **404** | **200**, 81 656 B |
| App A `/admin/mission-nexus` | 200 (older build) | **200** |
| App A `/admin/security/cyber-operations` | — | **200** |
| App A `/admin/kai-gesture.js` | — | **200** |
| Bridge `allow_prefixes` | `kai-chat, kg, twin, persona, briefing, research, memory` — **no `holding`** | `… , holding, capabilities, cyber` |
| App B `/admin/holding/view` | **404** (router unmounted) | **403** (mounted, correctly denied) |
| App B `/admin/holding/{timeline,attention,missions,health,system-graph}` | 404 | **403** each |

Browser (Chrome, hosted URL, unauthenticated): 19 panels render, 37 honest `NOT CONNECTED` markers,
**zero fabricated values**, presence orb present, contract banner correctly **not** shown (App B is
compatible). Screenshot: `.kai-evidence/STAGING_holding_desktop.png`.

## 4. Hosted verification — authenticated, full chain

Performed with the staging owner key injected from Railway (never typed, never printed):

| Step | Result |
|---|---|
| `POST /admin/session/login` | **200**, `wv_session` cookie minted |
| `GET /admin/session/whoami` | `role: owner`, scopes include `kai.ultra`, `source: session` |
| `GET /admin/kai/holding/view` | **200** |
| `/overview` · `/status` · `/timeline` | **200** each |
| `/view` payload | **21 top-level keys**; all five contract keys present (`health, attention, timeline, missions, system_model`) |

This exercises the whole path — browser origin → App A → owner session → bridge → App B → data.

**A security property confirmed, not a defect:** sending `X-API-Key` directly yields **403** at App B.
The bridge deliberately does not forward raw browser secrets (`core/kai_bridge.py:15`); only the signed
session cookie crosses, and App B re-resolves the principal independently. An API key that App A honours
is therefore *not* sufficient to reach App B — which is the intended defence against an operator-role
credential escalating by hitting App B directly.

## 5. Visibility repairs, verified live on staging

The three defects that would have survived a perfect deploy (commit `45aa5bd`):

| Defect | Live evidence on staging |
|---|---|
| `/admin/holding` was an orphan URL with zero inbound links | `/admin/hub` serves cards for holding, mission-nexus and cyber-operations; `/admin/command` sidebar carries "Holding Command" and "Cyber Operations" |
| Stale backend rendered every panel "unavailable" indistinguishably from an outage | Contract banner correctly **absent** against the compatible staging backend; browser-verified present against a stale-shaped payload, naming the missing keys |
| Sign-in guidance pointed at a different page and at a login that never mints the cookie | Live banner reads "the KAI orb in the bottom-right corner of this page…" with an "Open KAI sign-in" action |

## 6. Bounded gaps — what this record does NOT claim

- **No authenticated hosted BROWSER screenshot.** The authenticated chain was proven at the API layer;
  driving the browser through sign-in would have required putting the staging key into page context.
  The screenshot on file is the unauthenticated state.
- **Timeline was empty by construction.** `timeline.ingest()` had no caller outside its own test, so the
  panel stayed empty even deployed and flagged on. Not a deployment fault. **SUPERSEDED on
  `release/kai-holding-os`:** `timeline.view()` now ingests from the real sources on the read path and the
  payload/panel carry per-source status, so an empty timeline states whether the sources were readable.
  The observation above remains the accurate record of what this staging run measured.
- **Missions/working_now stay empty** while the A2 brakes are off — no `worker_jobs` are produced.
- **Voice and camera were not exercised**, by design: their router is dark. Real-device media testing is
  **NOT RUN** (no consent given, no hardware harness).
- **App A cannot attest its own SHA** (§1).
- **No load, soak, restart-recovery or stream-reconnect testing** was performed on staging.

## 7. Production — NOT deployed, approval still required

Production is untouched and was re-verified during this work: App A `app.wheellsverse.com` reports
`git_sha 4fbfb8e`, `build_time 2026-09-03T10:09:50Z`; App B `kai-prod` healthy, `env production`.

A production release requires a **separate scoped approval** naming the SHA and targets, per the
documented G3 gate. Note additionally that on today's production App B, **five of the nine flags are not
declared in `config.py` at all**, and pydantic's `extra="ignore"` drops undeclared variables silently —
so flag-setting on production before the code deploy is a guaranteed silent no-op.

## 8. Incident — staging credential exposure (disclosed)

While probing the login endpoint, a request used the field name `key` instead of `secret`. FastAPI's
422 validation error **echoed the submitted value**, printing the staging `API_KEY` into the session
transcript. The value was not published anywhere else, production credentials were never handled, and
subsequent calls suppressed response bodies. **Recommended action: rotate `API_KEY` on the
`kai-appA-staging` service.** Recorded here rather than omitted because a credential that reached a
transcript must be treated as disclosed.
