# KAI Daemon — Senior Engineering Audit
**Target:** `backend/app` (the FastAPI KAI daemon, ~28,254 LOC) · **Date:** 2026-06-29
**Method:** multi-agent reverse-engineering + 4-lens audit, every finding adversarially re-verified against the real code.
**Verification legend:** ✅ confirmed (verifier re-read the code) · ❌ false-positive (verifier refuted it) · ⚠️ unverified (verifier hit a token limit; the finding comes from a code-reading auditor but was not independently re-checked).

> Scope note: this repo holds **two apps**. `core/api.py` is a separate ~628KB single-file FastAPI service on :5050. This audit covers **`backend/app`** only — the daemon run by launchd `com.wheellsverse.nai` → `uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1`.

---

## 1. Architecture breakdown

A single-process FastAPI **monolith** that fuses three products behind one ASGI app:

1. **Public companion-AI SaaS** — `/kai/*` (legacy `/nai/*`, dual-mounted), Supabase-JWT auth, tier-gated, paid via Stripe.
2. **Operator control plane** — 24 `/admin/*` routers (full-tool chat, browser control, planning execution, Sol money ops), gated by a single static `X-Admin-Token`.
3. **Autonomous agent** — ~45 service subsystems (kg, twin, persona, eq, learning, planning, research, digest, security, ceo…) governed by an `@audited` scope system.

**Layers (request path):** ASGI middleware (CORS → SlowAPI rate-limit → SecurityHeaders, outermost) → 36 routers → dependency/auth layer (Supabase JWT / cookie / SSE / `kai_` API key / admin secret) → ~45 services → split persistence.

**Persistence (two-tier, deliberate):**
- **Postgres/Supabase** (SQLAlchemy, `app/database.py`) — users, conversations, messages, subscriptions, api_keys, pgvector RAG, `llm_call_log`. *Multi-node-ready.*
- **~11–12 local SQLite sidecars** (`services/*/storage.py`) + **JSONL append-only logs** (governance audit, failures, security, browser, research) — KAI's own subsystems. *Single-node only.*

**Governance spine (a genuine strength):** one `@audited(scope, destructive)` decorator across **85 call sites / ~40 scopes** enforces off-by-default `KAI_SCOPE_*` flags, requires `approved=True` for destructive actions, and appends every call to a redacted append-only audit log — without threading flags through business logic.

**Three traced data flows:**
- **Chat turn:** `nai.py` → builds `Router` + ~30-tool registry *per request* → `Brain` (persists conv/messages in Postgres, assembles layered system prompt: memory+eq+persona+twin+ceo+relationship+lessons) → `Router.select` (prefer_local→Ollama; over-cap→Ollama; intent→provider) → tool loop (≤5 iters, OpenAI 429→Anthropic→local failover) → save message w/ cost/tokens.
- **Money action:** `sol.py`/`billing.py` → `@audited` scope+approval gate → `DwollaClient` (sandbox-locked) / Stripe → atomic conditional-UPDATE ledger claim + Idempotency-Key → HMAC-verified webhook.
- **Governed admin action:** `/admin/*` → `require_admin_token` → service `@audited` → scope check → execute → append to `data/governance/audit.jsonl`.

### What's genuinely strong (keep these)
- **Defense-in-depth money paths.** Sol transfers are *quadruple-locked* (scope + `approved` + Dwolla sandbox-lock + no LLM tool reachability), integer-cents, atomic claims, Idempotency-Keys, fail-closed HMAC webhook.
- **Resilient cost-aware LLM routing.** Local-first, intent-based, soft caps that *degrade to local* instead of refusing, real provider failover ladder.
- **Loose subsystem coupling.** Lazy-import + fail-open preambles → persona/twin/ceo/learning can each be absent or throwing without breaking chat.
- **SSE-safe pure-ASGI security headers** with strict same-origin CSP + production-gated HSTS.
- **Externalized identity** (Supabase ES256/JWKS, no per-request DB round-trip).
- **Pragmatic persistence isolation** — experimental subsystems on disposable SQLite can churn schema with zero risk to billing/auth/conversations.

---

## 2. Critical problem areas (prioritized)

