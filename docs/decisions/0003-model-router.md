# 0003 — Model router decisions

Date: 2026-05-19
Stage: 2
Status: locked

## Decisions
1. **Rule-based router v1.** Learned routing deferred until we have a labeled production sample.
2. **Adapter contract: `complete()` + `stream()` returning `CompletionResult`** (Protocol-typed, runtime-checkable).
3. **Routing rules** (single dict in `router.py`, easy to change):
   - `Intent.CODE` → Anthropic
   - `Intent.REALTIME` → Perplexity
   - `Intent.GENERAL` → OpenAI
   - `over_daily_cap` or `prefer_local=True` → Ollama
4. **Spend tracking** in `llm_call_log` table (FK to `profiles`).
5. **Soft cap** = `NAI_MAX_DAILY_SPEND_USD` ($2/day default); when hit, downgrade silently to Ollama.
6. **Hard cap** = $20/mo per provider in dashboards (Stage 0 — operator-set).
7. **No fallback chain in v1.** Adapter failure raises. Retry/fallback complexity belongs in v2 once we know real failure modes.
8. **Streaming token counts are estimated** (chars/4) because not every provider returns usage cleanly mid-stream. Accurate streaming usage deferred.
9. **Single `PRICING` dict** in `adapters/base.py` — must be updated when model strings or prices change. Unknown models silently cost $0 (logged at call site).

## Model defaults locked
- OpenAI: `gpt-4o-mini` (default), `gpt-4o` (reserved)
- Anthropic: `claude-sonnet-4-6` (default), `claude-opus-4-7` in PRICING (reserved)
- Perplexity: `sonar-pro`
- Ollama: `llama3.1:8b` (from Stage 0)

## Reversible?
- Adapter swap: yes (Protocol-based, no inheritance lock-in).
- Routing rules: yes (constants in `router.py` + `intent.py` regex tuples).
- Soft cap thresholds: yes (env vars `NAI_MAX_DAILY_SPEND_USD` / `NAI_MAX_MONTHLY_SPEND_USD`).
- Adding a 5th adapter: yes (one new file + one entry in `build_default_router`).
- Streaming token accounting: yes (post-hoc estimation is a known approximation; swap in real usage tracking when v2 lands).

## Deviations from the Stage 2 prompt
1. **Plan said `claude-opus-4-6` in PRICING.** Used `claude-opus-4-7` — the current Opus 4.X release. Sonnet default stays at `claude-sonnet-4-6` as the plan locked.
2. **Real code under `backend/app/services/router/`**, with `services/narai/router/__init__.py` as a re-export shim. Same Stage-0-spirit reconciliation that Stage 1 used for memory: the locked namespace `services.narai.router` is preserved for consumers; the real implementation co-locates with `backend/app/` so it shares Base, Alembic, and the existing test infra. Shim integrity is asserted in the verification step (`nr.Router is app.services.router.Router`).
3. **Migration applied via Supabase MCP** (`add_llm_call_log_table`); the parity Alembic file (`0004_add_llm_call_log_table.py`) is committed but unapplied locally — same pattern as Stages 0 and 1.
4. **No `DIRECT_DATABASE_URL` introduced.** The plan called for it; we don't run Alembic locally, so it's moot.

## Verification status
- [x] Schema landed on Supabase: 12 columns, FK `user_id → profiles(id) ON DELETE CASCADE`, 3 secondary indexes (`ix_llm_call_log_user_id_created_at`, `ix_llm_call_log_adapter_created_at`, `ix_llm_call_log_created_at`) + pkey.
- [x] All 17 Stage 2 files parse cleanly.
- [x] Full import chain works: `app.services.router` exports + `services.narai.router` shim point at the same `Router` class (identity check `is` passes).
- [x] 13/13 DB-free unit tests pass (`test_intent.py` ×4 + `test_router.py` ×9). Run via `python -m pytest tests/test_intent.py tests/test_router.py --noconftest` from `backend/`. `--noconftest` is required because the shared `conftest.py` pulls `app.main` → routers → celery, which isn't in this venv yet.
- [ ] **`test_spend_tracker.py` — NOT RUN.** Requires `psycopg2-binary` + a reachable Postgres with `llm_call_log` + `profiles` (Supabase has both; local PG doesn't).
- [ ] **`scripts/smoke_test_router.py` — NOT RUN.** Same prereqs plus three live API keys exported. Recorded as operator follow-ups.

## Out of scope for Stage 2
- Tool use / function calling (Stage 3).
- Memory injection into prompts (Stage 3).
- Async support (Phase B).
- Retry / fallback chains.
- Cross-provider accurate streaming token counts.
- Per-user spend caps in DB (current caps are global env vars).
- Citation rendering for Perplexity responses (stored in `metadata` but not surfaced).

## Operator follow-ups (do before Stage 3 needs them)
- [ ] `pip install -r backend/requirements.txt` — adds `psycopg2-binary`, `celery`, the rest of backend deps. Unblocks the full pytest suite (Stage 1 spend tracker + Stage 2 spend tracker + every backend test).
- [ ] Verify the three API keys in the root `.env` work: `OPENAI_API_KEY` (confirmed present), `ANTHROPIC_API_KEY` (confirmed present), `PERPLEXITY_API_KEY` (still blank as of Stage 0 — fill it).
- [ ] Run the smoke test once an env with `DATABASE_URL` + all three API keys is in place. Expected cost: <$0.01 total. Inspect `llm_call_log` after — should show 4 rows with non-zero `cost_usd` for the cloud adapters and `cost_usd=0` for Ollama.
- [ ] Spot-check Anthropic pricing for `claude-sonnet-4-6` and `claude-opus-4-7` before any rollout — `PRICING` was hand-entered and providers shift prices over time.
