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
  retry_mark_processed
          when finish could not store 'processed' for an event whose side
          effects ran, tries again in the background after each wait in
          MARK_RETRY_DELAYS. A row left 'received' counts as abandoned 10
          minutes after its claim (board_claim_webhook, migration 0002), and a
          late duplicate of the event would then run its side effects again.

The receiver writes no money. A verified event starts the Stripe sync
(core/board/connectors/stripe_sync.py), which reads the balance transactions.
"""
from __future__ import annotations

import asyncio
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
# Seconds to wait before each retry of a 'processed' mark that failed. Each wait is longer than
# the one before. Together they come to 5 min 12 s, plus at most 20 s for each try (ledger's
# timeout), so even the last try normally lands inside the 10 minutes after the claim, past
# which board_claim_webhook treats a 'received' row as abandoned.
MARK_RETRY_DELAYS = (2.0, 10.0, 60.0, 240.0)
_sleep = asyncio.sleep              # tests replace it


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


async def retry_mark_processed(event: dict) -> bool:
    """A background task for an event whose side effects ran but whose
    'processed' mark failed: mark it again after each wait in MARK_RETRY_DELAYS
    (asleep without holding a worker thread), until one try is stored. True
    once it is; False, with an error in the log, after the last try. Never
    raises, so the background tasks queued after it still run."""
    event_id = event.get("id")
    for attempt, delay in enumerate(MARK_RETRY_DELAYS, start=1):
        await _sleep(delay)
        try:
            if await finish(event, True):
                log.warning("stripe webhook: marked %s processed on retry %d", event_id, attempt)
                return True
        except Exception as e:  # noqa: BLE001 — a retry that breaks is one more failed try
            log.error("stripe webhook: retry %d to mark %s processed broke (%s)", attempt, event_id,
                      type(e).__name__)
    log.error("stripe webhook: gave up marking %s processed after %d retries. Its row stays 'received', "
              "so a delivery of the same event 10 minutes or more after its claim would run its side "
              "effects again", event_id, len(MARK_RETRY_DELAYS))
    return False


def start_sync() -> None:
    """The Stripe sync, after a verified event (run as a background task)."""
    from core.board.jobs import sync_stripe
    sync_stripe(trigger="webhook")
