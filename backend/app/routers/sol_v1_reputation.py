"""Sol v1 reputation API — trust scores from payment history.

  GET /sol/v1/reputation/me               my own global score
  GET /sol/v1/groups/{group_id}/reputation  every member's WITHIN-GROUP score
                                            (members-only; no cross-group leak)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.models.sol import SolMembership
from app.schemas.sol_v1_reputation import MemberProfileOut, ReputationOut
from app.services.sol_v1 import badges, reputation

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-reputation"])


@router.get("/reputation/me", response_model=ReputationOut)
def my_reputation(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReputationOut:
    today = datetime.now(timezone.utc).date()
    data = reputation.compute_reputation(db, user_id=current.id, today=today)
    return ReputationOut.model_validate(data)


@router.get("/badges/me", response_model=MemberProfileOut)
def my_profile(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemberProfileOut:
    """The member's SOL profile: stats + earned/locked badge wall (derived read-only)."""
    today = datetime.now(timezone.utc).date()
    data = badges.member_profile(db, user_id=current.id, today=today)
    return MemberProfileOut.model_validate(data)


@router.get("/groups/{group_id}/reputation", response_model=list[ReputationOut])
def group_reputation(
    group_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReputationOut]:
    # members-only: co-members share risk and may see each other's in-circle
    # reliability, but nobody outside the group can.
    is_member = db.scalar(
        select(SolMembership.id).where(
            SolMembership.group_id == group_id, SolMembership.user_id == current.id
        )
    )
    if not is_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member of this group")
    today = datetime.now(timezone.utc).date()
    reps = reputation.group_reputations(db, group_id=group_id, today=today)
    return [ReputationOut.model_validate(r) for r in reps]
