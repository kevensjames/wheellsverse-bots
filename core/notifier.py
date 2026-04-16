#!/usr/bin/env python3
"""
core/notifier.py
─────────────────────────────────────────────────────────────────────────────
In-app notification center.
Stores notifications in the notifications table (created by chat_db.init_db).

API (via notify_router):
  GET  /api/notify           — list notifications
  GET  /api/notify/count     — unread count
  POST /api/notify/read/{id} — mark one as read
  POST /api/notify/read-all  — mark all as read
  DELETE /api/notify/{id}    — delete one
─────────────────────────────────────────────────────────────────────────────
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List

from core.chat_db import _get_conn, _lock

logger = logging.getLogger("notifier")


def create_notification(
    title: str,
    body: str = "",
    type: str = "info",
    action_url: str = "",
) -> str:
    """
    Create a notification.
    type: info | warning | error | success
    Returns notification ID.
    """
    nid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO notifications(id,title,body,type,read,created_at,action_url) VALUES(?,?,?,?,0,?,?)",
            (nid, title, body, type, now, action_url)
        )
        conn.commit()
    return nid


def get_notifications(unread_only: bool = False, limit: int = 50) -> List[Dict]:
    conn = _get_conn()
    query = "SELECT id,title,body,type,read,created_at,action_url FROM notifications"
    if unread_only:
        query += " WHERE read=0"
    query += " ORDER BY created_at DESC LIMIT ?"
    with _lock:
        rows = conn.execute(query, (limit,)).fetchall()
    return [
        {"id": r[0], "title": r[1], "body": r[2], "type": r[3],
         "read": bool(r[4]), "created_at": r[5], "action_url": r[6]}
        for r in rows
    ]


def get_unread_count() -> int:
    conn = _get_conn()
    with _lock:
        return conn.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]


def mark_read(notification_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        conn.execute("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))
        conn.commit()
    return True


def mark_all_read() -> int:
    conn = _get_conn()
    with _lock:
        count = conn.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]
        conn.execute("UPDATE notifications SET read=1 WHERE read=0")
        conn.commit()
    return count


def delete_notification(notification_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM notifications WHERE id=?", (notification_id,))
        conn.commit()
    return True


def delete_old(days: int = 30) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    with _lock:
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE created_at < ?", (cutoff,)
        ).fetchone()[0]
        conn.execute("DELETE FROM notifications WHERE created_at < ?", (cutoff,))
        conn.commit()
    return count


# ─── Convenience hooks ────────────────────────────────────────────────────────

def notify_bot_event(bot_name: str, event: str, details: str = "") -> str:
    """Notify about a bot lifecycle event (crash, start, stop)."""
    type_map = {"crashed": "error", "started": "success", "stopped": "info", "restarted": "warning"}
    ntype = type_map.get(event.lower(), "info")
    return create_notification(
        title=f"Bot {bot_name} {event}",
        body=details,
        type=ntype,
        action_url="/dashboard#botctl",
    )


def notify_code_event(name: str, event: str, details: str = "") -> str:
    """Notify about a code run event."""
    ntype = "success" if event == "completed" else "error"
    return create_notification(
        title=f"Code run '{name}' {event}",
        body=details,
        type=ntype,
        action_url="/dashboard#codestudio",
    )
