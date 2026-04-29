"""One-shot synchronous ingestion. No Celery, no Redis required.

Examples:
    python -m scripts.ingest_once --all
    python -m scripts.ingest_once --symbol AAPL --lookback-days 7
    python -m scripts.ingest_once --symbol BTC-USD
"""
from __future__ import annotations

import argparse
import sys

from app.config import settings
from app.database import SessionLocal
from app.models.asset import Asset
from app.services.market_data import ingest_asset, ingest_batch, normalize_symbol


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest OHLCV for one asset or all active assets.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbol", help="single asset symbol, e.g. AAPL or BTC-USD")
    group.add_argument("--all", action="store_true", help="every active asset")
    p.add_argument(
        "--lookback-days",
        type=int,
        default=settings.MARKET_DATA_LOOKBACK_DAYS,
        help="how much history to pull",
    )
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.symbol:
            normalized = normalize_symbol(args.symbol)
            asset = db.query(Asset).filter(Asset.symbol == normalized).first()
            if asset is None:
                print(f"unknown symbol: {normalized}")
                return 1
            results = [ingest_asset(db, asset, lookback_days=args.lookback_days)]
        else:
            assets = db.query(Asset).filter(Asset.is_active.is_(True)).all()
            results = ingest_batch(
                db,
                assets,
                delay_seconds=settings.YFINANCE_REQUEST_DELAY_SECONDS,
                lookback_days=args.lookback_days,
            )

        print(f"{'symbol':<12}{'fetched':>8}{'inserted':>10}{'ms':>8}  error")
        print("-" * 60)
        failures = 0
        for r in results:
            err = r.error or "-"
            print(f"{r.symbol:<12}{r.rows_fetched:>8}{r.rows_inserted:>10}{r.duration_ms:>8}  {err}")
            if r.error:
                failures += 1
        print("-" * 60)
        print(f"total: {len(results)} assets, {failures} failures")
        return 0 if failures == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
