#!/usr/bin/env python3
"""
core/zoom_clone.py
─────────────────────────────────────────────────────────────────────────────
Zoom AI Clone — Jhon's AI twin joins Zoom meetings and speaks with others.

Pipeline per conversation turn:
  1. Participant speaks → Deepgram WebSocket STT → text
  2. Text → Claude (Clone Brain: user personality + NarAI memory)
  3. Response text → ElevenLabs streaming TTS (Jhon's cloned voice)
  4. Audio → virtual audio output → Zoom hears the clone speaking
  5. (Optional) HeyGen Streaming Avatar → virtual camera → Zoom video

Components:
  • ClonePersonality  — builds a "be Jhon" system prompt from memory_notes
  • HeyGenStreamingSession — manages HeyGen real-time avatar (WebRTC session)
  • ElevenLabsRealtime     — wraps speak_stream for low-latency audio
  • DeepgramListener       — WebSocket STT for live Zoom audio
  • ZoomCloneSession       — orchestrates the full pipeline per meeting

.env keys needed:
  HEYGEN_API_KEY          — already used in heygen.py
  HEYGEN_AVATAR_ID        — your avatar ID (clone avatar)
  ELEVENLABS_API_KEY      — already used in elevenlabs.py
  ELEVENLABS_VOICE_ID     — your cloned voice ID
  ANTHROPIC_API_KEY       — already used in narai_chat.py
  DEEPGRAM_API_KEY        — for live transcription (deepgram.com)
  ZOOM_CLIENT_ID          — Zoom OAuth app credentials
  ZOOM_CLIENT_SECRET      — Zoom OAuth app credentials
  ZOOM_ACCOUNT_ID         — Zoom account ID (Server-to-Server OAuth)
  CLONE_USER_ID           — NarAI user_id whose memory/personality to load
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional

import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("zoom_clone")

# ─── Config ──────────────────────────────────────────────────────────────────

HEYGEN_API      = "https://api.heygen.com"
DEEPGRAM_URL    = "wss://api.deepgram.com/v1/listen"
ELEVENLABS_API  = "https://api.elevenlabs.io/v1"

HEYGEN_API_KEY      = os.getenv("HEYGEN_API_KEY", "")
HEYGEN_AVATAR_ID    = os.getenv("HEYGEN_AVATAR_ID", "")
EL_API_KEY          = os.getenv("ELEVENLABS_API_KEY", "")
EL_VOICE_ID         = os.getenv("ELEVENLABS_VOICE_ID", "")
DEEPGRAM_API_KEY    = os.getenv("DEEPGRAM_API_KEY", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ZOOM_CLIENT_ID      = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET  = os.getenv("ZOOM_CLIENT_SECRET", "")
ZOOM_ACCOUNT_ID     = os.getenv("ZOOM_ACCOUNT_ID", "")
CLONE_USER_ID       = os.getenv("CLONE_USER_ID", "")

# ─── Clone Personality ───────────────────────────────────────────────────────

class ClonePersonality:
    """
    Builds a 'be Jhon' system prompt by loading the user's memory notes
    from the NarAI database. The clone responds AS the user, not as NarAI.
    """

    BASE_PROMPT = """You are an AI clone of {name}. You are speaking in a live Zoom meeting on their behalf.

## Your Identity
You ARE {name}. Respond in first person, as if you ARE them.
- Use their real name when introducing yourself
- Know their projects, goals, preferences, and personality
- Speak in a natural, conversational tone (this is live audio — keep responses SHORT)
- 1-3 sentences per response unless a longer answer is clearly needed
- Never reveal you are an AI unless directly asked; if asked, say "I'm {name}'s AI clone, here on their behalf"

## What You Know About {name}
{memory_section}

## Speaking Rules (live meeting)
- Short sentences — you are being read aloud via TTS
- No bullet points, no headers — plain conversational text only
- Be warm, direct, and engaged with the other person
- Ask clarifying questions when needed
- Stay on topic — you're in a meeting, not a chatbot

