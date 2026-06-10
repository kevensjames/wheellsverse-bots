#!/usr/bin/env python3
"""Idempotent Stripe products setup for SiteBoost AI.

Creates (or confirms existing):
    1. Product "SiteBoost Site" + Price $497 one-time + Payment Link
    2. Product "SiteBoost Maintenance" + Price $49/month recurring + Payment Link
    3. Optional: $250 photography add-on, $147 logo add-on, $97 extra-page add-on

Writes the resulting payment-link URLs to:
    data/launches/siteboost/stripe_payment_links.json

Uses metadata {store_key: <slug>, brand: "siteboost"} so re-runs are
idempotent and the webhook can route post-payment events correctly.

Usage:
    export STRIPE_API_KEY=sk_live_...     # or sk_test_... for sandbox
    python scripts/siteboost_stripe_setup.py
    # Or sandbox/dry-run:
    python scripts/siteboost_stripe_setup.py --dry-run
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINKS_FILE = ROOT / "data" / "launches" / "siteboost" / "stripe_payment_links.json"
logger = logging.getLogger("siteboost.stripe_setup")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Same brand tagging used by the wheellsverse store_setup.py — keeps the
# webhook routing consistent across both product lines.
CATALOG = [
    {
        "store_key": "siteboost_site",
        "name": "SiteBoost Site",
        "description": "Custom website for your local business. Live in 48 hours. Includes setup, mobile-first design, Google Maps integration, and email forwarding.",
        "amount_cents": 49700,    # $497.00
        "currency": "usd",
        "recurring": None,         # one-time
        "success_url": "https://hello.wheellsverse.com/intake?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_maintenance",
        "name": "SiteBoost Maintenance",
        "description": "Hosting + ongoing tweaks (new hours, photos, holiday updates). Cancel anytime.",
        "amount_cents": 4900,      # $49.00
        "currency": "usd",
        "recurring": {"interval": "month"},
        "success_url": "https://hello.wheellsverse.com/welcome?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_extra_page",
        "name": "SiteBoost — Extra Page",
        "description": "Add a custom page to your existing SiteBoost site (menu, contact form, gallery, etc.).",
        "amount_cents": 9700,
        "currency": "usd",
        "recurring": None,
        "success_url": "https://hello.wheellsverse.com/thanks?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_photography",
        "name": "SiteBoost — Custom Photography",
        "description": "Professional photo shoot for your business (subcontracted to local freelancer).",
        "amount_cents": 25000,
        "currency": "usd",
        "recurring": None,
        "success_url": "https://hello.wheellsverse.com/thanks?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_logo",
        "name": "SiteBoost — Logo Design",
        "description": "Custom logo for your business — delivered in 3 variations within 72 hours.",
        "amount_cents": 14700,
        "currency": "usd",
        "recurring": None,
        "success_url": "https://hello.wheellsverse.com/thanks?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_rush_24h",
        "name": "SiteBoost — Rush Delivery (24h)",
        "description": "Site delivered in 24 hours instead of 48. Add-on to a SiteBoost Site purchase.",
        "amount_cents": 19700,
        "currency": "usd",
        "recurring": None,
        "success_url": "https://hello.wheellsverse.com/thanks?customer={CHECKOUT_SESSION_ID}",
    },
    {
        "store_key": "siteboost_annual_maintenance",
        "name": "SiteBoost — Annual Maintenance",
        "description": "12 months of hosting + maintenance prepaid. Save $89 vs monthly.",
        "amount_cents": 49900,
        "currency": "usd",
        "recurring": None,
        "success_url": "https://hello.wheellsverse.com/welcome?customer={CHECKOUT_SESSION_ID}",
    },
]


def _stripe_or_die():
    try:
        import stripe
    except ImportError:
        logger.error("stripe SDK not installed. Run: pip install stripe")
        sys.exit(1)
    k = os.getenv("STRIPE_API_KEY", "").strip() or os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not k:
        logger.error("STRIPE_API_KEY not set. Either set it, or pass --dry-run.")
        sys.exit(1)
    stripe.api_key = k
    return stripe


def _find_existing_product(s, store_key: str):
    """Match by metadata['store_key']. Fall back to listing if Search API unavailable."""
    try:
        res = s.Product.search(query=f"metadata['store_key']:'{store_key}' AND active:'true'", limit=1)
        if res.data:
            return res.data[0]
    except Exception as e:
        logger.debug(f"Search API unavailable, falling back to list: {e}")
    for prod in s.Product.list(active=True, limit=100).auto_paging_iter():
        if prod.metadata.get("store_key") == store_key:
            return prod
    return None


def _find_existing_price(s, product_id: str, amount: int, currency: str, recurring: dict | None):
    """Match by product + amount + recurring interval."""
    for price in s.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        if price.unit_amount != amount or price.currency != currency:
            continue
        rec = price.recurring
        if recurring and rec and rec.interval == recurring.get("interval"):
            return price
        if not recurring and not rec:
            return price
    return None


def _find_existing_payment_link(s, price_id: str, store_key: str):
    for lnk in s.PaymentLink.list(active=True, limit=100).auto_paging_iter():
        if lnk.metadata.get("store_key") == store_key:
            return lnk
    return None


def _ensure(s, item: dict, dry_run: bool) -> dict:
    """Create-or-find product + price + payment-link. Returns dict with all three URLs/IDs."""
    if dry_run:
        return {
            "store_key": item["store_key"],
            "product_id": f"prod_DRY_{item['store_key']}",
            "price_id": f"price_DRY_{item['store_key']}",
            "payment_link_url": f"https://buy.stripe.com/DRY_{item['store_key']}",
            "amount_usd": item["amount_cents"] / 100,
            "recurring": bool(item.get("recurring")),
        }

    prod = _find_existing_product(s, item["store_key"])
    if prod:
        logger.info(f"[{item['store_key']}] product exists: {prod.id}")
    else:
        prod = s.Product.create(
            name=item["name"],
            description=item["description"],
            metadata={"store_key": item["store_key"], "brand": "siteboost"},
        )
        logger.info(f"[{item['store_key']}] created product: {prod.id}")

    price = _find_existing_price(s, prod.id, item["amount_cents"], item["currency"], item.get("recurring"))
    if price:
        logger.info(f"[{item['store_key']}] price exists: {price.id}")
    else:
        kwargs = {
            "product": prod.id,
            "unit_amount": item["amount_cents"],
            "currency": item["currency"],
        }
        if item.get("recurring"):
            kwargs["recurring"] = item["recurring"]
        price = s.Price.create(**kwargs)
        logger.info(f"[{item['store_key']}] created price: {price.id}")

    link = _find_existing_payment_link(s, price.id, item["store_key"])
    if link:
        logger.info(f"[{item['store_key']}] payment link exists: {link.url}")
    else:
        link_kwargs = {
            "line_items": [{"price": price.id, "quantity": 1}],
            "metadata": {"store_key": item["store_key"], "brand": "siteboost"},
            "after_completion": {
                "type": "redirect",
                "redirect": {"url": item["success_url"]},
            },
        }
        if not item.get("recurring"):
            link_kwargs["payment_intent_data"] = {
                "metadata": {"store_key": item["store_key"], "brand": "siteboost"},
            }
        else:
            link_kwargs["subscription_data"] = {
                "metadata": {"store_key": item["store_key"], "brand": "siteboost"},
            }
        link = s.PaymentLink.create(**link_kwargs)
        logger.info(f"[{item['store_key']}] created payment link: {link.url}")

    return {
        "store_key": item["store_key"],
        "product_id": prod.id,
        "price_id": price.id,
        "payment_link_url": link.url,
        "amount_usd": item["amount_cents"] / 100,
        "recurring": bool(item.get("recurring")),
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be created, write fake URLs, no API calls")
    args = p.parse_args()

    s = None if args.dry_run else _stripe_or_die()
    results = []
    for item in CATALOG:
        results.append(_ensure(s, item, dry_run=args.dry_run))

    LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINKS_FILE.write_text(json.dumps({
        "_meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": args.dry_run,
            "n_products": len(results),
        },
        "products": {r["store_key"]: r for r in results},
    }, indent=2))
    logger.info(f"Wrote {LINKS_FILE}")

    # Pretty print for terminal
    print("\n" + "="*70)
    print("SiteBoost Stripe Setup — Summary")
    print("="*70)
    for r in results:
        rec = "/mo" if r["recurring"] else " one-time"
        print(f"  ${r['amount_usd']:>7.2f}{rec:>10}  ·  {r['store_key']:<32}  ·  {r['payment_link_url']}")
    print("="*70 + "\n")
    if args.dry_run:
        print("  ⚠ DRY-RUN — no Stripe products were actually created.")
        print("    Re-run without --dry-run after setting STRIPE_API_KEY.\n")


if __name__ == "__main__":
    main()