### 🔴 Tier 1 — Security & money-bleed (fix first)
| ID | Sev | Status | Problem | File |
|----|-----|--------|---------|------|
| AUTHZ-002 / CORR-F1 | High | ⚠️/✅ | `/kai/chat` + `/chat/stream` give **any authenticated user the full ~30-tool loop and unbounded LLM spend** — no per-route rate limit, no tier gate; over-cap only *soft-downgrades to local Ollama* instead of refusing. Real money bleed + abuse vector. | `routers/nai.py:49-110`, `core/rate_limit.py` |
| AUTHZ-004 | Med | ⚠️ | **One static shared `X-Admin-Token` protects all 24 `/admin/*` surfaces + full-tool operator chat + Sol money ops**, defaults to reusing `JWT_SECRET_KEY`, compared non-constant-time, no rotation/MFA/RBAC. One leak = total operator+money+autonomy compromise. WS token is in the query string. | `dependencies/admin.py:10-20`, `ws_collab.py:24` |
| CONFIG-003 | Med | ⚠️ | **Insecure-by-default:** `DEBUG=True`, dev CORS, and `JWT_SECRET_KEY`-as-admin-token fallback are the *defaults* — fails open if env is incomplete. | `config.py:17,42-44,55`, `dependencies/admin.py` |
| SSRF-001 | High | ⚠️ | `web_fetch` SSRF: the IP guard is a **string-prefix check** and **redirects aren't re-validated** — a 302 to `169.254.169.254`/`localhost` bypasses it. | `services/tools/web_fetch.py:69-84` |
| GOV-005 | Med | ⚠️ | Governance **wildcard over-grant**: a parent `KAI_SCOPE_<MODULE>` flag silently satisfies destructive money sub-scopes (`sol.transfer`, `dwolla.transfer`). A destructive scope should never be satisfied by a parent. | `governance/actions.py:46-63` |

### 🔴 Tier 1 — Correctness (data integrity)
| ID | Sev | Status | Problem | File |
|----|-----|--------|---------|------|
| CORR-F2 | High | ✅ | **Stripe webhook has no event-id idempotency.** Relies only on a `UNIQUE(stripe_subscription_id)` that doesn't cover all handlers; a `None` sub-id creates duplicate rows and **re-fires side effects** on replay. | `routers/billing.py:298-432` |
| CORR-F4 | Med | ✅ | **Streaming chat orphans the user message** and persists an *empty assistant turn* on mid-stream failure. | `services/nai_brain/brain.py:286-351` |
| CORR-F3 | Med | ✅ | Governance audit log's docstring claims **POSIX-atomic appends, but records exceed `PIPE_BUF` and writes are unlocked** — the durability invariant is false and breaks under concurrency. | `services/governance/audit_log.py:1-18,78-83` |
| CORR-F5 | Med | ⚠️ | `SpendTracker.log_call` **never commits on router fallback/failure paths** — cost + failure audit silently lost. | `services/router/router.py:83-162`, `spend_tracker.py:37-74` |

### 🟠 Tier 2 — Performance (latency on every chat turn) — all ✅ confirmed
| ID | Problem | File |
|----|---------|------|
| PERF-F1 | Every chat turn **reads + JSON-parses the entire `failures.jsonl`** (unbounded) for a Jaccard scan. | `failure_memory/storage.py:171-201` |
| PERF-F3 | **Synchronous OpenAI embedding call on the critical path** of every chat turn (memory recall). | `nai_brain/memory_injection.py:80`, `memory/embeddings.py:40` |
| PERF-F6 | `async def` routes do **blocking LLM/embedding/HTTP work directly on the event loop** (transcribe, documents→rag). | `routers/transcribe.py:55`, `routers/documents.py:59` |
| PERF-F2 | **LLM adapters + OpenAI client reconstructed on every request** (re-reads env, re-instantiates SDK clients). | `routers/nai.py:41-46`, `router/__init__.py:38-67` |
| PERF-F4 | 12 SQLite stores **connect-per-call AND re-run `executescript(schema)` on every call.** | `services/*/storage.py` (kg/eq/journal/learning/persona/planning/twin/checkin/sol) |

### 🟡 Tier 3 — Scalability (blocks "millions of users")
The Postgres tier scales; the **KAI-subsystem layer is architecturally single-node**:
- **In-memory rate limiter** (`core/rate_limit.py`) — correct only at `--workers 1`; a 2nd worker/host silently breaks every limit. `REDIS_URL` is in config but **unused by the limiter**.
- **12 SQLite sidecars + JSONL logs** pinned to one disk via `Path(__file__).parents[4]`, single-writer assumption.
- **6 background scheduler threads run inside the API process** (`main.py` lifespan) with **no leader election** — every replica would duplicate Telegram sends, research cycles, Sol ticks. (`celery_app.py` already exists, unused for this.)
- **Per-request Router + tool-registry construction.**
- **Local-model affinity** (Ollama/Kokoro/Piper) hard-binds the daemon to the Mac mini host.
- **In-memory WebSocket collab state** (`collab/hub.py`) — can't broadcast across instances; leaks on crash.
- **Module-global mutable caches** (Dwolla token, JWKS, settings, HSTS flag) — config rotation needs a full restart, incoherent across processes.

### ❌ Correctly refuted (verification working)
- **PERF-F5** — "stores lack `busy_timeout`": the verifier found the contended stores **do** set it. Downgraded to false-positive.
- **PERF-F11** — "SpendTracker write amplification": negligible; refuted to none.

---

## 3. Refactoring strategy

