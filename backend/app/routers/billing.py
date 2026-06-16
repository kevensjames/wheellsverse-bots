"""Stripe billing endpoints — refactored to match prod schema (no Plan table).

Flow:
  1. Free user → /nai-ui/pricing.html → clicks Subscribe → frontend POSTs
     /billing/checkout {plan_code: "pro"}.
  2. We look up the tier in the in-code TIER registry, get its stripe_price_id,
     create/lookup a Stripe customer (storing customer_id on the profile),
     create a Stripe Checkout Session, return the checkout_url.
  3. User pays on Stripe → Stripe POSTs checkout.session.completed to
     /billing/webhook → we upsert by stripe_subscription_id (UNIQUE constraint
     in prod gives us idempotency for free), set the row's tier + price_id,
     and also flip profiles.tier so the rate-limit check is one query, not two.
  4. customer.subscription.updated/deleted/invoice.payment_failed events
     mutate the existing row's status / cancel_at_period_end / period dates.

Why this looks different from Stage 5 / earlier billing.py:
- The fictional Plan model is gone. The `plans` table never existed in prod.
  Tier metadata (name, predictions/day, price_id) lives in
  app/services/billing/tiers.py — a single in-code registry. Stripe owns the
  price; we own the meaning.
- Subscription rows store tier (text) + stripe_price_id (text) directly,
  matching prod's denormalized schema.
- Webhook handler is idempotent: stripe_subscription_id has a UNIQUE
  constraint in prod, so re-deliveries are safe upserts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.models.subscription import Subscription
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    SubscriptionResponse,
    WebhookAck,
)
from app.services import stripe_service
from app.services.billing import tiers


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# ---------- helpers ----------


def _load_profile_or_404(db: Session, user_id) -> Profile:
    prof = db.get(Profile, user_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return prof


def _active_sub(db: Session, user_id) -> Subscription | None:
    """Most recent non-canceled subscription for this user."""
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status.in_(("active", "trialing", "past_due")),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


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
        spec = tiers.get(sub.tier) or tiers.get("free")
        return SubscriptionResponse(
            plan_code=sub.tier,
            plan_name=spec.display_name if spec else sub.tier.title(),
            status=sub.status,
            predictions_per_day=spec.predictions_per_day if spec else 0,
            current_period_end=sub.current_period_end,
            cancel_url=settings.BILLING_PUBLIC_UPGRADE_URL,
        )

    # No active sub → free tier
    free = tiers.get("free")
    return SubscriptionResponse(
        plan_code="free",
        plan_name=free.display_name,
        status="free",
        predictions_per_day=free.predictions_per_day,
        current_period_end=None,
        cancel_url=None,
    )


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    body: CheckoutRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
) -> CheckoutResponse:
    price_id = tiers.price_id_for(body.plan_code)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Plan '{body.plan_code}' not configured (no Stripe price ID set)",
        )

    profile = _load_profile_or_404(db, user.id)
    try:
        customer_id = stripe_service.get_or_create_customer(
            user_id=str(user.id),
            email=profile.email or (user.email or ""),
            existing_customer_id=profile.stripe_customer_id,
        )
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


# ---------- cancel survey ----------


class CancellationReasonRequest(BaseModel):
    reason_code: str = Field(..., pattern=r"^(too_expensive|missing_feature|not_using|switched_to|bug|other)$")
    free_text: str | None = Field(default=None, max_length=2000)


@router.post("/cancellation-reason", status_code=status.HTTP_201_CREATED)
def submit_cancellation_reason(
    body: CancellationReasonRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
):
    """User clicked Cancel in Stripe portal and returned to chat with
    ?canceled=1 — modal asks why. Store one row per submission, no dedup."""
    from app.models.cancellation_reason import CancellationReason
    from app.services import observability
    row = CancellationReason(
        user_id=user.id,
        reason_code=body.reason_code,
        free_text=(body.free_text or "").strip() or None,
    )
    db.add(row)
    db.commit()
    # Operator alert — cancellation reason is the highest-value retention signal.
    observability.notify(
        f"🔍 <b>Cancel reason</b>\n"
        f"user: {user.email or '?'}\n"
        f"reason: {body.reason_code}\n"
        + (f"<i>{body.free_text[:200] if body.free_text else ''}</i>" if body.free_text else "")
    )
    return {"received": True}


# ---------- winback ----------


WINBACK_COUPON_ID = "kai_winback_50off_1mo"


class WinbackResponse(BaseModel):
    applied: bool
    coupon_id: str
    message: str


@router.post("/winback/apply-discount", response_model=WinbackResponse)
def apply_winback_discount(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
) -> WinbackResponse:
    """Apply a 50%-off-next-month coupon to the user's active subscription.

    Triggered from the cancel-survey modal's "Wait — get 50% off" button.
    Idempotent at the Stripe level: re-applying the same coupon updates
    rather than stacks. Returns 409 if the user has no Stripe customer
    or no active sub.
    """
    profile = _load_profile_or_404(db, user.id)
    if not profile.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Stripe customer on file — nothing to discount.",
        )
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.status.in_(("active", "trialing")),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub is None or not sub.stripe_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active subscription to discount.",
        )

    # Apply via Stripe API: update the subscription's coupon field
    import urllib.parse, urllib.request, urllib.error, json as _json
    sk = settings.STRIPE_SECRET_KEY
    if not sk:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    body = urllib.parse.urlencode([("coupon", WINBACK_COUPON_ID)]).encode()
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/subscriptions/{sub.stripe_subscription_id}",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {sk}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            _json.loads(r.read())
    except urllib.error.HTTPError as e:
        logger.warning("winback coupon apply failed: %s %s", e.code, e.read()[:200])
        raise HTTPException(status_code=502, detail=f"Stripe error applying coupon")

    # Operator alert — every winback save is signal
    from app.services import observability
    observability.notify(
        f"💸 <b>Winback save</b>\n"
        f"user: {user.email or '?'}\n"
        f"coupon: {WINBACK_COUPON_ID} (50% off next month)\n"
        f"sub: <code>{sub.stripe_subscription_id}</code>"
    )

    return WinbackResponse(
        applied=True,
        coupon_id=WINBACK_COUPON_ID,
        message="50% off next month applied. Thank you for staying.",
    )


# ---------- webhook ----------


@router.post("/webhook", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> WebhookAck:
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
        logger.exception("webhook handler crashed for %s", event_type)
        raise HTTPException(status_code=500, detail="handler error")

    return WebhookAck(received=True, event_type=event_type)


# ---------- webhook handlers ----------


def _resolve_profile(db: Session, data: dict[str, Any]) -> Profile | None:
    """Locate the profiles row a webhook event refers to. metadata.user_id
    is preferred (we set it on /checkout); customer-id lookup is fallback."""
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


def _extract_price_id(data: dict[str, Any]) -> str | None:
    """Pull the Stripe price ID from any of the webhook payload shapes
    (checkout.session and customer.subscription wrap it differently)."""
    items = (data.get("items") or {}).get("data") or []
    if items:
        price = items[0].get("price") or {}
        if price.get("id"):
            return price["id"]
    # checkout.session.completed wraps via line_items expansion (we don't
    # expand by default), so fall back to metadata.plan_code → price_id.
    meta = data.get("metadata") or {}
    return tiers.price_id_for(meta.get("plan_code") or "")


def _handle_checkout_completed(db: Session, data: dict[str, Any]) -> None:
    """User finished paying. Upsert the subscription row + flip profile.tier."""
    profile = _resolve_profile(db, data)
    if not profile:
        logger.warning(
            "checkout.session.completed: no profile match for %s", data.get("id")
        )
        return

    meta = data.get("metadata") or {}
    plan_code = meta.get("plan_code")
    tier_code = plan_code if tiers.get(plan_code or "") else None
    # If metadata didn't carry plan_code (older flows), reverse-map price_id
    if not tier_code:
        tier_code = tiers.tier_for_price_id(_extract_price_id(data))
    if not tier_code or tier_code == "free":
        logger.warning(
            "checkout.session.completed: cannot resolve paid tier (plan_code=%r price_id=%r)",
            plan_code, _extract_price_id(data),
        )
        return

    stripe_sub_id = data.get("subscription")
    stripe_price_id = tiers.price_id_for(tier_code)

    # Upsert by UNIQUE stripe_subscription_id — Stripe retries are safe.
    sub = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_sub_id)
        .first()
        if stripe_sub_id
        else None
    )
    if sub:
        sub.status = "active"
        sub.tier = tier_code
        sub.stripe_price_id = stripe_price_id
    else:
        sub = Subscription(
            user_id=profile.id,
            tier=tier_code,
            stripe_subscription_id=stripe_sub_id,
            stripe_price_id=stripe_price_id,
            status="active",
        )
        db.add(sub)

    # Mirror tier on the profile for fast rate-limit checks (single query).
    profile.tier = tier_code
    # Backfill customer_id if it wasn't set during /checkout (edge case).
    if not profile.stripe_customer_id and data.get("customer"):
        profile.stripe_customer_id = data["customer"]

    db.commit()
    logger.info(
        "sub activated: user=%s tier=%s sub=%s", profile.id, tier_code, stripe_sub_id
    )
    from app.services import observability
    observability.alert_paid(profile.email, tier_code, stripe_sub_id or "")


def _handle_sub_updated(db: Session, data: dict[str, Any]) -> None:
    """Stripe tells us status changed (trialing→active, active→past_due, …)
    or the price changed (upgrade/downgrade). Trust Stripe verbatim."""
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

    new_status = data.get("status", sub.status)
    sub.status = new_status
    sub.current_period_start = _utc_from_ts(data.get("current_period_start"))
    sub.current_period_end = _utc_from_ts(data.get("current_period_end"))
    sub.cancel_at_period_end = bool(data.get("cancel_at_period_end"))

    new_price_id = _extract_price_id(data)
    if new_price_id and new_price_id != sub.stripe_price_id:
        sub.stripe_price_id = new_price_id
        new_tier = tiers.tier_for_price_id(new_price_id)
        if new_tier:
            sub.tier = new_tier
            # Sync the profile mirror — but only when status is still active.
            if new_status in ("active", "trialing"):
                profile = db.get(Profile, sub.user_id)
                if profile:
                    profile.tier = new_tier

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
    # Drop the profile back to free so rate limits kick in immediately.
    profile = db.get(Profile, sub.user_id)
    if profile:
        profile.tier = "free"
    db.commit()
    logger.info("sub canceled: %s", stripe_sub_id)
    from app.services import observability
    observability.alert_canceled(profile.email if profile else "?", stripe_sub_id)


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
    profile = db.get(Profile, sub.user_id)
    from app.services import observability
    observability.alert_payment_failed(
        profile.email if profile else "?", stripe_sub_id
    )
