"""Sol v1 template waitlist (Stage 18).

Users WAIT on a circle template; when the creator spawns a new instance,
notify_waitlist() nudges everyone waiting (an in-app 'circle_opening' with the
new instance's invite code) so they can join.

NON-CUSTODIAL: a waitlist entry + its notification carry no money. Reads/writes
only touch coordination records.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sol import SolCircleTemplate, SolGroup, SolWaitlist
from app.services.sol_v1.lifecycle import SolError

logger = logging.getLogger(__name__)


def _require_template(db: Session, template_id: UUID) -> SolCircleTemplate:
    tpl = db.get(SolCircleTemplate, template_id)
    if tpl is None:
        raise SolError(404, "template not found")
    return tpl


def _entry(db: Session, template_id: UUID, user_id: UUID) -> SolWaitlist | None:
    return db.scalar(
        select(SolWaitlist).where(
            SolWaitlist.template_id == template_id, SolWaitlist.user_id == user_id
        )
    )


def join_waitlist(db: Session, *, template_id: UUID, user_id: UUID) -> SolWaitlist:
    """Add the user to a template's waitlist (idempotent — one entry per user)."""
    _require_template(db, template_id)
    existing = _entry(db, template_id, user_id)
    if existing is not None:
        return existing
    entry = SolWaitlist(template_id=template_id, user_id=user_id)
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:  # concurrent double-join → the UNIQUE won; take theirs
        db.rollback()
        return _entry(db, template_id, user_id)
    db.refresh(entry)
    return entry


def leave_waitlist(db: Session, *, template_id: UUID, user_id: UUID) -> bool:
    """Remove the user from the waitlist. Returns True if a row was removed."""
    entry = _entry(db, template_id, user_id)
    if entry is None:
        return False
    db.delete(entry)
    db.commit()
    return True


def list_waitlist(db: Session, *, template_id: UUID, creator_id: UUID) -> list[SolWaitlist]:
    """The users waiting on a template — visible ONLY to the template creator."""
    tpl = _require_template(db, template_id)
    if tpl.creator_id != creator_id:
        raise SolError(403, "only the template creator can see its waitlist")
    return list(
        db.scalars(
            select(SolWaitlist)
            .where(SolWaitlist.template_id == template_id)
            .order_by(SolWaitlist.created_at)  # FIFO
        ).all()
    )


def my_waitlists(db: Session, *, user_id: UUID) -> list[SolWaitlist]:
    """Every template the caller is waiting on (newest first)."""
    return list(
        db.scalars(
            select(SolWaitlist)
            .where(SolWaitlist.user_id == user_id)
            .order_by(SolWaitlist.created_at.desc())
        ).all()
    )


def notify_waitlist(db: Session, *, template: SolCircleTemplate, group: SolGroup) -> int:
    """Notify everyone waiting on `template` that a new instance (`group`) is open.

    Fail-soft: a notification error never breaks the spawn that triggered it.
    Idempotent per (user, group) via the notification dedup key. Returns the count
    of new notifications created.
    """
    from app.services.sol_v1 import notifications

    try:
        waiters = db.scalars(
            select(SolWaitlist.user_id).where(SolWaitlist.template_id == template.id)
        ).all()
    except Exception as e:  # fully fail-soft: never break the spawn that called us
        db.rollback()
        logger.warning("sol waitlist: could not read waitlist: %s", e)
        return 0
    title = "A circle just opened"
    body = f"A new '{template.name}' circle is open — join with invite code {group.invite_code}."
    created = 0
    for uid in waiters:
        try:
            if notifications.emit(
                db, user_id=uid, kind="circle_opening", title=title, body=body,
                dedup_key=f"circle_opening:{group.id}",
            ) is not None:
                created += 1
        except Exception as e:  # a bad notify must not abort the spawn/loop
            db.rollback()
            logger.warning("sol waitlist: notify failed for %s: %s", uid, e)
    return created
