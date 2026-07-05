"""Sol v1 timeline API — the member's "what's next" stream.

A single read endpoint that projects the signed-in member's contributions, payouts,
and milestones into one chronological list. JWT-authed; the identity is always the
token principal. NON-CUSTODIAL: read-only, no money movement.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_timeline import TimelineEvent, TimelineOut
from app.services.sol_v1 import timeline

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-timeline"])


@router.get("/timeline", response_model=TimelineOut)
def my_timeline(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimelineOut:
    today = datetime.now(timezone.utc).date()  # same UTC clock as lock/reminders
    data = timeline.build_timeline(db, user_id=current.id, today=today)
    return TimelineOut(
        as_of=data["as_of"],
        events=[TimelineEvent(**e) for e in data["events"]],
    )
