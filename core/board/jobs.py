"""The board's scheduled jobs (replica/architecture.md, Jobs), started by
start_board_scheduler() in narai/integrations/scheduler.py on New York time.
Plain def: APScheduler runs them in a worker thread, off the event loop.

  sync_stripe      every hour at :07, and after each verified Stripe event
  morning_report   07:00 (BOARD_REPORT_CRON): a Stripe sync (60 s at most; while
                   Stripe has no completed sync yet, up to 15 minutes for that
                   first backfill, in this run or another, unless a sync fails),
                   then yesterday's message to each configured channel. Each channel is
                   claimed once per day, board_claim_run('morning_report',
                   'YYYY-MM-DD:channel'), so it is sent once, even when two
                   containers run the job during a deploy. A failed send is
                   marked failed, and only a failed or unclaimed channel can be
                   claimed again.
  catch_up         once at startup: if today's report time has passed and it is
                   before noon in New York, the same job. The claim makes it a
                   no-op when the day was sent already, so a deploy around 07:00
                   still yields exactly one message.

Telegram is the one channel so far (core/telegram.py notify, HTML).
"""
from __future__ import annotations

import logging
import threading
import time as clock
from datetime import datetime, time, timezone
from typing import Callable, Optional

from core.board import day as board_day
from core.board import ledger
from core.board.connectors import stripe_sync
from core.board.ledger import BoardDBError

log = logging.getLogger("board.jobs")

REPORT_JOB = "morning_report"
SYNC_BUDGET = 60.0          # seconds the report waits for its sync
FIRST_SYNC_WAIT = 900.0     # seconds it waits for Stripe's first sync, a backfill
NOON = time(12, 0)          # the catch-up gives up at noon, New York time
_POLL = 10.0                # seconds between two looks at the source while it waits
_sleep = clock.sleep        # tests replace it


def _telegram_ready() -> bool:
    from core.telegram import get_notifier
    return get_notifier().is_connected()


def _telegram_send(text: str) -> bool:
    from core.telegram import notify
    return bool(notify(text))


# channel name -> (is it configured, send the HTML text and say whether it went out)
CHANNELS: dict[str, tuple[Callable[[], bool], Callable[[str], bool]]] = {
    "telegram": (_telegram_ready, _telegram_send),
}


def sync_stripe(trigger: str = "schedule") -> dict:
    """One Stripe sync run (it records its own failures); never raises."""
    try:
        return stripe_sync.run(trigger=trigger)
    except Exception:  # noqa: BLE001 — a scheduled job must not die
        log.exception("stripe sync job failed")
        return {"status": "failed"}


def _sync_within(budget: float, trigger: str) -> None:
    """Run a Stripe sync and wait for it at most `budget` seconds. A slow sync
    carries on in its thread; the report says how far the data got."""
    worker = threading.Thread(target=sync_stripe, kwargs={"trigger": trigger},
                              name="board-report-sync", daemon=True)
    worker.start()
    worker.join(budget)


def _first_sync_pending(since: Optional[datetime] = None) -> bool:
    """Whether Stripe has a live key but no completed sync yet (so its first
    sync, a backfill from BOARD_BACKFILL_FROM with one Checkout lookup per
    sale, is still to finish) and no sync has failed since `since`."""
    found = stripe_sync.read_key()
    if found is None or stripe_sync.is_test_key(found[0]):
        return False
    try:
        src = ledger.source_row(stripe_sync.SOURCE_ID)
    except BoardDBError:
        return False
    if not src or src.get("enabled") is False or src.get("measured_from"):
        return False
    failed_at = ledger.parse_ts(src.get("last_error_at"))
    return not (since is not None and failed_at is not None and failed_at >= since)


def _wait_for_first_sync(since: datetime, limit: float = FIRST_SYNC_WAIT) -> None:
    """Wait, at most `limit` seconds, while Stripe's first sync runs (in the
    report's thread, or a run started elsewhere), so the first message after a
    deploy has numbers rather than "not connected". A failed sync ends the
    wait: the message then says what failed."""
    deadline = clock.monotonic() + limit
    while clock.monotonic() < deadline and _first_sync_pending(since):
        _sleep(_POLL)


def _ready_channels() -> dict[str, Callable[[str], bool]]:
    ready = {}
    for name, (is_ready, send) in CHANNELS.items():
        try:
            if is_ready():
                ready[name] = send
        except Exception:  # noqa: BLE001
            log.exception("morning report: cannot tell whether %s is configured", name)
    return ready


def morning_report(trigger: str = "schedule", sync_budget: float = SYNC_BUDGET) -> dict:
    """Yesterday's message to every configured channel, each sent at most once."""
    channels = _ready_channels()
    if not channels:
        log.info("morning report: no channel configured (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
        return {"status": "skipped", "channels": {}}
    if sync_budget > 0:
        started = datetime.now(timezone.utc)
        first = _first_sync_pending()
        _sync_within(sync_budget, trigger)
        if first:
            _wait_for_first_sync(started)
    view = board_day.day_view(None)          # yesterday in New York, decided in SQL
    text = board_day.render_report(view)
    results: dict[str, str] = {}
    for name, send in channels.items():
        try:
            run_id = ledger.claim_run(REPORT_JOB, f"{view['day']}:{name}", trigger)
        except BoardDBError as e:
            log.warning("morning report: cannot claim %s for %s (%s); not sent", name, view["day"], e)
            results[name] = "not claimed"
            continue
        if run_id is None:
            results[name] = "sent already or sending"
            continue
        error = None
        try:
            sent = send(text)
            if not sent:
                error = f"{name} did not accept the message"
        except Exception as e:  # noqa: BLE001
            sent, error = False, f"{name} send failed ({type(e).__name__})"
        try:
            ledger.finish_run(run_id, "ok" if sent else "failed", error=error,
                              detail={"day": view["day"], "channel": name, "chars": len(text)})
        except BoardDBError as e:
            log.warning("morning report: could not record the %s send (%s)", name, e)
        results[name] = "sent" if sent else "failed"
        log.info("morning report %s %s: %s", view["day"], name, results[name])
    return {"status": "done", "day": view["day"], "channels": results}


def catch_up(report_trigger, now: Optional[datetime] = None) -> dict:
    """At startup: run the morning report if today's report time has passed and
    it is not yet noon in New York. `report_trigger` is the report's cron
    trigger (anything with get_next_fire_time(previous, now))."""
    now = (now or datetime.now(timezone.utc)).astimezone(board_day.NY)
    if now.time() >= NOON:
        return {"status": "skipped", "reason": "after noon in New York"}
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first = report_trigger.get_next_fire_time(None, midnight)
    if first is None or first > now:
        return {"status": "skipped", "reason": "before today's report time"}
    return morning_report(trigger="startup")
