"""Sol v1 — Stripe rail contribution settlement (Connect Stage C).

A payer settles a ledger payment by paying the recipient through Stripe. The
charge is a DIRECT charge created ON the recipient's connected account
(stripe_account=<recipient account>): the RECIPIENT is the merchant of record,
funds settle in their account, and Sol's platform balance is NEVER touched AND
Sol bears NO refund/chargeback liability — the fully non-custodial model. Sol
takes no cut (no application fee); it earns only the $9.99 subscription.

When Stripe reports the charge genuinely paid (reconcile() verifies the
PaymentIntent succeeded, full amount, not refunded/disputed; the Stage-D webhook
will do the same in real time), the ledger payment is marked 'confirmed' —
Stripe settling into the recipient's account IS the confirmation.

SANDBOX-LOCKED (reuses stripe_connect._guard): refuses live Stripe until the
ROSCA use case is approved.

THE INVARIANT (enforced in code): build_direct_charge_call refuses to build any
charge without the recipient's connected account, and never uses transfer_data
(a destination charge would make Sol merchant of record = chargeback custody).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sol import SolPayment, SolStripeAccount, SolStripePayment
from app.services.sol_v1 import ledger
from app.services.sol_v1.lifecycle import SolError
from app.services.sol_v1.stripe_connect import _guard as _connect_guard

logger = logging.getLogger(__name__)

# a payment can be settled via Stripe only while it's genuinely unpaid
PAYABLE_STATUSES = ("pending", "late")


# ── pure: the non-custodial invariant ────────────────────────────────────────


def to_cents(amount) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _assert_connected_account(connected_account_id: str | None) -> None:
    # NON-CUSTODIAL invariant: the contribution charge is ALWAYS a DIRECT charge
    # created ON the recipient's connected account. Without one the charge would
    # land on Sol's platform account (custody). Refuse.
    if not connected_account_id or not str(connected_account_id).strip():
        raise SolError(500, "refusing to build a charge with no connected account (non-custodial invariant)")


def build_direct_charge_call(
    *, connected_account_id: str, amount_cents: int, payment_id, payer_id,
    success_url: str, cancel_url: str, currency: str = "usd",
) -> dict:
    """Kwargs for a DIRECT-charge Checkout Session created ON the recipient's
    connected account (stripe_account). Recipient is merchant of record; Sol's
    balance + liability are never involved. No transfer_data, no application fee."""
    _assert_connected_account(connected_account_id)
    if amount_cents <= 0:
        raise SolError(400, "contribution amount must be positive")
    meta = {"sol_payment_id": str(payment_id), "sol_payer_id": str(payer_id)}
    return {
        "mode": "payment",
        "line_items": [{
            "price_data": {
                "currency": currency,
                "product_data": {"name": "Sol circle contribution"},
                "unit_amount": amount_cents,
            },
            "quantity": 1,
        }],
        "payment_intent_data": {"metadata": meta},
        "metadata": meta,
        "success_url": success_url,
        "cancel_url": cancel_url,
        # DIRECT charge on the recipient's connected account — the ONLY way both
        # the funds AND the chargeback liability stay entirely with the recipient.
        "stripe_account": connected_account_id,
    }


# ── settlement ────────────────────────────────────────────────────────────────


def mark_settled(db: Session, *, sol_stripe_payment: SolStripePayment) -> SolStripePayment:
    """A verified-paid charge → confirm the ledger payment (idempotent).

    Reuses the ledger's completion cascade so a Stripe-settled cycle completes
    exactly like a manually-confirmed one. Callers (reconcile / Stage-D webhook)
    MUST have verified the charge genuinely succeeded first.
    """
    row = sol_stripe_payment
    if row.status in ("paid", "refunded", "disputed"):
        # already settled, or REVERSED (refund/chargeback) — never (re)settle.
        # This is the guard that stops an out-of-order/retried
        # checkout.session.completed from re-confirming reversed money.
        return row
    row.status = "paid"
    payment = db.get(SolPayment, row.payment_id, with_for_update=True)
    if payment is not None and payment.disputed_at is None and payment.status not in ("confirmed", "disputed"):
        now = datetime.now(timezone.utc)
        payment.method = "stripe"
        payment.status = "confirmed"
        payment.payer_marked_at = payment.payer_marked_at or now
        payment.payee_confirmed_at = now
        db.flush()
        ledger._maybe_complete_cycle(db, payment.cycle_id)
    db.commit()
    db.refresh(row)
    return row


def settle_payment_intent(db: Session, *, payment_intent_id: str) -> SolStripePayment | None:
    """Webhook entry: settle by Stripe payment_intent id (already verified paid)."""
    row = db.scalar(
        select(SolStripePayment).where(SolStripePayment.stripe_payment_intent_id == payment_intent_id)
    )
    if row is None:
        return None
    return mark_settled(db, sol_stripe_payment=row)


def _session_is_genuinely_paid(session_obj: dict, connected_account_id: str) -> tuple[bool, str | None]:
    """(paid, payment_intent_id) — True ONLY if the PaymentIntent succeeded, the
    full amount was captured, and nothing was refunded/disputed. Never trust the
    session's payment_status flag alone (it stays 'paid' after a later refund)."""
    pi_id = session_obj.get("payment_intent")
    if session_obj.get("payment_status") != "paid" or not pi_id:
        return False, pi_id
    try:
        pi = stripe.PaymentIntent.retrieve(pi_id, stripe_account=connected_account_id, expand=["latest_charge"])
    except stripe.StripeError:  # pragma: no cover
        return False, pi_id
    if pi.get("status") != "succeeded":
        return False, pi_id
    charge = pi.get("latest_charge") or {}
    if isinstance(charge, str):  # not expanded → be conservative
        return False, pi_id
    if charge.get("refunded") or (charge.get("amount_refunded") or 0) > 0 or charge.get("disputed"):
        return False, pi_id
    return True, pi_id


