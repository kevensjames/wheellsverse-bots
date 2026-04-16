#!/usr/bin/env python3
"""
core/bot_router.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router for bot process management.
Prefix: /api/botctl
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.bot_manager import (
    bot_status,
    discover_bots,
    get_log,
    list_bots,
    restart_bot,
    start_bot,
    stop_bot,
)

logger = logging.getLogger("bot_router")
router = APIRouter(prefix="/api/botctl", tags=["botctl"])


# ─── Request models ───────────────────────────────────────────────────────────

class BotStartRequest(BaseModel):
    bot_name: str
    category: Optional[str] = ""


class BotNameRequest(BaseModel):
    bot_name: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/list")
def botctl_list():
    """
    Return all bots: both managed (running/crashed) and discovered (idle).
    Merges discover_bots() with list_bots() so the panel shows everything.
    """
    discovered = discover_bots()
    managed = {b["name"]: b for b in list_bots()}

    # Overwrite idle entries with live managed data
    result = []
    seen: set = set()
    for bot in discovered:
        name = bot["name"]
        seen.add(name)
        if name in managed:
            result.append(managed[name])
        else:
            result.append(bot)

    # Add managed bots not found in discovered (e.g. generated bots started from chat)
    for name, data in managed.items():
        if name not in seen:
            result.append(data)

    return {"bots": result, "total": len(result)}


@router.post("/start")
def botctl_start(req: BotStartRequest):
    """Start a bot subprocess."""
    try:
        entry = start_bot(req.bot_name, req.category or "")
        return {"ok": True, "bot": entry}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error starting bot {req.bot_name}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
def botctl_stop(req: BotNameRequest):
    """Stop a running bot subprocess."""
    try:
        entry = stop_bot(req.bot_name)
        return {"ok": True, "bot": entry}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error stopping bot {req.bot_name}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart")
def botctl_restart(req: BotStartRequest):
    """Restart a bot subprocess."""
    try:
        entry = restart_bot(req.bot_name, req.category or "")
        return {"ok": True, "bot": entry}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error restarting bot {req.bot_name}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{bot_name}")
def botctl_status(bot_name: str):
    """Get live status for a managed bot."""
    try:
        return {"ok": True, "bot": bot_status(bot_name)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/log/{bot_name}")
def botctl_log(bot_name: str, lines: int = Query(default=100, ge=1, le=2000)):
    """Get the last N lines of a bot's log file."""
    return {"bot": bot_name, "lines": lines, "log": get_log(bot_name, lines)}
