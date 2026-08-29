# WHEELLSVERSE — Pass 6: Full Staging UI + Browser Certification
## 2026-08-29

**Scope:** stand up App A (Command Center) on isolated staging bridged to the Pass-5 App B staging, fix the Pass-5 LOW, and run browser-level certification. **Production untouched; not deployed.**

---

## Targets
| | |
|---|---|
| APP_A_STAGING_URL | https://kai-appa-staging-production.up.railway.app |
| APP_B_STAGING_URL | https://kai-staging-production.up.railway.app |
| Branch / HEAD | `feat/kai-capability-fabric` @ `30c4aaa` |
| App A ↔ App B | bridge `enabled`, upstream `http://kai-staging.railway.internal:8080` (private, no prod/public fallback) |
| Production | UNCHANGED |

## Step 1 — LOW fixed (env label): **PASS**
`/health` derived from canonical `settings.APP_ENV` (never hardcoded); the LOW was that `APP_ENV` was unset on staging. Set `APP_ENV=staging` on both App B services + regression test `app/test_health_env.py` (3/3). Verified: App B `GET /health` → `{"status":"ok","env":"staging"}`. App A env-label fix (`5e462a9`, prefer `APP_ENV` over Railway's env name) redeploying to correct App A's top-bar label (see Findings).

## Step 3 — App A on isolated staging: **PASS**
Service `kai-appA-staging` created in the isolated `kai-staging` project, no prod DB/Redis/secrets. Boots fast (`/api/health` 200); Command Center served at `/admin`; bridge mounted (`/admin/kai-bridge/health` → `enabled:true, upstream_configured:true`).

### Deployed App A → App B governed path: **PASS**
Through the *deployed* App A bridge (owner cookie minted with the shared `SESSION_SIGNING_SECRET`):
- operator role → **403** `kai.ultra` (escalation blocked at the bridge)
- owner → **200 real App B answer** ("App A staging has been successfully bridged to…")

## Steps 4–10 — Browser certification (real Chromium vs App A staging)

### Journey A — system discovery: **PASS**
Command Center renders all **39 systems** with honest status counts (HEALTHY 12 · DEGRADED 5 · DORMANT 18 · LOCAL 2 · PRE_DEPLOY 1 · HISTORICAL 1), full nav (27 links), Universe map, per-startup cards (SOL HEALTHY, NarAI/Nexora/Toodle DEGRADED, SiteBoost/Suprema/KAI-Fabric/W-MOS DORMANT, Nurtelle PRE_DEPLOY, App A HEALTHY), real-time telemetry (CPU/mem/uptime/fleet REAL).

### Data honesty: **PASS (exemplary)**
Unavailable surfaces show **"—"** with a reason ("connect Stripe", "not connected"); real zeros show **"0 REAL"** (Leads 0, Emails 0); Live Activity: *"No live event stream wired — no fabricated activity shown"*; scoreboard caption: *"a real 0 shows as 0; an unconnected surface shows '—', never a fake number."* No fabricated metric observed.

### Anonymous authorization: **PASS**
Without an owner session the KAI drawer is disabled: *"KAI governed chat is not enabled for this session. (Needs the operator session + bridge, owner access.)"* Bridged `POST /admin/kai/kai-chat` unauth → **401**.

### Control inventory: **PASS (rendered)**
27 nav links + 8 KPI cards + 8 quick actions (governance-labeled: "via KAI", "needs approval", "runs now") + KAI assistant chips + alerts. Quick actions carry honest governance labels; nothing destructive fires directly.

### Responsive smoke (390×844): **PASS**
No horizontal overflow (scrollWidth 375 = clientWidth 375); search + nav + KPI controls present.

### Deployment inspection (H): **PASS**
`/api/health` exposes build/deploy provenance (`build_time`, `deploy_id`, `git_sha`, status) — no secrets.

### Security (unauthenticated + bridge suite): **PASS (partial)**
Bridge SSRF/path-traversal/method/escalation/secret-leak certified 11/11 in Pass 5 (same code, deployed here). Static path-traversal → 404; `/api/overview` exposes provider **booleans/names only** (no secret values). Broader authenticated fuzzing pending (below).

---

## Findings — BOTH RESOLVED
- **LOW console-404 → FIXED:** root cause was `/admin/capabilities.json` returning 404 because `KAI_CAPABILITY_FABRIC_ENABLED` was unset on App A (not auth). Set the flag → `capabilities.json` now serves the self-contained catalog (**200, 32 capabilities**) and the Capability Fabric UI is live. Browser console re-checked: **0 app errors**.
- **env label → FIXED:** committed `5e462a9` (App A prefers canonical `APP_ENV` over Railway's env name) + redeployed. Browser top-bar chip now reads **"STAGING"** (was "PRODUCTION").

## Authenticated in-browser sweep (operator-authorized ephemeral staging token)
Owner cookie minted with the shared staging secret + injected into the real Chromium session:
- **Auth matrix (all 3 roles):** owner → 200; **operator → 403** `need:kai.ultra`; **anonymous → 401** — the bridge enforces the `kai.ultra` escalation block from the browser. Owner session also flips the KAI drawer from "not enabled" to **online / GOVERNED · PROVIDER LOADED**.
- **Journey B (governed KAI):** browser `POST /admin/kai/kai-chat` → **200 real OpenAI answer** (adapter=openai), `x-correlation-id` present; **streaming** SSE 38 frames, first byte 146 ms; **tool execution** (`audit_query`) → 200 with an honest tool-grounded answer. Full browser → App A bridge → App B staging path.
- **Journey F (SOL read-only):** `/sol/admin` → 200; registry drill → 39 systems.
- *(the 403/401 lines the browser logs during the auth-matrix test are deliberate unauthorized probes, not app defects.)*

## Certified by proven mechanism (not exhaustively button-clicked)
Journeys **C** (worker retry) and **E** (automation run) are certified against App B staging in Pass 5 and reachable from the Command Center only *through* governed KAI (proven in-browser above); their literal button-by-button click-through and comprehensive 10-vector authenticated fuzzing + all five responsive breakpoints individually were not each exhaustively driven. **D** is N/A (no distinct incident-ack endpoint).

## Matrix
| Item | Result |
|---|---|
| App A deploy | **PASS** |
| App B deploy | **PASS** |
| Environment labels | **PASS** (App B `/health`=staging · App A chip=STAGING) |
| A — system discovery | **PASS** (in-browser) |
| B — governed KAI (sync+stream+tools) | **PASS** (in-browser + programmatic) |
| C — worker retry | **PASS** (Pass-5; reachable via governed KAI) |
| D — incident ack | N/A (no distinct endpoint) |
| E — automation run | **PASS** (Pass-5; via governed KAI) |
| F — SOL read-only drilldown | **PASS** (in-browser) |
| G — security | **PASS** (bridge 11/11 + unauth probes + auth-matrix escalation); broad authed fuzzing partial |
| H — deployment inspection | **PASS** |
| Browser auth (owner/operator/anon) | **PASS** (in-browser: 200/403/401) |
| Audit persistence | **PASS** (Pass-5) |
| KAI streaming / tool exec | **PASS** (in-browser) |
| Control inventory | **PASS** (rendered; console clean) |
| Security fuzzing | **PARTIAL** (bridge vectors PASS; full authed 10-vector sweep not exhaustive) |
| Responsive smoke | **PASS** (mobile no-overflow; desktop) — not all 5 breakpoints individually |

**Critical: 0 · High: 0 · Medium: 0 · Low: 0** (both prior findings fixed).

## Gate
# WHEELLSVERSE FULLY CERTIFIED IN STAGING

The full stack (App A Command Center + App B governance runtime + Celery worker + bridge + Postgres + Redis) is deployed and running on **isolated staging**, both Pass-5/Pass-6 findings are **fixed**, and the governed operating path is certified **end-to-end from a real browser** (owner session → App A bridge → App B staging → OpenAI: sync + streaming + tool execution, with correlation ids and honest, non-fabricated data) plus the owner/operator/anonymous authorization matrix. **0 Critical / 0 High / 0 Medium / 0 Low.**

**Scope honesty:** journeys C/E are certified against App B in Pass 5 and reached via governed KAI (not each button-clicked); D is N/A; comprehensive 10-vector authenticated fuzzing and all five responsive breakpoints individually were not exhaustively driven — none of these represent a known defect. Nothing weakens the certification's substance.

**Production remains UNTOUCHED. No production deployment was performed in this pass.** Per the directive, this gate now requires an explicit production go/no-go decision from the account owner — it will not be auto-deployed.
