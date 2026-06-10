"""Browser (computer-control) admin endpoints — the operator's Browser tab.

Reads (scope-gated via the router dep + admin token; not approval-gated):
  GET  /admin/browser/status   enabled? headless? allowlist + action-log stats
  GET  /admin/browser/log      recent browser actions (reads + proposals + blocks)

Actions (@audited scope=browser.*, destructive=False — envelope A executes NO
writes, so there's no approval gate; everything is logged + scope-checked):
  POST /admin/browser/navigate {url}    navigate an allowlisted URL + read it
  POST /admin/browser/propose  {...}    record a DRY-RUN write proposal (no exec)

Nothing here clicks/types/submits. `navigate` is read-only (GET + extract);
`propose` only records what KAI would do for operator review.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.browser import config, log, session
from app.services.governance import PendingApproval, ScopeDenied, audited

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/browser",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ─── reads ───────────────────────────────────────────────────────────


@router.get("/status")
def browser_status() -> dict[str, Any]:
    return {
        "enabled": config.browser_enabled(),
        "headless": config.headless(),
        "allowlist": config.allowlist(),
        "page_timeout_ms": config.page_timeout_ms(),
        "stats": log.stats(),
    }


@router.get("/log")
def browser_log(limit: int = 50) -> dict[str, Any]:
    actions = log.list_actions(limit=limit)
    return {"count": len(actions), "actions": actions}


# ─── request models ──────────────────────────────────────────────────


class NavigateRequest(BaseModel):
    url: str
    approved: bool = False  # accepted for symmetry; v1 navigate isn't destructive


class ProposeRequest(BaseModel):
    action_type: str | None = None  # click / type / submit
    selector: str | None = None
    value: str | None = None
    description: str = ""
    url: str = ""
    approved: bool = False


# ─── audited actions ─────────────────────────────────────────────────


@audited(scope="browser.navigate", destructive=False)
def _audited_navigate(*, url: str) -> dict[str, Any]:
    try:
        safe = config.check_url(url)
    except config.BrowserPolicyError as e:
        log.record_action(kind="blocked", status="blocked", url=url, detail=str(e))
        raise
    try:
        result = session.read_page(safe)
    except session.BrowserUnavailable as e:
        log.record_action(kind="navigate", status="error", url=safe, detail=str(e))
        raise
    log.record_action(
        kind="navigate", status="ok",
        url=result.get("url", safe), detail=result.get("title", ""),
    )
    return {"result": result}


@audited(scope="browser.propose", destructive=False)
def _audited_propose(
    *, action_type: str | None, selector: str | None, value: str | None,
    description: str, url: str,
) -> dict[str, Any]:
    proposed = {"action_type": action_type, "selector": selector, "value": value}
    log.record_action(
        kind="propose_write", status="ok", url=url, detail=description, proposed=proposed,
    )
    return {
        "note": "DRY RUN — not executed. Recorded for operator review/approval.",
        "description": description,
        "proposed": proposed,
    }


# ─── write routes ────────────────────────────────────────────────────


def _guard(fn, **kwargs):
    try:
        return fn(**kwargs)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except config.BrowserPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except session.BrowserUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/navigate")
def browser_navigate(body: NavigateRequest):
    return _guard(_audited_navigate, url=body.url, approved=body.approved)


@router.post("/propose")
def browser_propose(body: ProposeRequest):
    return _guard(
        _audited_propose,
        action_type=body.action_type, selector=body.selector, value=body.value,
        description=body.description, url=body.url, approved=body.approved,
    )
