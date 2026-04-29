"""DB-aware orchestration around the pure predictor.

Splits cleanly from `app.ml.*` (pure) so that Celery tasks, the admin API,
and the CLI all share a single code path.
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.constants import SIGNAL_HOLD
from app.ml.indicators import compute_all
from app.ml.predictor import PredictionOutput, predict
from app.models.admin import AuditLog
from app.models.asset import Asset, PriceHistory
from app.models.prediction import Prediction


logger = logging.getLogger(__name__)


_INDICATOR_COLS = ("rsi", "macd", "macd_signal", "macd_hist")


def load_price_history(db: Session, asset_id: int, limit: int = 250) -> pd.DataFrame:
    """Return the most recent `limit` rows sorted ASC (oldest first)."""
    stmt = (
        select(
            PriceHistory.timestamp,
            PriceHistory.open,
            PriceHistory.high,
            PriceHistory.low,
            PriceHistory.close,
            PriceHistory.volume,
        )
        .where(PriceHistory.asset_id == asset_id)
        .order_by(PriceHistory.timestamp.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    # numeric columns come back as Decimal from psycopg2; cast to float for ta.
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    # DB gave us newest-first (for the limit); flip for chronological indicator math.
    return df.sort_values("timestamp").reset_index(drop=True)


def _persist_prediction(
    db: Session,
    asset: Asset,
    output: PredictionOutput,
) -> Prediction:
    row = Prediction(
        asset_id=asset.id,
        signal=output.signal,
        confidence=output.confidence,
        target_price=output.target_price,
        stop_loss=output.stop_loss,
        horizon_hours=output.horizon_hours,
        model_version=output.features_snapshot.get("model_version"),
        features_snapshot=output.features_snapshot,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def predict_for_asset(db: Session, asset: Asset) -> Prediction:
    """Load history, compute indicators, call predictor, persist. Always writes
    a row (including HOLD/insufficient_data) to keep an audit trail.
    """
    df = load_price_history(db, asset.id, limit=250)

    if df.empty:
        output = predict(df, asset.asset_type)
        logger.warning("No price_history for asset_id=%s symbol=%s — writing HOLD", asset.id, asset.symbol)
        return _persist_prediction(db, asset, output)

    enriched = compute_all(df, asset_type=asset.asset_type)
    # Drop warmup rows where any indicator is still NaN. Keep the chronological order.
    existing_cols = [c for c in _INDICATOR_COLS if c in enriched.columns]
    enriched = enriched.dropna(subset=existing_cols).reset_index(drop=True)

    output = predict(enriched, asset.asset_type)
    if output.signal == SIGNAL_HOLD and output.confidence == 0:
        logger.warning(
            "Insufficient data for asset_id=%s symbol=%s — reason=%s",
            asset.id,
            asset.symbol,
            output.features_snapshot.get("reason"),
        )

    return _persist_prediction(db, asset, output)


def predict_for_all_active_assets(
    db: Session,
    asset_type: str | None = None,
) -> list[Prediction]:
    """Iterate every active asset; individual failures are logged and do not
    abort the batch."""
    q = db.query(Asset).filter(Asset.is_active.is_(True))
    if asset_type is not None:
        q = q.filter(Asset.asset_type == asset_type)
    assets = q.all()

    predictions: list[Prediction] = []
    for asset in assets:
        try:
            predictions.append(predict_for_asset(db, asset))
        except Exception as e:  # pragma: no cover — defensive
            db.rollback()
            logger.exception("predict_for_asset failed for %s", asset.symbol)
            db.add(
                AuditLog(
                    actor_type="system",
                    action="predict.error",
                    target_type="asset",
                    target_id=str(asset.id),
                    event_metadata={"symbol": asset.symbol, "error": str(e)},
                )
            )
            db.commit()
    return predictions
