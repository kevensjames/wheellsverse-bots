"""Temporary admin auth: shared-secret header.

Stage 11 replaces this with real `admin_users` table auth.
"""
from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or x_admin_token != settings.JWT_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin token required",
        )
