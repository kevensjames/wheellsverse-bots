# NarAI — Architecture

Owner: J.K. Blaze (WheellsVerse)
Last updated: 2026-04-18
Phase: 0 (Foundation)

---

## Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Existing codebase; best ML/AI ecosystem |
| API framework | FastAPI | Already in use in monorepo; async-native; auto OpenAPI |
| Model router | litellm | Single interface for Claude, GPT-4o, Ollama; auto-fallback; no vendor lock-in |
| Primary model | claude-sonnet-4-6 | Best reasoning quality; owner has API key; ~$3/M tokens |
| Fast model | claude-haiku-4-5 | 10x cheaper than Sonnet; sufficient for quick queries |
| Local LLM | Ollama + Llama 3.2 | Runs on Apple Silicon MPS; zero API cost; privacy |
| Vector memory | ChromaDB (local) | Embedded, no server needed; persistent to disk; cosine similarity |
| Embeddings | all-MiniLM-L6-v2 | Local sentence-transformers; Apple Silicon friendly; free |
| RAG text splitting | LangChain TextSplitters | Mature, battle-tested; rest of LangChain excluded to keep deps minimal |
| DB (dev) | SQLite + aiosqlite | Zero-setup; sufficient for single-user Phase 0 |
| DB (prod) | PostgreSQL 16 | Railway-native; handles concurrent writes in Phase 1+ |
| Auth | JWT (python-jose) + bcrypt | Single-user; no third-party auth service needed |
| Encryption | Fernet (cryptography) | AES-128-CBC + HMAC-SHA256; key from env; standard library |
| Resilience | tenacity + pybreaker | Retry with exponential backoff; circuit breaker per service |
| TTS | piper-tts (Phase 2) | Local, offline, Apple Silicon; added in Phase 2 |
| STT | faster-whisper (Phase 2) | Local, Apple Silicon; added in Phase 2 |

## Module boundaries

```
wheellsverse_bots/
├── narai/          ← NEW: production NarAI module (this doc)
│   ├── core/       ← router, memory, RAG, resilience, tiers, skills, storage, db
│   ├── api/        ← FastAPI app on port 5051, JWT auth, /api/v2/narai/*
│   ├── trading/    ← Phase 1: forecaster, backtest, risk, paper trading
│   ├── voice/      ← Phase 2: STT, TTS, wake word
│   ├── integrations/ ← Phase 2/3: Telegram, Discord, Gmail, Notion
│   ├── skills/     ← .md skill packs: trader, coder, writer
│   ├── migrations/ ← Alembic DB migrations
│   └── tests/      ← pytest suite (required for all trading/risk modules)
├── bots/narai/     ← LEGACY: existing NarAI bot (keep running until Phase 1 complete)
├── core/           ← Shared monorepo infra (existing, untouched)
└── dashboard/      ← Existing frontend (extended with v2 toggle)
```

## API surface

All NarAI v2 routes are prefixed `/api/v2/narai/`.
The app runs standalone on port 5051 (NARAI_PORT) or can be mounted into the existing `core/api.py`.

```
POST /api/v2/narai/auth/login        — get JWT token
GET  /api/v2/narai/health            — health + circuit breaker status

POST /api/v2/narai/chat              — main chat endpoint
POST /api/v2/narai/chat/stream       — SSE streaming chat

POST /api/v2/narai/memory            — store a memory
POST /api/v2/narai/memory/recall     — semantic search
DELETE /api/v2/narai/memory/{key}    — forget a memory
GET  /api/v2/narai/memory/count      — memory + RAG doc count

POST /api/v2/narai/rag/ingest/text   — ingest raw text
POST /api/v2/narai/rag/ingest/file   — ingest PDF/MD/CSV/JSON file
POST /api/v2/narai/rag/query         — semantic search over docs

GET  /api/v2/narai/skills            — list available skill packs
POST /api/v2/narai/skills/activate/{name}  — activate a skill
POST /api/v2/narai/skills/deactivate       — deactivate
```

## Data flow (chat request)

```
User message
  → tier classifier (fast | deep)
  → parallel: ChromaDB recall(query, n=4) + RAG query(query, n=3)
  → build_system_prompt(skill + base + memory_ctx + rag_ctx)
  → litellm router → Claude Sonnet (primary) → GPT-4o (fallback) → Ollama (fallback)
  → response stored in SQLite chat_logs
  → return {reply, model, tier, tokens, skill}
```

## Phase roadmap

| Phase | Target machine | Features |
|---|---|---|
| 0 — Foundation | MacBook | Router, memory, RAG, tiers, skills, encrypted storage, dark UI shell |
| 1 — Trading core | MacBook | LSTM forecaster, sentiment, backtest, paper trading, risk manager, dashboard widgets |
| 2 — Always-on | Mac mini M4 | Wake word, streaming TTS, voice clone, menubar app, Telegram/Discord/Gmail/Notion/Plaid, daily briefing |
| 3 — Advanced + monetization | Mac mini M4 | Agent mode, fine-tuning, options flow, on-chain, auto-execution, alt-data, browser extension, Stripe tiers, signal marketplace, public API, white-label |

## Ambiguous choices log

- **litellm over custom router**: simpler; handles provider API differences, retries, and model aliases. Custom router adds complexity with no benefit at Phase 0 scale.
- **ChromaDB over Qdrant/Pinecone**: embedded mode, zero infrastructure, persistent on disk. Qdrant is better for multi-user scale — revisit at Phase 3 if needed.
- **SQLite in dev**: single-user, local-first, zero ops overhead. Postgres is one env var change away when deploying to Railway.
- **all-MiniLM-L6-v2 embeddings**: 80MB, runs on CPU, 384-dim vectors, good enough for personal knowledge base. OpenAI embeddings are better but cost money and send data off-device.
- **Skill packs as .md files**: hot-reloadable, version-controllable, human-editable without code changes. JSON or Python would add unnecessary complexity.
