# KAI Threat Model (STRIDE-ish)

**Scope:** the KAI backend in `/Users/jhonwheeler/wheellsverse-kai-audit/backend`.
**Analysis branch:** `feat/kai-swe-agent`, HEAD `4850b0d`.
**Date:** 2026-07-22.

Every control below is cited to a file:line that was read, or marked `NONE`.
Paths are relative to `backend/` unless they start with `deploy/` or `docs/`.

---

## 0. Provenance — merged vs. open PR

`git diff --name-only origin/istanbul...HEAD` returns exactly 29 paths, all of
them the SWE-agent set: `app/services/swe_runtime/*`, `app/routers/admin_swe.py`,
`app/routers/admin_swe_tasks.py`, `app/dependencies/approver.py`,
`app/models/swe_task.py`, `alembic/versions/0007_add_kai_swe_tasks.py`,
`app/services/governance/audit_log.py`, `app/main.py`, `backend/.env.example`,
their tests, and `plans/PLAN-kai-autonomous-swe-agent.md`.

Therefore:

| Component | Status |
|---|---|
| Chat + tool loop, router, all `/admin/*` routers, Sol/Dwolla, Stripe billing, governance decorator, all 10 SQLite sidecars, all schedulers | **merged on `istanbul`** — this is production |
| SWE sandbox + agent, approver-token dependency, `kai_swe_tasks`, value-level audit redaction | **open PR #41 / #42** — not in production |
| Governed tool loop (scope/`allow_writes`/`record_action` inside `ToolRegistry.execute`) | **open PR #39** — not in this checkout. Verified absent: `app/services/tools/base.py` has no `scope` or `allow_writes` attribute (grep returns nothing) |
| Code intelligence (`kai_code_chunks`, pgvector code search) | **open PR #40** — not in this checkout; `app/services/code_intel/` here holds only stale `.pyc` files |

**Consequence for this threat model: every "NONE" control below is a NONE *in
production today*, even where an open PR would fix it.**

---

## 1. Trust boundaries

1. **Public internet → Cloudflare Tunnel → `127.0.0.1:8001`** (`deploy/cloudflared/config.yml.example`; uvicorn bound to loopback, single worker, `deploy/start_nai.sh`).
2. **Supabase-JWT lane** — `/kai/*`, `/nai/*`, `/account/*`, `/billing`. Auth: `app/dependencies/supabase_jwt.py:109`. Multi-tenant.
3. **Shared-admin-token lane** — the entire `/admin/*` surface. Auth: `app/dependencies/admin.py:99`. Single shared secret, no roles.
4. **API-key lane** — `/v1/*`. Auth: `app/dependencies/api_key_auth.py:30`. No tool loop.
5. **Unauthenticated webhook lane** — `POST /sol/webhook` (`app/routers/sol.py:361`), `POST /billing/webhook` (`app/routers/billing.py:298`). Both HMAC-verified.
6. **LLM output → tool execution** — `app/services/router/router.py:374`. This is the sharpest boundary in the system and it is unguarded (§2.1).
7. **Model provider network egress** — five adapters, four carrying secrets (`app/services/router/adapters/*`).

---

## 2. SPOOFING / ELEVATION — identity and authorization

### 2.1 Prompt injection via documents and tool output → arbitrary side effects

**Attacker.** Anyone who can get text in front of the model: a paying tenant
(direct prompt), or an unauthenticated third party who controls a page the model
fetches, an MCP server's response, a CRM record, a PubMed abstract, or a PDF the
user uploads.

**Entry points.**
- User-uploaded documents: `POST /account/documents` (`app/routers/documents.py:58`), retrieved back into context by `document_search` (`app/services/tools/document_search.py:53`, `rag.retrieve`).
- Fetched web pages: `web_fetch` (`app/services/tools/web_fetch.py:59`).
- Third-party tool output: MCP servers (`app/services/mcp_tools.py:180`), Twenty CRM records, Composio results.
- Memory: `memories.content` retrieved into every turn.

**Current control.** **NONE.** There is no injection filter, no provenance
marking, no untrusted-content fencing anywhere in `app/services/nai_brain/` or
`app/services/tools/`. Tool output is returned to the model verbatim as a tool
message in the loop at `router.py:373-408`.

**Why it is critical here rather than merely annoying:** the model's next action
after reading injected text goes straight through the choke point:

```
LLM emits tool_call
 → app/services/router/router.py:374   tool_registry.execute(tc.name, tc.arguments, tool_context)
 → app/services/tools/registry.py:69   output = tool.execute(ctx, **arguments)
 → side effect
```

`ToolRegistry.execute` (`registry.py:58-83`) is a dict lookup plus a call. There
is **no scope check, no approval check, no allowlist, and no audit record** —
only failure logging. `grep -rn "@audited" app/services/tools/` returns two hits
and **both are comments** (`dwolla_tool.py:6`, `tools/__init__.py:134`), not
decorators.

**Reachable side effects from a single authenticated chat turn** (`POST /kai/chat`
with `use_tools=true`, `app/routers/nai.py:49-56`, registry built unfiltered at
`nai.py:55` `build_default_registry()`):

