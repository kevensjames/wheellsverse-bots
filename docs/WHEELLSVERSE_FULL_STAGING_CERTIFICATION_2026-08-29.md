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

## Findings
- **LOW — console 404:** the Command Center requests `/admin/capabilities.json` from App A (an App-B endpoint); App A 404s it. Degrades gracefully (KAI "Capabilities —") but logs one console error, so the "0 console errors" bar is not met. Fix: fetch capabilities via the bridge or suppress on App A.
- **(fixing) env label:** App A's top bar read **"PRODUCTION"** (pre-fix build derived env from Railway's env name, which is "production" in this project). Fix committed (`5e462a9`) + redeploying.

## Not yet certified in-browser (honest)
The **authenticated** in-browser journeys — governed KAI click-through (B), mutation buttons (C/D/E), and the owner-side of the auth matrix — were **certified programmatically** (deployed App A bridge → App B, owner 200 / operator 403 / anon 401), **not driven through the browser UI**. Driving them in-browser requires injecting the owner session token into logged browser tool calls, which conflicts with the standing token-handling policy (never place a session token in logs/transcripts). The operator's decision is required on whether to (a) accept the programmatic certification of the authenticated path, or (b) authorize browser auth with the ephemeral staging token. Also pending: comprehensive fuzzing across all 10 vectors under an authenticated session, and the remaining responsive breakpoints individually.

## Matrix
| Item | Result |
|---|---|
| App A deploy | PASS |
| App B deploy | PASS |
| Environment labels | App B PASS · App A fixing |
| A — system discovery | PASS |
| B — governed KAI | PASS (programmatic) · in-browser pending |
| C — worker retry | PASS (Pass-5, programmatic) · in-browser pending |
| D — incident ack | N/A (no distinct endpoint) |
| E — automation run | PASS (Pass-5, programmatic) · in-browser pending |
| F — SOL read-only drilldown | pending |
| G — security | PASS (bridge suite + unauth) · authenticated fuzzing pending |
| H — deployment inspection | PASS |
| Browser auth (anon) | PASS · owner/operator in-browser pending |
| Audit persistence | PASS (Pass-5) |
| KAI streaming / tool exec | PASS (Pass-5, programmatic) |
| Control inventory | PASS (rendered) · full click-through pending |
| Security fuzzing | PARTIAL |
| Responsive smoke | PASS (mobile) · other breakpoints pending |

**Critical: 0 · High: 0 · Medium: 0 · Low: 1** (console 404) — plus the env-label item, in remediation.

## Gate
**FULL STAGING CERTIFICATION — not yet complete.** The full stack is deployed and running on isolated staging, the Pass-5 LOW is fixed, and the unauthenticated UI + programmatic governed path are certified. `WHEELLSVERSE FULLY CERTIFIED IN STAGING` is **withheld** pending: (1) the App A env-label redeploy landing, (2) the console-404 fix, and (3) an operator decision on the authenticated in-browser sweep (programmatic vs. browser-token). **Production remains untouched — no production deployment in this pass.**
