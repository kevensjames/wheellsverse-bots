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

## 3. Staging provisioning runbook (Part A — operator-run)
Claude cannot provision Railway. Recommended: a **separate Railway project** `kai-staging` (strongest isolation; matches the prior staging pattern in memory), with its OWN Postgres + Redis + secrets — never the production DB/Redis/queue.
```
# operator runs, from a worktree checked out at a9f6900 and linked to the kai-staging project:
railway environment                      # confirm you are NOT on kai-production
railway add                              # provision staging Postgres + Redis (dedicated)
railway variables --set APP_ENV=staging --set MONEY_MODE=MOCK \
                       --set KAI_HOLDING_ENABLED=true --set HOLDING_AUTONOMY_ENABLED=true \
                       --set SESSION_SIGNING_SECRET=<fresh-staging-secret>   # never a prod secret
railway up --service kai-staging-appb    # Dockerfile.staging; migrations 0000→0006 on empty DB
railway domain --port 8000               # → APP_B_STAGING_URL
```
Seed only synthetic fixtures (no production customer/health data). Record `APP_A_STAGING_URL`, `APP_B_STAGING_URL`, deployment IDs, SHA, terminal state (require SUCCESS).

## 4. Runtime completion (operator-run, on staging first)
- **Playwright (step 3):** `requirements-staging.txt` already pins `playwright==1.55.0`; add to `Dockerfile.staging`: `RUN python -m playwright install --with-deps chromium`. Then register staging origins via `browser_validate.register_validation_suite(...)` (or the ops config) and inject the runner. **Then run the mandatory adversarial recheck of the SSRF/origin/redirect surface before certifying** (see §H of the wave).
- **Context7 (step 4):** wire a governed server-side client into `tech_doc_lookup.make_tech_doc_provider(client=<context7_client>)` — the smallest read-only path (official API or a reviewed MCP bridge). Typed contract only; no arbitrary method passthrough.
- **Railway read token (step 5):** inject a **read-scoped** Railway API token and pass it as `make_deployment_provider(railway_api=<read_client>)`; register each service's source via `register_deployment_source(service_id, provider="RAILWAY", company_id=..., environment="production")`. The adapter has no mutation method; it returns whitelisted facts only.

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
