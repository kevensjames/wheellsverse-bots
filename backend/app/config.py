from functools import lru_cache
from typing import List

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
    # Safe default: OFF. Debug tracebacks in HTTP/SSE responses leak internals,
    # so development must explicitly opt in with DEBUG=true — we never rely on
    # deployment discipline to keep it off in staging/prod.
    DEBUG: bool = False

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

    # ── Unified operator session (merge Phase P2). Default OFF. When enabled,
    #    require_admin_token also accepts a valid wv_session cookie signed with
    #    SESSION_SIGNING_SECRET, which MUST match App A's value so one login
    #    authenticates both apps. Legacy X-Admin-Token stays valid regardless.
    OPERATOR_SESSION_ENABLED: bool = False
    SESSION_SIGNING_SECRET: str = ""
    # Holding Operations OS — governed READ-ONLY holding endpoints. Default off:
    # when False the router is not mounted at all (zero new surface).
    KAI_HOLDING_ENABLED: bool = False
    # Daily morning-briefing routine (report-only, no external send). Default off.
    KAI_HOLDING_BRIEFING_ENABLED: bool = False
    KAI_HOLDING_BRIEFING_UTC_HOUR: int = 11   # 07:00 America/New_York (EDT); use 12 for EST
    # OPT-IN briefing delivery to the operator's own channel (Telegram). Default OFF — a deliberate
    # exception to report-only; nothing sends unless this is true AND a channel is configured.
    KAI_HOLDING_DELIVERY_ENABLED: bool = False
    # Continuous watch loop (Wave 1): proactive change/anomaly detection across entities. Default OFF.
    # Read-only; alerts deliver only if KAI_HOLDING_DELIVERY_ENABLED + a channel is configured too.
    KAI_HOLDING_WATCH_ENABLED: bool = False

    # Telegram alerting — used by app.services.observability to notify the
    # operator of signup / paid-conversion / cancellation events. Optional;
    # if either is empty, alerts are silently skipped.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

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
    # Canonical names only. Legacy aliases (STRIPE_PRO_PRICE_ID,
    # STRIPE_BOT_PACK_PRICE_ID) were dropped 2026-06-04 after they silently
    # resolved to a stale $29 May-era price while the UI advertised $19 —
    # see docs/decisions/0010-rename-nai-to-kai.md addendum.
    STRIPE_PRICE_PRO: str = ""
    # NOTE: "Elite" was Stage 5's marketing name. Prod schema's CHECK
    # constraint allows tiers ('pro','max','ultra') — there is no 'elite'
    # tier. The Elite button in pricing.html stays hidden until the
    # operator creates real Max/Ultra recurring prices in Stripe and sets
    # the corresponding env vars below.
    STRIPE_PRICE_ELITE: str = ""
    STRIPE_PRICE_MAX: str = ""
    STRIPE_PRICE_ULTRA: str = ""
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
