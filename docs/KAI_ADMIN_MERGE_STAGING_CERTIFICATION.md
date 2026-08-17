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

## Gate 3 — real governed LLM (CONDITIONAL)  [2026-08-11 update]

App B fully provisioned locally: DB `kai_gate3` (create_all bootstrap — the alembic
chain assumes a Supabase-provisioned base, so the documented local mechanism is
`Base.metadata.create_all` + the `llm_call_log` shadow, exactly as App B's own
conftest does), `vector`+`pgcrypto` extensions, seeded tier=ultra operator profile
(`KAI_OPERATOR_USER_ID`), `DEBUG=false`, and **local ollama (llama3.1:8b)** as the
real provider (`prefer_local` default). A placeholder `OPENAI_API_KEY` satisfies
App B's `REQUIRED_ADAPTERS={'openai'}` router-construction check; real inference
goes to ollama (no real openai call, no cost, no prod credential).

| Check | Result | Evidence |
|---|---|---|
| App B schema | ✅ PASS | 18 tables via canonical create_all bootstrap |
| App B ready | ✅ PASS | `/health` 200 |
| **Real provider** | ✅ PASS | owner chat → 200 (12.1s), `adapter:'ollama'`, coherent answer, `conversation_id` persisted (`conversations=2, messages=4`) |
| Owner-only chat | ✅ PASS | operator → `/admin/kai/kai-chat` → **403** (escalation closed) |
| Correlation id | ✅ PASS | propagated end-to-end |
| Audit | ✅ PASS | one secret-free bridge event per action |
| Spend ceiling | ✅ PASS (mechanism) | `SpendTracker` in-path, `llm_call_log` rows written, `NAI_MAX_DAILY_SPEND_USD=$2` cap (ollama=$0, not exhausted) |
| Error redaction | ✅ PASS | `DEBUG=false` → redacted `Internal Server Error`, no traceback |
| **Real incremental streaming** | ⚠️ N/A (by design) | `/admin/kai-chat` is **synchronous/buffered JSON, not SSE** |
| SSE framing / cancellation | ⚠️ N/A | no stream on the operator endpoint to frame/cancel |
| Rate limit | ⚠️ N/A | no request-rate limiter on the operator chat; the **spend ceiling is the control** |
| Context receipt | ⚠️ PARTIAL | bridge carries the envelope; App B `AdminChatRequest` has **no `context` field** yet (P7 App B follow-up) |

**GATE 3 = CONDITIONAL** (not silently PASS): the governed LLM works end-to-end
through the bridge — owner-only, real local provider, persisted, spend-tracked,
redacted, audited — but **real SSE streaming + cancellation are N/A because the
governed operator endpoint is buffered by design** (App B's SSE lives on the
user endpoint `/kai/chat/stream`, which is Supabase-JWT auth, not the operator
session). This is a precisely-documented transport boundary, not a merge defect.

## Findings ledger (Gate 3)
1. **Operator→ultra escalation — FIXED** (merge security defect): `/admin/kai-chat`
   always runs tier=ultra + App B auth is binary, so an operator could reach it.
   Bridge now gates the whole `kai-chat` prefix to owner-only `kai.ultra`
   (`17cce12`, regression tests).
2. **Governed streaming gap** (App B/architecture): the operator chat is buffered.
   To get streaming subtitles in the drawer/command bar, App B needs a governed
   **streaming** operator endpoint (or the bridge points at a streaming path with
   operator auth). Decision required before the presence drawer's streaming UX.
3. **`AdminChatRequest` has no `context` field** (P7): App B can't consume the
   envelope yet — small App B change to accept + use it.
4. **`DEBUG` defaults `True`** (`config.py:17`): tracked separately; before prod,
   flip the safe default to `False` with explicit local opt-in.
5. **`REQUIRED_ADAPTERS={'openai'}`**: even local-only runs need the openai adapter
   to construct (placeholder key). Consider making ollama a valid sole adapter.
6. **Schema bootstrap** (documented, not a defect): alembic assumes the Supabase
   base; local/staging uses `create_all` (App B's own conftest mechanism).

## What still needs hosted-edge certification (blocks PRODUCTION only)
HTTPS `Secure`-cookie behavior, Cloudflare same-origin proxying, SSE-through-edge,
disconnect propagation, header filtering. Tracked as `HOSTED_EDGE_CERTIFICATION`.

## Gate 3 — governed STREAMING (PASS)  [2026-08-17 update]

The buffered-endpoint limitation is resolved: **`POST /admin/kai-chat/stream`** —
governed operator SSE, reusing the SAME stack (`Brain.stream` → `Router.stream` →
`OllamaAdapter.stream`, ollama's real `/api/chat` stream). Findings #2–#5 above are
now addressed in code.

| Check | Result | Evidence |
|---|---|---|
| Real incremental streaming | ✅ PASS | 88 token frames spread over ~4.3s (not a buffered split); `text/event-stream` |
| TTFC recorded | ✅ | ~10.2s first token (llama3.1:8b CPU); TOTAL ~14.6s |
| SSE framing | ✅ PASS | `meta → status → meta → token×N → usage → done` |
| Owner-only (RBAC) | ✅ PASS | owner streams via bridge; operator → **403** (kai.ultra) |
| Cancellation | ✅ PASS | real socket close → `kai.stream.cancelled` audit, no traceback; closing the sync generator closes ollama's httpx stream → connection drops → generation stops. Boundary = next token-yield after disconnect |
| Correlation / audit | ✅ PASS | `X-Correlation-Id`; bounded `kai.stream.{started,completed,cancelled,failed}`, no per-token, no secrets |
| Conversation / spend | ✅ PASS | conversation+messages persisted; `llm_call_log` ollama rows ($0) |
| Error redaction | ✅ PASS | `DEBUG=false` (now the safe default) → redacted SSE `error`, no traceback |
| Context (§7) | ✅ PASS | `AdminChatRequest.context` allowlisted to 6 descriptive fields (cookie/auth/api_key/DOM dropped), passed into the system prompt; never authz |
| Rate limit (§6) | ✅ PASS | fixed-window keyed by the VERIFIED principal; rotating/forged/expired credentials collapse to one bucket (regression tested); 429 + Retry-After |
| ollama-only local | ✅ PASS | `KAI_LLM_ALLOW_LOCAL_ONLY=1` — no placeholder OpenAI key needed; prod `REQUIRED_ADAPTERS` unchanged |

Bridge already routes `/admin/kai/kai-chat/stream` owner-only and streams SSE.
Buffered `/admin/kai-chat` remains for tool-using turns (tools need a cloud
tool-capable adapter). Note: real cancellation needs a genuine disconnect — a
pooling HTTP client that closes gracefully may defer detection to the next send.

## Verdict
Gate 1, Gate 2, C1, and **Gate 3 (streaming)** are **certified over real HTTP**
against a fully-provisioned local App B (ollama). The governed operator chat now
streams token-by-token with cancellation, RBAC, context, rate limiting, spend,
audit, and redaction. The merge spine is complete for local staging. **Presence
(P11–P15) is unlocked** for local development on this streaming foundation.
**Production stays blocked** on `HOSTED_EDGE_CERTIFICATION` (HTTPS Secure cookies,
Cloudflare, SSE-through-edge, disconnect propagation).
