"""Synchronous one-shot predictions (no Celery, no Redis required).

Examples:
    python -m scripts.predict_once --all
    python -m scripts.predict_once --stocks
    python -m scripts.predict_once --crypto
    python -m scripts.predict_once --symbol BTC-USD
"""
from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.models.asset import Asset
from app.services.market_data import normalize_symbol
from app.services.prediction_service import (
    predict_for_all_active_assets,
    predict_for_asset,
)


def _row(pred, close_price: float | None = None) -> str:
    target = f"{float(pred.target_price):.6f}" if pred.target_price is not None else "-"
    stop = f"{float(pred.stop_loss):.6f}" if pred.stop_loss is not None else "-"
    close = f"{close_price:.6f}" if close_price is not None else "-"
    return (
        f"{pred.asset_id:<6}"
        f"{pred.signal:<8}"
        f"{float(pred.confidence):>7.2f}  "
        f"{target:>14}  "
        f"{stop:>14}  "
        f"{close:>14}"
    )


def _close_price_for(db, asset_id: int) -> float | None:
    from app.models.asset import PriceHistory

    row = (
        db.query(PriceHistory.close)
        .filter(PriceHistory.asset_id == asset_id)
        .order_by(PriceHistory.timestamp.desc())
        .first()
    )
    return float(row[0]) if row and row[0] is not None else None


def main() -> int:
    p = argparse.ArgumentParser(description="Run predictions against live DB data.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="every active asset")
    group.add_argument("--stocks", action="store_true", help="only stocks")
    group.add_argument("--crypto", action="store_true", help="only crypto")
    group.add_argument("--symbol", help="single asset, e.g. AAPL or BTC-USD")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.symbol:
            normalized = normalize_symbol(args.symbol)
            asset = db.query(Asset).filter(Asset.symbol == normalized).first()
            if asset is None:
                print(f"unknown symbol: {normalized}")
                return 1
            predictions = [predict_for_asset(db, asset)]
        else:
            asset_type: str | None = None
            if args.stocks:
                asset_type = "stock"
            elif args.crypto:
                asset_type = "crypto"
            predictions = predict_for_all_active_assets(db, asset_type=asset_type)

        print(f"{'aid':<6}{'signal':<8}{'conf':>7}  {'target':>14}  {'stop':>14}  {'close':>14}")
        print("-" * 78)
        for pred in predictions:
            close = _close_price_for(db, pred.asset_id)
            print(_row(pred, close))
        print("-" * 78)
        print(f"total: {len(predictions)} predictions")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
