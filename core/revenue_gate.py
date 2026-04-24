#!/usr/bin/env python3
"""
core/revenue_gate.py
─────────────────────────────────────────────────────────────────────────────
Audience-threshold gate that pauses content-creation bots when the audience
is too small to justify more content.

WHY THIS EXISTS:
    Screenshots showed:
    - 112 blog articles live
    - $0.00 today, $0.00 7-day
    - 0 clicks, 2 subscribers
    - "Bots ran: 0" in revenue pipeline

    The bottleneck is distribution, not creation. More blog posts won't
    help. This gate forces the system into DISTRIBUTE mode until any of
    the audience metrics crosses a minimum threshold.

WHICH CATEGORIES ARE GATED:
    The gate is category-based. Content-creation categories are gated;
    infrastructure/monitoring/response categories are not.

    Default GATED categories (pause when audience small):
        marketing, books, social_media, seo_autopilot, specialized,
        ecommerce, business, sales
    Default BYPASS categories (always run):
        agent_workforce, narai, assistant, problem_solving, tool_catalog,
        prompt_intel, core

    Override via env:
        WV_REVENUE_GATED_CATEGORIES   (comma-separated)
        WV_REVENUE_BYPASS_CATEGORIES  (comma-separated)

THRESHOLD LOGIC:
    If ANY of (subscribers, weekly_clicks, weekly_revenue) crosses its
    minimum, CREATE mode unlocks. Below all three → DISTRIBUTE only.

    Env override:
        WV_MIN_SUBSCRIBERS         (int, default 100)
        WV_MIN_WEEKLY_CLICKS       (int, default 50)
        WV_MIN_WEEKLY_REVENUE_USD  (float, default 10.0)

METRICS SOURCE:
    Default reads from env vars (WV_SUBSCRIBERS / WV_WEEKLY_CLICKS /
    WV_WEEKLY_REVENUE_USD) so you can set them from a cron that polls
    ConvertKit, Plausible, Stripe, etc.

    Swap in a real metrics function via set_metrics_provider().
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable, List, Optional, Set

# ─── Types ────────────────────────────────────────────────────────────────────
class Mode(str, Enum):
    CREATE = "create"
    DISTRIBUTE = "distribute"


@dataclass
class GateConfig:
    min_subscribers: int = int(os.getenv("WV_MIN_SUBSCRIBERS", "100"))
    min_weekly_clicks: int = int(os.getenv("WV_MIN_WEEKLY_CLICKS", "50"))
    min_weekly_revenue_usd: float = float(os.getenv("WV_MIN_WEEKLY_REVENUE_USD", "10"))


@dataclass
class Metrics:
    subscribers: int
    weekly_clicks: int
    weekly_revenue_usd: float


# ─── Category policy ─────────────────────────────────────────────────────────
_DEFAULT_GATED = {
    "marketing", "books", "social_media", "seo_autopilot",
    "specialized", "ecommerce", "business", "sales",
}
_DEFAULT_BYPASS = {
    "agent_workforce", "narai", "assistant", "problem_solving",
    "tool_catalog", "prompt_intel", "core",
}


def _csv_to_set(v: Optional[str]) -> Set[str]:
    return {s.strip() for s in v.split(",") if s.strip()} if v else set()


_GATED_CATEGORIES: Set[str] = _csv_to_set(os.getenv("WV_REVENUE_GATED_CATEGORIES")) or _DEFAULT_GATED
_BYPASS_CATEGORIES: Set[str] = _csv_to_set(os.getenv("WV_REVENUE_BYPASS_CATEGORIES")) or _DEFAULT_BYPASS


def is_category_gated(category: str) -> bool:
    """Return True if bots in this category should be suppressed when
    audience metrics are below threshold. Explicit bypass wins over
    explicit gate (safer default: if both listed, don't block)."""
    if category in _BYPASS_CATEGORIES:
        return False
    return category in _GATED_CATEGORIES


# ─── Metrics provider ────────────────────────────────────────────────────────
_metrics_provider: Optional[Callable[[], Metrics]] = None


def set_metrics_provider(fn: Callable[[], Metrics]) -> None:
    """Install a callable that returns current Metrics. Call this once at
    app startup after you've wired ConvertKit/Plausible/Stripe clients."""
    global _metrics_provider
    _metrics_provider = fn


def _env_metrics() -> Metrics:
    """Default provider — reads from env vars. Replace with real API calls:
        - ConvertKit / Beehiiv / Substack for subscribers
        - Plausible / GA4 for weekly_clicks
        - Stripe for weekly_revenue_usd
    A cron can write the env vars to a dotenv file, or set_metrics_provider
    can be called with a real function.
    """
    return Metrics(
        subscribers=int(os.getenv("WV_SUBSCRIBERS", "0")),
        weekly_clicks=int(os.getenv("WV_WEEKLY_CLICKS", "0")),
        weekly_revenue_usd=float(os.getenv("WV_WEEKLY_REVENUE_USD", "0")),
    )


def _get_metrics() -> Metrics:
    fn = _metrics_provider or _env_metrics
    try:
        return fn()
    except Exception as e:
        # Fail safe: if we can't read metrics, don't block creation.
        # Better to over-create while metrics are broken than over-gate.
        print(f"[revenue_gate] metrics fetch failed ({e}) — defaulting to CREATE")
        return Metrics(
            subscribers=10_000,
            weekly_clicks=10_000,
            weekly_revenue_usd=10_000.0,
        )


# ─── Gate logic ──────────────────────────────────────────────────────────────
def check_mode(config: Optional[GateConfig] = None) -> Mode:
    """Return CREATE if audience is big enough, DISTRIBUTE otherwise."""
    cfg = config or GateConfig()
    m = _get_metrics()
    if (
        m.subscribers >= cfg.min_subscribers
        or m.weekly_clicks >= cfg.min_weekly_clicks
        or m.weekly_revenue_usd >= cfg.min_weekly_revenue_usd
    ):
        return Mode.CREATE
    return Mode.DISTRIBUTE


def should_block(category: str, config: Optional[GateConfig] = None) -> bool:
    """
    True if a bot in the given category should be skipped RIGHT NOW.
    Used by BaseBot.execute() to decide whether to run or bail early.
    """
    if not is_category_gated(category):
        return False
    return check_mode(config) == Mode.DISTRIBUTE


def explain(category: str, config: Optional[GateConfig] = None) -> dict:
    """Human-readable snapshot — useful for dashboards and debug logs."""
    cfg = config or GateConfig()
    m = _get_metrics()
    mode = check_mode(cfg)
    gated = is_category_gated(category)
    return {
        "category": category,
        "category_gated": gated,
        "mode": mode.value,
        "metrics": {
            "subscribers": m.subscribers,
            "weekly_clicks": m.weekly_clicks,
            "weekly_revenue_usd": m.weekly_revenue_usd,
        },
        "thresholds": {
            "min_subscribers": cfg.min_subscribers,
            "min_weekly_clicks": cfg.min_weekly_clicks,
            "min_weekly_revenue_usd": cfg.min_weekly_revenue_usd,
        },
        "blocked": gated and mode == Mode.DISTRIBUTE,
    }


def requires_audience(category: str, config: Optional[GateConfig] = None):
    """Decorator for standalone functions (non-BaseBot callers).
    BaseBot.execute() does this automatically — you only need this if you
    have a utility function that should also respect the gate."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if should_block(category, config):
                print(
                    f"[revenue_gate] {func.__name__} blocked — DISTRIBUTE mode. "
                    f"Push existing content to humans first."
                )
                return None
            return func(*args, **kwargs)

        return wrapper

    return decorator
