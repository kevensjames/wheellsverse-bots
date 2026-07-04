"""Sol v1 templates — the reusable circle blueprint + instance/round spawning.

A SolCircleTemplate is the recurring PRODUCT ($100/mo, 5 members, rules), defined
once. From it:
  - spawn_instance() creates a fresh SolGroup (an "instance") of that blueprint —
    open for a new cohort to fill. The organizer can run the same product again
    and again without recreating it.
  - start_next_round() takes a COMPLETED group and starts the next round with the
    SAME members — a new SolGroup (round_number + 1) that clones the cohort, so
    they keep saving together instead of building a brand-new circle.

NON-CUSTODIAL: templates hold no money; spawning/rounds only create coordination
records (SolGroup/SolMembership). Members still pay each other directly.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sol import (
    FREQUENCIES,
    VISIBILITIES,
    SolCircleTemplate,
    SolGroup,
    SolMembership,
)
from app.services.sol_v1 import lifecycle
from app.services.sol_v1.lifecycle import SolError

logger = logging.getLogger(__name__)


def create_template(
    db: Session,
    *,
    creator_id: UUID,
    name: str,
    contribution_amount,
    frequency: str,
    member_limit: int,
    visibility: str = "invite_only",
) -> SolCircleTemplate:
    """Create a reusable blueprint. Validates the same domain rules as a group."""
    if frequency not in FREQUENCIES:
        raise SolError(400, f"frequency must be one of {FREQUENCIES}")
    if visibility not in VISIBILITIES:
        raise SolError(400, f"visibility must be one of {VISIBILITIES}")
    if member_limit < 2:
        raise SolError(400, "member_limit must be at least 2")
    if contribution_amount is None or contribution_amount <= 0:
        raise SolError(400, "contribution_amount must be positive")

    tpl = SolCircleTemplate(
        creator_id=creator_id,
        name=name.strip(),
        contribution_amount=contribution_amount,
        frequency=frequency,
        member_limit=member_limit,
        visibility=visibility,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def list_templates(db: Session, *, creator_id: UUID) -> list[SolCircleTemplate]:
    return list(
        db.scalars(
            select(SolCircleTemplate)
            .where(SolCircleTemplate.creator_id == creator_id)
            .order_by(SolCircleTemplate.created_at.desc())
        ).all()
    )


def _owned_template(db: Session, *, template_id: UUID, creator_id: UUID) -> SolCircleTemplate:
    tpl = db.get(SolCircleTemplate, template_id)
    if tpl is None:
        raise SolError(404, "template not found")
    if tpl.creator_id != creator_id:
        raise SolError(403, "only the template creator can do that")
    return tpl


def get_template(db: Session, *, template_id: UUID, creator_id: UUID) -> SolCircleTemplate:
    return _owned_template(db, template_id=template_id, creator_id=creator_id)


def instances_of(db: Session, *, template_id: UUID, creator_id: UUID) -> list[SolGroup]:
    """Every group spawned from this template (newest first). Owner-scoped."""
    _owned_template(db, template_id=template_id, creator_id=creator_id)
    return list(
        db.scalars(
            select(SolGroup)
            .where(SolGroup.template_id == template_id)
            .order_by(SolGroup.created_at.desc())
        ).all()
    )


def spawn_instance(
    db: Session, *, template_id: UUID, actor_id: UUID, name: str | None = None
) -> SolGroup:
    """Create a fresh, open instance (a SolGroup) of the template. Creator only.

    Reuses lifecycle.create_group, so the organizer is enrolled and the instance
    behaves exactly like any group — it just carries template_id + round 1.
    """
    tpl = _owned_template(db, template_id=template_id, creator_id=actor_id)
    if not tpl.active:
        raise SolError(409, "template is archived; reactivate it to spawn instances")
    return _do_spawn(db, tpl, name=name)


def _do_spawn(db: Session, tpl: SolCircleTemplate, *, name: str | None = None) -> SolGroup:
    """Create a fresh open instance of `tpl` (organizer = the creator) and nudge
    the waitlist. Auth is the CALLER's job — spawn_instance checks ownership;
    auto-spawn-on-fill is system-triggered."""
    group = lifecycle.create_group(
        db,
        organizer_id=tpl.creator_id,
        name=(name.strip() if name else tpl.name),
        contribution_amount=tpl.contribution_amount,
        frequency=tpl.frequency,
        member_limit=tpl.member_limit,
        template_id=tpl.id,
        round_number=1,
    )
    # Nudge everyone waiting on this template that a new instance is open (best
    # effort — the spawn already committed; a notify failure must not undo it).
    try:
        from app.services.sol_v1 import waitlist
        waitlist.notify_waitlist(db, template=tpl, group=group)
    except Exception as e:  # noqa: BLE001 — non-critical side effect
        db.rollback()
        logger.warning("sol templates: waitlist notify failed: %s", e)
    return group


def auto_spawn_next_if_full(db: Session, group: SolGroup) -> SolGroup | None:
    """When a join FILLS a template instance, auto-spawn the next open instance so
    the waitlist has somewhere to flow. Returns the new group, or None if nothing
    was spawned. Best-effort — the caller wraps this fail-soft.

    Guards (avoid over-spawning): only fires for a full, still-'open' template
    instance of an ACTIVE template, and only when there is NO OTHER open instance
    of the template that still has room (that one will absorb the next joiners).
    """
    if group.template_id is None or group.status != "open":
        return None
    filled = db.scalar(
        select(func.count(SolMembership.id)).where(SolMembership.group_id == group.id)
    ) or 0
    if filled < group.member_limit:
        return None  # not full yet
    # Lock the template row to serialize concurrent fills of SIBLING instances of
    # the same template: the second caller blocks, then sees the first's committed
    # new instance in the open_with_room check below and returns None (no dup).
    tpl = db.get(SolCircleTemplate, group.template_id, with_for_update=True)
    if tpl is None or not tpl.active:
        return None

    member_ct = (
        select(func.count(SolMembership.id))
        .where(SolMembership.group_id == SolGroup.id)
        .correlate(SolGroup)
        .scalar_subquery()
    )
    open_with_room = db.scalar(
        select(SolGroup.id)
        .where(
            SolGroup.template_id == tpl.id,
            SolGroup.status == "open",
            SolGroup.id != group.id,
            member_ct < SolGroup.member_limit,
        )
        .limit(1)
    )
    if open_with_room is not None:
        return None  # another open instance can still take members
    return _do_spawn(db, tpl)


def start_next_round(db: Session, *, group_id: UUID, actor_id: UUID) -> SolGroup:
    """From a COMPLETED group, start the next round with the SAME members.

    Organizer only. Creates a new SolGroup (round_number + 1, previous_group_id
    set, same template link + terms) and clones every membership so the cohort
    carries over. The new group is 'open' — the organizer locks it to assign the
    fresh payout rotation.
    """
    group = db.get(SolGroup, group_id)
    if group is None:
        raise SolError(404, "group not found")
    if group.organizer_id != actor_id:
        raise SolError(403, "only the organizer can start the next round")
    if group.status != "complete":
        raise SolError(409, "the current round must be complete before starting the next")
    # Idempotency: at most ONE successor per completed group. The source group's
    # status never changes (it stays 'complete'), so guard on the successor link
    # instead — otherwise a double-submit would fork the circle into two divergent
    # round-N+1 groups. A DB partial-unique index (migration 0017) backstops this
    # against a concurrent double-submit (TOCTOU).
    if db.scalar(select(SolGroup.id).where(SolGroup.previous_group_id == group.id)) is not None:
        raise SolError(409, "the next round has already been started for this group")

    members = list(
        db.scalars(select(SolMembership).where(SolMembership.group_id == group.id)).all()
    )

    # ONE atomic transaction: the new group, its organizer, and the cloned cohort
    # commit together (commit=False), so a mid-operation failure can't leave a
    # round group with only the organizer enrolled.
    try:
        new_group = lifecycle.create_group(
            db,
            organizer_id=group.organizer_id,
            name=group.name,
            contribution_amount=group.contribution_amount,
            frequency=group.frequency,
            member_limit=group.member_limit,
            template_id=group.template_id,
            round_number=group.round_number + 1,
            previous_group_id=group.id,
            commit=False,
        )
        for m in members:
            if m.user_id == group.organizer_id:
                continue  # create_group already enrolled the organizer
            db.add(SolMembership(user_id=m.user_id, group_id=new_group.id, role=m.role))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise SolError(409, "the next round has already been started for this group")
    db.refresh(new_group)
    return new_group
