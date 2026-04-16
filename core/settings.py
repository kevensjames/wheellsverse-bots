"""
core/settings.py
Centralized Configuration + Startup Validation

Single source of truth for all environment variables.
Call settings.validate() at app startup — it raises a clear
EnvironmentError listing every missing required variable so the
system fails fast rather than silently producing wrong results.

Usage:
    from core.settings import settings
    settings.validate()  # call once at startup
    print(settings.SHOPIFY_STORE)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("Settings")


@dataclass
class Settings:
    # ── REQUIRED — system cannot function without these ───────────────────
    OPENAI_API_KEY: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    ANTHROPIC_API_KEY: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    SHOPIFY_STORE: str = field(
        default_factory=lambda: os.getenv("SHOPIFY_STORE", "")
    )
    SHOPIFY_TOKEN: str = field(
        default_factory=lambda: (
            os.getenv("SHOPIFY_TOKEN") or
            os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        )
    )
    PRINTIFY_API_KEY: str = field(
        default_factory=lambda: (
            os.getenv("PRINTIFY_API_KEY") or
            os.getenv("PRINTIFY_API_TOKEN", "")
        )
    )

    # ── OPTIONAL — system degrades gracefully without these ───────────────
    STRIPE_SECRET_KEY: Optional[str] = field(
        default_factory=lambda: os.getenv("STRIPE_SECRET_KEY")
    )
    TELEGRAM_BOT_TOKEN: Optional[str] = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    CONVERTKIT_API_KEY: Optional[str] = field(
        default_factory=lambda: (
            os.getenv("CONVERTKIT_API_KEY") or
            os.getenv("CONVERTKIT_KEY")
        )
    )
    CONVERTKIT_API_SECRET: Optional[str] = field(
        default_factory=lambda: os.getenv("CONVERTKIT_API_SECRET")
    )
    OPENAI_MODEL: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    CLAUDE_MODEL: str = field(
        default_factory=lambda: os.getenv(
            "NARAI_MODEL",
            os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        )
    )
    DASHBOARD_PORT: int = field(
        default_factory=lambda: int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "5050")))
    )
    LOG_LEVEL: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    DEBUG: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )

    # ── VALIDATION ────────────────────────────────────────────────────────
    def validate(self) -> None:
        """
        Check all required env vars at startup.
        Raises EnvironmentError listing every missing variable.
        Warns (does not raise) for optional variables.
        """
        required = {
            "OPENAI_API_KEY":    self.OPENAI_API_KEY,
            "ANTHROPIC_API_KEY": self.ANTHROPIC_API_KEY,
            "SHOPIFY_STORE":     self.SHOPIFY_STORE,
            "SHOPIFY_TOKEN":     self.SHOPIFY_TOKEN,
            "PRINTIFY_API_KEY":  self.PRINTIFY_API_KEY,
        }

        missing = [k for k, v in required.items() if not v]

        if missing:
            raise EnvironmentError(
                "\n\n❌ CRITICAL — Missing required environment variables:\n"
                + "\n".join(f"  • {k}" for k in missing)
                + "\n\nSet these in Railway → Variables (or your .env file) "
                "before starting NarAI.\n"
                "See .env.example for the full list.\n"
            )

        # Warn about missing optional vars (don't crash)
        optional_missing = []
        if not self.STRIPE_SECRET_KEY:
            optional_missing.append("STRIPE_SECRET_KEY (revenue tracking disabled)")
        if not self.TELEGRAM_BOT_TOKEN:
            optional_missing.append("TELEGRAM_BOT_TOKEN (notifications disabled)")
        if not self.CONVERTKIT_API_KEY:
            optional_missing.append("CONVERTKIT_API_KEY (email broadcasts disabled)")

        if optional_missing:
            log.warning(
                "Optional env vars not set — some features disabled:\n"
                + "\n".join(f"  • {v}" for v in optional_missing)
            )

        log.info(
            f"✅ Settings validated | "
            f"model={self.OPENAI_MODEL} | "
            f"claude={self.CLAUDE_MODEL} | "
            f"port={self.DASHBOARD_PORT} | "
            f"debug={self.DEBUG}"
        )

    def summary(self) -> dict:
        """Return non-sensitive settings summary for status endpoints."""
        return {
            "openai_model":    self.OPENAI_MODEL,
            "claude_model":    self.CLAUDE_MODEL,
            "shopify_store":   self.SHOPIFY_STORE,
            "has_printify":    bool(self.PRINTIFY_API_KEY),
            "has_stripe":      bool(self.STRIPE_SECRET_KEY),
            "has_telegram":    bool(self.TELEGRAM_BOT_TOKEN),
            "has_convertkit":  bool(self.CONVERTKIT_API_KEY),
            "dashboard_port":  self.DASHBOARD_PORT,
            "debug":           self.DEBUG,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
settings = Settings()
