# NarAI — Build Progress

## Phase 0 — Foundation (MacBook)

### 2026-04-18

**Status: COMPLETE ✓**

All Phase 0 files created under `narai/`.

| Task | Status |
|---|---|
| P0-1: Repo skeleton (narai/, requirements, Makefile, docker-compose, .env.example) | ✓ |
| P0-2: FastAPI app + JWT auth + SQLAlchemy DB models + Alembic | ✓ |
| P0-3: `core/resilience.py` — retry + rate-limit + circuit breaker | ✓ |
| P0-4: Multi-model router via litellm (Claude → GPT-4o → Ollama) | ✓ |
| P0-5: ChromaDB memory layer — remember, recall, forget | ✓ |
| P0-6: RAG pipeline — PDF/MD/CSV/JSON ingest, chunk, embed, query | ✓ |
| P0-7: Response tier classifier — fast vs deep | ✓ |
| P0-8: Skill pack loader — trader/coder/writer .md modules | ✓ |
| P0-9: Encrypted local storage (Fernet/AES-128) | ✓ |
| P0-10: Dashboard v2 toggle — wired to new API, skill selector | ✓ |
| P0-11: Migration script — narai_memory.json + activity → Chroma + SQLite | ✓ |
| P0-12: Tests — router, memory, RAG, skills, tiers, storage | ✓ |
| P0-13: ARCHITECTURE.md + README.md + PROGRESS.md | ✓ |

### Files created
```
narai/
├── __init__.py
├── requirements.txt
├── Makefile
├── docker-compose.yml
├── .env.example
├── README.md
├── ARCHITECTURE.md
├── core/
│   ├── db.py          (ChatLog, MemoryEntry, RagDocument, ApiCallLog)
│   ├── router.py      (litellm multi-model, fallback chain)
│   ├── memory.py      (ChromaDB long-term memory)
│   ├── rag.py         (PDF/MD/CSV/JSON ingestion + semantic query)
│   ├── resilience.py  (tenacity retry + token-bucket rate limiter + pybreaker)
│   ├── tiers.py       (fast/deep classifier)
│   ├── skills.py      (skill pack loader)
│   └── storage.py     (Fernet encrypted local files)
├── api/
│   ├── auth.py        (JWT single-user auth)
│   ├── main.py        (FastAPI app, port 5051)
│   └── routes/
│       ├── chat.py        (POST /chat, POST /chat/stream)
│       ├── memory.py      (memory CRUD + RAG ingest/query)
│       └── skills_route.py
├── skills/
│   ├── trader.md
│   ├── coder.md
│   └── writer.md
├── migrations/
│   ├── env.py
│   └── alembic.ini
├── scripts/
│   └── migrate_legacy.py
└── tests/
    ├── test_router.py
    ├── test_memory.py
    ├── test_rag.py
    ├── test_skills.py
    ├── test_tiers.py
    └── test_storage.py
```
### Dashboard
- `dashboard/index.html` extended with NarAI v2 toggle + skill selector
- v2 routes to `http://localhost:5051/api/v2/narai/chat`
- Existing v1 chat flow unchanged (toggle off = legacy mode)

---

## Phase 1 — Trading Core (MacBook)
**Status: NOT STARTED**

Next: LSTM + transformer forecaster, sentiment pipeline, backtest engine, paper trading, risk manager, dashboard P&L widget.

---

## Phase 2 — Always-on (Mac mini M4)
**Status: WAITING — Mac mini M4 not yet available**
