#!/usr/bin/env python3
"""
core/pinterest.py
─────────────────────────────────────────────────────────────────────────────
Pinterest Auto-Pin Engine — evergreen traffic machine.

Why Pinterest matters:
  • Pins live for YEARS (unlike tweets that die in 20 minutes)
  • 1,000 pins = 1,000 permanent doorways to affiliate content
  • Pinterest users are buyers — high purchase intent
  • Each pin with an affiliate link drives passive clicks forever

What this module does:
  • Create pins with images + affiliate links
  • Auto-generate DALL-E images for pins (no manual design needed)
  • Batch pin creation (post 5-10 pins at once across multiple boards)
  • Create and manage boards by niche
  • Repurpose blog posts into pins automatically
  • Schedule pins for optimal posting times

Auth (OAuth 2.0):
  1. Go to developers.pinterest.com → Create App
  2. Set redirect URI: https://grateful-flexibility-production.up.railway.app/api/pinterest/callback
  3. Request scopes: boards:read, boards:write, pins:read, pins:write
  4. Copy App ID + Secret → .env
  5. Visit /api/pinterest/auth in browser → complete OAuth

.env keys:
  PINTEREST_APP_ID       — from Pinterest developer app
  PINTEREST_APP_SECRET   — from Pinterest developer app
  PINTEREST_ACCESS_TOKEN — (auto-saved after OAuth, or paste directly)
  PINTEREST_BOARD_ID     — default board ID to pin to
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TOKEN_FILE = DATA_DIR / "pinterest_token.json"

logger = logging.getLogger("pinterest")
API_BASE = "https://api.pinterest.com/v5"
AUTH_BASE = "https://www.pinterest.com/oauth"

APP_ID = os.getenv("PINTEREST_APP_ID", "")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "")
REDIRECT_URI = os.getenv("PINTEREST_REDIRECT_URI",
                         "https://grateful-flexibility-production.up.railway.app/api/pinterest/callback")
BOARD_ID = os.getenv("PINTEREST_BOARD_ID", "")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
CTA_URL = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev/blueprint.pdf")

SCOPES = ["boards:read", "boards:write", "pins:read", "pins:write", "user_accounts:read"]

# Niche → boards to auto-create
NICHE_BOARDS = {
    "crypto": "Crypto Investing 2025",
    "investing": "Stock Market & Investing Tips",
    "ai_tools": "AI Tools That Make Money",
    "passive_income": "Passive Income Ideas",
    "affiliate": "Affiliate Marketing Strategies",
}


# ─── Token management ────────────────────────────────────────────────────────

def _load_token() -> dict:
    env_token = os.getenv("PINTEREST_ACCESS_TOKEN", "")
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


def get_access_token() -> Optional[str]:
    return _load_token().get("access_token")


def is_configured() -> bool:
    return bool(get_access_token())


def _headers() -> dict:
    token = get_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ─── OAuth ────────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    import urllib.parse
    params = {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": "wheellsverse_pinterest",
    }
    return f"{AUTH_BASE}/?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    import base64
    creds = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
    resp = requests.post(
        f"{AUTH_BASE}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        _save_token(data)
        return data
    return {"error": resp.text}


# ─── Board management ─────────────────────────────────────────────────────────

def list_boards() -> List[Dict]:
    if not is_configured():
        return []
    try:
        resp = requests.get(f"{API_BASE}/boards", headers=_headers(), timeout=15)
        if resp.status_code == 200:
            return resp.json().get("items", [])
        return []
    except Exception as e:
        logger.error(f"[Pinterest] list_boards failed: {e}")
        return []


def create_board(name: str, description: str = "", privacy: str = "PUBLIC") -> Dict:
    """Create a new Pinterest board."""
    if not is_configured():
        return {"error": "Not configured"}
    try:
        resp = requests.post(
            f"{API_BASE}/boards",
            json={"name": name, "description": description, "privacy": privacy},
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(f"[Pinterest] Board created: {name} ({data.get('id')})")
            return data
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def get_or_create_board(name: str, description: str = "") -> Optional[str]:
    """Return board ID, creating it if it doesn't exist."""
    boards = list_boards()
    for b in boards:
        if b.get("name", "").lower() == name.lower():
            return b["id"]
    result = create_board(name, description)
    return result.get("id")


