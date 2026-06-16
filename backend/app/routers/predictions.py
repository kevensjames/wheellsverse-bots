from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.asset import Asset
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.services.billing import tiers
from app.models.usage import UsageLog
from app.dependencies.supabase_jwt import UserPrincipal as User  # Path X alias
from app.schemas.prediction import PredictionResponse, PredictionStats, SignalCounts


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/predictions", tags=["predictions"])

_STATS_CACHE_KEY = "predictions:stats:30d"
_STATS_CACHE_TTL = 300  # seconds — 5 minutes
_ACTION_VIEW = "view_predictions"

try:
    _redis = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
except Exception:  # pragma: no cover
    _redis = None


# ---------- helpers ----------

def _user_tier(db: Session, user: User) -> str:
    """Resolve the user's tier code. Reads the profile.tier mirror first
    (single query — the webhook keeps it in sync with the active sub);
    falls back to a Subscription scan if the mirror is somehow empty."""
    from app.models.profile import Profile  # local import: avoid circular

    prof = db.get(Profile, user.id)
    if prof and prof.tier:
        return prof.tier
    # Defensive fallback — should never hit if webhook ran
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == "active")
        .first()
    )
    return sub.tier if sub else "free"


def _today_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _enforce_rate_limit(db: Session, user: User) -> None:
    """Raise 402 if the caller has used up today's quota for their tier."""
    tier_code = _user_tier(db, user)
    spec = tiers.get(tier_code) or tiers.get("free")
    limit = spec.predictions_per_day if spec else 3

    used = (
        db.query(func.count(UsageLog.id))
        .filter(
            UsageLog.user_id == user.id,
            UsageLog.action == _ACTION_VIEW,
            UsageLog.created_at >= _today_start_utc(),
        )
        .scalar()
        or 0
    )
    if used >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Daily prediction limit reached",
                "limit": int(limit),
                "plan": tier_code,
                "action": "Upgrade to Pro for unlimited access",
                "upgrade_url": settings.BILLING_PUBLIC_UPGRADE_URL,
            },
        )


def _log_view(db: Session, user: User, resource_id: str | None = None) -> None:
    """Insert a usage_log row AFTER the response was successfully built so
    a failed handler doesn't eat quota."""
    db.add(UsageLog(user_id=user.id, action=_ACTION_VIEW, resource_id=resource_id))
    db.commit()


def _to_response(pred: Prediction, symbol: str) -> PredictionResponse:
    return PredictionResponse(
        id=pred.id,
        asset_symbol=symbol,
        signal=pred.signal,
        confidence=float(pred.confidence),
        target_price=float(pred.target_price) if pred.target_price is not None else None,
        stop_loss=float(pred.stop_loss) if pred.stop_loss is not None else None,
        horizon_hours=pred.horizon_hours,
        created_at=pred.created_at,
    )


# ---------- endpoints ----------

@router.get("/stats", response_model=PredictionStats)
def prediction_stats(db: Session = Depends(get_db)) -> PredictionStats:
    """Public — feeds the landing page 'live proof' block. Cached 5 minutes."""
    if _redis is not None:
        try:
            cached = _redis.get(_STATS_CACHE_KEY)
            if cached:
                return PredictionStats.model_validate_json(cached)
        except Exception as e:  # pragma: no cover — fail open
            logger.warning("redis get failed: %s", e)

    since = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        rows = (
            db.query(Prediction.signal, Prediction.confidence, Prediction.actual_outcome)
            .filter(Prediction.created_at >= since)
            .all()
        )
    except ProgrammingError as e:
        # Prod Supabase doesn't have the predictions table yet (feature shipped
        # in code, table not migrated). Fail open with zeros so the landing
        # page renders instead of 500ing on every visit.
        db.rollback()
        logger.warning("predictions table unavailable, returning zero stats: %s", e.orig)
        return PredictionStats(
            total_predictions=0,
            by_signal=SignalCounts(BUY=0, SELL=0, HOLD=0),
            closed_predictions=0,
            win_rate=None,
            avg_confidence=0.0,
        )

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    wins = losses = closed = 0
    confidences: list[float] = []
    for signal, confidence, outcome in rows:
        if signal in counts:
            counts[signal] += 1
        if confidence is not None:
            confidences.append(float(confidence))
        if outcome == "WIN":
            wins += 1
            closed += 1
        elif outcome == "LOSS":
            losses += 1
            closed += 1

    win_rate: float | None = round(wins / (wins + losses), 4) if (wins + losses) else None
    avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    stats = PredictionStats(
        total_predictions=len(rows),
        by_signal=SignalCounts(**counts),
        closed_predictions=closed,
        win_rate=win_rate,
        avg_confidence=avg_confidence,
    )

    if _redis is not None:
        try:
            _redis.setex(_STATS_CACHE_KEY, _STATS_CACHE_TTL, stats.model_dump_json())
        except Exception as e:  # pragma: no cover — fail open
            logger.warning("redis setex failed: %s", e)

    return stats


@router.get("/today", response_model=list[PredictionResponse])
def predictions_today(
    asset_type: Optional[str] = Query(default=None, pattern="^(stock|crypto)$"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PredictionResponse]:
    _enforce_rate_limit(db, user)

    start = _today_start_utc()

    # Rank predictions per-asset by created_at desc, keep the newest for each.
    ranked_sub = (
        db.query(
            Prediction,
            Asset.symbol.label("symbol"),
            Asset.asset_type.label("atype"),
            func.row_number()
            .over(partition_by=Prediction.asset_id, order_by=Prediction.created_at.desc())
            .label("rn"),
        )
        .join(Asset, Asset.id == Prediction.asset_id)
        .filter(Prediction.created_at >= start)
    )
    if asset_type:
        ranked_sub = ranked_sub.filter(Asset.asset_type == asset_type)
    ranked = ranked_sub.all()

    results = [(p, sym) for p, sym, _atype, rn in ranked if rn == 1][:limit]
    response = [_to_response(p, sym) for p, sym in results]
    _log_view(db, user, resource_id="today")
    return response


@router.get("/{symbol}", response_model=list[PredictionResponse])
def predictions_for_symbol(
    symbol: str,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PredictionResponse]:
    asset = db.query(Asset).filter(Asset.symbol == symbol.strip().upper()).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    _enforce_rate_limit(db, user)

    rows = (
        db.query(Prediction)
        .filter(Prediction.asset_id == asset.id)
        .order_by(Prediction.created_at.desc())
        .limit(limit)
        .all()
    )
    response = [_to_response(p, asset.symbol) for p in rows]
    _log_view(db, user, resource_id=asset.symbol)
    return response
