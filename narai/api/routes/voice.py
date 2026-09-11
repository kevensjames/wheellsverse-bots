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

from fastapi import HTTPException, Depends, APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from infra.brain.interface import BrainClient
from narai.api.auth import require_auth
from narai.voice.session import VoiceSession
from narai.voice.stt import get_stt
from narai.voice.tts import get_tts

rt = APIRouter(tags=["voice"])
from pydantic import BaseModel

from narai.api import ws_auth

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

# _verify_token was REMOVED with the ?token= parameter it served. It called
#     jwt.decode(token, os.getenv("NARAI_JWT_SECRET", "change-me-in-production-narai-2026"), ...)
# so an unset NARAI_JWT_SECRET made every token forgeable by anyone who read this file — and this
# repository is public. The variable IS set on production, so the fallback was latent rather than
# live, but a fail-open default is not something to leave behind once its only caller is gone.
# Bearer-JWT verification for HTTP routes remains in narai/api/auth.py::require_auth, which is now
# also the only path by which a WebSocket ticket can be obtained.


VOICE_WS_ROUTE = "/api/v2/narai/voice/ws"


class _TicketOut(BaseModel):
    ticket: str
    expires_in: int
    route: str


@rt.post("/voice/ws-ticket", response_model=_TicketOut)
async def mint_voice_ws_ticket(sub: str = Depends(require_auth)) -> _TicketOut:
    """Exchange a bearer JWT for a single-use WebSocket ticket, over HTTPS, in a POST body.

    This exists so the JWT never has to appear in a URL. The client authenticates normally here —
    Authorization header, same as every other v2 route — and receives an artifact that is bound to
    one principal, one route and one environment, expires in 30 seconds, and can be spent exactly
    once. Browsers should not need this at all: they present the session cookie on the handshake.
    """
    secret = os.getenv("NARAI_WS_TICKET_SECRET") or os.getenv("SESSION_SIGNING_SECRET") or ""
    if not secret:
        # No signing key means we cannot mint something we could later trust. Refusing to issue is
        # the only honest answer; issuing an unverifiable ticket would be worse than issuing none.
        raise HTTPException(status_code=503, detail=ws_auth.UNAVAILABLE)
    ticket = ws_auth.mint_ticket(
        subject=sub, role="operator", route=VOICE_WS_ROUTE,
        environment=os.getenv("APP_ENV", "production").strip().lower(), secret=secret,
    )
    return _TicketOut(ticket=ticket, expires_in=ws_auth.TICKET_TTL_SECONDS, route=VOICE_WS_ROUTE)


@rt.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket) -> None:
    # RESOLVED BEFORE accept(). The previous version accepted first and closed after, and its own
    # comment explained why — but a handshake completed with an unauthenticated peer is still a
    # handshake completed with them. `token: str = Query(...)` is gone entirely: the parameter is now
    # refused by the resolver rather than read, so a client still sending a standing JWT in a URL
    # fails loudly instead of silently working.
    trusted = frozenset(
        o.strip().rstrip("/").lower()
        for o in (os.getenv("CSRF_TRUSTED_ORIGINS", "") or "").split(",") if o.strip()
    )
    outcome, principal, reason = ws_auth.resolve_ws_principal(
        websocket, VOICE_WS_ROUTE,
        trusted_origins=trusted,
        session_secret=os.getenv("SESSION_SIGNING_SECRET") or "",
        ticket_secret=(os.getenv("NARAI_WS_TICKET_SECRET")
                       or os.getenv("SESSION_SIGNING_SECRET") or ""),
    )
    if outcome != ws_auth.OK or principal is None:
        # The outcome names the failure class; `reason` never echoes the credential. Closing without
        # accepting is what makes this a refusal rather than an accepted-then-dropped connection.
        logger.warning("voice WS refused: %s (%s)", outcome, reason)
        await websocket.close(code=1008, reason=outcome)
        return

    sub = principal.subject
    await websocket.accept()
    # role and source only — never the subject, the ticket, the cookie or the JWT.
    logger.info("voice WS connected: role=%s via=%s", principal.role, principal.source)

    # 2. Per-socket BrainClient. WebSocket connections are long-lived, so a
    # single instance per session gives implicit caching without touching
    # the chat-route TTLCache.
    brain = BrainClient(user_id=sub, mode="narai")

    # 3. Pick providers. Edge TTS is the default (free, no key) — ElevenLabs
    # can be enabled by setting NARAI_TTS_PROVIDER=elevenlabs + the API key.
    stt = get_stt(os.getenv("NARAI_STT_PROVIDER", "openai"))
    tts_client = get_tts(os.getenv("NARAI_TTS_PROVIDER", "edge"))

    async def tts_fn(text: str) -> bytes:
        return await tts_client.synthesize(text)

    # 4. Wrap the shared chat pipeline so VoiceSession can call it.
    from narai.api.routes.chat import run_pipeline_async

    async def handle_turn_fn(user_id: str, message: str) -> tuple[str, str]:
        result = await run_pipeline_async(
            brain=brain, user_id=user_id, user_message=message
        )
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
                # Size only. This used to log sub= plus the first 16 bytes as hex "so we know what
                # the browser actually sent" — that is the authenticated subject and a slice of the
                # audio stream, in a log. A byte count answers the same operational question ("did a
                # frame arrive, and was it plausible") without recording who spoke or what was sent.
                logger.info("voice audio in: bytes=%d", len(audio))
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
                    logger.warning("voice pipeline failed: err=%s", exc)   # no subject: identifying
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
                        logger.info("voice WS interrupt")                      # no subject: identifying

    except WebSocketDisconnect:
        logger.info("voice WS disconnected")
    except Exception as e:
        logger.warning("voice WS error: %s", e)
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
