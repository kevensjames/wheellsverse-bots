"""Task manager — SQLite-backed todo list with priority, due date, and tags."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from narai.core.db import Base, SessionLocal


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=3)   # 1=high, 5=low
    due: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TaskManager:
    async def add(self, title: str, description: str = "", priority: int = 3,
                  due: Optional[datetime] = None, tags: Optional[list[str]] = None) -> dict[str, Any]:
        async with SessionLocal() as s:
            t = Task(title=title, description=description, priority=priority,
                     due=due, tags=tags or [])
            s.add(t)
            await s.commit()
            await s.refresh(t)
            return self._to_dict(t)

    async def complete(self, task_id: int) -> dict[str, Any]:
        async with SessionLocal() as s:
            t = await s.get(Task, task_id)
            if not t:
                raise ValueError(f"Task {task_id} not found")
            t.done = True
            t.done_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(t)
            return self._to_dict(t)

    async def list(self, include_done: bool = False, tag: Optional[str] = None,
                   limit: int = 100) -> list[dict[str, Any]]:
        async with SessionLocal() as s:
            q = select(Task).order_by(Task.priority, Task.due).limit(limit)
            if not include_done:
                q = q.where(Task.done == False)  # noqa: E712
            rows = (await s.execute(q)).scalars().all()
        results = [self._to_dict(t) for t in rows]
        if tag:
            results = [r for r in results if tag in (r.get("tags") or [])]
        return results

    async def delete(self, task_id: int) -> bool:
        async with SessionLocal() as s:
            t = await s.get(Task, task_id)
            if not t:
                return False
            await s.delete(t)
            await s.commit()
            return True

    @staticmethod
    def _to_dict(t: Task) -> dict[str, Any]:
        return {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "priority": t.priority,
            "due": t.due.isoformat() if t.due else None,
            "tags": t.tags or [],
            "done": t.done,
            "done_at": t.done_at.isoformat() if t.done_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
