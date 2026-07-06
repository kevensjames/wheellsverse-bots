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


# ── SOL profile / badges (Stage 26) ─────────────────────────────────────────────


class BadgeOut(BaseModel):
    key: str
    label: str
    description: str
    earned: bool


class MemberStatsOut(BaseModel):
    circles_joined: int
    circles_completed: int
    circles_organized: int
    on_time: int
    actionable: int
    sol_score: int | None = None  # the 0-100 reliability score, surfaced as SOL Score
    reputation_label: str


class MemberProfileOut(BaseModel):
    stats: MemberStatsOut
    badges: list[BadgeOut]
