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


class ActionIn(BaseModel):
    type: str                    # click / type / submit / select
    selector: str
    value: str | None = None


class ExecuteRequest(BaseModel):
    """Envelope B: a sequence of write actions on one allowlisted page."""
    url: str
    actions: list[ActionIn]
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


@audited(scope="browser.execute", destructive=True)
def _audited_execute(*, url: str, actions: list[dict]) -> dict[str, Any]:
    try:
        out = session.execute_actions(url, actions)
    except config.BrowserPolicyError as e:
        log.record_action(kind="blocked", status="blocked", url=url, detail=str(e))
        raise
    except session.BrowserUnavailable as e:
        log.record_action(kind="execute_write", status="error", url=url, detail=str(e))
        raise
    final_url = out.get("final", {}).get("url", url)
    for r in out.get("results", []):
        ok = bool(r.get("ok"))
        detail = f"{r.get('type')} {r.get('selector')}"
        if not ok:
            detail += f" → {r.get('error', 'failed')}"
        log.record_action(
            kind="execute_write", status=("ok" if ok else "error"),
            url=final_url, detail=detail,
            proposed={"type": r.get("type"), "selector": r.get("selector")},
        )
    for b in out.get("blocked_navigations", []):
        log.record_action(
            kind="blocked", status="blocked", url=b.get("url", ""),
            detail=f"nav blocked: {b.get('reason', 'off-allowlist')}",
        )
    return out


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


@router.post("/execute")
def browser_execute(body: ExecuteRequest):
    """Envelope B — EXECUTE a sequence of write actions (operator-approved only).
    Triple-gated: KAI_BROWSER_WRITE_ENABLED (here) + KAI_SCOPE_BROWSER + approved
    (in @audited). KAI proposes via the tool; only this operator endpoint executes."""
    if not config.write_enabled():
        raise HTTPException(
            status_code=403,
            detail="browser writes are disabled (set KAI_BROWSER_WRITE_ENABLED=1)",
        )
    return _guard(
        _audited_execute, url=body.url,
        actions=[a.model_dump() for a in body.actions], approved=body.approved,
    )
