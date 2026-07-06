"""Sol v1 late policy — grace-aware delinquency detection + organizer escalation.

The existing ledger already flips an overdue 'pending' payment to 'late'. This adds
the POLICY layer on top: a member is *delinquent* once a contribution is unpaid
beyond the circle's configured grace period, and when that happens the ORGANIZER —
the person who can act (nudge, waive, or remove before lock) — is escalated.

Non-custodial: this only READS ledger state and RECORDS a coordination alert. It
moves no money, holds nothing, and never mutates a payment or the rotation. The
classifiers are pure functions (unit-tested); the rest is reads + fail-soft notify.

Deliberately OUT of scope (documented for later): late fees (money-adjacent),
auto-suspension, and mid-circle auto-removal/replacement (that mutates a locked
rotation — a seat-transfer feature with a much larger blast radius).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolGroup, SolPayment
from app.services.sol_v1.lifecycle import SolError

logger = logging.getLogger(__name__)

# unpaid = the payer still owes (drives the delinquency check)
_UNPAID = ("pending", "late")


# ── pure ────────────────────────────────────────────────────────────────────


def days_overdue(due_date: date, today: date) -> int:
    """Whole days a contribution is past its due date (0 if not yet due)."""
    return max(0, (today - due_date).days)


def is_delinquent(*, due_date: date, today: date, grace_days: int) -> bool:
    """True once an unpaid contribution is overdue BEYOND the grace window."""
    return days_overdue(due_date, today) > grace_days


# ── reads ───────────────────────────────────────────────────────────────────


def find_delinquencies(
    db: Session, *, group_id: UUID, actor_id: UUID, today: date
) -> list[dict]:
    """Members of one circle who are delinquent (unpaid past due + grace).

    Organizer-only. Returns one row per delinquent member, worst first:
    {user_id, overdue_count, total_owed, oldest_due_date, max_days_overdue}.
    """
    group = db.get(SolGroup, group_id)
    if group is None:
        raise SolError(404, "group not found")
    if group.organizer_id != actor_id:
        raise SolError(403, "only the organizer can view delinquencies")

    grace = group.grace_period_days
    rows = db.execute(
        select(SolPayment.payer_id, SolPayment.amount, SolCycle.due_date)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(
            SolCycle.group_id == group_id,
            SolCycle.status == "active",
            SolPayment.status.in_(_UNPAID),
        )
    ).all()

    agg: dict[UUID, dict] = {}
    for payer_id, amount, due in rows:
        d = days_overdue(due, today)
        if d <= grace:  # still within grace — not yet delinquent
            continue
        cur = agg.get(payer_id)
        if cur is None:
            agg[payer_id] = {
                "user_id": payer_id, "overdue_count": 1, "total_owed": Decimal(amount),
                "oldest_due_date": due, "max_days_overdue": d,
            }
        else:
            cur["overdue_count"] += 1
            cur["total_owed"] += amount
            cur["oldest_due_date"] = min(cur["oldest_due_date"], due)
            cur["max_days_overdue"] = max(cur["max_days_overdue"], d)

    return sorted(
        agg.values(), key=lambda x: (-x["max_days_overdue"], -x["overdue_count"])
    )


# ── escalation (called by the daily scan; fully fail-soft) ────────────────────


def notify_organizer_delinquencies(db: Session, today: date) -> int:
    """Escalate each circle's delinquent members to its organizer, once per
    delinquency episode (in-app dedup makes a standing episode idempotent).

    Returns the number of delinquent members escalated this pass (non-organizer
    delinquents seen) — NOT the number of NEW in-app rows written, since a
    standing episode is deduped by emit(). Fail-soft: a notification failure
    never breaks the scan."""
    from app.services.sol_v1 import notifications  # local: avoid import cycle

    candidate_gids = db.scalars(
        select(SolCycle.group_id)
        .join(SolPayment, SolPayment.cycle_id == SolCycle.id)
        .where(SolCycle.status == "active", SolPayment.status.in_(_UNPAID))
        .distinct()
    ).all()

    sent = 0
    for gid in candidate_gids:
        group = db.get(SolGroup, gid)
        if group is None:
            continue
        try:
            delinquents = find_delinquencies(
                db, group_id=gid, actor_id=group.organizer_id, today=today
            )
        except SolError:
            continue
        for d in delinquents:
            if d["user_id"] == group.organizer_id:
                continue  # don't escalate the organizer to themselves
            notifications.notify_member_delinquent(
                organizer_id=group.organizer_id, group_id=gid, circle=group.name,
                member_id=d["user_id"], oldest_due=d["oldest_due_date"],
                overdue_count=d["overdue_count"], total=d["total_owed"],
                days=d["max_days_overdue"],
            )
            sent += 1
    return sent
