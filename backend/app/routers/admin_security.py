from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.admin import require_admin_token
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.security.store import SecurityStore

router = APIRouter(prefix="/admin/security", tags=["security"],
                   dependencies=[Depends(require_admin_token)])


def _store() -> SecurityStore:
    return SecurityStore(SecurityStore.default_dir())


@router.get("/summary")
def summary():
    snap = _store().read_latest()
    if snap is None:
        return {"status": "no-data"}
    counts = Counter(f.severity for f in snap.findings)
    return {
        "generated_at": snap.generated_at,
        "by": snap.by,
        "score": snap.score.model_dump(),
        "counts_by_severity": dict(counts),
        "backup": snap.backup.model_dump(),
        "runner_status": [s.model_dump() for s in snap.runner_status],
    }


@router.get("/findings")
def findings(category: str | None = Query(None), severity: str | None = Query(None)):
    snap = _store().read_latest()
    if snap is None:
        return {"findings": []}
    items = snap.findings
    if category:
        items = [f for f in items if f.category == category]
    if severity:
        items = [f for f in items if f.severity == severity]
    return {"findings": [f.model_dump() for f in items]}


@router.get("/score")
def score():
    snap = _store().read_latest()
    return (snap.score.model_dump() if snap else {"overall": None, "categories": []})


@audited(scope="security.scan", destructive=False)
def _queue_scan() -> dict:
    _store().request_scan()
    return {"queued": True}


@router.post("/scan")
def scan():
    # @audited enforces KAI_SCOPE_SECURITY_SCAN (or parent KAI_SCOPE_SECURITY) and
    # records the action. The daemon only writes a .request marker — it never
    # spawns a scanner; the isolated launchd worker picks the marker up.
    try:
        return _queue_scan()
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=f"security.scan scope disabled: {e}")
    except PendingApproval as e:  # pragma: no cover - destructive=False, not expected
        raise HTTPException(status_code=409, detail=str(e))
