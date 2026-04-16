#!/usr/bin/env python3
"""
core/whatsapp.py
─────────────────────────────────────────────────────────────────────────────
WhatsApp Business Cloud API handler + NarAI Mood Check-In Scheduler.

Features:
  • Parse incoming text messages and status updates
  • Send replies via WhatsApp Cloud API
  • Forward new message alerts to Telegram
  • Auto-reply with a default message when configured
  • Proactive mood check-in messages (morning, after silences, etc.)
  • Incoming messages analyzed by EmotionEngine → empathetic replies
  • Psychological profile tracking (private, stored locally)

Credentials needed in .env:
  WHATSAPP_ACCESS_TOKEN    — permanent token from Meta app dashboard
  WHATSAPP_PHONE_NUMBER_ID — phone number ID from Meta app dashboard
  WHATSAPP_AUTO_REPLY      — optional default reply text (leave empty to disable)
  WHATSAPP_OWNER_NUMBER    — owner's phone number for check-in messages (e.g. 14155552671)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("whatsapp")

GRAPH_API = "https://graph.facebook.com/v19.0"


class WhatsAppClient:

    def __init__(self):
        self.access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.auto_reply = os.getenv("WHATSAPP_AUTO_REPLY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    # ── Send ──────────────────────────────────────────────────────────────────

    def send_message(self, to: str, text: str) -> bool:
        """Send a text message to a WhatsApp number (e.g. '14155552671')."""
        if not self.is_configured():
            logger.warning("WhatsApp not configured — message not sent")
            return False

        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info("WhatsApp message sent to %s", to)
                return True
            logger.warning("WhatsApp send failed [%s]: %s", resp.status_code, resp.text[:300])
            return False
        except Exception as e:
            logger.error("WhatsApp send error: %s", e)
            return False

    def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        """Send an image message via URL (DALL-E, CDN, etc.)."""
        if not self.is_configured():
            return False
        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url, "caption": caption},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                logger.info("WhatsApp image sent to %s", to)
                return True
            logger.warning("WhatsApp image send failed [%s]: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("WhatsApp send_image error: %s", e)
            return False

    def send_audio(self, to: str, audio_url: str) -> bool:
        """Send an audio (voice note) message via URL."""
        if not self.is_configured():
            return False
        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                logger.info("WhatsApp audio sent to %s", to)
                return True
            logger.warning("WhatsApp audio send failed [%s]: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("WhatsApp send_audio error: %s", e)
            return False

    def send_video(self, to: str, video_url: str, caption: str = "") -> bool:
        """Send a video message via URL (HeyGen, CDN, etc.)."""
        if not self.is_configured():
            return False
        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "video",
            "video": {"link": video_url, "caption": caption},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                logger.info("WhatsApp video sent to %s", to)
                return True
            logger.warning("WhatsApp video send failed [%s]: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("WhatsApp send_video error: %s", e)
            return False

    def mark_read(self, message_id: str) -> None:
        """Mark a message as read (shows blue ticks)."""
        if not self.is_configured():
            return
        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        try:
            requests.post(url, json=payload, headers=headers, timeout=5)
        except Exception as e:
            logger.debug("mark_read error: %s", e)

    # ── Parse & Handle ────────────────────────────────────────────────────────

    def handle_payload(self, data: dict) -> None:
        """Entry point: parse a full Meta webhook payload."""
        if data.get("object") != "whatsapp_business_account":
            return

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                self._handle_messages(value)
                self._handle_statuses(value)

    def _handle_messages(self, value: dict) -> None:
        messages = value.get("messages", [])
        contacts = {c["wa_id"]: c["profile"]["name"] for c in value.get("contacts", [])}

        for msg in messages:
            sender = msg.get("from", "")
            msg_id = msg.get("id", "")
            msg_type = msg.get("type", "")
            name = contacts.get(sender, sender)

            if msg_type == "text":
                body = msg.get("text", {}).get("body", "")
                logger.info("WhatsApp message from %s (%s): %s", name, sender, body[:200])
                self._on_text_message(sender, name, msg_id, body)

            elif msg_type in ("image", "audio", "video", "document"):
                logger.info("WhatsApp %s from %s (%s)", msg_type, name, sender)
                self._on_media_message(sender, name, msg_id, msg_type)

            else:
                logger.info("WhatsApp unsupported type '%s' from %s", msg_type, sender)

    def _handle_statuses(self, value: dict) -> None:
        for status in value.get("statuses", []):
            recipient = status.get("recipient_id", "")
            state = status.get("status", "")        # sent | delivered | read | failed
            logger.info("WhatsApp status update: %s → %s", recipient, state)

    def _save_inbox_message(self, sender: str, name: str, body: str, msg_id: str):
        """Persist incoming WhatsApp message to inbox file."""
        import json as _json
        from pathlib import Path as _Path
        inbox_file = _Path(__file__).parent.parent / "data" / "wa_inbox.json"
        try:
            inbox = _json.loads(inbox_file.read_text()) if inbox_file.exists() else []
            inbox.append({
                "id": msg_id,
                "from": sender,
                "name": name,
                "body": body,
                "ts": __import__('datetime').datetime.now().isoformat(),
                "read": False,
                "replied": False,
                "reply": "",
            })
            # Keep last 500 messages
            inbox = inbox[-500:]
            inbox_file.write_text(_json.dumps(inbox, indent=2))
        except Exception as e:
            logger.warning("Inbox save failed: %s", e)

    def _mark_replied(self, msg_id: str, reply_text: str):
        import json as _json
        from pathlib import Path as _Path
        inbox_file = _Path(__file__).parent.parent / "data" / "wa_inbox.json"
        try:
            inbox = _json.loads(inbox_file.read_text()) if inbox_file.exists() else []
            for m in inbox:
                if m.get("id") == msg_id:
                    m["replied"] = True
                    m["reply"] = reply_text
                    m["read"] = True
                    break
            inbox_file.write_text(_json.dumps(inbox, indent=2))
        except Exception:
            pass

    def _on_text_message(self, sender: str, name: str, msg_id: str, body: str) -> None:
        # Save to inbox
        self._save_inbox_message(sender, name, body, msg_id)

        # Mark as read
        self.mark_read(msg_id)

        # ── Emotion analysis ──────────────────────────────────────────────────
        detected_mood = "neutral"
        try:
            from core.emotion_engine import get_engine
            emotion_result = get_engine().detect_and_store(body, source="whatsapp")
            detected_mood = emotion_result.get("mood", "neutral")
            logger.info("WhatsApp mood from %s: %s", name, detected_mood)
        except Exception:
            pass

        # Notify Telegram
        try:
            from core.telegram import notify
            mood_emoji = {"sad": "💙", "happy": "✨", "angry": "🔥", "anxious": "🌿"}.get(detected_mood, "💬")
            notify(
                f"📲 <b>WhatsApp message</b>\n"
                f"👤 {name} (+{sender})\n"
                f"{mood_emoji} Mood: {detected_mood}\n"
                f"💬 {body[:300]}"
            )
        except Exception:
            pass

        # ── NarAI empathetic reply ────────────────────────────────────────────
        # First try emotion-aware reply via EmotionEngine, then fallback to NarAI voice_chat
        owner_number = os.getenv("WHATSAPP_OWNER_NUMBER", "")
        is_owner = sender == owner_number or sender.endswith(owner_number[-10:]) if owner_number else False

        try:
            if is_owner:
                # Owner message → use EmotionEngine for empathetic response
                from core.emotion_engine import get_engine
                reply = get_engine().get_empathetic_response(body, mood=detected_mood)
            else:
                reply = ""

            if not reply:
                # Non-owner or fallback: use NarAI voice_chat
                from bots.narai.bot import get_narai
                narai = get_narai()
                mood_ctx = f"[User mood detected: {detected_mood}] " if detected_mood != "neutral" else ""
                reply_result = narai.voice_chat(
                    f"{mood_ctx}[WhatsApp message from {name} (+{sender})]: '{body}'. "
                    f"Detect language and reply in THAT language. Be warm, empathetic, human."
                )
                reply = reply_result.get("response", "") if isinstance(reply_result, dict) else str(reply_result)

            if reply:
                self.send_message(sender, reply)
                self._mark_replied(msg_id, reply)
                # Update last interaction time for check-in scheduler
                _checkin_scheduler.record_interaction()
                return
        except Exception as e:
            logger.warning("WhatsApp reply error: %s", e)

        # Fallback: static auto-reply if configured
        if self.auto_reply:
            self.send_message(sender, self.auto_reply)

    def _on_media_message(self, sender: str, name: str, msg_id: str, media_type: str) -> None:
        self.mark_read(msg_id)
        try:
            from core.telegram import notify
            notify(
                f"📲 <b>WhatsApp {media_type}</b>\n"
                f"👤 {name} (+{sender})"
            )
        except Exception:
            pass


# ─── Mood Check-In Scheduler ─────────────────────────────────────────────────

class MoodCheckInScheduler:
    """
    Proactively sends mood check-in messages to the owner via WhatsApp.

    Triggers:
      • Morning check-in (8:00–9:00 AM)
      • After 3+ hours of silence
      • After detecting a sad/anxious mood streak

    All data stays local — no cloud analytics.
    """

    # Hours at which morning check-in is sent
    MORNING_HOUR_START = 8
    MORNING_HOUR_END = 9
    # Silence threshold before sending a "everything okay?" message
    SILENCE_HOURS = 3
    # Minimum gap between any two check-ins (hours)
    MIN_GAP_HOURS = 4

    def __init__(self):
        self._last_interaction: Optional[datetime] = None
        self._last_checkin: Optional[datetime] = None
        self._morning_sent_today: bool = False
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._owner_number = os.getenv("WHATSAPP_OWNER_NUMBER", "")

    def start(self):
        if not self._owner_number:
            logger.warning("WHATSAPP_OWNER_NUMBER not set — mood check-ins disabled")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="NarAI-CheckIn",
        )
        self._thread.start()
        logger.info("Mood check-in scheduler started for owner: %s", self._owner_number)

    def stop(self):
        self._running = False

    def record_interaction(self):
        """Call whenever the owner sends a WhatsApp message."""
        self._last_interaction = datetime.now()
        self._morning_sent_today = True   # If they messaged us, skip the morning nudge

    def _scheduler_loop(self):
        while self._running:
            try:
                self._evaluate()
            except Exception as e:
                logger.debug("Check-in scheduler tick error: %s", e)
            time.sleep(300)   # Check every 5 minutes

    def _evaluate(self):
        now = datetime.now()
        today = now.date()

        # Reset morning flag at midnight
        if self._last_checkin and self._last_checkin.date() < today:
            self._morning_sent_today = False

        # Enforce minimum gap
        if self._last_checkin:
            gap = (now - self._last_checkin).total_seconds() / 3600
            if gap < self.MIN_GAP_HOURS:
                return

        # ── Morning check-in ──────────────────────────────────────────────
        if (self.MORNING_HOUR_START <= now.hour < self.MORNING_HOUR_END
                and not self._morning_sent_today):
            self._send_checkin(reason="morning")
            self._morning_sent_today = True
            return

        # ── Silence check ─────────────────────────────────────────────────
        if self._last_interaction:
            silence_hours = (now - self._last_interaction).total_seconds() / 3600
            if silence_hours >= self.SILENCE_HOURS:
                self._send_checkin(reason="silence")
                return

        # ── Mood streak check ─────────────────────────────────────────────
        try:
            from core.emotion_engine import get_engine
            engine = get_engine()
            trend = engine.get_mood_trend(days=2)
            dominant = trend.get("dominant", "neutral")
            if dominant in ("sad", "anxious") and trend.get("total_readings", 0) >= 3:
                self._send_checkin(reason="mood_streak", mood=dominant)
        except Exception:
            pass

    def _send_checkin(self, reason: str = "general", mood: str = None):
        if not self._owner_number:
            return

        try:
            from core.emotion_engine import get_engine
            engine = get_engine()
            current_mood = mood or engine.get_current_mood()
            message = engine.get_checkin_message(current_mood)

            # Add personalized insights occasionally
            insights = engine.get_personalized_insights()
            if insights and reason != "morning":
                import random
                if random.random() < 0.3:
                    message = random.choice(insights)

        except Exception:
            # Fallback messages
            import random
            fallbacks = [
                "Hey, how are you feeling today? 💙",
                "I noticed you've been quiet. Everything okay?",
                "What's on your mind right now?",
                "Just checking in — I'm here.",
            ]
            message = random.choice(fallbacks)

        client = get_client()
        if client.is_configured():
            sent = client.send_message(self._owner_number, message)
            if sent:
                self._last_checkin = datetime.now()
                logger.info("Mood check-in sent (reason=%s, mood=%s): %s", reason, mood, message[:80])
            else:
                logger.warning("Mood check-in failed to send")


# ── Scheduler singleton ───────────────────────────────────────────────────────
_checkin_scheduler = MoodCheckInScheduler()


def start_checkins():
    """Start the proactive mood check-in scheduler. Call at app startup."""
    _checkin_scheduler.start()


def stop_checkins():
    """Stop the check-in scheduler."""
    _checkin_scheduler.stop()


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[WhatsAppClient] = None


def get_client() -> WhatsAppClient:
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client


def send_message(to: str, text: str) -> bool:
    """Send a WhatsApp text message. Import this anywhere in the codebase."""
    return get_client().send_message(to, text)


def send_image(to: str, image_url: str, caption: str = "") -> bool:
    """Send a WhatsApp image. Import this anywhere in the codebase."""
    return get_client().send_image(to, image_url, caption)


def send_audio(to: str, audio_url: str) -> bool:
    """Send a WhatsApp audio/voice note. Import this anywhere in the codebase."""
    return get_client().send_audio(to, audio_url)


def send_video(to: str, video_url: str, caption: str = "") -> bool:
    """Send a WhatsApp video. Import this anywhere in the codebase."""
    return get_client().send_video(to, video_url, caption)
