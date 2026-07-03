"""Sol v1 Stripe-rail contribution schemas (Connect Stage C)."""
from __future__ import annotations

from pydantic import BaseModel


class ChargeCheckoutOut(BaseModel):
    url: str


class ChargeStatusOut(BaseModel):
    exists: bool
    status: str | None = None
    destination_account_id: str | None = None
    stripe_payment_intent_id: str | None = None