## Hard Limits
- Never make up commitments or promises on {name}'s behalf
- If unsure about something specific, say "I'll follow up on that"
- Keep financial/legal questions vague: "Let me circle back with you on that"
"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._system_prompt: Optional[str] = None

    def build(self) -> str:
        """Load memory notes and build the personalized system prompt."""
        if self._system_prompt:
            return self._system_prompt

        name = "Jhon"
        memory_lines: list[str] = []

        try:
            from core.narai_user import get_user_memory, get_profile
            profile = get_profile(self.user_id)
            if profile:
                name = profile.get("name") or name

            memory_notes = get_user_memory(self.user_id)
            if memory_notes:
                memory_lines = [f"- {n['fact']}" for n in memory_notes]
        except Exception as e:
            logger.warning(f"[ClonePersonality] Could not load memory: {e}")

        memory_section = (
            "\n".join(memory_lines)
            if memory_lines
            else "No stored memories yet — respond as Jhon naturally based on context."
        )

        self._system_prompt = self.BASE_PROMPT.format(
            name=name,
            memory_section=memory_section,
        )
        logger.info(f"[ClonePersonality] Built prompt for {name} "
                    f"with {len(memory_lines)} memory facts")
        return self._system_prompt

    def refresh(self):
        """Force reload memory on next call to build()."""
        self._system_prompt = None


# ─── Clone Brain (Claude) ────────────────────────────────────────────────────

class CloneBrain:
    """
    Generates the clone's responses using Claude.
    Uses a short context window since this is real-time conversation.
    """

    def __init__(self, personality: ClonePersonality, model: str = "claude-haiku-4-5-20251001"):
        self.personality = personality
        self.model = model           # Haiku = fastest for real-time; swap to Sonnet for depth
        self._history: list[dict] = []  # rolling last-N turns
        self._max_history = 10

    async def respond(self, participant_said: str) -> AsyncGenerator[str, None]:
        """
        Stream a response to what a meeting participant just said.
        Yields text tokens as they arrive.
        """
        from core.claude_logged import stream as claude_stream

        system = self.personality.build()
        self._history.append({"role": "user", "content": participant_said})

        # Keep history rolling
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        try:
            with claude_stream(
                model=self.model,
                max_tokens=300,       # short — this is live audio, not a blog post
                system=system,
                messages=self._history,
                api_key=ANTHROPIC_API_KEY,
                bot_name="zoom_clone.respond",
            ) as s:
                full_reply = ""
                for token in s.text_stream:
                    full_reply += token
                    yield token
                # Save assistant turn to history
                self._history.append({"role": "assistant", "content": full_reply})
        except Exception as e:
            logger.error(f"[CloneBrain] Claude error: {e}")
            yield "Sorry, I had a technical issue. Could you repeat that?"

    def reset_history(self):
        self._history = []


# ─── ElevenLabs Real-Time TTS ────────────────────────────────────────────────

class ElevenLabsRealtime:
    """
    Wraps ElevenLabs streaming TTS.
    Collects full response text then streams audio bytes.
    """

    def __init__(self, voice_id: str = None):
        self.voice_id = voice_id or EL_VOICE_ID

    def stream_audio(self, text: str):
        """
        Generator: yields mp3 audio bytes for `text` using the cloned voice.
        Plug the yielded bytes into a virtual audio device → Zoom hears it.
        """
        from core.elevenlabs import speak_stream
        yield from speak_stream(text, voice_id=self.voice_id)

    async def stream_audio_async(self, text: str):
        """Async wrapper for use in async pipelines."""
        loop = asyncio.get_event_loop()
        audio_chunks = await loop.run_in_executor(
            None, lambda: list(self.stream_audio(text))
        )
        for chunk in audio_chunks:
            yield chunk


