#!/usr/bin/env python3
"""
core/telegram_bot.py
─────────────────────────────────────────────────────────────────────────────
NarAI Telegram bot integration.

Commands:
  /start            — Welcome message
  /help             — List commands
  /ask <question>   — Ask NarAI a question
  /bots             — List running bots
  /startbot <name>  — Start a bot
  /stopbot <name>   — Stop a bot
  /status           — System status
  /run <code>       — Generate + run code

Plain messages → NarAI response (uses per-chat conversation context).
Voice messages → transcribe with Whisper → NarAI.

Webhook mode when TELEGRAM_WEBHOOK_URL is set, polling mode otherwise.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os

logger = logging.getLogger("telegram_bot")

_app = None        # telegram.ext.Application
_started = False


def is_enabled() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN"))


async def _get_narai_response(text: str, chat_id: str) -> str:
    """Get NarAI response for a Telegram message."""
    try:
        import anthropic
        from core.chat_db import (
            add_message, create_conversation, get_claude_history,
            get_setting,
        )
        from core.memory_engine import format_memory_context

        # Use chat_id as conversation ID prefix for per-chat context

        # Find or create a conversation keyed to this Telegram chat
        conn = None
        try:
            from core.chat_db import _get_conn, _lock
            conn = _get_conn()
            with _lock:
                row = conn.execute(
                    "SELECT id FROM conversations WHERE title=? LIMIT 1",
                    (f"Telegram:{chat_id}",)
                ).fetchone()
            conv_id = row[0] if row else create_conversation(title=f"Telegram:{chat_id}")
        except Exception:
            conv_id = create_conversation(title=f"Telegram:{chat_id}")

        sys_prompt = (
            get_setting("system_prompt") or
            "You are NarAI, a powerful AI assistant built by Jhon (J.K. Blaze) for WheellsVerse. "
            "You are talking via Telegram. Be concise — Telegram messages should be short and clear."
        )

        mem_ctx = format_memory_context()
        if mem_ctx:
            sys_prompt = mem_ctx + "\n" + sys_prompt

        history = get_claude_history(conv_id, max_messages=20)
        add_message(conv_id, "user", text)

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        model = get_setting("default_model") or "claude-sonnet-4-6"
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=sys_prompt,
            messages=history + [{"role": "user", "content": text}],
        )
        response_text = resp.content[0].text if resp.content else "Sorry, I couldn't process that."
        add_message(conv_id, "assistant", response_text)
        return response_text

    except Exception as e:
        logger.error(f"[telegram] NarAI response error: {e}")
        return f"Error: {e}"


async def _start(update, context):
    await update.message.reply_text(
        "🌟 Hello! I'm *NarAI*, your WheellsVerse AI assistant.\n\n"
        "Commands:\n"
        "/ask <question> — Ask me anything\n"
        "/bots — List running bots\n"
        "/startbot <name> — Start a bot\n"
        "/stopbot <name> — Stop a bot\n"
        "/status — System status\n\n"
        "Or just send me any message!",
        parse_mode="Markdown"
    )


async def _help_cmd(update, context):
    await update.message.reply_text(
        "🤖 *NarAI Commands*\n\n"
        "/ask <question> — Ask NarAI\n"
        "/bots — List all running bots\n"
        "/startbot <name> — Start bot (category/name)\n"
        "/stopbot <name> — Stop a running bot\n"
        "/status — Platform health\n"
        "/run <prompt> — Generate + describe code\n\n"
        "Or send any message to chat with NarAI!",
        parse_mode="Markdown"
    )


async def _ask_cmd(update, context):
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    await update.message.chat.send_action("typing")
    response = await _get_narai_response(question, str(update.effective_chat.id))
    # Split long responses
    for i in range(0, len(response), 4000):
        await update.message.reply_text(response[i:i + 4000])


async def _bots_cmd(update, context):
    try:
        from core.bot_manager import list_bots
        running = list_bots()
        if not running:
            await update.message.reply_text("No bots currently running.")
            return
        lines = ["🤖 *Running Bots*\n"]
        for b in running:
            status_icon = "🟢" if b.get("status") == "running" else "🔴"
            lines.append(f"{status_icon} `{b['name']}` — {b.get('status', 'unknown')}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def _startbot_cmd(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /startbot <name> [category]")
        return
    name = context.args[0]
    category = context.args[1] if len(context.args) > 1 else ""
    try:
        from core.bot_manager import start_bot
        result = start_bot(name, category)
        await update.message.reply_text(f"✅ Bot `{name}` started (PID {result.get('pid', '?')})", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to start bot: {e}")


async def _stopbot_cmd(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /stopbot <name>")
        return
    name = context.args[0]
    try:
        from core.bot_manager import stop_bot
        stop_bot(name)
        await update.message.reply_text(f"🛑 Bot `{name}` stopped", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def _status_cmd(update, context):
    try:
        from core.bot_manager import list_bots
        running = list_bots()
        await update.message.reply_text(
            f"📊 *WheellsVerse Status*\n\n"
            f"🤖 Running bots: {len(running)}\n"
            f"🌐 API: Online\n"
            f"🧠 NarAI: Active",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Status error: {e}")


async def _run_cmd(update, context):
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("Usage: /run <describe what code should do>")
        return
    await update.message.chat.send_action("typing")
    try:
        from core.code_engine import generate_code, validate_code
        code = generate_code(prompt)
        valid, err = validate_code(code)
        preview = code[:800] + ("..." if len(code) > 800 else "")
        status = "✅ Valid" if valid else f"⚠️ Syntax error: {err}"
        await update.message.reply_text(
            f"Generated code ({status}):\n\n```python\n{preview}\n```",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Code gen error: {e}")


async def _message_handler(update, context):
    """Handle plain text messages → NarAI chat."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return
    await update.message.chat.send_action("typing")
    response = await _get_narai_response(text, str(update.effective_chat.id))
    for i in range(0, len(response), 4000):
        await update.message.reply_text(response[i:i + 4000])


