"""Seed the plans table. Idempotent — safe to re-run.

If STRIPE_PRICE_PRO / STRIPE_PRICE_ELITE are set in the environment,
those values are written to `plans.stripe_price_id`. Re-run after
creating Prices in Stripe so webhooks can map back to plans.

Run from backend/:  python -m scripts.seed_plans
"""
from app.config import settings
from app.database import SessionLocal
from app.models.subscription import Plan


PLANS = [
    {"code": "free",  "name": "Free",  "price_cents": 0,    "predictions_per_day": 3,   "sms_alerts": False,  "stripe_price_id": None},
    {"code": "pro",   "name": "Pro",   "price_cents": 1900, "predictions_per_day": 999, "sms_alerts": False,  "stripe_price_id": settings.STRIPE_PRICE_PRO or None},
    {"code": "elite", "name": "Elite", "price_cents": 4900, "predictions_per_day": 999, "sms_alerts": True,   "stripe_price_id": settings.STRIPE_PRICE_ELITE or None},
]


def main() -> None:
    db = SessionLocal()
    try:
        for row in PLANS:
            existing = db.query(Plan).filter(Plan.code == row["code"]).first()
            if existing:
                # Upsert stripe_price_id if it changed or was previously null.
                if existing.stripe_price_id != row["stripe_price_id"]:
                    existing.stripe_price_id = row["stripe_price_id"]
                    print(f"update {row['code']}  stripe_price_id={row['stripe_price_id']}")
                else:
                    print(f"skip   {row['code']}  (unchanged)")
                continue
            db.add(Plan(**row))
            print(f"add    {row['code']}  stripe_price_id={row['stripe_price_id']}")
        db.commit()
        print(f"done — {db.query(Plan).count()} plans in table")
    finally:
        db.close()


if __name__ == "__main__":
    main()
