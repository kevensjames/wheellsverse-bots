"""Sol v1 admin metrics — read-only operator aggregations over the ledger.

Powers the operator dashboard: portfolio overview, a risk board (overdue +
disputed), dispute review, a groups list + drill-down, and a recent-activity
feed. Every function is a pure read — it NEVER writes, and (per the whole Sol
design) never touches money. `recorded_*` volumes are the sum of RECORDED
amounts members paid each other directly; Sol moved none of it.

Access is enforced at the router (admin-token only); nothing here is member-
reachable.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolGroup, SolMembership, SolPayment, SolPaymentProof
from app.services.sol_v1 import reputation as rep

# statuses a payer still owes on (plainly unpaid)
_UNPAID = ("pending", "late")
# at-risk WHEN PAST DUE: unpaid OR claimed-but-unconfirmed ('marked'). This aligns
# the dashboard with reputation.classify_payment + the operator digest, which both
# treat a past-due 'marked' payment as needing attention — closing the "mark-to-
# vanish" hole where a payer marks paid to disappear from the operator's risk view.
_AT_RISK = ("pending", "late", "marked")
# Hard safety cap on the list endpoints. overview's counts stay EXACT (COUNT()),
# so the operator still sees the true totals even if a list is capped.
_MAX_ROWS = 1000


def _counts_by(db: Session, column) -> dict[str, int]:
    """`{value: count}` for a status-like column (missing values omitted)."""
    return {k: int(v) for k, v in db.execute(select(column, func.count()).group_by(column)).all()}


def _past_due_count(db: Session, today: date, statuses: tuple[str, ...]) -> int:
    """How many payments in `statuses` are past their cycle's due date."""
    return int(
        db.scalar(
            select(func.count(SolPayment.id))
            .select_from(SolPayment)
            .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
            .where(SolPayment.status.in_(statuses), SolCycle.due_date < today)
        )
        or 0
    )


def overview(db: Session, today: date) -> dict:
    """Portfolio snapshot: group/payment/cycle counts, recorded volume, and the
    two attention numbers (overdue + disputed)."""
    groups = _counts_by(db, SolGroup.status)
    payments = _counts_by(db, SolPayment.status)
    cycles = _counts_by(db, SolCycle.status)
    members_total = int(db.scalar(select(func.count()).select_from(SolMembership)) or 0)
    recorded_confirmed = db.scalar(
        select(func.coalesce(func.sum(SolPayment.amount), 0)).where(SolPayment.status == "confirmed")
    ) or Decimal("0")
    return {
        "groups": {
            "open": groups.get("open", 0),
            "locked": groups.get("locked", 0),
            "complete": groups.get("complete", 0),
            "total": sum(groups.values()),
        },
        "members_total": members_total,
        "payments": {
            "pending": payments.get("pending", 0),
            "marked": payments.get("marked", 0),
            "confirmed": payments.get("confirmed", 0),
            "disputed": payments.get("disputed", 0),
            "late": payments.get("late", 0),
            "waived": payments.get("waived", 0),  # Stage 21 terminal status — keep total reconcilable
            "total": sum(payments.values()),
        },
        "cycles": {
            "pending": cycles.get("pending", 0),
            "active": cycles.get("active", 0),
            "complete": cycles.get("complete", 0),
            "total": sum(cycles.values()),
        },
        # RECORDED (members paid each other directly; Sol moved nothing).
        "recorded_confirmed_volume": Decimal(recorded_confirmed),
        "attention": {
            "overdue": _past_due_count(db, today, _UNPAID),
            # past-due but payer-marked & unconfirmed — stale, needs the payee to
            # confirm/dispute (a mark alone must NOT clear the payment from view).
            "unconfirmed": _past_due_count(db, today, ("marked",)),
            "disputed": payments.get("disputed", 0),
        },
    }


def risk_items(db: Session, today: date) -> list[dict]:
    """Payments needing attention: disputed, or unpaid past their due date.
    Disputed first, then oldest-due — so the operator triages top-down."""
    rows = db.execute(
        select(SolPayment, SolCycle.due_date, SolGroup.id, SolGroup.name)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .join(SolGroup, SolCycle.group_id == SolGroup.id)
        .where(
            or_(
                SolPayment.status == "disputed",
                and_(SolPayment.status.in_(_AT_RISK), SolCycle.due_date < today),
            )
        )
        .limit(_MAX_ROWS)
    ).all()

    def _kind(status: str) -> str:
        if status == "disputed":
            return "disputed"
        if status == "marked":
            return "unconfirmed"  # claimed paid, not yet confirmed, and past due
        return "overdue"

    items = [
        {
            "payment_id": p.id,
            "group_id": gid,
            "group_name": gname,
            "payer_id": p.payer_id,
            "payee_id": p.payee_id,
            "amount": p.amount,
            "status": p.status,
            "due_date": due,
            "kind": _kind(p.status),
            "disputed_at": p.disputed_at,
        }
        for p, due, gid, gname in rows
    ]
    # disputed (0) first; the rest (overdue / unconfirmed) by oldest due date
    items.sort(key=lambda i: (0 if i["kind"] == "disputed" else 1, i["due_date"]))
    return items


