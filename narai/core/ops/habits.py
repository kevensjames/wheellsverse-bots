"""Habit tracker — daily check-ins with streak counting."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Date, DateTime, Integer, String, Boolean, select
from sqlalchemy.orm import Mapped, mapped_column

from narai.core.db import Base, SessionLocal


class Habit(Base):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HabitLog(Base):
    __tablename__ = "habit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(Integer)
    day: Mapped[date] = mapped_column(Date)
    completed: Mapped[bool] = mapped_column(Boolean, default=True)


class HabitTracker:
    async def add_habit(self, name: str) -> dict[str, Any]:
        async with SessionLocal() as s:
            h = Habit(name=name)
            s.add(h)
            await s.commit()
            await s.refresh(h)
            return {"id": h.id, "name": h.name, "active": h.active}

    async def checkin(self, habit_id: int, day: Optional[date] = None) -> dict[str, Any]:
        day = day or date.today()
        async with SessionLocal() as s:
            # Upsert: delete existing entry for day, then add
            existing = (await s.execute(
                select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.day == day)
            )).scalar_one_or_none()
            if existing:
                return {"ok": True, "already": True}
            s.add(HabitLog(habit_id=habit_id, day=day, completed=True))
            await s.commit()
        return {"ok": True, "day": day.isoformat()}

    async def streak(self, habit_id: int) -> int:
        """Current consecutive-day streak ending today or yesterday."""
        today = date.today()
        async with SessionLocal() as s:
            rows = (await s.execute(
                select(HabitLog).where(HabitLog.habit_id == habit_id).order_by(HabitLog.day.desc())
            )).scalars().all()

        if not rows:
            return 0
        days_done = {r.day for r in rows}
        streak = 0
        # Allow streak to start at today OR yesterday (grace)
        d = today if today in days_done else today - timedelta(days=1)
        while d in days_done:
            streak += 1
            d -= timedelta(days=1)
        return streak

    async def status(self) -> list[dict[str, Any]]:
        async with SessionLocal() as s:
            habits = (await s.execute(select(Habit).where(Habit.active == True))).scalars().all()  # noqa: E712
        out = []
        today = date.today()
        for h in habits:
            streak = await self.streak(h.id)
            async with SessionLocal() as s:
                done_today = (await s.execute(
                    select(HabitLog).where(HabitLog.habit_id == h.id, HabitLog.day == today)
                )).scalar_one_or_none() is not None
            out.append({"id": h.id, "name": h.name, "streak": streak, "done_today": done_today})
        return out
