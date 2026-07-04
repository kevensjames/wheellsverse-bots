"""Sol v1 templates API — the reusable blueprint + instance/round spawning.

  POST /sol/v1/templates                 create a blueprint (consent-gated)
  GET  /sol/v1/templates                 the caller's blueprints
  GET  /sol/v1/templates/{id}            a blueprint + its spawned instances
  POST /sol/v1/templates/{id}/spawn      spawn a fresh open instance (a group)
  POST /sol/v1/groups/{id}/next-round    start the next round with the same members

Every route is JWT-authed; the acting identity is always current.id. Rate-limited
+ consent-gated like the lifecycle routes. NON-CUSTODIAL: blueprints/instances are
coordination records only — members pay each other directly.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1 import GroupOut
from app.schemas.sol_v1_templates import (
    SpawnRequest,
    TemplateCreate,
    TemplateDetail,
    TemplateOut,
    WaitlistEntryOut,
)
from app.services.sol_v1 import disclosures, subscription, templates, waitlist
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-templates"])


def _raise(err: SolError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")
def create_template(
    request: Request,
    body: TemplateCreate,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemplateOut:
    try:
        disclosures.require_consent(db, user_id=current.id)  # same non-custodial gate as create
        subscription.require_active_if_enabled(db, user_id=current.id)
        tpl = templates.create_template(
            db, creator_id=current.id, name=body.name,
            contribution_amount=body.contribution_amount, frequency=body.frequency,
            member_limit=body.member_limit, visibility=body.visibility,
        )
    except SolError as e:
        _raise(e)
    return TemplateOut.model_validate(tpl)


@router.get("/templates", response_model=list[TemplateOut])
def my_templates(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TemplateOut]:
    return [TemplateOut.model_validate(t) for t in templates.list_templates(db, creator_id=current.id)]


@router.get("/templates/{template_id}", response_model=TemplateDetail)
def template_detail(
    template_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    try:
        tpl = templates.get_template(db, template_id=template_id, creator_id=current.id)
        instances = templates.instances_of(db, template_id=template_id, creator_id=current.id)
    except SolError as e:
        _raise(e)
    return TemplateDetail(
        template=TemplateOut.model_validate(tpl),
        instances=[GroupOut.model_validate(g) for g in instances],
    )


@router.post("/templates/{template_id}/spawn", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")
def spawn_instance(
    template_id: UUID,
    request: Request,
    body: SpawnRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupOut:
    try:
        disclosures.require_consent(db, user_id=current.id)
        subscription.require_active_if_enabled(db, user_id=current.id)
        group = templates.spawn_instance(
            db, template_id=template_id, actor_id=current.id, name=body.name
        )
    except SolError as e:
        _raise(e)
    return GroupOut.model_validate(group)


@router.post("/groups/{group_id}/next-round", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")
def start_next_round(
    group_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupOut:
    try:
        # next-round CREATES a new circle → same gates as create/join/spawn
        disclosures.require_consent(db, user_id=current.id)
        subscription.require_active_if_enabled(db, user_id=current.id)
        group = templates.start_next_round(db, group_id=group_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return GroupOut.model_validate(group)


# ── waitlist ──────────────────────────────────────────────────────────────────


@router.post("/templates/{template_id}/waitlist", response_model=WaitlistEntryOut,
             status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
def join_waitlist(
    template_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WaitlistEntryOut:
    try:
        entry = waitlist.join_waitlist(db, template_id=template_id, user_id=current.id)
    except SolError as e:
        _raise(e)
    return WaitlistEntryOut.model_validate(entry)


@router.delete("/templates/{template_id}/waitlist", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
def leave_waitlist(
    template_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    waitlist.leave_waitlist(db, template_id=template_id, user_id=current.id)


@router.get("/templates/{template_id}/waitlist", response_model=list[WaitlistEntryOut])
def template_waitlist(
    template_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WaitlistEntryOut]:
    try:
        entries = waitlist.list_waitlist(db, template_id=template_id, creator_id=current.id)
    except SolError as e:
        _raise(e)
    return [WaitlistEntryOut.model_validate(w) for w in entries]


@router.get("/waitlists", response_model=list[WaitlistEntryOut])
def my_waitlists(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WaitlistEntryOut]:
    return [WaitlistEntryOut.model_validate(w) for w in waitlist.my_waitlists(db, user_id=current.id)]
