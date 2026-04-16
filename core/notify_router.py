#!/usr/bin/env python3
"""
core/notify_router.py
─────────────────────────────────────────────────────────────────────────────
Notification center API.

GET    /api/notify           — list notifications
GET    /api/notify/count     — unread count
POST   /api/notify/read/{id} — mark one as read
POST   /api/notify/read-all  — mark all as read
DELETE /api/notify/{id}      — delete notification
POST   /api/notify           — create notification (internal use)
─────────────────────────────────────────────────────────────────────────────
"""

from fastapi import APIRouter
from pydantic import BaseModel

from core.notifier import (
    create_notification, delete_notification, get_notifications,
    get_unread_count, mark_all_read, mark_read,
)

router = APIRouter(prefix="/api/notify", tags=["notify"])


class NotifyCreate(BaseModel):
    title: str
    body: str = ""
    type: str = "info"
    action_url: str = ""


@router.get("")
def notify_list(unread_only: bool = False, limit: int = 50):
    return {"notifications": get_notifications(unread_only=unread_only, limit=limit)}


@router.get("/count")
def notify_count():
    return {"unread": get_unread_count()}


@router.post("/read/{nid}")
def notify_mark_read(nid: str):
    mark_read(nid)
    return {"read": True}


@router.post("/read-all")
def notify_read_all():
    count = mark_all_read()
    return {"marked": count}


@router.delete("/{nid}")
def notify_delete(nid: str):
    delete_notification(nid)
    return {"deleted": True}


@router.post("")
def notify_create(req: NotifyCreate):
    nid = create_notification(req.title, req.body, req.type, req.action_url)
    return {"id": nid, "created": True}
