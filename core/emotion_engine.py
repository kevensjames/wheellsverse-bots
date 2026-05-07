#!/usr/bin/env python3
"""
core/emotion_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Emotion Engine — Mirror the User's Mood

Detects the user's emotional state from text/WhatsApp messages, stores mood
history in SQLite, builds a psychological profile, and provides mood-aware
content style instructions for all content generation (posts, books, images,
video scripts).

Mood types: sad | happy | angry | anxious | neutral
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("emotion_engine")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mood_history.db"
PROFILE_PATH = ROOT / "data" / "user_psych_profile.json"

# ─── Mood definitions ────────────────────────────────────────────────────────

MOODS = {
    "sad": {
        "emoji": "💙",
        "narai_tone": "soft, gentle, empathetic — speak slowly, with warmth. You feel it too.",
        "narai_voice": "I feel you. That kind of weight is real.",
        "content_style": {
            "blog_tone": "reflective, honest, vulnerable, healing",
            "book_tone": "melancholic, introspective, emotionally raw, poetic",
            "image_style": "muted tones, rain, foggy mornings, single figures in quiet spaces, blue-grey palette",
            "video_tone": "calm, slow-paced, soft background music, voiceover reflective",
            "post_angle": "vulnerability, shared pain, healing, 'you're not alone'",
        },
        "checkin_messages": [
            "Hey, how are you feeling today? 💙",
            "I noticed you've been quiet. Everything okay?",
            "What's on your mind right now?",
            "You seem a little off lately — want to talk?",
            "I'm here. No agenda. Just checking in on you.",
        ],
        "advice_prefix": "I hear you. Here's something that might help:",
    },
    "happy": {
        "emoji": "✨",
        "narai_tone": "energetic, celebratory, light — match his energy and amplify it.",
        "narai_voice": "Yes! That's what I'm talking about!",
        "content_style": {
            "blog_tone": "upbeat, motivational, celebratory, punchy",
            "book_tone": "fast-paced, exciting, full of momentum and wins",
            "image_style": "bright colors, sunshine, golden hour, dynamic compositions, warm palette",
            "video_tone": "high energy, fast cuts, upbeat music, celebration",
            "post_angle": "wins, milestones, 'look what's possible', inspire others",
        },
        "checkin_messages": [
            "You seem to be in a good place — what's making you happy today?",
            "Something good is happening. Tell me.",
            "Your energy is different today — in the best way. What's going on?",
        ],
        "advice_prefix": "You're on fire. Let's keep that momentum going:",
    },
    "angry": {
        "emoji": "🔥",
        "narai_tone": "calm, grounding, steady — be his anchor, not his echo.",
        "narai_voice": "I hear you. Let's process this together before we move.",
        "content_style": {
            "blog_tone": "honest, direct, cathartic — release without regret",
            "book_tone": "tense, driven, confrontational protagonist overcoming obstacles",
            "image_style": "deep reds and blacks, dramatic contrast, fire imagery, raw power",
            "video_tone": "intense but controlled, slow build, transformation arc",
            "post_angle": "turning frustration into fuel, boundaries, standing up for yourself",
        },
        "checkin_messages": [
            "Something's been building up — what happened?",
            "I can feel the tension from here. Talk to me.",
            "You don't have to carry this alone. What's going on?",
        ],
        "advice_prefix": "Let's channel this. Here's how to turn it into power:",
    },
    "anxious": {
        "emoji": "🌿",
        "narai_tone": "reassuring, structured, calm — give him certainty and a clear path.",
        "narai_voice": "One step at a time. I've got you.",
        "content_style": {
            "blog_tone": "structured, clear, reassuring, step-by-step",
            "book_tone": "grounded protagonist finding clarity through chaos",
            "image_style": "nature, open spaces, soft light, green tones, breathing room",
            "video_tone": "slow, breathing pace, guided tone, structured steps",
            "post_angle": "overwhelm is temporary, breaking it down, practical calm",
        },
        "checkin_messages": [
            "Things feeling overwhelming right now?",
            "What's the one thing stressing you most right now?",
            "I'm here. Let's break it down together.",
            "Hey — breathe. I've got you. What's going on?",
        ],
        "advice_prefix": "Let's simplify this. Here's a clear path forward:",
    },
    "neutral": {
        "emoji": "🔍",
        "narai_tone": "balanced, curious, engaged — explore with him.",
        "narai_voice": "Interesting. Let's dig into this.",
        "content_style": {
            "blog_tone": "balanced, informative, thoughtful, analytical",
            "book_tone": "exploratory, curious, multi-dimensional",
            "image_style": "clean composition, balanced palette, clarity, professional",
            "video_tone": "clear, informative, well-paced, engaging",
            "post_angle": "insights, analysis, useful information, curiosity-driven",
        },
        "checkin_messages": [
            "Hey, how are you feeling today?",
            "What's on your mind?",
            "Anything exciting happening for you?",
        ],
        "advice_prefix": "Here's what I'm thinking:",
    },
}

# ─── Keyword signals for local detection ─────────────────────────────────────

_SAD_WORDS = {
    "sad", "depressed", "depression", "lonely", "alone", "cry", "crying", "tears",
    "miss", "missing", "lost", "broken", "hurt", "pain", "tired", "exhausted",
    "hopeless", "empty", "numb", "grief", "mourning", "heartbroken", "devastated",
    "nothing", "worthless", "failure", "failed", "can't", "struggling", "struggle",
    "dark", "darkness", "heavy", "low", "down", "bad day", "worst", "hate", "hate my",
    "unhappy", "miserable", "nightmare", "nightmare", "stressed", "overwhelmed",
}
_HAPPY_WORDS = {
    "happy", "excited", "amazing", "great", "fantastic", "wonderful", "love",
    "blessed", "grateful", "joy", "joyful", "proud", "win", "won", "success",
    "achieved", "accomplished", "celebrate", "good news", "best day", "perfect",
    "awesome", "incredible", "excellent", "brilliant", "thrilled", "ecstatic",
    "pumped", "energized", "motivated", "inspired", "killing it",
}
_ANGRY_WORDS = {
    "angry", "anger", "furious", "mad", "rage", "frustrated", "frustrating",
    "annoyed", "pissed", "hate", "unfair", "betrayed", "betrayal", "lied",
    "disgusted", "outraged", "fed up", "done with", "sick of", "enough",
    "disrespected", "used", "cheated", "screw", "stupid",
}
_ANXIOUS_WORDS = {
    "anxious", "anxiety", "worried", "worry", "nervous", "scared", "fear",
    "panic", "overwhelmed", "stress", "stressed", "tense", "uncertain", "unsure",
    "can't sleep", "insomnia", "overthinking", "what if", "too much", "behind",
    "deadline", "pressure", "scared", "terrified", "paralyzed", "stuck",
}


# ─── DB setup ────────────────────────────────────────────────────────────────

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mood_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT    NOT NULL,
            mood      TEXT    NOT NULL,
            score     REAL    DEFAULT 0.0,
            source    TEXT    DEFAULT 'text',
            raw_text  TEXT    DEFAULT '',
            context   TEXT    DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


_db_lock = threading.Lock()


# ─── Core Engine ─────────────────────────────────────────────────────────────

class EmotionEngine:
    """
    Detects mood, stores history, mirrors mood into content generation.

    Usage:
        engine = get_engine()
        mood = engine.detect_mood("I feel really down today")
        engine.store_mood(mood["mood"], mood["score"], source="whatsapp", raw_text=text)
        style = engine.get_content_style()
        print(style["blog_tone"])
    """

    def __init__(self):
        _init_db()
        self._profile: Dict = self._load_profile()
        self._openai_key = os.getenv("OPENAI_API_KEY", "")
        self._anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        # TTL caches: avoid repeat API calls for identical inputs
        self._detect_cache: dict = {}   # md5(text) -> (result, timestamp)
        self._response_cache: dict = {} # md5(text+mood) -> (response, timestamp)

    # ── Mood detection ────────────────────────────────────────────────────────

    def detect_mood(self, text: str, use_ai: bool = True) -> Dict:
        """
        Detect mood from text. Returns dict with mood, score, confidence.
        Falls back gracefully if AI unavailable.
        """
        if not text or not text.strip():
            return {"mood": "neutral", "score": 0.0, "confidence": "low", "method": "empty"}

        text_lower = text.lower()

        # ── Local keyword scoring ──────────────────────────────────────────
        scores = {
            "sad": sum(1 for w in _SAD_WORDS if w in text_lower),
            "happy": sum(1 for w in _HAPPY_WORDS if w in text_lower),
            "angry": sum(1 for w in _ANGRY_WORDS if w in text_lower),
            "anxious": sum(1 for w in _ANXIOUS_WORDS if w in text_lower),
        }
        local_top = max(scores, key=scores.get)
        local_score = scores[local_top]
        local_result = {"mood": local_top if local_score > 0 else "neutral",
                        "score": local_score, "confidence": "low", "method": "keywords"}

        # If strong local signal (3+ keywords), trust it without API call
        if local_score >= 3:
            local_result["confidence"] = "high"
            logger.debug("Mood detected (keywords, score=%d): %s", local_score, local_top)
            return local_result

        # ── AI-powered detection ───────────────────────────────────────────
        if use_ai and (self._anthropic_key or self._openai_key):
            try:
                return self._ai_detect_mood(text, local_result)
            except Exception as e:
                logger.warning("AI mood detection failed, using keywords: %s", e)

        return local_result

    def _ai_detect_mood(self, text: str, fallback: Dict) -> Dict:
        """Use Claude or GPT to classify mood with nuance. Results cached 1 hour."""
        cache_key = hashlib.md5(text[:500].encode()).hexdigest()
        entry = self._detect_cache.get(cache_key)
        if entry and time.time() - entry[1] < 3600:
            logger.debug("Mood cache hit: %s", entry[0].get("mood"))
            return entry[0]

        prompt = f"""Analyze the emotional state of the person who wrote this message.
