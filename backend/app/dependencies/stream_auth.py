"""Streaming-only auth dependency.

EventSource cannot set Authorization headers, so the SSE endpoint accepts the
JWT via the ``?token=`` query param. This is acceptable while the server binds
to 127.0.0.1 only (Phase A). Phase B must replace this with an HttpOnly cookie
before any public exposure.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import get_db
from app.models.user import User


_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
)


def get_user_from_query_token(
    token: str = Query(..., min_length=10),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(token)
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
