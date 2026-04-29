"""Celery wrappers around the market-data service. No business logic here —
just session management, logging, and retry policy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.admin import AuditLog
from app.models.asset import Asset
from app.services.market_data import MarketDataError, ingest_asset as _ingest_asset
from app.services.prediction_service import (
    predict_for_all_active_assets as _predict_all,
    predict_for_asset as _predict_asset,
)
from app.workers.celery_app import celery_app


_TRANSIENT_MARKERS = ("network error", "timeout", "connection", "rate limit", "429", "503")


def _is_transient(error: str | None) -> bool:
    if not error:
        return False
    low = error.lower()
    return any(m in low for m in _TRANSIENT_MARKERS)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="app.workers.tasks.ingest_single_asset")
def ingest_single_asset(self, asset_id: int):
    db = SessionLocal()
    try:
        asset = db.get(Asset, asset_id)
        if asset is None or not asset.is_active:
            return {"skipped": True, "asset_id": asset_id}

        result = _ingest_asset(db, asset, lookback_days=settings.MARKET_DATA_LOOKBACK_DAYS)

        db.add(
            AuditLog(
                actor_type="system",
                action="market_data.ingest_asset",
                target_type="asset",
                target_id=str(asset.id),
                event_metadata=result.model_dump(),
            )
        )
        db.commit()

        if result.error and _is_transient(result.error):
            # Exponential-ish backoff: 60s, 120s, 240s.
            countdown = 60 * (2 ** self.request.retries)
            raise self.retry(exc=MarketDataError(result.error), countdown=countdown)

        return result.model_dump()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.ingest_all_assets")
def ingest_all_assets():
    db = SessionLocal()
    try:
        assets = db.query(Asset).filter(Asset.is_active.is_(True)).all()
        batch_size = settings.MARKET_DATA_BATCH_SIZE
        batches = (len(assets) + batch_size - 1) // batch_size if assets else 0

        for asset in assets:
            ingest_single_asset.delay(asset.id)

        dispatched_at = datetime.now(timezone.utc).isoformat()
        summary = {
            "total_assets": len(assets),
            "batches": batches,
            "dispatched_at": dispatched_at,
        }
        db.add(
            AuditLog(
                actor_type="system",
                action="market_data.ingest_all",
                event_metadata=summary,
            )
        )
        db.commit()
        return summary
    finally:
        db.close()


# ---------- Stage 4: predictions ----------


@celery_app.task(name="app.workers.tasks.predict_single_asset")
def predict_single_asset(asset_id: int):
    db = SessionLocal()
    try:
        asset = db.get(Asset, asset_id)
        if asset is None or not asset.is_active:
            return {"skipped": True, "asset_id": asset_id}

        prediction = _predict_asset(db, asset)
        summary = {
            "asset_id": asset.id,
            "symbol": asset.symbol,
            "prediction_id": str(prediction.id),
            "signal": prediction.signal,
            "confidence": float(prediction.confidence),
        }
        db.add(
            AuditLog(
                actor_type="system",
                action="predict.single",
                target_type="asset",
                target_id=str(asset.id),
                event_metadata=summary,
            )
        )
        db.commit()
        return summary
    finally:
        db.close()


def _run_predict_all(asset_type: str) -> dict:
    db = SessionLocal()
    try:
        predictions = _predict_all(db, asset_type=asset_type)
        summary = {
            "asset_type": asset_type,
            "predictions_written": len(predictions),
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }
        db.add(
            AuditLog(
                actor_type="system",
                action=f"predict.all.{asset_type}",
                event_metadata=summary,
            )
        )
        db.commit()
        return summary
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.predict_all_stocks")
def predict_all_stocks():
    return _run_predict_all("stock")


@celery_app.task(name="app.workers.tasks.predict_all_crypto")
def predict_all_crypto():
    return _run_predict_all("crypto")
