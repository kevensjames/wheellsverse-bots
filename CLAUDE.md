# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

WheellsVerse Bot Ecosystem — a Python monorepo housing ~70+ autonomous bots, a FastAPI dashboard/API, a next-gen NarAI assistant module, a Money Center revenue tracker, and a static frontend. Bots are Python packages discovered at runtime; the system is orchestrated as one process (`core/api.py` app on port 5050, or `main.py` CLI) rather than as independent services.

## Common commands

Always work inside the venv (`source venv/bin/activate`) before running Python directly.

```bash
# Entry points
./launch.sh                              # interactive CLI menu (main.py)
./launch.sh --run marketing/01_content_generator   # run ONE bot
./launch.sh --category marketing         # run a whole category
./launch.sh --pipeline morning_blast     # run a named pipeline from config.yaml
./launch.sh --schedule                   # start blocking scheduler
./dashboard.sh                           # FastAPI dashboard on :5050
python main.py --check                   # verify .env + bot discovery

# Root test runner (unittest, no pytest needed)
python run_tests.py                      # full suite: import checks + 5 test modules
python run_tests.py --fast               # skip test_api_endpoints (needs running server)
python run_tests.py --module literary_qc # single module

# NarAI v2 (separate FastAPI app on :5051, uses pytest + Makefile)
make -C narai dev                        # uvicorn narai.api.main:app --reload
make -C narai test                       # pytest narai/tests/ -v
make -C narai test-fast                  # unit tests only (no embeddings)
make -C narai migrate                    # port legacy narai_memory.json → Chroma+SQLite
make -C narai seed                       # ingest skill packs into RAG
make -C narai hash-password              # bcrypt hash for NARAI_PASSWORD_HASH

# Money Center (separate Flask dashboard on :7777)
python money_center/cli.py list          # list all revenue-generating assets
python money_center/cli.py status
python money_center/dashboard.py --port 7777
python -m pytest money_center/tests/ -v

# Bug Hunter (static bug scanner over bots/ and core/)
python -m bots.core.bug_hunter scan
python -m bots.core.bug_hunter fix --auto
python -m bots.core.bug_hunter watch

# Marketing autopilot (30-day KDP launch)
python narai/marketing/marketing_autopilot.py run     # run today's tasks
python narai/marketing/marketing_autopilot.py daemon  # 6h loop

# Lint (flake8 with very permissive cosmetic exemptions — see .flake8)
flake8 core bots narai
```

Production server command (used by Dockerfile, Railway, nixpacks): `uvicorn core.api:app --host 0.0.0.0 --port $PORT`.

## Architecture

This is **not** microservices. One process loads every bot as a Python module and exposes them through three parallel surfaces: CLI menu (`main.py`), scheduler (`core/scheduler.py`), and FastAPI (`core/api.py`). All three drive the same `Orchestrator` singleton.

### Bot discovery & lifecycle

`core/orchestrator.py` walks `bots/<category>/<NN_name>/` at startup and imports every `bot.py` it finds. A bot is any class that subclasses `BaseBot` (`core/base_bot.py`) and implements `run(**kwargs)`. Adding a new bot = creating the folder + `bot.py` + `config.json`; no registration step. Dynamic discovery means **do not** hand-maintain an import list.

