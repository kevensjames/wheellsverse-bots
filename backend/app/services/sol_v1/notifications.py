"""Sol v1 notifications — durable in-app inbox + fail-soft external channels.

Before this, the reminder scan only built an *operator* Telegram digest; a
member was never told anything. This module gives each member a durable in-app
inbox and wires the daily due/overdue sweep to actually nudge them.

Design:
  - In-app is the source of truth: `emit()` writes a `sol_notifications` row,
    idempotently (INSERT ... ON CONFLICT (user_id, dedup_key) DO NOTHING) so the
    daily scan re-runs without ever duplicating a nudge.
  - External channels (email/SMS) are OPTIONAL, opt-in, and FAIL-SOFT: they are
    disabled unless both a config flag AND a provider are wired, and a delivery
    failure never raises into the caller (a member always still gets the in-app
    row). No provider is bundled yet — the abstraction lights up when one is
    added, without touching call sites.

NON-CUSTODIAL: notifications carry text + an in-app deep-link only. No money, no
bank data, no fund movement — this only reads ledger state and nudges people.
The pure `content_*` builders are testable offline; the DB helpers are thin.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sol import SolCycle, SolNotification, SolPayment
from app.services.sol_v1.reminders import UNPAID_STATUSES, classify_due

logger = logging.getLogger(__name__)

# Due-bucket → notification kind. Only buckets that warrant a payer nudge.
_BUCKET_KIND = {
    "overdue": "payment_overdue",
    "due_today": "payment_due",
    "upcoming": "payment_due",
    # "scheduled" (far future) intentionally does NOT notify.
}


# ── pure content builders (offline-testable) ───────────────────────────────────


def _fmt_amount(amount: Decimal | int | float | str) -> str:
    """'$100.00' — display only; never used for money movement."""
    try:
        return f"${Decimal(str(amount)):.2f}"
    except Exception:
        return f"${amount}"


def content_for_payer_obligation(
    *, payment_id: UUID, amount, due_date: date, bucket: str
) -> dict | None:
    """Build the notification a PAYER gets about an open obligation, or None if
    the bucket doesn't warrant one. `dedup_key` ties one nudge to (kind,payment)
    so 'due' then later 'overdue' each fire once — natural escalation, no spam."""
    kind = _BUCKET_KIND.get(bucket)
    if kind is None:
        return None
    amt = _fmt_amount(amount)
    if kind == "payment_overdue":
        title = "Payment overdue"
        body = f"Your {amt} contribution was due {due_date.isoformat()}. Please pay your circle member."
    else:
        when = "today" if bucket == "due_today" else f"on {due_date.isoformat()}"
        title = "Payment due"
        body = f"Your {amt} contribution is due {when}. Pay your circle member, then mark it paid."
    # Dedup on the BUCKET for the payment_due family (upcoming vs due_today), else
    # the earlier "upcoming" nudge's key would swallow the "due today" one (same
    # kind) and the member would get no reminder ON the due date. Overdue already
    # has its own kind. → three escalating one-shot nudges: upcoming, due_today,
    # overdue — each fires exactly once, no daily spam.
    dedup_scope = bucket if kind == "payment_due" else kind
    return {
        "kind": kind,
        "title": title,
        "body": body,
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
        "dedup_key": f"{dedup_scope}:{payment_id}",
    }


# ── external channel abstraction (fail-soft, opt-in) ────────────────────────────


def _flag(name: str) -> bool:
    return str(getattr(settings, name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _email_enabled() -> bool:
    # Opt-in AND a provider must be configured; neither is bundled yet, so this
    # is False by default and emit() degrades to in-app only.
    return _flag("SOL_NOTIFY_EMAIL_ENABLED")


def _sms_enabled() -> bool:
    return _flag("SOL_NOTIFY_SMS_ENABLED")


def _deliver_external(*, user_id: UUID, kind: str, title: str, body: str) -> None:
    """Best-effort email/SMS fan-out. NEVER raises — the in-app row already
    landed. No provider is wired yet; when one is, plug it in here behind the
    flags. Kept a no-op-by-default so we don't fake a channel that can't send."""
    try:
        if _email_enabled():
            logger.info("sol notify: email channel enabled but no provider wired (kind=%s)", kind)
            # TODO(provider): send_email(resolve_email(user_id), title, body)
        if _sms_enabled():
            logger.info("sol notify: sms channel enabled but no provider wired (kind=%s)", kind)
            # TODO(provider): send_sms(resolve_phone(user_id), f"{title}: {body}")
    except Exception as e:  # a broken channel must never break emission
        logger.warning("sol notify: external delivery failed (kind=%s): %s", kind, e)


# ── emit (idempotent) ───────────────────────────────────────────────────────────


def emit(
    db: Session,
    *,
    user_id: UUID,
    kind: str,
    title: str,
    body: str,
    dedup_key: str,
    link: str | None = None,
    payment_id: UUID | None = None,
) -> UUID | None:
    """Create one in-app notification, idempotently. Returns the new row id, or
    None if a row with the same (user_id, dedup_key) already existed (no dup,
    and external channels are NOT re-fired). Fail-soft on the external fan-out."""
    stmt = (
        pg_insert(SolNotification)
        .values(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            link=link,
            payment_id=payment_id,
            dedup_key=dedup_key,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
        .returning(SolNotification.id)
    )
    new_id = db.execute(stmt).scalar_one_or_none()
    db.commit()
    if new_id is not None:
        _deliver_external(user_id=user_id, kind=kind, title=title, body=body)
    return new_id


def emit_due_overdue_scan(db: Session, today: date, upcoming_within_days: int = 7) -> int:
    """Scan every open (unpaid) obligation and nudge each PAYER once per bucket.

    Idempotent via emit()'s dedup — safe to run daily. Returns rows created."""
    rows = db.execute(
        select(SolPayment.id, SolPayment.payer_id, SolPayment.amount, SolCycle.due_date)
        .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
        .where(SolPayment.status.in_(UNPAID_STATUSES))
    ).all()

    created = 0
    for payment_id, payer_id, amount, due in rows:
        try:  # one bad row must not abort the whole sweep — guard build + emit
            bucket = classify_due(due, today, upcoming_within_days)
            content = content_for_payer_obligation(
                payment_id=payment_id, amount=amount, due_date=due, bucket=bucket
            )
            if content is None:
                continue
            if emit(db, user_id=payer_id, **content) is not None:
                created += 1
        except Exception as e:
            db.rollback()
            logger.warning("sol notify: emit failed for payment %s: %s", payment_id, e)
    return created


