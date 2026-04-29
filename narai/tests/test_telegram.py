"""Tests for Telegram integration — no live Telegram or pipeline calls."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from narai.integrations.telegram import _format_reply, handle_update


def test_format_reply_plain():
    assert _format_reply("hello world") == "hello world"


def test_format_reply_bold():
    assert _format_reply("**done**") == "<b>done</b>"


def test_format_reply_code():
    assert _format_reply("`git status`") == "<code>git status</code>"


_DUMMY_TOKEN = "123456789:AABBCCDDEEFFaabbccddeeff1234567890AB"


async def test_handle_update_drops_non_owner(monkeypatch):
    monkeypatch.setattr("narai.integrations.telegram.OWNER_CHAT_ID", 999)
    monkeypatch.setattr("narai.integrations.telegram.TOKEN", _DUMMY_TOKEN)
    mock_pipeline = AsyncMock()
    fake_chat = MagicMock()
    fake_chat.run_pipeline_async = mock_pipeline
    monkeypatch.setitem(sys.modules, "narai.api.routes.chat", fake_chat)

    update_data = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 12345, "type": "private"},
            "date": 0,
            "text": "hello",
            "from": {"id": 12345, "is_bot": False, "first_name": "X"},
        },
    }
    await handle_update(update_data)
    mock_pipeline.assert_not_called()


async def test_handle_update_owner_calls_pipeline(monkeypatch):
    monkeypatch.setattr("narai.integrations.telegram.OWNER_CHAT_ID", 12345)
    monkeypatch.setattr("narai.integrations.telegram.TOKEN", _DUMMY_TOKEN)
    fake_result = {
        "reply": "Ship it.",
        "mode": "operator",
        "overwhelm": "none",
        "tier": "fast",
        "tokens": 50,
        "model": "claude-haiku-4-5",
        "skill": None,
    }
    mock_pipeline = AsyncMock(return_value=fake_result)
    fake_chat = MagicMock()
    fake_chat.run_pipeline_async = mock_pipeline
    monkeypatch.setitem(sys.modules, "narai.api.routes.chat", fake_chat)

    update_data = {
        "update_id": 2,
        "message": {
            "message_id": 2,
            "chat": {"id": 12345, "type": "private"},
            "date": 0,
            "text": "what's next?",
            "from": {"id": 12345, "is_bot": False, "first_name": "JK"},
        },
    }
    with patch("telegram.Bot.send_message", new_callable=AsyncMock):
        with patch("telegram.Bot.send_chat_action", new_callable=AsyncMock):
            await handle_update(update_data)
    mock_pipeline.assert_called_once_with(user_id="owner", user_message="what's next?")
