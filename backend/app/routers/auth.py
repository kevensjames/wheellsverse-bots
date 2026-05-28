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
from __future__ import annotations

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
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services import supabase_auth
from app.services.supabase_auth import AuthError


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
def logout(response: Response) -> Response:
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
