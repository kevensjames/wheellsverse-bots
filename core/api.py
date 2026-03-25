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

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("api")

# ─── API Key Auth ─────────────────────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "").strip()

# Public paths that never require auth
_PUBLIC_PATHS = {"/", "/landing", "/api/health", "/api/overview", "/api/lead", "/favicon.ico"}

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

app = FastAPI(
    title="WheellsVerse Bot Ecosystem",
    version="2.0.0",
    description="70 Autonomous AI Bots — Production Control API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    background_tasks: BackgroundTasks,
):
    orch = _get_orch()
    full_name = f"{category}/{bot_name}"
    if full_name not in orch.bots:
        raise HTTPException(404, f"Bot '{full_name}' not found")

    def _run():
        _add_log(f"Running bot: {full_name}", "INFO")
        try:
            orch.run_bot(full_name, **req.kwargs)
            _add_log(f"Bot completed: {full_name}", "INFO")
        except Exception as e:
            _add_log(f"Bot failed: {full_name} — {e}", "ERROR")

    background_tasks.add_task(_run)
    return {"status": "started", "bot": full_name}


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
        _add_log(f"Lead captured: {req.email[:30]} from {req.source}", "INFO")
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

    uvicorn.run(
        "core.api:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        reload=False,
    )
