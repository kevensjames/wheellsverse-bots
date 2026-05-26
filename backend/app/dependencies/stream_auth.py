"""Streaming-only auth dependency.

Stage 6 update: SSE now prefers HttpOnly cookies (browsers auto-send them on
same-origin EventSource requests). The ``?token=`` query param is kept ONLY as
a transitional fallback — it logs a deprecation warning on use and will be
removed once all UI callers are migrated.

Why this matters: query-param tokens leak into browser history, referer
headers, and access logs. Cookies don't.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Query, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)


_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
)


def get_user_for_stream(
    nai_access: str | None = Cookie(default=None),
    token: str | None = Query(default=None, min_length=10),
    db: Session = Depends(get_db),
) -> User:
    """Cookie-preferred, query-param fallback (deprecated).

    The cookie path is the canonical Stage 6 flow. The query-param path stays
    alive only so existing UI sessions don't break mid-migration.
    """
    presented = nai_access
    if not presented and token:
        # Surface this so we can grep logs and confirm when nothing uses the
        # legacy path anymore — that's the signal to delete it.
        logger.warning("SSE auth used deprecated ?token= query param")
        presented = token
    if not presented:
        raise _INVALID

    try:
        payload = decode_token(presented)
    except JWTError:
        raise _INVALID
    if payload.get("type") != "access":
        raise _INVALID
    sub = payload.get("sub")
    if not sub:
        raise _INVALID
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise _INVALID
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _INVALID
    return user


# Backward-compat alias — callers still import this name.
get_user_from_query_token = get_user_for_stream
