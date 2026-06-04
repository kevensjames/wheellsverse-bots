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
