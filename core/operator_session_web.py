"""FastAPI adapter for the unified operator session (Phase P2 wiring).

Framework layer over ``core/operator_session.py``. Import-light (only fastapi +
operator_session), so it is testable with a minimal TestClient app WITHOUT
booting either 15k-line production app. Both App A (core/api.py) and App B
(backend/app/main.py) call ``install_operator_session(app, cfg)`` exactly once.

Guarantee: when ``cfg.enabled`` is False nothing is registered and there is ZERO
behavior change — the session routes don't exist and the cookie is never
consulted. Existing X-API-Key / X-Admin-Token paths are untouched either way.

The two apps share one ``SESSION_SIGNING_SECRET`` so a cookie minted by App A
validates in App B and vice-versa — that is what lets one login authenticate the
admin shell, the KAI orb/drawer, and the Nexus as the same principal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import operator_session as osess
from core.operator_session import Principal

COOKIE_NAME = "wv_session"


@dataclass(frozen=True)
class SessionConfig:
    """All config passed in explicitly (each app sources it its own way:
    App A from os.getenv, App B from pydantic Settings)."""
    enabled: bool
    owner_key: Optional[str]
    admin_token: Optional[str]
    session_secret: Optional[str]
    secure_cookies: bool = True          # False only in local dev (http)
    ttl_seconds: int = 43200             # 12h
    cookie_name: str = COOKIE_NAME


def principal_for_request(request: Request, cfg: SessionConfig) -> Optional[Principal]:
    """Resolve the one Principal for a request from headers + the session cookie.
    Returns None (anonymous) on anything invalid — never a privileged default."""
    return osess.resolve_principal(
        x_api_key=request.headers.get("x-api-key"),
        x_admin_token=request.headers.get("x-admin-token"),
        session_cookie=request.cookies.get(cfg.cookie_name),
        owner_key=cfg.owner_key,
        admin_token=cfg.admin_token,
        session_secret=cfg.session_secret,
    )


def _set_session_cookie(resp: Response, token: str, cfg: SessionConfig) -> None:
    resp.set_cookie(
        key=cfg.cookie_name,
        value=token,
        max_age=cfg.ttl_seconds,
        httponly=True,
        secure=cfg.secure_cookies,
        samesite="lax",
        path="/",
    )


class _LoginBody(BaseModel):
    # The operator presents an existing secret (owner API key or admin token)
    # during migration. Accepted over HTTPS in the POST body; never echoed back.
    secret: str


def make_session_router(cfg: SessionConfig) -> APIRouter:
    router = APIRouter(tags=["operator-session"])

    @router.post("/admin/session/login")
    async def login(body: _LoginBody):
        if not cfg.session_secret:
            return JSONResponse({"error": "session_not_configured"}, status_code=503)
        # Reuse the pure resolver: owner key beats admin token. Constant-time.
        principal = osess.resolve_secret(
            x_api_key=body.secret,
            x_admin_token=body.secret,
            owner_key=cfg.owner_key,
            admin_token=cfg.admin_token,
        )
        if principal is None:
            # Do NOT echo the secret or say which scheme failed.
            return JSONResponse({"error": "invalid_credentials"}, status_code=401)
        token = osess.mint_session(principal.role, secret=cfg.session_secret,
                                   ttl_seconds=cfg.ttl_seconds)
        resp = JSONResponse({"role": principal.role,
                             "scopes": sorted(principal.scopes)})
        _set_session_cookie(resp, token, cfg)
        return resp

    @router.post("/admin/session/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(cfg.cookie_name, path="/")
        return resp

    @router.get("/admin/session/whoami")
    async def whoami(request: Request):
        p = principal_for_request(request, cfg)
        if p is None:
            return {"authenticated": False, "role": "anonymous", "scopes": []}
        return {"authenticated": True, "role": p.role,
                "scopes": sorted(p.scopes), "source": p.source}

    return router


def install_operator_session(app: FastAPI, cfg: SessionConfig) -> bool:
    """Register the session routes iff enabled. Returns whether it installed, so
    the caller can log it. No-op (and no route surface) when disabled."""
    if not cfg.enabled:
        return False
    app.include_router(make_session_router(cfg))
    return True
