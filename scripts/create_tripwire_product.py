#!/usr/bin/env python3
"""
scripts/create_tripwire_product.py
─────────────────────────────────────────────────────────────────────────────
Creates the AI Stock Alerts $7 Starter tripwire on Shopify.

What this builds:
  - Shopify product titled "AI Stock Alerts — 30-day Starter ($7)"
  - Price: $7 USD
  - Digital deliverable: top_5_ai_tools_2026.pdf (auto-emailed via orders/paid)
  - Tags: tripwire, ai-stock-alerts, starter
  - Auto-tags buyers in ConvertKit as "tripwire-buyer" (already wired in
    core/api.py orders/paid handler)

What you do AFTER running this (one-time, in ConvertKit UI):
  1. Create a sequence "Tripwire → Subscription upsell" with these emails:
     - Day 0:  "Your AI Tools roundup + how to activate your 30-day trial"
     - Day 7:  "Your first week — 3 wins from this week's signals"
     - Day 21: "Heads up: your trial ends in 7 days"
     - Day 27: "Final 24h — lock in $19/mo for life (price goes up Jan 1)"
  2. Trigger: subscriber tagged "tripwire-buyer"

Idempotent: re-running returns the existing product if titled match found.

Usage:
  python3 scripts/create_tripwire_product.py
  python3 scripts/create_tripwire_product.py --dry-run
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

TRIPWIRE_TITLE = "AI Stock Alerts — 30-day Starter ($7)"
TRIPWIRE_PRICE = 7.00
TRIPWIRE_BODY_HTML = """
<p><strong>Your fast lane into AI Stock Alerts.</strong></p>
<p>Get the WheellsVerse <em>Top 5 AI Tools 2026</em> PDF instantly — and unlock 30 days of our paid AI Stock Alerts subscription as a no-card-required taste test.</p>
<h3>What you get</h3>
<ul>
  <li><strong>Top 5 AI Tools 2026 PDF</strong> — the same roundup we charge for separately</li>
  <li><strong>30 days of AI Stock Alerts</strong> — daily signals delivered to email + private Telegram group</li>
  <li><strong>Lifetime grandfathered pricing</strong> — if you upgrade after 30 days, you lock in $19/mo for life (price goes to $29/mo for new members on Jan 1)</li>
</ul>
<h3>How it works</h3>
<ol>
  <li>Pay $7 — confirmation email arrives within 60 seconds</li>
  <li>Your PDF + Telegram invite link arrive in that email</li>
  <li>You get daily AI-curated trade signals for 30 days</li>
  <li>On day 27 you'll get a one-tap upgrade link if you want to keep going</li>
</ol>
<p><em>Educational content. Not financial advice. No refunds on digital downloads, but cancel any time before day 30 to avoid the upsell.</em></p>
"""
TRIPWIRE_TAGS = ["tripwire", "ai-stock-alerts", "starter", "$7", "digital", "viral"]
DIGITAL_KEYWORDS_TO_ADD = ["ai stock alerts — 30-day starter", "30-day starter", "ai stock alerts starter"]


def find_existing(title: str) -> dict | None:
    """Use the canonical narai_shopify_engine GET-by-title pattern."""
    try:
        from core.narai_shopify_engine import _shopify_request  # type: ignore
    except Exception as e:
        print(f"Cannot import narai_shopify_engine: {e}", file=sys.stderr)
        return None
    import urllib.parse
    q = urllib.parse.quote(title, safe="")
    resp = _shopify_request("GET", f"products.json?title={q}&limit=5")
    products = resp.get("products", []) if isinstance(resp, dict) else []
    return products[0] if products else None


def verify_digital_map_covers_tripwire() -> bool:
    """Ensure SHOPIFY_DIGITAL_MAP has a keyword that matches TRIPWIRE_TITLE."""
    from core.store_delivery import _find_shopify_match
    return _find_shopify_match(TRIPWIRE_TITLE) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    args = parser.parse_args()

    # 0. Sanity: digital fulfillment must be wired
    if not verify_digital_map_covers_tripwire():
        print(
            "!! SHOPIFY_DIGITAL_MAP in core/store_delivery.py has no keyword that\n"
            "   matches the tripwire title. The product would be sold but the\n"
            f"   PDF wouldn't auto-deliver.\n   Add an entry with keywords like {DIGITAL_KEYWORDS_TO_ADD}\n"
            "   pointing to top_5_ai_tools_2026.pdf, then re-run.",
            file=sys.stderr,
        )
        return 2

    # 1. Dedup check
    existing = find_existing(TRIPWIRE_TITLE)
    if existing:
        print(json.dumps({
            "status": "already_exists",
            "product_id": existing.get("id"),
            "handle": existing.get("handle"),
            "url_hint": f"/products/{existing.get('handle')}",
        }, indent=2))
        return 0

    if args.dry_run:
        print(json.dumps({
            "status": "would_create",
            "title": TRIPWIRE_TITLE,
            "price": TRIPWIRE_PRICE,
            "tags": TRIPWIRE_TAGS,
        }, indent=2))
        return 0

    # 2. Create
    from core.shopify_client import create_product
    result = create_product(
        title=TRIPWIRE_TITLE,
        description=TRIPWIRE_BODY_HTML,
        price=TRIPWIRE_PRICE,
        product_type="Digital",
        tags=TRIPWIRE_TAGS,
        requires_shipping=False,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
