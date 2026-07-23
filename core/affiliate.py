#!/usr/bin/env python3
"""
core/affiliate.py
─────────────────────────────────────────────────────────────────────────────
Shared affiliate-link utilities for the WheellsVerse bots.

Previously every affiliate/content bot copy-pasted the same ``_utm`` builder
plus the ``_DIGITAL`` / ``_BLOG`` / ``_CAMP`` / ``AMAZON_TAG`` constants. Per
the ``affiliate_swap`` passes, every CTA now routes through an owned
destination (digital product / blog) with UTM tagging instead of raw
``/go/<partner>`` redirects. This module is the single source of truth.

Usage in a bot::

    from core.affiliate import make_utm, AMAZON_TAG, BLOG_URL

    _utm = make_utm("77_ai_tools_affiliate_bot")
    COINBASE_URL = _utm("coinbase")
    CTA_URL = _utm("cta", medium="blog", base=BLOG_URL)
─────────────────────────────────────────────────────────────────────────────
"""
import os
from typing import Callable

# Owned destinations every affiliate CTA routes through.
STAN_STORE_URL = "https://stan.store/Wheellsverse"
BLOG_URL = "https://wheellsverse.com/blog/"

# Active UTM campaign for the current affiliate-swap pass.
DEFAULT_CAMPAIGN = "affiliate_swap_pass2_2026_06_02"

# Amazon Associates tracking tags.
AMAZON_TAG = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
AMAZON_TAG_2 = os.getenv("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")


def utm_link(source: str, content: str, medium: str = "content",
             campaign: str = DEFAULT_CAMPAIGN, base: str = STAN_STORE_URL) -> str:
    """Build a UTM-tagged URL pointing at an owned destination."""
    return (
        f"{base}?utm_source={source}&utm_medium={medium}"
        f"&utm_campaign={campaign}&utm_content={content}"
    )


def make_utm(source: str, campaign: str = DEFAULT_CAMPAIGN) -> Callable[..., str]:
    """Return a per-bot ``_utm(content, medium, base)`` builder bound to ``source``.

    ``source`` is the bot name (used as ``utm_source``); ``campaign`` defaults
    to the current affiliate-swap pass and may be overridden per bot.
    """
    def _utm(content: str, medium: str = "content", base: str = STAN_STORE_URL) -> str:
        return utm_link(source, content, medium=medium, campaign=campaign, base=base)
    return _utm
