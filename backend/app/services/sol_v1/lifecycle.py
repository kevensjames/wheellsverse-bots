"""Sol v1 group lifecycle — create, join, lock, and payout-calendar build.

NON-CUSTODIAL: nothing here moves, holds, or routes money. ``lock_group`` only
computes the rotation schedule (which member receives in which cycle, and when).
The member-to-member payment records + double-confirmation flow are Stage 3.

Design: the scheduling math (``add_interval``, ``build_payout_positions``,
``build_calendar``) is pure — no DB, no clock — so it is fully unit-testable
offline. The DB operations are thin wrappers that persist the results.
"""
from __future__ import annotations

import calendar as _calendar
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from random import Random
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sol import FREQUENCIES, SolCycle, SolGroup, SolMembership

logger = logging.getLogger(__name__)

# ── domain error ─────────────────────────────────────────────────────────────


class SolError(Exception):
    """Domain error carrying an HTTP status. The router maps it to HTTPException."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


ORDER_MODES = ("random", "organizer_assigned")

_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L ambiguity


# ── pure helpers (no DB, no wall clock) ──────────────────────────────────────


def generate_invite_code(n: int = 8, *, rng: Random | None = None) -> str:
    """A short, human-shareable, unambiguous invite code (default 8 chars)."""
    pick = (rng.choice if rng else secrets.choice)
    return "".join(pick(_INVITE_ALPHABET) for _ in range(n))


def _add_months(d: date, months: int) -> date:
    """Advance ``d`` by whole calendar months, clamping the day to month length."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_interval(base: date, frequency: str, n: int) -> date:
    """Return ``base`` advanced by ``n`` periods of ``frequency``."""
    if frequency == "weekly":
        return base + timedelta(weeks=n)
    if frequency == "biweekly":
        return base + timedelta(weeks=2 * n)
    if frequency == "monthly":
        return _add_months(base, n)
    raise ValueError(f"unknown frequency: {frequency!r}")


def build_payout_positions(
    membership_ids: list[UUID],
    mode: str,
    assignment: dict[UUID, int] | None = None,
    *,
    rng: Random | None = None,
) -> dict[UUID, int]:
    """Map each membership to a payout position 1..N.

    - ``random``: shuffle the members into an order (rng injectable for tests).
    - ``organizer_assigned``: ``assignment`` must be an exact permutation of
      1..N over exactly the given membership ids.
    """
    ids = list(membership_ids)
    n = len(ids)
    if n < 2:
        raise SolError(400, "a group needs at least 2 members to lock")

    if mode == "random":
        order = list(ids)
        (rng or Random()).shuffle(order)
        return {mid: i + 1 for i, mid in enumerate(order)}

    if mode == "organizer_assigned":
        if not assignment:
            raise SolError(400, "organizer_assigned requires a positions map")
        if set(assignment) != set(ids):
            raise SolError(400, "positions map must cover exactly the group's members")
        if sorted(assignment.values()) != list(range(1, n + 1)):
            raise SolError(400, f"positions must be a permutation of 1..{n}")
        return dict(assignment)

    raise SolError(400, f"unknown order_mode: {mode!r} (want one of {ORDER_MODES})")


def build_calendar(
    positions: dict[UUID, int], start: date, frequency: str
) -> list[tuple[int, UUID, date]]:
    """Return [(cycle_number, recipient_membership_id, due_date)] ordered 1..N.

    Cycle ``n`` is due ``n`` periods after ``start`` — i.e. the first collection
    lands one interval after the lock date, giving members lead time.
    """
    by_position = {pos: mid for mid, pos in positions.items()}
    return [
        (n, by_position[n], add_interval(start, frequency, n))
        for n in range(1, len(positions) + 1)
    ]


# ── DB operations ────────────────────────────────────────────────────────────


def _member_count(db: Session, group_id: UUID) -> int:
    return db.scalar(
        select(func.count(SolMembership.id)).where(SolMembership.group_id == group_id)
    ) or 0


