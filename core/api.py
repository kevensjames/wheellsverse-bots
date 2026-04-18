#!/usr/bin/env python3
"""
core/api.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Production API — FastAPI backend.
Serves the web dashboard + REST endpoints for all bot operations.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

# ─── Structured log rotation ──────────────────────────────────────────────────

LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

def _setup_logging():
    """Configure rotating file handlers for persistent structured logs."""
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # System-wide rotating log (10 MB × 5 backups)
    sys_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "system.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    sys_handler.setFormatter(fmt)
    root_logger.addHandler(sys_handler)

    # Errors-only log for quick triage
    err_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)
    root_logger.addHandler(err_handler)

    # Console (WARNING+ only so uvicorn stays clean)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(fmt)
    root_logger.addHandler(console_handler)

_setup_logging()

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("api")

# ─── API Key Auth ─────────────────────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "").strip()

# Public paths that never require auth
_PUBLIC_PATHS = {"/", "/landing", "/api/health", "/api/overview", "/api/lead", "/favicon.ico",
                 # Legal pages — publicly accessible, no auth required
                 "/terms", "/terms.html", "/privacy", "/privacy.html", "/disclaimer", "/store",
                 # Public site pages
                 "/login", "/signup", "/pricing", "/narai",
                 # NarAI user API (auth handled per-endpoint via Bearer token)
                 "/api/narai/chat", "/api/narai/conversations", "/api/narai/profile",
                 "/api/narai/memory",
                 "/api/auth/login", "/api/telegram/webhook", "/api/whatsapp/webhook",
                 "/api/stripe/webhook",
                 "/api/wordpress/oauth-callback", "/api/wordpress/oauth-url",
                 "/api/canva/oauth-callback", "/api/canva/oauth-url",
                 "/api/nexora/status", "/api/nexora/recruit", "/api/nexora/growth",
                 # NarAI autopilot — dashboard-only, protected by same-origin
                 "/api/narai-autopilot/status", "/api/narai-autopilot/start",
                 "/api/narai-autopilot/stop", "/api/narai-autopilot/log",
                 "/api/narai-autopilot/queue", "/api/narai-autopilot/reels",
                 # QC + Factory dashboard endpoints
                 "/api/qc/stats", "/api/qc/results", "/api/qc/review",
                 "/api/factory/alltime", "/api/factory/status", "/api/factory/reset",
                 "/api/narai/memory/stats", "/api/narai/memory/search",
                 "/api/narai/memory/context",
                 # NEXORA platform — auth + public creator endpoints are their own auth
                 "/api/nx/register", "/api/nx/login", "/api/nx/logout", "/api/nx/stripe-webhook",
                 "/api/nx/fan/register", "/api/nx/fan/login", "/api/nx/fan/logout"}

# Shopify dashboard endpoints — all served by the same-origin dashboard, no extra auth
for _p in [
    "/api/shopify/status", "/api/shopify/products", "/api/shopify/orders",
    "/api/shopify/customers", "/api/shopify/webhooks/status", "/api/shopify/webhook",
    "/api/shopify/discount", "/api/shopify/register-webhooks",
    "/api/shopify/oauth-url", "/api/shopify/callback",
    "/api/shopify/publish-narai-product",
    # Agent Workforce
    "/api/shopify/agents/start", "/api/shopify/agents/stop",
    "/api/shopify/agents/status", "/api/shopify/agents/dispatch",
    "/api/shopify/agents/upgrade-now", "/api/shopify/agents/logs",
    # Media Engine
    "/api/shopify/media/generate-batch",
    # Store Intelligence
    "/api/shopify/intelligence/analyze", "/api/shopify/intelligence/opportunities",
    "/api/shopify/intelligence/autopilot", "/api/shopify/intelligence/status",
]:
    _PUBLIC_PATHS.add(_p)

async def verify_api_key(request: Request):
    """
    Optional API key guard.
    Set API_KEY in .env to enable. If not set, all requests pass through.
    Dashboard always passes (it's served from the same origin with the key embedded).
    """
    if not _API_KEY:
        return  # Auth disabled

    path = request.url.path
    # NEXORA platform uses its own Bearer token auth — never block these with API key
    if path in _PUBLIC_PATHS or not path.startswith("/api/") or path.startswith("/api/nx/"):
        return  # Public route

    key = (
        request.headers.get("X-API-Key")
        or request.headers.get("x-api-key")
        or request.query_params.get("api_key")
    )
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ─── Global state ─────────────────────────────────────────────────────────────

_orchestrator = None
_pipeline_engine = None
_scheduler = None
_command_interpreter = None
_log_buffer: deque = deque(maxlen=500)
_server_start = time.time()


def _add_log(msg: str, level: str = "INFO"):
    _log_buffer.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": msg,
        "ts": time.time(),
    })


def _get_orch():
    global _orchestrator
    if _orchestrator is None:
        from core.orchestrator import get_orchestrator
        _orchestrator = get_orchestrator()
    return _orchestrator


def _get_pipeline():
    global _pipeline_engine
    if _pipeline_engine is None:
        from core.pipeline import PipelineEngine
        _pipeline_engine = PipelineEngine(_get_orch())
    return _pipeline_engine


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from core.scheduler import BotScheduler
        _scheduler = BotScheduler(_get_orch())
        _scheduler.register_all()
    return _scheduler


def _get_cmd():
    global _command_interpreter
    if _command_interpreter is None:
        from core.command import CommandInterpreter
        _command_interpreter = CommandInterpreter()
    return _command_interpreter


# ─── FastAPI App ───────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(application: FastAPI):
    # ── FAST startup: yield immediately so Railway health check passes ────────
    # All heavy init (loading 70 bots, schedulers, engines) runs in a background
    # thread AFTER uvicorn is already accepting requests.
    import threading as _ls_th
    import time as _ls_time

    # Job queue MUST start on uvicorn's event loop — not a new one in a thread.
    # Creating a new loop and closing it kills the workers (RuntimeError: loop closed).
    try:
        from core.job_queue import get_queue
        await get_queue().start()
        _add_log("Async job queue started", "INFO")
    except Exception as _jq_err:
        _add_log(f"Job queue start failed: {_jq_err}", "WARNING")

    def _lifespan_bg():
        _ls_time.sleep(3)  # brief pause, then start loading
        _add_log("Background startup: loading bots and schedulers...", "INFO")

        # Auto-start scheduler so bots run on their cron schedules
        try:
            sched = _get_scheduler()
            sched.start(blocking=False)
            _add_log("Scheduler auto-started on server boot", "INFO")
        except Exception as _e:
            _add_log(f"Scheduler auto-start failed: {_e}", "WARNING")

        _add_log("Auto-post schedules disabled — manual posting only", "INFO")

        # NarAI hourly diagnostic
        try:
            import schedule as _schedN
            def _narai_hourly():
                try:
                    narai = _get_narai()
                    if narai:
                        narai.execute(action="diagnostic")
                        _add_log("NarAI: hourly diagnostic complete", "INFO")
                except Exception as _eN:
                    _add_log(f"NarAI hourly diagnostic failed: {_eN}", "WARNING")
            _schedN.every().hour.do(_narai_hourly)
            _ls_th.Thread(target=_narai_hourly, daemon=True).start()
            _add_log("NarAI: hourly diagnostic scheduled", "INFO")
        except Exception as _eN:
            _add_log(f"NarAI schedule setup failed: {_eN}", "WARNING")

        # NarAI Social Blast: daily 09:15
        try:
            import schedule as _schedNB
            def _narai_blast():
                try:
                    narai = _get_narai()
                    if narai:
                        result = narai.execute(action="social_blast")
                        _add_log(f"NarAI social blast complete: {list(result.get('results',{}).keys())}", "INFO")
                except Exception as _eNB:
                    _add_log(f"NarAI social blast failed: {_eNB}", "WARNING")
            _schedNB.every().day.at("09:15").do(lambda: _ls_th.Thread(target=_narai_blast, daemon=True).start())
            _add_log("NarAI social blast scheduled: daily 09:15", "INFO")
        except Exception as _e:
            _add_log(f"NarAI blast schedule failed: {_e}", "WARNING")

        # NarAI Inbox Handler: every 30 min
        try:
            import schedule as _schedNI
            def _narai_inbox():
                try:
                    narai = _get_narai()
                    if narai:
                        result = narai.execute(action="handle_inbox", platform="all")
                        replied = result.get("replied", 0)
                        if replied:
                            _add_log(f"NarAI replied to {replied} comments/messages", "INFO")
                except Exception as _eNI:
                    _add_log(f"NarAI inbox failed: {_eNI}", "WARNING")
            _schedNI.every(30).minutes.do(lambda: _ls_th.Thread(target=_narai_inbox, daemon=True).start())
            _add_log("NarAI inbox handler scheduled: every 30min", "INFO")
        except Exception as _e:
            _add_log(f"NarAI inbox schedule failed: {_e}", "WARNING")

        # Video Creator: daily at 11:00
        try:
            import schedule as _schedV
            def _run_video_creator():
                try:
                    orch = _get_orch()
                    result = orch.run_bot("specialized/90_video_creator")
                    _add_log(f"Video creator complete: {result.get('status', 'done')}", "INFO")
                except Exception as _eV:
                    _add_log(f"Video creator failed: {_eV}", "ERROR")
            _schedV.every().day.at("11:00").do(lambda: _ls_th.Thread(target=_run_video_creator, daemon=True).start())
            _add_log("Video creator scheduled: daily 11:00", "INFO")
        except Exception as _e:
            _add_log(f"Video creator schedule failed: {_e}", "WARNING")

        # Revenue Pipeline: daily at 08:30
        try:
            import schedule as _schedR
            def _run_revenue_pipeline():
                try:
                    pe = _get_pipeline()
                    result = pe.run_pipeline("full_revenue_blast")
                    published = result.get("completed", 0)
                    _add_log(f"Revenue pipeline complete — {published} bots ran", "INFO")
                    try:
                        from core.telegram import notify
                        notify(f"💰 <b>Revenue Pipeline Complete</b>\n📊 Bots ran: {published}\n⏰ {__import__('datetime').datetime.now().strftime('%H:%M')}")
                    except Exception:
                        pass
                except Exception as _eR:
                    _add_log(f"Revenue pipeline failed: {_eR}", "ERROR")
            _schedR.every().day.at("08:30").do(lambda: _ls_th.Thread(target=_run_revenue_pipeline, daemon=True).start())
            _add_log("Revenue pipeline scheduled: daily 08:30", "INFO")
        except Exception as _e:
            _add_log(f"Revenue pipeline schedule failed: {_e}", "WARNING")

        # SEO Daily Pipeline: 06:30
        try:
            import schedule as _schedS
            def _run_seo_pipeline():
                try:
                    pe = _get_pipeline()
                    pe.run_pipeline("seo_daily")
                    _add_log("SEO daily pipeline complete", "INFO")
                except Exception as _eS:
                    _add_log(f"SEO pipeline failed: {_eS}", "ERROR")
            _schedS.every().day.at("06:30").do(lambda: _ls_th.Thread(target=_run_seo_pipeline, daemon=True).start())
            _add_log("SEO daily pipeline scheduled: 06:30", "INFO")
        except Exception as _e:
            _add_log(f"SEO pipeline schedule failed: {_e}", "WARNING")

        # Social Domination Pipeline: 3× per day
        try:
            import schedule as _schedSD
            def _run_social_pipeline():
                try:
                    pe = _get_pipeline()
                    pe.run_pipeline("social_domination")
                    _add_log("Social domination pipeline complete", "INFO")
                except Exception as _eSD:
                    _add_log(f"Social pipeline failed: {_eSD}", "ERROR")
            _schedSD.every().day.at("09:00").do(lambda: _ls_th.Thread(target=_run_social_pipeline, daemon=True).start())
            _schedSD.every().day.at("14:00").do(lambda: _ls_th.Thread(target=_run_social_pipeline, daemon=True).start())
            _schedSD.every().day.at("19:00").do(lambda: _ls_th.Thread(target=_run_social_pipeline, daemon=True).start())
            _add_log("Social domination pipeline scheduled: 09:00, 14:00, 19:00", "INFO")
        except Exception as _e:
            _add_log(f"Social pipeline schedule failed: {_e}", "WARNING")

        # Affiliate Revenue Pipeline: 3× per day
        try:
            import schedule as _schedAR
            def _run_affiliate_pipeline():
                try:
                    pe = _get_pipeline()
                    pe.run_pipeline("affiliate_revenue")
                    _add_log("Affiliate revenue pipeline complete", "INFO")
                except Exception as _eAR:
                    _add_log(f"Affiliate pipeline failed: {_eAR}", "ERROR")
            _schedAR.every().day.at("10:00").do(lambda: _ls_th.Thread(target=_run_affiliate_pipeline, daemon=True).start())
            _schedAR.every().day.at("15:00").do(lambda: _ls_th.Thread(target=_run_affiliate_pipeline, daemon=True).start())
            _schedAR.every().day.at("20:00").do(lambda: _ls_th.Thread(target=_run_affiliate_pipeline, daemon=True).start())
            _add_log("Affiliate revenue pipeline scheduled: 10:00, 15:00, 20:00", "INFO")
        except Exception as _e:
            _add_log(f"Affiliate pipeline schedule failed: {_e}", "WARNING")

        # Telegram daily summary: 07:00
        try:
            import schedule as _sched4
            import asyncio as _asyncio2
            def _telegram_daily():
                try:
                    loop = _asyncio2.new_event_loop()
                    loop.run_until_complete(telegram_daily_alert())
                    loop.close()
                except Exception as _e2:
                    _add_log(f"Telegram daily alert failed: {_e2}", "ERROR")
            _sched4.every().day.at("07:00").do(_telegram_daily)
            _add_log("Telegram daily summary scheduled: 07:00 daily", "INFO")
        except Exception as _e:
            _add_log(f"Telegram schedule setup failed: {_e}", "WARNING")

        # WhatsApp scheduled messages — check every minute
        try:
            import schedule as _schedWA
            def _wa_scheduler_tick():
                try:
                    from core.whatsapp import get_client
                    wa = get_client()
                    if not wa.is_configured():
                        return
                    now = datetime.now()
                    items = _load_wa_schedule()
                    changed = False
                    for item in items:
                        if item.get("status") != "pending":
                            continue
                        try:
                            send_at = datetime.fromisoformat(item["send_at"])
                        except Exception:
                            continue
                        if now >= send_at:
                            message = item["message"]
                            if item.get("ai_compose"):
                                try:
                                    narai = _get_narai()
                                    if narai:
                                        label = item.get("label", "a friendly message")
                                        result = narai.ai(
                                            f"Write {label} (2-3 sentences, natural, no quotes).",
                                            max_tokens=100
                                        )
                                        if result:
                                            message = result
                                except Exception:
                                    pass
                            ok = wa.send_message(to=item["to"], text=message)
                            if ok:
                                _add_log(f"WhatsApp scheduled sent to {item['to']}: {message[:60]}", "INFO")
                                item["last_sent"] = now.isoformat()
                                if item["repeat"] == "daily":
                                    from datetime import timedelta
                                    next_dt = send_at + timedelta(days=1)
                                    item["send_at"] = next_dt.isoformat()
                                elif item["repeat"] == "weekly":
                                    from datetime import timedelta
                                    next_dt = send_at + timedelta(weeks=1)
                                    item["send_at"] = next_dt.isoformat()
                                else:
                                    item["status"] = "sent"
                                changed = True
                            else:
                                _add_log(f"WhatsApp scheduled FAILED to {item['to']}", "WARNING")
                    if changed:
                        _save_wa_schedule(items)
                except Exception as e:
                    logger.warning("WA scheduler tick error: %s", e)
            _schedWA.every(1).minutes.do(lambda: _ls_th.Thread(target=_wa_scheduler_tick, daemon=True).start())
            _add_log("WhatsApp message scheduler started: checks every minute", "INFO")
        except Exception as _e:
            _add_log(f"WhatsApp scheduler setup failed: {_e}", "WARNING")

        # ── NarAI Autopilot: Market Intel every Monday 01:00 ──────────────────
        try:
            import schedule as _schedMI
            def _weekly_market_intel():
                try:
                    _add_log("🔭 Weekly Market Intel scan starting (Monday 01:00)…", "INFO")
                    from core.market_intelligence import start_scan_background
                    session_id = start_scan_background()
                    _add_log(f"Market Intel scan started: {session_id}", "INFO")
                    # After scan completes, trigger autopilot if not already running
                    import threading as _mi_wait_th
                    def _wait_for_scan_then_autopilot():
                        import time as _t
                        from core.market_intelligence import get_status as _mi_status
                        max_wait = 3600  # 1 hour max
                        waited = 0
                        while waited < max_wait:
                            _t.sleep(30)
                            waited += 30
                            if not _mi_status().get("running"):
                                _add_log("Market Intel scan complete — saving to NarAI memory", "INFO")
                                break
                        # Save all intel to NarAI tiered memory
                        try:
                            from core.market_intelligence import _mi_load
                            from core.narai_memory_manager import save_market_intel
                            mi = _mi_load()
                            for plat, data in mi.get("platforms", {}).items():
                                if data:
                                    save_market_intel(plat, data)
                            _add_log(f"Market Intel saved to NarAI memory: {len(mi.get('platforms',{}))} platforms", "INFO")
                        except Exception as _em:
                            _add_log(f"Memory save after scan error: {_em}", "WARNING")
                    _mi_wait_th.Thread(target=_wait_for_scan_then_autopilot, daemon=True).start()
                except Exception as _eMI:
                    _add_log(f"Weekly market intel failed: {_eMI}", "ERROR")
            _schedMI.every().monday.at("01:00").do(
                lambda: __import__('threading').Thread(target=_weekly_market_intel, daemon=True).start()
            )
            _add_log("Market Intel scheduled: every Monday at 01:00", "INFO")
        except Exception as _e:
            _add_log(f"Market Intel schedule failed: {_e}", "WARNING")

        # ── NarAI Autopilot: Daily creation session at 01:30 ─────────────────
        try:
            import schedule as _schedAP
            def _daily_autopilot():
                try:
                    from core.narai_autopilot import start_autopilot_background, get_ap_status
                    status = get_ap_status()
                    if status.get("running"):
                        _add_log("Autopilot already running — skipping 01:30 trigger", "WARNING")
                        return
                    session_id = start_autopilot_background()
                    _add_log(f"🤖 NarAI Autopilot daily session started: {session_id}", "INFO")
                    try:
                        from core.narai_scheduler import mark_ran
                        mark_ran("narai_autopilot", "running")
                    except Exception:
                        pass
                    try:
                        from core.telegram import notify
                        notify("🤖 <b>NarAI Autopilot Started</b>\nDaily creation session beginning — social posts, 2 products per platform + Instagram & Facebook promotion incoming…")
                    except Exception:
                        pass
                except Exception as _eAP:
                    _add_log(f"Daily autopilot trigger failed: {_eAP}", "ERROR")
            _schedAP.every().day.at("01:30").do(
                lambda: __import__('threading').Thread(target=_daily_autopilot, daemon=True).start()
            )
            _add_log("NarAI Autopilot scheduled: daily at 01:30", "INFO")
        except Exception as _e:
            _add_log(f"Autopilot schedule failed: {_e}", "WARNING")

        # ── NarAI Daily Reels: 3× per day (Instagram + Facebook) ─────────────
        # Morning  10:00 — Power of AI (inspiring/cinematic)
        # Afternoon 15:00 — AI Trying to Be Human (comedy/cartoon)
        # Evening  20:00 — AI in Real Life Viral (punchy/cinematic)
        try:
            import schedule as _schedReel
            def _make_reel_job(slot_name):
                def _run():
                    try:
                        from core.narai_autopilot import start_reels_background
                        sid = start_reels_background(slot_name)
                        _add_log(f"🎬 Daily Reels [{slot_name}] started: {sid}", "INFO")
                        try:
                            from core.telegram import notify
                            slot_labels = {
                                "morning": "🌅 Power of AI",
                                "afternoon": "😂 AI Trying to Be Human",
                                "evening": "🔥 AI in Real Life Viral",
                            }
                            notify(f"🎬 <b>Daily Reel Starting</b>\n{slot_labels.get(slot_name, slot_name)}\nPosting to Instagram + Facebook…")
                        except Exception:
                            pass
                    except Exception as _eR:
                        _add_log(f"Daily Reels [{slot_name}] failed: {_eR}", "ERROR")
                return _run
            _schedReel.every().day.at("10:00").do(lambda: __import__('threading').Thread(target=_make_reel_job("morning"), daemon=True).start())
            _schedReel.every().day.at("15:00").do(lambda: __import__('threading').Thread(target=_make_reel_job("afternoon"), daemon=True).start())
            _schedReel.every().day.at("20:00").do(lambda: __import__('threading').Thread(target=_make_reel_job("evening"), daemon=True).start())
            _add_log("🎬 Daily Reels scheduled: 10:00 (AI Power), 15:00 (AI Comedy), 20:00 (AI Viral) → Instagram + Facebook", "INFO")
        except Exception as _e:
            _add_log(f"Daily Reels schedule failed: {_e}", "WARNING")

        _add_log("All background startup tasks complete", "INFO")

        # ── Master schedule runner — calls run_pending() every 30 seconds ────
        # All schedule jobs registered above (NarAI autopilot, reels, blast,
        # inbox, pipelines, market intel, WhatsApp, Telegram) share the same
        # global `schedule` module. This single loop drives ALL of them.
        try:
            import schedule as _master_sched
            import time as _master_time

            def _master_schedule_loop():
                _add_log("🕐 Master schedule loop started — all NarAI tasks now active", "INFO")
                while True:
                    try:
                        _master_sched.run_pending()
                    except Exception as _loop_err:
                        _add_log(f"Schedule loop error: {_loop_err}", "WARNING")
                    _master_time.sleep(30)

            _ls_th.Thread(
                target=_master_schedule_loop,
                daemon=True,
                name="narai-master-scheduler",
            ).start()
            _add_log("Master schedule loop running (30s tick)", "INFO")
        except Exception as _e:
            _add_log(f"Master schedule loop failed to start: {_e}", "ERROR")

    # Launch background init — DO NOT block here
    _ls_th.Thread(target=_lifespan_bg, daemon=True, name="lifespan-bg").start()
    _add_log("WheellsVerse API started — background init running", "INFO")

    yield
    # Shutdown — must not raise; any exception here causes "Application shutdown failed"
    try:
        from core.job_queue import get_queue
        await get_queue().stop()
    except Exception as _stop_err:
        _add_log(f"JobQueue stop error (non-fatal): {_stop_err}", "WARNING")
    if _scheduler:
        try:
            _scheduler.stop()
        except Exception:
            pass

app = FastAPI(
    title="WheellsVerse Bot Ecosystem",
    version="2.0.0",
    description="70 Autonomous AI Bots — Production Control API",
    lifespan=_lifespan,
)

_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-NarAI-Text", "X-NarAI-Mood", "X-NarAI-Emoji", "X-NarAI-Energy",
                    "Content-Length", "Content-Type"],
)


# ─── Rate Limiting ─────────────────────────────────────────────────────────
from collections import defaultdict
import time as _time

_rate_limit_store: dict = defaultdict(list)
_RATE_LIMIT_REQUESTS = 100   # max requests
_RATE_LIMIT_WINDOW   = 60    # per 60 seconds

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple in-memory rate limiter per IP."""
    # Skip rate limiting for static files and health
    if request.url.path in ("/api/health", "/") or not request.url.path.startswith("/api/"):
        return await call_next(request)

    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    now = _time.time()
    window_start = now - _RATE_LIMIT_WINDOW

    # Clean old entries; remove IP entirely when empty to prevent unbounded growth
    hits = [t for t in _rate_limit_store[client_ip] if t > window_start]
    if hits:
        _rate_limit_store[client_ip] = hits
    else:
        _rate_limit_store.pop(client_ip, None)
        hits = []

    if len(hits) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse({"error": "Rate limit exceeded. Try again later."}, status_code=429)

    _rate_limit_store[client_ip].append(now)
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses and prevent CDN/browser caching."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Prevent Fastly/CDN from caching API responses (especially 404s)
    if request.url.path.startswith("/api/") or request.url.path in ("/", "/landing"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Surrogate-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Apply optional API key guard to all /api/ routes except public ones."""
    if _API_KEY:
        path = request.url.path
        _PUBLIC_PREFIXES = ("/api/nx/", "/api/qc/", "/api/factory/", "/api/narai-autopilot/",
                             "/api/shopify-autopilot/", "/api/shopify/agents/",
                             "/api/shopify/media/", "/api/shopify/intelligence/",
                             "/api/shopify/", "/api/narai/schedules", "/api/sa/",
                             "/api/narai/run", "/api/narai/revenue", "/api/narai/status")
        if path.startswith("/api/") and not any(path.startswith(p) for p in _PUBLIC_PREFIXES) and path not in _PUBLIC_PATHS:
            key = (
                request.headers.get("X-API-Key")
                or request.headers.get("x-api-key")
                or request.query_params.get("api_key")
            )
            if key != _API_KEY:
                return JSONResponse(
                    {"error": "Unauthorized", "hint": "Set X-API-Key header"},
                    status_code=401,
                )
    return await call_next(request)


# ─── Pydantic models ──────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    command: str

class BotRunRequest(BaseModel):
    kwargs: Dict[str, Any] = {}

class SettingUpdate(BaseModel):
    key: str
    value: str


# ─── Dashboard HTML ───────────────────────────────────────────────────────────

@app.get("/landing", response_class=HTMLResponse)
async def serve_landing():
    """Public landing page — AI + Finance signals capture."""
    lp_path = ROOT / "frontend" / "landing_page.html"
    if not lp_path.exists():
        return HTMLResponse(
            "<h1>Landing page not found. Expected: frontend/landing_page.html</h1>",
            status_code=500,
        )
    return HTMLResponse(lp_path.read_text(encoding="utf-8"))


# ─── Frontend helpers ─────────────────────────────────────────────────────────

_SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
_SUPABASE_ANON = os.getenv("SUPABASE_ANON_KEY", "")


def _serve_frontend(filename: str, cache: bool = True) -> HTMLResponse:
    """Read and serve an HTML file from the frontend/ directory.
    Injects Supabase credentials into %%SUPABASE_URL%% / %%SUPABASE_ANON_KEY%% placeholders.
    """
    path = ROOT / "frontend" / filename
    if not path.exists():
        return HTMLResponse(f"<h1>{filename} not found</h1>", status_code=404)
    html = path.read_text(encoding="utf-8")
    # Inject Supabase public keys (safe — anon key is meant to be public)
    html = html.replace("'%%SUPABASE_URL%%'", f"'{_SUPABASE_URL}'")
    html = html.replace("'%%SUPABASE_ANON_KEY%%'", f"'{_SUPABASE_ANON}'")
    headers = {"Cache-Control": "no-store, no-cache"} if not cache else {}
    return HTMLResponse(html, headers=headers)


@app.get("/terms", response_class=HTMLResponse)
@app.get("/terms.html", response_class=HTMLResponse)
async def serve_terms():
    """Terms of Use — publicly accessible."""
    return _serve_frontend("terms.html")


@app.get("/privacy", response_class=HTMLResponse)
@app.get("/privacy.html", response_class=HTMLResponse)
async def serve_privacy():
    """Privacy Policy — publicly accessible."""
    return _serve_frontend("privacy.html")


@app.get("/disclaimer", response_class=HTMLResponse)
async def serve_disclaimer():
    """Disclaimer — publicly accessible."""
    return _serve_frontend("disclaimer.html")


@app.get("/store", response_class=HTMLResponse)
async def serve_store():
    return _serve_frontend("store/index.html")


# ─── Public Site Pages ────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    return _serve_frontend("login.html", cache=False)


@app.get("/signup", response_class=HTMLResponse)
async def serve_signup():
    return _serve_frontend("signup.html", cache=False)


@app.get("/pricing", response_class=HTMLResponse)
async def serve_pricing():
    return _serve_frontend("pricing.html")


@app.get("/narai", response_class=HTMLResponse)
async def serve_narai_landing():
    return _serve_frontend("narai_landing.html")


@app.get("/chat", response_class=HTMLResponse)
async def serve_chat():
    return _serve_frontend("chat.html", cache=False)


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_user_dashboard():
    return _serve_frontend("dashboard.html", cache=False)


@app.get("/nexora", response_class=HTMLResponse)
async def serve_nexora():
    return _serve_frontend("nexora/index.html")


@app.get("/blog", response_class=HTMLResponse)
async def serve_blog():
    return _serve_frontend("blog/index.html")


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def serve_blog_post(slug: str):
    """Serve individual blog post HTML files."""
    # Accept both with and without .html extension
    filename = slug if slug.endswith(".html") else f"{slug}.html"
    path = ROOT / "frontend" / "blog" / filename
    if not path.exists():
        return HTMLResponse(f"<h1>Article not found</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "public, max-age=3600"})


# ─── NarAI User API ───────────────────────────────────────────────────────────

from fastapi import Header


def _get_narai_user(authorization: str = None):
    """Extract and verify Bearer token, return user dict or raise 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        from core.narai_user import verify_token
        user = verify_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user, token
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/narai/checkout")
async def narai_checkout(request: Request):
    """Create a Stripe checkout session for a NarAI subscription plan."""
    try:
        body = await request.json()
        plan = body.get("plan", "").lower()
        user_email = body.get("email", "")

        price_map = {
            "pro":   os.getenv("STRIPE_PRICE_PRO", ""),
            "max":   os.getenv("STRIPE_PRICE_MAX", ""),
            "ultra": os.getenv("STRIPE_PRICE_ULTRA", ""),
        }
        price_id = price_map.get(plan)
        if not price_id:
            raise HTTPException(400, f"Unknown plan: {plan}")

        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=user_email or None,
            success_url="https://app.wheellsverse.com/chat?upgraded=" + plan,
            cancel_url="https://app.wheellsverse.com/pricing",
            metadata={"narai_plan": plan, "user_email": user_email},
        )
        return {"url": session.url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


class NaraiChatRequest(BaseModel):
    conversation_id: str
    message: str
    model: Optional[str] = None


class CreateConvRequest(BaseModel):
    title: Optional[str] = "New Chat"


@app.get("/api/narai/profile")
async def narai_get_profile(request: Request):
    """Return the authenticated user's profile."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)
    try:
        from core.narai_user import get_profile
        profile = get_profile(user["id"])
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/narai/conversations")
async def narai_list_conversations(request: Request):
    """List conversations for the authenticated user."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)
    try:
        from core.narai_user import list_conversations
        return list_conversations(user["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/conversations")
async def narai_create_conversation(request: Request, body: CreateConvRequest):
    """Create a new conversation."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)
    try:
        from core.narai_user import create_conversation
        from core.narai_chat import chat_title_from_message
        title = body.title or "New Chat"
        conv_id = create_conversation(user["id"], title[:60])
        if not conv_id:
            raise HTTPException(status_code=500, detail="Failed to create conversation")
        return {"id": conv_id, "title": title}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/narai/conversations/{conv_id}/messages")
async def narai_get_messages(conv_id: str, request: Request):
    """Get messages for a conversation."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)
    try:
        from core.narai_user import get_conversation_messages
        return get_conversation_messages(conv_id, user["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/narai/memory")
async def narai_get_memory(request: Request):
    """Get memory notes for the authenticated user."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)
    try:
        from core.narai_user import get_user_memory
        return get_user_memory(user["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/chat")
async def narai_chat(request: Request, body: NaraiChatRequest):
    """Stream a chat response from NarAI."""
    auth = request.headers.get("Authorization")
    user, _ = _get_narai_user(auth)

    # Check quota
    try:
        from core.narai_user import check_and_increment_quota
        quota = check_and_increment_quota(user["id"])
        if not quota.get("allowed"):
            raise HTTPException(status_code=429, detail={
                "reason": "quota_exceeded",
                "used": quota.get("used"),
                "limit": quota.get("limit"),
                "tier": quota.get("tier"),
                "upgrade_url": "/pricing",
            })
    except HTTPException:
        raise
    except Exception:
        pass  # Fail open on quota check errors

    # Stream response
    from core.narai_chat import chat_stream
    from core.narai_user import get_profile
    profile = get_profile(user["id"]) or {}
    tier = profile.get("tier", "free")

    return StreamingResponse(
        chat_stream(
            user_id=user["id"],
            conversation_id=body.conversation_id,
            user_message=body.message,
            tier=tier,
            requested_model=body.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ─── Zoom AI Clone Routes ────────────────────────────────────────────────────

class ZoomCloneStartRequest(BaseModel):
    meeting_id: str
    sdp_answer: Optional[str] = None
    use_heygen_video: bool = True
    clone_model: str = "claude-haiku-4-5-20251001"

class ZoomCloneSayRequest(BaseModel):
    meeting_id: str
    text: str

class ZoomMeetingCreateRequest(BaseModel):
    topic: str
    duration_minutes: int = 60
    password: Optional[str] = None


@app.post("/api/narai/clone/start")
async def clone_start(body: ZoomCloneStartRequest, request: Request):
    """Start the AI clone in a Zoom meeting."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import ZoomCloneSession, get_session, register_session
    if get_session(body.meeting_id):
        raise HTTPException(400, "Clone already active for this meeting")
    session = ZoomCloneSession(
        meeting_id=body.meeting_id,
        user_id=user["id"],
        use_heygen_video=body.use_heygen_video,
        clone_model=body.clone_model,
    )
    register_session(session)
    result = await session.start(sdp_answer=body.sdp_answer)
    return result


@app.post("/api/narai/clone/stop")
async def clone_stop(meeting_id: str, request: Request):
    """Stop the AI clone session."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import get_session, unregister_session
    session = get_session(meeting_id)
    if not session:
        raise HTTPException(404, "No active clone for this meeting")
    result = await session.stop()
    unregister_session(meeting_id)
    return result


@app.post("/api/narai/clone/say")
async def clone_say(body: ZoomCloneSayRequest, request: Request):
    """Manually inject text — make the clone say something (test / hybrid control)."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import get_session
    session = get_session(body.meeting_id)
    if not session:
        raise HTTPException(404, "No active clone for this meeting")
    session.inject_message(body.text)
    return {"status": "queued", "text": body.text[:100]}


@app.get("/api/narai/clone/status/{meeting_id}")
async def clone_status(meeting_id: str, request: Request):
    """Check if the AI clone is active for a given meeting."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import get_session
    session = get_session(meeting_id)
    if not session:
        return {"active": False, "meeting_id": meeting_id}
    return {"active": session.is_active, "meeting_id": meeting_id, "model": session.clone_model}


@app.post("/api/narai/clone/meeting/new")
async def clone_new_meeting(body: ZoomMeetingCreateRequest, request: Request):
    """Create a new Zoom meeting (uses Zoom Server-to-Server OAuth)."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import create_zoom_meeting
    result = create_zoom_meeting(
        topic=body.topic,
        duration_minutes=body.duration_minutes,
        password=body.password,
    )
    if "error" in result:
        raise HTTPException(500, result["error"])
    return {
        "meeting_id": result.get("id"),
        "topic": result.get("topic"),
        "join_url": result.get("join_url"),
        "start_url": result.get("start_url"),
        "password": result.get("password"),
    }


@app.get("/api/narai/clone/meetings")
async def clone_list_meetings(request: Request):
    """List upcoming Zoom meetings for the authenticated user."""
    auth = request.headers.get("Authorization", "")
    user, _ = _get_narai_user(auth)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from core.zoom_clone import list_zoom_meetings
    return {"meetings": list_zoom_meetings()}


# ─── Homepage ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_homepage():
    """Root — always serve the public user homepage."""
    hp = ROOT / "frontend" / "index.html"
    if hp.exists():
        return HTMLResponse(hp.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store, no-cache"})
    # Fallback: redirect to login if homepage missing
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login")


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_dashboard():
    """Admin dashboard — internal use."""
    return await _serve_old_dashboard()


async def _serve_old_dashboard():
    html_path = ROOT / "dashboard" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Dashboard not found. Expected: dashboard/index.html</h1>", status_code=500)
    html = html_path.read_text(encoding="utf-8")
    # Inject API key for authenticated dashboard access
    if _API_KEY:
        html = html.replace(
            "const API_KEY = '';",
            f"const API_KEY = '{_API_KEY}';",
        )
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


# ─── Overview ─────────────────────────────────────────────────────────────────

@app.get("/api/overview")
async def overview():
    orch = _get_orch()
    all_bots = orch.list_bots()
    statuses = [orch.bots[n].get_status() for n in all_bots if n in orch.bots]

    running = sum(1 for s in statuses if s["status"] == "running")
    failed  = sum(1 for s in statuses if s["status"] == "error")
    done    = sum(1 for s in statuses if s["status"] == "done")
    idle    = len(statuses) - running - failed - done

    sched = _scheduler
    scheduler_running = bool(sched and getattr(sched, "_running", False))

    return {
        "total_bots": len(statuses),
        "running": running,
        "failed": failed,
        "done": done,
        "idle": idle,
        "scheduler_running": scheduler_running,
        "uptime_seconds": int(time.time() - _server_start),
        "system_status": "running" if running > 0 else "idle",
        "log_count": len(_log_buffer),
        "last_updated": datetime.now().isoformat(),
    }


# ─── Bots ─────────────────────────────────────────────────────────────────────

@app.get("/api/bots")
async def list_bots():
    orch = _get_orch()
    result = []
    for full_name in orch.list_bots():
        bot = orch.bots.get(full_name)
        if not bot:
            continue
        s = bot.get_status()
        meta = orch.registry.get(full_name, {})
        s["full_name"] = full_name
        s["description"] = meta.get("description", "")
        s["schedule"]    = meta.get("schedule", "")
        result.append(s)
    return result


@app.post("/api/bots/{category}/{bot_name}/run")
async def run_bot_endpoint(
    category: str,
    bot_name: str,
    req: BotRunRequest,
):
    from core.job_queue import get_queue
    orch = _get_orch()
    full_name = f"{category}/{bot_name}"
    if full_name not in orch.bots:
        raise HTTPException(404, f"Bot '{full_name}' not found")

    kwargs = req.kwargs

    def _run():
        _add_log(f"Running bot: {full_name}", "INFO")
        result = orch.run_bot(full_name, **kwargs)
        _add_log(f"Bot completed: {full_name}", "INFO")
        return result

    job_id = await get_queue().submit(
        name=full_name,
        fn=_run,
        meta={"bot": full_name, "kwargs": kwargs},
    )
    return {"status": "queued", "bot": full_name, "job_id": job_id}


@app.get("/api/jobs")
async def list_jobs(status: str = "", limit: int = 50):
    """List recent async jobs with status and results."""
    from core.job_queue import get_queue
    return {
        "jobs":  get_queue().list_jobs(status=status, limit=limit),
        "stats": get_queue().stats(),
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get status and result of a specific job by ID."""
    from core.job_queue import get_queue
    job = get_queue().get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@app.get("/api/bots/{category}/{bot_name}/output")
async def get_bot_output(category: str, bot_name: str):
    output_dir = ROOT / "outputs" / category / bot_name
    files = []
    if output_dir.exists():
        for f in sorted(output_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            content = ""
            if f.suffix in (".md", ".txt", ".json", ".html"):
                try:
                    content = f.read_text(encoding="utf-8")[:3000]
                except Exception:
                    content = "[Could not read file]"
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "ext": f.suffix,
                "content": content,
            })
    return files


# ─── Pipelines ────────────────────────────────────────────────────────────────

@app.get("/api/pipelines")
async def list_pipelines():
    pe = _get_pipeline()
    return pe.list_pipelines()


@app.post("/api/pipelines/{pipeline_name}/run")
async def run_pipeline_endpoint(pipeline_name: str, background_tasks: BackgroundTasks):
    pe = _get_pipeline()
    if pipeline_name not in pe.pipelines:
        raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")

    def _run():
        _add_log(f"Running pipeline: {pipeline_name}", "INFO")
        try:
            result = pe.run_pipeline(pipeline_name)
            ok = result.get("succeeded", 0)
            total = result.get("total_bots", 0)
            _add_log(f"Pipeline '{pipeline_name}' complete — {ok}/{total} bots succeeded", "INFO")
        except Exception as e:
            _add_log(f"Pipeline failed: {pipeline_name} — {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "started", "pipeline": pipeline_name}


# ─── Scheduler ────────────────────────────────────────────────────────────────

@app.get("/api/scheduler")
async def scheduler_status():
    sched = _get_scheduler()
    jobs = []
    for j in sched.jobs:
        job_obj = j.get("job")
        next_run = None
        if job_obj and hasattr(job_obj, "next_run") and job_obj.next_run:
            next_run = job_obj.next_run.isoformat()
        jobs.append({
            "bot": j["bot"],
            "schedule": j["schedule"],
            "next_run": next_run or j.get("next_run"),
        })
    return {
        "running": getattr(sched, "_running", False),
        "jobs": jobs,
        "total": len(jobs),
    }


@app.get("/api/scheduler/jobs")
async def scheduler_jobs():
    """Alias for /api/scheduler — returns job list."""
    return await scheduler_status()


@app.post("/api/scheduler/start")
async def start_scheduler(background_tasks: BackgroundTasks):
    sched = _get_scheduler()
    background_tasks.add_task(lambda: sched.start(blocking=False))
    _add_log("Scheduler started", "INFO")
    return {"status": "started"}


@app.post("/api/scheduler/stop")
async def stop_scheduler():
    sched = _get_scheduler()
    sched.stop()
    _add_log("Scheduler stopped", "INFO")
    return {"status": "stopped"}


# ─── Categories ───────────────────────────────────────────────────────────────

@app.get("/api/categories")
async def get_categories():
    return _get_orch().get_categories()


@app.post("/api/categories/{category}/run")
async def run_category_endpoint(category: str, background_tasks: BackgroundTasks):
    orch = _get_orch()
    if category not in orch.get_categories():
        raise HTTPException(404, f"Category '{category}' not found")

    def _run():
        _add_log(f"Running category: {category}", "INFO")
        try:
            orch.run_category(category, parallel=True)
            _add_log(f"Category '{category}' completed", "INFO")
        except Exception as e:
            _add_log(f"Category '{category}' failed: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "started", "category": category}


@app.post("/api/run-all")
async def run_all_endpoint(background_tasks: BackgroundTasks):
    orch = _get_orch()

    def _run():
        _add_log("Running ALL 70 bots", "INFO")
        try:
            orch.run_all(parallel=True)
            _add_log("All bots completed", "INFO")
        except Exception as e:
            _add_log(f"Run-all failed: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "started", "message": "All bots queued"}


# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs(limit: int = 200):
    entries = list(_log_buffer)[-limit:]
    return entries


@app.get("/api/logs/stream")
async def stream_logs():
    """Server-Sent Events stream for real-time log tailing."""

    async def event_generator():
        last_ts = 0.0
        while True:
            new_entries = [e for e in _log_buffer if e["ts"] > last_ts]
            if new_entries:
                for entry in new_entries:
                    yield f"data: {json.dumps(entry)}\n\n"
                last_ts = new_entries[-1]["ts"]
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Outputs ──────────────────────────────────────────────────────────────────

@app.get("/api/outputs")
async def list_outputs():
    outputs_dir = ROOT / "outputs"
    result: Dict[str, List] = {}
    if not outputs_dir.exists():
        return result

    for cat_dir in sorted(outputs_dir.iterdir()):
        if not cat_dir.is_dir():
            continue
        files = []
        for bot_dir in sorted(cat_dir.iterdir()):
            if not bot_dir.is_dir():
                continue
            for f in sorted(bot_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                files.append({
                    "bot": bot_dir.name,
                    "file": f.name,
                    "path": str(f.relative_to(ROOT)),
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
        if files:
            result[cat_dir.name] = files

    return result


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    """Return all config keys — reads from env vars first, falls back to .env file."""
    SENSITIVE = ("KEY", "SECRET", "TOKEN", "PASSWORD")

    def _mask(key: str, val: str) -> str:
        if any(kw in key.upper() for kw in SENSITIVE):
            return "***" + val[-4:] if len(val) > 4 else "***"
        return val

    settings: Dict[str, str] = {}

    # 1. Read from .env file if it exists
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if val:
                settings[key] = _mask(key, val)

    # 2. Override/fill with actual live environment variables (Railway vars win)
    KNOWN_KEYS = [
        "ANTHROPIC_API_KEY","OPENAI_API_KEY","OPENAI_MODEL",
        "FACEBOOK_PAGE_TOKEN","FACEBOOK_PAGE_ID","FACEBOOK_APP_ID","FACEBOOK_APP_SECRET",
        "INSTAGRAM_ACCOUNT_ID","INSTAGRAM_PAGE_TOKEN","META_APP_ID","META_APP_SECRET",
        "TWITTER_API_KEY","TWITTER_API_SECRET","TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_SECRET","TWITTER_BEARER_TOKEN",
        "TIKTOK_CLIENT_KEY","TIKTOK_CLIENT_SECRET","TIKTOK_ACCESS_TOKEN",
        "REDDIT_CLIENT_ID","REDDIT_CLIENT_SECRET","REDDIT_USERNAME",
        "REDDIT_PASSWORD","REDDIT_SUBREDDIT",
        "TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID",
        "WHATSAPP_ACCESS_TOKEN","WHATSAPP_PHONE_NUMBER_ID","WHATSAPP_VERIFY_TOKEN",
        "YOUTUBE_API_KEY","YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET",
        "STRIPE_SECRET_KEY","STRIPE_PUBLIC_KEY","STRIPE_WEBHOOK_SECRET",
        "CONVERTKIT_API_KEY","CONVERTKIT_API_SECRET","CONVERTKIT_FORM_ID",
        "WORDPRESS_URL","WORDPRESS_USERNAME","WORDPRESS_PASSWORD",
        "HEYGEN_API_KEY","HEYGEN_AVATAR_ID","HEYGEN_VOICE_ID",
        "ELEVENLABS_API_KEY","ELEVENLABS_VOICE_ID","ELEVENLABS_MODEL",
        "EMAIL_USER","EMAIL_PASSWORD","EMAIL_FROM_NAME","EMAIL_HOST","EMAIL_PORT",
        "SERPER_API_KEY","GSC_PROPERTY_URL","GOOGLE_SERVICE_ACCOUNT_JSON",
        "BRAND_NAME","AUTHOR_NAME","BRAND_NICHE","CTA_URL",
        "DECISION_ENGINE_ENABLED","DECISION_ENGINE_INTERVAL",
        "RAILWAY_PUBLIC_URL","API_KEY","DASHBOARD_PASSWORD",
    ]
    for key in KNOWN_KEYS:
        val = os.getenv(key, "")
        if val:
            settings[key] = _mask(key, val)

    return settings


@app.post("/api/settings")
async def update_setting(update: SettingUpdate):
    """Save a setting to .env file (persists across restarts on local; use Railway vars for prod)."""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{update.key}=") or stripped.startswith(f"{update.key} ="):
            new_lines.append(f"{update.key}={update.value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{update.key}={update.value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    # Also set in current process so it takes effect immediately
    os.environ[update.key] = update.value
    _add_log(f"Setting updated: {update.key}", "INFO")
    return {"status": "updated", "key": update.key}


# ─── Command ──────────────────────────────────────────────────────────────────

@app.post("/api/command")
async def handle_command(req: CommandRequest, background_tasks: BackgroundTasks):
    cmd_interp = _get_cmd()
    orch       = _get_orch()
    pe         = _get_pipeline()
    sched      = _get_scheduler()

    _add_log(f"Command received: {req.command}", "INFO")
    parsed = cmd_interp.parse(req.command)
    _add_log(f"Parsed: {parsed}", "INFO")

    preview = cmd_interp.execute_async(
        parsed, orch, pe, sched,
        on_complete=lambda r: _add_log(f"Command result: {r}", "INFO"),
    )

    return {
        "status": "executing",
        "parsed": parsed,
        "preview": preview,
    }


# ─── Health system ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    """Dashboard password check."""
    dashboard_pw = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not dashboard_pw:
        # No password set — allow access
        return {"ok": True}
    if req.password == dashboard_pw:
        return {"ok": True}
    return {"ok": False}


@app.get("/api/health")
async def health():
    import platform, psutil as _ps
    browser_ok = False
    try:
        from core.browser import is_available
        browser_ok = is_available()
    except Exception:
        pass

    memory_ok = True
    cpu_pct = None
    mem_pct = None
    try:
        cpu_pct = _ps.cpu_percent(interval=0.1)
        mem = _ps.virtual_memory()
        mem_pct = mem.percent
        memory_ok = mem.percent < 90
    except Exception:
        pass

    uptime = int(time.time() - _server_start)
    return {
        "status":   "ok" if memory_ok else "degraded",
        "uptime":   uptime,
        "uptime_human": f"{uptime // 3600}h {(uptime % 3600) // 60}m",
        "browser":  browser_ok,
        "version":  "nexora-v6-agent-workforce",
        "nx_routes": True,
        "narai_autopilot": True,
        "system": {
            "cpu_pct": cpu_pct,
            "mem_pct": mem_pct,
            "platform": platform.system(),
        },
    }


@app.get("/api/security/status")
async def security_status():
    """Security overview."""
    api_key_set = bool(os.getenv("API_KEY", ""))
    return {
        "api_key_auth": "enabled" if api_key_set else "disabled — set API_KEY env var to enable",
        "rate_limiting": f"{_RATE_LIMIT_REQUESTS} req/{_RATE_LIMIT_WINDOW}s per IP",
        "security_headers": "enabled",
        "audit_logging": "enabled",
        "https": "enforced by Railway",
        "recommendations": [] if api_key_set else ["Set API_KEY environment variable to require authentication"],
    }


@app.get("/api/health/bots")
async def bot_health():
    from core.health import get_health_registry
    hr = get_health_registry()
    return {
        "summary": hr.get_summary(),
        "bots": hr.get_all(),
    }


@app.get("/api/health/summary")
async def health_summary():
    from core.health import get_health_registry
    return get_health_registry().get_summary()


# ─── Memory ───────────────────────────────────────────────────────────────────

class MemorySaveRequest(BaseModel):
    key: str
    content: str
    source: str = ""
    tags: List[str] = []
    project: str = "global"

class MemorySearchRequest(BaseModel):
    query: str
    project: str = "global"
    limit: int = 10
    tags: Optional[List[str]] = None


@app.get("/api/memory")
async def list_memory(project: str = "global", limit: int = 50):
    from core.memory import get_memory
    mem = get_memory()
    return {
        "entries": mem.list_all(project=project, limit=limit),
        "stats": mem.get_stats(project=project),
    }


@app.post("/api/memory/save")
async def save_memory(req: MemorySaveRequest):
    from core.memory import get_memory
    mem = get_memory()
    mem.save(
        key=req.key,
        content=req.content,
        project=req.project,
        source=req.source,
        tags=req.tags,
    )
    _add_log(f"Memory saved: {req.key}", "INFO")
    return {"status": "saved", "key": req.key}


@app.post("/api/memory/search")
async def search_memory(req: MemorySearchRequest):
    from core.memory import get_memory
    mem = get_memory()
    results = mem.search(req.query, project=req.project, limit=req.limit,
                         tags=req.tags)
    return {"results": results, "count": len(results)}


@app.delete("/api/memory/{key}")
async def delete_memory(key: str, project: str = "global"):
    from core.memory import get_memory
    ok = get_memory().global_store.delete(key)
    return {"status": "deleted" if ok else "not_found"}


# ─── Decision Engine ──────────────────────────────────────────────────────────

_decision_engine = None


def _get_de():
    global _decision_engine
    if _decision_engine is None:
        from core.decision_engine import get_decision_engine
        from core.health import get_health_registry
        from core.memory import get_memory
        _decision_engine = get_decision_engine(
            orchestrator=_get_orch(),
            pipeline_engine=_get_pipeline(),
            health_registry=get_health_registry(),
            memory=get_memory(),
        )
    return _decision_engine


@app.get("/api/decisions")
async def get_decisions(limit: int = 50):
    de = _get_de()
    return {
        "status": de.get_status(),
        "rules": de.get_rules(),
        "log": de.get_log(limit),
    }


@app.post("/api/decisions/start")
async def start_decision_engine(background_tasks: BackgroundTasks, interval: int = 10):
    de = _get_de()
    background_tasks.add_task(lambda: de.start(interval))
    _add_log(f"Decision engine started (every {interval}min)", "INFO")
    return {"status": "started", "interval_minutes": interval}


@app.post("/api/decisions/stop")
async def stop_decision_engine():
    de = _get_de()
    de.stop()
    _add_log("Decision engine stopped", "INFO")
    return {"status": "stopped"}


@app.post("/api/decisions/cycle")
async def run_decision_cycle(background_tasks: BackgroundTasks):
    """Manually trigger one decision cycle."""
    de = _get_de()

    def _run():
        results = de.run_cycle()
        _add_log(f"Decision cycle: {len(results)} actions triggered", "INFO")

    background_tasks.add_task(_run)
    return {"status": "cycle_started"}


@app.patch("/api/decisions/rules/{rule_name}")
async def toggle_rule(rule_name: str, enabled: bool):
    de = _get_de()
    ok = de.enable_rule(rule_name, enabled)
    return {"status": "updated" if ok else "not_found", "rule": rule_name, "enabled": enabled}


@app.get("/api/decisions/state")
async def get_system_state():
    from core.health import get_health_registry
    from core.decision_engine import build_system_state
    state = build_system_state(_get_orch(), get_health_registry())
    return state


@app.post("/api/decision/run")
async def run_full_intelligence(background_tasks: BackgroundTasks):
    """
    Trigger the full autonomous intelligence cycle:
      1. evaluate_market()        — crypto price alerts
      2. evaluate_trends()        — trending topics → content pipeline
      3. evaluate_system_health() — retry failed bots, escalate
      4. run_cycle()              — time/state-based rules

    Runs in background; returns a summary when complete via logs.
    Use GET /api/decisions to check updated log/status.
    """
    de = _get_de()
    result_holder: Dict[str, Any] = {}

    def _run():
        summary = de.run()
        result_holder.update(summary)
        _add_log(
            f"Intelligence cycle — {summary['total_actions']} actions | "
            f"market:{summary['market_actions']} "
            f"trend:{summary['trend_actions']} "
            f"health:{summary['health_actions']} "
            f"rules:{summary['rule_actions']} | "
            f"alerts:{summary['alerts_sent']}",
            "INFO",
        )

    background_tasks.add_task(_run)
    _add_log("Full intelligence cycle triggered via API", "INFO")
    return {
        "status": "started",
        "message": "Intelligence cycle running in background. "
                   "Check GET /api/decisions for results.",
    }


# ─── Projects ─────────────────────────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    slug: str
    name: str = ""
    brand: str = ""
    niche: str = ""
    goal: str = ""
    tone: str = "professional, engaging"
    model: str = "gpt-4o-mini"

class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    niche: Optional[str] = None
    goal: Optional[str] = None
    tone: Optional[str] = None
    model: Optional[str] = None
    active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


@app.get("/api/projects")
async def list_projects():
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    return {
        "active": pm.active_slug,
        "projects": pm.list_projects(),
    }


@app.post("/api/projects")
async def create_project(req: ProjectCreateRequest):
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    config = {k: v for k, v in req.dict().items() if v and k != "slug"}
    proj = pm.create_project(req.slug, config)
    _add_log(f"Project created: {req.slug}", "INFO")
    return proj.to_dict()


@app.post("/api/projects/{slug}/switch")
async def switch_project(slug: str):
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    proj = pm.switch_project(slug)
    _add_log(f"Switched to project: {slug}", "INFO")
    return {"status": "switched", "project": proj.to_dict()}


@app.patch("/api/projects/{slug}")
async def update_project(slug: str, req: ProjectUpdateRequest):
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    proj = pm.update_project(slug, updates)
    if not proj:
        raise HTTPException(404, f"Project '{slug}' not found")
    return proj.to_dict()


@app.delete("/api/projects/{slug}")
async def delete_project(slug: str):
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    ok = pm.delete_project(slug)
    return {"status": "deleted" if ok else "not_found"}


@app.get("/api/projects/{slug}/outputs")
async def get_project_outputs(slug: str):
    from core.project_manager import get_project_manager
    pm = get_project_manager()
    return pm.get_project_outputs(slug)


@app.get("/api/projects/active/context")
async def get_active_context():
    from core.project_manager import get_project_manager
    return get_project_manager().get_active_context()


# ─── Integrations (Real Data) ─────────────────────────────────────────────────

@app.get("/api/integrations/market")
async def get_market_summary():
    """Aggregated snapshot: top crypto, stocks, fear & greed, top news."""
    from core.integrations import get_integrations
    return get_integrations().get_market_summary()


@app.get("/api/integrations/news")
async def get_news(query: str = "AI automation entrepreneurship"):
    from core.integrations import get_integrations
    return get_integrations().get_news(query)


@app.get("/api/integrations/crypto")
async def get_crypto():
    from core.integrations import get_integrations
    return get_integrations().get_crypto_prices()


@app.get("/api/integrations/stocks")
async def get_stocks(tickers: str = ""):
    from core.integrations import get_integrations
    hub = get_integrations()
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None
    return hub.get_stock_prices(ticker_list)


@app.get("/api/integrations/trends")
async def get_trends(keywords: str = ""):
    from core.integrations import get_integrations
    hub = get_integrations()
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
    return hub.get_google_trends(kw_list)


@app.get("/api/integrations/reddit")
async def get_reddit(subreddit: str = "entrepreneur"):
    from core.integrations import get_integrations
    return get_integrations().get_reddit_hot(subreddit)


@app.get("/api/integrations/content-intel")
async def get_content_intelligence():
    """Combined feed for content/marketing bots: trends + news + Reddit."""
    from core.integrations import get_integrations
    return get_integrations().get_content_intelligence()


@app.get("/api/integrations/cache")
async def get_integrations_cache():
    from core.integrations import get_integrations
    return get_integrations().get_cache_status()


@app.delete("/api/integrations/cache")
async def clear_integrations_cache(prefix: str = ""):
    from core.integrations import get_integrations
    get_integrations().clear_cache(prefix)
    return {"status": "cleared", "prefix": prefix or "all"}


# ─── Output Automation ────────────────────────────────────────────────────────

class AutomationSendRequest(BaseModel):
    bot_name: str
    title: str
    content: str
    channels: List[str] = ["queue"]
    export_formats: List[str] = ["html"]
    project_slug: str = "wheellsverse"

class AlertRequest(BaseModel):
    title: str
    message: str
    channels: List[str] = ["slack", "discord"]

class AutoPostRequest(BaseModel):
    content: str
    platform: str = "slack"
    topic: str = ""

class ExportRequest(BaseModel):
    title: str
    content: str
    project_slug: str = "wheellsverse"
    format: str = "html"


@app.get("/api/automation/status")
async def automation_status():
    """Check which delivery channels are configured."""
    from core.output_automation import get_automator
    return get_automator().get_status()


@app.post("/api/automation/send")
async def automation_send(req: AutomationSendRequest, background_tasks: BackgroundTasks):
    """Send bot output to email/Slack/Discord/file."""
    from core.output_automation import get_automator
    auto = get_automator()
    output_dir = ROOT / "projects" / req.project_slug / "outputs" / "automation"

    def _send():
        result = auto.send_to_all(
            bot_name=req.bot_name,
            title=req.title,
            content=req.content,
            channels=req.channels,
            output_dir=output_dir if req.export_formats else None,
            export_formats=req.export_formats,
        )
        _add_log(f"Automation send: {req.bot_name} → {req.channels}", "INFO")
        return result

    background_tasks.add_task(_send)
    return {"status": "queued", "bot": req.bot_name, "channels": req.channels}


@app.post("/api/automation/alert")
async def send_alert(req: AlertRequest):
    from core.output_automation import get_automator
    return get_automator().send_alert(req.title, req.message, req.channels)


@app.post("/api/automation/post")
async def auto_post(req: AutoPostRequest):
    """Auto-post content to a channel (Slack/Discord/email)."""
    from core.output_automation import get_automator
    return get_automator().auto_post_content(req.content, req.platform, req.topic)


@app.post("/api/automation/digest")
async def flush_digest(background_tasks: BackgroundTasks):
    """Flush the report queue and send as a batched digest."""
    from core.output_automation import get_automator

    def _flush():
        result = get_automator().flush_digest()
        _add_log(f"Digest flushed: {result.get('count', 0)} items", "INFO")

    background_tasks.add_task(_flush)
    return {"status": "flushing"}


@app.post("/api/automation/export")
async def export_report(req: ExportRequest):
    from core.output_automation import get_automator
    path = get_automator().export_report(req.title, req.content, req.project_slug, req.format)
    if path:
        return {"status": "exported", "path": str(path.relative_to(ROOT)), "format": req.format}
    return {"status": "error", "reason": "Export failed"}


@app.get("/api/automation/log")
async def automation_log(limit: int = 100):
    from core.output_automation import get_automator
    return get_automator().get_delivery_log(limit)


@app.get("/api/automation/queue")
async def automation_queue():
    """View items currently in the report queue."""
    from core.output_automation import get_automator
    auto = get_automator()
    return {"size": auto.queue.size(), "items": auto.queue.get_items()}


# ─── Log files (rotation-aware) ───────────────────────────────────────────────

@app.get("/api/logs/files")
async def list_log_files():
    """List all rotated log files with sizes."""
    files = []
    for f in sorted(LOGS_DIR.iterdir()):
        if f.is_file() and f.suffix in (".log", ""):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return files


@app.get("/api/logs/tail")
async def tail_log_file(filename: str = "system.log", lines: int = 200):
    """Read last N lines from a rotated log file."""
    log_path = LOGS_DIR / filename
    if not log_path.exists() or not log_path.is_relative_to(LOGS_DIR):
        raise HTTPException(404, "Log file not found")
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail_lines = text.splitlines()[-lines:]
        return {"file": filename, "lines": tail_lines, "total_shown": len(tail_lines)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── Content Pipeline ────────────────────────────────────────────────────────

class ContentRunRequest(BaseModel):
    topics: Optional[List[str]] = None
    top_n:  int = 2
    publish: bool = False
    publish_platforms: List[str] = ["static"]


class PublishRequest(BaseModel):
    content: str
    title: str = ""
    platforms: Optional[List[str]] = None   # None = all
    video_url: Optional[str] = None
    hashtags: Optional[List[str]] = None
    slug: str = ""


class LinkedInPostRequest(BaseModel):
    topic: str = ""
    text: str = ""
    niche: str = "general"
    image_url: str = ""
    generate: bool = True


@app.post("/api/content/run")
async def run_content_pipeline(req: ContentRunRequest, background_tasks: BackgroundTasks):
    """
    Trigger the full money-making content pipeline:
      trend fetch → topic scoring → generate (blog+Twitter+LinkedIn)
      → SEO → monetization → save → optional publish
    """
    from core.memory import get_memory
    from core.intelligence import get_intelligence
    from pipelines.content_pipeline import get_content_pipeline

    cp = get_content_pipeline(memory=get_memory(), intelligence=get_intelligence())
    result_holder: Dict[str, Any] = {}

    def _run():
        result = cp.run(
            topics=req.topics,
            top_n=req.top_n,
            publish=req.publish,
            publish_platforms=req.publish_platforms,
        )
        result_holder.update(result)
        _add_log(
            f"Content pipeline — {result.get('pieces_created',0)} pieces | "
            f"{result.get('pieces_published',0)} published | "
            f"{len(result.get('errors',[]))} errors",
            "INFO",
        )

    background_tasks.add_task(_run)
    _add_log("Content pipeline triggered", "INFO")
    return {"status": "started", "message": "Content pipeline running in background"}


@app.get("/api/content/history")
async def content_history(limit: int = 20):
    """Return last N content pipeline runs."""
    from pipelines.content_pipeline import get_content_pipeline
    cp = get_content_pipeline()
    return {"history": cp.get_history(limit), "analytics": cp.get_analytics()[:10]}


@app.get("/api/content/analytics")
async def content_analytics():
    """Detailed content analytics from all pipeline runs."""
    from pipelines.content_pipeline import get_content_pipeline
    return {"analytics": get_content_pipeline().get_analytics()}


@app.post("/api/content/publish")
async def publish_content_endpoint(req: PublishRequest, background_tasks: BackgroundTasks):
    """Publish a specific content piece to specified platforms."""
    from core.publisher import get_publisher
    from pipelines.content_pipeline import OUTPUTS_DIR
    import json

    # Find latest content JSON
    content_dirs = sorted(OUTPUTS_DIR.iterdir(),
                          key=lambda d: d.stat().st_mtime, reverse=True)
    if not content_dirs or req.piece_index >= len(content_dirs):
        raise HTTPException(404, "No content found. Run /api/content/run first.")

    target_dir = content_dirs[req.piece_index]
    json_file  = target_dir / "content_data.json"
    if not json_file.exists():
        raise HTTPException(404, "Content data file not found")

    piece = json.loads(json_file.read_text(encoding="utf-8"))

    def _pub():
        result = get_publisher().publish_content(piece, platforms=req.platforms)
        _add_log(
            f"Published '{piece.get('topic','')[:40]}' → "
            f"{result['success_count']}/{result['total_platforms']} platforms",
            "INFO",
        )

    background_tasks.add_task(_pub)
    return {"status": "publishing", "topic": piece.get("topic",""), "platforms": req.platforms}


# ─── Publisher Status ─────────────────────────────────────────────────────────

@app.get("/api/publish/status")
async def publisher_status():
    from core.publisher import get_publisher
    pub = get_publisher()
    return {
        "configured_platforms": pub.get_configured_platforms(),
        "wordpress": pub.wordpress.is_configured,
        "medium":    pub.medium.is_configured,
        "ghost":     pub.ghost.is_configured,
        "static":    True,
    }


# ─── Monetization ─────────────────────────────────────────────────────────────

@app.get("/api/monetization/stats")
async def monetization_stats():
    from core.monetization import get_monetization_engine
    return get_monetization_engine().get_injection_stats()


@app.post("/api/monetization/lead-magnet")
async def generate_lead_magnet(topic: str = "AI Automation", background_tasks: BackgroundTasks = None):
    from core.monetization import get_monetization_engine
    engine = get_monetization_engine()

    def _gen():
        engine.generate_lead_magnet_pdf(topic)
        _add_log(f"Lead magnet PDF generated: {topic[:40]}", "INFO")

    if background_tasks:
        background_tasks.add_task(_gen)
        return {"status": "generating", "topic": topic}
    path = engine.generate_lead_magnet_pdf(topic)
    if path:
        return {"status": "generated", "path": str(path.relative_to(ROOT))}
    return {"status": "error", "reason": "PDF generation failed"}


# ─── Intelligence System ──────────────────────────────────────────────────────

@app.get("/api/intelligence/summary")
async def intelligence_summary():
    from core.intelligence import get_intelligence
    return get_intelligence().get_summary()


@app.get("/api/intelligence/strategy")
async def intelligence_strategy():
    from core.intelligence import get_intelligence
    return get_intelligence().get_strategy()


@app.get("/api/intelligence/records")
async def intelligence_records(limit: int = 50):
    from core.intelligence import get_intelligence
    return {
        "records":    get_intelligence().get_all_records(limit),
        "pipeline_performance": get_intelligence().get_pipeline_performance(),
    }


@app.post("/api/intelligence/record-engagement")
async def record_engagement(
    content_id: str,
    views:    int = 0,
    clicks:   int = 0,
    shares:   int = 0,
    comments: int = 0,
):
    from core.intelligence import get_intelligence
    rec = get_intelligence().record_engagement(content_id, views, clicks, shares, comments)
    if not rec:
        raise HTTPException(404, f"Content ID '{content_id}' not found")
    return {"status": "updated", "performance_score": rec.performance_score}


@app.post("/api/intelligence/report")
async def generate_intelligence_report(background_tasks: BackgroundTasks):
    from core.intelligence import get_intelligence
    def _gen():
        get_intelligence().generate_improvement_report()
        _add_log("Intelligence improvement report generated", "INFO")
    background_tasks.add_task(_gen)
    return {"status": "generating", "location": "outputs/reports/"}


# ─── Email Lead Capture ───────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    email: str
    name:  str = ""
    source: str = "landing_page"
    topic:  str = ""
    metadata: Optional[Dict[str, Any]] = None


@app.post("/api/lead")
async def capture_lead(req: LeadRequest):
    """
    Capture an email lead from landing page or any form.
    Saves to data/leads/leads.json + leads.csv
    Tracks in analytics + intelligence.
    """
    from core.email_capture import get_email_capture
    cap    = get_email_capture()
    result = cap.capture(
        email=req.email,
        name=req.name,
        source=req.source,
        topic=req.topic,
        metadata=req.metadata,
    )
    if result["status"] == "new":
        # Track in analytics
        try:
            from core.analytics import get_analytics
            get_analytics().track_lead(source=req.source)
        except Exception:
            pass
        # Record in intelligence (boosts topic score)
        try:
            from core.intelligence import get_intelligence
            get_intelligence().record_lead(topic=req.topic, source=req.source)
        except Exception:
            pass
        # Auto-add to ConvertKit
        try:
            from core.drip import enroll_in_drip
            enroll_in_drip(email=req.email, first_name=req.name, source=req.source)
        except Exception:
            pass
        try:
            from core.telegram import notify_new_lead
            notify_new_lead(email=req.email, source=req.source, topic=req.topic)
        except Exception:
            pass
        _add_log(f"Lead captured + drip enrolled: {req.email[:30]} from {req.source}", "INFO")
    return {"status": result["status"], "message": "Thanks! You'll hear from us soon."}


@app.get("/api/leads")
async def list_leads(limit: int = 100, source: str = ""):
    from core.email_capture import get_email_capture
    cap = get_email_capture()
    return {
        "leads": cap.get_leads(limit=limit, source=source),
        "stats": cap.get_stats(),
    }


@app.get("/api/leads/stats")
async def lead_stats():
    from core.email_capture import get_email_capture
    return get_email_capture().get_stats()


@app.post("/api/leads/sync-convertkit")
async def sync_leads_to_convertkit():
    """
    Backfill all local leads into ConvertKit.
    Skips emails already tagged 'ck_synced' in their metadata.
    """
    from core.email_capture import get_email_capture
    from core.drip import enroll_in_drip
    cap = get_email_capture()
    leads = cap.get_leads(limit=10000)
    synced, skipped, failed = 0, 0, 0
    for lead in leads:
        if lead.get("metadata", {}).get("ck_synced"):
            skipped += 1
            continue
        try:
            result = enroll_in_drip(
                email=lead["email"],
                first_name=lead.get("name", ""),
                source=lead.get("source", "backfill"),
            )
            if result.get("status") != "skipped":
                # Mark synced in local record
                lead.setdefault("metadata", {})["ck_synced"] = True
                synced += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            _add_log(f"CK sync failed for {lead['email'][:20]}: {e}", "ERROR")
    # Persist updated metadata
    try:
        import json as _json
        from pathlib import Path as _Path
        _f = _Path(__file__).parent.parent / "data" / "leads" / "leads.json"
        _f.write_text(_json.dumps(leads, indent=2, ensure_ascii=False))
    except Exception:
        pass
    _add_log(f"ConvertKit sync: {synced} synced, {skipped} skipped, {failed} failed", "INFO")
    return {"synced": synced, "skipped": skipped, "failed": failed, "total": len(leads)}


@app.get("/api/leads/scored")
async def scored_leads():
    """
    Return all leads with a 0-100 score based on source, topic, and recency.
    High score = higher purchase intent.
    """
    from core.email_capture import get_email_capture
    from datetime import datetime
    SOURCE_SCORES = {
        "blog_cta": 30, "blog_index": 25, "landing_page": 20,
        "twitter": 15, "tiktok": 15, "smoke_test": 0,
    }
    TOPIC_SCORES = {
        "crypto": 35, "bitcoin": 35, "investing": 30, "stocks": 30,
        "passive income": 25, "ai tools": 20, "side hustle": 20,
    }
    now = datetime.now()
    leads = get_email_capture().get_leads(limit=10000)
    scored = []
    for lead in leads:
        score = 0
        src = lead.get("source", "").lower()
        topic = lead.get("topic", "").lower()
        captured = lead.get("captured_at", "")
        score += SOURCE_SCORES.get(src, 10)
        for kw, pts in TOPIC_SCORES.items():
            if kw in topic:
                score += pts
                break
        # Recency bonus: max 20 pts if captured in last 24h, decays over 30 days
        try:
            dt = datetime.fromisoformat(captured)
            days_old = (now - dt).days
            score += max(0, 20 - days_old)
        except Exception:
            pass
        # CK synced bonus
        if lead.get("metadata", {}).get("ck_synced"):
            score += 5
        scored.append({**lead, "score": min(score, 100)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {"leads": scored, "total": len(scored)}


@app.post("/api/report/weekly")
async def generate_weekly_report():
    """
    AI-generated weekly performance report.
    Pulls all live metrics and uses GPT to write a branded HTML summary.
    """
    from core.email_capture import get_email_capture
    from core.click_tracker import get_stats as click_stats

    # Gather metrics
    try:
        from core.impact import get_earnings
        earned_7d_raw = get_earnings(days=7)
        earned_7d = earned_7d_raw.get("total_earned", 0) or 0
    except Exception:
        earned_7d = 0.0

    lead_stats_data = get_email_capture().get_stats()
    clicks_data = click_stats()
    total_articles = 20
    total_leads = lead_stats_data.get("total_leads", 0)
    leads_today = lead_stats_data.get("leads_today", 0)
    total_clicks = clicks_data.get("total_clicks", 0)
    top_partner = max(
        clicks_data.get("by_partner", {}).items(),
        key=lambda x: x[1], default=("none", 0)
    )[0]

    from datetime import datetime
    week = datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are the AI report writer for WheellsVerse — a professional AI content and affiliate marketing agency.

Write a concise, professional weekly performance report as styled HTML. Use inline CSS. Dark theme (#0d0f14 bg, #00d4ff cyan accents, #e0e6f0 text).

This week's data (week ending {week}):
- Articles live on blog: {total_articles}
- New email leads: {total_leads} total, {leads_today} today
- Affiliate clicks tracked: {total_clicks}
- Top affiliate program by clicks: {top_partner}
- Revenue earned (7 days): ${earned_7d:.2f}

Write a report with:
1. A headline "WheellsVerse — Weekly Performance Report"
2. An executive summary paragraph (3 sentences, specific numbers)
3. 3 stat cards (Revenue, Leads, Clicks) as styled boxes
4. What's working (2 bullet points based on the data)
5. Recommended action for next week (1 specific, actionable item)
6. A professional closing line

Keep total length under 600 words. Use clean HTML with inline styles. No markdown."""

    import os
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=0.6,
    )
    import re as _re
    html = resp.choices[0].message.content.strip()
    html = _re.sub(r"^```html?\s*", "", html).rstrip("`").strip()
    _add_log("Weekly report generated", "INFO")
    return {"html": html, "generated_at": datetime.now().isoformat(), "metrics": {
        "articles": total_articles, "leads": total_leads,
        "clicks": total_clicks, "revenue_7d": earned_7d,
    }}


# ─── Analytics ────────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics_summary():
    """Today's analytics + 30-day summary."""
    from core.analytics import get_analytics
    return get_analytics().get_full_summary()


@app.get("/api/analytics/today")
async def get_analytics_today():
    from core.analytics import get_analytics
    return get_analytics().get_today()


@app.get("/api/analytics/summary")
async def get_analytics_period(days: int = 30):
    from core.analytics import get_analytics
    return get_analytics().get_summary(days=days)


@app.post("/api/analytics/report")
async def generate_analytics_report(background_tasks: BackgroundTasks):
    """Generate and save the daily analytics report."""
    from core.analytics import get_analytics
    def _gen():
        get_analytics().generate_daily_report()
        _add_log("Daily analytics report generated", "INFO")
    background_tasks.add_task(_gen)
    return {"status": "generating", "location": "outputs/reports/"}


@app.get("/api/intelligence/conversions")
async def get_conversion_stats():
    """Get conversion rate stats from intelligence system."""
    from core.intelligence import get_intelligence
    return get_intelligence().get_conversion_stats()


# ─── Browser Automation (Playwright) ─────────────────────────────────────────

class ScreenshotRequest(BaseModel):
    url: str
    filename: str = ""

class TwitterPostRequest(BaseModel):
    tweets: List[str]

class ScrapeRequest(BaseModel):
    url: str
    selector: str = ""
    wait_for: str = ""


@app.get("/api/browser/status")
async def browser_status():
    """Check if Playwright browsers are installed and ready."""
    try:
        from core.browser import is_available
        available = is_available()
        twitter_set  = bool(os.getenv("TWITTER_EMAIL") and os.getenv("TWITTER_PASSWORD"))
        linkedin_set = bool(os.getenv("LINKEDIN_EMAIL") and os.getenv("LINKEDIN_PASSWORD"))
        return {
            "playwright_available": available,
            "twitter_configured":   twitter_set,
            "linkedin_configured":  linkedin_set,
            "auto_post_twitter":    os.getenv("AUTO_POST_TWITTER", "false").lower() == "true",
            "auto_post_linkedin":   os.getenv("AUTO_POST_LINKEDIN", "false").lower() == "true",
        }
    except ImportError:
        return {"playwright_available": False, "reason": "playwright not installed"}


@app.post("/api/browser/screenshot")
async def take_screenshot(req: ScreenshotRequest, background_tasks: BackgroundTasks):
    """Take a full-page screenshot of any URL."""
    from core.browser import is_available
    if not is_available():
        raise HTTPException(503, "Playwright not available. Run: playwright install chromium")

    result_holder: Dict[str, Any] = {}

    def _run():
        from core.browser import screenshot
        try:
            path = screenshot(req.url, req.filename)
            result_holder["path"] = str(path)
            _add_log(f"Screenshot taken: {req.url[:60]}", "INFO")
        except Exception as e:
            result_holder["error"] = str(e)
            _add_log(f"Screenshot failed: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "capturing", "url": req.url}


@app.post("/api/browser/post-twitter")
async def post_to_twitter(req: TwitterPostRequest, background_tasks: BackgroundTasks):
    """Post a Twitter/X thread. Requires TWITTER_EMAIL + TWITTER_PASSWORD in .env."""
    if not (os.getenv("TWITTER_EMAIL") and os.getenv("TWITTER_PASSWORD")):
        raise HTTPException(400, "TWITTER_EMAIL / TWITTER_PASSWORD not set in .env")

    result_holder: Dict[str, Any] = {}

    def _run():
        from core.browser import post_twitter_thread
        try:
            result = post_twitter_thread(req.tweets)
            result_holder.update(result)
            _add_log(f"Twitter thread posted: {len(req.tweets)} tweets", "INFO")
        except Exception as e:
            result_holder["error"] = str(e)
            _add_log(f"Twitter post failed: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "posting", "tweet_count": len(req.tweets)}


@app.post("/api/browser/post-linkedin")
async def post_to_linkedin(req: LinkedInPostRequest, background_tasks: BackgroundTasks):
    """Post to LinkedIn. Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env."""
    if not (os.getenv("LINKEDIN_EMAIL") and os.getenv("LINKEDIN_PASSWORD")):
        raise HTTPException(400, "LINKEDIN_EMAIL / LINKEDIN_PASSWORD not set in .env")

    def _run():
        from core.browser import post_linkedin
        try:
            post_linkedin(req.content)
            _add_log(f"LinkedIn post published ({len(req.content)} chars)", "INFO")
        except Exception as e:
            _add_log(f"LinkedIn post failed: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "posting", "chars": len(req.content)}


@app.get("/api/browser/trends")
async def browser_trends():
    """Scrape Google Trends real-time (full JS-rendered data via Playwright)."""
    from core.browser import is_available
    if not is_available():
        raise HTTPException(503, "Playwright not available. Run: playwright install chromium")
    from core.browser import scrape_google_trends
    try:
        return scrape_google_trends()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/browser/crypto")
async def browser_crypto():
    """Scrape live crypto prices from CoinMarketCap (JS-rendered)."""
    from core.browser import is_available
    if not is_available():
        raise HTTPException(503, "Playwright not available. Run: playwright install chromium")
    from core.browser import scrape_crypto_prices
    try:
        return scrape_crypto_prices()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/browser/scrape")
async def browser_scrape(req: ScrapeRequest):
    """Scrape a JS-rendered page and return its text content."""
    from core.browser import is_available
    if not is_available():
        raise HTTPException(503, "Playwright not available. Run: playwright install chromium")
    from core.browser import scrape_page
    try:
        return scrape_page(req.url, req.selector, req.wait_for)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/browser/post-latest-content")
async def post_latest_content_to_social(background_tasks: BackgroundTasks):
    """
    Auto-post the most recently generated content to Twitter and LinkedIn
    (if credentials are configured).
    """
    from pipelines.content_pipeline import OUTPUTS_DIR
    import json as _json

    content_dirs = sorted(
        [d for d in OUTPUTS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    if not content_dirs:
        raise HTTPException(404, "No content found. Run /api/content/run first.")

    json_file = content_dirs[0] / "content_data.json"
    if not json_file.exists():
        raise HTTPException(404, "content_data.json not found in latest output")

    piece = _json.loads(json_file.read_text(encoding="utf-8"))
    topic   = piece.get("topic", "")
    tweets  = piece.get("twitter", {}).get("tweets", [])
    li_text = piece.get("linkedin", {}).get("content", "")
    posted: List[str] = []

    if tweets and os.getenv("TWITTER_EMAIL") and os.getenv("TWITTER_PASSWORD"):
        def _tw():
            from core.browser import post_twitter_thread
            try:
                post_twitter_thread(tweets)
                _add_log(f"Auto-posted Twitter thread: {topic[:50]}", "INFO")
            except Exception as e:
                _add_log(f"Twitter auto-post failed: {e}", "ERROR")
        background_tasks.add_task(_tw)
        posted.append("twitter")

    if li_text and os.getenv("LINKEDIN_EMAIL") and os.getenv("LINKEDIN_PASSWORD"):
        def _li():
            from core.browser import post_linkedin
            try:
                post_linkedin(li_text)
                _add_log(f"Auto-posted LinkedIn: {topic[:50]}", "INFO")
            except Exception as e:
                _add_log(f"LinkedIn auto-post failed: {e}", "ERROR")
        background_tasks.add_task(_li)
        posted.append("linkedin")

    if not posted:
        return {"status": "skipped", "reason": "No social credentials configured"}

    return {
        "status":  "posting",
        "topic":   topic,
        "posting_to": posted,
        "tweet_count": len(tweets),
    }


# ─── Static published files ───────────────────────────────────────────────────

@app.get("/api/published")
async def list_published():
    """List all statically published HTML pages."""
    from core.publisher import STATIC_DIR
    files = []
    if STATIC_DIR.exists():
        for f in sorted(STATIC_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix == ".html" and f.name != "index.html":
                files.append({
                    "filename": f.name,
                    "url":      f"/published/{f.name}",
                    "size":     f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
    return {"total": len(files), "files": files}


@app.get("/published/{filename}")
async def serve_published(filename: str):
    """Serve a statically published HTML page."""
    from core.publisher import STATIC_DIR
    # Sanitize filename
    if ".." in filename or "/" in filename:
        raise HTTPException(400, "Invalid filename")
    path = STATIC_DIR / filename
    if not path.exists() or path.suffix != ".html":
        raise HTTPException(404, "Published page not found")
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ─── Impact.com Affiliate Earnings ───────────────────────────────────────────

@app.get("/api/affiliate/earnings")
async def affiliate_earnings(days: int = 30):
    """Pull real earnings from Impact.com (Robinhood + Coinbase + all programs)."""
    from core.impact import get_earnings
    return get_earnings(days=days)


@app.get("/api/affiliate/today")
async def affiliate_today():
    """Today's affiliate earnings."""
    from core.impact import get_today_earnings
    return get_today_earnings()


@app.get("/api/affiliate/clicks")
async def affiliate_clicks(days: int = 7):
    """Click stats from Impact.com."""
    from core.impact import get_clicks
    return get_clicks(days=days)


@app.get("/api/affiliate/programs")
async def affiliate_programs():
    """List all joined affiliate programs on Impact.com."""
    from core.impact import get_programs
    return get_programs()


@app.get("/api/affiliate/summary")
async def affiliate_summary():
    """Full affiliate dashboard — earnings + clicks + programs."""
    from core.impact import get_summary
    return get_summary()


@app.get("/api/impact/summary")
async def impact_summary():
    """Alias for /api/affiliate/summary — Impact.com dashboard."""
    from core.impact import get_summary
    return get_summary()


# ─── SuperAgent ───────────────────────────────────────────────────────────────

def _get_superagent():
    from core.superagent import get_superagent
    return get_superagent(orchestrator=_get_orch())


@app.get("/api/superagent/status")
async def superagent_status():
    """SuperAgent current state, decision log, and created bots."""
    return _get_superagent().get_status()


@app.post("/api/superagent/cycle")
async def superagent_cycle(background_tasks: BackgroundTasks):
    """Trigger one full assess→plan→execute cycle."""
    sa = _get_superagent()
    if sa.status == "running":
        return {"status": "busy", "message": "Cycle already running"}
    result_holder: Dict[str, Any] = {}

    def _run():
        result_holder.update(sa.run_cycle())

    background_tasks.add_task(_run)
    _add_log("SuperAgent cycle triggered", "INFO")
    return {"status": "started", "message": "Cycle running in background"}


@app.post("/api/superagent/start")
async def superagent_start_auto(interval_minutes: int = 120):
    """Start autonomous mode (runs a full cycle every N minutes)."""
    result = _get_superagent().start_auto(interval_minutes=interval_minutes)
    _add_log(f"SuperAgent auto-mode started ({interval_minutes}m interval)", "INFO")
    return result


@app.post("/api/superagent/stop")
async def superagent_stop_auto():
    """Stop autonomous mode."""
    result = _get_superagent().stop_auto()
    _add_log("SuperAgent auto-mode stopped", "INFO")
    return result


class GoalRequest(BaseModel):
    daily_usd: float


@app.post("/api/superagent/goal")
async def superagent_set_goal(req: GoalRequest):
    """Update the daily revenue goal."""
    return _get_superagent().set_goal(req.daily_usd)


@app.get("/api/superagent/log")
async def superagent_log(limit: int = 100):
    """Return the last N decision log entries."""
    sa = _get_superagent()
    return {"log": sa.decision_log[-limit:], "total": len(sa.decision_log)}


@app.get("/api/superagent/bots")
async def superagent_created_bots():
    """List all bots created by the SuperAgent."""
    sa = _get_superagent()
    return {"created_bots": sa.created_bots, "count": len(sa.created_bots)}


class ChatRequest(BaseModel):
    message: str


@app.post("/api/superagent/chat")
async def superagent_chat(req: ChatRequest):
    """
    Send a natural-language message to the SuperAgent.
    It understands intent, responds, and can execute actions (run bots,
    create bots, upgrade bots, change goals, etc.).
    """
    sa = _get_superagent()
    result = sa.chat(req.message)
    _add_log(f"SuperAgent chat: {req.message[:60]}", "INFO")
    return result


class UpgradeRequest(BaseModel):
    target: str
    improvement: str = "improve revenue generation and affiliate link placement"


@app.post("/api/superagent/upgrade")
async def superagent_upgrade(req: UpgradeRequest, background_tasks: BackgroundTasks):
    """Upgrade an existing bot with GPT-4-generated improvements."""
    sa = _get_superagent()

    def _run():
        result = sa._action_upgrade_bot({"target": req.target, "improvement": req.improvement})
        _add_log(f"Bot upgrade: {req.target} → {result}", "INFO")

    background_tasks.add_task(_run)
    return {"status": "upgrading", "target": req.target}


@app.get("/api/revenue")
async def revenue_earnings(days: int = 30):
    """
    Single combined endpoint for the Money Board.
    Returns affiliate earnings, bot statuses, and system config in one call.
    """
    from core.impact import get_earnings, get_clicks

    earnings = get_earnings(days=days)
    earnings_7 = get_earnings(days=7)
    clicks = get_clicks(days=7)

    # Revenue bots status
    orch = _get_orch()
    revenue_bot_keys = [
        "marketing/01_content_generator", "marketing/02_seo_optimizer",
        "marketing/03_email_campaign", "marketing/05_funnel_builder",
        "marketing/07_keyword_scraper", "marketing/09_landing_page",
        "marketing/16_blog_publisher", "marketing/17_newsletter_generator",
        "social_media/37_auto_post", "social_media/38_content_scheduler",
        "social_media/40_dm_automation", "social_media/45_multi_platform_poster",
        "ecommerce/61_product_description", "ecommerce/62_pricing_optimization",
    ]
    revenue_bots = []
    for key in revenue_bot_keys:
        bot = orch.bots.get(key)
        if bot:
            s = bot.get_status()
            s["full_name"] = key
            revenue_bots.append(s)
        else:
            cat, name = key.split("/", 1)
            revenue_bots.append({"full_name": key, "name": name, "category": cat,
                                  "status": "idle", "run_count": 0, "last_run": None})

    return {
        "earnings": earnings,
        "earnings_7d": earnings_7,
        "clicks": clicks,
        "revenue_bots": revenue_bots,
        "amazon_tag": os.getenv("AFFILIATE_AMAZON_TAG", ""),
        "impact_configured": bool(os.getenv("IMPACT_ACCOUNT_SID") and os.getenv("IMPACT_API_PASSWORD")),
    }


# ─── TikTok ────────────────────────────────────────────────────────────────────

def _get_tiktok():
    from core.tiktok import get_tiktok
    return get_tiktok()


@app.get("/api/tiktok/status")
async def tiktok_status():
    """TikTok connection status — credentials, token expiry, auth URL."""
    return _get_tiktok().get_status()


@app.get("/api/tiktok/auth")
async def tiktok_auth():
    """Redirect user to TikTok OAuth consent screen."""
    from fastapi.responses import RedirectResponse
    url = _get_tiktok().get_auth_url(fresh=True)
    _add_log("TikTok OAuth initiated", "INFO")
    return RedirectResponse(url)


@app.get("/api/tiktok/callback")
async def tiktok_callback(code: str = "", state: str = "", error: str = ""):
    """Handle TikTok OAuth callback — exchange code for tokens."""
    if error:
        _add_log(f"TikTok OAuth error: {error}", "ERROR")
        return HTMLResponse(
            f"<h2>TikTok Auth Failed</h2><p>{error}</p>"
            "<p><a href='/'>Back to dashboard</a></p>"
        )
    if not code:
        raise HTTPException(400, "Missing code parameter")

    try:
        token_data = _get_tiktok().exchange_code(code, state=state)
        _add_log(f"TikTok connected — open_id: {token_data.get('open_id','')[:12]}", "INFO")
        return HTMLResponse(
            "<h2 style='font-family:monospace;color:#00d4ff'>✅ TikTok Connected!</h2>"
            "<p style='font-family:monospace'>Your account is now linked. "
            "You can close this tab and return to the dashboard.</p>"
            "<script>setTimeout(()=>window.close(),3000);</script>"
        )
    except Exception as e:
        _add_log(f"TikTok token exchange failed: {e}", "ERROR")
        raise HTTPException(500, str(e))


@app.get("/api/tiktok/me")
async def tiktok_me():
    """Return the authenticated TikTok user's profile."""
    try:
        return _get_tiktok().get_user_info()
    except Exception as e:
        raise HTTPException(400, str(e))


class TikTokVideoRequest(BaseModel):
    video_url: str
    caption: str
    privacy: str = "SELF_ONLY"
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False


@app.post("/api/tiktok/post/video")
async def tiktok_post_video(req: TikTokVideoRequest):
    """Post a video to TikTok from a URL."""
    try:
        result = _get_tiktok().post_video_from_url(
            video_url=req.video_url,
            caption=req.caption,
            privacy=req.privacy,
            disable_comment=req.disable_comment,
            disable_duet=req.disable_duet,
            disable_stitch=req.disable_stitch,
        )
        _add_log(f"TikTok video posted — publish_id: {result.get('publish_id','')}", "INFO")
        return result
    except Exception as e:
        _add_log(f"TikTok post failed: {e}", "ERROR")
        raise HTTPException(400, str(e))


class TikTokPhotoRequest(BaseModel):
    photo_urls: List[str]
    caption: str
    privacy: str = "SELF_ONLY"


@app.post("/api/tiktok/post/photo")
async def tiktok_post_photo(req: TikTokPhotoRequest):
    """Post a photo carousel to TikTok."""
    try:
        result = _get_tiktok().post_photo_carousel(
            photo_urls=req.photo_urls,
            caption=req.caption,
            privacy=req.privacy,
        )
        _add_log(f"TikTok photo carousel posted — publish_id: {result.get('publish_id','')}", "INFO")
        return result
    except Exception as e:
        _add_log(f"TikTok photo post failed: {e}", "ERROR")
        raise HTTPException(400, str(e))


@app.get("/api/tiktok/post/{publish_id}/status")
async def tiktok_post_status(publish_id: str):
    """Check the publish status of a TikTok post."""
    try:
        return _get_tiktok().get_post_status(publish_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/tiktok/disconnect")
async def tiktok_disconnect():
    """Revoke TikTok access token and clear stored credentials."""
    _get_tiktok().revoke()
    _add_log("TikTok disconnected", "INFO")
    return {"status": "disconnected"}


# ─── Twitter/X ────────────────────────────────────────────────────────────────

@app.get("/api/twitter/status")
async def twitter_status():
    from core.twitter import get_twitter
    return get_twitter().get_status()


class TweetRequest(BaseModel):
    text: str


class ThreadRequest(BaseModel):
    tweets: List[str]


class ThreadFromContentRequest(BaseModel):
    content: str
    max_tweets: int = 8


@app.post("/api/twitter/tweet")
async def post_tweet(req: TweetRequest):
    import asyncio
    from core.twitter import get_twitter
    try:
        tw = get_twitter()
        result = await asyncio.to_thread(tw.post_tweet, req.text)
        _add_log(f"Tweet posted: {result.get('url','')}", "INFO")
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/twitter/thread")
async def post_thread(req: ThreadRequest):
    import asyncio
    from core.twitter import get_twitter
    try:
        tw = get_twitter()
        results = await asyncio.to_thread(tw.post_thread, req.tweets)
        _add_log(f"Thread posted: {len(results)} tweets", "INFO")
        return {"tweets": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/twitter/thread/from-content")
async def thread_from_content(req: ThreadFromContentRequest):
    """Convert markdown content into a Twitter thread preview (does not post)."""
    from core.twitter import TwitterClient
    tweets = TwitterClient.format_thread_from_markdown(req.content, req.max_tweets)
    return {"tweets": tweets, "count": len(tweets)}


# ─── Twitter Blitz ────────────────────────────────────────────────────────────

_BLITZ_QUEUE_FILE = Path(__file__).parent.parent / "data" / "twitter_queue.json"
_NETLIFY_BLOG = "https://wheellsverse-bots.pages.dev/blog/"

def _load_blitz_queue() -> Dict:
    if _BLITZ_QUEUE_FILE.exists():
        try:
            return json.loads(_BLITZ_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"queue": [], "total_posted": 0, "last_post": None}

def _save_blitz_queue(data: Dict):
    _BLITZ_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BLITZ_QUEUE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _generate_thread_for_article(title: str, category: str, url: str,
                                  affiliates: List[str]) -> List[str]:
    """Use GPT to write a punchy 7-tweet thread from article metadata."""
    import os
    from openai import OpenAI

    AFF_CTAS = {
        "robinhood": "📈 Free stock → https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1",
        "coinbase":  "₿ $10 free BTC → https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1",
        "amazon":    "📚 Best books on this → https://amzn.to/wheellsverse",
    }
    cta_links = "\n".join(AFF_CTAS[a] for a in affiliates if a in AFF_CTAS)

    prompt = f"""Write a Twitter thread for this blog article. 7 tweets max, each ≤280 characters.

Article: "{title}"
Category: {category}
Read more: {url}

Rules:
- Tweet 1: Hook — bold statement or surprising fact that stops scrolling. End with "(thread 🧵)"
- Tweets 2-6: One key insight per tweet, numbered "2/" "3/" etc. Concrete, specific, no fluff.
- Tweet 7: Call to action. Include the article link and these affiliate links on separate lines:
{cta_links}
  Follow @wheelsverse for daily money moves 🚀

Return ONLY the 7 tweets, separated by "---" on its own line. No other text."""

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900,
        temperature=0.8,
    )
    raw = resp.choices[0].message.content.strip()
    tweets = [t.strip() for t in raw.split("---") if t.strip()]
    # Hard cap each at 280 chars
    return [t[:280] for t in tweets if t][:7]


@app.get("/api/twitter/blitz/queue")
async def blitz_queue():
    """Return the full Twitter Blitz queue."""
    return _load_blitz_queue()


@app.post("/api/twitter/blitz/generate")
async def blitz_generate(background_tasks: BackgroundTasks):
    """
    Generate Twitter threads for all 20 blog articles that don't have one yet.
    Runs in background — check /api/twitter/blitz/queue for progress.
    """
    data = _load_blitz_queue()
    existing_slugs = {item["slug"] for item in data["queue"]}

    new_articles = [a for a in _BLOG_ARTICLES if a["filename"].replace(".html", "") not in existing_slugs]

    if not new_articles:
        return {"status": "already_complete", "message": "All articles already have threads queued."}

    async def _run():
        d = _load_blitz_queue()
        for art in new_articles:
            slug = art["filename"].replace(".html", "")
            try:
                tweets = _generate_thread_for_article(
                    title=art["title"],
                    category=art["category"],
                    url=_NETLIFY_BLOG + art["filename"],
                    affiliates=art["affiliates"],
                )
                d["queue"].append({
                    "slug":         slug,
                    "title":        art["title"],
                    "category":     art["category"],
                    "url":          _NETLIFY_BLOG + art["filename"],
                    "affiliates":   art["affiliates"],
                    "tweets":       tweets,
                    "status":       "pending",
                    "generated_at": datetime.now().isoformat(),
                    "posted_at":    None,
                    "tweet_urls":   [],
                })
                _save_blitz_queue(d)
                _add_log(f"Thread generated: {art['title'][:60]}", "INFO")
            except Exception as e:
                _add_log(f"Thread gen failed for {slug}: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {
        "status":    "generating",
        "articles":  len(new_articles),
        "message":   f"Generating {len(new_articles)} threads in background. Check /api/twitter/blitz/queue.",
    }


@app.post("/api/twitter/blitz/post-next")
async def blitz_post_next(count: int = 1):
    """Post the next N pending threads from the queue. Default: 1."""
    import asyncio
    from core.twitter import get_twitter
    tw = get_twitter()
    if not tw.is_connected():
        raise HTTPException(400, "Twitter not connected — check .env credentials")

    data = _load_blitz_queue()
    pending = [item for item in data["queue"] if item["status"] == "pending"]
    if not pending:
        return {"status": "empty", "message": "No pending threads in queue."}

    to_post = pending[:count]
    results = []
    for item in to_post:
        try:
            posted = await asyncio.to_thread(tw.post_thread, item["tweets"])
            item["status"]     = "posted"
            item["posted_at"]  = datetime.now().isoformat()
            item["tweet_urls"] = [t.get("url", "") for t in posted]
            item.pop("last_error", None)
            data["total_posted"] = data.get("total_posted", 0) + 1
            data["last_post"]    = datetime.now().isoformat()
            results.append({"slug": item["slug"], "status": "posted", "url": item["tweet_urls"][0] if item["tweet_urls"] else ""})
            _add_log(f"Thread posted: {item['title'][:60]}", "INFO")
        except Exception as e:
            item["status"]     = "failed"
            item["last_error"] = str(e)[:300]
            results.append({"slug": item["slug"], "status": "failed", "error": str(e)[:200]})
            _add_log(f"Thread post failed: {item['title'][:40]} — {e}", "ERROR")
        _save_blitz_queue(data)

    return {"posted": len([r for r in results if r["status"] == "posted"]),
            "failed": len([r for r in results if r["status"] == "failed"]),
            "results": results}


@app.post("/api/twitter/blitz/reset/{slug}")
async def blitz_reset_item(slug: str):
    """Reset a posted/failed thread back to pending so it can be re-posted."""
    data = _load_blitz_queue()
    for item in data["queue"]:
        if item["slug"] == slug:
            item["status"]    = "pending"
            item["posted_at"] = None
            item["tweet_urls"] = []
            _save_blitz_queue(data)
            return {"status": "reset", "slug": slug}
    raise HTTPException(404, f"Slug not found: {slug}")


@app.post("/api/twitter/blitz/reset-failed")
async def blitz_reset_failed():
    """Reset all failed threads back to pending so they can be re-tried."""
    data = _load_blitz_queue()
    count = 0
    for item in data["queue"]:
        if item["status"] == "failed":
            item["status"] = "pending"
            item["posted_at"] = None
            item["tweet_urls"] = []
            item.pop("last_error", None)
            count += 1
    _save_blitz_queue(data)
    return {"status": "reset", "count": count}


@app.delete("/api/twitter/blitz/queue")
async def blitz_clear_queue():
    """Clear the entire queue (keeps posted history, removes pending)."""
    data = _load_blitz_queue()
    data["queue"] = [i for i in data["queue"] if i["status"] == "posted"]
    _save_blitz_queue(data)
    return {"status": "cleared", "kept_posted": len(data["queue"])}


def _blitz_scheduled_post(count: int = 1) -> None:
    """Sync helper called by the scheduler to post N pending Twitter threads."""
    try:
        from core.twitter import get_twitter
        tw = get_twitter()
        if not tw.is_connected():
            _add_log("Blitz auto-post skipped — Twitter not connected", "WARNING")
            return
        data = _load_blitz_queue()
        pending = [item for item in data["queue"] if item["status"] == "pending"]
        if not pending:
            _add_log("Blitz auto-post: no pending threads in queue", "INFO")
            return
        for item in pending[:count]:
            try:
                posted = tw.post_thread(item["tweets"])
                item["status"] = "posted"
                item["posted_at"] = datetime.now().isoformat()
                item["tweet_urls"] = [t.get("url", "") for t in posted]
                item.pop("last_error", None)
                data["total_posted"] = data.get("total_posted", 0) + 1
                data["last_post"] = datetime.now().isoformat()
                _add_log(f"Auto-post ✅ {item['title'][:60]}", "INFO")
            except Exception as e:
                item["status"] = "failed"
                item["last_error"] = str(e)[:300]
                _add_log(f"Auto-post ❌ {item['title'][:40]} — {e}", "ERROR")
            _save_blitz_queue(data)
    except Exception as e:
        _add_log(f"Blitz scheduled post error: {e}", "ERROR")


# ─── ConvertKit ───────────────────────────────────────────────────────────────

@app.get("/api/convertkit/status")
async def convertkit_status():
    from core.convertkit import get_convertkit
    ck = get_convertkit()
    status = ck.get_status()
    # Also verify API secret works by hitting account endpoint
    try:
        import requests as _req
        r = _req.get(
            "https://api.convertkit.com/v3/account",
            params={"api_secret": os.getenv("CONVERTKIT_API_SECRET","")},
            timeout=8,
        )
        if r.status_code == 200:
            acct = r.json()
            status["connected"] = True
            status["account_name"] = acct.get("name","")
            status["plan"] = acct.get("plan_type","")
            status["email"] = acct.get("primary_email_address","")
            # Get forms
            forms_r = _req.get("https://api.convertkit.com/v3/forms",
                                params={"api_key": os.getenv("CONVERTKIT_API_KEY","")}, timeout=8)
            forms = forms_r.json().get("forms",[]) if forms_r.status_code==200 else []
            status["forms"] = [{"id":f["id"],"name":f["name"]} for f in forms]
            status["forms_count"] = len(forms)
        else:
            status["connected"] = False
            status["error"] = r.json().get("message","Auth failed")
    except Exception as e:
        status["api_check_error"] = str(e)
    return status


@app.post("/api/convertkit/create-form")
async def convertkit_create_form():
    """Instructions: ConvertKit forms must be created in the dashboard, not via API."""
    return {
        "status": "manual_required",
        "message": "Go to app.convertkit.com → Landing Pages & Forms → New Form → Inline → create it → copy the Form ID number",
        "url": "https://app.convertkit.com/forms",
        "next": "Then go to Connections panel and set CONVERTKIT_FORM_ID to the numeric ID",
    }


class SubscriberRequest(BaseModel):
    email: str
    first_name: str = ""
    tags: List[str] = []


@app.post("/api/convertkit/subscribe")
async def convertkit_subscribe(req: SubscriberRequest):
    from core.convertkit import get_convertkit
    try:
        result = get_convertkit().add_subscriber(req.email, req.first_name, req.tags)
        _add_log(f"ConvertKit subscriber: {req.email}", "INFO")
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/convertkit/subscribers")
async def convertkit_subscribers():
    from core.convertkit import get_convertkit
    try:
        return get_convertkit().list_subscribers()
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── WordPress ────────────────────────────────────────────────────────────────

def _wpcom_site_id():
    """Return the site identifier for WordPress.com API calls."""
    url = os.getenv("WORDPRESS_URL","").rstrip("/")
    # strip https:// and trailing slash to get bare domain
    return url.replace("https://","").replace("http://","").rstrip("/")

def _wpcom_token():
    return os.getenv("WORDPRESS_TOKEN","") or os.getenv("WORDPRESS_PASSWORD","")

@app.get("/api/wordpress/status")
async def wordpress_status():
    wp_url   = os.getenv("WORDPRESS_URL","").rstrip("/")
    wp_token = _wpcom_token()
    site_id  = _wpcom_site_id()
    if not (wp_url and site_id):
        return {"connected": False, "error": "Missing WORDPRESS_URL"}
    try:
        import requests as _req_wp
        # Always try without token first (public posts) — token only needed for write ops
        # Validate token if present
        token_valid = False
        if wp_token:
            tr = _req_wp.get(
                "https://public-api.wordpress.com/rest/v1.1/me",
                headers={"Authorization": f"Bearer {wp_token}"},
                timeout=8,
            )
            token_valid = tr.status_code == 200

        # Fetch posts — authenticated gets drafts too, public-only gets published
        headers = {}
        params = {"number": 50, "fields": "ID,title,status,URL,date"}
        if token_valid:
            headers["Authorization"] = f"Bearer {wp_token}"
            params["status"] = "any"

        r = _req_wp.get(
            f"https://public-api.wordpress.com/rest/v1.1/sites/{site_id}/posts",
            headers=headers,
            params=params,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            posts = data.get("posts", [])
            return {
                "connected": True,
                "url": wp_url,
                "platform": "wordpress.com",
                "site": site_id,
                "found": data.get("found", 0),
                "total_posts": data.get("found", 0),
                "token_valid": token_valid,
                "can_write": token_valid,
                "posts": [{"ID": p["ID"], "title": p["title"], "status": p["status"],
                           "URL": p.get("URL",""), "date": p.get("date","")} for p in posts],
            }
        return {"connected": False, "status_code": r.status_code, "error": r.text[:200]}
    except Exception as e:
        return {"connected": False, "error": str(e)}


class WPPostRequest(BaseModel):
    title: str
    content: str
    status: str = "publish"
    tags: List[str] = []


@app.post("/api/wordpress/post")
async def wordpress_post(req: WPPostRequest):
    site_id  = _wpcom_site_id()
    wp_token = _wpcom_token()
    if not site_id:
        raise HTTPException(400, "WordPress not configured — set WORDPRESS_URL")
    if not wp_token:
        raise HTTPException(400, "WordPress token required — set WORDPRESS_TOKEN in Railway")
    try:
        import requests as _req
        r = _req.post(
            f"https://public-api.wordpress.com/rest/v1.1/sites/{site_id}/posts/new",
            headers={"Authorization": f"Bearer {wp_token}"},
            json={"title": req.title, "content": req.content, "status": req.status,
                  "tags": ",".join(req.tags) if req.tags else ""},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        _add_log(f"WordPress post published: {data.get('URL','')}", "INFO")
        return {"status": "published", "url": data.get("URL",""), "id": data.get("ID")}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/wordpress/posts")
async def wordpress_posts(limit: int = 20):
    site_id = _wpcom_site_id()
    if not site_id:
        return {"posts": [], "error": "WordPress not configured"}
    try:
        import requests as _req
        token = _wpcom_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = _req.get(
            f"https://public-api.wordpress.com/rest/v1.1/sites/{site_id}/posts",
            headers=headers,
            params={"number": limit, "fields": "ID,title,status,URL,date"},
            timeout=10,
        )
        posts = r.json().get("posts", []) if r.status_code == 200 else []
        return {"posts": [{"id": p["ID"], "title": p["title"], "status": p["status"], "link": p["URL"], "date": p["date"]} for p in posts]}
    except Exception as e:
        return {"posts": [], "error": str(e)}


@app.delete("/api/wordpress/post/{post_id}")
async def wordpress_delete_post(post_id: int):
    site_id  = _wpcom_site_id()
    wp_token = _wpcom_token()
    if not site_id or not wp_token:
        raise HTTPException(400, "WordPress not configured")
    try:
        import requests as _req
        r = _req.post(
            f"https://public-api.wordpress.com/rest/v1.1/sites/{site_id}/posts/{post_id}/delete",
            headers={"Authorization": f"Bearer {wp_token}"},
            timeout=15,
        )
        r.raise_for_status()
        _add_log(f"WordPress post {post_id} deleted", "INFO")
        return {"status": "deleted", "id": post_id}
    except Exception as e:
        raise HTTPException(400, str(e))


class WPUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None


@app.post("/api/wordpress/post/{post_id}")
async def wordpress_update_post(post_id: int, req: WPUpdateRequest):
    site_id  = _wpcom_site_id()
    wp_token = _wpcom_token()
    if not site_id or not wp_token:
        raise HTTPException(400, "WordPress not configured")
    try:
        import requests as _req
        payload = {k: v for k, v in req.dict().items() if v is not None}
        r = _req.post(
            f"https://public-api.wordpress.com/rest/v1.1/sites/{site_id}/posts/{post_id}",
            headers={"Authorization": f"Bearer {wp_token}"},
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        _add_log(f"WordPress post {post_id} updated", "INFO")
        return {"status": "updated", "url": data.get("URL",""), "id": post_id}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/wordpress/oauth-callback")
async def wordpress_oauth_callback(code: str = "", error: str = ""):
    """Handles WordPress.com OAuth redirect — exchanges code for token and saves it."""
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if not code:
        return JSONResponse({"error": "No code received"}, status_code=400)
    import requests as _req
    client_id     = os.getenv("WORDPRESS_CLIENT_ID", "136770")
    client_secret = os.getenv("WORDPRESS_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("RAILWAY_PUBLIC_URL","").rstrip("/") + "/api/wordpress/oauth-callback"
    r = _req.post("https://public-api.wordpress.com/oauth2/token", data={
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "code":          code,
        "grant_type":    "authorization_code",
    }, timeout=15)
    if r.status_code == 200:
        token_data = r.json()
        token = token_data.get("access_token","")
        # Save to Railway env via env file
        _add_log(f"WordPress OAuth token received — save WORDPRESS_TOKEN={token[:8]}... to Railway", "INFO")
        return HTMLResponse(f"""
        <html><body style="font-family:monospace;background:#0d1117;color:#00ff88;padding:40px">
        <h2>✅ WordPress Connected!</h2>
        <p>Your access token:</p>
        <code style="background:#1a2030;padding:10px;display:block;word-break:break-all">{token}</code>
        <p>Copy the token above and save it in Railway as:<br>
        <b>WORDPRESS_TOKEN</b> = <code>{token}</code></p>
        <p>Then paste the token to your setup assistant.</p>
        </body></html>
        """)
    return JSONResponse({"error": "Token exchange failed", "detail": r.text[:300]}, status_code=400)


@app.get("/api/wordpress/oauth-url")
async def wordpress_oauth_url():
    """Returns the URL to click to authorize WordPress.com access."""
    import urllib.parse
    client_id    = os.getenv("WORDPRESS_CLIENT_ID", "136770")
    redirect_uri = os.getenv("RAILWAY_PUBLIC_URL","").rstrip("/") + "/api/wordpress/oauth-callback"
    params = {
        "client_id":    client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope":        "global",
        "blog":         _wpcom_site_id(),
    }
    url = "https://public-api.wordpress.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    return {"url": url, "instructions": "Open this URL in your browser, authorize the app, then paste the token you receive back here."}


# ─── Notion ───────────────────────────────────────────────────────────────────

def _notion_headers():
    token = os.getenv("NOTION_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def _notion_text(rich):
    """Extract plain text from Notion rich_text array."""
    return "".join(t.get("plain_text","") for t in (rich or []))


@app.get("/api/notion/status")
async def notion_status():
    token = os.getenv("NOTION_TOKEN","")
    if not token:
        return {"connected": False, "error": "NOTION_TOKEN not set"}
    try:
        import requests as _rn
        r = _rn.get("https://api.notion.com/v1/users/me", headers=_notion_headers(), timeout=8)
        if r.status_code != 200:
            return {"connected": False, "error": r.text[:200]}
        user = r.json()
        # Search all accessible pages + databases
        s = _rn.post("https://api.notion.com/v1/search",
                     headers=_notion_headers(),
                     json={"page_size": 50, "sort": {"direction":"descending","timestamp":"last_edited_time"}},
                     timeout=10)
        results = s.json().get("results", []) if s.status_code == 200 else []
        pages = [x for x in results if x.get("object") == "page"]
        databases = [x for x in results if x.get("object") == "database"]
        return {
            "connected": True,
            "workspace": user.get("bot",{}).get("workspace_name",""),
            "user": user.get("name",""),
            "pages_count": len(pages),
            "databases_count": len(databases),
            "total": len(results),
            "pages": [
                {
                    "id": p["id"],
                    "title": _notion_text(p.get("properties",{}).get("title",{}).get("title") or
                                          p.get("properties",{}).get("Name",{}).get("title") or
                                          next((v.get("title",[]) for v in p.get("properties",{}).values() if isinstance(v,dict) and v.get("type")=="title"), [])),
                    "url": p.get("url",""),
                    "last_edited": p.get("last_edited_time",""),
                    "created": p.get("created_time",""),
                    "parent_type": p.get("parent",{}).get("type",""),
                }
                for p in pages
            ],
            "databases": [
                {
                    "id": d["id"],
                    "title": _notion_text(d.get("title",[])),
                    "url": d.get("url",""),
                    "last_edited": d.get("last_edited_time",""),
                    "properties": list(d.get("properties",{}).keys()),
                }
                for d in databases
            ],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.get("/api/notion/database/{db_id}/rows")
async def notion_db_rows(db_id: str, limit: int = 50):
    try:
        import requests as _rn
        r = _rn.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=_notion_headers(),
            json={"page_size": limit},
            timeout=12,
        )
        if r.status_code != 200:
            raise HTTPException(400, r.text[:300])
        data = r.json()
        rows = []
        for item in data.get("results", []):
            row = {"id": item["id"], "url": item.get("url",""), "last_edited": item.get("last_edited_time","")}
            for k, v in item.get("properties", {}).items():
                t = v.get("type","")
                if t == "title":       row[k] = _notion_text(v.get("title",[]))
                elif t == "rich_text": row[k] = _notion_text(v.get("rich_text",[]))
                elif t == "number":    row[k] = v.get("number")
                elif t == "select":    row[k] = (v.get("select") or {}).get("name","")
                elif t == "multi_select": row[k] = [x["name"] for x in v.get("multi_select",[])]
                elif t == "date":      row[k] = (v.get("date") or {}).get("start","")
                elif t == "checkbox":  row[k] = v.get("checkbox", False)
                elif t == "url":       row[k] = v.get("url","")
                elif t == "email":     row[k] = v.get("email","")
                elif t == "status":    row[k] = (v.get("status") or {}).get("name","")
            rows.append(row)
        return {"rows": rows, "has_more": data.get("has_more", False)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


class NotionPageRequest(BaseModel):
    parent_id: str          # page or database ID
    title: str
    content: str = ""
    parent_type: str = "page"  # "page" or "database"


@app.post("/api/notion/page")
async def notion_create_page(req: NotionPageRequest):
    try:
        import requests as _rn
        if req.parent_type == "database":
            parent = {"database_id": req.parent_id}
            properties = {"Name": {"title": [{"text": {"content": req.title}}]}}
        else:
            parent = {"page_id": req.parent_id}
            properties = {"title": {"title": [{"text": {"content": req.title}}]}}

        children = []
        if req.content:
            # Split into paragraphs
            for para in req.content.split("\n\n"):
                para = para.strip()
                if not para:
                    continue
                if para.startswith("# "):
                    children.append({"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":para[2:]}}]}})
                elif para.startswith("## "):
                    children.append({"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":para[3:]}}]}})
                else:
                    children.append({"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":para[:2000]}}]}})

        body = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children

        r = _rn.post("https://api.notion.com/v1/pages", headers=_notion_headers(), json=body, timeout=15)
        if r.status_code not in (200, 201):
            raise HTTPException(400, r.json().get("message", r.text[:300]))
        data = r.json()
        _add_log(f"Notion page created: {req.title}", "INFO")
        return {"id": data["id"], "url": data.get("url",""), "title": req.title}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/notion/page/{page_id}")
async def notion_delete_page(page_id: str):
    try:
        import requests as _rn
        r = _rn.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(),
            json={"archived": True},
            timeout=10,
        )
        if r.status_code != 200:
            raise HTTPException(400, r.text[:300])
        _add_log(f"Notion page {page_id} archived", "INFO")
        return {"status": "archived", "id": page_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── Canva Connect API ────────────────────────────────────────────────────────
_CANVA_TOKEN_FILE = Path("/var/data/canva_token.json") if Path("/var/data").exists() else Path("data/canva_token.json")
_CANVA_BASE = "https://api.canva.com"

def _canva_save_token(data: dict):
    _CANVA_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CANVA_TOKEN_FILE.write_text(json.dumps(data))

def _canva_load_token() -> dict:
    if _CANVA_TOKEN_FILE.exists():
        try:
            return json.loads(_CANVA_TOKEN_FILE.read_text())
        except Exception:
            pass
    return {}

def _canva_access_token() -> str:
    """Return valid access token, refreshing if expired."""
    t = _canva_load_token()
    if not t:
        return ""
    # Check expiry
    expires_at = t.get("expires_at", 0)
    if expires_at and time.time() < expires_at - 60:
        return t.get("access_token", "")
    # Try refresh
    refresh = t.get("refresh_token", "")
    if not refresh:
        return t.get("access_token", "")
    try:
        import requests as _rc
        r = _rc.post("https://api.canva.com/rest/v1/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": os.getenv("CANVA_CLIENT_ID",""),
            "client_secret": os.getenv("CANVA_CLIENT_SECRET",""),
        }, timeout=10)
        if r.status_code == 200:
            new = r.json()
            new["expires_at"] = time.time() + new.get("expires_in", 3600)
            if not new.get("refresh_token"):
                new["refresh_token"] = refresh
            _canva_save_token(new)
            return new.get("access_token","")
    except Exception:
        pass
    return t.get("access_token","")

def _canva_headers():
    tok = _canva_access_token()
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# In-memory store for PKCE code_verifiers keyed by state
_canva_pkce_store: dict = {}

@app.get("/api/canva/oauth-url")
async def canva_oauth_url(request: Request):
    import urllib.parse, secrets, hashlib, base64
    client_id = os.getenv("CANVA_CLIENT_ID","")
    if not client_id:
        return {"error": "CANVA_CLIENT_ID not set"}
    host = request.headers.get("host","")
    if host.startswith("127.0.0.1") or host.startswith("localhost"):
        base_url = f"http://{host}"
    else:
        base_url = os.getenv("RAILWAY_PUBLIC_URL", f"http://{host}").rstrip("/")
    redirect_uri = base_url + "/api/canva/oauth-callback"
    state = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    _canva_pkce_store[state] = code_verifier
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "design:content:read design:content:write design:meta:read asset:read asset:write profile:read",
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    url = "https://www.canva.com/api/oauth/authorize?" + urllib.parse.urlencode(params)
    return {"url": url, "redirect_uri": redirect_uri}


@app.get("/api/canva/oauth-callback")
async def canva_oauth_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    if error:
        return HTMLResponse(f"<h2 style='color:red'>Canva error: {error}</h2>")
    if not code:
        return HTMLResponse("<h2 style='color:red'>No code received from Canva</h2>")
    try:
        import requests as _rc
        host = request.headers.get("host","")
        if host.startswith("127.0.0.1") or host.startswith("localhost"):
            base_url = f"http://{host}"
        else:
            base_url = os.getenv("RAILWAY_PUBLIC_URL", f"http://{host}").rstrip("/")
        redirect_uri = base_url + "/api/canva/oauth-callback"
        code_verifier = _canva_pkce_store.pop(state, None)
        if not code_verifier:
            return HTMLResponse("<h2 style='color:red'>Invalid or expired state — please try connecting again.</h2>")
        r = _rc.post("https://api.canva.com/rest/v1/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": os.getenv("CANVA_CLIENT_ID",""),
            "client_secret": os.getenv("CANVA_CLIENT_SECRET",""),
            "code_verifier": code_verifier,
        }, timeout=15)
        if r.status_code != 200:
            return HTMLResponse(f"<h2 style='color:red'>Token exchange failed: {r.text[:300]}</h2>")
        data = r.json()
        data["expires_at"] = time.time() + data.get("expires_in", 3600)
        _canva_save_token(data)
        _add_log("Canva OAuth connected successfully", "INFO")
        return HTMLResponse("""
        <html><body style='background:#0d0f14;color:#00ff88;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
        <div style='text-align:center;padding:40px;background:#13161d;border:1px solid #00ff8844;border-radius:16px'>
          <div style='font-size:40px;margin-bottom:16px'>✅</div>
          <div style='font-size:18px;font-weight:700;color:#00ff88;margin-bottom:8px'>Canva Connected!</div>
          <div style='font-size:12px;color:#8891a8;margin-bottom:20px'>You can close this tab and return to the dashboard.</div>
          <script>setTimeout(()=>window.close(),3000)</script>
        </div></body></html>""")
    except Exception as e:
        return HTMLResponse(f"<h2 style='color:red'>Error: {e}</h2>")


@app.get("/api/canva/status")
async def canva_status():
    tok = _canva_access_token()
    if not tok:
        client_id = os.getenv("CANVA_CLIENT_ID","")
        return {"connected": False, "error": "Not authorized" if client_id else "CANVA_CLIENT_ID not set"}
    try:
        import requests as _rc
        r = _rc.get(f"{_CANVA_BASE}/rest/v1/users/me", headers=_canva_headers(), timeout=8)
        if r.status_code != 200:
            return {"connected": False, "error": f"API error {r.status_code}: {r.text[:200]}"}
        user = r.json().get("user",{})
        # Fetch recent designs
        dr = _rc.get(f"{_CANVA_BASE}/rest/v1/designs", headers=_canva_headers(),
                     params={"limit": 20}, timeout=10)
        designs = []
        if dr.status_code == 200:
            for d in dr.json().get("items",[]):
                designs.append({
                    "id": d.get("id",""),
                    "title": d.get("title","Untitled"),
                    "thumbnail": d.get("thumbnail",{}).get("url",""),
                    "url": d.get("urls",{}).get("edit_url","") or d.get("urls",{}).get("view_url",""),
                    "created": d.get("created_at",""),
                    "updated": d.get("updated_at",""),
                    "type": d.get("design_type",{}).get("name","Design"),
                })
        return {
            "connected": True,
            "user_id": user.get("user_id",""),
            "display_name": user.get("display_name",""),
            "email": user.get("email",""),
            "designs_count": len(designs),
            "designs": designs,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.post("/api/canva/design")
async def canva_create_design(req: dict):
    """Create a new blank Canva design."""
    tok = _canva_access_token()
    if not tok:
        raise HTTPException(401, "Canva not connected")
    try:
        import requests as _rc
        title = req.get("title", "WheellsVerse Design")
        body = _canva_design_body(req.get("platform", "blog"), title)
        r = _rc.post(f"{_CANVA_BASE}/rest/v1/designs", headers=_canva_headers(), json=body, timeout=15)
        if r.status_code not in (200, 201):
            raise HTTPException(400, r.text[:300])
        data = r.json().get("design",{})
        _add_log(f"Canva design created: {title}", "INFO")
        return {
            "id": data.get("id",""),
            "title": data.get("title",""),
            "url": data.get("urls",{}).get("edit_url",""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/canva/export/{design_id}")
async def canva_export_design(design_id: str, req: dict = {}):
    """Start an export job for a Canva design."""
    tok = _canva_access_token()
    if not tok:
        raise HTTPException(401, "Canva not connected")
    try:
        import requests as _rc
        fmt = req.get("format", "PNG")
        r = _rc.post(f"{_CANVA_BASE}/rest/v1/exports", headers=_canva_headers(),
                     json={"design_id": design_id, "format": {"type": fmt}}, timeout=15)
        if r.status_code not in (200, 201):
            raise HTTPException(400, r.text[:300])
        job = r.json().get("job",{})
        return {"job_id": job.get("id",""), "status": job.get("status",""), "format": fmt}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── Canva Auto-Design Pipeline ───────────────────────────────────────────────

# Platform → (width, height, label) for custom Canva designs
_CANVA_PLATFORM_MAP = {
    "blog":        (1200, 628,  "Blog Featured Image"),
    "wordpress":   (1200, 628,  "Blog Featured Image"),
    "instagram":   (1080, 1080, "Instagram Post"),
    "twitter":     (1200, 675,  "Twitter / X Post"),
    "facebook":    (1200, 630,  "Facebook Post"),
    "youtube":     (1280, 720,  "YouTube Thumbnail"),
    "tiktok":      (1080, 1920, "TikTok Video"),
    "newsletter":  (600,  900,  "Newsletter"),
    "email":       (600,  900,  "Email"),
    "poster":      (794,  1123, "Poster (A4)"),
    "flyer":       (794,  1123, "Flyer (A4)"),
    "logo":        (500,  500,  "Logo"),
    "social":      (1080, 1080, "Social Media Post"),
}

def _canva_design_body(platform: str, title: str) -> dict:
    dims = _CANVA_PLATFORM_MAP.get(platform, (1200, 628, platform.title()))
    w, h, _ = dims
    return {
        "design_type": {"type": "custom", "width": w, "height": h},
        "title": title,
    }

@app.post("/api/canva/auto-design")
async def canva_auto_design(req: dict):
    """
    Smart design creator: given a title + platform, picks the right Canva design
    size and creates it. Returns edit URL so user can customise immediately.
    Body: {title, platform, excerpt (optional)}
    """
    tok = _canva_access_token()
    if not tok:
        return {"error": "Canva not connected — please connect first"}
    try:
        import requests as _rc
        title    = req.get("title", "WheellsVerse Design")
        platform = req.get("platform", "blog").lower()
        dims     = _CANVA_PLATFORM_MAP.get(platform, (1200, 628, platform.title()))
        label    = dims[2]
        body     = _canva_design_body(platform, title)
        r = _rc.post(f"{_CANVA_BASE}/rest/v1/designs", headers=_canva_headers(), json=body, timeout=15)
        if r.status_code not in (200, 201):
            raise HTTPException(400, r.text[:300])
        data  = r.json().get("design", {})
        d_id  = data.get("id", "")
        d_url = data.get("urls", {}).get("edit_url", "")
        _add_log(f"Canva auto-design created [{label}]: {title}", "INFO")
        return {
            "id":          d_id,
            "title":       data.get("title", title),
            "design_type": label,
            "platform":    platform,
            "edit_url":    d_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/canva/pipeline")
async def canva_content_pipeline(req: dict):
    """
    Full content → design pipeline.
    Creates Canva design, optionally publishes a WordPress post referencing it.
    Body: {title, body, platform, publish_to_wp (bool), wp_status ('publish'|'draft')}
    """
    tok = _canva_access_token()
    if not tok:
        return {"error": "Canva not connected"}
    import requests as _rc
    title    = req.get("title", "WheellsVerse Content")
    body_txt = req.get("body", "")
    platform = req.get("platform", "blog").lower()
    publish  = req.get("publish_to_wp", False)
    wp_status = req.get("wp_status", "draft")

    # Step 1 — create Canva design
    dims = _CANVA_PLATFORM_MAP.get(platform, (1200, 628, platform.title()))
    design_type = dims[2]
    body_payload = _canva_design_body(platform, title)
    dr = _rc.post(f"{_CANVA_BASE}/rest/v1/designs", headers=_canva_headers(), json=body_payload, timeout=15)
    if dr.status_code not in (200, 201):
        return {"error": f"Canva design failed: {dr.text[:200]}"}
    design = dr.json().get("design", {})
    edit_url = design.get("urls", {}).get("edit_url", "")
    design_id = design.get("id", "")

    result = {
        "design_id":   design_id,
        "design_type": design_type,
        "edit_url":    edit_url,
        "wp_post_id":  None,
        "wp_url":      None,
    }

    # Step 2 — optionally publish to WordPress
    if publish:
        wp_url   = os.getenv("WORDPRESS_URL","").rstrip("/")
        wp_token = os.getenv("WORDPRESS_TOKEN","")
        site     = wp_url.replace("https://","").replace("http://","")
        if wp_url and wp_token:
            canva_link = f'\n\n<p><a href="{edit_url}" target="_blank">🎨 View / edit design in Canva</a></p>'
            post_body = {
                "title":   title,
                "content": body_txt + canva_link,
                "status":  wp_status,
            }
            wp_r = _rc.post(
                f"https://public-api.wordpress.com/rest/v1.1/sites/{site}/posts/new",
                headers={"Authorization": f"Bearer {wp_token}"},
                json=post_body,
                timeout=20,
            )
            if wp_r.status_code in (200, 201):
                wp_data = wp_r.json()
                result["wp_post_id"] = wp_data.get("ID")
                result["wp_url"]     = wp_data.get("URL")
                _add_log(f"Pipeline: WP post created [{wp_status}]: {title}", "INFO")
            else:
                result["wp_error"] = wp_r.text[:200]

    _add_log(f"Canva pipeline complete: {title} ({platform})", "INFO")
    return result


# ─── Publish Pipeline ─────────────────────────────────────────────────────────

def _get_publisher():
    from core.publish_pipeline import get_publisher
    return get_publisher()


@app.get("/api/pipeline/status")
async def pipeline_status():
    """Which social/email platforms are connected and ready."""
    return _get_publisher().get_status()


@app.post("/api/pipeline/publish")
async def publish_content(req: PublishRequest, background_tasks: BackgroundTasks):
    """Publish content to all connected platforms simultaneously."""
    pub = _get_publisher()
    result_holder: Dict[str, Any] = {}

    def _run():
        result = pub.publish(
            content=req.content,
            title=req.title,
            platforms=req.platforms,
            video_url=req.video_url,
            hashtags=req.hashtags,
            slug=req.slug,
        )
        result_holder.update(result)
        _add_log(
            f"Published '{req.title or 'content'}' — "
            f"{result['published']} published, {result['skipped']} skipped",
            "INFO",
        )

    background_tasks.add_task(_run)
    _add_log(f"Publish pipeline triggered: {req.title or 'content'}", "INFO")
    return {"status": "publishing", "platforms": req.platforms or ["twitter","tiktok","email","blog"]}


class PublishFileRequest(BaseModel):
    file_path: str
    platforms: Optional[List[str]] = None
    video_url: Optional[str] = None


@app.post("/api/pipeline/publish/file")
async def publish_file(req: PublishFileRequest, background_tasks: BackgroundTasks):
    """Publish directly from a generated .md file path."""
    full_path = ROOT / req.file_path
    if not full_path.exists():
        raise HTTPException(404, f"File not found: {req.file_path}")

    pub = _get_publisher()

    def _run():
        result = pub.publish_from_file(
            str(full_path),
            platforms=req.platforms,
            video_url=req.video_url,
        )
        _add_log(
            f"Published file '{req.file_path}' — "
            f"{result['published']} published, {result['skipped']} skipped",
            "INFO",
        )

    background_tasks.add_task(_run)
    return {"status": "publishing", "file": req.file_path}


@app.post("/api/pipeline/batch")
async def publish_batch(background_tasks: BackgroundTasks,
                        limit: int = 10, platforms: Optional[str] = None):
    """Publish the N most recent unpublished bot outputs."""
    platform_list = [p.strip() for p in platforms.split(",")] if platforms else None
    outputs_dir = ROOT / "outputs"
    # Gather recent markdown files not yet in blog
    md_files = sorted(
        [f for f in outputs_dir.rglob("*.md")
         if "published" not in str(f)],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]

    pub = _get_publisher()

    def _run():
        for f in md_files:
            try:
                result = pub.publish_from_file(str(f), platforms=platform_list)
                _add_log(
                    f"Batch published: {f.name} — "
                    f"{result['published']} channels",
                    "INFO",
                )
            except Exception as e:
                _add_log(f"Batch publish failed {f.name}: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "batch_publishing", "files": len(md_files),
            "platforms": platform_list or ["twitter","tiktok","email","blog"]}


# ─── Daily Auto-Publish ───────────────────────────────────────────────────────

@app.post("/api/publish/daily")
async def trigger_daily_publish(background_tasks: BackgroundTasks):
    """Manually trigger the daily auto-publish job right now."""
    def _run():
        from scripts.daily_publish import run_daily_publish
        result = run_daily_publish()
        _add_log(
            f"Manual daily publish: {len(result['published'])} posts published, "
            f"{len(result['errors'])} errors",
            "INFO",
        )
    background_tasks.add_task(_run)
    _add_log("Manual daily publish triggered", "INFO")
    return {
        "status": "running",
        "posts_per_run": int(os.getenv("DAILY_POSTS_COUNT", "5")),
        "schedule_time": os.getenv("DAILY_PUBLISH_TIME", "08:00"),
    }


@app.get("/api/publish/schedule")
async def get_publish_schedule():
    """Return current auto-publish schedule settings."""
    import json
    used_file = ROOT / "data" / "used_topics.json"
    used_count = 0
    if used_file.exists():
        try:
            used_count = len(json.loads(used_file.read_text()))
        except Exception:
            pass
    return {
        "daily_publish_time":  os.getenv("DAILY_PUBLISH_TIME", "08:00"),
        "posts_per_run":       int(os.getenv("DAILY_POSTS_COUNT", "5")),
        "topic_pool_size":     27,
        "topics_used":         used_count,
        "topics_remaining":    max(0, 27 - used_count),
        "netlify_site":        "https://wheellsverse-bots.pages.dev",
    }


# ─── YouTube Integration ──────────────────────────────────────────────────────

class YouTubeUploadRequest(BaseModel):
    video_path:     str
    title:          str
    description:    str = ""
    content:        str = ""        # markdown article → auto-builds description
    tags:           Optional[List[str]] = None
    privacy:        str = "private" # private | unlisted | public
    thumbnail_path: str = ""
    publish_at:     str = ""        # ISO 8601 scheduled time


class YouTubeScriptUploadRequest(BaseModel):
    script_path: str   # path to script_writer .md output
    video_path:  str   # path to rendered MP4
    privacy:     str = "private"


@app.get("/api/youtube/status")
async def youtube_status():
    """YouTube connection status + channel stats."""
    from core.youtube import get_youtube
    return get_youtube().get_status()


@app.post("/api/youtube/auth")
async def youtube_auth():
    """Trigger YouTube OAuth flow (opens browser for one-time authorization)."""
    from core.youtube import get_youtube
    try:
        result = get_youtube().auth()
        _add_log("YouTube OAuth complete — token saved", "INFO")
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/upload")
async def youtube_upload(req: YouTubeUploadRequest, background_tasks: BackgroundTasks):
    """Upload a video to YouTube with auto-generated description + affiliate links."""
    def _run():
        from core.youtube import get_youtube
        result = get_youtube().upload_video(
            video_path=req.video_path,
            title=req.title,
            description=req.description,
            content=req.content,
            tags=req.tags,
            privacy=req.privacy,
            thumbnail_path=req.thumbnail_path,
            publish_at=req.publish_at,
        )
        _add_log(f"YouTube upload complete: {result.get('url', '')}", "INFO")
        try:
            from core.telegram import notify_post_live
            notify_post_live(title=req.title, platform="YouTube",
                             url=result.get("url", ""))
        except Exception:
            pass

    background_tasks.add_task(_run)
    return {"status": "uploading", "title": req.title, "privacy": req.privacy}


@app.post("/api/youtube/upload-from-script")
async def youtube_upload_from_script(req: YouTubeScriptUploadRequest,
                                     background_tasks: BackgroundTasks):
    """Upload a video using a script_writer bot output as title + description source."""
    script = ROOT / req.script_path
    if not script.exists():
        raise HTTPException(404, f"Script file not found: {req.script_path}")

    def _run():
        from core.youtube import get_youtube
        result = get_youtube().upload_from_script(
            script_path=str(script),
            video_path=req.video_path,
            privacy=req.privacy,
        )
        _add_log(f"YouTube script-upload complete: {result.get('url', '')}", "INFO")
        try:
            from core.telegram import notify_post_live
            notify_post_live(title=result.get("title", req.script_path),
                             platform="YouTube", url=result.get("url", ""))
        except Exception:
            pass

    background_tasks.add_task(_run)
    return {"status": "uploading", "script": req.script_path}


@app.get("/api/youtube/videos")
async def youtube_list_videos(limit: int = 10):
    """List recent YouTube videos with view/like/comment counts."""
    from core.youtube import get_youtube
    try:
        return {"videos": get_youtube().list_videos(limit=limit)}
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── Stripe Payments ─────────────────────────────────────────────────────────

class InvoiceItem(BaseModel):
    description: str
    amount_cents: int
    quantity: int = 1

class InvoiceRequest(BaseModel):
    customer_email: str
    items: List[InvoiceItem]
    send: bool = True


@app.get("/api/stripe/status")
async def stripe_status():
    """Stripe connection status + account info."""
    from core.stripe_client import get_stripe
    return get_stripe().get_status()


@app.post("/api/stripe/setup")
async def stripe_setup():
    """Create default WheellsVerse products + prices on Stripe (run once)."""
    from core.stripe_client import get_stripe
    try:
        result = get_stripe().setup_default_products()
        _add_log("Stripe products created", "INFO")
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/stripe/checkout-links")
async def stripe_checkout_links():
    """Return ready-to-use Stripe payment links for all products."""
    from core.stripe_client import get_stripe
    try:
        return get_stripe().get_checkout_links()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/stripe/invoice")
async def create_invoice(req: InvoiceRequest):
    """Create and send a Stripe invoice to a customer."""
    from core.stripe_client import get_stripe
    try:
        result = get_stripe().create_invoice(
            customer_email=req.customer_email,
            items=[i.dict() for i in req.items],
            send=req.send,
        )
        _add_log(f"Invoice created for {req.customer_email}", "INFO")
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── WhatsApp Webhook ─────────────────────────────────────────────────────────

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "wheellsverse_whatsapp")


@app.get("/api/whatsapp/webhook")
async def whatsapp_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Meta webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "Verification failed")


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages and status updates."""
    data = await request.json()
    logger.info("WhatsApp webhook received: %s", json.dumps(data)[:500])
    from core.whatsapp import get_client
    background_tasks.add_task(get_client().handle_payload, data)
    return {"status": "ok"}


# ─── WhatsApp Dashboard API ────────────────────────────────────────────────

class WhatsAppSendRequest(BaseModel):
    to: str
    message: str = ""
    media_url: str = ""
    media_type: str = "image"  # image | audio | video

class WhatsAppContactRequest(BaseModel):
    name: str
    phone: str

@app.get("/api/whatsapp/info")
async def whatsapp_info():
    """Get WhatsApp business number info and status."""
    import requests as _req
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not token or not phone_id:
        return {"configured": False, "error": "Missing credentials"}
    try:
        r = _req.get(
            f"https://graph.facebook.com/v19.0/{phone_id}",
            params={"fields": "display_phone_number,verified_name,code_verification_status,quality_rating", "access_token": token},
            timeout=10
        )
        data = r.json()
        if "error" in data:
            return {"configured": True, "error": data["error"].get("message", "API error")}
        return {
            "configured": True,
            "phone": data.get("display_phone_number", ""),
            "name": data.get("verified_name", ""),
            "status": data.get("code_verification_status", ""),
            "quality": data.get("quality_rating", ""),
            "phone_id": phone_id,
        }
    except Exception as e:
        return {"configured": True, "error": str(e)}

@app.post("/api/whatsapp/send")
async def whatsapp_send(req: WhatsAppSendRequest, request: Request):
    """Send a WhatsApp text or media message from the dashboard."""
    from core.whatsapp import get_client
    client = get_client()
    phone = req.to.strip().replace("+", "").replace(" ", "").replace("-", "")
    logger.info("AUDIT: WhatsApp send to %s from IP %s", phone, request.headers.get("x-forwarded-for", "unknown"))

    if req.media_url:
        mt = req.media_type.lower()
        if mt == "audio":
            ok = client.send_audio(phone, req.media_url)
        elif mt == "video":
            ok = client.send_video(phone, req.media_url, req.message)
        else:
            ok = client.send_image(phone, req.media_url, req.message)
    else:
        if not req.message:
            raise HTTPException(400, "message is required for text messages")
        ok = client.send_message(to=phone, text=req.message)

    if ok:
        _add_log(f"WhatsApp {req.media_type if req.media_url else 'text'} sent to {phone}", "INFO")
        return {"status": "sent", "to": phone}
    raise HTTPException(400, "Failed to send — check WhatsApp credentials")

@app.get("/api/whatsapp/contacts")
async def whatsapp_contacts():
    """Get saved contacts from NarAI memory."""
    try:
        narai = _get_narai()
        if narai:
            contacts = narai._mind.get("contacts", {})
            return {"contacts": [{"name": k, "phone": v} for k, v in contacts.items()]}
    except Exception:
        pass
    return {"contacts": []}

@app.post("/api/whatsapp/contacts")
async def whatsapp_save_contact(req: WhatsAppContactRequest):
    """Save a contact to NarAI memory."""
    try:
        narai = _get_narai()
        if narai:
            narai._save_contact(req.name.lower().strip(), req.phone.strip().replace("+","").replace(" ",""))
            return {"status": "saved", "name": req.name, "phone": req.phone}
    except Exception as e:
        raise HTTPException(400, str(e))
    raise HTTPException(503, "NarAI offline")

@app.delete("/api/whatsapp/contacts/{name}")
async def whatsapp_delete_contact(name: str):
    """Delete a contact from NarAI memory."""
    try:
        narai = _get_narai()
        if narai:
            contacts = narai._mind.get("contacts", {})
            contacts.pop(name.lower(), None)
            narai._mind["contacts"] = contacts
            narai._save_mind()
            return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(400, str(e))
    raise HTTPException(503, "NarAI offline")

@app.get("/api/whatsapp/history")
async def whatsapp_history(limit: int = 50):
    """Get recent WhatsApp message history from activity log."""
    try:
        narai = _get_narai()
        if narai:
            log = narai.get_activity_log(limit=200)
            wa_msgs = [e for e in log if "whatsapp" in e.get("message","").lower() or "send_whatsapp" in e.get("message","").lower()]
            return {"messages": wa_msgs[-limit:]}
    except Exception:
        pass
    return {"messages": []}


# ─── WhatsApp Scheduled Messages ──────────────────────────────────────────

_WA_SCHEDULE_FILE = ROOT / "data" / "wa_schedule.json"

def _load_wa_schedule() -> list:
    try:
        if _WA_SCHEDULE_FILE.exists():
            return json.loads(_WA_SCHEDULE_FILE.read_text())
    except Exception:
        pass
    return []

def _save_wa_schedule(items: list):
    _WA_SCHEDULE_FILE.parent.mkdir(exist_ok=True)
    _WA_SCHEDULE_FILE.write_text(json.dumps(items, indent=2))

class WAScheduleRequest(BaseModel):
    to: str
    message: str
    send_at: str      # ISO datetime string e.g. "2026-04-03T09:00:00"
    repeat: str = "once"  # once | daily | weekly
    label: str = ""   # optional label like "good morning to girlfriend"
    ai_compose: bool = False  # if True, NarAI writes the message at send time

@app.get("/api/whatsapp/schedule")
async def wa_schedule_list():
    """List all scheduled WhatsApp messages."""
    return {"scheduled": _load_wa_schedule()}

@app.post("/api/whatsapp/schedule")
async def wa_schedule_add(req: WAScheduleRequest):
    """Add a new scheduled WhatsApp message."""
    import uuid
    items = _load_wa_schedule()
    item = {
        "id": str(uuid.uuid4())[:8],
        "to": req.to.strip().replace("+","").replace(" ","").replace("-",""),
        "message": req.message,
        "send_at": req.send_at,
        "repeat": req.repeat,
        "label": req.label,
        "ai_compose": req.ai_compose,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "last_sent": None,
    }
    items.append(item)
    _save_wa_schedule(items)
    _add_log(f"WhatsApp scheduled: {req.label or req.to} at {req.send_at}", "INFO")
    return {"status": "scheduled", "item": item}

@app.delete("/api/whatsapp/schedule/{item_id}")
async def wa_schedule_delete(item_id: str):
    """Delete a scheduled message."""
    items = _load_wa_schedule()
    items = [i for i in items if i.get("id") != item_id]
    _save_wa_schedule(items)
    return {"status": "deleted"}

@app.patch("/api/whatsapp/schedule/{item_id}/pause")
async def wa_schedule_pause(item_id: str):
    """Pause/resume a scheduled message."""
    items = _load_wa_schedule()
    for item in items:
        if item.get("id") == item_id:
            item["status"] = "paused" if item.get("status") == "pending" else "pending"
            break
    _save_wa_schedule(items)
    return {"status": "updated"}


# ─── WhatsApp Inbox API ────────────────────────────────────────────────────

def _load_wa_inbox() -> list:
    try:
        p = ROOT / "data" / "wa_inbox.json"
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return []

@app.get("/api/whatsapp/inbox")
async def wa_inbox(limit: int = 50, unread: bool = False):
    """Get WhatsApp inbox messages."""
    msgs = _load_wa_inbox()
    if unread:
        msgs = [m for m in msgs if not m.get("read")]
    # Return newest first
    return {"messages": list(reversed(msgs[-limit:]))}

@app.post("/api/whatsapp/inbox/{msg_id}/reply")
async def wa_inbox_reply(msg_id: str, req: WhatsAppSendRequest):
    """Reply to a specific WhatsApp message."""
    from core.whatsapp import get_client
    wa = get_client()
    inbox = _load_wa_inbox()
    msg = next((m for m in inbox if m.get("id") == msg_id), None)
    if not msg:
        raise HTTPException(404, "Message not found")
    phone = msg["from"]
    ok = wa.send_message(to=phone, text=req.message)
    if ok:
        # Mark as replied
        for m in inbox:
            if m.get("id") == msg_id:
                m["replied"] = True
                m["reply"] = req.message
                m["read"] = True
                break
        (ROOT / "data" / "wa_inbox.json").write_text(json.dumps(inbox, indent=2))
        return {"status": "sent"}
    raise HTTPException(400, "Send failed")

@app.patch("/api/whatsapp/inbox/{msg_id}/read")
async def wa_inbox_mark_read(msg_id: str):
    """Mark a message as read."""
    inbox = _load_wa_inbox()
    for m in inbox:
        if m.get("id") == msg_id:
            m["read"] = True
            break
    (ROOT / "data" / "wa_inbox.json").write_text(json.dumps(inbox, indent=2))
    return {"status": "ok"}

@app.get("/api/whatsapp/inbox/unread_count")
async def wa_unread_count():
    """Get count of unread messages."""
    inbox = _load_wa_inbox()
    return {"count": sum(1 for m in inbox if not m.get("read"))}


# ─── Reddit Automation ───────────────────────────────────────────────────────

class RedditPostRequest(BaseModel):
    title: str
    body:  str
    niche: str = ""                         # auto-detect if empty
    subreddits: Optional[List[str]] = None  # override auto-routing


@app.get("/api/reddit/status")
async def reddit_status():
    """Reddit connection status."""
    from core.reddit import get_reddit
    return get_reddit().get_status()


@app.post("/api/reddit/post")
async def reddit_post(req: RedditPostRequest, background_tasks: BackgroundTasks):
    """Post content to targeted subreddits based on niche."""
    result_holder: list = []

    def _run():
        from core.reddit import get_reddit
        results = get_reddit().post_to_niche(
            title=req.title,
            body=req.body,
            niche=req.niche or None,
            subreddits=req.subreddits,
        )
        result_holder.extend(results)
        posted = [r for r in results if r.get("status") == "posted"]
        _add_log(f"Reddit: posted to {len(posted)} subreddits", "INFO")

    background_tasks.add_task(_run)
    return {"status": "posting", "title": req.title[:80]}


class RedditRepurposeRequest(BaseModel):
    content: str
    title:   str = ""
    formats: Optional[List[str]] = None   # None = all 6 formats


@app.post("/api/reddit/post-repurposed")
async def reddit_post_repurposed(req: RedditRepurposeRequest, background_tasks: BackgroundTasks):
    """Repurpose content then post the Reddit format automatically."""
    def _run():
        from core.repurpose import repurpose
        from core.reddit import get_reddit
        repurposed = repurpose(content=req.content, title=req.title,
                               formats=["reddit_post"])
        results = get_reddit().post_from_repurposed(repurposed)
        posted = [r for r in results if r.get("status") == "posted"]
        _add_log(f"Reddit repurpose+post: {len(posted)} subreddits", "INFO")

    background_tasks.add_task(_run)
    return {"status": "repurposing_and_posting"}


# ─── System Report + Budget ──────────────────────────────────────────────────

@app.get("/api/system/report")
async def system_report():
    """Full system health + service status + budget/credits report."""
    import datetime as _dt

    report = {
        "ts": _dt.datetime.utcnow().isoformat(),
        "services": [],
        "budget": {},
        "revenue": {},
        "system": {},
    }

    # ── Services ──────────────────────────────────────────────────────────────
    def _svc(name, icon, check_fn, docs=""):
        try:
            result = check_fn()
            ok = result.get("connected") or result.get("configured") or result.get("ok") or result.get("status") == "ok"
            note = result.get("username") or result.get("bot_name") or result.get("account_id") or result.get("reason") or ""
            credits_ = result.get("credits")
            subscribers = result.get("subscriber_count")
            extra = {}
            if credits_ is not None: extra["credits"] = credits_
            if subscribers is not None: extra["subscribers"] = subscribers
            return {"name": name, "icon": icon, "ok": bool(ok), "note": str(note)[:80], "docs": docs, **extra}
        except Exception as e:
            return {"name": name, "icon": icon, "ok": False, "note": str(e)[:80], "docs": docs}

    # Anthropic
    try:
        ak = os.getenv("ANTHROPIC_API_KEY","")
        report["services"].append({"name":"Anthropic (Claude AI)","icon":"🤖","ok":bool(ak),"note":"API key set" if ak else "Missing ANTHROPIC_API_KEY","docs":"console.anthropic.com"})
    except Exception as e:
        logger.warning(f"Anthropic status check failed: {e}")

    # OpenAI
    try:
        ak = os.getenv("OPENAI_API_KEY","")
        report["services"].append({"name":"OpenAI (GPT)","icon":"🟢","ok":bool(ak),"note":"API key set" if ak else "Missing OPENAI_API_KEY","docs":"platform.openai.com"})
    except Exception as e:
        logger.warning(f"OpenAI status check failed: {e}")

    # Telegram
    try:
        from core.telegram import get_notifier
        r = get_notifier().get_status()
        report["services"].append({"name":"Telegram Bot","icon":"✈️","ok":r.get("connected",False),"note":r.get("username","") or r.get("error",""),"docs":"t.me/BotFather"})
    except Exception as e:
        report["services"].append({"name":"Telegram Bot","icon":"✈️","ok":False,"note":str(e)[:60]})

    # Stripe
    try:
        from core.stripe_client import get_stripe
        r = get_stripe().get_status()
        report["services"].append({"name":"Stripe (Payments)","icon":"💳","ok":r.get("connected",False),"note":f"mode={r.get('mode','?')} acct={r.get('account_id','?')[:12]}","docs":"dashboard.stripe.com"})
    except Exception as e:
        report["services"].append({"name":"Stripe (Payments)","icon":"💳","ok":False,"note":str(e)[:60]})

    # ConvertKit
    try:
        from core.convertkit import ConvertKitClient
        r = ConvertKitClient().get_status()
        subs = r.get("subscriber_count", 0)
        report["services"].append({"name":"ConvertKit (Email)","icon":"📬","ok":r.get("connected",False),"note":f"{subs} subscribers","docs":"app.convertkit.com","subscribers":subs})
    except Exception as e:
        report["services"].append({"name":"ConvertKit (Email)","icon":"📬","ok":False,"note":str(e)[:60]})

    # HeyGen
    try:
        from core.heygen import HeyGenClient
        r = HeyGenClient().get_status()
        creds = r.get("credits", "?")
        report["services"].append({"name":"HeyGen (AI Video)","icon":"🎬","ok":r.get("configured",False),"note":f"{creds} credits remaining","docs":"app.heygen.com","credits":creds})
    except Exception as e:
        report["services"].append({"name":"HeyGen (AI Video)","icon":"🎬","ok":False,"note":str(e)[:60]})

    # ElevenLabs
    try:
        ak = os.getenv("ELEVENLABS_API_KEY","")
        report["services"].append({"name":"ElevenLabs (Voice)","icon":"🎙","ok":bool(ak),"note":"API key set" if ak else "Missing key","docs":"elevenlabs.io"})
    except Exception as e:
        logger.warning(f"ElevenLabs status check failed: {e}")

    # Facebook/Instagram
    try:
        tok = os.getenv("FACEBOOK_PAGE_TOKEN","")
        pid = os.getenv("FACEBOOK_PAGE_ID","")
        ok = bool(tok and pid)
        report["services"].append({"name":"Facebook / Instagram","icon":"📘","ok":ok,"note":f"page_id={pid}" if ok else "Missing PAGE_TOKEN or PAGE_ID","docs":"developers.facebook.com"})
    except Exception as e:
        logger.warning(f"Facebook/Instagram status check failed: {e}")

    # Twitter
    try:
        from core.twitter import TwitterClient
        r = TwitterClient().get_status()
        report["services"].append({"name":"Twitter / X","icon":"🐦","ok":r.get("connected",False),"note":r.get("username","") or "Not configured","docs":"developer.twitter.com"})
    except Exception:
        report["services"].append({"name":"Twitter / X","icon":"🐦","ok":False,"note":"Missing API keys"})

    # YouTube
    try:
        from core.youtube import get_youtube_status
        r = get_youtube_status()
        report["services"].append({"name":"YouTube","icon":"▶️","ok":r.get("connected",False),"note":r.get("channel","") or r.get("reason","OAuth needed")[:60],"docs":"console.cloud.google.com"})
    except Exception:
        yt_key = os.getenv("YOUTUBE_API_KEY","")
        yt_cid = os.getenv("YOUTUBE_CLIENT_ID","")
        report["services"].append({"name":"YouTube","icon":"▶️","ok":bool(yt_key and yt_cid),"note":"API key set, OAuth needed" if (yt_key and yt_cid) else "Missing credentials"})

    # WhatsApp
    try:
        tok = os.getenv("WHATSAPP_ACCESS_TOKEN","")
        pid = os.getenv("WHATSAPP_PHONE_NUMBER_ID","")
        ok = bool(tok and pid)
        report["services"].append({"name":"WhatsApp","icon":"📱","ok":ok,"note":f"phone_id={pid}" if ok else "Missing token or phone ID","docs":"developers.facebook.com/docs/whatsapp"})
    except Exception as e:
        logger.warning(f"WhatsApp status check failed: {e}")

    # Reddit
    try:
        cid = os.getenv("REDDIT_CLIENT_ID","")
        report["services"].append({"name":"Reddit","icon":"🔴","ok":bool(cid),"note":"Configured" if cid else "Missing CLIENT_ID","docs":"reddit.com/prefs/apps"})
    except Exception as e:
        logger.warning(f"Reddit status check failed: {e}")

    # WordPress
    try:
        wp_url = os.getenv("WORDPRESS_URL","")
        report["services"].append({"name":"WordPress","icon":"🌐","ok":bool(wp_url),"note":wp_url[:40] if wp_url else "Missing WORDPRESS_URL","docs":"wordpress.org"})
    except Exception as e:
        logger.warning(f"WordPress status check failed: {e}")

    # Serper (Google Search)
    try:
        ak = os.getenv("SERPER_API_KEY","")
        report["services"].append({"name":"Serper (Google Search)","icon":"🔍","ok":bool(ak),"note":"API key set" if ak else "Missing key","docs":"serper.dev"})
    except Exception as e:
        logger.warning(f"Serper status check failed: {e}")

    # ── Budget / Credits ──────────────────────────────────────────────────────
    report["budget"] = {
        "monthly_costs": [
            {"name": "Railway (Hosting)",    "cost": 5.00,  "cycle": "monthly", "status": "active"},
            {"name": "Anthropic (Claude)",   "cost": "pay-per-use", "cycle": "usage", "status": "active",
             "note": "~$0.003/1K tokens (Haiku)"},
            {"name": "OpenAI (GPT-4o)",      "cost": "pay-per-use", "cycle": "usage", "status": "active",
             "note": "~$0.005/1K tokens"},
            {"name": "HeyGen (Videos)",      "cost": "credits", "cycle": "per-video", "status": "active",
             "note": "3 credits left"},
            {"name": "ElevenLabs (Voice)",   "cost": "pay-per-use", "cycle": "usage", "status": "active"},
            {"name": "Serper (Search)",      "cost": "pay-per-use", "cycle": "usage", "status": "active",
             "note": "2,500 free/mo"},
        ],
        "heygen_credits": 3,
        "convertkit_subscribers": 0,
    }

    # ── Revenue ───────────────────────────────────────────────────────────────
    try:
        from core.impact import get_earnings
        earnings = get_earnings()
        report["revenue"] = earnings
    except Exception as e:
        logger.warning(f"Revenue fetch failed: {e}")
        report["revenue"] = {"today": 0, "week": 0, "month": 0, "all_time": 0}

    # ── System ────────────────────────────────────────────────────────────────
    total = len(report["services"])
    ok_count = sum(1 for s in report["services"] if s["ok"])
    report["system"] = {
        "services_total": total,
        "services_ok": ok_count,
        "services_failing": total - ok_count,
        "health_pct": round(ok_count / total * 100) if total else 0,
        "uptime_seconds": int((ROOT / "data").stat().st_mtime) if (ROOT / "data").exists() else 0,
        "autopilot": True,
        "narai_online": True,
    }

    return report


# ─── Telegram Notifications ──────────────────────────────────────────────────

@app.get("/api/telegram/status")
async def telegram_status():
    """Telegram bot connection status."""
    from core.telegram import get_notifier
    return get_notifier().get_status()


@app.post("/api/telegram/test")
async def telegram_test():
    """Send a test Telegram notification."""
    from core.telegram import notify
    ok = notify("🤖 <b>WheellsVerse</b> — Telegram notifications are working! ✅")
    if ok:
        return {"status": "sent"}
    raise HTTPException(400, "Telegram not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")


# ─── Telegram Incoming Webhook (instant two-way NarAI chat) ──────────────────

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram pushes every incoming message here instantly.
    Routes all text messages → NarAI voice_chat, replies back.
    """
    import threading as _tgthread
    import requests as _tgreq

    try:
        data = await request.json()
    except Exception:
        return {"ok": True}

    # Support message, channel_post, edited_message
    msg = (data.get("message")
           or data.get("channel_post")
           or data.get("edited_message")
           or {})
    text = (msg.get("text") or "").strip()

    if not text or text.startswith("/"):
        return {"ok": True}

    chat    = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    print(f"[TG-WEBHOOK] Message from chat_id={chat_id}: {text[:80]}", flush=True)

    def _reply_thread():
        try:
            from bots.narai.narai.bot import get_narai
            narai = get_narai()
            result = narai.voice_chat(text)
            reply = result.get("response", "") if isinstance(result, dict) else str(result)
            # Strip markdown
            import re as _re
            reply = _re.sub(r'[*_`#>]{1,3}', '', reply)
            reply = _re.sub(r'\[(.+?)\]\(.+?\)', r'\1', reply)
            reply = reply.strip() or "I'm here."

            print(f"[TG-WEBHOOK] NarAI reply ({len(reply)} chars): {reply[:80]}", flush=True)

            if not tg_token:
                print("[TG-WEBHOOK] ERROR: TELEGRAM_BOT_TOKEN not set!", flush=True)
                return

            r = _tgreq.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": chat_id, "text": reply},
                timeout=20,
            )
            print(f"[TG-WEBHOOK] sendMessage status={r.status_code} body={r.text[:200]}", flush=True)
        except Exception as _e:
            import traceback
            print(f"[TG-WEBHOOK] ERROR: {_e}\n{traceback.format_exc()}", flush=True)

    _tgthread.Thread(target=_reply_thread, daemon=True).start()
    return {"ok": True}


@app.post("/api/telegram/register_webhook")
async def telegram_register_webhook():
    """Register the Railway URL as Telegram webhook for instant message delivery."""
    token    = os.getenv("TELEGRAM_BOT_TOKEN", "")
    base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    if not token or not base_url:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN and RAILWAY_PUBLIC_URL required")
    import requests as _req
    # Delete any existing webhook / pending getUpdates first
    _req.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
              json={"drop_pending_updates": True}, timeout=10)
    webhook_url = f"{base_url}/api/telegram/webhook"
    resp = _req.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={"url": webhook_url, "allowed_updates": ["message", "channel_post"]},
        timeout=10,
    )
    result = resp.json()
    logger.info("Telegram webhook registration: %s", result)
    return {"webhook_url": webhook_url, "telegram_response": result}


# ─── Auto-Repurposing Pipeline ───────────────────────────────────────────────

@app.post("/api/repurpose")
async def repurpose_content(req: RedditRepurposeRequest, background_tasks: BackgroundTasks):
    """Repurpose markdown content into Twitter thread, TikTok caption, email subjects,
    Reddit post, Instagram caption, and LinkedIn post — all at once."""
    result_holder: Dict[str, Any] = {}

    def _run():
        from core.repurpose import repurpose
        result = repurpose(content=req.content, title=req.title, formats=req.formats)
        result_holder.update(result)
        _add_log(f"Repurposed '{result.get('title', 'content')}' into "
                 f"{len(result.get('formats', {}))} formats", "INFO")

    background_tasks.add_task(_run)
    return {"status": "repurposing", "formats": req.formats or ["twitter_thread","tiktok_caption",
            "email_subjects","reddit_post","instagram_caption","linkedin_post"]}


@app.post("/api/repurpose/file")
async def repurpose_file(file_path: str, background_tasks: BackgroundTasks,
                         formats: Optional[str] = None):
    """Repurpose a markdown file from outputs/ into all platform formats."""
    full_path = ROOT / file_path
    if not full_path.exists():
        raise HTTPException(404, f"File not found: {file_path}")

    fmt_list = [f.strip() for f in formats.split(",")] if formats else None

    def _run():
        from core.repurpose import repurpose_file as _repurpose
        result = _repurpose(str(full_path), formats=fmt_list)
        _add_log(f"Repurposed file {file_path} → {len(result.get('formats',{}))} formats", "INFO")

    background_tasks.add_task(_run)
    return {"status": "repurposing", "file": file_path}


# ─── Affiliate Click Tracking ────────────────────────────────────────────────

@app.get("/go/{partner}")
async def affiliate_redirect(partner: str, request: Request):
    """Track affiliate click then redirect to partner URL."""
    from core.click_tracker import record_click
    from fastapi.responses import RedirectResponse
    referrer = request.headers.get("referer", "")
    ip = request.client.host if request.client else ""
    dest = record_click(partner, referrer=referrer, ip=ip)
    if not dest:
        raise HTTPException(404, f"Unknown affiliate partner: {partner}")
    _add_log(f"Affiliate click: {partner}", "INFO")
    return RedirectResponse(url=dest, status_code=302)


@app.get("/api/clicks")
async def get_click_stats():
    """Affiliate click stats — total, by partner, recent 20."""
    from core.click_tracker import get_stats
    return get_stats()


# ─── Blog Command Board ───────────────────────────────────────────────────────

_BLOG_ARTICLES = [
    {"filename":"20260326-10-ai-tools-that-replace-500-month-in-software-subscriptions.html","title":"10 AI Tools That Replace $500/Month in Software Subscriptions","category":"AI Tools","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-5-ai-tools-that-help-you-make-money-while-you-sleep.html","title":"5 AI Tools That Help You Make Money While You Sleep","category":"AI Tools","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-best-beginner-crypto-wallets-2025-safety-guide.html","title":"Best Beginner Crypto Wallets 2025 — Safety Guide","category":"Crypto","date":"2026-03-26","affiliates":["coinbase"]},
    {"filename":"20260326-best-crypto-exchange-for-beginners-in-2025-coinbase-vs-binan.html","title":"Best Crypto Exchange for Beginners in 2025: Coinbase vs Binance","category":"Crypto","date":"2026-03-26","affiliates":["coinbase","robinhood"]},
    {"filename":"20260326-boost-your-crypto-portfolio-with-smart-investing-strategies.html","title":"Boost Your Crypto Portfolio With Smart Investing Strategies","category":"Crypto","date":"2026-03-26","affiliates":["coinbase"]},
    {"filename":"20260326-coinbase-vs-kraken-vs-binance-which-is-best-for-beginners.html","title":"Coinbase vs Kraken vs Binance: Which Is Best for Beginners?","category":"Crypto","date":"2026-03-26","affiliates":["coinbase"]},
    {"filename":"20260326-cryptocurrency-trends-insights-and-opportunities.html","title":"Cryptocurrency Trends, Insights and Opportunities","category":"Crypto","date":"2026-03-26","affiliates":["coinbase"]},
    {"filename":"20260326-latest-in-crypto-news.html","title":"Latest in Crypto News","category":"Crypto","date":"2026-03-26","affiliates":["coinbase"]},
    {"filename":"20260326-dividend-stocks-that-pay-monthly-income-2025.html","title":"Dividend Stocks That Pay Monthly Income 2025","category":"Stocks","date":"2026-03-26","affiliates":["robinhood","amazon"]},
    {"filename":"20260326-how-to-get-a-free-stock-on-robinhood-in-2025-and-what-to-inv.html","title":"How to Get a Free Stock on Robinhood in 2025","category":"Stocks","date":"2026-03-26","affiliates":["robinhood"]},
    {"filename":"20260326-how-to-start-investing-in-etfs-with-100.html","title":"How to Start Investing in ETFs With $100","category":"Stocks","date":"2026-03-26","affiliates":["robinhood","amazon"]},
    {"filename":"20260326-affiliate-campaign-best-investing-apps-with-signup-bonuses-i.html","title":"Best Investing Apps With Signup Bonuses in 2025","category":"Stocks","date":"2026-03-26","affiliates":["robinhood","coinbase"]},
    {"filename":"20260326-exploring-high-ticket-affiliate-programs-maximize-your-earni.html","title":"The Ultimate Guide to High-Ticket Affiliate Programs","category":"Passive Income","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-how-to-build-3-passive-income-streams-in-90-days-starting-wi.html","title":"How to Build 3 Passive Income Streams in 90 Days Starting With $0","category":"Passive Income","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-passive-income-7-passive-income-streams-that-made-real-peopl.html","title":"7 Passive Income Streams That Made Real People $500/Month — With Proof","category":"Passive Income","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-passive-income-how-to-make-500-a-month-in-passive-income-fro.html","title":"How to Make $500 a Month in Passive Income From Home","category":"Passive Income","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260327-best-of-passive-income-march-2026-unlock-financial-freedom-w.html","title":"Best of Passive Income: March 2026 — Unlock Financial Freedom","category":"Passive Income","date":"2026-03-27","affiliates":["amazon"]},
    {"filename":"20260326-side-hustles-that-made-real-people-1-000-month-in-2025-no-ex.html","title":"Side Hustles That Made Real People $1,000+/Month in 2025","category":"Side Hustles","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260326-top-side-hustles-earning-2000-a-month-in-2025.html","title":"Top Side Hustles Earning $2,000 a Month in 2025","category":"Side Hustles","date":"2026-03-26","affiliates":["amazon"]},
    {"filename":"20260327-can-startups-with-no-revenue-still-get-grants-grantwatch.html","title":"Can Startups With No Revenue Still Get Grants?","category":"Side Hustles","date":"2026-03-27","affiliates":["amazon"]},
]

_NETLIFY_BASE = "https://wheellsverse-bots.pages.dev/blog/"

@app.get("/api/blog/articles")
async def blog_articles():
    """Blog Command Board — 20 live articles with per-article click attribution."""
    from core.click_tracker import _load_clicks
    raw_clicks = _load_clicks()
    slug_clicks: Dict[str, int] = {}
    for c in raw_clicks:
        ref = c.get("referrer", "")
        for art in _BLOG_ARTICLES:
            slug = art["filename"].replace(".html", "")
            if slug in ref:
                slug_clicks[slug] = slug_clicks.get(slug, 0) + 1

    cat_counts: Dict[str, int] = {}
    for art in _BLOG_ARTICLES:
        cat_counts[art["category"]] = cat_counts.get(art["category"], 0) + 1
    top_category = max(cat_counts, key=lambda k: cat_counts[k]) if cat_counts else ""

    all_affiliates: set = set()
    for art in _BLOG_ARTICLES:
        all_affiliates.update(art["affiliates"])

    articles = []
    for art in _BLOG_ARTICLES:
        slug = art["filename"].replace(".html", "")
        articles.append({
            "filename":   art["filename"],
            "title":      art["title"],
            "category":   art["category"],
            "date":       art["date"],
            "slug":       slug,
            "url":        _NETLIFY_BASE + art["filename"],
            "affiliates": art["affiliates"],
            "clicks":     slug_clicks.get(slug, 0),
            "status":     "live",
        })

    return {
        "articles":        articles,
        "total":           len(articles),
        "clicks_total":    len(raw_clicks),
        "top_category":    top_category,
        "active_programs": len(all_affiliates),
        "category_counts": cat_counts,
    }


# ─── Reddit Blitz ─────────────────────────────────────────────────────────────

_REDDIT_QUEUE_FILE = Path(__file__).parent.parent / "data" / "reddit_queue.json"


def _load_reddit_queue() -> Dict:
    if _REDDIT_QUEUE_FILE.exists():
        try:
            return json.loads(_REDDIT_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"queue": [], "generated_at": None, "total_posted": 0}


def _save_reddit_queue(data: Dict):
    _REDDIT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REDDIT_QUEUE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _generate_reddit_post(title: str, category: str, url: str) -> Dict:
    """GPT writes a Reddit self-post in personal-story format."""
    cat_map = {
        "Crypto": "crypto",
        "Stocks": "investing",
        "Passive Income": "passive_income",
        "Side Hustles": "side_hustle",
        "AI Tools": "ai_tools",
    }
    niche = cat_map.get(category, "passive_income")
    prompt = (
        f"Write a Reddit self-post for r/{niche} in an honest personal-story format.\n"
        f"Topic: {title}\nBlog URL: {url}\n\n"
        "Rules: No obvious promotion. Start with a personal experience. "
        "Share 3 genuine insights. End with a question to spark discussion. "
        "Mention the blog link naturally as 'I wrote more about this here: [link]'.\n"
        "Return exactly this JSON (no other text):\n"
        '{"reddit_title":"<post title max 200 chars>","body":"<self-post body 150-250 words>","niche":"' + niche + '"}'
    )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.75,
        )
        import re as _re
        raw = resp.choices[0].message.content.strip()
        raw = _re.sub(r"^```json?\s*", "", raw).rstrip("`").strip()
        return json.loads(raw)
    except Exception as e:
        _add_log(f"Reddit post gen failed for {title[:40]}: {e}", "ERROR")
        return {
            "reddit_title": title[:200],
            "body": f"I've been researching {title.lower()} and found some great insights. Here's what I learned:\n\n{url}\n\nWhat's your experience with this?",
            "niche": niche,
        }


@app.get("/api/reddit/blitz/queue")
async def reddit_blitz_queue():
    data = _load_reddit_queue()
    queue = data.get("queue", [])
    arts = [{
        "slug":          item["slug"],
        "title":         item["title"],
        "category":      item.get("category", ""),
        "reddit_title":  item.get("reddit_title", ""),
        "body":          item.get("body", ""),
        "niche":         item.get("niche", ""),
        "status":        item.get("status", "pending"),
        "posted_at":     item.get("posted_at"),
        "reddit_url":    item.get("reddit_url", ""),
        "url":           item.get("url", ""),
    } for item in queue]
    return {
        "articles":     arts,
        "total":        len(arts),
        "pending":      len([a for a in arts if a["status"] == "pending"]),
        "posted":       len([a for a in arts if a["status"] == "posted"]),
        "failed":       len([a for a in arts if a["status"] == "failed"]),
        "generated_at": data.get("generated_at"),
    }


@app.post("/api/reddit/blitz/generate")
async def reddit_blitz_generate(background_tasks: BackgroundTasks):
    existing = {item["slug"] for item in _load_reddit_queue().get("queue", [])}
    new_articles = [a for a in _BLOG_ARTICLES if a["filename"].replace(".html", "") not in existing]
    if not new_articles:
        return {"status": "already_generated", "message": "All articles already have Reddit posts."}

    def _generate_all():
        data = _load_reddit_queue()
        for art in new_articles:
            slug = art["filename"].replace(".html", "")
            url  = _NETLIFY_BASE + art["filename"]
            result = _generate_reddit_post(art["title"], art["category"], url)
            data["queue"].append({
                "slug":         slug,
                "title":        art["title"],
                "category":     art["category"],
                "url":          url,
                "reddit_title": result.get("reddit_title", art["title"]),
                "body":         result.get("body", ""),
                "niche":        result.get("niche", "passive_income"),
                "status":       "pending",
                "posted_at":    None,
                "reddit_url":   "",
            })
            _save_reddit_queue(data)
        data["generated_at"] = datetime.now().isoformat()
        _save_reddit_queue(data)
        _add_log(f"Reddit Blitz: {len(new_articles)} posts generated", "INFO")

    background_tasks.add_task(_generate_all)
    return {"status": "generating", "count": len(new_articles)}


@app.post("/api/reddit/blitz/post-next")
async def reddit_blitz_post_next(count: int = 1):
    from core.reddit import get_reddit
    reddit = get_reddit()
    if not reddit.is_connected():
        raise HTTPException(400, "Reddit not connected — add credentials to .env")

    data = _load_reddit_queue()
    pending = [item for item in data["queue"] if item["status"] == "pending"]
    if not pending:
        return {"status": "empty", "message": "No pending Reddit posts."}

    results = []
    for item in pending[:count]:
        try:
            posts = reddit.post_to_niche(
                title=item["reddit_title"],
                body=item["body"],
                niche=item["niche"],
                delay_seconds=5,
            )
            posted = [p for p in posts if p.get("status") == "posted"]
            item["status"] = "posted" if posted else "failed"
            item["posted_at"] = datetime.now().isoformat()
            item["reddit_url"] = posted[0]["url"] if posted else ""
            data["total_posted"] = data.get("total_posted", 0) + len(posted)
            results.append({"slug": item["slug"], "status": item["status"], "url": item["reddit_url"]})
            _add_log(f"Reddit posted: {item['title'][:50]}", "INFO")
        except Exception as e:
            item["status"] = "failed"
            results.append({"slug": item["slug"], "status": "failed", "error": str(e)})
            _add_log(f"Reddit post failed: {item['title'][:40]} — {e}", "ERROR")
        _save_reddit_queue(data)

    return {"posted": len([r for r in results if r["status"] == "posted"]),
            "failed":  len([r for r in results if r["status"] == "failed"]),
            "results": results}


@app.post("/api/reddit/blitz/reset/{slug}")
async def reddit_blitz_reset(slug: str):
    data = _load_reddit_queue()
    for item in data["queue"]:
        if item["slug"] == slug:
            item["status"] = "pending"
            item["posted_at"] = None
            item["reddit_url"] = ""
            _save_reddit_queue(data)
            return {"status": "reset", "slug": slug}
    raise HTTPException(404, f"Slug not found: {slug}")


def _reddit_scheduled_post(count: int = 1) -> None:
    """Sync helper called by scheduler to post N pending Reddit posts."""
    try:
        from core.reddit import get_reddit
        reddit = get_reddit()
        if not reddit.is_connected():
            _add_log("Reddit auto-post skipped — not connected", "WARNING")
            return
        data = _load_reddit_queue()
        pending = [item for item in data["queue"] if item["status"] == "pending"]
        if not pending:
            _add_log("Reddit auto-post: no pending posts", "INFO")
            return
        for item in pending[:count]:
            try:
                posts = reddit.post_to_niche(title=item["reddit_title"], body=item["body"],
                                             niche=item["niche"], delay_seconds=5)
                posted = [p for p in posts if p.get("status") == "posted"]
                item["status"] = "posted" if posted else "failed"
                item["posted_at"] = datetime.now().isoformat()
                item["reddit_url"] = posted[0]["url"] if posted else ""
                _add_log(f"Reddit auto-post ✅ {item['title'][:50]}", "INFO")
            except Exception as e:
                item["status"] = "failed"
                _add_log(f"Reddit auto-post ❌ {item['title'][:40]} — {e}", "ERROR")
            _save_reddit_queue(data)
    except Exception as e:
        _add_log(f"Reddit scheduled post error: {e}", "ERROR")


# ─── Google Search Console ────────────────────────────────────────────────────

@app.get("/api/gsc/status")
async def gsc_status():
    from core.gsc import get_gsc
    return get_gsc().get_status()


@app.get("/api/gsc/data")
async def gsc_data(days: int = 28):
    from core.gsc import get_gsc
    gsc = get_gsc()
    if not gsc.is_connected():
        return {"error": "GSC not connected", "setup": gsc.get_status().get("setup_steps", [])}
    try:
        return {
            "summary":     gsc.get_summary(days=days),
            "top_queries": gsc.get_top_queries(days=days),
            "top_pages":   gsc.get_top_pages(days=days),
            "property":    gsc.property_url,
        }
    except Exception as e:
        raise HTTPException(500, f"GSC API error: {e}")


@app.post("/api/gsc/submit-sitemap")
async def gsc_submit_sitemap():
    from core.gsc import get_gsc
    gsc = get_gsc()
    if not gsc.is_connected():
        raise HTTPException(400, "GSC not connected")
    try:
        return gsc.submit_sitemap()
    except Exception as e:
        raise HTTPException(500, f"Sitemap submit error: {e}")


# ─── Telegram Alerts ─────────────────────────────────────────────────────────

@app.post("/api/telegram/alerts/daily")
async def telegram_daily_alert():
    """Send a daily revenue + activity summary to Telegram."""
    from core.telegram import notify
    from core.impact import get_earnings
    try:
        earn = get_earnings(days=1)
        today_earned = earn.get("total_earned", 0)
    except Exception:
        today_earned = 0

    try:
        earn7 = get_earnings(days=7)
        week_earned = earn7.get("total_earned", 0)
    except Exception:
        week_earned = 0

    blog_dir = ROOT / "frontend" / "blog"
    article_count = max(0, len(list(blog_dir.glob("*.html"))) - 1) if blog_dir.exists() else 0

    try:
        from core.click_tracker import _load_clicks
        clicks_today = sum(1 for c in _load_clicks()
                           if c.get("timestamp", "")[:10] == datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        clicks_today = 0

    msg = (
        f"📊 <b>WheellsVerse Daily Summary</b>\n"
        f"📅 {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"💰 Today's Earnings: <b>${today_earned:.2f}</b>\n"
        f"📈 7-Day Total: <b>${week_earned:.2f}</b>\n"
        f"🖱 Affiliate Clicks Today: <b>{clicks_today}</b>\n"
        f"📝 Blog Articles Live: <b>{article_count}</b>\n\n"
        f"🌐 <a href='https://wheellsverse-bots.pages.dev'>View Blog</a>"
    )
    ok = notify(msg)
    if ok:
        return {"status": "sent", "message": msg[:100]}
    raise HTTPException(400, "Telegram not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")


@app.get("/api/telegram/alerts/config")
async def telegram_alerts_config():
    from core.telegram import get_notifier
    status = get_notifier().get_status()
    return {
        **status,
        "scheduled_alerts": [
            {"event": "Daily Summary",     "time": "07:00",         "active": status.get("connected", False)},
            {"event": "Publish Complete",  "time": "after publish", "active": True},
            {"event": "New Blog Article",  "time": "on publish",    "active": True},
        ],
    }


# ─── Blog Email Capture Injection ────────────────────────────────────────────

_CAPTURE_FORM_HTML = """\
<div style="background:linear-gradient(135deg,#0d0f14,#1a1a2e);border:1px solid #00d4ff;border-radius:12px;padding:28px 32px;margin:40px 0;text-align:center">
  <h3 style="color:#00d4ff;margin:0 0 8px;font-size:1.3em">📬 Get Free Weekly Money Tips</h3>
  <p style="color:#ccc;margin:0 0 20px;font-size:14px">Join thousands of readers getting passive income strategies every Monday. Free.</p>
  <form id="wv-capture" onsubmit="wvSubscribe(event)" style="display:flex;gap:10px;max-width:420px;margin:0 auto;flex-wrap:wrap;justify-content:center">
    <input type="email" id="wv-email" placeholder="your@email.com" required
           style="flex:1;min-width:200px;padding:12px 16px;border-radius:8px;border:1px solid #00d4ff;background:#0d0f14;color:#fff;font-size:14px;outline:none">
    <button type="submit" id="wv-btn"
            style="background:#00d4ff;color:#000;padding:12px 22px;border-radius:8px;border:none;font-weight:700;cursor:pointer;font-size:14px">
      Subscribe →
    </button>
  </form>
  <p id="wv-msg" style="color:#00ff88;margin:12px 0 0;display:none;font-weight:600">✅ You are in! Check your inbox.</p>
  <p style="color:#666;font-size:11px;margin:10px 0 0">No spam. Unsubscribe any time.</p>
</div>
<script>
async function wvSubscribe(e){
  e.preventDefault();
  var btn=document.getElementById('wv-btn');
  btn.textContent='...';btn.disabled=true;
  try{
    await fetch('/.netlify/functions/subscribe',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:document.getElementById('wv-email').value})
    });
    document.getElementById('wv-capture').style.display='none';
    document.getElementById('wv-msg').style.display='block';
  }catch(err){btn.textContent='Subscribe →';btn.disabled=false;}
}
</script>"""


@app.post("/api/blog/inject-capture-form")
async def inject_capture_form():
    """Inject email capture form into all existing blog articles that don't have it yet."""
    blog_dir = ROOT / "frontend" / "blog"
    if not blog_dir.exists():
        raise HTTPException(404, "Blog directory not found")

    injected = []
    skipped  = []
    errors   = []

    for html_file in blog_dir.glob("*.html"):
        if html_file.name == "index.html":
            continue
        try:
            content = html_file.read_text(encoding="utf-8")
            if "wv-capture" in content or "wvSubscribe" in content:
                skipped.append(html_file.name)
                continue
            # Inject before </footer> or before </body>
            if "<footer" in content:
                content = content.replace("<footer", _CAPTURE_FORM_HTML + "\n<footer", 1)
            elif "</body>" in content:
                content = content.replace("</body>", _CAPTURE_FORM_HTML + "\n</body>", 1)
            else:
                content += "\n" + _CAPTURE_FORM_HTML
            html_file.write_text(content, encoding="utf-8")
            injected.append(html_file.name)
        except Exception as e:
            errors.append(f"{html_file.name}: {e}")

    _add_log(f"Email capture form injected into {len(injected)} articles", "INFO")
    return {"injected": len(injected), "skipped": len(skipped), "errors": errors,
            "files": injected}


# ─── TikTok Blitz ─────────────────────────────────────────────────────────────

_TIKTOK_BLITZ_FILE = Path(__file__).parent.parent / "data" / "tiktok_queue.json"


def _load_tiktok_queue() -> Dict:
    if _TIKTOK_BLITZ_FILE.exists():
        try:
            return json.loads(_TIKTOK_BLITZ_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"queue": [], "generated_at": None, "total_done": 0}


def _save_tiktok_queue(data: Dict):
    _TIKTOK_BLITZ_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TIKTOK_BLITZ_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _generate_tiktok_script(title: str, category: str, url: str,
                             affiliates: List[str]) -> Dict:
    """GPT generates a 60-second TikTok script for a blog article."""
    aff_line = ""
    if "coinbase" in affiliates:
        aff_line += " Sign up to Coinbase and earn free Bitcoin."
    if "robinhood" in affiliates:
        aff_line += " Get a free stock on Robinhood."
    if "amazon" in affiliates:
        aff_line += " Shop the best tools on Amazon."
    prompt = (
        f"Write a punchy 60-second TikTok video script for this blog article.\n"
        f"Title: {title}\nCategory: {category}\nURL: {url}\n"
        f"Affiliate CTAs to weave in:{aff_line if aff_line else ' none'}\n\n"
        "Return exactly this JSON (no other text):\n"
        '{"hook":"<15-second attention-grabbing opening line>","script":"<45-second main content, 3-4 sentences>","caption":"<TikTok caption max 150 chars with emoji>","hashtags":["<tag1>","<tag2>","<tag3>","<tag4>","<tag5>"]}'
    )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.8,
        )
        import re as _re
        raw = resp.choices[0].message.content.strip()
        raw = _re.sub(r"^```json?\s*", "", raw).rstrip("`").strip()
        return json.loads(raw)
    except Exception as e:
        _add_log(f"TikTok script gen failed for {title[:40]}: {e}", "ERROR")
        return {
            "hook": f"Did you know {title[:60]}?",
            "script": f"Here's what you need to know about {title}. Visit the link in bio to read more.",
            "caption": f"{title[:100]} #passiveincome #financetips",
            "hashtags": ["#passiveincome", "#financetips", "#crypto", "#investing", "#sidehustle"],
        }


@app.get("/api/tiktok/blitz/queue")
async def tiktok_blitz_queue():
    data = _load_tiktok_queue()
    queue = data.get("queue", [])
    arts = []
    for item in queue:
        arts.append({
            "slug":     item["slug"],
            "title":    item["title"],
            "category": item.get("category", ""),
            "date":     item.get("date", ""),
            "url":      item.get("url", ""),
            "status":   item.get("status", "pending"),
            "hook":     item.get("hook", ""),
            "script":   item.get("script", ""),
            "caption":  item.get("caption", ""),
            "hashtags": item.get("hashtags", []),
            "done_at":  item.get("done_at"),
        })
    pending = len([a for a in arts if a["status"] == "pending"])
    done    = len([a for a in arts if a["status"] == "done"])
    return {
        "articles":    arts,
        "total":       len(arts),
        "pending":     pending,
        "done":        done,
        "generated_at": data.get("generated_at"),
    }


@app.post("/api/tiktok/blitz/generate")
async def tiktok_blitz_generate(background_tasks: BackgroundTasks):
    """Generate TikTok scripts for all 20 blog articles (background task)."""
    existing = {item["slug"] for item in _load_tiktok_queue().get("queue", [])}
    new_articles = [a for a in _BLOG_ARTICLES if a["filename"].replace(".html", "") not in existing]
    if not new_articles:
        return {"status": "already_generated", "message": "All articles already have scripts."}

    def _generate_all():
        data = _load_tiktok_queue()
        for art in new_articles:
            slug = art["filename"].replace(".html", "")
            url  = _NETLIFY_BASE + art["filename"]
            _add_log(f"TikTok script generating: {art['title'][:50]}", "INFO")
            scripts = _generate_tiktok_script(art["title"], art["category"], url, art["affiliates"])
            data["queue"].append({
                "slug":     slug,
                "title":    art["title"],
                "category": art["category"],
                "date":     art["date"],
                "url":      url,
                "status":   "pending",
                "hook":     scripts.get("hook", ""),
                "script":   scripts.get("script", ""),
                "caption":  scripts.get("caption", ""),
                "hashtags": scripts.get("hashtags", []),
                "done_at":  None,
            })
            _save_tiktok_queue(data)
        data["generated_at"] = datetime.now().isoformat()
        _save_tiktok_queue(data)
        _add_log(f"TikTok Blitz: {len(new_articles)} scripts generated", "INFO")

    background_tasks.add_task(_generate_all)
    return {"status": "generating", "count": len(new_articles),
            "message": f"Generating {len(new_articles)} TikTok scripts in background."}


@app.post("/api/tiktok/blitz/done/{slug}")
async def tiktok_blitz_done(slug: str):
    """Mark a script as recorded / done."""
    data = _load_tiktok_queue()
    for item in data["queue"]:
        if item["slug"] == slug:
            item["status"] = "done"
            item["done_at"] = datetime.now().isoformat()
            _save_tiktok_queue(data)
            return {"status": "done", "slug": slug}
    raise HTTPException(404, f"Slug not found: {slug}")


@app.post("/api/tiktok/blitz/reset/{slug}")
async def tiktok_blitz_reset(slug: str):
    """Reset a done script back to pending."""
    data = _load_tiktok_queue()
    for item in data["queue"]:
        if item["slug"] == slug:
            item["status"] = "pending"
            item["done_at"] = None
            _save_tiktok_queue(data)
            return {"status": "reset", "slug": slug}
    raise HTTPException(404, f"Slug not found: {slug}")


# ─── Publish Log ──────────────────────────────────────────────────────────────

@app.get("/api/publish/log")
async def get_publish_log(lines: int = 50):
    """Return the last N lines from the daily publish log as structured entries."""
    log_file = ROOT / "logs" / "daily_publish.log"
    entries = []
    if log_file.exists():
        try:
            raw_lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in raw_lines[-lines:]:
                # Format: 2026-03-27 08:00:01 [INFO] message
                parts = line.split(" ", 3)
                if len(parts) >= 4:
                    entries.append({
                        "ts":      parts[0] + " " + parts[1],
                        "level":   parts[2].strip("[]"),
                        "message": parts[3],
                    })
                elif line.strip():
                    entries.append({"ts": "", "level": "INFO", "message": line.strip()})
        except Exception as e:
            entries = [{"ts": "", "level": "ERROR", "message": str(e)}]
    # Article count from frontend/blog/
    blog_dir = ROOT / "frontend" / "blog"
    article_count = len(list(blog_dir.glob("*.html"))) - 1 if blog_dir.exists() else 0  # -1 for index.html
    return {
        "entries":       entries[-lines:],
        "log_path":      str(log_file),
        "article_count": max(0, article_count),
        "topic_pool":    len([
            ("specialized/74_passive_income_bot", ""), ("specialized/71_crypto_content_creator", ""),
            ("specialized/72_stock_investing_content_creator", ""), ("specialized/78_side_hustle_affiliate_bot", ""),
            ("specialized/77_ai_tools_affiliate_bot", ""), ("specialized/82_high_ticket_affiliate_bot", ""),
        ]) * 4,  # approx pool size
        "daily_publish_time": os.getenv("DAILY_PUBLISH_TIME", "08:00"),
        "posts_per_run":      int(os.getenv("DAILY_POSTS_COUNT", "5")),
    }


# ─── Newsletter Bot ───────────────────────────────────────────────────────────

_NEWSLETTER_LOG_FILE = Path(__file__).parent.parent / "data" / "newsletter_log.json"


def _load_newsletter_log() -> List[Dict]:
    if _NEWSLETTER_LOG_FILE.exists():
        try:
            return json.loads(_NEWSLETTER_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@app.get("/api/newsletter/history")
async def newsletter_history():
    """Return last 10 newsletter drafts."""
    return {"history": _load_newsletter_log()[-10:]}


@app.post("/api/newsletter/generate")
async def generate_newsletter():
    """GPT writes a weekly digest email and creates a ConvertKit broadcast draft."""
    from core.convertkit import get_convertkit
    from core.impact import get_earnings

    ck = get_convertkit()
    # Revenue snapshot
    try:
        rev = get_earnings(days=7)
        earned_7d = rev.get("total_earned", 0)
    except Exception:
        earned_7d = 0

    # Top 5 latest articles
    top_articles = _BLOG_ARTICLES[-5:]
    art_lines = "\n".join(
        f"- [{a['title']}]({_NETLIFY_BASE + a['filename']}) ({a['category']})"
        for a in top_articles
    )
    today = datetime.now().strftime("%B %d, %Y")
    prompt = (
        f"Write a short, punchy email newsletter for WheellsVerse subscribers.\n"
        f"Brand: WheellsVerse | Author: J.K. Blaze | Date: {today}\n"
        f"Weekly affiliate revenue: ${earned_7d:.2f}\n"
        f"Featured articles this week:\n{art_lines}\n\n"
        "Write an HTML email body (no <html>/<head> tags — just <body> content) with:\n"
        "1. A catchy subject line (first line, prefixed 'SUBJECT: ')\n"
        "2. 2-3 short paragraphs with financial/crypto/passive income insights\n"
        "3. 3 featured article links with 1-line descriptions\n"
        "4. A CTA to join Robinhood or Coinbase\n"
        "5. Branded footer\n"
        "Keep it under 400 words. Use inline CSS. Make it look premium."
    )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200, temperature=0.7,
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(500, f"GPT error: {e}")

    # Extract subject from first line
    subject = f"WheellsVerse Weekly — {today}"
    lines = raw.split("\n")
    if lines[0].upper().startswith("SUBJECT:"):
        subject = lines[0].split(":", 1)[1].strip()
        raw = "\n".join(lines[1:]).strip()

    # Create ConvertKit draft
    ck_result = {}
    ck_id = None
    if ck.is_connected():
        try:
            ck_result = ck.create_broadcast(subject=subject, content=raw)
            ck_id = ck_result.get("broadcast", {}).get("id")
        except Exception as e:
            ck_result = {"error": str(e)}

    # Log it
    log = _load_newsletter_log()
    log.append({
        "date":       today,
        "subject":    subject,
        "ck_id":      ck_id,
        "ck_status":  "draft" if ck_id else ck_result.get("status", "not_created"),
        "preview":    raw[:300],
        "html":       raw,
        "earned_7d":  earned_7d,
    })
    _NEWSLETTER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _NEWSLETTER_LOG_FILE.write_text(json.dumps(log[-50:], indent=2, ensure_ascii=False))
    _add_log(f"Newsletter generated: {subject}", "INFO")
    return {
        "subject":    subject,
        "html":       raw,
        "ck_id":      ck_id,
        "ck_status":  ck_result.get("status", ""),
        "ck_message": ck_result.get("message", ""),
        "earned_7d":  earned_7d,
    }


# ─── Revenue Tracker V2 ───────────────────────────────────────────────────────

@app.get("/api/revenue/v2")
async def revenue_v2():
    """Enhanced revenue endpoint: Impact + click tracker + sparklines + goal tracking."""
    from core.impact import get_earnings
    from core.click_tracker import _load_clicks

    # Impact data
    try:
        earn30 = get_earnings(days=30)
        earn7  = get_earnings(days=7)
        earn1  = get_earnings(days=1)
    except Exception as e:
        earn30 = earn7 = earn1 = {"error": str(e), "total_earned": 0, "by_program": {}, "by_day": {}}

    # Build 14-day daily chart
    from datetime import timedelta
    today = datetime.now()
    daily_chart = []
    by_day = earn30.get("by_day", {})
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_chart.append({"date": d, "earned": round(by_day.get(d, 0.0), 2)})

    # Goal tracking ($500/month target)
    earned_7d     = earn7.get("total_earned", 0)
    earned_today  = earn1.get("total_earned", 0)
    projection_30 = round(earned_7d / 7 * 30, 2) if earned_7d > 0 else 0
    goal          = float(os.getenv("REVENUE_GOAL", "500"))
    goal_pct      = min(100, round(projection_30 / goal * 100, 1)) if goal > 0 else 0

    # Click tracker — local affiliate link clicks per article
    try:
        raw_clicks = _load_clicks()
        tracker_total = len(raw_clicks)
        tracker_today = sum(1 for c in raw_clicks
                            if c.get("timestamp", "")[:10] == today.strftime("%Y-%m-%d"))
    except Exception:
        tracker_total = tracker_today = 0

    # Per-program cards with program metadata
    PROGRAM_META = {
        "coinbase":  {"icon": "₿",  "color": "#00d4ff", "target": 200},
        "robinhood": {"icon": "📈", "color": "#00ff88", "target": 150},
        "amazon":    {"icon": "📚", "color": "#ffd700", "target": 150},
    }
    by_program = earn30.get("by_program", {})
    programs = []
    for name, meta in PROGRAM_META.items():
        earned = 0.0
        for prog_name, amount in by_program.items():
            if name.lower() in prog_name.lower():
                earned += amount
        pct = min(100, round(earned / meta["target"] * 100, 1)) if meta["target"] > 0 else 0
        programs.append({
            "name":    name.title(),
            "icon":    meta["icon"],
            "color":   meta["color"],
            "earned":  round(earned, 2),
            "target":  meta["target"],
            "pct":     pct,
        })

    return {
        "today":           round(earned_today, 2),
        "this_week":       round(earned_7d, 2),
        "this_month":      round(earn30.get("total_earned", 0), 2),
        "projection_30d":  projection_30,
        "goal":            goal,
        "goal_pct":        goal_pct,
        "daily_chart":     daily_chart,
        "programs":        programs,
        "tracker_clicks":  tracker_total,
        "tracker_today":   tracker_today,
        "pending":         earn30.get("pending", 0),
        "locked":          earn30.get("locked", 0),
        "top_programs":    by_program,
        "fetched_at":      datetime.now().isoformat(),
    }


# ─── Content Performance ──────────────────────────────────────────────────────

@app.post("/api/performance/refresh")
async def refresh_performance(background_tasks: BackgroundTasks):
    """Pull Twitter engagement metrics + click data → update intelligence.json."""
    def _run():
        from core.performance import refresh_performance as _refresh
        result = _refresh()
        _add_log(
            f"Performance refreshed — {result['tweets_tracked']} tweets, "
            f"{result['topics_scored']} topics scored",
            "INFO",
        )
    background_tasks.add_task(_run)
    return {"status": "refreshing"}


@app.get("/api/performance")
async def get_performance():
    """Latest performance data — top topics, tweet metrics, affiliate clicks."""
    from core.performance import _load_json, PERF_FILE, INTELLIGENCE_FILE
    perf  = _load_json(PERF_FILE, {})
    intel = _load_json(INTELLIGENCE_FILE, {})
    return {
        "top_topics":      intel.get("top_topics", []),
        "topic_scores":    dict(list(sorted(
            intel.get("topic_scores", {}).items(),
            key=lambda x: x[1], reverse=True
        ))[:20]),
        "tweets_tracked":  len(perf.get("tweets", {})),
        "affiliate_clicks": intel.get("affiliate_clicks", {}),
        "updated_at":      intel.get("performance_updated", "never"),
    }


# ─── Ads Board ────────────────────────────────────────────────────────────────

_ADS_FILE = ROOT / "data" / "ads_queue.json"

def _load_ads() -> dict:
    if _ADS_FILE.exists():
        try:
            return json.loads(_ADS_FILE.read_text())
        except Exception:
            pass
    return {"queue": [], "updated_at": None}

def _save_ads(data: dict):
    _ADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    _ADS_FILE.write_text(json.dumps(data, indent=2))

def _generate_ad_copy(product: str, ad_type: str, cta_url: str, tone: str, platform: str) -> str:
    """Use OpenAI to generate platform-tailored ad copy."""
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")

    platform_guides = {
        "twitter":    "Max 280 chars. Hook first. Add 2-3 hashtags. Include CTA link.",
        "reddit":     "No hard selling. Write as a helpful community post. 2-3 sentences + link. Use subreddit-style casual tone.",
        "tiktok":     "Hook in first 3 words. Viral energy. 3-5 punchy lines + hashtags. Emoji-friendly.",
        "facebook":   "Conversational. 2-4 sentences with a value proposition. End with a question or CTA.",
        "instagram":  "Visual storytelling tone. 3-4 lines + 5-10 hashtags. Use emojis naturally.",
        "linkedin":   "Professional. Insight-driven. 3-5 lines with stats or a bold claim. CTA at end.",
        "forum":      "Helpful and non-promotional. Provide value first, mention product naturally. 3-4 sentences.",
        "blog":       "SEO-friendly paragraph. 50-80 words. Include the CTA as an inline hyperlink anchor text.",
        "email":      "Subject line + 3-4 sentence body. Personalized opener. Clear CTA button text at the end.",
        "telegram":   "Short and punchy. 2-3 lines. Bold key phrase. Link at end.",
    }

    guide = platform_guides.get(platform, "Write a concise, compelling ad. Include CTA link.")
    prompt = (
        f"Write a {tone} ad for: {product}\n"
        f"Ad type: {ad_type}\n"
        f"CTA URL: {cta_url}\n"
        f"Platform: {platform.upper()} — {guide}\n"
        f"Brand: WheellsVerse (AI tools, crypto, passive income niche)\n"
        f"Return ONLY the ad copy, no labels or explanation."
    )

    resp = openai.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.85,
    )
    return resp.choices[0].message.content.strip()


class AdsGenerateRequest(BaseModel):
    product: str
    ad_type: str = "affiliate"          # affiliate | product | content
    cta_url: str = ""
    tone: str = "bold"                  # bold | professional | casual | urgent
    platforms: List[str] = ["twitter", "reddit", "tiktok", "facebook", "instagram", "linkedin", "forum", "blog", "email", "telegram"]


class AdsDeployRequest(BaseModel):
    slug: str


@app.get("/api/ads/queue")
async def get_ads_queue():
    return _load_ads()


@app.post("/api/ads/generate")
async def ads_generate(req: AdsGenerateRequest, background_tasks: BackgroundTasks):
    """Generate platform-specific ad copies in background."""
    import uuid
    batch_id = uuid.uuid4().hex[:8]

    def _run():
        d = _load_ads()
        for platform in req.platforms:
            slug = f"{batch_id}-{platform}"
            try:
                copy = _generate_ad_copy(req.product, req.ad_type, req.cta_url, req.tone, platform)
                d["queue"].append({
                    "slug":        slug,
                    "batch_id":    batch_id,
                    "product":     req.product,
                    "ad_type":     req.ad_type,
                    "platform":    platform,
                    "cta_url":     req.cta_url,
                    "tone":        req.tone,
                    "copy":        copy,
                    "status":      "ready",
                    "deployed_at": None,
                    "result":      None,
                    "created_at":  datetime.now().isoformat(),
                })
                _save_ads(d)
                _add_log(f"Ad generated [{platform}]: {req.product[:40]}", "INFO")
            except Exception as e:
                _add_log(f"Ad gen failed [{platform}]: {e}", "ERROR")

    background_tasks.add_task(_run)
    return {
        "status":    "generating",
        "batch_id":  batch_id,
        "platforms": req.platforms,
        "message":   f"Generating {len(req.platforms)} ads in background. Check /api/ads/queue.",
    }


@app.post("/api/ads/deploy")
async def ads_deploy(req: AdsDeployRequest, background_tasks: BackgroundTasks):
    """Deploy a single ad by slug to its target platform."""
    d = _load_ads()
    item = next((x for x in d["queue"] if x["slug"] == req.slug), None)
    if not item:
        raise HTTPException(404, "Ad not found")
    if item["status"] == "deployed":
        return {"status": "already_deployed"}

    def _deploy(item, d):
        platform = item["platform"]
        copy     = item["copy"]
        result   = {"status": "unsupported"}
        try:
            if platform == "twitter":
                from core.twitter import get_twitter
                tw = get_twitter()
                if tw.is_connected():
                    r = tw.post_tweet(copy[:280])
                    result = {"status": "posted", "url": r.get("url", "")}
                else:
                    result = {"status": "not_connected"}

            elif platform == "reddit":
                from core.reddit import get_reddit
                rd = get_reddit()
                subreddit = "passive_income"
                if rd.is_connected():
                    r = rd.submit_text(subreddit, item["product"], copy)
                    result = {"status": "posted", "url": r.get("url", "")}
                else:
                    result = {"status": "not_connected"}

            elif platform == "telegram":
                from core.telegram import get_notifier
                tg = get_notifier()
                if tg.is_connected():
                    tg.send_message(copy)
                    result = {"status": "sent"}
                else:
                    result = {"status": "not_connected"}

            elif platform == "blog":
                from core.publish_pipeline import get_publisher
                pp = get_publisher()
                r = pp.publish(item["product"] + " — Sponsored", copy, platforms=["blog"])
                result = {"status": "published", "results": r}

            elif platform == "email":
                from core.convertkit import get_convertkit
                ck = get_convertkit()
                if ck.is_connected():
                    r = ck.create_broadcast(
                        subject=f"[Ad] {item['product']}",
                        content=copy,
                        description=f"Ad campaign — {item['product']}",
                    )
                    result = {"status": "draft_created", "id": r.get("broadcast", {}).get("id")}
                else:
                    result = {"status": "not_connected"}

            else:
                # Facebook, Instagram, LinkedIn, Forum, TikTok — copy ready, paste manually
                result = {"status": "ready_to_post", "note": "Copy ready — paste manually or connect API"}

        except Exception as e:
            result = {"status": "error", "error": str(e)}
            _add_log(f"Ad deploy failed [{platform}]: {e}", "ERROR")

        # Update queue
        d2 = _load_ads()
        for x in d2["queue"]:
            if x["slug"] == item["slug"]:
                x["status"] = "deployed" if result.get("status") in ("posted", "sent", "published", "draft_created", "ready_to_post") else "failed"
                x["deployed_at"] = datetime.now().isoformat()
                x["result"] = result
                break
        _save_ads(d2)
        _add_log(f"Ad deployed [{platform}]: {result['status']}", "INFO")

    background_tasks.add_task(_deploy, item, d)
    return {"status": "deploying", "slug": req.slug, "platform": item["platform"]}


@app.post("/api/ads/deploy-all")
async def ads_deploy_all(background_tasks: BackgroundTasks):
    """Deploy all ready ads in the queue."""
    d = _load_ads()
    ready = [x for x in d["queue"] if x["status"] == "ready"]
    if not ready:
        return {"status": "nothing_to_deploy", "message": "No ready ads in queue."}

    def _run_all():
        for item in ready:
            # inline deploy logic per item
            platform = item["platform"]
            copy     = item["copy"]
            result   = {"status": "unsupported"}
            try:
                if platform == "twitter":
                    from core.twitter import get_twitter
                    tw = get_twitter()
                    if tw.is_connected():
                        r = tw.post_tweet(copy[:280])
                        result = {"status": "posted", "url": r.get("url", "")}
                    else:
                        result = {"status": "not_connected"}
                elif platform == "reddit":
                    from core.reddit import get_reddit
                    rd = get_reddit()
                    if rd.is_connected():
                        r = rd.submit_text("passive_income", item["product"], copy)
                        result = {"status": "posted", "url": r.get("url", "")}
                    else:
                        result = {"status": "not_connected"}
                elif platform == "telegram":
                    from core.telegram import get_notifier
                    tg = get_notifier()
                    if tg.is_connected():
                        tg.send_message(copy)
                        result = {"status": "sent"}
                    else:
                        result = {"status": "not_connected"}
                elif platform == "blog":
                    from core.publish_pipeline import get_publisher
                    pp = get_publisher()
                    r = pp.publish(item["product"] + " — Ad", copy, platforms=["blog"])
                    result = {"status": "published"}
                elif platform == "email":
                    from core.convertkit import get_convertkit
                    ck = get_convertkit()
                    if ck.is_connected():
                        r = ck.create_broadcast(subject=f"[Ad] {item['product']}", content=copy)
                        result = {"status": "draft_created"}
                    else:
                        result = {"status": "not_connected"}
                else:
                    result = {"status": "ready_to_post"}
            except Exception as e:
                result = {"status": "error", "error": str(e)}

            d2 = _load_ads()
            for x in d2["queue"]:
                if x["slug"] == item["slug"]:
                    x["status"] = "deployed" if result.get("status") in ("posted", "sent", "published", "draft_created", "ready_to_post") else "failed"
                    x["deployed_at"] = datetime.now().isoformat()
                    x["result"] = result
                    break
            _save_ads(d2)
            _add_log(f"Batch ad deployed [{platform}]: {result['status']}", "INFO")

    background_tasks.add_task(_run_all)
    return {"status": "deploying_all", "count": len(ready)}


@app.delete("/api/ads/queue")
async def ads_clear_queue():
    _save_ads({"queue": []})
    return {"status": "cleared"}


# ─── Publisher Engine ─────────────────────────────────────────────────────────

class PublisherEngineRunRequest(BaseModel):
    manuscript: str
    title: str
    genre: str = "mystery"
    author: str = "J.K. Blaze"
    skip_agents: list = []


@app.get("/api/publisher-engine/status")
async def publisher_engine_status():
    """Return current publisher engine status."""
    from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
    return PublisherEnginePipeline()._load_status()


@app.get("/api/publisher-engine/results")
async def publisher_engine_results(limit: int = 20):
    """Return recent publisher engine run results."""
    from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
    results = PublisherEnginePipeline()._load_results()
    return {"results": results[:limit]}


@app.post("/api/publisher-engine/run")
async def publisher_engine_run(req: PublisherEngineRunRequest):
    """Run a manuscript through the full 7-agent publisher engine."""
    from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
    result = await asyncio.to_thread(
        PublisherEnginePipeline().process,
        manuscript=req.manuscript,
        title=req.title,
        genre=req.genre,
        author=req.author,
        skip_agents=req.skip_agents,
    )
    return result


# ─── Literary QC ──────────────────────────────────────────────────────────────

class LiteraryQCRequest(BaseModel):
    manuscript: str
    title: str
    genre: str = "mystery"
    vol1_bible: dict = None
    manuscript_path: str = ""


@app.get("/api/literary-qc/results")
async def literary_qc_results(limit: int = 50):
    """Return recent literary QC results."""
    from core.literary_qc import LiteraryQCAgent
    results = LiteraryQCAgent()._load_results()
    return {"results": results[:limit]}


@app.get("/api/literary-qc/rewrite-queue")
async def literary_qc_rewrite_queue():
    """Return manuscripts queued for rewrite."""
    from core.literary_qc import QC_RESULTS_FILE
    import json
    if QC_RESULTS_FILE.exists():
        all_results = json.loads(QC_RESULTS_FILE.read_text())
        queue = [r for r in all_results if r.get("rewrite_needed")]
    else:
        queue = []
    return {"queue": queue}


@app.post("/api/literary-qc/review")
async def literary_qc_review(req: LiteraryQCRequest):
    """Run a manuscript through literary QC review passes."""
    from core.literary_qc import LiteraryQCAgent
    result = await asyncio.to_thread(
        LiteraryQCAgent().review_manuscript,
        manuscript=req.manuscript,
        title=req.title,
        vol1_bible=req.vol1_bible,
        genre=req.genre,
    )
    return result


@app.post("/api/literary-qc/full-analysis")
async def literary_qc_full_analysis(req: LiteraryQCRequest):
    """Run a full literary analysis including chapter count and structure."""
    from core.literary_qc import LiteraryQCAgent
    result = await asyncio.to_thread(
        LiteraryQCAgent().full_book_analysis,
        manuscript=req.manuscript,
        title=req.title,
        genre=req.genre,
        vol1_bible=req.vol1_bible,
        manuscript_path=req.manuscript_path,
    )
    return result


# ─── Volume Completion ────────────────────────────────────────────────────────

@app.get("/api/volumes/status")
async def volumes_status():
    """Return volume scan/completion status summary."""
    from bots.books.volume_completion_bot import SCAN_FILE
    import json
    if SCAN_FILE.exists():
        data = json.loads(SCAN_FILE.read_text())
    else:
        data = {}
    return {"status": "ok", "scan": data}


@app.get("/api/volumes/scan")
async def volumes_scan():
    """Scan all manuscript outputs and identify incomplete volumes."""
    from bots.books.volume_completion_bot import VolumeCompletionBot
    result = await asyncio.to_thread(VolumeCompletionBot().scan_all_manuscripts)
    return result


@app.post("/api/volumes/complete")
async def volumes_complete(request: Request):
    """Complete a specific incomplete volume."""
    body = await request.json()
    file_path = body.get("file")
    if not file_path:
        raise HTTPException(status_code=422, detail="'file' field is required")
    from bots.books.volume_completion_bot import VolumeCompletionBot
    result = await asyncio.to_thread(
        VolumeCompletionBot().complete_volume, file_path
    )
    return result


# ─── Continuity Engine ────────────────────────────────────────────────────────

class ContinuityExtractRequest(BaseModel):
    manuscript_path: str


class ContinuityCheckRequest(BaseModel):
    vol1_path: str
    vol2_path: str


@app.post("/api/continuity/extract-bible")
async def continuity_extract_bible(req: ContinuityExtractRequest):
    """Extract a story bible from a manuscript file."""
    from core.continuity_engine import ContinuityEngine
    result = await asyncio.to_thread(
        ContinuityEngine().extract_from_file, req.manuscript_path
    )
    return result


@app.post("/api/continuity/check")
async def continuity_check(req: ContinuityCheckRequest):
    """Compare two volumes for continuity issues."""
    from core.continuity_engine import ContinuityEngine
    result = await asyncio.to_thread(
        ContinuityEngine().compare_volumes,
        req.vol1_path,
        req.vol2_path,
    )
    return result


# ─── Amazon KDP ───────────────────────────────────────────────────────────────

KDP_GENRES_LIST = ["childrens","mystery","adventure","historical","self_help",
                   "romance","sci_fi","fantasy","horror","true_crime"]
KDP_LOG_PATH    = ROOT / "outputs" / "books" / "daily_publish.log"
KDP_BOOKS_ROOT  = ROOT / "outputs" / "books"

class KDPRunRequest(BaseModel):
    mode:  str = "today"   # "today" | "genre" | "publish_only"
    genre: Optional[str] = None
    file:  Optional[str] = None

def _kdp_load_results() -> Dict[str, Any]:
    """Load latest KDP result per genre from kdp_result_*.json files."""
    import glob as _glob
    results = {}
    for f in sorted(_glob.glob(str(KDP_BOOKS_ROOT / "kdp_result_*.json")), reverse=True):
        try:
            d = json.loads(Path(f).read_text(errors="replace"))
            g = d.get("genre", "")
            if g and g not in results:
                results[g] = d
        except Exception:
            continue
    return results

@app.get("/api/kdp/stats")
async def kdp_stats():
    """Return KDP stats: all-time published, pending, errors, per-genre status."""
    import glob as _glob

    # Count written books per genre
    total_written = 0
    genre_book_counts: Dict[str, int] = {}
    for g in KDP_GENRES_LIST:
        gdir = KDP_BOOKS_ROOT / g
        cnt = len(list(gdir.glob("book_*.md"))) if gdir.exists() else 0
        genre_book_counts[g] = cnt
        total_written += cnt

    # Build latest-per-genre result map (ALL TIME, not just today)
    all_results: Dict[str, dict] = {}
    for f in sorted(_glob.glob(str(KDP_BOOKS_ROOT / "kdp_result_*.json"))):
        try:
            d = json.loads(Path(f).read_text(errors="replace"))
            g = d.get("genre", "")
            if not g:
                continue
            prev = all_results.get(g)
            if prev is None or Path(f).stat().st_mtime > Path(prev.get("_file","")).stat().st_mtime if prev and prev.get("_file") else True:
                d["_file"] = f
                all_results[g] = d
        except Exception:
            continue

    # Compute per-genre status
    genre_status: Dict[str, str] = {}
    genre_titles: Dict[str, str] = {}
    genre_errors: Dict[str, str] = {}
    for g, d in all_results.items():
        err = d.get("error", "")
        raw_status = d.get("status", "error")
        if raw_status == "error" and "account_limit" in err:
            genre_status[g] = "pending_approval"
        else:
            genre_status[g] = raw_status
        genre_titles[g] = d.get("title", "")
        genre_errors[g] = err

    # All-time totals
    total_published     = sum(1 for s in genre_status.values() if s in ("published", "review_required"))
    total_pending       = sum(1 for s in genre_status.values() if s == "pending_approval")
    total_errors        = sum(1 for s in genre_status.values() if s == "error")
    genres_not_run      = len([g for g in KDP_GENRES_LIST if g not in genre_status])

    # Today's run
    import time as _t
    cutoff = _t.time() - 86400
    published_today = 0
    for f in _glob.glob(str(KDP_BOOKS_ROOT / "kdp_result_*.json")):
        try:
            if Path(f).stat().st_mtime < cutoff:
                continue
            d = json.loads(Path(f).read_text(errors="replace"))
            if d.get("status") in ("published", "review_required"):
                published_today += 1
        except Exception:
            continue

    # Live ASINs
    kdp_results = _kdp_load_results()
    live_asins = sum(1 for d in kdp_results.values() if d.get("asin"))

    # Running check
    running = False
    if KDP_LOG_PATH.exists():
        tail = KDP_LOG_PATH.read_text(errors="replace")[-3000:]
        running = ("STEP 1" in tail or "STEP 2" in tail or "STEP 3" in tail) and "DAILY PUBLISH COMPLETE" not in tail

    limit_note = ""
    if total_pending > 0:
        limit_note = f"⚠️ {total_pending} genre(s) hit Amazon's new-title limit. Books are queued — Amazon typically approves within 24–72 hrs."

    return {
        "published_today":   published_today,
        "total_published":   total_published,
        "total_pending":     total_pending,
        "total_errors":      total_errors,
        "genres_not_run":    genres_not_run,
        "total_books":       total_written,
        "account_limit":     total_pending,
        "errors_today":      total_errors,
        "status":            "running" if running else ("done" if total_published > 0 else "idle"),
        "live_asins":        live_asins,
        "genre_status":      genre_status,
        "genre_titles":      genre_titles,
        "genre_errors":      genre_errors,
        "limit_note":        limit_note,
    }

@app.get("/api/kdp/log")
async def kdp_log(lines: int = 80):
    """Return tail of the daily_publish.log."""
    if not KDP_LOG_PATH.exists():
        return {"lines": ["No publish log yet — run a KDP publish session to see output here."]}
    text = KDP_LOG_PATH.read_text(errors="replace")
    all_lines = [l for l in text.splitlines() if l.strip()]
    return {"lines": all_lines[-lines:]}

@app.get("/api/kdp/books")
async def kdp_books(genre: str = ""):
    """Return list of written books with real KDP publish status."""
    import datetime as _dt
    kdp_results = _kdp_load_results()
    books = []
    genres = [genre] if genre and genre in KDP_GENRES_LIST else KDP_GENRES_LIST
    for g in genres:
        gdir = KDP_BOOKS_ROOT / g
        if not gdir.exists():
            continue
        # Get latest KDP result for this genre
        gr = kdp_results.get(g, {})
        gr_status = gr.get("status", "")
        gr_title  = gr.get("title", "")
        gr_asin   = gr.get("asin", "")
        for f in sorted(gdir.glob("book_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:2]:
            mtime = _dt.datetime.fromtimestamp(f.stat().st_mtime)
            raw_title = f.stem.replace("book_","").replace("_"," ").title()
            # Match this file to the KDP result by title similarity
            file_matches_result = gr_title and (raw_title[:20].lower() in gr_title.lower() or gr_title[:20].lower() in raw_title.lower())
            if file_matches_result and gr_status:
                status = gr_status
                asin   = gr_asin
            elif gr_status and f == sorted(gdir.glob("book_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[0]:
                # Latest file for this genre — use the genre result
                status = gr_status
                asin   = gr_asin
            else:
                status = "written"
                asin   = ""
            words = len(f.read_text(errors="replace").split())
            books.append({
                "title":  raw_title,
                "genre":  g,
                "file":   str(f.relative_to(ROOT)),
                "status": status,
                "asin":   asin,
                "words":  words,
                "price":  "2.99",
                "date":   mtime.strftime("%Y-%m-%d %H:%M"),
            })
    return {"books": books}

@app.post("/api/kdp/cover/{genre}")
async def kdp_generate_cover(genre: str, req: dict = {}):
    """
    Generate a DALL-E 3 cover for the latest written book in this genre.
    Also creates a Canva poster design for manual editing.
    Returns cover image path + Canva edit URL.
    """
    gdir = KDP_BOOKS_ROOT / genre
    if not gdir.exists():
        return {"error": f"No books found for genre: {genre}"}
    manuscripts = sorted(gdir.glob("book_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not manuscripts:
        return {"error": f"No manuscripts found for genre: {genre}"}
    latest = manuscripts[0]
    raw_title = req.get("title") or (latest.stem.replace("book_","").replace("_"," ").title())
    cover_path = None
    canva_url  = None
    try:
        from core.kdp_uploader import generate_cover as _gen_cover
        cover_path = _gen_cover(raw_title, genre)
        _add_log(f"KDP cover generated: {genre}/{raw_title}", "INFO")
    except Exception as e:
        return {"error": f"Cover generation failed: {e}"}

    # Also create Canva design for custom editing
    try:
        tok = _canva_access_token()
        if tok:
            import requests as _rc
            dims = _CANVA_PLATFORM_MAP.get("poster", (794, 1123, "Poster (A4)"))
            body = {"design_type": {"type": "custom", "width": dims[0], "height": dims[1]},
                    "title": f"{raw_title} — Book Cover"}
            cr = _rc.post(f"{_CANVA_BASE}/rest/v1/designs", headers=_canva_headers(),
                          json=body, timeout=15)
            if cr.status_code in (200, 201):
                canva_url = cr.json().get("design", {}).get("urls", {}).get("edit_url", "")
    except Exception:
        pass

    return {
        "genre":      genre,
        "title":      raw_title,
        "cover_path": str(cover_path),
        "canva_url":  canva_url,
    }


@app.post("/api/kdp/package/{genre}")
async def kdp_package_book(genre: str, req: dict = {}):
    """
    Package the latest written book for KDP: generate HTML with cover page.
    Returns path to the packaged HTML file.
    """
    gdir = KDP_BOOKS_ROOT / genre
    if not gdir.exists():
        return {"error": f"No books found for genre: {genre}"}
    manuscripts = sorted(gdir.glob("book_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not manuscripts:
        return {"error": f"No manuscripts found for genre: {genre}"}
    latest    = manuscripts[0]
    manuscript = latest.read_text(encoding="utf-8", errors="replace")
    raw_title  = req.get("title") or (latest.stem.replace("book_","").replace("_"," ").title())
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Look for existing cover
    covers_dir = ROOT / "outputs" / "books" / "covers" / "generated"
    cover_path = None
    if covers_dir.exists():
        matching = sorted(covers_dir.glob(f"cover_{genre}_*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
        if matching:
            cover_path = matching[0]

    # Re-use the packaging logic from base_book_bot
    import re as _re
    lines = manuscript.split("\n")
    body  = []
    for line in lines:
        if line.startswith("# "):    body.append(f'<h1 class="title">{line[2:]}</h1>')
        elif line.startswith("## "): body.append(f'<h2 class="chapter">{line[3:]}</h2>')
        elif line.startswith("### "):body.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith("**") and line.endswith("**"):
            body.append(f'<p class="center"><strong>{line[2:-2]}</strong></p>')
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            body.append(f'<p class="center"><em>{line[1:-1]}</em></p>')
        elif line.strip() == "---": body.append('<hr>')
        elif line.strip() == "":    body.append('<p>&nbsp;</p>')
        else:
            line = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = _re.sub(r'\*(.+?)\*',     r'<em>\1</em>', line)
            body.append(f'<p>{line}</p>')

    cover_html = ""
    if cover_path and cover_path.exists():
        import base64
        cover_html = f'<div class="cover-page"><img src="data:image/png;base64,{base64.b64encode(cover_path.read_bytes()).decode()}" alt="Book Cover"></div>'

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>{raw_title}</title>
<style>body{{font-family:Georgia,serif;max-width:680px;margin:0 auto;padding:40px 30px;line-height:1.8;color:#1a1a1a;font-size:16px}}
h1.title{{text-align:center;font-size:2.2em;margin:60px 0 10px}}
h2.chapter{{font-size:1.4em;margin:60px 0 20px;border-bottom:1px solid #ddd;padding-bottom:8px;page-break-before:always}}
p{{margin:0 0 1em;text-indent:1.5em}}p.center{{text-align:center;text-indent:0}}
hr{{border:none;border-top:1px solid #ccc;margin:40px auto;width:40%}}
.cover-page{{text-align:center;page-break-after:always;margin-bottom:60px}}
.cover-page img{{max-width:100%;max-height:90vh;box-shadow:0 4px 24px rgba(0,0,0,.2)}}
@media print{{h2.chapter{{page-break-before:always}}}}</style></head>
<body>{cover_html}{''.join(body)}</body></html>"""

    out_dir = ROOT / "outputs" / "books" / "packaged"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = raw_title.lower().replace(" ", "_")[:40]
    html_path = out_dir / f"{safe}_{ts}.html"
    html_path.write_text(html, encoding="utf-8")
    _add_log(f"KDP package created: {genre}/{raw_title}", "INFO")
    return {
        "genre":      genre,
        "title":      raw_title,
        "html_path":  str(html_path.relative_to(ROOT)),
        "word_count": len(manuscript.split()),
        "has_cover":  cover_path is not None,
    }


@app.post("/api/kdp/run")
async def kdp_run(req: KDPRunRequest, background_tasks: BackgroundTasks):
    """Launch the KDP daily publish pipeline as a background subprocess."""
    import subprocess
    script = ROOT / "bots" / "books" / "daily_publish.py"
    venv_py = ROOT / "venv" / "bin" / "python3"
    python  = str(venv_py) if venv_py.exists() else "python3"

    cmd = [python, str(script)]
    if req.mode == "genre" and req.genre:
        cmd += ["--genres", req.genre]
    elif req.mode == "publish_only" and req.genre:
        cmd += ["--genres", req.genre, "--skip-write", "--skip-packages"]

    def _launch():
        try:
            with open(str(KDP_LOG_PATH), "a") as lf:
                subprocess.Popen(cmd, stdout=lf, stderr=lf, cwd=str(ROOT))
            _add_log(f"KDP publish started: mode={req.mode} genre={req.genre}", "INFO")
        except Exception as e:
            _add_log(f"KDP launch failed: {e}", "ERROR")

    background_tasks.add_task(_launch)
    return {"status": "launched", "mode": req.mode, "genre": req.genre}


# ─── Character Registry Endpoints ────────────────────────────────────────────

_character_registry_singleton = None

def _get_character_registry():
    global _character_registry_singleton
    if _character_registry_singleton is None:
        try:
            from core.character_registry import CharacterRegistry
            _character_registry_singleton = CharacterRegistry()
        except Exception as e:
            logger.error("CharacterRegistry init failed: %s", e)
    return _character_registry_singleton


class CharNameCheckRequest(BaseModel):
    names: list
    series_name: str = ""


class CharAddRequest(BaseModel):
    name: str
    role: str = "supporting"
    book_title: str
    series_name: str = ""
    genre: str = "fiction"


@app.get("/api/character-registry")
async def get_character_registry_api(
    genre: str = None,
    series: str = None,
):
    """Return all registered character entries, optionally filtered by genre/series."""
    cr = _get_character_registry()
    if not cr:
        raise HTTPException(status_code=503, detail="Character registry unavailable")
    entries = cr._load()
    if genre:
        entries = [e for e in entries if e.get("genre", "").lower() == genre.lower()]
    if series:
        entries = [e for e in entries if series.lower() in e.get("series_name", "").lower()]
    return {"entries": entries, "total": len(entries), "total_books": len(entries)}


@app.post("/api/character-registry/check")
async def check_character_names(req: CharNameCheckRequest):
    """Check a list of proposed names for conflicts with existing registry entries."""
    cr = _get_character_registry()
    if not cr:
        raise HTTPException(status_code=503, detail="Character registry unavailable")
    conflicts = cr.check_conflicts(req.names, series_name=req.series_name)
    safe = [n for n in req.names if n not in conflicts]
    return {"conflicts": conflicts, "safe": safe, "total_checked": len(req.names)}


@app.post("/api/character-registry/add")
async def add_character_api(req: CharAddRequest):
    """Manually add a single character name to the registry."""
    cr = _get_character_registry()
    if not cr:
        raise HTTPException(status_code=503, detail="Character registry unavailable")
    if not req.name.strip() or not req.book_title.strip():
        raise HTTPException(status_code=400, detail="name and book_title are required")
    conflicts = cr.check_conflicts([req.name], series_name=req.series_name)
    entry = cr.add_character(
        name=req.name,
        role=req.role,
        book_title=req.book_title,
        series_name=req.series_name,
        genre=req.genre,
    )
    return {
        "ok": True,
        "entry_id": entry.get("id"),
        "conflict_warning": conflicts[0] if conflicts else None,
        "message": f"'{req.name}' added to registry for '{req.book_title}'",
    }


# ─── Book Write-from-Idea Endpoints ──────────────────────────────────────────

class BookWriteRequest(BaseModel):
    title: str
    logline: str
    genre: str = "fantasy"
    num_chapters: int = 20


@app.post("/api/books/write")
async def write_book_from_idea(req: BookWriteRequest):
    """Queue an async best-seller writing job from a user-supplied idea. Returns job_id immediately."""
    from core.job_queue import get_queue as get_job_queue
    from bots.books.write_bestseller import BestsellerWriter

    if not req.title.strip() or not req.logline.strip():
        raise HTTPException(status_code=400, detail="title and logline are required")

    num_chapters = max(10, min(25, req.num_chapters))
    # Capture in local vars for the closure
    _title, _logline, _genre, _nch = req.title, req.logline, req.genre, num_chapters

    def _run_write():
        writer = BestsellerWriter(genre=_genre)
        return writer.write(title=_title, logline=_logline, num_chapters=_nch)

    jq = get_job_queue()
    job_id = await jq.submit(
        name=f"write:{_title[:40]}",
        fn=_run_write,
        meta={"title": _title, "genre": _genre, "logline": _logline, "num_chapters": _nch},
    )
    _add_log(f"Book write queued: '{_title}' ({_genre}, {_nch} ch)", "INFO")
    return {"ok": True, "job_id": job_id, "title": _title, "genre": _genre}


@app.get("/api/books/job/{job_id}")
async def get_book_job(job_id: str):
    """Get status and result of a book-writing job."""
    from core.job_queue import get_queue as get_job_queue
    job = get_job_queue().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


# ─── Book Library — Read / Edit ───────────────────────────────────────────────

@app.get("/api/kdp/book-content")
async def kdp_book_content(path: str):
    """Return full markdown content of a book file."""
    try:
        target = (ROOT / path).resolve()
        # Safety: must stay inside project root
        if not str(target).startswith(str(ROOT)):
            raise HTTPException(status_code=403, detail="Access denied")
        if not target.exists() or not target.suffix == ".md":
            raise HTTPException(status_code=404, detail="Book file not found")
        content = target.read_text(encoding="utf-8", errors="replace")
        words   = len(content.split())
        lines   = content.count("\n")
        chapters = content.count("\n## ") + content.count("\n# ")
        return {
            "path":     path,
            "content":  content,
            "words":    words,
            "lines":    lines,
            "chapters": chapters,
            "filename": target.name,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BookSaveRequest(BaseModel):
    path: str
    content: str


@app.post("/api/kdp/book-save")
async def kdp_book_save(req: BookSaveRequest):
    """Save edited book content back to disk. Creates a backup before writing."""
    import shutil
    try:
        target = (ROOT / req.path).resolve()
        if not str(target).startswith(str(ROOT)):
            raise HTTPException(status_code=403, detail="Access denied")
        if not target.suffix == ".md":
            raise HTTPException(status_code=400, detail="Only .md files allowed")
        # Backup original
        backup = target.with_suffix(f".bak_{int(__import__('time').time())}.md")
        if target.exists():
            shutil.copy2(target, backup)
        target.write_text(req.content, encoding="utf-8")
        words = len(req.content.split())
        _add_log(f"Book saved: {target.name} ({words} words)", "INFO")
        return {"status": "saved", "path": req.path, "words": words, "backup": str(backup.name)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kdp/all-books")
async def kdp_all_books():
    """Return every .md book file found in outputs/books/**, with metadata."""
    import datetime as _dt
    books_root = ROOT / "outputs" / "books"
    books = []
    if not books_root.exists():
        return {"books": []}
    for f in sorted(books_root.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            words = len(text.split())
            # Try to extract title from first H1
            import re as _re
            m = _re.search(r"^#+\s+(.+)$", text, _re.MULTILINE)
            title = m.group(1).strip() if m else f.stem.replace("_", " ").title()
            genre = f.parent.name
            mtime = _dt.datetime.fromtimestamp(f.stat().st_mtime)
            chapters = text.count("\n## ")
            books.append({
                "title":    title[:120],
                "genre":    genre,
                "file":     str(f.relative_to(ROOT)),
                "words":    words,
                "chapters": chapters,
                "date":     mtime.strftime("%Y-%m-%d %H:%M"),
                "size_kb":  round(f.stat().st_size / 1024, 1),
            })
        except Exception:
            continue
    return {"books": books, "total": len(books)}


# ─── NarAI — General Overseer AI ─────────────────────────────────────────────

_narai = None

def _get_narai():
    global _narai
    if _narai is None:
        try:
            from bots.narai.narai.bot import get_narai
            _narai = get_narai()
        except Exception as e:
            logger.error(f"NarAI init failed: {e}")
    return _narai


class NarAICommandRequest(BaseModel):
    text: str

class NarAISkillRequest(BaseModel):
    name: str
    description: str

class NarAIRunBotRequest(BaseModel):
    bot: Optional[str] = None
    pipeline: Optional[str] = None

class NarAIVoiceChatRequest(BaseModel):
    text: str

class NarAILearnHumanRequest(BaseModel):
    question: str
    answer: str


@app.get("/api/narai/status")
async def narai_status():
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    return narai.get_status()


@app.get("/api/narai/log")
async def narai_log(limit: int = 50):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    return {"log": narai.get_activity_log(limit=limit)}


@app.get("/api/narai/feed")
async def narai_feed(limit: int = 100):
    """Categorized activity feed — posts, videos, images, actions, current task."""
    narai = _get_narai()
    log = narai.get_activity_log(limit=limit) if narai else []

    posts, videos, images, actions = [], [], [], []
    current = None

    KEYWORDS = {
        "post":   ["📢","posted","publish","tweet","thread","facebook post","instagram post","linkedin","telegram","caption"],
        "video":  ["🎬","video","heygen","short","reel","youtube","tiktok video"],
        "image":  ["🖼","dall-e","image","dalle","photo","thumbnail","visual","generated image"],
    }

    for entry in reversed(log):
        evt = entry.get("event","").lower()
        ts  = entry.get("ts","")
        raw = entry.get("event","")
        data = entry.get("data", {})

        item = {"event": raw, "ts": ts, "data": data}

        if any(k in evt for k in KEYWORDS["video"]):
            if len(videos) < 30: videos.append(item)
        elif any(k in evt for k in KEYWORDS["image"]):
            if len(images) < 30: images.append(item)
        elif any(k in evt for k in KEYWORDS["post"]):
            if len(posts) < 50: posts.append(item)
        else:
            if len(actions) < 50: actions.append(item)

    # Current task = most recent log entry
    if log:
        latest = log[-1]
        current = {"event": latest.get("event",""), "ts": latest.get("ts",""), "mood": latest.get("mood","")}

    return {
        "current": current,
        "posts":   posts,
        "videos":  videos,
        "images":  images,
        "actions": actions,
        "total":   len(log),
    }


@app.get("/api/narai/report")
async def narai_report():
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    return narai.get_report()


@app.get("/api/narai/skills")
async def narai_skills():
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    return narai.get_skills()


@app.post("/api/narai/diagnostic")
async def narai_diagnostic(background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    background_tasks.add_task(narai.execute, action="diagnostic")
    _add_log("NarAI: diagnostic triggered", "INFO")
    return {"status": "diagnostic_started"}


@app.post("/api/narai/analyze")
async def narai_analyze(background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    background_tasks.add_task(narai.execute, action="analyze")
    _add_log("NarAI: deep analysis triggered", "INFO")
    return {"status": "analysis_started"}


@app.post("/api/narai/fix")
async def narai_fix(background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    background_tasks.add_task(narai.execute, action="fix")
    _add_log("NarAI: auto-fix triggered", "INFO")
    return {"status": "fix_started"}


@app.post("/api/narai/command")
async def narai_command(req: NarAICommandRequest, background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    # Run synchronously so we get the response back
    try:
        response = narai.run(action="command", text=req.text)
        return {"response": response, "mood": narai.get_mood()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/create_skill")
async def narai_create_skill(req: NarAISkillRequest, background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    background_tasks.add_task(narai.execute, action="create_skill", name=req.name, description=req.description)
    return {"status": "skill_creation_started", "skill": req.name}


@app.post("/api/narai/run_bot")
async def narai_run_bot(req: NarAIRunBotRequest, background_tasks: BackgroundTasks):
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    if req.bot:
        background_tasks.add_task(narai.execute, action="run_bot", bot=req.bot)
        return {"status": "bot_triggered", "bot": req.bot}
    if req.pipeline:
        background_tasks.add_task(narai.execute, action="run_pipeline", pipeline=req.pipeline)
        return {"status": "pipeline_triggered", "pipeline": req.pipeline}
    raise HTTPException(status_code=400, detail="Provide 'bot' or 'pipeline'")


@app.post("/api/narai/voice_chat")
async def narai_voice_chat(req: NarAIVoiceChatRequest, request: Request):
    """Live voice conversation — synchronous, short spoken reply."""
    logger.info("AUDIT: NarAI voice_chat from IP %s: %s", request.headers.get("x-forwarded-for", "unknown"), req.text[:80])
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    try:
        result = narai.voice_chat(req.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class NarAITTSRequest(BaseModel):
    text: str
    voice: str = "nova"
    speed: float = 0.88


@app.post("/api/narai/tts")
async def narai_tts(req: NarAITTSRequest):
    """Convert text to speech via OpenAI TTS-HD."""
    import io
    text = req.text.strip()[:600]
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    try:
        from openai import OpenAI as _OAI
        client = _OAI(api_key=os.getenv("OPENAI_API_KEY"))
        audio = client.audio.speech.create(
            model="tts-1", voice=req.voice, input=text,
            speed=max(0.25, min(4.0, req.speed)),
        )
        b = audio.content
        return StreamingResponse(io.BytesIO(b), media_type="audio/mpeg",
            headers={"Content-Length": str(len(b)), "Cache-Control": "no-store"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


class NarAISpeakRequest(BaseModel):
    text: str   # the user's spoken input


@app.post("/api/narai/speak")
async def narai_speak(req: NarAISpeakRequest):
    """
    Single-call endpoint: user text → NarAI reply → TTS audio (MP3).
    Returns audio/mpeg directly so the browser only makes ONE request.
    Also returns NarAI's text reply and mood in response headers.
    """
    import io, urllib.parse
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    # Step 1: generate conversational reply (Claude)
    try:
        result = narai.voice_chat(req.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NarAI reply failed: {e}")

    reply_text = result.get("response", "").strip()[:600]
    mood       = result.get("mood", {})

    # Step 2: generate TTS audio from that reply
    try:
        from openai import OpenAI as _OAI
        client = _OAI(api_key=os.getenv("OPENAI_API_KEY"))
        audio = client.audio.speech.create(
            model="tts-1", voice="nova", input=reply_text, speed=0.9,
        )
        audio_bytes = audio.content
    except Exception:
        # TTS failed — return text-only JSON so frontend can show the reply
        return JSONResponse({"response": reply_text, "mood": mood, "audio": False})

    # Encode reply text into header (URL-encoded, safe for HTTP)
    safe_text  = urllib.parse.quote(reply_text, safe='')
    safe_mood  = urllib.parse.quote(str(mood.get("mood","curious")), safe='')
    safe_emoji = urllib.parse.quote(str(mood.get("emoji","🌟")), safe='')

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={
            "Content-Length":      str(len(audio_bytes)),
            "Cache-Control":       "no-store",
            "X-NarAI-Text":        safe_text,
            "X-NarAI-Mood":        safe_mood,
            "X-NarAI-Emoji":       safe_emoji,
            "X-NarAI-Energy":      str(mood.get("energy", 0.85)),
        },
    )


@app.get("/api/narai/greeting")
async def narai_greeting():
    """NarAI generates a unique, memory-aware opening greeting for this session."""
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    try:
        return narai.get_greeting()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/narai/ask_human")
async def narai_ask_human():
    """NarAI picks her next humanity question to ask the user."""
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    try:
        return narai.ask_about_humanity()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/learn_human")
async def narai_learn_human(req: NarAILearnHumanRequest):
    """Store user's answer and get NarAI's reflection."""
    narai = _get_narai()
    if not narai:
        raise HTTPException(status_code=503, detail="NarAI offline")
    try:
        return narai.learn_from_human(req.question, req.answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── NarAI Self-Improvement API ──────────────────────────────────────────────

class NarAIImproveRequest(BaseModel):
    user_id: Optional[str] = None


class NarAIProposalActionRequest(BaseModel):
    pass


@app.post("/api/narai/propose-improvement")
async def narai_propose_improvement(req: NarAIImproveRequest):
    """Analyse recent conversations and generate one improvement proposal."""
    try:
        from core.narai_self_improve import generate_improvement_proposal
        proposal = generate_improvement_proposal(req.user_id)
        return proposal
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/narai/proposals")
async def narai_list_proposals(status: Optional[str] = None):
    """List all improvement proposals, optionally filtered by status."""
    try:
        from core.narai_self_improve import list_proposals
        return {"proposals": list_proposals(status)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/proposals/{proposal_id}/apply")
async def narai_apply_proposal(proposal_id: str):
    """Apply an approved improvement proposal to the system prompt."""
    try:
        from core.narai_self_improve import apply_proposal
        ok = apply_proposal(proposal_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Proposal not found or already processed")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/proposals/{proposal_id}/reject")
async def narai_reject_proposal(proposal_id: str):
    """Reject an improvement proposal."""
    try:
        from core.narai_self_improve import reject_proposal
        ok = reject_proposal(proposal_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── NarAI Image Generation (DALL-E 3) ───────────────────────────────────────

class NarAIImageRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"
    quality: str = "standard"


@app.post("/api/narai/generate-image")
async def narai_generate_image(req: NarAIImageRequest):
    """Generate an image via DALL-E 3 and return the URL."""
    prompt = req.prompt.strip()[:800]
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt required")
    allowed_sizes = {"1024x1024", "1792x1024", "1024x1792"}
    size = req.size if req.size in allowed_sizes else "1024x1024"
    quality = req.quality if req.quality in {"standard", "hd"} else "standard"
    try:
        from openai import OpenAI as _OAI
        client = _OAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
        img = resp.data[0]
        return {"url": img.url, "revised_prompt": getattr(img, "revised_prompt", prompt)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")


# ─── Defensive Security Scanner API ─────────────────────────────────────────

class SecurityScanRequest(BaseModel):
    path: str
    max_files: int = 200


@app.post("/api/security/scan")
async def security_scan(req: SecurityScanRequest):
    """Scan a file or directory for threats (defensive/educational use)."""
    import pathlib
    target = pathlib.Path(req.path).resolve()
    target_str = str(target)
    # Safety: allow project dir, /tmp (and macOS /private/tmp), /var/folders, home Downloads
    allowed_roots = [
        pathlib.Path("/tmp").resolve(),
        pathlib.Path("/private/tmp"),
        pathlib.Path("/var/folders"),
        pathlib.Path(os.path.expanduser("~/Downloads")),
        pathlib.Path(os.path.expanduser("~/Desktop")),
        pathlib.Path(os.getcwd()).resolve(),
    ]
    if not any(target_str.startswith(str(r)) for r in allowed_roots):
        raise HTTPException(status_code=403, detail="Scan path not in allowed locations")
    try:
        from core.security_scanner import scan_directory, scan_file
        if target.is_file():
            return scan_file(str(target))
        return scan_directory(str(target), max_files=min(req.max_files, 500))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Budget Manager API ──────────────────────────────────────────────────────

@app.get("/api/budget/summary")
async def budget_summary():
    from core.budget_manager import BudgetManager
    return BudgetManager.get().summary()

@app.get("/api/budget/report")
async def budget_report():
    from core.budget_manager import BudgetManager
    return BudgetManager.get().daily_report()

class BoostRequest(BaseModel):
    post_id: str
    platform: str = "facebook"
    topic: str = ""
    amount: float = 5.0

@app.post("/api/budget/boost")
async def budget_boost(req: BoostRequest, background_tasks: BackgroundTasks):
    from core.budget_manager import BudgetManager
    bm = BudgetManager.get()
    remaining = bm.today_remaining()
    if req.amount > remaining:
        raise HTTPException(status_code=400,
            detail=f"Insufficient budget — ${remaining:.2f} remaining today")
    def _boost():
        r = bm.boost_post(req.post_id, req.platform, req.topic, req.amount)
        _add_log(f"Budget boost: ${req.amount} on {req.platform} — {r.get('status')}", "INFO")
    background_tasks.add_task(_boost)
    return {"status": "boosting", "amount": req.amount, "platform": req.platform}

class RevenueRecord(BaseModel):
    post_id: str
    revenue: float

@app.post("/api/budget/revenue")
async def budget_revenue(req: RevenueRecord):
    from core.budget_manager import BudgetManager
    BudgetManager.get().record_revenue(req.post_id, req.revenue)
    return {"status": "recorded", "post_id": req.post_id, "revenue": req.revenue}

@app.post("/api/budget/start")
async def budget_start():
    from core.budget_manager import BudgetManager
    BudgetManager.get().start()
    return {"status": "budget_manager_started"}


# ─── Affiliate Optimizer API ──────────────────────────────────────────────────

@app.get("/api/affiliate/optimizer/summary")
async def affiliate_optimizer_summary():
    from core.affiliate_optimizer import AffiliateOptimizer
    return AffiliateOptimizer.get().summary()

@app.get("/api/affiliate/winners")
async def affiliate_winners():
    from core.affiliate_optimizer import AffiliateOptimizer
    return {"winners": AffiliateOptimizer.get().get_all_winners()}

@app.get("/api/affiliate/best-link")
async def affiliate_best_link(niche: str = "general"):
    from core.affiliate_optimizer import get_best_link
    return get_best_link(niche)

class AffConversionRequest(BaseModel):
    niche: str = "general"
    program: str
    revenue: float = 0.0

@app.post("/api/affiliate/conversion")
async def affiliate_conversion(req: AffConversionRequest):
    from core.affiliate_optimizer import AffiliateOptimizer
    AffiliateOptimizer.get().record_conversion(req.niche, req.program, req.revenue)
    return {"status": "recorded", "niche": req.niche, "program": req.program}

@app.post("/api/affiliate/start")
async def affiliate_start():
    from core.affiliate_optimizer import AffiliateOptimizer
    AffiliateOptimizer.get().start()
    return {"status": "affiliate_optimizer_started"}


# ─── Email Funnel API ─────────────────────────────────────────────────────────

@app.get("/api/email/summary")
async def email_summary():
    from core.email_funnel import summary
    return summary()

@app.get("/api/email/stats")
async def email_stats():
    from core.email_funnel import get_stats
    return get_stats()

class KitSubscribeRequest(BaseModel):
    email: str
    first_name: str = ""
    tags: List[str] = []
    niche: str = "general"

@app.post("/api/email/subscribe")
async def email_subscribe_kit(req: KitSubscribeRequest):
    from core.email_funnel import add_subscriber
    result = add_subscriber(req.email, req.first_name, req.tags)
    _add_log(f"Email subscribe: {req.email} — {result.get('status','error')}", "INFO")
    return result

class BuildSequenceRequest(BaseModel):
    niche: str = "general"
    sequence_type: str = "nurture"
    name: str = ""

@app.post("/api/email/build-sequence")
async def email_build_sequence(req: BuildSequenceRequest,
                                background_tasks: BackgroundTasks):
    from core.email_funnel import build_sequence, create_sequence_in_convertkit
    def _build():
        emails = build_sequence(req.niche, req.sequence_type)
        name   = req.name or f"{req.niche}_{req.sequence_type}"
        create_sequence_in_convertkit(name, emails)
        _add_log(f"Email sequence built: {name} ({len(emails)} emails)", "INFO")
    background_tasks.add_task(_build)
    return {"status": "building", "niche": req.niche, "type": req.sequence_type}

class BroadcastRequest(BaseModel):
    topic: str
    niche: str = "general"

@app.post("/api/email/broadcast")
async def email_broadcast(req: BroadcastRequest, background_tasks: BackgroundTasks):
    from core.email_funnel import generate_broadcast
    def _send():
        result = generate_broadcast(req.topic, req.niche)
        _add_log(f"Email broadcast: {result.get('subject','')[:50]}", "INFO")
    background_tasks.add_task(_send)
    return {"status": "sending", "topic": req.topic}

@app.post("/api/email/weekly-newsletter")
async def email_weekly(background_tasks: BackgroundTasks):
    from core.email_funnel import send_weekly_newsletter
    background_tasks.add_task(send_weekly_newsletter)
    _add_log("Weekly newsletter generation started", "INFO")
    return {"status": "started"}


# ─── LinkedIn API ────────────────────────────────────────────────────────────

@app.get("/api/linkedin/status")
async def linkedin_status():
    from core.linkedin import is_configured, get_person_urn
    return {
        "configured": is_configured(),
        "person_urn": get_person_urn() if is_configured() else None,
        "client_id_set": bool(os.getenv("LINKEDIN_CLIENT_ID")),
    }

@app.get("/api/linkedin/auth")
async def linkedin_auth():
    from core.linkedin import get_auth_url, CLIENT_ID
    if not CLIENT_ID:
        raise HTTPException(status_code=503,
            detail="LINKEDIN_CLIENT_ID not set. Add it to .env first.")
    url = get_auth_url()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)

@app.get("/api/linkedin/callback")
async def linkedin_callback(code: str = None, error: str = None, state: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f"LinkedIn OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    from core.linkedin import exchange_code
    result = exchange_code(code)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    _add_log("LinkedIn OAuth completed — access token saved", "INFO")
    return {"status": "connected", "expires_in": result.get("expires_in"),
            "message": "LinkedIn connected! You can now post to LinkedIn."}

@app.post("/api/linkedin/post")
async def linkedin_post(req: LinkedInPostRequest, background_tasks: BackgroundTasks):
    from core.linkedin import get_linkedin
    li = get_linkedin()
    if not li.is_configured():
        raise HTTPException(status_code=503,
            detail="LinkedIn not connected — visit /api/linkedin/auth")
    def _post():
        r = li.post(text=req.text, topic=req.topic, niche=req.niche,
                    image_url=req.image_url or None, generate=req.generate)
        _add_log(f"LinkedIn post: {r.get('status','error')} — {req.topic[:40]}", "INFO")
    background_tasks.add_task(_post)
    return {"status": "posting", "topic": req.topic}

@app.post("/api/linkedin/generate-post")
async def linkedin_generate(req: LinkedInPostRequest):
    from core.linkedin import generate_post
    text = generate_post(req.topic, niche=req.niche)
    return {"text": text, "chars": len(text)}


# ─── Pinterest API ────────────────────────────────────────────────────────────

@app.get("/api/pinterest/status")
async def pinterest_status():
    from core.pinterest import is_configured, list_boards
    boards = list_boards() if is_configured() else []
    return {
        "configured": is_configured(),
        "boards":     len(boards),
        "app_id_set": bool(os.getenv("PINTEREST_APP_ID")),
    }

@app.get("/api/pinterest/auth")
async def pinterest_auth():
    from core.pinterest import get_auth_url, APP_ID
    if not APP_ID:
        raise HTTPException(status_code=503,
            detail="PINTEREST_APP_ID not set. Add it to .env first.")
    url = get_auth_url()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)

@app.get("/api/pinterest/callback")
async def pinterest_callback(code: str = None, error: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Pinterest OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    from core.pinterest import exchange_code
    result = exchange_code(code)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    _add_log("Pinterest OAuth completed — token saved", "INFO")
    return {"status": "connected", "message": "Pinterest connected!"}

@app.get("/api/pinterest/boards")
async def pinterest_boards():
    from core.pinterest import list_boards
    return {"boards": list_boards()}

class PinRequest(BaseModel):
    topic: str
    niche: str = "general"
    link: str = ""
    image_url: str = ""
    board_id: str = ""

@app.post("/api/pinterest/pin")
async def pinterest_pin(req: PinRequest, background_tasks: BackgroundTasks):
    from core.pinterest import get_pinterest
    pt = get_pinterest()
    if not pt.is_configured():
        raise HTTPException(status_code=503,
            detail="Pinterest not connected — visit /api/pinterest/auth")
    def _pin():
        r = pt.pin(req.topic, niche=req.niche,
                   link=req.link or None)
        _add_log(f"Pinterest pin: {r.get('status','error')} — {req.topic[:40]}", "INFO")
    background_tasks.add_task(_pin)
    return {"status": "pinning", "topic": req.topic}

class BatchPinRequest(BaseModel):
    topics: List[str]
    niche: str = "general"

@app.post("/api/pinterest/batch-pin")
async def pinterest_batch(req: BatchPinRequest, background_tasks: BackgroundTasks):
    from core.pinterest import get_pinterest
    pt = get_pinterest()
    if not pt.is_configured():
        raise HTTPException(status_code=503, detail="Pinterest not connected")
    background_tasks.add_task(pt.batch, req.topics, req.niche)
    return {"status": "batch_started", "count": len(req.topics), "niche": req.niche}


# ─── Threads API ──────────────────────────────────────────────────────────────

@app.get("/api/threads/status")
async def threads_status():
    from core.threads import is_configured, _get_user_id
    return {
        "configured":      is_configured(),
        "user_id":         _get_user_id() if is_configured() else None,
        "token_source":    ("dedicated" if os.getenv("THREADS_ACCESS_TOKEN")
                           else "instagram" if os.getenv("INSTAGRAM_PAGE_TOKEN")
                           else "none"),
    }

class ThreadsPostRequest(BaseModel):
    text: str = ""
    topic: str = ""
    niche: str = "general"
    image_url: str = ""
    generate: bool = False

@app.post("/api/threads/post")
async def threads_post(req: ThreadsPostRequest, background_tasks: BackgroundTasks):
    from core.threads import get_threads
    th = get_threads()
    if not th.is_configured():
        raise HTTPException(status_code=503,
            detail="Threads not configured — set THREADS_ACCESS_TOKEN or INSTAGRAM_PAGE_TOKEN")
    def _post():
        r = th.post(text=req.text, topic=req.topic, niche=req.niche,
                    image_url=req.image_url or None, generate=req.generate)
        _add_log(f"Threads post: {r.get('status','error')} — {(req.topic or req.text)[:40]}", "INFO")
    background_tasks.add_task(_post)
    return {"status": "posting", "topic": req.topic or req.text[:50]}

@app.post("/api/threads/generate-post")
async def threads_generate(req: ThreadsPostRequest):
    from core.threads import generate_post
    text = generate_post(req.topic, niche=req.niche)
    return {"text": text, "chars": len(text)}

class ThreadsSeriesRequest(BaseModel):
    topics: List[str]
    niche: str = "general"

@app.post("/api/threads/series")
async def threads_series(req: ThreadsSeriesRequest, background_tasks: BackgroundTasks):
    from core.threads import get_threads, post_series
    th = get_threads()
    if not th.is_configured():
        raise HTTPException(status_code=503, detail="Threads not configured")
    background_tasks.add_task(post_series, req.topics, req.niche)
    return {"status": "series_started", "count": len(req.topics)}


# ─── ElevenLabs API ──────────────────────────────────────────────────────────

@app.get("/api/elevenlabs/status")
async def elevenlabs_status():
    from core import elevenlabs as el
    return {
        "configured": el.is_configured(),
        "voice_id":   os.getenv("ELEVENLABS_VOICE_ID",""),
        "model":      os.getenv("ELEVENLABS_MODEL","eleven_turbo_v2_5"),
        "usage":      el.get_usage(),
    }

@app.get("/api/elevenlabs/voices")
async def elevenlabs_voices():
    from core import elevenlabs as el
    return {"voices": el.list_voices()}

class TTSRequest(BaseModel):
    text: str
    filename: str = ""
    voice_id: str = ""

@app.post("/api/elevenlabs/speak")
async def elevenlabs_speak(req: TTSRequest, background_tasks: BackgroundTasks):
    from core import elevenlabs as el
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    def _speak():
        path = el.speak(req.text, voice_id=req.voice_id or None,
                        filename=req.filename or None)
        _add_log(f"ElevenLabs TTS: {len(req.text)} chars → {path}", "INFO")
    background_tasks.add_task(_speak)
    return {"status": "generating", "chars": len(req.text)}


# ─── HeyGen API ───────────────────────────────────────────────────────────────

@app.get("/api/heygen/status")
async def heygen_status():
    from core import heygen
    return {
        "configured": heygen.is_configured(),
        "avatar_id":  os.getenv("HEYGEN_AVATAR_ID",""),
        "voice_id":   os.getenv("HEYGEN_VOICE_ID",""),
        "credits":    heygen.get_remaining_credits(),
    }

@app.get("/api/heygen/avatars")
async def heygen_avatars():
    from core import heygen
    return {"avatars": heygen.list_avatars()}

@app.get("/api/heygen/voices")
async def heygen_voices():
    from core import heygen
    return {"voices": heygen.list_voices()}

@app.get("/api/heygen/videos")
async def heygen_videos(limit: int = 20):
    from core import heygen
    return {"videos": heygen.get_video_list(limit=limit)}

class HeyGenVideoRequest(BaseModel):
    script: str
    title: str = ""
    format: str = "shorts"
    use_elevenlabs: bool = True

@app.post("/api/heygen/generate")
async def heygen_generate(req: HeyGenVideoRequest, background_tasks: BackgroundTasks):
    from core import heygen
    if not heygen.is_configured():
        raise HTTPException(status_code=503, detail="HeyGen not configured — add HEYGEN_API_KEY and HEYGEN_AVATAR_ID to .env")
    def _gen():
        result = heygen.create_video_and_wait(
            req.script, title=req.title,
            format=req.format, use_elevenlabs=req.use_elevenlabs
        )
        _add_log(f"HeyGen video: {result.get('status')} — {req.title}", "INFO")
    background_tasks.add_task(_gen)
    return {"status": "generating", "title": req.title, "format": req.format}


# ─── Shorts Pipeline API ──────────────────────────────────────────────────────

@app.get("/api/shorts/status")
async def shorts_status():
    from core import heygen, elevenlabs as el
    results = list((ROOT / "outputs" / "shorts_results").glob("*.json"))
    results = sorted(results, key=lambda f: f.stat().st_mtime, reverse=True)
    recent  = []
    for r in results[:10]:
        try:
            recent.append(json.loads(r.read_text()))
        except Exception:
            pass
    return {
        "heygen_configured":      heygen.is_configured(),
        "elevenlabs_configured":  el.is_configured(),
        "total_shorts_created":   len(results),
        "recent":                 recent,
    }

class ShortsRequest(BaseModel):
    topic: str = ""
    niche: str = ""
    platforms: str = ""
    format: str = "shorts"
    skip_video: bool = False
    dry_run: bool = False

@app.post("/api/shorts/run")
async def shorts_run(req: ShortsRequest, background_tasks: BackgroundTasks):
    from core.shorts_pipeline import get_shorts_pipeline
    platforms = [p.strip() for p in req.platforms.split(",")] if req.platforms else None
    def _run():
        result = get_shorts_pipeline().run(
            topic=req.topic or None,
            niche=req.niche or None,
            publish_to=platforms,
            format=req.format,
            skip_video=req.skip_video,
            dry_run=req.dry_run,
        )
        _add_log(f"Shorts pipeline: {result.get('status')} — {result.get('topic','')[:50]}", "INFO")
    background_tasks.add_task(_run)
    return {"status": "started", "topic": req.topic or "auto-pick",
            "platforms": platforms or os.getenv("SHORTS_DEFAULT_PLATFORMS","youtube,tiktok,instagram,facebook").split(",")}

@app.get("/api/shorts/results")
async def shorts_results(limit: int = 20):
    results_dir = ROOT / "outputs" / "shorts_results"
    files = sorted(results_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return {"results": out, "total": len(files)}


# ─── Feedback Loop API ───────────────────────────────────────────────────────

@app.get("/api/feedback/summary")
async def feedback_summary(days: int = 7):
    from core.feedback_loop import FeedbackLoop
    return FeedbackLoop.get().summary(days=days)

@app.get("/api/feedback/best-topics")
async def feedback_best_topics(niche: str = None, platform: str = None, limit: int = 5):
    from core.feedback_loop import FeedbackLoop
    return {"topics": FeedbackLoop.get().get_best_topics(niche=niche, platform=platform, limit=limit)}

@app.get("/api/feedback/viral")
async def feedback_viral(hours: int = 24):
    from core.feedback_loop import FeedbackLoop
    posts = FeedbackLoop.get().get_viral_posts(hours=hours)
    return {"viral_posts": [p.to_dict() for p in posts]}

class EngagementUpdate(BaseModel):
    post_id: str
    views: int = 0
    likes: int = 0
    shares: int = 0
    comments: int = 0
    clicks: int = 0
    affiliate_clicks: int = 0
    leads: int = 0
    revenue: float = 0.0

@app.post("/api/feedback/update")
async def feedback_update(req: EngagementUpdate):
    from core.feedback_loop import FeedbackLoop
    record = FeedbackLoop.get().update_engagement(req.post_id, **req.dict(exclude={"post_id"}))
    if not record:
        raise HTTPException(status_code=404, detail="post_id not found")
    return {"score": record.score, "viral": record.viral}

class RegisterPost(BaseModel):
    post_id: str
    topic: str
    niche: str = "general"
    bot_name: str = "unknown"
    platform: str
    content_type: str = "post"

@app.post("/api/feedback/register")
async def feedback_register(req: RegisterPost):
    from core.feedback_loop import FeedbackLoop
    r = FeedbackLoop.get().register_post(
        req.post_id, req.topic, req.niche, req.bot_name, req.platform, req.content_type
    )
    return {"post_id": r.post_id, "created_at": r.created_at}


# ─── Viral Detector API ───────────────────────────────────────────────────────

@app.get("/api/viral/summary")
async def viral_summary():
    from core.viral_detector import ViralDetector
    return ViralDetector.get().summary()

@app.get("/api/viral/events")
async def viral_events(hours: int = 24):
    from core.viral_detector import ViralDetector
    events = ViralDetector.get().get_events(hours=hours)
    return {"events": [e.to_dict() for e in events]}

@app.post("/api/viral/check")
async def viral_check(background_tasks: BackgroundTasks):
    from core.viral_detector import ViralDetector
    background_tasks.add_task(ViralDetector.get().check_now)
    return {"status": "viral_check_triggered"}


# ─── DM Reply API ─────────────────────────────────────────────────────────────

@app.get("/api/dm/summary")
async def dm_summary():
    from core.dm_reply import DMReplyEngine
    return DMReplyEngine.get().summary()

@app.get("/api/dm/people")
async def dm_people(limit: int = 50):
    from core.dm_reply import DMReplyEngine
    people = DMReplyEngine.get().get_all_people()
    people.sort(key=lambda p: p.last_seen, reverse=True)
    return {"people": [p.to_dict() for p in people[:limit]]}

@app.post("/api/dm/start")
async def dm_start():
    from core.dm_reply import DMReplyEngine
    DMReplyEngine.get().start()
    return {"status": "dm_reply_engine_started"}

@app.post("/api/dm/stop")
async def dm_stop():
    from core.dm_reply import DMReplyEngine
    DMReplyEngine.get().stop()
    return {"status": "dm_reply_engine_stopped"}

class WhatsAppWebhookPayload(BaseModel):
    sender_id: str
    name: str = ""
    text: str

@app.post("/api/whatsapp/incoming")
async def whatsapp_incoming(req: WhatsAppWebhookPayload):
    """Endpoint for incoming WhatsApp messages — routes through DM reply engine."""
    from core.dm_reply import DMReplyEngine
    reply = DMReplyEngine.get().handle_whatsapp_message(req.sender_id, req.name, req.text)
    if reply:
        try:
            from core.whatsapp import WhatsAppClient
            wa = WhatsAppClient()
            wa.send_message(req.sender_id, reply)
        except Exception as e:
            logger.warning(f"WhatsApp auto-reply send failed: {e}")
    return {"replied": bool(reply), "reply_preview": (reply or "")[:100]}


# ─── Week 9: Money Command Center API ────────────────────────────────────────

_stripe_payments_file = ROOT / "data" / "stripe_payments.json"

def _load_stripe_payments() -> list:
    if _stripe_payments_file.exists():
        try:
            return json.loads(_stripe_payments_file.read_text())
        except Exception:
            return []
    return []

def _save_stripe_payment(event: dict):
    payments = _load_stripe_payments()
    payments.insert(0, event)
    payments = payments[:500]  # keep last 500
    _stripe_payments_file.parent.mkdir(parents=True, exist_ok=True)
    _stripe_payments_file.write_text(json.dumps(payments, indent=2))


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook — records payment events (checkout.session.completed, invoice.paid, etc.)"""
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    secret  = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # Verify signature if secret is set
    if secret:
        try:
            import stripe as _stripe_lib
            _stripe_lib.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            event = _stripe_lib.Webhook.construct_event(payload, sig, secret)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Webhook signature invalid: {e}")
    else:
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

    etype  = event.get("type", "")
    data   = event.get("data", {}).get("object", {})
    amount = data.get("amount_total") or data.get("amount_paid") or data.get("amount", 0)
    amount_usd = round(amount / 100, 2) if amount else 0.0

    record = {
        "ts":       datetime.now().isoformat(),
        "type":     etype,
        "amount":   amount_usd,
        "currency": data.get("currency", "usd"),
        "email":    data.get("customer_email") or data.get("customer_details", {}).get("email", ""),
        "product":  data.get("description") or data.get("lines", {}).get("data", [{}])[0].get("description", "") if etype == "invoice.paid" else "",
        "event_id": event.get("id", ""),
    }
    _save_stripe_payment(record)
    _add_log(f"Stripe {etype}: ${amount_usd} from {record['email'][:30]}", "INFO")

    # Auto-enroll buyer into ConvertKit drip if email present
    if record["email"] and etype in ("checkout.session.completed", "invoice.paid"):
        try:
            from core.drip import enroll_in_drip
            enroll_in_drip(email=record["email"], first_name="", source=f"stripe_{etype}")
        except Exception:
            pass

    # Upgrade NarAI user tier after successful NarAI plan purchase
    if etype == "checkout.session.completed":
        meta = data.get("metadata", {})
        narai_plan = meta.get("narai_plan", "")
        user_email = meta.get("user_email", "") or record["email"]
        if narai_plan in ("pro", "max", "ultra") and user_email:
            try:
                from core.narai_user import get_supabase
                sb = get_supabase()
                # Find user by email and upgrade their tier
                res = sb.table("profiles").update({"tier": narai_plan}).eq("email", user_email).execute()
                _add_log(f"NarAI tier upgraded: {user_email} → {narai_plan}", "INFO")
            except Exception as _e:
                _add_log(f"NarAI tier upgrade failed: {_e}", "WARNING")

    return {"received": True}


@app.get("/api/money/summary")
async def money_summary():
    """Money Command Center — combined real-time snapshot of all revenue streams."""
    from datetime import date, timedelta
    today_str = date.today().isoformat()
    week_ago  = (date.today() - timedelta(days=7)).isoformat()

    # ── Stripe ────────────────────────────────────────────────────────────────
    payments  = _load_stripe_payments()
    stripe_today  = sum(p["amount"] for p in payments if p["ts"][:10] == today_str)
    stripe_week   = sum(p["amount"] for p in payments if p["ts"][:10] >= week_ago)
    stripe_total  = sum(p["amount"] for p in payments)
    stripe_recent = payments[:5]

    # ── KDP ───────────────────────────────────────────────────────────────────
    kdp_stats = _kdp_load_results()
    kdp_published = sum(1 for g in kdp_stats.values() if g.get("status") == "published")
    kdp_errors    = sum(1 for g in kdp_stats.values() if g.get("status") == "error")
    # Estimated KDP revenue: published × $2.99 × 70% royalty / 30 days
    kdp_est_daily = round(kdp_published * 2.99 * 0.70 / 30, 2)

    # ── Leads ─────────────────────────────────────────────────────────────────
    try:
        from core.email_capture import get_email_capture
        lead_stats = get_email_capture().get_stats()
        leads_total = lead_stats.get("total", 0)
        leads_today = lead_stats.get("today", 0)
    except Exception:
        leads_total, leads_today = 0, 0

    # ── ConvertKit list size ───────────────────────────────────────────────────
    try:
        from core.convertkit import ConvertKitClient
        ck = ConvertKitClient()
        ck_data = ck._get("/subscribers", {"sort_field": "created_at", "sort_order": "desc"})
        list_size = ck_data.get("total_subscribers", 0)
    except Exception:
        list_size = 0

    # ── Monetization injection stats ──────────────────────────────────────────
    try:
        from core.monetization import get_monetization_engine
        mono_stats = get_monetization_engine().get_injection_stats()
    except Exception:
        mono_stats = {"total_injections": 0, "total_links": 0}

    # ── Affiliate clicks ──────────────────────────────────────────────────────
    try:
        from core.click_tracker import get_click_tracker
        click_data = get_click_tracker().get_summary(days=7)
        aff_clicks_week = click_data.get("total_clicks", 0)
    except Exception:
        aff_clicks_week = 0

    return {
        "stripe": {
            "today":   stripe_today,
            "week":    stripe_week,
            "total":   stripe_total,
            "recent":  stripe_recent,
        },
        "kdp": {
            "published":   kdp_published,
            "errors":      kdp_errors,
            "est_daily":   kdp_est_daily,
            "genres":      kdp_stats,
        },
        "leads": {
            "total":  leads_total,
            "today":  leads_today,
            "list_size": list_size,
        },
        "monetization": mono_stats,
        "affiliate_clicks_7d": aff_clicks_week,
        "total_revenue_today": round(stripe_today + kdp_est_daily, 2),
    }


@app.get("/api/money/stripe")
async def money_stripe(days: int = 30):
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    payments = [p for p in _load_stripe_payments() if p["ts"][:10] >= cutoff]
    total = sum(p["amount"] for p in payments)
    by_type = {}
    for p in payments:
        by_type[p["type"]] = by_type.get(p["type"], 0) + p["amount"]
    return {"total": round(total, 2), "count": len(payments), "by_type": by_type, "payments": payments[:50]}


@app.post("/api/money/record")
async def money_record_manual(source: str, amount: float, note: str = ""):
    """Manually record a revenue event (KDP royalty, affiliate payout, etc.)."""
    record = {
        "ts":     datetime.now().isoformat(),
        "type":   f"manual_{source}",
        "amount": amount,
        "currency": "usd",
        "email":  "",
        "product": note,
        "event_id": f"manual_{int(datetime.now().timestamp())}",
    }
    _save_stripe_payment(record)
    _add_log(f"Manual revenue recorded: ${amount} from {source}", "INFO")
    return {"status": "recorded", "amount": amount}


# ─── Money Center: Income Assets ─────────────────────────────────────────────

@app.get("/api/money/assets")
async def money_assets():
    """Return all income assets from the money_center registry."""
    import json as _json
    try:
        # Read directly from the JSON file — no SSD check needed on Railway
        assets_path = ROOT / "money_center" / "assets.json"
        if not assets_path.exists():
            return {"error": "assets.json not found", "assets": [], "summary": {}}
        assets = _json.loads(assets_path.read_text(encoding="utf-8"))
        clean = []
        total_low = total_mid = total_high = 0
        for a in assets:
            est = a.get("monthly_estimate_usd", {})
            low  = est.get("low", 0)
            mid  = est.get("mid", 0)
            high = est.get("high", 0)
            total_low  += low
            total_mid  += mid
            total_high += high
            clean.append({
                "id":            a["id"],
                "name":          a["name"],
                "category":      a.get("category", ""),
                "status":        a.get("status", "idle"),
                "monthly_low":   low,
                "monthly_mid":   mid,
                "monthly_high":  high,
                "eta_days":      a.get("time_to_first_revenue_days", 0),
                "last_run":      a.get("last_run"),
                "revenue_model": a.get("revenue_model", ""),
                "notes":         a.get("notes", ""),
            })
        summary = {"total_low": total_low, "total_mid": total_mid, "total_high": total_high, "asset_count": len(clean)}
        return {"assets": clean, "summary": summary}
    except Exception as e:
        logger.warning(f"money/assets failed: {e}")
        return {"error": str(e), "assets": [], "summary": {}}


# ─── NEXORA Platform API ──────────────────────────────────────────────────────

_nexora_outputs_dir = ROOT / "outputs" / "agent_workforce" / "102_nexora_builder"

@app.get("/api/nexora/status")
async def nexora_status():
    """NEXORA platform status and latest recruitment output."""
    import glob as _glob
    outputs = sorted(_glob.glob(str(_nexora_outputs_dir / "nexora_recruit_*.md")), reverse=True)
    recruit_content = ""
    if outputs:
        try:
            recruit_content = Path(outputs[0]).read_text(errors="replace")[:2000]
        except Exception:
            pass
    posts_today = len([
        f for f in outputs
        if Path(f).stat().st_mtime > (__import__('time').time() - 86400)
    ])
    pages = [
        {"name": "Landing Page",      "file": "index.html",     "url": "/frontend/nexora/index.html"},
        {"name": "Creator Dashboard",  "file": "creator.html",   "url": "/frontend/nexora/creator.html"},
        {"name": "Fan Subscribe Page", "file": "subscribe.html", "url": "/frontend/nexora/subscribe.html"},
        {"name": "Live Stream Room",   "file": "live.html",      "url": "/frontend/nexora/live.html"},
    ]
    pages_built = [p for p in pages if (ROOT / "frontend" / "nexora" / p["file"]).exists()]
    # Pull real ConvertKit subscriber count
    ck_subscribers = 0
    try:
        from core.convertkit import get_convertkit
        ck_subscribers = get_convertkit().get_subscriber_count()
    except Exception:
        pass
    # Pull local lead count tagged nexora
    nexora_leads = 0
    try:
        from core.email_capture import get_email_capture
        stats = get_email_capture().get_stats()
        nexora_leads = stats.get("total", 0)
    except Exception:
        pass
    nexora_stripe_url = os.getenv("STRIPE_NEXORA_URL", os.getenv("STRIPE_PRO_URL", ""))
    return {
        "status":          "live" if pages_built else "building",
        "pages_built":     len(pages_built),
        "pages":           pages_built,
        "posts_today":     posts_today,
        "founding_spots":  50,
        "spots_taken":     nexora_leads,
        "mrr":             0,
        "subscribers":     ck_subscribers,
        "leads":           nexora_leads,
        "recruit_content": recruit_content,
        "stripe_set":      bool(nexora_stripe_url),
        "stripe_url":      nexora_stripe_url,
        "beta_url":        os.getenv("NEXORA_BETA_URL", "https://nexora.wheellsverse.com/beta"),
        "waitlist_url":    os.getenv("NEXORA_WAITLIST_URL", "https://wheellsverse.ck.page/nexora"),
    }


@app.post("/api/nexora/recruit")
async def nexora_recruit(background_tasks: BackgroundTasks):
    """Run the NEXORA recruitment bot — generates creator recruitment posts."""
    def _run():
        try:
            from bots.revenue.bot_09_nexora_beta import NexoraBetaBot
            bot = NexoraBetaBot()
            bot.run(action="recruit")
            _add_log("NEXORA recruitment posts generated", "INFO")
        except ImportError:
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT / "bots" / "revenue" / "09_nexora_beta"))
                import importlib as _il
                spec = _il.util.spec_from_file_location("bot", ROOT/"bots"/"revenue"/"09_nexora_beta"/"bot.py")
                mod  = _il.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.NexoraBetaBot().run(action="recruit")
                _add_log("NEXORA recruitment posts generated", "INFO")
            except Exception as e:
                _add_log(f"NEXORA recruit failed: {e}", "ERROR")
    background_tasks.add_task(_run)
    return {"status": "running", "message": "Generating recruitment posts..."}


@app.post("/api/nexora/growth")
async def nexora_growth(background_tasks: BackgroundTasks):
    """Run NEXORA growth strategy generator."""
    def _run():
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT))
            spec_path = ROOT / "bots" / "revenue" / "09_nexora_beta" / "bot.py"
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("bot09", spec_path)
            mod  = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.NexoraBetaBot().run(action="status")
            _add_log("NEXORA growth strategy generated", "INFO")
        except Exception as e:
            _add_log(f"NEXORA growth failed: {e}", "ERROR")
    background_tasks.add_task(_run)
    return {"status": "running", "message": "Generating growth strategy..."}


@app.get("/frontend/nexora/{filename}")
async def serve_nexora_page(filename: str):
    """Serve NEXORA frontend pages (long path form)."""
    from fastapi.responses import FileResponse
    path = ROOT / "frontend" / "nexora" / filename
    if not path.exists() or path.suffix != ".html":
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(str(path), media_type="text/html")

# ── Clean short URLs: /nexora, /nexora/creator, /nexora/subscribe, /nexora/live
@app.get("/nexora")
@app.get("/nexora/")
async def nexora_index():
    from fastapi.responses import FileResponse
    return FileResponse(str(ROOT / "frontend" / "nexora" / "index.html"), media_type="text/html")

@app.get("/nexora/join")
@app.get("/nexora/subscribe")
@app.get("/nexora/subscribe.html")
async def nexora_subscribe():
    from fastapi.responses import FileResponse
    return FileResponse(str(ROOT / "frontend" / "nexora" / "subscribe.html"), media_type="text/html")

@app.get("/nexora/dashboard")
@app.get("/nexora/creator")
@app.get("/nexora/creator.html")
async def nexora_creator():
    from fastapi.responses import FileResponse
    return FileResponse(str(ROOT / "frontend" / "nexora" / "creator.html"), media_type="text/html")

@app.get("/nexora/live")
@app.get("/nexora/live.html")
async def nexora_live():
    from fastapi.responses import FileResponse
    return FileResponse(str(ROOT / "frontend" / "nexora" / "live.html"), media_type="text/html")

@app.get("/nexora/fan")
@app.get("/nexora/fan.html")
async def nexora_fan():
    from fastapi.responses import FileResponse
    return FileResponse(str(ROOT / "frontend" / "nexora" / "fan.html"), media_type="text/html")


# ─── NEXORA Platform — Real Backend ──────────────────────────────────────────
#
#  Auth:         POST /api/nx/register  POST /api/nx/login  POST /api/nx/logout
#  Profile:      GET  /api/nx/me        PATCH /api/nx/me
#  Posts:        GET/POST /api/nx/posts  DELETE /api/nx/posts/{id}
#  Public:       GET /api/nx/creator/{handle}  GET /api/nx/creator/{handle}/posts
#  Subscribers:  GET /api/nx/subscribers  POST /api/nx/subscribe
#  Earnings:     GET /api/nx/earnings
#  Payouts:      GET/POST /api/nx/payouts
#  Messages:     GET/POST /api/nx/messages
#  Stats:        GET /api/nx/stats
#  Stripe hook:  POST /api/nx/stripe-webhook
# ─────────────────────────────────────────────────────────────────────────────

def _nx_public():
    """Public nexora paths — no auth required."""
    return {
        "/api/nx/register", "/api/nx/login",
        "/api/nx/creator",  # prefix checked below
    }

def _nx_get_creator(request: Request) -> Optional[Dict]:
    """Extract creator from Bearer token. Returns None if missing/invalid."""
    from core.nexora_auth import verify_token
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    return verify_token(token)

def _nx_require_creator(request: Request) -> Dict:
    creator = _nx_get_creator(request)
    if not creator:
        raise HTTPException(status_code=401, detail="Login required")
    return creator


# ── Auth ───────────────────────────────────────────────────────────────────────

class _NxRegisterReq(BaseModel):
    email:    str
    password: str
    name:     str

class _NxLoginReq(BaseModel):
    email:    str
    password: str

@app.post("/api/nx/register")
async def nx_register(req: _NxRegisterReq):
    from core.nexora_db   import init_db
    from core.nexora_auth import register_creator
    init_db()
    result = register_creator(req.email, req.password, req.name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/nx/login")
async def nx_login(req: _NxLoginReq):
    from core.nexora_db   import init_db
    from core.nexora_auth import login_creator
    init_db()
    result = login_creator(req.email, req.password)
    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])
    return result

@app.post("/api/nx/logout")
async def nx_logout(request: Request):
    from core.nexora_auth import revoke_token
    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        revoke_token(token)
    return {"status": "logged_out"}


# ── Creator profile ────────────────────────────────────────────────────────────

@app.get("/api/nx/me")
async def nx_me(request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import get_creator_stats
    stats = get_creator_stats(creator["id"])
    return {**creator, **stats}

class _NxProfileReq(BaseModel):
    name:          Optional[str] = None
    bio:           Optional[str] = None
    avatar:        Optional[str] = None
    price:         Optional[float] = None
    payout_method: Optional[str] = None
    stripe_link:   Optional[str] = None

@app.patch("/api/nx/me")
async def nx_update_profile(req: _NxProfileReq, request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import update_creator_profile, get_creator_by_id
    fields = {k: v for k, v in req.dict().items() if v is not None}
    update_creator_profile(creator["id"], fields)
    return get_creator_by_id(creator["id"])


# ── Posts ──────────────────────────────────────────────────────────────────────

class _NxPostReq(BaseModel):
    title:      str = ""
    body:       str = ""
    access:     str = "subscribers"
    media_urls: List[str] = []

@app.get("/api/nx/posts")
async def nx_list_my_posts(request: Request, limit: int = 50):
    creator = _nx_require_creator(request)
    from core.nexora_db import list_posts
    return {"posts": list_posts(creator["id"], limit=limit)}

@app.post("/api/nx/posts")
async def nx_create_post(req: _NxPostReq, request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import create_post
    post_id = create_post(creator["id"], req.title, req.body, req.access, req.media_urls)
    return {"id": post_id, "status": "created"}

@app.delete("/api/nx/posts/{post_id}")
async def nx_delete_post(post_id: int, request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import delete_post
    delete_post(post_id, creator["id"])
    return {"status": "deleted"}

# Public — fan view of creator + posts
@app.get("/api/nx/creator/{handle}")
async def nx_public_creator(handle: str):
    from core.nexora_db import get_creator_by_handle, get_active_subscriber_count, list_posts
    creator = get_creator_by_handle(handle)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    subs = get_active_subscriber_count(creator["id"])
    free_posts = [p for p in list_posts(creator["id"], limit=20) if p["access"] == "free"]
    return {
        "name":        creator["name"],
        "handle":      creator["handle"],
        "bio":         creator["bio"],
        "avatar":      creator["avatar"],
        "price":       creator["price"],
        "subscribers": subs,
        "free_posts":  free_posts,
    }

@app.get("/api/nx/creator/{handle}/posts")
async def nx_public_posts(handle: str, request: Request):
    """Return posts for a fan — subscribers see all, others only free."""
    from core.nexora_db import (get_creator_by_handle, list_posts, get_conn)
    creator = get_creator_by_handle(handle)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    posts = list_posts(creator["id"], limit=50)
    # Check if the requesting fan has an active subscription
    fan_email = request.query_params.get("fan_email", "")
    is_subscribed = False
    if fan_email:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM nx_subscribers WHERE creator_id=? AND fan_email=? AND status='active'",
            (creator["id"], fan_email)
        ).fetchone()
        conn.close()
        is_subscribed = bool(row)
    # Filter locked posts
    visible = []
    for p in posts:
        if p["access"] == "free" or is_subscribed:
            visible.append(p)
        else:
            visible.append({**p, "body": "", "media_urls": [], "locked": True})
    return {"posts": visible, "is_subscribed": is_subscribed}


# ── Subscribers ────────────────────────────────────────────────────────────────

@app.get("/api/nx/subscribers")
async def nx_list_subscribers(request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import list_subscribers, get_active_subscriber_count
    subs = list_subscribers(creator["id"])
    return {
        "total":       len(subs),
        "active":      get_active_subscriber_count(creator["id"]),
        "subscribers": subs,
    }

class _NxSubscribeReq(BaseModel):
    creator_handle: str
    fan_email:      str
    fan_name:       str = ""
    price_paid:     float = 0
    stripe_cust:    str = ""

@app.post("/api/nx/subscribe")
async def nx_subscribe(req: _NxSubscribeReq):
    """Called after Stripe checkout completes to record a new fan subscriber."""
    from core.nexora_db import get_creator_by_handle, add_subscriber, record_transaction
    creator = get_creator_by_handle(req.creator_handle)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    add_subscriber(creator["id"], req.fan_email, req.fan_name, req.price_paid, req.stripe_cust)
    if req.price_paid > 0:
        record_transaction(creator["id"], req.price_paid, "subscription", req.fan_email)
    # Also enroll in ConvertKit
    try:
        from core.convertkit import get_convertkit
        get_convertkit().add_subscriber(req.fan_email, req.fan_name, tags=["nexora_subscriber"])
    except Exception:
        pass
    return {"status": "subscribed", "creator": creator["name"]}


# ── Earnings ───────────────────────────────────────────────────────────────────

@app.get("/api/nx/earnings")
async def nx_earnings(request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import get_earnings
    return get_earnings(creator["id"])


# ── Payouts ────────────────────────────────────────────────────────────────────

class _NxPayoutReq(BaseModel):
    amount: float
    method: str = "bank"

@app.post("/api/nx/payouts")
async def nx_request_payout(req: _NxPayoutReq, request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import get_earnings, request_payout
    earnings = get_earnings(creator["id"])
    available = earnings["total"]
    if req.amount < 20:
        raise HTTPException(status_code=400, detail="Minimum payout is $20")
    if req.amount > available:
        raise HTTPException(status_code=400, detail=f"Only ${available:.2f} available")
    result = request_payout(creator["id"], req.amount, req.method)
    return result

@app.get("/api/nx/payouts")
async def nx_list_payouts(request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import list_payouts, get_pending_payout_amount
    return {
        "payouts":  list_payouts(creator["id"]),
        "pending":  get_pending_payout_amount(creator["id"]),
    }


# ── Messages ───────────────────────────────────────────────────────────────────

class _NxMessageReq(BaseModel):
    fan_email: str
    body:      str
    sender:    str = "creator"

@app.get("/api/nx/messages")
async def nx_list_messages(request: Request, fan_email: str = ""):
    creator = _nx_require_creator(request)
    from core.nexora_db import list_messages, mark_messages_read
    msgs = list_messages(creator["id"], fan_email)
    mark_messages_read(creator["id"])
    return {"messages": msgs}

@app.post("/api/nx/messages")
async def nx_send_message(req: _NxMessageReq, request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import send_message
    msg_id = send_message(creator["id"], req.fan_email, req.sender, req.body)
    return {"id": msg_id, "status": "sent"}


# ── Full stats for creator dashboard ──────────────────────────────────────────

@app.get("/api/nx/stats")
async def nx_stats(request: Request):
    creator = _nx_require_creator(request)
    from core.nexora_db import get_creator_stats
    return get_creator_stats(creator["id"])


# ── Stripe webhook — record subscriptions from real payments ──────────────────

@app.post("/api/nx/stripe-webhook")
async def nx_stripe_webhook(request: Request):
    """
    Handle Stripe checkout.session.completed events.
    Expects metadata: {creator_handle, fan_email, fan_name}
    """
    import json as _json
    body = await request.body()
    try:
        event = _json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    if event_type in ("checkout.session.completed", "invoice.payment_succeeded"):
        obj      = event.get("data", {}).get("object", {})
        meta     = obj.get("metadata", {})
        handle   = meta.get("creator_handle", "")
        fan_email = (
            meta.get("fan_email")
            or obj.get("customer_email")
            or obj.get("customer_details", {}).get("email", "")
        )
        fan_name  = meta.get("fan_name", "")
        amount    = obj.get("amount_total", 0) / 100  # cents → dollars
        stripe_id = obj.get("id", "")

        if handle and fan_email:
            from core.nexora_db import (get_creator_by_handle, add_subscriber,
                                         record_transaction)
            creator = get_creator_by_handle(handle)
            if creator:
                add_subscriber(creator["id"], fan_email, fan_name, amount, stripe_id)
                record_transaction(creator["id"], amount, "subscription",
                                   fan_email, stripe_id)
                _add_log(f"NEXORA: new subscriber {fan_email} → @{handle} (${amount})", "INFO")

    return {"received": True}


# ── Fan auth endpoints ────────────────────────────────────────────────────────

class _NxFanRegisterReq(BaseModel):
    email:    str
    password: str

class _NxFanLoginReq(BaseModel):
    email:    str
    password: str

@app.post("/api/nx/fan/register")
async def nx_fan_register(req: _NxFanRegisterReq):
    from core.nexora_db   import init_db
    from core.nexora_auth import register_fan
    init_db()
    result = register_fan(req.email, req.password)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/nx/fan/login")
async def nx_fan_login(req: _NxFanLoginReq):
    from core.nexora_db   import init_db
    from core.nexora_auth import login_fan
    init_db()
    result = login_fan(req.email, req.password)
    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])
    return result

@app.post("/api/nx/fan/logout")
async def nx_fan_logout(request: Request):
    from core.nexora_db import revoke_fan_token
    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        revoke_fan_token(token)
    return {"ok": True}

@app.get("/api/nx/fan/me")
async def nx_fan_me(request: Request):
    from core.nexora_db import verify_fan_token, get_fan_subscriptions, init_db
    init_db()
    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    fan_email = verify_fan_token(token)
    if not fan_email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    subs = get_fan_subscriptions(fan_email)
    return {"fan_email": fan_email, "subscriptions": subs}

@app.get("/api/nx/fan/content/{handle}")
async def nx_fan_content(handle: str, request: Request):
    """Return unlocked posts for a subscribed fan."""
    from core.nexora_db import (verify_fan_token, get_creator_by_handle,
                                  get_fan_subscriptions, list_posts, init_db)
    init_db()
    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    fan_email = verify_fan_token(token) if token else None

    creator = get_creator_by_handle(handle)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    posts = list_posts(creator["id"])
    # Check if fan is subscribed
    is_subscribed = False
    if fan_email:
        subs = get_fan_subscriptions(fan_email)
        is_subscribed = any(s["creator_id"] == creator["id"] for s in subs)

    result = []
    for p in posts:
        if p["access"] == "free" or is_subscribed:
            result.append({**p, "locked": False})
        else:
            result.append({"id": p["id"], "title": p["title"], "access": p["access"],
                           "created_at": p["created_at"], "locked": True})
    return {"posts": result, "is_subscribed": is_subscribed, "fan_email": fan_email}


# ─── Week 8: Trending Intelligence API ───────────────────────────────────────

@app.get("/api/trending/summary")
async def trending_summary():
    from core.trending import TrendingEngine
    return TrendingEngine.get().summary()

@app.get("/api/trending/top")
async def trending_top(niche: str = "", limit: int = 10):
    from core.trending import get_top
    return {"trends": get_top(niche, limit), "niche": niche or "all"}

@app.get("/api/trending/best")
async def trending_best(platform: str = "", niche: str = ""):
    from core.trending import get_best_topic
    topic = get_best_topic(platform, niche)
    return topic or {"message": "No trending topics yet — run /api/trending/refresh first"}

@app.get("/api/trending/viral")
async def trending_viral():
    from core.trending import TrendingEngine
    opps = TrendingEngine.get().get_viral_opportunities()
    return {"count": len(opps), "opportunities": opps}

@app.post("/api/trending/refresh")
async def trending_refresh(background_tasks: BackgroundTasks):
    from core.trending import TrendingEngine
    background_tasks.add_task(TrendingEngine.get().refresh)
    return {"status": "refreshing"}


# ─── Week 8: Conversion Analytics API ────────────────────────────────────────

@app.get("/api/conversion/summary")
async def conversion_summary():
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().summary()

@app.get("/api/conversion/dashboard")
async def conversion_dashboard(days: int = 30):
    from core.conversion_analytics import get_dashboard
    return get_dashboard(days)

@app.get("/api/conversion/funnel")
async def conversion_funnel(days: int = 30, platform: str = "", niche: str = ""):
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().funnel(days, platform, niche)

@app.get("/api/conversion/attribution")
async def conversion_attribution(days: int = 30):
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().attribution(days)

@app.get("/api/conversion/cohorts")
async def conversion_cohorts(weeks: int = 8):
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().cohorts(weeks)

@app.get("/api/conversion/ltv")
async def conversion_ltv(days: int = 90):
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().ltv_by_source(days)

@app.get("/api/conversion/content-roi")
async def conversion_content_roi(days: int = 30):
    from core.conversion_analytics import ConversionAnalytics
    return ConversionAnalytics.get().content_roi(days)

class TrackEventRequest(BaseModel):
    event_type: str
    platform: str = ""
    niche: str = ""
    user_id: str = ""
    content_id: str = ""
    value: float = 0.0

@app.post("/api/conversion/track")
async def conversion_track(req: TrackEventRequest):
    from core.conversion_analytics import track
    return track(req.event_type, req.platform, req.niche,
                 req.user_id, req.content_id, req.value)

class ABTestCreateRequest(BaseModel):
    test_id: str
    name: str
    variants: List[str]

@app.post("/api/conversion/ab/create")
async def conversion_ab_create(req: ABTestCreateRequest):
    from core.conversion_analytics import ConversionAnalytics
    test = ConversionAnalytics.get().create_ab_test(req.test_id, req.name, req.variants)
    return test.to_dict()

class ABRecordRequest(BaseModel):
    test_id: str
    variant: str
    event: str
    value: float = 0.0

@app.post("/api/conversion/ab/record")
async def conversion_ab_record(req: ABRecordRequest):
    from core.conversion_analytics import ConversionAnalytics
    ConversionAnalytics.get().record_ab(req.test_id, req.variant, req.event, req.value)
    test = ConversionAnalytics.get().get_ab_test(req.test_id)
    return test or {"error": "test not found"}

@app.get("/api/conversion/ab/{test_id}")
async def conversion_ab_get(test_id: str):
    from core.conversion_analytics import ConversionAnalytics
    test = ConversionAnalytics.get().get_ab_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    return test

@app.get("/api/conversion/ab")
async def conversion_ab_list():
    from core.conversion_analytics import ConversionAnalytics
    return {"tests": ConversionAnalytics.get().get_all_ab_tests()}


# ─── Week 8: Autopilot API ────────────────────────────────────────────────────

@app.get("/api/autopilot/status")
async def autopilot_status():
    from core.autopilot import AutopilotEngine
    return AutopilotEngine.get().status()

@app.get("/api/autopilot/summary")
async def autopilot_summary():
    from core.autopilot import AutopilotEngine
    return AutopilotEngine.get().summary()

@app.get("/api/autopilot/log")
async def autopilot_log(limit: int = 50):
    from core.autopilot import AutopilotEngine
    return {"log": AutopilotEngine.get().get_log(limit)}

@app.post("/api/autopilot/enable")
async def autopilot_enable(mode: str = "full"):
    from core.autopilot import AutopilotEngine
    AutopilotEngine.get().enable(mode)
    _add_log(f"Autopilot ENABLED — mode: {mode}", "INFO")
    return {"status": "enabled", "mode": mode}

@app.post("/api/autopilot/disable")
async def autopilot_disable():
    from core.autopilot import AutopilotEngine
    AutopilotEngine.get().disable()
    _add_log("Autopilot DISABLED", "INFO")
    return {"status": "disabled"}

@app.post("/api/autopilot/run-now")
async def autopilot_run_now(background_tasks: BackgroundTasks):
    from core.autopilot import AutopilotEngine
    background_tasks.add_task(AutopilotEngine.get().run_hourly)
    _add_log("Autopilot manual hourly cycle triggered", "INFO")
    return {"status": "running"}

@app.post("/api/autopilot/run-daily")
async def autopilot_run_daily(background_tasks: BackgroundTasks):
    from core.autopilot import AutopilotEngine
    background_tasks.add_task(AutopilotEngine.get().run_daily)
    _add_log("Autopilot manual daily cycle triggered", "INFO")
    return {"status": "running"}

@app.post("/api/autopilot/mode")
async def autopilot_set_mode(mode: str):
    from core.autopilot import AutopilotEngine
    valid = ["full", "content_only", "monitor_only"]
    if mode not in valid:
        raise HTTPException(status_code=400, detail=f"Mode must be one of: {valid}")
    AutopilotEngine.get().set_mode(mode)
    return {"status": "updated", "mode": mode}


# ─── Week 7: Revenue Dashboard API ───────────────────────────────────────────

@app.get("/api/revenue/summary")
async def revenue_summary():
    from core.revenue import get_summary
    return get_summary()

@app.get("/api/revenue/dashboard")
async def revenue_dashboard():
    from core.revenue import get_dashboard
    return get_dashboard(refresh_live=True)

@app.post("/api/revenue/record")
async def revenue_record(source: str, label: str, amount: float):
    from core.revenue import record_revenue
    record_revenue(amount, source, label)
    return {"status": "recorded", "source": source, "label": label, "amount": amount}

@app.get("/api/revenue/report")
async def revenue_report():
    from core.revenue import RevenueEngine
    return {"report": RevenueEngine.get().daily_report()}

@app.post("/api/revenue/send-report")
async def revenue_send_report():
    from core.revenue import RevenueEngine
    RevenueEngine.get().send_daily_report()
    return {"status": "sent"}


# ─── Week 7: Content Calendar API ─────────────────────────────────────────────

@app.get("/api/calendar/summary")
async def calendar_summary():
    from core.content_calendar import ContentCalendar
    return ContentCalendar.get().summary()

@app.get("/api/calendar/queue")
async def calendar_queue(platform: str = "", limit: int = 20):
    from core.content_calendar import ContentCalendar
    items = ContentCalendar.get().get_pending(platform)
    return {"total": len(items), "items": [i.to_dict() for i in items[:limit]]}

@app.get("/api/calendar/view")
async def calendar_view():
    from core.content_calendar import ContentCalendar
    cal = ContentCalendar.get()
    return {"calendar": cal._calendar}

class GenerateWeekRequest(BaseModel):
    platforms: List[str] = []
    start_date: str = ""

@app.post("/api/calendar/generate-week")
async def calendar_generate_week(req: GenerateWeekRequest, background_tasks: BackgroundTasks):
    from core.content_calendar import ContentCalendar
    def _run():
        result = ContentCalendar.get().generate_week(
            platforms=req.platforms or None,
            start_date=req.start_date,
        )
        _add_log(f"Calendar generated: {result['days']} days, {result['items_queued']} items", "INFO")
    background_tasks.add_task(_run)
    return {"status": "generating", "platforms": req.platforms or "default"}

class QueuePostRequest(BaseModel):
    platform: str
    topic: str
    content: str = ""
    scheduled_time: str = ""
    content_type: str = "post"

@app.post("/api/calendar/queue")
async def calendar_queue_post(req: QueuePostRequest):
    from core.content_calendar import ContentCalendar
    item = ContentCalendar.get().add(
        req.platform, req.topic, req.content,
        req.scheduled_time, req.content_type,
    )
    _add_log(f"Queued: {req.platform} — {req.topic[:40]}", "INFO")
    return item.to_dict()

@app.delete("/api/calendar/queue/{item_id}")
async def calendar_remove(item_id: str):
    from core.content_calendar import ContentCalendar
    removed = ContentCalendar.get().remove(item_id)
    return {"removed": removed, "id": item_id}

@app.post("/api/calendar/process-due")
async def calendar_process_due(background_tasks: BackgroundTasks):
    from core.content_calendar import ContentCalendar
    def _run():
        results = ContentCalendar.get().process_due()
        _add_log(f"Processed {len(results)} due queue items", "INFO")
    background_tasks.add_task(_run)
    return {"status": "processing"}


# ─── Week 7: Lead Capture API ─────────────────────────────────────────────────

@app.get("/api/leads/summary")
async def leads_summary():
    from core.lead_capture import LeadCaptureEngine
    return LeadCaptureEngine.get().summary()

@app.get("/api/leads/all")
async def leads_all(limit: int = 50):
    from core.lead_capture import LeadCaptureEngine
    leads = LeadCaptureEngine.get().get_all(limit)
    return {"total": len(leads), "leads": leads}

class LeadCaptureRequest(BaseModel):
    contact: str       # email or phone
    name: str = ""
    source: str = "landing_page"
    platform: str = ""
    user_id: str = ""
    niche: str = "general"

@app.post("/api/leads/capture")
async def leads_capture(req: LeadCaptureRequest, background_tasks: BackgroundTasks):
    from core.lead_capture import LeadCaptureEngine
    def _run():
        LeadCaptureEngine.get().capture(
            req.contact, req.name, req.source,
            req.platform, req.user_id, niche=req.niche,
        )
        _add_log(f"Lead captured: {req.contact} via {req.source}", "INFO")
    background_tasks.add_task(_run)
    return {"status": "capturing", "contact": req.contact}

@app.post("/api/leads/capture-sync")
async def leads_capture_sync(req: LeadCaptureRequest):
    from core.lead_capture import LeadCaptureEngine
    result = LeadCaptureEngine.get().capture(
        req.contact, req.name, req.source,
        req.platform, req.user_id, niche=req.niche,
    )
    _add_log(f"Lead captured: {req.contact} via {req.source}", "INFO")
    return result

class OptinCheckRequest(BaseModel):
    message: str
    platform: str = ""
    user_id: str = ""
    handle: str = ""

@app.post("/api/leads/check-optin")
async def leads_check_optin(req: OptinCheckRequest):
    from core.lead_capture import LeadCaptureEngine
    engine = LeadCaptureEngine.get()
    triggered = engine.detect_optin(req.message)
    result = {"triggered": triggered}
    if triggered and req.platform and req.user_id:
        result = engine.handle_optin_message(
            req.platform, req.user_id, req.message, req.handle
        )
    return result

@app.post("/api/leads/re-engage")
async def leads_re_engage(background_tasks: BackgroundTasks):
    from core.lead_capture import LeadCaptureEngine
    background_tasks.add_task(LeadCaptureEngine.get().re_engage_cold_leads)
    return {"status": "re-engaging"}


# ─── Week 6: Content Repurposer API ──────────────────────────────────────────

class RepurposeRequest(BaseModel):
    content: str = ""
    title: str = ""
    topic: str = ""
    niche: str = "general"
    formats: List[str] = []

@app.post("/api/repurpose/content")
async def repurpose_content_v2(req: RepurposeRequest, background_tasks: BackgroundTasks):
    from core.repurpose import repurpose, repurpose_topic
    if not req.content and not req.topic:
        raise HTTPException(status_code=400, detail="Provide 'content' or 'topic'")
    def _run():
        if req.content:
            result = repurpose(req.content, title=req.title,
                               formats=req.formats or None)
        else:
            result = repurpose_topic(req.topic, niche=req.niche,
                                     formats=req.formats or None)
        _add_log(f"Repurposed: {result.get('title','')[:50]} → {len(result.get('formats',{}))} formats", "INFO")
    background_tasks.add_task(_run)
    return {"status": "repurposing", "topic": req.topic or req.title,
            "formats_requested": req.formats or "all"}

@app.post("/api/repurpose/topic")
async def repurpose_from_topic(req: RepurposeRequest):
    """Synchronous version — returns all formats in one response."""
    from core.repurpose import repurpose_topic, repurpose
    if not req.topic and not req.content:
        raise HTTPException(status_code=400, detail="Provide 'topic' or 'content'")
    if req.content:
        result = repurpose(req.content, title=req.title, formats=req.formats or None)
    else:
        result = repurpose_topic(req.topic, niche=req.niche, formats=req.formats or None)
    _add_log(f"Repurposed sync: {result.get('title','')[:50]}", "INFO")
    return result

@app.get("/api/repurpose/formats")
async def repurpose_formats():
    from core.repurpose import FORMATS
    return {"formats": list(FORMATS.keys()), "count": len(FORMATS)}


# ─── Week 6: SEO Autopilot API ────────────────────────────────────────────────

@app.get("/api/seo/summary")
async def seo_summary():
    from core.seo import summary
    return summary()

class SEOScoreRequest(BaseModel):
    content: str
    keyword: str = ""

@app.post("/api/seo/score")
async def seo_score(req: SEOScoreRequest):
    from core.seo import score_content
    return score_content(req.content, req.keyword)

class SEOOptimizeRequest(BaseModel):
    content: str
    keyword: str
    title: str = ""

@app.post("/api/seo/optimize")
async def seo_optimize(req: SEOOptimizeRequest):
    from core.seo import optimize_content
    return optimize_content(req.content, req.keyword, req.title)

class SEOResearchRequest(BaseModel):
    topic: str
    niche: str = "general"
    count: int = 10

@app.post("/api/seo/research")
async def seo_research(req: SEOResearchRequest):
    from core.seo import research_keywords
    return research_keywords(req.topic, req.niche, req.count)

@app.get("/api/seo/quick-wins")
async def seo_quick_wins(niche: str = "general"):
    from core.seo import get_quick_wins
    wins = get_quick_wins(niche)
    return {"niche": niche, "quick_wins": wins, "count": len(wins)}

@app.get("/api/seo/gsc")
async def seo_gsc(days: int = 28):
    from core.seo import get_gsc_insights
    return get_gsc_insights(days)

class SEOGenerateRequest(BaseModel):
    keyword: str
    niche: str = "general"

@app.post("/api/seo/generate")
async def seo_generate(req: SEOGenerateRequest, background_tasks: BackgroundTasks):
    from core.seo import generate_seo_content
    def _run():
        result = generate_seo_content(req.keyword, req.niche)
        _add_log(f"SEO content generated: '{req.keyword}' — score {result.get('seo_score')}", "INFO")
    background_tasks.add_task(_run)
    return {"status": "generating", "keyword": req.keyword}

@app.post("/api/seo/rank")
async def seo_rank(keyword: str, position: float, impressions: int = 0, clicks: int = 0):
    from core.seo import update_ranking
    update_ranking(keyword, position, impressions, clicks)
    return {"status": "recorded", "keyword": keyword, "position": position}


# ─── Week 6: Performance Dashboard API ───────────────────────────────────────

@app.get("/api/performance/summary")
async def performance_summary_v2():
    from core.performance import get_summary
    return get_summary()

@app.get("/api/performance/dashboard")
async def performance_dashboard_v2():
    from core.performance import get_dashboard
    return get_dashboard()

@app.post("/api/performance/refresh-full")
async def performance_refresh_full(background_tasks: BackgroundTasks):
    from core.performance import refresh_performance, get_dashboard
    def _run():
        refresh_performance()
        get_dashboard()
    background_tasks.add_task(_run)
    return {"status": "refreshing"}

@app.get("/api/performance/topics")
async def performance_topics_v2():
    from core.performance import _load_json, PERF_FILE
    perf = _load_json(PERF_FILE, {})
    topics = sorted(perf.get("topics", {}).items(), key=lambda x: x[1], reverse=True)
    return {"topics": [{"topic": t, "score": round(s, 1)} for t, s in topics[:20]]}


# ─── Week 5: Personality Engine API ──────────────────────────────────────────

@app.get("/api/personality/summary")
async def personality_summary():
    from core.personality import PersonalityEngine
    return PersonalityEngine.get().summary()

@app.get("/api/personality/prompt")
async def personality_prompt(platform: str = "twitter", topic: str = ""):
    from core.personality import PersonalityEngine
    return {
        "platform": platform,
        "topic": topic,
        "prompt": PersonalityEngine.get().get_full_prompt(platform, topic),
    }

@app.get("/api/personality/platforms")
async def personality_platforms():
    from core.personality import PLATFORM_TONES
    return {"platforms": list(PLATFORM_TONES.keys()),
            "tones": {k: {"style": v["style"], "format": v["format"]}
                      for k, v in PLATFORM_TONES.items()}}

class PersonalityStateRequest(BaseModel):
    state: str

@app.post("/api/personality/state")
async def personality_set_state(req: PersonalityStateRequest):
    from core.personality import PersonalityEngine, EMOTIONAL_STATES
    if req.state not in EMOTIONAL_STATES:
        raise HTTPException(status_code=400,
            detail=f"Invalid state. Choose: {', '.join(EMOTIONAL_STATES.keys())}")
    PersonalityEngine.get().set_emotional_state(req.state)
    return {"status": "updated", "state": req.state}

class StyleOverrideRequest(BaseModel):
    platform: str
    instruction: str

@app.post("/api/personality/override")
async def personality_override(req: StyleOverrideRequest):
    from core.personality import PersonalityEngine
    PersonalityEngine.get().set_style_override(req.platform, req.instruction)
    return {"status": "saved", "platform": req.platform}

@app.post("/api/personality/performance")
async def personality_perf(platform: str, score: float):
    from core.personality import PersonalityEngine
    PersonalityEngine.get().update_platform_performance(platform, score)
    return {"status": "recorded", "platform": platform, "score": score}


# ─── Week 5: People Memory API ───────────────────────────────────────────────

@app.get("/api/people/summary")
async def people_summary():
    from core.people_memory import PeopleMemory
    return PeopleMemory.get().summary()

@app.get("/api/people/all")
async def people_all(platform: str = "", limit: int = 50):
    from core.people_memory import PeopleMemory
    people = PeopleMemory.get().get_all(platform)
    return {"total": len(people), "people": people[:limit]}

@app.get("/api/people/vip")
async def people_vip():
    from core.people_memory import PeopleMemory
    vips = PeopleMemory.get().get_vip_list()
    return {"total": len(vips), "vips": vips}

@app.get("/api/people/hot-leads")
async def people_hot():
    from core.people_memory import PeopleMemory
    leads = PeopleMemory.get().get_hot_leads()
    return {"total": len(leads), "leads": leads}

@app.get("/api/people/cold-leads")
async def people_cold():
    from core.people_memory import PeopleMemory
    leads = PeopleMemory.get().get_cold_leads()
    return {"total": len(leads), "leads": leads}

@app.get("/api/people/customers")
async def people_customers():
    from core.people_memory import PeopleMemory
    customers = PeopleMemory.get().get_customers()
    return {"total": len(customers), "customers": customers}

@app.get("/api/people/search")
async def people_search(q: str):
    from core.people_memory import PeopleMemory
    results = PeopleMemory.get().search(q)
    return {"query": q, "results": results}

@app.get("/api/people/person")
async def people_person(platform: str, user_id: str):
    from core.people_memory import PeopleMemory
    person = PeopleMemory.get().get_person(platform, user_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person

@app.get("/api/people/context")
async def people_context(platform: str, user_id: str):
    from core.people_memory import PeopleMemory
    return {
        "platform": platform,
        "user_id": user_id,
        "context": PeopleMemory.get().get_relationship_prompt(platform, user_id),
    }

class RememberRequest(BaseModel):
    platform: str
    user_id: str
    message: str
    direction: str = "inbound"
    intent: str = ""
    topic: str = ""
    handle: str = ""
    sentiment_delta: float = 0.0

@app.post("/api/people/remember")
async def people_remember(req: RememberRequest):
    from core.people_memory import PeopleMemory
    p = PeopleMemory.get().remember(
        req.platform, req.user_id, req.message,
        direction=req.direction, intent=req.intent,
        topic=req.topic, handle=req.handle,
        sentiment_delta=req.sentiment_delta,
    )
    return {"status": "remembered", "uid": p.uid, "stage": p.purchase_stage,
            "interactions": p.interaction_count}

class TagRequest(BaseModel):
    platform: str
    user_id: str
    tag: str

@app.post("/api/people/tag")
async def people_tag(req: TagRequest):
    from core.people_memory import PeopleMemory
    PeopleMemory.get().add_tag(req.platform, req.user_id, req.tag)
    return {"status": "tagged", "tag": req.tag}

class ConvertRequest(BaseModel):
    platform: str
    user_id: str

@app.post("/api/people/convert")
async def people_convert(req: ConvertRequest):
    from core.people_memory import PeopleMemory
    PeopleMemory.get().mark_converted(req.platform, req.user_id)
    return {"status": "marked_converted"}


# ─── Week 5: Goal Tracker API ─────────────────────────────────────────────────

@app.get("/api/goals/summary")
async def goals_summary():
    from core.goal_tracker import GoalTracker
    return GoalTracker.get().summary()

@app.get("/api/goals/report")
async def goals_report():
    from core.goal_tracker import GoalTracker
    return {"report": GoalTracker.get().daily_report()}

@app.get("/api/goals/priority")
async def goals_priority():
    from core.goal_tracker import GoalTracker
    g = GoalTracker.get().get_priority_goal()
    return g.to_dict() if g else {"message": "All goals achieved!"}

@app.get("/api/goals/lagging")
async def goals_lagging(threshold: float = 50.0):
    from core.goal_tracker import GoalTracker
    lagging = GoalTracker.get().get_lagging_goals(threshold)
    return {"threshold_pct": threshold, "lagging": [g.to_dict() for g in lagging]}

@app.get("/api/goals/prompt")
async def goals_prompt(platform: str = "", topic: str = ""):
    from core.goal_tracker import GoalTracker
    gt = GoalTracker.get()
    return {
        "goal_prompt": gt.get_goal_prompt(),
        "content_directive": gt.get_content_directive(platform, topic),
    }

class GoalUpdateRequest(BaseModel):
    goal_key: str
    value: float

@app.post("/api/goals/update")
async def goals_update(req: GoalUpdateRequest):
    from core.goal_tracker import GoalTracker
    GoalTracker.get().update(req.goal_key, req.value)
    g = GoalTracker.get()._goals.get(req.goal_key)
    return {"status": "updated", "goal": req.goal_key,
            "progress_pct": g.progress_pct if g else None}

class GoalIncrementRequest(BaseModel):
    goal_key: str
    amount: int = 1

@app.post("/api/goals/increment")
async def goals_increment(req: GoalIncrementRequest):
    from core.goal_tracker import GoalTracker
    GoalTracker.get().increment(req.goal_key, req.amount)
    g = GoalTracker.get()._goals.get(req.goal_key)
    return {"status": "incremented", "goal": req.goal_key,
            "new_value": g.current if g else None,
            "progress_pct": g.progress_pct if g else None}

class GoalTargetRequest(BaseModel):
    goal_key: str
    target: float

@app.post("/api/goals/set-target")
async def goals_set_target(req: GoalTargetRequest):
    from core.goal_tracker import GoalTracker
    GoalTracker.get().set_target(req.goal_key, req.target)
    return {"status": "updated", "goal": req.goal_key, "new_target": req.target}

@app.post("/api/goals/send-report")
async def goals_send_report():
    from core.goal_tracker import GoalTracker
    GoalTracker.get().send_daily_report()
    return {"status": "sent"}

@app.post("/api/goals/reset-monthly")
async def goals_reset_monthly():
    from core.goal_tracker import GoalTracker
    GoalTracker.get().reset_monthly_goals()
    return {"status": "monthly_goals_reset"}


# ══════════════════════════════════════════════════════════════════════════════
# ─── ETSY ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_ETSY_BASE          = "https://openapi.etsy.com/v3"
_ETSY_TOKEN_FILE    = Path(os.getenv("RAILWAY_VOLUME_PATH", "/var/data")) / "etsy_token.json"
_etsy_pkce_store: dict = {}

def _etsy_save_token(data: dict):
    try:
        _ETSY_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ETSY_TOKEN_FILE.write_text(json.dumps(data))
    except Exception as e:
        logger.warning(f"Failed to save Etsy token: {e}")

def _etsy_load_token() -> dict:
    try:
        if _ETSY_TOKEN_FILE.exists():
            return json.loads(_ETSY_TOKEN_FILE.read_text())
    except Exception as e:
        logger.warning(f"Failed to load Etsy token: {e}")
    return {}

def _etsy_access_token() -> str:
    """Return valid Etsy access token, refreshing if needed."""
    tok_data = _etsy_load_token()
    if not tok_data: return os.getenv("ETSY_ACCESS_TOKEN", "")
    # Check expiry
    if tok_data.get("expires_at", 0) < time.time() + 60:
        # Refresh
        rt = tok_data.get("refresh_token", "") or os.getenv("ETSY_REFRESH_TOKEN", "")
        kid = os.getenv("ETSY_KEYSTRING", "")
        if rt and kid:
            try:
                import requests as _rc
                r = _rc.post("https://api.etsy.com/v3/public/oauth/token", data={
                    "grant_type": "refresh_token",
                    "client_id":  kid,
                    "refresh_token": rt,
                }, timeout=15)
                if r.status_code == 200:
                    new_data = r.json()
                    new_data["expires_at"] = time.time() + new_data.get("expires_in", 3600)
                    new_data.setdefault("refresh_token", rt)
                    _etsy_save_token(new_data)
                    return new_data["access_token"]
            except Exception as e:
                logger.warning(f"Etsy token refresh failed: {e}")
    return tok_data.get("access_token", os.getenv("ETSY_ACCESS_TOKEN", ""))

def _etsy_headers() -> dict:
    tok = _etsy_access_token()
    kid = os.getenv("ETSY_KEYSTRING", "")
    return {"Authorization": f"Bearer {tok}", "x-api-key": kid}

_PUBLIC_PATHS.add("/api/etsy/oauth-callback")
_PUBLIC_PATHS.add("/api/etsy/oauth-url")

@app.get("/api/etsy/oauth-url")
async def etsy_oauth_url(request: Request):
    """
    Generate Etsy OAuth2 PKCE authorization URL.
    Always uses RAILWAY_PUBLIC_URL as redirect so the callback always hits
    the production server — no in-memory state required across machines.
    PKCE verifier is encoded inside the state parameter (stateless PKCE).
    """
    import urllib.parse, secrets, hashlib, base64 as _b64
    kid = os.getenv("ETSY_KEYSTRING", "")
    if not kid:
        return {"error": "ETSY_KEYSTRING not set in .env"}

    # Always use Railway URL so redirect works regardless of which server
    # the browser hits when generating the URL (local dev or Railway)
    railway_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    if not railway_url:
        host = request.headers.get("host", "localhost:8080")
        scheme = "https" if not host.startswith("localhost") and not host.startswith("127") else "http"
        railway_url = f"{scheme}://{host}"
    redirect_uri = railway_url + "/api/etsy/oauth-callback"

    # Stateless PKCE: embed verifier in state so no server-side store needed.
    # state = "{nonce}.{base64url(verifier)}"  — callback splits on first "."
    code_verifier  = secrets.token_urlsafe(64)
    nonce          = secrets.token_urlsafe(8)
    state          = nonce + "." + _b64.urlsafe_b64encode(code_verifier.encode()).rstrip(b"=").decode()
    code_challenge = _b64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    params = {
        "response_type":         "code",
        "client_id":             kid,
        "redirect_uri":          redirect_uri,
        "scope":                 "listings_r listings_w listings_d shops_r transactions_r",
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    }
    url = "https://www.etsy.com/oauth/connect?" + urllib.parse.urlencode(params)
    return {"url": url, "redirect_uri": redirect_uri}


@app.get("/api/etsy/oauth-callback")
async def etsy_oauth_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    import base64 as _b64
    if error:
        return HTMLResponse(f"""<html><body style='background:#0d0f14;color:#ff6060;font-family:monospace;
            display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
            <div style='text-align:center;padding:40px;background:#13161d;border:1px solid #ff606044;border-radius:16px'>
            <div style='font-size:40px'>❌</div>
            <div style='font-size:16px;margin-top:12px'>Etsy error: {error}</div>
            <div style='font-size:11px;color:#8891a8;margin-top:8px'>Close this tab and try again from the dashboard.</div>
            </div></body></html>""")
    if not code:
        return HTMLResponse("<h2 style='color:red'>No code received from Etsy</h2>")
    if not state or "." not in state:
        return HTMLResponse("<h2 style='color:red'>Invalid state — please reconnect from the dashboard.</h2>")

    # Extract verifier from stateless PKCE state
    try:
        verifier_b64 = state.split(".", 1)[1]
        # Re-add padding
        pad = 4 - len(verifier_b64) % 4
        code_verifier = _b64.urlsafe_b64decode(verifier_b64 + "=" * (pad % 4)).decode()
    except Exception:
        return HTMLResponse("<h2 style='color:red'>Could not decode state — please reconnect.</h2>")

    railway_url  = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    if not railway_url:
        host   = request.headers.get("host", "")
        scheme = "https" if not host.startswith("localhost") and not host.startswith("127") else "http"
        railway_url = f"{scheme}://{host}"
    redirect_uri = railway_url + "/api/etsy/oauth-callback"

    try:
        import requests as _rc
        kid = os.getenv("ETSY_KEYSTRING", "")
        r = _rc.post("https://api.etsy.com/v3/public/oauth/token", data={
            "grant_type":    "authorization_code",
            "client_id":     kid,
            "redirect_uri":  redirect_uri,
            "code":          code,
            "code_verifier": code_verifier,
        }, timeout=15)
        if r.status_code != 200:
            return HTMLResponse(f"""<html><body style='background:#0d0f14;color:#ff6060;font-family:monospace;
                display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
                <div style='text-align:center;padding:40px;background:#13161d;border:1px solid #ff606044;border-radius:16px'>
                <div style='font-size:40px'>❌</div>
                <div style='font-size:14px;margin-top:12px'>Token exchange failed ({r.status_code})</div>
                <div style='font-size:11px;color:#8891a8;margin-top:8px;max-width:400px'>{r.text[:300]}</div>
                <div style='font-size:11px;color:#8891a8;margin-top:8px'>Redirect URI used: {redirect_uri}</div>
                </div></body></html>""")
        data = r.json()
        data["expires_at"] = time.time() + data.get("expires_in", 3600)
        _etsy_save_token(data)
        _add_log("✅ Etsy OAuth connected successfully", "INFO")
        return HTMLResponse("""
        <html><body style='background:#0d0f14;color:#00ff88;font-family:monospace;
              display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
        <div style='text-align:center;padding:40px;background:#13161d;border:1px solid #00ff8844;border-radius:16px'>
          <div style='font-size:40px;margin-bottom:16px'>✅</div>
          <div style='font-size:18px;font-weight:700;color:#f0a500;margin-bottom:8px'>Etsy Connected!</div>
          <div style='font-size:12px;color:#8891a8;margin-bottom:20px'>You can close this tab and return to the dashboard.</div>
          <script>if(window.opener){window.opener.postMessage('etsy_connected','*');setTimeout(()=>window.close(),1500);}else{setTimeout(()=>{window.location.href='/';},2000);}</script>
        </div></body></html>""")
    except Exception as e:
        return HTMLResponse(f"<h2 style='color:red'>Error: {e}</h2>")


@app.get("/api/etsy/status")
async def etsy_status():
    """Validate Etsy token, return shop info + listing summary."""
    tok = _etsy_access_token()
    if not tok:
        return {"connected": False, "error": "Not connected — click Connect Etsy to authorize"}
    try:
        import requests as _rc
        # Get current user
        ur = _rc.get(f"{_ETSY_BASE}/application/users/me", headers=_etsy_headers(), timeout=10)
        if ur.status_code == 401:
            return {"connected": False, "error": "Etsy token expired — reconnect"}
        if ur.status_code != 200:
            return {"connected": False, "error": f"Etsy error {ur.status_code}"}
        user = ur.json()
        user_id = user.get("user_id", "")

        # Get shop
        shop_id = os.getenv("ETSY_SHOP_ID", "")
        shop = {}
        listings = []
        revenue  = 0.0
        if shop_id:
            sr = _rc.get(f"{_ETSY_BASE}/application/shops/{shop_id}", headers=_etsy_headers(), timeout=10)
            if sr.status_code == 200: shop = sr.json()
            # Active listings
            lr = _rc.get(f"{_ETSY_BASE}/application/shops/{shop_id}/listings/active",
                         headers=_etsy_headers(), params={"limit": 50}, timeout=10)
            if lr.status_code == 200:
                listings = lr.json().get("results", [])
            # Receipts (sales)
            rr = _rc.get(f"{_ETSY_BASE}/application/shops/{shop_id}/receipts",
                         headers=_etsy_headers(), params={"limit": 25}, timeout=10)
            if rr.status_code == 200:
                receipts = rr.json().get("results", [])
                revenue = sum(
                    float(r.get("grandtotal", {}).get("amount", 0)) / 100
                    for r in receipts
                )
        else:
            # Auto-discover shop from user
            shops_r = _rc.get(f"{_ETSY_BASE}/application/users/{user_id}/shops",
                               headers=_etsy_headers(), timeout=10)
            if shops_r.status_code == 200:
                shops = shops_r.json().get("results", [])
                if shops:
                    shop    = shops[0]
                    shop_id = str(shop.get("shop_id", ""))

        return {
            "connected":       True,
            "user_id":         str(user_id),
            "shop_id":         shop_id,
            "shop_name":       shop.get("shop_name", ""),
            "shop_url":        f"https://www.etsy.com/shop/{shop.get('shop_name','')}",
            "listings_count":  len(listings),
            "total_revenue":   round(revenue, 2),
            "listings": [
                {
                    "id":          str(l.get("listing_id", "")),
                    "title":       l.get("title", ""),
                    "price":       float(l.get("price", {}).get("amount", 0)) / 100,
                    "currency":    l.get("price", {}).get("currency_code", "USD"),
                    "quantity":    l.get("quantity", 0),
                    "state":       l.get("state", ""),
                    "url":         l.get("url", ""),
                    "views":       l.get("views", 0),
                    "image":       ((l.get("images") or [{}])[0]).get("url_570xN", ""),
                }
                for l in listings
            ],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.post("/api/etsy/listing")
async def etsy_create_listing(req: dict):
    """
    Create a new Etsy digital listing.
    Body: {title, description, price, quantity, tags (list), type ('download'|'made_to_order')}
    Note: After creating, you must upload the digital file via Etsy dashboard.
    """
    tok = _etsy_access_token()
    if not tok:
        return {"error": "Etsy not connected — authorize first"}
    shop_id = os.getenv("ETSY_SHOP_ID", "")
    if not shop_id:
        # Try to get it from status
        st = await etsy_status()
        shop_id = st.get("shop_id", "")
    if not shop_id:
        return {"error": "ETSY_SHOP_ID not set — add it to .env after connecting"}
    try:
        import requests as _rc
        price_cents = int(float(req.get("price", 0)) * 100)
        tags = req.get("tags", [])[:13]  # Etsy max 13 tags
        payload = {
            "title":             req.get("title", "WheellsVerse Digital Download"),
            "description":       req.get("description", ""),
            "price":             price_cents,
            "quantity":          req.get("quantity", 999),
            "who_made":          "i_did",
            "when_made":         "made_to_order",
            "taxonomy_id":       6206,  # Art & Collectibles > Digital Prints
            "type":              "download",
            "shipping_profile_id": None,
            "state":             "draft",
            "tags":              tags,
            "is_digital":        True,
            "file_data":         "",
        }
        r = _rc.post(
            f"{_ETSY_BASE}/application/shops/{shop_id}/listings",
            headers={**_etsy_headers(), "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if r.status_code not in (200, 201):
            return {"error": f"Etsy {r.status_code}: {r.text[:300]}"}
        data = r.json()
        _add_log(f"Etsy listing created: {payload['title']}", "INFO")
        return {
            "id":    str(data.get("listing_id", "")),
            "title": data.get("title", ""),
            "url":   data.get("url", ""),
            "state": data.get("state", ""),
        }
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/etsy/listing/{listing_id}")
async def etsy_delete_listing(listing_id: str):
    """Delete an Etsy listing."""
    tok = _etsy_access_token()
    if not tok: return {"error": "Etsy not connected"}
    shop_id = os.getenv("ETSY_SHOP_ID", "")
    if not shop_id: return {"error": "ETSY_SHOP_ID not set"}
    try:
        import requests as _rc
        r = _rc.delete(f"{_ETSY_BASE}/application/shops/{shop_id}/listings/{listing_id}",
                       headers=_etsy_headers(), timeout=15)
        if r.status_code not in (200, 204):
            return {"error": f"Etsy {r.status_code}: {r.text[:200]}"}
        _add_log(f"Etsy listing deleted: {listing_id}", "INFO")
        return {"deleted": True}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# ─── GUMROAD ─────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_GUMROAD_BASE = "https://api.gumroad.com/v2"

def _gumroad_token() -> str:
    return os.getenv("GUMROAD_ACCESS_TOKEN", "")

def _gumroad_headers() -> dict:
    return {"Authorization": f"Bearer {_gumroad_token()}"}


@app.get("/api/gumroad/status")
async def gumroad_status():
    """Validate token, return user info + product + sales summary."""
    tok = _gumroad_token()
    if not tok:
        return {"connected": False, "error": "GUMROAD_ACCESS_TOKEN not set in .env"}
    try:
        import requests as _rc
        # Gumroad: GET /user returns current user
        ur = _rc.get(f"{_GUMROAD_BASE}/user", headers=_gumroad_headers(), timeout=10)
        if ur.status_code == 401:
            return {"connected": False, "error": "Invalid Gumroad token — check GUMROAD_ACCESS_TOKEN"}
        if ur.status_code != 200:
            return {"connected": False, "error": f"Gumroad error {ur.status_code}"}
        user = ur.json().get("user", {})

        # Products
        pr = _rc.get(f"{_GUMROAD_BASE}/products", headers=_gumroad_headers(), timeout=10)
        products = pr.json().get("products", []) if pr.status_code == 200 else []

        # Sales summary
        sr = _rc.get(f"{_GUMROAD_BASE}/sales", headers=_gumroad_headers(), timeout=10)
        sales_raw = sr.json().get("sales", []) if sr.status_code == 200 else []
        total_revenue = sum(float(s.get("price", 0)) / 100 for s in sales_raw)

        return {
            "connected":     True,
            "name":          user.get("name", ""),
            "email":         user.get("email", ""),
            "bio":           user.get("bio", ""),
            "profile_url":   user.get("profile_url", ""),
            "products_count": len(products),
            "sales_count":   len(sales_raw),
            "total_revenue": round(total_revenue, 2),
            "products": [
                {
                    "id":           p.get("id", ""),
                    "name":         p.get("name", ""),
                    "price":        p.get("price", 0),
                    "currency":     p.get("currency", "usd"),
                    "sales_count":  p.get("sales_count", 0),
                    "published":    p.get("published", False),
                    "url":          p.get("short_url", ""),
                    "description":  (p.get("description", "") or "")[:120],
                    "product_type": p.get("product_type", "digital"),
                    "cover_url":    (p.get("thumbnail_url") or ""),
                }
                for p in products
            ],
            "recent_sales": [
                {
                    "id":            s.get("id", ""),
                    "product_name":  s.get("product_name", ""),
                    "price":         round(float(s.get("price", 0)) / 100, 2),
                    "email":         s.get("email", ""),
                    "created_at":    s.get("created_at", ""),
                    "country":       s.get("country", ""),
                }
                for s in sales_raw[:20]
            ],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.post("/api/gumroad/product")
async def gumroad_create_product(req: dict):
    """
    Create a new Gumroad product.
    Body: {name, price_cents, description, url (optional file URL), category}
    """
    tok = _gumroad_token()
    if not tok:
        return {"error": "GUMROAD_ACCESS_TOKEN not set"}
    try:
        import requests as _rc
        payload = {
            "name":        req.get("name", "WheellsVerse Product"),
            "price":       int(req.get("price_cents", 0)),
            "description": req.get("description", ""),
            "published":   req.get("published", False),
        }
        if req.get("url"):
            payload["url"] = req["url"]
        r = _rc.post(f"{_GUMROAD_BASE}/products", headers=_gumroad_headers(), data=payload, timeout=15)
        if r.status_code not in (200, 201):
            return {"error": f"Gumroad {r.status_code}: {r.text[:200]}"}
        p = r.json().get("product", {})
        _add_log(f"Gumroad product created: {payload['name']}", "INFO")
        return {
            "id":        p.get("id", ""),
            "name":      p.get("name", ""),
            "short_url": p.get("short_url", ""),
            "price":     p.get("price", 0),
            "published": p.get("published", False),
        }
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/gumroad/product/{product_id}")
async def gumroad_update_product(product_id: str, req: dict):
    """Update name, price, description, or published state."""
    tok = _gumroad_token()
    if not tok:
        return {"error": "GUMROAD_ACCESS_TOKEN not set"}
    try:
        import requests as _rc
        payload = {}
        if "name"        in req: payload["name"]        = req["name"]
        if "price_cents" in req: payload["price"]       = int(req["price_cents"])
        if "description" in req: payload["description"] = req["description"]
        if "published"   in req: payload["published"]   = req["published"]
        r = _rc.put(f"{_GUMROAD_BASE}/products/{product_id}", headers=_gumroad_headers(), data=payload, timeout=15)
        if r.status_code != 200:
            return {"error": f"Gumroad {r.status_code}: {r.text[:200]}"}
        p = r.json().get("product", {})
        _add_log(f"Gumroad product updated: {product_id}", "INFO")
        return {"id": p.get("id"), "name": p.get("name"), "published": p.get("published")}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/gumroad/product/{product_id}")
async def gumroad_delete_product(product_id: str):
    """Permanently delete a Gumroad product."""
    tok = _gumroad_token()
    if not tok:
        return {"error": "GUMROAD_ACCESS_TOKEN not set"}
    try:
        import requests as _rc
        r = _rc.delete(f"{_GUMROAD_BASE}/products/{product_id}", headers=_gumroad_headers(), timeout=15)
        if r.status_code != 200:
            return {"error": f"Gumroad {r.status_code}: {r.text[:200]}"}
        _add_log(f"Gumroad product deleted: {product_id}", "INFO")
        return {"deleted": True}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/gumroad/product/{product_id}/toggle")
async def gumroad_toggle_product(product_id: str, req: dict):
    """Enable or disable (publish/unpublish) a product. Body: {published: bool}"""
    tok = _gumroad_token()
    if not tok:
        return {"error": "GUMROAD_ACCESS_TOKEN not set"}
    try:
        import requests as _rc
        published = req.get("published", True)
        endpoint = "enable" if published else "disable"
        r = _rc.put(f"{_GUMROAD_BASE}/products/{product_id}/{endpoint}",
                    headers=_gumroad_headers(), timeout=15)
        if r.status_code != 200:
            return {"error": f"Gumroad {r.status_code}: {r.text[:200]}"}
        state = "enabled" if published else "disabled"
        _add_log(f"Gumroad product {state}: {product_id}", "INFO")
        return {"product_id": product_id, "published": published}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# ─── PAYHIP ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_PAYHIP_BASE          = "https://payhip.com/api/v1"
_PAYHIP_DATA_DIR      = Path(os.getenv("RAILWAY_VOLUME_PATH", str(ROOT / "data")))
_PAYHIP_WEBHOOK_FILE  = _PAYHIP_DATA_DIR / "payhip_sales.json"
_PAYHIP_STATE_FILE    = _PAYHIP_DATA_DIR / "payhip_state.json"
_PUBLIC_PATHS.add("/api/payhip/webhook")
_PUBLIC_PATHS.add("/api/payhip/mark-registered")

def _payhip_token() -> str:
    return os.getenv("PAYHIP_API_KEY", "")

def _payhip_headers() -> dict:
    return {"Authorization": f"Bearer {_payhip_token()}", "Content-Type": "application/json"}

def _payhip_load_sales() -> list:
    try:
        if _PAYHIP_WEBHOOK_FILE.exists():
            return json.loads(_PAYHIP_WEBHOOK_FILE.read_text())
    except Exception:
        pass
    return []

def _payhip_save_sales(sales: list):
    try:
        _PAYHIP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _PAYHIP_WEBHOOK_FILE.write_text(json.dumps(sales, indent=2))
    except Exception:
        pass

def _payhip_load_state() -> dict:
    try:
        if _PAYHIP_STATE_FILE.exists():
            return json.loads(_PAYHIP_STATE_FILE.read_text())
    except Exception:
        pass
    return {"verified": False, "registered": False, "last_event_at": None, "last_event_type": None, "event_count": 0}

def _payhip_save_state(state: dict):
    try:
        _PAYHIP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _PAYHIP_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass

def _payhip_fetch_railway_data() -> dict:
    """
    When running locally, try to fetch live data from Railway deployment.
    Returns empty dict if unavailable.
    """
    railway_url = os.getenv("RAILWAY_PUBLIC_URL", "")
    if not railway_url or "127.0.0.1" in railway_url or "localhost" in railway_url:
        return {}
    # Only fetch if we're running locally (not on Railway itself)
    is_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME"))
    if is_railway:
        return {}
    try:
        import requests as _rc
        api_key = os.getenv("NARAI_API_KEY", os.getenv("API_KEY", ""))
        headers = {"X-API-Key": api_key} if api_key else {}
        r = _rc.get(f"{railway_url.rstrip('/')}/api/payhip/status", headers=headers, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


@app.post("/api/payhip/webhook")
async def payhip_webhook(request: Request):
    """
    Payhip webhook receiver — no API plan needed.
    Payhip POSTs here on every sale (and sends a test ping when first registered).
    Register this URL in Payhip: Account → Settings → Webhooks → Add Webhook
    URL: https://grateful-flexibility-production.up.railway.app/api/payhip/webhook
    """
    try:
        body = await request.body()
        # Payhip sends form-encoded or JSON
        try:
            data = json.loads(body)
        except Exception:
            from urllib.parse import parse_qs
            parsed = parse_qs(body.decode("utf-8", errors="replace"))
            data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

        now_iso = datetime.now().isoformat()

        # Mark webhook as verified (Payhip sends a test ping on registration)
        state = _payhip_load_state()
        state["verified"]  = True
        state["registered"] = True
        state["last_event_at"] = now_iso
        state["event_count"]   = state.get("event_count", 0) + 1

        # Detect ping / test events (no purchase key, no buyer email, type=test)
        event_type = data.get("event", data.get("type", ""))
        is_ping    = (
            event_type in ("ping", "test", "verification") or
            (not data.get("purchase_key") and not data.get("buyer_email") and not data.get("email"))
        )

        if is_ping:
            state["last_event_type"] = "ping"
            _payhip_save_state(state)
            _add_log("📡 Payhip webhook verified — test ping received", "INFO")
            return {"status": "ok", "type": "ping"}

        state["last_event_type"] = "sale"
        _payhip_save_state(state)

        # Normalise sale fields
        sale = {
            "id":           data.get("purchase_key") or data.get("id") or "",
            "product_name": data.get("product_title") or data.get("product_name") or data.get("title") or "Unknown Product",
            "amount":       float(data.get("price") or data.get("amount") or 0),
            "currency":     (data.get("currency") or "USD").upper(),
            "email":        data.get("buyer_email") or data.get("email") or "",
            "country":      data.get("buyer_country") or data.get("country") or "",
            "created_at":   data.get("purchase_date") or data.get("created_at") or now_iso,
            "raw":          data,
        }

        sales = _payhip_load_sales()
        if sale["id"] and any(s.get("id") == sale["id"] for s in sales):
            return {"status": "duplicate"}
        sales.insert(0, sale)
        _payhip_save_sales(sales[:500])

        _add_log(f"💳 Payhip sale: {sale['product_name']} — ${sale['amount']} from {sale['email']}", "INFO")

        try:
            from core.telegram import notify
            notify(
                f"💳 <b>New Payhip Sale!</b>\n"
                f"📦 Product: {sale['product_name']}\n"
                f"💵 Amount: ${sale['amount']} {sale['currency']}\n"
                f"📧 Buyer: {sale['email']} ({sale['country']})"
            )
        except Exception:
            pass

        return {"status": "ok", "type": "sale"}
    except Exception as e:
        _add_log(f"Payhip webhook error: {e}", "ERROR")
        return {"status": "error", "detail": str(e)}


@app.post("/api/payhip/mark-registered")
async def payhip_mark_registered():
    """User manually confirms they've registered the webhook in Payhip."""
    state = _payhip_load_state()
    state["registered"] = True
    if not state.get("verified"):
        state["last_event_type"] = "manual"
    _payhip_save_state(state)
    return {"status": "ok", "registered": True}


@app.get("/api/payhip/status")
async def payhip_status():
    """
    Return Payhip status. Merges local webhook data with Railway live data when running locally.
    """
    tok          = _payhip_token()
    wh_state     = _payhip_load_state()
    webhook_sales = _payhip_load_sales()
    railway_url  = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    webhook_url  = (railway_url or "http://localhost:5050") + "/api/payhip/webhook"

    # If running locally and Railway is configured, pull live data from Railway
    railway_data = _payhip_fetch_railway_data()
    if railway_data:
        # Merge Railway sales into local (Railway is source of truth for webhook events)
        railway_sales = railway_data.get("recent_purchases", [])
        if railway_sales:
            webhook_sales = railway_sales
        railway_state = railway_data.get("webhook_state", {})
        if railway_state.get("verified"):
            wh_state["verified"]  = True
            wh_state["registered"] = True

    total_revenue = sum(float(s.get("amount", 0)) for s in webhook_sales)

    # Try the REST API — works on Plus plan
    if tok:
        try:
            import requests as _rc
            pr = _rc.get(f"{_PAYHIP_BASE}/product", headers=_payhip_headers(), timeout=8)
            if pr.status_code == 200:
                products_data = pr.json()
                products = products_data.get("data", products_data if isinstance(products_data, list) else [])
                purr = _rc.get(f"{_PAYHIP_BASE}/purchase", headers=_payhip_headers(), timeout=8)
                purchases = []
                if purr.status_code == 200:
                    pdata = purr.json()
                    purchases = pdata.get("data", pdata if isinstance(pdata, list) else [])
                    total_revenue = sum(float(p.get("amount", 0)) for p in purchases)
                return {
                    "connected":        True,
                    "api_active":       True,
                    "webhook_mode":     False,
                    "webhook_url":      webhook_url,
                    "webhook_state":    wh_state,
                    "products_count":   len(products),
                    "sales_count":      len(purchases),
                    "total_revenue":    round(total_revenue, 2),
                    "products":         [
                        {
                            "id":          p.get("link", p.get("id", "")),
                            "name":        p.get("title", p.get("name", "Untitled")),
                            "price":       p.get("price", 0),
                            "currency":    p.get("currency", "usd"),
                            "sales_count": p.get("total_sales", 0),
                            "published":   p.get("active", True),
                            "url":         f"https://payhip.com/b/{p.get('link','')}",
                            "description": (p.get("description", "") or "")[:120],
                            "cover_url":   (p.get("cover_image", "") or ""),
                        }
                        for p in products
                    ],
                    "recent_purchases": [
                        {
                            "id":           p.get("purchase_key", p.get("id", "")),
                            "product_name": p.get("product_title", p.get("product_name", "")),
                            "amount":       float(p.get("amount", 0)),
                            "email":        p.get("email", ""),
                            "created_at":   p.get("created_at", ""),
                            "country":      p.get("country", ""),
                        }
                        for p in purchases[:20]
                    ],
                }
        except Exception:
            pass

    # Webhook-only mode (free plan) — always "connected", uses webhook events for sales
    return {
        "connected":        True,
        "api_active":       False,
        "webhook_mode":     True,
        "webhook_url":      webhook_url,
        "webhook_state":    wh_state,
        "webhook_verified": wh_state.get("verified", False),
        "webhook_registered": wh_state.get("registered", False),
        "last_event_at":    wh_state.get("last_event_at"),
        "last_event_type":  wh_state.get("last_event_type"),
        "products_count":   0,
        "sales_count":      len(webhook_sales),
        "total_revenue":    round(total_revenue, 2),
        "products":         [],
        "recent_purchases": webhook_sales[:20],
        "note":             "Webhook mode active — sales tracked automatically. API products list requires Payhip Plus plan.",
        "railway_url":      railway_url,
    }


@app.post("/api/payhip/product")
async def payhip_create_product(req: dict):
    """
    Create a new Payhip digital product.
    Body: {name, price, description, type ('ebook'|'course'|'software'|'other')}
    Note: Payhip API allows product creation; file upload is done via dashboard.
    """
    tok = _payhip_token()
    if not tok:
        return {"error": "PAYHIP_API_KEY not set"}
    try:
        import requests as _rc
        payload = {
            "title":       req.get("name", "WheellsVerse Product"),
            "price":       float(req.get("price", 0)),
            "description": req.get("description", ""),
            "type":        req.get("type", "ebook"),
        }
        r = _rc.post(f"{_PAYHIP_BASE}/product", headers=_payhip_headers(),
                     json=payload, timeout=15)
        if r.status_code not in (200, 201):
            return {"error": f"Payhip {r.status_code}: {r.text[:200]}"}
        p = r.json()
        _add_log(f"Payhip product created: {payload['title']}", "INFO")
        return {
            "id":    p.get("link", p.get("id", "")),
            "name":  p.get("title", payload["title"]),
            "url":   f"https://payhip.com/b/{p.get('link','')}",
            "price": p.get("price", payload["price"]),
        }
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/payhip/product/{product_id}")
async def payhip_delete_product(product_id: str):
    """Archive/delete a Payhip product."""
    tok = _payhip_token()
    if not tok:
        return {"error": "PAYHIP_API_KEY not set"}
    try:
        import requests as _rc
        r = _rc.delete(f"{_PAYHIP_BASE}/product/{product_id}",
                       headers=_payhip_headers(), timeout=15)
        if r.status_code not in (200, 204):
            return {"error": f"Payhip {r.status_code}: {r.text[:200]}"}
        _add_log(f"Payhip product deleted: {product_id}", "INFO")
        return {"deleted": True}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/payhip/prepare")
async def payhip_prepare_product(req: dict):
    """
    Generate a high-converting product description using Claude.
    Returns title, price, description ready to paste into Payhip.
    Body: {name, price, type, includes, description (optional)}
    """
    name     = req.get("name", "").strip()
    price    = req.get("price", 0)
    ptype    = req.get("type", "ebook")
    includes = req.get("includes", "")
    desc     = req.get("description", "").strip()

    if not name:
        return {"error": "Product name is required"}

    # If user already wrote a description, just return it
    if desc and len(desc) > 50:
        return {"title": name, "price": price, "description": desc}

    # Generate with Claude
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        prompt = (
            f"Write a high-converting Payhip product description for:\n"
            f"Product: {name}\n"
            f"Type: {ptype}\n"
            f"What's included: {includes or 'digital download'}\n"
            f"Price: ${price}\n\n"
            "Write a compelling product description (200-350 words) that:\n"
            "- Opens with the #1 pain point this product solves\n"
            "- Lists 5-7 specific things included (bullet points with ✓)\n"
            "- Explains who it's perfect for\n"
            "- Ends with a clear call to action\n"
            "- Mentions it's an instant digital download\n"
            "Keep it professional, warm, and benefit-focused. No hype or false claims.\n"
            "Return ONLY the description text, no extra commentary."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        generated = msg.content[0].text.strip()
        _add_log(f"Payhip product description generated: {name}", "INFO")
        return {"title": name, "price": price, "description": generated}
    except Exception:
        # Fallback: return basic template
        fallback = (
            f"{name}\n\n"
            f"Get instant access to this {ptype} — {includes or 'digital download'}.\n\n"
            f"✓ Instant digital download\n"
            f"✓ Easy to use\n"
            f"✓ Professional quality\n\n"
            f"Perfect for creators, entrepreneurs, and anyone who wants to save time.\n\n"
            f"Download immediately after purchase. 100% digital."
        )
        return {"title": name, "price": price, "description": fallback}


# ══════════════════════════════════════════════════════════════════════════════
# ─── PRODUCT FACTORY — NarAI-Orchestrated Daily Publishing Pipeline ───────────
# ══════════════════════════════════════════════════════════════════════════════

_PF_STATE_FILE = Path(os.getenv("RAILWAY_VOLUME_PATH", str(ROOT / "data"))) / "product_factory_state.json"
_PF_LOG_FILE   = Path(os.getenv("RAILWAY_VOLUME_PATH", str(ROOT / "data"))) / "product_factory_log.json"
_pf_running    = False   # guard flag
_pf_thread     = None

_PF_PLATFORMS = {
    "gumroad": {"name": "Gumroad",  "icon": "🛒", "target": 4, "color": "#ffb347"},
    "payhip":  {"name": "Payhip",   "icon": "💳", "color": "#00c896", "target": 4},
    "etsy":    {"name": "Etsy",     "icon": "🛍️", "color": "#f98a6c", "target": 3},
    "kdp":     {"name": "Amazon KDP","icon": "📚", "color": "#ff9933", "target": 2},
}

_PF_NICHES = [
    # Digital templates
    "Canva social media templates for coaches", "Instagram story templates for real estate",
    "Notion productivity templates for students", "Resume templates for tech jobs",
    "Business plan templates for startups", "Budget tracker spreadsheet templates",
    # eBooks
    "How to make money with digital products", "Passive income with Canva templates",
    "AI tools for entrepreneurs beginner guide", "Social media marketing for small businesses",
    "Crypto investing for beginners", "Freelancing blueprint 2025",
    # Printables
    "Daily planner printables", "Habit tracker printables", "Goal setting worksheets",
    "Meal planning printables", "Wedding planning checklist printables",
    # Courses / Guides
    "ChatGPT prompt guide for content creators", "How to sell digital products on Etsy",
    "Canva beginner to pro course", "Build passive income with KDP",
    "YouTube channel growth guide", "TikTok affiliate marketing blueprint",
]

_PF_PRODUCT_TYPES = {
    "gumroad": ["ebook", "template_pack", "prompt_pack", "guide", "course_pdf"],
    "payhip":  ["ebook", "template", "printable", "guide", "course_pdf"],
    "etsy":    ["template", "printable", "planner", "worksheet", "canva_template"],
    "kdp":     ["ebook"],
}

def _pf_load_state() -> dict:
    try:
        if _PF_STATE_FILE.exists():
            return json.loads(_PF_STATE_FILE.read_text())
    except Exception:
        pass
    return {
        "running": False, "session_id": None, "started_at": None,
        "products_today": {}, "total_products": 0, "total_revenue": 0.0,
        "current_phase": "idle", "current_task": "", "sessions": [],
    }

def _pf_save_state(state: dict):
    try:
        _PF_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PF_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass

def _pf_load_log() -> list:
    try:
        if _PF_LOG_FILE.exists():
            return json.loads(_PF_LOG_FILE.read_text())
    except Exception:
        pass
    return []

def _pf_log(msg: str, level: str = "INFO", extra: dict = None):
    """Append a log entry to the factory log."""
    entry = {
        "ts":    datetime.now().isoformat(),
        "level": level,
        "msg":   msg,
        **(extra or {}),
    }
    try:
        log = _pf_load_log()
        log.insert(0, entry)
        log = log[:2000]
        _PF_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PF_LOG_FILE.write_text(json.dumps(log))
    except Exception:
        pass
    _add_log(f"[ProductFactory] {msg}", level)

def _pf_claude(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Call Claude directly for the factory pipeline."""
    import anthropic as _ant
    client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    msgs = [{"role": "user", "content": prompt}]
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system or "You are a world-class digital product creator and marketer.",
        messages=msgs,
    )
    return r.content[0].text.strip()


def _pf_research_niche(niche: str) -> dict:
    """Use NarAI / Claude to deep-analyze a niche and generate product ideas."""
    _pf_log(f"🔍 Researching niche: {niche}")
    prompt = (
        f"You are the world's best digital product researcher.\n"
        f"Analyze this niche deeply: '{niche}'\n\n"
        "Deliver a JSON object (no markdown, valid JSON only) with:\n"
        "{\n"
        '  "niche": "...",\n'
        '  "demand_score": 1-10,\n'
        '  "competition": "low|medium|high",\n'
        '  "best_platform": "gumroad|payhip|etsy|kdp",\n'
        '  "product_ideas": [\n'
        '    {"title": "...", "type": "ebook|template|printable|guide|course_pdf", '
        '"price": 9.99, "unique_angle": "...", "target_buyer": "...", "pain_point": "..."}\n'
        "  ],\n"
        '  "keywords": ["keyword1", "keyword2", "keyword3"],\n'
        '  "hook": "one sentence that sells this product immediately"\n'
        "}\n"
        "Return 3-4 product ideas. Pure JSON, no explanation."
    )
    try:
        raw = _pf_claude(prompt, max_tokens=1200)
        # Strip markdown fences if present
        import re as _re
        raw = _re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = _re.sub(r"\n?```$", "", raw.strip())
        return json.loads(raw)
    except Exception as e:
        _pf_log(f"Niche research parse error: {e}", "WARNING")
        return {"niche": niche, "product_ideas": [], "demand_score": 5}


def _pf_create_product_content(idea: dict, platform: str) -> dict:
    """Generate full product content (description, body, title, tags) for a product idea."""
    title   = idea.get("title", "Digital Product")
    ptype   = idea.get("type", "ebook")
    price   = idea.get("price", 9.99)
    hook    = idea.get("hook", "")
    target  = idea.get("target_buyer", "entrepreneurs")
    pain    = idea.get("pain_point", "")

    _pf_log(f"✍️ Creating product content: {title} [{ptype}] for {platform}")

    # Generate full product body
    if ptype in ("ebook", "guide", "course_pdf"):
        body_prompt = (
            f"Write a complete, high-quality {ptype} on: '{title}'\n"
            f"Target buyer: {target}\n"
            f"Pain point solved: {pain}\n\n"
            "Structure:\n"
            "- Introduction (hook + promise)\n"
            "- 5-8 chapters with actionable content, each 400-600 words\n"
            "- Each chapter: concept + 3-5 actionable steps + quick win\n"
            "- Conclusion with next steps\n"
            "- Bonus resource list\n\n"
            "Write professional, valuable content. No fluff. Real insights.\n"
            "Format with ## headers for chapters."
        )
        body = _pf_claude(body_prompt, max_tokens=4000)
    else:
        # Templates/printables: generate detailed description + structure guide
        body_prompt = (
            f"Create a detailed product guide for: '{title}' ({ptype})\n"
            f"Target buyer: {target}\n\n"
            "Deliver:\n"
            "1. Product overview (what's included, exact files, formats)\n"
            "2. How to use guide (step-by-step)\n"
            "3. Customization instructions\n"
            "4. FAQ (5 common questions)\n"
            "5. Bonus tips for best results\n\n"
            "Write as if this is the README/instruction document included with the product."
        )
        body = _pf_claude(body_prompt, max_tokens=2000)

    # Generate platform-optimized listing
    listing_prompt = (
        f"Write a {platform} product listing for: '{title}'\n"
        f"Type: {ptype} | Price: ${price} | Target: {target}\n"
        f"Hook: {hook}\n\n"
        "Return JSON only:\n"
        "{\n"
        '  "title": "optimized title (max 140 chars)",\n'
        '  "description": "high-converting description (250-400 words)",\n'
        '  "tags": ["tag1","tag2","tag3","tag4","tag5"],\n'
        '  "price": ' + str(price) + '\n'
        "}"
    )
    try:
        listing_raw = _pf_claude(listing_prompt, max_tokens=800)
        import re as _re
        listing_raw = _re.sub(r"^```[a-z]*\n?", "", listing_raw.strip())
        listing_raw = _re.sub(r"\n?```$", "", listing_raw.strip())
        listing = json.loads(listing_raw)
    except Exception:
        listing = {
            "title":       title,
            "description": f"{title} — {ptype} for {target}. {hook}",
            "tags":        ["digital download", ptype, target.split()[0]],
            "price":       price,
        }

    return {
        "title":       listing.get("title", title),
        "description": listing.get("description", ""),
        "tags":        listing.get("tags", []),
        "price":       float(listing.get("price", price)),
        "body":        body,
        "type":        ptype,
        "platform":    platform,
        "niche":       idea.get("niche", ""),
    }


def _pf_publish_to_gumroad(product: dict) -> dict:
    """Publish a product to Gumroad via API."""
    tok = _gumroad_token()
    if not tok:
        return {"error": "Gumroad not connected"}
    try:
        import requests as _rc
        payload = {
            "name":        product["title"][:200],
            "price":       int(product["price"] * 100),
            "description": product["description"],
            "published":   True,
        }
        r = _rc.post(f"{_GUMROAD_BASE}/products", headers=_gumroad_headers(), data=payload, timeout=20)
        if r.status_code not in (200, 201):
            return {"error": f"Gumroad {r.status_code}: {r.text[:150]}"}
        p = r.json().get("product", {})
        return {"success": True, "id": p.get("id"), "url": p.get("short_url"), "platform": "gumroad"}
    except Exception as e:
        return {"error": str(e)}


def _pf_publish_to_payhip(product: dict) -> dict:
    """Payhip: no free-tier API — save product file locally for manual upload."""
    out_dir = ROOT / "outputs" / "products" / "payhip"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = product["title"].lower().replace(" ", "_")[:40]
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    fpath = out_dir / f"{safe}_{ts}.md"
    content = (
        f"# {product['title']}\n\n"
        f"**Price:** ${product['price']}\n"
        f"**Type:** {product['type']}\n\n"
        f"## Description\n{product['description']}\n\n"
        f"## Content\n{product['body']}\n"
    )
    fpath.write_text(content, encoding="utf-8")
    return {
        "success": True, "platform": "payhip",
        "file": str(fpath.relative_to(ROOT)),
        "note": "Saved locally — upload at payhip.com/product/add",
        "url":  "https://payhip.com/product/add",
    }


def _pf_publish_to_etsy(product: dict) -> dict:
    """Publish a digital listing to Etsy."""
    tok = _etsy_access_token()
    shop_id = os.getenv("ETSY_SHOP_ID", "")
    if not tok or not shop_id:
        return {"error": "Etsy not connected or ETSY_SHOP_ID not set"}
    try:
        import requests as _rc
        tags = product.get("tags", [])[:13]
        payload = {
            "title":       product["title"][:140],
            "description": product["description"],
            "price":       int(product["price"] * 100),
            "quantity":    999,
            "who_made":    "i_did",
            "when_made":   "made_to_order",
            "taxonomy_id": 6206,
            "type":        "download",
            "state":       "draft",
            "tags":        tags,
            "is_digital":  True,
        }
        r = _rc.post(
            f"{_ETSY_BASE}/application/shops/{shop_id}/listings",
            headers={**_etsy_headers(), "Content-Type": "application/json"},
            json=payload, timeout=20,
        )
        if r.status_code not in (200, 201):
            return {"error": f"Etsy {r.status_code}: {r.text[:150]}"}
        data = r.json()
        return {
            "success": True, "platform": "etsy",
            "id": str(data.get("listing_id", "")),
            "url": data.get("url", ""),
        }
    except Exception as e:
        return {"error": str(e)}


def _pf_publish_to_kdp(product: dict) -> dict:
    """Write a KDP book using the book bot and package it."""
    try:
        genre_map = {
            "make money": "self_help", "passive income": "self_help",
            "crypto": "sci_fi", "marketing": "self_help", "productivity": "self_help",
            "template": "self_help", "freelancing": "self_help",
        }
        title_lower = product["title"].lower()
        genre = next((g for k, g in genre_map.items() if k in title_lower), "self_help")
        out_dir = ROOT / "outputs" / "books" / genre
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = product["title"].lower().replace(" ", "_")[:40]
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = out_dir / f"book_{safe}_{ts}.md"
        fpath.write_text(product["body"], encoding="utf-8")
        return {
            "success": True, "platform": "kdp",
            "file":    str(fpath.relative_to(ROOT)),
            "genre":   genre,
            "note":    "Book saved — run 🎨 Cover + 📦 Pack in KDP dashboard to finalize",
        }
    except Exception as e:
        return {"error": str(e)}


_PF_PUBLISHERS = {
    "gumroad": _pf_publish_to_gumroad,
    "payhip":  _pf_publish_to_payhip,
    "etsy":    _pf_publish_to_etsy,
    "kdp":     _pf_publish_to_kdp,
}


def _pf_run_session(session_id: str, target_per_platform: int, platforms: list,
                    niches_override: list = None):
    """
    Main factory loop — runs in a background thread.
    For each platform: research niches → pick best ideas → create content → publish.
    """
    global _pf_running
    import random, time as _time

    state = _pf_load_state()
    state.update({
        "running": True, "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "current_phase": "starting", "current_task": "Initializing NarAI product factory…",
        "products_today": {p: [] for p in platforms},
        "target_per_platform": target_per_platform,
    })
    _pf_save_state(state)
    _pf_log(f"🚀 Product Factory session {session_id} started | platforms: {platforms} | target: {target_per_platform}/platform")

    try:
        niches = niches_override or _PF_NICHES.copy()
        random.shuffle(niches)

        for platform in platforms:
            if not _pf_running:
                break

            target = target_per_platform
            published = 0
            _pf_log(f"🎯 Platform: {platform.upper()} | target: {target} products")
            state["current_phase"] = f"working_{platform}"
            state["current_task"]  = f"Starting {platform} product creation…"
            _pf_save_state(state)

            niche_pool = niches[:max(8, len(niches))]

            for niche in niche_pool:
                if not _pf_running or published >= target:
                    break

                # ── Phase 1: Research ──────────────────────────────────────
                state["current_task"] = f"🔍 [{platform}] Researching: {niche[:50]}"
                _pf_save_state(state)
                research = _pf_research_niche(niche)
                ideas    = research.get("product_ideas", [])
                if not ideas:
                    _pf_log(f"No ideas for niche '{niche}' — skipping", "WARNING")
                    continue

                # Pick idea best suited for this platform type
                allowed_types = _PF_PRODUCT_TYPES.get(platform, ["ebook"])
                best_idea = next(
                    (i for i in ideas if i.get("type") in allowed_types),
                    ideas[0]
                )
                best_idea["niche"] = niche
                if not best_idea.get("hook"):
                    best_idea["hook"] = research.get("hook", "")

                # ── Phase 2: Create ────────────────────────────────────────
                state["current_task"] = f"✍️ [{platform}] Creating: {best_idea.get('title','')[:50]}"
                _pf_save_state(state)
                try:
                    product = _pf_create_product_content(best_idea, platform)
                except Exception as e:
                    _pf_log(f"Content creation failed for '{best_idea.get('title')}': {e}", "ERROR")
                    continue

                # ── Phase 3: Publish ───────────────────────────────────────
                state["current_task"] = f"📤 [{platform}] Publishing: {product['title'][:50]}"
                _pf_save_state(state)
                publisher = _PF_PUBLISHERS.get(platform)
                if not publisher:
                    _pf_log(f"No publisher for {platform}", "WARNING")
                    continue

                result = publisher(product)
                ts_now = datetime.now().isoformat()

                if result.get("success"):
                    published += 1
                    entry = {
                        "title":    product["title"],
                        "type":     product["type"],
                        "price":    product["price"],
                        "niche":    niche,
                        "platform": platform,
                        "url":      result.get("url", ""),
                        "file":     result.get("file", ""),
                        "note":     result.get("note", ""),
                        "ts":       ts_now,
                    }
                    state["products_today"].setdefault(platform, []).append(entry)
                    state["total_products"] = state.get("total_products", 0) + 1
                    _pf_save_state(state)
                    _pf_log(
                        f"✅ [{platform}] Published #{published}: '{product['title']}' "
                        f"${product['price']} | {result.get('url', result.get('file', ''))}",
                        extra={"platform": platform, "product": entry}
                    )
                    try:
                        from core.telegram import notify
                        notify(
                            f"🏭 Product Factory\n"
                            f"✅ {platform.upper()}: {product['title']}\n"
                            f"💰 ${product['price']} | {product['type']}\n"
                            f"📦 {published}/{target} today"
                        )
                    except Exception:
                        pass
                else:
                    _pf_log(
                        f"❌ [{platform}] Publish failed: {result.get('error', 'unknown')}",
                        "ERROR"
                    )

                # Rate limit — be respectful to APIs
                _time.sleep(3)

            _pf_log(f"🏁 [{platform}] Done: {published}/{target} published")

        # ── Session complete ───────────────────────────────────────────────
        total = sum(len(v) for v in state["products_today"].values())
        state.update({
            "running":       False,
            "current_phase": "idle",
            "current_task":  f"Session complete — {total} products published",
        })
        state.setdefault("sessions", []).insert(0, {
            "id":         session_id,
            "ts":         datetime.now().isoformat(),
            "total":      total,
            "platforms":  platforms,
            "products":   state["products_today"],
        })
        state["sessions"] = state["sessions"][:30]
        _pf_save_state(state)
        _pf_log(f"🎉 Session {session_id} complete — {total} total products published today")
        try:
            from core.telegram import notify
            notify(f"🏭 Product Factory complete!\n✅ {total} products published today\n"
                   f"Platforms: {', '.join(platforms)}")
        except Exception:
            pass

    except Exception as e:
        _pf_log(f"💥 Factory session crashed: {e}", "ERROR")
        state = _pf_load_state()
        state.update({"running": False, "current_phase": "error",
                       "current_task": f"Error: {e}"})
        _pf_save_state(state)
    finally:
        _pf_running = False


@app.get("/api/factory/status")
async def factory_status():
    """Return current Product Factory state + today's products."""
    state = _pf_load_state()
    products_today = state.get("products_today", {})

    # Flatten all products into a single list for the dashboard
    products_created = []
    for plat, items in products_today.items():
        for item in (items if isinstance(items, list) else []):
            products_created.append({**item, "platform": plat})

    # Per-platform published counts
    platform_counts = {p: len(products_today.get(p, [])) for p in _PF_PLATFORMS}

    # Sessions list
    sessions = state.get("sessions", [])

    return {
        **state,
        "platform_counts":    platform_counts,
        "products_created":   products_created,
        "target_per_platform": state.get("target_per_platform", 4),
        "sessions":           sessions,
        "platforms_available": {
            p: {
                "name":      cfg["name"],
                "icon":      cfg["icon"],
                "color":     cfg["color"],
                "target":    cfg["target"],
                "published": platform_counts[p],
                "connected": bool(
                    (p == "gumroad" and _gumroad_token()) or
                    (p == "payhip"  and True) or  # webhook mode always ok
                    (p == "etsy"    and _etsy_access_token()) or
                    (p == "kdp"     and os.getenv("KDP_EMAIL"))
                ),
            }
            for p, cfg in _PF_PLATFORMS.items()
        }
    }


@app.post("/api/factory/start")
async def factory_start(req: dict, background_tasks: BackgroundTasks):
    """
    Start the Product Factory pipeline.
    Body: {platforms: ['gumroad','payhip','etsy','kdp'], target_per_platform: 4, niches: []}
    """
    global _pf_running, _pf_thread
    if _pf_running:
        return {"error": "Factory is already running — stop it first"}

    platforms = req.get("platforms", list(_PF_PLATFORMS.keys()))
    target    = max(1, min(10, int(req.get("target_per_platform", 4))))
    niches    = req.get("niches") or None
    session_id = f"session_{int(time.time())}"

    _pf_running = True

    import threading as _pf_th
    t = _pf_th.Thread(
        target=_pf_run_session,
        args=(session_id, target, platforms, niches),
        daemon=True, name="product-factory"
    )
    t.start()
    _pf_thread = t

    _pf_log(f"▶ Factory started — session {session_id}")
    return {"status": "started", "session_id": session_id, "platforms": platforms, "target": target}


@app.post("/api/factory/stop")
async def factory_stop():
    """Gracefully stop the running factory session."""
    global _pf_running
    if not _pf_running:
        return {"status": "not_running"}
    _pf_running = False
    state = _pf_load_state()
    state.update({"running": False, "current_phase": "stopped",
                  "current_task": "Stopped by user"})
    _pf_save_state(state)
    _pf_log("⏹ Factory stopped by user")
    return {"status": "stopping"}


@app.get("/api/factory/log")
async def factory_log(limit: int = 100):
    """Return the factory log as formatted string lines, newest first."""
    raw = _pf_load_log()[:limit]
    lines = [
        f"[{entry.get('ts','')[:19]}] [{entry.get('level','INFO')}] {entry.get('msg','')}"
        for entry in raw
    ]
    return {"lines": lines, "count": len(lines)}


@app.get("/api/factory/alltime")
async def factory_alltime():
    """Return all-time aggregate product factory stats across all sessions."""
    state = _pf_load_state()
    sessions = state.get("sessions", [])
    total_products = sum(s.get("products_count", 0) for s in sessions)
    total_sessions = len(sessions)

    # Count by platform across all sessions
    by_platform: dict = {}
    for s in sessions:
        for p, n in (s.get("by_platform") or {}).items():
            by_platform[p] = by_platform.get(p, 0) + n

    # Revenue estimate (average $15 per digital product)
    avg_price = 15
    est_revenue = total_products * avg_price

    # Best platform
    best_platform = max(by_platform, key=lambda p: by_platform[p]) if by_platform else None

    # Today's count
    products_today = state.get("products_today", {})
    today_total = sum(len(v) for v in products_today.values() if isinstance(v, list))

    return {
        "total_products": total_products,
        "total_sessions": total_sessions,
        "today_total": today_total,
        "by_platform": by_platform,
        "est_revenue": est_revenue,
        "best_platform": best_platform,
        "last_session": sessions[0].get("started_at") if sessions else None,
    }


@app.delete("/api/factory/reset")
async def factory_reset():
    """Clear today's products and reset stats."""
    global _pf_running  # noqa: F824
    if _pf_running:
        return {"error": "Stop the factory first"}
    state = _pf_load_state()
    state.update({
        "products_today": {}, "current_phase": "idle", "current_task": "",
    })
    _pf_save_state(state)
    try:
        _PF_LOG_FILE.write_text("[]")
    except Exception:
        pass
    return {"status": "reset"}


# ══════════════════════════════════════════════════════════════════════════════
# NARAI AUTOPILOT API
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/narai-autopilot/status")
async def narai_autopilot_status():
    """Current status of NarAI's autonomous creation session."""
    from core.narai_autopilot import get_ap_status
    return get_ap_status()


@app.post("/api/narai-autopilot/start")
async def narai_autopilot_start():
    """
    Manually trigger NarAI's autopilot session.
    (Normally runs automatically at 01:30 daily.)
    """
    from core.narai_autopilot import start_autopilot_background, get_ap_status
    status = get_ap_status()
    if status.get("running"):
        return {"error": "Autopilot is already running"}
    session_id = start_autopilot_background()
    return {"status": "started", "session_id": session_id}


@app.post("/api/narai-autopilot/reels")
async def narai_autopilot_reels(slot: str = "all"):
    """
    Manually trigger the daily reels session.
    slot: 'morning' | 'afternoon' | 'evening' | 'all'
    """
    from core.narai_autopilot import start_reels_background
    sid = start_reels_background(slot)
    if sid == "already_running":
        return {"error": "Reels session already running"}
    return {"status": "started", "session_id": sid, "slot": slot}


@app.post("/api/narai-autopilot/stop")
async def narai_autopilot_stop():
    """Gracefully stop the running autopilot session."""
    from core.narai_autopilot import stop_autopilot, get_ap_status
    if not get_ap_status().get("running"):
        return {"status": "not_running"}
    stop_autopilot()
    return {"status": "stopping"}


@app.get("/api/narai-autopilot/log")
async def narai_autopilot_log(limit: int = 200):
    """Return autopilot activity log."""
    from core.narai_autopilot import get_ap_logs
    lines = get_ap_logs(limit)
    return {"lines": lines, "count": len(lines)}


@app.get("/api/narai-autopilot/queue")
async def narai_autopilot_queue():
    """Return the manual publish queue (content waiting to be posted)."""
    from core.narai_autopilot import get_publish_queue
    return {"queue": get_publish_queue(100)}


@app.post("/api/narai-autopilot/queue/{idx}/mark_done")
async def narai_autopilot_queue_mark_done(idx: int):
    """Mark a queue item as manually published."""
    try:
        from pathlib import Path as _P
        import json as _j
        qf = _P("data/autopilot_publish_queue.json")
        queue = _j.loads(qf.read_text()) if qf.exists() else []
        if 0 <= idx < len(queue):
            queue[idx]["status"] = "manually_published"
            queue[idx]["published_at"] = datetime.now().isoformat()
            qf.write_text(_j.dumps(queue, indent=2, default=str))
            return {"status": "updated"}
        return {"error": "Index out of range"}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO ENGINE API
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/video/engines")
async def video_engines():
    """Return which video engines are configured and available."""
    from core.video_engine import get_available_engines
    engines = get_available_engines()
    return {
        "engines": engines,
        "runway_key_set":  bool(os.getenv("RUNWAYML_API_KEY", "")),
        "pika_key_set":    bool(os.getenv("PIKA_API_KEY", "")),
        "heygen_key_set":  bool(os.getenv("HEYGEN_API_KEY", "")),
    }


@app.post("/api/video/generate")
async def video_generate(req: Request):
    """Manually trigger video generation."""
    body = await req.json()
    prompt  = body.get("prompt", "")
    style   = body.get("style", "anime")
    platform = body.get("platform", "tiktok")
    script  = body.get("script", "")
    if not prompt:
        return {"error": "prompt required"}
    from core.video_engine import generate_video
    result = generate_video(prompt=prompt, style=style, platform=platform, script=script)
    return result


@app.get("/api/video/list")
async def video_list():
    """List generated videos."""
    from pathlib import Path as _P
    video_dir = _P("outputs/videos")
    if not video_dir.exists():
        return {"videos": []}
    files = sorted(video_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"videos": [{"name": f.name, "size_mb": round(f.stat().st_size / 1_000_000, 2),
                        "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
                       for f in files[:50]]}


# ── NarAI Memory Manager API ─────────────────────────────────────────────────

@app.get("/api/narai/memory/stats")
async def narai_memory_stats():
    """Return NarAI memory usage across all tiers."""
    from core.narai_memory_manager import stats
    return stats()


@app.get("/api/narai/memory/search")
async def narai_memory_search(q: str, tiers: str = "", limit: int = 20):
    """Search NarAI's memory."""
    from core.narai_memory_manager import search
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    return {"results": search(q, tiers=tier_list, limit=limit)}


@app.get("/api/narai/memory/context")
async def narai_memory_context(platform: str = "general", task: str = "create content"):
    """Get NarAI's pre-creation context brief."""
    from core.narai_memory_manager import get_context
    return {"context": get_context(platform, task)}


@app.post("/api/narai/memory/save")
async def narai_memory_save(req: dict):
    """Save a memory entry. Body: {tier, key, content, tags, importance}"""
    from core.narai_memory_manager import save
    tier       = req.get("tier", "personal")
    key        = req.get("key", f"manual_{int(time.time())}")
    content    = req.get("content", "")
    tags       = req.get("tags", [])
    importance = req.get("importance", 7)
    if not content:
        return {"error": "content required"}
    entry = save(tier=tier, key=key, content=content, tags=tags, importance=importance)
    return {"saved": True, "key": entry["key"], "tier": tier}


@app.post("/api/narai/memory/consolidate")
async def narai_memory_consolidate():
    """Remove duplicate memories and consolidate."""
    from core.narai_memory_manager import consolidate
    return consolidate()


# ══════════════════════════════════════════════════════════════════════════════
# MARKET INTELLIGENCE API
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/market/status")
async def market_status():
    """Current status of the Market Intelligence engine."""
    from core.market_intelligence import get_status
    return get_status()


@app.post("/api/market/scan")
async def market_scan_start(req: dict = {}):
    """
    Start a market intelligence scan in the background.
    Body: {platforms: ["facebook","instagram",...]}  (empty = all platforms)
    Bot groups: "social", "marketplace", "amazon", "all"
    """
    from core.market_intelligence import start_scan_background, BOT_GROUPS, ALL_BOTS, get_status as _mi_get_status
    if _mi_get_status().get("running"):
        return {"error": "A scan is already running — stop it first"}

    platforms = req.get("platforms", [])
    group = req.get("group", "")
    if group and group in BOT_GROUPS:
        platforms = BOT_GROUPS[group]
    if not platforms:
        platforms = list(ALL_BOTS.keys())

    session_id = start_scan_background(platforms)
    return {"status": "started", "session_id": session_id, "platforms": platforms}


@app.post("/api/market/stop")
async def market_scan_stop():
    """Gracefully stop the running market scan."""
    from core.market_intelligence import stop_scan, get_status as _mi_get_status2
    if not _mi_get_status2().get("running"):
        return {"status": "not_running"}
    stop_scan()
    return {"status": "stopping"}


@app.get("/api/market/data")
async def market_data_all():
    """Return all collected market intelligence data."""
    from core.market_intelligence import _mi_load
    return _mi_load()


@app.get("/api/market/data/{platform}")
async def market_data_platform(platform: str):
    """Return market intelligence for a specific platform."""
    from core.market_intelligence import get_platform_data
    data = get_platform_data(platform)
    if not data:
        return {"error": f"No data for platform '{platform}' — run a scan first"}
    return data


@app.get("/api/market/briefing")
async def market_briefing():
    """Return NarAI's full strategic market briefing."""
    from core.market_intelligence import get_narai_briefing
    return {"briefing": get_narai_briefing()}


@app.get("/api/market/log")
async def market_log(limit: int = 200):
    """Return market intelligence activity log."""
    from core.market_intelligence import get_logs
    lines = get_logs(limit)
    return {"lines": lines, "count": len(lines)}


# ── Quality Control API ───────────────────────────────────────────────────────

@app.post("/api/qc/review")
async def qc_review(req: dict):
    """
    Submit content for quality control review.
    Body: {content, content_type, platform, title}
    """
    content      = req.get("content", "")
    content_type = req.get("content_type", "post")
    platform     = req.get("platform", "general")
    title        = req.get("title", "Untitled")
    if not content:
        return {"error": "content is required"}

    from core.market_intelligence import QualityControlBot
    bot = QualityControlBot()
    result = bot.review(content=content, content_type=content_type,
                        platform=platform, title=title)
    return result


@app.get("/api/qc/results")
async def qc_results(limit: int = 50):
    """Return recent QC results."""
    from core.market_intelligence import _qc_load
    return {"results": _qc_load()[:limit]}


@app.get("/api/qc/results/{qc_id}")
async def qc_result_detail(qc_id: str):
    """Return a specific QC result by ID."""
    from core.market_intelligence import _qc_load
    results = _qc_load()
    for r in results:
        if r.get("id") == qc_id:
            return r
    return {"error": "QC result not found"}


@app.get("/api/qc/stats")
async def qc_stats():
    """Return aggregate QC statistics for the dashboard."""
    from core.market_intelligence import _qc_load
    from datetime import datetime, timezone
    results = _qc_load()
    if not results:
        return {
            "total": 0, "approved": 0, "rejected": 0,
            "approval_rate": 0, "avg_score": 0,
            "today_count": 0, "last_reviewed_at": None,
            "by_platform": {}, "by_content_type": {},
            "score_distribution": {"90_100": 0, "75_89": 0, "50_74": 0, "0_49": 0},
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    approved = sum(1 for r in results if r.get("approved"))
    rejected = len(results) - approved
    scores = [r.get("score", 0) for r in results]
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    today_count = sum(1 for r in results if (r.get("reviewed_at") or "").startswith(today))

    by_platform: dict = {}
    by_type: dict = {}
    dist = {"90_100": 0, "75_89": 0, "50_74": 0, "0_49": 0}
    for r in results:
        p = r.get("platform", "unknown")
        by_platform[p] = by_platform.get(p, 0) + 1
        t = r.get("content_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        s = r.get("score", 0)
        if s >= 90:   dist["90_100"] += 1
        elif s >= 75: dist["75_89"] += 1
        elif s >= 50: dist["50_74"] += 1
        else:         dist["0_49"] += 1

    # Top platforms sorted
    by_platform = dict(sorted(by_platform.items(), key=lambda x: -x[1])[:8])

    return {
        "total": len(results),
        "approved": approved,
        "rejected": rejected,
        "approval_rate": round(approved / len(results) * 100) if results else 0,
        "avg_score": avg_score,
        "today_count": today_count,
        "last_reviewed_at": results[0].get("reviewed_at") if results else None,
        "by_platform": by_platform,
        "by_content_type": by_type,
        "score_distribution": dist,
    }


# ─── Launch helper ────────────────────────────────────────────────────────────

def launch(port: int = 5050, preload: bool = True):
    """Launch the FastAPI server with uvicorn.
    All heavy initialization runs in a background thread so uvicorn starts
    immediately and can respond to health checks while engines load.
    """
    import uvicorn
    import threading as _launch_th
    import time as _launch_time

    def _background_init():

        """Heavy engine startup — runs in background so uvicorn starts immediately."""
        _launch_time.sleep(8)  # give uvicorn time to start and pass Railway health check

        if not preload:
            return

        _add_log("WheellsVerse API background init starting...", "INFO")
        try:
            _get_orch()
            _get_pipeline()
            n = len(_get_orch().list_bots())
            _add_log(f"System ready — {n} bots loaded", "INFO")
        except Exception as e:
            _add_log(f"Orchestrator init failed: {e}", "WARNING")

        # Auto-register decision engine on scheduler (every 15 min)
        try:
            sched = _get_scheduler()
            de_interval = int(os.getenv("DECISION_ENGINE_INTERVAL", "15"))
            sched.register_decision_engine(interval_minutes=de_interval)
            _add_log(f"Decision engine scheduled every {de_interval}min", "INFO")
        except Exception as e:
            _add_log(f"Decision engine scheduler registration failed: {e}", "WARNING")

        # Start Budget Manager
        try:
            from core.budget_manager import BudgetManager
            BudgetManager.get().start()
            daily = os.getenv("DAILY_AD_BUDGET","10")
            _add_log(f"Budget Manager started — ${daily}/day ad budget", "INFO")
        except Exception as e:
            _add_log(f"Budget Manager failed to start: {e}", "WARNING")

        # Start Affiliate Optimizer
        try:
            from core.affiliate_optimizer import AffiliateOptimizer
            AffiliateOptimizer.get().start()
            _add_log("Affiliate Optimizer started — A/B testing all niches", "INFO")
        except Exception as e:
            _add_log(f"Affiliate Optimizer failed to start: {e}", "WARNING")

        # Start Feedback Loop engagement poller
        try:
            from core.feedback_loop import EngagementPoller
            ep = EngagementPoller()
            ep.start()
            _add_log("Feedback Loop engagement poller started", "INFO")
        except Exception as e:
            _add_log(f"Feedback Loop poller failed to start: {e}", "WARNING")

        # Start Viral Detector
        try:
            from core.viral_detector import ViralDetector
            ViralDetector.get().start()
            _add_log("Viral Detector started — monitoring every 10min", "INFO")
        except Exception as e:
            _add_log(f"Viral Detector failed to start: {e}", "WARNING")

        # Start DM Reply Engine
        try:
            from core.dm_reply import DMReplyEngine
            DMReplyEngine.get().start()
            _add_log("DM Reply Engine started — replying to all platforms", "INFO")
        except Exception as e:
            _add_log(f"DM Reply Engine failed to start: {e}", "WARNING")

        # Register Telegram webhook for instant two-way NarAI chat
        try:
            import requests as _tgreq
            _tg_token    = os.getenv("TELEGRAM_BOT_TOKEN", "")
            _tg_base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
            if _tg_token and _tg_base_url:
                _tgreq.post(f"https://api.telegram.org/bot{_tg_token}/deleteWebhook",
                            json={"drop_pending_updates": True}, timeout=10)
                webhook_url = f"{_tg_base_url}/api/telegram/webhook"
                r = _tgreq.post(
                    f"https://api.telegram.org/bot{_tg_token}/setWebhook",
                    json={"url": webhook_url, "allowed_updates": ["message", "channel_post", "edited_message"]},
                    timeout=10,
                )
                _add_log(f"Telegram webhook registered: {webhook_url} — {r.json().get('description','')}", "INFO")
        except Exception as e:
            _add_log(f"Telegram webhook registration failed: {e}", "WARNING")

        # Schedule daily Shorts pipeline
        try:
            import schedule as _sched2
            import threading as _th2
            from core.shorts_pipeline import get_shorts_pipeline

            shorts_time  = os.getenv("SHORTS_DAILY_TIME", "09:00")
            shorts_count = int(os.getenv("SHORTS_DAILY_COUNT", "2"))
            platforms    = os.getenv("SHORTS_DEFAULT_PLATFORMS",
                                     "youtube,tiktok,instagram,facebook").split(",")

            def _run_daily_shorts():
                _add_log(f"Daily Shorts pipeline starting ({shorts_count} videos)", "INFO")
                pipe = get_shorts_pipeline()
                for i in range(shorts_count):
                    try:
                        result = pipe.run(publish_to=platforms)
                        _add_log(
                            f"Short {i+1}/{shorts_count}: {result.get('status')} — "
                            f"{result.get('topic','')[:50]}", "INFO"
                        )
                    except Exception as e:
                        _add_log(f"Short {i+1} failed: {e}", "ERROR")

            _sched2.every().day.at(shorts_time).do(_run_daily_shorts)

            def _sched2_loop():
                while True:
                    _sched2.run_pending()
                    import time as _t; _t.sleep(30)

            _th2.Thread(target=_sched2_loop, daemon=True,
                        name="shorts-scheduler").start()
            _add_log(f"Shorts pipeline scheduled: {shorts_count} videos/day at {shorts_time}", "INFO")
        except Exception as e:
            _add_log(f"Shorts scheduler failed to start: {e}", "WARNING")

        # Schedule daily auto-publish
        try:
            import schedule as _sched
            import threading as _threading
            from scripts.daily_publish import run_daily_publish

            publish_time = os.getenv("DAILY_PUBLISH_TIME", "08:00")
            _sched.every().day.at(publish_time).do(
                lambda: (_add_log("Daily publish started", "INFO"),
                         run_daily_publish(),
                         _add_log("Daily publish complete", "INFO"))
            )

            def _sched_loop():
                while True:
                    _sched.run_pending()
                    import time as _t; _t.sleep(30)

            t = _threading.Thread(target=_sched_loop, daemon=True, name="daily-publisher")
            t.start()
            _add_log(f"Daily publish scheduled at {publish_time} every day", "INFO")
        except Exception as e:
            _add_log(f"Daily publish scheduler failed: {e}", "WARNING")

        # Schedule weekly newsletter (every Monday at 08:00)
        try:
            import schedule as _sched3
            import threading as _th3
            from core.email_funnel import send_weekly_newsletter

            def _weekly_newsletter():
                _add_log("Weekly newsletter starting", "INFO")
                r = send_weekly_newsletter()
                _add_log(f"Weekly newsletter: {r.get('status','?')} — {r.get('subject','')[:50]}", "INFO")

            _sched3.every().monday.at("08:00").do(_weekly_newsletter)

            def _sched3_loop():
                while True:
                    _sched3.run_pending()
                    import time as _t; _t.sleep(60)

            _th3.Thread(target=_sched3_loop, daemon=True,
                        name="newsletter-scheduler").start()
            _add_log("Weekly newsletter scheduled every Monday 08:00", "INFO")
        except Exception as e:
            _add_log(f"Newsletter scheduler failed: {e}", "WARNING")

        # ── Week 5 daily goal report scheduler ─────────────────────────────────
        try:
            import schedule as _sched5
            import threading as _th5
            from core.goal_tracker import GoalTracker

            def _daily_goal_report():
                GoalTracker.get().send_daily_report()
                _add_log("Daily goal report sent", "INFO")

            _sched5.every().day.at("07:00").do(_daily_goal_report)

            def _sched5_loop():
                while True:
                    _sched5.run_pending()
                    import time as _t; _t.sleep(60)

            _th5.Thread(target=_sched5_loop, daemon=True, name="goal-report-scheduler").start()
            _add_log("Daily goal report scheduled at 07:00", "INFO")
        except Exception as e:
            _add_log(f"Goal report scheduler failed: {e}", "WARNING")

        # ── Auto-start Week 5 engines ───────────────────────────────────────────
        try:
            from core.goal_tracker import GoalTracker  # noqa: F811
            GoalTracker.get().start()
            _add_log("GoalTracker started — daily goal reports at 07:00", "INFO")
        except Exception as e:
            _add_log(f"GoalTracker start failed: {e}", "WARNING")

        # ── Week 9: Money Command Center ────────────────────────────────────
        try:
            from pathlib import Path as _P9
            (_P9(__file__).parent.parent / "data").mkdir(exist_ok=True)
            _add_log("Week 9: Money Command Center ready — /api/money/summary + /api/stripe/webhook", "INFO")
        except Exception as e:
            _add_log(f"Week 9 init failed: {e}", "WARNING")

        # ── Week 8: Auto-start engines ──────────────────────────────────────
        try:
            from core.trending import TrendingEngine
            TrendingEngine.get().start()
            _add_log("TrendingEngine started — refreshing every 2 hours", "INFO")
        except Exception as e:
            _add_log(f"TrendingEngine start failed: {e}", "WARNING")

        try:
            from core.autopilot import AutopilotEngine
            AutopilotEngine.get().start()
            _add_log("AutopilotEngine loop started (enable via /api/autopilot/enable)", "INFO")
        except Exception as e:
            _add_log(f"AutopilotEngine start failed: {e}", "WARNING")

        # ── Week 7: Content Calendar auto-start ────────────────────────────────
        try:
            from core.content_calendar import ContentCalendar
            cal = ContentCalendar.get()
            cal.start()
            if not cal._calendar:
                import threading as _calth
                _calth.Thread(target=cal.generate_week, daemon=True).start()
            _add_log("ContentCalendar started", "INFO")
        except Exception as e:
            _add_log(f"ContentCalendar start failed: {e}", "WARNING")

        # ── Week 7: Revenue daily report at 08:00 ───────────────────────────────
        try:
            import schedule as _sched7
            import threading as _th7
            from core.revenue import RevenueEngine

            _sched7.every().day.at("08:00").do(RevenueEngine.get().send_daily_report)

            def _sched7_loop():
                while True:
                    _sched7.run_pending()
                    import time as _t; _t.sleep(60)

            _th7.Thread(target=_sched7_loop, daemon=True, name="revenue-reporter").start()
            _add_log("Revenue daily report scheduled at 08:00", "INFO")
        except Exception as e:
            _add_log(f"Revenue reporter failed: {e}", "WARNING")

        # ── Week 6: Performance dashboard refresh every 4 hours ─────────────────
        try:
            import schedule as _sched6
            import threading as _th6
            from core.performance import get_dashboard

            def _perf_refresh():
                get_dashboard()
                _add_log("Performance dashboard refreshed", "INFO")

            _sched6.every(4).hours.do(_perf_refresh)

            def _sched6_loop():
                while True:
                    _sched6.run_pending()
                    import time as _t; _t.sleep(60)

            _th6.Thread(target=_sched6_loop, daemon=True, name="perf-refresh").start()
            _add_log("Performance dashboard refresh scheduled every 4 hours", "INFO")
        except Exception as e:
            _add_log(f"Performance refresh scheduler failed: {e}", "WARNING")

        # ── NEXORA DB init ────────────────────────────────────────────────────────

        try:
            from core.nexora_db import init_db as _nx_init
            _nx_init()
            _add_log("NEXORA database initialised", "INFO")
        except Exception as e:
            _add_log(f"NEXORA DB init failed: {e}", "WARNING")

        _add_log("Background init complete — all engines running", "INFO")

    # Start background init thread BEFORE uvicorn (uvicorn.run blocks)
    _launch_th.Thread(target=_background_init, daemon=True, name="bg-init").start()

    uvicorn.run(
        "core.api:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        reload=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# SHOPIFY INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
# OAuth:    GET  /api/shopify/oauth-url?shop=mystore.myshopify.com
#           GET  /api/shopify/callback?code=...&shop=...&hmac=...
# Status:   GET  /api/shopify/status
# Products: GET  /api/shopify/products
#           POST /api/shopify/products
# Orders:   GET  /api/shopify/orders
# Webhooks: POST /api/shopify/webhook
# Publish:  POST /api/shopify/publish-narai-product
# ═════════════════════════════════════════════════════════════════════════════

_PUBLIC_PATHS.add("/api/shopify/oauth-url")
_PUBLIC_PATHS.add("/api/shopify/callback")
_PUBLIC_PATHS.add("/api/shopify/webhook")


@app.get("/api/shopify/oauth-url")
async def shopify_oauth_url(shop: str = Query(..., description="mystore.myshopify.com")):
    """
    Step 1 of OAuth. Returns the Shopify authorization URL.
    Redirect the user's browser to the returned URL.
    """
    from core.shopify_client import get_oauth_url
    url = get_oauth_url(shop)
    return {"oauth_url": url, "shop": shop}


@app.get("/api/shopify/callback")
async def shopify_oauth_callback(
    code:  str = Query(...),
    shop:  str = Query(...),
    hmac:  str = Query(""),
    state: str = Query(""),
):
    """
    Step 2 of OAuth. Shopify redirects here after the user approves.
    Exchanges the code for a permanent access token and registers webhooks.
    """
    from core.shopify_client import exchange_code_for_token, register_webhooks
    import os

    result = exchange_code_for_token(shop, code)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "OAuth failed"))

    # Register all webhooks automatically after connecting
    base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    webhooks = register_webhooks(base_url)
    registered = sum(1 for w in webhooks if w["registered"])

    logger.info(f"Shopify connected: {shop} — {registered}/{len(webhooks)} webhooks registered")

    return HTMLResponse(f"""
    <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0d0d1a;color:#fff">
    <h1 style="color:#00e5b0">✅ Shopify Connected!</h1>
    <p><strong>{shop}</strong> is now linked to WheellsVerse.</p>
    <p style="color:#888">{registered}/{len(webhooks)} webhooks registered</p>
    <p><a href="/" style="color:#00e5b0">← Back to Dashboard</a></p>
    </body></html>
    """)


@app.get("/api/shopify/status")
async def shopify_status():
    """Return Shopify connection + store summary."""
    from core.shopify_client import get_status
    return get_status()


@app.get("/api/shopify/products")
async def shopify_list_products(limit: int = Query(50), status: str = Query("active")):
    """List all products in the Shopify store."""
    from core.shopify_client import list_products
    products = list_products(limit=limit, status=status)
    return {"products": products, "count": len(products)}


@app.post("/api/shopify/products")
async def shopify_create_product(request: Request):
    """
    Manually create a Shopify product.
    Body: {title, description, price, tags[], product_type}
    """
    from core.shopify_client import create_product
    body = await request.json()
    result = create_product(
        title=body.get("title", ""),
        description=body.get("description", ""),
        price=float(body.get("price", 0)),
        product_type=body.get("product_type", "Digital"),
        tags=body.get("tags", []),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.put("/api/shopify/products/{product_id}")
async def shopify_update_product(product_id: int, request: Request):
    """Update an existing Shopify product. Body: {title, description, price, status, tags}"""
    from core.shopify_client import _api
    body = await request.json()
    update = {}
    if "title" in body:
        update["title"] = body["title"]
    if "description" in body:
        update["body_html"] = body["description"]
    if "price" in body:
        update["variants"] = [{"price": str(float(body["price"]))}]
    if "status" in body:
        update["status"] = body["status"]
    if "tags" in body:
        update["tags"] = body["tags"]
    resp = _api("PUT", f"products/{product_id}.json", {"product": update})
    product = resp.get("product", {})
    if not product.get("id"):
        raise HTTPException(status_code=400, detail=resp.get("errors", "Update failed"))
    return {"success": True, "product_id": product.get("id"), "title": product.get("title")}


@app.delete("/api/shopify/products/{product_id}")
async def shopify_delete_product(product_id: int):
    """Delete a Shopify product by ID."""
    from core.shopify_client import _api
    _api("DELETE", f"products/{product_id}.json")
    return {"success": True, "deleted_id": product_id}


@app.get("/api/shopify/customers")
async def shopify_list_customers(limit: int = Query(50)):
    """List Shopify customers."""
    from core.shopify_client import _api
    resp = _api("GET", f"customers.json?limit={limit}")
    customers = resp.get("customers", [])
    return {
        "customers": [
            {
                "id": c.get("id"),
                "email": c.get("email"),
                "first_name": c.get("first_name"),
                "last_name": c.get("last_name"),
                "orders_count": c.get("orders_count", 0),
                "total_spent": c.get("total_spent", "0.00"),
                "created_at": c.get("created_at"),
                "tags": c.get("tags", ""),
            }
            for c in customers
        ],
        "count": len(customers),
    }


@app.get("/api/shopify/webhooks/status")
async def shopify_webhooks_status():
    """List all registered webhooks."""
    from core.shopify_client import _api
    resp = _api("GET", "webhooks.json")
    webhooks = resp.get("webhooks", [])
    return {
        "webhooks": [
            {
                "id": w.get("id"),
                "topic": w.get("topic"),
                "address": w.get("address"),
                "created_at": w.get("created_at"),
            }
            for w in webhooks
        ],
        "count": len(webhooks),
    }


@app.get("/api/shopify/orders")
async def shopify_list_orders(limit: int = Query(50), status: str = Query("any")):
    """List orders and revenue summary."""
    from core.shopify_client import list_orders, get_orders_summary
    summary = get_orders_summary()
    orders  = list_orders(limit=limit, status=status)
    return {"summary": summary, "orders": orders}


@app.post("/api/shopify/webhook")
async def shopify_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive Shopify webhook events.
    Topics handled: orders/create, orders/paid, products/create, app/uninstalled.
    """
    from core.shopify_client import _add_log

    payload   = await request.body()
    hmac_hdr  = request.headers.get("X-Shopify-Hmac-Sha256", "")
    topic     = request.headers.get("X-Shopify-Topic", "")
    shop_hdr  = request.headers.get("X-Shopify-Shop-Domain", "")

    # Verify HMAC
    if hmac_hdr:
        from core.shopify_client import verify_webhook_hmac
        if not verify_webhook_hmac(payload, hmac_hdr):
            logger.warning(f"Shopify webhook HMAC mismatch — topic={topic}")
            raise HTTPException(status_code=401, detail="Invalid HMAC")

    try:
        data = json.loads(payload)
    except Exception:
        data = {}

    logger.info(f"Shopify webhook: {topic} from {shop_hdr}")
    _add_log(f"Webhook received: {topic} from {shop_hdr}")

    def _handle():
        try:
            if topic == "orders/paid":
                order_id   = data.get("id")
                total      = data.get("total_price")
                customer   = data.get("customer", {})
                email      = customer.get("email", "")
                first_name = customer.get("first_name", "")
                _add_log(f"💰 Order paid: #{order_id} ${total} — {email}")

                # ── ConvertKit: tag buyer (upgrade #19) ──────────────────────
                if email:
                    try:
                        from core.convertkit import add_subscriber
                        line_items = data.get("line_items", [])
                        product_names = [li.get("title","") for li in line_items]
                        tags = ["customer", "buyer"] + [f"bought:{n[:40]}" for n in product_names if n]
                        add_subscriber(email, first_name=first_name, tags=tags, fields={
                            "order_id": str(order_id),
                            "order_total": str(total),
                        })
                        _add_log(f"📧 ConvertKit: subscribed buyer {email}")
                    except Exception as ck_err:
                        _add_log(f"ConvertKit capture error: {ck_err}", "WARNING")

                # ── Auto-restock: trigger new product publish in background ──
                try:
                    from core.narai_shopify_engine import run_autopilot_session
                    run_autopilot_session(num_digital=1, num_pod=0, num_services=0, num_subscriptions=0)
                    _add_log("♻️ Auto-restock: queued 1 new product after sale")
                except Exception as rs_err:
                    _add_log(f"Auto-restock error: {rs_err}", "WARNING")

            elif topic == "orders/create":
                order_id = data.get("id")
                _add_log(f"🛒 New order created: #{order_id}")

            elif topic == "products/create":
                product_id = data.get("id")
                title      = data.get("title", "")
                _add_log(f"📦 Product created: '{title}' (ID {product_id})")

            elif topic == "app/uninstalled":
                # Clear token on uninstall
                from core.shopify_client import TOKEN_FILE
                if TOKEN_FILE.exists():
                    TOKEN_FILE.unlink()
                _add_log("⚠️ Shopify app uninstalled — token cleared", "WARNING")

        except Exception as e:
            _add_log(f"Webhook handler error ({topic}): {e}", "ERROR")

    background_tasks.add_task(_handle)
    return {"status": "ok"}


@app.post("/api/shopify/publish-narai-product")
async def shopify_publish_narai_product(request: Request):
    """
    Publish a NarAI product package to Shopify.
    Body: the full product package JSON from build_complete_product_package()
          or pass {"package_path": "/path/to/package.json"} to load from disk.
    """
    from core.shopify_client import publish_narai_product, is_connected

    if not is_connected():
        raise HTTPException(
            status_code=400,
            detail="Shopify not connected. Visit /api/shopify/oauth-url?shop=yourstore.myshopify.com to connect.",
        )

    body = await request.json()

    # Load from disk if package_path provided
    if "package_path" in body and not body.get("title"):
        pkg_path = Path(body["package_path"])
        if not pkg_path.exists():
            raise HTTPException(status_code=404, detail=f"Package not found: {pkg_path}")
        body = json.loads(pkg_path.read_text())

    result = publish_narai_product(body)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/shopify/discount")
async def shopify_create_discount(request: Request):
    """
    Create a discount code.
    Body: {title, code, percent_off?, amount_off?, usage_limit?, ends_at?}
    """
    from core.shopify_client import create_discount_code
    body = await request.json()
    result = create_discount_code(
        title=body.get("title", "Discount"),
        code=body.get("code", ""),
        percent_off=float(body.get("percent_off", 0)),
        amount_off=float(body.get("amount_off", 0)),
        usage_limit=int(body.get("usage_limit", 100)),
        ends_at=body.get("ends_at", ""),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/shopify/register-webhooks")
async def shopify_register_webhooks():
    """Re-register all Shopify webhooks (call after changing server URL)."""
    from core.shopify_client import register_webhooks, is_connected
    if not is_connected():
        raise HTTPException(status_code=400, detail="Shopify not connected")
    import os
    base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    results  = register_webhooks(base_url)
    return {"webhooks": results, "registered": sum(1 for w in results if w["registered"])}


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY AUTOPILOT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

_PUBLIC_PATHS.add("/api/shopify-autopilot/status")
_PUBLIC_PATHS.add("/api/shopify-autopilot/log")

# /api/sa/* — short aliases used by the dashboard
for _p in ["/api/sa/status", "/api/sa/store", "/api/sa/products", "/api/sa/funnel",
           "/api/sa/trend-scan", "/api/sa/performance", "/api/sa/log",
           "/api/sa/start", "/api/sa/stop", "/api/sa/setup-boutique"]:
    _PUBLIC_PATHS.add(_p)


@app.get("/api/shopify-autopilot/status")
async def shopify_autopilot_status():
    """Current Shopify autopilot state — phase, progress, stats."""
    from core.narai_shopify_autopilot import get_shopify_autopilot_status
    return get_shopify_autopilot_status()


@app.post("/api/shopify-autopilot/start")
async def shopify_autopilot_start(request: Request):
    """
    Start a Shopify autopilot session in the background.
    Optional body: {media_mode: bool, intelligence_mode: bool}
    """
    from core.narai_shopify_autopilot import start_shopify_autopilot_background
    try:
        body = await request.json()
    except Exception:
        body = {}
    media_mode       = bool(body.get("media_mode", False))
    intelligence_mode = bool(body.get("intelligence_mode", False))
    return start_shopify_autopilot_background(
        media_mode=media_mode,
        intelligence_mode=intelligence_mode,
    )


@app.post("/api/shopify-autopilot/stop")
async def shopify_autopilot_stop():
    """Signal the Shopify autopilot to stop after the current phase."""
    from core.narai_shopify_autopilot import stop_shopify_autopilot
    return stop_shopify_autopilot()


@app.get("/api/shopify-autopilot/log")
async def shopify_autopilot_log(limit: int = 100):
    """Recent Shopify autopilot log entries (newest first)."""
    from core.narai_shopify_autopilot import get_shopify_autopilot_logs
    return {"logs": get_shopify_autopilot_logs(limit=limit)}


@app.get("/api/shopify-autopilot/products")
async def shopify_autopilot_products():
    """Products created in the current/last Shopify autopilot session."""
    from core.narai_shopify_autopilot import _sa_load
    state = _sa_load()
    return {
        "products":    state.get("today_products", []),
        "total":       len(state.get("today_products", [])),
        "session_id":  state.get("session_id"),
    }


@app.get("/api/shopify-autopilot/funnel")
async def shopify_autopilot_funnel():
    """The active 5-step monetization funnel built by the autopilot."""
    from core.funnel_builder import get_active_funnel
    funnel = get_active_funnel()
    if not funnel:
        return {"funnel": None, "message": "No funnel built yet — run a session first"}
    return {"funnel": funnel}


@app.get("/api/shopify-autopilot/performance")
async def shopify_autopilot_performance():
    """Performance insights and learning from recent sessions."""
    from pathlib import Path
    import json
    learning_file = Path(__file__).parent.parent / "data" / "shopify_learning.json"
    if not learning_file.exists():
        return {"insights": [], "message": "No performance data yet"}
    try:
        insights = json.loads(learning_file.read_text())
        return {"insights": insights[:10]}
    except Exception:
        return {"insights": [], "error": "Failed to read learning file"}


@app.post("/api/shopify-autopilot/trend-scan")
async def shopify_autopilot_trend_scan():
    """Trigger an immediate viral trend scan and return opportunities."""
    from core.viral_trend_engine import run_trend_scan
    opportunities = run_trend_scan(refresh=True)
    return {
        "opportunities": opportunities,
        "count":         len(opportunities),
    }


# ── /api/sa/* short aliases (used by Shopify Autopilot dashboard tab) ─────────

@app.get("/api/sa/status")
async def sa_status():
    from core.narai_shopify_autopilot import get_shopify_autopilot_status
    return get_shopify_autopilot_status()

@app.get("/api/sa/store")
async def sa_store():
    from core.shopify_client import get_status, list_products
    from core.narai_shopify_autopilot import _sa_load
    status = get_status()
    state  = _sa_load()
    products = list_products(limit=50)
    return {
        "connected":           status.get("connected", False),
        "shop":                status.get("shop", ""),
        "total_products":      status.get("products_count", len(products)),
        "total_revenue_today": status.get("total_revenue", 0),
        "total_orders":        status.get("total_orders", 0),
        "products":            [
            {
                "id":           p.get("id"),
                "title":        p.get("title"),
                "price":        float(p["variants"][0]["price"]) if p.get("variants") else 0,
                "product_type": p.get("product_type", ""),
                "status":       p.get("status"),
                "image":        (p.get("image") or {}).get("src", ""),
            }
            for p in products
        ],
        "session_id":   state.get("session_id"),
        "session_phase": state.get("phase", "idle"),
    }

@app.post("/api/sa/start")
async def sa_start(request: Request):
    from core.narai_shopify_autopilot import start_shopify_autopilot_background
    try:
        body = await request.json()
    except Exception:
        body = {}
    return start_shopify_autopilot_background(
        media_mode=bool(body.get("media_mode", False)),
        intelligence_mode=bool(body.get("intelligence_mode", False)),
    )

@app.post("/api/sa/stop")
async def sa_stop():
    from core.narai_shopify_autopilot import stop_shopify_autopilot
    return stop_shopify_autopilot()

@app.get("/api/sa/products")
async def sa_products():
    from core.narai_shopify_autopilot import _sa_load
    state = _sa_load()
    return {"products": state.get("today_products", []), "total": len(state.get("today_products", []))}

@app.get("/api/sa/funnel")
async def sa_funnel():
    try:
        from core.funnel_builder import get_active_funnel
        funnel = get_active_funnel()
        return {"funnel": funnel} if funnel else {"funnel": None, "message": "No funnel yet"}
    except Exception:
        return {"funnel": None, "message": "Funnel builder not available"}

@app.get("/api/sa/trend-scan")
async def sa_trend_scan_get():
    from core.viral_trend_engine import run_trend_scan
    opps = run_trend_scan(refresh=False)
    return {"opportunities": opps, "count": len(opps)}

@app.post("/api/sa/trend-scan")
async def sa_trend_scan_post():
    from core.viral_trend_engine import run_trend_scan
    opps = run_trend_scan(refresh=True)
    return {"opportunities": opps, "count": len(opps)}

@app.get("/api/sa/performance")
async def sa_performance():
    from pathlib import Path as _Path
    lf = _Path(__file__).parent.parent / "data" / "shopify_learning.json"
    try:
        import json as _json
        insights = _json.loads(lf.read_text()) if lf.exists() else []
        return {"insights": insights[:10]}
    except Exception:
        return {"insights": []}

@app.get("/api/sa/log")
async def sa_log(limit: int = 80):
    from core.narai_shopify_autopilot import get_shopify_autopilot_logs
    return {"logs": get_shopify_autopilot_logs(limit=limit)}

@app.post("/api/sa/setup-boutique")
async def sa_setup_boutique():
    """Set up Shopify boutique collections and pages."""
    from core.narai_shopify_engine import create_boutique_collections, create_boutique_page
    try:
        cols  = create_boutique_collections()
        page  = create_boutique_page()
        return {"success": True, "collections": len(cols), "page": bool(page)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# NARAI POD ENGINE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

for _p in ["/api/pod/status", "/api/pod/start", "/api/pod/stop",
           "/api/pod/memory", "/api/pod/log"]:
    _PUBLIC_PATHS.add(_p)


@app.get("/api/pod/status")
async def pod_status():
    """Current NarAI POD session status."""
    from core.narai_pod_engine import get_pod_session_status
    return get_pod_session_status()


@app.post("/api/pod/start")
async def pod_start(request: Request, background_tasks: BackgroundTasks):
    """Start a NarAI POD creation session in the background."""
    from core.narai_pod_engine import get_pod_session_status, run_pod_session
    if get_pod_session_status().get("running"):
        return {"started": False, "reason": "Session already running"}
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    target = int(body.get("target", 10))
    product_types = body.get("product_types") or None
    background_tasks.add_task(run_pod_session, target=target, product_types=product_types)
    return {"started": True, "target": target}


@app.post("/api/pod/stop")
async def pod_stop():
    """Signal the POD session to stop after the current product."""
    from core.narai_pod_engine import _session_state
    _session_state["products_target"] = _session_state.get("products_created", 0)
    return {"stopping": True}


@app.get("/api/pod/memory")
async def pod_memory():
    """Return NarAI product memory stats."""
    from core.narai_pod_engine import get_pod_memory_stats
    return get_pod_memory_stats()


@app.get("/api/pod/log")
async def pod_log(limit: int = 50):
    """Return recent POD session log entries."""
    from core.narai_pod_engine import _session_state
    return {"log": _session_state.get("log", [])[-limit:]}


# ── Media Engine endpoints ────────────────────────────────────────────────────

@app.post("/api/shopify/media/generate/{product_id}")
async def shopify_generate_media(product_id: int, request: Request, background_tasks: BackgroundTasks):
    """
    Trigger media generation (cover images + 3D mockup + video) for an existing
    Shopify product and upload everything automatically.
    Body (optional): {title, tagline, _product_type_key, _niche}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    def _do_media():
        try:
            from core.media_engine import generate_and_upload
            result = generate_and_upload(product_id, body)
            logger.info(f"Media generated for product {product_id}: {result}")
        except Exception as e:
            logger.error(f"Media generation error for {product_id}: {e}")

    background_tasks.add_task(_do_media)
    return {
        "status": "generating",
        "product_id": product_id,
        "message": "Media generation started in background — check product in Shopify admin in 2–5 minutes",
    }


@app.post("/api/shopify/media/generate-batch")
async def shopify_generate_media_batch(request: Request, background_tasks: BackgroundTasks):
    """
    Generate media for multiple products at once.
    Body: {products: [{product_id, title, tagline, _product_type_key}, ...]}
    """
    body = await request.json()
    products = body.get("products", [])

    def _do_batch():
        from core.media_engine import generate_and_upload
        import time as _time
        for p in products:
            pid = p.get("product_id")
            if not pid:
                continue
            try:
                generate_and_upload(int(pid), p)
                logger.info(f"Batch media done for product {pid}")
            except Exception as e:
                logger.error(f"Batch media error for {pid}: {e}")
            _time.sleep(2)

    background_tasks.add_task(_do_batch)
    return {"status": "batch_generating", "product_count": len(products)}


# ── Store Intelligence endpoints ──────────────────────────────────────────────

@app.post("/api/shopify/intelligence/analyze")
async def shopify_intelligence_analyze():
    """
    Run a full store analysis: revenue per category, niche gaps, dead stock, top products.
    Caches result to data/store_intelligence.json.
    """
    from core.store_intelligence import analyze_store
    result = analyze_store()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/shopify/intelligence/opportunities")
async def shopify_intelligence_opportunities():
    """
    Return scored opportunities from the last cached analysis.
    Call /analyze first to refresh data.
    """
    from core.store_intelligence import get_cached_analysis, score_opportunities, analyze_store
    analysis = get_cached_analysis()
    if not analysis:
        analysis = analyze_store()
    opportunities = score_opportunities(analysis)
    return {
        "opportunities": opportunities,
        "count": len(opportunities),
        "analyzed_at": analysis.get("analyzed_at"),
        "store_summary": {
            "total_products": analysis.get("total_products"),
            "total_revenue":  analysis.get("total_revenue"),
            "total_orders":   analysis.get("total_orders"),
            "gaps_count":     len(analysis.get("category_gaps", [])),
        },
    }


@app.post("/api/shopify/intelligence/autopilot")
async def shopify_intelligence_autopilot(request: Request, background_tasks: BackgroundTasks):
    """
    Run the full intelligence autopilot:
    Analyze store → Score opportunities → Publish best products → (optional) Generate media.
    Body: {n_products: int, media_mode: bool}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    n_products = int(body.get("n_products", 5))
    media_mode = bool(body.get("media_mode", False))

    def _do_intel():
        from core.store_intelligence import run_intelligence_autopilot
        run_intelligence_autopilot(n_products=n_products, media_mode=media_mode)

    background_tasks.add_task(_do_intel)
    return {
        "status": "started",
        "n_products": n_products,
        "media_mode": media_mode,
        "message": "Intelligence autopilot running in background — check logs for progress",
    }


@app.get("/api/shopify/intelligence/status")
async def shopify_intelligence_status():
    """Return the last cached store intelligence analysis."""
    from core.store_intelligence import get_cached_analysis
    analysis = get_cached_analysis()
    if not analysis:
        return {"available": False, "message": "No analysis yet — run /api/shopify/intelligence/analyze first"}
    return {"available": True, **analysis}


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY AGENT WORKFORCE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/shopify/agents/start")
async def shopify_agents_start(request: Request, background_tasks: BackgroundTasks):
    """Start the full AI Agent Workforce (all 10 agents)."""
    from core.shopify_agent_workforce import start_workforce, start_upgrade_scheduler
    try:
        body = await request.json()
    except Exception:
        body = {}
    upgrade_interval = float(body.get("upgrade_interval_hours", 6.0))

    result = start_workforce()

    def _sched():
        start_upgrade_scheduler(interval_hours=upgrade_interval)
    if result.get("started"):
        background_tasks.add_task(_sched)

    return result


@app.post("/api/shopify/agents/stop")
async def shopify_agents_stop():
    """Stop the AI Agent Workforce."""
    from core.shopify_agent_workforce import stop_workforce
    return stop_workforce()


@app.get("/api/shopify/agents/status")
async def shopify_agents_status():
    """Get current status of all agents, queue size, and recent task log."""
    from core.shopify_agent_workforce import workforce_status
    return workforce_status()


@app.post("/api/shopify/agents/dispatch")
async def shopify_agents_dispatch(request: Request):
    """
    Manually dispatch a task to a specific agent.
    Body: {agent_type, action, payload?, priority?}
    Agents: ThemeAgent, BoutiqueAgent, SEOAgent, CopywriterAgent, PricingAgent,
            ProductResearchAgent, FunnelAgent, ReviewAgent, MonitorAgent, UpgradeAgent
    """
    body = await request.json()
    from core.shopify_agent_workforce import dispatch_task, PRIORITY_MEDIUM
    task_id = dispatch_task(
        agent_type=body.get("agent_type", "UpgradeAgent"),
        action=body.get("action", "run_upgrade_cycle"),
        payload=body.get("payload", {}),
        priority=int(body.get("priority", PRIORITY_MEDIUM)),
    )
    return {"task_id": task_id, "queued": True}


@app.post("/api/shopify/agents/upgrade-now")
async def shopify_agents_upgrade_now():
    """Trigger an immediate full upgrade cycle across all agents."""
    from core.shopify_agent_workforce import dispatch_task, PRIORITY_HIGH
    task_id = dispatch_task("UpgradeAgent", "run_upgrade_cycle", {}, PRIORITY_HIGH)
    return {"task_id": task_id, "message": "Full upgrade cycle queued for immediate execution"}


@app.get("/api/shopify/agents/logs")
async def shopify_agents_logs(limit: int = 50):
    """Get recent agent activity logs."""
    from core.shopify_agent_workforce import _load_json, AGENT_LOG_FILE, TASK_LOG_FILE
    return {
        "agent_logs": _load_json(AGENT_LOG_FILE, [])[:limit],
        "task_logs":  _load_json(TASK_LOG_FILE, [])[:min(limit, 20)],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NARAI SCHEDULE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

_PUBLIC_PATHS.add("/api/narai/schedules")


@app.get("/api/narai/schedules")
async def narai_get_schedules():
    """List all NarAI scheduled tasks with status, next run, last run."""
    from core.narai_scheduler import get_schedules, get_schedule_stats
    return {
        "schedules": get_schedules(),
        "stats":     get_schedule_stats(),
    }


@app.patch("/api/narai/schedules/{schedule_id}")
async def narai_update_schedule(schedule_id: str, request: Request):
    """
    Enable/disable a schedule or change its run time.
    Body: {enabled?: bool, time?: "HH:MM"}
    """
    from core.narai_scheduler import update_schedule
    body    = await request.json()
    enabled = body.get("enabled")
    t       = body.get("time")
    result  = update_schedule(schedule_id, enabled=enabled, time=t)
    if not result:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    return result


@app.post("/api/narai/schedules/{schedule_id}/trigger")
async def narai_trigger_schedule(schedule_id: str):
    """Manually trigger a schedule right now (runs in background)."""
    from core.narai_scheduler import trigger_schedule
    result = trigger_schedule(schedule_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.get("/api/narai/schedules/stats")
async def narai_schedule_stats():
    """Quick summary stats for the schedule dashboard."""
    from core.narai_scheduler import get_schedule_stats
    return get_schedule_stats()


# ══════════════════════════════════════════════════════════════════════════════
# NARAI CORE ENGINE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/narai/status")
async def narai_core_status():
    """Return NarAI system state: revenue, audience, assets, last goal, cycle count."""
    try:
        from core.narai_memory_manager import load_state
        from core.settings import settings
        state = load_state()
        return {
            "status":   "online",
            "state":    state,
            "settings": settings.summary(),
        }
    except Exception as e:
        logger.error(f"narai_core_status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/run")
async def narai_core_run(background_tasks: BackgroundTasks):
    """
    Run one full NarAI autonomous cycle in the background.
    Cycle: State → Goal → Plan → Execute → Evaluate → Learn
    """
    try:
        from core.narai_core import get_narai_core
        core = get_narai_core()

        def _run():
            try:
                result = core.run_cycle()
                logger.info(f"NarAI Core cycle complete: {result.get('metrics')}")
            except Exception as exc:
                logger.error(f"NarAI Core cycle error: {exc}")

        background_tasks.add_task(_run)
        return {"started": True, "message": "NarAI Core cycle started in background"}
    except Exception as e:
        logger.error(f"narai_core_run error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/narai/revenue")
async def narai_revenue_run(background_tasks: BackgroundTasks):
    """
    Run one full revenue loop in the background.
    Loop: Shopify session → POD top-up → Stripe snapshot → memory update
    """
    try:
        from core.revenue_loop import get_revenue_loop
        loop = get_revenue_loop()

        def _run():
            try:
                result = loop.run()
                logger.info(
                    f"Revenue loop complete: "
                    f"shopify={result['shopify'].get('status')} "
                    f"pod={result['pod'].get('status')} "
                    f"errors={result['errors_count']}"
                )
            except Exception as exc:
                logger.error(f"Revenue loop error: {exc}")

        background_tasks.add_task(_run)
        return {"started": True, "message": "Revenue loop started in background"}
    except Exception as e:
        logger.error(f"narai_revenue_run error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL SUBSCRIBE ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

class SubscribeRequest(BaseModel):
    email: str
    first_name: str = ""
    tags: list = []

_PUBLIC_PATHS.add("/api/subscribe")

@app.post("/api/subscribe")
async def email_subscribe(req: SubscribeRequest):
    """
    Add an email subscriber via ConvertKit.
    Called from the blog HTML email capture form.
    """
    import re as _re
    if not req.email or not _re.match(r"[^@]+@[^@]+\.[^@]+", req.email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    try:
        from core.convertkit import ConvertKitClient
        ck = ConvertKitClient()
        result = ck.subscribe(email=req.email, first_name=req.first_name, tags=req.tags)
        logger.info(f"New subscriber: {req.email}")
        return {"subscribed": True, "email": req.email, "result": result}
    except Exception as e:
        logger.warning(f"ConvertKit subscribe failed for {req.email}: {e}")
        # Don't expose internal errors — return success to user regardless
        return {"subscribed": True, "email": req.email}


# ── NarAI Marketing Autopilot ─────────────────────────────────────────────────
try:
    from narai.marketing.api import router as _marketing_router
    app.include_router(_marketing_router)
    logger.info("Marketing autopilot router loaded at /marketing")
except Exception as _e:
    logger.warning(f"Marketing autopilot not loaded: {_e}")


# ── Bug Hunter API ───────────────────────────────────────────────────��────────

@app.get("/api/bug-hunter/status")
async def bug_hunter_status():
    """Return the latest bug-hunter scan summary."""
    from pathlib import Path as _Path
    import json as _json
    report_dir = ROOT / "logs" / "bug_hunter"
    latest = report_dir / "latest.md"
    if not latest.exists():
        return {"status": "no_scan", "message": "Run a scan first: python -m bots.core.bug_hunter scan"}
    real = latest.resolve()
    # Return metadata from most recent JSON report
    json_report = real.with_suffix(".json")
    if json_report.exists():
        try:
            data = _json.loads(json_report.read_text())
            return {
                "status": "ok",
                "run_id": data.get("run_id"),
                "timestamp": data.get("timestamp"),
                "summary": data.get("summary", {}),
                "report_md": str(real.name),
            }
        except Exception as e:
            logger.warning(f"Bug hunter report parse failed: {e}")
    return {"status": "ok", "report": str(real)}


@app.post("/api/bug-hunter/scan")
async def bug_hunter_scan(background_tasks: BackgroundTasks):
    """Trigger a full bug-hunter scan in the background."""
    def _scan():
        try:
            from bots.core.bug_hunter.scheduler import _do_scan
            _do_scan()
        except Exception as e:
            logger.error(f"Bug hunter scan failed: {e}")

    background_tasks.add_task(_scan)
    return {"status": "started", "message": "Bug hunter scan started in background"}
