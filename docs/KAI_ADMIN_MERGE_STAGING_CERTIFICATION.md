# KAI ⇄ Admin Merge — Staging Certification (local isolated staging)

> 2026-08-11. Certification run against a **local isolated staging** (operator
> chose this over paid Railway): App B live as `uvicorn app.main:app` on
> 127.0.0.1:8020 (local Postgres `kai_staging` + Redis, `APP_ENV=staging`,
> `DEBUG=false`, sessions ON, shared `SESSION_SIGNING_SECRET`); App A in-process
> making **real HTTP** bridge calls to it. Reproducible via
> `tests/test_live_gate.py` (skips when App B isn't on :8020). **Production
> untouched; all prod flags OFF.**

## Why local, not Railway
The repo worktree was linked to `sol-api` **production**; no staging project
existed; Railway staging costs money and App B streaming needs staging LLM keys
not available. Local isolated staging proves the merge spine over real HTTP with
zero cost and zero production risk.

## Results

| Check | Result | Evidence |
|---|---|---|
| **Gate 1 — identity** | ✅ PASS | owner→owner+`kai.ultra`; operator→no ultra; anonymous→no privilege (live App A + App B) |
| **S4 — cross-app over real HTTP** | ✅ PASS | App A-minted cookie → **live App B** `/admin/session/whoami` resolves the SAME owner principal + scopes over the wire |
| **Gate 2 — bridge security** | ✅ PASS | operator `?ultra=1`→403 (pre-forward); anonymous→401; path allowlist + traversal→404; method→405 |
| **Gate 2 — real transport** | ✅ PASS | bridge forwards `/admin/kai/kai-chat` → **live App B `/admin/kai-chat`** (status ≠ 404/502 → path-mapping fix validated); correlation id propagated |
| **Gate 2 — safe errors** | ✅ PASS | with `DEBUG=false`, App B's error relays as redacted `Internal Server Error` — **no traceback leaks through the bridge** |
| **C1 — query-secret closed** | ✅ PASS | `?api_key=` → 401 when sessions ON (real App A middleware); header still authenticates |
| **RBAC / ultra** | ✅ PASS | `SCOPE_KAI_ULTRA` owner-only; operator can't reach the tier-bypass |
| **Audit** | ✅ PASS (unit) | one secret-free event per bridged action |
| **Gate 3 — real streaming** | ⏳ BLOCKED | needs App B full schema (pgvector) + a staging LLM key (operator-provisioned) |

**87 committed tests green** (83 prior + 4 net new: bridge path-mapping regression + live-gate). Live-gate = 6 tests vs the running App B.

## Findings surfaced by staging (not merge defects, but must be handled)

1. **Bridge path mapping (FIXED, merge defect).** App B's governed routes are
   `/admin/kai-chat` and `/admin/kg/*`; the bridge had forwarded to `/kai-chat`
   (would 404 every call). Fixed via `BridgeConfig.upstream_prefix="/admin"` +
   regression test. This is the one real defect staging-prep caught.
2. **App B `DEBUG` defaults `True`** (`backend/app/config.py:17`). In this local
   run it leaked a traceback on 500 until `DEBUG=false` was set. **Staging/prod
   MUST set `DEBUG=false`** or App B error responses leak stack traces. App B
   config concern, not merge code — flag for the operator.
3. **App B schema needs provisioning** (`alembic upgrade head` + the `vector`
   extension). The bridged chat 500'd on a missing `profiles` table — App B DB
   provisioning, exactly what an operator-provisioned staging supplies.

## What real (operator-provisioned) staging still adds
- App B full schema + LLM/provider keys → **Gate 3 real incremental SSE streaming
  + cancellation** end-to-end (the one gate not certifiable locally).
- HTTPS `Secure`-cookie behavior + Cloudflare same-origin topology.

## Verdict
The merge **spine is certified over real HTTP** (identity, cross-app, bridge
transport + security + redaction, C1, RBAC). Gate 3 real-streaming is blocked on
App B provisioning (schema + LLM key), which is operator-owned. Per the directive,
**presence wiring (P11–P15) remains gated** until Gate 3 is green in a fully
provisioned staging.