# ── readers ─────────────────────────────────────────────────────────────────────


def list_for_user(
    db: Session, *, user_id: UUID, unread_only: bool = False, limit: int = 50
) -> list[SolNotification]:
    """A member's notifications, newest first. `limit` is clamped to [1, 200]."""
    limit = max(1, min(int(limit), 200))
    q = select(SolNotification).where(SolNotification.user_id == user_id)
    if unread_only:
        q = q.where(SolNotification.read_at.is_(None))
    q = q.order_by(SolNotification.created_at.desc()).limit(limit)
    return list(db.execute(q).scalars().all())


def unread_count(db: Session, *, user_id: UUID) -> int:
    from sqlalchemy import func as sa_func

    return int(
        db.execute(
            select(sa_func.count())
            .select_from(SolNotification)
            .where(SolNotification.user_id == user_id, SolNotification.read_at.is_(None))
        ).scalar_one()
    )


def mark_read(db: Session, *, user_id: UUID, notification_id: UUID) -> bool:
    """Mark one notification read. Ownership-scoped (user_id in the WHERE), so a
    member can never mark someone else's. Idempotent. Returns True if it matched
    an unread row this call."""
    result = db.execute(
        update(SolNotification)
        .where(
            SolNotification.id == notification_id,
            SolNotification.user_id == user_id,
            SolNotification.read_at.is_(None),
        )
        .values(read_at=func.now())
    )
    db.commit()
    return (result.rowcount or 0) > 0


def mark_all_read(db: Session, *, user_id: UUID) -> int:
    """Mark all of a member's unread notifications read. Returns rows changed."""
    result = db.execute(
        update(SolNotification)
        .where(SolNotification.user_id == user_id, SolNotification.read_at.is_(None))
        .values(read_at=func.now())
    )
    db.commit()
    return result.rowcount or 0