`BaseBot` is the foundation for almost everything in `bots/`:
- **AI calls via `self.ai(...)` or `self.claude(...)`** — both have 3-attempt exponential-backoff retry (`_retry`), transient network error detection, and automatic token logging to `data/token_usage.json`.
- **OpenAI → Claude fallback** is built into `self.ai()`: quota/auth/rate-limit errors transparently fall back to `_ai_claude()` so bots keep running when OpenAI is unavailable. Don't wrap `self.ai()` with your own fallback — it already does this.
- **`self._get_personality_system()`** is injected automatically if no `system` prompt is provided (NarAI's live personality from `core/personality.py`). Passing `system=` explicitly opts out.
- **`self.http_get/http_post`** — always use these instead of raw `requests`; they enforce `BOT_HTTP_TIMEOUT` (default 30s) and `raise_for_status()`.
- **`self.save_output(...)` / `self.save_json(...)`** — write to `outputs/<category>/<name>/`; pass `topic=` to register a 7-day dedup entry in `data/used_topics.json`. Call `self.topic_is_duplicate(topic)` before generating to skip recent topics.
- **`execute(**kwargs)`** is the public entry point (wraps `run()` with timing, status, bounded error deque). Orchestrator and scheduler call `execute`, never `run` directly.

Every subclass needs `sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))` before `from core.base_bot import BaseBot` — look at `bots/marketing/01_content_generator/bot.py` for the template.

### Pipelines

`core/pipeline.py` + `config.yaml` → chained bot runs where each bot's return dict merges into a shared context passed as kwargs to the next bot. Pipelines live under the top-level `pipelines:` key in `config.yaml` (e.g. `morning_blast`, `full_revenue_blast`, `full_seo_blast`). Pipeline names are referenced by `main.py --pipeline <name>` and by the API.

### Scheduler

`core/scheduler.py` registers bots based on each bot's `config.json` `schedule` field (formats: `@every_5min`, `@daily 09:00`, `@weekly mon 08:00`, `@monthly`). `register_all()` is idempotent (tag-based dedup — see H-02 in AUDIT_REPORT.md). Consecutive failures escalate via Telegram after 3 strikes.

### API (`core/api.py`)

One large FastAPI app (~5000 lines) with all routes inline — the `core/*_router.py` files exist but are mostly unused dead code (L-02). Public paths are hardcoded in `_PUBLIC_PATHS`; everything else requires `API_KEY` header auth when `API_KEY` env var is set. CORS origins come from `CORS_ORIGINS` env var (comma-separated), falls back to `["*"]`. `/api/health` returns degraded status when memory > 90%.

Logging is set up in `_setup_logging()`: rotating `logs/system.log` (10MB × 5) and `logs/errors.log` (5MB × 3). Per-bot loggers write to `logs/<bot_name>.log`.

### Two NarAIs

There are **two distinct NarAI subsystems** — don't confuse them:

1. **Legacy NarAI** — `core/narai_*.py` + `bots/narai/*` — integrated into the main FastAPI at `/api/narai/*`, uses the monorepo's shared infrastructure. Still live.
2. **NarAI v2** — `narai/` as a standalone FastAPI on port 5051 at `/api/v2/narai/*`. Uses **litellm** (Claude→GPT-4o→Ollama fallback), **ChromaDB** vector memory, **sentence-transformers** embeddings, **SQLAlchemy + Alembic** + SQLite, **JWT auth**, **Fernet-encrypted** local storage, and **.md skill packs** (trader/coder/writer). Has its own `requirements.txt`, `Makefile`, `pytest.ini`, tests. See `narai/ARCHITECTURE.md`.

The dashboard toggles between them client-side. Phase roadmap and module boundaries are in `narai/ARCHITECTURE.md`. **Do not merge these** — NarAI v2 is a deliberate greenfield rewrite.

### Money Center (`money_center/`)

A separate revenue-tracking app (Flask, port 7777) with its own CLI, dashboard, `assets.json` registry, and per-asset background processes. Aborts startup if the `/Volumes/Wheellsverse` SSD isn't mounted (`registry.check_ssd()`). Writes auto-backup (`assets.backup.json`) before every mutation. Launched from the main menu via `m` or `--money`.

### Settings & env

`core/settings.py` is the single source of truth for env vars. `settings.validate()` runs at startup in `main.py` and raises `EnvironmentError` listing all missing required vars. Required: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SHOPIFY_STORE`, `SHOPIFY_TOKEN`, `PRINTIFY_API_KEY`. See `.env.example` (15KB, heavily annotated) for the full list.

## Conventions & gotchas

- **Bot naming**: folders are `NN_snake_case` with a two-digit prefix; the prefix is part of the `name` arg passed to `super().__init__()` and the string used in CLI/pipelines (e.g. `marketing/01_content_generator`). Don't rename the prefix — `config.yaml` pipelines reference them by exact string.
- **Deduplication**: any content-generating bot should call `self.topic_is_duplicate(topic)` before generating and pass `topic=` to `save_output()` afterward. Skip window is `DEDUP_DAYS` env var (default 7).
- **Bounded state**: `run_history`, `_errors`, `_rate_limit_store` are all explicitly bounded (deque/pop) to prevent unbounded memory growth. Don't convert them back to plain lists/dicts (see AUDIT_REPORT.md H-01, M-01).
- **`bots_backup/`, `wheelsverse/`, `venv/`** are excluded in `.flake8`; don't run tools over them.
- **Tests use mocks, not real APIs**: `tests/conftest.py` provides `patch_claude(...)` context manager + sample manuscripts. Unit tests should never hit live Anthropic/OpenAI. NarAI v2 tests under `narai/tests/` are pytest + asyncio-auto.
- **Test runner is unittest-based** at the repo root (`run_tests.py`), but NarAI uses pytest. Keep them separate — don't try to unify.
- **Deployment targets**: Docker (GHCR via `.github/workflows/docker-push.yml`), Railway (`railway.json` + `nixpacks.toml`, uses `requirements-server.txt` — a leaner subset), Fly, Render (`deploy/`). The prod entrypoint is `uvicorn core.api:app`, **not** `main.py`.
- **Secrets**: `.env` is gitignored; `.dockerignore` also blocks `.env.*`, `*.pem`, `*.key`, `*_secret*`, `*credentials*` patterns (C-01 fix). Never add these patterns to `COPY`.
- **`core/*_router.py`** files are mostly dead code from a never-completed refactor (L-02). New routes go inline into `core/api.py` alongside the existing ones.
