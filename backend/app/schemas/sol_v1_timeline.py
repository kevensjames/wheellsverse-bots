"""Sol v1 timeline schemas — a member's chronological event stream.

Read-only projection: every field is derived from existing ledger rows. No money
is moved; `amount` is a recorded/estimated number for display.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class TimelineEvent(BaseModel):
    date: date
    kind: str          # contribution | payout | milestone
    status: str
    group_id: UUID
    circle_name: str
    amount: Decimal | None = None
    cycle_number: int | None = None
    payment_id: UUID | None = None   # set for contribution events → deep-link
    title: str
    detail: str


class TimelineOut(BaseModel):
    as_of: date
    events: list[TimelineEvent]
