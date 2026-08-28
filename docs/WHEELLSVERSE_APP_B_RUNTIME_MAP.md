# WHEELLSVERSE App B — Governed KAI Runtime Map (Pass-3 §1)

Forensic map of the governed KAI backend, produced while bringing it up locally.

## Identity
- **Repo/worktree:** `wheellsverse-bots` @ `/Users/jhonwheeler/wheellsverse-kai-merge`, branch `feat/kai-capability-fabric`.
- **Entrypoint:** `backend/app/main.py` → `app = FastAPI(title="Wheellsverse")`, **154 routes**, ~30 admin routers
  (admin_chat, admin_audit, admin_supreme, admin_self_heal, admin_planning, admin_research, admin_kg,
  admin_data, api_keys_admin, auth, billing, predictions, sol, …).
- **Port (local):** 8020 (`uvicorn app.main:app`).
- **Health:** `GET /health` → 200. Docs at `/docs`.

## Runtime dependencies (env NAMES only)
| Need | Var | Local value used |
|---|---|---|
| Postgres | `DATABASE_URL` (required, no default) | `postgresql://localhost:5432/wheellsverse_test` (psycopg2 — psycopg3 not installed) |
| Redis | `REDIS_URL` | `redis://localhost:6379/0` (running) |
| Celery | `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | redis (workers not started in safe mode) |
| Env | `APP_ENV` | development |
| Providers | `PROVIDER_MODE` | mock |
| Unified session | `OPERATOR_SESSION_ENABLED`, `SESSION_SIGNING_SECRET` | on + shared with App A |
| LLM | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OLLAMA_HOST` / `OLLAMA_MODEL` / `KAI_LLM_ALLOW_LOCAL_ONLY` | ollama-only (llama3.1:8b @ 127.0.0.1:11434) |

## Canonical startup (recorded)
```
INSTALL      : deps already present in the shared venv (sqlalchemy, psycopg2, fastapi, …); psycopg3 absent → use postgresql:// URL
MIGRATION    : alembic upgrade head   ← FAILS standalone (see defects); local bootstrap = Base.metadata.create_all() + alembic stamp head
APP_B_START  : uvicorn app.main:app --host 127.0.0.1 --port 8020
WORKER       : celery -A app.workers.celery_app worker   (not needed / not started in safe mode)
SCHEDULER    : gated by KAI_*_ENABLED flags (all off in safe mode)
```

## Auth model
Unified `wv_session` cookie signed with `SESSION_SIGNING_SECRET` — **the same cookie App A mints**
(`core/operator_session.mint_session(ROLE_OWNER, secret=…)`). App B `require_kai_ultra` verifies the
cookie + requires an operator Profile at `tier='ultra'` (or `KAI_OPERATOR_USER_ID`). Fail-closed.

## App A ↔ App B bridge
`core/kai_bridge.py`: `KAI_BRIDGE_ENABLED` + `KAI_UPSTREAM_URL`; forwards `/admin/kai/{path}` →
`<upstream>/admin/{path}`; path allowlist (blocks SSRF/traversal), correlation id, timeout→504,
fail-closed 404 when disabled. **Verified:** transport works; owner cookie authorizes (401→405→503→502);
no cookie → 401; **App B offline → App A 502 (never fake success)**.

## Audit / call-log stores
`audit_log` (id, actor_id, actor_type, action, target_type, target_id, metadata, created_at) — the
governance action log. `usage_log` (create_all) vs `llm_call_log` (migration 0004) — **NAME DRIFT**.

## DEFECTS FOUND (§16) — must be fixed before full certification
1. **HIGH — migrations can't build the schema standalone.** 0001 doesn't create `profiles`/`conversations`
   (Supabase provides them in prod). `alembic upgrade head` fails locally (`relation "profiles"/"conversations"
   does not exist`). Local bring-up needs a Supabase-shaped bootstrap. Not a prod bug (Supabase supplies
   these), but blocks isolated staging from migrations alone.
2. **HIGH — call-log / audit persistence broken by table drift.** The chat path inserts into `llm_call_log`
   but `create_all` builds `usage_log`; migration 0004 builds `llm_call_log`. With create_all-bootstrap the
   insert fails → **governed LLM calls are not audited** (audit_log stayed at 0 rows for the chat path).
3. **LOW (local-only) — ollama tool path.** With `KAI_LLM_ALLOW_LOCAL_ONLY`, a tool-using chat routes to
   ollama and calls `OllamaAdapter.complete(tools=…)` → TypeError → clean 502. Prod-unaffected (prod has
   openai, a tool-capable adapter). Router should raise "no tool-capable adapter" cleanly instead.

## External blocker
Tool-using KAI answers (Journey B "company health") need a **tool-capable cloud adapter**
(`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) — ollama is tool-incapable. That is a genuine external credential.