# ── create the contribution checkout ─────────────────────────────────────────


def create_contribution_checkout(db: Session, *, payment_id: UUID, payer_id: UUID) -> str:
    """A Stripe Checkout URL for the payer to settle this ledger payment."""
    _connect_guard()  # sandbox lock

    payment = db.get(SolPayment, payment_id)
    if payment is None:
        raise SolError(404, "payment not found")
    if payment.payer_id != payer_id:
        raise SolError(403, "only the payer can pay this")
    if payment.status not in PAYABLE_STATUSES:
        raise SolError(409, f"this payment is already {payment.status}")

    recipient = db.scalar(
        select(SolStripeAccount).where(SolStripeAccount.user_id == payment.payee_id)
    )
    if recipient is None or not recipient.charges_enabled:
        raise SolError(409, "the recipient hasn't finished setting up card payments yet")

    stripe.api_key = (settings.STRIPE_SECRET_KEY or "").strip()

    # Double-charge guard: don't blindly mint a second session for a payment that
    # already has a Stripe attempt. If a prior session already paid, settle it
    # and refuse; otherwise reuse the row.
    existing = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == payment_id))
    if existing is not None:
        if existing.status == "paid":
            raise SolError(409, "this contribution was already paid")
        if existing.stripe_checkout_session_id:
            try:
                sess = stripe.checkout.Session.retrieve(
                    existing.stripe_checkout_session_id, stripe_account=existing.destination_account_id
                )
                paid, pi_id = _session_is_genuinely_paid(sess, existing.destination_account_id)
                if pi_id and not existing.stripe_payment_intent_id:
                    existing.stripe_payment_intent_id = pi_id
                    db.commit()
                if paid:
                    mark_settled(db, sol_stripe_payment=existing)
                    raise SolError(409, "this contribution was already paid")
            except stripe.StripeError:
                pass  # can't verify the old session — fall through to a fresh one

    params = build_direct_charge_call(
        connected_account_id=recipient.stripe_account_id,
        amount_cents=to_cents(payment.amount),
        payment_id=payment.id, payer_id=payer_id,
        success_url=settings.STRIPE_CONNECT_RETURN_URL,
        cancel_url=settings.STRIPE_CONNECT_REFRESH_URL,
    )
    try:
        session = stripe.checkout.Session.create(**params, idempotency_key="sol_contrib_" + str(payment_id))
    except stripe.StripeError as e:  # pragma: no cover — network path
        logger.exception("stripe checkout create (contribution) failed")
        raise SolError(502, f"Stripe error creating checkout: {getattr(e, 'user_message', None) or 'unknown'}")

    if existing is None:
        row = SolStripePayment(
            payment_id=payment_id, payer_id=payer_id,
            destination_account_id=recipient.stripe_account_id, amount=payment.amount,
            stripe_checkout_session_id=session.get("id"),
            stripe_payment_intent_id=session.get("payment_intent"),
            status="pending",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == payment_id))
    else:
        existing.stripe_checkout_session_id = session.get("id")
        existing.stripe_payment_intent_id = session.get("payment_intent")
        db.commit()
    return session.get("url")


def reconcile(db: Session, *, payment_id: UUID, actor_id: UUID) -> dict:
    """Re-check Stripe for a payment's charge and settle if genuinely paid (the
    bridge until the Stage-D webhook). Payer or payee may reconcile."""
    _connect_guard()
    row = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == payment_id))
    if row is None:
        raise SolError(404, "no Stripe payment for this")
    payment = db.get(SolPayment, payment_id)
    if payment is None or actor_id not in (payment.payer_id, payment.payee_id):
        raise SolError(403, "you are not a party to this payment")

    stripe.api_key = (settings.STRIPE_SECRET_KEY or "").strip()
    if row.status != "paid" and row.stripe_checkout_session_id:
        try:
            sess = stripe.checkout.Session.retrieve(
                row.stripe_checkout_session_id, stripe_account=row.destination_account_id
            )
        except stripe.StripeError as e:  # pragma: no cover
            raise SolError(502, f"Stripe error reconciling: {e}")
        paid, pi_id = _session_is_genuinely_paid(sess, row.destination_account_id)
        if pi_id and not row.stripe_payment_intent_id:
            row.stripe_payment_intent_id = pi_id
            db.commit()
        if paid:
            row = mark_settled(db, sol_stripe_payment=row)
    return charge_status(db, payment_id=payment_id, actor_id=actor_id)


def charge_status(db: Session, *, payment_id: UUID, actor_id: UUID) -> dict:
    """The Stripe charge status for a payment — party-only (payer or payee)."""
    payment = db.get(SolPayment, payment_id)
    if payment is not None and actor_id not in (payment.payer_id, payment.payee_id):
        raise SolError(403, "you are not a party to this payment")
    row = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == payment_id))
    if row is None:
        return {"exists": False, "status": None, "destination_account_id": None, "stripe_payment_intent_id": None}
    return {
        "exists": True,
        "status": row.status,
        "destination_account_id": row.destination_account_id,
        "stripe_payment_intent_id": row.stripe_payment_intent_id,
    }