async def _voice_handler(update, context):
    """Handle voice messages → Whisper → NarAI."""
    if not update.message or not update.message.voice:
        return
    try:
        import tempfile
        from openai import OpenAI
        oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, "rb") as f:
                transcript = oai.audio.transcriptions.create(model="whisper-1", file=f)
        text = transcript.text.strip()
        if not text:
            await update.message.reply_text("Sorry, couldn't transcribe your voice message.")
            return
        await update.message.reply_text(f"🎙 *You said:* {text}", parse_mode="Markdown")
        await update.message.chat.send_action("typing")
        response = await _get_narai_response(text, str(update.effective_chat.id))
        await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(f"Voice transcription error: {e}")


async def start_bot_service():
    """Start the Telegram bot (webhook or polling)."""
    global _app, _started
    if _started:
        return
    if not is_enabled():
        logger.info("[telegram] TELEGRAM_BOT_TOKEN not set — skipping")
        return

    try:
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
    except ImportError:
        logger.warning("[telegram] python-telegram-bot not installed. Run: pip install 'python-telegram-bot[webhooks]>=20.0'")
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    _app = Application.builder().token(token).build()

    # Register handlers
    _app.add_handler(CommandHandler("start", _start))
    _app.add_handler(CommandHandler("help", _help_cmd))
    _app.add_handler(CommandHandler("ask", _ask_cmd))
    _app.add_handler(CommandHandler("bots", _bots_cmd))
    _app.add_handler(CommandHandler("startbot", _startbot_cmd))
    _app.add_handler(CommandHandler("stopbot", _stopbot_cmd))
    _app.add_handler(CommandHandler("status", _status_cmd))
    _app.add_handler(CommandHandler("run", _run_cmd))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler))
    _app.add_handler(MessageHandler(filters.VOICE, _voice_handler))

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    if webhook_url:
        # Webhook mode (production)
        await _app.bot.set_webhook(url=webhook_url)
        await _app.initialize()
        await _app.start()
        logger.info(f"[telegram] Webhook set: {webhook_url}")
    else:
        # Polling mode (local dev)
        logger.info("[telegram] Starting in polling mode")
        await _app.initialize()
        await _app.start()
        await _app.updater.start_polling(drop_pending_updates=True)

    _started = True
    logger.info("[telegram] Bot started")


async def stop_bot_service():
    global _started
    if _app and _started:
        try:
            await _app.updater.stop()
            await _app.stop()
            await _app.shutdown()
        except Exception:
            pass
        _started = False


async def process_update(update_data: dict):
    """Process a webhook update payload."""
    if _app is None:
        return
    try:
        from telegram import Update
        update = Update.de_json(update_data, _app.bot)
        await _app.process_update(update)
    except Exception as e:
        logger.error(f"[telegram] process_update error: {e}")
