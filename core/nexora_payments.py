#!/usr/bin/env python3
"""core/nexora_payments.py — Stripe Checkout session creation + webhook record handling."""
import os
from typing import Dict


def _stripe():
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def _checkout(name: str, amount_cents: int, success_url: str, cancel_url: str, metadata: Dict) -> Dict:
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {"currency": "usd", "product_data": {"name": name}, "unit_amount": amount_cents},
            "quantity": 1,
        }],
        success_url=success_url or "",
        cancel_url=cancel_url or "",
        metadata=metadata,
    )
    return {"checkout_url": session.url}


def create_subscription_checkout(actor: Dict, body: Dict) -> Dict:
    price = float(body.get("subscription_price") or 0)
    if price <= 0:
        raise ValueError("invalid subscription price")
    return _checkout(
        f"Subscription to {body.get('creator_name', 'creator')}",
        int(round(price * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "subscription", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "creator_profile_id": str(body.get("creator_profile_id", ""))},
    )


def create_tip_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or 0)
    if amount < 1:
        raise ValueError("tip minimum is $1")
    return _checkout(
        f"Tip to {body.get('creator_name', 'creator')}",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "tip", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "message": (body.get("message") or "")[:200],
         "livestream_id": str(body.get("livestream_id") or "")},
    )


def create_ppv_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or body.get("ppv_price") or 0)
    if amount <= 0:
        raise ValueError("invalid PPV price")
    return _checkout(
        body.get("title") or body.get("post_title") or "Exclusive content",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "ppv", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "post_id": str(body.get("post_id", ""))},
    )