def create_group(
    db: Session,
    *,
    organizer_id: UUID,
    name: str,
    contribution_amount,
    frequency: str,
    member_limit: int,
    grace_period_days: int = 0,
    template_id: UUID | None = None,
    round_number: int = 1,
    previous_group_id: UUID | None = None,
    commit: bool = True,
) -> SolGroup:
    """Create a group (status=open) and enroll the organizer as its first member.

    The template/round args are optional (Stage 17): a standalone group leaves
    them at their defaults (template_id NULL, round 1) — identical to before.
    commit=False leaves the group + organizer membership pending (flushed, not
    committed) so a caller can add more rows and commit atomically (next-round).
    """
    if frequency not in FREQUENCIES:
        raise SolError(400, f"frequency must be one of {FREQUENCIES}")
    if member_limit < 2:
        raise SolError(400, "member_limit must be at least 2")
    if contribution_amount is None or contribution_amount <= 0:
        raise SolError(400, "contribution_amount must be positive")
    if grace_period_days < 0 or grace_period_days > 90:
        raise SolError(400, "grace_period_days must be between 0 and 90")

    # Retry on the (astronomically unlikely) invite_code UNIQUE collision.
    for _ in range(5):
        group = SolGroup(
            organizer_id=organizer_id,
            name=name.strip(),
            contribution_amount=contribution_amount,
            frequency=frequency,
            member_limit=member_limit,
            grace_period_days=grace_period_days,
            status="open",
            invite_code=generate_invite_code(),
            template_id=template_id,
            round_number=round_number,
            previous_group_id=previous_group_id,
        )
        db.add(group)
        try:
            db.flush()
            break
        except Exception:
            db.rollback()
            continue
    else:
        raise SolError(500, "could not allocate a unique invite code")

    db.add(
        SolMembership(user_id=organizer_id, group_id=group.id, role="organizer")
    )
    if commit:
        db.commit()
        db.refresh(group)
    else:
        db.flush()  # group.id available; caller commits atomically
    return group


def join_group(db: Session, *, user_id: UUID, invite_code: str) -> SolMembership:
    """Join an open, non-full group by its invite code."""
    # Lock the group row so the "is it full?" check + the membership insert are
    # atomic against a concurrent join racing the last seat (else two joiners can
    # both pass the count check and exceed member_limit). Mirrors ledger.py's
    # with_for_update pattern.
    group = db.scalar(
        select(SolGroup)
        .where(SolGroup.invite_code == invite_code.strip().upper())
        .with_for_update()
    )
    if group is None:
        raise SolError(404, "invite code not found")
    if group.status != "open":
        raise SolError(409, "group is locked — no new members can join")

    already = db.scalar(
        select(SolMembership).where(
            SolMembership.group_id == group.id,
            SolMembership.user_id == user_id,
        )
    )
    if already is not None:
        raise SolError(409, "you are already a member of this group")

    if _member_count(db, group.id) >= group.member_limit:
        raise SolError(409, "group is full")

    membership = SolMembership(user_id=user_id, group_id=group.id, role="member")
    db.add(membership)
    db.commit()
    db.refresh(membership)
    # Detach the committed membership so the fail-soft rollback in the hook below
    # can't re-expire it — the router serializes it AFTER this returns, and a
    # rollback would otherwise force a lazy reload that fails on a degraded DB
    # (turning a durably-committed join into a 500). Its columns are all loaded.
    db.expunge(membership)
    # If this join FILLED a template instance, auto-spawn the next open instance
    # so the waitlist has somewhere to flow. Best-effort — a spawn failure must
    # NEVER break the join that already committed. (local import avoids a cycle.)
    try:
        from app.services.sol_v1 import templates as _templates
        _templates.auto_spawn_next_if_full(db, group)
    except Exception as e:  # noqa: BLE001 — non-critical side effect
        db.rollback()
        logger.warning("sol: auto-spawn-on-fill failed: %s", e)
    return membership


def lock_group(
    db: Session,
    *,
    group_id: UUID,
    actor_id: UUID,
    order_mode: str = "random",
    assignment: dict[UUID, int] | None = None,
    start_date: date | None = None,
    rng: Random | None = None,
) -> SolGroup:
    """Lock the group: freeze membership, assign payout order, build the calendar.

    Only the organizer may lock. Idempotency is NOT assumed — a locked group
    rejects a second lock. On success the group has status=locked, every
    membership has a payout_position, and one SolCycle row exists per member.
    """
    # Lock the group row so lock serializes with join/leave/remove (all of which
    # take this row lock): a member can't slip in or out AFTER we snapshot the
    # roster but BEFORE we assign positions + create cycles, which would strand a
    # member with no cycle (or a cycle whose recipient membership was deleted).
    group = db.get(SolGroup, group_id, with_for_update=True)
    if group is None:
        raise SolError(404, "group not found")
    if group.organizer_id != actor_id:
        raise SolError(403, "only the organizer can lock the group")
    if group.status != "open":
        raise SolError(409, "group is already locked")

    members = list(
        db.scalars(
            select(SolMembership).where(SolMembership.group_id == group_id)
        ).all()
    )
    if len(members) < 2:
        raise SolError(400, "a group needs at least 2 members to lock")

    positions = build_payout_positions(
        [m.id for m in members], order_mode, assignment, rng=rng
    )
    for m in members:
        m.payout_position = positions[m.id]

    # Mint due dates on the SAME clock the reminders read (UTC), so generation
    # and the due/overdue sweep never disagree at a day boundary on a non-UTC
    # host. (Per-member/group timezones are a future refinement.)
    start = start_date or datetime.now(timezone.utc).date()
    group.status = "locked"
    group.locked_at = datetime.now(timezone.utc)

    for cycle_number, recipient_id, due in build_calendar(
        positions, start, group.frequency
    ):
        db.add(
            SolCycle(
                group_id=group_id,
                cycle_number=cycle_number,
                recipient_membership_id=recipient_id,
                due_date=due,
                status="pending",
            )
        )

    db.commit()
    db.refresh(group)
    return group


