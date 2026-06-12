"""KAI self-audit admin endpoint — live system health report.

Read-only introspection (admin-token only; no scope needed — auditing the
system shouldn't require enabling a scope). Runs INSIDE the daemon so it sees
the real os.environ (scope flags, LLM keys) the daemon actually loaded.

  GET /admin/audit/run   full report: summary + runtime + subsystems[] + issues[]
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies.admin import require_admin_token
from app.services.audit import run_audit

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/run")
def audit_run() -> dict[str, Any]:
    return run_audit()
