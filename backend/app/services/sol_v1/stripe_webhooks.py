"""Sol v1 — Stripe webhook handlers (Connect Stage D).

Closes the loops that reconcile() and the subscription gate re-sync bridge
manually:
  - checkout.session.completed  → settle a contribution (confirm the ledger)
  - customer.subscription.*      → mirror the member's $9.99 subscription status
  - account.updated              → refresh a connected account's capability flags
  - charge.refunded / charge.dispute.created → REVERSE a settled contribution
    (flag the ledger payment disputed so it stops counting as paid)

Events for BOTH the platform (subscriptions) and connected accounts
(contributions) arrive here; each handler filters to what it owns (Sol price,
known Sol customer/account/payment), so KAI-tier and unrelated events no-op.
Signature verification + idempotency are enforced by the router.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sol import (
    SolMemberSubscription, SolPayment, SolStripeAccount, SolStripePayment,
)
from app.services.sol_v1 import stripe_charges
from app.services.sol_v1 import subscription as sub_svc
from app.services.sol_v1.stripe_connect import map_capabilities

logger = logging.getLogger(__name__)

HANDLED_TYPES = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "account.updated",
    "charge.refunded",
    "charge.dispute.created",
}


def _ts_to_dt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def _on_checkout_completed(db: Session, obj: dict) -> bool:
    """A contribution checkout completed → settle the ledger payment."""
    meta = obj.get("metadata") or {}
    payment_id = meta.get("sol_payment_id")
    if not payment_id:
        return False  # not a Sol contribution (e.g. a subscription checkout)
    row = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == payment_id))
    if row is None:
        return False
    pi = obj.get("payment_intent")
    if pi and not row.stripe_payment_intent_id:
        row.stripe_payment_intent_id = pi
        db.flush()
    if obj.get("payment_status") == "paid":
        # Verify the LIVE PaymentIntent (like reconcile) rather than trusting the
        # event's frozen payment_status — an out-of-order/retried event must not
        # settle a charge that has since been refunded/disputed.
        stripe.api_key = (settings.STRIPE_SECRET_KEY or "").strip()
        genuinely_paid, _pi = stripe_charges._session_is_genuinely_paid(obj, row.destination_account_id)
        if genuinely_paid:
            stripe_charges.mark_settled(db, sol_stripe_payment=row)
            return True
    db.commit()
    return True


def _on_subscription_change(db: Session, obj: dict) -> bool:
    """Mirror a member's $9.99 subscription status (only ours, by price)."""
    price = (settings.STRIPE_PRICE_SOL_MEMBER or "").strip()
    if not price or not sub_svc._has_price(obj, price):
        return False  # a KAI-tier or unrelated subscription — leave it alone
    customer = obj.get("customer")
    row = db.scalar(
        select(SolMemberSubscription).where(SolMemberSubscription.stripe_customer_id == customer)
    )
    if row is None:
        return False  # not a Sol-tracked customer
    incoming_status = obj.get("status", "none")
    incoming_sub = obj.get("id")
    # Out-of-order guard: 'canceled' is terminal for a given subscription id — a
    # late/retried 'updated' (active) for the SAME sub must not resurrect it.
    # (A genuine re-subscribe arrives with a NEW subscription id and still applies.)
    if row.status == "canceled" and row.stripe_subscription_id == incoming_sub and incoming_status != "canceled":
        return False
    row.status = incoming_status
    row.stripe_subscription_id = incoming_sub
    row.current_period_end = _ts_to_dt(obj.get("current_period_end"))
    db.commit()
    return True


def _on_account_updated(db: Session, obj: dict) -> bool:
    """Refresh a connected account's capability flags."""
    row = db.scalar(
        select(SolStripeAccount).where(SolStripeAccount.stripe_account_id == obj.get("id"))
    )
    if row is None:
        return False
    caps = map_capabilities(obj)
    row.charges_enabled = caps["charges_enabled"]
    row.payouts_enabled = caps["payouts_enabled"]
    row.details_submitted = caps["details_submitted"]
    db.commit()
    return True


def _on_charge_reversal(db: Session, obj: dict, *, kind: str) -> bool:
    """A settled contribution was refunded/disputed → un-count it.

    Flags the ledger payment 'disputed' (sticky disputed_at, so reputation
    reflects it) and marks the Stripe row refunded/disputed. NOTE: it does NOT
    auto-reverse a cycle that already completed on this payment — that financial
    unwinding is an exceptional case for manual resolution (logged here).
    """
    pi = obj.get("payment_intent")
    if not pi:
        return False
    row = db.scalar(
        select(SolStripePayment).where(SolStripePayment.stripe_payment_intent_id == pi)
    )
    if row is None:
        return False
    row.status = "refunded" if kind == "refund" else "disputed"
    payment = db.get(SolPayment, row.payment_id, with_for_update=True)
    if payment is not None and payment.method == "stripe":
        payment.status = "disputed"
        if payment.disputed_at is None:
            payment.disputed_at = datetime.now(timezone.utc)
        logger.warning(
            "sol stripe %s on settled contribution payment=%s (manual review may be needed)",
            kind, row.payment_id,
        )
    db.commit()
    return True


def handle_event(db: Session, event: dict) -> dict:
    """Dispatch a verified Stripe event. Returns {handled, type}."""
    etype = event.get("type")
    obj = ((event.get("data") or {}).get("object")) or {}
    handled = False
    try:
        if etype == "checkout.session.completed":
            handled = _on_checkout_completed(db, obj)
        elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            handled = _on_subscription_change(db, obj)
        elif etype == "account.updated":
            handled = _on_account_updated(db, obj)
        elif etype == "charge.refunded":
            handled = _on_charge_reversal(db, obj, kind="refund")
        elif etype == "charge.dispute.created":
            handled = _on_charge_reversal(db, obj, kind="dispute")
    except Exception:
        db.rollback()
        logger.exception("sol stripe webhook handler failed for %s", etype)
        raise
    return {"handled": handled, "type": etype}
