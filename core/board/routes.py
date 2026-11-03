"""HTTP routes for the daily numbers board (replica/architecture.md, API).

  * pages:  GET /board/login, POST /board/auth/login, POST /board/auth/logout
  * router: /api/board/*, every route behind require_owner at router level,
            so a route added here later cannot skip it. The board API does its
            own auth, so api_key_middleware leaves /api/board/ to it. A write
            (POST) also needs the board's own Origin (require_owner checks it).

Handlers are plain def: FastAPI runs the blocking Supabase calls in its
threadpool, off the event loop.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from core.board import auth
from core.board import day as board_day
from core.board.auth import require_owner
from core.board.connectors import stripe_sync

ROOT = Path(__file__).resolve().parents[2]
LOGIN_PAGE = ROOT / "frontend" / "admin" / "board_login.html"

# The sign-in page is static and has no inline data, so it can be strict. It may
# show inside the admin pages' own frames (the /admin dashboard frames /admin/*).
_LOGIN_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'"
    ),
}

pages = APIRouter(tags=["board-auth"])
router = APIRouter(prefix="/api/board", tags=["board"], dependencies=[Depends(require_owner)])


def _refusal(status: int, message: str, retry_after: int | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse({"error": message}, status_code=status, headers=headers)


@pages.get("/board/login", response_class=HTMLResponse, include_in_schema=False)
def board_login_page():
    """The sign-in form (S23): the same static bytes for every visitor."""
    if not LOGIN_PAGE.exists():
        return HTMLResponse("<h1>board_login.html not found</h1>", status_code=404)
    return HTMLResponse(LOGIN_PAGE.read_text(encoding="utf-8"), headers=_LOGIN_PAGE_HEADERS)


@pages.post("/board/auth/login", include_in_schema=False)
def board_sign_in(
    request: Request,
    email: str = Form(..., max_length=320),
    password: str = Form(..., max_length=1024),
    next_path: str = Form("", alias="next", max_length=8192),   # safe_next keeps <= 2048
):
    """F11: one password grant, then a 7-day owner session in an HttpOnly cookie,
    and a known-device cookie that keeps this browser out of other people's
    sign-in backoff. 303 to `next` (a relative path on this site) or the board;
    401 wrong email or password; 403 not the owner or not this site's page; 429
    backing off; 502 the sign-in service failed; 503 not configured."""
    try:
        token, device = auth.sign_in(request, email, password)
    except auth.SignInError as e:
        return _refusal(e.status, e.message, e.retry_after)
    response = RedirectResponse(auth.safe_next(next_path), status_code=303)
    auth.set_session_cookie(response, token)
    auth.set_device_cookie(response, device)
    return response


@pages.post("/board/auth/logout", include_in_schema=False)
def board_sign_out(request: Request):
    """Revoke this browser's session now and clear the cookie; 303 to sign-in."""
    cfg = auth.board_settings()
    if cfg is None:
        response: Response = _refusal(503, "Sign-in is not configured on the server.")
        auth.clear_session_cookie(response)
        return response
    if not auth.same_origin(request):
        return _refusal(403, "Sign out from this site's own pages.")
    try:
        auth.revoke_session(cfg, request.cookies.get(auth.SESSION_COOKIE))
    except auth.SessionStoreError:
        return _refusal(502, "Could not sign out. Try again shortly.")
    response = RedirectResponse(auth.LOGIN_PATH, status_code=303)
    auth.clear_session_cookie(response)
    return response


@router.get("/scoreboard")
def board_scoreboard() -> dict:
    """The scoreboard cards (core/scoreboard.py snapshot), for the signed-in owner."""
    from core.scoreboard import snapshot
    return snapshot()


@router.get("/opportunities")
def board_opportunities(limit: int = Query(8, ge=1, le=50)) -> dict:
    """The opportunity scan (core/opportunities.py), for the signed-in owner."""
    from core.opportunities import scan
    return scan(limit=limit)


@router.get("/day")
def board_day_view(
    day: Optional[str] = Query(None, alias="date", max_length=10, description="YYYY-MM-DD"),
    d: Optional[str] = Query(None, max_length=10, description="the same as date"),
) -> JSONResponse:
    """F02, the morning view of one New York calendar day: revenue with every
    sale, and the Stripe source's state. Default: yesterday in New York. A
    source that is not connected reads null, never $0."""
    if day and d and day != d:
        raise HTTPException(422, "date and d disagree")
    raw = day or d
    try:
        wanted = board_day.parse_day(raw) if raw else None
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD") from None
    return JSONResponse(board_day.day_view(wanted), headers={"Cache-Control": "no-store"})


# Runs one sync now (the page's Sync button). One a minute per source, here.
SYNCS = {"stripe": stripe_sync}       # source -> connector module with run(trigger, days)
SYNC_EVERY = 60.0     # seconds
_sync_lock = threading.Lock()
_last_sync: dict[str, float] = {}
_SYNC_STATUS = {"ok": 200, "busy": 409, "skipped": 503, "failed": 502}


@router.post("/sync/{source}")
def board_sync(
    source: str = PathParam(..., max_length=32),
    days: Optional[int] = Query(None, ge=1, le=31, description="read at least the last N days"),
) -> JSONResponse:
    """F01: one sync run of `source` now, claimed like any other run. Answers
    the run: 200 ok, 409 another run is in progress, 429 asked less than a
    minute ago, 502 failed, 503 the source's key is not set."""
    connector = SYNCS.get(source)
    if connector is None:
        raise HTTPException(404, "Unknown source")
    with _sync_lock:
        wait = _last_sync.get(source, -SYNC_EVERY) + SYNC_EVERY - time.monotonic()
        if wait > 0:
            return JSONResponse({"error": "One sync a minute per source"}, status_code=429,
                                headers={"Retry-After": str(int(wait) + 1), "Cache-Control": "no-store"})
        _last_sync[source] = time.monotonic()
    result = connector.run(trigger="owner", days=days)
    return JSONResponse(result, status_code=_SYNC_STATUS.get(result.get("status"), 500),
                        headers={"Cache-Control": "no-store"})
