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

import yaml
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

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("api")

# ─── API Key Auth ─────────────────────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "").strip()

# Public paths that never require auth
_PUBLIC_PATHS = {"/", "/landing", "/api/health", "/api/overview", "/api/lead", "/favicon.ico",
                 "/api/auth/login", "/api/telegram/webhook", "/api/whatsapp/webhook",
                 "/api/stripe/webhook",
                 "/api/nexora/status", "/api/nexora/recruit", "/api/nexora/growth"}

async def verify_api_key(request: Request):
    """
    Optional API key guard.
    Set API_KEY in .env to enable. If not set, all requests pass through.
    Dashboard always passes (it's served from the same origin with the key embedded).
    """
    if not _API_KEY:
        return  # Auth disabled

    path = request.url.path
    if path in _PUBLIC_PATHS or not path.startswith("/api/"):
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
    # Startup
    from core.job_queue import get_queue
    await get_queue().start()
    _add_log("Async job queue started", "INFO")
    # Auto-start scheduler so bots run on their cron schedules
    try:
        sched = _get_scheduler()
        sched.start(blocking=False)
        _add_log("Scheduler auto-started on server boot", "INFO")
    except Exception as _e:
        _add_log(f"Scheduler auto-start failed: {_e}", "WARNING")
    # Auto-posting schedules DISABLED — NarAI only posts when owner explicitly asks
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
        # Also boot-time diagnostic in background
        import threading as _threading
        _threading.Thread(target=_narai_hourly, daemon=True).start()
        _add_log("NarAI: hourly diagnostic scheduled", "INFO")
    except Exception as _eN:
        _add_log(f"NarAI schedule setup failed: {_eN}", "WARNING")
    # ── NarAI Social Blast: daily 09:15 ──────────────────────────────────────
    try:
        import schedule as _schedNB
        import threading as _threadNB
        def _narai_blast():
            try:
                narai = _get_narai()
                if narai:
                    result = narai.execute(action="social_blast")
                    _add_log(f"NarAI social blast complete: {list(result.get('results',{}).keys())}", "INFO")
            except Exception as _eNB:
                _add_log(f"NarAI social blast failed: {_eNB}", "WARNING")
        _schedNB.every().day.at("09:15").do(lambda: _threadNB.Thread(target=_narai_blast, daemon=True).start())
        _add_log("NarAI social blast scheduled: daily 09:15", "INFO")
    except Exception as _e:
        _add_log(f"NarAI blast schedule failed: {_e}", "WARNING")

    # ── NarAI Inbox Handler: every 30 min (Facebook + Instagram comments) ────
    try:
        import schedule as _schedNI
        import threading as _threadNI
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
        _schedNI.every(30).minutes.do(lambda: _threadNI.Thread(target=_narai_inbox, daemon=True).start())
        _add_log("NarAI inbox handler scheduled: every 30min", "INFO")
    except Exception as _e:
        _add_log(f"NarAI inbox schedule failed: {_e}", "WARNING")

    # ── Video Creator: daily at 11:00 ────────────────────────────────────────
    try:
        import schedule as _schedV
        import threading as _threadV
        def _run_video_creator():
            try:
                orch = _get_orch()
                result = orch.run_bot("specialized/90_video_creator")
                _add_log(f"Video creator complete: {result.get('status', 'done')}", "INFO")
            except Exception as _eV:
                _add_log(f"Video creator failed: {_eV}", "ERROR")
        _schedV.every().day.at("11:00").do(lambda: _threadV.Thread(target=_run_video_creator, daemon=True).start())
        _add_log("Video creator scheduled: daily 11:00", "INFO")
    except Exception as _e:
        _add_log(f"Video creator schedule failed: {_e}", "WARNING")

    # ── Revenue Pipeline: full_revenue_blast daily at 08:30 ──────────────────
    try:
        import schedule as _schedR
        import threading as _threadR
        def _run_revenue_pipeline():
            try:
                pe = _get_pipeline_engine()
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
        _schedR.every().day.at("08:30").do(lambda: _threadR.Thread(target=_run_revenue_pipeline, daemon=True).start())
        _add_log("Revenue pipeline scheduled: daily 08:30", "INFO")
    except Exception as _e:
        _add_log(f"Revenue pipeline schedule failed: {_e}", "WARNING")

    # ── SEO Daily Pipeline: 06:30 every day ──────────────────────────────────
    try:
        import schedule as _schedS
        import threading as _threadS
        def _run_seo_pipeline():
            try:
                pe = _get_pipeline_engine()
                pe.run_pipeline("seo_daily")
                _add_log("SEO daily pipeline complete", "INFO")
            except Exception as _eS:
                _add_log(f"SEO pipeline failed: {_eS}", "ERROR")
        _schedS.every().day.at("06:30").do(lambda: _threadS.Thread(target=_run_seo_pipeline, daemon=True).start())
        _add_log("SEO daily pipeline scheduled: 06:30", "INFO")
    except Exception as _e:
        _add_log(f"SEO pipeline schedule failed: {_e}", "WARNING")

    # ── Social Domination Pipeline: 3× per day ───────────────────────────────
    try:
        import schedule as _schedSD
        import threading as _threadSD
        def _run_social_pipeline():
            try:
                pe = _get_pipeline_engine()
                pe.run_pipeline("social_domination")
                _add_log("Social domination pipeline complete", "INFO")
            except Exception as _eSD:
                _add_log(f"Social pipeline failed: {_eSD}", "ERROR")
        _schedSD.every().day.at("09:00").do(lambda: _threadSD.Thread(target=_run_social_pipeline, daemon=True).start())
        _schedSD.every().day.at("14:00").do(lambda: _threadSD.Thread(target=_run_social_pipeline, daemon=True).start())
        _schedSD.every().day.at("19:00").do(lambda: _threadSD.Thread(target=_run_social_pipeline, daemon=True).start())
        _add_log("Social domination pipeline scheduled: 09:00, 14:00, 19:00", "INFO")
    except Exception as _e:
        _add_log(f"Social pipeline schedule failed: {_e}", "WARNING")

    # ── Affiliate Revenue Pipeline: 3× per day ───────────────────────────────
    try:
        import schedule as _schedAR
        import threading as _threadAR
        def _run_affiliate_pipeline():
            try:
                pe = _get_pipeline_engine()
                pe.run_pipeline("affiliate_revenue")
                _add_log("Affiliate revenue pipeline complete", "INFO")
            except Exception as _eAR:
                _add_log(f"Affiliate pipeline failed: {_eAR}", "ERROR")
        _schedAR.every().day.at("10:00").do(lambda: _threadAR.Thread(target=_run_affiliate_pipeline, daemon=True).start())
        _schedAR.every().day.at("15:00").do(lambda: _threadAR.Thread(target=_run_affiliate_pipeline, daemon=True).start())
        _schedAR.every().day.at("20:00").do(lambda: _threadAR.Thread(target=_run_affiliate_pipeline, daemon=True).start())
        _add_log("Affiliate revenue pipeline scheduled: 10:00, 15:00, 20:00", "INFO")
    except Exception as _e:
        _add_log(f"Affiliate pipeline schedule failed: {_e}", "WARNING")

    # Telegram daily summary: 07:00 every day
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
        import threading as _threadWA
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
                        # Time to send
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
                            # Handle repeat
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
        _schedWA.every(1).minutes.do(lambda: _threadWA.Thread(target=_wa_scheduler_tick, daemon=True).start())
        _add_log("WhatsApp message scheduler started: checks every minute", "INFO")
    except Exception as _e:
        _add_log(f"WhatsApp scheduler setup failed: {_e}", "WARNING")

    yield
    # Shutdown
    from core.job_queue import get_queue
    await get_queue().stop()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

    # Clean old entries
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if t > window_start]

    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse({"error": "Rate limit exceeded. Try again later."}, status_code=429)

    _rate_limit_store[client_ip].append(now)
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Apply optional API key guard to all /api/ routes except public ones."""
    if _API_KEY:
        path = request.url.path
        if path.startswith("/api/") and path not in _PUBLIC_PATHS:
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


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
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
    return HTMLResponse(html)


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
    env_path = ROOT / ".env"
    settings: Dict[str, str] = {}
    if not env_path.exists():
        return settings

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Mask sensitive values
        if any(kw in key.upper() for kw in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            settings[key] = "***" + val[-4:] if len(val) > 4 else "***"
        else:
            settings[key] = val

    return settings


@app.post("/api/settings")
async def update_setting(update: SettingUpdate):
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
    browser_ok = False
    try:
        from core.browser import is_available
        browser_ok = is_available()
    except Exception:
        pass
    return {
        "status":   "ok",
        "uptime":   int(time.time() - _server_start),
        "browser":  browser_ok,
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
    entry = mem.save(
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
    piece_index: int = 0            # index into last run's pieces
    platforms:   List[str] = ["static"]


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
        path = engine.generate_lead_magnet_pdf(topic)
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
        report = get_intelligence().generate_improvement_report()
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
    from datetime import datetime, timedelta
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
        report = get_analytics().generate_daily_report()
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

class LinkedInPostRequest(BaseModel):
    content: str

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
            result = post_linkedin(req.content)
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
async def revenue_dashboard(days: int = 30):
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
    return get_convertkit().get_status()


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


# ─── Publish Pipeline ─────────────────────────────────────────────────────────

def _get_publisher():
    from core.publish_pipeline import get_publisher
    return get_publisher()


@app.get("/api/pipeline/status")
async def pipeline_status():
    """Which social/email platforms are connected and ready."""
    return _get_publisher().get_status()


class PublishRequest(BaseModel):
    content: str
    title: str = ""
    platforms: Optional[List[str]] = None   # None = all
    video_url: Optional[str] = None
    hashtags: Optional[List[str]] = None
    slug: str = ""


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
    blog_dir    = ROOT / "outputs" / "published" / "blog"

    # Gather recent markdown files not yet in blog
    existing_slugs = {f.stem[9:] for f in blog_dir.glob("*.html")} if blog_dir.exists() else set()

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
    from core.click_tracker import _load_clicks
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


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (payment success → drip enroll)."""
    from core.stripe_client import get_stripe
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        result = get_stripe().handle_webhook(payload, sig_header)
        return result
    except ValueError as e:
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


