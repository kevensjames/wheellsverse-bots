"""Sol v1 supervisor — read-only integrity + health monitor.

The SOLCIRCLE spec asked for an "AI Supervisor that never sleeps" which auto-fixes
things. On money-adjacent data that is exactly the wrong shape. This is the safe
version: a READ-ONLY monitor that (a) checks structural invariants the ledger
state machine should NEVER violate — a non-zero count means a bug or data
corruption — and (b) summarizes operational health. It NEVER mutates anything;
the operator sees the report and decides. No auto-fix, no money, no writes.

Two batteries:
  - integrity_violations: invariants that must always be empty. Any hit is a
    defect/corruption to investigate (e.g. a 'complete' cycle with an unconfirmed
    payment means the completion logic or a manual edit broke).
  - health: operational counts (overdue / unconfirmed / stuck disputes) — not
    bugs, just attention. Overlaps the dashboard, but here it's scheduled + alerted.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.sol import (
    SolCycle,
    SolGroup,
    SolMembership,
    SolPayment,
    SolStripeAccount,
    SolStripePayment,
)

_UNPAID = ("pending", "late")


def _sample(db: Session, id_col, *wheres, sample: int = 5, join=None) -> list[str]:
    """Up to sample+1 offending ids for a violation query (has_more = >sample)."""
    stmt = select(id_col)
    if join is not None:
        stmt = stmt.select_from(join)
    for w in wheres:
        stmt = stmt.where(w)
    stmt = stmt.distinct().limit(sample + 1)
    return [str(r[0]) for r in db.execute(stmt).all()]


def _violation(key: str, description: str, ids: list[str], sample: int) -> dict | None:
    if not ids:
        return None
    return {
        "check": key,
        "description": description,
        "sample_ids": ids[:sample],
        "has_more": len(ids) > sample,
    }


def integrity_violations(db: Session, *, sample: int = 5) -> list[dict]:
    """Structural invariants that must ALWAYS be empty. Any result is a defect."""
    findings: list[dict] = []

    # 1. A 'complete' cycle with a payment that is neither confirmed NOR disputed.
    #    A post-completion Stripe refund/chargeback legitimately flips a payment to
    #    'disputed' WITHOUT reverting the completed cycle (see stripe_webhooks
    #    ._on_charge_reversal) — that's a handled business event, surfaced under
    #    health.stuck_disputes, NOT corruption. But 'pending'/'marked'/'late' on a
    #    complete cycle is a real completion-logic bug.
    ids = _sample(
        db, SolCycle.id,
        SolCycle.status == "complete",
        SolPayment.status.notin_(("confirmed", "disputed")),
        sample=sample,
        join=SolCycle.__table__.join(SolPayment, SolPayment.cycle_id == SolCycle.id),
    )
    findings.append(_violation("completed_cycle_unconfirmed_payment",
        "cycle is 'complete' but has a pending/marked/late payment", ids, sample))

    # 2. A 'complete' group with a non-complete cycle.
    ids = _sample(
        db, SolGroup.id,
        SolGroup.status == "complete",
        SolCycle.status != "complete",
        sample=sample,
        join=SolGroup.__table__.join(SolCycle, SolCycle.group_id == SolGroup.id),
    )
    findings.append(_violation("completed_group_open_cycle",
        "group is 'complete' but has a non-complete cycle", ids, sample))

    # 3. An 'active' cycle with zero materialized payments.
    ids = _sample(
        db, SolCycle.id,
        SolCycle.status == "active",
        ~exists().where(SolPayment.cycle_id == SolCycle.id),
        sample=sample,
    )
    findings.append(_violation("active_cycle_no_payments",
        "cycle is 'active' but has no payment rows", ids, sample))

    # 4. A 'locked' group with zero cycles (calendar never generated).
    ids = _sample(
        db, SolGroup.id,
        SolGroup.status == "locked",
        ~exists().where(SolCycle.group_id == SolGroup.id),
        sample=sample,
    )
    findings.append(_violation("locked_group_no_cycles",
        "group is 'locked' but has no cycles", ids, sample))

    # 5. A 'confirmed' payment missing its confirmation timestamp.
    ids = _sample(
        db, SolPayment.id,
        SolPayment.status == "confirmed",
        SolPayment.payee_confirmed_at.is_(None),
        sample=sample,
    )
    findings.append(_violation("confirmed_without_timestamp",
        "payment is 'confirmed' but payee_confirmed_at is NULL", ids, sample))

    # 6. A 'disputed' payment missing the sticky disputed_at (anti-gaming invariant).
    ids = _sample(
        db, SolPayment.id,
        SolPayment.status == "disputed",
        SolPayment.disputed_at.is_(None),
        sample=sample,
    )
    findings.append(_violation("disputed_without_timestamp",
        "payment is 'disputed' but disputed_at is NULL", ids, sample))

    # 7. A cycle whose recipient membership belongs to a DIFFERENT group.
    ids = _sample(
        db, SolCycle.id,
        SolMembership.group_id != SolCycle.group_id,
        sample=sample,
        join=SolCycle.__table__.join(
            SolMembership, SolMembership.id == SolCycle.recipient_membership_id
        ),
    )
    findings.append(_violation("cycle_recipient_wrong_group",
        "cycle recipient membership is in a different group", ids, sample))

    # 8. Two members sharing a payout position in the same group.
    dup = (
        select(SolMembership.group_id)
        .where(SolMembership.payout_position.is_not(None))
        .group_by(SolMembership.group_id, SolMembership.payout_position)
        .having(func.count() > 1)
        .limit(sample + 1)
    )
    ids = [str(r[0]) for r in db.execute(dup).all()]
    findings.append(_violation("duplicate_payout_position",
        "two members share a payout position in one group", ids, sample))

    # 9. NON-CUSTODIAL invariant: a Stripe payment whose destination is NOT the
    #    PAYEE's OWN connected account. Missing/empty destination, a payee with no
    #    connected account, or a destination pointing anywhere else (e.g. Sol's
    #    platform account) would make the charge custodial. This checks the actual
    #    custody property, not mere presence.
    ids = _sample(
        db, SolStripePayment.id,
        (SolStripePayment.destination_account_id.is_(None))
        | (func.trim(SolStripePayment.destination_account_id) == "")
        | (SolStripeAccount.stripe_account_id.is_(None))
        | (SolStripePayment.destination_account_id != SolStripeAccount.stripe_account_id),
        sample=sample,
        join=SolStripePayment.__table__
            .join(SolPayment, SolPayment.id == SolStripePayment.payment_id)
            .outerjoin(SolStripeAccount, SolStripeAccount.user_id == SolPayment.payee_id),
    )
    findings.append(_violation("stripe_payment_wrong_destination",
        "Stripe payment destination is not the payee's own connected account (custody risk)",
        ids, sample))

    return [f for f in findings if f is not None]


def health(db: Session, today: date, *, stuck_dispute_days: int = 7) -> dict:
    """Operational counts — not bugs, just attention (scheduled + alerted)."""
    overdue = int(
        db.scalar(
            select(func.count(SolPayment.id))
            .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
            .where(SolPayment.status.in_(_UNPAID), SolCycle.due_date < today)
        ) or 0
    )
    unconfirmed = int(
        db.scalar(
            select(func.count(SolPayment.id))
            .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
            .where(SolPayment.status == "marked", SolCycle.due_date < today)
        ) or 0
    )
    # UTC-anchor the cutoff: disputed_at is timestamptz, so comparing it to a bare
    # date would cast at the DB SESSION timezone's midnight (off-by-up-to-a-day at
    # the boundary). Pin the boundary to 00:00 UTC to match the module's discipline.
    cutoff = datetime.combine(
        today - timedelta(days=stuck_dispute_days), time.min, tzinfo=timezone.utc
    )
    stuck_disputes = int(
        db.scalar(
            select(func.count(SolPayment.id)).where(
                SolPayment.status == "disputed",
                SolPayment.disputed_at < cutoff,
            )
        ) or 0
    )
    return {"overdue": overdue, "unconfirmed": unconfirmed, "stuck_disputes": stuck_disputes}


def run_checks(db: Session, today: date, *, sample: int = 5, stuck_dispute_days: int = 7) -> dict:
    """The full supervisor pass: integrity invariants + operational health.
    `ok` is True iff there are NO integrity violations (health issues don't flip
    it — they're informational)."""
    violations = integrity_violations(db, sample=sample)
    h = health(db, today, stuck_dispute_days=stuck_dispute_days)
    return {
        "ok": len(violations) == 0,
        "integrity_violations": violations,
        "health": h,
        "checked_at": today.isoformat(),
    }


def build_alert(report: dict) -> str:
    """A Telegram-friendly summary — only worth sending when there's something."""
    lines = ["🛰️ <b>Sol supervisor</b>"]
    v = report["integrity_violations"]
    if v:
        lines.append(f"🔴 <b>{len(v)} integrity violation(s)</b> — investigate:")
        for f in v:
            more = "+" if f["has_more"] else ""
            lines.append(f"• {f['check']}: {len(f['sample_ids'])}{more} (e.g. {f['sample_ids'][0]})")
    else:
        lines.append("🟢 integrity: all invariants hold")
    h = report["health"]
    lines.append(
        f"• health — overdue: <b>{h['overdue']}</b>, awaiting confirm: "
        f"<b>{h['unconfirmed']}</b>, stuck disputes: <b>{h['stuck_disputes']}</b>"
    )
    return "\n".join(lines)


def is_noteworthy(report: dict) -> bool:
    """Whether the daily scheduler should actually alert the operator."""
    if not report["ok"]:
        return True
    h = report["health"]
    return bool(h["overdue"] or h["unconfirmed"] or h["stuck_disputes"])
