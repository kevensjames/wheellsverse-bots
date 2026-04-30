#!/usr/bin/env python3
"""Store setup — creates 10 WheellsVerse store products in Stripe.

Idempotent: each product is tagged with metadata {store_key: <slug>} so
re-runs skip anything already created. Writes the resulting payment link
URLs to data/store_payment_links.json, which is what the /store handler
injects into the HTML via %%LINK_*%% placeholders.

Run once on LIVE Stripe:
    python -m core.store_setup
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("store_setup")

LINKS_FILE = ROOT / "data" / "store" / "payment_links.json"


# ── Catalog ──────────────────────────────────────────────────────────────────
# The source of truth for what the store sells. Prices in cents.
# One-time items: recurring=False. Subscriptions: recurring=True.
# store_key is the metadata tag that makes this idempotent.

CATALOG: List[Dict] = [
    # one-time products
    {
        "store_key": "bundle",
        "name": "The AI Income Kit Bundle",
        "description": "Prompt Bible + AI Income Course + Social Templates + Crypto Toolkit + Automation Guide + Resource Vault bonus.",
        "amount_cents": 14900,  # $149 (save $146 vs $295 individual total)
        "recurring": False,
    },
    {
        "store_key": "prompt_bible",
        "name": "The Prompt Bible",
        "description": "10,000 ChatGPT prompts across 20 categories — business, marketing, crypto, productivity.",
        "amount_cents": 4700,  # $47
        "recurring": False,
    },
    {
        "store_key": "ai_course",
        "name": "AI Income Blueprint",
        "description": "5-module course: Make Your First $500 With AI. Includes workbook + video scripts.",
        "amount_cents": 9700,  # $97
        "recurring": False,
    },
    {
        "store_key": "social_templates",
        "name": "Social Media Template Pack",
        "description": "365 days of pre-written Facebook + Instagram posts for AI/income/crypto niches.",
        "amount_cents": 3700,  # $37
        "recurring": False,
    },
    {
        "store_key": "crypto_toolkit",
        "name": "Crypto Starter Toolkit",
        "description": "Exchange comparison, safe investing guide, DeFi yields, portfolio tracker.",
        "amount_cents": 4700,  # $47
        "recurring": False,
    },
    {
        "store_key": "automation_guide",
        "name": "AI Automation Guide",
        "description": "10 automation workflows that save 20+ hours per week. No coding required.",
        "amount_cents": 6700,  # $67
        "recurring": False,
    },
    {
        "store_key": "bot_pack",
        "name": "WheellsVerse Bot Pack (6 months)",
        "description": "6-month access to 110+ AI bots running 24/7. Auto-posts content, generates signals.",
        "amount_cents": 19700,  # $197
        "recurring": False,
    },
    # subscriptions
    {
        "store_key": "crypto_newsletter",
        "name": "Crypto Newsletter",
        "description": "Weekly crypto signals, DeFi yields, Monday market analysis.",
        "amount_cents": 900,  # $9/mo
        "recurring": True,
    },
    {
        "store_key": "inner_circle",
        "name": "WhatsApp Inner Circle",
        "description": "Daily AI income tips, weekly crypto signal, 20-50% off products, direct WhatsApp access, monthly Q&A.",
        "amount_cents": 1900,  # $19/mo
        "recurring": True,
    },
    {
        "store_key": "nexora_beta",
        "name": "NEXORA Creator Platform — Beta",
        "description": "90% revenue share, live streaming, fan subscriptions, instant payouts, AI content tools.",
        "amount_cents": 2900,  # $29/mo
        "recurring": True,
    },
]


def _stripe():
    secret = os.getenv("STRIPE_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    import stripe
    stripe.api_key = secret
    return stripe, "TEST" if secret.startswith(("sk_test", "rk_test")) else "LIVE"


def _find_existing_product(s, store_key: str):
    """Search Stripe for a product already tagged with this store_key."""
    # Stripe search requires the Search API; fall back to listing if unavailable.
    try:
        result = s.Product.search(query=f"metadata['store_key']:'{store_key}' AND active:'true'", limit=1)
        if result.data:
            return result.data[0]
    except Exception:
        for prod in s.Product.list(active=True, limit=100).auto_paging_iter():
            if prod.metadata.get("store_key") == store_key:
                return prod
    return None


def _find_existing_price(s, product_id: str):
    prices = s.Price.list(product=product_id, active=True, limit=1)
    return prices.data[0] if prices.data else None


def _find_existing_payment_link(s, price_id: str, store_key: str):
    # Match by metadata first (fastest), then fall back to scanning line items.
    for lnk in s.PaymentLink.list(active=True, limit=100).auto_paging_iter():
        if lnk.metadata.get("store_key") == store_key:
            return lnk
        try:
            items = s.PaymentLink.list_line_items(lnk.id, limit=5).data
            if any(it.price and it.price.id == price_id for it in items):
                return lnk
        except Exception:
            continue
    return None


def _ensure_product(s, item: Dict):
    existing = _find_existing_product(s, item["store_key"])
    if existing:
        logger.info(f"[{item['store_key']}] product exists: {existing.id}")
        return existing
    prod = s.Product.create(
        name=item["name"],
        description=item["description"],
        metadata={"store_key": item["store_key"], "source": "wheellsverse_store"},
    )
    logger.info(f"[{item['store_key']}] created product: {prod.id}")
    return prod


def _ensure_price(s, product, item: Dict):
    existing = _find_existing_price(s, product.id)
    if existing and existing.unit_amount == item["amount_cents"]:
        logger.info(f"[{item['store_key']}] price exists: {existing.id}")
        return existing
    kwargs = {
        "product": product.id,
        "unit_amount": item["amount_cents"],
        "currency": "usd",
    }
    if item["recurring"]:
        kwargs["recurring"] = {"interval": "month"}
    price = s.Price.create(**kwargs)
    logger.info(f"[{item['store_key']}] created price: {price.id}")
    return price


def _ensure_payment_link(s, price, item: Dict, success_url: str):
    existing = _find_existing_payment_link(s, price.id, item["store_key"])
    if existing:
        logger.info(f"[{item['store_key']}] payment link exists: {existing.url}")
        return existing
    # Propagate store_key to the resulting Checkout Session + PaymentIntent/Subscription
    # so the webhook can read it from session.metadata reliably.
    meta = {"store_key": item["store_key"]}
    link_kwargs = {
        "line_items": [{"price": price.id, "quantity": 1}],
        "after_completion": {"type": "redirect", "redirect": {"url": success_url}},
        "metadata": meta,
    }
    if item["recurring"]:
        link_kwargs["subscription_data"] = {"metadata": meta}
    else:
        link_kwargs["payment_intent_data"] = {"metadata": meta}
    link = s.PaymentLink.create(**link_kwargs)
    logger.info(f"[{item['store_key']}] created payment link: {link.url}")
    return link


def _is_deliverable(item: Dict) -> bool:
    """Only create a Stripe product if the deliverable is ready:
    either a file exists in the repo (core.store_delivery.has_local_deliverable)
    or DELIVERY_URL_<KEY> is set as an env var."""
    try:
        from core.store_delivery import has_local_deliverable
        if has_local_deliverable(item["store_key"]):
            return True
    except Exception:
        pass
    env_var = f"DELIVERY_URL_{item['store_key'].upper()}"
    return bool(os.getenv(env_var, "").strip())


def run(dry_run: bool = False, only: Optional[list] = None) -> Dict[str, str]:
    s, mode = _stripe()
    site = os.getenv("CTA_URL") or os.getenv("PUBLIC_APP_URL") or "https://app.wheellsverse.com"
    logger.warning(f"Stripe mode: {mode}{' (DRY RUN)' if dry_run else ''}")

    selected = [it for it in CATALOG if (not only or it["store_key"] in only) and _is_deliverable(it)]
    skipped = [it["store_key"] for it in CATALOG if it not in selected]
    for sk in skipped:
        logger.info(f"[skip] {sk}: no deliverable (no local file, no DELIVERY_URL_{sk.upper()})")

    if not selected:
        logger.warning("no products selected — nothing to do")
        return {}

    if dry_run:
        for item in selected:
            logger.info(f"[dry] would setup {item['store_key']}: {item['name']} ${item['amount_cents']/100:.2f}{'/mo' if item['recurring'] else ''}")
        return {item["store_key"]: "dry-run" for item in selected}

    links: Dict[str, str] = {}
    for item in selected:
        prod = _ensure_product(s, item)
        price = _ensure_price(s, prod, item)
        success_url = f"{site}/?purchase={item['store_key']}"
        link = _ensure_payment_link(s, price, item, success_url)
        links[item["store_key"]] = link.url

    # Merge with any existing links so re-running for a subset doesn't clobber
    # previously-written entries.
    existing: Dict[str, str] = {}
    if LINKS_FILE.exists():
        try:
            existing = json.loads(LINKS_FILE.read_text())
        except Exception:
            pass
    existing.update(links)
    LINKS_FILE.parent.mkdir(exist_ok=True)
    LINKS_FILE.write_text(json.dumps(existing, indent=2))
    logger.info(f"wrote {len(existing)} links → {LINKS_FILE}")
    return existing


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    dry = "--dry-run" in sys.argv
    only = None
    for i, arg in enumerate(sys.argv):
        if arg == "--only" and i + 1 < len(sys.argv):
            only = [k.strip() for k in sys.argv[i + 1].split(",") if k.strip()]
    try:
        result = run(dry_run=dry, only=only)
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error(f"setup failed: {e}")
        sys.exit(1)
