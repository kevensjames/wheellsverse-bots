# KAI — Current-State Architecture

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit`
**Branch this document was written from:** `feat/kai-swe-agent` (HEAD `4850b0d`)
**Merged baseline:** `origin/istanbul` (HEAD `2fe6e46`, "Fix/kai critical reliability (#33)")
**Date:** 2026-07-22

Every claim below cites a file:line that was read, or a command that was run. Anything not
verified is marked **UNVERIFIED** with what would be needed to confirm it.

---

## 0. Provenance — merged vs open PR

Verified with:

```
git merge-base --is-ancestor origin/<branch> origin/istanbul
```

| Branch | PR | Merged into `istanbul`? |
|---|---|---|
| `fix/kai-governed-tool-loop` | #39 | **NO** |
| `fix/kai-code-intelligence` | #40 | **NO** |
| `fix/kai-swe-sandbox` | #41 | **NO** |
| `feat/kai-swe-agent` | #42 | **NO** |

`git diff --name-only origin/istanbul...HEAD` on this checkout returns exactly 30 paths — the
SWE work of #41 + #42 stacked together. Everything else described in this document is on
**merged `istanbul`**.

### Component-by-component provenance table

| Component | Path | Status |
|---|---|---|
| Chat / SSE router | `backend/app/routers/nai.py` | merged istanbul |
| OpenAI-compatible API | `backend/app/routers/v1.py` | merged istanbul |
| Operator chat | `backend/app/routers/admin_chat.py` | merged istanbul |
| Model router + adapters | `backend/app/services/router/` | merged istanbul |
| Tool framework + 30-odd tools | `backend/app/services/tools/` | merged istanbul |
| Governance (`@audited`, audit JSONL) | `backend/app/services/governance/actions.py` | merged istanbul |
| Sol ROSCA + Dwolla ACH | `backend/app/routers/sol.py`, `app/services/sol/`, `app/services/dwolla/` | merged istanbul |
| Stripe billing | `backend/app/routers/billing.py` | merged istanbul |
| Schedulers (supreme, self-heal, research, digest, sol, checkin) | `backend/app/main.py:47-112` + `app/services/*/scheduler.py` | merged istanbul |
| Celery workers | `backend/app/workers/` | merged istanbul |
| Deploy (launchd, cloudflared, health check) | `deploy/` | merged istanbul |
| **Governed tool registry** (scope + default-deny writes + audit on `registry.execute`) | `backend/app/services/tools/registry.py` | **PR #39 only — NOT in this checkout** |
| **Code intelligence** (`code_intel/`, `kai_code_chunks`, migration `0007_add_kai_code_chunks`) | `backend/app/services/code_intel/` | **PR #40 only — NOT in this checkout.** What exists here is stale `__pycache__/*.pyc` with no `.py` source. `git log --all -- backend/app/services/code_intel` → `728c334`, only on `fix/kai-code-intelligence`. |
| **SWE sandbox** (`swe_runtime/sandbox.py`, `admin_swe.py`) | commit `0e72db2` | **PR #41 — on this branch, not on istanbul** |
| **SWE agent** (`swe_runtime/brain.py`, `push.py`, `admin_swe_tasks.py`, `dependencies/approver.py`, `models/swe_task.py`, migration `0007_add_kai_swe_tasks`, hardened `audit_log.py` value-redaction) | commits `4850b0d`, `43645e8` | **PR #42 — on this branch, not on istanbul** |

---

## 1. System overview

KAI is a single-process FastAPI application (`backend/app/main.py`) that fronts:

- a **multi-provider LLM router** with intent-based model selection and spend caps
  (`app/services/router/router.py`),
- a **tool-calling loop** with ~30 registered tools, several of which reach external SaaS
  with operator credentials (`app/services/tools/`),
- a **governance/audit layer** applied to admin routes and library operations
  (`app/services/governance/actions.py`),
- **two independent money systems** — Stripe card subscriptions (`app/routers/billing.py`)
  and Dwolla ACH for the Sol ROSCA product (`app/routers/sol.py`),
- **six in-process daemon schedulers** plus a Celery beat/worker pair for market data,
- a **34-router HTTP surface** (`ls app/routers/*.py` → 34), of which 23+ are `/admin/*`.

Persistence is split three ways: Postgres/Supabase via SQLAlchemy + Alembic, **ten local
SQLite sidecar databases**, and four append-only JSONL logs.

Production is a **single uvicorn worker on a Mac mini**, exposed only through a Cloudflare
Tunnel. Single-worker is a correctness dependency, not just capacity — admin brute-force
throttling and rate limiting keep state in process memory (`app/dependencies/admin.py`,
`app/core/rate_limit.py`).

---

## 2. Request paths

### 2.1 Router mounting

The chat router is **dual-mounted** during the NAI→KAI rename (`app/main.py:235-236`):

```python
app.include_router(nai.router, prefix="/kai")
app.include_router(nai.router, prefix="/nai")
```

Every chat route therefore exists twice. `v1.router` at `main.py:231`; `admin_chat.router`
at `main.py:184`.

The SWE admin surface is **conditionally mounted** (`main.py:192-195`, PR #41/#42):

```python
from app.services.swe_runtime.config import swe_admin_enabled
if swe_admin_enabled():
    app.include_router(admin_swe.router)
    app.include_router(admin_swe_tasks.router)
```

On a production `APP_ENV` the routes do not exist at all (`swe_runtime/config.py:31-39`).

Middleware order: SlowAPI (`main.py:164`), CORS (`:166`), SecurityHeaders added last so it is
outermost and stamps SSE responses too (`:178`).

### 2.2 Route table

| Method + path | File:line | Auth | Notes |
|---|---|---|---|
| `POST /kai/chat`, `POST /nai/chat` | `nai.py:49-53` | `Depends(get_current_user)` → `dependencies/supabase_jwt.py:109` | Full tool loop when `use_tools`. Optional `auto_route` super-router (`nai.py:61-71`). |
| `GET /kai/chat/stream` | `nai.py:100-106` | `Depends(get_user_for_stream)` → `supabase_jwt.py:129` | SSE. Cookie `nai_access` preferred; **deprecated `?token=` query fallback still accepted** (`supabase_jwt.py:133-137`, logs a warning). Tools disabled. |
| `GET /kai/conversations` | `nai.py:121` | `get_current_user` | |
| `GET /kai/conversations/{id}` | `nai.py:141` | `get_current_user` | |
| `DELETE /kai/conversations/{id}` | `nai.py:160` | `get_current_user` | |
| `POST /admin/kai-chat` | `admin_chat.py:167` | router-level `require_admin_token` (`admin_chat.py:48`) | Forces tier `ultra`, unfiltered registry, optional self-correction + verification passes. No streaming variant. |
| `POST /v1/chat/completions` | `v1.py:87-88` | `require_api_key_user` (`dependencies/api_key_auth.py:30`) | OpenAI-compatible. **`stream:true` is fake streaming** — blocking `complete()` first, then role-chunk / whole-text-chunk / stop / `[DONE]` (`v1.py:135-155`, comment at `:136` says so). No tool loop, no persistence. |
| `GET /v1/models` | `v1.py:176-177` | `require_api_key_user` | |
| `POST /billing/webhook` | `billing.py:298` | Stripe HMAC via `construct_event` (`billing.py:309`) | Missing/bad signature → 400, never 500. |
| `POST /sol/webhook` | `sol.py:361` (`webhook_router`, `sol.py:46`) | Dwolla HMAC-SHA256, fail-closed, constant-time (`dwolla/client.py:232-244`) | The only unauthenticated non-webhook-verified-free route. |
| `/admin/sol/*` | `sol.py:44` | router-level `require_admin_token` | See §7. |

**No chat, stream, or completions route is rate-limited.** `app/core/rate_limit.py:19` sets
`default_limits=[]` and `grep -n "limiter.limit" app/routers/*.py` hits only `auth.py` (59,
90, 104).

---

## 3. Model routing and providers

### 3.1 Construction

`build_default_router(session)` (`app/services/router/__init__.py:40-63`) iterates candidate
adapters openai / anthropic / perplexity / ollama / cloudflare; each adapter `__init__` raises
`RuntimeError` when its key is unset and is silently skipped (`__init__.py:29-37`).
`Router.__init__` hard-requires openai (`router.py:23` `REQUIRED_ADAPTERS =
frozenset({"openai"})`, enforced `router.py:39-41`) — with no `OPENAI_API_KEY` the chat
endpoint raises at construction.

### 3.2 Selection (`router.py:96-116`, strictly ordered)

1. `prefer_local=True` → ollama (`:102-104`)
2. `spend.over_daily_cap(user_id)` → ollama (`:106-108`)
3. `Intent.CODE` → anthropic (`:110`)
4. `Intent.REALTIME` → perplexity (`:112`)
5. `Intent.SIMPLE` → cloudflare (`:114`)
6. else → openai (`:116`)

Intent classification is a single regex pass over the **last user message only**
(`app/services/router/intent.py:54-71`); SIMPLE additionally caps at 200 chars
(`intent.py:47`).

### 3.3 Fallback — three distinct mechanisms

- **Config-time**: `_get()` (`router.py:45-55`) — preferred adapter not configured → openai.
- **Runtime, non-tool**: `_runtime_fallback()` (`router.py:57-73`) rescues **only** a failed
  ollama → openai. A failed cloud adapter alerts and re-raises (`router.py:147-152`).
- **Runtime, tool loop**: `_next_tool_brain()` (`router.py:75-82`) tries anthropic then
  openai; on exhaustion `chat()` degrades to a plain ollama answer **with tools dropped**
  (`router.py:326-345`).

`Router.stream()` (`router.py:171-228`) has **no fallback at all** — any adapter exception
logs, alerts, and re-raises (`router.py:204-213`).

Tool-capability guard: `TOOL_INCAPABLE_ADAPTERS = {"cloudflare","perplexity","ollama"}`
(`router.py:30`); when a registry is passed and the selected adapter is in that set, `chat()`
swaps to openai (`router.py:268-277`).

### 3.4 Providers

| Adapter | File | Key env | Network target |
|---|---|---|---|
| openai | `adapters/openai_adapter.py:21-26` | `OPENAI_API_KEY` | OpenAI SDK default |
| anthropic | `adapters/anthropic_adapter.py:21-26` | `ANTHROPIC_API_KEY` | Anthropic SDK |
| perplexity | `adapters/perplexity_adapter.py:21-26` | `PERPLEXITY_API_KEY` | `https://api.perplexity.ai` |
| ollama | `adapters/ollama_adapter.py:18-25,55,88` | none | `OLLAMA_HOST`, default `http://127.0.0.1:11434` |
| cloudflare | `adapters/cloudflare_adapter.py:47-64,105,161` | `CLOUDFLARE_AI_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | `api.cloudflare.com/.../ai/run/{model}`; spoofed Mozilla UA (`:79-81`) because the default httpx UA triggers CF error 1010 |

### 3.5 Spend tracking

`app/services/router/spend_tracker.py` writes to `llm_call_log` via parameterized `text()` SQL
(`:51-74`); `log_result()` (`:76-86`) is called at `router.py:168` (complete), `:349` (each
tool-loop turn), `:344` (degraded local). Caps read at import time:
`NAI_MAX_DAILY_SPEND_USD` default 2.00, `NAI_MAX_MONTHLY_SPEND_USD` default 60.00
(`spend_tracker.py:18-19`). Only `over_daily_cap` is consulted (`router.py:106`);
`over_monthly_cap` (`spend_tracker.py:119`) is defined but never referenced in `router.py`.

Two honest weaknesses:

- **Streaming cost is estimated, not measured** — `router.py:215-228` computes
  `out_tokens = len(text)//4`, tagged `metadata={"streamed": True, "estimated_tokens": True}`.
- **`calculate_cost` returns 0.0 silently for unknown models** (`adapters/base.py:11-37`).
- Cap enforcement is **degrade-only and evaluated once at turn start** — a multi-iteration
  tool loop can run its full `max_tool_iters` past the cap without re-checking.

---

## 4. Tool framework

### 4.1 The single choke point

```python
# app/services/router/router.py:374
tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)
```

Inside the per-tool-call loop (`router.py:373-408`), inside the bounded outer loop
(`router.py:297`, `DEFAULT_MAX_TOOL_ITERS = 5` at `router.py:25`; exhaustion raises
`ToolLoopExceededError` at `router.py:410`).

Downstream is `ToolRegistry.execute` (`app/services/tools/registry.py:58-84`). Read in full:
it does a dict lookup and `output = tool.execute(ctx, **arguments)` (`registry.py:68`), with
only `ToolError`/`Exception` handling around it. **On merged istanbul there is no scope check,
no approval check, no audit record, and no allowlist on that path.** Confirmed by
`grep -rn "@audited" app/services/tools/` → 0 matches.

**PR #39 is what closes this.** Its diff adds to `registry.py` a `writes`/`scope`
class-attribute read, a scope gate via `is_scope_enabled`, a default-deny `ctx.allow_writes`
check for side-effecting tools, and `record_action(...)` on every path including block and
error; it threads `allow_writes: bool = False` through `Brain.chat` into `ToolContext`.

### 4.2 Reachability

- `POST /kai/chat` with `use_tools=true` → `Brain.chat` (`app/services/nai_brain/brain.py:201-211`)
  builds `ToolContext(user_id, session)` and calls `Router.chat`. **Reaches the choke point.**
- `POST /admin/kai-chat` with `use_tools=true` → same path, unfiltered registry
  (`admin_chat.py:167-176`). **Reaches it.**
- `GET /kai/chat/stream` → `Brain.stream` (`brain.py:279`) → `Router.stream`, which never
  passes a registry. **Cannot reach it.**
- `POST /v1/chat/completions` → `Router.complete` (`v1.py:117`). **Cannot reach it.**

### 4.3 Registered tools (`app/services/tools/__init__.py:46-160+`)

Unconditional: `memory`, `trading_signal`, `web_fetch`, `kg_query`, `document_search`,
`verify_claim`, `pubmed_search`, `sec_edgar_search`, `courtlistener_search`, `who_search`,
`clinicaltrials_search`, `suggest_agent`, `failure_lookup`, `plan_query`, `learning_query`,
`twin_query`, `audit_query`, `github_scout`, `site_builder`, `image_gen`.

Conditional on env: `web_search` (`PERPLEXITY_API_KEY`), `twenty_crm` (`TWENTY_API_URL` +
`TWENTY_API_KEY`), `dwolla` (read-only, `DWOLLA_KEY` + `DWOLLA_SECRET`), `video_gen`
(`RUNWAYML_API_KEY`), `browser` (`KAI_BROWSER_ENABLED`), `notion` + `composio`
(`COMPOSIO_API_KEY`), MCP (config-file presence, **defaults to on**, `__init__.py:64-66`).

Writing tools and their sinks:

| Tool | Write |
|---|---|
| `memory_tool` | DB insert + `ctx.session.commit()` — `memory_tool.py:87-93` |
| `twenty_crm` | `POST {TWENTY_API_URL}/rest/{obj}` — `twenty_crm.py:133-135` |
| `notion` | `create_page` / `append_blocks` in the operator's workspace — `composio_notion.py:44-48` |
| `composio` | `action='execute'` with any `tool_slug` (e.g. `GMAIL_SEND_EMAIL`) — `composio_generic.py:44-70`. **Unbounded mutation of ~200 connected SaaS accounts.** Compounded by `composio_auth.py:35-37`: when `COMPOSIO_USER_ID` is set, every user's calls resolve to that one identity. |
| `mcp_<label>__<tool>` | whatever the operator's MCP servers do — `mcp_tools.py:161,180-191` |
| `site_builder` | LLM-generated HTML to `KAI_SITE_DRAFTS_DIR` — `site_builder.py:24` |
| `image_gen` / `video_gen` | files on disk; Runway credits — `image_gen.py:27-33`, `video_gen.py:22-26` |

Deliberately fenced: `dwolla_tool.py` exposes six read actions only (`account`,
`list_customers`, `get_customer`, `list_funding_sources`, `list_transfers`, `get_transfer`) —
no create/transfer action exists, so **money movement is unreachable from a prompt**.
`browser_tool.py:23` exposes only `read` and `propose_write` (dry-run). `github_scout.py:11-14`
never clones or executes.

### 4.4 `web_fetch` SSRF

`web_fetch.py:62-78` string-prefix-matches the **literal hostname** against `10.`, `192.168.`,
`172.16–31.`, `169.254.`, then calls `httpx.get(..., follow_redirects=True)`. A hostname whose
DNS resolves privately, a decimal/hex IP literal, IPv6 forms, `172.32+`, and any public URL
that 302s to `169.254.169.254` all pass, and the redirect is followed with no re-check.

---

## 5. Governance and audit

`@audited(scope, destructive=)` (`app/services/governance/actions.py:71`) wraps a **sync**
callable: pops `approved`/`actor` kwargs → `is_scope_enabled(scope)` else `ScopeDenied` (403)
→ if `destructive and not approved` → `PendingApproval` (409) → run → `record_action` on every
path. Sink is an append-only JSONL at `KAI_AUDIT_LOG_PATH` (`audit_log.py:36`).

Forty scopes are declared across the codebase. Destructive ones include `sol.transfer`,
`dwolla.transfer`, `stripe.refund`, `self_heal`, `digest.run`, `kg.add_edge`,
`browser.execute`, `learning.dismiss|activate`, `persona.activate|archive`,
`planning.{revise,execute,edit,create,approve}`, `twin.{archive,activate}`, and (PR-only)
`swe.run`, `swe.brain.execute`, `swepush.execute`.

### Known weaknesses in the mechanism

1. **Wildcard-parent scope widening.** Read at `actions.py:56-63`:

   ```python
   norm = scope.replace(".", "_").replace("-", "_").upper()
   if _is_env_truthy(f"KAI_SCOPE_{norm}"): return True
   parent = norm.split("_")[0]
   if parent and _is_env_truthy(f"KAI_SCOPE_{parent}"): return True
   ```

   So `KAI_SCOPE_SOL=1` transitively enables `sol.transfer` (real ACH), `KAI_SCOPE_DWOLLA`
   enables `dwolla.transfer`, `KAI_SCOPE_BROWSER` enables `browser.execute`,
   `KAI_SCOPE_PLANNING` enables `planning.execute`, and `KAI_SCOPE_SELF` enables `self_heal`
   (parent of `SELF_HEAL` is `SELF`). `KAI_SCOPE_SOL` is exactly the var the Sol scheduler
   checks (`sol/scheduler.py:60-62`), so enabling reminders the obvious way opens the transfer
   scope. The SWE work explicitly defends against this (`.env.example:72-77` warns not to set
   the `KAI_SCOPE_SWE` wildcard, and push lives under a disjoint `swepush.execute` root,
   `admin_swe_tasks.py:273`). Sol, Dwolla, browser, and planning got no equivalent.

2. **`approved` is caller-supplied, not proven** — `actions.py:91` pops it from kwargs and
   routes forward it straight from the request body (`sol.py:340-352`,
   `admin_self_heal.py:57`). Anyone holding the shared admin token can set `approved: true`.

3. **`@audited` is sync-only** — the wrapper at `actions.py:90` is a plain `def`. Decorating an
   `async def` would log success against an un-awaited coroutine. No current target is async.

4. **The audit log is not tamper-evident.** `grep -rn "prev_hash|chain|hmac"
   app/services/governance/` → none. Plain appended JSON lines, writable by the daemon, while
   `app/services/audit/auditor.py:31` advertises it as a "tamper-evident action log".
   `record_action` is fail-soft (`audit_log.py:82-83`), so a write failure silently drops the
   record. The one exception is the SWE push, which fsyncs-or-aborts (`swe_runtime/push.py:22-23,161`).

5. **Redaction is name/shape-based** (`audit_log.py:89-103`) — misses any secret whose key
   isn't in the pattern list and whose value doesn't match the regex. Value-level scrubbing
   (`bearer …`, `gh[posur]_…`, `github_pat_…`, `sk-…`) is **PR #42 only**; merged istanbul has
   key-based redaction only.

### Where governance does not apply

- **The entire tool surface** (§4.1).
- **The Stripe webhook** — none of the four handlers in `billing.py:298+` are `@audited`; tier
  changes are written directly to the DB.
- **Admin write endpoints with no `@audited`**: `POST /admin/ingest/all`, `/admin/ingest/{symbol}`,
  `/admin/predict/all`, `/admin/predict/{symbol}` (`admin_data.py:31-77`, Celery fan-out),
  `POST /admin/supreme/scan` (`admin_supreme.py:77`), `POST /admin/learning/feedback`
  (`admin_learning.py:55`), `POST /admin/journal/entries` (`admin_journal.py:58`),
  `POST /admin/persona/entries` (`admin_persona.py:55`), `POST /admin/twin/entries`
  (`admin_twin.py:78`), `POST /admin/relationship/milestones` (`admin_relationship.py:41`).
- **`POST /admin/planning/{id}/execute-next`** (`admin_planning.py:323` →
  `_audited_execute_next`, `:201-215`) — this one *is* `@audited(planning.execute,
  destructive=True)`, but inside the approved call it does `registry = build_default_registry()`
  and hands the full registry to an LLM step runner. **One approval authorizes an unbounded,
  unaudited tool loop**; the audit record says `planning.execute` and nothing more.

---

## 6. Auth model — four independent credentials

| Credential | Dependency | Verification | Grants |
|---|---|---|---|
| **Supabase user JWT** (cookie `nai_access` or `Authorization: Bearer`) | `dependencies/supabase_jwt.py:109` (`get_current_user`), `:129` (`get_user_for_stream`) | ES256 via JWKS, strict `exp`/`iat`, `aud="authenticated"` (`supabase_jwt.py:72-88`). No DB round-trip. | `/kai/*`, `/nai/*`, `/account/*`, `/billing` — **plus the full ungoverned tool loop**. SSE still accepts a deprecated `?token=` query param (`supabase_jwt.py:133-137`), which lands tokens in logs and Referer headers. |
| **Shared admin token** `X-Admin-Token` | `dependencies/admin.py:99` `require_admin_token` | `hmac.compare_digest` (`admin.py:110`); >10 failures/300s per client → 429 (`admin.py:34-35,127`), throttle disabled in dev/test (`:42-45`); forwarded-IP headers trusted only from a loopback/private peer (`:48-59`). | **The entire `/admin/*` surface**, including Sol money. One secret, no roles, no per-route scoping, no rotation, no per-actor attribution — `actor` defaults to the literal string `"operator"` (`actions.py:75`). The file header says Stage 11 is supposed to replace this with real `admin_users` auth. |
| **API key** `Authorization: Bearer kai_...` | `dependencies/api_key_auth.py:30` `require_api_key_user` | `api_keys.verify` + owner profile lookup + tier ∈ `{max, ultra}` (`api_key_auth.py:27,60`) | `/v1/*` only. No tool loop (`v1.py:19` says function-calling "needs the full Brain loop, separate work"). Lowest-risk lane. |
| **Approver token** `X-Approver-Token` — **PR #42 only** | `dependencies/approver.py:39` `require_approver` | SHA-256 of the token matched against `admin_users.password_hash` (`approver.py:47-52`); returns the row's `email` as the audit identity. Optional separation of duties via `KAI_SWE_REQUIRE_TWO_PERSON` (`approver.py:34`, enforced `admin_swe_tasks.py:311`). | Only the three SWE gates. **The one place approval names a proven identity.** Gap: the SQL has **no `role` filter** despite the docstring prescribing `role='approver'` (`approver.py:19-20` vs `:48-50`) — any `admin_users` row whose `password_hash` is a raw SHA-256 hex qualifies. |

Cookie issuance/clearing lives in `dependencies/cookie_auth.py` (HttpOnly, SameSite=Lax, Secure
outside dev, refresh cookie scoped to `/auth`).

**Missing controls, stated plainly:** there is **no paid-tier gate on `/kai/chat`'s tool
registry**. Grepping `nai.py` and `app/services/nai_brain/` for `tier`/`gate` returns nothing,
contradicting `mcp_tools.py:30-32` ("Inherit the chat endpoint's paid-tier gate") and
`__init__.py:126` for Twenty. Any authenticated user drives the operator's CRM, Notion,
Composio and MCP servers.

---

## 7. Money paths

Two independent systems sharing no code.

### 7.1 Stripe (card, `app/routers/billing.py`, 510 lines)

- `POST /billing/checkout` (`:118`) — authed user; price ID must exist in the in-code tier
  registry else 503. No user-supplied amount — only `plan_code` → `tiers.price_id_for()`.
- `POST /billing/portal` (`:157`), `POST /billing/cancellation-reason` (`:186`).
- `POST /billing/winback/apply-discount` (`:225`) — hardcoded coupon
  `kai_winback_50off_1mo`; calls Stripe with raw `urllib` (`:259-277`), not the SDK.
- `POST /billing/webhook` (`:298`) — `stripe_service.construct_event` (`:309`) is documented as
  "the ONLY trust boundary" (`stripe_service.py:116-137`). Handlers:
  `checkout.session.completed` upserts by `stripe_subscription_id` (UNIQUE in prod → idempotent
  re-delivery, `:399-419`); `customer.subscription.updated/deleted` and
  `invoice.payment_failed` mutate status and mirror `profiles.tier`. A tier resolving to `free`
  or unknown is **rejected, not defaulted** (`:389-394`).

### 7.2 Sol ROSCA ACH (`app/routers/sol.py` + `app/services/sol/` + `app/services/dwolla/`)

Ledger is a **SQLite sidecar** at `data/sol/sol.db` (`sol/storage.py:33-37`), deliberately
isolated from the Postgres billing DB. Money is always integer cents; conversion to Dwolla's
`"200.00"` happens only at the API boundary (`sol.py:49`, `dwolla/client.py:252`).

Three transfer-initiating routes: `POST /admin/sol/cycles/{id}/collect` (`sol.py:340` →
`_collect` `:237`), `/retry-failed` (`:345` → `:255`), `/payout` (`:350` → `:301`). Each carries
`@audited(scope="sol.transfer", destructive=True)`.

Layered guards on each:

1. Router-level `require_admin_token` (`sol.py:44`).
2. Scope gate — `ScopeDenied` unless `KAI_SCOPE_SOL_TRANSFER` (or, per §5.1, the `KAI_SCOPE_SOL`
   wildcard) is truthy.
3. Explicit `approved=True` or `PendingApproval` → 409 (`actions.py:109-120`).
4. Sandbox lock — `DwollaClient.__init__` (`dwolla/client.py:80-85`) raises
   `DwollaProductionLocked` if `DWOLLA_ENV=production` without `DWOLLA_ALLOW_PRODUCTION=1`.
5. Two-layer idempotency — atomic conditional-UPDATE claims (`sol.py:221-222`, `:319`) plus a
   stable `Idempotency-Key` per ledger row (`client.py:132-137`); retry keys use
   `retry_count+1` and `retry_count` advances only on a confirmed transfer (`sol.py:279-291`),
   so a lost response reuses the same key.
6. Error revert to `pending` so the row stays retryable (`sol.py:232-234`, `:294-296`, `:335-337`).
7. Off-host SSRF guard — `client._request` refuses any absolute URL not on the configured
   Dwolla host (`client.py:122-125`), so a malicious `_links.href` cannot redirect a transfer.

Also `POST /admin/sol/customers` and `/customers/{id}/funding-sources` (`sol.py:180,186`) —
pass-through of raw operator dicts to Dwolla, provisioning bank accounts, under
`destructive=False`; they call the already-`@audited` `dwolla.customer`/`dwolla.funding`
operations directly to avoid double audit records (`sol.py:177-179` comment).

`operations.initiate_transfer` (`app/services/dwolla/operations.py:41`,
`@audited(dwolla.transfer, destructive=True)`) is a library/script surface — no HTTP route
reaches it.

Webhook `POST /sol/webhook` (`sol.py:361`): fail-closed HMAC-SHA256 over the raw body, constant-
time compared (`client.py:232-244`); missing secret or signature → 401. Only whitelisted topics
drive state, and transitions are idempotent and monotonic (`engine.mark_contribution_result:111`,
`mark_payout_result:249`).

**Documented limitations in the money model** (`sol/engine.py:16-25`): a transient orphan if a
Dwolla POST succeeds but the response is lost (self-heals via the stable idempotency key, no
double debit); and **no clawback** — a contribution that ACH-returns after its payout settled
does not claw back the disbursed pool.

---

## 8. Data model and migrations

### 8.1 Postgres (SQLAlchemy, `app/models/`, registry at `models/__init__.py:5-38`)

| Table | Model | Tenant key |
|---|---|---|
| `profiles` | `profile.py:31` — THE user table, mirrors Supabase `auth.users`; `tier` CHECK free/pro/max/ultra, `messages_used_today`, `stripe_customer_id` | `id` |
| `subscriptions` | `subscription.py:34` | `user_id` FK CASCADE |
| `conversations` | `conversation.py:41` | `user_id` FK CASCADE |
| `messages` | `conversation.py:93` — content + `tool_calls` JSONB + `cost_usd` | `user_id` denormalized (`:106`) |
| `memories` | `memory.py:18` — `pgvector Vector(1536)` NOT NULL | `user_id`, **FK deliberately omitted from the ORM** (`memory.py:26-28`), declared only in the migration |
| `kai_documents` | `document.py:22` — `full_text` stored whole | `user_id` FK CASCADE |
| `kai_doc_chunks` | `doc_chunk.py:20` — `embedding` mapped as Text in the ORM, real column is `vector(1536)`, read/written via raw SQL (`services/documents.py:38-41`) | `user_id` + `doc_id` |
| `kai_api_keys` | `api_key.py:24` | `user_id` FK CASCADE |
| `cancellation_reasons` | `cancellation_reason.py:23` | `user_id` |
| `usage_log` | `usage.py:12` | `user_id` |
| `watchlists`, `alerts` | `alert.py:12,31` | `user_id` |
| `assets`, `price_history` | `asset.py:9,20` | none — legitimately global |
| `predictions` | `prediction.py:13` | **none — global, not user-scoped** |
| `admin_users` | `admin.py:13` | n/a |
| `audit_log` | `admin.py:26` | only a nullable `actor_id` (`:31`) |
| `llm_call_log` | **no ORM model** — migration only, `alembic/versions/0004:22-64` | `user_id` FK CASCADE |
| `kai_swe_tasks` | `swe_task.py:33` — **PR #42 only**; 9-state CHECK (`:26-30`), `plan`/`patch`/`patch_sha256`/`review_branch`/approver columns | **none by design** — "Single-operator model — no user_id / RLS" (`swe_task.py:9`) |
| `kai_code_chunks` | **PR #40 only** — `Vector(1536)`, `repo_id`/`path`/`symbol`/`content_sha` | `user_id` |

Legacy: `0001_initial_schema.py` creates `users` (`:25`) and `plans` (`:44`), both now dead
(`models/__init__.py:1-4`, `subscription.py:9-12`) — later code FKs to `profiles`.

### 8.2 Migration chain

`ls backend/alembic/versions/` on this branch:
`0001_initial_schema` → `0002_stripe_customer_id` → `0003_add_memories_table` →
`0004_add_llm_call_log_table` → `0005_stage4_enhance_conversations_messages` →
`0006_add_kai_api_keys` → `0007_add_kai_swe_tasks`.

- **Head on merged istanbul: `0006_add_kai_api_keys`** (istanbul ships 0001–0006 only).
- Head on this branch: `0007_add_kai_swe_tasks` (`:24-25`).
- `0001:22` creates extension `pgcrypto`; `0003:23` creates extension `vector`.

**Three competing `0007` revisions exist across branches**, all with
`down_revision = "0006_add_kai_api_keys"`:

1. `feat/kai-swe-agent` → `0007_add_kai_swe_tasks` (`:24-25`)
2. `fix/kai-code-intelligence` → `0007_add_kai_code_chunks` (`:19-20`)
3. `origin/feat/sol-v1` → `0007_sol_v1_data_model` (`:17-18`), continuing 0008…0020

Revision ids differ so alembic will not hard-collide, but merging any two produces **multiple
alembic heads** and `alembic upgrade head` fails until a merge revision is written. PRs #39 and
#41 add no migrations.

### 8.3 The shadow persistence layer — 10 SQLite sidecars (all on merged istanbul)

None are in alembic, none has a tenant key, all default under `<repo>/data/`, each env-overridable:

| Env (default) | File | Tables |
|---|---|---|
| `KAI_JOURNAL_DB_PATH` (`data/journal/journal.db`) | `services/journal/storage.py:25` | `journal_entries` `:45` |
| `KAI_LEARNING_DB_PATH` | `services/learning/storage.py:36` | `feedback` `:82`, `lessons` `:92` |
| `KAI_EQ_DB_PATH` | `services/eq/storage.py:25` | `mood_samples` `:47` |
| `KAI_SOL_DB_PATH` | `services/sol/storage.py:34` | `circles`, `members` (name/email/`dwolla_customer_id`/`funding_source_href`), `cycles`, `contributions`, `payouts` `:138-196` |
| `KAI_RELATIONSHIP_DB_PATH` | `services/relationship/storage.py:30` | `relationship_state` `:54`, `milestones` `:63` |
| `KAI_KG_DB_PATH` | `services/kg/storage.py:47` | `entities` `:85`, `edges` `:96` |
| `KAI_PERSONA_DB_PATH` | `services/persona/storage.py:31` | `entries` `:84` |
| `KAI_TWIN_DB_PATH` | `services/twin/storage.py:34` | `entries` `:77`, `drafts` `:89` |
| `KAI_CHECKIN_DB_PATH` | `services/checkin/storage.py:27` | `checkins` `:50` |
| `KAI_PLANNING_DB_PATH` | `services/planning/storage.py:69` | `plans` `:175`, `steps` `:187`, `step_runs` `:205` |

Plus four append-only JSONL sinks: governance audit `data/governance/audit.jsonl`
(`governance/audit_log.py:36-42`), `data/failures.jsonl` (`failure_memory/storage.py:41`),
`data/research/digests.jsonl` (`research/digest.py:47`), `data/digest/digests.jsonl`
(`digest/digest.py:25`).

### 8.4 Retention

Chat content, uploads, and memories are stored in full, indefinitely. Deletion is only
cascade-on-profile-delete, plus `services/memory/store.py:75 delete_memory(memory_id)` and
`planning/storage.py:406`. `grep -rn "retention|prune|VACUUM|DELETE FROM" backend/app` returns
only a comment in `billing.py:203`, the `cancellation_reason.py` docstring, and that planning
delete. **No TTL, no pruning, no log rotation.** Real PII sits in the untenanted SQLite —
`sol.db members.email` / `dwolla_customer_id` / `funding_source_href`
(`sol/storage.py:150-161`), journal text, mood samples.

---

## 9. Background jobs

### 9.1 In-process daemon threads (FastAPI lifespan, `app/main.py:39-151`)

Every start/stop is individually try/excepted so a failure only logs a warning
(`main.py:51,60,71,81,93,112`). All default OFF. Shutdown is reverse order.

| Job | Start | Gate | Trigger | Capability |
|---|---|---|---|---|
| supreme | `main.py:47-51` | `KAI_SUPREME_ENABLED=1` | loop every `supreme.scan_interval_seconds`, default 900s (`supreme/scheduler.py:30,45-57`) | 7 read-only scanners → `save_proposal` → Telegram on ≥medium (`supreme/scanner.py:451-468`) |
| self-heal | `:56-60` | `KAI_SELF_HEAL_SCHEDULER_ENABLED=1` **and** scope `self_heal` **and** `KAI_SELF_HEAL_ENABLED`, re-checked each tick (`self_heal_scheduler.py:45-58`) | every `KAI_SELF_HEAL_INTERVAL_SECONDS`, min 60, default 1800 (`:30-34`) | **writes** — rewrites `OLLAMA_MODEL_MAP` in the `.env` file (`self_heal.py:147-148`) and `rmtree`s every `__pycache__` under the repo (`:154-165`). Two-item allowlist; code edits, commits, git ops, process kills are never auto-done. |
| research | `:67-71` | `KAI_RESEARCH_ENABLED=1` | 60s poll, once/day at `KAI_RESEARCH_HOUR_UTC` (default 8) (`research/scheduler.py:31-43`) | fetch HN/arXiv/GH-trending, append JSONL, Telegram on HIGH |
| digest | `:77-81` | `KAI_DIGEST_SCHEDULER_ENABLED=1` + scope `KAI_SCOPE_DIGEST` each cycle (`digest/scheduler.py:37-58`) | 60s poll, once/day at `KAI_DIGEST_HOUR_UTC` (13) | LLM system snapshot → Telegram → JSONL. `@audited(digest.run, destructive=True)` |
| sol | `:89-93` | `KAI_SOL_SCHEDULER_ENABLED=1` + scope `sol` (`sol/scheduler.py:42-62`) | 60s poll, once/day at `KAI_SOL_SCHEDULER_HOUR_UTC` (14) | scan + Telegram; under `KAI_SOL_AUTOPILOT` auto-advances circle cycles (`sol/scheduler.py:87-106`, module lock `:34`). **Collect/payout stay operator-approved — the scheduler never moves money.** |
| checkin | `:108-112` | `KAI_CHECKIN_SCHEDULER_ENABLED=1` + `KAI_SCOPE_CHECKIN` (`checkin/scheduler.py:40-56`) | once/day at `KAI_CHECKIN_HOUR_UTC` (13), dedup'd by calendar day, plus a retry pass every tick with backoff (`:155,222-249`) | composes + Telegram-delivers a proactive message |

Startup-only, not a job: `persona.seed_defaults()` fail-soft (`main.py:98-102`).

### 9.2 Celery

`app/workers/celery_app.py` — broker/result default `redis://localhost:6379/0|1`
(`app/config.py:66-67`). `beat_schedule` (`celery_app.py:27-39`): `ingest_all_assets`,
`predict_all_stocks`, `predict_all_crypto` on `MARKET_DATA_FETCH_INTERVAL_MINUTES` /
`STOCK_PREDICTION_INTERVAL_MINUTES` / `CRYPTO_PREDICTION_INTERVAL_MINUTES`. Tasks at
`app/workers/tasks.py:30-153`. Not started by the app process; the only in-app consumer is
`app/routers/admin_data.py:14-49` (manual enqueue + `AsyncResult` poll). There is no
Procfile or Dockerfile under `backend/`, so **UNVERIFIED whether celery beat runs in
production at all** — confirming would need the Mac mini's launchd inventory (`launchctl list`).

---

## 10. Embedded products

**Sol (ROSCA money system).** Full rotating-savings lifecycle: create circle → add members with
a Dwolla customer + funding source → activate (requires an exactly-full roster of funded
members; assigns payout positions by join order; opens cycle 1) → per-cycle collect → payout →
advance → complete. Business rules in `sol/engine.py`: everyone active contributes every cycle
including the recipient (`:104-106`); payout releases once a **majority** (`total//2 + 1`) of
contributions clear (`:171-181`); nobody covers a defaulter — the recipient gets what was
collected (`:242`); a member failing past `SOL_MAX_CONTRIBUTION_RETRIES` (default 2) is marked
delinquent and forfeits their position; a forfeited or failed payout **rolls the pool forward**
on the circle (`:226-232`, `:286-292`), cleared only when a payout settles. Rollover accounting
adds rather than overwrites for the post-advance case (`:270-275`).

**self_heal** (206 lines) — see §9.1. Detection is always-on and read-only; auto-fix is opt-in
and limited to two actions.

**supreme** (468-line scanner) — seven read-only scanners ported from a standalone NarAI app:
process health (pgrep), port health (TCP connect), log ERROR/CRITICAL in the last hour, API
reachability probes, env-var completeness, disk usage, git uncommitted-file count. Config from
`SUPPREMA_MAP.yaml` via `KAI_SUPREME_MAP_PATH`.

**research** — daily parallel fetch of HN + arXiv + GitHub-trending, scored against
`KAI_RESEARCH_INTERESTS`, top-K digest appended to JSONL, Telegram on ≥HIGH.
`@audited(research.run_cycle, destructive=False)`.

**digest** — Operator Digest: cross-subsystem snapshot (audit health, blocked plans, negative
feedback, active lessons, twin) → LLM synthesis <180 words → Telegram → JSONL.

**SWE agent (PR #41 + #42, not on istanbul)** — `POST /admin/swe/run` (`admin_swe.py:52`, scope
`swe.run`) runs an operator-supplied command in a disposable container;
`POST /admin/swe/tasks/{id}/plan/approve` (`admin_swe_tasks.py:230`, scope `swe.brain.execute`)
drives a bounded agent loop; `POST /tasks/{id}/push/approve` (`:301`, scope `swepush.execute`)
calls `push.apply_and_push`. This is the **best-governed surface in the repo**:
`swe_admin_enabled()` allow-lists non-prod `APP_ENV` and vetoes on `ENV=production` so the
routes never mount (`swe_runtime/config.py:31-39`, wired `main.py:193`);
`KAI_SWE_RUNTIME_ENABLED` off by default; repo/image allowlists deny-by-default
(`config.py:88-101`); TOCTOU re-validation at approve time (`admin_swe_tasks.py:244`); the patch
is bound to its reviewed sha256 (`:279-280`); lazy approval expiry (`:75-85`); race-safe
conditional transitions; push hardened with a fresh clone, no ambient git credential, CI-path
block, no `--force`, fsync'd fail-closed audit (`push.py:5-25`).

---

## 11. Deployment topology

**Two distinct targets live in this repo. Do not conflate them.**

### (A) KAI backend — macOS Mac mini, launchd + Cloudflare Tunnel (the real KAI production)

- `deploy/launchd/com.wheellsverse.kai.plist` — a **LaunchDaemon** (system-level, starts at boot
  before GUI login) running as `UserName jhonwheeler`, `KeepAlive true` (restarts even on clean
  exit 0), `ThrottleInterval 10`, `ProcessType Interactive`, logs to
  `~/Library/Logs/wheellsverse/kai.{stdout,stderr}.log`. Header notes it supersedes the legacy
  per-user LaunchAgent `com.wheellsverse.nai.plist` and warns to bootout the old one to avoid
  two processes on :8001.
- Entrypoint `deploy/start_nai.sh` — loads `.env` then `backend/.env` with a **literal
  KEY=VALUE parser** (not `source`, because `set -u` plus `$`-bearing values silently dropped
  every key after the first); asserts `DATABASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  and `ADMIN_TOKEN`-or-`JWT_SECRET_KEY`; re-stamps static asset cache-busters; then
  `exec uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --app-dir backend
  --no-access-log`. **Single worker, loopback only.**
- Public exposure: `cloudflared` (`deploy/cloudflared/config.yml.example`) maps
  `kai.wheellsverse.com` and legacy `nai.wheellsverse.com` → `http://127.0.0.1:8001`, catch-all
  `http_status:404`. Supervised by `com.wheellsverse.cloudflared.plist`.
- Other plists: `com.wheellsverse.healthcheck` (StartInterval → `deploy/health_check.sh`),
  `com.wheellsverse.ollama`, `com.wheellsverse.kai.tier-heal` (`scripts/heal_tier_mirror.py`),
  legacy `com.wheellsverse.nai`.
- `deploy/health_check.sh` every 300s checks local `127.0.0.1:8001/health`, public
  `kai.wheellsverse.com/health`, disk headroom (default 85% — "full disk once kernel-panicked
  this box"), and restart-loop detection (PID sampling, 3 restarts/hour). Telegram alerts are
  rate-limited (default 3600s) and **stamp the dedup file only on a confirmed send**, so a real
  outage is not muted by a failed alert. The token is passed via `curl -K -` on stdin so it
  never appears in `ps`. `KAI_HEALTHCHECK_DRY_RUN=1` for testing.

**Single-worker is load-bearing, not a capacity choice**: `dependencies/admin.py` and
`core/rate_limit.py` keep throttle state in process memory and their docstrings say a
multi-worker deploy needs Redis.

### (B) Railway — a different application

`railway.json` startCommand runs **`uvicorn core.api:app`** (the root `core/api.py`
"WheellsVerse Production API"), healthcheck `/api/health`, `restartPolicyType ON_FAILURE`
max 3, stamping `/app/GIT_SHA` + `/app/BUILD_TIME`. Plus `Dockerfile` (python:3.11-slim,
ffmpeg/opus), `Dockerfile.kdp` + `railway.kdp.json`, and unused-here `deploy/fly.toml`,
`deploy/render.yaml`, `deploy/docker-compose.yml`. **`core/api.py` is not the KAI backend.**

### Secret surface

`backend/.env.example` documents ~35 vars; the code reads far more. The full inventory found by
grepping `os.environ.get` / `os.getenv` / `Settings` fields spans boot/infra, auth
(`ADMIN_TOKEN` guards the entire `/admin` surface including Sol money; `config.py:107-123`
refuses to boot when `APP_ENV` is non-dev and the token is weak or <32 chars), Stripe
(including a dead `STRIPE_PRICE_ELITE` declared at `config.py:96` but absent from
`tiers._PRICE_ENV`), Dwolla, ~40 `KAI_SCOPE_*` scopes, 10 SQLite path vars, browser automation,
the SWE runtime, LLM keys, and Telegram.

**Documentation gap, stated plainly: `.env.example` omits every Dwolla variable** — including
`DWOLLA_ALLOW_PRODUCTION`, the single latch between sandbox and real bank transfers — and also
omits every `KAI_SCOPE_*`, Supabase, Telegram, and all subsystem toggles.
`start_nai.sh` comments say the root `.env` holds ~230 keys, so the real production secret
surface exceeds what any code grep can enumerate. **UNVERIFIED** — `.env` is not in the repo.

---

## 12. Test coverage

`grep -rh "def test_" backend/tests | wc -l` → **966** test functions across 61 test files
(`ls backend/tests/*.py backend/tests/services/*.py | wc -l`). `pytest.ini`: `pythonpath = .`,
`testpaths = tests`, `addopts = -ra` — **no coverage plugin, no coverage threshold, no gate in
pytest config.** The suite was **not executed** for this document (per project notes, this
repo's `requirements.txt` is unsatisfiable and needs a curated venv plus local Postgres), so
every number below is a count of test functions, **not** verified passes and **not** line
coverage.

**Well covered:** `test_planning.py` 95, `test_twin.py` 43, `test_learning.py` 43,
`test_browser.py` 43, `test_kg.py` 31, `test_supreme.py` 29, `test_research.py` 28,
`test_failure_memory.py` 27, `test_self_correction.py` 26, `test_presets.py` 24.
**Sol: 53** (`test_sol_engine.py` 23 — the pure state machine, `test_sol_router.py` 22 —
scope/approval gating, `test_sol_scheduler.py` 8). **Dwolla 19, governance 19 + audit 7**,
admin security 16, auth 16 + 13 cookie + 3 rate-limit, security headers 7.

**Thin — the biggest real gap:**

- **`test_billing.py` has only 11 tests** for a 510-line router handling real card money with
  four webhook event types, an upsert path, a tier-mirror write, and a hand-rolled `urllib`
  Stripe call. Compare 53 tests for Sol. Stripe is the *live-revenue* path and the least-tested
  money code in the repo.
- **`test_spend_tracker.py` has 3 tests** for the LLM cost caps.
- `test_prediction_service.py` 3, `test_pubmed_search.py` 4, `test_document_search.py` 5,
  `test_site_builder.py` 5, `test_brain.py` 5, `test_indicators.py` 5.

**HTTP layer untested.** Grepping tests for each router name, **18 of 34 routers have zero test
references**: `admin_audit`, `admin_briefing`, `admin_browser`, `admin_checkin`, `admin_eq`,
`admin_failures`, `admin_journal`, `admin_kg`, `admin_persona`, `admin_relationship`,
`admin_research`, `admin_self_correction`, `admin_self_heal`, `admin_supreme`,
`api_keys_admin`, `documents`, `transcribe`, `tts`. Caveat on method: several of these have
strong *service*-layer suites (supreme 29, research 28, self_heal 14, kg 31), so the gap is
specifically the route/auth/serialization layer — but `api_keys_admin`, `documents`,
`transcribe`, and `tts` have neither.

**PR-only tests (#41/#42): 74** across `backend/tests/services/swe_runtime/` —
`test_admin_swe_tasks.py` 23, `test_push.py` 14, `test_brain.py` 10, `test_swe_policy.py` 9,
`test_task_store.py` 8, `test_swe_sandbox.py` 6, `test_swe_admin_gating.py` 4 — plus
`tests/services/test_audit_value_redaction.py` 3. Gate-focused rather than happy-path.

**Code intelligence (PR #40) has no tests on this branch** because neither its source nor its
tests exist here. Do not conclude from this checkout that it is untested.

**The deploy layer has no tests anywhere I could find.** `deploy/health_check.sh` is written to
be testable (every threshold env-overridable, `KAI_HEALTHCHECK_DRY_RUN=1`) but no test file
exercises it; same for `start_nai.sh`'s literal `.env` parser, a subtle and previously
bug-ridden piece of shell.

---

## 13. What this system cannot currently do

An honest list of real limits, each traceable to code.

1. **It cannot audit what its own tools did.** No tool call passes through `@audited`
   (`grep -rn "@audited" app/services/tools/` → 0). `registry.execute` (`registry.py:58-84`)
   performs no scope, approval, or audit step. The audit log's claim to be the "single source of
   truth for 'what did KAI do'" (`actions.py:21-22`) is false for the entire tool surface until
   PR #39 lands.
2. **It cannot prevent an ordinary authenticated user from driving operator-scoped
   integrations.** There is no tier gate on `/kai/chat`'s registry; `composio`, `notion`,
   `twenty_crm`, and every MCP tool are reachable from any Supabase JWT, and
   `composio_auth.py:35-37` collapses all users onto `COMPOSIO_USER_ID` when it is set.
3. **It cannot prove who approved a destructive action** — except on the three SWE gates.
   `approved` is a caller-supplied kwarg (`actions.py:91`) and `actor` defaults to the constant
   string `"operator"` (`actions.py:75`). There is one shared admin token, no roles, no rotation.
4. **It cannot guarantee its audit trail is intact.** No hash chain or HMAC
   (`grep -rn "prev_hash|chain|hmac" app/services/governance/` → none), and `record_action`
   fails soft (`audit_log.py:82-83`).
5. **It cannot enforce fine-grained scopes reliably.** The wildcard-parent rule
   (`actions.py:56-63`) means `KAI_SCOPE_SOL=1` — the variable the Sol scheduler itself requires
   — transitively enables `sol.transfer`.
6. **It cannot stop SSRF through `web_fetch`.** Prefix-matching literal hostnames plus
   `follow_redirects=True` with no per-hop re-check (`web_fetch.py:62-78`) leaves cloud metadata
   and internal services reachable from a plain user chat turn.
7. **It cannot truly stream from the OpenAI-compatible API.** `v1.py:135-155` blocks on
   `complete()` and then fakes chunks.
8. **It cannot call tools while streaming.** `Router.stream` is never given a registry
   (`brain.py:279`), so `GET /kai/chat/stream` has no tool loop.
9. **It cannot measure streamed spend.** Streaming tokens are estimated at `len(text)//4`
   (`router.py:215-228`), and unknown models cost 0.0 (`adapters/base.py:11-37`).
10. **It cannot refuse work when over budget.** Caps degrade to a free local model, never refuse
    (`router.py:106-108`), and are checked once at turn start, so a 5-iteration tool loop runs
    past the cap.
11. **It cannot fall back during streaming.** `Router.stream` re-raises on any adapter failure
    (`router.py:204-213`).
12. **It cannot run more than one worker.** Admin brute-force throttling and rate limiting are
    in-process memory; `start_nai.sh` pins `--workers 1`.
13. **It cannot rate-limit chat.** `rate_limit.py:19` sets `default_limits=[]`; no chat, stream,
    or completions route carries `limiter.limit`.
14. **It cannot tenant-scope most of its memory.** Ten SQLite sidecars, 18 tables, zero `user_id`
    columns — journal, EQ mood, relationship/trust, persona, twin, KG, checkins, planning,
    learning feedback, and the entire Sol money model are one global bag. Plus `predictions`
    (`prediction.py:13`) and `audit_log` (`admin.py:26`).
15. **It cannot delete or expire user data.** No retention, TTL, pruning, or log rotation
    anywhere; deletion is cascade-on-profile-delete plus two single-row helpers.
16. **It cannot claw back a returned contribution after payout** — documented at
    `sol/engine.py:16-25`.
17. **It cannot audit Stripe.** None of the four webhook handlers is `@audited`, and 11 tests
    cover 510 lines of live-revenue code.
18. **It cannot be upgraded cleanly across PRs as they stand.** Three branches each define a
    revision `0007` with the same `down_revision`; merging any two yields multiple alembic heads
    and `alembic upgrade head` fails.
19. **It cannot run the SWE agent in production** — by design. `swe_admin_enabled()` vetoes on
    production `APP_ENV`/`ENV` (`swe_runtime/config.py:31-39`), so the routes do not mount.
20. **It cannot do code intelligence at all on merged istanbul or on this branch.** PR #40 is
    unmerged and its source is absent here — only stale `__pycache__/*.pyc` remains.

### Explicitly UNVERIFIED

- Whether celery beat/worker actually run in production (no Procfile/Dockerfile under
  `backend/`; would need `launchctl list` on the Mac mini).
- Whether `memories` has a real FK to `profiles` in the live database — the ORM deliberately
  omits it (`memory.py:26-28`); would need `\d memories` on prod.
- The contents of the ~230-key production `.env` (not in the repo).
- `app/services/alerts.py` internals (the outbound notification target on every adapter failure,
  `router.py:151,157,165,212,317,334,342,346`) — not read.
- `app/services/agent_router.py` (`classify_domain`, an extra LLM call per auto-routed request),
  `app/services/presets.py`, `app/services/self_correction.py`, `app/services/grounding.py` —
  not read.
- Whether `fix/kai-code-intelligence` carries its own test suite (its tests are not in this
  checkout).