| Tool | Side effect | Cite |
|---|---|---|
| `memory_tool(action="save")` | DB insert + commit | `app/services/tools/memory_tool.py:87-93` |
| `twenty_crm(action="create")` | `POST {TWENTY_API_URL}/rest/{obj}` — writes the operator's CRM | `app/services/tools/twenty_crm.py:138` |
| `notion(create_page/append_blocks)` | writes the operator's Notion | `app/services/tools/composio_notion.py` |
| `composio(action="execute", tool_slug=…)` | **arbitrary mutation of ~200 connected SaaS accounts**, e.g. `GMAIL_SEND_EMAIL` | `app/services/tools/composio_generic.py:42-70` |
| `mcp_<label>__<tool>` | whatever the configured MCP server does; registration **defaults to on** | `app/services/mcp_tools.py:161`; `app/services/tools/__init__.py:64-66` |
| `site_builder` | writes an LLM-generated HTML file to disk | `app/services/tools/site_builder.py:24` |
| `video_gen` | burns Runway credits | `app/services/tools/video_gen.py` |

**Residual risk: CRITICAL.** A poisoned document or a hostile web page turns into
mail sent as the operator, CRM records created, or an MCP subprocess invoked,
with no audit trail. The audit module's own claim to be the "single source of
truth for 'what did KAI do'" (`app/services/governance/actions.py:21-22`) is
false for the entire tool surface.

**Dark KAI delta.** See §11 — every increase in autonomy (unattended loops,
self-authored plans, repo write access) multiplies this single unguarded line.

---

### 2.2 Confused deputy on operator tools — tenant prompt acting as the operator

**Attacker.** Any authenticated Supabase user (i.e. any signed-up account).

**Entry point.** `POST /kai/chat` / `POST /nai/chat` — the router is dual-mounted
at both `/kai` and `/nai` prefixes (`app/main.py:235-236`), so both URL trees
reach the same code.

**Current control.** **NONE at the tier level.** `nai.py:55` calls
`build_default_registry()` with no arguments and no tier check; the only registry
filtering happens when the caller opts into `auto_route` and a preset matches
(`nai.py:61-71`). This directly contradicts the code's own comments — `app/services/mcp_tools.py:30-32` states MCP tools "inherit the chat endpoint's paid-tier gate", and `app/services/tools/__init__.py:126-129` registers Twenty CRM on the same assumption. That gate does not exist.

**Worse: the identity collapses.** `app/services/tools/composio_auth.py:34-37` —
when `COMPOSIO_USER_ID` is set, **every** user's Composio calls resolve to that
single operator identity. A tenant's prompt therefore acts with the operator's
OAuth grants across every connected SaaS app.

**Residual risk: CRITICAL.** Operator-scoped credentials (Twenty, Notion,
Composio, MCP, Dwolla-read) are exposed in a multi-tenant lane.

**Dark KAI delta.** Any Dark KAI capability reachable from the same
`build_default_registry()` inherits the same missing gate by default.

---

### 2.3 Shared-admin-token compromise

**Attacker.** Anyone who obtains `ADMIN_TOKEN` — from a log, a shell history, a
`.env` read, a backup, or an operator's browser.

**Entry point.** `X-Admin-Token` on any `/admin/*` route. All 23 admin routers
plus `app/routers/sol.py:44` declare `dependencies=[Depends(require_admin_token)]`
at the `APIRouter` level; there are no per-route gaps.

**Current controls.**
- Constant-time compare — `app/dependencies/admin.py:110` (`hmac.compare_digest`).
- Failed-attempt throttle, 10 failures / 300s per client → 429 — `admin.py:34-35, 127`; **disabled in dev/test** (`admin.py:42-45`); state is **in-process memory**, which is why the single-worker uvicorn in `deploy/start_nai.sh` is a correctness dependency, not a capacity choice.
- Forwarded-IP headers trusted only from a loopback/private peer — `admin.py:48-59`.
- Weak-token boot refusal — `app/config.py:107-123` refuses to start outside dev/test when the token is a known-weak value or <32 chars.

**What is NOT controlled.** No roles, no per-route scoping, no rotation, no
expiry, no per-actor attribution: the `actor` recorded in every audit record
defaults to the literal string `"operator"` (`app/services/governance/actions.py:75, 91`).
The file header in `app/dependencies/admin.py` itself says "Stage 11 replaces
this with real `admin_users` auth."

**Blast radius behind that one secret:** live ACH debits and payouts
(`sol.py:340,345,350`), Dwolla customer + bank-account provisioning
(`sol.py:180,186`), host `.env` rewriting via self-heal (`app/services/self_heal.py:147-148`),
an unbounded LLM tool loop (`app/routers/admin_planning.py:201-215`), real browser
clicks (`app/routers/admin_browser.py:185`), and the full unfiltered tool registry
via `POST /admin/kai-chat` (`app/routers/admin_chat.py:167-176`).

