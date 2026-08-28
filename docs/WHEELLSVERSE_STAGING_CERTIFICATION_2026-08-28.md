# WHEELLSVERSE — Functional Certification Pass 5
## App B Staging Certification — 2026-08-28 (LIVE checkpoint)

**Status: `STAGING CERTIFICATION IN PROGRESS` — App B is deployed and healthy on isolated Railway staging, and the governed cloud-LLM core is certified on real infra. Remaining journeys (App A↔B bridge, C/D/E, full auth matrix, restart/rollback, security, Playwright) are pending — the final Section-20 gate is not yet set.**

No product features added, no UI redesigned, no governance weakened, no production credentials used, **production (App A, app.wheellsverse.com) UNCHANGED and NOT deployed.**

---

## 1. Frozen targets (Section 1)

| Field | Value |
|---|---|
| APP_A/B_BRANCH | `feat/kai-capability-fabric` |
| APP_B_SHA (at deploy) | descendant of `aa349df` (staging build fixes), clean tree |
| APP_B_MIGRATION_HEAD | `0006_add_kai_api_keys` |
| Production (App A) | `grateful-flexibility/production` → wheellsverse.com — **UNCHANGED** |

## 2. Isolated staging provisioned (Section 2) — SOL-pattern

| Resource | Name / value |
|---|---|
| Project | `kai-staging` (`0dcd21ec-…`) — separate from `grateful-flexibility` |
| Postgres | dedicated plugin, Online (`postgres-ssl:18`, bundles pgvector) |
| Redis | dedicated plugin, Online |
| App B service | `kai-staging` — Dockerfile builder (`backend/Dockerfile.staging`, repo-root context for `core/`), `/health` check |
| Public edge | **https://kai-staging-production.up.railway.app** |
| Not reused | prod Postgres / Redis / hostname / secrets — all fresh, isolated |

Build notes (in-repo, additive; App A untouched): App B is **not** self-contained under `backend/` (imports repo-root `core.operator_session_web`), so it builds from the repo root via a dedicated Dockerfile. `requirements-staging.txt` drops the unsatisfiable `mcp`, bumps `pydantic` to the local working `2.13.4`, and adds three undeclared-but-required deps (`pgvector`, `PyJWT`, `supabase`).

## 3. Live evidence

### Migration on real infra (Section 3): **PASS**
Container ran the canonical `alembic upgrade head` against the empty staging Postgres — full chain `0000 → 0006`, incl. `0003`'s `CREATE EXTENSION IF NOT EXISTS vector` (pgvector present on Railway). No create_all / stamp / manual SQL.

### Health / readiness (Section 5): **PASS**
`GET /health` → `200 {"status":"ok"}`; `/docs` → 200; boot log shows every scheduler honestly reporting "not started (…_ENABLED not set)" — no fabricated activity. *(Minor: `/health` reports `env:"development"` — cosmetic env label to set to `staging`.)*

### Governance gates (Sections 5/11): **PASS**
On the public edge, `POST /admin/kai-chat` and `/admin/kai-chat/stream`:
- no auth → **403** `owner access required (kai.ultra)`
- operator-role token (`X-Admin-Token`) → **403** — the Pass-4 fix proven on real infra: App B enforces `kai.ultra` itself, so an operator credential hitting App B directly cannot escalate.

### Journey B — governed cloud LLM (Section 7): **PASS**
Owner `wv_session` cookie (minted with the staging secret, `role=owner kai.ultra=true`) → `POST /admin/kai-chat` (`prefer_local=false`) → **HTTP 200**, real OpenAI answer. Usage evidence: `llm_call_log` row `openai · gpt-4o-mini · success=t · cost_usd=0.000510`.
- **Authorized tool execution: PASS** — a forced `audit_query` call produced a 2-turn tool loop (two `openai success=t` rows at one timestamp, cost 0.000622 + 0.000504); the answer was grounded in the real (empty) audit state — honest, not fabricated.

### Streaming (Section 13): **PASS**
`POST /admin/kai-chat/stream` → `Content-Type: text/event-stream`, **25 incremental frames**, first token **0.20s**, total 1.66s, with a `correlation_id` in the meta frame and `status: thinking → done`. Real SSE, not buffered.

