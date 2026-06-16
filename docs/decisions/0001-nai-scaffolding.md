# 0001 — NAI / NarAI scaffolding decisions

Date: 2026-05-19
Stage: 0
Status: locked

## Decisions
1. Two services: `services/narai/` (engine), `services/nai/` (consumer face).
2. pgvector for memory storage and retrieval — enabled on Supabase project `rqcngphvpjcscculehph` (Postgres 17.6, `vector` v0.8.0 in `public` schema).
3. Ollama + Llama 3.1 8B as local model on Mac mini (coexists with existing `qwen2.5:7b`, `nomic-embed-text`, `llama3.2`).
4. OpenAI `text-embedding-3-small` for embeddings (1536-dim).
5. Vanilla HTML/JS frontend for v1 — no React until Phase B.
6. Hard spend cap $20/mo per cloud provider → $60/mo total burn ceiling.

## Reversible?
- Local model: yes (swap to any Ollama model).
- Embeddings: yes, but re-embedding existing memories required.
- Service split: NO — refactor cost grows every stage. Lock now.
- Frontend stack: yes (Phase B may move to React).

## Deviations from the Stage 0 prompt
- **Postgres**: project uses Supabase (no local Postgres / `DATABASE_URL`). pgvector enabled via Supabase MCP migration `enable_pgvector_extension` instead of a local `psql` invocation. Pre-flight `psql "$DATABASE_URL"` check skipped for this reason.
- **Redis**: not installed locally on the Mac mini. Stage 0 has no Redis dependency; the gap is logged here for Stage 1+ to address before any Redis-backed work begins.
- **`sse-starlette` pin**: plan said `>=2.1.0`. Restricted to `>=2.1.0,<3.0.0` because 3.x bumps `starlette` to 1.0, which violates FastAPI 0.115.x's `starlette<0.47.0` constraint.
- **`openai`/`anthropic`/`httpx`/`tiktoken`**: not re-added — existing pins in `requirements.txt` already satisfy the plan's floors. Avoided downgrading.
- **`.env.example` reuse**: existing file already declared `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`; only added `PERPLEXITY_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`, and the two `NAI_MAX_*_SPEND_USD` caps.
- **`.gitignore`**: existing `memory/` rule (intended for `.omc/memory/` runtime data) was too broad and would have hidden the `services/narai/memory/` Python package. Added a narrow negation `!services/narai/memory/**` immediately after. The `logs/` rule still ignores `deploy/logs/` — intentional, since that's a runtime log destination, not source.

## Out of scope for Stage 0
- Any business logic
- Any DB schema beyond pgvector enable
- Any API endpoints
- Stripe, signups, public exposure

## Operator follow-ups (not blockers for Stage 1, but do these soon)
- [ ] Set $20/mo hard caps in OpenAI / Anthropic / Perplexity dashboards (Task 7).
- [ ] Decide on Redis: install locally (`brew install redis`) or point at a managed instance before Stage 1 needs it.
- [ ] Fill real values in local `.env` for `PERPLEXITY_API_KEY`.