**Residual risk: CRITICAL.** One static string is the sole barrier between the
internet and real bank transfers.

**Dark KAI delta.** If Dark KAI is mounted behind the same token, it inherits
this single point of failure and widens what one leaked string buys.

---

### 2.4 Approver-token weaknesses (PR #42 only)

**Attacker.** Anyone with a row in `admin_users` whose `password_hash` happens to
be a raw SHA-256 hex digest.

**Entry point.** `X-Approver-Token` on the three SWE gates.

**Current control.** `app/dependencies/approver.py:39-52` — SHA-256 of the
presented token matched against `admin_users.password_hash`, returning that row's
`email` as the audit identity. **This is the only place in the codebase where
approval is bound to a proven identity rather than a request-body boolean.**
Optional separation of duties via `KAI_SWE_REQUIRE_TWO_PERSON`
(`approver.py:32-35`, enforced at `admin_swe_tasks.py:311`).

**Gap.** The docstring prescribes `role='approver'` (`approver.py:15-16`) but the
query has **no `role` filter**: `SELECT email FROM admin_users WHERE password_hash = :h`
(`approver.py:48-50`). Any admin row is an approver.

**Residual risk: MEDIUM** — and only on an unmerged branch, behind
`swe_admin_enabled()`, which refuses to even mount the routes on a prod-marked
env (`app/services/swe_runtime/config.py:31-41`, wired at `app/main.py:192-200`).

---

### 2.5 Approval is caller-asserted everywhere else

**Attacker.** Anyone holding the admin token (see §2.3).

**Entry point.** Any `destructive=True` `@audited` action.

**Current control.** `app/services/governance/actions.py:91` pops `approved`
straight out of kwargs; routes forward it verbatim from the request body — e.g.
`app/routers/sol.py:341-352` (`body.approved` → collect / retry / payout).

**Residual risk: HIGH.** "Approval" is not a second factor; it is a JSON field
the same caller sets. The real barrier is the admin token, not the approval.

---

### 2.6 SSE query-param token

**Attacker.** Anyone reading proxy logs, browser history, or a `Referer` header.

**Entry point.** `GET /kai/chat/stream` — `app/dependencies/supabase_jwt.py:129-141`
prefers the `nai_access` cookie but **still accepts a `?token=` query param**,
logging a deprecation warning at `:137`.

**Residual risk: MEDIUM.** JWTs land in logs. Streaming cannot reach the tool loop
(`Router.stream` at `router.py:171-228` is never passed a registry), so the
credential is worth chat history and conversation access, not tool execution.

---

## 3. TAMPERING — audit-log integrity

**Attacker.** Anyone with code execution as the daemon user, or the model itself
if it ever gains file-write reach; also any operator wishing to erase a record.

**Entry point.** The governance audit sink: an append-only JSONL file at
`KAI_AUDIT_LOG_PATH`, default `<repo>/data/governance/audit.jsonl`
(`app/services/governance/audit_log.py:34-42`).

