"""Seed the assets table. Idempotent — safe to re-run.

Run from backend/:  python -m scripts.seed_assets
"""
from app.database import SessionLocal
from app.models.asset import Asset


STOCKS = [
    ("AAPL",  "Apple Inc."),
    ("MSFT",  "Microsoft Corp."),
    ("GOOGL", "Alphabet Inc."),
    ("AMZN",  "Amazon.com Inc."),
    ("META",  "Meta Platforms"),
    ("NVDA",  "NVIDIA Corp."),
    ("TSLA",  "Tesla Inc."),
    ("JPM",   "JPMorgan Chase"),
    ("V",     "Visa Inc."),
    ("WMT",   "Walmart Inc."),
]

CRYPTO = [
    ("BTC-USD",  "Bitcoin"),
    ("ETH-USD",  "Ethereum"),
    ("SOL-USD",  "Solana"),
    ("XRP-USD",  "XRP"),
    ("DOGE-USD", "Dogecoin"),
]


def upsert(db, symbol: str, name: str, asset_type: str) -> None:
    existing = db.query(Asset).filter(Asset.symbol == symbol).first()
    if existing:
        print(f"skip  {symbol}")
        return
    db.add(Asset(symbol=symbol, name=name, asset_type=asset_type, is_active=True))
    print(f"add   {symbol:<10} {asset_type}")


def main() -> None:
    db = SessionLocal()
    try:
        for sym, name in STOCKS:
            upsert(db, sym, name, "stock")
        for sym, name in CRYPTO:
            upsert(db, sym, name, "crypto")
        db.commit()
        print(f"done — {db.query(Asset).count()} assets in table")
    finally:
        db.close()


if __name__ == "__main__":
    main()