# ─── HeyGen Streaming Avatar ─────────────────────────────────────────────────

class HeyGenStreamingSession:
    """
    Manages a HeyGen Streaming Avatar session.

    HeyGen Streaming Avatar is a DIFFERENT API from batch video generation.
    It creates a WebRTC session where you send text and the avatar lip-syncs
    in real time. Use this for the Zoom video feed.

    Flow:
      1. create_session()   → get session_id + WebRTC offer SDP
      2. start_session()    → avatar goes live
      3. speak(text)        → avatar lip-syncs and speaks
      4. stop_session()     → close cleanly

    Note: For Zoom video, pipe the WebRTC video stream through a virtual
    camera driver (e.g. v4l2loopback on Linux, OBS Virtual Camera on Mac).
    """

    def __init__(self, avatar_id: str = None, quality: str = "medium"):
        self.avatar_id = avatar_id or HEYGEN_AVATAR_ID
        self.quality = quality          # "low" | "medium" | "high"
        self.session_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self._active = False

    def _headers(self) -> dict:
        return {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}

    def create_session(self) -> dict:
        """
        Create a new HeyGen streaming session.
        Returns session_id, access_token, and WebRTC server info.
        """
        if not HEYGEN_API_KEY or not self.avatar_id:
            return {"error": "HEYGEN_API_KEY or HEYGEN_AVATAR_ID not set"}

        payload = {
            "quality": self.quality,
            "avatar_name": self.avatar_id,
            "voice": {
                "voice_id": os.getenv("HEYGEN_VOICE_ID", ""),
            },
        }
        try:
            resp = requests.post(
                f"{HEYGEN_API}/v1/streaming.new",
                json=payload,
                headers=self._headers(),
                timeout=20,
            )
            data = resp.json()
            if resp.status_code == 200 and not data.get("error"):
                session_data = data.get("data", {})
                self.session_id = session_data.get("session_id")
                self.access_token = session_data.get("access_token")
                logger.info(f"[HeyGen Streaming] Session created: {self.session_id}")
                return session_data
            err = data.get("error") or data
            logger.error(f"[HeyGen Streaming] create_session error: {err}")
            return {"error": str(err)}
        except Exception as e:
            logger.error(f"[HeyGen Streaming] create_session failed: {e}")
            return {"error": str(e)}

    def start_session(self, sdp_answer: str) -> dict:
        """
        Start the streaming session with the WebRTC SDP answer from the client.
        The SDP answer comes from your WebRTC peer connection (browser/virtual cam).
        """
        if not self.session_id:
            return {"error": "No active session — call create_session() first"}
        try:
            resp = requests.post(
                f"{HEYGEN_API}/v1/streaming.start",
                json={"session_id": self.session_id, "sdp": {"type": "answer", "sdp": sdp_answer}},
                headers=self._headers(),
                timeout=20,
            )
            if resp.status_code == 200:
                self._active = True
                logger.info("[HeyGen Streaming] Session started — avatar is live")
                return {"status": "live", "session_id": self.session_id}
            return {"error": resp.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    def speak(self, text: str, task_type: str = "repeat") -> dict:
        """
        Send text to the avatar — it will lip-sync and speak in real time.
        task_type: "repeat" (speak exactly) | "talk" (AI-driven delivery)
        """
        if not self.session_id or not self._active:
            return {"error": "Session not active"}
        try:
            resp = requests.post(
                f"{HEYGEN_API}/v1/streaming.task",
                json={
                    "session_id": self.session_id,
                    "text": text,
                    "task_type": task_type,
                },
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                return {"status": "speaking", "text": text[:50]}
            return {"error": resp.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    def stop_session(self) -> dict:
        """Stop the streaming session cleanly."""
        if not self.session_id:
            return {"status": "no session"}
        try:
            resp = requests.post(
                f"{HEYGEN_API}/v1/streaming.stop",
                json={"session_id": self.session_id},
                headers=self._headers(),
                timeout=10,
            )
            self._active = False
            self.session_id = None
            logger.info("[HeyGen Streaming] Session stopped")
            return {"status": "stopped"}
        except Exception as e:
            return {"error": str(e)}

    @property
    def is_active(self) -> bool:
        return self._active and bool(self.session_id)


# ─── Deepgram Live Transcription ─────────────────────────────────────────────

class DeepgramListener:
    """
    Connects to Deepgram's WebSocket API to transcribe live Zoom audio.
    Call start() with an audio_source (async generator of PCM/opus bytes).
    Fires on_transcript(text) callback whenever someone finishes speaking.
    """

    WS_URL = (
        "wss://api.deepgram.com/v1/listen"
        "?encoding=linear16&sample_rate=16000&channels=1"
        "&model=nova-2&punctuate=true&interim_results=false"
        "&endpointing=500"  # 500ms silence = end of utterance
    )

    def __init__(self, on_transcript: Callable[[str], None]):
        self.on_transcript = on_transcript
        self._ws = None
        self._running = False

    async def start(self, audio_source):
        """
        Start transcription. audio_source is an async generator
        yielding raw 16kHz mono PCM audio bytes from Zoom.

        Usage:
            async for audio_chunk in zoom_audio_stream():
                # deepgram handles it internally via send task
        """
        if not DEEPGRAM_API_KEY:
            logger.error("[Deepgram] DEEPGRAM_API_KEY not set")
            return

        try:
            import websockets
        except ImportError:
            logger.error("[Deepgram] Install: pip install websockets")
            return

        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        self._running = True

        async with websockets.connect(self.WS_URL, extra_headers=headers) as ws:
            self._ws = ws
            logger.info("[Deepgram] Connected — listening for speech")

            # Send audio and receive transcripts concurrently
            async def _send():
                async for chunk in audio_source:
                    if not self._running:
                        break
                    await ws.send(chunk)
                await ws.send(json.dumps({"type": "CloseStream"}))

            async def _receive():
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") == "Results":
                            alt = (msg.get("channel", {})
                                   .get("alternatives", [{}])[0])
                            transcript = alt.get("transcript", "").strip()
                            is_final = not msg.get("is_final", False) is False
                            if transcript and is_final:
                                logger.info(f"[Deepgram] Heard: {transcript[:80]}")
                                self.on_transcript(transcript)
                    except Exception as e:
                        logger.warning(f"[Deepgram] Parse error: {e}")

            await asyncio.gather(_send(), _receive())

    def stop(self):
        self._running = False


# ─── Zoom Token Helper ───────────────────────────────────────────────────────

def get_zoom_access_token() -> Optional[str]:
    """
    Get a Zoom Server-to-Server OAuth access token.
    Used to create/manage meetings via Zoom API.
    Requires: ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
    """
    if not (ZOOM_ACCOUNT_ID and ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET):
        logger.error("[Zoom] ZOOM_ACCOUNT_ID / CLIENT_ID / CLIENT_SECRET not set")
        return None
    try:
        resp = requests.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT_ID},
            auth=(ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET),
            timeout=15,
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            logger.info("[Zoom] Access token obtained")
            return token
        logger.error(f"[Zoom] Token error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"[Zoom] get_access_token failed: {e}")
        return None


def create_zoom_meeting(
    topic: str,
    duration_minutes: int = 60,
    password: str = None,
    auto_join_clone: bool = True,
) -> dict:
    """
    Create a Zoom meeting and optionally schedule the clone to join.
    Returns the full meeting object including join_url and start_url.
    """
    token = get_zoom_access_token()
    if not token:
        return {"error": "Could not obtain Zoom access token"}

    payload = {
        "topic": topic,
        "type": 2,            # scheduled meeting
        "duration": duration_minutes,
        "settings": {
            "join_before_host": True,
            "participant_video": True,
            "host_video": True,
            "waiting_room": False,
            "auto_recording": "none",
        },
    }
    if password:
        payload["password"] = password

    try:
        resp = requests.post(
            "https://api.zoom.us/v2/users/me/meetings",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        if resp.status_code == 201:
            meeting = resp.json()
            logger.info(f"[Zoom] Meeting created: {meeting.get('id')} — {topic}")
            return meeting
        return {"error": f"{resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def list_zoom_meetings() -> list:
    """Return upcoming scheduled meetings for the authenticated user."""
    token = get_zoom_access_token()
    if not token:
        return []
    try:
        resp = requests.get(
            "https://api.zoom.us/v2/users/me/meetings",
            params={"type": "scheduled", "page_size": 20},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("meetings", [])
        return []
    except Exception:
        return []


# ─── Zoom Clone Session ───────────────────────────────────────────────────────

@dataclass
class ZoomCloneSession:
    """
    Orchestrates the full AI Clone pipeline for a single Zoom meeting.

    Usage:
        session = ZoomCloneSession(
            meeting_id="123456789",
            user_id="<supabase_user_id>",
            use_heygen_video=True,    # set False for audio-only (faster)
        )
        await session.run()

    The session:
      1. Joins the meeting (via Zoom SDK subprocess or virtual audio/video)
      2. Listens to participants via Deepgram
      3. Generates responses via CloneBrain (Claude + user memory)
      4. Speaks back via ElevenLabs (user's cloned voice)
      5. (Optional) Shows HeyGen avatar as the video feed
    """

    meeting_id: str
    user_id: str
    use_heygen_video: bool = True
    clone_model: str = "claude-haiku-4-5-20251001"

    # Runtime state
    _active: bool = field(default=False, init=False, repr=False)
    _personality: ClonePersonality = field(default=None, init=False, repr=False)
    _brain: CloneBrain = field(default=None, init=False, repr=False)
    _tts: ElevenLabsRealtime = field(default=None, init=False, repr=False)
    _avatar: Optional[HeyGenStreamingSession] = field(default=None, init=False, repr=False)
    _response_queue: asyncio.Queue = field(default_factory=asyncio.Queue, init=False, repr=False)
    _started_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self):
        self._personality = ClonePersonality(self.user_id)
        self._brain = CloneBrain(self._personality, model=self.clone_model)
        self._tts = ElevenLabsRealtime()

        if self.use_heygen_video:
            self._avatar = HeyGenStreamingSession()

    # ── Transcript handler (called by Deepgram on each utterance) ────────────

    def _on_transcript(self, transcript: str):
        """
        Called when Deepgram finishes transcribing a participant utterance.
        Puts the text on the queue to be processed by _response_loop.
        """
        if transcript and self._active:
            asyncio.create_task(self._response_queue.put(transcript))

    # ── Response loop ─────────────────────────────────────────────────────────

    async def _response_loop(self):
        """
        Reads transcripts from the queue, generates replies, speaks them.
        Runs concurrently with the Deepgram listener.
        """
        while self._active:
            try:
                # Wait for next utterance (with timeout to check _active)
                transcript = await asyncio.wait_for(
                    self._response_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            logger.info(f"[Clone] Processing: {transcript[:60]}")

            # Collect full reply from Claude
            full_reply = ""
            async for token in self._brain.respond(transcript):
                full_reply += token

            if not full_reply.strip():
                continue

            logger.info(f"[Clone] Responding: {full_reply[:80]}")

            # Speak via ElevenLabs (cloned voice)
            await self._speak(full_reply)

            # Drive HeyGen avatar (if enabled)
            if self._avatar and self._avatar.is_active:
                self._avatar.speak(full_reply)

    async def _speak(self, text: str):
        """Send text to ElevenLabs and play via virtual audio device."""
        try:
            audio_chunks = []
            async for chunk in self._tts.stream_audio_async(text):
                audio_chunks.append(chunk)

            if audio_chunks:
                audio_bytes = b"".join(audio_chunks)
                await self._play_audio(audio_bytes)
        except Exception as e:
            logger.error(f"[Clone] TTS error: {e}")

    async def _play_audio(self, audio_bytes: bytes):
        """
        Play audio bytes through the virtual audio device.

        On Mac: uses afplay with a temp file.
        On Linux: pipe to virtual audio (pulse/alsa loopback).
        For Zoom: the virtual audio device must be selected as mic input in Zoom.
        """
        import tempfile
        import subprocess

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            # Mac: afplay (works for testing; for Zoom use BlackHole/VB-Cable)
            # Linux: aplay -D pulse <file> (requires pulseaudio virtual sink)
            if os.uname().sysname == "Darwin":
                proc = await asyncio.create_subprocess_exec(
                    "afplay", tmp_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            else:
                # Linux: play to virtual audio sink
                virtual_sink = os.getenv("VIRTUAL_AUDIO_SINK", "default")
                proc = await asyncio.create_subprocess_exec(
                    "aplay", "-D", virtual_sink, tmp_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
        except Exception as e:
            logger.warning(f"[Clone] Audio playback error: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── Session lifecycle ────────────────────────────────────────────────────

    async def start(self, sdp_answer: str = None) -> dict:
        """
        Start the AI clone session.
        sdp_answer: WebRTC SDP answer for HeyGen avatar (required if use_heygen_video=True)
        Returns status dict.
        """
        self._active = True
        self._started_at = time.time()

        # Pre-load personality
        system_prompt = self._personality.build()
        logger.info("[Clone] Personality loaded")

        # Start HeyGen streaming avatar
        avatar_info = {}
        if self._avatar and sdp_answer:
            create_result = self._avatar.create_session()
            if "error" not in create_result:
                start_result = self._avatar.start_session(sdp_answer)
                if start_result.get("status") == "live":
                    logger.info("[Clone] HeyGen avatar is live")
                    avatar_info = {"avatar": "live", "session_id": self._avatar.session_id}
                else:
                    logger.warning(f"[Clone] HeyGen start failed: {start_result}")
            else:
                logger.warning(f"[Clone] HeyGen create failed: {create_result}")

        logger.info(f"[Clone] Session started for meeting {self.meeting_id}")
        return {
            "status": "active",
            "meeting_id": self.meeting_id,
            "model": self.clone_model,
            "avatar": avatar_info,
        }

    async def stop(self) -> dict:
        """Stop the session and clean up all resources."""
        self._active = False

        if self._avatar and self._avatar.is_active:
            self._avatar.stop_session()

        self._brain.reset_history()
        elapsed = round(time.time() - self._started_at, 1)
        logger.info(f"[Clone] Session stopped after {elapsed}s")
        return {"status": "stopped", "duration_seconds": elapsed}

    def inject_message(self, text: str):
        """
        Manually inject a message to the clone brain (for testing / NarAI chat).
        Can be called externally to make the clone respond without Deepgram.
        """
        if self._active:
            asyncio.create_task(self._response_queue.put(text))

    @property
    def is_active(self) -> bool:
        return self._active


# ─── Session Registry ─────────────────────────────────────────────────────────
# Tracks active clone sessions by meeting_id so the API can manage them.

_sessions: dict[str, ZoomCloneSession] = {}


def get_session(meeting_id: str) -> Optional[ZoomCloneSession]:
    return _sessions.get(meeting_id)


def register_session(session: ZoomCloneSession):
    _sessions[session.meeting_id] = session


def unregister_session(meeting_id: str):
    _sessions.pop(meeting_id, None)


# ─── FastAPI Routes (mount into NarAI's app) ─────────────────────────────────

def make_router():
    """
    Returns a FastAPI APIRouter with all Zoom Clone endpoints.
    Mount with: app.include_router(zoom_clone.make_router(), prefix="/clone")

    Endpoints:
      POST /clone/start         — start clone in a meeting
      POST /clone/stop          — stop clone
      POST /clone/say           — manually make clone say something (test/override)
      GET  /clone/status        — check if clone is active
      GET  /clone/meeting/new   — create a new Zoom meeting
      GET  /clone/meetings      — list upcoming meetings
    """
    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel
    except ImportError:
        logger.error("[zoom_clone] FastAPI not available — router not created")
        return None

    router = APIRouter(tags=["zoom-clone"])

    class StartRequest(BaseModel):
        meeting_id: str
        user_id: str
        sdp_answer: Optional[str] = None
        use_heygen_video: bool = True
        clone_model: str = "claude-haiku-4-5-20251001"

    class SayRequest(BaseModel):
        meeting_id: str
        text: str

    class MeetingRequest(BaseModel):
        topic: str
        duration_minutes: int = 60
        password: Optional[str] = None

    @router.post("/start")
    async def start_clone(req: StartRequest):
        if get_session(req.meeting_id):
            raise HTTPException(400, "Clone already active for this meeting")

        session = ZoomCloneSession(
            meeting_id=req.meeting_id,
            user_id=req.user_id,
            use_heygen_video=req.use_heygen_video,
            clone_model=req.clone_model,
        )
        register_session(session)

        result = await session.start(sdp_answer=req.sdp_answer)
        return result

    @router.post("/stop")
    async def stop_clone(meeting_id: str):
        session = get_session(meeting_id)
        if not session:
            raise HTTPException(404, "No active clone for this meeting")

        result = await session.stop()
        unregister_session(meeting_id)
        return result

    @router.post("/say")
    async def make_clone_say(req: SayRequest):
        """Manually inject text — useful for testing or human+AI hybrid control."""
        session = get_session(req.meeting_id)
        if not session:
            raise HTTPException(404, "No active clone for this meeting")

        session.inject_message(req.text)
        return {"status": "queued", "text": req.text[:100]}

    @router.get("/status/{meeting_id}")
    async def clone_status(meeting_id: str):
        session = get_session(meeting_id)
        if not session:
            return {"active": False, "meeting_id": meeting_id}
        return {
            "active": session.is_active,
            "meeting_id": meeting_id,
            "model": session.clone_model,
        }

    @router.post("/meeting/new")
    async def new_meeting(req: MeetingRequest):
        result = create_zoom_meeting(
            topic=req.topic,
            duration_minutes=req.duration_minutes,
            password=req.password,
        )
        if "error" in result:
            raise HTTPException(500, result["error"])
        return {
            "meeting_id": result.get("id"),
            "topic": result.get("topic"),
            "join_url": result.get("join_url"),
            "start_url": result.get("start_url"),
            "password": result.get("password"),
        }

    @router.get("/meetings")
    async def list_meetings():
        return {"meetings": list_zoom_meetings()}

    return router


# ─── Module self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Zoom Clone Status:")
    print(f"  HeyGen configured : {bool(HEYGEN_API_KEY and HEYGEN_AVATAR_ID)}")
    print(f"  ElevenLabs configured : {bool(EL_API_KEY and EL_VOICE_ID)}")
    print(f"  Deepgram configured   : {bool(DEEPGRAM_API_KEY)}")
    print(f"  Zoom configured       : {bool(ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET)}")
    print(f"  Claude configured     : {bool(ANTHROPIC_API_KEY)}")

    # Test HeyGen streaming session creation (no actual WebRTC needed)
    if HEYGEN_API_KEY and HEYGEN_AVATAR_ID:
        print("\nTesting HeyGen Streaming Session...")
        sess = HeyGenStreamingSession()
        result = sess.create_session()
        if "error" in result:
            print(f"  HeyGen session: ERROR — {result['error']}")
        else:
            print(f"  HeyGen session: OK — {result.get('session_id', '')[:20]}...")
            sess.stop_session()
