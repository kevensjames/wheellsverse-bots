"""Sol v1 admin (operator) API — read-only dashboard over the ledger.

  GET /admin/sol-v1/overview        portfolio snapshot + attention counts
  GET /admin/sol-v1/risk            risk board (disputed + overdue), triage order
  GET /admin/sol-v1/disputes        disputes with review context
  GET /admin/sol-v1/groups          all circles with fill + cycle progress
  GET /admin/sol-v1/groups/{id}     drill-down (members + cycles + payments + reputation)
  GET /admin/sol-v1/activity        recent-activity feed (?limit)

Prefix is /admin/sol-v1 (NOT /admin/sol) to stay cleanly separate from the
legacy custodial Dwolla Sol router that still lives at /admin/sol.

OPERATOR-ONLY: the whole router is gated by require_admin_token (X-Admin-Token
header, constant-time, fail-closed) — NOT the member Supabase cookie. A member
session carries no admin token, so every route here 403s for members. It is also
registered only in the operator profile (not is_consumer), so it is physically
absent from a consumer replica. Read-only; NON-CUSTODIAL (no money, no writes).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.schemas.sol_v1_admin import (
    ActivityOut,
    DisputesOut,
    GroupDetailOut,
    GroupsOut,
    HealthOut,
    OverviewOut,
    RiskOut,
    SupervisorReportOut,
)
from app.services.sol_v1 import admin_metrics as M
from app.services.sol_v1 import health as H
from app.services.sol_v1 import supervisor as SUP

router = APIRouter(
    prefix="/admin/sol-v1",
    tags=["admin", "sol-admin"],
    dependencies=[Depends(require_admin_token)],  # gate EVERY route (fail-closed)
)


def _today() -> "datetime.date":
    return datetime.now(timezone.utc).date()


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db)) -> OverviewOut:
    return OverviewOut(**M.overview(db, _today()))


@router.get("/risk", response_model=RiskOut)
def risk(db: Session = Depends(get_db)) -> RiskOut:
    return RiskOut(items=M.risk_items(db, _today()))


@router.get("/disputes", response_model=DisputesOut)
def disputes(db: Session = Depends(get_db)) -> DisputesOut:
    return DisputesOut(items=M.disputes(db))


@router.get("/groups", response_model=GroupsOut)
def groups(db: Session = Depends(get_db)) -> GroupsOut:
    return GroupsOut(items=M.groups(db))


@router.get("/groups/{group_id}", response_model=GroupDetailOut)
def group_detail(group_id: UUID, db: Session = Depends(get_db)) -> GroupDetailOut:
    data = M.group_detail(db, group_id=group_id, today=_today())
    if not data:
        raise HTTPException(status_code=404, detail="group not found")
    return GroupDetailOut(**data)


@router.get("/activity", response_model=ActivityOut)
def activity(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ActivityOut:
    return ActivityOut(items=M.recent_activity(db, limit=limit))


@router.get("/supervisor", response_model=SupervisorReportOut)
def supervisor(db: Session = Depends(get_db)) -> SupervisorReportOut:
    """Run the read-only integrity + health monitor on demand. NEVER mutates."""
    return SupervisorReportOut(**SUP.run_checks(db, _today()))


@router.get("/health", response_model=HealthOut)
def sol_health(db: Session = Depends(get_db)) -> HealthOut:
    """Sol subsystem liveness: DB reachable + scheduler arm-state + row counts."""
    return HealthOut(**H.health(db))


@router.get("/metrics")
def sol_metrics(db: Session = Depends(get_db)) -> Response:
    """The Sol counters in Prometheus text-exposition format (scrapeable)."""
    return Response(
        content=H.prometheus_metrics(db, _today()),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
