#!/usr/bin/env python3
"""
core/performance.py
─────────────────────────────────────────────────────────────────────────────
Content performance feedback loop.

Polls Twitter/X for engagement metrics on published tweets and stores
results in data/intelligence.json so the Decision Engine and SuperAgent
can prioritise high-performing topics.

Metrics collected:
  - Impressions, likes, retweets, replies, bookmarks (per tweet)
  - Click counts from core/click_tracker.py (affiliate revenue signal)
  - Top topics by engagement score

Engagement score formula:
  score = (likes × 2) + (retweets × 5) + (replies × 3) + (bookmarks × 4) + (impressions × 0.01)

Usage (manual):
  python -m core.performance

Usage (programmatic):
  from core.performance import refresh_performance
  stats = refresh_performance()

Scheduled automatically every 4 hours via scheduler.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("performance")

INTELLIGENCE_FILE = ROOT / "data" / "intelligence.json"
PERF_FILE = ROOT / "data" / "performance.json"
PUBLISHED_LOG = ROOT / "data" / "published_log.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _engagement_score(metrics: Dict) -> float:
    return (
        metrics.get("like_count", 0) * 2
        + metrics.get("retweet_count", 0) * 5
        + metrics.get("reply_count", 0) * 3
        + metrics.get("bookmark_count", 0) * 4
        + metrics.get("impression_count", 0) * 0.01
    )


# ── Tweet metrics ─────────────────────────────────────────────────────────────

def _fetch_tweet_metrics(tweet_ids: List[str]) -> Dict[str, Dict]:
    """Fetch engagement metrics for a list of tweet IDs via Twitter API v2."""
    try:
        import tweepy
        api_key = os.getenv("TWITTER_API_KEY", "")
        api_secret = os.getenv("TWITTER_API_SECRET", "")
        access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
        access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")
        bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")

        if not bearer_token and not all([api_key, api_secret, access_token, access_secret]):
            logger.warning("Twitter credentials missing — skipping metrics fetch")
            return {}

        client = tweepy.Client(
            bearer_token=bearer_token or None,
            consumer_key=api_key or None,
            consumer_secret=api_secret or None,
            access_token=access_token or None,
            access_token_secret=access_secret or None,
            wait_on_rate_limit=True,
        )

        results = {}
        # Twitter allows up to 100 IDs per request
        for i in range(0, len(tweet_ids), 100):
            batch = tweet_ids[i:i + 100]
            resp = client.get_tweets(
                ids=batch,
                tweet_fields=["public_metrics", "created_at", "text"],
            )
            if resp.data:
                for tweet in resp.data:
                    m = tweet.public_metrics or {}
                    results[str(tweet.id)] = {
                        "text": tweet.text[:100],
                        "created_at": str(tweet.created_at),
                        "like_count": m.get("like_count", 0),
                        "retweet_count": m.get("retweet_count", 0),
                        "reply_count": m.get("reply_count", 0),
                        "bookmark_count": m.get("bookmark_count", 0),
                        "impression_count": m.get("impression_count", 0),
                    }
            time.sleep(1)

        return results

    except Exception as e:
        logger.warning(f"Tweet metrics fetch failed: {e}")
        return {}


# ── Blog performance (click proxy) ───────────────────────────────────────────

def _blog_topic_clicks() -> Dict[str, int]:
    """Aggregate affiliate clicks by topic slug from published blog files."""
    from core.click_tracker import get_stats
    stats = get_stats()
    return stats.get("by_partner", {})


# ── Main refresh ──────────────────────────────────────────────────────────────

def refresh_performance() -> Dict:
    """
    Pull latest metrics, score topics, update intelligence.json.
    Returns a summary dict.
    """
    perf = _load_json(PERF_FILE, {"tweets": {}, "topics": {}, "updated_at": ""})

    # ── 1. Load previously logged tweet IDs ──────────────────────────────────
    stored_tweet_ids: List[str] = perf.get("tweet_ids", [])

    # ── 2. Fetch live metrics from Twitter ───────────────────────────────────
    if stored_tweet_ids:
        fresh = _fetch_tweet_metrics(stored_tweet_ids)
        perf["tweets"].update(fresh)
        logger.info(f"Metrics fetched for {len(fresh)} tweets")

    # ── 3. Score topics from tweet metrics ───────────────────────────────────
    topic_scores: Dict[str, float] = {}
    for tweet_id, m in perf.get("tweets", {}).items():
        score = _engagement_score(m)
        text = m.get("text", "")
        # Derive a short topic label from the first 6 words
        words = text.replace("#", "").split()[:6]
        topic = " ".join(words).lower()
        topic_scores[topic] = topic_scores.get(topic, 0) + score

    # ── 4. Merge affiliate click signals ─────────────────────────────────────
    click_data = _blog_topic_clicks()
    for partner, count in click_data.items():
        key = f"affiliate_{partner}"
        topic_scores[key] = topic_scores.get(key, 0) + count * 10  # clicks = strong signal

    # ── 5. Save performance data ──────────────────────────────────────────────
    perf["topics"] = topic_scores
    perf["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_json(PERF_FILE, perf)

    # ── 6. Update intelligence.json ──────────────────────────────────────────
    intel = _load_json(INTELLIGENCE_FILE, {})
    intel["topic_scores"] = {
        **intel.get("topic_scores", {}),
        **{k: round(v, 2) for k, v in topic_scores.items()},
    }
    intel["performance_updated"] = perf["updated_at"]
    intel["top_topics"] = sorted(
        topic_scores.items(), key=lambda x: x[1], reverse=True
    )[:10]
    _save_json(INTELLIGENCE_FILE, intel)
    logger.info(f"Intelligence updated — {len(topic_scores)} scored topics")

    # ── 7. Return summary ─────────────────────────────────────────────────────
    top5 = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "tweets_tracked": len(perf.get("tweets", {})),
        "topics_scored": len(topic_scores),
        "top_topics": top5,
        "updated_at": perf["updated_at"],
        "affiliate_clicks": click_data,
    }


def register_tweet_ids(tweet_ids: List[str]):
    """
    Call this after posting a Twitter thread to track the tweet IDs.
    publish_pipeline calls this automatically.
    """
    perf = _load_json(PERF_FILE, {"tweets": {}, "tweet_ids": []})
    existing = set(perf.get("tweet_ids", []))
    existing.update(str(tid) for tid in tweet_ids)
    perf["tweet_ids"] = list(existing)
    _save_json(PERF_FILE, perf)
    logger.info(f"Registered {len(tweet_ids)} tweet IDs for tracking")


# ── Facebook / Instagram metrics ─────────────────────────────────────────────

def _fetch_facebook_insights() -> Dict:
    """Pull Facebook Page insights (reach, impressions, followers)."""
    token = os.getenv("FACEBOOK_PAGE_TOKEN", "")
    page_id = os.getenv("FACEBOOK_PAGE_ID", "")
    if not token or not page_id:
        return {}
    try:
        import requests
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{page_id}",
            params={
                "fields": "followers_count,fan_count",
                "access_token": token,
            },
            timeout=10,
        )
        d = r.json()
        return {
            "followers": d.get("followers_count", 0) or d.get("fan_count", 0),
        }
    except Exception as e:
        logger.warning(f"Facebook insights failed: {e}")
        return {}


def _fetch_instagram_insights() -> Dict:
    """Pull Instagram account follower count via Graph API."""
    token = os.getenv("INSTAGRAM_PAGE_TOKEN", "")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    if not token or not account_id:
        return {}
    try:
        import requests
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{account_id}",
            params={
                "fields": "followers_count,media_count",
                "access_token": token,
            },
            timeout=10,
        )
        d = r.json()
        return {
            "followers": d.get("followers_count", 0),
            "media_count": d.get("media_count", 0),
        }
    except Exception as e:
        logger.warning(f"Instagram insights failed: {e}")
        return {}


def _fetch_twitter_followers() -> int:
    """Get Twitter follower count for the configured account."""
    try:
        import tweepy
        bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
        username = os.getenv("TWITTER_USERNAME", "").lstrip("@")
        if not bearer or not username:
            return 0
        client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)
        user = client.get_user(username=username,
                               user_fields=["public_metrics"])
        if user.data and user.data.public_metrics:
            return user.data.public_metrics.get("followers_count", 0)
    except Exception as e:
        logger.warning(f"Twitter followers fetch failed: {e}")
    return 0


# ── Unified dashboard ─────────────────────────────────────────────────────────

def get_dashboard() -> Dict:
    """
    Pull metrics from all platforms and return a unified performance dashboard.
    Also syncs key metrics to GoalTracker automatically.
    """
    now = datetime.utcnow().isoformat() + "Z"
    perf = _load_json(PERF_FILE, {"tweets": {}, "topics": {}, "updated_at": ""})

    # Platform metrics
    fb = _fetch_facebook_insights()
    ig = _fetch_instagram_insights()
    tw_followers = _fetch_twitter_followers()

    # Topic scores from existing performance data
    top_topics = sorted(
        perf.get("topics", {}).items(), key=lambda x: x[1], reverse=True
    )[:10]

    dashboard = {
        "updated_at": now,
        "platforms": {
            "twitter": {
                "followers": tw_followers,
                "tweets_tracked": len(perf.get("tweets", {})),
            },
            "facebook": fb,
            "instagram": ig,
        },
        "content": {
            "tweets_tracked": len(perf.get("tweets", {})),
            "top_topics": [{"topic": t, "score": round(s, 1)} for t, s in top_topics],
        },
        "affiliate": _blog_topic_clicks(),
    }

    # Auto-sync to GoalTracker
    try:
        from core.goal_tracker import update_goal
        if tw_followers:
            update_goal("twitter_followers", tw_followers)
        if ig.get("followers"):
            update_goal("instagram_followers", ig["followers"])
        if fb.get("followers"):
            update_goal("facebook_followers", fb.get("followers", 0))
    except Exception:
        pass

    # Auto-sync to PersonalityEngine platform performance
    try:
        from core.personality import PersonalityEngine
        pe = PersonalityEngine.get()
        for tweet_id, m in perf.get("tweets", {}).items():
            score = _engagement_score(m)
            if score > 0:
                pe.update_platform_performance("twitter", score)
    except Exception:
        pass

    _save_json(PERF_FILE, {**perf, "dashboard": dashboard, "updated_at": now})
    return dashboard


def get_summary() -> Dict:
    """Lightweight summary without live API calls."""
    perf = _load_json(PERF_FILE, {})
    dashboard = perf.get("dashboard", {})
    top_topics = sorted(
        perf.get("topics", {}).items(), key=lambda x: x[1], reverse=True
    )[:5]
    return {
        "tweets_tracked": len(perf.get("tweets", {})),
        "topics_scored": len(perf.get("topics", {})),
        "top_topics": [{"topic": t, "score": round(s, 1)} for t, s in top_topics],
        "platforms": dashboard.get("platforms", {}),
        "updated_at": perf.get("updated_at", "never"),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = refresh_performance()
    print(json.dumps(result, indent=2))
