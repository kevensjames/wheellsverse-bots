"""
core/goal_tracker.py — NarAI Goal Awareness Engine

NarAI knows exactly what she's working toward and adjusts her content
strategy automatically to hit lagging goals. Every decision she makes
is informed by where she stands relative to her targets.
"""

from __future__ import annotations
import json, os, threading, logging, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DATA_FILE = Path("data/goals.json")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Goal definitions ──────────────────────────────────────────────────────────

DEFAULT_GOALS = {
    "twitter_followers": {
        "label": "Twitter Followers",
        "target": 10_000,
        "current": 0,
        "unit": "followers",
        "category": "growth",
        "priority": 2,
        "strategy": "Post 3x/day, engage with replies, use viral hooks",
    },
    "instagram_followers": {
        "label": "Instagram Followers",
        "target": 5_000,
        "current": 0,
        "unit": "followers",
        "category": "growth",
        "priority": 3,
        "strategy": "Daily Reels, story polls, follow-for-follow in niche",
    },
    "tiktok_followers": {
        "label": "TikTok Followers",
        "target": 10_000,
        "current": 0,
        "unit": "followers",
        "category": "growth",
        "priority": 2,
        "strategy": "2 Shorts/day, trending audio, hook in first 2 seconds",
    },
    "email_subscribers": {
        "label": "Email Subscribers",
        "target": 1_000,
        "current": 0,
        "unit": "subscribers",
        "category": "monetization",
        "priority": 1,   # highest priority — email = owned audience
        "strategy": "Lead magnet promotion, CTA in every post, landing page optimization",
    },
    "monthly_revenue": {
        "label": "Monthly Revenue",
        "target": 1_000,
        "current": 0.0,
        "unit": "USD",
        "category": "monetization",
        "priority": 1,
        "strategy": "Push affiliate links in top content, promote digital products, ConvertKit sequences",
    },
    "affiliate_clicks": {
        "label": "Affiliate Clicks (monthly)",
        "target": 500,
        "current": 0,
        "unit": "clicks",
        "category": "monetization",
        "priority": 2,
        "strategy": "Embed affiliate links in blog posts, Shorts descriptions, email sequences",
    },
    "viral_posts": {
        "label": "Viral Posts (monthly)",
        "target": 3,
        "current": 0,
        "unit": "posts",
        "category": "reach",
        "priority": 3,
        "strategy": "Post bold takes, track viral triggers, amplify top performers with ad spend",
    },
    "blog_posts": {
        "label": "Blog Posts Published (monthly)",
        "target": 20,
        "current": 0,
        "unit": "posts",
        "category": "content",
        "priority": 3,
        "strategy": "Run content pipeline daily, autopost to WordPress",
    },
    "shorts_published": {
        "label": "Shorts Published (monthly)",
        "target": 30,
        "current": 0,
        "unit": "videos",
        "category": "content",
        "priority": 2,
        "strategy": "2 Shorts/day via automated pipeline, re-post top performers",
    },
    "leads_captured": {
        "label": "Leads Captured (monthly)",
        "target": 100,
        "current": 0,
        "unit": "leads",
        "category": "monetization",
        "priority": 1,
        "strategy": "Lead magnet on every platform, WhatsApp opt-in flow, CTA on all Shorts",
    },
}

# ─── Content strategy adjustments per lagging goal ────────────────────────────

