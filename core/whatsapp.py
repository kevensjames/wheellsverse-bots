#!/usr/bin/env python3
"""
core/whatsapp.py
─────────────────────────────────────────────────────────────────────────────
WhatsApp Business Cloud API handler.

Features:
  • Parse incoming text messages and status updates
  • Send replies via WhatsApp Cloud API
  • Forward new message alerts to Telegram
  • Auto-reply with a default message when configured

Credentials needed in .env:
  WHATSAPP_ACCESS_TOKEN    — permanent token from Meta app dashboard
  WHATSAPP_PHONE_NUMBER_ID — phone number ID from Meta app dashboard
  WHATSAPP_AUTO_REPLY      — optional default reply text (leave empty to disable)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
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
        self.access_token    = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.auto_reply      = os.getenv("WHATSAPP_AUTO_REPLY", "").strip()

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
            "Content-Type":  "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to":                to,
            "type":              "text",
            "text":              {"body": text},
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
            sender    = msg.get("from", "")
            msg_id    = msg.get("id", "")
            msg_type  = msg.get("type", "")
            name      = contacts.get(sender, sender)

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
            state     = status.get("status", "")        # sent | delivered | read | failed
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

        # Notify Telegram
        try:
            from core.telegram import notify
            notify(
                f"📲 <b>WhatsApp message</b>\n"
                f"👤 {name} (+{sender})\n"
                f"💬 {body[:300]}"
            )
        except Exception:
            pass

        # NarAI conversational reply (overrides static auto_reply)
        try:
            from bots.narai.bot import get_narai
            narai = get_narai()
            reply_result = narai.voice_chat(
                f"[WhatsApp message received from {name} (+{sender})]. They wrote in their language: '{body}'. Detect what language they wrote in and reply naturally in THAT SAME LANGUAGE. Be warm, helpful, human. Keep it short."
            )
            reply = reply_result.get("response", "") if isinstance(reply_result, dict) else str(reply_result)
            if reply:
                self.send_message(sender, reply)
                self._mark_replied(msg_id, reply)
                return
        except Exception:
            pass

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
