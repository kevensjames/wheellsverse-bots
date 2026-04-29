from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.models.asset import Asset
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
