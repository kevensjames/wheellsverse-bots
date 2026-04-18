"""
core/autopilot.py — NarAI Master Autopilot Brain

This is the final piece. When autopilot is ON, NarAI runs herself
completely autonomously — no human input required.

Every hour she:
  1. Checks trending topics (TrendingEngine)
  2. Picks the best topic for each platform (FeedbackLoop + GoalTracker)
  3. Generates and publishes content (Repurposer + ContentCalendar)
  4. Checks for viral posts and multiplies them (ViralDetector)
  5. Monitors and replies to DMs (DMReplyEngine)
  6. Reviews ad spend and adjusts boosts (BudgetManager)
  7. Updates revenue dashboard (RevenueEngine)
  8. Adjusts her emotional state based on performance (PersonalityEngine)

Every day she:
  - Generates SEO blog posts for top keywords
  - Publishes 2 YouTube Shorts
  - Sends weekly newsletter (Mondays)
  - Reports goal progress to Telegram
  - Re-engages cold leads

This is full autonomy. NarAI is the employee who never sleeps.
"""

from __future__ import annotations
import json
import os
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

STATE_FILE = Path("data/autopilot.json")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

BRAND_NICHE = os.getenv("BRAND_NICHE", "AI tools, crypto, and passive income")


# ─── Autopilot State ──────────────────────────────────────────────────────────

class AutopilotState:
    def __init__(self):
        self.enabled = False
        self.mode = "full"     # full / content_only / monitor_only
        self.last_hourly_run = ""
        self.last_daily_run = ""
        self.hourly_count = 0
        self.daily_count = 0
        self.total_posts = 0
        self.total_leads = 0
        self.errors: List[str] = []
        self.log: List[Dict] = []

    def add_log(self, message: str, level: str = "INFO"):
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "level": level, "message": message}
        self.log.append(entry)
        if len(self.log) > 200:
            self.log = self.log[-200:]
        getattr(log, level.lower(), log.info)(f"[Autopilot] {message}")

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled, "mode": self.mode,
            "last_hourly_run": self.last_hourly_run,
            "last_daily_run": self.last_daily_run,
            "hourly_count": self.hourly_count,
            "daily_count": self.daily_count,
            "total_posts": self.total_posts,
            "total_leads": self.total_leads,
            "errors": self.errors[-20:],
            "log": self.log[-50:],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "AutopilotState":
        s = cls()
        s.enabled = d.get("enabled", False)
        s.mode = d.get("mode", "full")
        s.last_hourly_run = d.get("last_hourly_run", "")
        s.last_daily_run = d.get("last_daily_run", "")
        s.hourly_count = d.get("hourly_count", 0)
        s.daily_count = d.get("daily_count", 0)
        s.total_posts = d.get("total_posts", 0)
        s.total_leads = d.get("total_leads", 0)
        s.errors = d.get("errors", [])
        s.log = d.get("log", [])
        return s


# ─── Autopilot Engine ─────────────────────────────────────────────────────────

