# KAI — Trust Boundary Analysis

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit` (backend at `backend/`)
**Branch analysed:** `feat/kai-swe-agent`
**Merge base with `origin/istanbul`:** `2fe6e46` — which *is* `origin/istanbul` HEAD, so `git diff --name-only origin/istanbul...HEAD` is exactly the unmerged work.

## Provenance rule used throughout

Everything cited below is on **merged `istanbul`** unless explicitly tagged. The complete set of files on this branch that are *not* on istanbul (verified with `git diff --name-only origin/istanbul...HEAD`) is:

`backend/.env.example`, `alembic/versions/0007_add_kai_swe_tasks.py`, `app/dependencies/approver.py`, `app/main.py`, `app/models/__init__.py`, `app/models/swe_task.py`, `app/routers/admin_swe.py`, `app/routers/admin_swe_tasks.py`, `app/services/governance/audit_log.py`, all of `app/services/swe_runtime/`, `backend/docs/swe_*.md`, the `tests/services/swe_runtime/*` suite and `tests/services/test_audit_value_redaction.py`, `plans/PLAN-kai-autonomous-swe-agent.md`.

Those trace to **PR #41 (swe sandbox)** and **PR #42 (swe agent)**. PR #39 (`fix/kai-governed-tool-loop`) and PR #40 (`fix/kai-code-intelligence`) are **not in this checkout at all** — their branches were not fetched into this working tree, so nothing in this document is sourced from them, and every "this is ungoverned" statement below describes **merged istanbul as it stands today**.

---

## Boundary index

| # | Boundary | Enforcement strength |
|---|---|---|
| 1 | Internet → app (edge / transport / CORS / rate limit) | **WEAK** — no rate limit on any chat or completions route |
| 2 | Unauthenticated → authenticated (four credential lanes) | **MEDIUM** — strong JWT + admin token, but SSE accepts `?token=` |
| 3 | User → tenant data (Postgres) | **MEDIUM-STRONG** for the ORM tables; **UNENFORCED** for the SQLite sidecars |
| 4 | Model → tool execution | **UNENFORCED** — the headline finding |
| 5 | Agent → host (code execution, filesystem, self-modification) | **STRONG** for SWE (PR-only); **WEAK** for self-heal / site_builder / planning |
| 6 | App → provider APIs (LLM + SaaS credentials) | **WEAK** — operator credentials reachable from a tenant prompt |
| 7 | App → money rails (Stripe, Dwolla/Sol) | **STRONG** for Dwolla/Sol; **WEAK** for Stripe (unaudited) |
| 8 | Operator → admin surface | **WEAK** — one shared bearer secret, no identity, no roles |
| 9 | Third-party document / web content → prompt context | **UNENFORCED** — no prompt-injection boundary exists |

---

## 1. Internet → app

**What crosses:** every HTTP request that reaches the daemon. Public ingress is a Cloudflare Tunnel (`deploy/cloudflared/config.yml.example`) mapping `kai.wheellsverse.com` and legacy `nai.wheellsverse.com` to `http://127.0.0.1:8001`; the app itself binds loopback only (`deploy/start_nai.sh`, `exec uvicorn … --host 127.0.0.1 --port 8001 --workers 1`). Supervised by launchd (`deploy/launchd/com.wheellsverse.kai.plist`, `KeepAlive true`).

**What enforces it:**
- CORS allowlist with credentials — `backend/app/main.py:166-172` (`allow_origins=settings.cors_origins`, `allow_credentials=True`, but `allow_methods=["*"]`, `allow_headers=["*"]`).
- Security headers, added last so it is the outermost middleware and stamps SSE and 429s too — `backend/app/main.py:178`.
- SlowAPI limiter wired at `backend/app/main.py:162-164`.

**How strong: WEAK.**
- `backend/app/core/rate_limit.py:19` — `Limiter(key_func=get_remote_address, default_limits=[])`. There is **no default limit**.
- `grep -rn "limiter.limit" backend/app/routers/` returns exactly three hits, all in `backend/app/routers/auth.py:59, 90, 104`. **No chat, stream, `/v1/chat/completions`, admin, billing, or document route is rate-limited.** An authenticated user can drive the tool loop, the LLM spend, and every downstream provider API as fast as they can issue requests.
- The limiter state and the admin brute-force throttle are in-process dicts (`backend/app/core/rate_limit.py:9-12` docstring; `backend/app/dependencies/admin.py` `_failures`), so **single-worker uvicorn is a correctness dependency, not a capacity choice**. A second worker silently halves both protections.
- The chat router is dual-mounted at `/kai` and `/nai` (`backend/app/main.py:235-236`), so every route below has two URL trees — any path-based WAF rule must cover both.

## 2. Unauthenticated → authenticated

**What crosses:** credentials. There are four independent ones, with no shared identity model.

| Credential | Verified at | Grants |
|---|---|---|
| Supabase user JWT (cookie `nai_access` or `Authorization: Bearer`) | `backend/app/dependencies/supabase_jwt.py:108-127` (`get_current_user`) | `/kai/*`, `/nai/*`, `/billing`, `/documents`, **and the full tool loop** |
| Same JWT, SSE variant | `backend/app/dependencies/supabase_jwt.py:129-141` (`get_user_for_stream`) | `GET /kai/chat/stream` |
| Shared admin token `X-Admin-Token` | `backend/app/dependencies/admin.py:99-130` (`require_admin_token`) | the entire `/admin/*` surface incl. Sol ACH money |
| API key `Authorization: Bearer kai_…` | `backend/app/dependencies/api_key_auth.py:30` (`require_api_key_user`) | `/v1/*` only, tier-gated |
| Approver token `X-Approver-Token` — **PR #42 only** | `backend/app/dependencies/approver.py:39` (`require_approver`) | the three SWE gates |

**How strong: MEDIUM.**
- The JWT path is genuinely strong: ES256 via JWKS, strict `exp`/`iat`, `aud="authenticated"`, no DB round-trip needed (`backend/app/dependencies/supabase_jwt.py`).
- The admin token compare is constant-time and throttled — `hmac.compare_digest` at `backend/app/dependencies/admin.py:110-113`, failure-streak counter at `:118-130`, valid token clears the streak so an attacker cannot lock the operator out (`:123-125`). But the throttle is disabled when `_throttle_enabled()` is false (dev/test), and a missing/incorrect token yields 403 with no lockout in that mode (`:116-119`).

**WEAK point:** `backend/app/dependencies/supabase_jwt.py:132-138` — the SSE dependency still accepts a **`?token=` query parameter** as a fallback, logging only `"SSE auth used deprecated ?token= query param"`. Bearer tokens in query strings land in access logs, proxy logs, and `Referer` headers. This is an accepted-but-live credential leak channel.

**Correctly unauthenticated:** `POST /sol/webhook` (`backend/app/routers/sol.py:361-368`) — no admin auth by design, but fail-closed HMAC. See §7.

## 3. User → tenant data

**What crosses:** one user's chat history, memories, documents, API keys.

**What enforces it — ORM tables:** every read/write filters on the authenticated principal's id, not on a client-supplied id.
- `backend/app/services/nai_brain/brain.py:65-104` — `get_or_create_conversation` filters `Conversation.user_id == user_id` (`:72`), `list_conversations` filters `:90`, `get_conversation` filters `:103`.
- `backend/app/routers/nai.py:141-158` — `brain.get_conversation(current_user.id, conv_id)`; a foreign id returns 404, not 403 (no existence oracle).
- `backend/app/routers/nai.py:160-178` — DELETE re-filters `Conversation.user_id == current_user.id` at `:172`.
- Messages carry a denormalised `user_id` (`backend/app/services/nai_brain/brain.py:145`, comment: "denormalized, NOT NULL on live table").
- Documents are all `Depends(get_current_user)` scoped (`backend/app/routers/documents.py:58-152`), with a paid-tier check at `:33` and hard caps in `backend/app/services/documents.py:17-19` (5 MB, 200k chars, 50 docs/user).

**How strong: MEDIUM-STRONG at the application layer, but application-layer only.** There is no row-level security; a bug that omits a `.filter(user_id == …)` is an immediate cross-tenant read. And per Map C, `memories` deliberately omits the ORM-level FK to `profiles` — tenant integrity there depends on the migration having created it in the live DB (**UNVERIFIED against prod; would need `\d memories` on the production database**).

**UNENFORCED sub-boundary:** the ten SQLite sidecar databases (journal, learning, EQ, Sol, relationship, KG, persona, twin, checkin, planning) have **no tenant column at all** — they are a single global bag under `data/`, outside alembic. `predictions` and `audit_log` likewise carry no tenant key. Any code path that surfaces those to a user surfaces them to every user.

## 4. Model → tool execution — **THE weakest boundary in the system**

**What crosses:** an LLM-emitted `tool_call` with LLM-authored arguments, turning into a real side effect.

**The single choke point:** `backend/app/services/router/router.py:374`

```python
tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)
```

inside the per-call loop at `:373-380`, inside the bounded outer loop (`DEFAULT_MAX_TOOL_ITERS = 5`, exhaustion raises `ToolLoopExceededError` at `backend/app/services/router/router.py:410-414`).

**What enforces it:** **nothing.** `ToolRegistry.execute` (`backend/app/services/tools/registry.py:58-84`) does a dict lookup (`:60-66`) and then `output = tool.execute(ctx, **arguments)` (`:69`). There is no scope check, no approval check, no allowlist, no audit record — only exception classification (`:70-84`). The governance decorator exists and is well-built (`backend/app/services/governance/actions.py:71-120`: scope check first at `:88`, destructive-without-approval at `:109`, `record_action` on every path) but **`grep -rn "@audited" backend/app/services/tools/` returns zero matches.**

The registry is built unconditionally from `build_default_registry()` (`backend/app/services/tools/__init__.py:46-140+`) and handed to `Brain.chat`'s `ToolContext(user_id, session)` at `backend/app/services/nai_brain/brain.py:202-211`. `POST /kai/chat` requires only a Supabase user JWT (`backend/app/routers/nai.py:49-53`) — and `grep` for a tier gate in `nai.py` / `nai_brain/` finds none, despite `backend/app/services/tools/mcp_tools.py:30-32` claiming MCP inherits "the chat endpoint's paid-tier gate".

**Concrete side effects reachable from one authenticated chat turn:**
- `memory_tool(action="save")` → DB insert + commit.
- `twenty_crm(action="create", …)` → `POST` against the operator's CRM (registered whenever `TWENTY_API_URL`+`TWENTY_API_KEY` are set — `backend/app/services/tools/__init__.py:126-129`).
- `notion(action="create_page"|"append_blocks")` → writes the operator's Notion workspace.
- `composio(action="execute", tool_slug=…)` → **arbitrary mutation of ~200 connected SaaS accounts**, explicitly including `GMAIL_SEND_EMAIL` per the tool's own description (`backend/app/services/tools/composio_generic.py:48-52`). Compounded by `backend/app/services/tools/composio_auth.py:35-38`: when `COMPOSIO_USER_ID` is set it **overrides the per-user id for every user**, so any tenant's prompt executes as the operator's Composio identity.
- `mcp_<label>__<tool>` → whatever the operator's MCP servers do. Registration **defaults to on** — `backend/app/services/tools/__init__.py:63-67`: `include_mcp = True` with the comment "Auto-on whenever a config file exists."
- `site_builder`, `image_gen`, `video_gen` → files on disk, Runway spend.

**Second-order bypass:** `POST /admin/planning/{plan_id}/execute-next` **is** `@audited(scope="planning.execute", destructive=True)`, but inside the approved call it constructs `build_default_registry()` and hands the full registry to an LLM step runner. **One approval authorises an unbounded, unaudited tool loop**; the audit record says `planning.execute` and nothing about what was actually done.

**Reachability limits (real, and worth keeping):** the streaming path cannot reach `:374` — `Brain.stream` calls `Router.stream`, which never receives a registry. `/v1/chat/completions` calls `Router.complete` and has no tool loop.

## 5. Agent → host

**What crosses:** intent to execute code, write files, or modify the daemon's own configuration.

**STRONG (PR #41/#42 only, not on istanbul):** the SWE runtime is the standard the rest of the repo should be measured against.
- The routes **do not exist** on a prod runner: `backend/app/main.py:192-200` mounts `admin_swe` / `admin_swe_tasks` only `if swe_admin_enabled()`, which allow-lists non-prod `APP_ENV` values (`app/services/swe_runtime/config.py`). The `else` branch logs a warning (`main.py:196-200`). Defence-in-depth on top of `KAI_SWE_RUNTIME_ENABLED` (default off).
- Deny-by-default repo and image allowlists, TOCTOU re-validation at approve time, patch bound to its reviewed `sha256`, lazy approval expiry, protected-branch and CI-path blocks, no `--force`, fresh clone with no ambient git credential, fsync-or-abort audit.
- It is the **only** place approval is bound to a proven identity — `require_approver` (`backend/app/dependencies/approver.py:39-52`) matches SHA-256 of `X-Approver-Token` against `admin_users.password_hash` and uses the row's `email` as the audit actor. Two gaps: the SQL carries **no `role` filter** despite the docstring prescribing `role='approver'` (`approver.py:19-20` vs `:48-50`), and the push scope is deliberately named `swepush.execute` so the `KAI_SCOPE_SWE` wildcard cannot reach it.

**WEAK (merged istanbul):**
- **self-heal** writes to the host. `app/services/self_heal.py:147-148` rewrites `OLLAMA_MODEL_MAP` inside the `.env` file; `:154-165` `rmtree`s every `__pycache__` under the repo. It runs unattended from a daemon thread started at `backend/app/main.py:56-60` when `KAI_SELF_HEAL_SCHEDULER_ENABLED=1`. The blast radius is deliberately bounded to a two-item allowlist and it is off by default — but "the agent edits the file that holds its own configuration" is a host boundary being crossed by a scheduler, not by an operator.
- **site_builder / draft-adapter** write LLM-generated source to disk (`KAI_SITE_DRAFTS_DIR`, `KAI_INTEGRATION_DRAFTS_DIR`). `admin_planning.py:366` (`draft-adapter`, KAI writing its own tool source) is marked `destructive=False`.
- **image_gen** injects into `sys.path` to import `core.local_image` (`app/services/tools/image_gen.py:27-29`).

## 6. App → provider APIs

**What crosses:** the operator's secrets, outbound, on behalf of whoever sent the prompt.

Five LLM destinations, four carrying a key: `OPENAI_API_KEY` (`app/services/router/adapters/openai_adapter.py:21-26`), `ANTHROPIC_API_KEY` (`anthropic_adapter.py:21-26`), `PERPLEXITY_API_KEY` (`perplexity_adapter.py:21-26`), `CLOUDFLARE_AI_TOKEN`+`CLOUDFLARE_ACCOUNT_ID` (`cloudflare_adapter.py:47-81`, which also spoofs a Mozilla User-Agent to dodge CF error 1010), plus keyless local `OLLAMA_HOST` (`ollama_adapter.py:18-25`).

**What enforces it:**
- Adapter construction raises `RuntimeError` when its key is unset and the candidate is silently skipped (`app/services/router/__init__.py:29-37`).
- Spend caps — `app/services/router/spend_tracker.py:18-19` (`NAI_MAX_DAILY_SPEND_USD` default $2.00, `NAI_MAX_MONTHLY_SPEND_USD` default $60.00), consulted at `app/services/router/router.py:106`.

**How strong: WEAK.**
- The cap is **degrade-only, never refuse** — over-cap routes to free local ollama (`router.py:106-108`). It is **evaluated once at turn start**, so a five-iteration tool loop runs its whole budget past the cap without re-checking. `over_monthly_cap` is defined (`spend_tracker.py:119`) but **not referenced in `router.py` at all**.
- Streaming cost is *estimated*, not measured: `router.py:215-228` computes `len(text)//4` and tags `metadata={"streamed": True, "estimated_tokens": True}`. `calculate_cost` returns **0.0 silently for unknown models** (`adapters/base.py:11-37`). So the cap can be under-counting the spend it is supposed to bound.
- The bigger problem is §4: the tool loop reaches Twenty CRM, Notion, Composio (~200 SaaS accounts), Runway, GitHub, Dwolla-read and arbitrary MCP servers — **all operator-scoped credentials, in a multi-tenant lane, with no per-user attribution and no audit trail.**
- **SSRF is live.** `app/services/tools/web_fetch.py:68-78` blocks `localhost`/`127.0.0.1`/`0.0.0.0`/`::1` and then **string-prefix-matches the literal hostname** against `10.`, `192.168.`, `169.254.`, `172.16.`–`172.31.` — then calls `httpx.get(url, …, follow_redirects=True)` at `:80-83` **with no re-check on any redirect hop**. Bypassed by: a hostname whose DNS resolves to a private IP; a decimal/hex IP literal (`http://2130706433/`); IPv6 forms; `172.32+`; and decisively, any public URL that 302s to `169.254.169.254`. Cloud/host metadata and internal services are reachable from a plain user chat turn. Fix is one shape: resolve the host and test `ipaddress.ip_address(...).is_private/is_loopback/is_link_local`, re-checking every hop.

## 7. App → money rails

Two independent systems sharing no code.

### 7a. Dwolla / Sol ACH — **STRONG**

**What crosses:** real bank debits and payouts. Three initiating routes: `POST /admin/sol/cycles/{id}/collect`, `/retry-failed`, `/payout` (`backend/app/routers/sol.py:340, 345, 350`).

**What enforces it — genuinely layered:**
- Router-level admin auth on the whole `/admin/sol` tree (`sol.py:44`).
- `@audited(scope="sol.transfer", destructive=True)` → `ScopeDenied` (403) unless the scope is enabled (`app/services/governance/actions.py:88-104`), `PendingApproval` (409) unless `approved=True` (`:109-120`).
- Sandbox latch: `DwollaClient.__init__` raises `DwollaProductionLocked` unless `DWOLLA_ALLOW_PRODUCTION=1` when `DWOLLA_ENV=production`.
- Two-layer idempotency: atomic conditional-UPDATE claims app-side (`sol.py:221-222`, `:319`) plus a stable Dwolla `Idempotency-Key` per ledger row; retry keys advance only on a *confirmed* transfer, so a lost response reuses the same key (`sol.py:279-291`).
- Off-host SSRF guard: `DwollaClient._request` refuses any absolute URL not on the configured Dwolla host, so a malicious `_links.href` cannot redirect a transfer.
- **The LLM is fenced out by construction** — `app/services/tools/dwolla_tool.py` exposes six read-only actions and no create/transfer path; it is registered only when `DWOLLA_KEY`+`DWOLLA_SECRET` are set (`app/services/tools/__init__.py:133-137`, with the comment "Money movement is NOT in this tool").
- Webhook is fail-closed: `backend/app/routers/sol.py:361-370` — missing signature or missing secret → `verify_webhook` returns False → **401**, before any JSON parse. Only whitelisted topics drive state (`sol.py:356-359`, `:376-378`).

**WEAK spot inside the strong system:** `is_scope_enabled` supports a **wildcard parent** — `backend/app/services/governance/actions.py:59-61`: `parent = norm.split("_")[0]`, so `KAI_SCOPE_SOL=1` transitively enables `sol.transfer`. And `KAI_SCOPE_SOL` is exactly what the Sol reminder scheduler checks, so an operator enabling the *notifications* the obvious way also opens the *transfer* scope. The same rule gives `KAI_SCOPE_DWOLLA` → `dwolla.transfer`, `KAI_SCOPE_BROWSER` → `browser.execute`, `KAI_SCOPE_PLANNING` → `planning.execute`, and `KAI_SCOPE_SELF` → `self_heal`. The SWE work defends against precisely this pattern (disjoint `SWEPUSH` root); Sol, Dwolla, browser and planning got no equivalent. Admin token + `approved=True` still stand, so this is not "money moves by itself" — but the advertised quadruple lock is a triple lock in that configuration.

Second weak spot: **`approved` is caller-supplied, not proven.** `actions.py:91` pops it from kwargs and the routes forward it straight from the request body (`sol.py:342/347/352`). Anyone holding the shared admin token is their own approver.

### 7b. Stripe — **WEAK**

**What crosses:** subscription state and, through the tier mirror, product entitlements.

**What enforces it:** `backend/app/routers/billing.py:298-315` — a missing `Stripe-Signature` is a 400 at `:304-305`, and `stripe_service.construct_event` HMAC-verifies the raw body, with a verify failure logged and re-raised as 400 (`:308-314`). Never a 500. Amounts are never user-supplied: checkout takes a `plan_code` mapped through the in-code tier registry; the winback discount is a **hardcoded coupon id**.

**How weak:** **none of the four webhook handlers is `@audited`** (`billing.py:319-330` dispatches straight to `_handle_checkout_completed` / `_handle_sub_updated` / `_handle_sub_deleted` / `_handle_payment_failed`, which mutate subscription rows and mirror `profiles.tier` directly). The live-revenue path is the *only* money path in the repo with no governance record — and per Map D it carries 11 tests against 510 lines, versus 53 tests for Sol.

## 8. Operator → admin surface

**What crosses:** operator intent to move money, execute plans, mutate KAI's own guidance and persona, and (in the PR) run containers and push git.

**What enforces it:** exactly one thing — `X-Admin-Token`, checked by `require_admin_token` (`backend/app/dependencies/admin.py:99-130`), declared at `APIRouter` level on every `/admin/*` router (verified for all of them, plus `backend/app/routers/sol.py:44`). No per-route gaps.

**How strong: WEAK — not because the check is bad, but because of what one secret buys.**
- Single shared bearer secret. No roles, no per-route scoping, no rotation, no expiry.
- **No per-actor attribution:** `audited(..., actor_default="operator")` at `backend/app/services/governance/actions.py:74` means the `actor` field of essentially every audit record is the constant string `"operator"`. The audit log cannot tell you *who*.
- Whoever holds it is also the approver for every destructive action (§7a).
- The file's own header says "Stage 11 replaces this with real `admin_users` auth" — this is known debt, not an oversight.
- Boot-time guard exists and is worth crediting: `app/config.py:107-123` refuses to start when `APP_ENV` is not a dev/test value and the token is a known-weak value or under 32 chars.
- A set of admin write endpoints carry **no `@audited` at all**: `/admin/ingest/*` and `/admin/predict/*` (Celery fan-out), `/admin/supreme/scan`, `/admin/learning/feedback`, `/admin/journal/entries`, `/admin/persona/entries`, `/admin/twin/entries`, `/admin/relationship/milestones`.

**Also weak: the audit log itself is not a control.**
- Plain appended JSONL at `KAI_AUDIT_LOG_PATH` — `grep -rn "prev_hash|chain|hmac" backend/app/services/governance/` returns nothing. **Not tamper-evident**, despite `app/services/audit/auditor.py:31` advertising it as "a tamper-evident action log". Writable by the same daemon whose actions it records.
- `record_action` is deliberately fail-soft, so a write failure silently drops the record. (The SWE push is the sole exception — it fsyncs or aborts.)
- Redaction is name/shape-based (key patterns plus, on the PR branch only, a value regex), so any secret whose key isn't in the pattern list and whose value doesn't match the regex passes through. The same class of gap exists in the failure log's `_safe_args` (`backend/app/services/router/router.py:417-434`).
- `@audited`'s `wrapper` is a plain `def` (`actions.py:90`) — sync only. Decorating an `async def` would log success against an un-awaited coroutine. No current target is async; nothing prevents one.

## 9. Third-party document / web content → prompt context — **UNENFORCED**

**What crosses:** attacker-controlled text, from outside the trust domain, into the model's context window in a turn that has tool-calling enabled.

**Ingestion channels, all reaching the same context:**
- `web_fetch` — arbitrary URL, `trafilatura`-extracted, returned as `{"text": …}` (`backend/app/services/tools/web_fetch.py:94-130`).
- `web_search` (Perplexity), `pubmed_search`, `sec_edgar_search`, `courtlistener_search`, `who_search`, `clinicaltrials_search`, `github_scout` — all live external content, registered unconditionally in `build_default_registry` (`backend/app/services/tools/__init__.py:81-121`).
- User-uploaded documents — `POST /documents` accepts a file and stores `full_text` (`backend/app/routers/documents.py:58-83`; extraction in `backend/app/services/documents.py`), then `document_search` / `verify_claim` retrieve chunks back into context.
- `composio` and MCP tool *results* — content produced by third-party SaaS and by operator-declared subprocesses.

**What enforces it:** **nothing.** Tool output is appended verbatim as a `role: "tool"` message — `backend/app/services/router/router.py:401-408`:

```python
msgs.append({
    "role": "tool", "tool_call_id": tc.id,
    "name": tc.name, "content": tool_result.as_content(),
})
```

The only controls on that content are **size**, not trust: `MAX_OUTPUT_CHARS` truncation in `web_fetch.py:114-117`, `_RESULT_TEXT_BUDGET = 4000` in `composio_generic.py:41`, and the document caps in `documents.py:17-19`. There is no delimiting, no provenance marking, no "content below is untrusted data, not instructions" framing, and no re-authorisation of tool calls that follow ingested content.

**Why this is the compounding finding:** the loop that ingests the untrusted text is the same loop that executes tools, and that loop is ungoverned (§4). An attacker who controls a page KAI fetches — or a PDF a user uploads — is one successful injection away from `composio(action="execute", tool_slug="GMAIL_SEND_EMAIL", …)` running under the operator's Composio identity (`composio_auth.py:35-38`), with no approval prompt and no audit record. `web_fetch`'s bypassable SSRF guard (§6) means the same injection can also pivot the fetch itself at internal endpoints.

---

## Boundaries that are WEAK or unenforced — the list

1. **Model → tool execution: UNENFORCED.** `backend/app/services/tools/registry.py:69` calls `tool.execute(ctx, **arguments)` with no scope, approval, allowlist or audit. Reachable from `POST /kai/chat` with only a user JWT. (merged istanbul)
2. **Third-party content → prompt context: UNENFORCED.** Verbatim injection at `backend/app/services/router/router.py:401-408`; only size limits, no trust boundary. Compounds #1. (merged istanbul)
3. **Operator credential model: WEAK.** One shared `X-Admin-Token` for the whole `/admin/*` surface including ACH transfers; `actor` is the constant `"operator"` (`app/services/governance/actions.py:74`); `approved` is caller-supplied (`:91`). (merged istanbul)
4. **Governance scope wildcards: WEAK.** `app/services/governance/actions.py:59-61` — `KAI_SCOPE_SOL` reaches `sol.transfer`, `KAI_SCOPE_DWOLLA` reaches `dwolla.transfer`, `KAI_SCOPE_PLANNING` reaches `planning.execute`, `KAI_SCOPE_SELF` reaches `self_heal`. (merged istanbul)
5. **`web_fetch` SSRF guard: BYPASSABLE.** String-prefix hostname check + `follow_redirects=True` with no per-hop re-check (`app/services/tools/web_fetch.py:70-83`). (merged istanbul)
6. **Rate limiting: ABSENT on every expensive route.** `app/core/rate_limit.py:19` `default_limits=[]`; `limiter.limit` appears only in `app/routers/auth.py:59, 90, 104`. (merged istanbul)
7. **Stripe money: UNAUDITED.** No `@audited` on any handler in `backend/app/routers/billing.py:319-330`. (merged istanbul)
8. **Audit log: NOT tamper-evident and fail-soft**, while `app/services/audit/auditor.py:31` claims otherwise. (merged istanbul)
9. **SSE `?token=` query fallback: LIVE credential leak channel.** `app/dependencies/supabase_jwt.py:132-138`. (merged istanbul)
10. **Multi-tenant credential sharing: WEAK.** `COMPOSIO_USER_ID` collapses every user to one Composio identity (`app/services/tools/composio_auth.py:35-38`); Twenty/Notion/Runway/MCP are operator-scoped credentials exposed in a per-user registry. (merged istanbul)
11. **Sidecar persistence: NO TENANT BOUNDARY.** Ten SQLite DBs under `data/` with no `user_id` column anywhere, outside alembic, holding Sol member email / `dwolla_customer_id` / `funding_source_href`, journal text, and mood samples. (merged istanbul)
12. **Spend cap: DEGRADE-ONLY, checked once per turn, estimated on streaming.** `app/services/router/router.py:106`, `:215-228`; `over_monthly_cap` never called. (merged istanbul)
13. **Single-worker uvicorn is a security dependency**, not a capacity choice — the rate limiter and admin brute-force throttle are in-process memory (`app/core/rate_limit.py:9-12`). (merged istanbul)

## Boundaries that are genuinely strong

- **Dwolla/Sol money** (§7a) — five independent layers plus a fail-closed webhook and an LLM fenced out by construction.
- **SWE runtime** (§5, **PR #41/#42 only, not on istanbul**) — routes that do not exist in prod, deny-by-default allowlists, TOCTOU re-validation, patch-sha binding, fail-closed fsync'd audit, and the only identity-bound approval in the repo.
- **Supabase JWT verification** (§2) and **ORM-level tenant scoping of conversations/messages/documents** (§3).

## Explicitly UNVERIFIED

- Whether `memories` has a real FK to `profiles` in the live database (ORM omits it deliberately; only the migration declares it). Would need `\d memories` on prod.
- `backend/app/services/alerts.py` — `provider_alert(...)` fires on every adapter failure and is an outbound notification path (Telegram per surrounding comments); I did not read the module, so its own credential handling and failure mode are unassessed.
- Whether Celery beat actually runs in production — there is no Procfile or Dockerfile in `backend/`, and the launchd plists start only uvicorn.
- Everything about PR #39 (`fix/kai-governed-tool-loop`) and PR #40 (`fix/kai-code-intelligence`): neither branch is present in this checkout. If #39 lands as described elsewhere, it is the fix for finding #1 — but it is **not** in the tree analysed here, and `backend/app/services/code_intel/` in this working copy contains only stale `.pyc` files with no `.py` source.
