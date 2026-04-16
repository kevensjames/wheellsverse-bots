"""
core/people_memory.py — NarAI's Memory of Every Person

Every human NarAI has ever interacted with gets a persistent profile.
This gives NarAI relationship context so she never treats a loyal fan
like a stranger, and never misses a warm lead.
"""

from __future__ import annotations
import json
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

DATA_FILE = Path("data/people_memory.json")
MAX_MESSAGES_PER_PERSON = 100   # keep last N messages per person
VIP_INTERACTION_THRESHOLD = 10  # 10+ interactions = VIP
COLD_LEAD_DAYS = 7              # no contact in 7 days = cold lead
HOT_LEAD_SCORE = 50             # engagement score to consider "hot"


class PersonRecord:
    """Full profile for one person across all platforms."""

    def __init__(self, uid: str, platform: str, handle: str = ""):
        self.uid = uid                         # unique key: platform:user_id
        self.platform = platform
        self.handle = handle
        self.name = ""
        self.email = ""
        self.tags: List[str] = []              # interests, segments, labels
        self.interaction_count = 0
        self.sentiment_score = 0.0             # -1.0 (hostile) to +1.0 (fan)
        self.purchase_stage = "cold"           # cold/warm/hot/customer/vip
        self.topics_mentioned: Dict[str, int] = {}   # topic → mention count
        self.intents: List[str] = []           # last 20 detected intents
        self.messages: List[Dict] = []         # last 100 messages (both directions)
        self.affiliate_clicks: List[str] = []  # which affiliate links they clicked
        self.converted = False                 # purchased / subscribed
        self.first_seen = datetime.now(timezone.utc).isoformat()
        self.last_seen = self.first_seen
        self.notes = ""                        # manual notes about person

    # ── Scoring ────────────────────────────────────────────────────────────────

    @property
    def engagement_score(self) -> float:
        """Higher = more valuable relationship."""
        score = self.interaction_count * 5.0
        score += self.sentiment_score * 20.0
        score += len(self.affiliate_clicks) * 10.0
        score += (50.0 if self.converted else 0.0)
        if self.purchase_stage == "vip":
            score += 100.0
        elif self.purchase_stage == "customer":
            score += 50.0
        elif self.purchase_stage == "hot":
            score += 25.0
        elif self.purchase_stage == "warm":
            score += 10.0
        return round(score, 1)

    @property
    def is_vip(self) -> bool:
        return self.interaction_count >= VIP_INTERACTION_THRESHOLD or self.purchase_stage == "vip"

    @property
    def is_cold(self) -> bool:
        try:
            last = datetime.fromisoformat(self.last_seen)
            return (datetime.now(timezone.utc) - last).days >= COLD_LEAD_DAYS
        except Exception:
            return True

    @property
    def top_interest(self) -> str:
        if not self.topics_mentioned:
            return "general"
        return max(self.topics_mentioned, key=self.topics_mentioned.get)

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "uid": self.uid,
            "platform": self.platform,
            "handle": self.handle,
            "name": self.name,
            "email": self.email,
            "tags": self.tags,
            "interaction_count": self.interaction_count,
            "sentiment_score": self.sentiment_score,
            "purchase_stage": self.purchase_stage,
            "topics_mentioned": self.topics_mentioned,
            "intents": self.intents[-20:],
            "messages": self.messages[-MAX_MESSAGES_PER_PERSON:],
            "affiliate_clicks": self.affiliate_clicks,
            "converted": self.converted,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "engagement_score": self.engagement_score,
            "is_vip": self.is_vip,
            "is_cold": self.is_cold,
            "top_interest": self.top_interest,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PersonRecord":
        p = cls(d["uid"], d["platform"], d.get("handle", ""))
        p.name = d.get("name", "")
        p.email = d.get("email", "")
        p.tags = d.get("tags", [])
        p.interaction_count = d.get("interaction_count", 0)
        p.sentiment_score = d.get("sentiment_score", 0.0)
        p.purchase_stage = d.get("purchase_stage", "cold")
        p.topics_mentioned = d.get("topics_mentioned", {})
        p.intents = d.get("intents", [])
        p.messages = d.get("messages", [])
        p.affiliate_clicks = d.get("affiliate_clicks", [])
        p.converted = d.get("converted", False)
        p.first_seen = d.get("first_seen", datetime.now(timezone.utc).isoformat())
        p.last_seen = d.get("last_seen", p.first_seen)
        p.notes = d.get("notes", "")
        return p


# ─── People Memory Engine ──────────────────────────────────────────────────────

