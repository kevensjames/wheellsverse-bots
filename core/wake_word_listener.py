#!/usr/bin/env python3
"""
core/wake_word_listener.py
─────────────────────────────────────────────────────────────────────────────
NarAI Always-On Wake Word Listener

Runs a background thread that continuously listens for the wake word "NarAI".
When detected, NarAI responds with a random casual greeting and activates
the full voice pipeline.

Requires:
  pip install SpeechRecognition pyaudio

Optional (offline fallback):
  pip install vosk
  Download model: https://alphacephei.com/vosk/models (vosk-model-small-en-us)

.env optional:
  NARAI_WAKE_WORD=narai          (default: narai)
  NARAI_VOSK_MODEL_PATH=...      (path to vosk model dir for offline mode)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("wake_word_listener")

ROOT = Path(__file__).resolve().parent.parent

WAKE_WORD = os.getenv("NARAI_WAKE_WORD", "narai").lower()
VOSK_MODEL_PATH = os.getenv("NARAI_VOSK_MODEL_PATH", str(ROOT / "models" / "vosk-small-en"))

# Google often mishears "NarAI" — accept all these as the wake word
WAKE_WORD_ALIASES = {
    "narai", "nara", "nari", "narrate", "narrow", "narray",
    "nerei", "nerai", "naray", "nare", "nare i", "na rai",
    "hey narai", "hey nara", "ok narai", "yo narai",
    # Common Google mishearings of "NarAI":
    "now i", "now", "nori", "nori", "nora", "norri",
    "no i", "nor i", "nah i", "nah", "nurai", "nuray",
    "new i", "na i", "nar", "narr",
}

# Casual greetings NarAI responds with when wake word is detected
WAKE_GREETINGS = [
    "Hey, what's up?",
    "I'm here.",
    "Finally you need me!",
    "Tell me.",
    "Yes?",
    "I got you — what's going on?",
    "Always here. What do you need?",
]


class WakeWordListener:
    """
    Background microphone listener. Runs in its own daemon thread.
    Calls on_wake_word(greeting_text) when "NarAI" is heard.
    Calls on_command(text) with the follow-up command after wake word.
    """

    def __init__(
        self,
        on_wake_word: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
    ):
        self.on_wake_word = on_wake_word or (lambda g: logger.info("Wake word! Greeting: %s", g))
        self.on_command = on_command or (lambda t: logger.info("Command: %s", t))
        self.on_transcript = on_transcript or (lambda t: None)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._active = False   # True = after wake word, listening for command
        self._active_timer: Optional[threading.Timer] = None
        self._method = "none"  # which backend is in use

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start background listening. Returns True if started successfully."""
        if self._running:
            return True

        # Detect which backend to use
        backend = self._select_backend()
        if not backend:
            logger.warning(
                "No audio backend available. Install SpeechRecognition + pyaudio, or vosk.\n"
                "  pip install SpeechRecognition pyaudio\n"
                "  or: pip install vosk"
            )
            return False

        self._running = True
        self._method = backend
        self._thread = threading.Thread(
            target=self._listen_loop,
            args=(backend,),
            daemon=True,
            name="NarAI-WakeWord",
        )
        self._thread.start()
        logger.info("Wake word listener started (backend=%s, wake_word='%s')", backend, WAKE_WORD)
        return True

    def stop(self):
        """Stop the background listener."""
        self._running = False
        if self._active_timer:
            self._active_timer.cancel()
        logger.info("Wake word listener stopped")

    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    def get_status(self) -> dict:
        return {
            "running": self.is_running(),
            "backend": self._method,
            "wake_word": WAKE_WORD,
            "active_listening": self._active,
        }

    # ── Backend selection ─────────────────────────────────────────────────────

    def _select_backend(self) -> Optional[str]:
        """Check which audio backends are available. Returns backend name."""
        # 1. Try SpeechRecognition (most reliable, online via Google)
        try:
            import speech_recognition as sr   # noqa
            import pyaudio                    # noqa
            return "speech_recognition"
        except ImportError:
            pass

        # 2. Try Vosk (fully offline)
        try:
            import vosk   # noqa
            if Path(VOSK_MODEL_PATH).exists():
                return "vosk"
            logger.warning("Vosk installed but model not found at: %s", VOSK_MODEL_PATH)
        except ImportError:
            pass

        return None

    # ── Listen loops ──────────────────────────────────────────────────────────

    def _listen_loop(self, backend: str):
        """Main background listen loop — runs forever until stop() is called."""
        if backend == "speech_recognition":
            self._sr_loop()
        elif backend == "vosk":
            self._vosk_loop()

    # ─── SpeechRecognition backend ────────────────────────────────────────────

    def _sr_loop(self):
        """Continuous listen loop using SpeechRecognition + Google (online)."""
        try:
            import speech_recognition as sr
        except ImportError:
            logger.error("SpeechRecognition not installed")
            return

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 200       # low threshold — catches normal speech
        recognizer.dynamic_energy_threshold = False  # don't auto-raise the threshold
        recognizer.pause_threshold = 0.6

        # Prefer MacBook Pro Microphone (index 1), fall back to default
        mic_index = None
        try:
            names = sr.Microphone.list_microphone_names()
            for i, name in enumerate(names):
                if "macbook" in name.lower() or "built-in" in name.lower():
                    mic_index = i
                    break
        except Exception:
            pass

        with sr.Microphone(device_index=mic_index) as mic:
            logger.info("Microphone ready (index=%s). Listening for '%s'...", mic_index, WAKE_WORD)

            while self._running:
                try:
                    # Listen for a short phrase (3s max in idle, 8s when active)
                    phrase_limit = 8.0 if self._active else 3.0
                    audio = recognizer.listen(mic, phrase_time_limit=phrase_limit, timeout=None)
                except Exception as e:
                    logger.debug("Listen error: %s", e)
                    time.sleep(0.1)
                    continue

                # Run recognition in a thread to avoid blocking
                threading.Thread(
                    target=self._sr_recognize,
                    args=(recognizer, audio),
                    daemon=True,
                ).start()

    def _sr_recognize(self, recognizer, audio):
        """Transcribe and process one audio chunk."""
        try:
            import speech_recognition as sr
        except ImportError:
            return
        try:
            text = recognizer.recognize_google(audio, language="en-US").lower().strip()
            logger.info("Heard: '%s'", text)
            self.on_transcript(text)
            self._process_transcript(text)
        except sr.UnknownValueError:
            pass   # silence / unrecognized — normal
        except sr.RequestError as e:
            logger.warning("Google Speech API error: %s", e)
        except Exception as e:
            logger.debug("SR error: %s", e)

    # ─── Vosk backend ─────────────────────────────────────────────────────────

    def _vosk_loop(self):
        """Continuous listen loop using Vosk (fully offline)."""
        try:
            import vosk
            import pyaudio
            import json as _json
        except ImportError:
            logger.error("Vosk or pyaudio not installed")
            return

        model = vosk.Model(VOSK_MODEL_PATH)
        rec = vosk.KaldiRecognizer(model, 16000)

        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=8192,
        )
        stream.start_stream()
        logger.info("Vosk microphone ready. Listening for '%s'...", WAKE_WORD)

        while self._running:
            try:
                data = stream.read(4096, exception_on_overflow=False)
                if rec.AcceptWaveform(data):
                    result = _json.loads(rec.Result())
                    text = result.get("text", "").strip().lower()
                    if text:
                        logger.debug("Vosk heard: %s", text)
                        self.on_transcript(text)
                        self._process_transcript(text)
                else:
                    # Partial result — check for wake word in partial
                    partial = _json.loads(rec.PartialResult()).get("partial", "").lower()
                    if WAKE_WORD in partial and not self._active:
                        self._handle_wake_word()
            except Exception as e:
                logger.debug("Vosk read error: %s", e)
                time.sleep(0.05)

        stream.stop_stream()
        stream.close()
        p.terminate()

    # ── Processing ────────────────────────────────────────────────────────────

    def _is_wake_word(self, text: str) -> bool:
        """Check if text contains the wake word or any known alias."""
        t = text.lower().strip()
        # Direct match
        if WAKE_WORD in t:
            return True
        # Alias match
        for alias in WAKE_WORD_ALIASES:
            if alias in t:
                return True
        # Whole-word fuzzy: text IS one of the aliases
        if t in WAKE_WORD_ALIASES:
            return True
        return False

    def _process_transcript(self, text: str):
        """Decide if this is a wake word hit or a command to act on."""
        if not text:
            return

        if self._is_wake_word(text):
            if not self._active:
                self._handle_wake_word()
            # If already active, the rest of the sentence after wake word is the command
            for alias in [WAKE_WORD] + sorted(WAKE_WORD_ALIASES, key=len, reverse=True):
                if alias in text.lower():
                    remainder = text.lower().split(alias, 1)[-1].strip()
                    if remainder and len(remainder) > 3:
                        self._handle_command(remainder)
                    break
        elif self._active:
            # In active mode — this is the user's command
            self._handle_command(text)

    def _handle_wake_word(self):
        """Triggered when wake word is detected."""
        greeting = random.choice(WAKE_GREETINGS)
        logger.info("Wake word detected! Greeting: %s", greeting)
        self._active = True

        # Cancel any existing active timer
        if self._active_timer:
            self._active_timer.cancel()

        # Auto-deactivate after 15 seconds of silence
        self._active_timer = threading.Timer(15.0, self._deactivate)
        self._active_timer.daemon = True
        self._active_timer.start()

        # Fire the callback
        try:
            self.on_wake_word(greeting)
        except Exception as e:
            logger.error("on_wake_word callback error: %s", e)

    def _handle_command(self, text: str):
        """Triggered with user command after wake word."""
        if not text.strip():
            return
        logger.info("Command received: %s", text)
        self._deactivate()
        try:
            self.on_command(text)
        except Exception as e:
            logger.error("on_command callback error: %s", e)

    def _deactivate(self):
        """Return to passive listening (waiting for wake word)."""
        self._active = False
        if self._active_timer:
            self._active_timer.cancel()
            self._active_timer = None
        logger.debug("Listener deactivated — waiting for wake word")


