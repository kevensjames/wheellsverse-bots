#!/usr/bin/env python3
"""
core/narai_catalog.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Money-Maker Catalog — 8 ready-to-launch products.

Wired to the existing NarAI Shopify engine with the hard quality gate.
Every product goes through: draft-first → DALL-E cover → gate → activate.
Products that fail the gate stay as DRAFT for manual review.

CLI:
  python3 -m core.narai_catalog list
  python3 -m core.narai_catalog one ai_stock_alerts
  python3 -m core.narai_catalog all
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

log = logging.getLogger("narai_catalog")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ─── CATALOG ──────────────────────────────────────────────────────────────────

CATALOG = {
    # ── Subscriptions (recurring revenue) ───────────────────────────────────
    "ai_stock_alerts": {
        "kind": "digital",
        "title": "AI Stock + Crypto Alerts — $19/month",
        "tagline": "AI-generated trading signals at 7am EST. Entry zones, exits, market briefings.",
        "price": 19.00,
        "product_type": "Subscription",
        "tags": "ai, trading, stocks, crypto, alerts, signals, subscription, passive",
        "seo_title": "AI Stock + Crypto Alerts Club — Daily Signals at 7am EST",
        "seo_description": "Backtested AI trading signals, entry/exit zones, morning market briefings. Cancel anytime.",
        "cover_prompt": "dark cinematic financial trading dashboard, neon candlestick charts, "
                        "AI signal overlays, moody 4k, premium fintech aesthetic",
        "body_html": (
            "<p><strong>Stop gambling. Start trading with an edge.</strong></p>"
            "<p>Every morning at 7am EST, you get:</p>"
            "<ul>"
            "<li>✓ 3–5 AI-scored trading signals (stocks + crypto)</li>"
            "<li>✓ Entry zones, stop-loss, and profit targets</li>"
            "<li>✓ Morning market briefing — what moved, what's next</li>"
            "<li>✓ Weekly portfolio review and rebalance suggestions</li>"
            "<li>✓ Discord community access with live alerts</li>"
            "</ul>"
            "<p>Backtested models. Real math. No hype. Cancel anytime.</p>"
            "<p><em>Built by NarAI — the WheellsVerse AI trading engine.</em></p>"
        ),
    },
    "narai_pro": {
        "kind": "digital",
        "title": "NarAI Pro — AI Trading Assistant",
        "tagline": "Personal AI trading assistant with voice control and cross-session memory.",
        "price": 49.00,
        "product_type": "Subscription",
        "tags": "ai, narai, trading, voice-assistant, subscription, pro, premium",
        "seo_title": "NarAI Pro — Your Personal AI Trading Assistant ($49/mo)",
        "seo_description": "Real-time AI analysis, predictive signals, voice commands, persistent memory. For serious traders.",
        "cover_prompt": "futuristic AI assistant interface, holographic trading charts, "
                        "voice waveform visualization, dark neon aesthetic, premium product shot",
        "body_html": (
            "<p><strong>An AI that remembers every trade you make.</strong></p>"
            "<p>NarAI Pro is your private trading co-pilot:</p>"
            "<ul>"
            "<li>✓ Real-time market analysis (stocks, crypto, forex)</li>"
            "<li>✓ Predictive signals tuned to your risk profile</li>"
            "<li>✓ Voice commands — ask about any ticker, any timeframe</li>"
            "<li>✓ Persistent memory across every session</li>"
            "<li>✓ Priority API access (Claude Opus + GPT-4o)</li>"
            "</ul>"
            "<p>Built for active traders, quants, and AI power-users who need more than a chatbot.</p>"
        ),
    },
    "narai_elite": {
        "kind": "digital",
        "title": "NarAI Elite — Autonomous Trading Agent",
        "tagline": "Fully autonomous AI trading agent with auto-execution and 24/7 monitoring.",
        "price": 149.00,
        "product_type": "Subscription",
        "tags": "ai, narai, trading, autonomous, elite, premium, 24-7, institutional",
        "seo_title": "NarAI Elite — Autonomous AI Trading Agent ($149/mo)",
        "seo_description": "Auto-execution, risk management, portfolio optimization, 24/7 monitoring. For portfolios 50k+.",
        "cover_prompt": "elite private command center, multi-monitor trading setup, AI autonomous agent "
                        "holographic interface, cinematic dark blue lighting, luxury tech aesthetic",
        "body_html": (
            "<p><strong>The AI that trades while you sleep.</strong></p>"
            "<p>NarAI Elite is a fully autonomous trading agent:</p>"
            "<ul>"
            "<li>✓ Auto-execution via Alpaca, Coinbase, and Interactive Brokers</li>"
            "<li>✓ Built-in risk management and drawdown protection</li>"
            "<li>✓ Portfolio optimization rebalanced daily</li>"
            "<li>✓ 24/7 monitoring with push alerts on edge events</li>"
            "<li>✓ Direct Slack/Telegram support channel</li>"
            "<li>✓ Monthly 1-on-1 strategy call</li>"
            "</ul>"
            "<p>Built for traders managing $50k+. Every signal is logged. Every trade is auditable.</p>"
        ),
    },

    # ── Ebooks (digital, high margin) ────────────────────────────────────────
    "bloodline_vol1": {
        "kind": "digital",
        "title": "Bloodline Awakening Vol 1 — Dark Vampire Novel",
        "tagline": "Dark vampire fiction by J.K. Blaze. 20 chapters of power, blood, and betrayal.",
        "price": 9.99,
        "product_type": "Ebook",
        "tags": "ebook, fiction, vampire, dark-fantasy, jk-blaze, bloodline, digital-download",
        "seo_title": "Bloodline Awakening Vol 1 — Dark Vampire Novel by J.K. Blaze",
        "seo_description": "20 chapters of dark vampire fiction. Power, blood, betrayal. For readers tired of sparkly vampires.",
        "cover_prompt": "dark vampire novel book cover, gothic cathedral at night, blood-red moon, "
                        "silhouette figure in black cloak, cinematic horror aesthetic, premium book cover art",
        "body_html": (
            "<p><strong>Forget the sparkly vampires. This one bites back.</strong></p>"
            "<p>Follow Alex Caarter — a man whose bloodline awakens something ancient, brutal, and patient.</p>"
            "<ul>"
            "<li>✓ 20 full chapters (100k+ words)</li>"
            "<li>✓ Dark urban fantasy with horror edges</li>"
            "<li>✓ Morally grey protagonist. No chosen ones.</li>"
            "<li>✓ DRM-free PDF + EPUB + MOBI delivery</li>"
            "<li>✓ Bonus: character art + behind-the-scenes notes</li>"
            "</ul>"
            "<p>For readers who want fiction with teeth. Written by J.K. Blaze.</p>"
        ),
    },
    "seven_circles_ebook": {
        "kind": "digital",
        "title": "Seven Circles — Dark Fiction Series Vol 1",
        "tagline": "A 29-year-old walks through seven layers of hell. Psychological horror meets moral reckoning.",
        "price": 12.99,
        "product_type": "Ebook",
        "tags": "ebook, horror, dark-fiction, seven-circles, jk-blaze, philosophy, digital-download",
        "seo_title": "Seven Circles — Dark Fiction by J.K. Blaze (Series Opener)",
        "seo_description": "Psychological horror. Seven layers of hell. For readers of Dante, McCarthy, and Ligotti.",
        "cover_prompt": "seven concentric circles descending into darkness, dante-esque hellscape, "
                        "lone figure silhouette, red-black gradient, literary horror book cover, 4k",
        "body_html": (
            "<p><strong>D is 29. He's about to meet every version of himself that failed.</strong></p>"
            "<p>Seven Circles is a descent — chapter by chapter, level by level:</p>"
            "<ul>"
            "<li>✓ Full Volume 1 (7 circles, 140k+ words)</li>"
            "<li>✓ Psychological horror with philosophical weight</li>"
            "<li>✓ For readers of Dante, McCarthy, Ligotti</li>"
            "<li>✓ DRM-free PDF + EPUB + MOBI</li>"
            "<li>✓ Bonus: circle-by-circle annotation guide</li>"
            "</ul>"
            "<p>This isn't escapism. This is a mirror. By J.K. Blaze.</p>"
        ),
    },

    # ── Merch (Printify POD) ─────────────────────────────────────────────────
    "jk_blaze_hoodie": {
        "kind": "printify",
        "title": "J.K. Blaze Signature Hoodie",
        "tagline": "Minimalist dark logo on heavy cotton. Built for night writers, traders, outsiders.",
        "price": 44.99,
        "product_type": "Apparel",
        "tags": "apparel, hoodie, jk-blaze, streetwear, dark-aesthetic, merch, unisex",
        "seo_title": "J.K. Blaze Signature Hoodie — WheellsVerse Merch",
        "seo_description": "Heavy cotton hoodie with minimalist J.K. Blaze logo. Built for outsiders.",
        "cover_prompt": "premium black hoodie flat-lay product photography, minimalist white logo "
                        "that reads 'J.K. BLAZE' in sharp sans-serif, studio lighting, editorial aesthetic",
        "body_html": (
            "<p><strong>For the ones who write at 3am.</strong></p>"
            "<ul>"
            "<li>✓ Heavy 8.5oz cotton blend — no cheap polyester</li>"
            "<li>✓ Minimalist J.K. Blaze mark, printed not patched</li>"
            "<li>✓ Unisex cut, runs true to size</li>"
            "<li>✓ Printed on demand — zero overstock waste</li>"
            "<li>✓ Ships worldwide from US/EU facilities</li>"
            "</ul>"
        ),
        "niche_key": "entrepreneur mindset",
        "printify_product_type": "hoodie",
    },
    "bloodline_tee": {
        "kind": "printify",
        "title": "Bloodline Awakening Tee — Limited Drop",
        "tagline": "Novel cover art on premium black cotton. Tied to the Bloodline Vol 1 launch.",
        "price": 29.99,
        "product_type": "Apparel",
        "tags": "apparel, tshirt, bloodline, jk-blaze, book-merch, dark-fantasy, limited",
        "seo_title": "Bloodline Awakening Tee — Limited Novel Drop",
        "seo_description": "Novel cover art tee. Limited drop. Premium black cotton. Worldwide shipping.",
        "cover_prompt": "premium black t-shirt flat-lay, gothic bloodline artwork front-print, "
                        "blood-red ink, minimalist horror aesthetic, editorial product photography",
        "body_html": (
            "<p><strong>Wear the bloodline.</strong></p>"
            "<ul>"
            "<li>✓ Front-print Bloodline Vol 1 cover artwork</li>"
            "<li>✓ Premium ring-spun cotton, black only</li>"
            "<li>✓ Limited drop — tied to the book launch</li>"
            "<li>✓ Unisex sizing S–2XL</li>"
            "<li>✓ Ships from US + EU print facilities</li>"
            "</ul>"
        ),
        "niche_key": "dark fantasy / anime",
        "printify_product_type": "tshirt",
    },
    "seven_circles_poster": {
        "kind": "printify",
        "title": "Seven Circles Art Poster — Collector Edition",
        "tagline": "Museum-grade matte print. Dark collector piece. Limited run.",
        "price": 24.99,
        "product_type": "Wall Art",
        "tags": "wall-art, poster, seven-circles, dark-art, collector, jk-blaze, limited",
        "seo_title": "Seven Circles of Hell Art Poster — Collector Edition",
        "seo_description": "Museum-grade matte print. Dark collector piece from the Seven Circles series.",
        "cover_prompt": "seven concentric circles descending into darkness, dante hell illustration, "
                        "museum-grade art print design, framed poster mockup, gallery lighting",
        "body_html": (
            "<p><strong>A piece of the descent on your wall.</strong></p>"
            "<ul>"
            "<li>✓ Museum-grade matte paper, 200 gsm</li>"
            "<li>✓ Three sizes: 8x10, 11x14, 18x24</li>"
            "<li>✓ Limited collector run</li>"
            "<li>✓ Printed + shipped within 5 business days</li>"
            "</ul>"
        ),
        "niche_key": "dark fantasy / anime",
        "printify_product_type": "poster",
    },
}


# ─── RUNNER ───────────────────────────────────────────────────────────────────

def _publish_one(slug: str, item: dict) -> dict:
    """Publish a single catalog item via the NarAI engine."""
    from core.narai_shopify_engine import publish_digital_product, publish_pod_via_printful

    # Inject cover_prompts so the gate-required DALL-E call has something to work with
    product_data = {
        "title": item["title"],
        "tagline": item.get("tagline", ""),
        "body_html": item.get("body_html", ""),
        "price": item["price"],
        "tags": item.get("tags", ""),
        "product_type": item.get("product_type", "Digital Download"),
        "seo_title": item.get("seo_title", item["title"]),
        "seo_description": item.get("seo_description", item.get("tagline", "")),
        "cover_prompts": {"dalle": item.get("cover_prompt", f"premium product photography of {item['title']}")},
        "_product_type_key": "ai_prompt_pack",
        "_collection": "AI Tools & Templates",
    }

    kind = item.get("kind", "digital")
    if kind == "printify":
        pod_data = {
            **product_data,
            "_niche_key": item.get("niche_key", "entrepreneur mindset"),
            "_product_type": item.get("printify_product_type", "tshirt"),
            "_price": item["price"],
        }
        return publish_pod_via_printful(pod_data)
    return publish_digital_product(product_data)


def launch_catalog(only: Optional[list] = None) -> dict:
    """Launch all (or specific) catalog items. Returns slug → result dict."""
    items = CATALOG.items() if not only else [(s, CATALOG[s]) for s in only if s in CATALOG]
    results = {}
    for slug, item in items:
        log.info("=" * 70)
        log.info(f"LAUNCHING: {slug} — {item['title']}")
        log.info("=" * 70)
        try:
            r = _publish_one(slug, item)
            results[slug] = r
            status = "ACTIVE" if r.get("success") else f"BLOCKED ({r.get('error','?')[:80]})"
            log.info(f"→ {slug}: {status}")
        except Exception as e:
            results[slug] = {"success": False, "error": f"{type(e).__name__}: {e}"}
            log.exception(f"→ {slug}: FATAL")
    return results


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli():
    argv = sys.argv[1:]
    if not argv or argv[0] == "list":
        print("Available catalog items:")
        for slug, item in CATALOG.items():
            print(f"  {slug:22s} | ${item['price']:>7.2f} | {item['kind']:9s} | {item['title']}")
        print(f"\nUsage: python3 -m core.narai_catalog one <slug>")
        print(f"       python3 -m core.narai_catalog all")
        return

    if argv[0] == "one" and len(argv) >= 2:
        slug = argv[1]
        if slug not in CATALOG:
            print(f"Unknown slug: {slug}")
            return
        results = launch_catalog(only=[slug])
    elif argv[0] == "all":
        results = launch_catalog()
    else:
        print("Usage: list | one <slug> | all")
        return

    print("\n" + "=" * 70)
    print("CATALOG RUN SUMMARY")
    print("=" * 70)
    for slug, r in results.items():
        ok = "✓" if r.get("success") else "✗"
        print(f"  {ok} {slug:22s} {r.get('error','OK')[:70]}")


if __name__ == "__main__":
    _cli()
