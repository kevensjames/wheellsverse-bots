"""Pipeline tracker — persisted deal stages in SQLite via SQLAlchemy async.

Stages: lead → contacted → qualified → demo → proposal → closed_won | closed_lost
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import String, Float, DateTime, Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from narai.core.db import Base, SessionLocal


class DealStage(str, Enum):
    LEAD = "lead"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    DEMO = "demo"
    PROPOSAL = "proposal"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


_STAGE_ORDER = [s.value for s in DealStage]


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_email: Mapped[str] = mapped_column(String(320))
    company: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(32), default=DealStage.LEAD.value)
    source: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Pipeline API ──────────────────────────────────────────────────────────────

class Pipeline:
    """Convenience wrapper around Deal table."""

    async def create(self, contact_email: str, company: str = "", amount: float = 0.0,
                     source: str = "", notes: str = "") -> dict[str, Any]:
        async with SessionLocal() as s:
            deal = Deal(contact_email=contact_email, company=company,
                        amount=amount, source=source, notes=notes)
            s.add(deal)
            await s.commit()
            await s.refresh(deal)
            return self._to_dict(deal)

    async def update_stage(self, deal_id: int, new_stage: DealStage | str,
                           note: str = "") -> dict[str, Any]:
        stage = new_stage.value if isinstance(new_stage, DealStage) else new_stage
        if stage not in _STAGE_ORDER:
            raise ValueError(f"Unknown stage '{stage}'")
        async with SessionLocal() as s:
            deal = await s.get(Deal, deal_id)
            if deal is None:
                raise ValueError(f"Deal {deal_id} not found")
            deal.stage = stage
            deal.updated_at = datetime.now(timezone.utc)
            if note:
                deal.notes = (deal.notes + f"\n[{deal.updated_at.isoformat()}] {note}").strip()
            await s.commit()
            await s.refresh(deal)
            return self._to_dict(deal)

    async def update_amount(self, deal_id: int, amount: float) -> dict[str, Any]:
        async with SessionLocal() as s:
            deal = await s.get(Deal, deal_id)
            if deal is None:
                raise ValueError(f"Deal {deal_id} not found")
            deal.amount = amount
            deal.updated_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(deal)
            return self._to_dict(deal)

    async def list_by_stage(self, stage: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        async with SessionLocal() as s:
            q = select(Deal).order_by(Deal.updated_at.desc()).limit(limit)
            if stage:
                q = q.where(Deal.stage == stage)
            rows = (await s.execute(q)).scalars().all()
            return [self._to_dict(d) for d in rows]

    async def summary(self) -> dict[str, Any]:
        """Aggregate pipeline stats: counts and $ by stage."""
        async with SessionLocal() as s:
            rows = (await s.execute(select(Deal))).scalars().all()
        by_stage: dict[str, dict[str, Any]] = {st: {"count": 0, "amount": 0.0} for st in _STAGE_ORDER}
        total_amount = 0.0
        for d in rows:
            by_stage.setdefault(d.stage, {"count": 0, "amount": 0.0})
            by_stage[d.stage]["count"] += 1
            by_stage[d.stage]["amount"] += d.amount
            total_amount += d.amount

        open_stages = ["contacted", "qualified", "demo", "proposal"]
        open_amount = sum(by_stage[s]["amount"] for s in open_stages if s in by_stage)
        closed_won = by_stage.get("closed_won", {"count": 0, "amount": 0.0})

        return {
            "total_deals": len(rows),
            "total_amount": round(total_amount, 2),
            "open_amount": round(open_amount, 2),
            "won_amount": round(closed_won["amount"], 2),
            "by_stage": by_stage,
        }

    @staticmethod
    def _to_dict(d: Deal) -> dict[str, Any]:
        return {
            "id": d.id,
            "contact_email": d.contact_email,
            "company": d.company,
            "amount": d.amount,
            "stage": d.stage,
            "source": d.source,
            "notes": d.notes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
