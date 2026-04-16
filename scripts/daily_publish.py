#!/usr/bin/env python3
"""
scripts/daily_publish.py
─────────────────────────────────────────────────────────────────────────────
Daily auto-publish job for WheellsVerse.

Runs every day at the time set in DAILY_PUBLISH_TIME (default 08:00).
Each run:
  1. Picks 5 bot+topic combos (rotates through a pool so topics never repeat)
  2. Generates content with GPT
  3. Publishes to blog (HTML → Netlify)
  4. Sends Telegram summary

Run standalone:
  python scripts/daily_publish.py          # run once immediately
  python scripts/daily_publish.py --daemon  # run as scheduler (loops forever)

Called automatically by the API scheduler every morning.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs" / "daily_publish.log"),
    ],
)
logger = logging.getLogger("daily_publish")

# ── Topic pool — rotates so content never repeats ─────────────────────────────

TOPIC_POOL = [
    # Passive income
    ("specialized/74_passive_income_bot", "how to make $1000 a month in passive income in 2025"),
    ("specialized/74_passive_income_bot", "best passive income apps that pay real money"),
    ("specialized/74_passive_income_bot", "passive income ideas for beginners with no money"),
    ("marketing/73_passive_income_strategy", "how to build a passive income portfolio step by step"),
    ("marketing/73_passive_income_strategy", "REITs vs dividend stocks which is better passive income"),
    ("marketing/73_passive_income_strategy", "how much money do you need to live off dividends"),

    # Crypto
    ("specialized/71_crypto_content_creator", "best crypto to buy for beginners in 2025"),
    ("specialized/71_crypto_content_creator", "how to earn crypto without buying it staking explained"),
    ("specialized/71_crypto_content_creator", "is ethereum a good investment in 2025"),
    ("specialized/76_crypto_affiliate_booster", "how to buy bitcoin for the first time step by step"),
    ("specialized/76_crypto_affiliate_booster", "coinbase earn free crypto complete guide 2025"),
    ("specialized/79_crypto_news_affiliate_bot", "top crypto gainers to watch in 2025"),
    ("specialized/81_crypto_investing_booster", "how to build a crypto portfolio from scratch with $500"),
    ("specialized/81_crypto_investing_booster", "crypto staking rewards best platforms compared 2025"),

    # Stocks & investing
    ("specialized/72_stock_investing_content_creator", "best index funds for beginners to invest in 2025"),
    ("specialized/72_stock_investing_content_creator", "how to invest in S&P 500 from any country"),
    ("specialized/72_stock_investing_content_creator", "growth stocks vs dividend stocks which is better"),
    ("marketing/73_passive_income_strategy", "dividend reinvestment plan DRIP how it works"),

    # Side hustles
    ("specialized/78_side_hustle_affiliate_bot", "best online side hustles you can start today with no money"),
    ("specialized/78_side_hustle_affiliate_bot", "how to make money on fiverr as a complete beginner"),
    ("specialized/78_side_hustle_affiliate_bot", "freelance writing side hustle make $500 a month"),

    # AI tools
    ("specialized/77_ai_tools_affiliate_bot", "best AI tools for making money online in 2025"),
    ("specialized/77_ai_tools_affiliate_bot", "how to use ChatGPT to make money step by step"),
    ("specialized/77_ai_tools_affiliate_bot", "AI side hustle ideas that actually work in 2025"),

    # Affiliate & high-ticket
    ("specialized/82_high_ticket_affiliate_bot", "best high ticket affiliate programs for beginners"),
    ("specialized/82_high_ticket_affiliate_bot", "how to start affiliate marketing with no audience"),
    ("marketing/75_affiliate_sales_booster", "affiliate marketing mistakes that kill your commissions"),
]

USED_TOPICS_FILE = ROOT / "data" / "used_topics.json"
POSTS_PER_RUN = int(os.getenv("DAILY_POSTS_COUNT", "5"))


def _load_used() -> set:
    if USED_TOPICS_FILE.exists():
        try:
            return set(json.loads(USED_TOPICS_FILE.read_text()))
        except Exception:
            return set()
    return set()


def _save_used(used: set):
    USED_TOPICS_FILE.parent.mkdir(exist_ok=True)
    USED_TOPICS_FILE.write_text(json.dumps(list(used)))


def _pick_topics(n: int):
    """Return n unused (bot, topic) pairs. Resets pool if exhausted."""
    used = _load_used()
    available = [t for t in TOPIC_POOL if t[1] not in used]

    if len(available) < n:
        logger.info("Topic pool exhausted — resetting")
        used = set()
        available = list(TOPIC_POOL)

    picks = random.sample(available, min(n, len(available)))
    used.update(p[1] for p in picks)
    _save_used(used)
    return picks


# ── Main run ──────────────────────────────────────────────────────────────────

def run_daily_publish() -> dict:
    """Generate and publish POSTS_PER_RUN posts. Returns summary."""
    start = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"=== Daily publish started: {date_str} ===")

    from core.orchestrator import get_orchestrator
    from core.publish_pipeline import get_publisher

    orch = get_orchestrator()
    pub = get_publisher()

    topics = _pick_topics(POSTS_PER_RUN)
    results = {"generated": [], "published": [], "errors": []}

    # ── Step 1: Generate content ──────────────────────────────────────────────
    for bot_name, topic in topics:
        try:
            logger.info(f"  Generating: [{bot_name}] {topic}")
            result = orch.run_bot(bot_name, topic=topic)
            out_file = result.get("file") or result.get("output_file", "")
            if out_file and Path(out_file).exists():
                results["generated"].append(out_file)
                logger.info(f"    ✅ {Path(out_file).name}")
            else:
                results["errors"].append(f"{bot_name}: no output file")
                logger.warning(f"    ⚠️  No output file from {bot_name}")
        except Exception as e:
            results["errors"].append(f"{bot_name}: {e}")
            logger.error(f"    ❌ {bot_name}: {e}")

    # ── Step 2: Publish to blog ───────────────────────────────────────────────
    site_base = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev").rstrip("/")
    blog_urls = []
    for md_path in results["generated"]:
        try:
            content = Path(md_path).read_text(encoding="utf-8")
            pub_result = pub.publish(content=content, platforms=["blog"])
            blog_r = next(
                (r for r in pub_result["results"] if r.get("platform") == "blog"), {}
            )
            slug = blog_r.get("slug", "")
            if blog_r.get("status") == "saved":
                url = f"{site_base}/blog/{slug}.html"
                blog_urls.append(url)
                results["published"].append(slug)
                logger.info(f"    📝 Published: {slug[:60]}")
        except Exception as e:
            results["errors"].append(f"publish:{Path(md_path).name}: {e}")
            logger.error(f"    ❌ Publish error: {e}")

    # ── Step 3: Regenerate sitemap ────────────────────────────────────────────
    if results["published"]:
        try:
            from datetime import datetime as _dt
            today = _dt.now().strftime("%Y-%m-%d")
            base_url = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev").rstrip("/")
            blog_dir = ROOT / "frontend" / "blog"
            posts = sorted(blog_dir.glob("*.html"),
                               key=lambda f: f.stat().st_mtime, reverse=True)
            urls = [f'  <url><loc>{base_url}/</loc><changefreq>daily</changefreq><priority>1.0</priority><lastmod>{today}</lastmod></url>']
            urls += [f'  <url><loc>{base_url}/blog/</loc><changefreq>daily</changefreq><priority>0.9</priority><lastmod>{today}</lastmod></url>']
            for p in posts:
                if p.name != "index.html":
                    urls.append(f'  <url><loc>{base_url}/blog/{p.name}</loc><changefreq>weekly</changefreq><priority>0.8</priority><lastmod>{today}</lastmod></url>')
            sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            sitemap += '\n'.join(urls) + '\n</urlset>'
            (ROOT / "frontend" / "sitemap.xml").write_text(sitemap)
            logger.info(f"Sitemap updated — {len(urls)} URLs")
        except Exception as e:
            logger.warning(f"Sitemap update failed: {e}")

    # ── Step 4: Deploy to Netlify ─────────────────────────────────────────────
    if results["published"]:
        try:
            import subprocess
            deploy = subprocess.run(
                ["netlify", "deploy", "--dir", ".", "--prod"],
                capture_output=True, text=True, timeout=120,
                cwd=str(ROOT / "frontend"),
            )
            if deploy.returncode == 0:
                logger.info("✅ Netlify deployed successfully")
            else:
                logger.error(f"❌ Netlify deploy failed: {deploy.stderr[:300]}")
        except Exception as e:
            logger.error(f"Netlify deploy error: {e}")

    # ── Step 5: Telegram summary ──────────────────────────────────────────────
    duration = round(time.time() - start, 1)
    try:
        from core.telegram import notify
        lines = [
            "📅 <b>Daily Publish Complete</b>",
            f"🗓 {date_str}",
            f"✅ Generated: <b>{len(results['generated'])}</b> posts",
            f"📤 Published: <b>{len(results['published'])}</b> posts",
        ]
        if blog_urls:
            lines.append("\n🔗 <b>New posts:</b>")
            for url in blog_urls[:5]:
                slug = url.split("/")[-1].replace(".html", "")[:50]
                lines.append(f"  • <a href='{url}'>{slug}</a>")
        if results["errors"]:
            lines.append(f"\n⚠️ {len(results['errors'])} error(s) — check logs")
        lines.append(f"\n⏱ Completed in {duration}s")
        notify("\n".join(lines))
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")

    logger.info(
        f"=== Daily publish done: {len(results['published'])} published, "
        f"{len(results['errors'])} errors, {duration}s ==="
    )
    return results


# ── Daemon mode ───────────────────────────────────────────────────────────────

def run_daemon():
    """Run as a long-lived scheduler process (called with --daemon)."""
    import schedule as sched

    publish_time = os.getenv("DAILY_PUBLISH_TIME", "08:00")
    logger.info(f"Daily publisher daemon started — runs every day at {publish_time}")

    sched.every().day.at(publish_time).do(run_daily_publish)

    # Also run immediately on first start if RUN_ON_START=true
    if os.getenv("RUN_ON_START", "false").lower() == "true":
        logger.info("RUN_ON_START=true — running now")
        run_daily_publish()

    while True:
        sched.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true",
                        help="Run as long-lived scheduler (loops forever)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        result = run_daily_publish()
        print(json.dumps({
            "generated": len(result["generated"]),
            "published": len(result["published"]),
            "errors": result["errors"],
        }, indent=2))
