#!/usr/bin/env python3
"""
core/linkedin.py
─────────────────────────────────────────────────────────────────────────────
LinkedIn Publishing Engine

LinkedIn is the highest-converting platform for affiliate income — the
audience has money, is career-focused, and trusts detailed professional
content. One good LinkedIn post can drive $200-500 in affiliate signups.

What this module does:
  • Post text updates to your LinkedIn profile / company page
  • Post images (auto-generates with DALL-E if none provided)
  • Post articles (LinkedIn Newsletter / long-form)
  • Repurpose existing blog content into LinkedIn format
  • Auto-generate LinkedIn-optimised content from any topic

Auth (OAuth 2.0 — one-time setup):
  1. Go to linkedin.com/developers → Create App
  2. Add products: "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect"
  3. Set redirect URI: https://grateful-flexibility-production.up.railway.app/api/linkedin/callback
  4. Copy Client ID + Secret → .env
  5. Visit /api/linkedin/auth in your browser → complete OAuth
  6. Token saved to data/linkedin_token.json (valid 60 days)

.env keys:
  LINKEDIN_CLIENT_ID      — from developer app
  LINKEDIN_CLIENT_SECRET  — from developer app
  LINKEDIN_ACCESS_TOKEN   — (auto-saved after OAuth, or paste directly)
  LINKEDIN_PERSON_URN     — your LinkedIn person ID (auto-fetched after auth)
  LINKEDIN_ORG_URN        — (optional) your company page URN

Alternative — direct token:
  If you already have a token from LinkedIn developer tools,
  just paste it as LINKEDIN_ACCESS_TOKEN in .env. Tokens last 60 days.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TOKEN_FILE = DATA_DIR / "linkedin_token.json"

logger = logging.getLogger("linkedin")

API_BASE = "https://api.linkedin.com/v2"
AUTH_BASE = "https://www.linkedin.com/oauth/v2"

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI",
                          "https://grateful-flexibility-production.up.railway.app/api/linkedin/callback")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")

SCOPES = ["openid", "profile", "email", "w_member_social"]


# ─── Token management ────────────────────────────────────────────────────────

def _load_token() -> dict:
    """Load token from .env first, then token file."""
    env_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    if env_token:
        return {"access_token": env_token}
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_token(data: dict):
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    logger.info("[LinkedIn] Token saved to data/linkedin_token.json")


def get_access_token() -> Optional[str]:
    t = _load_token()
    return t.get("access_token") or None


def is_configured() -> bool:
    return bool(get_access_token())


def get_person_urn() -> Optional[str]:
    """Get the authenticated user's LinkedIn person URN."""
    urn = os.getenv("LINKEDIN_PERSON_URN", "")
    if urn:
        return urn
    token = get_access_token()
    if not token:
        return None
    try:
        resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("sub", "")
            if sub:
                urn = f"urn:li:person:{sub}"
                logger.info(f"[LinkedIn] Person URN: {urn}")
                return urn
    except Exception as e:
        logger.warning(f"[LinkedIn] get_person_urn failed: {e}")
    return None


# ─── OAuth helpers (used by /api/linkedin/auth endpoint) ─────────────────────

