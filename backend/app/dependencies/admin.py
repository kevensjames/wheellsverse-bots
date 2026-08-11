"""Temporary admin auth: shared-secret header.

Stage 11 replaces this with real `admin_users` table auth.

Merge Phase P2: when OPERATOR_SESSION_ENABLED is on (default OFF), this ALSO
accepts a valid unified `wv_session` cookie signed with SESSION_SIGNING_SECRET —
the same cookie App A mints — so one operator login authenticates both apps.
Legacy X-Admin-Token keeps working regardless of the flag.
"""
import hmac
import sys as _sys
from pathlib import Path as _Path

from fastapi import Header, HTTPException, Request, status

from app.config import settings

# App B runs with `backend/` on sys.path (package `app`); the shared, pure
# security core lives at the repo root as `core/`. Add the repo root so
# `core.operator_session` is importable here without duplicating the logic.
_REPO_ROOT = str(_Path(__file__).resolve().parents[3])
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)


def _session_cookie_ok(request: Request) -> bool:
    """True iff the unified session is enabled AND the request carries a valid
    signed wv_session cookie. Fail-closed on any error / when disabled."""
    if not getattr(settings, "OPERATOR_SESSION_ENABLED", False):
        return False
    secret = getattr(settings, "SESSION_SIGNING_SECRET", "") or ""
    if not secret:
        return False
    try:
        from core.operator_session import verify_session
        return verify_session(request.cookies.get("wv_session"), secret=secret) is not None
    except Exception:
        return False


def require_admin_token(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Accept the legacy X-Admin-Token (now constant-time compared) OR, when the
    unified-session flag is on, a valid wv_session cookie. Fail-closed otherwise."""
    expected = settings.admin_token
    if x_admin_token and expected and hmac.compare_digest(x_admin_token, expected):
        return
    if _session_cookie_ok(request):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin token required",
    )
