"""
core/content_calendar.py — Content Calendar & Auto-Queue

NarAI plans her entire content week autonomously:
  - Generates a 7-day content calendar based on FeedbackLoop + GoalTracker
  - Queues posts per platform with optimal timing
  - Auto-publishes queued content on schedule
  - Tracks what was published vs pending
  - Adjusts timing based on platform engagement data

This is NarAI's brain for "what do I post today and when?"
"""

from __future__ import annotations
import json
import os
import threading
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

QUEUE_FILE = Path("data/content_queue.json")
CALENDAR_FILE = Path("data/content_calendar.json")

BRAND_NICHE = os.getenv("BRAND_NICHE", "AI tools, crypto, and passive income")
CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")

# ─── Optimal posting times per platform ───────────────────────────────────────

OPTIMAL_TIMES: Dict[str, List[str]] = {
    "twitter": ["08:00", "12:00", "17:00", "21:00"],
    "instagram": ["09:00", "15:00", "20:00"],
    "tiktok": ["07:00", "12:00", "19:00", "21:00"],
    "linkedin": ["08:00", "12:00", "17:30"],
    "threads": ["09:00", "14:00", "20:00"],
    "facebook": ["09:00", "13:00", "17:00"],
    "pinterest": ["20:00", "21:00", "23:00"],
    "youtube": ["09:00", "15:00"],
    "telegram": ["09:00", "18:00"],
}

# ─── Content themes per day of week ───────────────────────────────────────────

WEEKLY_THEMES = {
    0: {"theme": "Monday Motivation", "type": "motivational", "topics": ["passive income mindset", "wealth building"]},
    1: {"theme": "Tutorial Tuesday", "type": "educational", "topics": ["AI tools tutorial", "crypto how-to"]},
    2: {"theme": "Win Wednesday", "type": "social_proof", "topics": ["results", "success stories", "case studies"]},
    3: {"theme": "Tip Thursday", "type": "tips", "topics": ["quick tips", "hacks", "shortcuts"]},
    4: {"theme": "Finance Friday", "type": "financial", "topics": ["investing", "crypto", "income streams"]},
    5: {"theme": "Strategy Saturday", "type": "deep_dive", "topics": ["affiliate strategy", "SEO", "content strategy"]},
    6: {"theme": "Sunday Reflection", "type": "reflective", "topics": ["lessons learned", "what's working", "week ahead"]},
}


# ─── Queue item ───────────────────────────────────────────────────────────────

class QueueItem:
    def __init__(self, platform: str, content_type: str, topic: str,
                 scheduled_time: str, content: str = "", status: str = "pending",
                 item_id: str = "", account: str = "main"):
        import uuid
        self.id = item_id or str(uuid.uuid4())[:8]
        self.platform = platform
        self.account = account  # "main" / "shop" / etc. — routes to per-account creds
        self.content_type = content_type
        self.topic = topic
        self.scheduled_time = scheduled_time
        self.content = content
        self.status = status   # pending / published / failed / skipped
        self.published_at = ""
        self.result = {}
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "platform": self.platform, "account": self.account,
            "content_type": self.content_type, "topic": self.topic,
            "scheduled_time": self.scheduled_time, "content": self.content,
            "status": self.status, "published_at": self.published_at,
            "result": self.result, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "QueueItem":
        item = cls(d["platform"], d["content_type"], d["topic"],
                   d["scheduled_time"], d.get("content", ""),
                   d.get("status", "pending"), d.get("id", ""),
                   d.get("account", "main"))  # default for legacy queue items
        item.published_at = d.get("published_at", "")
        item.result = d.get("result", {})
        item.created_at = d.get("created_at", "")
        return item


# ─── Content Calendar ─────────────────────────────────────────────────────────

