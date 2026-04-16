#!/usr/bin/env python3
"""
WheellsVerse → Amazon KDP Publisher
One command to write, generate covers, and publish all books to Amazon.

Usage:
  python publish_to_kdp.py              # publish all genres
  python publish_to_kdp.py --genre mystery
  python publish_to_kdp.py --visible    # show browser (useful for debugging)
  python publish_to_kdp.py --covers-only  # just generate all covers
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_PATH))

# Load .env explicitly
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_PATH / ".env")
except Exception:
    pass
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

ROOT = Path(__file__).resolve().parents[2]

GENRES = [
    "childrens", "mystery", "adventure", "historical",
    "self_help", "romance", "sci_fi", "fantasy", "horror", "true_crime"
]


def check_credentials() -> bool:
    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")
    if not email or not password:
        print("\n⚠️  KDP credentials not set.")
        print("Add to your .env file:")
        print("  KDP_EMAIL=your@amazon.com")
        print("  KDP_PASSWORD=yourpassword")
        print("\nThen run again.")
        return False
    print(f"✅ KDP credentials found: {email}")
    return True


def generate_all_covers():
    """Generate DALL-E covers for all genres."""
    from core.kdp_uploader import generate_cover

    print("\n🎨 Generating book covers with DALL-E 3...\n")
    covers = {}
    for genre in GENRES:
        # Get title from latest manuscript
        genre_dir = ROOT / "outputs" / "books" / genre
        manuscripts = sorted(
            [f for f in genre_dir.glob("*.md")
             if not any(f.name.startswith(p) for p in ("outline_", "cover_", "kdp_", "series_", "book_"))],
            key=lambda f: f.stat().st_mtime, reverse=True
        ) if genre_dir.exists() else []

        if manuscripts:
            title = manuscripts[0].stem.replace("_", " ").title()[:50]
            try:
                cover_path = generate_cover(title, genre)
                covers[genre] = str(cover_path)
                print(f"  ✅ {genre}: {cover_path.name}")
            except Exception as e:
                print(f"  ❌ {genre}: {e}")
                covers[genre] = None
        else:
            print(f"  ⏳ {genre}: no manuscript found")
            covers[genre] = None

        time.sleep(2)  # Rate limit DALL-E

    return covers


def publish_all(headless: bool = True, genres: list = None):
    """Full pipeline: covers + KDP upload for all genres."""
    from core.kdp_uploader import upload_book

    if not check_credentials():
        return

    target_genres = genres or GENRES
    print(f"\n📚 Publishing {len(target_genres)} books to Amazon KDP...")
    print("This will open a browser and automate the full upload process.\n")

    # Step 1: Generate covers
    print("Step 1/2: Generating book covers with DALL-E 3...")
    covers = {}
    for genre in target_genres:
        genre_dir = ROOT / "outputs" / "books" / genre
        manuscripts = sorted(
            [f for f in genre_dir.glob("*.md")
             if not any(f.name.startswith(p) for p in ("outline_", "cover_", "kdp_", "series_", "book_"))],
            key=lambda f: f.stat().st_mtime, reverse=True
        ) if genre_dir.exists() else []

        if manuscripts:
            title = manuscripts[0].stem.replace("_", " ").title()[:50]
            try:
                from core.kdp_uploader import generate_cover
                cover_path = generate_cover(title, genre)
                covers[genre] = str(cover_path)
                print(f"  🎨 {genre}: cover ready")
            except Exception as e:
                print(f"  ⚠️ {genre}: cover failed ({e}) — will use KDP cover maker")
                covers[genre] = None
            time.sleep(1)

    # Step 2: Upload to KDP
    print(f"\nStep 2/2: Uploading {len(target_genres)} books to KDP...")
    results = []
    for genre in target_genres:
        print(f"\n  📤 Uploading: {genre}...")
        result = upload_book(
            genre=genre,
            cover_path=covers.get(genre),
            headless=headless,
        )
        results.append(result)
        emoji = "✅" if result["status"] in ("published", "review_required") else "❌"
        print(f"  {emoji} {genre}: {result['status']}")
        if result.get("error"):
            print(f"     Error: {result['error']}")
        if result.get("screenshot"):
            print(f"     Screenshot: {result['screenshot']}")
        time.sleep(3)

    # Summary
    published = sum(1 for r in results if r["status"] == "published")
    review = sum(1 for r in results if r["status"] == "review_required")
    errors = sum(1 for r in results if r["status"] == "error")

    print(f"\n{'=' * 50}")
    print(f"✅ Published: {published}/{len(results)}")
    print(f"👀 Review required: {review}")
    print(f"❌ Errors: {errors}")
    print(f"{'=' * 50}")

    # Telegram final report
    try:
        from core.telegram import notify
        book_list = "\n".join(
            f"{'✅' if r['status'] == 'published' else '⚠️' if r['status'] == 'review_required' else '❌'} "
            f"{r['genre'].title()}: {r.get('title', '')[:40]}"
            for r in results
        )
        notify(
            f"📚 KDP PUBLISH COMPLETE\n\n"
            f"{book_list}\n\n"
            f"✅ {published} published | 👀 {review} review | ❌ {errors} errors\n"
            f"💰 Books go live on Amazon within 24-72 hours"
        )
    except Exception:
        pass

    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Publish WheellsVerse books to Amazon KDP")
    p.add_argument("--genre", type=str, help="Publish single genre")
    p.add_argument("--all", action="store_true", default=True, help="Publish all genres")
    p.add_argument("--visible", action="store_true", help="Show browser window")
    p.add_argument("--covers-only", action="store_true", help="Only generate covers")
    args = p.parse_args()

    headless = not args.visible

    if args.covers_only:
        generate_all_covers()
    elif args.genre:
        if not check_credentials():
            sys.exit(1)
        from core.kdp_uploader import upload_book
        result = upload_book(genre=args.genre, headless=headless)
        print(f"\n{'✅' if result['status'] == 'published' else '❌'} Result: {result}")
    else:
        publish_all(headless=headless)
