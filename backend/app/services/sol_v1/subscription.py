"""Sol v1 — member subscription (Connect Stage B): the $9.99/mo SaaS fee.

Sol's software revenue: a Stripe Billing subscription on Sol's OWN platform
account (reuses the existing stripe_service), entirely separate from member
ROSCA money. 'active'/'trialing' = the member has platform access.

Access suspension is OPT-IN: require_active_if_enabled() is a no-op unless
SOL_REQUIRE_SUBSCRIPTION=1, so the free manual rail is unaffected by default.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sol import SolMemberSubscription
from app.services import stripe_service
from app.services.sol_v1.lifecycle import SolError

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("active", "trialing")
PLAN_CODE = "sol_member"


# ── pure ──────────────────────────────────────────────────────────────────────


def is_active(status: str | None) -> bool:
    return status in ACTIVE_STATUSES


def _price_or_raise() -> str:
    price = (settings.STRIPE_PRICE_SOL_MEMBER or "").strip()
    if not price:
        raise SolError(503, "The membership subscription isn't available yet.")
    return price


def _pick_subscription(subs: list[dict], price_id: str) -> dict | None:
    """From a customer's subscriptions, the one for OUR price (prefer active)."""
    ours = [s for s in subs if _has_price(s, price_id)]
    if not ours:
        return None
    for s in ours:
        if s.get("status") in ACTIVE_STATUSES:
            return s
    return ours[0]


def _has_price(sub: dict, price_id: str) -> bool:
    get = (lambda o, k: o.get(k)) if isinstance(sub, dict) else (lambda o, k: getattr(o, k, None))
    items = (get(sub, "items") or {})
    data = (items.get("data") if isinstance(items, dict) else getattr(items, "data", None)) or []
    for it in data:
        price = it.get("price") if isinstance(it, dict) else getattr(it, "price", None)
        pid = (price.get("id") if isinstance(price, dict) else getattr(price, "id", None)) if price else None
        if pid == price_id:
            return True
    return False


# ── DB ────────────────────────────────────────────────────────────────────────


def _row(db: Session, user_id: UUID) -> SolMemberSubscription | None:
    return db.scalar(select(SolMemberSubscription).where(SolMemberSubscription.user_id == user_id))


def _get_or_create_row(db: Session, user_id: UUID) -> SolMemberSubscription:
    row = _row(db, user_id)
    if row is not None:
        return row
    row = SolMemberSubscription(user_id=user_id, status="none")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # concurrent checkout won the UNIQUE(user_id) race — return its row
        db.rollback()
        existing = _row(db, user_id)
        if existing is not None:
            return existing
        raise SolError(409, "could not initialize subscription, please retry")
    db.refresh(row)
    return row


def create_checkout(db: Session, *, user_id: UUID, email: str | None) -> str:
    """A Stripe Checkout URL for the $9.99/mo membership."""
    price = _price_or_raise()
    row = _get_or_create_row(db, user_id)
    try:
        customer_id = stripe_service.get_or_create_customer(
            user_id=str(user_id), email=email or "", existing_customer_id=row.stripe_customer_id
        )
        if row.stripe_customer_id != customer_id:
            row.stripe_customer_id = customer_id
            db.commit()
        return stripe_service.create_checkout_session(
            customer_id=customer_id, price_id=price,
            success_url=settings.SOL_SUBSCRIPTION_SUCCESS_URL,
            cancel_url=settings.SOL_SUBSCRIPTION_CANCEL_URL,
            user_id=str(user_id), plan_code=PLAN_CODE,
        )
    except stripe_service.StripeError as e:
        raise SolError(502, f"Stripe error: {e}")


def portal_link(db: Session, *, user_id: UUID) -> str:
    row = _row(db, user_id)
    if row is None or not row.stripe_customer_id:
        raise SolError(409, "Start a subscription first.")
    try:
        return stripe_service.create_portal_session(
            customer_id=row.stripe_customer_id, return_url=settings.SOL_SUBSCRIPTION_SUCCESS_URL
        )
    except stripe_service.StripeError as e:
        raise SolError(502, f"Stripe error: {e}")


def refresh(db: Session, *, user_id: UUID) -> SolMemberSubscription | None:
    """Re-sync the member's subscription status from Stripe."""
    row = _row(db, user_id)
    if row is None or not row.stripe_customer_id:
        return row
    price = (settings.STRIPE_PRICE_SOL_MEMBER or "").strip()
    stripe.api_key = (settings.STRIPE_SECRET_KEY or "").strip()
    try:
        resp = stripe.Subscription.list(customer=row.stripe_customer_id, status="all", limit=20)
    except stripe.StripeError as e:  # pragma: no cover — network path
        raise SolError(502, f"Stripe error refreshing subscription: {e}")
    data = resp.get("data", []) if isinstance(resp, dict) else getattr(resp, "data", [])
    sub = _pick_subscription(list(data), price)
    if sub is None:
        row.status = "none"
        row.stripe_subscription_id = None
        row.current_period_end = None
    else:
        row.status = sub.get("status", "none")
        row.stripe_subscription_id = sub.get("id")
        cpe = sub.get("current_period_end")
        row.current_period_end = datetime.fromtimestamp(cpe, tz=timezone.utc) if cpe else None
    db.commit()
    db.refresh(row)
    return row


def status(db: Session, *, user_id: UUID) -> dict:
    price_configured = bool((settings.STRIPE_PRICE_SOL_MEMBER or "").strip())
    row = _row(db, user_id)
    st = row.status if row else "none"
    return {
        "status": st,
        "active": is_active(st),
        "current_period_end": row.current_period_end if row else None,
        "available": price_configured,
        "required": bool(settings.SOL_REQUIRE_SUBSCRIPTION),
    }


def require_active_if_enabled(db: Session, *, user_id: UUID) -> None:
    """Access gate — a no-op unless SOL_REQUIRE_SUBSCRIPTION is on.

    When on, re-syncs from Stripe before deciding so the gate reflects the
    member's CURRENT status — a portal cancellation / card lapse revokes access,
    and a just-completed checkout grants it, without waiting for a client
    /refresh. (Stage-D webhooks will make this real-time; this keeps the gate
    trustworthy until then.) Fail-soft: if Stripe can't be reached, fall back to
    the stored status rather than hard-blocking a paying member on an outage.
    """
    if not settings.SOL_REQUIRE_SUBSCRIPTION:
        return
    row = _row(db, user_id)
    if row is not None and row.stripe_customer_id:
        try:
            row = refresh(db, user_id=user_id)
        except SolError:
            logger.warning("subscription gate: Stripe re-sync failed; using stored status")
    if row is None or not is_active(row.status):
        raise SolError(402, "An active membership subscription is required to do that.")
