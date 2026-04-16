#!/usr/bin/env python3
"""
core/stripe_engine.py
─────────────────────────────────────────────────────────────────────────────
Stripe subscription management.

Plans: free, starter ($9/mo), pro ($29/mo), enterprise ($99/mo)

Uses subscriptions table (created by chat_db.init_db).
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from typing import Dict

logger = logging.getLogger("stripe_engine")

PLANS = {
    "free": {
        "name": "Free",
        "price": 0,
        "limits": {"api_calls": 100, "bots": 3, "kb_docs": 10, "chat_msgs": 50},
    },
    "starter": {
        "name": "Starter",
        "price": 9,
        "price_id": os.getenv("STRIPE_STARTER_PRICE_ID", ""),
        "limits": {"api_calls": 1000, "bots": 10, "kb_docs": 100, "chat_msgs": 500},
    },
    "pro": {
        "name": "Pro",
        "price": 29,
        "price_id": os.getenv("STRIPE_PRO_PRICE_ID", ""),
        "limits": {"api_calls": 10000, "bots": 50, "kb_docs": 1000, "chat_msgs": 5000},
    },
    "enterprise": {
        "name": "Enterprise",
        "price": 99,
        "price_id": os.getenv("STRIPE_ENTERPRISE_PRICE_ID", ""),
        "limits": {"api_calls": -1, "bots": -1, "kb_docs": -1, "chat_msgs": -1},  # -1 = unlimited
    },
}


def _get_stripe():
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def create_checkout_session(
    plan: str,
    user_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session. Returns checkout URL."""
    stripe = _get_stripe()
    plan_data = PLANS.get(plan)
    if not plan_data:
        raise ValueError(f"Unknown plan: {plan}")
    price_id = plan_data.get("price_id", "")
    if not price_id:
        raise ValueError(f"No Stripe price ID configured for plan: {plan}")

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer_email=user_email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"plan": plan, "user_email": user_email},
    )
    return session.url


def create_portal_session(user_email: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session."""
    stripe = _get_stripe()
    from core.chat_db import _get_conn, _lock
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT stripe_customer_id FROM subscriptions WHERE user_email=?",
            (user_email,)
        ).fetchone()
    if not row or not row[0]:
        raise ValueError("No Stripe customer found for this email")
    session = stripe.billing_portal.Session.create(
        customer=row[0],
        return_url=return_url,
    )
    return session.url


def handle_webhook(payload: bytes, sig_header: str) -> Dict:
    """
    Process a Stripe webhook event.
    Returns {"processed": True, "event": event_type} or raises.
    """
    stripe = _get_stripe()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError as e:
        raise ValueError(f"Invalid webhook signature: {e}")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _activate_subscription(
            user_email=data.get("customer_email", ""),
            plan=data.get("metadata", {}).get("plan", "starter"),
            customer_id=data.get("customer", ""),
            sub_id=data.get("subscription", ""),
        )
    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        _deactivate_subscription(sub_id=data.get("id", ""))

    return {"processed": True, "event": event_type}


def _activate_subscription(user_email: str, plan: str, customer_id: str, sub_id: str):
    from core.chat_db import _get_conn, _lock
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO subscriptions(user_email,plan,stripe_customer_id,stripe_sub_id,status) "
            "VALUES(?,?,?,?,'active')",
            (user_email, plan, customer_id, sub_id)
        )
        conn.commit()
    logger.info(f"[stripe] Activated {plan} for {user_email}")


def _deactivate_subscription(sub_id: str):
    from core.chat_db import _get_conn, _lock
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE subscriptions SET status='inactive' WHERE stripe_sub_id=?", (sub_id,)
        )
        conn.commit()
    logger.info(f"[stripe] Deactivated subscription {sub_id}")


def get_plan(user_email: str) -> Dict:
    """Get current subscription plan for a user."""
    if not user_email:
        return {**PLANS["free"], "plan_id": "free", "status": "free"}
    from core.chat_db import _get_conn, _lock
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT plan,status FROM subscriptions WHERE user_email=?",
            (user_email,)
        ).fetchone()
    if not row or row[1] != "active":
        return {**PLANS["free"], "plan_id": "free", "status": "free"}
    plan_id = row[0]
    plan_data = PLANS.get(plan_id, PLANS["free"])
    return {**plan_data, "plan_id": plan_id, "status": "active"}


def is_active(user_email: str) -> bool:
    plan = get_plan(user_email)
    return plan.get("status") == "active" or plan.get("plan_id") == "free"


def get_usage_limits(user_email: str) -> Dict:
    plan = get_plan(user_email)
    return plan.get("limits", PLANS["free"]["limits"])