GOAL_STRATEGIES: Dict[str, Dict] = {
    "email_subscribers": {
        "focus": "lead_magnet",
        "prompt_inject": "Every post should mention the free AI Entrepreneur Blueprint — drive people to sign up.",
        "platforms": ["instagram", "tiktok", "twitter"],
        "content_type": "educational with CTA",
    },
    "monthly_revenue": {
        "focus": "affiliate",
        "prompt_inject": "Naturally include affiliate recommendations in content — Coinbase, Robinhood, Jasper AI.",
        "platforms": ["linkedin", "email", "youtube"],
        "content_type": "review / comparison / tutorial",
    },
    "twitter_followers": {
        "focus": "engagement",
        "prompt_inject": "Write punchy, controversial takes that make people want to follow for more.",
        "platforms": ["twitter"],
        "content_type": "hot takes and threads",
    },
    "tiktok_followers": {
        "focus": "virality",
        "prompt_inject": "Focus on hooks that stop the scroll — surprising facts, bold claims, fast pacing.",
        "platforms": ["tiktok", "instagram"],
        "content_type": "short-form video scripts",
    },
    "viral_posts": {
        "focus": "reach",
        "prompt_inject": "Create bold, shareable content — strong opinions, surprising stats, relatable frustrations.",
        "platforms": ["twitter", "tiktok", "instagram"],
        "content_type": "viral hooks and hot takes",
    },
    "affiliate_clicks": {
        "focus": "conversion",
        "prompt_inject": "Include clear, natural affiliate link placements with strong reasons to click.",
        "platforms": ["email", "youtube", "linkedin"],
        "content_type": "product recommendations",
    },
    "leads_captured": {
        "focus": "lead_gen",
        "prompt_inject": "Every piece of content ends with a clear lead magnet CTA — free blueprint, free resource.",
        "platforms": ["instagram", "tiktok", "whatsapp"],
        "content_type": "value + CTA posts",
    },
}


class Goal:
    def __init__(self, key: str, data: Dict):
        self.key = key
        self.label = data["label"]
        self.target = data["target"]
        self.current = data.get("current", 0)
        self.unit = data["unit"]
        self.category = data["category"]
        self.priority = data["priority"]
        self.strategy = data["strategy"]
        self.history: List[Dict] = data.get("history", [])  # [{ts, value}]
        self.deadline = data.get("deadline", "")
        self.active = data.get("active", True)

    @property
    def progress_pct(self) -> float:
        if self.target <= 0:
            return 100.0
        return round(min(100.0, (self.current / self.target) * 100), 1)

    @property
    def remaining(self):
        return max(0, self.target - self.current)

    @property
    def is_achieved(self) -> bool:
        return self.current >= self.target

    @property
    def urgency_score(self) -> float:
        """Higher = needs more attention. Priority × (1 - progress%)."""
        gap = 1.0 - (self.progress_pct / 100.0)
        return round(self.priority * gap * 10, 2)

    def update(self, value):
        self.current = value
        self.history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "value": value,
        })
        if len(self.history) > 90:   # keep 90 data points
            self.history = self.history[-90:]

    def increment(self, amount=1):
        self.update(self.current + amount)

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "label": self.label,
            "target": self.target,
            "current": self.current,
            "unit": self.unit,
            "category": self.category,
            "priority": self.priority,
            "strategy": self.strategy,
            "history": self.history[-30:],  # last 30 for API response
            "deadline": self.deadline,
            "active": self.active,
            "progress_pct": self.progress_pct,
            "remaining": self.remaining,
            "is_achieved": self.is_achieved,
            "urgency_score": self.urgency_score,
        }


# ─── Goal Tracker ──────────────────────────────────────────────────────────────

