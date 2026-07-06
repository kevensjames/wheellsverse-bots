"""Sol v1 request/response schemas.

Kept deliberately small and money-free: amounts are plain recorded numbers,
never balances the app owes anyone. No bank/routing/card fields appear here.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── requests ─────────────────────────────────────────────────────────────────


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contribution_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    frequency: Literal["weekly", "biweekly", "monthly"]
    member_limit: int = Field(ge=2, le=100)
    # Stage 24 — days past a due date before the organizer is escalated (0 = now).
    grace_period_days: int = Field(default=0, ge=0, le=90)


class JoinRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=32)


class LockRequest(BaseModel):
    order_mode: Literal["random", "organizer_assigned"] = "random"
    # organizer_assigned only: {membership_id: position} — a permutation of 1..N.
    positions: dict[UUID, int] | None = None
    # optional anchor for the first cycle; defaults to lock date server-side.
    start_date: date | None = None


# ── responses ────────────────────────────────────────────────────────────────


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organizer_id: UUID
    name: str
    contribution_amount: Decimal
    frequency: str
    member_limit: int
    grace_period_days: int = 0
    status: str
    invite_code: str
    locked_at: datetime | None = None
    created_at: datetime


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    group_id: UUID
    payout_position: int | None = None
    role: str
    created_at: datetime


class CycleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cycle_number: int
    recipient_membership_id: UUID | None = None
    due_date: date
    status: str


class GroupDetail(BaseModel):
    group: GroupOut
    members: list[MembershipOut]
    cycles: list[CycleOut]


# ── late policy (Stage 24) ─────────────────────────────────────────────────────


class DelinquentMemberOut(BaseModel):
    user_id: UUID
    overdue_count: int
    total_owed: Decimal
    oldest_due_date: date
    max_days_overdue: int


class DelinquencyOut(BaseModel):
    group_id: UUID
    grace_period_days: int
    as_of: date
    delinquents: list[DelinquentMemberOut]
