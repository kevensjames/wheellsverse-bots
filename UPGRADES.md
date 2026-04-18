# WheellsVerse Bot Ecosystem — Upgrades

**Implemented:** 2026-04-18  
**Scope:** 10 highest-impact system upgrades across security, reliability, performance, and observability.

---

## U-01 · CORS Lockdown via Environment Variable

**File:** `core/api.py`  
**Impact:** SECURITY — HIGH  
**Change:** `allow_origins=["*"]` replaced with origins read from `CORS_ORIGINS` env var.  
**Usage:** Set `CORS_ORIGINS=https://narai.app,https://dashboard.narai.app` in `.env`.  
Falls back to `["*"]` if env var is unset, preserving existing dev behavior.

---

## U-02 · SQLite WAL Mode in emotion_engine

**File:** `core/emotion_engine.py`  
**Impact:** RELIABILITY — MEDIUM  
**Change:** Added `PRAGMA journal_mode=WAL` to all `sqlite3.connect()` calls.  
WAL mode allows concurrent readers + one writer, preventing "database is locked" errors under multi-threaded bot load.

---

## U-03 · Bounded Error History in BaseBot

**File:** `core/base_bot.py`  
**Impact:** RELIABILITY — MEDIUM  
**Change:** Added `self._errors: Deque[str] = deque(maxlen=50)`. Each failed `execute()` call appends a timestamped error string. `get_status()` now returns `recent_errors` (last 5). Prevents unbounded memory growth on bots that crash repeatedly.

---

## U-04 · .dockerignore Hardening

**File:** `.dockerignore`  
**Impact:** SECURITY — CRITICAL  
**Change:** Added `.env.*`, `*.pem`, `*.key`, `*_secret*`, `*credentials*` patterns. Ensures no secrets can be baked into Docker images even if environment files follow non-standard naming.

---

## U-05 · Auto-restart Crashed Bots in bot_manager

**File:** `core/bot_manager.py`  
**Impact:** RELIABILITY — HIGH  
**Change:** Added `revive_crashed(max_restarts=3)` function. Scans `_procs` for crashed processes, restarts them (up to `max_restarts` times per bot), and logs each revival. Guards against infinite restart storms. Call from health-check cron or admin endpoint.

---

## U-06 · Enhanced `/api/health` Endpoint

**File:** `core/api.py`  
**Impact:** OBSERVABILITY — MEDIUM  
**Change:** `/api/health` now returns `system.cpu_pct`, `system.mem_pct`, `uptime_human`, and sets `status: "degraded"` when memory > 90%. Requires `psutil` (already in requirements).

---

## U-07 · Bug Hunter API Routes

**File:** `core/api.py`  
**Impact:** OBSERVABILITY — MEDIUM  
**Change:** Added two endpoints:
- `GET /api/bug-hunter/status` — returns latest scan summary (JSON)
- `POST /api/bug-hunter/scan` — triggers a background scan  

Routes delegate to the bug_hunter module built in Phase 2.

---

## U-08 · HTTP Helper Methods with Default Timeout in BaseBot

**File:** `core/base_bot.py`  
**Impact:** RELIABILITY — HIGH  
**Change:** Added `http_get(url, **kwargs)` and `http_post(url, **kwargs)` methods. Both default to `BOT_HTTP_TIMEOUT=30s` (env-configurable) and call `raise_for_status()`. Bot subclasses should use these instead of raw `requests.*` calls to ensure every outbound HTTP call has a timeout.

---

## U-09 · Orchestrator Startup Env Validation

**File:** `core/orchestrator.py`  
**Impact:** RELIABILITY — LOW  
**Change:** Added `_validate_env()` called in `__init__`. Logs a `WARNING` at startup if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is missing, so deployment failures surface immediately in logs instead of silently at first bot run.

---

## U-10 · Graceful Shutdown for AutopilotEngine Loop

**File:** `core/autopilot.py`  
**Impact:** RELIABILITY — MEDIUM  
**Change:** Added `self._stop_event = threading.Event()` to `__init__`. Replaced `while True: ... time.sleep(60)` with `while not self._stop_event.is_set(): ... self._stop_event.wait(60)`. Added `stop()` method that sets the event and joins the thread (timeout=5s). The loop now terminates cleanly on server shutdown instead of being abandoned as an unkillable daemon thread.

---

## Summary

| # | File | Category | Severity |
|---|------|----------|----------|
| U-01 | `core/api.py` | security | HIGH |
| U-02 | `core/emotion_engine.py` | reliability | MEDIUM |
| U-03 | `core/base_bot.py` | reliability | MEDIUM |
| U-04 | `.dockerignore` | security | CRITICAL |
| U-05 | `core/bot_manager.py` | reliability | HIGH |
| U-06 | `core/api.py` | observability | MEDIUM |
| U-07 | `core/api.py` | observability | MEDIUM |
| U-08 | `core/base_bot.py` | reliability | HIGH |
| U-09 | `core/orchestrator.py` | reliability | LOW |
| U-10 | `core/autopilot.py` | reliability | MEDIUM |
