"""Sol v1 admin (operator) schemas — read-only dashboard responses.

Money-free: `recorded_confirmed_volume` and `amount` are RECORDED numbers (what
members paid each other directly), never a balance Sol holds.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.sol_v1 import CycleOut, GroupOut, MembershipOut
from app.schemas.sol_v1_ledger import PaymentOut
from app.schemas.sol_v1_reputation import ReputationOut


class GroupCounts(BaseModel):
    open: int
    locked: int
    complete: int
    total: int


class PaymentCounts(BaseModel):
    pending: int
    marked: int
    confirmed: int
    disputed: int
    late: int
    total: int


class CycleCounts(BaseModel):
    pending: int
    active: int
    complete: int
    total: int


class Attention(BaseModel):
    overdue: int
    # past-due but payer-marked & unconfirmed (stale — needs payee confirm/dispute)
    unconfirmed: int
    disputed: int


class OverviewOut(BaseModel):
    groups: GroupCounts
    members_total: int
    payments: PaymentCounts
    cycles: CycleCounts
    recorded_confirmed_volume: Decimal
    attention: Attention


class RiskItem(BaseModel):
    payment_id: UUID
    group_id: UUID
    group_name: str
    payer_id: UUID
    payee_id: UUID
    amount: Decimal
    status: str
    due_date: date
    kind: str  # 'disputed' | 'overdue'
    disputed_at: datetime | None = None


class RiskOut(BaseModel):
    items: list[RiskItem]


class DisputeItem(BaseModel):
    payment_id: UUID
    group_id: UUID
    group_name: str
    payer_id: UUID
    payee_id: UUID
    amount: Decimal
    payer_marked_at: datetime | None = None
    disputed_at: datetime | None = None
    proof_count: int


class DisputesOut(BaseModel):
    items: list[DisputeItem]


class GroupSummary(BaseModel):
    id: UUID
    name: str
    status: str
    organizer_id: UUID
    contribution_amount: Decimal
    frequency: str
    member_count: int
    member_limit: int
    cycles_complete: int
    cycles_total: int
    created_at: datetime


class GroupsOut(BaseModel):
    items: list[GroupSummary]


class GroupDetailOut(BaseModel):
    group: GroupOut
    members: list[MembershipOut]
    cycles: list[CycleOut]
    payments: list[PaymentOut]
    reputations: list[ReputationOut]


class ActivityItem(BaseModel):
    at: datetime
    event: str  # 'created' | 'marked' | 'confirmed' | 'disputed'
    payment_id: UUID
    group_name: str
    amount: Decimal
    payer_id: UUID
    payee_id: UUID


class ActivityOut(BaseModel):
    items: list[ActivityItem]
