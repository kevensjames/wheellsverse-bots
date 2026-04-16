#!/usr/bin/env python3
"""
core/click_tracker.py
─────────────────────────────────────────────────────────────────────────────
Affiliate click tracking.

Every affiliate link in published content should route through:
  /go/{partner}   →  logs click  →  302 redirect to real affiliate URL

Supported partners (map to .env keys):
  coinbase    → AFFILIATE_COINBASE_URL
  robinhood   → AFFILIATE_ROBINHOOD_URL
  binance     → AFFILIATE_BINANCE_URL
  amazon      → AFFILIATE_AMAZON_TAG  (builds search URL)
  convertkit  → AFFILIATE_CONVERTKIT_URL
  jasper      → AFFILIATE_JASPER_URL
  bluehost    → AFFILIATE_BLUEHOST_URL
  fiverr      → AFFILIATE_FIVERR_URL
  clickbank   → AFFILIATE_CLICKBANK_URL
  appsumo     → AFFILIATE_APPSUMO_URL

Click log: data/clicks.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("click_tracker")

CLICKS_FILE = ROOT / "data" / "clicks.json"

# ── Partner → destination URL ─────────────────────────────────────────────────


def _affiliate_urls() -> Dict[str, str]:
    """Read affiliate URLs from .env at call time (supports hot-reload)."""
    amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
    amazon_tag_2 = os.getenv("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")
    return {
        "coinbase": os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com"),
        "robinhood": os.getenv("AFFILIATE_ROBINHOOD_URL", "https://robinhood.com"),
        "binance": os.getenv("AFFILIATE_BINANCE_URL", "https://binance.com"),
        "amazon": f"https://www.amazon.com/s?k=passive+income&tag={amazon_tag}",
        "amazon_video": os.getenv("AFFILIATE_AMAZON_VIDEO_URL", f"https://www.amazon.com/gp/video/storefront?tag={amazon_tag_2}"),
        "convertkit": os.getenv("AFFILIATE_CONVERTKIT_URL", "https://convertkit.com"),
        "jasper": os.getenv("AFFILIATE_JASPER_URL", "https://jasper.ai"),
        "bluehost": os.getenv("AFFILIATE_BLUEHOST_URL", "https://bluehost.com"),
        "fiverr": os.getenv("AFFILIATE_FIVERR_URL", "https://fiverr.com"),
        "clickbank": os.getenv("AFFILIATE_CLICKBANK_URL", "https://clickbank.com"),
        "appsumo": os.getenv("AFFILIATE_APPSUMO_URL", "https://appsumo.com"),
    }


# ── Click log helpers ─────────────────────────────────────────────────────────

def _load_clicks() -> List[Dict]:
    if CLICKS_FILE.exists():
        try:
            return json.loads(CLICKS_FILE.read_text())
        except Exception:
            return []
    return []


def _save_clicks(clicks: List[Dict]):
    CLICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLICKS_FILE.write_text(json.dumps(clicks, indent=2))


# ── Public API ────────────────────────────────────────────────────────────────

def record_click(partner: str, referrer: str = "", ip: str = "") -> Optional[str]:
    """
    Log a click and return the destination URL.
    Returns None if partner is unknown.
    """
    urls = _affiliate_urls()
    dest = urls.get(partner.lower())
    if not dest:
        logger.warning(f"Unknown affiliate partner: {partner!r}")
        return None

    click = {
        "partner": partner.lower(),
        "ts": datetime.utcnow().isoformat() + "Z",
        "referrer": referrer,
        "ip": ip,
        "dest": dest,
    }

    clicks = _load_clicks()
    clicks.append(click)
    _save_clicks(clicks)
    total = len(clicks)
    logger.info(f"Click recorded: {partner} (total={total})")

    # Telegram alert (silent — high frequency)
    try:
        from core.telegram import notify_click
        notify_click(partner=partner, total_today=total)
    except Exception:
        pass

    return dest


def get_stats() -> Dict:
    """Return click counts per partner and recent clicks."""
    clicks = _load_clicks()
    counts: Dict[str, int] = {}
    for c in clicks:
        counts[c["partner"]] = counts.get(c["partner"], 0) + 1

    return {
        "total_clicks": len(clicks),
        "by_partner": counts,
        "recent": clicks[-20:][::-1],   # last 20, newest first
    }


def tracking_url(partner: str, base_url: str = "") -> str:
    """
    Return the /go/{partner} tracking URL.
    base_url defaults to the CTA_URL host or localhost.
    """
    host = base_url or os.getenv("CTA_URL", "http://localhost:5050").rstrip("/")
    # Strip path from CTA_URL — we only want the host
    from urllib.parse import urlparse
    parsed = urlparse(host)
    host = f"{parsed.scheme}://{parsed.netloc}"
    return f"{host}/go/{partner}"


def inject_tracking_links(html: str, base_url: str = "") -> str:
    """
    Replace raw affiliate URLs in HTML with /go/{partner} tracking URLs.
    Safe to call on already-published HTML to upgrade it in place.
    """
    urls = _affiliate_urls()
    for partner, dest in urls.items():
        if dest and dest in html:
            track = tracking_url(partner, base_url)
            html = html.replace(dest, track)
    return html