class RepurposeRequest(BaseModel):
    content: str
    title:   str = ""
    formats: Optional[List[str]] = None   # None = all 6 formats


@app.post("/api/reddit/post-repurposed")
async def reddit_post_repurposed(req: RepurposeRequest, background_tasks: BackgroundTasks):
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
async def repurpose_content(req: RepurposeRequest, background_tasks: BackgroundTasks):
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
    from core.impact import get_earnings, get_clicks
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
            req = AdsDeployRequest(slug=item["slug"])
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
    """Return quick stats for the KDP dashboard."""
    import datetime as _dt
    total = 0
    for g in KDP_GENRES_LIST:
        gdir = KDP_BOOKS_ROOT / g
        if gdir.exists():
            total += len(list(gdir.glob("book_*.md")))

    # Deduplicate latest result per genre from today's files
    import glob as _glob, time as _t
    cutoff = _t.time() - 86400
    genre_status: Dict[str, str] = {}
    for f in sorted(_glob.glob(str(KDP_BOOKS_ROOT / "kdp_result_*.json")), reverse=True):
        try:
            if Path(f).stat().st_mtime < cutoff:
                continue
            d = json.loads(Path(f).read_text(errors="replace"))
            g = d.get("genre", "")
            if g and g not in genre_status:
                genre_status[g] = d.get("status", "error")
        except Exception:
            continue
    published_today = sum(1 for s in genre_status.values() if s in ("published", "review_required"))
    errors_today    = sum(1 for s in genre_status.values() if s == "error")
    # Enrich genre_status with error details for account_limit cases
    for f in sorted(_glob.glob(str(KDP_BOOKS_ROOT / "kdp_result_*.json")), reverse=True):
        try:
            d = json.loads(Path(f).read_text(errors="replace"))
            g = d.get("genre", "")
            err = d.get("error", "")
            if g and genre_status.get(g) == "error" and "account_limit" in err:
                genre_status[g] = "account_limit"
        except Exception:
            continue
    account_limit = sum(1 for s in genre_status.values() if s == "account_limit")
    kdp_results = _kdp_load_results()

    # Check if a publish run is currently active (log has STEP but not COMPLETE)
    running = False
    if KDP_LOG_PATH.exists():
        tail = KDP_LOG_PATH.read_text(errors="replace")[-3000:]
        running = ("STEP 1" in tail or "STEP 2" in tail or "STEP 3" in tail) and "DAILY PUBLISH COMPLETE" not in tail

    live_asins = sum(1 for d in kdp_results.values() if d.get("asin"))

    return {
        "published_today":   published_today,
        "errors_today":      errors_today,
        "account_limit":     account_limit,
        "total_books":       total,
        "status":            "running" if running else ("done" if published_today > 0 else "idle"),
        "live_asins":        live_asins,
        "genre_status":      genre_status,
        "limit_note":        "Amazon limits new title submissions per account. Wait for pending books to be approved, then re-run." if account_limit > 0 else "",
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


# ─── NarAI — General Overseer AI ─────────────────────────────────────────────

_narai = None

def _get_narai():
    global _narai
    if _narai is None:
        try:
            from bots.narai.bot import get_narai
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

class SubscribeRequest(BaseModel):
    email: str
    first_name: str = ""
    tags: List[str] = []
    niche: str = "general"

@app.post("/api/email/subscribe")
async def email_subscribe(req: SubscribeRequest):
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
        result = create_sequence_in_convertkit(name, emails)
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

class LinkedInPostRequest(BaseModel):
    topic: str = ""
    text: str = ""
    niche: str = "general"
    image_url: str = ""
    generate: bool = True

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
    results = list((RESULTS_DIR := ROOT / "outputs" / "shorts_results").glob("*.json"))
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
    from pathlib import Path as _P
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
    import hmac, hashlib
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
            result = bot.run(action="recruit")
            _add_log("NEXORA recruitment posts generated", "INFO")
        except ImportError:
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT / "bots" / "revenue" / "09_nexora_beta"))
                import importlib as _il
                spec = _il.util.spec_from_file_location("bot", ROOT/"bots"/"revenue"/"09_nexora_beta"/"bot.py")
                mod  = _il.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                result = mod.NexoraBetaBot().run(action="recruit")
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
    """Serve NEXORA frontend pages directly from the dashboard server."""
    from fastapi.responses import FileResponse
    path = ROOT / "frontend" / "nexora" / filename
    if not path.exists() or not path.suffix == ".html":
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(str(path), media_type="text/html")


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
        result = LeadCaptureEngine.get().capture(
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


# ─── Launch helper ────────────────────────────────────────────────────────────

def launch(port: int = 5050, preload: bool = True):
    """Launch the FastAPI server with uvicorn."""
    import uvicorn

    if preload:
        _add_log("WheellsVerse API starting...", "INFO")
        _get_orch()
        _get_pipeline()
        n = len(_get_orch().list_bots())
        _add_log(f"System ready — {n} bots loaded", "INFO")

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
            import requests as _tgreq, threading as _tgth
            def _register_tg_webhook():
                import time as _tgt; _tgt.sleep(5)  # wait for server to be up
                _tg_token    = os.getenv("TELEGRAM_BOT_TOKEN", "")
                _tg_base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
                if not (_tg_token and _tg_base_url):
                    return
                # Delete any old webhook / polling conflict
                _tgreq.post(f"https://api.telegram.org/bot{_tg_token}/deleteWebhook",
                            json={"drop_pending_updates": True}, timeout=10)
                webhook_url = f"{_tg_base_url}/api/telegram/webhook"
                r = _tgreq.post(
                    f"https://api.telegram.org/bot{_tg_token}/setWebhook",
                    json={"url": webhook_url, "allowed_updates": ["message", "channel_post", "edited_message"]},
                    timeout=10,
                )
                _add_log(f"Telegram webhook registered: {webhook_url} — {r.json().get('description','')}", "INFO")
            _tgth.Thread(target=_register_tg_webhook, daemon=True, name="TelegramWebhookReg").start()
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
        from core.goal_tracker import GoalTracker
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
        # Auto-generate this week if calendar is empty
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

    uvicorn.run(
        "core.api:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        reload=False,
    )
