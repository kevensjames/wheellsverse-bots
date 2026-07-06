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
import threading
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
    # Opt-in flag; email ALSO requires SMTP to be configured (see _email_configured).
    return _flag("SOL_NOTIFY_EMAIL_ENABLED")


def _sms_enabled() -> bool:
    return _flag("SOL_NOTIFY_SMS_ENABLED")


def _email_configured() -> bool:
    return bool((settings.SMTP_HOST or "").strip() and (settings.SMTP_FROM or "").strip())


def _resolve_email(user_id: UUID) -> str | None:
    """The member's email — resolved in its OWN short-lived session so a lookup
    error can never poison the caller's (scan/request) session. Money-free."""
    from app.database import SessionLocal
    from app.models.profile import Profile

    s = SessionLocal()
    try:
        return s.scalar(select(Profile.email).where(Profile.id == user_id))
    finally:
        s.close()


def _send_email(to: str, subject: str, body: str) -> None:
    """Send one email over SMTP with certificate verification. Any provider speaks
    SMTP (SendGrid/Mailgun/SES/Gmail). Raises on failure; the caller is fail-soft.

    Security: verifies the server cert (create_default_context → CERT_REQUIRED +
    hostname check) so an on-path attacker can't MITM the AUTH exchange, and NEVER
    sends AUTH credentials over an unencrypted channel."""
    import smtplib
    import ssl
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = settings.SMTP_PORT or 587
    ctx = ssl.create_default_context()  # verify cert chain + hostname (blocks MITM)

    if port == 465:  # implicit TLS from the first byte
        with smtplib.SMTP_SSL(settings.SMTP_HOST, port, timeout=10, context=ctx) as s:
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            s.send_message(msg)
        return

    with smtplib.SMTP(settings.SMTP_HOST, port, timeout=10) as s:
        if settings.SMTP_STARTTLS:
            s.starttls(context=ctx)
        if settings.SMTP_USER:
            if not settings.SMTP_STARTTLS:
                # refuse to send credentials over a cleartext channel
                raise RuntimeError(
                    "refusing SMTP AUTH over cleartext — enable SMTP_STARTTLS or use port 465"
                )
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        s.send_message(msg)


def _deliver_email_sync(user_id: UUID, subject: str, body: str) -> None:
    """Resolve the member's address (own session) + send. Synchronous; raises on
    error. Runs on the background thread below and is tested directly."""
    to = _resolve_email(user_id)
    if to:
        _send_email(to, subject, body)


def _deliver_external(*, user_id: UUID, kind: str, title: str, body: str) -> None:
    """Fire email/SMS OFF the caller's critical path. Email runs in a BACKGROUND
    daemon thread with its OWN session, so a slow/unreachable SMTP host or a lookup
    error can never block the caller (the per-payer scan loop, or a member's
    mark/confirm/dispute request) nor poison its session. NEVER raises; the member
    always has their durable in-app notification regardless."""
    if _email_enabled() and _email_configured():
        def _run() -> None:
            try:
                _deliver_email_sync(user_id, title, body)
            except Exception as e:  # a broken channel must never break emission
                logger.warning("sol notify: email delivery failed (kind=%s): %s", kind, e)
        threading.Thread(target=_run, name="sol-email", daemon=True).start()
    if _sms_enabled():
        # SMS needs a provider (Twilio) + a phone on file; not wired. No-op log.
        logger.info("sol notify: sms channel enabled but no provider wired (kind=%s)", kind)


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


# ── ledger-event content builders (offline-testable) ───────────────────────────


