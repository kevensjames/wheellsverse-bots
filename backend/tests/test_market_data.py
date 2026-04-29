from unittest.mock import MagicMock

import pandas as pd
import pytest
from tenacity import wait_none

from app.models.asset import Asset
from app.models.prediction import Prediction  # noqa: F401  (ensure table registered)
from app.services import market_data as md
from app.services.market_data import (
    MarketDataError,
    fetch_ohlcv,
    ingest_asset,
    ingest_batch,
    normalize_symbol,
    upsert_prices,
)


def _yf_df(n: int = 5) -> pd.DataFrame:
    """Shape of a raw yfinance daily response (tz-aware Date index, Title-case columns)."""
    start = pd.Timestamp("2026-04-15", tz="UTC")
    idx = pd.DatetimeIndex([start + pd.Timedelta(days=i) for i in range(n)], name="Date")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [105.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [102.0 + i for i in range(n)],
            "Volume": [1_000_000 + i * 1000 for i in range(n)],
            "Dividends": [0.0] * n,
            "Stock Splits": [0.0] * n,
        },
        index=idx,
    )


def _normalized_df(n: int = 5) -> pd.DataFrame:
    """Already-normalized shape (output of fetch_ohlcv) for upsert tests."""
    start = pd.Timestamp("2026-04-15", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": [start + pd.Timedelta(days=i) for i in range(n)],
            "open": [100.0 + i for i in range(n)],
            "high": [105.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [102.0 + i for i in range(n)],
            "volume": [1_000_000 + i * 1000 for i in range(n)],
        }
    )


def _mock_yf_ticker(monkeypatch, df_or_sides):
    """Patch yf.Ticker so each call returns a mock whose .history is pre-programmed."""
    ticker = MagicMock()
    if isinstance(df_or_sides, list):
        ticker.history.side_effect = df_or_sides
    else:
        ticker.history.return_value = df_or_sides
    factory = MagicMock(return_value=ticker)
    monkeypatch.setattr("app.services.market_data.yf.Ticker", factory)
    return ticker


# --- fetch_ohlcv ---

def test_fetch_ohlcv_success(monkeypatch):
    _mock_yf_ticker(monkeypatch, _yf_df(5))
    df = fetch_ohlcv("AAPL")
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 5


def test_fetch_ohlcv_empty(monkeypatch):
    _mock_yf_ticker(monkeypatch, pd.DataFrame())
    with pytest.raises(MarketDataError):
        fetch_ohlcv("NOPE")


def test_fetch_ohlcv_retries_on_network_error(monkeypatch):
    # Make retry waits zero so the test is fast.
    monkeypatch.setattr(md._fetch_with_retry.retry, "wait", wait_none())
    ticker = _mock_yf_ticker(
        monkeypatch,
        [ConnectionError("flap"), ConnectionError("flap"), _yf_df(3)],
    )
    df = fetch_ohlcv("AAPL")
    assert len(df) == 3
    assert ticker.history.call_count == 3


# --- normalize_symbol ---

def test_normalize_symbol():
    assert normalize_symbol("AAPL") == "AAPL"
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol("BTC-USD") == "BTC-USD"
    assert normalize_symbol(" TSLA ") == "TSLA"
    with pytest.raises(MarketDataError):
        normalize_symbol("")


# --- upsert_prices ---

def test_upsert_prices_inserts_new(db_session, test_asset):
    df = _normalized_df(5)
    inserted = upsert_prices(db_session, test_asset.id, df)
    assert inserted == 5


def test_upsert_prices_idempotent(db_session, test_asset):
    df = _normalized_df(5)
    first = upsert_prices(db_session, test_asset.id, df)
    second = upsert_prices(db_session, test_asset.id, df)
    assert first == 5
    assert second == 0


# --- ingest_asset ---

def test_ingest_asset_success(db_session, test_asset, monkeypatch):
    monkeypatch.setattr(
        "app.services.market_data.fetch_ohlcv",
        lambda sym, period="30d", interval="1d": _normalized_df(4),
    )
    result = ingest_asset(db_session, test_asset)
    assert result.error is None
    assert result.rows_fetched == 4
    assert result.rows_inserted == 4
    assert result.symbol == test_asset.symbol


def test_ingest_asset_handles_error(db_session, test_asset, monkeypatch):
    def _boom(*a, **kw):
        raise MarketDataError("yahoo broke")

    monkeypatch.setattr("app.services.market_data.fetch_ohlcv", _boom)
    result = ingest_asset(db_session, test_asset)
    assert result.error == "yahoo broke"
    assert result.rows_inserted == 0


# --- ingest_batch ---

def test_ingest_batch_continues_on_failure(db_session, monkeypatch):
    # Three assets — middle one fails, others succeed.
    assets = [
        Asset(symbol="ONE", name="One", asset_type="stock", is_active=True),
        Asset(symbol="BAD", name="Bad", asset_type="stock", is_active=True),
        Asset(symbol="TWO", name="Two", asset_type="stock", is_active=True),
    ]
    for a in assets:
        db_session.add(a)
    db_session.commit()
    for a in assets:
        db_session.refresh(a)

    def _maybe_fail(symbol, period="30d", interval="1d"):
        if symbol == "BAD":
            raise MarketDataError("intentional fail")
        return _normalized_df(3)

    monkeypatch.setattr("app.services.market_data.fetch_ohlcv", _maybe_fail)

    results = ingest_batch(db_session, assets, delay_seconds=0.0)
    assert len(results) == 3
    assert results[0].error is None and results[0].rows_inserted == 3
    assert results[1].error is not None
    assert results[2].error is None and results[2].rows_inserted == 3
