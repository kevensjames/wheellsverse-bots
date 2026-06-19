from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from . import store

logger = logging.getLogger(__name__)


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("ceo.kpis: source %s failed: %s", getattr(fn, "__name__", fn), e)
        return default


def _plan_counts() -> tuple[int, int]:
    from app.services.planning import storage
    plans = storage.list_plans(limit=500)
    active = sum(1 for p in plans if p.status in ("approved", "executing"))
    return active, len(plans)


def _revenue() -> float:
    # Placeholder source: revenue aggregation is wired to the real billing
    # surface in a follow-up. Until then returns 0 (fail-soft default), which
    # the brain reads as "no revenue signal yet".
    return 0.0


def _security_score() -> int | None:
    from app.services.security import scoring  # type: ignore
    return scoring.latest_overall()


def _alerts() -> int:
    from app.services.supreme import storage as sup  # type: ignore
    latest = sup.latest_proposal()
    return len((latest or {}).get("findings", []))


def build_snapshot() -> dict[str, Any]:
    active, total = _safe(_plan_counts, (0, 0))
    snap = {
        "revenue": _safe(_revenue, 0.0),
        "spend_period": 0.0,
        "security_score": _safe(_security_score, None),
        "alerts": _safe(_alerts, 0),
        "plans_active": active,
        "plans_total": total,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    store.record_snapshot(snap)
    return snap
