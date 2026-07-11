"""Rate-limited operator alerts for LLM-provider degradation.

The router degrades Anthropic → OpenAI → local Ollama on failure. Historically
that degradation was *silent*: a ``logger.warning`` plus an ``llm_call_log`` row
nobody queries. KAI's persona could collapse to a local model with the operator
none the wiser. This module turns each degradation into a Telegram alert.

Design (mirrors ``router._log_failure_safe`` discipline):
- **Best-effort, never fatal.** Alerting a failure must never *defeat* the
  fallback or *mask* the original provider error, so every path here swallows
  its own exceptions.
- **Non-blocking.** Reuses ``observability.notify`` (fire-and-forget daemon
  thread) — we do not wait on Telegram from the chat hot path.
- **Rate-limited per provider.** At most one alert per provider per window
  (default 1h, ``KAI_ALERT_MIN_INTERVAL_SECONDS``) so a provider outage that
  trips on every request can't spam the operator into muting the channel.
- In-memory window state — fine for the single-worker uvicorn we ship (see
  ``core/rate_limit.py`` for the same tradeoff).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL_SECONDS = 3600  # one alert per provider per hour

_lock = threading.Lock()
_last_sent: dict[str, float] = {}  # key -> time.monotonic() of last alert sent


def _min_interval() -> float:
    raw = (os.environ.get("KAI_ALERT_MIN_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return float(_DEFAULT_MIN_INTERVAL_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(_DEFAULT_MIN_INTERVAL_SECONDS)


def _should_send(key: str, now: float) -> bool:
    """True iff no alert for ``key`` went out within the min interval. Records
    ``now`` as the last-send time when it returns True. Thread-safe."""
    interval = _min_interval()
    with _lock:
        last = _last_sent.get(key)
        if last is not None and (now - last) < interval:
            return False
        _last_sent[key] = now
        return True


def _extract_status(exc: BaseException) -> int | None:
    """Best-effort HTTP status off a provider-SDK exception. OpenAI/Anthropic
    SDK errors expose ``.status_code``; httpx errors carry ``.response.status_code``.
    Returns None when nothing usable is present."""
    for attr in ("status_code", "http_status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    v = getattr(resp, "status_code", None)
    return v if isinstance(v, int) else None


def provider_alert(
    *, provider: str, exc: BaseException, active_fallback: str | None
) -> bool:
    """Alert the operator that ``provider`` failed and traffic moved to
    ``active_fallback`` (or nothing, when the whole ladder is exhausted).

    Rate-limited per provider. Returns True if an alert was handed to the
    notifier, False if it was suppressed within the window (or an internal error
    was swallowed). Because delivery is fire-and-forget, True means "dispatched",
    not "delivered" — when Telegram is unconfigured the notifier no-ops.
    **Never raises.**
    """
    try:
        now = time.monotonic()
        if not _should_send(f"provider:{provider}", now):
            logger.info(
                "alerts: provider '%s' degradation alert suppressed (within window)",
                provider,
            )
            return False
        status = _extract_status(exc)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            "⚠️ <b>KAI provider degraded</b>",
            f"failed: <b>{_esc(provider)}</b>",
            f"error: <code>{_esc(type(exc).__name__)}</code>",
        ]
        if status is not None:
            lines.append(f"http: <b>{status}</b>")
        lines.append(
            f"now serving: <b>{_esc(active_fallback) if active_fallback else 'ERROR (no fallback left)'}</b>"
        )
        lines.append(f"at: {ts}")
        from app.services import observability

        observability.notify("\n".join(lines))
        return True
    except Exception as e:  # pragma: no cover - alerting must never crash caller
        logger.warning("alerts: provider_alert swallowed: %s", e)
        return False


def reset_state() -> None:
    """Clear the rate-limit window. For tests only."""
    with _lock:
        _last_sent.clear()


def _esc(s: str) -> str:
    return (str(s) if s else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
