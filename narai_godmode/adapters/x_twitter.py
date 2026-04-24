"""
X (Twitter) adapter — post tweets, read mentions, upload media.

Credentials loaded from .env:
  TWITTER_API_KEY, TWITTER_API_SECRET            — app consumer keys
  TWITTER_BEARER_TOKEN                           — v2 app-only (read public data)
  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET    — user context (post as user)

Uses the v2 Tweets endpoint (free tier allows ~1500 posts/month).
Media uploads still go through v1.1 API (Twitter hasn't migrated media to v2).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tweepy


def _load_env():
    """Lazy .env loader so this adapter works even if dotenv isn't imported elsewhere."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass


def _check(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"X adapter needs {key} in .env")
    return val


def _v2_client() -> tweepy.Client:
    """Tweepy v2 Client with user-context auth (can post, like, follow)."""
    _load_env()
    return tweepy.Client(
        bearer_token=_check("TWITTER_BEARER_TOKEN"),
        consumer_key=_check("TWITTER_API_KEY"),
        consumer_secret=_check("TWITTER_API_SECRET"),
        access_token=_check("TWITTER_ACCESS_TOKEN"),
        access_token_secret=_check("TWITTER_ACCESS_SECRET"),
    )


def _v1_api() -> tweepy.API:
    """Tweepy v1.1 API — only used for media uploads (v2 doesn't support media)."""
    _load_env()
    auth = tweepy.OAuth1UserHandler(
        _check("TWITTER_API_KEY"),
        _check("TWITTER_API_SECRET"),
        _check("TWITTER_ACCESS_TOKEN"),
        _check("TWITTER_ACCESS_SECRET"),
    )
    return tweepy.API(auth)


# ── Public API ───────────────────────────────────────────────────────────────

def whoami() -> dict:
    """Verify credentials and return the authenticated user's handle + id."""
    c = _v2_client()
    me = c.get_me(user_fields=["username", "name", "public_metrics"]).data
    return {
        "id":       me.id,
        "username": me.username,
        "name":     me.name,
        "followers": me.public_metrics.get("followers_count"),
        "tweets":    me.public_metrics.get("tweet_count"),
    }


def post_tweet(text: str, media_paths: list[str] | None = None,
               reply_to_id: int | None = None) -> dict:
    """Post a tweet. Up to 4 images or 1 video. Returns the new tweet's id and url."""
    media_ids: list[str] = []
    if media_paths:
        v1 = _v1_api()
        for p in media_paths[:4]:
            uploaded = v1.media_upload(filename=p)
            media_ids.append(uploaded.media_id_string)

    kwargs: dict[str, Any] = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids
    if reply_to_id:
        kwargs["in_reply_to_tweet_id"] = reply_to_id

    resp = _v2_client().create_tweet(**kwargs)
    tweet_id = resp.data["id"]
    username = whoami()["username"]
    return {
        "id":  tweet_id,
        "url": f"https://twitter.com/{username}/status/{tweet_id}",
    }


def list_mentions(max_results: int = 10) -> list[dict]:
    """Recent mentions of @you."""
    c = _v2_client()
    me_id = c.get_me().data.id
    resp = c.get_users_mentions(
        id=me_id, max_results=min(max_results, 100),
        tweet_fields=["created_at", "author_id", "public_metrics"],
        expansions=["author_id"],
        user_fields=["username", "name"],
    )
    users = {u.id: u for u in (resp.includes.get("users", []) if resp.includes else [])}
    out = []
    for t in (resp.data or []):
        author = users.get(t.author_id)
        out.append({
            "id":       t.id,
            "text":     t.text,
            "created": str(t.created_at) if t.created_at else None,
            "author":  author.username if author else str(t.author_id),
            "likes":    t.public_metrics.get("like_count", 0) if t.public_metrics else 0,
        })
    return out


def search_recent(query: str, max_results: int = 10) -> list[dict]:
    """Search recent (last 7 days) public tweets. Query uses X search syntax."""
    c = _v2_client()
    resp = c.search_recent_tweets(
        query=query, max_results=min(max_results, 100),
        tweet_fields=["created_at", "author_id", "public_metrics"],
    )
    return [
        {
            "id": t.id, "text": t.text,
            "created": str(t.created_at) if t.created_at else None,
            "likes": t.public_metrics.get("like_count", 0) if t.public_metrics else 0,
        }
        for t in (resp.data or [])
    ]


def delete_tweet(tweet_id: int) -> bool:
    """Delete a tweet by id (must belong to the authenticated user)."""
    return _v2_client().delete_tweet(tweet_id).data["deleted"]
