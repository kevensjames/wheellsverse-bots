#!/usr/bin/env python3
"""
core/telegram.py
─────────────────────────────────────────────────────────────────────────────
Telegram Bot notifications.

Sends real-time alerts to your Telegram chat when:
  - A pipeline or bot completes
  - A new lead is captured
  - A blog post goes live
  - A payment/invoice is received (Stripe)
  - An error occurs

Credentials needed in .env:
  TELEGRAM_BOT_TOKEN   — from @BotFather on Telegram
  TELEGRAM_CHAT_ID     — your personal chat ID (send /start to @userinfobot)

Setup (one-time):
  1. Message @BotFather → /newbot → copy token to TELEGRAM_BOT_TOKEN
  2. Message @userinfobot → copy your ID to TELEGRAM_CHAT_ID
  3. Start your bot by messaging it once (required before first send)

Usage:
  from core.telegram import notify
  notify("Pipeline complete: 3 posts published 🚀")
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def is_connected(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, message: str, parse_mode: str = "HTML",
             silent: bool = False) -> bool:
        """
        Send a message to the configured Telegram chat.
        Returns True on success.
        """
        if not self.is_connected():
            logger.debug("Telegram not configured — notification skipped")
            return False

        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_notification": silent,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Telegram sent: {message[:60]}...")
                return True
            else:
                logger.warning(f"Telegram failed [{resp.status_code}]: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return False

    def get_status(self) -> dict:
        if not self.is_connected():
            return {
                "connected": False,
                "reason": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env",
            }
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                bot = resp.json().get("result", {})
                return {
                    "connected": True,
                    "bot_name": bot.get("first_name", ""),
                    "username": f"@{bot.get('username', '')}",
                    "chat_id": self.chat_id,
                }
            return {"connected": False, "error": resp.text[:200]}
        except Exception as e:
            return {"connected": False, "error": str(e)}


# ── Singleton ─────────────────────────────────────────────────────────────────

_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier


def notify(message: str, silent: bool = False) -> bool:
    """Send a Telegram notification. Fails silently if not configured."""
    return get_notifier().send(message, silent=silent)


# ── Preset notification helpers ───────────────────────────────────────────────

def notify_pipeline_complete(pipeline_name: str, published: int, skipped: int,
                              blog_url: str = ""):
    msg = (
        f"✅ <b>Pipeline Complete</b>\n"
        f"📋 {pipeline_name}\n"
        f"📤 Published: <b>{published}</b> channels\n"
        f"⏭ Skipped: {skipped}\n"
    )
    if blog_url:
        msg += f"🔗 <a href='{blog_url}'>View post</a>"
    notify(msg)


def notify_new_lead(email: str, source: str, topic: str = ""):
    # Mask email for privacy in notifications
    parts = email.split("@")
    masked = f"{parts[0][:2]}***@{parts[1]}" if len(parts) == 2 else "***"
    msg = (
        f"🎯 <b>New Lead Captured!</b>\n"
        f"📧 {masked}\n"
        f"📍 Source: {source}\n"
    )
    if topic:
        msg += f"💡 Topic: {topic}"
    notify(msg)


def notify_post_live(title: str, platform: str, url: str = ""):
    msg = (
        f"🚀 <b>Post Live!</b>\n"
        f"📝 {title[:80]}\n"
        f"📱 Platform: {platform}\n"
    )
    if url:
        msg += f"🔗 <a href='{url}'>View</a>"
    notify(msg)


def notify_payment(amount_cents: int, customer_email: str, product: str = ""):
    amount = f"${amount_cents / 100:.2f}"
    parts = customer_email.split("@")
    masked = f"{parts[0][:2]}***@{parts[1]}" if len(parts) == 2 else "***"
    msg = (
        f"💰 <b>Payment Received!</b>\n"
        f"💵 Amount: <b>{amount}</b>\n"
        f"👤 Customer: {masked}\n"
    )
    if product:
        msg += f"🛒 Product: {product}"
    notify(msg)


def notify_error(bot_name: str, error: str):
    msg = (
        f"❌ <b>Bot Error</b>\n"
        f"🤖 {bot_name}\n"
        f"⚠️ {error[:200]}"
    )
    notify(msg, silent=False)


def notify_click(partner: str, total_today: int = 0):
    # OLD: msg = f"🖱 Affiliate click: <b>{partner}</b>"
    # OLD: msg = f"🖱 Product click: <b>{partner}</b>"
    # NEW (2026-06-16): broadcast never exposes the source partner key
    # (doordash / cashapp / robinhood / etc). All clicks land on the owned
    # stan.store product — the notification reflects that exclusively. The
    # partner key is still recorded to data/clicks.json for source attribution.
    msg = "🖱 Product click → <b>stan.store/Wheellsverse</b>"
    if total_today:
        msg += f" (today: {total_today})"
    notify(msg, silent=True)  # Silent — high frequency
