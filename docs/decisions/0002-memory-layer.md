# 0002 — Memory layer decisions

Date: 2026-05-19
Stage: 1
Status: locked

## Decisions
1. OpenAI `text-embedding-3-small`, 1536-dim — cheap, strong, easy to swap.
2. ivfflat cosine index, lists=100 — adequate at <1M vectors.
3. Memory types: `fact`, `event`, `preference`, `note` (enum-checked at DB and Python).
4. Retrieval scoring: `0.7 * cosine_similarity + 0.3 * recency`, recency exp-decay with 30-day half-life on `last_used_at`.
5. Top-K default = 8.
6. Sync SQLAlchemy in v1; async deferred.
7. Auto-bump `last_used_at` on every successful retrieval (toggleable via `bump_last_used=False`).

## Reversible?
- Embedding model: yes, but requires re-embedding all stored memories.
- Scoring weights: yes — change constants in `retrieval.py`.
- Index type (ivfflat → hnsw): yes, single migration; `ANALYZE` after.
- Memory-type enum: extending is yes; removing is no without data migration.

## Deviations from the Stage 1 prompt

These mattered enough to surface — every one was forced by repo reality that the plan template didn't account for:

1. **FK target is `public.profiles(id)`, not `users(id)`.** Production Supabase has no `public.users` — only Supabase Auth's `auth.users` + the standard `public.profiles` mirror. Every other user-scoped table in the repo (`conversations`, `messages`, `memory_notes`, `subscriptions`) FKs to `profiles.id`, and Stage 1 follows suit.
2. **No `ForeignKey` on the SQLAlchemy `Memory.user_id`** — declared at the Alembic / DDL level only. Reason: `backend/`'s tests bootstrap their schema with `Base.metadata.create_all`, and `backend/`'s `Base` has no `Profile` model. Putting the FK on the ORM would force the test environment to grow a Profile model just for `create_all` to succeed. The FK exists in production (Supabase) where `profiles` already lives.
3. **Code home is `backend/app/`, not `services/narai/memory/`.** The Stage 0 plan locked the engine path at `services/narai/`, but the existing `users`/Alembic/conftest/Base infrastructure all live under `backend/app/`. Reconciliation: the engine implementation sits in `backend/app/{models,services}/memory/`, and `services/narai/memory/__init__.py` is a re-export shim that injects `backend/` into `sys.path` and exposes the same public API. Call-sites in NarAI consumer code still write `from services.narai.memory import ...`. When NarAI is lifted to its own deployable in Phase B, only the shim moves.
4. **DDL applied via Supabase MCP, not local `psql`.** Stage 0 already established this — no local Postgres exists. The Alembic file (`0003_add_memories_table.py`) is committed for parity, but it has not been run; the production schema lives in Supabase migration `add_memories_table` (applied 2026-05-19).
5. **No `DIRECT_DATABASE_URL` introduced.** The plan called for a 5432 direct connection for Alembic. Skipped because we don't run Alembic locally — the Supabase MCP path bypasses the pooler/direct distinction entirely.

## Verification status

- [x] Schema landed on Supabase: 8 columns, FK `user_id → profiles(id) ON DELETE CASCADE`, check constraint on `memory_type`, 3 secondary indexes (`ix_memories_user_id_created_at`, `ix_memories_memory_type`, `ix_memories_embedding` ivfflat lists=100) + pkey.
- [x] All Stage 1 Python files parse and the Memory model + service callables import cleanly (sqlite-shimmed because the venv lacks `psycopg2-binary`).
- [ ] **`pytest backend/tests/test_memory.py` — NOT RUN.** Requires `psycopg2-binary` (in `backend/requirements.txt` but absent from this venv) + a reachable Postgres at `TEST_DATABASE_URL`. Operator must install backend deps and either restore local PG or point `TEST_DATABASE_URL` at a Supabase test branch before this can be exercised end-to-end.
- [ ] **`python -m scripts.smoke_test_memory` — NOT RUN.** Same prerequisites, plus `OPENAI_API_KEY` exported (currently in root `.env` but not picked up by the shell automatically).

## Out of scope for Stage 1
- Auto-extraction of salient facts from chat turns (Stage 3 + Celery).
- Cross-user / shared memory pools.
- Memory editing UI.
- Embedding cache.
- Memory consolidation / dedup.

## Operator follow-ups
- [ ] `pip install -r backend/requirements.txt` (adds `psycopg2-binary` and friends).
- [ ] Decide on `TEST_DATABASE_URL` — local PG or a Supabase branch — then run `pytest backend/tests/test_memory.py -v`.
- [ ] Export `OPENAI_API_KEY` + a working `DATABASE_URL` and run `python -m scripts.smoke_test_memory` from `backend/` to validate ranking quality on real embeddings.
- [ ] (Optional) Add a `Profile` SQLAlchemy model to `backend/app/models/` so future migrations can declare FKs on the ORM rather than at DDL level.
