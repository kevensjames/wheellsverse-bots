"""HTTP routes for Telegram private-group subscription checkout."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from narai.integrations import telegram_subscription as ts

logger = logging.getLogger("narai.telegram.subscription.routes")

rt = APIRouter(prefix="/telegram/subscription", tags=["telegram-subscription"])


class CheckoutRequest(BaseModel):
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str
    deep_link: str


@rt.post("/checkout", response_model=CheckoutResponse)
def create_checkout(body: CheckoutRequest) -> CheckoutResponse:
    """Create a Stripe subscription checkout session that pairs to Telegram on success.

    Returns the Stripe-hosted checkout URL plus the deep link that the success
    page should redirect to. The deep link carries a pairing token; once the
    user opens it the Telegram bot DMs them a single-use invite link.
    """
    price_id = os.getenv("STRIPE_PRICE_TG_GROUP", "")
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "")
    base_url = os.getenv("APP_BASE_URL", "https://app.wheellsverse.com").rstrip("/")
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")

    missing = [
        name for name, val in (
            ("STRIPE_PRICE_TG_GROUP", price_id),
            ("TELEGRAM_BOT_USERNAME", bot_username),
            ("STRIPE_SECRET_KEY", stripe_key),
        ) if not val
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Telegram subscription not configured: missing {', '.join(missing)}",
        )

    token = ts.new_pairing_token()
    deep_link = f"https://t.me/{bot_username}?start={token}"
    success_url = f"{base_url}/subscribe/success?goto={deep_link}"
    cancel_url = f"{base_url}/subscribe/cancelled"

    try:
        import stripe
    except ImportError:
        raise HTTPException(status_code=503, detail="stripe SDK not installed")

    stripe.api_key = stripe_key
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=body.email,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tg_pairing_token": token, "product": "tg_group"},
            subscription_data={
                "metadata": {"tg_pairing_token": token, "product": "tg_group"},
            },
            allow_promotion_codes=True,
        )
    except Exception as e:
        logger.exception("stripe checkout creation failed")
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")

    ts.attach_session(token, session.id)
    return CheckoutResponse(checkout_url=session.url, deep_link=deep_link)