# ─── Pin creation ─────────────────────────────────────────────────────────────

def create_pin(
    title: str,
    description: str,
    link: str,
    board_id: str = None,
    image_url: str = None,
    alt_text: str = "",
) -> Dict:
    """
    Create a pin. image_url must be a publicly accessible image.
    If image_url is None, DALL-E generates one automatically.
    """
    if not is_configured():
        return {"error": "Pinterest not configured — visit /api/pinterest/auth"}

    bid = board_id or BOARD_ID
    if not bid:
        return {"error": "No board_id provided and PINTEREST_BOARD_ID not set"}

    # Generate image if not provided
    if not image_url:
        image_url = _generate_pin_image(title, description)
    if not image_url:
        return {"error": "No image URL available"}

    payload = {
        "board_id": bid,
        "title": title[:100],
        "description": description[:500],
        "link": link,
        "alt_text": alt_text[:500] or title,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }

    try:
        resp = requests.post(
            f"{API_BASE}/pins",
            json=payload,
            headers=_headers(),
            timeout=20,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            pin_id = data.get("id", "")
            logger.info(f"[Pinterest] Pin created: {pin_id} | {title[:40]}")
            return {"status": "published", "pin_id": pin_id, "title": title}
        logger.error(f"[Pinterest] create_pin {resp.status_code}: {resp.text[:300]}")
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"[Pinterest] create_pin error: {e}")
        return {"error": str(e)}


def batch_pin(topic_links: List[Dict], board_id: str = None,
              delay_seconds: int = 5) -> List[Dict]:
    """
    Create multiple pins in sequence.
    topic_links: [{"title": str, "description": str, "link": str, "image_url": str}, ...]
    Returns list of results.
    """
    results = []
    for i, item in enumerate(topic_links):
        logger.info(f"[Pinterest] Batch pin {i + 1}/{len(topic_links)}: {item.get('title', '')[:40]}")
        result = create_pin(
            title=item.get("title", ""),
            description=item.get("description", ""),
            link=item.get("link", CTA_URL),
            board_id=board_id or item.get("board_id"),
            image_url=item.get("image_url"),
        )
        results.append(result)
        if i < len(topic_links) - 1:
            time.sleep(delay_seconds)  # rate limit respect
    return results


# ─── Auto-pin from topic ──────────────────────────────────────────────────────

def auto_pin_topic(topic: str, niche: str = "general",
                   affiliate_link: str = None) -> Dict:
    """
    Full pipeline: topic → GPT description → DALL-E image → pin.
    The fastest way to create affiliate-linked pins at scale.
    """
    # Generate pin content with GPT
    title, description = _generate_pin_content(topic, niche)
    link = affiliate_link or _get_niche_affiliate(niche) or CTA_URL
    bid = _get_niche_board(niche)

    return create_pin(
        title=title,
        description=description,
        link=link,
        board_id=bid,
    )


def auto_pin_batch(topics: List[str], niche: str = "general",
                   affiliate_link: str = None) -> List[Dict]:
    """Create a batch of pins from a list of topics."""
    results = []
    link = affiliate_link or _get_niche_affiliate(niche) or CTA_URL
    bid = _get_niche_board(niche)

    for i, topic in enumerate(topics):
        logger.info(f"[Pinterest] Auto-pin {i + 1}/{len(topics)}: {topic[:50]}")
        title, description = _generate_pin_content(topic, niche)
        result = create_pin(
            title=title, description=description,
            link=link, board_id=bid,
        )
        results.append({"topic": topic, **result})
        if i < len(topics) - 1:
            time.sleep(8)

    return results


