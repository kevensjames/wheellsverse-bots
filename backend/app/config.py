from functools import lru_cache
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Wheellsverse"
    APP_ENV: str = "development"
    DEBUG: bool = True

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    # Legacy self-managed JWT secret. Still read at startup so existing .env
    # files don't break — but no Stage 6+ code path uses it for user auth.
    # `dependencies/admin.py` reuses it as a shared admin-API token; the
    # rename to ADMIN_TOKEN is tracked but a soft alias keeps backward compat.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Path X: Supabase Auth is the real identity system. Anon-level password
    # grant uses the publishable key; admin create_user uses the secret key.
    # JWT validation is JWKS (ES256) — no shared secret needed.
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # Dedicated admin-API token. Falls back to JWT_SECRET_KEY for transition
    # so deployments don't break before .env is updated.
    ADMIN_TOKEN: str = ""

    @property
    def admin_token(self) -> str:
        return self.ADMIN_TOKEN or self.JWT_SECRET_KEY

    # Stored as a plain CSV string — pydantic-settings 2.x tries to JSON-decode
    # List[str] fields from env, which breaks on "http://a,http://b". We parse
    # lazily via the `cors_origins` property below.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Celery / workers
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Market data ingestion
    MARKET_DATA_FETCH_INTERVAL_MINUTES: int = 15
    MARKET_DATA_LOOKBACK_DAYS: int = 30
    MARKET_DATA_BATCH_SIZE: int = 10
    YFINANCE_REQUEST_DELAY_SECONDS: float = 0.5

    # Predictions (Stage 4)
    STOCK_PREDICTION_INTERVAL_MINUTES: int = 60
    CRYPTO_PREDICTION_INTERVAL_MINUTES: int = 60
    STOCK_PREDICTION_HORIZON_HOURS: int = 24
    CRYPTO_PREDICTION_HORIZON_HOURS: int = 24
    MIN_PRICE_HISTORY_ROWS: int = 200
    MODEL_VERSION: str = "rules-v1"

    # Stripe billing (Stage 5)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Price IDs accept BOTH the canonical name AND the legacy name from the
    # operator's existing .env (STRIPE_PRO_PRICE_ID, STRIPE_BOT_PACK_PRICE_ID).
    # Pydantic-settings v2 AliasChoices picks whichever is set, canonical wins.
    STRIPE_PRICE_PRO: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_PRO", "STRIPE_PRO_PRICE_ID"),
    )
    STRIPE_PRICE_ELITE: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_ELITE", "STRIPE_BOT_PACK_PRICE_ID"),
    )
    STRIPE_SUCCESS_URL: str = "http://localhost:5173/billing/success"
    STRIPE_CANCEL_URL: str = "http://localhost:5173/billing/cancel"
    BILLING_PUBLIC_UPGRADE_URL: str = "http://localhost:5173/pricing"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
