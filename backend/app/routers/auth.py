"""Path X: Supabase Auth-backed signup/login/refresh/logout/me.

Stage 6 originally wrote to a self-managed ``public.users`` table that doesn't
exist in production (canonical Supabase uses auth.users + profiles trigger).
This rewrite delegates identity to Supabase Auth; cookies, rate limits, and
security headers from earlier Stage 6 work are unchanged.

Endpoints
- POST /auth/signup    create auth.users row (trigger → profiles), auto-login,
                       set cookies, return tokens
- POST /auth/login     password grant via Supabase, set cookies, return tokens
- POST /auth/refresh   refresh-token grant (cookie OR JSON body), rotate
- POST /auth/logout    clear cookies
- GET  /auth/me        return profile-backed UserResponse
"""
# NOTE: deliberately NO `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper resolves this module's annotations against
# ITS OWN namespace, where SignupRequest/LoginRequest don't exist. With PEP-563
# string annotations that breaks the body parameter: pydantic 2.9 raises
# PydanticUndefinedAnnotation at route definition, and pydantic 2.13 silently
# demotes the body to a QUERY param so every valid signup/login 422s
# ("loc": ["query","body"]). Keeping annotations eager makes both work.
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.cookie_auth import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services import supabase_auth
from app.services.supabase_auth import AuthError

import logging

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])


def _emit_tokens(tokens: dict, response: Response) -> TokenResponse:
    """Set cookies + return JSON body. Same UX as Stage 6: cookies for the
    browser, JSON tokens for API clients without a cookie jar."""
    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )


def _http_from_auth(err: AuthError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def signup(
    request: Request,
    body: SignupRequest,
    response: Response,
) -> TokenResponse:
    """Create the auth.users row (trigger creates profile) and auto-login."""
    email = body.email.strip().lower()
    try:
        supabase_auth.create_user(email, body.password, full_name=body.full_name)
    except AuthError as e:
        raise _http_from_auth(e)
    # Fire signup alert in the background — runs in a daemon thread, won't
    # block the response or break if Telegram is unreachable.
    from app.services import observability
    observability.alert_signup(email)
    # Auto-login so the signup response carries usable cookies + tokens.
    try:
        tokens = supabase_auth.password_login(email, body.password)
    except AuthError as e:
        # If the create succeeded but the immediate login somehow didn't,
        # don't pretend signup failed — but surface a 500 so the operator
        # notices. The user CAN log in next time.
        raise HTTPException(
            status_code=500,
            detail=f"signup succeeded but auto-login failed: {e.detail}",
        )
    return _emit_tokens(tokens, response)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
) -> TokenResponse:
    try:
        tokens = supabase_auth.password_login(body.email.strip().lower(), body.password)
    except AuthError as e:
        raise _http_from_auth(e)
    return _emit_tokens(tokens, response)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
) -> dict:
    """Trigger a password-reset email. Always returns the same neutral 202
    regardless of whether the email exists (anti-enumeration). Actual delivery
    requires Supabase SMTP configured (operator); a missing config is swallowed
    so this endpoint can't be used to probe which emails are registered."""
    try:
        supabase_auth.request_password_reset(body.email.strip().lower())
    except Exception as e:  # config/network — never leak to the caller
        logger.warning("forgot-password suppressed error: %s", e)
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.get("/me/export")
def export_my_data(
    current_user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GDPR Art. 20 — the caller's own data as JSON (profile + conversations +
    messages + memories). All tenanted by user_id; in multi-user mode the
    companion sidecars write nothing (companion_mode), so this is complete."""
    from app.models.conversation import Conversation, Message
    from app.models.memory import Memory

    uid = current_user.id
    prof = db.execute(
        text("SELECT id, email, name, tier, created_at FROM public.profiles WHERE id = :id"),
        {"id": str(uid)},
    ).mappings().first()
    convs = db.query(Conversation).filter(Conversation.user_id == uid).order_by(Conversation.created_at).all()
    msgs = db.query(Message).filter(Message.user_id == uid).order_by(Message.created_at).all()
    mems = db.query(Memory).filter(Memory.user_id == uid).order_by(Memory.created_at).all()
    return {
        "profile": dict(prof) if prof else None,
        "conversations": [
            {"id": str(c.id), "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at}
            for c in convs
        ],
        "messages": [
            {"id": str(m.id), "conversation_id": str(m.conversation_id), "role": m.role,
             "content": m.content, "created_at": m.created_at}
            for m in msgs
        ],
        "memories": [
            {"id": str(m.id), "content": m.content, "type": m.memory_type, "created_at": m.created_at}
            for m in mems
        ],
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    response: Response,
    current_user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GDPR Art. 17 — self-serve account deletion. Deleting the profiles row
    cascades (ON DELETE CASCADE) to conversations, messages, memories,
    subscriptions, api_keys, and every other user-owned table. The Supabase auth
    identity is removed too (best-effort). In multi-user mode no untenanted
    sidecar PII exists, so this is a COMPLETE erasure."""
    uid = str(current_user.id)
    try:
        supabase_auth.delete_user(uid)
    except Exception as e:  # Supabase unconfigured/unreachable — still purge our DB
        logger.warning("delete /me: supabase delete_user failed (continuing): %s", e)
    db.execute(text("DELETE FROM public.profiles WHERE id = :id"), {"id": uid})
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    nai_refresh: str | None = Cookie(default=None),
) -> TokenResponse:
    """Cookie-first refresh; JSON body kept for API-client backward compat."""
    presented = (body.refresh_token if body else None) or nai_refresh
    if not presented:
        raise HTTPException(status_code=401, detail="missing refresh token")
    try:
        tokens = supabase_auth.refresh_session(presented)
    except AuthError as e:
        raise _http_from_auth(e)
    return _emit_tokens(tokens, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> Response:
    """Revoke the Supabase session (invalidates the refresh token so it can't be
    replayed) and clear cookies. Idempotent: a missing/expired token is a no-op.
    The access token remains valid until expiry — see supabase_auth.sign_out."""
    from app.dependencies.cookie_auth import ACCESS_COOKIE
    token = request.cookies.get(ACCESS_COOKIE) or ""
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    try:
        supabase_auth.sign_out(token)
    except Exception as e:  # never let revocation failure block logout
        logger.warning("logout: sign_out suppressed error: %s", e)
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(
    current_user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Pull profile-side fields (name, tier, created_at) by id.

    The Supabase JWT already carries id+email, but the UI may want display
    name and plan tier — both live on profiles.
    """
    row = db.execute(
        text(
            "SELECT id, email, name, tier, created_at "
            "FROM public.profiles WHERE id = :id"
        ),
        {"id": str(current_user.id)},
    ).mappings().first()
    if row is None:
        # Trigger should have created this; if not, treat as invalid session.
        raise HTTPException(status_code=404, detail="profile not found")
    return UserResponse(
        id=row["id"],
        email=row["email"] or current_user.email or "",
        full_name=row["name"],
        tier=row["tier"],
        created_at=row["created_at"],
    )
