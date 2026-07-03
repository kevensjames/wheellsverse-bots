"""Sol v1 reminders API — a member's own upcoming/overdue obligations.

GET /sol/v1/reminders returns what the caller owes (as payer) and what's owed
to them (as payee), each bucketed by due date. Read-only; the daily sweep that
flips overdue → 'late' + notifies runs in reminder_scheduler.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_ledger import RemindersOut
from app.services.sol_v1 import reminders as reminders_svc

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-reminders"])


@router.get("/reminders", response_model=RemindersOut)
def my_reminders(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RemindersOut:
    today = datetime.now(timezone.utc).date()
    data = reminders_svc.member_reminders(db, user_id=current.id, today=today)
    return RemindersOut(**data)