# ─── Singleton + integration helpers ─────────────────────────────────────────

_listener: Optional[WakeWordListener] = None
_listener_lock = threading.Lock()


def get_listener() -> WakeWordListener:
    global _listener
    with _listener_lock:
        if _listener is None:
            _listener = _build_default_listener()
    return _listener


def _build_default_listener() -> WakeWordListener:
    """Build the default listener wired to NarAI voice pipeline."""

    def _on_wake_word(greeting: str):
        """NarAI woke up — speak the greeting and optionally play via TTS."""
        logger.info("NarAI activated: %s", greeting)
        # Speak greeting with Ava Neural voice (mood-aware)
        try:
            from core.narai_tts import speak_with_mood
            speak_with_mood(greeting)
        except Exception as e:
            logger.debug("TTS error: %s", e)
        # Also notify the API's WebSocket clients if available
        try:
            from core import api as _api
            if hasattr(_api, "_broadcast_wake"):
                _api._broadcast_wake(greeting)
        except Exception:
            pass

    def _on_command(text: str):
        """User spoke a command — pass it to NarAI voice_chat."""
        logger.info("NarAI processing voice command: %s", text)
        try:
            # Detect mood from voice command text
            try:
                from core.emotion_engine import get_engine
                mood_result = get_engine().detect_and_store(text, source="voice")
                logger.info("Voice mood: %s", mood_result.get("mood", "neutral"))
            except Exception:
                pass

            # Pass to NarAI
            from bots.narai.bot import get_narai
            narai = get_narai()
            result = narai.voice_chat(text)
            response = result.get("response", "")
            if response:
                try:
                    from core.narai_tts import speak_with_mood
                    speak_with_mood(response)
                except Exception as e:
                    logger.debug("TTS response error: %s", e)
                # Also send response to WebSocket clients
                try:
                    from core import api as _api
                    if hasattr(_api, "_broadcast_response"):
                        _api._broadcast_response(response, result.get("mood", "neutral"))
                except Exception:
                    pass
        except Exception as e:
            logger.error("Voice command processing error: %s", e)

    return WakeWordListener(
        on_wake_word=_on_wake_word,
        on_command=_on_command,
    )


def start_listener() -> bool:
    """Start the always-on wake word listener. Call once at app startup."""
    return get_listener().start()


def stop_listener():
    """Stop the wake word listener."""
    if _listener:
        _listener.stop()


def get_listener_status() -> dict:
    """Get current listener status."""
    if _listener:
        return _listener.get_status()
    return {"running": False, "backend": "none", "wake_word": WAKE_WORD, "active_listening": False}
