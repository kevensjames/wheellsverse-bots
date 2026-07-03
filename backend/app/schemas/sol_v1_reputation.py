"""Sol v1 reputation schemas."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ReputationBreakdown(BaseModel):
    on_time: int
    late_paid: int
    overdue: int
    disputed: int
    in_flight: int


class ReputationOut(BaseModel):
    user_id: UUID
    # None = 'unrated' (no actionable history yet)
    score: int | None
    label: str
    actionable: int
    provisional: bool
    breakdown: ReputationBreakdown
