"""
core/lead_capture.py — Lead Capture & Delivery System

Handles the full opt-in funnel:
  1. Someone messages NarAI on WhatsApp / Telegram / DM asking for the blueprint
  2. NarAI captures their contact info
  3. Lead magnet (AI Entrepreneur Blueprint PDF) is delivered instantly
  4. Lead is tagged in ConvertKit and enrolled in welcome sequence
  5. PeopleMemory is updated with their stage (warm lead → hot lead)
  6. GoalTracker increments leads_captured

Also handles:
  - Landing page lead capture (POST /api/leads/capture)
  - WhatsApp opt-in keyword detection ("blueprint", "free guide", "send me")
  - Re-engagement of cold leads
"""

from __future__ import annotations
import json
import os
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

DATA_FILE = Path("data/leads.json")

LEAD_MAGNET_TITLE = os.getenv("LEAD_MAGNET_TITLE", "The AI Entrepreneur Blueprint")
CTA_URL = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev/blueprint.pdf")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
AUTHOR = os.getenv("AUTHOR_NAME", "J.K. Blaze")
EMAIL_FROM = os.getenv("EMAIL_FROM_NAME", "WheellsVerse Bot")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Keywords that trigger lead magnet delivery ───────────────────────────────

OPT_IN_KEYWORDS = [
    "blueprint", "free guide", "send me", "send it", "i want it",
    "how do i get", "where do i get", "free pdf", "free ebook",
    "sign me up", "sign up", "subscribe", "opt in", "opt-in",
    "lead magnet", "free resource", "gimme", "get it",
]

# ─── Lead record ──────────────────────────────────────────────────────────────


