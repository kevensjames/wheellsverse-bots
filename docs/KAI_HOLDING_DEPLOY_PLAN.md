# KAI Holding OS — Deployment Plan (for operator go/no-go)

**Status: PLAN ONLY — nothing deployed. Requires explicit operator approval of the exact commit + rollout + rollback before any step runs.**
**Branch:** `feature/kai-holding-operations-os` · **HEAD:** `bc3cc50` · **Date:** 2026-08-30

## The scope reality (read this first)
This branch is **204 files changed vs `main`** — it carries the whole accumulated KAI stack (capability
fabric, Nexus/avatar/voice frontend, presence, admin_chat), NOT just the Holding OS. **Deploying the
branch ≠ deploying the Holding OS.** The Holding OS is a clean, flag-gated **~18-file subset**:

- **App B** (`kai-prod`, backend snapshot): `backend/app/services/holding/*`, `backend/app/routers/admin_holding.py`,
  `backend/app/workers/holding_tasks.py`, `backend/app/config.py` (3 flags), `backend/app/main.py` (flag-gated include).
- **App A** (`app.wheellsverse.com`, git branch `production`): `frontend/admin/holding.html`, `core/api.py` (serve route),
  `core/kai_bridge.py` (allow-prefix `holding`).
- **Workers** (`ops/browser-worker`, `ops/github-worker`): LOCAL operator tooling (colima) — **NOT part of any Railway deploy.**

## What's certified (pre-flight — all PASS, all local)
- Holding staging cert 7/7 (owner-only access, operator-role 403 no-escalation, truth-grounding, flag-off dark).
- Unit: registry 9/9 · reports 11/11 · kpi_feed 5/5.
- Workers: browser 7/7 · github 7/7 (isolation + egress default-deny + no secret leak).
- Money mode MOCK throughout; all endpoints read-only; no external send.

## Recommended path: STAGING FIRST (no prod risk)
No isolated hosted staging for this stack exists yet. Step 1 is to stand one up and certify there.
1. Deploy the branch to an **isolated** Railway staging env (separate project/DB/Redis), flags ON
   (`KAI_HOLDING_ENABLED=true`, `KAI_HOLDING_BRIEFING_ENABLED=true`).
2. Run the **hosted** equivalent of `staging_cert.py` against it (owner cookie via the bridge).
3. Confirm: owner-only 200, non-owner 403, priorities ranked + source-cited, live signals, movement,
   money/customer/banking still disclaimed.
4. **Go/no-go checkpoint** → only then consider prod.

## Prod path (only after staging passes + explicit approval)
Because the branch is 204 files, the safe prod change is the **isolated Holding OS subset**, deployed **DARK**:

**App B (dark deploy, snapshot):**
1. Operator sets prod env flags **OFF** first (default) — deploy adds ZERO surface.
2. `railway up` (kai-prod) from the certified tree. Migrations: none required (kpi_history self-creates its table lazily).
   ⚠️ Caveat: `railway up` snapshots the whole working tree — confirm kai-prod is already on this branch's App B
   code (the operational-truth commit `2db87f2` is on this branch and already in kai-prod) so the snapshot adds
   only the holding files, not 204 unrelated changes. If not, isolate via a clean holding-only branch first.
3. Verify `/health` env=production, `/admin/holding/*` → 404 while flags off (dark).
4. **Flip `KAI_HOLDING_ENABLED=true`** → verify owner-only 200 + truth-grounding on the live endpoint.
5. Flip `KAI_HOLDING_BRIEFING_ENABLED=true` only when you want the daily Celery briefing (it persists KPI history).

**App A (serve route + bridge prefix):** cherry-pick the 3 App A holding commits onto the `production` branch
(operator runs — classifier-gated), redeploy App A. `holding.html` is inert until App B's flag is on.

## Rollback (fast, tested by design)
- **Instant:** set `KAI_HOLDING_ENABLED=false` → all holding routes vanish (proven by staging cert Step 4). No redeploy needed.
- **App B:** redeploy the prior kai-prod snapshot/deployment (Railway keeps prior deploys).
- **App A:** revert the cherry-picked commits on `production` + redeploy.
- **KPI history table:** harmless if left (empty/unused when flag off); `DROP TABLE holding_kpi_history` if desired.

## Explicit go/no-go decision points (operator)
1. **Approve staging-first?** (recommended) — I prepare the exact Railway commands + a hosted cert; you run the deploy.
2. **Prod dark deploy** — only after (1); requires your approval of commit `bc3cc50` (or an isolated holding-only branch),
   the flags-off→verify→flip sequence, and the rollback above.
3. **Workers** — remain local operator tooling; no deploy proposed (they never touch prod).

**I will not run any deploy step without your explicit approval of the specific commit + sequence.**