class AutopilotEngine:
    _instance: Optional["AutopilotEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._state = AutopilotState()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._load()

    @classmethod
    def get(cls) -> "AutopilotEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if STATE_FILE.exists():
            try:
                self._state = AutopilotState.from_dict(
                    json.loads(STATE_FILE.read_text())
                )
            except Exception as e:
                log.error(f"Autopilot load error: {e}")

    def _save(self):
        STATE_FILE.write_text(json.dumps(self._state.to_dict(), indent=2))

    # ── Controls ───────────────────────────────────────────────────────────────

    def enable(self, mode: str = "full"):
        self._state.enabled = True
        self._state.mode = mode
        self._save()
        self._start_loop()
        self._notify(f"🤖 NarAI Autopilot ENABLED — mode: {mode}\n\nShe's running on her own now.")
        self._state.add_log(f"Autopilot enabled — mode: {mode}")

    def disable(self):
        self._state.enabled = False
        self._save()
        self._notify("⏸️ NarAI Autopilot PAUSED — waiting for human input.")
        self._state.add_log("Autopilot disabled")

    def set_mode(self, mode: str):
        """full / content_only / monitor_only"""
        self._state.mode = mode
        self._save()

    # ── Hourly cycle ───────────────────────────────────────────────────────────

    def run_hourly(self) -> Dict:
        """The main hourly autopilot cycle."""
        s = self._state
        s.add_log("Hourly cycle starting")
        results: Dict[str, any] = {"started_at": datetime.now(timezone.utc).isoformat()}

        # ── 1. Refresh trending topics ────────────────────────────────────────
        try:
            from core.trending import TrendingEngine
            trend_result = TrendingEngine.get().refresh()
            s.add_log(f"Trends: {trend_result.get('total', 0)} topics found")
            results["trending"] = trend_result.get("total", 0)
        except Exception as e:
            s.add_log(f"Trending refresh failed: {e}", "WARNING")

        if s.mode == "monitor_only":
            s.last_hourly_run = datetime.now(timezone.utc).isoformat()
            s.hourly_count += 1
            self._save()
            return results

        # ── 2. Pick best topic and generate content ───────────────────────────
        try:
            topic = self._pick_best_topic()
            if topic:
                s.add_log(f"Topic selected: {topic}")
                results["topic"] = topic

                # Generate for priority platforms
                posted = self._publish_topic(topic)
                s.total_posts += len(posted)
                results["published"] = posted
                s.add_log(f"Published to {len(posted)} platforms")
        except Exception as e:
            s.add_log(f"Content generation failed: {e}", "ERROR")
            s.errors.append(f"{datetime.now().strftime('%H:%M')} content: {str(e)[:80]}")

        # ── 3. Process content calendar due items ────────────────────────────
        try:
            from core.content_calendar import ContentCalendar
            due_results = ContentCalendar.get().process_due()
            if due_results:
                s.add_log(f"Calendar: processed {len(due_results)} due items")
                results["calendar_processed"] = len(due_results)
        except Exception as e:
            s.add_log(f"Calendar processing failed: {e}", "WARNING")

        # ── 4. Budget check — auto-boost if high score post found ─────────────
        if s.mode == "full":
            try:
                from core.budget_manager import BudgetManager
                bm = BudgetManager.get()
                # BudgetManager's background loop handles this, just log status
                remaining = bm.today_remaining()
                results["ad_budget_remaining"] = remaining
            except Exception as e:
                s.add_log(f"Budget check failed: {e}", "WARNING")

        # ── 5. Adjust emotional state based on performance ────────────────────
        try:
            from core.feedback_loop import FeedbackLoop
            from core.personality import PersonalityEngine
            summary = FeedbackLoop.get().summary()
            avg_score = summary.get("avg_engagement_score", 0)
            PersonalityEngine.get().auto_adjust_state(avg_score)
            results["emotional_state"] = PersonalityEngine.get()._state.get("emotional_state")
        except Exception as e:
            s.add_log(f"Personality adjustment failed: {e}", "WARNING")

        # ── 6. Track analytics event ──────────────────────────────────────────
        try:
            from core.conversion_analytics import ConversionAnalytics
            ConversionAnalytics.get().flush()
        except Exception:
            pass

        s.last_hourly_run = datetime.now(timezone.utc).isoformat()
        s.hourly_count += 1
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        s.add_log(f"Hourly cycle complete — {s.hourly_count} total runs")
        return results

    # ── Daily cycle ────────────────────────────────────────────────────────────

    def run_daily(self) -> Dict:
        """Full daily tasks — runs at 08:00."""
        s = self._state
        s.add_log("Daily cycle starting")
        results: Dict = {"started_at": datetime.now(timezone.utc).isoformat()}

        # ── 1. Generate SEO blog post ─────────────────────────────────────────
        try:
            from core.seo import generate_seo_content
            from core.trending import TrendingEngine
            trend = TrendingEngine.get().get_best_for_content(niche="crypto")
            keyword = (trend["topic"][:50] if trend else "AI tools for passive income 2025")
            seo = generate_seo_content(keyword, niche="crypto")
            s.add_log(f"SEO post generated: '{keyword}' — score {seo.get('seo_score')}")
            results["seo_post"] = {"keyword": keyword, "score": seo.get("seo_score")}
        except Exception as e:
            s.add_log(f"SEO generation failed: {e}", "WARNING")

        # ── 2. Generate content calendar for today ────────────────────────────
        try:
            from core.content_calendar import ContentCalendar
            cal = ContentCalendar.get()
            pending = cal.get_pending()
            if len(pending) < 5:  # less than 5 posts queued — generate more
                cal.generate_week()
                s.add_log("Content calendar regenerated")
            results["queue_size"] = len(cal.get_pending())
        except Exception as e:
            s.add_log(f"Calendar generation failed: {e}", "WARNING")

        # ── 3. Publish 2 Shorts ────────────────────────────────────────────────
        try:
            from core.shorts_pipeline import ShortsPipeline
            for i in range(2):
                ShortsPipeline().run()
                s.total_posts += 1
            s.add_log("2 Shorts published")
            results["shorts"] = 2
        except Exception as e:
            s.add_log(f"Shorts pipeline failed: {e}", "WARNING")

        # ── 4. Re-engage cold leads ───────────────────────────────────────────
        try:
            from core.lead_capture import LeadCaptureEngine
            re_eng = LeadCaptureEngine.get().re_engage_cold_leads()
            if re_eng.get("re_engaged"):
                s.add_log(f"Re-engaged {re_eng['re_engaged']} cold leads")
            results["re_engaged"] = re_eng.get("re_engaged", 0)
        except Exception as e:
            s.add_log(f"Re-engagement failed: {e}", "WARNING")

        # ── 5. Revenue report ─────────────────────────────────────────────────
        try:
            from core.revenue import RevenueEngine
            RevenueEngine.get().send_daily_report()
            s.add_log("Revenue report sent")
        except Exception as e:
            s.add_log(f"Revenue report failed: {e}", "WARNING")

        # ── 6. Goal check + send report ───────────────────────────────────────
        try:
            from core.goal_tracker import GoalTracker
            GoalTracker.get().send_daily_report()
            s.add_log("Goal report sent")
        except Exception as e:
            s.add_log(f"Goal report failed: {e}", "WARNING")

        # ── 7. Keyword research for tomorrow ──────────────────────────────────
        try:
            from core.seo import research_keywords as _research_keywords
            _research_keywords("AI passive income 2025", niche="ai_tools", count=10)
            s.add_log("Keyword research complete")
        except Exception as e:
            s.add_log(f"Keyword research failed: {e}", "WARNING")

        s.last_daily_run = datetime.now(timezone.utc).isoformat()
        s.daily_count += 1
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        s.add_log(f"Daily cycle complete — {s.daily_count} total runs")
        return results

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _pick_best_topic(self) -> Optional[str]:
        """Pick the best topic to create content about right now."""
        # 1. Try trending engine
        try:
            from core.trending import TrendingEngine
            trend = TrendingEngine.get().get_best_for_content()
            if trend and trend.get("angle"):
                return trend["topic"]
        except Exception:
            pass

        # 2. Try feedback loop best topics
        try:
            from core.feedback_loop import FeedbackLoop
            topics = FeedbackLoop.get().get_best_topics(3)
            if topics:
                return topics[0]["topic"]
        except Exception:
            pass

        # 3. Goal-driven topic
        try:
            from core.goal_tracker import GoalTracker
            g = GoalTracker.get().get_priority_goal()
            if g:
                from core.goal_tracker import GOAL_STRATEGIES
                strat = GOAL_STRATEGIES.get(g.key, {})
                if strat.get("platforms"):
                    return f"{g.label} — how to achieve it with AI tools"
        except Exception:
            pass

        # 4. Fallback rotation
        FALLBACK_TOPICS = [
            "How to make passive income with AI tools in 2025",
            "Top 5 crypto coins to watch this week",
            "I automated my income — here's exactly how",
            "The AI tool that doubled my affiliate commissions",
            "Why most people fail at investing (and how to fix it)",
        ]
        import random
        return random.choice(FALLBACK_TOPICS)

    def _publish_topic(self, topic: str) -> List[str]:
        """Generate and publish topic to 2-3 platforms per hour."""
        published = []

        # Pick 2 platforms based on what performed best recently
        platforms_to_try = ["twitter", "threads", "telegram"]
        try:
            from core.personality import PersonalityEngine
            pp = PersonalityEngine.get()._state.get("platform_performance", {})
            if pp:
                sorted_platforms = sorted(pp, key=lambda k: pp[k]["avg"], reverse=True)
                platforms_to_try = sorted_platforms[:2] + ["telegram"]
        except Exception:
            pass

        for platform in platforms_to_try[:3]:
            try:
                from core.repurpose import repurpose_topic
                fmt_map = {
                    "twitter": "twitter_thread", "instagram": "instagram_caption",
                    "threads": "threads_post", "facebook": "facebook_post",
                    "linkedin": "linkedin_post", "telegram": "threads_post",
                }
                fmt = fmt_map.get(platform, "twitter_thread")
                result = repurpose_topic(topic, formats=[fmt])
                content = result.get("formats", {}).get(fmt, "")
                if not content:
                    continue

                # Publish
                if platform == "twitter":
                    from core.twitter import TwitterClient
                    TwitterClient().post_tweet(content[:280])
                elif platform == "threads":
                    from core.threads import post_text
                    post_text(content[:500])
                elif platform == "facebook":
                    from core.facebook import post_text as fb_post
                    fb_post(content)
                elif platform == "telegram":
                    import requests
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": TELEGRAM_CHAT, "text": content[:4096]},
                        timeout=10,
                    )

                published.append(platform)

                # Register in FeedbackLoop
                try:
                    from core.feedback_loop import FeedbackLoop
                    FeedbackLoop.get().register_post(
                        post_id=f"auto_{platform}_{int(time.time())}",
                        platform=platform, topic=topic, content_type="auto",
                    )
                except Exception:
                    pass

            except Exception as e:
                log.warning(f"Auto-publish to {platform} failed: {e}")

        return published

    def _notify(self, message: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
            return
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": message},
                timeout=5,
            )
        except Exception:
            pass

    # ── Background loop ────────────────────────────────────────────────────────

    def _start_loop(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="autopilot")
        self._thread.start()
        log.info("AutopilotEngine: loop started")

    def start(self):
        """Start the loop regardless of enabled state — will check internally."""
        self._stop_event.clear()
        self._start_loop()

    def stop(self):
        """Gracefully stop the autopilot background loop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log.info("AutopilotEngine: loop stopped")

    def _run(self):
        last_hourly_minute = -1
        last_daily_day = -1

        while not self._stop_event.is_set():
            try:
                now = datetime.now()

                # Hourly cycle — at :00 of every hour
                if now.minute == 0 and now.minute != last_hourly_minute:
                    last_hourly_minute = now.minute
                    if self._state.enabled:
                        self.run_hourly()

                # Daily cycle — at 08:05 every day
                if now.hour == 8 and now.minute == 5 and now.day != last_daily_day:
                    last_daily_day = now.day
                    if self._state.enabled and self._state.mode == "full":
                        self.run_daily()

            except Exception as e:
                log.error(f"Autopilot loop error: {e}")
            self._stop_event.wait(60)  # interruptible sleep

    # ── Status & summary ──────────────────────────────────────────────────────

    def status(self) -> Dict:
        s = self._state
        return {
            "enabled": s.enabled,
            "mode": s.mode,
            "last_hourly_run": s.last_hourly_run,
            "last_daily_run": s.last_daily_run,
            "hourly_cycles": s.hourly_count,
            "daily_cycles": s.daily_count,
            "total_posts_auto": s.total_posts,
            "recent_errors": s.errors[-5:],
        }

    def get_log(self, limit: int = 50) -> List[Dict]:
        return self._state.log[-limit:]

    def summary(self) -> Dict:
        return {
            **self.status(),
            "systems_active": self._count_active_systems(),
        }

    def _count_active_systems(self) -> Dict:
        """Show which engines are currently running."""
        active = {}
        for name, module, cls_name in [
            ("feedback_loop", "core.feedback_loop", "FeedbackLoop"),
            ("viral_detector", "core.viral_detector", "ViralDetector"),
            ("dm_reply", "core.dm_reply", "DMReplyEngine"),
            ("budget_manager", "core.budget_manager", "BudgetManager"),
            ("trending", "core.trending", "TrendingEngine"),
            ("goal_tracker", "core.goal_tracker", "GoalTracker"),
            ("content_calendar", "core.content_calendar", "ContentCalendar"),
        ]:
            try:
                mod = __import__(module, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                inst = cls._instance
                if inst and hasattr(inst, "_thread"):
                    active[name] = bool(inst._thread and inst._thread.is_alive())
                else:
                    active[name] = inst is not None
            except Exception:
                active[name] = False
        return active


# ─── Module-level convenience ─────────────────────────────────────────────────

def enable(mode: str = "full"):
    AutopilotEngine.get().enable(mode)


def disable():
    AutopilotEngine.get().disable()


def status() -> Dict:
    return AutopilotEngine.get().status()


def run_now() -> Dict:
    return AutopilotEngine.get().run_hourly()
