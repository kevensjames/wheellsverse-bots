#!/usr/bin/env python3
"""
WheellsVerse — Daily KDP Publisher
Writes + publishes 10 books per day (one per genre) to Amazon KDP.

Schedule:
  Step 1: Write 10 books (one per genre) via book_orchestrator
  Step 2: Generate KDP packages for all 10
  Step 3: Upload + publish all 10 to Amazon KDP via Playwright

Run:
  python daily_publish.py               # run all 10 genres
  python daily_publish.py --genres mystery romance  # specific genres
  python daily_publish.py --headless    # headless browser (default)
  python daily_publish.py --visible     # show browser
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "outputs" / "books" / "daily_publish.log"),
    ]
)
logger = logging.getLogger("daily_publish")

GENRES = [
    "childrens", "mystery", "adventure", "historical",
    "self_help", "romance", "sci_fi", "fantasy", "horror", "true_crime"
]


def write_all_books(genres: list) -> dict:
    """Write one book per genre using book_orchestrator."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "book_orchestrator", ROOT / "bots/books/book_orchestrator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    results = {}
    for genre in genres:
        logger.info("Writing book: %s", genre)
        try:
            r = mod.write_book(genre, action="write")
            results[genre] = r
            if r["status"] == "ok":
                title = r["result"].get("title", genre)
                logger.info("✅ %s: '%s'", genre, title)
            else:
                logger.warning("❌ %s: %s", genre, r.get("error", ""))
        except Exception as e:
            logger.error("Error writing %s: %s", genre, e)
            results[genre] = {"status": "error", "error": str(e)}
        time.sleep(2)

    return results


def generate_kdp_packages(genres: list):
    """Generate KDP metadata packages for each genre."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "book_publisher", ROOT / "bots/books/book_publisher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    publisher = mod.BookPublisher()

    for genre in genres:
        try:
            publisher.execute(action="publish", genre=genre)
            logger.info("📦 KDP package ready: %s", genre)
        except Exception as e:
            logger.warning("KDP package failed for %s: %s", genre, e)
        time.sleep(1)


def publish_all_to_kdp(genres: list, headless: bool = True) -> list:
    """Upload all books to Amazon KDP."""
    from core.kdp_uploader import upload_book, generate_cover

    results = []
    account_limit_hit = False
    for genre in genres:
        if account_limit_hit:
            logger.warning("⏭ Skipping %s — Amazon title creation limit reached", genre)
            results.append({"genre": genre, "status": "skipped", "error": "account_limit_reached — skipped"})
            continue

        logger.info("📤 Publishing to KDP: %s", genre)
        try:
            # Generate cover using the best (longest) book_ manuscript
            genre_dir = ROOT / "outputs" / "books" / genre
            cover_path = None
            if genre_dir.exists():
                book_mds = sorted(
                    genre_dir.glob("book_*.md"),
                    key=lambda f: len(f.read_text(errors="replace").split()), reverse=True
                )
                if book_mds:
                    title = book_mds[0].stem.replace("book_", "").replace("_", " ").title()[:50]
                    try:
                        cover_path = str(generate_cover(title, genre))
                        logger.info("🎨 Cover generated: %s", genre)
                    except Exception as e:
                        logger.warning("Cover failed for %s: %s", genre, e)

            result = upload_book(genre=genre, cover_path=cover_path, headless=headless)
            results.append(result)

            # Check if account limit was hit — stop remaining genres
            if result.get("error", "").startswith("account_limit_reached"):
                account_limit_hit = True
                logger.warning("🚫 Amazon title creation limit hit — stopping batch")

            emoji = "✅" if result["status"] == "published" else "⚠️" if result["status"] == "review_required" else "❌"
            logger.info("%s %s: %s — %s", emoji, genre, result["status"],
                        result.get("title", "")[:50])

        except Exception as e:
            err = str(e)
            logger.error("KDP upload failed for %s: %s", genre, err)
            results.append({"genre": genre, "status": "error", "error": err})
            if "account_limit_reached" in err:
                account_limit_hit = True

        # Wait between uploads to avoid KDP rate limiting
        time.sleep(5)

    return results


def send_daily_report(results: list, written: dict, today: str):
    """Send Telegram summary of the day's publishing run."""
    try:
        from core.telegram import notify
        published = sum(1 for r in results if r["status"] == "published")
        review = sum(1 for r in results if r["status"] == "review_required")
        errors = sum(1 for r in results if r["status"] == "error")

        lines = []
        for r in results:
            e = "✅" if r["status"] == "published" else "⚠️" if r["status"] == "review_required" else "❌"
            lines.append(f"{e} {r['genre'].title()}: {r.get('title', '')[:35]}")

        notify(
            f"📚 KDP DAILY PUBLISH — {today}\n\n"
            + "\n".join(lines)
            + f"\n\n✅ Published: {published} | ⚠️ Review: {review} | ❌ Errors: {errors}\n"
            f"💰 Books go live on Amazon within 24-72 hours"
        )
    except Exception as e:
        logger.warning("Telegram report failed: %s", e)


def run(genres: list = None, headless: bool = True,
        skip_write: bool = False, skip_packages: bool = False):
    today = datetime.now().strftime("%A, %B %d, %Y")
    target_genres = genres or GENRES

    logger.info("=" * 60)
    logger.info("WheellsVerse Daily Publish — %s", today)
    logger.info("Target: %d books → Amazon KDP", len(target_genres))
    logger.info("=" * 60)

    # Step 1: Write books
    written = {}
    if not skip_write:
        logger.info("\n📝 STEP 1/3: Writing %d books...", len(target_genres))
        written = write_all_books(target_genres)
        ok = sum(1 for r in written.values() if r.get("status") == "ok")
        logger.info("Books written: %d/%d", ok, len(target_genres))
    else:
        logger.info("Skipping book writing (--skip-write)")

    # Step 2: KDP packages
    if not skip_packages:
        logger.info("\n📦 STEP 2/3: Generating KDP packages...")
        generate_kdp_packages(target_genres)
    else:
        logger.info("Skipping KDP packages (--skip-packages)")

    # Step 3: Upload to KDP
    logger.info("\n🚀 STEP 3/3: Publishing to Amazon KDP...")
    results = publish_all_to_kdp(target_genres, headless=headless)

    # Summary
    published = sum(1 for r in results if r["status"] == "published")
    review = sum(1 for r in results if r["status"] == "review_required")
    errors_count = sum(1 for r in results if r["status"] == "error")

    logger.info("\n" + "=" * 60)
    logger.info("DAILY PUBLISH COMPLETE — %s", today)
    logger.info("✅ Published: %d | ⚠️ Review: %d | ❌ Errors: %d",
                published, review, errors_count)
    logger.info("=" * 60)

    send_daily_report(results, written, today)
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="WheellsVerse — Publish 10 books/day to Amazon KDP")
    p.add_argument("--genres", nargs="*", help="Specific genres (default: all 10)")
    p.add_argument("--visible", action="store_true", help="Show browser window")
    p.add_argument("--skip-write", action="store_true", help="Skip book writing (use existing)")
    p.add_argument("--skip-packages", action="store_true", help="Skip KDP package generation")
    args = p.parse_args()

    results = run(
        genres=args.genres,
        headless=not args.visible,
        skip_write=args.skip_write,
        skip_packages=args.skip_packages,
    )
    published = sum(1 for r in results if r["status"] == "published")
    print(f"\n✅ Done: {published}/{len(results)} books published to Amazon KDP")
