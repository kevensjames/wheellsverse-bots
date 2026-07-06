"""Sol v1 reminders — due/overdue scanning for the manual ledger.

Two consumers:
  1. A daily scheduler (reminder_scheduler.py) that flips overdue pending
     payments to 'late' and pushes an operator digest to Telegram.
  2. GET /sol/v1/reminders, which returns a member's own upcoming/overdue
     obligations (as payer) and incoming items (as payee).

NON-CUSTODIAL: this only reads/labels recorded payments and nudges people; it
never touches money. `classify_due` and `build_operator_digest` are pure
(testable offline); the scan/update helpers are thin DB queries.
"""
from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.sol import SolCycle, SolPayment

logger = logging.getLogger(__name__)

# statuses that still represent an open obligation (not confirmed)
OPEN_STATUSES = ("pending", "late", "marked", "disputed")
# statuses that mean "payer still owes" (drives overdue → late + payer nudges)
UNPAID_STATUSES = ("pending", "late")


# ── pure ──────────────────────────────────────────────────────────────────────


def classify_due(due_date: date, today: date, upcoming_within_days: int = 7) -> str:
    """Bucket a due date relative to today."""
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "due_today"
    if (due_date - today).days <= upcoming_within_days:
        return "upcoming"
    return "scheduled"


def build_operator_digest(*, marked_late: int, summary: dict[str, int]) -> str:
    """One Telegram-friendly line-set summarizing the day's Sol obligations."""
    lines = ["🟡 <b>Sol reminders</b>"]
    if marked_late:
        lines.append(f"• {marked_late} payment(s) flipped to <b>late</b>")
    disputed = summary.get("disputed", 0)
    if disputed:
        lines.append(f"• ⚠️ <b>{disputed}</b> disputed — needs attention")
    lines.append(f"• overdue (unpaid): <b>{summary.get('overdue', 0)}</b>")
    lines.append(f"• due today: <b>{summary.get('due_today', 0)}</b>")
    lines.append(f"• upcoming: <b>{summary.get('upcoming', 0)}</b>")
    lines.append(f"• awaiting confirmation: <b>{summary.get('awaiting_confirmation', 0)}</b>")
    return "\n".join(lines)


# ── DB ────────────────────────────────────────────────────────────────────────


def mark_overdue_late(db: Session, today: date) -> int:
    """Flip every still-'pending' payment whose cycle is past due to 'late'.

    One atomic UPDATE (no TOCTOU). Returns the number of rows changed.
    """
    overdue_cycles = select(SolCycle.id).where(
        SolCycle.due_date < today, SolCycle.status == "active"
    )
    stmt = (
        update(SolPayment)
        .where(
            SolPayment.status == "pending",
            SolPayment.cycle_id.in_(overdue_cycles),
        )
        .values(status="late")
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def scan_summary(db: Session, today: date, upcoming_within_days: int = 3) -> dict[str, int]:
    """Aggregate counts across ALL active obligations, for the operator digest."""
    rows = db.execute(
        select(SolPayment.status, SolCycle.due_date)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(SolPayment.status.in_(OPEN_STATUSES))
    ).all()

    summary = {
        "overdue": 0, "due_today": 0, "upcoming": 0,
        "awaiting_confirmation": 0, "disputed": 0,
    }
    for status, due in rows:
        if status == "marked":
            summary["awaiting_confirmation"] += 1
            continue
        if status == "disputed":
            # action-requiring: a dispute strands the cycle until resolved, so it
            # must surface to the operator (not a due-date bucket).
            summary["disputed"] += 1
            continue
        if status not in UNPAID_STATUSES:
            continue
        kind = classify_due(due, today, upcoming_within_days)
        if kind in summary:
            summary[kind] += 1
    return summary


def member_reminders(
    db: Session, *, user_id: UUID, today: date, upcoming_within_days: int = 7
) -> dict[str, list[dict]]:
    """A member's own open items: what they owe (as payer) + incoming (as payee).

    Each item carries the counterparty, amount, due date, status, and a due
    bucket ('overdue'/'due_today'/'upcoming'/'scheduled') so the UI can sort +
    badge without re-deriving dates.
    """
    rows = db.execute(
        select(SolPayment, SolCycle.due_date)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(
            SolPayment.status.in_(OPEN_STATUSES),
            (SolPayment.payer_id == user_id) | (SolPayment.payee_id == user_id),
        )
        .order_by(SolCycle.due_date)
    ).all()

    as_payer: list[dict] = []
    as_payee: list[dict] = []
    for payment, due in rows:
        item = {
            "payment_id": payment.id,
            "cycle_id": payment.cycle_id,
            "amount": payment.amount,
            "status": payment.status,
            "due_date": due,
            "kind": classify_due(due, today, upcoming_within_days),
        }
        if payment.payer_id == user_id:
            as_payer.append({**item, "counterparty_id": payment.payee_id, "role": "payer"})
        if payment.payee_id == user_id:
            as_payee.append({**item, "counterparty_id": payment.payer_id, "role": "payee"})
    return {"as_payer": as_payer, "as_payee": as_payee}


def run_reminder_cycle(db: Session, today: date) -> dict:
    """One scheduler pass: mark overdue as late, escalate delinquents to their
    organizers (grace-aware, Stage 24), then summarize. Returns the counts + the
    built digest text (caller decides whether to deliver)."""
    marked_late = mark_overdue_late(db, today)
    # Late-policy escalation is fully fail-soft — it must never break the scan.
    try:
        from app.services.sol_v1 import delinquency
        delinquent_alerts = delinquency.notify_organizer_delinquencies(db, today)
    except Exception as e:  # noqa: BLE001 — a broken escalation can't stop reminders
        # roll back so a failed read on the shared session can't leave it in a
        # pending-rollback state and blow up the scan_summary() call right below.
        db.rollback()
        logger.warning("sol reminders: delinquency escalation failed: %s", e)
        delinquent_alerts = 0
    summary = scan_summary(db, today)
    return {
        "marked_late": marked_late,
        "delinquent_alerts": delinquent_alerts,
        "summary": summary,
        "digest": build_operator_digest(marked_late=marked_late, summary=summary),
    }
