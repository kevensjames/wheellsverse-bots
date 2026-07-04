"""Sol v1 notifications API — a member's own in-app inbox.

  GET  /sol/v1/notifications              list (newest first; ?unread_only, ?limit)
  GET  /sol/v1/notifications/unread-count badge count
  POST /sol/v1/notifications/{id}/read    mark one read (ownership-scoped)
  POST /sol/v1/notifications/read-all     mark all read

Read/patch only — the daily sweep that CREATES notifications runs in the
scheduler. Every mutation is scoped to the caller's own user_id, so a member can
never touch another member's notifications. NON-CUSTODIAL: no money here.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_notifications import (
    MarkedOut,
    NotificationListOut,
    UnreadCountOut,
)
from app.services.sol_v1 import notifications as notif_svc

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-notifications"])


@router.get("/notifications", response_model=NotificationListOut)
def my_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListOut:
    items = notif_svc.list_for_user(
        db, user_id=current.id, unread_only=unread_only, limit=limit
    )
    unread = notif_svc.unread_count(db, user_id=current.id)
    return NotificationListOut(items=items, unread=unread)


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def my_unread_count(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountOut:
    return UnreadCountOut(count=notif_svc.unread_count(db, user_id=current.id))


@router.post("/notifications/{notification_id}/read", response_model=MarkedOut)
@limiter.limit("60/minute")
def mark_one_read(
    notification_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkedOut:
    # Ownership is enforced inside mark_read (user_id in the WHERE) — an id that
    # isn't the caller's simply matches nothing and returns updated=0 (no leak).
    changed = notif_svc.mark_read(db, user_id=current.id, notification_id=notification_id)
    return MarkedOut(updated=1 if changed else 0)


@router.post("/notifications/read-all", response_model=MarkedOut)
@limiter.limit("60/minute")
def mark_all_read(
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkedOut:
    return MarkedOut(updated=notif_svc.mark_all_read(db, user_id=current.id))
