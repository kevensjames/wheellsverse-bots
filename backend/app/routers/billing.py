"""Stripe billing endpoints.

Flow:
  1. Free user hits /predictions/today 3x → 4th gets 402 w/ `upgrade_url`.
  2. Frontend sends them to /pricing → they pick Pro → frontend POSTs
     /billing/checkout → we return a Stripe Checkout URL → frontend redirects.
  3. User pays on Stripe-hosted page → Stripe POSTs checkout.session.completed
     to /billing/webhook → we flip their subscription to active.
  4. Next request to /predictions/today sees an active Pro sub → no 402.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.models.subscription import Plan, Subscription
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    SubscriptionResponse,
    WebhookAck,
)
from app.services import stripe_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# ---------- helpers ----------

def _price_id_for_plan(plan_code: str) -> str:
    mapping = {
        "pro": settings.STRIPE_PRICE_PRO,
        "elite": settings.STRIPE_PRICE_ELITE,
    }
    return mapping.get(plan_code, "")


def _active_sub(db: Session, user_id) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status.in_(("active", "trialing", "past_due")),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


def _plan_by_price_id(db: Session, price_id: str | None) -> Plan | None:
    if not price_id:
        return None
    return db.query(Plan).filter(Plan.stripe_price_id == price_id).first()


def _plan_by_code(db: Session, code: str) -> Plan | None:
    return db.query(Plan).filter(Plan.code == code).first()


def _load_profile_or_404(db: Session, user_id) -> Profile:
    """Path X: pull the profile row by id. The Supabase trigger guarantees
    one exists for every auth.users row, so missing = bug."""
    prof = db.get(Profile, user_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return prof


def _utc_from_ts(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


# ---------- user-facing endpoints ----------

@router.get("/subscription", response_model=SubscriptionResponse)
def current_subscription(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
) -> SubscriptionResponse:
    sub = _active_sub(db, user.id)
    if sub:
        plan = db.get(Plan, sub.plan_id)
        return SubscriptionResponse(
            plan_code=plan.code if plan else "unknown",
            plan_name=plan.name if plan else "Unknown",
            status=sub.status,
            predictions_per_day=plan.predictions_per_day if plan else 0,
            current_period_end=sub.current_period_end,
            cancel_url=f"{settings.BILLING_PUBLIC_UPGRADE_URL}",  # portal is behind auth
        )

    # No active sub → free tier
    free = _plan_by_code(db, "free")
    return SubscriptionResponse(
        plan_code="free",
        plan_name=free.name if free else "Free",
        status="free",
        predictions_per_day=free.predictions_per_day if free else 3,
        current_period_end=None,
        cancel_url=None,
    )


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    body: CheckoutRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
) -> CheckoutResponse:
    price_id = _price_id_for_plan(body.plan_code)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Plan '{body.plan_code}' not configured (STRIPE_PRICE_* env missing)",
        )

    profile = _load_profile_or_404(db, user.id)
    try:
        customer_id = stripe_service.get_or_create_customer(
            user_id=str(user.id),
            email=profile.email or (user.email or ""),
            existing_customer_id=profile.stripe_customer_id,
        )
        # Persist customer_id so we don't create duplicates on retry
        if profile.stripe_customer_id != customer_id:
            profile.stripe_customer_id = customer_id
            db.commit()

        checkout_url = stripe_service.create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
            user_id=str(user.id),
            plan_code=body.plan_code,
        )
    except stripe_service.StripeError as e:
        logger.warning("checkout failed for %s: %s", user.id, e)
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")

    return CheckoutResponse(checkout_url=checkout_url, plan_code=body.plan_code)


@router.post("/portal", response_model=PortalResponse)
def create_portal(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
) -> PortalResponse:
    profile = _load_profile_or_404(db, user.id)
    if not profile.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Stripe customer on file — subscribe first",
        )
    try:
        portal_url = stripe_service.create_portal_session(
            customer_id=profile.stripe_customer_id,
            return_url=settings.BILLING_PUBLIC_UPGRADE_URL,
        )
    except stripe_service.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")
    return PortalResponse(portal_url=portal_url)


# ---------- webhook ----------

@router.post("/webhook", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> WebhookAck:
    """Stripe hits this on every billing event.

    Return 2xx on success OR on 'known unhandled' events — Stripe retries any
    non-2xx with exponential backoff. Only return 4xx for malformed payloads.
    """
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="missing Stripe-Signature")

    payload = await request.body()
    try:
        event = stripe_service.construct_event(
            payload=payload, sig_header=stripe_signature
        )
    except stripe_service.StripeError as e:
        logger.warning("webhook signature verify failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {}) or {}

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(db, data)
        elif event_type == "customer.subscription.updated":
            _handle_sub_updated(db, data)
        elif event_type == "customer.subscription.deleted":
            _handle_sub_deleted(db, data)
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(db, data)
        else:
            logger.info("webhook: ignoring unhandled event type %s", event_type)
    except Exception:
        # Log full context but still 500 so Stripe retries. A buggy handler is
        # our problem — let Stripe's retry loop buy us time to fix.
        logger.exception("webhook handler crashed for %s", event_type)
        raise HTTPException(status_code=500, detail="handler error")

    return WebhookAck(received=True, event_type=event_type)


# ---------- webhook handlers ----------

def _resolve_profile(db: Session, data: dict[str, Any]) -> Profile | None:
    """Path X: locate the profiles row from a webhook payload.

    Tries metadata.user_id first (set by /checkout), falls back to
    stripe_customer_id lookup (for subscription.updated events where
    metadata may not be preserved).
    """
    meta = data.get("metadata") or {}
    user_id = meta.get("user_id")
    if user_id:
        prof = db.get(Profile, user_id)
        if prof:
            return prof

    customer_id = data.get("customer")
    if customer_id:
        return (
            db.query(Profile)
            .filter(Profile.stripe_customer_id == customer_id)
            .first()
        )
    return None


def _handle_checkout_completed(db: Session, data: dict[str, Any]) -> None:
    """User finished paying — create or activate the Subscription row."""
    profile = _resolve_profile(db, data)
    if not profile:
        logger.warning("checkout.session.completed: no matching profile in %s", data.get("id"))
        return

    meta = data.get("metadata") or {}
    plan_code = meta.get("plan_code")
    plan = _plan_by_code(db, plan_code) if plan_code else None
    stripe_sub_id = data.get("subscription")

    if not plan:
        logger.warning("checkout.session.completed: unknown plan_code=%s", plan_code)
        return

    # Upsert: one row per stripe_subscription_id. If it exists, just flip to active.
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_sub_id)
        .first()
        if stripe_sub_id
        else None
    )
    if sub:
        sub.status = "active"
        sub.plan_id = plan.id
    else:
        sub = Subscription(
            user_id=profile.id,
            plan_id=plan.id,
            stripe_subscription_id=stripe_sub_id,
            status="active",
        )
        db.add(sub)

    # Ensure stripe_customer_id is persisted (user could have paid via Checkout
    # without us having created the customer first — edge case but covers it).
    if not profile.stripe_customer_id and data.get("customer"):
        profile.stripe_customer_id = data["customer"]

    db.commit()
    logger.info("sub activated: user=%s plan=%s sub=%s", profile.id, plan.code, stripe_sub_id)


def _handle_sub_updated(db: Session, data: dict[str, Any]) -> None:
    """Stripe tells us status changed (trialing→active, active→past_due, etc.).

    We trust Stripe's status verbatim — our `status` column is free-form.
    """
    stripe_sub_id = data.get("id")
    if not stripe_sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_sub_id)
        .first()
    )
    if not sub:
        logger.info("sub.updated: no local row for %s (possibly pre-checkout)", stripe_sub_id)
        return

    sub.status = data.get("status", sub.status)
    sub.current_period_end = _utc_from_ts(data.get("current_period_end"))

    # Price change? Re-link to new plan.
    items = (data.get("items") or {}).get("data") or []
    if items:
        price_id = (items[0].get("price") or {}).get("id")
        new_plan = _plan_by_price_id(db, price_id)
        if new_plan and new_plan.id != sub.plan_id:
            sub.plan_id = new_plan.id

    db.commit()


def _handle_sub_deleted(db: Session, data: dict[str, Any]) -> None:
    stripe_sub_id = data.get("id")
    if not stripe_sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_sub_id)
        .first()
    )
    if not sub:
        return
    sub.status = "canceled"
    db.commit()
    logger.info("sub canceled: %s", stripe_sub_id)


def _handle_payment_failed(db: Session, data: dict[str, Any]) -> None:
    stripe_sub_id = data.get("subscription")
    if not stripe_sub_id:
        return
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_sub_id)
        .first()
    )
    if not sub:
        return
    sub.status = "past_due"
    db.commit()
