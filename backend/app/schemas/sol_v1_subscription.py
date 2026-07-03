"""Sol v1 member-subscription schemas (Connect Stage B)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SubscriptionStatusOut(BaseModel):
    status: str
    active: bool
    current_period_end: datetime | None = None
    available: bool   # the price is configured (feature is usable)
    required: bool    # access is gated on an active subscription


class CheckoutOut(BaseModel):
    url: str


class PortalOut(BaseModel):
    url: str
