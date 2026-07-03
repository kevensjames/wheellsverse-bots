"""Sol v1 notification schemas — the member's in-app inbox.

Money-free: a notification is text + an in-app deep-link + a read flag. No bank
data, no amounts that move — `body` may *mention* an amount for a nudge, but
nothing here settles money.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    title: str
    body: str
    link: str | None = None
    payment_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int


class UnreadCountOut(BaseModel):
    count: int


class MarkedOut(BaseModel):
    updated: int
