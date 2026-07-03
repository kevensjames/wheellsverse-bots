"""Sol v1 — Stripe Connect rail (non-custodial, sandbox-locked).

The SECOND payment provider, behind the same ROSCA core. Each member connects
their OWN Stripe (Express) account; contributions will settle directly into the
recipient's connected account via DESTINATION charges (Sol's platform balance is
never touched — non-custodial). This module (Connect Stage A) covers only the
foundation: the sandbox lock + connected-account onboarding. No money moves here.

SANDBOX LOCK (the safety core): every Connect operation goes through _guard(),
which refuses to run when
  - Stripe Connect isn't enabled (STRIPE_CONNECT_ENABLED),
  - Stripe isn't configured, or
  - a LIVE key (sk_live_) is set WITHOUT STRIPE_CONNECT_LIVE_APPROVED — the
    operator sets that only after Stripe approves the ROSCA use case in writing
    AND counsel signs off. Until then the rail is test-mode only.

sandbox_state() and map_capabilities() are pure (unit-tested); the Stripe API
calls are isolated so they can be mocked in tests and only ever run in sandbox.
"""
from __future__ import annotations

import logging
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sol import SolStripeAccount
from app.services.sol_v1.lifecycle import SolError

logger = logging.getLogger(__name__)


# ── pure: sandbox state + capability mapping ─────────────────────────────────


def sandbox_state() -> dict:
    """What mode the Connect rail is in, without touching Stripe."""
    key = (settings.STRIPE_SECRET_KEY or "").strip()
    approved = bool(settings.STRIPE_CONNECT_LIVE_APPROVED)
    # Fail CLOSED: only a key that is provably a TEST key (contains "_test_")
    # counts as test. sk_live_, rk_live_ (restricted live — Stripe's recommended
    # production key), and ANY unrecognized format classify as live → blocked
    # unless STRIPE_CONNECT_LIVE_APPROVED. Never treat an unknown key as safe.
    live = bool(key) and "_test_" not in key
    if not key:
        mode = "unconfigured"
    elif not live:
        mode = "test"
    elif approved:
        mode = "live"
    else:
        mode = "blocked_live"  # live (or unrecognized) key present but not approved → refuse
    return {
        "enabled": bool(settings.STRIPE_CONNECT_ENABLED),
        "configured": bool(key),
        "live_key": live,
        "live_approved": approved,
        "mode": mode,
    }


def map_capabilities(acct) -> dict:
    """Map a Stripe Account object/dict to our stored capability flags."""
    get = (lambda k: acct.get(k)) if isinstance(acct, dict) else (lambda k: getattr(acct, k, None))
    return {
        "charges_enabled": bool(get("charges_enabled")),
        "payouts_enabled": bool(get("payouts_enabled")),
        "details_submitted": bool(get("details_submitted")),
    }


def _guard() -> None:
    s = sandbox_state()
    if not s["enabled"]:
        raise SolError(403, "The Stripe rail is not enabled.")
    if not s["configured"]:
        raise SolError(503, "Stripe is not configured.")
    if s["mode"] == "blocked_live":
        raise SolError(403, "The Stripe rail is sandbox-only until live use is approved.")
    stripe.api_key = (settings.STRIPE_SECRET_KEY or "").strip()


# ── DB helpers ────────────────────────────────────────────────────────────────


def _row(db: Session, user_id: UUID) -> SolStripeAccount | None:
    return db.scalar(select(SolStripeAccount).where(SolStripeAccount.user_id == user_id))


# ── connected-account onboarding ─────────────────────────────────────────────


def create_or_get_account(db: Session, *, user_id: UUID, email: str | None = None) -> SolStripeAccount:
    """Get (or create in Stripe) the member's Express connected account."""
    _guard()
    row = _row(db, user_id)
    if row is not None:
        return row
    try:
        acct = stripe.Account.create(
            type="express",
            email=email,
            capabilities={"transfers": {"requested": True}},
            metadata={"sol_user_id": str(user_id)},
            # Dedupe concurrent/retried creates so a double-click can't mint a
            # second real connected account for the same member.
            idempotency_key="sol_connect_acct_" + str(user_id),
        )
    except stripe.StripeError as e:  # pragma: no cover — network path
        logger.exception("stripe.Account.create failed")
        raise SolError(502, f"Stripe error creating account: {getattr(e, 'user_message', None) or 'unknown'}")

    caps = map_capabilities(acct)
    row = SolStripeAccount(user_id=user_id, stripe_account_id=acct["id"], **caps)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # a concurrent onboard won the UNIQUE(user_id) race — return its row
        db.rollback()
        existing = _row(db, user_id)
        if existing is not None:
            return existing
        raise SolError(409, "could not create the connected account, please retry")
    db.refresh(row)
    return row


def onboarding_link(db: Session, *, user_id: UUID, email: str | None = None) -> str:
    """A Stripe-hosted onboarding URL for the member's connected account."""
    _guard()
    row = create_or_get_account(db, user_id=user_id, email=email)
    try:
        link = stripe.AccountLink.create(
            account=row.stripe_account_id,
            refresh_url=settings.STRIPE_CONNECT_REFRESH_URL,
            return_url=settings.STRIPE_CONNECT_RETURN_URL,
            type="account_onboarding",
        )
    except stripe.StripeError as e:  # pragma: no cover
        logger.exception("stripe.AccountLink.create failed")
        raise SolError(502, f"Stripe error creating onboarding link: {getattr(e, 'user_message', None) or 'unknown'}")
    return link["url"]


def refresh_status(db: Session, *, user_id: UUID) -> SolStripeAccount | None:
    """Re-fetch the connected account from Stripe and update our capability flags."""
    _guard()
    row = _row(db, user_id)
    if row is None:
        return None
    try:
        acct = stripe.Account.retrieve(row.stripe_account_id)
    except stripe.StripeError as e:  # pragma: no cover
        logger.exception("stripe.Account.retrieve failed")
        raise SolError(502, f"Stripe error refreshing account: {getattr(e, 'user_message', None) or 'unknown'}")
    caps = map_capabilities(acct)
    row.charges_enabled = caps["charges_enabled"]
    row.payouts_enabled = caps["payouts_enabled"]
    row.details_submitted = caps["details_submitted"]
    db.commit()
    db.refresh(row)
    return row


def account_status(db: Session, *, user_id: UUID) -> dict:
    """The member's connect status (from our DB; no Stripe call)."""
    s = sandbox_state()
    row = _row(db, user_id)
    if row is None:
        return {
            "connected": False, "onboarding_complete": False, "charges_enabled": False,
            "payouts_enabled": False, "details_submitted": False, "mode": s["mode"],
        }
    return {
        "connected": True,
        "onboarding_complete": bool(row.details_submitted and row.charges_enabled),
        "charges_enabled": row.charges_enabled,
        "payouts_enabled": row.payouts_enabled,
        "details_submitted": row.details_submitted,
        "mode": s["mode"],
    }
