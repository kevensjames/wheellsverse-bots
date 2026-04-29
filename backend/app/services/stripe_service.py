"""Stripe SDK wrapper. Every call that touches the Stripe network lives here,
so routes and tests only talk to this module.

The functions below are deliberately thin — no DB access, no business logic.
They take plain inputs (email, price_id, customer_id) and return plain outputs
(customer_id, checkout_url, parsed Event). That boundary is what lets the tests
mock one module (`stripe`) and assert on our behavior instead of Stripe's.
"""
from __future__ import annotations

import logging
from typing import Any

import stripe

from app.config import settings


logger = logging.getLogger(__name__)

# Set once at import time. Library is idempotent about this.
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeError(RuntimeError):
    """Raised for any non-success response from Stripe. Router maps to 502."""


def _ensure_configured() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise StripeError("STRIPE_SECRET_KEY not configured")


def get_or_create_customer(
    *, user_id: str, email: str, existing_customer_id: str | None
) -> str:
    """Return a Stripe customer_id for this user.

    If the user already has one persisted we trust it (no round-trip). Only
    create a new customer when we don't. Metadata carries our user UUID so we
    can reconcile from Stripe's dashboard or webhook payloads.
    """
    _ensure_configured()
    if existing_customer_id:
        return existing_customer_id

    try:
        customer = stripe.Customer.create(
            email=email,
            metadata={"user_id": user_id},
        )
    except stripe.StripeError as e:  # pragma: no cover — network path
        logger.exception("stripe.Customer.create failed")
        raise StripeError(str(e)) from e

    return customer["id"]


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    user_id: str,
    plan_code: str,
) -> str:
    """Open a Stripe-hosted Checkout page. Returns the URL to redirect to.

    `metadata` is echoed back on the webhook event — we put `user_id` and
    `plan_code` there so the webhook handler can resolve both without
    another DB lookup.
    """
    _ensure_configured()
    if not price_id:
        raise StripeError("price_id missing for plan")

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": user_id, "plan_code": plan_code},
            subscription_data={
                "metadata": {"user_id": user_id, "plan_code": plan_code},
            },
            allow_promotion_codes=True,
        )
    except stripe.StripeError as e:  # pragma: no cover
        logger.exception("stripe.checkout.Session.create failed")
        raise StripeError(str(e)) from e

    url = session.get("url")
    if not url:
        raise StripeError("Stripe checkout session returned no URL")
    return url


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Billing portal — where users manage/cancel subscriptions."""
    _ensure_configured()
    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except stripe.StripeError as e:  # pragma: no cover
        logger.exception("stripe.billing_portal.Session.create failed")
        raise StripeError(str(e)) from e
    return portal["url"]


def construct_event(*, payload: bytes, sig_header: str) -> dict[str, Any]:
    """Verify the webhook signature and return the parsed Event.

    This is the ONLY trust boundary — anything inside the returned event can be
    treated as Stripe-authenticated. If signature verification fails we raise
    StripeError; the router maps that to 400 (never 500 — a bad signature is
    client error from Stripe's retry infra).
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise StripeError("STRIPE_WEBHOOK_SECRET not configured")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError as e:
        raise StripeError(f"invalid payload: {e}") from e
    except stripe.SignatureVerificationError as e:
        raise StripeError(f"invalid signature: {e}") from e
    # Event is a StripeObject; convert to dict so router doesn't import stripe.
    return dict(event)
