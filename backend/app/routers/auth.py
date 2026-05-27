from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.cookie_auth import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user_id: UUID, response: Response) -> TokenResponse:
    """Mint access+refresh tokens, set cookies, return JSON body.

    Body still includes the tokens so API clients (without cookies) keep
    working; cookies are layered on for browser flows.
    """
    sub = str(user_id)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # brute-force / fake-account-spam defense
def signup(
    request: Request,  # required by slowapi; do not remove
    body: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = body.email.strip().lower()
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue_tokens(user.id, response)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # credential-stuffing defense
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = body.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    # Same error message for unknown email and bad password — prevents enumeration.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return _issue_tokens(user.id, response)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")  # refresh is cheap but still rate-bound
def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: Session = Depends(get_db),
    nai_refresh: str | None = Cookie(default=None),
) -> TokenResponse:
    """Rotate tokens using either the cookie OR the JSON body.

    The cookie path covers browser flows (UI); the body path covers API clients.
    """
    invalid = HTTPException(status_code=401, detail="Invalid refresh token")
    token = (body.refresh_token if body else None) or nai_refresh
    if not token:
        raise invalid
    try:
        payload = decode_token(token)
    except JWTError:
        raise invalid

    if payload.get("type") != "refresh":
        raise invalid

    sub = payload.get("sub")
    if not sub:
        raise invalid
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise invalid

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid

    return _issue_tokens(user.id, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    """Clear cookies. Returns 204 No Content — no body needed."""
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
