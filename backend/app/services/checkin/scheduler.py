"""Daily check-in scheduler — a daemon thread that sends one warm check-in/day.

Mirrors the digest/sol scheduler pattern (60s poll, fire once/day at a UTC hour,
dedup by calendar day, scope-gated, graceful stop). The check-in is a PROACTIVE
Telegram message (KAI reaching out), not a prompt layer.

Delivery is CONFIRMED, not fire-and-forget: a check-in is marked ``sent`` only
after Telegram returns 2xx. A send that fails (network blip, token hiccup, crash
mid-send) leaves the row ``sent=0`` and is redelivered on a later poll with
per-row exponential backoff — so a check-in can no longer be silently lost.

Config (.env):
  KAI_CHECKIN_SCHEDULER_ENABLED=1     start the thread (off by default)
  KAI_CHECKIN_HOUR_UTC=13             hour to send (default 13)
  KAI_SCOPE_CHECKIN=1                 scope gate (re-checked each cycle)
  KAI_CHECKIN_RETRY_BASE_SECONDS=60   backoff base for redelivery
  KAI_CHECKIN_RETRY_CAP_SECONDS=3600  backoff ceiling
  KAI_CHECKIN_RETRY_MAX_AGE_HOURS=24  stop retrying a check-in older than this
  KAI_CHECKIN_RETRY_MAX_ATTEMPTS=12   give up after this many attempts
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _enabled() -> bool:
    return _truthy("KAI_CHECKIN_SCHEDULER_ENABLED")


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_CHECKIN_HOUR_UTC") or "13").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 13
    return max(0, min(h, 23))


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("checkin"))
    except Exception:  # pragma: no cover
        return False


# ── Delivery retry knobs (exponential backoff across scheduler polls) ──────
def _float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _retry_base_seconds() -> float:
    return _float_env("KAI_CHECKIN_RETRY_BASE_SECONDS", 60.0)


def _retry_cap_seconds() -> float:
    return _float_env("KAI_CHECKIN_RETRY_CAP_SECONDS", 3600.0)


def _retry_max_age_hours() -> float:
    return _float_env("KAI_CHECKIN_RETRY_MAX_AGE_HOURS", 24.0)


def _retry_max_attempts() -> int:
    return int(_float_env("KAI_CHECKIN_RETRY_MAX_ATTEMPTS", 12.0))


def _deliver(message: str) -> bool:
    """Send a check-in and REPORT success (True iff Telegram returned 2xx)."""
    from app.services import observability
    return observability.send_sync(
        "🌅 <b>KAI check-in</b>\n" + observability._html_escape(message)
    )


def run_checkin(*, force: bool = False, deliver: bool = True) -> dict[str, Any]:
    """Compose + (optionally) send today's check-in. Idempotent per day unless
    force=True. Delivery is CONFIRMED: the row is marked sent only on a 2xx from
    Telegram; a failed send leaves the row unsent for backed-off retry. Returns
    {sent, already_done, message}."""
    date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        from app.services.checkin import composer, storage
    except Exception as e:  # pragma: no cover
        logger.warning("checkin: import failed (%s)", e)
        return {"sent": False, "already_done": False, "message": "", "error": str(e)}

    if not force and storage.has_checkin(date_key):
        return {"sent": False, "already_done": True, "message": ""}

    message = composer.compose_checkin()
    # CLAIM the day BEFORE sending (UNIQUE date_key). Only the caller that wins the
    # insert sends — so a manual run-now racing the scheduled tick can't double-send.
    rec = storage.record_checkin(date_key, message, sent=False, pending=deliver)
    if rec is None and not force:  # someone else already claimed today
        return {"sent": False, "already_done": True, "message": message}

    if not deliver:
        # Preview / claim-only path — no send, row stays unsent.
        return {"sent": False, "already_done": False, "message": message}

    ok = False
    try:
        ok = _deliver(message)
    except Exception as e:  # pragma: no cover - _deliver already fails soft
        logger.warning("checkin: send raised (%s)", e)
        ok = False
    # Record the attempt: flips sent=1 only on success, else bumps the attempt
    # counter and leaves the row for the retry pass — never a silent loss.
    storage.record_attempt(date_key, success=ok)
    if not ok:
        logger.warning(
            "checkin: delivery FAILED for %s — left unsent for backed-off retry",
            date_key,
        )
    return {"sent": ok, "already_done": False, "message": message}


def _is_due(row: Any, now: datetime, base: float, cap: float) -> bool:
    """An unsent row is due for redelivery when enough time has passed since its
    last attempt: min(base * 2**(attempts-1), cap). Never-attempted rows
    (last_attempt_at is None) are immediately due."""
    if row.last_attempt_at is None:
        return True
    try:
        last = datetime.fromisoformat(row.last_attempt_at)
    except ValueError:  # pragma: no cover - corrupt timestamp → retry now
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    wait = min(base * (2 ** max(0, row.attempts - 1)), cap)
    return (now - last).total_seconds() >= wait


def retry_due_unsent(now: datetime | None = None) -> dict[str, Any]:
    """Redeliver any unsent check-in whose backoff has elapsed. Scope-gated and
    fail-soft. This is the durable complement to run_checkin — a check-in whose
    send failed (or whose process died mid-send) is retried here until it lands
    or ages out."""
    if not _scope_on():
        return {"attempted": 0, "delivered": 0, "skipped": "scope_off"}
    try:
        from app.services.checkin import storage
    except Exception as e:  # pragma: no cover
        logger.warning("checkin: retry import failed (%s)", e)
        return {"attempted": 0, "delivered": 0, "error": str(e)}

    now = now or datetime.now(timezone.utc)
    base, cap = _retry_base_seconds(), _retry_cap_seconds()
    max_age_seconds = _retry_max_age_hours() * 3600
    max_attempts = _retry_max_attempts()

    attempted = delivered = 0
    for row in storage.list_unsent():
        # Skip rows never marked for delivery (last_attempt_at is None) — a
        # deliver=False preview. A crashed real send was claimed with pending=True
        # (last_attempt_at stamped at claim), so it stays retry-eligible even at
        # attempts==0 and is NOT dropped here.
        if row.last_attempt_at is None:
            continue
        # Age out stale check-ins — a check-in two days late is noise, not value.
        if row.created_at:
            try:
                created = datetime.fromisoformat(row.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (now - created).total_seconds() > max_age_seconds:
                    continue
            except ValueError:  # pragma: no cover
                pass
        if row.attempts >= max_attempts:
            continue
        if not _is_due(row, now, base, cap):
            continue
        attempted += 1
        ok = False
        try:
            ok = _deliver(row.message)
        except Exception as e:  # pragma: no cover
            logger.warning("checkin: retry send raised for %s (%s)", row.date_key, e)
        storage.record_attempt(row.date_key, success=ok)
        if ok:
            delivered += 1
            logger.info("checkin: retry DELIVERED %s (attempt %d)",
                        row.date_key, row.attempts + 1)
        elif row.attempts + 1 >= max_attempts:
            # This failing attempt exhausted the retry budget — surface the loss
            # to the operator instead of dropping it silently.
            logger.warning("checkin: %s permanently undelivered after %d attempts — giving up",
                           row.date_key, row.attempts + 1)
            try:
                from app.services import observability
                observability.notify(
                    f"⚠️ <b>KAI check-in undelivered</b>\n{row.date_key}: "
                    f"gave up after {row.attempts + 1} attempts"
                )
            except Exception as ex:  # pragma: no cover
                logger.warning("checkin: give-up alert failed (%s)", ex)
    return {"attempted": attempted, "delivered": delivered}


def _loop() -> None:
    last_day: str | None = None
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_day:
            if _scope_on():
                try:
                    res = run_checkin()
                    last_day = today_key  # claimed for today; retries handle failed sends
                    logger.info("checkin: scheduled (sent=%s already=%s)",
                                res.get("sent"), res.get("already_done"))
                except Exception as e:  # pragma: no cover
                    logger.exception("checkin: scheduled cycle crashed: %s", e)
            else:
                logger.info("checkin: scheduled hour reached but KAI_SCOPE_CHECKIN off — skipping")
        # Durable redelivery of any unsent check-in — runs every poll; backoff is
        # enforced per-row so this is cheap when nothing is due.
        try:
            res = retry_due_unsent(now)
            if res.get("attempted"):
                logger.info("checkin: retry pass (attempted=%s delivered=%s)",
                            res.get("attempted"), res.get("delivered"))
        except Exception as e:  # pragma: no cover
            logger.warning("checkin: retry pass crashed: %s", e)
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break


def start() -> bool:
    global _thread, _stop_event
    if not _enabled():
        logger.info("checkin: scheduler not started (KAI_CHECKIN_SCHEDULER_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-checkin", daemon=True)
    _thread.start()
    logger.info("checkin: scheduler thread started (hour=%d UTC)", _scheduled_hour())
    return True


def stop(timeout: float = 5.0) -> None:
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None
    _stop_event = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def status() -> dict[str, Any]:
    return {"enabled": _enabled(), "running": is_running(),
            "hour_utc": _scheduled_hour(), "scope_on": _scope_on()}