class ContentCalendar:
    _instance: Optional["ContentCalendar"] = None
    _lock = threading.Lock()

    def __init__(self):
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._queue: List[QueueItem] = []
        self._calendar: Dict = {}
        self._thread: Optional[threading.Thread] = None
        self._load()

    @classmethod
    def get(cls) -> "ContentCalendar":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if QUEUE_FILE.exists():
            try:
                raw = json.loads(QUEUE_FILE.read_text())
                self._queue = [QueueItem.from_dict(i) for i in raw]
            except Exception as e:
                log.error(f"Queue load error: {e}")
        if CALENDAR_FILE.exists():
            try:
                self._calendar = json.loads(CALENDAR_FILE.read_text())
            except Exception:
                pass

    def _save_queue(self):
        QUEUE_FILE.write_text(json.dumps([i.to_dict() for i in self._queue], indent=2))

    def _save_calendar(self):
        CALENDAR_FILE.write_text(json.dumps(self._calendar, indent=2))

    # ── Calendar generation ────────────────────────────────────────────────────

    def generate_week(self, platforms: List = None, start_date: str = "") -> Dict:
        """Generate a full 7-day content calendar with queue items.

        `platforms` accepts either:
          - List[str]              — legacy form, posts go to account="main"
          - List[Tuple[str, str]]  — (platform, account) pairs, e.g. ("instagram","shop")
          - Mixed, e.g. ["twitter", ("instagram", "main"), ("instagram", "shop")]
        """
        if not platforms:
            platforms = ["twitter", "instagram", "tiktok", "linkedin", "threads", "facebook"]

        # Normalize to (platform, account) tuples
        targets: List[tuple] = [
            (p, "main") if isinstance(p, str) else (p[0], p[1]) for p in platforms
        ]

        best_topics = []
        try:
            from core.feedback_loop import FeedbackLoop
            best_topics = [t["topic"] for t in FeedbackLoop.get().get_best_topics(7)]
        except Exception:
            pass

        goal_directive = ""
        try:
            from core.goal_tracker import GoalTracker
            goal_directive = GoalTracker.get().get_content_directive()
        except Exception:
            pass

        from datetime import date as _date
        start = datetime.now(timezone.utc).date()
        if start_date:
            try:
                start = _date.fromisoformat(start_date)
            except Exception:
                pass

        calendar: Dict = {}
        new_items: List[QueueItem] = []
        existing_keys = {
            (i.platform, getattr(i, "account", "main"), i.topic, i.scheduled_time[:10])
            for i in self._queue
        }

        for day_offset in range(7):
            day = start + timedelta(days=day_offset)
            dow = day.weekday()
            theme_info = WEEKLY_THEMES[dow]

            if best_topics and day_offset < len(best_topics):
                topic = best_topics[day_offset]
            else:
                topic = theme_info["topics"][day_offset % len(theme_info["topics"])]

            day_str = day.isoformat()
            calendar[day_str] = {
                "theme": theme_info["theme"],
                "topic": topic,
                "content_type": theme_info["type"],
                "goal_directive": goal_directive,
                "platforms": {},
            }

            for platform, account in targets:
                times = OPTIMAL_TIMES.get(platform, ["10:00"])
                post_time = times[day_offset % len(times)]
                scheduled = f"{day_str}T{post_time}:00+00:00"

                key = (platform, account, topic, day_str)
                if key not in existing_keys:
                    item = QueueItem(platform, theme_info["type"], topic, scheduled,
                                     account=account)
                    new_items.append(item)
                    existing_keys.add(key)
                    # Calendar key: bare platform for main (back-compat), "platform@account" else
                    cal_key = platform if account == "main" else f"{platform}@{account}"
                    calendar[day_str]["platforms"][cal_key] = {
                        "scheduled": scheduled, "queue_id": item.id, "status": "pending",
                        "account": account,
                    }

        with self._lock:
            self._queue.extend(new_items)
            self._calendar.update(calendar)
            self._save_queue()
            self._save_calendar()

        return {
            "status": "generated",
            "days": len(calendar),
            "items_queued": len(new_items),
            "targets": targets,
            "calendar": calendar,
        }

    # ── Queue management ───────────────────────────────────────────────────────

    def add(self, platform: str, topic: str, content: str = "",
            scheduled_time: str = "", content_type: str = "post",
            account: str = "main") -> QueueItem:
        if not scheduled_time:
            times = OPTIMAL_TIMES.get(platform, ["10:00"])
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
            scheduled_time = f"{tomorrow.isoformat()}T{times[0]}:00+00:00"
        item = QueueItem(platform, content_type, topic, scheduled_time, content,
                         account=account)
        with self._lock:
            self._queue.append(item)
            self._save_queue()
        return item

    def remove(self, item_id: str) -> bool:
        with self._lock:
            before = len(self._queue)
            self._queue = [i for i in self._queue if i.id != item_id]
            self._save_queue()
            return len(self._queue) < before

    def get_pending(self, platform: str = "") -> List[QueueItem]:
        items = [i for i in self._queue if i.status == "pending"]
        if platform:
            items = [i for i in items if i.platform == platform]
        return sorted(items, key=lambda x: x.scheduled_time)

    def get_due(self) -> List[QueueItem]:
        now = datetime.now(timezone.utc)
        due = []
        for item in self._queue:
            if item.status != "pending":
                continue
            try:
                sched = datetime.fromisoformat(item.scheduled_time.replace("Z", "+00:00"))
                if sched <= now:
                    due.append(item)
            except Exception:
                pass
        return due

    def mark_published(self, item_id: str, result: Dict = None):
        for item in self._queue:
            if item.id == item_id:
                item.status = "published"
                item.published_at = datetime.now(timezone.utc).isoformat()
                item.result = result or {}
                break
        self._save_queue()

    def mark_failed(self, item_id: str, error: str = ""):
        for item in self._queue:
            if item.id == item_id:
                item.status = "failed"
                item.result = {"error": error}
                break
        self._save_queue()

    # ── Content generation ─────────────────────────────────────────────────────

    def generate_content_for(self, item: QueueItem) -> str:
        if item.content:
            return item.content
        try:
            from core.repurpose import repurpose_topic
            fmt = _platform_format(item.platform)
            result = repurpose_topic(item.topic, formats=[fmt])
            item.content = result.get("formats", {}).get(fmt, "")
        except Exception as e:
            log.warning(f"Repurpose failed for {item.id}: {e}")

        if not item.content:
            try:
                from core.personality import get_prompt
                from openai import OpenAI
                system = get_prompt(item.platform, item.topic)
                resp = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "")).chat.completions.create(
                    model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": f"Write a {item.platform} post about: {item.topic}"},
                    ],
                    max_tokens=300, temperature=0.8,
                )
                item.content = resp.choices[0].message.content.strip()
            except Exception as e:
                log.error(f"Fallback content gen failed: {e}")
                item.content = f"{item.topic}\n\nLearn more: {CTA_URL}"

        self._save_queue()
        return item.content

    # ── Process due items ─────────────────────────────────────────────────────

    def process_due(self) -> List[Dict]:
        due = self.get_due()
        results = []
        for item in due:
            self.generate_content_for(item)
            result = self._publish(item)
            results.append({"id": item.id, "platform": item.platform,
                            "topic": item.topic[:40], **result})
        return results

    def _publish(self, item: QueueItem) -> Dict:
        try:
            p = item.platform.lower()
            account = getattr(item, "account", "main")  # legacy items lack the field
            if p == "twitter":
                from core.twitter import TwitterClient
                r = TwitterClient().post_tweet(item.content[:280])
            elif p == "facebook":
                from core.facebook import get_facebook
                r = get_facebook(account).post(item.content)
            elif p == "instagram":
                # IG requires an image — client auto-generates via DALL-E + Pillow
                from core.instagram import get_instagram
                r = get_instagram(account).post(item.content)
            elif p == "linkedin":
                from core.linkedin import get_linkedin
                r = get_linkedin().post(text=item.content)
            elif p == "threads":
                from core.threads import post_text
                r = post_text(item.content[:500])
            elif p == "telegram":
                import requests
                resp = requests.post(
                    f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN', '')}/sendMessage",
                    json={"chat_id": os.getenv("TELEGRAM_CHAT_ID", ""), "text": item.content},
                    timeout=10,
                )
                r = {"status": "published" if resp.ok else "failed"}
            else:
                r = {"status": "skipped", "reason": f"{p} requires media upload"}

            self.mark_published(item.id, r)
            return {"status": "published"}
        except Exception as e:
            self.mark_failed(item.id, str(e))
            return {"status": "failed", "error": str(e)}

    # ── Background loop ────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="content-calendar")
        self._thread.start()
        log.info("ContentCalendar: started")

    def _run(self):
        import time
        last_gen_day = -1
        while True:
            try:
                due = self.get_due()
                if due:
                    self.process_due()
                now = datetime.now()
                if now.weekday() == 6 and now.hour == 18 and now.day != last_gen_day:
                    self.generate_week()
                    last_gen_day = now.day
                # Prune old published items
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                before = len(self._queue)
                self._queue = [
                    i for i in self._queue
                    if not (i.status in ("published", "failed")
                           and i.published_at
                           and datetime.fromisoformat(
                               i.published_at.replace("Z", "+00:00")) < cutoff)
                ]
                if len(self._queue) < before:
                    self._save_queue()
            except Exception as e:
                log.error(f"ContentCalendar loop error: {e}")
            time.sleep(300)

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        pending = [i for i in self._queue if i.status == "pending"]
        published = [i for i in self._queue if i.status == "published"]
        failed = [i for i in self._queue if i.status == "failed"]
        due_now = self.get_due()

        by_platform: Dict[str, int] = {}
        for i in pending:
            by_platform[i.platform] = by_platform.get(i.platform, 0) + 1

        next_item = None
        if pending:
            ni = sorted(pending, key=lambda x: x.scheduled_time)[0]
            next_item = {"id": ni.id, "platform": ni.platform,
                        "topic": ni.topic, "scheduled": ni.scheduled_time}

        return {
            "total_queued": len(self._queue),
            "pending": len(pending),
            "published": len(published),
            "failed": len(failed),
            "due_now": len(due_now),
            "pending_by_platform": by_platform,
            "next_item": next_item,
            "calendar_days": len(self._calendar),
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _platform_format(platform: str) -> str:
    return {
        "twitter": "twitter_thread", "instagram": "instagram_caption",
        "tiktok": "tiktok_caption", "linkedin": "linkedin_post",
        "threads": "threads_post", "facebook": "facebook_post",
        "pinterest": "pinterest_pin", "youtube": "youtube_script",
    }.get(platform.lower(), "twitter_thread")


# ─── Module-level convenience ─────────────────────────────────────────────────

def get_summary() -> Dict:
    return ContentCalendar.get().summary()


def queue_post(platform: str, topic: str, content: str = "",
               scheduled_time: str = "", account: str = "main") -> Dict:
    return ContentCalendar.get().add(
        platform, topic, content, scheduled_time, account=account
    ).to_dict()
