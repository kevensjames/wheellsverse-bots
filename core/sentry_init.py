"""Sentry initialization — call once at app startup.

Usage:
    # In core/api.py, near the top of the file:
    from core.sentry_init import init_sentry
    init_sentry()

Setup:
    1. Create a project at https://sentry.io
    2. Copy the DSN (looks like: https://abc123@o12345.ingest.sentry.io/67890)
    3. Add to .env: SENTRY_DSN=...
    4. (Optional) Add SENTRY_ENV=production and SENTRY_RELEASE=git-sha

Without SENTRY_DSN set, this is a silent no-op — safe to call unconditionally.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_initialized = False


def init_sentry() -> bool:
    """Returns True if Sentry was initialized, False if skipped (no DSN or import failed)."""
    global _initialized
    if _initialized:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("SENTRY_DSN not set — Sentry disabled (set it in .env to enable)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        log.warning(
            "SENTRY_DSN is set but sentry-sdk not installed. "
            "Run: pip install 'sentry-sdk[fastapi]>=2.0.0'"
        )
        return False

    env = os.getenv("SENTRY_ENV", os.getenv("ENV", "production"))
    release = os.getenv("SENTRY_RELEASE") or os.getenv("GIT_SHA")
    sample_rate = float(os.getenv("SENTRY_SAMPLE_RATE", "1.0"))
    traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        release=release,
        sample_rate=sample_rate,
        traces_sample_rate=traces_rate,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    _initialized = True
    log.info(f"Sentry initialized (env={env}, release={release or 'unset'})")
    return True