**Current controls.**
- Key-pattern redaction, recursive through dicts/lists — `audit_log.py:88-115`.
- Value-level regex scrub for `bearer …`, `gh[posur]_…`, `github_pat_…`, `x-access-token:…`, `sk-…`, plus 500-char truncation — `audit_log.py:96-105, 124-133`. **PR-only**; merged `istanbul` has key-based redaction only.
- Fail-closed fsync on the SWE push path only — `app/services/swe_runtime/push.py:161-179` (PR #42).

**What is NOT controlled.**
- **No tamper evidence.** `grep -rn "prev_hash\|hmac\|chain" app/services/governance/` returns **nothing**. Plain appended JSON lines, writable by the daemon, no hash chain, no signature, no external sink. `app/services/audit/auditor.py:31` nonetheless advertises it as a "tamper-evident action log" — that claim is false.
- **Fail-soft writes.** `audit_log.py:82-83` catches every write exception and only logs a warning; a full disk or a permissions change silently drops records. Everything except the SWE push behaves this way.
- **Redaction is name/shape-based.** A bare Dwolla or Twenty API key — no `sk-` prefix, no secret-looking key name — passes through unredacted.
- **No rotation, no retention.** The JSONL sinks (`data/governance/audit.jsonl`, `data/failures.jsonl`, `data/research/digests.jsonl`, `data/digest/digests.jsonl`) grow unbounded; `grep -rn "retention|prune|VACUUM"` over `app/` finds no pruning anywhere.

**Residual risk: HIGH.** The audit log cannot be relied on for incident
reconstruction: it is incomplete (no tool calls at all — §2.1), silently lossy,
un-attributed (`actor="operator"` — §2.3), and freely rewritable.

---

## 4. ELEVATION — governance scope widening (confused deputy on the gate itself)

**Attacker.** No attacker required — this is an operator footgun that grants the
next attacker more than intended.

**Entry point.** `is_scope_enabled` — `app/services/governance/actions.py:46-63`.

```python
norm = scope.replace(".", "_").replace("-", "_").upper()
if _is_env_truthy(f"KAI_SCOPE_{norm}"): return True
parent = norm.split("_")[0]                    # actions.py:60
if parent and _is_env_truthy(f"KAI_SCOPE_{parent}"): return True
```

The wildcard parent is the **first underscore-delimited segment**, so:

| Setting the obvious var… | …silently enables |
|---|---|
| `KAI_SCOPE_SOL=1` (required by the Sol reminder scheduler, `app/services/sol/scheduler.py:60-62`) | `sol.transfer` — live ACH debits and payouts (`sol.py:340,345,350`) |
| `KAI_SCOPE_DWOLLA=1` | `dwolla.transfer` (`app/services/dwolla/operations.py:41`) |
| `KAI_SCOPE_BROWSER=1` | `browser.execute` — real clicks and typing |
| `KAI_SCOPE_PLANNING=1` | `planning.execute` — the unbounded tool loop (§5) |
| `KAI_SCOPE_SELF=1` | `self_heal` — host `.env` rewriting |

**Current control.** Partial and only for SWE: `backend/.env.example:72-77`
documents the hazard and the push scope is deliberately named `swepush.execute`
so that `KAI_SCOPE_SWE` cannot reach it (`app/routers/admin_swe_tasks.py:273`).
**No equivalent protection exists for sol, dwolla, browser, planning, or self_heal.**

**Residual risk: HIGH.** The Sol module documents a "quadruple lock"
(`sol.py:23-25`); under the most natural configuration it is a triple lock —
admin token + `approved=true` + sandbox latch — because the scope gate is
transitively open.

---

## 5. ELEVATION — single approval authorizing an unbounded loop

**Attacker.** Admin-token holder, or an injected plan step (§2.1) once a plan is
approved.

**Entry point.** `POST /admin/planning/{plan_id}/execute-next`
(`app/routers/admin_planning.py:323`).

**Current control.** `@audited(scope="planning.execute", destructive=True)` at
`admin_planning.py:201`. That is one scope check and one approval.

**What it actually authorizes** (`admin_planning.py:204-212`): it constructs
`build_default_registry()` and hands the **full, unfiltered** tool registry to an
LLM step runner executing LLM-authored plan steps. Downstream, every call goes
through the ungoverned `registry.py:69`.

**Residual risk: CRITICAL.** One `approved=true` buys an unbounded, unaudited
tool loop. The audit record says `planning.execute` and nothing about what was
done.

---

## 6. INFORMATION DISCLOSURE — cross-tenant leakage

**Attacker.** A tenant, or an admin-token holder viewing another tenant's data.

**Entry points and state.**

| Store | Tenant key | Control |
|---|---|---|
| `profiles`, `conversations`, `messages`, `kai_documents`, `kai_doc_chunks`, `kai_api_keys`, `usage_log`, `alerts`, `watchlists`, `subscriptions`, `cancellation_reasons` | `user_id`, FK to `profiles` with CASCADE | Application-level scoping; **no RLS policy found in any migration** |
| `memories` | `user_id`, but the **ORM FK is deliberately omitted** (`app/models/memory.py:26-28`), declared only in migration `0003` | Tenant integrity depends on the migration having run in prod — **UNVERIFIED against the live DB** (needs `\d memories`) |
| `predictions` | **NONE** (`app/models/prediction.py:13`) | global by design |
| `audit_log` | nullable `actor_id` only (`app/models/admin.py:31`) | no tenant key |
| `kai_swe_tasks` (PR #42) | **NONE by design** — "Single-operator model — no user_id / RLS" (`app/models/swe_task.py:9`) | admin gate only |
| **10 SQLite sidecars / 18 tables** | **NONE — zero `user_id` columns anywhere** | filesystem permissions only |
| 4 JSONL sinks | **NONE** | filesystem permissions only |

The SQLite sidecars (`journal`, `learning`, `eq`, `sol`, `relationship`, `kg`,
`persona`, `twin`, `checkin`, `planning`) are one global bag — see
`app/services/journal/storage.py:25`, `app/services/sol/storage.py:34`,
`app/services/kg/storage.py:47`, etc. **`sol.db` holds real payment PII**:
member `email`, `dwolla_customer_id`, `funding_source_href`
(`app/services/sol/storage.py:150-161`).

**Retention.** **NONE.** Chat content, uploaded document full text, and memory
embeddings are stored in full, indefinitely. The entire deletion surface is
`app/services/memory/store.py:75` (`delete_memory`), `app/services/planning/storage.py:406`,
and profile-delete cascades.

**Also leaking upward into the model:** `audit_query`
(`app/services/tools/audit_query.py:13`) hands the model the subsystem and
enabled-scope inventory — useful reconnaissance for §2.1.

**Residual risk: HIGH.** No database-enforced tenant isolation anywhere; a single
missing `WHERE user_id = …` is a full cross-tenant read. The absence of RLS means
the ORM is the only boundary.

---

## 7. INFORMATION DISCLOSURE — provider key exfiltration and SSRF

**Attacker.** A tenant, or an injected document/page (§2.1).

### 7.1 SSRF via `web_fetch` — confirmed bypassable

`app/services/tools/web_fetch.py:59-86`:

```python
if parsed.hostname in ("localhost","127.0.0.1","0.0.0.0","::1"): raise ToolError(...)
if parsed.hostname and parsed.hostname.startswith((            # web_fetch.py:72
    "10.", "192.168.", "169.254.", "172.16.", … "172.31.",
)): raise ToolError(...)
r = httpx.get(url, timeout=FETCH_TIMEOUT, follow_redirects=True, …)  # web_fetch.py:81-84
```

The guard string-prefix-matches the **literal hostname text**, then follows
redirects with no re-check. Bypasses:

- a hostname whose DNS resolves to a private IP;
- decimal/hex IP literals (`http://2130706433/` = `127.0.0.1`);
- IPv6 forms;
- `172.32.*`+ and other RFC1918-adjacent ranges outside the hardcoded list;
- **decisively:** any public URL that 302s to `http://169.254.169.254/…`.

**Residual risk: HIGH.** Cloud metadata and internal services are reachable from
a plain user chat turn. On the current Mac-mini deployment there is no IMDS, but
`127.0.0.1:11434` (Ollama) and any other loopback service are reachable via the
redirect path.

**Fix (not applied):** resolve the host and test
`ipaddress.ip_address(resolved).is_private/is_loopback/is_link_local`, and re-check
on every redirect hop (`follow_redirects=False` + a manual loop).

### 7.2 Provider keys

Four adapters hold secrets and reach the network on every chat turn:
`OPENAI_API_KEY` (`adapters/openai_adapter.py:21-26`), `ANTHROPIC_API_KEY`
(`anthropic_adapter.py:21-26`), `PERPLEXITY_API_KEY` (`perplexity_adapter.py:21-26`),
`CLOUDFLARE_AI_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (`cloudflare_adapter.py:47-81`).

**Current control against exfiltration.** Keys are never placed into the model's
context — they live in adapter constructors, not prompts. That is the real
control and it holds. **NONE** beyond that: there is no egress allowlist, and
`web_fetch` will POST-free but GET any URL, so a model that ever *did* obtain a
secret could exfiltrate it as a query string. Reaching a secret would require
tool-mediated file read; no such tool is registered today
(`app/services/tools/__init__.py:46-160`).

**Residual risk: MEDIUM today, HIGH the moment any file-read or shell tool is
added to the default registry.**

### 7.3 Off-host request pinning (a control that works)

`app/services/dwolla/client.py:122-125` refuses any absolute URL not on the
configured Dwolla host, so a malicious `_links.href` in a Dwolla response cannot
redirect a transfer. This is the pattern `web_fetch` should copy.

---

## 8. TAMPERING / ELEVATION — sandbox escape (PR #41/#42 only)

**Attacker.** Admin-token holder submitting a command, or the SWE agent brain
acting on an injected task description.

**Entry points.** `POST /admin/swe/run` (`app/routers/admin_swe.py:52`, scope
`swe.run`), `POST /admin/swe/tasks/{id}/plan/approve` (`admin_swe_tasks.py:230`,
scope `swe.brain.execute`).

**Current controls — this is the best-governed surface in the repo.**
- Routes **do not mount at all** on a prod-marked env: `swe_admin_enabled()` allow-lists `{development, dev, local, test, testing, ci}` and an explicit `ENV=production|prod` vetoes even a non-prod `APP_ENV` (`app/services/swe_runtime/config.py:31-41`), wired at `app/main.py:192-200`. Note it deliberately refuses `staging` too — the mislabeled-prod workaround.
- `KAI_SWE_RUNTIME_ENABLED` off by default; `DisabledSandbox` never executes (`app/services/swe_runtime/sandbox.py:57-64`).
- Container lockdown: **no host bind mount** (source copied in via `docker cp`), `--network none`, `--cap-drop ALL`, `--security-opt no-new-privileges`, no host Docker socket, memory/pids/cpu caps, wall-clock timeout with `docker kill`, force-removed afterward (`sandbox.py:1-12`, policy fields at `config.py:62-76`, argv built by the pure function `build_create_args`, `sandbox.py:78+`).
- Deny-by-default allowlists: images (`config.py:44-47`, `image_allowed` `:86`), repo roots resolved with `os.path.realpath` and prefix-checked (`config.py:89-105`) — **with no allowlist configured, nothing is runnable**.
- Command substring denylist for egress/credential/escape intent, explicitly for auditability rather than as the primary control (`config.py:53-59`).
- Artifact caps: 2 MB total, 500 files (`config.py:71-72`).

**Residual risk: MEDIUM, and not in production.** Documented gap: the container
runs as **root inside the container** — `config.py:66-69` states containment is
via network/caps/no-mount/ephemeral and that "a chown-on-entry non-root variant
is a hardening follow-up." A Docker or kernel escape is therefore an escape to
the daemon user on the host. `docker` itself is in the denied-substring list, so
the socket-abuse path is closed by intent as well as by absence.

---

## 9. TAMPERING — money-movement abuse

**Attacker.** Admin-token holder; or the model, if any path ever bridges the LLM
to a transfer.

**Entry points.** `POST /admin/sol/cycles/{id}/collect|retry-failed|payout`
(`app/routers/sol.py:340,345,350` → `_collect` `:237`, `_retry_failed` `:255`,
`_payout` `:301`).

**Current controls — layered, and mostly real.**
1. Admin token at router level — `sol.py:44`.
2. `@audited(scope="sol.transfer", destructive=True)` → `ScopeDenied` (403) / `PendingApproval` (409) — `app/services/governance/actions.py:96-120`.
3. Sandbox latch — `DwollaClient.__init__` raises `DwollaProductionLocked` unless `DWOLLA_ALLOW_PRODUCTION=1` when `DWOLLA_ENV=production` (`app/services/dwolla/client.py:80-85`).
4. Atomic conditional-UPDATE claims (`st.claim_contribution` pending→processing, `st.claim_payout`) so a double-click loses the race — `sol.py:221-222, 319`.
5. Stable per-row Dwolla `Idempotency-Key` (`sol-contrib-{id}`, `sol-payout-{id}`, `sol-contrib-{id}-retry-{n}`) — `client.py:132-137`; `retry_count` advances only on a **confirmed** transfer, so a lost response reuses the same key (`sol.py:279-291`).
6. Claim revert on `DwollaError` keeps rows retryable — `sol.py:232-234, 294-296, 335-337`.
7. Money is integer cents end-to-end; string conversion only at the API boundary, rejecting non-numeric/non-positive amounts — `sol.py:49`, `client.py:252`.
8. **The LLM is fenced out.** `app/services/tools/dwolla_tool.py:19` `_ACTIONS` is exactly six read verbs (`account`, `list_customers`, `get_customer`, `list_funding_sources`, `list_transfers`, `get_transfer`) — verified; there is no create/transfer action.
9. The Sol scheduler never moves money — it scans and notifies; `KAI_SOL_AUTOPILOT` only auto-advances cycles, serialized by a module lock (`app/services/sol/scheduler.py:34, 87-106`).
10. `POST /sol/webhook` is fail-closed HMAC-SHA256 over the raw body, constant-time (`sol.py:361-370`, `client.py:232-244`), whitelisted topics only, with monotonic idempotent state transitions.

**Weaknesses.**
- The scope gate is transitively open under `KAI_SCOPE_SOL=1` — §4. The "quadruple lock" is a triple lock in the natural configuration.
- `approved` is caller-asserted — §2.5.
- `POST /admin/sol/customers` and `/customers/{id}/funding-sources` (`sol.py:180,186`) pass raw operator dicts through to Dwolla and provision bank accounts under `destructive=False`.
- **Stripe is the weaker money system.** None of the four webhook handlers in `app/routers/billing.py:298+` is `@audited` — real card money changes tier and subscription state with **no governance record at all**. Signature verification is solid (`app/services/stripe_service.py:116-137`, documented as "the ONLY trust boundary"), and a tier resolving to `free`/unknown is rejected rather than defaulted (`billing.py:389-394`). But `tests/test_billing.py` has 11 tests for 510 lines of live-revenue code, against 53 tests for Sol.
- Known, documented limitation: **no clawback** — a contribution that ACH-returns *after* its payout settled does not claw back the disbursed pool (`app/services/sol/engine.py:16-25`).
- LLM spend caps are soft: `over_daily_cap` degrades to a free local model rather than refusing (`app/services/router/router.py:106-108`), is evaluated **once at turn start**, and is not re-checked across up to `DEFAULT_MAX_TOOL_ITERS = 5` iterations (`router.py:25, 297`). `over_monthly_cap` exists (`app/services/router/spend_tracker.py:119`) but is never referenced by the router. Unknown models cost 0.0 silently (`adapters/base.py:11-37`). Streaming cost is a `len(text)//4` estimate (`router.py:215-228`).

**Residual risk: HIGH for Stripe (unaudited, thinly tested), MEDIUM for Sol
(genuinely layered, weakened only by the scope wildcard).**

---

## 10. TAMPERING — memory poisoning, self-modification, supply chain

### 10.1 Memory poisoning

**Attacker.** A tenant, or injected content (§2.1) that persuades the model to
call `memory_tool`.

**Entry point.** `memory_tool(action="save")` → `add_memory` + `ctx.session.commit()`
(`app/services/tools/memory_tool.py:87-93`), from any chat turn.

**Current control.** **NONE** — no approval, no audit record, no rate limit, no
content review. Type is constrained to `{fact, event, preference, note}`
(`memory_tool.py:83-85`) and that is the whole validation.

**Persistence.** Memories are retrieved into every subsequent turn
(`app/services/nai_brain/memory_injection.py`), so a single poisoned save
influences all future conversations for that user — a durable prompt-injection
foothold. There is no TTL and no pruning (§6).

**Second-order poisoning surfaces, all admin-token-gated but unaudited or
weakly audited:** `POST /admin/learning/feedback` (`app/routers/admin_learning.py:55`,
**no `@audited`**) and lesson activate/dismiss (`:154,159`) change KAI's own
guidance; `admin_persona.py:87,92` and `admin_twin.py:175,180,191` change its
persona and digital twin; `admin_kg.py:128` adds knowledge-graph edges.

**Residual risk: HIGH.** Memory is the cheapest persistence mechanism an attacker
has, and it is entirely ungoverned.

### 10.2 Self-modification

**Attacker.** Admin-token holder, or the self-heal scheduler acting on a
detector.

**Entry points.** `POST /admin/self-heal/run` with `apply=true`
(`app/routers/admin_self_heal.py:49`); the in-process scheduler
(`app/main.py:56-60`).

**Current controls — deliberately bounded, and the bound holds.**
- Triple gate re-checked every tick: `KAI_SELF_HEAL_SCHEDULER_ENABLED` **and** scope `self_heal` **and** `KAI_SELF_HEAL_ENABLED` (`app/services/self_heal_scheduler.py:45-58`); interval floor 60s, default 1800s (`:30-34`).
- Auto-fix is a **two-item allowlist**: extend `OLLAMA_MODEL_MAP` in `.env` — only *adds* keys, validates JSON, and takes a timestamped backup first (`app/services/self_heal.py:138-150`); and `rmtree` every `__pycache__` under the repo (`self_heal.py:154-165`).
- Code edits, commits, git operations, process kills, and deleting non-cache files are never auto-done.

**Residual risk: MEDIUM.** The blast radius is a `.env` line and pycache — but it
is a *write to the daemon's own configuration file*, and the scope gate reaching
it is `KAI_SCOPE_SELF` (§4). A related, softer surface:
`POST /admin/planning/{id}/draft-adapter` (`admin_planning.py:366`) has KAI write
its own tool source into a drafts directory under `destructive=False`
(`admin_planning.py:258-278`).

### 10.3 Supply chain

**Attacker.** A compromised MCP server operator, a Composio-connected app, a
malicious PyPI release, or a GitHub project KAI is asked to assess.

**Entry points and controls.**

| Vector | Control |
|---|---|
| **MCP servers** — spawn operator-declared subprocesses, expose arbitrary tools with externally-defined schemas (`app/services/mcp_tools.py:161-195`) | Config-file presence only, and registration **defaults on** (`app/services/tools/__init__.py:64-66`). Only a per-call timeout (`mcp_tools.py:189-192`). No allowlist, no audit, no approval. **Effectively NONE.** |
| **Composio** — arbitrary action slugs against ~200 connected accounts (`composio_generic.py:44-70`) | Requires the operator's prior OAuth connection. Otherwise **NONE** at the KAI layer. |
| **Python dependencies** | No lockfile hash pinning observed; `backend/requirements.txt` is documented as unsatisfiable as-is. **UNVERIFIED** — I did not read `requirements.txt` or check for a lock/hashes; that check would need `pip-audit`/`uv lock`. |
| **GitHub projects assessed by `github_scout`** | Genuinely safe: it searches and assesses only, and **never clones or executes** (`app/services/tools/github_scout.py:11-14`). Adoption stays propose-then-approve. |
| **Docker base images (PR #41)** | Deny-by-default allowlist, default `python:3.11-slim` (`app/services/swe_runtime/config.py:44-47, 86`). Tag-based, not digest-pinned — a mutable tag is a supply-chain surface. |
| **CI** | **UNVERIFIED** — I did not inspect `.github/workflows/` in this repo. |

**Residual risk: HIGH for MCP and Composio** — both are unbounded third-party
code paths reachable from a tenant chat turn (§2.1, §2.2) with no gating.

---

## 11. Dark KAI (as proposed)

> **UNVERIFIED — SOURCE MISSING.** `docs/dark-kai/` was an **empty directory**
> before this file was written, and a repo-wide search for "dark kai" / "dark-kai"
> (excluding `.git`) returns **no matches**; `git log --all --grep=dark -i`
> returns nothing relevant. **There is no Dark KAI proposal document in this
> repository.** I will not invent its components.
>
> What follows is therefore written as a **conditional delta**: for each
> capability a "Dark KAI" might plausibly add, what the *existing, verified*
> control state means for it. Every "current control" cite below is real; every
> Dark KAI capability is labeled as an assumption. Replace this section with a
> concrete analysis once the proposal exists.
>
> The only concrete autonomy-expansion artifacts that *do* exist in the repo are
> `plans/PLAN-kai-autonomous-swe-agent.md` (PR #41/#42, analyzed in §8) and
> `docs/AGI_ROADMAP_SPRINT_PLAN.md` (which lists self-correction, long-term
> planning, learning, digital twin, and computer control as **needing real
> product specs before implementation** — `AGI_ROADMAP_SPRINT_PLAN.md:1-7`).

### 11.1 The structural point

Almost every KAI control today is **operator-in-the-loop**: the admin token
(§2.3), `approved=true` in a request body (§2.5), a scheduler that notifies
instead of acting (§9 control 9). Autonomy is exactly the property that removes
the human those controls depend on. So the Dark KAI delta is not primarily "new
code with new bugs" — it is that **the existing NONEs stop being survivable.**

Ranked by how much each proposed capability multiplies an existing unmitigated
finding:

| If Dark KAI adds… (ASSUMPTION) | It multiplies… | Because the current control is |
|---|---|---|
| **Unattended tool loops** (no per-turn human) | §2.1 prompt injection | `registry.py:69` — **NONE**: no scope, no approval, no audit on any tool call |
| **Self-authored plans executed without per-step approval** | §5 | `admin_planning.py:201-212` — one approval already buys an unbounded loop; removing the human removes the only gate |
| **Persistent autonomous identity / long-running agent** | §10.1 memory poisoning | `memory_tool.py:87-93` — **NONE**: no approval, no audit, no TTL. A poisoned memory becomes a durable goal, not just a durable fact |
| **Any file-read or shell tool in the default registry** | §7.2 key exfiltration | Keys are safe today *only* because no tool can read them. `web_fetch` is already an unrestricted GET-based egress channel (`web_fetch.py:81-84`) |
| **Money actions reachable without a human `approved=true`** | §9 + §4 | `dwolla_tool.py:19` fences the LLM out today — that fence is the single reason prompt injection is not a payments incident. Under `KAI_SCOPE_SOL=1` the scope gate is already open (§4) |
| **Autonomous code push / self-modification beyond the two-item allowlist** | §10.2, §8 | `self_heal.py:138-165` is bounded to `.env` + pycache; PR #42's push path is the only hardened variant (fresh clone, no ambient git credential, CI-path block, no `--force`, fsync'd fail-closed audit — `swe_runtime/push.py:5-25`) |
| **A Dark KAI admin surface behind `X-Admin-Token`** | §2.3 | One static string, no roles, no rotation, no per-actor attribution (`actions.py:75`) |
| **Multi-tenant autonomous agents** | §6 cross-tenant leakage | No RLS anywhere; 10 SQLite sidecars with **zero** `user_id` columns; `kai_swe_tasks` has none by design (`swe_task.py:9`) |
| **Any autonomous behavior at all** | §3 audit tampering | The log has no hash chain (`grep prev_hash|hmac|chain` → nothing), fails soft (`audit_log.py:82-83`), records `actor="operator"` for everything, and contains **no tool calls whatsoever** |
| **More MCP servers / broader Composio grants** | §10.3 | **NONE** — MCP registration already defaults on (`tools/__init__.py:64-66`) |

### 11.2 Prerequisites before Dark KAI is safe to build

These are not new controls invented for Dark KAI; they are the existing gaps that
autonomy converts from "bad" to "unrecoverable", in dependency order:

1. **Land PR #39.** Route `ToolRegistry.execute` through governance: a per-tool `scope` + `writes` declaration on the `Tool` protocol (`app/services/tools/base.py` has neither today), a default-deny `ctx.allow_writes` check, and `record_action(...)` on every path including block and error. This single change makes `actions.py:21-22`'s central claim true. Nothing else on this list matters until it lands.
2. **Restore the tier gate on `/kai/chat`'s registry** (`nai.py:55`) and drop `dwolla`/`twenty_crm`/`composio`/MCP from the per-user registry entirely — they are operator-scoped credentials in a multi-tenant lane (§2.2). Also remove the `COMPOSIO_USER_ID` identity collapse (`composio_auth.py:34-37`).
3. **Make the scope wildcard non-destructive-only** — require the exact scope when `destructive=True` (`actions.py:56-63`), or rename every destructive scope onto a disjoint root as SWE already does.
4. **Make the audit log tamper-evident and fail-closed** — hash-chain the JSONL and fsync-or-abort, the way `swe_runtime/push.py:161-179` already does for pushes. Add rotation.
5. **Bind approval to a proven identity everywhere**, not just the SWE gates: replace the shared admin token with `admin_users`-backed auth so `actor` stops being the constant `"operator"`, and add the missing `role='approver'` filter at `approver.py:48-50`.
6. **Fix `web_fetch` SSRF** — resolve the host, test the resolved IP with `ipaddress`, re-check every redirect hop (`web_fetch.py:72-84`).
7. **Add tenant keys / RLS** before any multi-tenant autonomy, and a retention policy before any long-running agent accumulates state (§6).

---

## Appendix — explicitly not verified

- `app/services/alerts.py` (outbound notification target — Telegram per surrounding comments) — not read.
- `.github/workflows/` — not inspected; CI supply-chain posture unknown.
- `backend/requirements.txt` — not read; dependency pinning/hashing unknown.
- Live production database — no RLS check, no `\d memories` FK confirmation.
- The root `.env` (~230 keys per `deploy/start_nai.sh` comments) — not in the repo, not read.
- Test *results* — 966 `def test_` across 66 files is a count of test functions, not verified passes; `pytest.ini` configures no coverage plugin and no threshold.
- **The Dark KAI proposal itself** — does not exist in this repository (§11).