def leave_group(db: Session, *, group_id: UUID, user_id: UUID) -> None:
    """A member leaves an OPEN circle, freeing their seat. Valid only before lock
    (after lock the payout rotation + cycles are fixed). The ORGANIZER can't leave
    — they own the circle (cancelling it is a separate, not-yet-built action).

    Non-custodial: a membership row is pure coordination; nothing owed exists
    before lock (cycles/payments are materialized at lock/activation).
    """
    group = db.get(SolGroup, group_id, with_for_update=True)  # serialize vs lock/join
    if group is None:
        raise SolError(404, "group not found")
    if group.status != "open":
        raise SolError(409, "the circle has started — members can't leave after it locks")
    if user_id == group.organizer_id:
        raise SolError(409, "the organizer can't leave their own circle")
    membership = db.scalar(
        select(SolMembership).where(
            SolMembership.group_id == group_id, SolMembership.user_id == user_id
        )
    )
    if membership is None:
        raise SolError(404, "you are not a member of this circle")
    db.delete(membership)
    db.commit()


def remove_member(db: Session, *, group_id: UUID, actor_id: UUID, target_user_id: UUID) -> None:
    """The organizer removes another member from an OPEN circle (e.g. a no-show or
    a leaked-invite joiner blocking a seat), freeing the seat. Valid only before
    lock. The organizer can't remove themselves.
    """
    group = db.get(SolGroup, group_id, with_for_update=True)  # serialize vs lock/join
    if group is None:
        raise SolError(404, "group not found")
    if group.organizer_id != actor_id:
        raise SolError(403, "only the organizer can remove members")
    if group.status != "open":
        raise SolError(409, "the circle has started — members can't be removed after it locks")
    if target_user_id == group.organizer_id:
        raise SolError(400, "the organizer can't be removed from their own circle")
    membership = db.scalar(
        select(SolMembership).where(
            SolMembership.group_id == group_id, SolMembership.user_id == target_user_id
        )
    )
    if membership is None:
        raise SolError(404, "that user is not a member of this circle")
    db.delete(membership)
    db.commit()


def rotate_invite_code(db: Session, *, group_id: UUID, actor_id: UUID) -> SolGroup:
    """Organizer regenerates the circle's invite code, IMMEDIATELY invalidating the
    old link (e.g. it leaked or was shared too widely). Only meaningful while the
    circle is open — after lock no one can join, so the link is moot.

    Non-custodial: rotates a random token only; no money, no member data changes.
    Serializes with join/lock/leave/remove via the group-row lock, so a rotation
    can't race a join on the old code.
    """
    for _ in range(5):  # retry the astronomically-unlikely UNIQUE(invite_code) collision
        group = db.get(SolGroup, group_id, with_for_update=True)
        if group is None:
            raise SolError(404, "group not found")
        if group.organizer_id != actor_id:
            raise SolError(403, "only the organizer can reset the invite link")
        if group.status != "open":
            raise SolError(409, "the circle is locked — the invite link is no longer used")
        group.invite_code = generate_invite_code()
        try:
            db.commit()
            db.refresh(group)
            return group
        except IntegrityError:
            db.rollback()  # a concurrent code collided — re-fetch + retry
            continue
    raise SolError(500, "could not allocate a unique invite code, please retry")


def list_groups_for_user(db: Session, *, user_id: UUID) -> list[SolGroup]:
    """Every group the user belongs to (organizer or member), newest first."""
    return list(
        db.scalars(
            select(SolGroup)
            .join(SolMembership, SolMembership.group_id == SolGroup.id)
            .where(SolMembership.user_id == user_id)
            .order_by(SolGroup.created_at.desc())
        ).all()
    )


def get_group_for_member(
    db: Session, *, group_id: UUID, user_id: UUID
) -> tuple[SolGroup, list[SolMembership], list[SolCycle]]:
    """Group detail (members + cycles). Caller must be a member — else 403/404."""
    group = db.get(SolGroup, group_id)
    if group is None:
        raise SolError(404, "group not found")

    members = list(
        db.scalars(
            select(SolMembership)
            .where(SolMembership.group_id == group_id)
            .order_by(SolMembership.payout_position.nulls_last(), SolMembership.created_at)
        ).all()
    )
    if not any(m.user_id == user_id for m in members):
        raise SolError(403, "you are not a member of this group")

    cycles = list(
        db.scalars(
            select(SolCycle)
            .where(SolCycle.group_id == group_id)
            .order_by(SolCycle.cycle_number)
        ).all()
    )
    return group, members, cycles
