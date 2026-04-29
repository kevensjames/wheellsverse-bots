#!/usr/bin/env python3
"""
core/click_tracker.py
─────────────────────────────────────────────────────────────────────────────
Affiliate click tracking.

Every affiliate link in published content should route through:
  /go/{partner}   →  logs click  →  302 redirect to real affiliate URL

Supported partners (map to .env keys):
  -- Investing --
  coinbase    → AFFILIATE_COINBASE_URL
  robinhood   → AFFILIATE_ROBINHOOD_URL  (user referral link)
  webull      → AFFILIATE_WEBULL_URL
  binance     → AFFILIATE_BINANCE_URL
  m1finance   → AFFILIATE_M1FINANCE_URL
  public      → AFFILIATE_PUBLIC_URL
  -- Gig economy --
  doordash    → AFFILIATE_DOORDASH_URL
  uber        → AFFILIATE_UBER_URL
  -- Fintech / payments --
  cashapp     → AFFILIATE_CASHAPP_URL
  onepay      → AFFILIATE_ONEPAY_URL
  capitalone  → AFFILIATE_CAPITALONE_URL
  creditone   → AFFILIATE_CREDITONE_URL
  -- Amazon --
  amazon         → AFFILIATE_AMAZON_TAG  (builds search URL)
  amazon_prime   → AFFILIATE_AMAZON_PRIME_URL
  amazon_kindle  → AFFILIATE_AMAZON_KINDLE_URL
  amazon_audible → AFFILIATE_AMAZON_AUDIBLE_URL
  amazon_music   → AFFILIATE_AMAZON_MUSIC_URL
  amazon_fresh   → AFFILIATE_AMAZON_FRESH_URL
  amazon_kids    → AFFILIATE_AMAZON_KIDS_URL
  amazon_business→ AFFILIATE_AMAZON_BUSINESS_URL
  amazon_photos  → AFFILIATE_AMAZON_PHOTOS_URL
  amazon_halo    → AFFILIATE_AMAZON_HALO_URL
  amazon_rx      → AFFILIATE_AMAZON_RX_URL
  amazon_gaming  → AFFILIATE_AMAZON_GAMING_URL
  amazon_pets    → AFFILIATE_AMAZON_PETS_URL
  amazon_wedding → AFFILIATE_AMAZON_WEDDING_URL
  -- Other --
  convertkit  → AFFILIATE_CONVERTKIT_URL
  jasper      → AFFILIATE_JASPER_URL
  bluehost    → AFFILIATE_BLUEHOST_URL
  fiverr      → AFFILIATE_FIVERR_URL
  clickbank   → AFFILIATE_CLICKBANK_URL
  appsumo     → AFFILIATE_APPSUMO_URL
  shareasale  → AFFILIATE_SHAREASALE_URL
  partnerstack→ AFFILIATE_PARTNERSTACK_URL
  cj          → AFFILIATE_CJ_URL

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
CONVERSIONS_FILE = ROOT / "data" / "conversions.json"

# ── Partner → destination URL ─────────────────────────────────────────────────


def _affiliate_urls() -> Dict[str, str]:
    """Read affiliate URLs from .env at call time (supports hot-reload)."""
    amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
    amazon_tag_2 = os.getenv("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")
    return {
        # Investing
        "coinbase":        os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com"),
        "robinhood":       os.getenv("AFFILIATE_ROBINHOOD_URL", "https://robinhood.com"),
        "webull":          os.getenv("AFFILIATE_WEBULL_URL", "https://www.webull.com/partner"),
        "binance":         os.getenv("AFFILIATE_BINANCE_URL", "https://binance.com"),
        "m1finance":       os.getenv("AFFILIATE_M1FINANCE_URL", "https://m1.com"),
        "public":          os.getenv("AFFILIATE_PUBLIC_URL", "https://public.com"),
        # Gig economy
        "doordash":        os.getenv("AFFILIATE_DOORDASH_URL", "https://doordash.com"),
        "uber":            os.getenv("AFFILIATE_UBER_URL", "https://uber.com"),
        # Fintech / payments
        "cashapp":         os.getenv("AFFILIATE_CASHAPP_URL", "https://cash.app"),
        "onepay":          os.getenv("AFFILIATE_ONEPAY_URL", "https://onepay.com"),
        "capitalone":      os.getenv("AFFILIATE_CAPITALONE_URL", "https://capitalone.com"),
        "creditone":       os.getenv("AFFILIATE_CREDITONE_URL", "https://creditonebank.com"),
        # Amazon search
        "amazon":          f"https://www.amazon.com/s?k=passive+income&tag={amazon_tag}",
        "amazon_video":    os.getenv("AFFILIATE_AMAZON_VIDEO_URL", f"https://www.amazon.com/gp/video/storefront?tag={amazon_tag_2}"),
        # Amazon subscription bounties
        "amazon_prime":    os.getenv("AFFILIATE_AMAZON_PRIME_URL", ""),
        "amazon_kindle":   os.getenv("AFFILIATE_AMAZON_KINDLE_URL", ""),
        "amazon_audible":  os.getenv("AFFILIATE_AMAZON_AUDIBLE_URL", ""),
        "amazon_music":    os.getenv("AFFILIATE_AMAZON_MUSIC_URL", ""),
        "amazon_fresh":    os.getenv("AFFILIATE_AMAZON_FRESH_URL", ""),
        "amazon_kids":     os.getenv("AFFILIATE_AMAZON_KIDS_URL", ""),
        "amazon_business": os.getenv("AFFILIATE_AMAZON_BUSINESS_URL", ""),
        "amazon_photos":   os.getenv("AFFILIATE_AMAZON_PHOTOS_URL", ""),
        "amazon_halo":     os.getenv("AFFILIATE_AMAZON_HALO_URL", ""),
        "amazon_rx":       os.getenv("AFFILIATE_AMAZON_RX_URL", ""),
        "amazon_gaming":   os.getenv("AFFILIATE_AMAZON_GAMING_URL", ""),
        "amazon_pets":     os.getenv("AFFILIATE_AMAZON_PETS_URL", ""),
        "amazon_wedding":  os.getenv("AFFILIATE_AMAZON_WEDDING_URL", ""),
        # Other
        "convertkit":      os.getenv("AFFILIATE_CONVERTKIT_URL", "https://convertkit.com"),
        "jasper":          os.getenv("AFFILIATE_JASPER_URL", "https://jasper.ai"),
        "bluehost":        os.getenv("AFFILIATE_BLUEHOST_URL", "https://bluehost.com"),
        "fiverr":          os.getenv("AFFILIATE_FIVERR_URL", "https://fiverr.com"),
        "clickbank":       os.getenv("AFFILIATE_CLICKBANK_URL", "https://clickbank.com"),
        "appsumo":         os.getenv("AFFILIATE_APPSUMO_URL", "https://appsumo.com"),
        "shareasale":      os.getenv("AFFILIATE_SHAREASALE_URL", "https://shareasale.com"),
        "partnerstack":    os.getenv("AFFILIATE_PARTNERSTACK_URL", "https://partnerstack.com"),
        "cj":              os.getenv("AFFILIATE_CJ_URL", "https://www.cj.com"),
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

    convs = _load_conversions()
    conv_counts: Dict[str, int] = {}
    revenue_by_partner: Dict[str, float] = {}
    for c in convs:
        p = c.get("partner", "unknown")
        conv_counts[p] = conv_counts.get(p, 0) + 1
        revenue_by_partner[p] = revenue_by_partner.get(p, 0.0) + float(c.get("amount_usd", 0) or 0)

    return {
        "total_clicks": len(clicks),
        "by_partner": counts,
        "recent": clicks[-20:][::-1],   # last 20, newest first
        "total_conversions": len(convs),
        "conversions_by_partner": conv_counts,
        "revenue_by_partner_usd": revenue_by_partner,
        "total_revenue_usd": sum(revenue_by_partner.values()),
    }


# ── Conversion attribution ────────────────────────────────────────────────────

def _load_conversions() -> List[Dict]:
    if CONVERSIONS_FILE.exists():
        try:
            return json.loads(CONVERSIONS_FILE.read_text())
        except Exception:
            return []
    return []


def _save_conversions(convs: List[Dict]):
    CONVERSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONVERSIONS_FILE.write_text(json.dumps(convs, indent=2))


def record_conversion(
    partner: str = "",
    amount_usd: float = 0.0,
    customer_email: str = "",
    source: str = "stripe",
    external_id: str = "",
    attributed_click_window_hours: int = 72,
) -> Dict:
    """
    Log a conversion (Stripe payment, affiliate postback, etc.) and attribute it
    to the most recent matching click within the lookback window.

    Args:
        partner: known partner key (e.g. 'coinbase'). Empty = attribute by recency only.
        amount_usd: revenue dollars (Stripe amount/100).
        customer_email: optional, used to match clicks if click logged email.
        source: 'stripe' | 'shopify' | 'cj' | 'shareasale' | manual id.
        external_id: idempotency key — same external_id won't double-count.
        attributed_click_window_hours: how far back to look for matching click.
    """
    convs = _load_conversions()
    if external_id and any(c.get("external_id") == external_id for c in convs):
        logger.info(f"Conversion {external_id} already recorded — skipping")
        return {"status": "duplicate", "external_id": external_id}

    clicks = _load_clicks()
    cutoff_iso = (datetime.utcnow().timestamp() - attributed_click_window_hours * 3600)
    attributed_click = None
    for click in reversed(clicks):
        try:
            click_ts = datetime.fromisoformat(click["ts"].rstrip("Z")).timestamp()
        except (KeyError, ValueError):
            continue
        if click_ts < cutoff_iso:
            break
        if partner and click.get("partner") != partner.lower():
            continue
        attributed_click = click
        break

    conv = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "partner": partner.lower() or (attributed_click or {}).get("partner", "unknown"),
        "amount_usd": round(float(amount_usd or 0), 2),
        "customer_email": customer_email,
        "source": source,
        "external_id": external_id,
        "attributed_click_ts": (attributed_click or {}).get("ts"),
        "attributed_click_referrer": (attributed_click or {}).get("referrer"),
    }
    convs.append(conv)
    _save_conversions(convs)
    logger.info(
        f"Conversion: {conv['partner']} ${conv['amount_usd']:.2f} "
        f"(attributed={'yes' if attributed_click else 'no'})"
    )

    try:
        from core.telegram import notify_conversion  # type: ignore
        notify_conversion(partner=conv["partner"], amount=conv["amount_usd"])
    except Exception:
        pass

    return {"status": "recorded", **conv}


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
