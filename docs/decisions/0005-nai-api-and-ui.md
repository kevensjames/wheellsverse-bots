# 0005 — NAI Chat API + UI decisions

Date: 2026-05-19
Stage: 4
Status: locked

## Decisions
1. **Two endpoints**: `POST /nai/chat` (tools-capable, JSON) and `GET /nai/chat/stream` (SSE, no tools). `GET /nai/conversations`, `GET /nai/conversations/{id}`, `DELETE /nai/conversations/{id}` round out the surface.
2. **Conversation auth is scoped by FK + WHERE filter**. Every read/write filters by `user_id == current_user.id`. No path can return another user's conversation.
3. **History window: last 20 messages per turn**. Tool-role and system-role rows are skipped on re-feed because they re-emerge from the tool loop when tools are enabled.
4. **Auto-title: first 60 chars of the first user message.** Overwrites the live default `'New Chat'` on the first real turn. LLM-titling deferred.
5. **JWT in stream URL via `?token=` query param.** EventSource cannot set headers; the Mac mini binds to `127.0.0.1`, so the URL never leaves localhost. Phase B must move to HttpOnly cookies before any public exposure.
6. **Streaming and tools are mutually exclusive in v1.** The streaming endpoint doesn't load the tool registry; the JSON endpoint can use either path depending on `use_tools`.
7. **Default mode = streaming + no tools.** User opts in to tools per turn via the checkbox.
8. **Memory injection: top-3 every turn** (already locked in Stage 3 decision 0004).
9. **Multi-conversation supported in the data model**; UI only shows one stream at a time. Conversation list sidebar = Phase B.
10. **Vanilla HTML/JS frontend**. No bundler, no React. Single page (`/nai-ui/`).

## Reversible?
- Frontend stack swap: yes (React/Svelte in Phase B).
- Auth mechanism: yes — Phase B must replace query-param JWT.
- History window size: yes (`HISTORY_WINDOW` constant).
- Endpoint shapes: backward-compatible additions yes, breaking changes painful.
- `model_used` vs `model` field naming: keeping `model_used` end-to-end because changing the DB column would mean migrating production data.

## Deviations from the Stage 4 prompt template

These mattered, all forced by production reality:

1. **The plan would have DESTROYED 29 conversations + 98 messages of real data.** `public.conversations` and `public.messages` already exist on Supabase with a different schema (from the prior NarAI v1 chat system). Instead of `CREATE TABLE`, Stage 4 issues an **additive ALTER** via Supabase MCP migration `stage4_enhance_conversations_messages`. Existing rows survive untouched.
2. **Schema reconciliation**: the live tables use `model_used` (not `model`), have a `message_count` counter (kept and maintained), have a denormalized `user_id` on `messages` (NOT NULL — Brain populates from conversation's user_id), and `title` is NOT NULL with default `'New Chat'`. The ORM matches the live schema exactly.
3. **Import paths** corrected for this monorepo:
   - `app.db.base.Base` → **`app.database.Base`**
   - `app.deps.get_current_user` → **`app.dependencies.auth.get_current_user`**
   - `app.deps.get_db` → **`app.database.get_db`**
4. **`MessageOut.model_config = ConfigDict(protected_namespaces=())`** because Pydantic v2 reserves `model_` field names. We need `model_used` to carry through to the API.
5. **Static mount uses a `Path(__file__).parent` resolution** so uvicorn boots from any working directory.
6. **`stream_auth.py` placed under `backend/app/dependencies/`** (where `auth.py` already lives), not at the plan's flat `app/deps_stream.py` path.

## Verification status
- [x] Schema enhanced on Supabase via MCP migration. New columns: `conversations.metadata`, `messages.{tool_calls, tool_call_id, tool_name, adapter, cost_usd, metadata}`. New constraint: `ck_messages_role`. New index: `ix_messages_conv_created`. 29 + 98 existing rows preserved (additive only).
- [x] All 15 Stage 4 files parse cleanly.
- [x] **FastAPI app boots end-to-end** with the NAI router and `/nai-ui` static mount registered. 28 total routes.
- [x] **26/26 prior unit tests still pass.** No regressions from Stage 4 changes.
- [ ] **`test_brain.py` (5 integration tests) — to be run by operator** once `TEST_DATABASE_URL` points at a Postgres with `profiles` + `users` tables. The existing test conftest uses `Base.metadata.create_all()`, which now creates `conversations` and `messages` with FKs to `profiles.id`. A local test DB without `profiles` will fail at FK creation; either ship a `Profile` ORM model or use a Supabase test branch.
- [ ] **`smoke_test_nai.py` — deferred.** Needs a running uvicorn + a real JWT from `POST /auth/login` + Supabase `DATABASE_URL` for the backend's Settings to load.
- [ ] **Browser sanity check — deferred.** Same prereq as smoke. The `/nai-ui/` static mount IS registered in the bootable app.

## Out of scope for Stage 4
- Streaming + tools simultaneously (Phase B).
- LLM-generated conversation titles.
- Conversation list UI sidebar.
- Tool-call visualization in the UI.
- Markdown rendering in chat (currently plain `textContent`).
- Message edit / regenerate.
- Real signup flow / Stripe (Phase B).
- Rate limiting.
- File uploads / vision.
- Per-user spend caps surfaced in the UI.

## Operator follow-ups (carried forward across Stages 1–4)
- **Set `DATABASE_URL` and `DIRECT_DATABASE_URL`** in the shell to Supabase pooler/direct with password. This unblocks every deferred verification.
- **Fill `PERPLEXITY_API_KEY`** in root `.env`.
- **Run all four smoke tests** in order (memory → router → tools → nai). The NAI smoke needs a JWT from `POST /auth/login`.
- **Decide on `Profile` ORM model** if running the Brain integration tests locally: either add a minimal `Profile` model to `backend/app/models/` so `create_all` builds the FK target, or point tests at a Supabase test branch that already has `profiles`.
- **Open the browser at `http://127.0.0.1:8001/nai-ui/`** once uvicorn is up. Paste a JWT when prompted. The first chat should stream; the tools-on path should save and recall a memory across new conversations.
- **Before any public exposure**: swap query-param JWT auth on the stream endpoint to an HttpOnly cookie. Bind the JWT lifetime to a short TTL.
