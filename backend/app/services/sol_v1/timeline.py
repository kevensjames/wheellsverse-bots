"""Sol v1 timeline — a member's "what's next" projection.

A READ-ONLY projection over existing rows (memberships + cycles + payments): for
the signed-in member it assembles a single chronological stream of the events
that matter to them —

  contribution   a payment they owe (upcoming / due / overdue / paid / waived …)
  payout         a cycle where they are the recipient (scheduled / incoming / received)
  milestone      a circle they're in has completed

NON-CUSTODIAL: this module never writes and never touches money — it only reads
recorded ledger state and describes it. The status classifiers and label builders
are pure functions (unit-tested offline); the rest is a handful of read queries.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolGroup, SolMembership, SolPayment

# ── pure: event status classifiers ─────────────────────────────────────────────

CONTRIBUTION_STATUSES = (
    "paid", "waived", "disputed", "awaiting_confirmation", "overdue", "due_today", "upcoming",
)
PAYOUT_STATUSES = ("received", "incoming", "awaiting_start", "scheduled")


def contribution_status(*, payment_status: str, due_date: date, today: date) -> str:
    """Bucket one owed contribution into a timeline status. Settled/known states
    win; otherwise it's placed relative to its due date."""
    if payment_status == "confirmed":
        return "paid"
    if payment_status == "waived":
        return "waived"
    if payment_status == "disputed":
        return "disputed"
    if payment_status == "marked":
        return "awaiting_confirmation"
    # pending / late — still owed
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "due_today"
    return "upcoming"


def payout_status(*, cycle_status: str, due_date: date, today: date) -> str:
    """Bucket a cycle the member will receive into a timeline status.

    A cycle only starts collecting when the organizer ACTIVATES it (that's what
    materializes the payment rows), so a still-'pending' cycle is never
    "collecting" — even past its due date it's just awaiting the organizer.
    """
    if cycle_status == "complete":
        return "received"
    if cycle_status == "active":
        return "incoming"
    # pending — not activated, so nothing is collecting yet
    if due_date <= today:
        return "awaiting_start"  # should have started; the organizer hasn't yet
    return "scheduled"


# ── pure: human labels (offline-testable) ──────────────────────────────────────


def _fmt(amount) -> str:
    try:
        return f"${Decimal(str(amount)):.2f}"
    except Exception:
        return f"${amount}"


def contribution_labels(*, status: str, circle: str, amount, due_date: date) -> dict:
    amt, when = _fmt(amount), due_date.isoformat()
    table = {
        "paid": ("Contribution paid", f"You paid {amt} to {circle}."),
        "waived": ("Contribution waived", f"Your {amt} to {circle} was waived by the organizer."),
        "disputed": ("Contribution disputed", f"Your {amt} payment to {circle} is disputed."),
        "awaiting_confirmation": ("Waiting on confirmation", f"You marked {amt} to {circle} paid — waiting on the recipient."),
        "overdue": ("Contribution overdue", f"Your {amt} to {circle} was due {when}. Pay your circle member."),
        "due_today": ("Contribution due today", f"Pay {amt} to {circle} today."),
        "upcoming": ("Contribution due", f"{amt} to {circle} is due {when}."),
    }
    title, detail = table.get(status, ("Contribution", f"{amt} · {circle}"))
    return {"title": title, "detail": detail}


def payout_labels(*, status: str, circle: str, amount, due_date: date) -> dict:
    amt, when = _fmt(amount), due_date.isoformat()
    table = {
        "received": ("Payout received", f"You received about {amt} from {circle}."),
        "incoming": ("Payout incoming", f"Members are paying you about {amt} in {circle} now."),
        "awaiting_start": ("Payout not started", f"Your ~{amt} payout from {circle} isn't collecting yet — the organizer hasn't started this cycle."),
        "scheduled": ("Payout scheduled", f"You're set to receive about {amt} from {circle} on {when}."),
    }
    title, detail = table.get(status, ("Payout", f"~{amt} · {circle}"))
    return {"title": title, "detail": detail}


_MAX_EVENTS = 500  # bound the response; a member's real footprint is far smaller


def _kind_order(kind: str) -> int:
    # within a day, show contributions before payouts before milestones
    return {"contribution": 0, "payout": 1, "milestone": 2}.get(kind, 3)


# ── DB: assemble the member's stream ────────────────────────────────────────────


def build_timeline(db: Session, *, user_id: UUID, today: date) -> dict:
    """The signed-in member's chronological event stream (ascending by date)."""
    memberships = db.execute(
        select(SolMembership.id, SolMembership.group_id).where(SolMembership.user_id == user_id)
    ).all()
    if not memberships:
        return {"as_of": today, "events": []}
    my_membership_ids = {m.id for m in memberships}
    group_ids = {m.group_id for m in memberships}

    groups = {
        g.id: g for g in db.scalars(select(SolGroup).where(SolGroup.id.in_(group_ids))).all()
    }
    counts = dict(
        db.execute(
            select(SolMembership.group_id, func.count(SolMembership.id))
            .where(SolMembership.group_id.in_(group_ids))
            .group_by(SolMembership.group_id)
        ).all()
    )
    cycles = list(db.scalars(select(SolCycle).where(SolCycle.group_id.in_(group_ids))).all())

    events: list[dict] = []

    # contributions the member owes (any status)
    my_payments = db.execute(
        select(
            SolPayment.id, SolPayment.amount, SolPayment.status,
            SolCycle.due_date, SolCycle.cycle_number, SolCycle.group_id,
        )
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(SolPayment.payer_id == user_id)
    ).all()
    for pid, amount, pstatus, due, cyc_no, gid in my_payments:
        g = groups.get(gid)
        if g is None:
            continue
        st = contribution_status(payment_status=pstatus, due_date=due, today=today)
        events.append({
            "date": due, "kind": "contribution", "status": st, "group_id": gid,
            "circle_name": g.name, "amount": amount, "cycle_number": cyc_no, "payment_id": pid,
            **contribution_labels(status=st, circle=g.name, amount=amount, due_date=due),
        })

    # payouts the member will receive (cycles whose recipient membership is theirs)
    for c in cycles:
        if c.recipient_membership_id not in my_membership_ids:
            continue
        g = groups.get(c.group_id)
        if g is None:
            continue
        n_payers = max(counts.get(c.group_id, 1) - 1, 0)  # everyone but the recipient
        total = g.contribution_amount * n_payers
        st = payout_status(cycle_status=c.status, due_date=c.due_date, today=today)
        events.append({
            "date": c.due_date, "kind": "payout", "status": st, "group_id": c.group_id,
            "circle_name": g.name, "amount": total, "cycle_number": c.cycle_number, "payment_id": None,
            **payout_labels(status=st, circle=g.name, amount=total, due_date=c.due_date),
        })

    # milestone: circles the member is in that have completed
    for gid, g in groups.items():
        if g.status != "complete":
            continue
        last = max((c.due_date for c in cycles if c.group_id == gid), default=today)
        events.append({
            "date": last, "kind": "milestone", "status": "completed", "group_id": gid,
            "circle_name": g.name, "amount": None, "cycle_number": None, "payment_id": None,
            "title": f"{g.name} completed",
            "detail": "Every payout has been made — this circle is done.",
        })

    events.sort(key=lambda e: (e["date"], _kind_order(e["kind"])))
    return {"as_of": today, "events": events[:_MAX_EVENTS]}
