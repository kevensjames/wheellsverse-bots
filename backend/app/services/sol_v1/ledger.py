"""Sol v1 ledger — the manual/external rail: double-confirmed member payments.

NON-CUSTODIAL: money never touches Sol. Members pay each other directly outside
the app (Zelle / CashApp / Venmo / cash); this module only RECORDS what they say
happened and reconciles it with a two-sided confirmation:

    pending ──payer marks paid──▶ marked ──payee confirms──▶ confirmed
                                    ▲ │
             payer re-marks / payee │ └──payee disputes──▶ disputed
                  withdraws ────────┘                         │
                                    organizer waives (write-off) ──▶ waived (terminal)
    (late is set by the Stage-4 scheduler for overdue pending rows; it marks like pending)

A dispute used to be a dead-end — the ONLY exit was the payer re-marking, so an
unresolved dispute stranded its cycle (and then the whole group) in a non-terminal
state forever. Stage 21 adds two exits: the payee can WITHDRAW a mistaken dispute
(back to 'marked'), and the organizer can WAIVE it (a terminal write-off that lets
a frozen cycle close). A 'waived' payment counts as settled for completion and is
neutral for reputation — it is a recorded forgiveness DECISION; no money moves.

When every payment in a cycle is confirmed-or-waived the cycle completes; when
every cycle completes the group completes. Payment rows are materialized at cycle
activation (one per non-recipient → recipient), so the ledger is fully queryable.

The state-transition table and the payment-handle guard are pure functions
(no DB) so the core rules are unit-tested offline; the rest is thin persistence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sol import (
    PAYMENT_METHODS,
    PROFILE_METHODS,
    SolCycle,
    SolGroup,
    SolMembership,
    SolPayment,
    SolPaymentProfile,
    SolPaymentProof,
)
from app.services.sol_v1.lifecycle import SolError

# ── pure: the payment state machine ───────────────────────────────────────────
# (current_status, action) -> next_status. Anything not listed is a 409.
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("pending", "mark"): "marked",
    ("late", "mark"): "marked",
    ("disputed", "mark"): "marked",  # payer re-marks after a dispute
    ("marked", "confirm"): "confirmed",
    ("marked", "dispute"): "disputed",
    # Stage 21 — dispute resolution:
    ("disputed", "withdraw"): "marked",  # payee retracts a mistaken dispute
    ("disputed", "waive"): "waived",     # organizer writes it off (terminal)
}
PAYMENT_ACTIONS = ("mark", "confirm", "dispute", "withdraw", "waive")


def next_status(current: str, action: str) -> str:
    """Return the status after ``action`` from ``current``, or raise 409/400."""
    if action not in PAYMENT_ACTIONS:
        raise SolError(400, f"unknown action {action!r}")
    try:
        return _TRANSITIONS[(current, action)]
    except KeyError:
        raise SolError(409, f"cannot {action} a payment that is {current!r}")


# ── pure: non-custodial handle guard ──────────────────────────────────────────
_BANKISH = re.compile(r"^\d{9}$|^\d{12,17}$")  # ABA routing (9) / account (12-17)


def validate_handle(method: str, handle: str) -> str:
    """Normalize + guard a payment-profile handle. Rejects anything that looks
    like a bank account/routing number — Sol stores external rails ONLY.

    Heuristic, not exhaustive (the schema has no bank columns at all, so this is
    defense-in-depth): 10–11 digit phone numbers pass; 9-digit and 12–17-digit
    pure-number strings (routing / account shapes) are rejected.
    """
    if method not in PROFILE_METHODS:
        raise SolError(400, f"method must be one of {PROFILE_METHODS}")
    cleaned = handle.strip()
    if not cleaned:
        raise SolError(400, "handle is required")
    if len(cleaned) > 128:
        raise SolError(400, "handle too long")
    digits = re.sub(r"\D", "", cleaned)
    # Reject a routing/account-shaped number regardless of how it's punctuated
    # (spaces, hyphens, dots, parens, slashes...). Real external rails always
    # carry a letter / @ / $ / + (emails, cashtags, @handles, +country phones),
    # so a bank-length pure-number string WITHOUT any of those markers is the tell.
    if _BANKISH.match(digits) and not re.search(r"[A-Za-z@$+]", cleaned):
        raise SolError(
            400,
            "that looks like a bank account/routing number — use a phone, "
            "email, or app tag instead (Sol never handles bank details)",
        )
    return cleaned


# ── helpers ───────────────────────────────────────────────────────────────────


def _group_of_cycle(db: Session, cycle: SolCycle) -> SolGroup:
    group = db.get(SolGroup, cycle.group_id)
    if group is None:
        raise SolError(404, "group not found")
    return group


def _require_payment_party(payment: SolPayment, user_id: UUID, *, side: str) -> None:
    """side='payer' or 'payee' — the acting user must be that party."""
    owner = payment.payer_id if side == "payer" else payment.payee_id
    if owner != user_id:
        raise SolError(403, f"only the {side} can do that")


# ── cycle activation → materialize the expected payments ──────────────────────


def activate_cycle(db: Session, *, cycle_id: UUID, actor_id: UUID) -> tuple[SolCycle, list[SolPayment]]:
    """Organizer activates a cycle: pending→active + create one payment row per
    non-recipient member (they each owe the recipient the contribution).

    Rejects if the group isn't locked, the cycle isn't pending, or the recipient
    is unset. Idempotent guard: a non-pending cycle raises 409.
    """
    # Lock the cycle row so two concurrent activations serialize: the second
    # blocks, then sees status='active' and 409s instead of double-materializing.
    cycle = db.get(SolCycle, cycle_id, with_for_update=True)
    if cycle is None:
        raise SolError(404, "cycle not found")
    group = _group_of_cycle(db, cycle)
    if group.organizer_id != actor_id:
        raise SolError(403, "only the organizer can activate a cycle")
    if group.status != "locked":
        raise SolError(409, "group must be locked before activating cycles")
    if cycle.status != "pending":
        raise SolError(409, f"cycle is already {cycle.status}")
    if cycle.recipient_membership_id is None:
        raise SolError(409, "cycle has no recipient assigned")

    recipient = db.get(SolMembership, cycle.recipient_membership_id)
    if recipient is None:
        raise SolError(409, "cycle recipient membership no longer exists")

    members = list(
        db.scalars(select(SolMembership).where(SolMembership.group_id == group.id)).all()
    )
    payments: list[SolPayment] = []
    for m in members:
        if m.id == recipient.id or m.user_id == recipient.user_id:
            continue  # the recipient does not pay themselves this cycle
        payment = SolPayment(
            cycle_id=cycle.id,
            payer_id=m.user_id,
            payee_id=recipient.user_id,
            amount=group.contribution_amount,
            method=None,
            status="pending",
        )
        db.add(payment)
        payments.append(payment)

    cycle.status = "active"
    db.commit()
    # Notify before the refreshes (see mark_paid) — the fan-out reads only
    # id/payer_id/due_date/etc., all populated post-commit (expire_on_commit=False).
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    notifications.notify_cycle_activated(  # → each payer: cycle_started; recipient: payout_incoming
        cycle=cycle, payments=payments,
        recipient_user_id=recipient.user_id, amount=group.contribution_amount,
    )
    db.refresh(cycle)
    for p in payments:
        db.refresh(p)
    return cycle, payments


# ── the double-confirmation transitions ───────────────────────────────────────


def _load_payment(db: Session, payment_id: UUID, *, lock: bool = False) -> SolPayment:
    # lock=True → SELECT ... FOR UPDATE, so a status transition can't race another
    # transition on the same payment (each request has its own session, so the
    # second transition blocks, re-reads the new status, and 409s correctly).
    payment = (
        db.get(SolPayment, payment_id, with_for_update=True)
        if lock
        else db.get(SolPayment, payment_id)
    )
    if payment is None:
        raise SolError(404, "payment not found")
    return payment


def mark_paid(
    db: Session,
    *,
    payment_id: UUID,
    actor_id: UUID,
    method: str,
    proof_image_url: str | None = None,
) -> SolPayment:
    """Payer records that they sent the money (optionally with a proof photo)."""
    if method not in PAYMENT_METHODS:
        raise SolError(400, f"method must be one of {PAYMENT_METHODS}")
    payment = _load_payment(db, payment_id, lock=True)
    _require_payment_party(payment, actor_id, side="payer")
    payment.status = next_status(payment.status, "mark")
    payment.method = method
    payment.payer_marked_at = datetime.now(timezone.utc)
    if proof_image_url:
        db.add(SolPaymentProof(payment_id=payment.id, image_url=proof_image_url.strip()))
    db.commit()
    # Notify BEFORE refresh so the ledger session isn't pinned idle-in-transaction
    # across the notification's own-session write (expire_on_commit=False keeps the
    # attributes the hook reads populated after commit).
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    notifications.notify_payment_marked(payment)  # → payee: confirm receipt (own session)
    db.refresh(payment)
    return payment


def confirm_received(db: Session, *, payment_id: UUID, actor_id: UUID) -> SolPayment:
    """Payee confirms the money arrived. May complete the cycle (and the group)."""
    payment = _load_payment(db, payment_id, lock=True)
    _require_payment_party(payment, actor_id, side="payee")
    payment.status = next_status(payment.status, "confirm")
    payment.payee_confirmed_at = datetime.now(timezone.utc)
    db.flush()
    _maybe_complete_cycle(db, payment.cycle_id)
    db.commit()
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    notifications.notify_payment_confirmed(payment)  # → payer: confirmed (own session, pre-refresh)
    db.refresh(payment)
    return payment


def dispute(db: Session, *, payment_id: UUID, actor_id: UUID) -> SolPayment:
    """Payee flags that they did NOT receive the money the payer marked."""
    payment = _load_payment(db, payment_id, lock=True)
    _require_payment_party(payment, actor_id, side="payee")
    payment.status = next_status(payment.status, "dispute")
    if payment.disputed_at is None:  # sticky — keep the first dispute time
        payment.disputed_at = datetime.now(timezone.utc)
    db.commit()
    # The organizer needs to hear about the dispute so they can reach the waive
    # action (they may be neither party). Scalar lookup — no SolGroup ORM load.
    cycle = db.get(SolCycle, payment.cycle_id)
    organizer_id = (
        db.scalar(select(SolGroup.organizer_id).where(SolGroup.id == cycle.group_id))
        if cycle is not None
        else None
    )
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    # → payer: not received; → organizer (if a non-party): review + can waive
    notifications.notify_payment_disputed(payment, organizer_id=organizer_id)
    db.refresh(payment)
    return payment


def withdraw_dispute(db: Session, *, payment_id: UUID, actor_id: UUID) -> SolPayment:
    """Payee retracts a dispute they raised in error → back to 'marked' (the
    confirm/dispute decision point). PAYEE-only.

    Non-custodial: flips status only. The sticky `disputed_at` is deliberately
    NOT cleared — the dispute did happen, so if the payee later confirms, the
    payer earns partial (not full) reputation credit. This preserves the
    anti-gaming invariant that a non-receipt signal can't be erased.
    """
    payment = _load_payment(db, payment_id, lock=True)
    _require_payment_party(payment, actor_id, side="payee")
    payment.status = next_status(payment.status, "withdraw")  # disputed -> marked (else 409)
    # Refresh the mark timestamp: the payer's mark is live again (awaiting confirm).
    # This ALSO gives each disputed→marked→disputed round-trip a distinct value, so
    # the payment_disputed / payment_resolved dedup keys (both keyed on
    # payer_marked_at) don't collide and swallow a genuine re-notification. Safe for
    # reputation: an ever-disputed payment ignores marked_on entirely (see
    # reputation.classify_payment), so this never changes on-time vs late credit.
    payment.payer_marked_at = datetime.now(timezone.utc)
    db.commit()
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    notifications.notify_dispute_resolved(payment, outcome="withdrawn")  # → both parties
    db.refresh(payment)
    return payment


def waive_dispute(
    db: Session, *, payment_id: UUID, actor_id: UUID, note: str | None = None
) -> SolPayment:
    """Organizer writes off a stuck disputed payment as a TERMINAL 'waived'
    outcome — the recorded forgiveness that lets a frozen cycle/group close.
    ORGANIZER-only. Moves no money; records only status + who/when/why.

    A waived payment is SETTLED for cycle completion and NEUTRAL for reputation
    (it neither credits nor penalizes the payer). `resolved_by` is always stamped
    so the decision is auditable even when the organizer is also the payee.
    """
    cleaned = (note or "").strip()
    if len(cleaned) > 500:
        raise SolError(400, "resolution note too long (max 500 characters)")
    payment = _load_payment(db, payment_id, lock=True)
    cycle = db.get(SolCycle, payment.cycle_id)
    if cycle is None:
        raise SolError(404, "cycle not found")
    # Fetch ONLY the organizer id as a scalar — do NOT load the SolGroup as an ORM
    # object, or it would sit in the identity map and _maybe_complete_cycle's
    # `db.get(SolGroup, ..., with_for_update=True)` would return the cached row
    # WITHOUT issuing the FOR UPDATE lock, breaking completion serialization.
    organizer_id = db.scalar(select(SolGroup.organizer_id).where(SolGroup.id == cycle.group_id))
    if organizer_id is None:
        raise SolError(404, "group not found")
    if organizer_id != actor_id:
        raise SolError(403, "only the organizer can waive a disputed payment")

    payment.status = next_status(payment.status, "waive")  # disputed -> waived (else 409)
    payment.resolution_note = cleaned or None
    payment.resolved_by = actor_id
    payment.resolved_at = datetime.now(timezone.utc)
    db.flush()
    # A waive can immediately close a previously-stranded cycle (and its group).
    _maybe_complete_cycle(db, payment.cycle_id)
    db.commit()
    from app.services.sol_v1 import notifications  # local: avoid import cycle
    notifications.notify_dispute_resolved(payment, outcome="waived")  # → both parties
    db.refresh(payment)
    return payment


def add_proof(db: Session, *, payment_id: UUID, actor_id: UUID, image_url: str) -> SolPaymentProof:
    """Payer attaches an additional proof screenshot to their payment."""
    url = image_url.strip()
    if not url:
        raise SolError(400, "image_url is required")
    payment = _load_payment(db, payment_id)
    _require_payment_party(payment, actor_id, side="payer")
    proof = SolPaymentProof(payment_id=payment.id, image_url=url)
    db.add(proof)
    db.commit()
    db.refresh(proof)
    return proof


def _maybe_complete_cycle(db: Session, cycle_id: UUID) -> None:
    """If every payment in the cycle is settled (confirmed OR waived), complete
    it — and if every cycle in the group is complete, complete the group. Call
    within a txn."""
    cycle = db.get(SolCycle, cycle_id)
    if cycle is None:
        return
    # Serialize completion decisions for this group by locking the group row:
    # two concurrent final confirmations then can't each miss the other's
    # uncommitted update and both decline to complete (which would strand the
    # cycle/group in a non-terminal state forever).
    group = db.get(SolGroup, cycle.group_id, with_for_update=True)

    remaining = db.scalar(
        select(func.count(SolPayment.id)).where(
            SolPayment.cycle_id == cycle_id,
            SolPayment.status.notin_(("confirmed", "waived")),
        )
    )
    if remaining and remaining > 0:
        return
    cycle.status = "complete"
    db.flush()

    open_cycles = db.scalar(
        select(func.count(SolCycle.id)).where(
            SolCycle.group_id == cycle.group_id, SolCycle.status != "complete"
        )
    )
    if not open_cycles and group is not None and group.status == "locked":
        group.status = "complete"
        db.flush()


# ── reads ─────────────────────────────────────────────────────────────────────


def list_payments(
    db: Session, *, user_id: UUID, role: str = "all", status: str | None = None
) -> list[SolPayment]:
    """Payments where the user is payer and/or payee, newest first."""
    stmt = select(SolPayment)
    if role == "payer":
        stmt = stmt.where(SolPayment.payer_id == user_id)
    elif role == "payee":
        stmt = stmt.where(SolPayment.payee_id == user_id)
    elif role == "all":
        stmt = stmt.where(
            (SolPayment.payer_id == user_id) | (SolPayment.payee_id == user_id)
        )
    else:
        raise SolError(400, "role must be payer, payee, or all")
    if status is not None:
        stmt = stmt.where(SolPayment.status == status)
    stmt = stmt.order_by(SolPayment.created_at.desc())
    return list(db.scalars(stmt).all())


def get_payment_detail(
    db: Session, *, payment_id: UUID, user_id: UUID
) -> tuple[SolPayment, list[SolPaymentProof], list[SolPaymentProfile], UUID | None]:
    """Payment + its proofs + how-to-pay handles (the payee's profiles) + the
    circle's organizer_id (for the caller to decide who may waive).

    Visible to the payer, the payee, OR the circle organizer — but the organizer
    (when not a party) may view a payment ONLY while it is disputed (so they can
    review + waive it) or after they themselves resolved it (resolved_by == them,
    so the post-waive refresh still loads). This keeps settled payments between
    two other members private to those parties. Everyone else gets 403.
    """
    payment = _load_payment(db, payment_id)
    cycle = db.get(SolCycle, payment.cycle_id)
    organizer_id = (
        db.scalar(select(SolGroup.organizer_id).where(SolGroup.id == cycle.group_id))
        if cycle is not None
        else None
    )
    is_party = user_id in (payment.payer_id, payment.payee_id)
    organizer_may_view = user_id == organizer_id and (
        payment.status == "disputed" or payment.resolved_by == user_id
    )
    if not is_party and not organizer_may_view:
        raise SolError(403, "you are not a party to this payment")
    proofs = list(
        db.scalars(
            select(SolPaymentProof)
            .where(SolPaymentProof.payment_id == payment.id)
            .order_by(SolPaymentProof.uploaded_at)
        ).all()
    )
    pay_to = list(
        db.scalars(
            select(SolPaymentProfile)
            .where(SolPaymentProfile.user_id == payment.payee_id)
            .order_by(SolPaymentProfile.is_default.desc(), SolPaymentProfile.method)
        ).all()
    )
    return payment, proofs, pay_to, organizer_id


# ── payment profiles (how a member wants to be paid) ──────────────────────────


def upsert_payment_profile(
    db: Session, *, user_id: UUID, method: str, handle: str, is_default: bool = False
) -> SolPaymentProfile:
    """Create or update the user's handle for a rail (UNIQUE per user+method).

    Retries once on the UNIQUE(user_id, method) race: if a concurrent request
    inserted the same rail first, roll back and take the update path rather than
    surfacing an IntegrityError as a 500.
    """
    cleaned = validate_handle(method, handle)
    for _attempt in range(2):
        existing = db.scalar(
            select(SolPaymentProfile).where(
                SolPaymentProfile.user_id == user_id, SolPaymentProfile.method == method
            )
        )
        if is_default:
            # exactly one default per user
            for other in db.scalars(
                select(SolPaymentProfile).where(
                    SolPaymentProfile.user_id == user_id,
                    SolPaymentProfile.is_default.is_(True),
                )
            ).all():
                other.is_default = False

        if existing is not None:
            existing.handle = cleaned
            existing.is_default = is_default
            profile = existing
        else:
            profile = SolPaymentProfile(
                user_id=user_id, method=method, handle=cleaned, is_default=is_default
            )
            db.add(profile)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue  # a concurrent insert won the race — loop, now update it
        db.refresh(profile)
        return profile
    raise SolError(409, "could not save payment profile, please retry")


def list_payment_profiles(db: Session, *, user_id: UUID) -> list[SolPaymentProfile]:
    return list(
        db.scalars(
            select(SolPaymentProfile)
            .where(SolPaymentProfile.user_id == user_id)
            .order_by(SolPaymentProfile.is_default.desc(), SolPaymentProfile.method)
        ).all()
    )


def delete_payment_profile(db: Session, *, user_id: UUID, profile_id: UUID) -> None:
    profile = db.get(SolPaymentProfile, profile_id)
    if profile is None:
        raise SolError(404, "payment profile not found")
    if profile.user_id != user_id:
        raise SolError(403, "you can only delete your own payment profiles")
    db.delete(profile)
    db.commit()
