"""Sol v1 — non-custodial ROSCA coordinator API (group lifecycle).

Prefix ``/sol/v1`` — deliberately distinct from the legacy custodial Sol
(``/admin/sol`` admin + ``/sol`` Dwolla webhook) so the two never collide.
Every route is authenticated with the Supabase JWT principal; the acting user's
UUID (``current.id``) is the only identity the handlers trust — never a body
field — so a caller can't act as someone else.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1 import (
    CycleOut,
    GroupCreate,
    GroupDetail,
    GroupOut,
    JoinRequest,
    LockRequest,
    MembershipOut,
)
from app.services.sol_v1 import disclosures, lifecycle, subscription
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1"])


def _raise(err: SolError) -> None:
    raise HTTPException(status_code=err.status_code, detail=err.detail)


def _detail(group, members, cycles) -> GroupDetail:
    return GroupDetail(
        group=GroupOut.model_validate(group),
        members=[MembershipOut.model_validate(m) for m in members],
        cycles=[CycleOut.model_validate(c) for c in cycles],
    )


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")  # anti-spam: cap how fast one IP can create circles
def create_group(
    request: Request,
    body: GroupCreate,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupOut:
    try:
        disclosures.require_consent(db, user_id=current.id)  # legal gate
        subscription.require_active_if_enabled(db, user_id=current.id)  # access gate (opt-in)
        group = lifecycle.create_group(
            db,
            organizer_id=current.id,
            name=body.name,
            contribution_amount=body.contribution_amount,
            frequency=body.frequency,
            member_limit=body.member_limit,
        )
    except SolError as e:
        _raise(e)
    return GroupOut.model_validate(group)


@router.get("/groups", response_model=list[GroupOut])
def my_groups(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GroupOut]:
    groups = lifecycle.list_groups_for_user(db, user_id=current.id)
    return [GroupOut.model_validate(g) for g in groups]


@router.post(
    "/groups/join", response_model=MembershipOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/minute")  # BRUTE-FORCE DEFENSE: cap invite-code guessing per IP
def join_group(
    request: Request,
    body: JoinRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MembershipOut:
    try:
        disclosures.require_consent(db, user_id=current.id)  # legal gate
        subscription.require_active_if_enabled(db, user_id=current.id)  # access gate (opt-in)
        membership = lifecycle.join_group(
            db, user_id=current.id, invite_code=body.invite_code
        )
    except SolError as e:
        _raise(e)
    return MembershipOut.model_validate(membership)


@router.get("/groups/{group_id}", response_model=GroupDetail)
def group_detail(
    group_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupDetail:
    try:
        group, members, cycles = lifecycle.get_group_for_member(
            db, group_id=group_id, user_id=current.id
        )
    except SolError as e:
        _raise(e)
    return _detail(group, members, cycles)


@router.delete("/groups/{group_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("15/minute")
def leave_group(
    group_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """The caller leaves an OPEN circle they're a member of (frees their seat)."""
    try:
        lifecycle.leave_group(db, group_id=group_id, user_id=current.id)
    except SolError as e:
        _raise(e)


@router.delete(
    "/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("15/minute")
def remove_member(
    group_id: UUID,
    user_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """The organizer removes another member from an OPEN circle (frees the seat)."""
    try:
        lifecycle.remove_member(
            db, group_id=group_id, actor_id=current.id, target_user_id=user_id
        )
    except SolError as e:
        _raise(e)


@router.post("/groups/{group_id}/lock", response_model=GroupDetail)
@limiter.limit("30/minute")
def lock_group(
    group_id: UUID,
    request: Request,
    body: LockRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupDetail:
    try:
        lifecycle.lock_group(
            db,
            group_id=group_id,
            actor_id=current.id,
            order_mode=body.order_mode,
            assignment=body.positions,
            start_date=body.start_date,
        )
        group, members, cycles = lifecycle.get_group_for_member(
            db, group_id=group_id, user_id=current.id
        )
    except SolError as e:
        _raise(e)
    return _detail(group, members, cycles)
