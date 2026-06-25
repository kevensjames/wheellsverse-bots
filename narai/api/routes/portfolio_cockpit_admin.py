"""Per-business Build Cockpit API. Drives one business's supervisor loop through
the Plan-1 engine via the decoupled adapter registry. GREEN verbs draft artifacts;
auto_capped verbs queue for approval (ctx_for returns falsy preconditions)."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException

from core.portfolio import adapters, loops, preconditions, registry, rollup, seed, state, paths

router = APIRouter(prefix="/api/narai/portfolio/biz", tags=["portfolio-cockpit"])


def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


def _require(slug: str):
    b = registry.get_business(slug)
    if b is None:
        raise HTTPException(404, f"unknown business {slug!r}")
    return b


@router.get("/{slug}/overview")
def overview(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    b = _require(slug)
    st = state.load_state(slug)
    steps = loops.load_loop(slug)
    nxt = loops.select_next_step(steps, st)
    done, pend = set(st["completed_verbs"]), set(st["pending_verbs"])
    out = []
    for s in steps:
        if s.verb in done:
            sstate = "completed"
        elif s.verb in pend:
            sstate = "pending"
        elif nxt is not None and s.verb == nxt.verb:
            sstate = "next"
        else:
            sstate = "todo"
        out.append({"verb": s.verb, "class": s.action_class.value, "state": sstate})
    return {"business": slug, "name": b.name, "phase": st.get("phase", "planning"),
            "steps": out, "completed": len(done), "pending": len(pend)}


@router.get("/{slug}/artifacts")
def artifacts(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    root = paths.business_dir(slug) / "artifacts"
    items = []
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                items.append({"kind": p.parent.name, "name": p.name, "path": str(p)})
    return {"artifacts": items}


@router.get("/{slug}/audit")
def audit(slug: str, limit: int = 50, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    rows = [r for r in rollup.recent_audit(limit=500) if r.get("business") == slug]
    return {"audit": rows[:limit]}


@router.post("/{slug}/tick")
def tick(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    result = loops.tick(slug, adapters.adapter_for, preconditions.make_ctx_for(slug))
    if result is None:
        return {"status": "idle", "detail": "no step ready"}
    return {"status": result.status, "detail": result.detail}


@router.post("/{slug}/seed")
def seed_loop(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    if slug != "n8n":
        raise HTTPException(400, "only the n8n pilot loop is seedable in Plan 3")
    seed.seed_n8n_loop()
    return {"ok": True}
