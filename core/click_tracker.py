#!/usr/bin/env python3
"""
core/click_tracker.py
─────────────────────────────────────────────────────────────────────────────
Product click tracking.

OLD: this module mapped each network partner key to a per-network affiliate
URL pulled from .env. The enumeration of partner→env_key pairs was preserved
here as documentation. That mapping has been collapsed.

NEW (affiliate_swap_2026_05_29):
Every partner key resolves to DIGITAL_PRODUCT_URL with UTM tagging by
partner key. .env values are preserved on disk but no longer consumed at
this layer. The 'insider' owned-funnel entry is the only env-backed entry.

Click log: data/clicks.json
Conversion log: data/conversions.json
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

# ── Partner key → destination URL ────────────────────────────────────────────

# OLD: each known partner mapped to its own .env-backed network affiliate URL.
# NEW (affiliate_swap_2026_05_29): every partner key resolves to
# DIGITAL_PRODUCT_URL with UTM content = partner key. The owned 'insider'
# funnel still resolves to AFFILIATE_INSIDER_URL.

DIGITAL_PRODUCT_URL = "https://stan.store/Wheellsverse"


def _stan(partner: str, source: str = "click_tracker", medium: str = "redirect") -> str:
    """Build a UTM-tagged redirect URL to the owned digital product."""
    return (
        f"{DIGITAL_PRODUCT_URL}"
        f"?utm_source={source}"
        f"&utm_medium={medium}"
        f"&utm_campaign=affiliate_swap_2026_05_29"
        f"&utm_content={partner}"
    )


def _affiliate_urls() -> Dict[str, str]:
    """Return partner_key → destination URL map.

    Only the owned-funnel 'insider' key is env-backed. All other partner keys
    are resolved on demand via _resolve_destination().
    """
    base_app_url = os.getenv("APP_BASE_URL", "https://app.wheellsverse.com").rstrip("/")
    return {
        "insider": os.getenv("AFFILIATE_INSIDER_URL", f"{base_app_url}/insider"),
    }


def _resolve_destination(partner: str) -> str:
    """Resolve any partner key to its destination URL.

    'insider' → owned funnel. Anything else → DIGITAL_PRODUCT_URL with
    utm_content = partner key.
    """
    partner_key = partner.lower()
    urls = _affiliate_urls()
    if partner_key in urls:
        return urls[partner_key]
    return _stan(partner_key)


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

    OLD: returned None for partners not in the legacy dict.
    NEW: every partner key now resolves via _resolve_destination, which
    routes non-insider keys to DIGITAL_PRODUCT_URL with UTM tagging.
    """
    dest = _resolve_destination(partner)
    if not dest:
        logger.warning(f"Could not resolve partner: {partner!r}")
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
