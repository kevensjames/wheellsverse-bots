"""API tests for the /predictions endpoints. Covers auth, rate limiting,
and the public stats endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.asset import Asset
from app.models.prediction import Prediction


def _make_prediction(
    db_session,
    asset_id: int,
    signal: str = "HOLD",
    confidence: float = 50.0,
    outcome: str | None = None,
) -> Prediction:
    pred = Prediction(
        asset_id=asset_id,
        signal=signal,
        confidence=confidence,
        horizon_hours=24,
        actual_outcome=outcome,
    )
    db_session.add(pred)
    db_session.commit()
    db_session.refresh(pred)
    return pred


def test_get_today_requires_auth(client):
    r = client.get("/predictions/today")
    assert r.status_code == 401


def test_get_today_returns_predictions(client, db_session, free_user, auth_headers):
    asset = Asset(symbol="P1", name="P1", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    _make_prediction(db_session, asset.id, signal="BUY", confidence=72.5)

    r = client.get("/predictions/today", headers=auth_headers(free_user))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert any(p["asset_symbol"] == "P1" and p["signal"] == "BUY" for p in body)


def test_get_today_free_tier_limit(client, db_session, free_user, auth_headers):
    # Seed one prediction so the endpoint has something to return.
    asset = Asset(symbol="P2", name="P2", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    _make_prediction(db_session, asset.id, signal="HOLD")

    headers = auth_headers(free_user)
    # Free tier: predictions_per_day=3. Calls 1, 2, 3 succeed; 4th is 402.
    for i in range(3):
        r = client.get("/predictions/today", headers=headers)
        assert r.status_code == 200, f"call {i + 1}: {r.status_code} {r.text}"

    r = client.get("/predictions/today", headers=headers)
    assert r.status_code == 402
    body = r.json()
    assert body["detail"]["limit"] == 3
    assert body["detail"]["plan"] == "free"


def test_get_today_pro_tier_unlimited(client, db_session, pro_user, auth_headers):
    asset = Asset(symbol="P3", name="P3", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    _make_prediction(db_session, asset.id, signal="BUY")

    headers = auth_headers(pro_user)
    for i in range(10):
        r = client.get("/predictions/today", headers=headers)
        assert r.status_code == 200, f"pro call {i + 1} failed: {r.text}"


def test_get_stats_is_public(client):
    r = client.get("/predictions/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total_predictions" in body
    assert "by_signal" in body
    assert {"BUY", "SELL", "HOLD"} <= set(body["by_signal"].keys())


def test_get_stats_win_rate_computation(client, db_session):
    asset = Asset(symbol="P4", name="P4", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    # 7 wins + 3 losses among 10 closed predictions → win_rate 0.7
    for _ in range(7):
        _make_prediction(db_session, asset.id, signal="BUY", confidence=60.0, outcome="WIN")
    for _ in range(3):
        _make_prediction(db_session, asset.id, signal="BUY", confidence=60.0, outcome="LOSS")

    r = client.get("/predictions/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_predictions"] == 10
    assert body["closed_predictions"] == 10
    assert abs(body["win_rate"] - 0.7) < 1e-6
