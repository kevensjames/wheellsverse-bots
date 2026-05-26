#!/usr/bin/env python3
"""
core/threads.py
─────────────────────────────────────────────────────────────────────────────
Threads (Meta) Publishing Engine

Threads is Instagram's text-based platform — same audience, different format.
Growing fast, low competition, high organic reach right now.
Content from Instagram/Twitter repurposed here costs nothing extra.

What this module does:
  • Post text updates to Threads (up to 500 chars)
  • Post with images (auto-generates with DALL-E)
  • Repurpose Twitter threads and Instagram captions to Threads format
  • Auto-generate Threads-optimized posts from any topic
  • Reply to threads (conversation builder)

Auth (Meta Graph API — same token as Instagram):
  Threads uses the Instagram Graph API under the hood.
  If INSTAGRAM_PAGE_TOKEN + INSTAGRAM_ACCOUNT_ID are set, Threads works too.

  For dedicated Threads token:
  1. developers.facebook.com → Your App → Add Threads Product
  2. Generate token with threads_basic + threads_content_publish scopes
  3. Paste as THREADS_ACCESS_TOKEN in .env

.env keys:
  THREADS_ACCESS_TOKEN  — dedicated token, OR
  INSTAGRAM_PAGE_TOKEN  — reused from Instagram (same Meta ecosystem)
  THREADS_USER_ID       — your Threads user ID (auto-fetched or from IG account ID)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("threads")
API_BASE = "https://graph.threads.net/v1.0"
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
CTA_URL = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev/blueprint.pdf")

# Threads posts: max 500 chars
MAX_CHARS = 500


def _get_token() -> Optional[str]:
    """Return Threads token — dedicated first, then Instagram fallback."""
    return (
        os.getenv("THREADS_ACCESS_TOKEN") or
        os.getenv("INSTAGRAM_PAGE_TOKEN") or
        None
    )


def _get_user_id() -> Optional[str]:
    """Return Threads user ID."""
    uid = os.getenv("THREADS_USER_ID") or os.getenv("INSTAGRAM_ACCOUNT_ID")
    if uid:
        return uid
    # Auto-fetch from Threads API
    token = _get_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"{API_BASE}/me",
            params={"fields": "id,username", "access_token": token},
            timeout=10,
        )
        if resp.status_code == 200:
            uid = resp.json().get("id", "")
            logger.info(f"[Threads] User ID: {uid}")
            return uid
    except Exception as e:
        logger.warning(f"[Threads] get_user_id failed: {e}")
    return None


def is_configured() -> bool:
    return bool(_get_token() and _get_user_id())


# ─── Posting ──────────────────────────────────────────────────────────────────

def post_text(text: str) -> Dict:
    """
    Post a text thread (up to 500 chars).
    Threads API: create container → publish.
    """
    token = _get_token()
    user_id = _get_user_id()

    if not (token and user_id):
        return {"error": "Threads not configured — set THREADS_ACCESS_TOKEN or INSTAGRAM_PAGE_TOKEN"}

    text = text.strip()[:MAX_CHARS]

    try:
        # Step 1: Create media container
        container_resp = requests.post(
            f"{API_BASE}/{user_id}/threads",
            params={
                "media_type": "TEXT",
                "text": text,
                "access_token": token,
            },
            timeout=20,
        )

        if container_resp.status_code not in (200, 201):
            return {"error": f"Container error {container_resp.status_code}: {container_resp.text[:200]}"}

        container_id = container_resp.json().get("id", "")
        if not container_id:
            return {"error": "No container ID returned"}

        time.sleep(2)  # let Meta process the container

        # Step 2: Publish
        pub_resp = requests.post(
            f"{API_BASE}/{user_id}/threads_publish",
            params={
                "creation_id": container_id,
                "access_token": token,
            },
            timeout=20,
        )

        if pub_resp.status_code in (200, 201):
            post_id = pub_resp.json().get("id", "")
            logger.info(f"[Threads] Posted: {post_id} | {text[:40]}")
            return {"status": "published", "post_id": post_id, "text": text[:60]}

        return {"error": f"Publish error {pub_resp.status_code}: {pub_resp.text[:200]}"}

    except Exception as e:
        logger.error(f"[Threads] post_text error: {e}")
        return {"error": str(e)}


def post_with_image(text: str, image_url: str = None) -> Dict:
    """Post a thread with an image."""
    token = _get_token()
    user_id = _get_user_id()

    if not (token and user_id):
        return {"error": "Threads not configured"}

    if not image_url:
        image_url = _generate_image(text[:200])
    if not image_url:
        # Fall back to text-only
        return post_text(text)

    text = text.strip()[:MAX_CHARS]

    try:
        # Create image container
        container_resp = requests.post(
            f"{API_BASE}/{user_id}/threads",
            params={
                "media_type": "IMAGE",
                "image_url": image_url,
                "text": text,
                "access_token": token,
            },
            timeout=20,
        )

        if container_resp.status_code not in (200, 201):
            logger.warning("[Threads] Image container failed, falling back to text")
            return post_text(text)

        container_id = container_resp.json().get("id", "")
        time.sleep(3)

        pub_resp = requests.post(
            f"{API_BASE}/{user_id}/threads_publish",
            params={"creation_id": container_id, "access_token": token},
            timeout=20,
        )

        if pub_resp.status_code in (200, 201):
            post_id = pub_resp.json().get("id", "")
            logger.info(f"[Threads] Image post: {post_id}")
            return {"status": "published", "post_id": post_id}

        return {"error": f"Publish error {pub_resp.status_code}: {pub_resp.text[:200]}"}

    except Exception as e:
        logger.error(f"[Threads] post_with_image error: {e}")
        return {"error": str(e)}


def reply_to_thread(thread_id: str, text: str) -> Dict:
    """Reply to an existing thread."""
    token = _get_token()
    user_id = _get_user_id()
    if not (token and user_id):
        return {"error": "Threads not configured"}

    text = text.strip()[:MAX_CHARS]
    try:
        container_resp = requests.post(
            f"{API_BASE}/{user_id}/threads",
            params={
                "media_type": "TEXT",
                "text": text,
                "reply_to_id": thread_id,
                "access_token": token,
            },
            timeout=20,
        )
        if container_resp.status_code not in (200, 201):
            return {"error": container_resp.text[:200]}

        container_id = container_resp.json().get("id", "")
        time.sleep(2)

        pub_resp = requests.post(
            f"{API_BASE}/{user_id}/threads_publish",
            params={"creation_id": container_id, "access_token": token},
            timeout=20,
        )

        if pub_resp.status_code in (200, 201):
            return {"status": "replied", "reply_id": pub_resp.json().get("id", "")}
        return {"error": pub_resp.text[:200]}

    except Exception as e:
        return {"error": str(e)}


# ─── Content generation ───────────────────────────────────────────────────────

def generate_post(topic: str, niche: str = "general",
                  style: str = "conversational") -> str:
    """
    Generate a Threads post from a topic.
    Threads style: short, punchy, conversational — more casual than LinkedIn,
    more thoughtful than Twitter.
    """
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        style_guide = {
            "conversational": "Casual, relatable, like texting a smart friend. Ask a question.",
            "insight": "Share a non-obvious insight. Start with a bold claim.",
            "story": "Mini personal story. 3 sentences max. What happened, what I learned.",
            "list": "Quick list: 3 things most people don't know about this topic.",
        }.get(style, "Casual and punchy.")

        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": (
                    f"You write Threads posts for {BRAND}. "
                    "Threads is text-first, casual, max 500 chars. "
                    "No hashtag spam. Sound like a smart person, not a brand. "
                    "High signal, low noise."
                )},
                {"role": "user", "content": (
                    f"Write a Threads post on: '{topic}'\n"
                    f"Niche: {niche} | Style: {style_guide}\n"
                    f"Max 480 chars. End with a thought-provoking question OR a soft CTA.\n"
                    "No more than 3 hashtags. Output only the post text."
                )},
            ],
            max_tokens=200,
            temperature=0.82,
        )
        return resp.choices[0].message.content.strip()[:MAX_CHARS]
    except Exception as e:
        logger.error(f"[Threads] generate_post failed: {e}")
        return ""


def repurpose_from_twitter(tweet_thread: str, topic: str = "") -> str:
    """Convert a Twitter thread into a Threads post."""
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": (
                f"Convert this Twitter thread into a single Threads post (max 480 chars).\n"
                f"Topic: {topic}\n\nThread:\n{tweet_thread[:1500]}\n\n"
                "Keep the best insight. Threads is more conversational than Twitter. "
                "End with a question. No hashtag spam (max 2). Output only the post."
            )}],
            max_tokens=200,
            temperature=0.75,
        )
        return resp.choices[0].message.content.strip()[:MAX_CHARS]
    except Exception as e:
        logger.error(f"[Threads] repurpose_from_twitter failed: {e}")
        return ""


def repurpose_from_instagram(caption: str, topic: str = "") -> str:
    """Convert an Instagram caption into a Threads post."""
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": (
                f"Convert this Instagram caption into a Threads post (max 480 chars).\n"
                f"Topic: {topic}\n\nCaption:\n{caption[:1000]}\n\n"
                "Threads is text-first, more like a thoughtful tweet. "
                "Remove excessive hashtags (keep max 2). Make it feel organic. Output only the post."
            )}],
            max_tokens=200,
            temperature=0.75,
        )
        return resp.choices[0].message.content.strip()[:MAX_CHARS]
    except Exception as e:
        logger.error(f"[Threads] repurpose_from_instagram failed: {e}")
        return ""


def post_series(topics: List[str], niche: str = "general",
                delay_seconds: int = 30) -> List[Dict]:
    """Post a series of Threads posts on multiple topics."""
    results = []
    for i, topic in enumerate(topics):
        text = generate_post(topic, niche=niche)
        result = post_text(text) if text else {"error": "generation failed"}
        results.append({"topic": topic, **result})
        logger.info(f"[Threads] Series {i + 1}/{len(topics)}: {result.get('status', 'error')}")
        if i < len(topics) - 1:
            time.sleep(delay_seconds)
    return results


def get_thread_stats(thread_id: str) -> Dict:
    """Get views/likes/replies for a thread."""
    token = _get_token()
    if not token:
        return {}
    try:
        resp = requests.get(
            f"{API_BASE}/{thread_id}/insights",
            params={
                "metric": "views,likes,replies,reposts,quotes",
                "access_token": token,
            },
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _generate_image(prompt: str) -> Optional[str]:
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Social media image for Threads post: {prompt}. "
            "Clean, modern, dark background, purple/cyan tech aesthetic.",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        return resp.data[0].url
    except Exception as e:
        logger.warning(f"[Threads] image generation failed: {e}")
        return None


def get_threads() -> "ThreadsClient":
    return ThreadsClient()


class ThreadsClient:
    def is_configured(self) -> bool:
        return is_configured()

    def post(self, text: str = "", topic: str = "",
             niche: str = "general", image_url: str = None,
             generate: bool = False) -> Dict:
        if generate or not text:
            text = generate_post(topic or text, niche=niche)
        if not text:
            return {"error": "No content"}
        if image_url:
            return post_with_image(text, image_url=image_url)
        return post_text(text)

    def generate_and_post(self, topic: str, niche: str = "general") -> Dict:
        text = generate_post(topic, niche=niche)
        return post_text(text) if text else {"error": "generation failed"}
