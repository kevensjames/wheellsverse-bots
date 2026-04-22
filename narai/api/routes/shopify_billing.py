"""
Stripe merchant-billing routes.

  POST /api/narai/shopify/billing/checkout
       Create a Stripe Checkout URL for a merchant to upgrade to a tier.

  POST /shopify/billing/webhook
       Stripe-signed webhook. Updates plan_tier on
       checkout.session.completed / subscription.deleted / payment_failed.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from narai.core.shopify_mt.billing import (
    create_checkout_session, handle_stripe_event, TIER_ORDER,
)

log = logging.getLogger("shopify_billing")

api_router = APIRouter(prefix="/shopify/billing", tags=["shopify-billing"])
webhook_router = APIRouter(prefix="/shopify/billing", tags=["shopify-billing-webhook"])

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_MERCHANT_WEBHOOK_SECRET", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")


class CheckoutRequest(BaseModel):
    merchant_id: str
    tier: str


@api_router.post("/checkout")
def start_checkout(req: CheckoutRequest):
    if req.tier not in TIER_ORDER or req.tier == "free":
        raise HTTPException(400, f"Tier must be one of: {[t for t in TIER_ORDER if t != 'free']}")
    try:
        result = create_checkout_session(req.merchant_id, req.tier)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("create_checkout_session failed")
        raise HTTPException(500, f"Checkout error: {e}")
    return result


@webhook_router.post("/webhook")
async def stripe_webhook(request: Request,
                         stripe_signature: str | None = Header(None)):
    """
    Stripe webhook endpoint. Signature verification is critical:
    without it, attackers can forge plan upgrades for free.
    """
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe not configured")
    if not stripe_signature:
        raise HTTPException(400, "Missing Stripe-Signature header")

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    raw = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=raw, sig_header=stripe_signature, secret=STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(401, "Invalid Stripe signature")
    except Exception as e:
        raise HTTPException(400, f"Webhook parse error: {e}")

    try:
        handle_stripe_event(event)
    except Exception as e:
        log.exception(f"handle_stripe_event failed for {event.get('type')}")
        # Still return 200 so Stripe doesn't retry — we've already logged.
    return {"received": True}
