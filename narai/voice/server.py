"""
WebSocket voice endpoint.
Client sends audio frames; server streams back audio + text.

`websockets` is a runtime-only dependency — imported lazily so
`from narai.voice import ...` doesn't require it at package-import time.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from narai.voice.session import VoiceSession
from narai.voice.stt import get_stt
from narai.voice.tts import get_tts


HandleTurnAsync = Callable[[str, str], Awaitable[tuple[str, str]]]


async def handle_client(websocket, handle_turn_async: HandleTurnAsync, user_id: str = "owner"):
    """Handle one connected WebSocket client. Expects:
      - binary frames = audio input (webm/opus recommended)
      - text frames = control messages (JSON), e.g. {"type": "interrupt"}

    Emits:
      - text frame {"type": "transcript", "user": ..., "reply": ..., "mode": ...}
      - binary audio frame (synthesized reply)
      - text frame {"type": "audio_end"}
    """
    stt = get_stt()  # Auto-resolves from env (NARAI_STT_PROVIDER, LLM_BACKEND)
    tts_client = get_tts("edge")

    async def tts_fn(text: str) -> bytes:
        return await tts_client.synthesize(text)

    session = VoiceSession(
        user_id=user_id,
        stt_fn=stt.transcribe,
        tts_fn=tts_fn,
        handle_turn_fn=handle_turn_async,
    )

    async for message in websocket:
        if isinstance(message, bytes):
            # Audio frame
            result = await session.handle_audio_input(message)

            # Send text immediately so UI updates fast
            await websocket.send(json.dumps({
                "type": "transcript",
                "user": result.user_text,
                "reply": result.reply_text,
                "mode": result.mode,
            }))

            # Then stream audio
            audio = await session.get_audio_output()
            if audio:
                await websocket.send(audio)
                await websocket.send(json.dumps({"type": "audio_end"}))
        elif isinstance(message, str):
            data = json.loads(message)
            if data.get("type") == "interrupt":
                if session._current_tts_task:
                    session._current_tts_task.cancel()


async def start_server(
    handle_turn_async: HandleTurnAsync,
    host: str = "0.0.0.0",
    port: int = 8765,
    user_id: str = "owner",
):
    import websockets  # lazy — only needed when actually running the server

    async def handler(ws):
        await handle_client(ws, handle_turn_async, user_id=user_id)

    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # run forever
