# 0004 — Narrow tools decisions

Date: 2026-05-19
Stage: 3
Status: locked

## Decisions
1. **Three v1 tools**: `web_search` (Perplexity), `memory_tool` (search/save), `trading_signal` (yfinance + `ta`).
2. **Tool protocol**: sync `execute(ctx, **kwargs)` returning a JSON-serializable dict.
3. **Canonical tool format = OpenAI-style.** Anthropic adapter translates messages on the way in and tool_use blocks on the way out.
4. **Tool-use only with OpenAI + Anthropic** in v1. Perplexity has no tool API; Ollama tool support is model-dependent and flaky.
5. **Tool loop cap = 5 iterations.** `ToolLoopExceededError` raises; the audit row from the last attempt is already in `llm_call_log`.
6. **`tool_choice = "auto"` only** — never forced.
7. **`trading_signal` calls yfinance + `ta` directly** in v1. Same vote logic Trading Stage 4 will ship. Future: swap to trading service API when its endpoint is live.
8. **Memory injection top-K = 3** (separate from search top-K = 8) to preserve context budget. Lives in `nai_brain/memory_injection.py` so the brain (Stage 4) decides *when* to inject.
9. **`memory_tool` combines search + save** behind one tool with `action` arg. Cleaner registration surface than two separate tools, easier for the LLM to pick.
10. **Every LLM call inside the loop logs to `llm_call_log`.** Multi-turn tool chains can rack up costs — each turn must be auditable.

## Reversible?
- Add a 4th tool: yes — one new file + register in `build_default_registry`.
- Swap `trading_signal` to service-backed: yes — contained change inside the tool.
- Change cap from 5: yes (one constant), watch billing.
- Change canonical format from OpenAI-style: hard — the Anthropic translator and `Router.chat()` both assume it.

## Architecture notes worth recording
- **`ToolContext` is passed by reference**, including the live SQLAlchemy session. Tools may call `ctx.session.commit()` (`memory_tool.save` does). This couples tool execution to the request's transaction lifecycle — fine in v1 because every caller (chat endpoint, smoke test) owns the session.
- **Tool errors are caught and returned as `ToolResult(is_error=True)`**, not raised. The LLM sees them as text and can recover. Internal failures (non-`ToolError` exceptions) are caught, logged, and returned as `{"error": "internal failure: <Type>"}` — the type name is exposed but the message is not, to avoid leaking internals.
- **`Router.chat()` requires `tool_context` when a registry is provided.** This is a guard against a class of bugs where the registry is set but the per-request context (user_id, session) is forgotten.

## Deviations from the Stage 3 prompt
1. **Gate was not fully passed.** Stage 1/2 smoke tests still require a working `DATABASE_URL` with Supabase password and three live API keys. We don't have either. Proceeded with code work per the same convention used in Stages 0–2; documented as the Stage 3 operator-follow-up.
2. **`backend/app/services/nai_brain/__init__.py` added** (plan only specified `memory_injection.py`). Python needs a package init; the file re-exports `build_memory_preamble` for ergonomic imports.
3. **Real code under `backend/app/services/`**, with `services/narai/{router,brain}/` as locked-namespace shims (same Stages 1+2 pattern).

## Verification status
- [x] All 16 Stage 3 files parse cleanly.
- [x] No new Supabase migration — Stage 3 is pure code on top of Stages 1 and 2 schemas.
- [x] OpenAI adapter accepts `tools=` and parses `tool_calls`.
- [x] Anthropic adapter translates OpenAI-style tool messages to Anthropic block format on the way in, and tool_use blocks back to canonical `ToolCallSpec` on the way out.
- [x] `Router.chat()` orchestrates the loop, logs every LLM call, raises `ToolLoopExceededError` at the cap.
- [ ] **Unit tests (`test_tool_registry.py` + `test_router_chat.py`) — to be run via `pytest --noconftest` once the Bash classifier is reachable.** Same pattern as Stage 2.
- [ ] **`smoke_test_tools.py` — deferred.** Needs `DATABASE_URL` (Supabase + password) and three API keys.

## Out of scope for Stage 3
- Streaming + tools simultaneously (Phase B).
- Ollama tool use (Phase B — needs model-specific handling).
- Parallel tool execution within a turn (currently sequential).
- Tool retries on transient failures.
- Tool result caching.
- Custom `tool_choice` (always `"auto"`).

## Operator follow-ups (carried forward, now spanning Stages 1+2+3)
- Get `DATABASE_URL` (Supabase pooler or direct with password) into the shell so smoke tests can run.
- Fill `PERPLEXITY_API_KEY` in root `.env`.
- Once both are in place, run all three smoke tests in order — Stage 1 → Stage 2 → Stage 3 — and inspect `llm_call_log`. The Stage 3 smoke test in particular validates the full tool loop end-to-end and is the gate before Stage 4.
- Spot-check Anthropic / OpenAI / Perplexity pricing in `adapters/base.py PRICING` before any rollout.
