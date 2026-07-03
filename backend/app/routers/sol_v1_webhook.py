"""Sol v1 — Stripe webhook endpoint (Connect Stage D).

POST /sol/v1/stripe/webhook — verifies the Sol-specific signing secret
(STRIPE_CONNECT_WEBHOOK_SECRET, separate from the KAI billing webhook), claims
each event.id for idempotency (ProcessedStripeEvent), then dispatches to
services/sol_v1/stripe_webhooks. A bad signature is a 400 (client error from
Stripe's retry infra), never a 500. NON-CUSTODIAL: handlers only record/settle;
no money is moved here.
"""
from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.stripe_event import ProcessedStripeEvent
from app.services.sol_v1 import stripe_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-stripe"])


def _claim(db: Session, event_id: str | None, event_type: str | None) -> bool:
    """Atomically claim event_id — True if first-seen (proceed), False if a
    duplicate delivery (skip). Fail-soft: a dedupe-store hiccup returns True."""
    if not event_id:
        return True
    try:
        ProcessedStripeEvent.__table__.create(bind=db.get_bind(), checkfirst=True)
        res = db.execute(
            pg_insert(ProcessedStripeEvent)
            .values(event_id=event_id, event_type=event_type)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        db.commit()
        return res.rowcount > 0
    except Exception as e:  # noqa: BLE001
        logger.warning("sol webhook: event claim failed for %s: %s", event_id, e)
        db.rollback()
        return True


def _release(db: Session, event_id: str | None) -> None:
    """Undo a claim when the handler failed, so Stripe's retry re-processes."""
    if not event_id:
        return
    try:
        db.query(ProcessedStripeEvent).filter_by(event_id=event_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


@router.post("/stripe/webhook")
async def sol_stripe_webhook(request: Request, db: Session = Depends(get_db)):
    secret = (settings.STRIPE_CONNECT_WEBHOOK_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Sol webhook not configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="invalid signature")

    event = dict(event)
    if event.get("type") not in stripe_webhooks.HANDLED_TYPES:
        return {"received": True, "ignored": True}

    event_id = event.get("id")
    if not _claim(db, event_id, event.get("type")):
        return {"received": True, "duplicate": True}
    try:
        result = stripe_webhooks.handle_event(db, event)
    except Exception:
        _release(db, event_id)  # let Stripe retry a failed handler
        raise HTTPException(status_code=500, detail="handler error")
    return {"received": True, **result}
