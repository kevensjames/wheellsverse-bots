#!/usr/bin/env python3
"""
narai/marketing/api.py — FastAPI APIRouter for NarAI Marketing Autopilot

Already wired into core/api.py:
    from narai.marketing.api import router as _marketing_router
    app.include_router(_marketing_router)
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from narai.marketing.marketing_autopilot import Orchestrator, StateStore

router = APIRouter(prefix="/marketing", tags=["marketing"])

_orch: Optional[Orchestrator] = None


def _get_orch() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator()
    return _orch


@router.get("/status", summary="List all marketing tasks and their status")
def marketing_status() -> List[Dict[str, Any]]:
    orch = _get_orch()
    tasks = orch._store.get_all_tasks()
    return [
        {
            "id": t["id"],
            "day": t["day"],
            "type": t["type"],
            "slug": t["slug"],
            "status": t["status"],
            "updated_at": t["updated_at"],
        }
        for t in tasks
    ]


@router.post("/run", summary="Run today's pending marketing tasks in background")
def marketing_run(background_tasks: BackgroundTasks) -> Dict[str, str]:
    orch = _get_orch()
    background_tasks.add_task(orch.run_day)
    day = orch.get_current_day()
    return {"status": "started", "day": str(day)}


@router.post("/approve/{task_id}", summary="Approve a marketing task by ID")
def marketing_approve(task_id: int) -> Dict[str, Any]:
    orch = _get_orch()
    task = orch._store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    orch._store.update_task_status(task_id, "approved")
    updated = orch._store.get_task(task_id)
    return updated  # type: ignore[return-value]


@router.get("/task/{task_id}", summary="Get full task details including output")
def marketing_task(task_id: int) -> Dict[str, Any]:
    orch = _get_orch()
    task = orch._store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("/reload-schedule", summary="Reload schedule.yaml into DB (idempotent)")
def marketing_reload_schedule() -> Dict[str, int]:
    orch = _get_orch()
    n = orch.load_schedule()
    return {"loaded": n}
