#!/usr/bin/env python3
"""
core/agent_router.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router for the NarAI autonomous agent.

POST /api/agent/run           → start agent, returns {run_id}
GET  /api/agent/stream/{id}  → SSE stream of step events
POST /api/agent/cancel/{id}  → cancel running agent
GET  /api/agent/runs          → list active + recent runs
GET  /api/agent/history/{id} → full step history for a run
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.agent import (
    cancel_agent,
    get_history,
    list_agents,
    start_agent,
)

logger = logging.getLogger("agent_router")
router = APIRouter(prefix="/api/agent", tags=["agent"])


class RunRequest(BaseModel):
    task: str
    conversation_id: Optional[str] = None


class CancelRequest(BaseModel):
    run_id: str


@router.post("/run")
async def agent_run(req: RunRequest):
    """Start an autonomous agent task. Returns run_id immediately."""
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="Task cannot be empty")
    run_id = start_agent(req.task.strip(), req.conversation_id)
    return {"run_id": run_id, "status": "started"}


@router.get("/stream/{run_id}")
async def agent_stream(run_id: str):
    """
    SSE stream of agent step events.
    Polls history until a done/error/cancelled event appears.
    """
    async def event_gen():
        sent = 0
        max_polls = 600   # 10 min timeout at 1s interval
        for _ in range(max_polls):
            history = get_history(run_id)
            while sent < len(history):
                step = history[sent]
                yield f"data: {json.dumps(step)}\n\n"
                sent += 1
                # Yield done events and stop streaming
                if step.get("type") in ("done", "error", "cancelled"):
                    return
            await asyncio.sleep(0.5)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Stream timeout'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/cancel/{run_id}")
async def agent_cancel(run_id: str):
    """Cancel a running agent."""
    ok = cancel_agent(run_id)
    return {"cancelled": ok, "run_id": run_id}


@router.get("/runs")
async def agent_runs():
    """List all active and recently completed agent runs."""
    return {"runs": list_agents()}


@router.get("/history/{run_id}")
async def agent_history(run_id: str):
    """Return full step history for a run."""
    history = get_history(run_id)
    if not history:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "steps": history}