def disputes(db: Session) -> list[dict]:
    """Every disputed payment with review context (proof count + timestamps)."""
    rows = db.execute(
        select(SolPayment, SolGroup.id, SolGroup.name, func.count(SolPaymentProof.id))
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .join(SolGroup, SolCycle.group_id == SolGroup.id)
        .outerjoin(SolPaymentProof, SolPaymentProof.payment_id == SolPayment.id)
        .where(SolPayment.status == "disputed")
        .group_by(SolPayment.id, SolGroup.id, SolGroup.name)
        .limit(_MAX_ROWS)
    ).all()
    out = [
        {
            "payment_id": p.id,
            "group_id": gid,
            "group_name": gname,
            "payer_id": p.payer_id,
            "payee_id": p.payee_id,
            "amount": p.amount,
            "payer_marked_at": p.payer_marked_at,
            "disputed_at": p.disputed_at,
            "proof_count": int(proofs or 0),
        }
        for p, gid, gname, proofs in rows
    ]
    out.sort(key=lambda d: (d["disputed_at"] is None, d["disputed_at"]), reverse=True)
    return out


def groups(db: Session) -> list[dict]:
    """All circles with a one-line summary (member fill + cycle progress)."""
    members_by_group = dict(
        db.execute(select(SolMembership.group_id, func.count()).group_by(SolMembership.group_id)).all()
    )
    cycles_total = dict(
        db.execute(select(SolCycle.group_id, func.count()).group_by(SolCycle.group_id)).all()
    )
    cycles_done = dict(
        db.execute(
            select(SolCycle.group_id, func.count())
            .where(SolCycle.status == "complete")
            .group_by(SolCycle.group_id)
        ).all()
    )
    rows = db.scalars(
        select(SolGroup).order_by(SolGroup.created_at.desc()).limit(_MAX_ROWS)
    ).all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "status": g.status,
            "organizer_id": g.organizer_id,
            "contribution_amount": g.contribution_amount,
            "frequency": g.frequency,
            "member_count": int(members_by_group.get(g.id, 0)),
            "member_limit": g.member_limit,
            "cycles_complete": int(cycles_done.get(g.id, 0)),
            "cycles_total": int(cycles_total.get(g.id, 0)),
            "created_at": g.created_at,
        }
        for g in rows
    ]


def group_detail(db: Session, *, group_id: UUID, today: date) -> dict:
    """Drill-down: the group + members (with within-group reputation) + cycles +
    payments. Reuses reputation.group_reputations. Returns None-ish via KeyError-
    free path: the router raises 404 when the group is absent."""
    group = db.get(SolGroup, group_id)
    if group is None:
        return {}
    members = list(db.scalars(select(SolMembership).where(SolMembership.group_id == group_id)).all())
    cycles = list(
        db.scalars(
            select(SolCycle).where(SolCycle.group_id == group_id).order_by(SolCycle.cycle_number)
        ).all()
    )
    cycle_ids = [c.id for c in cycles]
    payments = (
        list(
            db.scalars(
                select(SolPayment).where(SolPayment.cycle_id.in_(cycle_ids)).limit(_MAX_ROWS)
            ).all()
        )
        if cycle_ids
        else []
    )
    return {
        "group": group,
        "members": members,
        "cycles": cycles,
        "payments": payments,
        "reputations": rep.group_reputations(db, group_id=group_id, today=today),
    }


def recent_activity(db: Session, limit: int = 50) -> list[dict]:
    """A time-ordered event feed derived from payment timestamps (created /
    marked / confirmed / disputed) — a lightweight audit trail without a
    dedicated log table. `limit` is clamped to [1, 200].

    NOTE: derives events from every payment's timestamps, so cost is O(payments).
    Fine at current scale; revisit with a real event table if volume grows.
    """
    limit = max(1, min(int(limit), 200))
    rows = db.execute(
        select(SolPayment, SolGroup.name)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .join(SolGroup, SolCycle.group_id == SolGroup.id)
    ).all()
    events: list[tuple] = []
    for p, gname in rows:
        for ts, ev in (
            (p.created_at, "created"),
            (p.payer_marked_at, "marked"),
            (p.payee_confirmed_at, "confirmed"),
            (p.disputed_at, "disputed"),
        ):
            if ts is not None:
                events.append((ts, ev, p, gname))
    events.sort(key=lambda e: e[0], reverse=True)
    return [
        {
            "at": ts,
            "event": ev,
            "payment_id": p.id,
            "group_name": gname,
            "amount": p.amount,
            "payer_id": p.payer_id,
            "payee_id": p.payee_id,
        }
        for ts, ev, p, gname in events[:limit]
    ]
