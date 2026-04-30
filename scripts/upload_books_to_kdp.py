#!/usr/bin/env python3
# Run with: source .venv/bin/activate && python scripts/upload_books_to_kdp.py
"""
scripts/upload_books_to_kdp.py
───────────────────────────────────────────────────────────────────────────────
Upload all 10 genre books to Amazon KDP with Canva-generated covers.
Stops before the Publish button — you publish manually at kdp.amazon.com.

Usage:
    python scripts/upload_books_to_kdp.py            # upload all genres
    python scripts/upload_books_to_kdp.py --genre mystery
    python scripts/upload_books_to_kdp.py --visible  # show browser
    python scripts/upload_books_to_kdp.py --publish  # also auto-publish (not recommended)
"""
import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
        logging.FileHandler(ROOT / "outputs" / "books" / "kdp_upload_run.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("upload_books_to_kdp")

from core.kdp_uploader import upload_all_genres, upload_book
from bots.books.book_publisher import KDP_PRICES


def main():
    p = argparse.ArgumentParser(description="Upload books to Amazon KDP")
    p.add_argument("--genre", type=str, help="Upload a single genre (e.g. mystery)")
    p.add_argument("--visible", action="store_true", help="Show browser window")
    p.add_argument("--publish", action="store_true", default=False,
                   help="Auto-click Publish (default: leave for manual publish)")
    args = p.parse_args()

    headless = not args.visible
    auto_publish = args.publish

    genres = list(KDP_PRICES.keys())

    print("\n" + "═" * 60)
    print("  KDP BOOK UPLOAD — WheellsVerse")
    print(f"  Genres: {', '.join(genres)}")
    print(f"  Mode: {'AUTO-PUBLISH' if auto_publish else 'UPLOAD ONLY (you publish manually)'}")
    print(f"  Browser: {'visible' if args.visible else 'headless'}")
    print("═" * 60 + "\n")

    if args.genre:
        if args.genre not in genres:
            print(f"❌ Unknown genre '{args.genre}'. Valid: {', '.join(genres)}")
            sys.exit(1)
        print(f"Uploading genre: {args.genre}")
        result = upload_book(args.genre, headless=headless, auto_publish=auto_publish)
        _print_result(result)
    else:
        print(f"Uploading all {len(genres)} genres...\n")
        results = upload_all_genres(headless=headless, auto_publish=auto_publish)
        print("\n" + "─" * 60)
        print("RESULTS:")
        for r in results:
            _print_result(r)

        ready = sum(1 for r in results if r.get("status") == "ready_to_publish")
        published = sum(1 for r in results if r.get("status") == "published")
        errors = sum(1 for r in results if r.get("status") not in ("ready_to_publish", "published", "skipped"))

        print("\n" + "═" * 60)
        print(f"  📋 Ready for manual publish: {ready}")
        print(f"  ✅ Auto-published:            {published}")
        print(f"  ❌ Errors:                    {errors}")
        if ready:
            print("\n  👉 Go to kdp.amazon.com → Bookshelf")
            print("     Click 'Publish Your Kindle eBook' on each draft book.")
        print("═" * 60 + "\n")


def _print_result(r: dict):
    status = r.get("status", "unknown")
    genre = r.get("genre", "?")
    title = r.get("title", "?")[:55]
    if status == "ready_to_publish":
        icon = "📋"
        note = "→ Publish manually at kdp.amazon.com"
    elif status == "published":
        icon = "✅"
        note = r.get("kdp_url", "")
    elif status == "skipped":
        icon = "⏭"
        note = r.get("error", "")
    else:
        icon = "❌"
        note = r.get("error", r.get("note", ""))
    print(f"  {icon} [{genre:12}] {title}")
    if note:
        print(f"           {note[:70]}")


if __name__ == "__main__":
    main()
