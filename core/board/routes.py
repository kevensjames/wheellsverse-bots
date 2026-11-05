"""HTTP routes for the daily numbers board (replica/architecture.md, API):
/api/board/*.

There is no board sign-in: the board uses production's owner login, the
operator session. Every route here is owner-only through production's check,
twice: api_key_middleware gates every /api/ path that is not public (and
/api/board/ is not), and core/api.py includes this router with
Depends(verify_api_key). Either way the caller needs the X-API-Key header
(API_KEY) or an owner wv_session cookie (core/operator_session_web.py); a
cookie on a write (POST) must also pass production's CSRF origin check. Every
refusal is a 401. This module must not import core.api (that import would be
circular), which is why the dependency is attached where the router is
included.

Handlers are plain def: FastAPI runs the blocking Supabase calls in its
threadpool, off the event loop.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from fastapi.responses import JSONResponse

from core.board import day as board_day
from core.board.connectors import instantly_sync, kit_sync, meta_sync, stripe_sync

log = logging.getLogger("board.routes")

router = APIRouter(prefix="/api/board", tags=["board"])


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
    """F02, the morning view of one New York calendar day: Toodle opt-ins,
    SiteBoost replies, revenue with every sale, Meta spend, the stop rule's
    verdict, and each source's state (Stripe, Kit, Instantly, Meta). Default:
    yesterday in New York. A source that is not connected reads null, never 0."""
    if day and d and day != d:
        raise HTTPException(422, "date and d disagree")
    raw = day or d
    try:
        wanted = board_day.parse_day(raw) if raw else None
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD") from None
    return JSONResponse(board_day.day_view(wanted), headers={"Cache-Control": "no-store"})


# Runs one sync now (the page's "Sync now" buttons). One a minute per source, here.
# source -> connector module with run(trigger, days)
SYNCS = {"stripe": stripe_sync, "kit": kit_sync, "instantly": instantly_sync, "meta_ads": meta_sync}
SYNC_EVERY = 60.0     # seconds
SYNC_WAIT = 50.0      # seconds the route waits for its run: Cloudflare cuts a request at about 100
SYNC_RUNNING = "Still running. The board updates when it finishes."
_sync_lock = threading.Lock()
_last_sync: dict[str, float] = {}
_SYNC_STATUS = {"ok": 200, "busy": 409, "skipped": 503, "failed": 502}


def _owner_run(source: str, connector, days: Optional[int], done: dict) -> None:
    """One owner-triggered run, in a worker thread of its own. run() records
    its own failures and never raises; what escapes it anyway is a failed
    run here, logged by its type only (its text can carry a URL or a key)."""
    try:
        done["result"] = connector.run(trigger="owner", days=days)
    except Exception as e:  # noqa: BLE001 — the last guard of a worker thread
        log.error("%s sync stopped unexpectedly (%s)", source, type(e).__name__)
        done["result"] = {"source_id": source, "status": "failed", "error": "the sync stopped unexpectedly"}


@router.post("/sync/{source}")
def board_sync(
    source: str = PathParam(..., max_length=32),
    days: Optional[int] = Query(None, ge=1, le=31, description="read at least the last N days"),
) -> JSONResponse:
    """F01: one sync run of `source` (stripe, kit, instantly or meta_ads) now,
    claimed like any other run. The run goes in a worker thread of its own and
    the route waits SYNC_WAIT seconds at most, so the owner always has an
    answer well before Cloudflare cuts the request. A run that ends in time is
    answered: 200 ok, 409 another run is in progress, 502 failed, 503 the
    source is not configured here (its key or settings; the error says which)
    or is disabled. One that does not is 202 {"source", "status": "running",
    "note"}: it carries on, holding its claim, and the board shows it when it
    ends. 404 no such source, 429 asked less than a minute ago."""
    connector = SYNCS.get(source)
    if connector is None:
        raise HTTPException(404, "Unknown source")
    with _sync_lock:
        wait = _last_sync.get(source, -SYNC_EVERY) + SYNC_EVERY - time.monotonic()
        if wait > 0:
            return JSONResponse({"error": "One sync a minute per source"}, status_code=429,
                                headers={"Retry-After": str(int(wait) + 1), "Cache-Control": "no-store"})
        _last_sync[source] = time.monotonic()
    done: dict = {}
    worker = threading.Thread(target=_owner_run, args=(source, connector, days, done),
                              name=f"board-owner-sync-{source}", daemon=True)
    worker.start()
    worker.join(SYNC_WAIT)
    result = done.get("result")
    if result is None:
        return JSONResponse({"source": source, "status": "running", "note": SYNC_RUNNING}, status_code=202,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse(result, status_code=_SYNC_STATUS.get(result.get("status"), 500),
                        headers={"Cache-Control": "no-store"})
