"""Sol v1 observability — health snapshot + Prometheus metrics.

Read-only. Two views over the same live data:
  - health(): a JSON snapshot for the operator — DB liveness, the scheduler
    statuses (reminders + supervisor: enabled/running/hour), and cheap row counts.
    Tells you "is Sol's subsystem healthy and are its daily jobs armed?"
  - prometheus_metrics(): the same counts in Prometheus text-exposition format so
    the operator can scrape Sol into Grafana/Prometheus without a new dependency.

NON-CUSTODIAL: counts + liveness only; no money, no writes.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolGroup, SolMembership, SolPayment
from app.services.sol_v1 import admin_metrics


def _count(db: Session, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def health(db: Session) -> dict:
    """Liveness + scheduler arm-state + row counts."""
    from app.services.sol_v1 import reminder_scheduler, supervisor_scheduler

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "schedulers": {
            "reminders": reminder_scheduler.status(),
            "supervisor": supervisor_scheduler.status(),
        },
        "counts": {
            "groups": _count(db, SolGroup) if db_ok else 0,
            "memberships": _count(db, SolMembership) if db_ok else 0,
            "cycles": _count(db, SolCycle) if db_ok else 0,
            "payments": _count(db, SolPayment) if db_ok else 0,
        },
    }


def _metric(name: str, value, labels: str = "") -> str:
    return f"sol_{name}{labels} {value}"


def prometheus_metrics(db: Session, today: date) -> str:
    """The Sol counters in Prometheus text-exposition format (v0.0.4).

    Reuses admin_metrics.overview so the numbers are identical to the dashboard.
    Payment amounts are RECORDED (members pay each other directly); Sol moves none.
    """
    ov = admin_metrics.overview(db, today)
    lines: list[str] = []

    lines.append("# HELP sol_groups Circles by status.")
    lines.append("# TYPE sol_groups gauge")
    for status in ("open", "locked", "complete"):
        lines.append(_metric("groups", ov["groups"][status], f'{{status="{status}"}}'))

    lines.append("# HELP sol_payments Recorded member payments by status.")
    lines.append("# TYPE sol_payments gauge")
    for status in ("pending", "marked", "confirmed", "disputed", "late"):
        lines.append(_metric("payments", ov["payments"][status], f'{{status="{status}"}}'))

    lines.append("# HELP sol_members_total Total circle memberships.")
    lines.append("# TYPE sol_members_total gauge")
    lines.append(_metric("members_total", ov["members_total"]))

    lines.append("# HELP sol_attention Payments needing operator attention.")
    lines.append("# TYPE sol_attention gauge")
    for kind in ("overdue", "unconfirmed", "disputed"):
        lines.append(_metric("attention", ov["attention"][kind], f'{{kind="{kind}"}}'))

    lines.append("# HELP sol_recorded_confirmed_volume Recorded confirmed contribution volume (members paid directly).")
    lines.append("# TYPE sol_recorded_confirmed_volume gauge")
    lines.append(_metric("recorded_confirmed_volume", ov["recorded_confirmed_volume"]))

    return "\n".join(lines) + "\n"
