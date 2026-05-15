#!/usr/bin/env python3
"""
core/discord_client.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Discord Webhook Poster

Minimal Discord integration — posts announcements to a Discord channel via
webhook URL. No bot, no OAuth, no slash commands. Just notifications.

Usage:
    from core.discord_client import DiscordClient
    c = DiscordClient()
    c.post("🎣 New drop: 1000 Viral TikTok Hooks — $47", url="https://...")

Setup:
    1. In Discord, go to channel → Edit Channel → Integrations → Webhooks
    2. Create New Webhook → Copy URL
    3. Add to .env: DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

Optionally set DISCORD_USERNAME and DISCORD_AVATAR_URL in .env.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("discord_client")


class DiscordClient:
    """Lightweight Discord webhook poster — no bot account required."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
        self.username = os.getenv("DISCORD_USERNAME", "WheellsVerse")
        self.avatar_url = os.getenv("DISCORD_AVATAR_URL", "")
        if not self.webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL not set — posts will no-op")

    def post(self, content: str, url: Optional[str] = None) -> bool:
        """Post a plain-text announcement. Returns True on success."""
        if not self.webhook_url:
            return False
        body = content if not url else f"{content}\n{url}"
        payload = {"content": body, "username": self.username}
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        try:
            r = httpx.post(self.webhook_url, json=payload, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error("Discord post failed: %s", e)
            return False

    def post_product_drop(
        self,
        title: str,
        short_desc: str,
        price_usd: float,
        buy_url: str,
        emoji: str = "🚀",
        thumbnail_url: Optional[str] = None,
    ) -> bool:
        """Post a structured product drop announcement using an embed."""
        if not self.webhook_url:
            return False
        embed = {
            "title": f"{emoji} {title}",
            "description": short_desc,
            "url": buy_url,
            "color": 0x9C5AFF,  # WheellsVerse purple
            "fields": [
                {"name": "Price", "value": f"${price_usd:,.2f}", "inline": True},
                {"name": "Get it", "value": f"[Buy now]({buy_url})", "inline": True},
            ],
        }
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
        payload = {
            "username": self.username,
            "embeds": [embed],
        }
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        try:
            r = httpx.post(self.webhook_url, json=payload, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error("Discord product drop failed: %s", e)
            return False


def _smoke_test():
    """Manual smoke test — run with: python -m core.discord_client"""
    c = DiscordClient()
    if not c.webhook_url:
        print("Set DISCORD_WEBHOOK_URL in .env first")
        return
    ok = c.post("✅ DiscordClient smoke test from WheellsVerse core/discord_client.py")
    print("Smoke test:", "OK" if ok else "FAILED")


if __name__ == "__main__":
    _smoke_test()