def repurpose_blog_to_pins(blog_content: str, topic: str,
                            niche: str = "general", count: int = 5) -> List[Dict]:
    """
    Extract count pin ideas from a blog post and create them all.
    One blog post → 5 evergreen pins.
    """
    try:
        import json as _json
        from core.llm_client import safe_openai_call
        resp = safe_openai_call(
            messages=[{"role": "user", "content": (
                f"Extract {count} Pinterest pin ideas from this blog post.\n"
                f"Topic: {topic}\nNiche: {niche}\n\n"
                f"Content:\n{blog_content[:3000]}\n\n"
                "For each pin return JSON with: title (max 80 chars), description (max 250 chars).\n"
                "Make titles curiosity-driven with a benefit. Make descriptions SEO-keyword-rich.\n"
                f"Return ONLY a JSON array of {count} objects."
            )}],
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=800,
            temperature=0.75,
            bot_name="pinterest.repurpose",
        )
        raw = resp.choices[0].message.content.strip()
        pins = _json.loads(raw if raw.startswith("[") else raw[raw.find("["):raw.rfind("]") + 1])

        link = _get_niche_affiliate(niche) or CTA_URL
        bid = _get_niche_board(niche)
        results = []

        for i, pin in enumerate(pins[:count]):
            logger.info(f"[Pinterest] Blog→pin {i + 1}/{count}: {pin.get('title', '')[:40]}")
            result = create_pin(
                title=pin.get("title", ""),
                description=pin.get("description", ""),
                link=link, board_id=bid,
            )
            results.append(result)
            if i < len(pins) - 1:
                time.sleep(6)

        return results
    except Exception as e:
        logger.error(f"[Pinterest] repurpose_blog_to_pins failed: {e}")
        return [{"error": str(e)}]


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _generate_pin_content(topic: str, niche: str) -> tuple:
    """Generate a Pinterest title + description for a topic."""
    try:
        from core.llm_client import safe_openai_call
        resp = safe_openai_call(
            messages=[{"role": "user", "content": (
                f"Create a Pinterest pin for: '{topic}' (niche: {niche})\n"
                "Return JSON: {\"title\": \"...\", \"description\": \"...\"}\n"
                "Title: max 80 chars, curiosity-hook with benefit.\n"
                "Description: max 250 chars, SEO keywords, ends with a soft CTA.\n"
                "Output ONLY the JSON."
            )}],
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=200,
            temperature=0.8,
            bot_name="pinterest.pin_content",
        )
        import json as _j
        data = _j.loads(resp.choices[0].message.content.strip())
        return data.get("title", topic), data.get("description", topic)
    except Exception as e:
        logger.warning(f"[Pinterest] _generate_pin_content failed: {e}")
        return topic[:80], topic[:250]


def _generate_pin_image(title: str, description: str) -> Optional[str]:
    """Generate a Pinterest-optimized image with DALL-E 3 (2:3 ratio)."""
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.images.generate(
            model="dall-e-3",
            prompt=(
                f"Pinterest pin image for: {title}. {description[:100]}. "
                "Vertical format, eye-catching, modern design, dark background with purple/cyan "
                "accents, bold typography space, financial/tech aesthetic, high contrast. "
                "Professional infographic style."
            ),
            size="1024x1792",   # Pinterest preferred: 2:3 ratio
            quality="standard",
            n=1,
        )
        url = resp.data[0].url
        logger.info(f"[Pinterest] DALL-E image: {url[:60]}...")
        return url
    except Exception as e:
        logger.warning(f"[Pinterest] DALL-E image failed: {e}")
        return None


def _get_niche_affiliate(niche: str) -> Optional[str]:
    """Return the best affiliate link for a niche."""
    mapping = {
        "crypto": os.getenv("AFFILIATE_COINBASE_URL"),
        "investing": os.getenv("AFFILIATE_WEBULL_URL"),
        "ai_tools": os.getenv("AFFILIATE_JASPER_URL"),
        "passive_income": os.getenv("AFFILIATE_CLICKBANK_URL"),
        "affiliate": os.getenv("AFFILIATE_CONVERTKIT_URL"),
    }
    return mapping.get(niche)


def _get_niche_board(niche: str) -> Optional[str]:
    """Get or create a board for a niche. Returns board ID."""
    board_name = NICHE_BOARDS.get(niche, f"{BRAND} — {niche.title()}")
    if BOARD_ID:
        return BOARD_ID
    try:
        return get_or_create_board(board_name, f"{BRAND} content for {niche}")
    except Exception:
        return None


def get_pinterest() -> "PinterestClient":
    return PinterestClient()


class PinterestClient:
    def is_configured(self) -> bool:
        return is_configured()

    def pin(self, topic: str, niche: str = "general",
            link: str = None) -> Dict:
        return auto_pin_topic(topic, niche=niche, affiliate_link=link)

    def batch(self, topics: List[str], niche: str = "general") -> List[Dict]:
        return auto_pin_batch(topics, niche=niche)
