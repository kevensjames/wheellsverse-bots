"""Sol v1 Stripe Connect schemas (Connect Stage A)."""
from __future__ import annotations

from pydantic import BaseModel


class ConnectStatusOut(BaseModel):
    connected: bool
    onboarding_complete: bool
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    # test | live | blocked_live | unconfigured
    mode: str


class OnboardingLinkOut(BaseModel):
    url: str
