from functools import lru_cache
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Admin-token hardening (see dependencies/admin.py). In production the effective
# admin token — ADMIN_TOKEN, or the legacy JWT_SECRET_KEY fallback — must be a
# strong secret; the app refuses to boot otherwise.
_MIN_ADMIN_TOKEN_LEN = 32
_WEAK_ADMIN_TOKENS = frozenset({"", "change_me_to_a_long_random_string"})
_NON_PROD_ENVS = frozenset({"development", "dev", "local", "test", "testing", "ci"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Wheellsverse"
    APP_ENV: str = "development"
    # Safe-by-default: DEBUG must be opted INTO, never left on by omission. A
    # debug-mode app leaks tracebacks (Starlette's ServerErrorMiddleware) and is
    # refused in production by the validator below.
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

    @model_validator(mode="after")
    def _enforce_strong_admin_token_in_prod(self):
        """Refuse to boot in production on a weak/absent admin token. The whole
        admin surface (journals, persona, relationship data, Sol money admin) is
        guarded by this single shared secret, so a short or example-default one
        is a full-compromise risk. Dev/test/local are exempt to stay frictionless."""
        env = (self.APP_ENV or "").strip().lower()
        if env in _NON_PROD_ENVS:
            return self
        tok = self.ADMIN_TOKEN or self.JWT_SECRET_KEY
        if tok in _WEAK_ADMIN_TOKENS or len(tok) < _MIN_ADMIN_TOKEN_LEN:
            raise ValueError(
                f"Refusing to boot in APP_ENV='{self.APP_ENV}': a strong ADMIN_TOKEN "
                f"is required (>= {_MIN_ADMIN_TOKEN_LEN} chars, not the example default). "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return self

    @model_validator(mode="after")
    def _enforce_debug_off_in_prod(self):
        """DEBUG in production leaks stack traces + disables the generic-500
        handler. Refuse to boot debug-on outside a non-prod env."""
        env = (self.APP_ENV or "").strip().lower()
        if env not in _NON_PROD_ENVS and self.DEBUG:
            raise ValueError(
                f"Refusing to boot in APP_ENV='{self.APP_ENV}' with DEBUG=True "
                "(leaks tracebacks). Set DEBUG=false in production."
            )
        return self

    @model_validator(mode="after")
    def _enforce_stripe_money_mode(self):
        """Bind the Stripe key mode to APP_ENV so a mismatch can't silently move
        (or fail to move) real money. Nothing else in the codebase ties the
        sk_test_/sk_live_ prefix to the environment — a live key on a staging box
        would charge real cards, and a test key in production would hand everyone
        $0 upgrades. (Mirrors the Dwolla sandbox latch.) Empty key = billing off,
        allowed anywhere. The DECISION to use a live key in production is the
        operator's; this only refuses the dangerous mismatches."""
        key = (self.STRIPE_SECRET_KEY or "").strip()
        if not key:
            return self
        env = (self.APP_ENV or "").strip().lower()
        is_prod = env not in _NON_PROD_ENVS
        if key.startswith("sk_live_") and not is_prod:
            raise ValueError(
                f"Refusing to boot: a LIVE Stripe key (sk_live_) in APP_ENV='{self.APP_ENV}' "
                "would charge real cards off production. Use a test key (sk_test_) here."
            )
        if key.startswith("sk_test_") and is_prod:
            raise ValueError(
                f"Refusing to boot in APP_ENV='{self.APP_ENV}': a TEST Stripe key gives "
                "everyone $0 upgrades. Set a live key (sk_live_) or run staging/mock money."
            )
        if not key.startswith(("sk_test_", "sk_live_")):
            raise ValueError(
                "STRIPE_SECRET_KEY set but not a recognized mode (sk_test_/sk_live_)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
