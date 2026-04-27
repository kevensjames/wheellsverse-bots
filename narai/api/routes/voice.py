"""
NarAI Voice WebSocket route.

Wires the Step 5 voice pipeline (STT → pipeline → TTS) into FastAPI so it
shares Railway's single port (8080) with the rest of the v2 API. The browser
speaks audio frames into a WebSocket and receives transcript JSON + synthesized
MP3 audio back.

Auth: JWT passed as a query parameter (browsers can't set custom headers on
WebSocket connections, so `?token=<jwt>` is the canonical pattern).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from narai.api.auth import require_auth  # noqa: F401 (re-used below)
from narai.voice.session import VoiceSession
from narai.voice.stt import get_stt
from narai.voice.tts import get_tts

rt = APIRouter(tags=["voice"])
logger = logging.getLogger("narai.voice")

_AVATAR_HTML_PATH = Path(__file__).parent.parent.parent / "voice" / "avatar.html"


# ── Avatar page ──────────────────────────────────────────────────────────────

@rt.get("/voice", response_class=HTMLResponse)
async def voice_ui() -> HTMLResponse:
    """Serve the lightweight 2D avatar page. JWT is passed to the WebSocket
    via query string, so the page is loaded unauthenticated but the WS will
    reject without a valid token."""
    try:
        html = _AVATAR_HTML_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"avatar.html missing: {e}")
        return HTMLResponse(
            "<h1>NarAI voice UI unavailable</h1>",
            status_code=500,
        )
    return HTMLResponse(html)


# ── WebSocket endpoint ───────────────────────────────────────────────────────

def _verify_token(token: str) -> str | None:
    """Validate a JWT and return the subject, or None if invalid."""
    try:
        import jwt  # PyJWT — pure Python, no compiled extensions
        secret = os.getenv("NARAI_JWT_SECRET", "change-me-in-production-narai-2026")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub")
    except Exception as e:
        logger.warning(f"WS JWT verify failed: {e}")
        return None


@rt.websocket("/voice/ws")
async def voice_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT from /auth/login"),
) -> None:
    # 1. Verify JWT before accepting (FastAPI requires accept() before close
    # can send a meaningful code, so we accept + close on failure).
    sub = _verify_token(token)
    if not sub:
        await websocket.close(code=1008, reason="Invalid or missing token")
        return

    await websocket.accept()
    logger.info(f"voice WS connected: sub={sub}")

    # 2. Pick providers. Edge TTS is the default (free, no key) — ElevenLabs
    # can be enabled by setting NARAI_TTS_PROVIDER=elevenlabs + the API key.
    stt = get_stt(os.getenv("NARAI_STT_PROVIDER", "openai"))
    tts_client = get_tts(os.getenv("NARAI_TTS_PROVIDER", "edge"))

    async def tts_fn(text: str) -> bytes:
        return await tts_client.synthesize(text)

    # 3. Wrap the shared chat pipeline so VoiceSession can call it.
    from narai.api.routes.chat import run_pipeline_async

    async def handle_turn_fn(user_id: str, message: str) -> tuple[str, str]:
        result = await run_pipeline_async(user_id=user_id, user_message=message)
        return result["reply"], result["mode"]

    session = VoiceSession(
        user_id=sub,
        stt_fn=stt.transcribe,
        tts_fn=tts_fn,
        handle_turn_fn=handle_turn_fn,
    )

    try:
        while True:
            message = await websocket.receive()
            # Binary audio frame
            if "bytes" in message and message["bytes"] is not None:
                audio = message["bytes"]
                # Log size + magic bytes so we know what the browser actually sent.
                head_hex = audio[:16].hex() if audio else ""
                logger.info(
                    f"voice audio in: sub={sub} bytes={len(audio)} head={head_hex}"
                )
                # Reject obviously-empty audio with a clear user-facing message.
                if len(audio) < 256:
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "user": "",
                        "reply": "Hold the mic for a full second and speak — I didn't catch anything.",
                        "mode": "operator",
                        "error": "audio_too_short",
                    }))
                    continue
                # Reject webm Cluster-only payloads — these arrive when the
                # browser releases the mic before MediaRecorder emitted the
                # EBML header chunk. Whisper rejects them as "Invalid file
                # format" with 0-second duration; we short-circuit with a
                # message the user can act on.
                if audio[:4] == b"\x1f\x43\xb6\x75":
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "user": "",
                        "reply": "Recording too short — hold the mic for a full second before releasing.",
                        "mode": "operator",
                        "error": "audio_no_header",
                    }))
                    continue
                try:
                    result = await session.handle_audio_input(audio)
                except Exception as exc:
                    logger.warning(f"voice pipeline failed: sub={sub} err={exc}")
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "user": "",
                        "reply": f"Voice pipeline error: {str(exc)[:200]}",
                        "mode": "operator",
                        "error": "pipeline_failed",
                    }))
                    continue

                # Emit transcript first so the UI can render instantly.
                await websocket.send_text(json.dumps({
                    "type": "transcript",
                    "user": result.user_text,
                    "reply": result.reply_text,
                    "mode": result.mode,
                }))

                # Then stream the synthesized audio.
                audio_out = await session.get_audio_output()
                if audio_out:
                    await websocket.send_bytes(audio_out)
                    await websocket.send_text(json.dumps({"type": "audio_end"}))
                else:
                    # No audio (TTS failed or empty reply) — still tell the browser
                    # the turn is over so the avatar UI flips back to listening.
                    await websocket.send_text(json.dumps({"type": "audio_end"}))
                continue

            # Text control frame
            if "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except Exception:
                    continue
                if data.get("type") == "interrupt":
                    if session._current_tts_task:
                        session._current_tts_task.cancel()
                        logger.info(f"voice WS interrupt: sub={sub}")

    except WebSocketDisconnect:
        logger.info(f"voice WS disconnected: sub={sub}")
    except Exception as e:
        logger.warning(f"voice WS error (sub={sub}): {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
