"""Temporary admin auth: shared-secret header.

Stage 11 replaces this with real `admin_users` table auth.
"""
from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Path X note: now reads settings.admin_token (alias of ADMIN_TOKEN with
    JWT_SECRET_KEY fallback). When operators rotate to a dedicated ADMIN_TOKEN
    env var, this keeps working; once JWT_SECRET_KEY can be removed entirely,
    the fallback in config.admin_token goes too."""
    expected = settings.admin_token
    if not x_admin_token or not expected or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin token required",
        )
