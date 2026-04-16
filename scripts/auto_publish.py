#!/usr/bin/env python3
"""
scripts/auto_publish.py
─────────────────────────────────────────────────────────────────────────────
Scans the latest generated content from each revenue bot and publishes it to
all connected platforms: Twitter (browser), blog (Netlify), ConvertKit email.

Usage:
  python scripts/auto_publish.py              # publish content from last 24h
  python scripts/auto_publish.py --hours 4    # only content from last 4h
  python scripts/auto_publish.py --dry-run    # preview without publishing
  python scripts/auto_publish.py --platforms twitter blog
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [auto_publish] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs" / "auto_publish.log", mode="a"),
    ]
)
logger = logging.getLogger("auto_publish")

# Revenue content bot output directories (one article per bot per run)
CONTENT_BOT_DIRS = [
    ROOT / "outputs" / "specialized" / "71_crypto_content_creator",
    ROOT / "outputs" / "specialized" / "72_stock_investing_content_creator",
    ROOT / "outputs" / "specialized" / "74_passive_income_bot",
    ROOT / "outputs" / "specialized" / "77_ai_tools_affiliate_bot",
    ROOT / "outputs" / "specialized" / "78_side_hustle_affiliate_bot",
    ROOT / "outputs" / "marketing" / "73_passive_income_strategy",
]

PUBLISHED_LOG = ROOT / "data" / "published_log.json"


def load_published_log() -> set:
    if PUBLISHED_LOG.exists():
        try:
            return set(json.loads(PUBLISHED_LOG.read_text()))
        except Exception:
            pass
    return set()


def save_published_log(published: set):
    PUBLISHED_LOG.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED_LOG.write_text(json.dumps(sorted(published), indent=2))


def find_recent_content(hours: int = 24) -> list:
    """Return the latest .md file per bot directory modified within last N hours."""
    cutoff = datetime.now() - timedelta(hours=hours)
    published = load_published_log()
    files = []

    for directory in CONTENT_BOT_DIRS:
        if not directory.exists():
            continue
        candidates = sorted(
            directory.glob("*.md"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        for f in candidates:
            if f.stat().st_mtime < cutoff.timestamp():
                break  # sorted newest→oldest, stop when past cutoff
            if str(f) not in published:
                files.append(f)
                break  # only the most recent unpublished file per bot

    return files


def main():
    parser = argparse.ArgumentParser(description="Auto-publish latest bot content to all platforms")
    parser.add_argument("--hours", type=int, default=24,
                        help="Only publish files from last N hours (default: 24)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without publishing")
    parser.add_argument("--platforms", nargs="+",
                        default=["twitter", "blog", "email"],
                        choices=["twitter", "blog", "email", "tiktok"],
                        help="Platforms to publish to (default: twitter blog email)")
    args = parser.parse_args()

    from core.publish_pipeline import get_publisher
    publisher = get_publisher()

    files = find_recent_content(args.hours)

    if not files:
        logger.info(f"No new content found in the last {args.hours}h — nothing to publish")
        return

    logger.info(f"Found {len(files)} content file(s) to publish → {', '.join(args.platforms)}")
    published_set = load_published_log()
    total_ok = 0
    total_fail = 0

    for md_path in files:
        logger.info(f"Publishing: {md_path.parent.name}/{md_path.name}")
        if args.dry_run:
            logger.info(f"  [dry-run] would publish to: {', '.join(args.platforms)}")
            continue

        try:
            result = publisher.publish_from_file(
                str(md_path),
                platforms=args.platforms,
            )
            published_set.add(str(md_path))
            save_published_log(published_set)

            for r in result.get("results", []):
                platform = r.get("platform")
                status = r.get("status")
                if status in ("posted", "saved", "sent", "draft_created", "content_saved"):
                    extra = ""
                    if r.get("live_url"):
                        extra = f" → {r['live_url']}"
                    elif r.get("send_url"):
                        extra = f" (review at {r['send_url']})"
                    elif r.get("tweets"):
                        extra = f" ({r['tweets']} tweets)"
                    logger.info(f"  ✅ {platform}: {status}{extra}")
                    total_ok += 1
                else:
                    logger.warning(f"  ⚠  {platform}: {status} — {r.get('error') or r.get('reason', '')}")
                    total_fail += 1

        except Exception as e:
            logger.error(f"  ✗ Failed to publish {md_path.name}: {e}")
            total_fail += 1

    # Regenerate blog index + sitemap after publishing
    if not args.dry_run and total_ok > 0:
        try:
            import subprocess
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "generate_blog_index.py")],
                check=True, capture_output=True, cwd=str(ROOT)
            )
            logger.info("Blog index + sitemap regenerated")
        except Exception as e:
            logger.warning(f"Blog index generation failed: {e}")

    logger.info(f"Auto-publish complete — {total_ok} succeeded, {total_fail} failed")


if __name__ == "__main__":
    main()
