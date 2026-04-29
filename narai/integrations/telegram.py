import os
import logging
import re

from telegram import Bot, Update
from telegram.constants import ParseMode

logger = logging.getLogger("narai.telegram")

OWNER_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_PATH = "/api/v2/narai/telegram/webhook"


async def setup_webhook(base_url: str) -> None:
    """Register the webhook with Telegram on startup. Idempotent — safe on redeploy."""
    bot = Bot(TOKEN)
    url = f"{base_url.rstrip('/')}{WEBHOOK_PATH}"
    await bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET or None)
    logger.info(f"Telegram webhook registered: {url}")


def _format_reply(text: str) -> str:
    """Convert plain NarAI markdown to Telegram HTML (bold + inline code only)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


async def handle_update(update_data: dict) -> None:
    """Parse a raw Telegram update dict, run NarAI pipeline, send reply.

    Public deep-links (`/start <pairing_token>`) are handled before the
    owner-only check so paying subscribers can pair without being silently
    dropped. Other non-owner messages are still dropped.
    """
    from narai.api.routes.chat import run_pipeline_async

    update = Update.de_json(update_data, Bot(TOKEN))
    msg = update.message or update.edited_message
    if msg is None:
        return

    text = (msg.text or "").strip()

    # Public path: subscription deep-link from Stripe success page.
    if text.startswith("/start ") and msg.from_user is not None:
        token = text[len("/start "):].strip()
        if token:
            await _handle_pairing_deep_link(msg, token)
            return

    if msg.chat_id != OWNER_CHAT_ID:
        logger.warning(f"Dropping message from non-owner chat_id={msg.chat_id}")
        return

    if not text:
        return

    bot = Bot(TOKEN)

    # /mode <operator|companion> and /reset translate into natural-language
    # phrases the mode_router already understands — no special pipeline path needed.
    if text.startswith("/mode "):
        text = f"stay in {text.split(None, 1)[1].strip()} mode"
    elif text == "/reset":
        text = "release mode lock"
    elif text == "/help":
        await bot.send_message(
            chat_id=msg.chat_id,
            text=(
                "<b>NarAI Telegram</b>\n\n"
                "/mode operator — force operator mode\n"
                "/mode companion — force companion mode\n"
                "/reset — release mode lock\n"
                "/help — this message"
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    await bot.send_chat_action(chat_id=msg.chat_id, action="typing")
    result = await run_pipeline_async(user_id="owner", user_message=text)
    await bot.send_message(
        chat_id=msg.chat_id,
        text=_format_reply(result["reply"]),
        parse_mode=ParseMode.HTML,
    )
    logger.info(
        f"Telegram turn: mode={result['mode']} overwhelm={result['overwhelm']} "
        f"tier={result['tier']} tokens={result['tokens']}"
    )


_PAIRING_ERROR_MESSAGES = {
    "unknown_token": (
        "That subscription link isn't recognized. "
        "If you just paid, please wait a few seconds and try again."
    ),
    "wrong_status:pending_payment": (
        "Payment hasn't completed yet — please try again in a moment."
    ),
    "wrong_status:active": (
        "You're already subscribed. Check this chat for your existing invite link."
    ),
    "wrong_status:revoked": (
        "Your subscription has ended. Resubscribe at app.wheellsverse.com to rejoin."
    ),
    "token_expired": (
        "That checkout link expired. Please start a new subscription."
    ),
    "channel_not_configured": (
        "The subscription system isn't set up yet. Please contact support."
    ),
}


async def _handle_pairing_deep_link(msg, token: str) -> None:
    """Validate a pairing token, mint a single-use channel invite, DM it back."""
    from datetime import datetime, timedelta, timezone
    from narai.integrations import telegram_subscription as ts

    bot = Bot(TOKEN)
    pre = ts.begin_pairing(token)
    if not pre["ok"]:
        await bot.send_message(
            chat_id=msg.chat_id,
            text=_PAIRING_ERROR_MESSAGES.get(
                pre["error"], f"Couldn't process subscription: {pre['error']}"
            ),
        )
        return

    expire = datetime.now(timezone.utc) + timedelta(seconds=ts.INVITE_LINK_TTL_SEC)
    try:
        link = await bot.create_chat_invite_link(
            chat_id=pre["channel_id"],
            member_limit=1,
            expire_date=expire,
            name=f"sub:{token[:8]}",
        )
    except Exception as e:
        logger.exception("create_chat_invite_link failed")
        await bot.send_message(
            chat_id=msg.chat_id,
            text=(
                "Couldn't generate your invite link right now. "
                "We've logged the issue — please try again in a minute."
            ),
        )
        return

    ts.finalize_pairing(
        token=token,
        telegram_user_id=msg.from_user.id,
        channel_id=pre["channel_id"],
        invite_link=link.invite_link,
    )
    await bot.send_message(
        chat_id=msg.chat_id,
        text=(
            "✅ <b>You're in.</b>\n\n"
            "Here's your single-use invite (expires in 1 hour):\n\n"
            f"{link.invite_link}\n\n"
            "Tap the link to join the private channel."
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
