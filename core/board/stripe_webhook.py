"""Checks for the Stripe webhook receiver (POST /api/stripe/webhook, core/api.py).

  verify  the Stripe-Signature header against STRIPE_WEBHOOK_SECRET. No secret
          configured: 503, so Stripe retries once it is set, and an error in
          the log (at startup, and at most every 10 minutes while refusing).
          A bad, missing or stale signature: 400. An unsigned event is never
          accepted.
  claim   board_claim_webhook on the event id, so the receiver's side effects run
          once per event: 'run' (new, or an earlier delivery failed or was
          abandoned), 'busy' (the same event is running now: answer 409 and Stripe
          retries later) or 'done' (processed already, or a test-mode event,
          stored as ignored: answer 200, nothing runs).
  finish  marks a claimed event processed, or failed (it runs again on retry).

The receiver writes no money. A verified event starts the Stripe sync
(core/board/connectors/stripe_sync.py), which reads the balance transactions.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from starlette.concurrency import run_in_threadpool

from core.board import ledger
from core.board.ledger import BoardDBError

log = logging.getLogger("board.stripe_webhook")

SOURCE_ID = "stripe"
TOLERANCE = 300   # seconds: Stripe's own default for a signature's timestamp
NO_SECRET = ("STRIPE_WEBHOOK_SECRET is not set: every Stripe event is refused with 503, so store "
             "deliveries, tier upgrades and subscription access wait on Stripe's retries (up to 3 days). "
             "Copy the endpoint's signing secret from the Stripe dashboard.")
_LOG_EVERY = 600.0                  # seconds between two log lines about the missing secret
_no_secret_logged: Optional[float] = None


def _secret() -> str:
    return os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()


def check_secret() -> None:
    """Startup: say in the log when the signing secret is missing."""
    if not _secret():
        log.error("stripe webhook: %s", NO_SECRET)


def _log_no_secret() -> None:
    global _no_secret_logged
    now = time.monotonic()
    if _no_secret_logged is None or now - _no_secret_logged >= _LOG_EVERY:
        _no_secret_logged = now
        log.error("stripe webhook: refused an event with 503. %s", NO_SECRET)


class Refused(Exception):
    """A delivery that is not processed. `status` and `message` go back to Stripe."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def verify(payload: bytes, signature: Optional[str]) -> dict:
    """The event, once its signature checks out; Refused otherwise."""
    secret = _secret()
    if not secret:
        _log_no_secret()
        raise Refused(503, "Stripe webhook signing secret is not configured")
    try:
        import stripe
    except ImportError:
        log.error("stripe webhook: the stripe package is missing; cannot verify signatures")
        raise Refused(503, "Stripe signature check unavailable") from None
    try:
        text = payload.decode("utf-8")
        stripe.WebhookSignature.verify_header(text, signature or "", secret, TOLERANCE)
    except Exception:  # noqa: BLE001 — any failure to verify is a refusal
        raise Refused(400, "Invalid Stripe signature") from None
    try:
        event = json.loads(text)
    except ValueError:
        raise Refused(400, "Invalid JSON") from None
    if (not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"].strip()
            or not isinstance(event.get("type"), str) or not event["type"].strip()):
        raise Refused(400, "Not a Stripe event")
    return event


def _claim(event: dict) -> str:
    livemode = event.get("livemode")
    return ledger.claim_webhook(SOURCE_ID, event["id"].strip()[:255], event["type"].strip()[:120],
                                livemode if isinstance(livemode, bool) else None)


async def claim(event: dict) -> str:
    """'run', 'busy' or 'done'. Raises BoardDBError when the event store cannot
    be reached: the receiver then answers 503 and runs nothing."""
    return await run_in_threadpool(_claim, event)


def _finish(event: dict, ok: bool, error: Optional[str]) -> bool:
    try:
        ledger.finish_webhook(SOURCE_ID, event["id"].strip()[:255], ok, error)
        return True
    except BoardDBError as e:
        log.error("stripe webhook: could not mark %s %s (%s)", event.get("id"),
                  "processed" if ok else "failed", e)
        return False


async def finish(event: dict, ok: bool, error: Optional[str] = None) -> bool:
    """Mark the event processed or failed; False when that could not be stored."""
    return await run_in_threadpool(_finish, event, ok, error)


def start_sync() -> None:
    """The Stripe sync, after a verified event (run as a background task)."""
    from core.board.jobs import sync_stripe
    sync_stripe(trigger="webhook")
