"""Sol v1 reputation — a 0-100 trust score from a member's PAYER history.

A member is scored on whether they pay their share, and on time. Receiving (as
payee) is neutral. The score is derived on demand from sol_payments — there is
no stored reputation, so it's always fresh and there's nothing to invalidate.

Categories (per payment the member owes):
  on_time    confirmed, and marked paid on/before the due date  → full credit
  late_paid  confirmed, but marked paid after the due date       → partial credit
  overdue    still unpaid (pending/late) past its due date        → no credit
  disputed   payee contests receipt                               → no credit
  in_flight  not yet due, or marked-and-awaiting-confirm          → excluded
  waived     organizer wrote the obligation off (a forgiven dispute) → excluded

score = 100 * (on_time + 0.6·late_paid) / (on_time + late_paid + overdue + disputed)

NON-CUSTODIAL: pure bookkeeping over recorded payments; no money involved. The
scoring + classification are pure functions (unit-tested); the rest is queries.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolMembership, SolPayment

WEIGHTS = {"on_time": 1.0, "late_paid": 0.6, "overdue": 0.0, "disputed": 0.0}
# below this many actionable payments, the score is a weak signal
PROVISIONAL_BELOW = 3

CATEGORIES = ("on_time", "late_paid", "overdue", "disputed", "in_flight", "waived")
# categories that count toward the denominator (a resolved-or-actionable outcome).
# 'waived' and 'in_flight' are EXCLUDED — a forgiven write-off is neutral, exactly
# like a not-yet-due payment: it neither credits nor penalizes the payer.
_ACTIONABLE = ("on_time", "late_paid", "overdue", "disputed")


# ── pure ──────────────────────────────────────────────────────────────────────


def classify_payment(
    *, status: str, due_date: date, today: date, marked_on: date | None, ever_disputed: bool = False
) -> str:
    """Bucket one owed payment into a reputation category.

    Anti-gaming (the score exists to flag bad actors, so a member can't move
    their own bad history out of it):
      - A payment that was EVER disputed is sticky: if it's resolved (now
        'confirmed') it earns only PARTIAL credit; otherwise it stays 'disputed'
        (no credit) — a payer can't re-mark away the payee's non-receipt signal.
      - An unconfirmed self-claim ('marked') past its due date earns NO credit
        until the payee actually confirms — otherwise a delinquent could mark an
        overdue payment and make it vanish from the denominator.
      - A 'waived' payment is NEUTRAL and short-circuits FIRST: the organizer
        deliberately wrote it off, so it drops out of the score entirely (it is
        not a payer signal). Checked before `ever_disputed` because a waived
        payment was disputed, and we must not let the sticky dispute re-penalize
        a debt the organizer already forgave.
    """
    if status == "waived":
        return "waived"
    if ever_disputed:
        return "late_paid" if status == "confirmed" else "disputed"
    if status == "confirmed":
        if marked_on is not None and marked_on > due_date:
            return "late_paid"
        return "on_time"
    if status == "disputed":
        return "disputed"
    if status == "marked":
        # not yet due → neutral; past due + still unconfirmed → counts as overdue
        return "in_flight" if due_date >= today else "overdue"
    # pending / late
    if due_date < today:
        return "overdue"
    return "in_flight"


def _label(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 40:
        return "fair"
    return "poor"


def score_from_counts(counts: dict[str, int]) -> dict:
    """Turn category counts into {score, label, actionable, provisional, breakdown}.

    Returns score=None ('unrated') when the member has no actionable history yet.
    """
    breakdown = {c: int(counts.get(c, 0)) for c in CATEGORIES}
    actionable = sum(breakdown[c] for c in _ACTIONABLE)
    if actionable == 0:
        return {
            "score": None, "label": "unrated", "actionable": 0,
            "provisional": True, "breakdown": breakdown,
        }
    earned = sum(WEIGHTS[c] * breakdown[c] for c in WEIGHTS)
    score = round(100 * earned / actionable)
    return {
        "score": score, "label": _label(score), "actionable": actionable,
        "provisional": actionable < PROVISIONAL_BELOW, "breakdown": breakdown,
    }


# ── DB ────────────────────────────────────────────────────────────────────────


def compute_reputation(
    db: Session, *, user_id: UUID, today: date, group_id: UUID | None = None
) -> dict:
    """Reputation for a member, globally or scoped to a single group.

    group_id=None → the member's whole payer history (their own view).
    group_id set  → only this group's payments (the in-circle trust signal,
                    so co-members never see cross-group behavior).
    """
    stmt = (
        select(
            SolPayment.status,
            SolCycle.due_date,
            SolPayment.payer_marked_at,
            SolPayment.disputed_at,
        )
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(SolPayment.payer_id == user_id)
    )
    if group_id is not None:
        stmt = stmt.where(SolCycle.group_id == group_id)

    counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for status, due_date, marked_at, disputed_at in db.execute(stmt).all():
        marked_on = marked_at.date() if marked_at is not None else None
        cat = classify_payment(
            status=status, due_date=due_date, today=today,
            marked_on=marked_on, ever_disputed=disputed_at is not None,
        )
        counts[cat] += 1
    result = score_from_counts(counts)
    result["user_id"] = user_id
    return result


def group_reputations(db: Session, *, group_id: UUID, today: date) -> list[dict]:
    """Within-group reputation for every member of the group (for co-members)."""
    members = db.scalars(
        select(SolMembership).where(SolMembership.group_id == group_id)
    ).all()
    return [
        compute_reputation(db, user_id=m.user_id, today=today, group_id=group_id)
        for m in members
    ]
