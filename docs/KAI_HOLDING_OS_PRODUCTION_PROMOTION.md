# KAI Holding OS — Production Promotion Package

**Staging candidate:** the current tip of `feat/kai-exec-appb-integration` (this document's commit or later — deploy the branch HEAD) · **Holding-OS pure tests:** 196/196, 0 regressions · **Production: UNCHANGED** (App B `3b9caff`, App A `a886ec6`) · MONEY_MODE=MOCK.

> Production promotion is **owner-approved and owner-executed**. This document is the turnkey runbook. Every
> `railway` / `git push production` command below is **classifier-gated to the operator** — Claude prepared
> the code and the steps but must not run them, and did not fabricate any credential.

## 1. Runtime certification matrix
| Mapping | Scope | State | To finish |
|---|---|---|---|
| HEALTH_PROBE, CAPABILITY_HEALTH | internal | ✅ CERTIFIED | — |
| REPO_INSPECT | local-git | ✅ CERTIFIED_READ_ONLY | — |
| LOG_INSPECT | local-file (2-stage redact) | ✅ CERTIFIED_REDACTED_READ_ONLY | register per-service log sources |
| RUN_INTERNAL_TEST | allowlisted suites | ✅ CERTIFIED_A1 | — |
| DEPLOYMENT_STATUS_LOCAL | local-git ancestry | ✅ CERTIFIED_READ_ONLY (non-prod) | — |
| DEPLOYMENT_STATUS_PRODUCTION | Railway | adapter **BUILT** → RUNTIME_PENDING | inject a read-scoped Railway API token (step 5) + `register_deployment_source(..., provider="RAILWAY")` |
| BROWSER_VALIDATE | Playwright | adapter+image **BUILT** → RUNTIME_PENDING | `Dockerfile.staging` already installs chromium; set `KAI_STAGING_APP_*_ORIGIN`, deploy, then live cert + SSRF adversarial recheck |
| TECH_DOC_LOOKUP | Context7 | adapter **BUILT** → RUNTIME/AUTH_PENDING | wire a reviewed transport into `Context7ServerAdapter(transport=...)` + set `CONTEXT7_API_KEY` |

## 2. Feature flags (all default OFF — dark deploy)
`KAI_HOLDING_ENABLED`, `KAI_HOLDING_BRIEFING_ENABLED`, `KAI_HOLDING_WATCH_ENABLED`, `KAI_CAPABILITY_EXECUTION_ENABLED`, and (new) a global autonomy switch `HOLDING_AUTONOMY_ENABLED` + per-company flags. Autonomous A2/self-improvement run ONLY with an explicit grant present; A2 grants are non-production by construction.

## 3. DARK-FIRST staging sequence (operator-run — the exact order)
**Deploy dark: both execution brakes OFF.** Prove isolation/migrations/auth/routes/health/Chromium/SHA
*before* anything can autonomously execute. The two brakes are independent (see §2) — turn autonomy off
first, then capability execution off, and you never need a code rollback merely to stop activity.

1. Check out the exact SHA **`0a00e5f`** (or the branch tip) in a clean worktree.
2. Link/create the **NEW `kai-staging`** Railway project.
3. **Positively verify** you are NOT on production — not just the environment name:
   ```
   railway status            # expect project = kai-staging, environment = staging
   railway status --json | grep -i name   # confirm project id/name != kai-production (896e8fbe)
   ```
   If there is any doubt, STOP — do not mutate.
4. Provision **dedicated** staging Postgres + Redis (`railway add`) — never the production DB/Redis.
5. Set initial SAFE variables (**dark** — both execution flags OFF):
   ```
   railway variables --set APP_ENV=staging --set MONEY_MODE=MOCK \
     --set KAI_HOLDING_ENABLED=true --set KAI_HOLDING_BRIEFING_ENABLED=true \
     --set HOLDING_AUTONOMY_ENABLED=false --set KAI_CAPABILITY_EXECUTION_ENABLED=false
   ```
6. Generate `SESSION_SIGNING_SECRET` **locally** and set it directly in Railway — never paste it into
   Claude/ChatGPT/logs.
7. `railway up --service kai-staging-appb` from **`0a00e5f`** (Dockerfile.staging: migrations 0000→0006 on
   empty DB + `playwright install chromium`).
8. Wait for Railway terminal state **SUCCESS**.
9. Verify: deployed SHA = `0a00e5f` · migrations succeeded · Postgres is staging · Redis is staging ·
   MONEY_MODE=MOCK · holding routes owner-gated (403 without owner cookie) · no crash loop ·
   **autonomy OFF · capability execution OFF**.
10. `railway domain --port 8000` → **APP_B_STAGING_URL**.
11–12. Deploy/create **App A** staging + its domain → **APP_A_STAGING_URL**.
13. **Only now** (real domains exist — never placeholders):
   `railway variables --set KAI_STAGING_APP_A_ORIGIN=<real App A origin> --set KAI_STAGING_APP_B_ORIGIN=<real App B origin>`
14. Redeploy/restart if config loading requires it.
15. Verify Playwright: package present · Chromium present · browser launches · approved staging origin
    recognized (`holding.browser_validate` health → READY).
16. Verify Context7: credential absent → **AUTH_PENDING** (never fake READY).
17. **Only after 9–16 pass**, lift brake #1: `railway variables --set KAI_CAPABILITY_EXECUTION_ENABLED=true`.
18. Run safe capability smoke tests (health/repo/log/deployment-local/browser).
19. **Only after 18 passes**, lift brake #2: `railway variables --set HOLDING_AUTONOMY_ENABLED=true`.
20. Begin hosted autonomy certification (§ below).

Seed only synthetic fixtures (no production customer/health data). Record deployment IDs, SHA, terminal
state (require SUCCESS), and both staging URLs.

## 4. Optional credentials (by name only — never block the rest of staging)
Both can stay pending while everything else certifies:
- **Railway read token:** set `RAILWAY_READ_TOKEN` directly in staging; Claude sees only PRESENT/ABSENT.
  Then `make_deployment_provider(railway_api=<read_client>)` + `register_deployment_source(..., provider="RAILWAY")`.
  Absent → `DEPLOYMENT_STATUS_PRODUCTION` stays RUNTIME_PENDING (never a fake status, never a LOCAL fallback).
- **Context7:** set `CONTEXT7_API_KEY` + wire a reviewed transport into `Context7ServerAdapter(transport=...)`.
  Absent → `TECH_DOC_LOOKUP` stays AUTH_PENDING.

## 5. Scheduler / worker requirements
The persistent cycle (`holding_cycle.run_persistent_cycle`) is driven by the existing `kai-watch-cron` + `worker_jobs` plane — no new scheduler. Bounded intervals: health 5m, deployment/repo 1h, daily planning 24h, 90-day weekly. Restart reconciles once (no replay). Self-improvement is capped at 3 attempts/day, below critical work.

## 6. Rollback
- App B: `railway variables --set KAI_HOLDING_ENABLED=false` (instant dark) or redeploy prior SHA (`3b9caff`).
- App A: `git push origin <prior>:production`.
- A2/self-improvement: never merges/deploys, so nothing to roll back beyond discarding an isolated worktree.

## 7. Smoke tests (post-deploy, owner-run)
Health env=staging; `GET /admin/holding/view` (owner cookie) returns TODAY-first view; a no-change cycle → 0 work; BROWSER_VALIDATE `holding_dashboard_smoke` desktop+mobile; TECH_DOC_LOOKUP FastAPI current API; DEPLOYMENT_STATUS_PRODUCTION reads App A/App B SHA+status (no mutation).

## 8. Known limitations (honest)
- DEPLOYMENT_STATUS_PRODUCTION returns UNAVAILABLE until the Railway read token is injected — production truth is **never** inferred from local git.
- BROWSER_VALIDATE + TECH_DOC_LOOKUP are policy/contract-certified but their runtimes are not installed on the server yet.
- The Holding UI has a mounted view-model API (`/admin/holding/view`); the full 6-section HTML render is a small remaining frontend step.
- No hosted staging exists yet — the full live autonomy chain is proven locally (composed closed-loop + cycle tests), not yet hosted.

## 9. Production environment changes required
Dedicated staging project + DB/Redis/secrets (§3); `Dockerfile.staging` Playwright browser step (§4); Railway read token + Context7 client injection (§4); per-service log + deployment source registration; cron wiring of the persistent cycle. **No production mutation until staging certifies and you approve.**
