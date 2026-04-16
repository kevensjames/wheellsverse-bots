#!/usr/bin/env python3
"""
core/stripe_router.py
─────────────────────────────────────────────────────────────────────────────
Stripe billing API.

POST /api/stripe/checkout  — create checkout session (auth required)
POST /api/stripe/webhook   — Stripe webhook (PUBLIC — no API key)
GET  /api/stripe/status    — current subscription status (auth required)
GET  /api/stripe/portal    — Stripe customer portal URL (auth required)
GET  /api/stripe/plans     — list available plans (public)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.stripe_engine import (
    PLANS, create_checkout_session, create_portal_session,
    get_plan, handle_webhook,
)

logger = logging.getLogger("stripe_router")
router = APIRouter(prefix="/api/stripe", tags=["stripe"])


class CheckoutRequest(BaseModel):
    plan: str
    user_email: str
    success_url: str = ""
    cancel_url: str = ""


class PortalRequest(BaseModel):
    user_email: str
    return_url: str = ""


@router.get("/plans")
def stripe_plans():
    """List all available subscription plans."""
    return {
        "plans": [
            {"id": k, "name": v["name"], "price": v["price"],
             "limits": v.get("limits", {})}
            for k, v in PLANS.items()
        ]
    }


@router.post("/checkout")
def stripe_checkout(req: CheckoutRequest):
    """Create a Stripe Checkout session."""
    import os
    base = os.getenv("DASHBOARD_URL", "http://localhost:5050")
    success = req.success_url or f"{base}/dashboard?billing=success"
    cancel = req.cancel_url or f"{base}/dashboard?billing=cancel"
    try:
        url = create_checkout_session(req.plan, req.user_email, success, cancel)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook — no API key auth needed.
    Stripe sends its own signature header.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = handle_webhook(payload, sig)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[stripe webhook] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def stripe_status(user_email: Optional[str] = None):
    """Get current subscription status."""
    plan = get_plan(user_email or "")
    return {"plan": plan}


@router.post("/portal")
def stripe_portal(req: PortalRequest):
    """Create a Stripe Customer Portal session."""
    import os
    base = os.getenv("DASHBOARD_URL", "http://localhost:5050")
    return_url = req.return_url or f"{base}/dashboard"
    try:
        url = create_portal_session(req.user_email, return_url)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