**A. Pure refactors — NO behavior change** (safe, do anytime):
1. **`BaseStore` class** — collapse the ~12 near-identical SQLite `storage.py` files (connect + `PRAGMA` + cached schema-init + per-thread connection) into one base. Kills PERF-F4 and ~30× duplicated boilerplate. (`relationship.py` already has the `_INITIALIZED` pattern to lift.)
2. **Process singletons** — build the `Router` + adapter set + tool registry once in the lifespan (`app.state`), inject only the per-request `session` into `SpendTracker`. Kills PERF-F2.
3. **Threadpool the blocking work** — make `transcribe`/`documents` handlers sync `def` (FastAPI runs them in the threadpool, matching the rest of the codebase) or wrap in `run_in_threadpool`. Kills PERF-F6.
4. **Cache query embeddings** (LRU on normalized text) + run memory recall concurrently with prompt assembly. Mitigates PERF-F3.
5. **Audit-log + failures rotation** (size/age) and move the Jaccard scan to a bounded in-memory recent-window. Mitigates PERF-F1, F12.

**B. Hardening — intentional behavior change** (security/correctness; needs your sign-off because it changes responses):
6. Per-tier **rate limits** on `/kai/chat[/stream]` keyed by user-id; over-cap **returns 402/429** for free tier instead of silent local downgrade. (AUTHZ-002/CORR-F1)
7. `hmac.compare_digest` admin-token check, **remove the `JWT_SECRET_KEY` fallback**, fail startup if `ADMIN_TOKEN` unset; move WS token out of the query string. (AUTHZ-004)
8. Secure-by-default config: `DEBUG=False`, `APP_ENV='production'`, `CORS_ORIGINS=[]`, refuse wildcard-with-credentials. (CONFIG-003)
9. **Stripe event-id idempotency table** (`processed_stripe_events`, PK on `event.id`, short-circuit replays). (CORR-F2)
10. **SSRF**: `follow_redirects=False` + re-resolve & `ipaddress`-check every hop. (SSRF-001)
11. Governance: a destructive scope must require its **exact** `KAI_SCOPE_*_TRANSFER` flag — never satisfied by a wildcard parent. (GOV-005)
12. `fcntl.flock` (or Postgres) for the audit-log writer + fix the false PIPE_BUF docstring. (CORR-F3)
13. Transactional streaming save (delete orphan user row / skip empty assistant on failure). (CORR-F4)

---

## 4. Target architecture (scale to millions)

Keep the monolith codebase; make the **runtime stateless + horizontally scalable**:

```
                         ┌───────────────────────────────┐
   Clients ── HTTPS ───▶ │  Load balancer / API gateway  │
                         └───────────────┬───────────────┘
                          (N stateless API replicas, --workers >1)
            ┌───────────────────┬────────┴────────┬───────────────────┐
            ▼                   ▼                 ▼                   ▼
   ┌─────────────┐     ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐
   │  Postgres   │     │     Redis       │  │  Inference   │  │  Scheduler   │
   │ (Supabase)  │     │ rate-limit +    │  │  tier        │  │  worker (1x  │
   │ users,conv, │     │ WS pub/sub +    │  │ Ollama/Kokoro│  │ leader): the │
   │ billing,    │     │ token/JWKS/     │  │ /Piper as a  │  │ 6 schedulers │
   │ spend, RAG, │     │ spend caches    │  │ shared svc   │  │ (Celery —    │
   │ + migrated  │     └─────────────────┘  └──────────────┘  │ celery_app   │
   │ KAI stores  │                                            │ exists)      │
   └─────────────┘                                            └──────────────┘
```

**Migration order (each independently shippable):**
1. Redis-backed slowapi (`storage_uri=REDIS_URL`) → unlocks `--workers >1` on one host *today*.
2. Extract the 6 schedulers into the existing Celery worker (single leader) → unlocks multi-replica without duplicate side effects.
3. Externalize WS collab state to Redis pub/sub (Hub is already a clean swappable abstraction).
4. Migrate the 12 SQLite sidecars → Postgres behind the new `BaseStore` interface (now a repository swap, not a rewrite).
5. Split local inference (Ollama/Kokoro/Piper) into a shared inference service; `OLLAMA_HOST` → service DNS.

---

## 5. Execution plan

| Batch | Contents | Behavior change? | Risk | Effort |
|-------|----------|------------------|------|--------|
| **0 — Safe quick wins** | Refactors #1–#5 (BaseStore, singletons, threadpool, embedding cache, rotation) | None | Low | M |
| **1 — Security/correctness hardening** | #6–#13 (rate limits, admin hmac+no-fallback, secure config, Stripe idempotency, SSRF, governance, audit-log lock, streaming save) | Yes (intentional) | Med | M–L |
| **2 — Scale-out** | Redis limiter → Celery schedulers → WS Redis → SQLite→Postgres → inference service | Operational | High | L |

**Recommended:** start with **Batch 0** (pure refactors, zero behavior change, immediate latency win on every chat turn) + the two highest-risk Batch 1 items (**Stripe idempotency CORR-F2** and **admin-token hmac/no-fallback AUTHZ-004**), each in an isolated worktree with tests. Re-verify the 11 ⚠️ findings after the token limit resets before acting on them.
