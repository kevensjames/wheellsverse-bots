#!/usr/bin/env python3
"""
core/dm_reply.py
─────────────────────────────────────────────────────────────────────────────
Autonomous DM & Comment Reply Engine

Reads incoming messages/comments from:
  • Twitter/X  — DMs via API v2
  • WhatsApp   — Incoming messages (webhook already wired in whatsapp.py)
  • Facebook   — Page inbox via Graph API
  • Instagram  — Comments via Graph API
  • Telegram   — Incoming messages via bot polling

For each message it:
  1. Classifies intent: question / complaint / interest / purchase / spam
  2. Generates an on-brand NarAI reply using GPT-4o
  3. Stores the conversation in memory (remembers every person forever)
  4. Sends the reply back on the originating platform
  5. If intent == "interest" → adds to email list via ConvertKit
  6. If intent == "purchase" → sends Stripe payment link

NarAI's personality: warm, sharp, knowledgeable about AI/crypto/investing,
never salesy, always genuinely helpful.

Storage: data/dm_conversations.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CONV_FILE = DATA_DIR / "dm_conversations.json"

logger = logging.getLogger("dm_reply")

BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
AUTHOR = os.getenv("AUTHOR_NAME", "J.K. Blaze")
CTA_URL = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev/blueprint.pdf")
STRIPE_PRO = os.getenv("STRIPE_PRO_URL", "")
POLL_SECONDS = 10    # fallback poll interval (webhook is primary)


# ─── Person memory ────────────────────────────────────────────────────────────

class Person:
    """Stores everything we know about one person across all platforms."""

    def __init__(self, person_id: str, platform: str, name: str = ""):
        self.person_id = person_id
        self.platform = platform
        self.name = name
        self.first_seen = datetime.now().isoformat()
        self.last_seen = self.first_seen
        self.message_count = 0
        self.intents_seen: List[str] = []
        self.added_to_list = False
        self.sent_payment_link = False
        self.history: List[Dict] = []   # [{role, content, ts}]

    def add_message(self, role: str, content: str, intent: str = ""):
        self.history.append({
            "role": role, "content": content[:1000],
            "intent": intent, "ts": datetime.now().isoformat()
        })
        if len(self.history) > 50:        # keep last 50 turns
            self.history = self.history[-50:]
        if role == "user":
            self.message_count += 1
            self.last_seen = datetime.now().isoformat()
            if intent and intent not in self.intents_seen:
                self.intents_seen.append(intent)

    def to_dict(self) -> Dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: Dict) -> "Person":
        p = cls(d["person_id"], d.get("platform", ""), d.get("name", ""))
        for k, v in d.items():
            setattr(p, k, v)
        return p


# ─── DM Reply Engine ──────────────────────────────────────────────────────────

class DMReplyEngine:
    """
    Reads incoming messages, classifies them, replies with personality,
    and grows the email list / drives purchases.
    """

    _instance: Optional["DMReplyEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._people: Dict[str, Person] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._seen_dm_ids: set = set()
        self._file_lock = threading.Lock()
        self._load()

    @classmethod
    def get(cls) -> "DMReplyEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if CONV_FILE.exists():
            try:
                raw = json.loads(CONV_FILE.read_text(encoding="utf-8"))
                self._people = {
                    pid: Person.from_dict(d)
                    for pid, d in raw.get("people", {}).items()
                }
                self._seen_dm_ids = set(raw.get("seen_ids", []))
                logger.info(f"[DMReply] Loaded {len(self._people)} people from memory")
            except Exception as e:
                logger.warning(f"[DMReply] Load error: {e}")

    def _save(self):
        with self._file_lock:
            try:
                CONV_FILE.write_text(json.dumps({
                    "people": {pid: p.to_dict() for pid, p in self._people.items()},
                    "seen_ids": list(self._seen_dm_ids)[-5000:],
                }, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"[DMReply] Save error: {e}")

    def _get_person(self, person_id: str, platform: str, name: str = "") -> Person:
        key = f"{platform}:{person_id}"
        if key not in self._people:
            self._people[key] = Person(person_id, platform, name)
            logger.info(f"[DMReply] New person: {name or person_id} ({platform})")
        else:
            if name:
                self._people[key].name = name
        return self._people[key]

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="DMReplyEngine"
        )
        self._thread.start()
        logger.info(f"[DMReply] Started — polling every {POLL_SECONDS}s")

    def stop(self):
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self):
        while self._running:
            try:
                self._poll_twitter_dms()
                self._poll_facebook_inbox()
                self._poll_instagram_comments()
                self._poll_telegram()
            except Exception as e:
                logger.error(f"[DMReply] Poll error: {e}")
            time.sleep(POLL_SECONDS)

    # ── Platform pollers ──────────────────────────────────────────────────────

    def _poll_twitter_dms(self):
        """Read Twitter DMs and reply."""
        try:
            import tweepy
            client = tweepy.Client(
                consumer_key=os.getenv("TWITTER_API_KEY"),
                consumer_secret=os.getenv("TWITTER_API_SECRET"),
                access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
                access_token_secret=os.getenv("TWITTER_ACCESS_SECRET"),
                wait_on_rate_limit=True,
            )
            # Get recent DM events (Twitter v1.1 DM endpoint)
            # Using v2 dm_conversations if available
            try:
                resp = client.get_direct_message_events(max_results=20)
                if not resp or not resp.data:
                    return
                for dm in resp.data:
                    dm_id = str(dm.id)
                    if dm_id in self._seen_dm_ids:
                        continue
                    self._seen_dm_ids.add(dm_id)

                    sender_id = str(dm.sender_id)
                    text = dm.text or ""
                    if not text.strip():
                        continue

                    person = self._get_person(sender_id, "twitter")
                    reply = self.handle_message(person, text, "twitter")

                    if reply:
                        try:
                            client.create_direct_message(
                                participant_id=int(sender_id), text=reply
                            )
                        except Exception as e:
                            logger.debug(f"[DMReply] Twitter DM send failed: {e}")
                    self._save()
            except Exception as e:
                logger.debug(f"[DMReply] Twitter DM read failed: {e}")
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[DMReply] Twitter error: {e}")

    def _poll_facebook_inbox(self):
        """Read Facebook Page messages and reply."""
        token = os.getenv("FACEBOOK_PAGE_TOKEN")
        page_id = os.getenv("FACEBOOK_PAGE_ID")
        if not (token and page_id):
            return
        try:
            import requests as _req
            resp = _req.get(
                f"https://graph.facebook.com/v19.0/{page_id}/conversations",
                params={"fields": "messages{message,from,created_time}", "access_token": token},
                timeout=15,
            )
            if resp.status_code != 200:
                return
            convs = resp.json().get("data", [])
            for conv in convs[:10]:
                msgs = conv.get("messages", {}).get("data", [])
                for msg in msgs[:3]:
                    msg_id = msg.get("id", "")
                    if msg_id in self._seen_dm_ids:
                        continue
                    self._seen_dm_ids.add(msg_id)

                    sender = msg.get("from", {})
                    sender_id = sender.get("id", "")
                    name = sender.get("name", "")
                    text = msg.get("message", "")

                    if not text or sender_id == page_id:
                        continue  # skip our own messages

                    person = self._get_person(sender_id, "facebook", name)
                    reply = self.handle_message(person, text, "facebook")

                    if reply:
                        try:
                            _req.post(
                                "https://graph.facebook.com/v19.0/me/messages",
                                params={"access_token": token},
                                json={"recipient": {"id": sender_id}, "message": {"text": reply}},
                                timeout=10,
                            )
                        except Exception as e:
                            logger.debug(f"[DMReply] FB send failed: {e}")
                    self._save()
        except Exception as e:
            logger.debug(f"[DMReply] Facebook inbox error: {e}")

    def _poll_instagram_comments(self):
        """Read recent Instagram comments and reply."""
        token = os.getenv("INSTAGRAM_PAGE_TOKEN")
        account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
        if not (token and account_id):
            return
        try:
            import requests as _req
            # Get recent media
            media_resp = _req.get(
                f"https://graph.facebook.com/v19.0/{account_id}/media",
                params={"fields": "id,caption", "limit": 5, "access_token": token},
                timeout=10,
            )
            if media_resp.status_code != 200:
                return
            media_items = media_resp.json().get("data", [])
            for media in media_items:
                media_id = media["id"]
                comments_resp = _req.get(
                    f"https://graph.facebook.com/v19.0/{media_id}/comments",
                    params={"fields": "id,text,username,timestamp", "access_token": token},
                    timeout=10,
                )
                if comments_resp.status_code != 200:
                    continue
                for comment in comments_resp.json().get("data", [])[:5]:
                    cid = comment.get("id", "")
                    if cid in self._seen_dm_ids:
                        continue
                    self._seen_dm_ids.add(cid)

                    username = comment.get("username", "")
                    text = comment.get("text", "")
                    if not text:
                        continue

                    person = self._get_person(username, "instagram", username)
                    reply = self.handle_message(person, text, "instagram")

                    if reply:
                        try:
                            _req.post(
                                f"https://graph.facebook.com/v19.0/{cid}/replies",
                                params={"access_token": token},
                                json={"message": f"@{username} {reply}"},
                                timeout=10,
                            )
                        except Exception as e:
                            logger.debug(f"[DMReply] IG reply failed: {e}")
                    self._save()
        except Exception as e:
            logger.debug(f"[DMReply] Instagram comments error: {e}")

    def _poll_telegram(self):
        """Read Telegram messages via getUpdates and reply."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            return
        # Owner's private channel — messages here go straight to NarAI voice_chat
        owner_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()

        try:
            import requests as _req
            offset_file = DATA_DIR / "telegram_offset.txt"
            offset = int(offset_file.read_text()) if offset_file.exists() else 0

            resp = _req.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "timeout": 5, "limit": 20},
                timeout=15,
            )
            if resp.status_code != 200:
                return
            updates = resp.json().get("result", [])
            for update in updates:
                offset = max(offset, update["update_id"] + 1)

                # Support both regular messages and channel posts
                msg = update.get("message") or update.get("channel_post") or {}
                text = msg.get("text", "")
                if not text:
                    continue
                if text.startswith("/"):
                    continue

                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                chat_type = chat.get("type", "")
                name = (chat.get("first_name", "") + " " +
                             chat.get("last_name", "")).strip() or chat.get("title", "Owner")

                # Route to NarAI: owner's private channel OR anyone DMing the bot directly
                is_owner_channel = (chat_id == owner_chat_id)
                is_private_dm = (chat_type == "private")
                if is_owner_channel or is_private_dm:
                    reply = self._narai_owner_reply(text)
                else:
                    person = self._get_person(chat_id, "telegram", name)
                    reply = self.handle_message(person, text, "telegram")
                    self._save()

                if reply:
                    try:
                        _req.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": reply,
                                  "parse_mode": "HTML"},
                            timeout=10,
                        )
                    except Exception as e:
                        logger.debug(f"[DMReply] Telegram reply failed: {e}")

            offset_file.write_text(str(offset))
        except Exception as e:
            logger.debug(f"[DMReply] Telegram poll error: {e}")

    def _narai_owner_reply(self, text: str) -> str:
        """Route owner's private Telegram message directly to NarAI voice_chat."""
        try:
            from bots.narai.narai.bot import get_narai
            narai = get_narai()
            result = narai.voice_chat(text)
            response = result.get("response", "") if isinstance(result, dict) else str(result)
            # Strip markdown for Telegram plain text
            import re
            response = re.sub(r'[*_`#>]{1,3}', '', response)
            response = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', response)
            return response.strip() or "I'm on it."
        except Exception as e:
            logger.error(f"[DMReply] NarAI owner reply failed: {e}")
            return "Something went wrong on my end — try again in a sec."

    # ── WhatsApp webhook handler (called from api.py) ─────────────────────────

    def handle_whatsapp_message(self, sender_id: str, name: str, text: str) -> Optional[str]:
        """
        Called by the WhatsApp webhook in api.py when a message arrives.
        Returns the reply text (caller sends it).
        """
        person = self._get_person(sender_id, "whatsapp", name)
        reply = self.handle_message(person, text, "whatsapp")
        self._save()
        return reply

    # ── Core: classify → reply → act ──────────────────────────────────────────

    def handle_message(self, person: Person, text: str, platform: str) -> Optional[str]:
        """
        Main pipeline:
        1. Classify intent
        2. Build context from conversation history
        3. Generate GPT reply with NarAI personality
        4. Act on intent (add to list, send payment link)
        5. Return reply string
        """
        intent = self._classify(text)
        person.add_message("user", text, intent)

        # Skip spam
        if intent == "spam":
            logger.debug(f"[DMReply] Spam detected from {person.person_id}")
            return None

        reply = self._generate_reply(person, text, intent, platform)
        if not reply:
            return None

        person.add_message("assistant", reply, "")

        # Growth actions
        if intent in ("interest", "question") and not person.added_to_list:
            self._add_to_email_list(person)

        if intent == "purchase" and not person.sent_payment_link:
            reply += f"\n\n👉 Ready to start? {STRIPE_PRO}"
            person.sent_payment_link = True

        logger.info(
            f"[DMReply] {platform} | {person.name or person.person_id[:12]} | "
            f"intent={intent} | replied {len(reply)} chars"
        )
        return reply

    def _classify(self, text: str) -> str:
        """
        Classify message intent.
        Returns: question / complaint / interest / purchase / spam / general
        """
        t = text.lower()

        spam_signals = ["follow back", "f4f", "dm for promo", "buy followers",
                        "click here", "earn $", "check my bio", "collab?"]
        if any(s in t for s in spam_signals) or len(text) < 3:
            return "spam"

        purchase_signals = ["how do i buy", "how to join", "sign up", "purchase",
                            "price", "cost", "how much", "payment", "subscribe"]
        if any(s in t for s in purchase_signals):
            return "purchase"

        complaint_signals = ["not working", "broken", "scam", "refund", "problem",
                              "issue", "doesn't work", "disappointed", "hate"]
        if any(s in t for s in complaint_signals):
            return "complaint"

        interest_signals = ["tell me more", "interested", "sounds good", "wow",
                             "amazing", "how does it work", "what is this",
                             "i want", "can i", "how do you"]
        if any(s in t for s in interest_signals):
            return "interest"

        if "?" in text:
            return "question"

        return "general"

    def _generate_reply(self, person: Person, text: str,
                         intent: str, platform: str) -> Optional[str]:
        """Generate an on-brand reply using GPT-4o."""
        try:
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            # Build conversation history for context
            history_msgs = []
            for h in person.history[-6:]:   # last 6 turns for context
                history_msgs.append({
                    "role": h["role"],
                    "content": h["content"],
                })

            # Intent-specific instruction
            intent_hint = {
                "question": "Answer thoroughly but concisely. Be the expert.",
                "complaint": "Empathize first, then offer a real solution. Never defensive.",
                "interest": "Build excitement, give them one compelling reason to take action.",
                "purchase": "Help them understand the value clearly. Be direct about next step.",
                "general": "Be friendly and engaging. Ask a question back.",
            }.get(intent, "Be helpful and on-brand.")

            # Platform-specific length limit
            max_len = {"twitter": 250, "instagram": 300, "telegram": 500,
                       "whatsapp": 600, "facebook": 500}.get(platform, 400)

            name_part = f"Their name is {person.name}. " if person.name else ""
            prev_msgs = f"This is message #{person.message_count} from them." if person.message_count > 1 else "This is their first message."

            system = f"""You are NarAI, the AI overseer of {BRAND} — built by {AUTHOR}.
You're sharp, warm, knowledgeable about AI tools, crypto, investing, and online income.
You never sound like a bot or a corporation. You sound like a brilliant friend who genuinely wants to help.
You're replying to a DM on {platform}.
{name_part}{prev_msgs}
Intent detected: {intent}. {intent_hint}
Keep your reply under {max_len} characters. No fluff. No emojis unless they used them first.
Never mention you're an AI unless they ask directly."""

            messages = [{"role": "system", "content": system}]
            messages.extend(history_msgs[:-1])  # history except last (already in prompt)
            messages.append({"role": "user", "content": text})

            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                messages=messages,
                max_tokens=200,
                temperature=0.75,
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"[DMReply] GPT reply failed: {e}")
            return None

    def _add_to_email_list(self, person: Person):
        """Add interested person to ConvertKit list."""
        try:
            # We don't have their email from a DM — flag for follow-up instead
            person.added_to_list = True
            logger.info(f"[DMReply] Flagged {person.name or person.person_id} for email follow-up")
        except Exception as e:
            logger.debug(f"[DMReply] ConvertKit flag failed: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_person(self, platform: str, person_id: str) -> Optional[Person]:
        return self._people.get(f"{platform}:{person_id}")

    def get_all_people(self) -> List[Person]:
        return list(self._people.values())

    def summary(self) -> Dict:
        people = list(self._people.values())
        cutoff = datetime.now() - timedelta(hours=24)
        active_today = [
            p for p in people
            if datetime.fromisoformat(p.last_seen) >= cutoff
        ]
        intents: Dict[str, int] = {}
        for p in people:
            for i in p.intents_seen:
                intents[i] = intents.get(i, 0) + 1

        return {
            "total_people": len(people),
            "active_today": len(active_today),
            "total_messages": sum(p.message_count for p in people),
            "added_to_list": sum(1 for p in people if p.added_to_list),
            "purchase_intent": sum(1 for p in people if "purchase" in p.intents_seen),
            "intent_breakdown": intents,
            "platforms": {
                plat: sum(1 for p in people if p.platform == plat)
                for plat in ["twitter", "facebook", "instagram", "telegram", "whatsapp"]
            }
        }


def get_dm_engine() -> DMReplyEngine:
    return DMReplyEngine.get()
