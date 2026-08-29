# WHEELLSVERSE PRODUCTION — PHASE 0 (FREEZE & VERIFICATION)
## 2026-08-29 · Production changes made: 0

**Scope approved: Option A (full certified stack). Phase 0 authorized ONLY. This is freeze + verification. Nothing was provisioned, deployed, or reconfigured in production.**

## Frozen identifiers
```
APP_A_PRODUCTION_SHA   = Command Center build (0a2f399-era) — verified by served markers, NOT the
                         stale GIT_SHA env (2b78508); Railway snapshot deploys record no git SHA.
APP_A_PRODUCTION_DEPLOY = e73ef751 (Railway deployment id, app.wheellsverse.com)  ← ROLLBACK TARGET
APP_A_CANDIDATE_SHA    = 72d7b0c  (feat/kai-capability-fabric HEAD, clean tree)
APP_B_CANDIDATE_SHA    = 72d7b0c  (same branch)
MIGRATION_HEAD         = 0006_add_kai_api_keys  (chain 0000→0006, proven repeatable from empty)
PRODUCTION_HOSTNAME    = app.wheellsverse.com
APP_B_PROPOSED_HOSTNAME= internal-only (kai-prod.railway.internal) recommended — bridge reaches it
                         privately; optional public kai.wheellsverse.com only if externally needed.
```

## Rollback target — mechanically verified (not assumed)
- `git cat-file -t e73ef751` → **not a git object**: `e73ef751` is the Railway **deployment id**, so rollback = **redeploy that deployment**, not a git checkout.
- prod `app.wheellsverse.com/api/health` → `deploy_id: e73ef751-877` → **the rollback target IS the current live prod deployment.** Confirmed.
- prod `/admin` serves the certified Command Center markers (title, sr-only h1, 16 pill-nodes, kpi sparklines) → the code baseline is the certified UI.

## Fail-closed — proven live in prod (no state change)
- prod `POST /admin/kai/kai-chat` → **404 `kai_bridge_disabled`**
- prod `/admin/kai-bridge/health` → `enabled:false, upstream_configured:false`
→ With the bridge OFF, App A **cannot** execute through App B; there is no fallback. **Production is currently in the exact rollback/kill state.**

## Pre-flight isolation matrix (PROD must be dedicated; STAGING must never be referenced)
| Resource | PROD (to provision) | STAGING (do not touch) | ISOLATED |
|---|---|---|---|
| App B service | new prod service | kai-staging | **YES** |
| PostgreSQL | new prod PG | kai-staging PG | **YES** |
| Redis | new prod Redis | kai-staging Redis | **YES** |
| Worker | new prod worker | kai-worker-staging | **YES** |
| Queue namespace | prod Redis | staging Redis | **YES** |
| Hostname | app.wheellsverse.com (+kai-prod internal) | *.up.railway.app | **YES** |
| OpenAI credential | new funded prod key (owner-supplied) | staging key | **YES** |
| Session signing secret | fresh prod secret | staging secret | **YES** |
| Audit/usage storage | prod PG `llm_call_log` + governance audit | staging PG | **YES** |
Candidate code contains **no** `kai-staging`/`railway.internal`/secret literals (env-only) → no crossover risk from code.

## Money & provider safety
- Money mode **MOCK** holds by absence — this deploy (App A Command Center + App B/KAI governance) does **not** include the SOL money engine (separate `wheellsverse-sol` service); no payment/payout/financial-mutation surface is introduced.
- Provider: prod requires a **separate funded OpenAI key** with conservative budget/rate/concurrency/timeout limits (owner-supplied at Phase 2); verified only as `PRESENT`, value never printed.

## Rollback mechanism (fastest → fullest) — validated to exist
1. **`KAI_BRIDGE_ENABLED=false`** on prod App A → governed path 404s (proven live now). Immediate containment.
2. Redeploy prod App A deployment **e73ef751**.
3. App B teardown (only after the bridge is off; never the first emergency action).

## Observability prerequisites
Telemetry sources exist + are certified: `llm_call_log` (spend, provider failures via Pass-4 durable failure audit, tool executions, 401/403 gate denials), governance `audit_log`, `/health` (App B) + `/api/health` (App A), Railway deploy logs/metrics (5xx, restarts). **Gap to close before Phase 4 traffic:** wire alerting/dashboard thresholds (spend cap, 5xx rate, provider-failure rate, audit-write failure). Not required for Phases 0–2 (dark).

---

## PHASE 0 RESULT
```
Production baseline             VERIFIED
Candidate App A                 VERIFIED
Candidate App B                 VERIFIED
Migration head                  VERIFIED
Rollback (deploy e73ef751)      VERIFIED (== current live deploy)
Bridge currently OFF            VERIFIED (fail-closed 404 proven live)
Money mode MOCK                 VERIFIED (SOL money engine not in this deploy)
Prod/staging isolation plan     VERIFIED (all rows ISOLATED=YES; no code crossover)
Rollback mechanism              VERIFIED (bridge kill-switch proven live)
Observability prerequisites     VERIFIED (sources exist; alerting to wire before Phase 4)

Production changes made: 0
Critical: 0 · High: 0 · Medium: 0 · Low: 0
```
## GATE: **READY FOR PHASE 1 APPROVAL**
Phase 1 (provision isolated prod Postgres + Redis, DARK — no App A/B change) will not begin without an explicit **GO PHASE 1**.
