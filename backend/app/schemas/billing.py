"""Pydantic request/response shapes for /billing/*."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


PlanCode = Literal["pro", "elite"]


class CheckoutRequest(BaseModel):
    plan_code: PlanCode = Field(..., description="Which paid plan to subscribe to")


class CheckoutResponse(BaseModel):
    checkout_url: str
    plan_code: PlanCode


class PortalResponse(BaseModel):
    portal_url: str


class SubscriptionResponse(BaseModel):
    """What the frontend renders in the 'Current Plan' card."""
    plan_code: str
    plan_name: str
    status: str  # active, past_due, canceled, free
    predictions_per_day: int
    current_period_end: Optional[datetime] = None
    cancel_url: Optional[str] = None  # portal link when user has a real sub


class WebhookAck(BaseModel):
    received: bool = True
    event_type: Optional[str] = None
