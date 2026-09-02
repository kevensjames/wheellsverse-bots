# KAI Holding OS — Staging Certification

Tracks the two-phase certification: **local pre-staging** (done, this branch) and **hosted staging**
(pending operator provisioning). Production UNCHANGED throughout.

## Phase 1 — Local pre-staging certification (COMPLETE)
- **196 holding-OS pure tests, 0 regressions** across: twin, reconciler, planner, resolver, owner queue,
  briefing/Today, persistent cycle, self-model, self-improvement, limited A2, repo/log/internal-test/
  deployment/browser/tech-doc capabilities, holding view-model + UI contract.
- Full autonomy chain proven locally via composed tests: observe → twin → reconcile → plan → resolver →
  certified capability → real evidence → completion → owner filtering; no-change → 0; restart → 1;
  kill-switch → 0 execution; self-improvement E2E → READY_FOR_REVIEW (never merges/deploys).
- Adapters built + fail-closed: Railway read (no token → RUNTIME_PENDING), Playwright runner
  (health-gated), Context7 server (transport/key → RUNTIME/AUTH_PENDING).
- Adversarial passes to date: REPO(4) LOG+TEST(1) A2(4) DEPLOYMENT(2) SELF-IMPROVE(11) + pre-staging
  surfaces — all confirmed findings fixed + regression-tested.

## Phase 2 — Hosted staging certification (PENDING PROVISIONING — next mission, certification-only)
After the operator provisions `kai-staging` + deploys the candidate SHA, the next pass verifies (no new
features):
1. staging isolation (DB/Redis/queue/secrets are NOT production)
2. deployed SHA matches the candidate
3. BROWSER_VALIDATE real hosted E2E (desktop + mobile) → then the **mandatory SSRF/origin adversarial recheck**
4. TECH_DOC_LOOKUP hosted E2E (real Context7 source + provenance)
5. DEPLOYMENT_STATUS_PRODUCTION real read-only E2E (App A + App B SHA/status, no mutation)
6. persistent autonomy cycle (live)
7. self-improvement disposable-defect E2E → READY_FOR_REVIEW
8. restart recovery (one reconcile, no replay storm)
9. Holding UI + visual screenshots (3440×1440 / 1920×1080 / 1440×900 / 390×844)
10. final hosted adversarial pass
11. produce the production promotion package for owner approval

## Target verdicts
Phase 1: **HOLDING_AUTONOMY_PRESTAGING_CERTIFIED** ✅
Phase 2: `HOLDING_AUTONOMY_STAGING_CERTIFIED` (pending) → then owner-approved production promotion.

See `KAI_HOLDING_OS_PRODUCTION_PROMOTION.md` for the exact provisioning + deploy commands.
