from __future__ import annotations
import logging, os, threading
from datetime import datetime, timezone
from . import store, kpis, brain, executor, floor

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop: threading.Event | None = None
_POLL = 300  # seconds


def _dry_default() -> bool:
    v = (os.environ.get("KAI_CEO_DRY_RUN", "1") or "1").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _scope_on() -> bool:
    from app.services.governance import is_scope_enabled
    return is_scope_enabled("ceo")


def run_cycle(*, router, user_id, dry_run: bool | None = None) -> dict:
    if not _scope_on():
        return {"ran": False, "reason": "scope KAI_SCOPE_CEO not enabled", "result": None}
    if floor.is_killed():
        return {"ran": False, "reason": "kill switch active (KAI_CEO_KILLED)", "result": None}
    company = store.get_company()
    if not company:
        return {"ran": False, "reason": "no company goal set", "result": None}
    if dry_run is None:
        dry_run = _dry_default()
    snapshot = kpis.build_snapshot()
    ds = brain.decide(router=router, user_id=user_id, company=company,
                      snapshot=snapshot, org=store.list_org())
    result = executor.apply(ds, dry_run=dry_run)
    logger.info("ceo: cycle ran (dry=%s) created=%d decisions=%d",
                dry_run, len(result["created"]), result["decisions"])
    return {"ran": True, "reason": "ok", "result": result}


# ── scheduler (mirrors digest) ─────────────────────────────────
def _enabled() -> bool:
    v = (os.environ.get("KAI_CEO_HEARTBEAT_ENABLED") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _hour() -> int:
    try:
        return int(os.environ.get("KAI_CEO_HEARTBEAT_HOUR_UTC", "14"))
    except ValueError:
        return 14


def _loop(router_factory) -> None:
    last_day: str | None = None
    while _stop is not None and not _stop.is_set():
        now = datetime.now(timezone.utc)
        key = now.strftime("%Y%m%d")
        if now.hour == _hour() and key != last_day and _scope_on() and not floor.is_killed():
            try:
                router, user_id = router_factory()
                run_cycle(router=router, user_id=user_id)
                last_day = key
            except Exception as e:  # pragma: no cover
                logger.exception("ceo: scheduled cycle crashed: %s", e)
        if _stop is not None and _stop.wait(timeout=_POLL):
            break


def start(router_factory=None) -> bool:
    global _thread, _stop
    if not _enabled():
        logger.info("ceo: scheduler not started (KAI_CEO_HEARTBEAT_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        return False
    if router_factory is None:
        logger.info("ceo: no router_factory provided; scheduler idle")
        return False
    _stop = threading.Event()
    _thread = threading.Thread(target=_loop, args=(router_factory,), name="kai-ceo", daemon=True)
    _thread.start()
    logger.info("ceo: scheduler started (hour=%d UTC, dry=%s)", _hour(), _dry_default())
    return True


def stop() -> None:
    global _thread, _stop
    if _stop is not None:
        _stop.set()
    _thread = None
