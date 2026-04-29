"""Service-layer tests — exercise the full pipeline (load → indicators →
predict → persist) against a real Postgres test DB."""
from __future__ import annotations

from app.models.asset import Asset
from app.models.prediction import Prediction
from app.services.prediction_service import (
    predict_for_all_active_assets,
    predict_for_asset,
)
from tests.conftest import seed_price_history


def test_predict_for_asset_writes_row(db_session):
    asset = Asset(symbol="SVC1", name="SVC1", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    seed_price_history(db_session, asset.id, rows=250)

    pred = predict_for_asset(db_session, asset)
    assert pred.id is not None
    assert pred.signal in ("BUY", "SELL", "HOLD")

    rows = db_session.query(Prediction).filter(Prediction.asset_id == asset.id).all()
    assert len(rows) == 1
    assert rows[0].features_snapshot is not None


def test_predict_for_asset_insufficient_data(db_session):
    # Asset exists but zero price_history → should still persist a HOLD row
    # for audit trail.
    asset = Asset(symbol="SVC2", name="SVC2", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    pred = predict_for_asset(db_session, asset)
    assert pred.signal == "HOLD"
    assert float(pred.confidence) == 0.0
    assert pred.features_snapshot.get("reason") == "insufficient_data"


def test_predict_for_all_active_assets(db_session):
    active_a = Asset(symbol="A1", name="A1", asset_type="stock", is_active=True)
    active_b = Asset(symbol="A2", name="A2", asset_type="stock", is_active=True)
    inactive = Asset(symbol="A3", name="A3", asset_type="stock", is_active=False)
    for a in (active_a, active_b, inactive):
        db_session.add(a)
    db_session.commit()
    for a in (active_a, active_b, inactive):
        db_session.refresh(a)

    seed_price_history(db_session, active_a.id, rows=250)
    seed_price_history(db_session, active_b.id, rows=250)
    seed_price_history(db_session, inactive.id, rows=250)

    predictions = predict_for_all_active_assets(db_session, asset_type="stock")
    assert len(predictions) == 2
    asset_ids = {p.asset_id for p in predictions}
    assert active_a.id in asset_ids
    assert active_b.id in asset_ids
    assert inactive.id not in asset_ids