class GoalTracker:
    _instance: Optional["GoalTracker"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._goals: Dict[str, Goal] = {}
        self._load()
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def get(cls) -> "GoalTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        saved: Dict = {}
        if DATA_FILE.exists():
            try:
                saved = json.loads(DATA_FILE.read_text())
            except Exception as e:
                log.error(f"GoalTracker load error: {e}")

        for key, default in DEFAULT_GOALS.items():
            merged = {**default, **saved.get(key, {})}
            self._goals[key] = Goal(key, merged)

        # Load any custom goals added at runtime
        for key, data in saved.items():
            if key not in self._goals:
                self._goals[key] = Goal(key, data)

        log.info(f"GoalTracker: loaded {len(self._goals)} goals")

    def _save(self):
        try:
            DATA_FILE.write_text(json.dumps(
                {key: g.to_dict() for key, g in self._goals.items()},
                indent=2
            ))
        except Exception as e:
            log.error(f"GoalTracker save error: {e}")

    # ── Goal management ────────────────────────────────────────────────────────

    def update(self, goal_key: str, value):
        """Set an absolute value for a goal (e.g., current follower count)."""
        if goal_key not in self._goals:
            log.warning(f"GoalTracker: unknown goal '{goal_key}'")
            return
        old = self._goals[goal_key].current
        self._goals[goal_key].update(value)
        self._save()

        # Notify on achievement
        if not old >= self._goals[goal_key].target <= value:
            if self._goals[goal_key].is_achieved:
                self._notify_achievement(goal_key)

    def increment(self, goal_key: str, amount: int = 1):
        """Increment a counter goal (e.g., +1 blog post published)."""
        if goal_key in self._goals:
            self._goals[goal_key].increment(amount)
            self._save()

    def set_target(self, goal_key: str, target):
        if goal_key in self._goals:
            self._goals[goal_key].target = target
            self._save()

    def add_goal(self, key: str, label: str, target, unit: str,
                 category: str = "custom", priority: int = 2, strategy: str = ""):
        self._goals[key] = Goal(key, {
            "label": label, "target": target, "current": 0,
            "unit": unit, "category": category, "priority": priority,
            "strategy": strategy,
        })
        self._save()

    def reset_monthly_goals(self):
        """Call at start of each month to reset count-based goals."""
        monthly_keys = ["viral_posts", "blog_posts", "shorts_published",
                        "affiliate_clicks", "leads_captured", "monthly_revenue"]
        for key in monthly_keys:
            if key in self._goals:
                self._goals[key].update(0)
        self._save()
        log.info("GoalTracker: monthly goals reset")

    # ── Intelligence ───────────────────────────────────────────────────────────

    def get_priority_goal(self) -> Optional[Goal]:
        """Returns the single most urgent goal that needs attention."""
        active = [g for g in self._goals.values() if g.active and not g.is_achieved]
        if not active:
            return None
        return max(active, key=lambda g: g.urgency_score)

    def get_lagging_goals(self, threshold_pct: float = 50.0) -> List[Goal]:
        """Goals below threshold% progress — needs strategic focus."""
        return [g for g in self._goals.values()
                if g.active and not g.is_achieved and g.progress_pct < threshold_pct]

    def get_goal_prompt(self) -> str:
        """
        Returns a context block to inject into GPT content generation calls.
        NarAI uses this to make every piece of content serve her goals.
        """
        priority = self.get_priority_goal()
        lagging = self.get_lagging_goals(40.0)

        lines = ["=== NARAI CURRENT GOALS ==="]

        if priority:
            strat = GOAL_STRATEGIES.get(priority.key, {})
            lines.append(f"\nTOP PRIORITY: {priority.label}")
            lines.append(f"  Progress: {priority.current} / {priority.target} {priority.unit} ({priority.progress_pct}%)")
            lines.append(f"  Strategy: {priority.strategy}")
            if strat.get("prompt_inject"):
                lines.append(f"  CONTENT DIRECTIVE: {strat['prompt_inject']}")

        if lagging:
            lines.append("\nLAGGING GOALS (need content support):")
            for g in lagging[:3]:  # top 3 lagging
                lines.append(f"  - {g.label}: {g.progress_pct}% ({g.current}/{g.target})")
                strat = GOAL_STRATEGIES.get(g.key, {})
                if strat.get("prompt_inject"):
                    lines.append(f"    → {strat['prompt_inject']}")

        # Top performing goals for context
        achieved = [g for g in self._goals.values() if g.is_achieved]
        if achieved:
            lines.append(f"\nACHIEVED: {', '.join(g.label for g in achieved[:3])}")

        return "\n".join(lines)

    def get_content_directive(self, platform: str = "", topic: str = "") -> str:
        """
        Returns the most relevant content directive based on lagging goals
        and the platform/topic context.
        """
        priority = self.get_priority_goal()
        if not priority:
            return "Create high-quality content that builds the WheellsVerse audience."

        strat = GOAL_STRATEGIES.get(priority.key, {})

        # Check if this platform is relevant to priority goal
        if platform and strat.get("platforms") and platform not in strat["platforms"]:
            # Fall back to second most urgent
            active = sorted(
                [g for g in self._goals.values() if g.active and not g.is_achieved],
                key=lambda g: g.urgency_score, reverse=True
            )
            for g in active[1:4]:
                s = GOAL_STRATEGIES.get(g.key, {})
                if not s.get("platforms") or platform in s.get("platforms", []):
                    return s.get("prompt_inject", priority.strategy)

        return strat.get("prompt_inject", priority.strategy)

    # ── Reporting ──────────────────────────────────────────────────────────────

    def daily_report(self) -> str:
        lines = [f"📊 NarAI Daily Goal Report — {datetime.now().strftime('%b %d')}"]
        lines.append("")

        categories: Dict[str, List[Goal]] = {}
        for g in self._goals.values():
            categories.setdefault(g.category, []).append(g)

        for cat, goals in sorted(categories.items()):
            lines.append(f"── {cat.upper()} ──")
            for g in sorted(goals, key=lambda x: x.priority):
                bar = self._progress_bar(g.progress_pct)
                status = "✅" if g.is_achieved else "🔥" if g.progress_pct >= 70 else "⚠️" if g.progress_pct >= 30 else "❌"
                lines.append(f"{status} {g.label}: {g.current}/{g.target} {g.unit} {bar} {g.progress_pct}%")

        priority = self.get_priority_goal()
        if priority:
            lines.append(f"\n🎯 Focus today: {priority.label}")
            lines.append(f"   {GOAL_STRATEGIES.get(priority.key, {}).get('prompt_inject', priority.strategy)}")

        return "\n".join(lines)

    def _progress_bar(self, pct: float, width: int = 8) -> str:
        filled = int(width * pct / 100)
        return "[" + "█" * filled + "░" * (width - filled) + "]"

    def _notify_achievement(self, goal_key: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
            return
        g = self._goals[goal_key]
        msg = f"🏆 NarAI Goal Achieved!\n\n{g.label}: {g.current} {g.unit}\nTarget was {g.target}. We hit it! 🎉"
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": msg},
                timeout=5
            )
        except Exception:
            pass

    def send_daily_report(self):
        report = self.daily_report()
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT, "text": report},
                    timeout=5
                )
            except Exception:
                pass

    # ── Background loop ────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("GoalTracker: background loop started")

    def _run(self):
        import time
        last_report_day = -1
        while True:
            try:
                now = datetime.now()
                # Send daily report at 07:00
                if now.hour == 7 and now.minute < 5 and now.day != last_report_day:
                    self.send_daily_report()
                    last_report_day = now.day
                # Reset monthly goals on the 1st at midnight
                if now.day == 1 and now.hour == 0 and now.minute < 5:
                    self.reset_monthly_goals()
            except Exception as e:
                log.error(f"GoalTracker loop error: {e}")
            time.sleep(300)  # check every 5 min

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        goals_data = {k: g.to_dict() for k, g in self._goals.items()}
        priority = self.get_priority_goal()
        lagging = self.get_lagging_goals()
        achieved = [g for g in self._goals.values() if g.is_achieved]
        return {
            "total_goals": len(self._goals),
            "achieved": len(achieved),
            "in_progress": len([g for g in self._goals.values() if not g.is_achieved and g.active]),
            "priority_goal": priority.key if priority else None,
            "lagging_count": len(lagging),
            "overall_progress_pct": round(
                sum(g.progress_pct for g in self._goals.values()) / max(len(self._goals), 1), 1
            ),
            "goals": goals_data,
        }


# ─── Module-level convenience ─────────────────────────────────────────────────

def get_goal_prompt() -> str:
    return GoalTracker.get().get_goal_prompt()

def increment(goal_key: str, amount: int = 1):
    GoalTracker.get().increment(goal_key, amount)

def update_goal(goal_key: str, value):
    GoalTracker.get().update(goal_key, value)
