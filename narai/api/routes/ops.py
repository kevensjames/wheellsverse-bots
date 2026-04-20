"""Personal ops API routes — tasks, habits, daily brief."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.ops import HabitTracker, TaskManager, generate_daily_brief

rt = APIRouter(tags=["ops"])
_tm = TaskManager()
_ht = HabitTracker()


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    priority: int = 3
    due: Optional[str] = None  # ISO 8601
    tags: list[str] = []


@rt.post("/ops/tasks")
async def ops_add_task(req: TaskCreateRequest, _=Depends(require_auth)) -> dict:
    due = datetime.fromisoformat(req.due) if req.due else None
    return {"ok": True, "task": await _tm.add(req.title, req.description, req.priority, due, req.tags)}


@rt.post("/ops/tasks/{task_id}/complete")
async def ops_complete_task(task_id: int, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "task": await _tm.complete(task_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@rt.delete("/ops/tasks/{task_id}")
async def ops_delete_task(task_id: int, _=Depends(require_auth)) -> dict:
    return {"ok": True, "deleted": await _tm.delete(task_id)}


@rt.get("/ops/tasks")
async def ops_list_tasks(include_done: bool = False, tag: Optional[str] = None,
                         limit: int = 100, _=Depends(require_auth)) -> dict:
    return {"ok": True, "tasks": await _tm.list(include_done=include_done, tag=tag, limit=limit)}


# ── Habits ────────────────────────────────────────────────────────────────────

class HabitCreateRequest(BaseModel):
    name: str


@rt.post("/ops/habits")
async def ops_add_habit(req: HabitCreateRequest, _=Depends(require_auth)) -> dict:
    return {"ok": True, "habit": await _ht.add_habit(req.name)}


@rt.post("/ops/habits/{habit_id}/checkin")
async def ops_habit_checkin(habit_id: int, _=Depends(require_auth)) -> dict:
    return {"ok": True, "result": await _ht.checkin(habit_id)}


@rt.get("/ops/habits")
async def ops_habits_status(_=Depends(require_auth)) -> dict:
    return {"ok": True, "habits": await _ht.status()}


# ── Daily brief ───────────────────────────────────────────────────────────────

@rt.get("/ops/brief")
async def ops_brief(include_market: bool = True, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, **(await generate_daily_brief(include_market=include_market))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
