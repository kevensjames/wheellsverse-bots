"""Pure market-data logic. No Celery imports — this runs identically under
the Celery worker, the admin API, and the one-shot CLI.
"""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.models.asset import Asset, PriceHistory


class MarketDataError(Exception):
    """Raised on empty responses, normalisation failures, or exhausted retries."""


class IngestResult(BaseModel):
    asset_id: int
    symbol: str
    rows_fetched: int = 0
    rows_inserted: int = 0
    duration_ms: int = 0
    error: str | None = None


# Errors we're willing to retry on (network-flavoured). Kept local so a missing
# `requests` install doesn't break import.
_NETWORK_ERRORS: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)
try:
    import requests  # noqa: F401

    _NETWORK_ERRORS = _NETWORK_ERRORS + (requests.exceptions.RequestException,)
except Exception:  # pragma: no cover
    pass


def normalize_symbol(symbol: str) -> str:
    """Uppercase + strip. Works for stocks ('AAPL') and yfinance crypto pairs ('BTC-USD')."""
    if not symbol:
        raise MarketDataError("symbol is empty")
    return symbol.strip().upper()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_NETWORK_ERRORS),
    reraise=True,
)
def _fetch_with_retry(symbol: str, period: str, interval: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    return ticker.history(period=period, interval=interval)


def fetch_ohlcv(symbol: str, period: str = "30d", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from yfinance. Returns a DataFrame with columns:
    timestamp, open, high, low, close, volume. Raises MarketDataError on failure.
    """
    try:
        df = _fetch_with_retry(symbol, period, interval)
    except _NETWORK_ERRORS as e:
        raise MarketDataError(f"network error fetching {symbol}: {e}") from e

    if df is None or df.empty:
        raise MarketDataError(f"no data returned for {symbol}")

    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    # yfinance uses 'date' for daily and 'datetime' for intraday intervals.
    if "date" in df.columns:
        df = df.rename(columns={"date": "timestamp"})
    elif "datetime" in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})

    expected = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = expected - set(df.columns)
    if missing:
        raise MarketDataError(f"unexpected yfinance shape for {symbol}: missing {missing}")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def upsert_prices(db: Session, asset_id: int, df: pd.DataFrame) -> int:
    """Bulk insert with ON CONFLICT DO NOTHING on (asset_id, timestamp).
    Returns the number of rows actually inserted (skipped duplicates don't count).
    """
    if df is None or df.empty:
        return 0

    rows: list[dict] = []
    for _, row in df.iterrows():
        vol = row["volume"]
        rows.append(
            {
                "asset_id": asset_id,
                "timestamp": row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                "open": float(row["open"]) if pd.notna(row["open"]) else None,
                "high": float(row["high"]) if pd.notna(row["high"]) else None,
                "low": float(row["low"]) if pd.notna(row["low"]) else None,
                "close": float(row["close"]) if pd.notna(row["close"]) else None,
                "volume": int(vol) if pd.notna(vol) else None,
            }
        )

    stmt = (
        insert(PriceHistory)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["asset_id", "timestamp"])
    )
    result = db.execute(stmt)
    db.commit()
    return int(result.rowcount or 0)


def ingest_asset(db: Session, asset: Asset, lookback_days: int = 30) -> IngestResult:
    """Fetch + upsert for one asset. Never raises — errors go into the result."""
    t0 = time.perf_counter()
    try:
        df = fetch_ohlcv(asset.symbol, period=f"{lookback_days}d")
        rows_fetched = len(df)
        rows_inserted = upsert_prices(db, asset.id, df)
        return IngestResult(
            asset_id=asset.id,
            symbol=asset.symbol,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    except Exception as e:
        db.rollback()
        return IngestResult(
            asset_id=asset.id,
            symbol=asset.symbol,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            error=str(e),
        )


def ingest_batch(
    db: Session,
    assets: list[Asset],
    delay_seconds: float = 0.5,
    lookback_days: int = 30,
) -> list[IngestResult]:
    """Serial ingest with delay between assets (to be polite to yfinance)."""
    results: list[IngestResult] = []
    for i, asset in enumerate(assets):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        results.append(ingest_asset(db, asset, lookback_days=lookback_days))
    return results
