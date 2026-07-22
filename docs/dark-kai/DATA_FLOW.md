# KAI — End-to-End Data Flow

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit` (backend at `backend/`)
**Branch this document was written from:** `feat/kai-swe-agent`, HEAD `4850b0d`
**Verified:** `git diff --name-only origin/istanbul...HEAD` returns only the SWE-agent set (`app/services/swe_runtime/*`, `app/routers/admin_swe.py`, `app/routers/admin_swe_tasks.py`, `app/dependencies/approver.py`, `app/models/swe_task.py`, `alembic/versions/0007_add_kai_swe_tasks.py`, `app/services/governance/audit_log.py`, `app/main.py`, `app/models/__init__.py`, `backend/.env.example`, their tests + docs).

**Provenance rule used throughout:** every hop below is on **merged `istanbul`** unless it carries an explicit `[PR #41/#42 — NOT MERGED]` tag. PR #39 (`fix/kai-governed-tool-loop`) and PR #40 (`fix/kai-code-intelligence`) are **not in this checkout at all** — their source files do not exist here, so nothing in these traces comes from them. Where #39 would change a hop, that is called out as a *would-change* note, not as present code.

All paths below are relative to `backend/` unless prefixed with `deploy/`.

---

## 0. Trust boundaries and secret-read points (index)

| Secret | Read at | Leaves to |
|---|---|---|
| `OPENAI_API_KEY` | `app/services/router/adapters/openai_adapter.py:21-26`; `app/services/memory/embeddings.py:22-28`; `app/services/rag.py:79` | api.openai.com |
| `ANTHROPIC_API_KEY` | `app/services/router/adapters/anthropic_adapter.py:21-26` | Anthropic SDK endpoint |
| `PERPLEXITY_API_KEY` | `app/services/router/adapters/perplexity_adapter.py:21-26` | `https://api.perplexity.ai` |
| `CLOUDFLARE_AI_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | `app/services/router/adapters/cloudflare_adapter.py:47-64` | `https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}` |
| (none) | `app/services/router/adapters/ollama_adapter.py:18-25` | `OLLAMA_HOST`, default `http://127.0.0.1:11434` — stays on the box |
| `DWOLLA_KEY` / `DWOLLA_SECRET` | `app/services/dwolla/client.py:59-62` via `_creds()`, used in `client.py:89-95` (`_token`) | `https://api-sandbox.dwolla.com` or `https://api.dwolla.com` (`client.py:32-34`) |
| `DWOLLA_WEBHOOK_SECRET` | `app/services/dwolla/client.py:240` | never leaves — HMAC compare only |
| `DWOLLA_ALLOW_PRODUCTION` | `app/services/dwolla/client.py:80-83` | the sandbox latch; without `=1` a `production` env raises |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | `app/config.py` settings, used `app/routers/billing.py:260`, `:309` | api.stripe.com |
| `ADMIN_TOKEN` | `app/dependencies/admin.py:104` (`settings.admin_token`), compared `admin.py:108-110` | never leaves |
| Supabase JWKS / `SUPABASE_*` | `app/dependencies/supabase_jwt.py:72-88` | JWKS fetch to Supabase |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | `app/services/observability.py:43-44`, `:86` | `https://api.telegram.org/bot{tok}/sendMessage` (`observability.py:58`) |

Process/network topology (merged `istanbul`, `deploy/`): a single uvicorn worker bound to loopback (`deploy/start_nai.sh`, `--host 127.0.0.1 --port 8001 --workers 1`), supervised by the LaunchDaemon `deploy/launchd/com.wheellsverse.kai.plist`, exposed publicly only through `cloudflared` (`deploy/cloudflared/config.yml.example` → `kai.wheellsverse.com` / `nai.wheellsverse.com` → `127.0.0.1:8001`). Single-worker is load-bearing, not just capacity: the admin brute-force throttle (`app/dependencies/admin.py`) and the alert rate limiter (`app/services/alerts.py:32-33`) hold state in process memory.

---

## 1. Flow A — a user chat message, end to end

Entry: `POST /kai/chat` (and the identical `POST /nai/chat`; the router is dual-mounted at `app/main.py:235-236`).

### Ordered hops

| # | Hop | file:line | Data at this hop |
|---|---|---|---|
| 1 | TLS terminates at Cloudflare, tunnel to loopback | `deploy/cloudflared/config.yml.example` | raw HTTPS request |
| 2 | Middleware: SlowAPI, CORS, SecurityHeaders (outermost) | `app/main.py:164`, `:166`, `:178` | headers only. **No rate limit applies** — `app/core/rate_limit.py:19` sets `default_limits=[]` and `limiter.limit` appears only in `app/routers/auth.py` |
| 3 | Auth: Supabase JWT (cookie `nai_access` or `Authorization: Bearer`), ES256 via JWKS, `aud="authenticated"` | `app/dependencies/supabase_jwt.py:72-88`, entry `:109` | token → `UserPrincipal(id=…)`. No DB round-trip |
| 4 | Route handler builds router + full tool registry | `app/routers/nai.py:49-56` (`rt = build_default_router(session)`, `registry = build_default_registry()`) | user message string, `use_tools`, `prefer_local`, `max_tokens` |
| 4a | *(optional)* `auto_route=true` → an **extra LLM call** to classify the domain, then the registry is filtered to a preset | `app/routers/nai.py:61-71` | the user's question is sent to a provider before the main turn |
| 5 | `Brain.chat` loads conversation + last-N history | `app/services/nai_brain/brain.py:186-188` | prior message rows read from Postgres |
| 6 | **PERSIST #1 — the user message is written before any model call** | `brain.py:190` → `_save_message` `brain.py:129-157` | row in `messages` (`app/models/conversation.py:93`) with `content`, `conversation_id`, denormalized `user_id` (`conversation.py:106`) |
| 7 | Memory recall: the message is **embedded** and used as a pgvector query | `brain.py:193` → `app/services/nai_brain/memory_injection.py:28` → `app/services/memory/retrieval.py:71` `embed_one(query)` → `app/services/memory/embeddings.py:50` | **the raw user message leaves the machine to api.openai.com** (`text-embedding-3-small`, `embeddings.py:12`) even when the turn is later routed to Anthropic/Ollama |
| 8 | EQ + relationship side effects | `brain.py:196` → `brain.py:24-45` → `app/services/eq/storage.py:74-84` | **PERSIST #2 — a truncated excerpt of the raw user message is written to the untenanted SQLite `data/eq/eq.db` table `mood_samples`** (`eq/storage.py:76-82`). Fail-open; no `user_id` column |
| 9 | System prompt assembled (memory preamble + persona + EQ preamble) | `brain.py:197-199` | prompt text |
| 10 | Model selection | `app/services/router/router.py:96-116` — `prefer_local`→ollama; `spend.over_daily_cap`→ollama (`:106`); `Intent.CODE`→anthropic; `REALTIME`→perplexity; `SIMPLE`→cloudflare; else openai. Intent from one regex pass over the **last user message only** (`app/services/router/intent.py:54-71`) | choice of provider |
| 11a | **No tools:** `Router.complete` | `router.py:118`, called from `brain.py:216` | full history + system prompt **leaves to the selected provider** (§0 table) |
| 11b | **Tools on:** `Router.chat` with a `ToolContext(user_id, session)` | `brain.py:202-211`; loop `router.py:230`, bounded `for _ in range(max_tool_iters + 1)` at `router.py:297` (`DEFAULT_MAX_TOOL_ITERS = 5`, `router.py:25`) | same, plus tool schemas |
| 12 | **THE CHOKE POINT** — every model-chosen side effect goes through one line | `router.py:374` `tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)` → `app/services/tools/registry.py:58-83` | `registry.py:62-69` does a dict lookup then `tool.execute(ctx, **arguments)`: **no scope check, no approval check, no audit record.** See §1.1 |
| 13 | **PERSIST #3 — LLM cost/telemetry** | `router.py:168` (complete), `:349` (each tool-loop turn), `:344` (degraded local) → `app/services/router/spend_tracker.py:51-74` raw parameterized `INSERT INTO llm_call_log` | adapter, model, in/out tokens, cost, latency, error, `metadata` jsonb. Table has **no ORM model** — migration only (`alembic/versions/0004_add_llm_call_log_table.py:22-64`) |
| 14 | **PERSIST #4 — assistant message** | `brain.py:221-229` then `self.session.commit()` `brain.py:232` | `messages` row with `content`, `adapter`, `model_used`, `cost_usd`, `tokens_used` |
| 15 | Response serialized back | `nai.py:83-90` | conversation id, message, total cost, preset id |

On any adapter failure the router fires an operator alert: `router.py:151, 157, 165, 212, 317, 334, 342, 346` → `app/services/alerts.py:71` `provider_alert` → `observability.notify` (`observability.py:84-88`) → a fire-and-forget daemon thread POSTs to `https://api.telegram.org/bot{tok}/sendMessage` (`observability.py:58`). Rate-limited to one per provider per `KAI_ALERT_MIN_INTERVAL_SECONDS` (default 3600s, `alerts.py:36-42`) with **in-memory** window state (`alerts.py:32-33`).

### ASCII

```
 browser ──HTTPS──> cloudflared ──> 127.0.0.1:8001 (uvicorn, 1 worker)
                                        │
                     [supabase_jwt.py:109]  ES256 / JWKS
                                        │
                              nai.py:49  POST /kai/chat
                                        │
                    ┌───────────────────┼────────────────────────┐
                    │                   │                        │
        brain.py:190 SAVE user msg      │            brain.py:196 EQ hook
             → PG messages              │            → eq/storage.py:74
                                        │               data/eq/eq.db  (no user_id)
                    brain.py:193 memory recall
                    → memory/embeddings.py:50 ──── raw message ───> api.openai.com
                    → pgvector SELECT on `memories`
                                        │
                          router.py:96-116  select()
                                        │
        ┌────────────┬──────────────┬───┴────────┬─────────────┐
     openai      anthropic      perplexity   cloudflare     ollama
   (OPENAI_    (ANTHROPIC_    (PERPLEXITY_  (CLOUDFLARE_   127.0.0.1
    API_KEY)     API_KEY)       API_KEY)     AI_TOKEN)      :11434
        └────────────┴──────────────┴────────────┴─────────────┘
                                        │
              use_tools=true ──> router.py:374 tool_registry.execute
                                        │        (registry.py:58-83 — UNGOVERNED)
                                        ▼
                       any registered tool → its own network + creds  (§1.1)
                                        │
                spend_tracker.py:51 INSERT llm_call_log (PG)
                brain.py:221 SAVE assistant msg + commit (PG)
                                        │
                                   HTTP 200 JSON
```

### Variant: SSE stream — `GET /kai/chat/stream`

`app/routers/nai.py:100-118`. Auth is `get_user_for_stream` (`app/dependencies/stream_auth.py:10` → `app/dependencies/supabase_jwt.py:129-141`), which prefers the `nai_access` cookie but **still accepts a `?token=` query parameter** (`supabase_jwt.py:136-138`, deprecation-warning path) — meaning a valid JWT can land in access logs and `Referer` headers. `Brain.stream` (`brain.py:238-297`) saves the user message and commits *before* streaming (`brain.py:259-261`), then saves + commits the assembled assistant message at `brain.py:295-297`. It calls `Router.stream` (`router.py:171-228`), which **passes no tool registry** — the choke point at `router.py:374` is unreachable from streaming — and has **no fallback whatsoever**: any adapter exception logs, alerts, and re-raises (`router.py:204-213`). Streamed cost is *estimated*, not measured: `router.py:215-228` uses `len(text)//4`, tagged `metadata={"streamed": True, "estimated_tokens": True}`.

### Variant: OpenAI-compatible — `POST /v1/chat/completions`

`app/routers/v1.py:87-90`, auth `require_api_key_user` (`app/dependencies/api_key_auth.py:30`, tier ∈ {max, ultra} at `:60`). Calls `Router.complete` (`v1.py:117`) — **no tool loop, no conversation persistence**. `stream:true` is fake: `v1.py:135-155` completes fully, then emits role-chunk / text-chunk / stop-chunk / `[DONE]`.

### 1.1 What the chat turn can reach through the choke point

`build_default_registry()` (`app/services/tools/__init__.py:46`) registers unconditionally: `memory_tool`, `trading_signal`, `web_fetch`, `kg_query`, `document_search`, `verify_claim`, `pubmed_search`, `sec_edgar_search`, `courtlistener_search`, `who_search`, `clinicaltrials_search`, `suggest_agent`, `failure_lookup`, `plan_query`, `learning_query`, `twin_query`, `audit_query`, `github_scout`. Conditionally on env: `web_search` (`PERPLEXITY_API_KEY`), `twenty_crm` (`TWENTY_API_URL`+`TWENTY_API_KEY`, read **and write**), `dwolla` (read-only), `video_gen` (`RUNWAYML_API_KEY`), `browser` (`KAI_BROWSER_ENABLED`), `notion`/`composio` (`COMPOSIO_API_KEY`), and MCP tools whose registration **defaults to on** when `mcp_config.json` is present (`tools/__init__.py:64-66`).

Because `registry.py:69` calls `tool.execute(ctx, **arguments)` with no gate, a plain authenticated user's prompt can cause: a DB write (`app/services/tools/memory_tool.py:87-93`, `add_memory` + `ctx.session.commit()`), a CRM create against the operator's Twenty instance (`app/services/tools/twenty_crm.py:133-135`), a Notion page create (`app/services/tools/composio_notion.py:44-48`), an **arbitrary** Composio action such as `GMAIL_SEND_EMAIL` (`app/services/tools/composio_generic.py:44-70`), any MCP server tool (`app/services/tools/mcp_tools.py:180-191`), or files on disk (`app/services/tools/site_builder.py:24`, `image_gen.py:27-33`, `video_gen.py:22-26`). Money is deliberately fenced out — `app/services/tools/dwolla_tool.py:29` exposes only six read actions.

> **PR #39 (`fix/kai-governed-tool-loop`) would change hop 12** by adding a `writes`/`scope` attribute read, an `is_scope_enabled` gate, a default-deny `ctx.allow_writes` check, and `record_action(...)` on every path in `registry.py`. That branch is **not present in this checkout** — none of its code was read for this document; the description is from the PR's stated diff and is **UNVERIFIED here**. Confirming it requires `git show fix/kai-governed-tool-loop:backend/app/services/tools/registry.py`.

---

## 2. Flow B — an admin action, end to end

Two shapes exist. Take the **audited** one first, because it is the reference pattern.

Entry: `POST /admin/sol/cycles/{id}/collect` (also `/retry-failed`, `/payout`) — the money case is traced in §3. Here is the generic admin shape, using the same gate.

### Ordered hops (generic audited admin action)

| # | Hop | file:line | Data |
|---|---|---|---|
| 1 | Router-level auth dependency — declared on the `APIRouter`, so it applies to every route in the module | e.g. `app/routers/sol.py:44-45`, `app/routers/admin_chat.py:48-52` | `X-Admin-Token` header |
| 2 | Constant-time compare against the single shared secret | `app/dependencies/admin.py:104-110` (`settings.admin_token`, `hmac.compare_digest`) | pass/fail |
| 3 | Failure throttle: >10 failures / 300s per client key → 429; a valid token clears the streak | `app/dependencies/admin.py:117-134` | in-process `_failures` dict — correct only under one worker |
| 4 | Route calls the audited inner function through an exception translator | `app/routers/sol.py:53-63` `_guard` — `ScopeDenied`→403, `PendingApproval`→409, `DwollaError`→502 | request body, incl. `approved` |
| 5 | `@audited` pops `approved` and `actor` from kwargs | `app/services/governance/actions.py:90-92` | **`approved` is caller-supplied and unproven** — it comes straight off the request body |
| 6 | Scope gate | `actions.py:96` `is_scope_enabled(scope)` → `actions.py:45-63` | env lookup `KAI_SCOPE_<SCOPE>`, **plus a wildcard parent** `parent = norm.split("_")[0]` (`actions.py:60-62`) |
| 7 | Destructive gate | `actions.py:109-120` — `destructive and not approved` → `PendingApproval`, audited as a failure first | |
| 8 | Inner function runs | `actions.py:123-125` | |
| 9 | **PERSIST — audit record on every path** (denied, pending, error, success) | `actions.py:97-107`, `:110-119`, `:127-134`, and the success call after `:135` → `app/services/governance/audit_log.py:45` `record_action` | one JSON line appended to `KAI_AUDIT_LOG_PATH`, default `<repo>/data/governance/audit.jsonl` (`audit_log.py:34-42`) |

`actor` defaults to the literal string `"operator"` (`actions.py:74`), so the audit log **cannot attribute an action to a person** — there is exactly one admin credential and no roles. The `[PR #42 — NOT MERGED]` `X-Approver-Token` dependency (`app/dependencies/approver.py:39-52`) is the only place approval is bound to a proven identity, and it applies only to the three SWE gates.

### The unaudited admin shape

`POST /admin/kai-chat` (`app/routers/admin_chat.py:167-168`) passes only hops 1-3, then does exactly what Flow A does but with the **unfiltered** registry (`admin_chat.py:181-183` builds `build_default_registry()` and `build_default_router(session)`) and the operator's own profile (`_resolve_operator_profile`, invoked `admin_chat.py:170`). No `@audited`, no scope, no approval — an operator chat turn reaches `router.py:374` with every tool enabled. Other admin write routes with **no** `@audited` at all: `app/routers/admin_data.py:31-77` (queues Celery jobs), `admin_supreme.py:77`, `admin_learning.py:55`, `admin_journal.py:58`, `admin_persona.py:55`, `admin_twin.py:78`, `admin_relationship.py:41`.

### ASCII

```
 operator ──X-Admin-Token──> cloudflared ──> uvicorn
                                  │
              admin.py:104-110  hmac.compare_digest(settings.admin_token)
              admin.py:117-134  in-memory failure throttle (10/300s → 429)
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
        AUDITED path                     UNAUDITED path
   sol.py:53 _guard(fn, approved=…)     admin_chat.py:167 POST /admin/kai-chat
                    │                            │
     actions.py:90  pop approved/actor    build_default_registry()  ← ALL tools
     actions.py:96  is_scope_enabled ──┐         │
        (wildcard parent :60-62)       │   Brain.chat → router.py:374
     actions.py:109 destructive+approved│         │        (ungoverned)
                    │                   │         ▼
              inner function            │   external SaaS / disk / DB
                    │                   │
     audit_log.py:45 record_action ─────┘
       → data/governance/audit.jsonl   (plain JSONL, no hash chain, fail-soft)
```

Two properties of that sink worth stating explicitly: `record_action` is **fail-soft** (`audit_log.py:82-83` swallows write errors, so a failed write silently drops the record), and redaction is name/shape based (`audit_log.py:89-103`) — a secret whose key isn't in the pattern list and whose value doesn't match the regex passes through. `grep -rn "prev_hash|chain|hmac" app/services/governance/` returns nothing, so the log is append-only by convention, not tamper-evident.

---

## 3. Flow C — a money movement, end to end

There are **two independent money systems that share no code**: Stripe (cards, subscriptions, Postgres) and Dwolla ACH (Sol ROSCA, SQLite sidecar). Both are traced.

### 3a. Dwolla ACH — Sol contribution collect

Entry: `POST /admin/sol/cycles/{cycle_id}/collect` (`app/routers/sol.py:340-343`).

| # | Hop | file:line | Data / persistence |
|---|---|---|---|
| 1 | Admin token gate (router-level) | `app/routers/sol.py:44-45` → `app/dependencies/admin.py:104-110` | `X-Admin-Token` |
| 2 | `_guard` maps governance/Dwolla errors to HTTP | `sol.py:53-63` | body `{approved: bool}` |
| 3 | `@audited(scope="sol.transfer", destructive=True)` | `sol.py:237` → `app/services/governance/actions.py:96` scope, `:109` approval | denial/pending are themselves audited |
| 4 | Cycle state check — must be `collecting` | `sol.py:240-241` | read from `data/sol/sol.db` (`app/services/sol/storage.py:34`, `KAI_SOL_DB_PATH`) |
| 5 | Dwolla client constructed — **sandbox latch** | `app/services/dwolla/client.py:76-85`: unknown `DWOLLA_ENV` raises; `production` without `DWOLLA_ALLOW_PRODUCTION=1` raises `DwollaProductionLocked` | reads `DWOLLA_KEY`/`DWOLLA_SECRET` at `client.py:59-62` |
| 6 | OAuth client-credentials token, cached | `client.py:89-117` — Basic auth of `key:secret` POSTed to `{base}/token` | **first outbound: the Dwolla API key + secret leave the machine** to `api-sandbox.dwolla.com` or `api.dwolla.com` (`client.py:32-34`) |
| 7 | Per contribution: **atomic claim** `pending → processing` (conditional UPDATE) | `sol.py:221-222` `st.claim_contribution(c.id, expect=c.status)` | the claim is the lock — a concurrent double-click loses the race and is skipped |
| 8 | **ONE** ACH debit fired: member funding source → Sol pool | `sol.py:223-229` `client.create_transfer(...)` with `idempotency_key=f"sol-contrib-{c.id}"` (`sol.py:250`) | amount is integer cents internally, converted to a `"200.00"` string only at the boundary (`sol.py:49 _cents_to_str`, `client.py:252 _money`) |
| 9 | Request built and sent | `client.py:120-145` — off-host guard at `client.py:122-125` refuses any absolute URL not on the configured Dwolla base (so a malicious `_links.href` cannot redirect a transfer); `Idempotency-Key` header set at `client.py:136-137` | **money instruction leaves the machine** |
| 10 | **PERSIST** — transfer URL recorded, row stays `processing` | `sol.py:230` `st.update_contribution(c.id, dwolla_transfer_url=url)` | `data/sol/sol.db` |
| 11 | On `DwollaError`: claim reverted to `pending` so it stays retryable | `sol.py:232-234` | the stable idempotency key makes the retry safe even if the debit actually landed |
| 12 | **PERSIST** — audit record | `actions.py` success path → `audit_log.py:45` | `data/governance/audit.jsonl` |

**Settlement arrives asynchronously and unauthenticated-but-verified:**

| # | Hop | file:line |
|---|---|---|
| 1 | `POST /sol/webhook` — **no admin auth** | `app/routers/sol.py:361-363` (mounted on `webhook_router`, `sol.py:46`) |
| 2 | Fail-closed HMAC-SHA256 over the raw body vs `DWOLLA_WEBHOOK_SECRET`, constant-time | `sol.py:365-369` `verify_webhook(raw, sig)` → `app/services/dwolla/client.py:232-244`; missing secret or missing signature → reject → 401 |
| 3 | Topic allowlist — only `_SUCCESS_TOPICS`/`_FAILURE_TOPICS` drive state | `sol.py:356-359`, checked `sol.py:377-379` |
| 4 | Transfer href → ledger row → idempotent, monotonic state transition | `sol.py:382-388` `engine.mark_contribution_result` / `sol.py:389-392` `mark_payout_result` (`app/services/sol/engine.py:111`, `:249`) |

Retry and payout follow the same shape: `_retry_failed` (`sol.py:255-299`) keys idempotency on `retry_count+1` and advances `retry_count` **only on a confirmed transfer** (`sol.py:288-290`), so a lost response reuses the same key; `_payout` (`sol.py:301-338`) guards on the existing payout's status/URL (`sol.py:310-314`) plus an atomic `st.claim_payout` (`sol.py:317`) before crediting.

**Known gap in the layered lock:** `is_scope_enabled` widens by wildcard parent (`app/services/governance/actions.py:60-62`, `parent = norm.split("_")[0]`), so `KAI_SCOPE_SOL=1` enables `sol.transfer`. `KAI_SCOPE_SOL` is exactly what the Sol reminder scheduler checks (`app/services/sol/scheduler.py:59-62`), so enabling the scheduler the obvious way also opens the transfer scope. The admin token and `approved=True` still stand in the way — this is not "money moves by itself" — but the advertised quadruple lock (`sol.py:23-25`) becomes a triple lock. The `[PR #42]` SWE work explicitly defends against this same pattern by putting push under a disjoint `swepush.execute` root; Sol has no equivalent.

```
 operator ──X-Admin-Token + {"approved": true}──> POST /admin/sol/cycles/7/collect
        │
   sol.py:44 admin gate → sol.py:53 _guard → sol.py:237 @audited(sol.transfer, destructive)
        │                                       actions.py:96 scope | :109 approval
        ▼
   sol.py:238 _collect
        ├─ storage.py (data/sol/sol.db)  read cycle + contributions
        ├─ client.py:80-85  sandbox latch (DWOLLA_ALLOW_PRODUCTION)
        ├─ client.py:89     POST {base}/token   ── DWOLLA_KEY:SECRET ──> dwolla
        └─ per contribution:
             sol.py:221  claim pending→processing        (atomic, SQLite)
             sol.py:223  create_transfer(Idempotency-Key: sol-contrib-{id})
                                                          ──── $ ────> dwolla
             sol.py:230  record transfer_url              (SQLite)
             sol.py:232  on error → revert to pending
        │
   audit_log.py:45 ──> data/governance/audit.jsonl
        │
        ⋯ hours later ⋯
   dwolla ──webhook──> POST /sol/webhook  (sol.py:361, NO admin auth)
             sol.py:367 verify_webhook (HMAC, fail-closed) ─ bad → 401
             sol.py:382 engine.mark_contribution_result    (SQLite, idempotent)
```

### 3b. Stripe — subscription lifecycle

| # | Hop | file:line | Data |
|---|---|---|---|
| 1 | `POST /billing/checkout`, user JWT | `app/routers/billing.py:118-124` | `plan_code` only — **no user-supplied amount**; the price id comes from the in-code tier registry (`app/services/billing/tiers.py`), unknown → 503 |
| 2 | Stripe Checkout session created | `billing.py:145-146` (`STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL`) | redirect URL returned |
| 3 | Card data never touches this backend — it is entered on Stripe | — | |
| 4 | `POST /billing/webhook` — the only trust boundary | `billing.py:299-309`; `stripe_service.construct_event` at `app/services/stripe_service.py:116-137` | missing signature → 400, bad signature → 400 (never 500) |
| 5 | **PERSIST** — `checkout.session.completed` upserts by `stripe_subscription_id` | `billing.py:374` `_handle_checkout_completed` | `subscriptions` (`app/models/subscription.py:34`), plus a mirrored `profiles.tier` write |
| 6 | `subscription.updated` / `.deleted` / `invoice.payment_failed` | `billing.py:435`, `:471`, `:493` | status + tier mutations |

Tier resolution prefers `metadata.plan_code`, else reverse-maps the price id (`billing.py:360` `_extract_price_id`); anything resolving to `free`/unknown is rejected rather than defaulted (`billing.py:389-394`).

**Finding:** none of the four Stripe handlers is wrapped in `@audited` — a real-money tier change writes to Postgres with no entry in `data/governance/audit.jsonl`. Only Sol/Dwolla money is audited. The winback discount path (`billing.py:226-277`) also calls Stripe with hand-rolled `urllib` rather than the SDK, using a hardcoded coupon (`billing.py:216`) the user cannot choose.

---

## 4. Flow D — document / RAG ingestion

Entry: `POST /account/documents` (multipart), `app/routers/documents.py:58-63`.

| # | Hop | file:line | Data / persistence |
|---|---|---|---|
| 1 | Supabase user JWT | `documents.py:61` `Depends(get_current_user)` | |
| 2 | **Paid-tier gate** — tier ∈ {pro, max, ultra}, else 402 | `documents.py:30`, `:33-47` | reads `profiles.tier` (`app/models/profile.py:31`) |
| 3 | Whole file read into memory | `documents.py:65` `raw = await file.read()` | bytes |
| 4 | Size / emptiness checks, then extension-first dispatch to a text extractor | `app/services/documents.py:161-167`, `:168-200` (PDF/docx/xlsx/pptx/text) | plaintext |
| 5 | Truncation to `MAX_TEXT_CHARS`, per-user document quota check | `documents.py:203-215` | |
| 6 | **PERSIST #1 — full document text** | `app/services/documents.py:217-225` (`db.add` + `db.commit`) | `kai_documents.full_text` stored **whole and indefinitely** (`app/models/document.py:22`), tenant key `user_id` FK CASCADE |
| 7 | RAG v2 indexing — non-fatal if it fails | `documents.py:227-234` → `app/services/rag.py:107` `index_document` | |
| 8 | Chunk, then batch-embed (`EMBED_BATCH = 96`, `rag.py:46`) | `rag.py:121` `_embed_batch(batch)` → `rag.py:74-100` | **the document's text leaves the machine** — a raw `urllib` POST to `https://api.openai.com/v1/embeddings` (`rag.py:85-88`) with `Authorization: Bearer {OPENAI_API_KEY}`, key read at `rag.py:79` |
| 9 | **PERSIST #2 — chunks + vectors**, committed per batch | `rag.py:131-147` raw parameterized `INSERT INTO kai_doc_chunks (doc_id, user_id, position, content, embedding) … CAST(:embedding AS vector)`, `db.commit()` at `rag.py:147` | `kai_doc_chunks` (`app/models/doc_chunk.py:20`) — ORM maps `embedding` as Text; the real column is `vector(1536)`, so all vector I/O is raw SQL |
| 10 | Embedding failure is tolerated: the chunk lands with `embedding=NULL` and is skipped at retrieval (`rag.py:23-25`) | | |

**Retrieval** happens two ways, both embedding the *query* to OpenAI first (`rag.py:169`):
- explicitly, `GET /account/documents/{doc_id}/retrieve` (`app/routers/documents.py:117`);
- from a chat turn, via the `document_search` tool (`app/services/tools/document_search.py:19`, `:53` `rag.retrieve(ctx.session, user_id=ctx.user_id, query=query, k=k)`) — reached through the ungoverned choke point at `router.py:374`. It is read-only and correctly scoped by `ctx.user_id`.

A second, separate embedding pipeline exists for **memories** (`app/services/memory/embeddings.py:36-56`, OpenAI SDK rather than raw urllib) writing `memories.embedding` (`app/models/memory.py:18`). Note `memories` has **no ORM-level FK to `profiles`** (`app/models/memory.py:26-28`, deliberately omitted; declared only in the migration) — tenant integrity there depends on the live DB having the constraint. **UNVERIFIED against production**; confirming needs `\d memories` on the prod database.

```
 user (paid tier) ──multipart──> POST /account/documents   documents.py:58
        │
   documents.py:33-47  tier gate (402 if free)
        │
   services/documents.py:168-200  extract text (pdf/docx/xlsx/pptx/txt)
        │
   services/documents.py:217-225  INSERT kai_documents.full_text   [PG, forever]
        │
   rag.py:107 index_document
        ├─ chunk
        ├─ rag.py:74-88  POST https://api.openai.com/v1/embeddings
        │                  Authorization: Bearer $OPENAI_API_KEY   ── text ──>
        └─ rag.py:131-147 INSERT kai_doc_chunks(embedding vector)  [PG]
                          (failure → embedding NULL, doc still usable)

 query time:
   documents.py:117  /retrieve            ┐
   tools/document_search.py:53            ┼─> rag.py:169 embed query ──> openai
   (via router.py:374 tool loop)          ┘   rag.py:180 ORDER BY embedding <=>
```

Retention: there is none. `grep -rn "retention|prune|VACUUM|DELETE FROM" backend/app` surfaces only a comment in `billing.py:203`, the `cancellation_reason.py` docstring, and `app/services/planning/storage.py:406`. Document text, chat message content, and memories persist indefinitely; deletion happens only via `DELETE /account/documents/{id}` (`documents.py:145`), `app/services/memory/store.py:75`, or cascade on profile delete.

---

## 5. Flow E — a background job

Two classes exist. **(a)** In-process daemon threads started by the FastAPI lifespan (`app/main.py:40-151`), all default-OFF, each start wrapped so a failure only logs a warning, stopped in reverse order (`main.py:118-151`). **(b)** Celery, defined at `app/workers/celery_app.py:27-39` with market-data ingest and prediction beats, broker/result `redis://localhost:6379/0|1` (`app/config.py:66-67`) — **not started by the app process**; the only in-app consumer is manual enqueue + `AsyncResult` polling from `app/routers/admin_data.py:14-49`. There is no Procfile or Dockerfile under `backend/`, so **whether celery beat runs in production is UNVERIFIED** — confirming needs the operator's launchd/process list on the Mac mini.

Traced here: the **daily check-in scheduler**, because it is the one that composes content and pushes it off-box.

| # | Hop | file:line | Data |
|---|---|---|---|
| 1 | Lifespan starts the thread iff `KAI_CHECKIN_SCHEDULER_ENABLED=1` | `app/main.py:104-112` → `app/services/checkin/scheduler.py:251` `start()` | |
| 2 | Loop wakes every 60s | `checkin/scheduler.py:222-249` `_loop` | |
| 3 | Scope re-checked **each cycle**, not once at start | `checkin/scheduler.py:53-59` `_scope_on()` (`KAI_SCOPE_CHECKIN`), skip logged at `:237` | turning the scope off stops the job without a restart |
| 4 | Fires once per calendar day at `KAI_CHECKIN_HOUR_UTC` (default 13, `scheduler.py:44-51`), deduped by date key | `scheduler.py:96-108` `run_checkin`, `storage.has_checkin(date_key)` at `:108` | |
| 5 | Message composed **locally — no LLM call** | `scheduler.py:111` → `app/services/checkin/composer.py:67-84` | pulls operator name, recent mood (from `data/eq/eq.db`), active goal, days-known (from the relationship store) and string-formats them |
| 6 | **PERSIST #1** — record written *before* the send attempt, `sent=False, pending=True` | `scheduler.py:114` `storage.record_checkin(...)` → `app/services/checkin/storage.py:27` (`KAI_CHECKIN_DB_PATH`, default `data/checkin/checkin.db`) | table `checkins` (`checkin/storage.py:50`), **no `user_id` column** |
| 7 | Delivery — synchronous Telegram send | `scheduler.py:88-93` `_deliver` → `app/services/observability.py:35` `send_sync` → `observability.py:58` POST `https://api.telegram.org/bot{tok}/sendMessage` | **the composed message leaves the machine to Telegram.** Token + chat id read at `observability.py:43-44`; both unset → silent no-op (`observability.py:86`) |
| 8 | **PERSIST #2** — attempt outcome | `scheduler.py:130` `storage.record_attempt(date_key, success=ok)` | |
| 9 | Retry pass on **every** 60s tick with exponential backoff, capped by `KAI_CHECKIN_RETRY_{BASE,CAP}_SECONDS`, `_MAX_AGE_HOURS` (24), `_MAX_ATTEMPTS` | `scheduler.py:139-153` `_is_due`, `:155-220` `retry_due_unsent`, giving-up notification at `:212-214` | |

```
 uvicorn lifespan (main.py:104-112)
        │  KAI_CHECKIN_SCHEDULER_ENABLED=1
        ▼
 checkin/scheduler.py:222  _loop  ── every 60s ──┐
        │                                        │
   :53 _scope_on()  KAI_SCOPE_CHECKIN ── off ──> skip
        │                                        │
   hour == KAI_CHECKIN_HOUR_UTC (13)             │  every tick:
        │                                        └─> :155 retry_due_unsent
   :111 composer.compose_checkin()                     (backoff, max age 24h)
        │  (local string build — NO LLM, NO network)
   :114 storage.record_checkin(sent=False)  ──> data/checkin/checkin.db (no user_id)
        │
   :88  _deliver → observability.py:35 send_sync
        │   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  (observability.py:43-44)
        └──────────── message ────────────> https://api.telegram.org
        │
   :130 storage.record_attempt(success)
```

The other five lifespan threads follow the same shape (`main.py:47-51` supreme, `:56-60` self-heal, `:67-71` research, `:77-81` digest, `:89-93` sol). Two differ materially:

- **self-heal** (`app/services/self_heal_scheduler.py:45-58`) is the only scheduler that **writes to the host**: `heal(apply=True)` rewrites `OLLAMA_MODEL_MAP` inside the `.env` file (`app/services/self_heal.py:147-148`) and `rmtree`s every `__pycache__` under the repo (`self_heal.py:154-165`). It requires three simultaneous conditions re-checked every tick — `KAI_SELF_HEAL_SCHEDULER_ENABLED`, the `self_heal` scope, and `KAI_SELF_HEAL_ENABLED`. Note the scope's wildcard parent is `SELF`, so `KAI_SCOPE_SELF=1` enables it.
- **sol** (`app/services/sol/scheduler.py:87-106`) never moves money — it scans due actions and notifies — but under `KAI_SOL_AUTOPILOT` it auto-advances circle cycles, serialized by a module-level lock (`sol/scheduler.py:34`).

---

## 6. Cross-cutting: where data ends up

| Store | Location | Tenant key |
|---|---|---|
| Postgres/Supabase | `profiles`, `subscriptions`, `conversations`, `messages`, `memories`, `kai_documents`, `kai_doc_chunks`, `kai_api_keys`, `usage_log`, `llm_call_log`, … (`app/models/__init__.py:5-38`) | `user_id`, except `predictions` (`app/models/prediction.py:13`) and `audit_log` (`app/models/admin.py:26-31`, nullable `actor_id` only) |
| 10 local SQLite DBs | `data/{journal,learning,eq,sol,relationship,kg,persona,twin,checkin}/*.db` + planning (`app/services/planning/storage.py:69`) | **none — zero `user_id` columns anywhere**. Includes real payment PII: `sol.db.members.email`, `dwolla_customer_id`, `funding_source_href` (`app/services/sol/storage.py:150-161`) |
| JSONL sinks | `data/governance/audit.jsonl` (`app/services/governance/audit_log.py:34-42`), `data/failures.jsonl` (`app/services/failure_memory/storage.py:41`), `data/research/digests.jsonl` (`app/services/research/digest.py:47`), `data/digest/digests.jsonl` (`app/services/digest/digest.py:25`) | none; unbounded growth, no rotation |

Migration head is `0006_add_kai_api_keys` on merged `istanbul`; `0007_add_kai_swe_tasks` on this branch (`alembic/versions/0007_add_kai_swe_tasks.py:24-25`). **Three competing `0007` revisions exist across branches** (this one, PR #40's `0007_add_kai_code_chunks`, and `origin/feat/sol-v1`'s `0007_sol_v1_data_model`), all with `down_revision = "0006_add_kai_api_keys"` — merging any two produces multiple alembic heads and `alembic upgrade head` will fail until a merge revision is written.

---

## 7. Explicitly unverified

- `fix/kai-governed-tool-loop` (#39) and `fix/kai-code-intelligence` (#40) source: **not in this checkout**. `app/services/code_intel/` here contains only stale `__pycache__` `.pyc` files, no `.py` source — a grep-based reader can easily mistake it for present code.
- Whether celery beat/worker actually runs in production (no Procfile/Dockerfile under `backend/`).
- Whether the `memories.user_id → profiles.id` FK exists in the live database (the ORM omits it by design, `app/models/memory.py:26-28`).
- The exact contents of the operator's root `.env` (~230 keys per `deploy/start_nai.sh` comments) — not in the repo, not read.