def content_payment_marked(*, payment_id: UUID, amount) -> dict:
    """To the PAYEE: the payer says they sent the money — go confirm receipt."""
    return {
        "kind": "payment_marked",
        "title": "Confirm payment received",
        "body": f"A circle member marked a {_fmt_amount(amount)} payment to you as sent. Confirm it once you receive it.",
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_payment_confirmed(*, payment_id: UUID, amount) -> dict:
    """To the PAYER: the recipient acknowledged receipt."""
    return {
        "kind": "payment_confirmed",
        "title": "Payment confirmed",
        "body": f"Your {_fmt_amount(amount)} payment was confirmed received. Thanks for keeping the circle on track!",
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_payment_disputed(*, payment_id: UUID, amount) -> dict:
    """To the PAYER: the recipient says they did NOT receive it."""
    return {
        "kind": "payment_disputed",
        "title": "Payment disputed",
        "body": f"The recipient reports they haven't received your {_fmt_amount(amount)} payment. Please follow up or re-send, then mark it paid again.",
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_payment_disputed_for_organizer(*, payment_id: UUID, amount) -> dict:
    """To the ORGANIZER: a payment in your circle was disputed — review it. This
    is the discovery path to the waive action (the organizer may be neither party
    to the payment, so they'd otherwise never learn a dispute is blocking a cycle)."""
    return {
        "kind": "payment_disputed",
        "title": "A payment in your circle was disputed",
        "body": f"A {_fmt_amount(amount)} payment was disputed. Review it — you can waive it to unblock the cycle if it can't be resolved.",
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_payment_resolved(*, payment_id: UUID, amount, outcome: str) -> dict:
    """To BOTH parties: a disputed payment was resolved. outcome 'waived'
    (organizer write-off — terminal) or 'withdrawn' (payee retracted the dispute
    → back to awaiting confirmation)."""
    if outcome == "waived":
        title = "Dispute resolved — payment waived"
        body = (
            f"A disputed {_fmt_amount(amount)} payment was waived by the circle organizer. "
            "It's settled on the books; no further action is needed."
        )
    else:  # withdrawn
        title = "Dispute withdrawn"
        body = (
            f"The dispute on a {_fmt_amount(amount)} payment was withdrawn — "
            "the recipient will confirm receipt."
        )
    return {
        "kind": "payment_resolved",
        "title": title,
        "body": body,
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_member_delinquent(*, group_id: UUID, circle: str, overdue_count: int, total, days: int) -> dict:
    """To the ORGANIZER: a member is unpaid past the grace period — act on it.
    Generic ('a member') on purpose; the group screen shows exactly who."""
    n = "s" if overdue_count != 1 else ""
    dsfx = "s" if days != 1 else ""
    return {
        "kind": "member_delinquent",
        "title": "A member is behind on payments",
        "body": (
            f"A member of {circle} is {days} day{dsfx} past due on {overdue_count} "
            f"contribution{n} ({_fmt_amount(total)} total). Follow up — or waive it if it can't be resolved."
        ),
        "link": f"#/group/{group_id}",
    }


def content_cycle_started(*, payment_id: UUID, amount, due_date: date) -> dict:
    """To a PAYER: a new cycle began; here's what you owe and by when."""
    return {
        "kind": "cycle_started",
        "title": "New cycle started",
        "body": f"A new cycle began — your {_fmt_amount(amount)} contribution is due {due_date.isoformat()}.",
        "link": f"#/payment/{payment_id}",
        "payment_id": payment_id,
    }


def content_payout_incoming(*, group_id: UUID, cycle_number: int, amount) -> dict:
    """To the RECIPIENT: it's your turn — members will pay you this cycle."""
    return {
        "kind": "payout_incoming",
        "title": "It's your turn to get paid",
        "body": f"Cycle {cycle_number} started — your circle members will each send you {_fmt_amount(amount)} directly.",
        "link": f"#/group/{group_id}",
    }


# ── ledger-event hooks (called by ledger.py transitions; fully fail-soft) ───────


def _emit_event_soft(*, user_id: UUID, dedup_key: str, content: dict) -> None:
    """Emit one ledger-event notification in ITS OWN session — fully DECOUPLED
    and fail-soft. It never touches, blocks, or rolls back the ledger session
    that triggered it, so a member's payment can never fail (or stall) because a
    notification couldn't be written. No-ops cleanly if the DB is unreachable."""
    from app.database import SessionLocal

    try:
        session = SessionLocal()
        try:
            emit(session, user_id=user_id, dedup_key=dedup_key, **content)
        finally:
            session.close()
    except Exception as e:
        logger.warning("sol notify: event '%s' emit failed: %s", content.get("kind"), e)


# The hooks take the (already-committed) ORM object and read plain attribute
# VALUES off it — they never re-use its session (see _emit_event_soft).


def notify_payment_marked(payment) -> None:
    # dedup includes payer_marked_at so a legitimate re-mark (after a dispute)
    # re-prompts the payee, while an exact duplicate emit stays idempotent.
    ts = payment.payer_marked_at.isoformat() if payment.payer_marked_at else "0"
    _emit_event_soft(user_id=payment.payee_id, dedup_key=f"payment_marked:{payment.id}:{ts}",
                     content=content_payment_marked(payment_id=payment.id, amount=payment.amount))


def notify_payment_confirmed(payment) -> None:
    _emit_event_soft(user_id=payment.payer_id, dedup_key=f"payment_confirmed:{payment.id}",
                     content=content_payment_confirmed(payment_id=payment.id, amount=payment.amount))


def notify_payment_disputed(payment, *, organizer_id: UUID | None = None) -> None:
    # dedup includes payer_marked_at (the mark THIS dispute reacts to) so a
    # re-dispute after a re-mark OR a withdraw (both refresh payer_marked_at)
    # re-notifies — symmetric with notify_payment_marked. A static key would
    # silently swallow dispute #2, stranding a payer who re-sent on dispute #1.
    ts = payment.payer_marked_at.isoformat() if payment.payer_marked_at else "0"
    _emit_event_soft(user_id=payment.payer_id, dedup_key=f"payment_disputed:{payment.id}:{ts}",
                     content=content_payment_disputed(payment_id=payment.id, amount=payment.amount))
    # Also nudge the circle organizer (if they're not already a party) — this is
    # their discovery path to the waive action for a dispute between two others.
    if organizer_id is not None and organizer_id not in (payment.payer_id, payment.payee_id):
        _emit_event_soft(
            user_id=organizer_id,
            dedup_key=f"payment_disputed:organizer:{payment.id}:{ts}",
            content=content_payment_disputed_for_organizer(payment_id=payment.id, amount=payment.amount),
        )


def notify_dispute_resolved(payment, *, outcome: str) -> None:
    """Tell BOTH parties a disputed payment was resolved — 'waived' (organizer
    write-off, terminal) or 'withdrawn' (payee retracted, back to 'marked').

    dedup discriminator: for a waive we key on resolved_at (a re-dispute →
    re-waive always re-notifies); for a withdraw we key on payer_marked_at (the
    mark the dispute reacted to) so a fresh dispute cycle re-notifies, mirroring
    notify_payment_disputed. Own session, fully fail-soft (see _emit_event_soft).
    """
    if outcome == "waived" and payment.resolved_at is not None:
        disc = payment.resolved_at.isoformat()
    else:
        disc = payment.payer_marked_at.isoformat() if payment.payer_marked_at else "0"
    content = content_payment_resolved(
        payment_id=payment.id, amount=payment.amount, outcome=outcome
    )
    for uid in (payment.payer_id, payment.payee_id):
        _emit_event_soft(
            user_id=uid,
            dedup_key=f"payment_resolved:{outcome}:{payment.id}:{disc}",
            content=content,
        )


def notify_member_delinquent(
    *, organizer_id: UUID, group_id: UUID, circle: str, member_id: UUID,
    oldest_due, overdue_count: int, total, days: int,
) -> None:
    """Escalate a delinquent member to the circle organizer, once per episode.
    dedup on (group, member, oldest unpaid due date) — a stable key while the
    member stays behind on the same obligation, a fresh one for a new episode."""
    content = content_member_delinquent(
        group_id=group_id, circle=circle, overdue_count=overdue_count, total=total, days=days
    )
    _emit_event_soft(
        user_id=organizer_id,
        dedup_key=f"member_delinquent:{group_id}:{member_id}:{oldest_due.isoformat()}",
        content=content,
    )


def notify_cycle_activated(*, cycle, payments, recipient_user_id: UUID, amount) -> None:
    """One 'cycle_started' to each payer + one 'payout_incoming' to the recipient."""
    for p in payments:
        _emit_event_soft(user_id=p.payer_id, dedup_key=f"cycle_started:{p.id}",
                         content=content_cycle_started(payment_id=p.id, amount=amount, due_date=cycle.due_date))
    _emit_event_soft(user_id=recipient_user_id, dedup_key=f"payout_incoming:{cycle.id}",
                     content=content_payout_incoming(group_id=cycle.group_id, cycle_number=cycle.cycle_number, amount=amount))


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
