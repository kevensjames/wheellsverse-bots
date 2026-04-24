import asyncio
import pytest
from narai.voice.session import VoiceSession


@pytest.mark.asyncio
async def test_session_basic_flow():
    async def fake_stt(audio): return "hello narai"
    async def fake_tts(text): return b"FAKE_AUDIO"
    async def fake_handle(uid, msg): return ("Hi back.", "operator")

    session = VoiceSession("jhon", fake_stt, fake_tts, fake_handle)
    result = await session.handle_audio_input(b"dummy")
    assert result.user_text == "hello narai"
    assert result.reply_text == "Hi back."
    assert result.mode == "operator"

    audio = await session.get_audio_output()
    assert audio == b"FAKE_AUDIO"


@pytest.mark.asyncio
async def test_session_interrupt_cancels_tts():
    async def fake_stt(audio): return "first" if audio == b"a" else "second"
    async def slow_tts(text):
        await asyncio.sleep(2.0)
        return b"LONG_AUDIO"
    async def fake_handle(uid, msg): return (f"reply to {msg}", "operator")

    session = VoiceSession("jhon", fake_stt, slow_tts, fake_handle)
    await session.handle_audio_input(b"a")
    # immediately interrupt
    result2 = await session.handle_audio_input(b"b")
    assert result2.user_text == "second"


@pytest.mark.asyncio
async def test_empty_transcript_returns_empty():
    async def fake_stt(audio): return "   "
    async def fake_tts(text): return b""
    async def fake_handle(uid, msg): return ("", "operator")

    session = VoiceSession("jhon", fake_stt, fake_tts, fake_handle)
    result = await session.handle_audio_input(b"silence")
    assert result.user_text == ""
    assert result.reply_text == ""