class Lead:
    def __init__(self, source: str, contact: str, name: str = "",
                 platform: str = "", user_id: str = ""):
        self.source = source     # landing_page / whatsapp / telegram / dm / manual
        self.contact = contact    # email or phone
        self.name = name
        self.platform = platform
        self.user_id = user_id
        self.stage = "new"      # new / delivered / subscribed / customer
        self.tags: List[str] = []
        self.captured_at = datetime.now(timezone.utc).isoformat()
        self.delivered_at = ""
        self.convertkit_id = ""
        self.notes = ""

    def to_dict(self) -> Dict:
        return {
            "source": self.source, "contact": self.contact, "name": self.name,
            "platform": self.platform, "user_id": self.user_id, "stage": self.stage,
            "tags": self.tags, "captured_at": self.captured_at,
            "delivered_at": self.delivered_at, "convertkit_id": self.convertkit_id,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Lead":
        ln = cls(d["source"], d["contact"], d.get("name", ""),
                d.get("platform", ""), d.get("user_id", ""))
        ln.stage = d.get("stage", "new")
        ln.tags = d.get("tags", [])
        ln.captured_at = d.get("captured_at", "")
        ln.delivered_at = d.get("delivered_at", "")
        ln.convertkit_id = d.get("convertkit_id", "")
        ln.notes = d.get("notes", "")
        return ln


# ─── Lead Capture Engine ──────────────────────────────────────────────────────

class LeadCaptureEngine:
    _instance: Optional["LeadCaptureEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._leads: List[Lead] = []
        self._load()

    @classmethod
    def get(cls) -> "LeadCaptureEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if DATA_FILE.exists():
            try:
                raw = json.loads(DATA_FILE.read_text())
                self._leads = [Lead.from_dict(ln) for ln in raw]
            except Exception as e:
                log.error(f"Lead load error: {e}")

    def _save(self):
        DATA_FILE.write_text(json.dumps([ln.to_dict() for ln in self._leads], indent=2))

    # ── Core capture flow ──────────────────────────────────────────────────────

    def capture(self, contact: str, name: str = "", source: str = "landing_page",
                platform: str = "", user_id: str = "",
                tags: List[str] = None, niche: str = "general") -> Dict:
        """
        Full lead capture flow:
        1. Save lead record
        2. Add to ConvertKit + start welcome sequence
        3. Deliver lead magnet
        4. Update PeopleMemory
        5. Increment GoalTracker
        6. Notify via Telegram
        """
        with self._lock:
            # Check for duplicate
            existing = [ln for ln in self._leads if ln.contact == contact]
            if existing:
                lead = existing[0]
                lead.notes += f" | Re-captured {datetime.now().strftime('%Y-%m-%d')}"
            else:
                lead = Lead(source, contact, name, platform, user_id)
                lead.tags = tags or []
                self._leads.append(lead)

        # 1. ConvertKit
        ck_result = self._add_to_convertkit(contact, name, niche, tags or [])
        if ck_result.get("subscriber_id"):
            lead.convertkit_id = str(ck_result["subscriber_id"])
            lead.stage = "subscribed"

        # 2. Deliver lead magnet
        delivery = self._deliver_lead_magnet(contact, name, platform, user_id)
        if delivery.get("delivered"):
            lead.delivered_at = datetime.now(timezone.utc).isoformat()
            if lead.stage == "new":
                lead.stage = "delivered"

        # 3. Update PeopleMemory
        if platform and user_id:
            try:
                from core.people_memory import PeopleMemory
                PeopleMemory.get().remember(
                    platform, user_id,
                    f"Opted in for {LEAD_MAGNET_TITLE}",
                    direction="inbound",
                    intent="purchase",
                    topic="lead_magnet",
                    sentiment_delta=0.3,
                )
                PeopleMemory.get().add_tag(platform, user_id, "lead")
                PeopleMemory.get().add_tag(platform, user_id, niche)
            except Exception as e:
                log.warning(f"PeopleMemory update failed: {e}")

        # 4. GoalTracker
        try:
            from core.goal_tracker import increment
            increment("leads_captured", 1)
            if ck_result.get("subscriber_id"):
                from core.goal_tracker import GoalTracker
                subs = len(self._leads)
                GoalTracker.get().update("email_subscribers", subs)
        except Exception:
            pass

        # 5. Notify
        self._notify_new_lead(lead)
        self._save()

        return {
            "status": "captured",
            "contact": contact,
            "name": name,
            "stage": lead.stage,
            "convertkit": ck_result,
            "delivery": delivery,
        }

    def _add_to_convertkit(self, email: str, name: str, niche: str,
                           tags: List[str]) -> Dict:
        api_key = os.getenv("CONVERTKIT_API_KEY", "")
        api_secret = os.getenv("CONVERTKIT_API_SECRET", "")
        if not api_key:
            return {"error": "ConvertKit not configured"}

        try:
            import requests
            # Subscribe to form
            form_id = os.getenv("CONVERTKIT_FORM_ID", "")
            if form_id:
                r = requests.post(
                    f"https://api.convertkit.com/v3/forms/{form_id}/subscribe",
                    json={"api_key": api_key, "email": email,
                          "first_name": name.split()[0] if name else "",
                          "tags": tags + [niche, LEAD_MAGNET_TITLE]},
                    timeout=10,
                )
                d = r.json()
                return {"subscriber_id": d.get("subscription", {}).get("subscriber", {}).get("id"),
                        "status": "subscribed" if r.ok else "error"}
            else:
                # No form ID — add via API directly
                r = requests.post(
                    "https://api.convertkit.com/v3/subscribers",
                    json={"api_secret": api_secret, "email_address": email,
                          "first_name": name.split()[0] if name else ""},
                    timeout=10,
                )
                d = r.json()
                return {"subscriber_id": d.get("subscriber", {}).get("id"),
                        "status": "subscribed" if r.ok else d.get("message", "error")}
        except Exception as e:
            log.warning(f"ConvertKit add failed: {e}")
            return {"error": str(e)}

    def _deliver_lead_magnet(self, contact: str, name: str,
                             platform: str, user_id: str) -> Dict:
        """
        Deliver the lead magnet:
        - If email: send via Gmail SMTP
        - If WhatsApp: send via WhatsApp API
        - If Telegram: send message with link
        - Always: send welcome email if we have email
        """
        delivered = False
        methods = []
        first_name = name.split()[0] if name else "there"

        # Email delivery
        if "@" in contact:
            email_result = self._send_welcome_email(contact, first_name)
            if email_result.get("sent"):
                delivered = True
                methods.append("email")

        # WhatsApp delivery
        if platform == "whatsapp" and user_id:
            wa_result = self._send_whatsapp_blueprint(user_id, first_name)
            if wa_result.get("sent"):
                delivered = True
                methods.append("whatsapp")

        # Telegram delivery
        if platform == "telegram" and user_id:
            tg_result = self._send_telegram_blueprint(user_id, first_name)
            if tg_result.get("sent"):
                delivered = True
                methods.append("telegram")

        return {"delivered": delivered, "methods": methods}

    def _send_welcome_email(self, to_email: str, first_name: str) -> Dict:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
            port = int(os.getenv("EMAIL_PORT", 587))
            user = os.getenv("EMAIL_USER", "")
            pwd = os.getenv("EMAIL_PASSWORD", "")
            if not user or not pwd:
                return {"sent": False, "error": "Email not configured"}

            body = f"""Hi {first_name}!

Welcome to {BRAND} — I'm so excited you're here.

Your free copy of "{LEAD_MAGNET_TITLE}" is ready for you:
👉 {CTA_URL}

Inside you'll discover:
• The exact AI tools I use to generate passive income on autopilot
• The 3-step framework to your first $1,000 online
• The affiliate programs paying the highest commissions right now
• How to repurpose one piece of content across 10 platforms in minutes

This isn't theory — these are the actual systems I run every day.

Download it now and reply to this email with your biggest question.
I read every reply.

To your financial freedom,
{AUTHOR}
{BRAND}

P.S. Tomorrow I'll send you my #1 AI tool recommendation that most people overlook.
"""
            msg = MIMEMultipart()
            msg["From"] = f"{EMAIL_FROM} <{user}>"
            msg["To"] = to_email
            msg["Subject"] = f'🎁 Your "{LEAD_MAGNET_TITLE}" is here, {first_name}!'
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, pwd)
                server.send_message(msg)

            log.info(f"Welcome email sent to {to_email}")
            return {"sent": True}
        except Exception as e:
            log.warning(f"Email delivery failed: {e}")
            return {"sent": False, "error": str(e)}

    def _send_whatsapp_blueprint(self, phone: str, first_name: str) -> Dict:
        token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        if not token or not phone_id:
            return {"sent": False, "error": "WhatsApp not configured"}
        try:
            import requests
            message = (
                f"Hey {first_name}! 🎉\n\n"
                f"Here's your free *{LEAD_MAGNET_TITLE}*:\n"
                f"👉 {CTA_URL}\n\n"
                f"Inside you'll find the exact AI + crypto strategies I use to earn passive income.\n\n"
                f"Reply *DONE* when you've downloaded it and I'll send you Step 1. 🚀"
            )
            r = requests.post(
                f"https://graph.facebook.com/v19.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": phone,
                      "type": "text", "text": {"body": message}},
                timeout=10,
            )
            return {"sent": r.ok, "status_code": r.status_code}
        except Exception as e:
            return {"sent": False, "error": str(e)}

    def _send_telegram_blueprint(self, chat_id: str, first_name: str) -> Dict:
        if not TELEGRAM_TOKEN:
            return {"sent": False, "error": "Telegram not configured"}
        try:
            import requests
            message = (
                f"Hey {first_name}! 🎉\n\n"
                f"Here's your free *{LEAD_MAGNET_TITLE}*:\n"
                f"👉 {CTA_URL}\n\n"
                f"It covers the exact AI + crypto strategies I use every day.\n"
                f"Download it and let me know what you think\\!"
            )
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                timeout=10,
            )
            return {"sent": r.ok}
        except Exception as e:
            return {"sent": False, "error": str(e)}

    def _notify_new_lead(self, lead: Lead):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
            return
        try:
            import requests
            msg = (
                f"🎯 New Lead Captured!\n\n"
                f"Contact: {lead.contact}\n"
                f"Name: {lead.name or 'Unknown'}\n"
                f"Source: {lead.source}\n"
                f"Platform: {lead.platform or 'web'}\n"
                f"Stage: {lead.stage}\n"
                f"Total leads: {len(self._leads)}"
            )
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": msg},
                timeout=5,
            )
        except Exception:
            pass

    # ── Opt-in keyword detection ───────────────────────────────────────────────

    def detect_optin(self, message: str) -> bool:
        """Detect if a message is requesting the lead magnet."""
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in OPT_IN_KEYWORDS)

    def handle_optin_message(self, platform: str, user_id: str,
                              message: str, handle: str = "") -> Dict:
        """
        Called when DM/WhatsApp/Telegram message triggers opt-in.
        Asks for email if not in PeopleMemory, else delivers directly.
        """
        if not self.detect_optin(message):
            return {"triggered": False}

        # Check if we already have their email from PeopleMemory
        email = None
        try:
            from core.people_memory import PeopleMemory
            person = PeopleMemory.get().get_person(platform, user_id)
            if person:
                email = person.get("email", "")
        except Exception:
            pass

        if email:
            result = self.capture(email, source=platform,
                                  platform=platform, user_id=user_id)
            return {"triggered": True, "action": "delivered", **result}

        # No email — send reply asking for it
        ask_message = self._get_optin_ask_message(platform)
        self._send_reply(platform, user_id, ask_message)
        return {"triggered": True, "action": "asked_for_email",
                "reply_sent": ask_message[:80]}

    def _get_optin_ask_message(self, platform: str) -> str:
        if platform == "whatsapp":
            return (
                f"I'd love to send you the free *{LEAD_MAGNET_TITLE}*! 🎁\n\n"
                f"Just reply with your *email address* and I'll send it straight to your inbox."
            )
        return (
            f"I'll send you the free {LEAD_MAGNET_TITLE} right now! "
            f"Just reply with your email address and I'll get it to you instantly."
        )

    def _send_reply(self, platform: str, user_id: str, message: str):
        try:
            if platform == "whatsapp":
                self._send_whatsapp_blueprint(user_id, "")  # reuse sender
            elif platform == "telegram":
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": user_id, "text": message},
                    timeout=10,
                )
        except Exception as e:
            log.warning(f"Reply send failed: {e}")

    # ── Re-engagement ──────────────────────────────────────────────────────────

    def re_engage_cold_leads(self) -> Dict:
        """Send re-engagement message to leads who haven't converted."""
        cold = [ln for ln in self._leads
                if ln.stage in ("delivered", "subscribed") and not ln.convertkit_id]
        count = 0
        for lead in cold[:20]:  # max 20 per run
            if "@" in lead.contact:
                self._send_reengagement_email(lead.contact, lead.name)
                count += 1
        return {"re_engaged": count}

    def _send_reengagement_email(self, to_email: str, name: str):
        first = name.split()[0] if name else "there"
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
            port = int(os.getenv("EMAIL_PORT", 587))
            user = os.getenv("EMAIL_USER", "")
            pwd = os.getenv("EMAIL_PASSWORD", "")
            if not user or not pwd:
                return
            body = (
                f"Hey {first},\n\n"
                f"Just checking in — did you get a chance to go through the {LEAD_MAGNET_TITLE}?\n\n"
                f"If not, here's the link again: {CTA_URL}\n\n"
                f"The section on passive income with AI tools alone is worth 10x your time.\n\n"
                f"Reply and let me know where you're stuck — I'll help personally.\n\n"
                f"{AUTHOR}\n{BRAND}"
            )
            msg = MIMEMultipart()
            msg["From"] = f"{EMAIL_FROM} <{user}>"
            msg["To"] = to_email
            msg["Subject"] = f"Did you see this, {first}?"
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, pwd)
                server.send_message(msg)
        except Exception as e:
            log.warning(f"Re-engagement email failed: {e}")

    # ── Stats ──────────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        by_source: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        for ln in self._leads:
            by_source[ln.source] = by_source.get(ln.source, 0) + 1
            by_stage[ln.stage] = by_stage.get(ln.stage, 0) + 1

        return {
            "total_leads": len(self._leads),
            "by_source": by_source,
            "by_stage": by_stage,
            "subscribed": by_stage.get("subscribed", 0),
            "delivered": by_stage.get("delivered", 0) + by_stage.get("subscribed", 0),
            "convertkit_configured": bool(os.getenv("CONVERTKIT_API_KEY")),
            "whatsapp_configured": bool(os.getenv("WHATSAPP_ACCESS_TOKEN")),
            "email_configured": bool(os.getenv("EMAIL_USER")),
        }

    def get_all(self, limit: int = 50) -> List[Dict]:
        return [ln.to_dict() for ln in self._leads[-limit:]]


# ─── Module-level convenience ─────────────────────────────────────────────────

def capture_lead(contact: str, name: str = "", source: str = "landing_page",
                 platform: str = "", user_id: str = "",
                 niche: str = "general") -> Dict:
    return LeadCaptureEngine.get().capture(contact, name, source, platform, user_id, niche=niche)


def detect_optin(message: str) -> bool:
    return LeadCaptureEngine.get().detect_optin(message)


def handle_optin(platform: str, user_id: str, message: str, handle: str = "") -> Dict:
    return LeadCaptureEngine.get().handle_optin_message(platform, user_id, message, handle)
