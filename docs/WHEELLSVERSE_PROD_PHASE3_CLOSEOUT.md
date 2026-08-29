# WHEELLSVERSE PRODUCTION — PHASE 3 CLOSEOUT
## 2026-08-29 · Gate: PHASE 3 CANARY PASS — READY FOR PHASE 4 REVIEW (NOT Phase 4 authorized)

## Final production state (live-verified)
| | |
|---|---|
| App A | branch `production` @ **`462adff`** · **git-authoritative** source · Command Center HEALTHY · registry **39** · capabilities **32** · unexpected 5xx **0** |
| App B | `462adff` · `env=production` · HEALTHY / **DARK** · isolated prod Postgres + Redis · audit + usage persistence PASS |
| Bridge | **OFF** (`KAI_BRIDGE_ENABLED=false`) · governed route fail-closed **404** · CC intact after rollback |
| Money mode | **MOCK** · production mutations **0** |

## Bridge canary (proven, through prod App A → App B prod)
Owner **200** · Operator **403** (`kai.ultra`) · Anonymous **401** · correlation chain PASS (`x-correlation-id`) · OpenAI execution PASS · usage evidence PASS (openai_today 2→3, $0.000268) · rollback kill-switch PASS · **final bridge OFF**.

## Deployment-source incident — CLOSED
Root cause: wheellsverse-v2's source was a **pinned Docker image** (`ghcr.io/…:4bbf5b95`, an old commit); `railway up` snapshots (the Command Center `0a2f399`) were ephemeral overlays, so a variable change rebuilt the stale image and reverted prod. Fix: created an intentional **`production` git branch @ `462adff`** (certified), disconnected the image source, connected Railway to git. **Reproducibility PASS** — a benign variable change now rebuilds `production@462adff` (Command Center persists), and enabling/disabling the bridge both preserved the CC. Single git authority; stale image source removed.

## Security
Critical 0 · High 0 · Medium 0 · **Low 2** (both pre-existing/infra, not regressions):
1. `/admin/session/whoami` 404 — legacy kai-presence orb (graceful).
2. Cloudflare beacon CSP console entry — infra (Cloudflare proxy), not app code.

## Inert prod App A variables (DO NOT delete/rotate during closeout)
`KAI_UPSTREAM_URL=PRESENT` · `SESSION_SIGNING_SECRET=PRESENT` (matches App B, hash-verified) · `KAI_BRIDGE_ENABLED=false` · `REMEDIATION_REPRO_CHECK=1`

## Standing items
- **Staging** (kai-staging + kai-worker-staging + kai-appA-staging + PG + Redis) kept available until Phase 4 / rollout completes.
- **Phase 4** (controlled enable + soak; KAI UI login via `OPERATOR_SESSION_ENABLED` as a deliberate decision) requires fresh explicit authorization — **NOT** performed.

## Key facts for the next session
- Prod App A now deploys from **git branch `production`** (kevensjames/wheellsverse-bots). To ship certified changes: update `production` → certified SHA → Railway auto-builds. A variable change safely rebuilds the same git source (incident class eliminated).
- Prod App B = service **`kai-prod`** in Railway project **`kai-production`** (`896e8fbe`), public `https://kai-prod-production.up.railway.app`, DARK (bridge off). Owner cookie = `mint_session(ROLE_OWNER, secret=<prod SESSION_SIGNING_SECRET on kai-prod>)`.
- Enabling the bridge for real = `KAI_BRIDGE_ENABLED=true` on prod App A (Phase 4).
