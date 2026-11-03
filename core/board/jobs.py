"""The board's scheduled jobs (replica/architecture.md, Jobs), started by
start_board_scheduler() in narai/integrations/scheduler.py on New York time.
Plain def: APScheduler runs them in a worker thread, off the event loop.

  sync_hourly      every hour at :07: the Stripe, Kit and Instantly syncs, each
                   in a thread of its own, so one that fails, raises or hangs
                   never stops the others or the scheduler
  sync_stripe      also after each verified Stripe event (the webhook)
  sync_meta        06:30 and 12:30: Meta spend and the account's day zone
  morning_report   07:00 (BOARD_REPORT_CRON): the three hourly syncs, and the
                   Meta sync when Meta has no ok run since 06:00 New York time
                   today, all at once, waiting 60 s at most (while Stripe has
                   no completed sync yet, up to 15 minutes for that first
                   backfill, in this run or another, unless a sync fails),
                   then yesterday's message to each configured channel. Each
                   channel is claimed once per day, board_claim_run(
                   'morning_report', 'YYYY-MM-DD:channel'), so it is sent once,
                   even when two containers run the job during a deploy. A
                   failed send is marked failed, and only a failed or unclaimed
                   channel can be claimed again.
  catch_up         once at startup: if today's report time has passed and it is
                   before noon in New York, the same job. The claim makes it a
                   no-op when the day was sent already, so a deploy around 07:00
                   still yields exactly one message.

Every sync is claimed in job_runs by its connector, so a sync that is still
running when the next one starts answers "busy" and nothing runs twice.

Telegram is the one channel so far (core/telegram.py notify, HTML).
"""
from __future__ import annotations

import logging
import threading
import time as clock
from datetime import datetime, time, timezone
from typing import Callable, Iterable, Optional

from core.board import day as board_day
from core.board import ledger
from core.board.connectors import instantly_sync, kit_sync, meta_sync, stripe_sync
from core.board.ledger import BoardDBError

log = logging.getLogger("board.jobs")

REPORT_JOB = "morning_report"
HOURLY = ("stripe", "kit", "instantly")     # the hourly job's syncs
SYNC_BUDGET = 60.0          # seconds the report waits for its syncs (they run at once)
HOURLY_BUDGET = 3000.0      # seconds the hourly job waits for its syncs: it ends before the next one
FIRST_SYNC_WAIT = 900.0     # seconds it waits for Stripe's first sync, a backfill
META_FRESH_FROM = time(6, 0)  # the report syncs Meta unless Meta has an ok run since then, New York time
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


# ─── the syncs ──────────────────────────────────────────────────────────────

def _run(source: str, connector, trigger: str) -> dict:
    """One connector run. A run records its own failures; this catches what
    escapes it, so a scheduled job never dies. Never raises."""
    try:
        return connector.run(trigger=trigger)
    except Exception:  # noqa: BLE001 — a scheduled job must not die
        log.exception("%s sync job failed", source)
        return {"status": "failed"}


def sync_stripe(trigger: str = "schedule") -> dict:
    """One Stripe sync run (it records its own failures); never raises. After
    an ok run, the monthly revenue goal follows the ledger's last 30 days."""
    out = _run("stripe", stripe_sync, trigger)
    if isinstance(out, dict) and out.get("status") == "ok":
        try:
            from core.revenue import update_revenue_goal
            update_revenue_goal()                   # best effort: never fails the job
        except Exception as e:  # noqa: BLE001
            log.warning("revenue goal not updated (%s)", type(e).__name__)
    return out


def sync_kit(trigger: str = "schedule") -> dict:
    """One Kit sync run (Toodle opt-ins); never raises."""
    return _run("kit", kit_sync, trigger)


def sync_instantly(trigger: str = "schedule") -> dict:
    """One Instantly sync run (SiteBoost replies); never raises."""
    return _run("instantly", instantly_sync, trigger)


def sync_meta(trigger: str = "schedule") -> dict:
    """One Meta sync run (ad spend); never raises. The board_meta job."""
    return _run("meta_ads", meta_sync, trigger)


def _job(source: str) -> Callable[..., dict]:
    """The job body that syncs `source`, looked up when it runs (tests replace them)."""
    return {"stripe": sync_stripe, "kit": sync_kit, "instantly": sync_instantly, "meta_ads": sync_meta}[source]


def _run_syncs(sources: Iterable[str], trigger: str, budget: float) -> dict[str, str]:
    """Run each source's sync in a thread of its own, all at once, and wait
    for them `budget` seconds at most in all. One that fails, raises or hangs
    never holds up the others; one still running after the budget carries on
    in its thread (its claim keeps a second run of it out). Returns each
    sync's status, 'running' for one that has not ended."""
    results: dict[str, str] = {}

    def work(source: str) -> None:
        try:
            out = _job(source)(trigger=trigger)
        except Exception:  # noqa: BLE001 — one sync's failure never stops the others
            log.exception("%s sync job failed", source)
            out = {"status": "failed"}
        results[source] = str((out.get("status") if isinstance(out, dict) else None) or "unknown")

    sources = list(sources)
    workers = [threading.Thread(target=work, args=(s,), name=f"board-sync-{s}", daemon=True) for s in sources]
    deadline = clock.monotonic() + budget
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(max(0.0, deadline - clock.monotonic()))
    return {s: results.get(s, "running") for s in sources}


def sync_hourly(trigger: str = "schedule") -> dict[str, str]:
    """The board_sync_hourly job: the Stripe, Kit and Instantly syncs at once,
    each isolated. Returns each one's status."""
    results = _run_syncs(HOURLY, trigger, HOURLY_BUDGET)
    log.info("board hourly sync: %s", ", ".join(f"{k} {v}" for k, v in results.items()))
    return results


def _meta_due(now: Optional[datetime] = None) -> bool:
    """Whether the report should sync Meta first: Meta is configured and has
    no ok run since 06:00 New York time today (the 06:30 job normally has
    one). When the database cannot say, it is due: the run finds out itself,
    and fails before it reads Meta."""
    if meta_sync.configured() is not None:
        return False
    local = (now or datetime.now(timezone.utc)).astimezone(board_day.NY)
    since = datetime.combine(local.date(), META_FRESH_FROM, tzinfo=board_day.NY)
    try:
        src = ledger.source_row(meta_sync.SOURCE_ID)
    except BoardDBError:
        return True
    last_ok = ledger.parse_ts((src or {}).get("last_ok_at"))
    return last_ok is None or last_ok < since


# ─── the morning report ─────────────────────────────────────────────────────

def _first_sync_pending(since: Optional[datetime] = None) -> bool:
    """Whether Stripe has a live key but no completed sync yet (so its first
    sync, a backfill from BOARD_BACKFILL_FROM with one Checkout lookup per
    sale, is still to finish) and no sync has failed since `since`. A sync is
    complete once the source has both measured_from and its watermark:
    mark_source_ok writes measured_from first, so measured_from alone can be
    a sync half-way through recording itself."""
    found = stripe_sync.read_key()
    if found is None or stripe_sync.is_test_key(found[0]):
        return False
    try:
        src = ledger.source_row(stripe_sync.SOURCE_ID)
    except BoardDBError:
        return False
    if not src or src.get("enabled") is False or (src.get("measured_from") and src.get("synced_through")):
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
        sources = HOURLY + (("meta_ads",) if _meta_due(started) else ())
        synced = _run_syncs(sources, trigger, sync_budget)
        log.info("morning report syncs: %s", ", ".join(f"{k} {v}" for k, v in synced.items()))
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
