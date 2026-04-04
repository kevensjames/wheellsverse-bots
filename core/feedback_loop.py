#!/usr/bin/env python3
"""
core/feedback_loop.py
─────────────────────────────────────────────────────────────────────────────
Self-Learning Feedback Loop — the intelligence layer that makes every bot
smarter over time.

How it works:
  1. Every time a bot publishes content, it registers a Post record here.
  2. Platforms (Twitter, Instagram, Facebook, etc.) push engagement updates
     back via update_engagement().
  3. FeedbackLoop scores every post (views × 1 + clicks × 5 + shares × 8 +
     revenue × 20) and builds a knowledge base of what works.
  4. Bots call get_best_topic(niche) / get_best_time(platform) before running
     to pick the highest-probability angle instead of guessing randomly.
  5. Decision engine queries is_underperforming() to decide when to adapt.

Storage: data/feedback_loop.json  (survives restarts)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR   = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
LOOP_FILE  = DATA_DIR / "feedback_loop.json"

logger = logging.getLogger("feedback_loop")

# ─── Scoring weights ──────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "views":            1.0,
    "likes":            3.0,
    "comments":         5.0,
    "shares":           8.0,
    "clicks":           5.0,
    "affiliate_clicks": 15.0,
    "leads":            20.0,
    "revenue":          25.0,
}

# A post is "viral" if its score is 3× the platform average
VIRAL_MULTIPLIER = 3.0

# Minimum posts needed before we trust the data
MIN_DATA_POINTS  = 3


# ─── Post Record ──────────────────────────────────────────────────────────────

class PostRecord:
    """Tracks a single published post from creation through performance."""

    def __init__(self, post_id: str, topic: str, niche: str,
                 bot_name: str, platform: str, content_type: str = "post",
                 hour: int = None):
        self.post_id      = post_id
        self.topic        = topic
        self.niche        = niche
        self.bot_name     = bot_name
        self.platform     = platform
        self.content_type = content_type
        self.hour         = hour if hour is not None else datetime.now().hour
        self.created_at   = datetime.now().isoformat()
        self.updated_at   = self.created_at

        self.engagement: Dict[str, float] = {
            "views": 0, "likes": 0, "comments": 0, "shares": 0,
            "clicks": 0, "affiliate_clicks": 0, "leads": 0, "revenue": 0.0,
        }
        self.score: float = 0.0
        self.viral: bool  = False

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if k in self.engagement:
                self.engagement[k] = max(self.engagement[k], float(v))
        self._recalculate()
        self.updated_at = datetime.now().isoformat()

    def _recalculate(self):
        self.score = sum(
            self.engagement.get(k, 0) * w
            for k, w in SCORE_WEIGHTS.items()
        )

    def to_dict(self) -> Dict:
        return {
            "post_id":      self.post_id,
            "topic":        self.topic,
            "niche":        self.niche,
            "bot_name":     self.bot_name,
            "platform":     self.platform,
            "content_type": self.content_type,
            "hour":         self.hour,
            "created_at":   self.created_at,
            "updated_at":   self.updated_at,
            "engagement":   self.engagement,
            "score":        self.score,
            "viral":        self.viral,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PostRecord":
        r = cls(d["post_id"], d["topic"], d.get("niche","general"),
                d.get("bot_name","unknown"), d.get("platform","unknown"),
                d.get("content_type","post"), d.get("hour",0))
        r.created_at  = d.get("created_at", r.created_at)
        r.updated_at  = d.get("updated_at", r.updated_at)
        r.engagement  = d.get("engagement", r.engagement)
        r.score       = d.get("score", 0.0)
        r.viral       = d.get("viral", False)
        return r


# ─── Main FeedbackLoop ────────────────────────────────────────────────────────

class FeedbackLoop:
    """
    Central self-learning hub.  Singleton — use feedback_loop.get() globally.
    """

    _instance: Optional["FeedbackLoop"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._posts: Dict[str, PostRecord] = {}
        self._file_lock = threading.Lock()
        self._load()

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def get(cls) -> "FeedbackLoop":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if LOOP_FILE.exists():
            try:
                raw = json.loads(LOOP_FILE.read_text(encoding="utf-8"))
                self._posts = {
                    pid: PostRecord.from_dict(d)
                    for pid, d in raw.get("posts", {}).items()
                }
                logger.info(f"FeedbackLoop loaded: {len(self._posts)} post records")
            except Exception as e:
                logger.warning(f"Could not load feedback loop: {e}")

    def _save(self):
        with self._file_lock:
            try:
                LOOP_FILE.write_text(
                    json.dumps({"posts": {pid: r.to_dict() for pid, r in self._posts.items()}},
                               indent=2),
                    encoding="utf-8"
                )
            except Exception as e:
                logger.error(f"Could not save feedback loop: {e}")

    # ── Registration ──────────────────────────────────────────────────────────

    def register_post(self, post_id: str, topic: str, niche: str,
                      bot_name: str, platform: str,
                      content_type: str = "post") -> PostRecord:
        """Call this when a bot publishes content."""
        record = PostRecord(post_id, topic, niche, bot_name, platform, content_type)
        self._posts[post_id] = record
        self._save()
        logger.info(f"[FeedbackLoop] Registered post {post_id} | {platform} | {topic[:40]}")
        return record

    def update_engagement(self, post_id: str, **metrics) -> Optional[PostRecord]:
        """Update engagement metrics for a post. Pass any of the SCORE_WEIGHTS keys."""
        record = self._posts.get(post_id)
        if not record:
            logger.warning(f"[FeedbackLoop] Unknown post_id: {post_id}")
            return None
        record.update(**metrics)
        # Mark viral if score exceeds platform average × VIRAL_MULTIPLIER
        avg = self._platform_avg_score(record.platform, exclude=post_id)
        if avg > 0 and record.score >= avg * VIRAL_MULTIPLIER:
            if not record.viral:
                record.viral = True
                logger.info(f"[FeedbackLoop] 🔥 VIRAL DETECTED: {post_id} | score={record.score:.0f} | avg={avg:.0f}")
        self._save()
        return record

    # ── Intelligence queries ───────────────────────────────────────────────────

    def get_best_topics(self, niche: str = None, platform: str = None,
                        limit: int = 5) -> List[Dict]:
        """
        Return the top-performing topics for a niche/platform.
        Bots call this instead of picking from their static topic list.
        """
        records = list(self._posts.values())
        if niche:
            records = [r for r in records if r.niche == niche]
        if platform:
            records = [r for r in records if r.platform == platform]
        if len(records) < MIN_DATA_POINTS:
            return []  # Not enough data yet

        by_topic: Dict[str, List[float]] = defaultdict(list)
        for r in records:
            by_topic[r.topic].append(r.score)

        ranked = [
            {"topic": t, "avg_score": sum(s)/len(s), "data_points": len(s)}
            for t, s in by_topic.items()
            if len(s) >= 1
        ]
        ranked.sort(key=lambda x: x["avg_score"], reverse=True)
        return ranked[:limit]

    def get_best_time(self, platform: str) -> Optional[int]:
        """
        Return the best hour (0-23) to post on a platform based on past scores.
        Returns None if not enough data.
        """
        records = [r for r in self._posts.values() if r.platform == platform]
        if len(records) < MIN_DATA_POINTS:
            return None

        hour_scores: Dict[int, List[float]] = defaultdict(list)
        for r in records:
            hour_scores[r.hour].append(r.score)

        if not hour_scores:
            return None

        best_hour = max(hour_scores.items(), key=lambda x: sum(x[1])/len(x[1]))
        return best_hour[0]

    def get_best_bot(self, niche: str = None) -> Optional[str]:
        """Return the bot name with the highest average score for a niche."""
        records = list(self._posts.values())
        if niche:
            records = [r for r in records if r.niche == niche]
        if len(records) < MIN_DATA_POINTS:
            return None

        bot_scores: Dict[str, List[float]] = defaultdict(list)
        for r in records:
            bot_scores[r.bot_name].append(r.score)

        if not bot_scores:
            return None
        return max(bot_scores.items(), key=lambda x: sum(x[1])/len(x[1]))[0]

    def get_viral_posts(self, hours: int = 24) -> List[PostRecord]:
        """Return all posts that went viral in the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            r for r in self._posts.values()
            if r.viral and datetime.fromisoformat(r.created_at) >= cutoff
        ]

    def is_underperforming(self, platform: str = None, hours: int = 6) -> bool:
        """
        Returns True if recent posts are scoring below historical average —
        a signal for the Decision Engine to adapt strategy.
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [
            r for r in self._posts.values()
            if datetime.fromisoformat(r.created_at) >= cutoff
            and (platform is None or r.platform == platform)
        ]
        if len(recent) < 2:
            return False

        recent_avg  = sum(r.score for r in recent) / len(recent)
        overall_avg = self._platform_avg_score(platform)
        if overall_avg == 0:
            return False

        return recent_avg < overall_avg * 0.5  # 50% below baseline = underperforming

    def summary(self, days: int = 7) -> Dict:
        """Return a summary dict for the dashboard / NarAI report."""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [
            r for r in self._posts.values()
            if datetime.fromisoformat(r.created_at) >= cutoff
        ]
        viral = [r for r in recent if r.viral]

        total_revenue = sum(r.engagement.get("revenue", 0) for r in recent)
        total_leads   = sum(r.engagement.get("leads", 0) for r in recent)
        total_clicks  = sum(r.engagement.get("affiliate_clicks", 0) for r in recent)

        top = sorted(recent, key=lambda x: x.score, reverse=True)[:5]

        return {
            "period_days":    days,
            "total_posts":    len(recent),
            "viral_posts":    len(viral),
            "total_revenue":  round(total_revenue, 2),
            "total_leads":    int(total_leads),
            "affiliate_clicks": int(total_clicks),
            "top_posts":      [{"topic": r.topic, "platform": r.platform,
                                 "score": round(r.score, 1)} for r in top],
            "best_niches":    self._best_niches(recent),
            "best_platforms": self._best_platforms(recent),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _platform_avg_score(self, platform: str = None, exclude: str = None) -> float:
        records = [
            r for r in self._posts.values()
            if r.post_id != exclude
            and (platform is None or r.platform == platform)
        ]
        if not records:
            return 0.0
        return sum(r.score for r in records) / len(records)

    def _best_niches(self, records: List[PostRecord]) -> List[str]:
        niche_scores: Dict[str, float] = defaultdict(float)
        niche_counts: Dict[str, int]   = defaultdict(int)
        for r in records:
            niche_scores[r.niche] += r.score
            niche_counts[r.niche] += 1
        ranked = sorted(niche_scores.items(),
                        key=lambda x: x[1] / max(niche_counts[x[0]], 1),
                        reverse=True)
        return [n for n, _ in ranked[:3]]

    def _best_platforms(self, records: List[PostRecord]) -> List[str]:
        plat_scores: Dict[str, List[float]] = defaultdict(list)
        for r in records:
            plat_scores[r.platform].append(r.score)
        ranked = sorted(plat_scores.items(),
                        key=lambda x: sum(x[1])/len(x[1]),
                        reverse=True)
        return [p for p, _ in ranked[:3]]


# ─── Engagement Poller ────────────────────────────────────────────────────────

class EngagementPoller:
    """
    Background thread that polls Twitter/X, Facebook, Instagram for engagement
    on registered posts and feeds the numbers back into FeedbackLoop.

    Runs every POLL_INTERVAL_MINUTES.
    """

    POLL_INTERVAL_MINUTES = 30

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop = FeedbackLoop.get()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="EngagementPoller")
        self._thread.start()
        logger.info("[EngagementPoller] Started — polling every "
                    f"{self.POLL_INTERVAL_MINUTES} minutes")

    def stop(self):
        self._running = False

    def _run(self):
        import time as _time
        while self._running:
            try:
                self._poll_twitter()
                self._poll_facebook()
            except Exception as e:
                logger.warning(f"[EngagementPoller] Poll error: {e}")
            _time.sleep(self.POLL_INTERVAL_MINUTES * 60)

    def _poll_twitter(self):
        """Pull metrics for Twitter posts via Tweepy."""
        try:
            import tweepy
            client = tweepy.Client(
                bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
                consumer_key=os.getenv("TWITTER_API_KEY"),
                consumer_secret=os.getenv("TWITTER_API_SECRET"),
                access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
                access_token_secret=os.getenv("TWITTER_ACCESS_SECRET"),
                wait_on_rate_limit=True,
            )
            twitter_posts = [
                r for r in self._loop._posts.values()
                if r.platform == "twitter" and r.post_id.startswith("tw_")
            ]
            for record in twitter_posts[:10]:  # max 10 per poll to stay in rate limits
                tweet_id = record.post_id.replace("tw_", "")
                try:
                    resp = client.get_tweet(
                        tweet_id,
                        tweet_fields=["public_metrics"],
                    )
                    if resp.data and resp.data.public_metrics:
                        m = resp.data.public_metrics
                        self._loop.update_engagement(
                            record.post_id,
                            views=m.get("impression_count", 0),
                            likes=m.get("like_count", 0),
                            shares=m.get("retweet_count", 0),
                            comments=m.get("reply_count", 0),
                            clicks=m.get("url_link_clicks", 0),
                        )
                except Exception:
                    pass
        except ImportError:
            logger.debug("[EngagementPoller] tweepy not installed — skip Twitter poll")
        except Exception as e:
            logger.debug(f"[EngagementPoller] Twitter poll: {e}")

    def _poll_facebook(self):
        """Pull metrics for Facebook posts via Graph API."""
        token = os.getenv("FACEBOOK_PAGE_TOKEN")
        if not token:
            return
        fb_posts = [
            r for r in self._loop._posts.values()
            if r.platform == "facebook" and r.post_id.startswith("fb_")
        ]
        import requests as _req
        for record in fb_posts[:10]:
            fb_id = record.post_id.replace("fb_", "")
            try:
                resp = _req.get(
                    f"https://graph.facebook.com/v19.0/{fb_id}/insights",
                    params={
                        "metric": "post_impressions,post_clicks,post_reactions_by_type_total",
                        "access_token": token,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    metrics = {d["name"]: d.get("values", [{}])[-1].get("value", 0)
                               for d in data}
                    self._loop.update_engagement(
                        record.post_id,
                        views=metrics.get("post_impressions", 0),
                        clicks=metrics.get("post_clicks", 0),
                    )
            except Exception:
                pass


# ─── Convenience singleton ────────────────────────────────────────────────────

def get_feedback_loop() -> FeedbackLoop:
    return FeedbackLoop.get()