class PeopleMemory:
    _instance: Optional["PeopleMemory"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._people: Dict[str, PersonRecord] = {}
        self._load()

    @classmethod
    def get(cls) -> "PeopleMemory":
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
                for uid, d in raw.items():
                    self._people[uid] = PersonRecord.from_dict(d)
                log.info(f"PeopleMemory: loaded {len(self._people)} person records")
            except Exception as e:
                log.error(f"PeopleMemory load error: {e}")

    def _save(self):
        try:
            DATA_FILE.write_text(json.dumps(
                {uid: p.to_dict() for uid, p in self._people.items()},
                indent=2
            ))
        except Exception as e:
            log.error(f"PeopleMemory save error: {e}")

    # ── Core API ───────────────────────────────────────────────────────────────

    def _uid(self, platform: str, user_id: str) -> str:
        return f"{platform.lower()}:{user_id}"

    def get_or_create(self, platform: str, user_id: str, handle: str = "") -> PersonRecord:
        uid = self._uid(platform, user_id)
        if uid not in self._people:
            self._people[uid] = PersonRecord(uid, platform, handle)
        elif handle and not self._people[uid].handle:
            self._people[uid].handle = handle
        return self._people[uid]

    def remember(
        self,
        platform: str,
        user_id: str,
        message: str,
        direction: str = "inbound",    # "inbound" | "outbound"
        intent: str = "",
        topic: str = "",
        handle: str = "",
        sentiment_delta: float = 0.0,
    ) -> PersonRecord:
        """
        Core method — called every time NarAI interacts with someone.
        Records the message, updates stats, auto-advances purchase stage.
        """
        with self._lock:
            p = self.get_or_create(platform, user_id, handle)
            now = datetime.now(timezone.utc).isoformat()

            # Record message
            p.messages.append({
                "ts": now,
                "direction": direction,
                "text": message[:500],  # cap to 500 chars
                "intent": intent,
                "topic": topic,
            })
            if len(p.messages) > MAX_MESSAGES_PER_PERSON:
                p.messages = p.messages[-MAX_MESSAGES_PER_PERSON:]

            # Update stats
            if direction == "inbound":
                p.interaction_count += 1
                p.last_seen = now

            # Intent tracking
            if intent:
                p.intents.append(intent)
                if len(p.intents) > 20:
                    p.intents = p.intents[-20:]

            # Topic tracking
            if topic:
                p.topics_mentioned[topic] = p.topics_mentioned.get(topic, 0) + 1

            # Sentiment
            p.sentiment_score = max(-1.0, min(1.0, p.sentiment_score + sentiment_delta))

            # Auto-advance purchase stage
            self._advance_stage(p)

            self._save()
            return p

    def _advance_stage(self, p: PersonRecord):
        """Move person through funnel automatically based on behavior."""
        if p.converted or p.purchase_stage == "customer":
            if p.interaction_count >= VIP_INTERACTION_THRESHOLD:
                p.purchase_stage = "vip"
            return

        score = p.engagement_score
        if score >= HOT_LEAD_SCORE:
            p.purchase_stage = "hot"
        elif score >= 20:
            p.purchase_stage = "warm"
        elif p.interaction_count > 0:
            p.purchase_stage = "cold"

        if p.affiliate_clicks:
            p.purchase_stage = "hot"

    def mark_converted(self, platform: str, user_id: str):
        uid = self._uid(platform, user_id)
        if uid in self._people:
            self._people[uid].converted = True
            self._people[uid].purchase_stage = "customer"
            self._save()

    def record_affiliate_click(self, platform: str, user_id: str, affiliate: str):
        with self._lock:
            p = self.get_or_create(platform, user_id)
            p.affiliate_clicks.append(affiliate)
            self._advance_stage(p)
            self._save()

    def add_tag(self, platform: str, user_id: str, tag: str):
        self._uid(platform, user_id)
        p = self.get_or_create(platform, user_id)
        if tag not in p.tags:
            p.tags.append(tag)
            self._save()

    def set_note(self, platform: str, user_id: str, note: str):
        p = self.get_or_create(platform, user_id)
        p.notes = note
        self._save()

    # ── Relationship prompt ────────────────────────────────────────────────────

    def get_relationship_prompt(self, platform: str, user_id: str) -> str:
        """
        Returns context about this person for injection into DM reply GPT calls.
        NarAI uses this to remember the person and respond appropriately.
        """
        uid = self._uid(platform, user_id)
        if uid not in self._people:
            return "This is a new person — NarAI has never interacted with them before. Be welcoming."

        p = self._people[uid]
        lines = [f"RELATIONSHIP CONTEXT for {p.handle or user_id}:"]

        if p.name:
            lines.append(f"- Name: {p.name}")
        lines.append(f"- Interactions: {p.interaction_count} times")
        lines.append(f"- Stage: {p.purchase_stage}")
        lines.append(f"- Top interest: {p.top_interest}")
        lines.append(f"- Sentiment: {'positive' if p.sentiment_score > 0.2 else 'neutral' if p.sentiment_score > -0.2 else 'negative'}")

        if p.intents:
            recent_intents = list(dict.fromkeys(p.intents[-5:]))  # deduplicated
            lines.append(f"- Recent intents: {', '.join(recent_intents)}")

        if p.affiliate_clicks:
            lines.append(f"- Clicked affiliate links: {', '.join(set(p.affiliate_clicks))}")

        if p.converted:
            lines.append("- Has converted / purchased before — treat as a customer.")

        if p.is_vip:
            lines.append("- VIP — highly engaged, treat with extra warmth and depth.")

        if p.is_cold:
            lines.append("- Has been away for a while — re-engage warmly, don't assume they remember everything.")

        # Last 3 messages for context
        recent = [m for m in p.messages[-6:] if m.get("direction") == "inbound"][-3:]
        if recent:
            lines.append("- Recent messages from them:")
            for m in recent:
                lines.append(f'  "{m["text"][:100]}"')

        if p.notes:
            lines.append(f"- Notes: {p.notes}")

        return "\n".join(lines)

    # ── Lists & segments ───────────────────────────────────────────────────────

    def get_person(self, platform: str, user_id: str) -> Optional[Dict]:
        uid = self._uid(platform, user_id)
        p = self._people.get(uid)
        return p.to_dict() if p else None

    def get_all(self, platform: str = "") -> List[Dict]:
        people = list(self._people.values())
        if platform:
            people = [p for p in people if p.platform == platform.lower()]
        return sorted([p.to_dict() for p in people], key=lambda x: x["engagement_score"], reverse=True)

    def get_vip_list(self) -> List[Dict]:
        return [p.to_dict() for p in self._people.values() if p.is_vip]

    def get_hot_leads(self) -> List[Dict]:
        return [p.to_dict() for p in self._people.values()
                if p.purchase_stage in ("hot", "warm") and not p.converted]

    def get_cold_leads(self) -> List[Dict]:
        return [p.to_dict() for p in self._people.values()
                if p.is_cold and not p.converted and p.interaction_count > 0]

    def get_customers(self) -> List[Dict]:
        return [p.to_dict() for p in self._people.values() if p.converted]

    def get_by_tag(self, tag: str) -> List[Dict]:
        return [p.to_dict() for p in self._people.values() if tag in p.tags]

    def get_by_topic(self, topic: str) -> List[Dict]:
        return [p.to_dict() for p in self._people.values()
                if topic in p.topics_mentioned]

    def search(self, query: str) -> List[Dict]:
        q = query.lower()
        results = []
        for p in self._people.values():
            if (q in p.handle.lower() or q in p.name.lower()
                    or q in p.email.lower() or q in p.notes.lower()):
                results.append(p.to_dict())
        return results

    # ── Stats & summary ────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        people = list(self._people.values())
        by_stage: Dict[str, int] = {}
        by_platform: Dict[str, int] = {}
        for p in people:
            by_stage[p.purchase_stage] = by_stage.get(p.purchase_stage, 0) + 1
            by_platform[p.platform] = by_platform.get(p.platform, 0) + 1

        return {
            "total_people": len(people),
            "vip": len([p for p in people if p.is_vip]),
            "hot_leads": len([p for p in people if p.purchase_stage == "hot"]),
            "warm_leads": len([p for p in people if p.purchase_stage == "warm"]),
            "cold_leads": len([p for p in people if p.is_cold and not p.converted]),
            "customers": len([p for p in people if p.converted]),
            "by_stage": by_stage,
            "by_platform": by_platform,
            "total_messages": sum(len(p.messages) for p in people),
            "avg_engagement_score": round(
                sum(p.engagement_score for p in people) / max(len(people), 1), 1
            ),
        }


# ─── Module-level convenience ─────────────────────────────────────────────────

def remember(platform: str, user_id: str, message: str, **kwargs) -> PersonRecord:
    return PeopleMemory.get().remember(platform, user_id, message, **kwargs)


def get_context(platform: str, user_id: str) -> str:
    return PeopleMemory.get().get_relationship_prompt(platform, user_id)
