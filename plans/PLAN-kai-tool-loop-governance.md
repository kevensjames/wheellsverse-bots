# PLAN — Govern the LLM tool loop (close the ungoverned-write gap)

**Status:** IN IMPLEMENTATION (integration #1, internal — no external dependency).

## 1. Goal
Every tool the LLM invokes must be **audited**, and any tool that causes an **external side effect** (SaaS write, CRM create, paid generation, MCP fs/git) must be **blocked unless the operator authorized writes for that request**. Read/propose tools keep working unchanged.

## 2. Current implementation (the gap)
`router.chat()` tool loop calls `tool_registry.execute(...)` (`router.py:374`) with **no scope, no approval, no audit**. Safe only because most tools are read/propose-only — but `composio.execute` (Gmail/Slack/Stripe writes), `twenty_crm.create`, `video_gen` (spend), and MCP tools (fs/git) genuinely write, and they run inside the ungoverned loop. Governance (`@audited` scope+approval+audit) is applied only at admin HTTP endpoints, never in the loop.

## 3. Verified gap
Confirmed in the capability inventory §3.1 and by reading `services/tools/registry.py:58` + `router.py:374`. A user chat can currently trigger external writes on the **operator's** single Composio/CRM account (also a cross-tenant leak).

## 4–6. Approach (no external repo)
Enforce at the single choke point `ToolRegistry.execute()`, reusing existing governance primitives (`is_scope_enabled`, `record_action`). Rejected alternatives: per-tool decorators (misses dynamic MCP tools); a new approval service (out of scope for the fix — reuse the flag+audit pattern).

## 7. License / threat model
No new dependency. Threat closed: **prompt-injected or user-driven external writes via the shared operator account.** Trust boundary: the LLM tool loop ↔ external SaaS/MCP. Control: default-deny writes + per-request operator authorization + complete audit. Residual: `allow_writes=True` requests still execute writes (by design, operator-authorized, audited).

## 8. Architecture / permission model
- `ToolContext.allow_writes: bool = False` — per-request operator authorization, threaded from the endpoint.
- A tool declares side effects via a class attribute `writes = True` (read defensively; default False).
- `ToolRegistry.execute()`:
  1. audit **every** call (`record_action`, secrets redacted);
  2. if `writes` and an optional declared `scope` isn't enabled → block;
  3. if `writes` and `not ctx.allow_writes` → block (return an error ToolResult; **do not execute**);
  4. else execute; audit success/failure with `destructive=writes`.
- Policy: **operator chat** (`admin_chat`, admin-token) may set `allow_writes=True`; **user chat** (`nai.py`, multi-tenant) never authorizes writes.

## 9–13. Files
Modify: `services/tools/base.py` (add `allow_writes`), `services/tools/registry.py` (governed execute), the 5 write-tool classes (`composio_generic`, `composio_notion`, `twenty_crm`, `video_gen`, `mcp_tools` → `writes = True`), `services/nai_brain/brain.py` (thread `allow_writes`), `routers/admin_chat.py` (request field + pass-through). No DB migration. No new env var required (optional per-tool `scope` supported for later).

## 14–18. Contracts / audit
Blocked write → `ToolResult(is_error=True, output={"error":"blocked: … requires operator approval"})` so the LLM surfaces it. Audit event per tool call: `tool.<name>` with actor=user_id, destructive=writes, approved=allow_writes, redacted args, success/error, duration.

## 19–20. Limits
No behavior change to timeouts/loop cap. Writes now additionally gated; spend tools (`video_gen`) gated behind authorization.

## 21–24. Tests (`tests/test_tool_governance.py`)
Write tool blocked when `allow_writes=False`; executes when True; read tool unaffected; unknown tool audited+error; each real write tool carries `writes=True`; `record_action` invoked for exec + block; `ToolContext`/`brain.chat` default `allow_writes=False`.

## 25–27. Rollout / rollback / acceptance
Default-off for writes = safe by default; no flag needed to be safe. Rollback = revert the commit (additive change; no migration). **Acceptance:** (a) a `writes=True` tool cannot execute in the chat loop without `allow_writes=True`; (b) every tool call is audited; (c) read tools unchanged; (d) baseline 69 tests still green + new tests pass.
