"""
VoiceSession: manages one voice conversation turn with interrupt support.

Flow:
1. User streams audio → STT → text.
2. Text goes through existing handle_turn pipeline (identity + memory + overwhelm + mode).
3. Reply is formatted for voice and streamed to TTS.
4. If user speaks while TTS is playing, we cancel TTS and start a new turn.
5. Canceled reply is still logged as an episode so memory stays coherent.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from narai.voice.formatter import format_for_voice


@dataclass
class VoiceTurnResult:
    user_text: str
    reply_text: str
    spoken_text: str
    mode: str
    interrupted: bool = False
    partial_spoken: str = ""  # what NarAI actually said before interrupt


@dataclass
class VoiceSession:
    user_id: str
    stt_fn: Callable[[bytes], Awaitable[str]]
    tts_fn: Callable[[str], Awaitable[bytes]]
    handle_turn_fn: Callable[[str, str], Awaitable[tuple[str, str]]]
    # handle_turn_fn returns (reply_text, mode) — wrap your existing sync
    # handle_turn in an async adapter.
    _current_tts_task: Optional[asyncio.Task] = field(default=None, init=False)
    _interrupt_flag: bool = field(default=False, init=False)

    async def handle_audio_input(self, audio_bytes: bytes) -> VoiceTurnResult:
        # If NarAI is currently speaking, cancel it
        if self._current_tts_task and not self._current_tts_task.done():
            self._interrupt_flag = True
            self._current_tts_task.cancel()
            try:
                await self._current_tts_task
            except asyncio.CancelledError:
                pass

        # 1. STT
        user_text = await self.stt_fn(audio_bytes)
        if not user_text.strip():
            return VoiceTurnResult(
                user_text="", reply_text="", spoken_text="",
                mode="operator",
            )

        # 2. Run pipeline
        reply_text, mode = await self.handle_turn_fn(self.user_id, user_text)

        # 3. Format for voice
        spoken_ssml, _ = format_for_voice(reply_text, mode=mode, use_ssml=True)
        spoken_plain = spoken_ssml  # keep SSML for the TTS engine

        # 4. Kick off TTS as cancellable task (caller awaits self._current_tts_task
        #    to stream audio; cancel on next input).
        self._interrupt_flag = False
        self._current_tts_task = asyncio.create_task(self.tts_fn(spoken_plain))

        return VoiceTurnResult(
            user_text=user_text,
            reply_text=reply_text,
            spoken_text=spoken_plain,
            mode=mode,
            interrupted=False,
        )

    async def get_audio_output(self) -> bytes:
        """Await the current TTS task. Returns b'' if interrupted."""
        if not self._current_tts_task:
            return b""
        try:
            return await self._current_tts_task
        except asyncio.CancelledError:
            return b""
