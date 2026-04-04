#!/usr/bin/env python3
"""
core/viral_detector.py
─────────────────────────────────────────────────────────────────────────────
Viral Detector — monitors all published posts in real-time.

When a post's engagement spikes 3× above the platform average it:
  1. Flags the post as VIRAL in FeedbackLoop
  2. Fires a content multiplication event — creates 5 variations
  3. Schedules those variations to all platforms immediately
  4. Sends an alert to Telegram + Slack

How it works:
  • ViralDetector runs as a background thread (check every 10 min)
  • Calls EngagementPoller data via FeedbackLoop
  • Triggers the Orchestrator to run the viral_multiplier pipeline
  • Tracks which posts already triggered so it doesn't spam

Storage: data/viral_events.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR    = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
EVENTS_FILE = DATA_DIR / "viral_events.json"

logger = logging.getLogger("viral_detector")

CHECK_INTERVAL_SECONDS = 600   # 10 minutes
VIRAL_MULTIPLIER       = 3.0   # 3× platform avg = viral
MAX_VARIATIONS         = 5     # how many spin-off posts to create
COOLDOWN_HOURS         = 4     # don't re-trigger same post for 4h


class ViralEvent:
    """Records a viral detection event."""

    def __init__(self, post_id: str, topic: str, platform: str,
                 score: float, avg_score: float):
        self.post_id    = post_id
        self.topic      = topic
        self.platform   = platform
        self.score      = score
        self.avg_score  = avg_score
        self.multiplier = round(score / max(avg_score, 1), 2)
        self.detected_at = datetime.now().isoformat()
        self.variations_created = 0
        self.alert_sent = False

    def to_dict(self) -> Dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: Dict) -> "ViralEvent":
        e = cls(d["post_id"], d["topic"], d["platform"],
                d.get("score", 0), d.get("avg_score", 0))
        e.detected_at         = d.get("detected_at", e.detected_at)
        e.variations_created  = d.get("variations_created", 0)
        e.alert_sent          = d.get("alert_sent", False)
        return e


class ViralDetector:
    """
    Background service that watches FeedbackLoop for viral posts and
    triggers content multiplication.
    """

    _instance: Optional["ViralDetector"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._events: Dict[str, ViralEvent] = {}
        self._triggered: Set[str] = set()
        self._running   = False
        self._thread: Optional[threading.Thread] = None
        self._load()

    @classmethod
    def get(cls) -> "ViralDetector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if EVENTS_FILE.exists():
            try:
                raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
                self._events = {
                    eid: ViralEvent.from_dict(d)
                    for eid, d in raw.get("events", {}).items()
                }
                self._triggered = set(raw.get("triggered", []))
                logger.info(f"[ViralDetector] Loaded {len(self._events)} viral events")
            except Exception as e:
                logger.warning(f"[ViralDetector] Load error: {e}")

    def _save(self):
        try:
            EVENTS_FILE.write_text(json.dumps({
                "events":    {eid: e.to_dict() for eid, e in self._events.items()},
                "triggered": list(self._triggered),
            }, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[ViralDetector] Save error: {e}")

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="ViralDetector"
        )
        self._thread.start()
        logger.info(f"[ViralDetector] Started — checking every {CHECK_INTERVAL_SECONDS}s")

    def stop(self):
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self):
        while self._running:
            try:
                self._check_for_viral()
            except Exception as e:
                logger.error(f"[ViralDetector] Check error: {e}")
            time.sleep(CHECK_INTERVAL_SECONDS)

    def _check_for_viral(self):
        from core.feedback_loop import FeedbackLoop
        loop   = FeedbackLoop.get()
        viral  = loop.get_viral_posts(hours=24)

        for record in viral:
            if record.post_id in self._triggered:
                continue
            # Cooldown check
            if record.post_id in self._events:
                last = datetime.fromisoformat(
                    self._events[record.post_id].detected_at
                )
                if datetime.now() - last < timedelta(hours=COOLDOWN_HOURS):
                    continue

            avg = loop._platform_avg_score(record.platform, exclude=record.post_id)
            event = ViralEvent(record.post_id, record.topic,
                               record.platform, record.score, avg)
            self._events[record.post_id] = event
            self._triggered.add(record.post_id)

            logger.info(
                f"[ViralDetector] 🔥 VIRAL → {record.topic[:50]} "
                f"({record.platform}) score={record.score:.0f} "
                f"({event.multiplier}× avg)"
            )

            # Fire content multiplication
            self._multiply(event, record.topic, record.niche)
            # Send alert
            self._send_alert(event)

        self._save()

    # ── Content multiplication ─────────────────────────────────────────────────

    def _multiply(self, event: ViralEvent, topic: str, niche: str):
        """
        Generate MAX_VARIATIONS spin-off posts from the viral topic
        and publish them to all platforms immediately.
        """
        try:
            from core.orchestrator import Orchestrator
            orch = Orchestrator()

            # Determine best bot for this niche
            from core.feedback_loop import FeedbackLoop
            best_bot = FeedbackLoop.get().get_best_bot(niche) or "01_content_generator"

            logger.info(f"[ViralDetector] Multiplying '{topic[:40]}' × {MAX_VARIATIONS}")

            angles = self._generate_angles(topic)
            count  = 0

            for angle in angles[:MAX_VARIATIONS]:
                try:
                    result = orch.run_bot(
                        "marketing", "01_content_generator",
                        topic=angle,
                        content_type="social_post",
                    )
                    if result:
                        count += 1
                        logger.info(f"[ViralDetector] Variation {count}: {angle[:50]}")
                except Exception as e:
                    logger.warning(f"[ViralDetector] Variation failed: {e}")

            event.variations_created = count
            self._save()

        except Exception as e:
            logger.error(f"[ViralDetector] Multiply error: {e}")

    def _generate_angles(self, topic: str) -> List[str]:
        """Use GPT to generate MAX_VARIATIONS spin-off angles from a viral topic."""
        try:
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                messages=[{
                    "role": "user",
                    "content": (
                        f"A post about '{topic}' just went viral. "
                        f"Generate {MAX_VARIATIONS} different angle variations on this topic "
                        "that we can publish immediately to capitalize on the momentum. "
                        "Each should be a unique angle, hook, or perspective. "
                        "Return ONLY a JSON array of strings, no explanation."
                    )
                }],
                max_tokens=400,
                temperature=0.85,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("["):
                angles = json.loads(raw)
                return [str(a) for a in angles[:MAX_VARIATIONS]]
        except Exception as e:
            logger.warning(f"[ViralDetector] GPT angle generation failed: {e}")

        # Fallback: simple manual variations
        return [
            f"Why everyone is talking about {topic}",
            f"The truth about {topic} (no one tells you this)",
            f"{topic} — my honest take after doing it myself",
            f"How to use {topic} to make money in 2025",
            f"3 things {topic} taught me about building income online",
        ]

    # ── Alerts ────────────────────────────────────────────────────────────────

    def _send_alert(self, event: ViralEvent):
        """Send viral alert to Telegram and Slack."""
        msg = (
            f"🔥 VIRAL DETECTED!\n\n"
            f"📝 Topic: {event.topic}\n"
            f"📱 Platform: {event.platform}\n"
            f"📈 Score: {event.score:.0f} ({event.multiplier}× avg)\n"
            f"⚡ Action: Creating {MAX_VARIATIONS} variations now\n"
            f"🕐 {event.detected_at[:16]}"
        )

        # Telegram
        try:
            import requests as _req
            token   = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat_id:
                _req.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
                event.alert_sent = True
        except Exception as e:
            logger.debug(f"[ViralDetector] Telegram alert failed: {e}")

        # Slack
        try:
            import requests as _req
            slack_url = os.getenv("SLACK_WEBHOOK_URL")
            if slack_url and "hooks.slack.com" in slack_url:
                _req.post(slack_url, json={"text": msg}, timeout=10)
        except Exception as e:
            logger.debug(f"[ViralDetector] Slack alert failed: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_events(self, hours: int = 24) -> List[ViralEvent]:
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            e for e in self._events.values()
            if datetime.fromisoformat(e.detected_at) >= cutoff
        ]

    def check_now(self) -> List[ViralEvent]:
        """Manually trigger a viral check. Returns new viral events found."""
        before = set(self._triggered)
        self._check_for_viral()
        new_ids = set(self._triggered) - before
        return [self._events[eid] for eid in new_ids if eid in self._events]

    def summary(self) -> Dict:
        events = list(self._events.values())
        return {
            "total_viral_events":     len(events),
            "last_24h":               len(self.get_events(24)),
            "total_variations_made":  sum(e.variations_created for e in events),
            "recent": [
                {"topic": e.topic, "platform": e.platform,
                 "multiplier": e.multiplier, "detected_at": e.detected_at[:16]}
                for e in sorted(events, key=lambda x: x.detected_at, reverse=True)[:5]
            ]
        }


def get_viral_detector() -> ViralDetector:
    return ViralDetector.get()