def get_auth_url() -> str:
    """Return the LinkedIn OAuth URL to redirect the user to."""
    import urllib.parse
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": "wheellsverse_linkedin",
    }
    return f"{AUTH_BASE}/authorization?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    """Exchange OAuth code for access token. Called by the callback endpoint."""
    resp = requests.post(
        f"{AUTH_BASE}/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        _save_token(data)
        return data
    return {"error": resp.text}


# ─── Posting ──────────────────────────────────────────────────────────────────

def post_text(text: str, author_urn: str = None) -> Dict:
    """
    Post a text update to LinkedIn.
    text: up to 3000 chars (LinkedIn limit for personal posts)
    """
    token = get_access_token()
    if not token:
        return {"error": "LinkedIn not authenticated — visit /api/linkedin/auth"}

    author = author_urn or get_person_urn() or os.getenv("LINKEDIN_ORG_URN", "")
    if not author:
        return {"error": "Could not determine LinkedIn author URN"}

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text[:3000]},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    try:
        resp = requests.post(
            f"{API_BASE}/ugcPosts",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=20,
        )
        if resp.status_code in (200, 201):
            post_id = resp.headers.get("x-restli-id", "")
            logger.info(f"[LinkedIn] Posted: {post_id}")
            return {"status": "published", "post_id": post_id}
        logger.error(f"[LinkedIn] Post failed {resp.status_code}: {resp.text[:300]}")
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"[LinkedIn] post_text error: {e}")
        return {"error": str(e)}


def post_with_image(text: str, image_url: str = None,
                    image_title: str = "", author_urn: str = None) -> Dict:
    """Post a LinkedIn update with an image link preview."""
    token = get_access_token()
    if not token:
        return {"error": "LinkedIn not authenticated"}

    author = author_urn or get_person_urn() or os.getenv("LINKEDIN_ORG_URN", "")
    if not author:
        return {"error": "Could not determine LinkedIn author URN"}

    # If no image_url, generate one with DALL-E
    if not image_url:
        image_url = _generate_dalle_image(text[:200])

    media_content = {
        "shareCommentary": {"text": text[:3000]},
        "shareMediaCategory": "ARTICLE" if image_url else "NONE",
    }

    if image_url:
        media_content["media"] = [{
            "status": "READY",
            "description": {"text": text[:200]},
            "originalUrl": image_url,
            "title": {"text": image_title[:200] or BRAND},
        }]

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": media_content
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    try:
        resp = requests.post(
            f"{API_BASE}/ugcPosts",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=20,
        )
        if resp.status_code in (200, 201):
            post_id = resp.headers.get("x-restli-id", "")
            logger.info(f"[LinkedIn] Image post: {post_id}")
            return {"status": "published", "post_id": post_id}
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


# ─── Content generation ───────────────────────────────────────────────────────

def generate_post(topic: str, niche: str = "general",
                  include_affiliate: bool = True) -> str:
    """
    Generate a LinkedIn-optimized post from a topic using GPT-4o.
    LinkedIn format: hook → insight → data → CTA. Professional but human.
    """
    try:
        from core.llm_client import safe_openai_call

        affiliate_hint = ""
        if include_affiliate:
            from core.monetization import get_affiliate_links
            links = get_affiliate_links(niche)
            affiliate_hint = f"\nNaturally embed 1 affiliate recommendation: {links[:200]}"

        resp = safe_openai_call(
            messages=[
                {"role": "system", "content": (
                    f"You write LinkedIn posts for {BRAND} — an AI entrepreneur "
                    "building passive income through AI tools, crypto, and affiliate marketing. "
                    "LinkedIn voice: professional, data-driven, personal story, no fluff. "
                    "NOT corporate. NOT salesy. Sounds like a smart founder sharing hard-won knowledge."
                )},
                {"role": "user", "content": (
                    f"Write a high-performing LinkedIn post on: '{topic}'\n"
                    f"Niche: {niche}\n\n"
                    "Structure:\n"
                    "• Hook line (bold claim or surprising stat — make them stop scrolling)\n"
                    "• 3-5 short paragraphs (insight, story, data, practical takeaway)\n"
                    "• 1 CTA (soft — not pushy)\n"
                    "• 3-5 relevant hashtags\n\n"
                    f"Max 1300 characters. Link to {CTA_URL} naturally if relevant.{affiliate_hint}\n"
                    "Output only the post text."
                )},
            ],
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=500,
            temperature=0.78,
            bot_name="linkedin",
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[LinkedIn] generate_post failed: {e}")
        return ""


def repurpose_to_linkedin(blog_content: str, topic: str) -> str:
    """Condense a blog post into a LinkedIn post."""
    try:
        from core.llm_client import safe_openai_call
        resp = safe_openai_call(
            messages=[{
                "role": "user",
                "content": (
                    f"Condense this blog post into a LinkedIn post (max 1200 chars).\n"
                    f"Topic: {topic}\n\n"
                    f"Blog content:\n{blog_content[:2000]}\n\n"
                    "Keep the best insight, add a hook, end with a CTA. "
                    "LinkedIn voice: professional but personal. "
                    "Add 3 hashtags. Output only the post."
                )
            }],
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=400,
            temperature=0.7,
            bot_name="linkedin",
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[LinkedIn] repurpose failed: {e}")
        return ""


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _generate_dalle_image(prompt: str) -> Optional[str]:
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.images.generate(
            model="gpt-image-1",
            prompt=f"Professional LinkedIn cover image for: {prompt[:200]}. "
            "Modern, clean, dark theme, data visualization aesthetic.",
            size="1536x1024",
            quality="high",
            n=1,
        )
        return resp.data[0].url
    except Exception as e:
        logger.warning(f"[LinkedIn] DALL-E image failed: {e}")
        return None


def get_post_stats(post_id: str) -> Dict:
    """Get likes/comments/shares for a post."""
    token = get_access_token()
    if not token:
        return {}
    try:
        resp = requests.get(
            f"{API_BASE}/socialActions/{post_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception:
        return {}


def get_linkedin() -> "LinkedInClient":
    return LinkedInClient()


class LinkedInClient:
    """Convenience wrapper matching the pattern of other core platform clients."""

    def is_configured(self) -> bool:
        return is_configured()

    def post(self, text: str, image_url: str = None, topic: str = "",
             generate: bool = False, niche: str = "general") -> Dict:
        if generate or not text:
            text = generate_post(topic or text, niche=niche)
        if not text:
            return {"error": "No content to post"}
        if image_url:
            return post_with_image(text, image_url=image_url, image_title=topic)
        return post_text(text)

    def generate_and_post(self, topic: str, niche: str = "general") -> Dict:
        text = generate_post(topic, niche=niche)
        if not text:
            return {"error": "Content generation failed"}
        return post_text(text)
