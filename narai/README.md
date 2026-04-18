# NarAI v2

Production-grade AI assistant for J.K. Blaze (WheellsVerse).
Local-first, multi-model, with long-term memory, RAG, and skill packs.

## Quick start

```bash
# 1. Install dependencies
pip install -r narai/requirements.txt

# 2. Set required env vars (add to .env in monorepo root)
ANTHROPIC_API_KEY=...
NARAI_STORAGE_KEY=some-random-string
NARAI_JWT_SECRET=another-random-string

# 3. Generate password hash
make hash-password -C narai/

# 4. Add to .env:
NARAI_PASSWORD_HASH=<hash from above>

# 5. Migrate legacy NarAI memory
make migrate -C narai/

# 6. Start the server
make dev -C narai/
# → http://localhost:5051/docs
```

## Dashboard integration

Open the existing dashboard (port 5050). On the NarAI page, click the **v2** button in the chat toolbar. Enter your password once — the token is stored in localStorage.

When v2 is active:
- Messages route to `/api/v2/narai/chat` (Claude Sonnet 4.6 primary)
- Skill selector appears: Auto / Trader / Coder / Writer
- Model, tier, and skill are shown in each response

## Available make targets

```
make dev          — start FastAPI server with hot reload (port 5051)
make test         — run full test suite
make test-fast    — run unit tests only (no embeddings loaded)
make migrate      — port legacy narai_memory.json + activity log → Chroma + SQLite
make seed         — ingest skill packs into RAG collection
make docker-up    — start Redis (+ Postgres with --profile prod)
make hash-password — generate bcrypt hash for your password
make deploy       — railway up --detach
```

## Environment variables

See [.env.example](.env.example) for all variables with cost annotations.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md).