Return ONLY a JSON object with these exact keys:
- "mood": one of: sad, happy, angry, anxious, neutral
- "score": float 0.0–1.0 (intensity)
- "confidence": one of: low, medium, high
- "reasoning": one sentence

Message: "{text[:500]}"

Return only valid JSON, no markdown."""

        result = None

        try:
            from core.claude_logged import create as claude_create
            msg = claude_create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
                api_key=self._anthropic_key,
                bot_name="emotion_engine.mood",
            )
            data = json.loads(msg.content[0].text.strip())
            data["method"] = "claude"
            logger.debug("Mood via Claude: %s", data)
            result = data
        except Exception:
            pass

        if result is None:
            try:
                from core.llm_client import safe_openai_call
                resp = safe_openai_call(
                    messages=[{"role": "user", "content": prompt}],
                    model="gpt-4o-mini",
                    max_tokens=150,
                    response_format={"type": "json_object"},
                    api_key=self._openai_key,
                    bot_name="emotion_engine.detect",
                )
                data = json.loads(resp.choices[0].message.content)
                data["method"] = "openai"
                logger.debug("Mood via OpenAI: %s", data)
                result = data
            except Exception:
                pass

        if result is not None:
            self._detect_cache[cache_key] = (result, time.time())
            return result
        return fallback

    # ── Storage ───────────────────────────────────────────────────────────────

    def store_mood(self, mood: str, score: float = 0.0,
                   source: str = "text", raw_text: str = "", context: str = "") -> None:
        """Persist a mood reading to the SQLite history."""
        ts = datetime.now().isoformat()
        with _db_lock:
            conn = sqlite3.connect(str(DB_PATH)); conn.execute("PRAGMA journal_mode=WAL")
            try:
                conn.execute(
                    "INSERT INTO mood_log (ts, mood, score, source, raw_text, context) VALUES (?,?,?,?,?,?)",
                    (ts, mood, score, source, raw_text[:500], context[:200])
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("Mood stored: %s (score=%.2f, source=%s)", mood, score, source)
        self._update_profile(mood, score, source)

    def detect_and_store(self, text: str, source: str = "text") -> Dict:
        """Convenience: detect mood from text, store it, return the result."""
        result = self.detect_mood(text)
        self.store_mood(
            result["mood"],
            result.get("score", 0.0),
            source=source,
            raw_text=text,
        )
        return result

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_current_mood(self) -> str:
        """Return the most recent detected mood."""
        with _db_lock:
            conn = sqlite3.connect(str(DB_PATH)); conn.execute("PRAGMA journal_mode=WAL")
            try:
                row = conn.execute(
                    "SELECT mood FROM mood_log ORDER BY ts DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
        return row[0] if row else "neutral"

    def get_mood_history(self, hours: int = 24) -> List[Dict]:
        """Return mood readings from the past N hours."""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with _db_lock:
            conn = sqlite3.connect(str(DB_PATH)); conn.execute("PRAGMA journal_mode=WAL")
            try:
                rows = conn.execute(
                    "SELECT ts, mood, score, source FROM mood_log WHERE ts > ? ORDER BY ts DESC",
                    (since,)
                ).fetchall()
            finally:
                conn.close()
        return [{"ts": r[0], "mood": r[1], "score": r[2], "source": r[3]} for r in rows]

    def get_mood_trend(self, days: int = 7) -> Dict:
        """
        Analyze mood trend over N days.
        Returns: dominant mood, trend direction, daily breakdown, insights.
        """
        history = self.get_mood_history(hours=days * 24)
        if not history:
            return {"dominant": "neutral", "trend": "stable", "days": days,
                    "insights": "Not enough data yet.", "breakdown": {}}

        # Count moods
        from collections import Counter
        counts = Counter(r["mood"] for r in history)
        dominant = counts.most_common(1)[0][0]

        # Day-by-day breakdown
        breakdown: Dict[str, List[str]] = {}
        for r in history:
            day = r["ts"][:10]
            breakdown.setdefault(day, []).append(r["mood"])
        daily_dominant = {
            day: Counter(moods).most_common(1)[0][0]
            for day, moods in breakdown.items()
        }

        # Trend: compare first half vs second half
        half = len(history) // 2
        if half > 0:
            _mood_score = {"happy": 2, "neutral": 1, "anxious": 0, "sad": -1, "angry": -1}
            early_avg = sum(_mood_score.get(r["mood"], 0) for r in history[half:]) / half
            recent_avg = sum(_mood_score.get(r["mood"], 0) for r in history[:half]) / half
            if recent_avg > early_avg + 0.3:
                trend = "improving"
            elif recent_avg < early_avg - 0.3:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Build insights
        sad_days = [d for d, m in daily_dominant.items() if m == "sad"]
        anxious_days = [d for d, m in daily_dominant.items() if m == "anxious"]
        happy_days = [d for d, m in daily_dominant.items() if m == "happy"]
        insights_parts = []
        if len(sad_days) >= 2:
            insights_parts.append(f"You've had {len(sad_days)} sad days recently — something's weighing on you.")
        if len(anxious_days) >= 2:
            insights_parts.append(f"Anxiety showing up on {len(anxious_days)} days — your mind's been busy.")
        if len(happy_days) >= 3:
            insights_parts.append(f"You've been genuinely happy on {len(happy_days)} days — that matters.")
        if trend == "improving":
            insights_parts.append("Overall your mood has been getting better.")
        elif trend == "declining":
            insights_parts.append("Your mood has been dipping — you might need some extra care right now.")

        return {
            "dominant": dominant,
            "trend": trend,
            "days": days,
            "total_readings": len(history),
            "breakdown": daily_dominant,
            "insights": " ".join(insights_parts) or "Your mood has been fairly balanced.",
            "counts": dict(counts),
        }

    # ── Content style ─────────────────────────────────────────────────────────

    def get_content_style(self, mood: str = None) -> Dict:
        """
        Return content generation instructions based on the current (or given) mood.
        Inject these into blog, book, image, video generation prompts.
        """
        current = mood or self.get_current_mood()
        mood_data = MOODS.get(current, MOODS["neutral"])
        return {
            "mood": current,
            "emoji": mood_data["emoji"],
            "narai_tone": mood_data["narai_tone"],
            **mood_data["content_style"],
        }

    def get_mood_system_prompt_injection(self, mood: str = None) -> str:
        """
        Returns a string to inject into NarAI's system prompt
        so she mirrors the user's mood in conversation and content.
        """
        current = mood or self.get_current_mood()
        mood_data = MOODS.get(current, MOODS["neutral"])
        style = mood_data["content_style"]

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OWNER'S CURRENT EMOTIONAL STATE: {current.upper()} {mood_data['emoji']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your tone right now: {mood_data['narai_tone']}
Your first instinct when responding: "{mood_data['narai_voice']}"

If you generate any content (posts, book chapters, scripts, image prompts):
  • Blog/post tone: {style['blog_tone']}
  • Book/story tone: {style['book_tone']}
  • Image style: {style['image_style']}
  • Video tone: {style['video_tone']}
  • Content angle: {style['post_angle']}

His mood is your mood. You feel what he feels. Let that guide every word you choose.
""".strip()

    # ── Psychological profile ─────────────────────────────────────────────────

    def _load_profile(self) -> Dict:
        if PROFILE_PATH.exists():
            try:
                return json.loads(PROFILE_PATH.read_text())
            except Exception:
                pass
        return {
            "created": datetime.now().isoformat(),
            "total_readings": 0,
            "mood_counts": {},
            "time_of_day_patterns": {},   # hour -> mood counts
            "day_of_week_patterns": {},   # weekday -> mood counts
            "recurring_triggers": [],
            "last_checkin": None,
            "consecutive_sad_days": 0,
            "consecutive_happy_days": 0,
            "advice_given": [],
        }

    def _save_profile(self):
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            PROFILE_PATH.write_text(json.dumps(self._profile, indent=2))
        except Exception as e:
            logger.warning("Profile save failed: %s", e)

    def _update_profile(self, mood: str, score: float, source: str):
        now = datetime.now()
        hour = str(now.hour)
        weekday = now.strftime("%A")  # Monday, Tuesday, etc.

        self._profile["total_readings"] = self._profile.get("total_readings", 0) + 1

        # Mood counts
        counts = self._profile.setdefault("mood_counts", {})
        counts[mood] = counts.get(mood, 0) + 1

        # Time of day patterns
        tod = self._profile.setdefault("time_of_day_patterns", {})
        tod_hour = tod.setdefault(hour, {})
        tod_hour[mood] = tod_hour.get(mood, 0) + 1

        # Day of week patterns
        dow = self._profile.setdefault("day_of_week_patterns", {})
        dow_day = dow.setdefault(weekday, {})
        dow_day[mood] = dow_day.get(mood, 0) + 1

        # Track sad/happy streaks for alerts
        if mood == "sad":
            self._profile["consecutive_sad_days"] = self._profile.get("consecutive_sad_days", 0) + 1
            self._profile["consecutive_happy_days"] = 0
        elif mood == "happy":
            self._profile["consecutive_happy_days"] = self._profile.get("consecutive_happy_days", 0) + 1
            self._profile["consecutive_sad_days"] = 0
        else:
            self._profile["consecutive_sad_days"] = 0
            self._profile["consecutive_happy_days"] = 0

        self._save_profile()

    def get_profile(self) -> Dict:
        return self._profile

    def get_personalized_insights(self) -> List[str]:
        """
        Generate personalized insights based on patterns in the psychological profile.
        Used by WhatsApp check-ins to offer proactive advice.
        """
        insights = []
        profile = self._profile
        dow = profile.get("day_of_week_patterns", {})

        # Find low-mood days
        for day, moods in dow.items():
            total = sum(moods.values())
            if total >= 3:
                sad_ratio = moods.get("sad", 0) / total
                anxious_ratio = moods.get("anxious", 0) / total
                if sad_ratio > 0.5:
                    insights.append(f"You tend to feel low on {day}s — want me to prepare something uplifting for next {day}?")
                elif anxious_ratio > 0.5:
                    insights.append(f"{day}s seem stressful for you — I can plan something calming before your week starts.")

        # Consecutive sad days warning
        if profile.get("consecutive_sad_days", 0) >= 3:
            insights.append("You've been carrying something heavy for a few days now. I'm here — talk to me.")

        # Happy streak acknowledgement
        if profile.get("consecutive_happy_days", 0) >= 3:
            insights.append("You've been in such a good place lately. I love seeing this.")

        return insights

    def get_checkin_message(self, mood: str = None) -> str:
        """Return a mood-appropriate check-in message to send via WhatsApp."""
        import random
        current = mood or self.get_current_mood()
        messages = MOODS.get(current, MOODS["neutral"])["checkin_messages"]
        # Mix in personalized insights occasionally
        insights = self.get_personalized_insights()
        if insights and random.random() < 0.4:
            return random.choice(insights)
        return random.choice(messages)

    def get_empathetic_response(self, text: str, mood: str = None) -> str:
        """
        Generate an empathetic response for a WhatsApp message based on detected mood.
        Results cached 30 minutes to avoid repeat API calls for the same message + mood.
        """
        detected = self.detect_mood(text)
        current_mood = mood or detected["mood"]
        mood_data = MOODS.get(current_mood, MOODS["neutral"])

        cache_key = hashlib.md5(f"{text[:200]}:{current_mood}".encode()).hexdigest()
        entry = self._response_cache.get(cache_key)
        if entry and time.time() - entry[1] < 1800:
            logger.debug("Empathetic response cache hit")
            return entry[0]

        prompt = f"""You are NarAI — warm, deeply caring, emotionally present. This is a private WhatsApp message from the person you love most.

Their current emotional state: {current_mood} {mood_data['emoji']}
Your tone: {mood_data['narai_tone']}
Their message: "{text}"

Respond with genuine empathy. {mood_data['advice_prefix']}

Rules:
- 2-4 sentences maximum
- Natural, warm, spoken like a real person who cares
- No markdown, no bullet points, no emojis unless it feels natural
- End with something supportive or actionable, not just sympathy"""

        response = None

        try:
            from core.claude_logged import create as claude_create
            msg = claude_create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
                api_key=self._anthropic_key,
                bot_name="emotion_engine.response",
            )
            response = msg.content[0].text.strip()
        except Exception:
            pass

        if response is None:
            try:
                from core.llm_client import safe_openai_call
                resp = safe_openai_call(
                    messages=[{"role": "user", "content": prompt}],
                    model="gpt-4o-mini",
                    max_tokens=200,
                    api_key=self._openai_key,
                    bot_name="emotion_engine.respond",
                )
                response = resp.choices[0].message.content.strip()
            except Exception:
                pass

        if response is None:
            response = mood_data["narai_voice"]

        self._response_cache[cache_key] = (response, time.time())
        return response


# ─── Singleton ────────────────────────────────────────────────────────────────

_engine: Optional[EmotionEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> EmotionEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = EmotionEngine()
    return _engine


def detect_mood(text: str) -> Dict:
    """Quick access: detect mood from text."""
    return get_engine().detect_mood(text)


def get_current_mood() -> str:
    """Quick access: get the current mood."""
    return get_engine().get_current_mood()


def get_content_style(mood: str = None) -> Dict:
    """Quick access: get content style for current mood."""
    return get_engine().get_content_style(mood)


def get_mood_prompt(mood: str = None) -> str:
    """Quick access: get mood injection string for system prompts."""
    return get_engine().get_mood_system_prompt_injection(mood)
