#!/usr/bin/env python3
"""
WheellsVerse Book Orchestrator
Writes 1 book per genre per day, queues for KDP publishing, promotes finished books.

Daily schedule:
  07:00-10:00 — Write books across all 10 genres (one per genre, rotating ideas)
  10:00-10:30 — Generate KDP packages for books written today
  10:30-11:00 — Post promotional content to FB + IG

Revenue model:
  10 genres × 1 book/day × $2.99-$9.99 = growing passive income catalog
  Week 1: 10 books live
  Month 1: 40+ books live across 10 genres
  Month 3: 120+ books — passive income at scale

Usage:
  python book_orchestrator.py --daily     # run daily workflow
  python book_orchestrator.py --genre mystery  # write one book
  python book_orchestrator.py --report    # revenue report
"""
import importlib
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]

GENRE_BOTS = {
    "childrens": ("bots/books/01_childrens/bot.py", "ChildrensBookBot"),
    "mystery": ("bots/books/02_mystery/bot.py", "MysteryBot"),
    "adventure": ("bots/books/03_adventure/bot.py", "AdventureBot"),
    "historical": ("bots/books/04_historical/bot.py", "HistoricalBot"),
    "self_help": ("bots/books/05_self_help/bot.py", "SelfHelpBot"),
    "romance": ("bots/books/06_romance/bot.py", "RomanceBot"),
    "sci_fi": ("bots/books/07_sci_fi/bot.py", "SciFiBot"),
    "fantasy": ("bots/books/08_fantasy/bot.py", "FantasyBot"),
    "horror": ("bots/books/09_horror/bot.py", "HorrorBot"),
    "true_crime": ("bots/books/10_true_crime/bot.py", "TrueCrimeBot"),
}


def load_bot(genre: str):
    """Dynamically load a genre bot."""
    bot_file, class_name = GENRE_BOTS[genre]
    spec_path = ROOT / bot_file
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"book_{genre}", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, class_name)()


def write_book(genre: str, action: str = "write", **kwargs) -> dict:
    """Write a book for a specific genre."""
    try:
        bot = load_bot(genre)
        result = bot.execute(action=action, **kwargs)
        return {"genre": genre, "status": "ok", "result": result}
    except Exception as e:
        return {"genre": genre, "status": "error", "error": str(e)}


def daily_workflow(genres: list = None, write_only: bool = False):
    """Run the full daily book writing + publishing workflow."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    target_genres = genres or list(GENRE_BOTS.keys())

    print(f"\n📚 WheellsVerse Book Factory — {today}")
    print(f"Writing {len(target_genres)} books today...\n")

    written = []
    errors = []

    # Step 1: Write one book per genre
    for genre in target_genres:
        print(f"  ✍️  Writing {genre}...", flush=True)
        result = write_book(genre, action="write")
        if result["status"] == "ok":
            title = result["result"].get("title", genre)
            written.append({"genre": genre, "title": title, "result": result["result"]})
            print(f"  ✅ {genre}: '{title}'")
        else:
            errors.append(f"❌ {genre}: {result.get('error', '')}")
            print(f"  ❌ {genre}: {result.get('error', '')}")

    if write_only:
        return written

    # Step 2: Generate KDP packages for today's books
    if written:
        print(f"\n📦 Generating KDP packages for {len(written)} books...")
        try:
            pub_spec = importlib.util.spec_from_file_location(
                "book_publisher", ROOT / "bots/books/book_publisher.py")
            pub_mod = importlib.util.module_from_spec(pub_spec)
            pub_spec.loader.exec_module(pub_mod)
            publisher = pub_mod.BookPublisher()
            for book in written[:3]:  # Limit to 3 KDP packages per day to save tokens
                publisher.execute(action="publish", genre=book["genre"])
                print(f"  📕 KDP package: {book['genre']}")
        except Exception as e:
            print(f"  ⚠️ KDP packaging skipped: {e}")

    # Step 3: Promote the best book of the day
    if written:
        best = written[0]
        print(f"\n📢 Promoting: '{best['title']}'")
        try:
            bot = load_bot(best["genre"])
            bot.execute(action="promote", title=best["title"])
            print("  ✅ Promoted to Facebook + Instagram")
        except Exception as e:
            print(f"  ⚠️ Promotion skipped: {e}")

    # Step 4: Telegram daily report
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("telegram", ROOT / "core/telegram.py")
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        books_list = "\n".join(f"  📖 {b['genre'].title()}: {b['title']}" for b in written)
        errors_list = "\n".join(errors) if errors else "None"
        mod.notify(
            f"📚 Book Factory Daily Report — {today}\n\n"
            f"✅ Written today ({len(written)}):\n{books_list}\n\n"
            f"{'❌ Errors: ' + errors_list if errors else ''}\n\n"
            f"📊 Total books in catalog grows daily.\n"
            f"💰 Each book = passive income on Amazon KDP forever."
        )
    except Exception as e:
        print(f"Telegram report failed: {e}")

    return {"written": written, "errors": errors}


def write_series(genre: str):
    """Plan and begin a 5-book series for a genre."""
    try:
        bot = load_bot(genre)
        r1 = bot.execute(action="series")
        r2 = bot.execute(action="outline")
        r3 = bot.execute(action="write")
        return {"series_plan": r1, "book1_outline": r2, "book1_manuscript": r3}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import argparse
    import importlib.util

    p = argparse.ArgumentParser(description="WheellsVerse Book Orchestrator")
    p.add_argument("--daily", action="store_true", help="Run full daily workflow")
    p.add_argument("--genre", type=str, help="Write one book for this genre")
    p.add_argument("--action", type=str, default="write")
    p.add_argument("--series", type=str, help="Plan + write series for genre")
    p.add_argument("--report", action="store_true", help="Revenue report")
    p.add_argument("--genres", nargs="*", help="Specific genres for daily run")
    args = p.parse_args()

    if args.report:
        spec = importlib.util.spec_from_file_location(
            "book_publisher", ROOT / "bots/books/book_publisher.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pub = mod.BookPublisher()
        pub.execute(action="revenue")

    elif args.series:
        print(f"📚 Planning series for: {args.series}")
        result = write_series(args.series)
        print(f"✅ Series planned: {result}")

    elif args.genre:
        print(f"✍️  Writing {args.action} for genre: {args.genre}")
        result = write_book(args.genre, action=args.action)
        print(f"{'✅' if result['status'] == 'ok' else '❌'} {args.genre}: {result}")

    else:
        # Default: daily workflow
        results = daily_workflow(genres=args.genres)
        print(f"\n✅ Daily workflow complete: {len(results.get('written', []))} books written")
