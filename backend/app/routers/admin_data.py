import time
from datetime import datetime, timedelta, timezone

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.models.asset import Asset
from app.models.profile import Profile
from app.models.subscription import Subscription
from app.services.market_data import normalize_symbol
from app.workers.celery_app import celery_app
from app.workers.tasks import (
    ingest_all_assets,
    ingest_single_asset,
    predict_all_crypto,
    predict_all_stocks,
    predict_single_asset,
)


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.post("/ingest/all")
def trigger_ingest_all():
    task = ingest_all_assets.delay()
    return {"task_id": task.id, "status": "queued"}


@router.post("/ingest/{symbol}")
def trigger_ingest_symbol(symbol: str, db: Session = Depends(get_db)):
    normalized = normalize_symbol(symbol)
    asset = db.query(Asset).filter(Asset.symbol == normalized).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    task = ingest_single_asset.delay(asset.id)
    return {"task_id": task.id, "asset_id": asset.id, "status": "queued"}


@router.get("/ingest/status/{task_id}")
def ingest_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.ready() else None,
    }


# ---------- Stage 4: prediction triggers ----------


@router.post("/predict/all")
def trigger_predict_all():
    stock_task = predict_all_stocks.delay()
    crypto_task = predict_all_crypto.delay()
    return {
        "stock_task_id": stock_task.id,
        "crypto_task_id": crypto_task.id,
        "status": "queued",
    }


@router.post("/predict/{symbol}")
def trigger_predict_symbol(symbol: str, db: Session = Depends(get_db)):
    normalized = normalize_symbol(symbol)
    asset = db.query(Asset).filter(Asset.symbol == normalized).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    task = predict_single_asset.delay(asset.id)
    return {"task_id": task.id, "asset_id": asset.id, "status": "queued"}


@router.get("/stats")
def launch_stats(db: Session = Depends(get_db)):
    """At-a-glance launch metrics. Use:  curl -H 'X-Admin-Token: $TOK' .../admin/stats"""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    total_users = db.query(func.count(Profile.id)).scalar() or 0
    users_24h = (
        db.query(func.count(Profile.id))
        .filter(Profile.created_at >= day_ago)
        .scalar() or 0
    )
    users_7d = (
        db.query(func.count(Profile.id))
        .filter(Profile.created_at >= week_ago)
        .scalar() or 0
    )

    by_tier = dict(
        db.query(Profile.tier, func.count(Profile.id))
        .group_by(Profile.tier).all()
    )

    active_subs = (
        db.query(func.count(Subscription.id))
        .filter(Subscription.status == "active").scalar() or 0
    )
    paid_24h = (
        db.query(func.count(Subscription.id))
        .filter(
            Subscription.status == "active",
            Subscription.created_at >= day_ago,
        ).scalar() or 0
    )

    return {
        "as_of": now.isoformat(),
        "users": {
            "total": int(total_users),
            "last_24h": int(users_24h),
            "last_7d": int(users_7d),
            "by_tier": {k: int(v) for k, v in by_tier.items()},
        },
        "subscriptions": {
            "active": int(active_subs),
            "new_24h": int(paid_24h),
        },
    }


@router.get("/recent-users")
def recent_users(limit: int = 20, db: Session = Depends(get_db)):
    """Most recent signups for the operator dashboard. Limit clamped to
    avoid pulling the whole table by accident."""
    limit = max(1, min(int(limit), 100))
    rows = (
        db.query(Profile.id, Profile.email, Profile.tier, Profile.created_at)
        .order_by(Profile.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "users": [
            {
                "id": str(r.id),
                "email": r.email,
                "tier": r.tier or "free",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# Process-level TTL cache for the spend rollup. The dashboard Stats tab polls
# this every 30s and the payload is identical for every admin viewer (no
# per-user data), so without a cache N open dashboards each trigger 3 full
# aggregate scans of llm_call_log every 30s. Caching just under the poll
# interval collapses that to ~3 queries per 25s for the whole fleet. A stale
# read is at most _SPEND_TTL_S old — fine for a cost dashboard.
_SPEND_CACHE: dict = {"at": 0.0, "data": None}
_SPEND_TTL_S = 25.0


@router.get("/spend")
def spend_rollup(db: Session = Depends(get_db)):
    """LLM-cost rollup: today + 7-day totals, broken down by adapter.

    Reads llm_call_log directly (raw SQL — same pattern as SpendTracker).
    Today = since 00:00 UTC. 7d = trailing 168 hours. Adapters are listed
    in descending cost order so the most expensive shows first.
    Cached process-wide for _SPEND_TTL_S (see note above).
    """
    _now = time.monotonic()
    if _SPEND_CACHE["data"] is not None and (_now - _SPEND_CACHE["at"]) < _SPEND_TTL_S:
        return _SPEND_CACHE["data"]
    today = db.execute(
        text(
            """
            SELECT adapter, COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS calls
            FROM llm_call_log
            WHERE created_at >= DATE_TRUNC('day', NOW())
            GROUP BY adapter
            ORDER BY total DESC
            """
        )
    ).all()
    week = db.execute(
        text(
            """
            SELECT adapter, COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS calls
            FROM llm_call_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
            GROUP BY adapter
            ORDER BY total DESC
            """
        )
    ).all()
    failures_24h = db.execute(
        text(
            """
            SELECT COUNT(*) AS n
            FROM llm_call_log
            WHERE success = FALSE
              AND created_at >= NOW() - INTERVAL '24 hours'
            """
        )
    ).scalar() or 0
    result = {
        "today": [
            {"adapter": r.adapter, "cost_usd": float(r.total), "calls": int(r.calls)}
            for r in today
        ],
        "last_7d": [
            {"adapter": r.adapter, "cost_usd": float(r.total), "calls": int(r.calls)}
            for r in week
        ],
        "today_total_usd": sum(float(r.total) for r in today),
        "last_7d_total_usd": sum(float(r.total) for r in week),
        "failures_24h": int(failures_24h),
    }
    _SPEND_CACHE["data"] = result
    _SPEND_CACHE["at"] = _now
    return result
