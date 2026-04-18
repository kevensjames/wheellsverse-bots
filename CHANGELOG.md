# Changelog

All notable changes to the WheellsVerse Bot Ecosystem.

---

## [2026-04-18] — System Audit, Bug Fixes & Upgrades

### Added
- **`bots/core/bug_hunter/`** — New autonomous bug-hunter module with 6 components:
  - `scanner.py` — Static source scanner (bare excepts, hardcoded secrets, mutable defaults, os.system, print-as-logging, unbounded loop appends)
  - `detector.py` — Classifies findings into `Bug` objects with severity/category/fix hints
  - `fixer.py` — Applies safe auto-fixes (bare `except:` → `except Exception as e:`)
  - `reporter.py` — Generates Markdown + JSON reports to `logs/bug_hunter/`
  - `watchdog.py` — Polling file-system watchdog that detects new bugs in changed files
  - `scheduler.py` — Integrates with main `BotScheduler` for daily scans at 03:00
  - `bot.py` + `__main__.py` — `BaseBot` subclass + full argparse CLI
  - `config.json` — Scheduled daily at 03:00, auto_fix disabled by default
- **`AUDIT_REPORT.md`** — Full static audit with 2 CRITICAL, 6 HIGH, 8 MEDIUM, 4 LOW findings
- **`UPGRADES.md`** — 10 implemented upgrades with rationale and file references
- **`narai/marketing/`** — 30-day marketing autopilot for KDP ebook launch (5 files)
- **`GET /api/bug-hunter/status`** — Returns latest bug-hunter scan summary
- **`POST /api/bug-hunter/scan`** — Triggers background scan via FastAPI BackgroundTasks
- **`revive_crashed(max_restarts=3)`** in `core/bot_manager.py` — Auto-restart crashed bots
- **`stop()`** method on `AutopilotEngine` — Graceful loop shutdown with threading.Event
- **`http_get()` / `http_post()`** on `BaseBot` — Default timeout + raise_for_status helpers
- **`self._errors: deque(maxlen=50)`** on `BaseBot` — Bounded error history per bot
- **`_validate_env()`** on `Orchestrator.__init__` — Warns at startup if API keys missing

### Fixed
- **`core/orchestrator.py`** — `self.run_history` changed from unbounded `List` to `deque(maxlen=1000)` (M-01: memory leak)
- **`core/orchestrator.py`** — All `fut.result()` → `fut.result(timeout=300)` with `TimeoutError` handling (H-02: hung futures)
- **`core/scheduler.py`** — Added `_is_registered()` dedup check; `register_all()` is now idempotent (M-02)
- **`core/scheduler.py`** — Added `_consecutive_failures` counter + `_alert_failure()` Telegram alert on 3 failures (H-03)
- **`core/base_bot.py`** — `_retry()` now retries transient network errors + exponential backoff (M-05)
- **`core/base_bot.py`** — `_ai_claude()` and `ai()` token logging use `getattr` fallback for field names (M-03)
- **`core/bot_manager.py`** — `Popen` launch wrapped in `try/finally` to close log_fd on exception (H-04)
- **`core/api.py`** — `_rate_limit_store.pop(client_ip, None)` prevents ghost IP accumulation
- **`core/api.py`** — 10 silent `except: pass` blocks replaced with `logger.warning()` (H-05)
- **`core/api.py`** — Last bare `except:` at revenue fetch replaced with `except Exception as e:` (C-02)
- **`core/emotion_engine.py`** — Added `PRAGMA journal_mode=WAL` to all SQLite connections

### Changed
- **`core/api.py`** — CORS now reads `CORS_ORIGINS` env var; falls back to `["*"]` if unset
- **`core/api.py`** — `/api/health` returns `system.cpu_pct`, `system.mem_pct`, `uptime_human`, `status: degraded` on high memory
- **`core/autopilot.py`** — `while True: ... time.sleep(60)` → `while not _stop_event.is_set(): ... _stop_event.wait(60)` (interruptible sleep + graceful stop)
- **`.dockerignore`** — Added `.env.*`, `*.pem`, `*.key`, `*_secret*`, `*credentials*` patterns

---

## CLI Reference (new commands)

```bash
# Bug Hunter
python -m bots.core.bug_hunter scan         # scan bots/ and core/
python -m bots.core.bug_hunter fix --auto   # apply safe auto-fixes
python -m bots.core.bug_hunter report       # print latest report summary
python -m bots.core.bug_hunter watch        # start real-time watchdog

# Marketing Autopilot
python narai/marketing/marketing_autopilot.py load     # load 59-task schedule
python narai/marketing/marketing_autopilot.py run      # run today's tasks
python narai/marketing/marketing_autopilot.py status   # show all tasks
python narai/marketing/marketing_autopilot.py daemon   # 6h loop daemon
```