### Failure-audit durability (Section 12, re-proving Pass-4): **PASS**
Before credits were added, a governed call hit OpenAI **429 "no credits"**, then degraded toward local ollama (absent → refused) and the request **502'd + rolled back** — yet **both** failure rows (`openai success=f` with the 429 text, `ollama success=f` connection-refused) **survived** in `llm_call_log`. The exact Pass-4 invariant, certified on hosted infra.

### App A ↔ App B bridge (Section 6): **PASS — 11/11**
The real `core/kai_bridge.py` (`install_kai_bridge`) mounted in-process with App B staging as the fixed upstream (the bridge's own httpx client makes real calls to the edge). All 11 checks passed:
- auth propagation (unauth → 401 *before* forwarding); role propagation + **§12 escalation blocked at the bridge** (operator cookie → 403 `need=kai.ultra`)
- allowlist + `..` traversal → 404 (SSRF/path protection); method allowlist
- OWNER forward → **200 real App B answer**, `x-correlation-id` propagated
- streaming forwarded as SSE (19 frames)
- audit events role-tagged (owner/operator/anonymous), **no secret/cookie leaked**
- unreachable upstream → 502, **disabled bridge → 404 fail-closed** (never a mock/silent success)

### Journey E — governed automation run (Section 10): **PASS**
`POST /admin/self-heal/run` (owner cookie): unauth → 403; **dry-run → 200** with an honest empty plan (`detected:[], note:"0 issue(s) detected"`); destructive `apply` → **403 ScopeDenied** ("Scope 'self_heal' is not enabled — set KAI_SCOPE_SELF_HEAL=1") — a server-side scope kill-switch denies the destructive mutation (defense-in-depth beyond the approval gate). Nothing executed.

### Restart recovery (Section 14): **PASS**
`railway redeploy` cycled the App B service — `/health` stayed **200 throughout** (zero-downtime), deploy settled back to **Online**, and a governed call **post-restart returned 200**. Full function recovered; `llm_call_log` audit persists across restarts by construction (Postgres is a separate service, not the app container).

## 4. Matrix (Section 19)

| Item | Result |
|---|---|
| App B deploy | **PASS** |
| Empty-DB migration (real infra) | **PASS** |
| Health / readiness | **PASS** |
| Redis | **PASS** (provisioned, Online) |
| Governance gates (403 unauth/operator) | **PASS** |
| KAI cloud-LLM answer (sync) | **PASS** |
| Authorized tool execution | **PASS** |
| Streaming (hosted SSE) | **PASS** |
| Usage/audit persistence | **PASS** |
| Failure-audit durability | **PASS** |
| App A ↔ App B bridge (Section 6) | **PASS (11/11)** |
| Automation run — Journey E | **PASS** (dry-run + destructive denied by scope gate) |
| Worker retry — Journey C | **PENDING** (needs Celery worker service + a seeded failed Sol cycle) |
| Incident ack — Journey D | **N/A** — App B has no distinct incident-ack endpoint; self-heal (Journey E) is the incident-remediation surface |
| Auth matrix (OWNER/OPERATOR/anonymous) | **PASS** (owner authorized; operator → 403 kai.ultra; anon → 401/403) — ADMIN/READ_ONLY roles not modeled in `core/operator_session` |
| Restart recovery | **PASS** (below) |
| Adversarial security | **PARTIAL** — SSRF/path-traversal/role-bypass/escalation/secret-leak all PASS via the bridge suite; broader fuzzing pending |
| Playwright browser journeys | **PENDING** (no App A UI on staging; API-level journeys certified above) |

**Defects found this pass — Critical: 0 · High: 0 · Medium: 0 · Low: 1** (LOW: `/health` reports `env:"development"` on staging — cosmetic env label).

## 5. Gate

**Not final.** The App B governed core (deploy · migration · health · gates · Journey B sync+stream+tools+usage · failure-audit durability) is **CERTIFIED on isolated staging**. `WHEELLSVERSE FULLY CERTIFIED IN STAGING` is withheld until the pending rows (bridge, C–E, auth matrix, restart/rollback, security, Playwright) are complete.

**External note:** Journey B was briefly blocked on an OpenAI **billing** state (429 no-credits, key valid) — cleared by the account owner adding credits; not a code/config issue.

**Production remains untouched and is not part of this pass.**
