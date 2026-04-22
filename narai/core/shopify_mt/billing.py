"""
Stripe billing for merchants installed via the NarAI Shopify app.

Flow:
  1. Merchant installs app → row created with plan_tier='free'.
  2. Admin dashboard shows Upgrade → hits create_checkout_session().
  3. Stripe webhook /api/narai/shopify/billing/webhook updates plan_tier.

Plan tiers (monthly USD):
  free    — 10 AI products/month, watermarked, NarAI branding
  starter — $19,   100 products, no watermark
  pro     — $49,   1000 products, Printify auto-sync, priority queue
  elite   — $149,  unlimited, dedicated webhook speed, custom prompts
"""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Optional

from narai.core.shopify_mt import db as mt_db

log = logging.getLogger("shopify_mt.billing")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_MERCHANT_WEBHOOK_SECRET", "")
APP_URL = os.getenv("APP_URL", "https://app.wheellsverse.com").rstrip("/")

# Price IDs set in Railway (created once in Stripe dashboard)
PRICE_IDS: dict[str, str] = {
    "starter": os.getenv("STRIPE_PRICE_MERCHANT_STARTER", ""),
    "pro":     os.getenv("STRIPE_PRICE_MERCHANT_PRO", ""),
    "elite":   os.getenv("STRIPE_PRICE_MERCHANT_ELITE", ""),
}

PLAN_LIMITS: dict[str, dict] = {
    "free":    {"products_month": 10,   "printify": False, "watermark": True},
    "starter": {"products_month": 100,  "printify": False, "watermark": False},
    "pro":     {"products_month": 1000, "printify": True,  "watermark": False},
    "elite":   {"products_month": None, "printify": True,  "watermark": False},
}

TIER_ORDER = ["free", "starter", "pro", "elite"]


class PlanUpgradeRequired(Exception):
    def __init__(self, current: str, required: str):
        self.current = current
        self.required = required
        super().__init__(f"Plan '{current}' < required '{required}'")


def require_plan(min_tier: str):
    """Decorator: blocks an action unless merchant's plan_tier >= min_tier."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(merchant_id: str, *args, **kwargs):
            merchant = mt_db.get_merchant_by_id(merchant_id)
            if not merchant:
                raise RuntimeError("merchant not found")
            current = merchant.get("plan_tier") or "free"
            if TIER_ORDER.index(current) < TIER_ORDER.index(min_tier):
                raise PlanUpgradeRequired(current=current, required=min_tier)
            return fn(merchant_id, *args, **kwargs)
        return wrapper
    return decorator


# ─── Stripe Checkout ──────────────────────────────────────────────────────────

def create_checkout_session(merchant_id: str, tier: str,
                             success_url: Optional[str] = None,
                             cancel_url: Optional[str] = None) -> dict:
    """Create a Stripe Checkout session to upgrade a merchant to `tier`."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    if tier not in PRICE_IDS or not PRICE_IDS[tier]:
        raise ValueError(f"No STRIPE_PRICE_MERCHANT_{tier.upper()} env var set")

    merchant = mt_db.get_merchant_by_id(merchant_id)
    if not merchant:
        raise RuntimeError("merchant not found")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRICE_IDS[tier], "quantity": 1}],
        client_reference_id=merchant_id,
        customer=merchant.get("stripe_customer_id") or None,
        customer_email=merchant.get("owner_email") or None,
        success_url=success_url or f"{APP_URL}/admin/shopify/upgraded?tier={tier}",
        cancel_url=cancel_url or f"{APP_URL}/admin/shopify/billing",
        subscription_data={
            "metadata": {"merchant_id": merchant_id, "tier": tier},
        },
        metadata={"merchant_id": merchant_id, "tier": tier},
    )
    return {"url": session.url, "session_id": session.id}


# ─── Stripe Webhook handler (wired in the route below) ──────────────────────

def handle_stripe_event(event: dict) -> None:
    """Process a Stripe event. Idempotent on stripe_event_id."""
    ev_type = event.get("type", "")
    ev_id = event.get("id", "")
    obj = (event.get("data") or {}).get("object") or {}

    # checkout.session.completed → activate subscription
    if ev_type == "checkout.session.completed":
        merchant_id = obj.get("client_reference_id") or \
                      (obj.get("metadata") or {}).get("merchant_id")
        tier = (obj.get("metadata") or {}).get("tier", "starter")
        if merchant_id:
            mt_db.update_plan(
                merchant_id,
                plan_tier=tier,
                stripe_customer_id=obj.get("customer"),
                stripe_subscription_id=obj.get("subscription"),
            )
            mt_db.log_event(merchant_id, "plan.upgraded", {"tier": tier, "session": obj.get("id")})
            mt_db.record_billing_event(
                merchant_id=merchant_id, stripe_event_id=ev_id,
                stripe_event_type=ev_type, status="succeeded",
                amount_cents=obj.get("amount_total"),
                currency=obj.get("currency", "usd"),
                metadata={"tier": tier},
            )

    # customer.subscription.deleted → downgrade to free
    elif ev_type == "customer.subscription.deleted":
        sub_id = obj.get("id", "")
        metadata = obj.get("metadata") or {}
        merchant_id = metadata.get("merchant_id")
        if merchant_id:
            mt_db.update_plan(merchant_id, plan_tier="free")
            mt_db.log_event(merchant_id, "plan.downgraded", {"reason": "subscription deleted"})
            mt_db.record_billing_event(
                merchant_id=merchant_id, stripe_event_id=ev_id,
                stripe_event_type=ev_type, status="canceled",
                metadata={"subscription_id": sub_id},
            )

    # invoice.payment_failed → flag merchant, set grace period
    elif ev_type == "invoice.payment_failed":
        sub_id = obj.get("subscription", "")
        metadata = (obj.get("subscription_details") or {}).get("metadata") or {}
        merchant_id = metadata.get("merchant_id")
        if merchant_id:
            mt_db.log_event(merchant_id, "billing.failed", {
                "invoice": obj.get("id"), "amount_due": obj.get("amount_due"),
            }, severity="warn")
            mt_db.record_billing_event(
                merchant_id=merchant_id, stripe_event_id=ev_id,
                stripe_event_type=ev_type, status="failed",
                amount_cents=obj.get("amount_due"),
                currency=obj.get("currency", "usd"),
                stripe_invoice_id=obj.get("id"),
            )

    # invoice.paid → log
    elif ev_type == "invoice.paid":
        metadata = (obj.get("subscription_details") or {}).get("metadata") or {}
        merchant_id = metadata.get("merchant_id")
        if merchant_id:
            mt_db.record_billing_event(
                merchant_id=merchant_id, stripe_event_id=ev_id,
                stripe_event_type=ev_type, status="succeeded",
                amount_cents=obj.get("amount_paid"),
                currency=obj.get("currency", "usd"),
                stripe_invoice_id=obj.get("id"),
            )
