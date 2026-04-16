#!/usr/bin/env python3
"""
bots/books/complete_and_publish_all.py
──────────────────────────────────────
Completes all incomplete manuscripts and publishes each to Amazon KDP.

Steps per book:
  1. Extract story bible (ContinuityEngine)
  2. Write completion sequel (~15K words)
  3. Literary QC — revise if needed
  4. Package HTML
  5. Upload to KDP via Playwright

Usage:
  python bots/books/complete_and_publish_all.py
  python bots/books/complete_and_publish_all.py --skip-publish   # complete only
  python bots/books/complete_and_publish_all.py --resume         # skip already-completed
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.base_bot import BaseBot  # noqa: E402

# These have already been handled — skip them
SKIP_FILES = {
    # Memory Thief Vol 1 — Vol 2 was already written + published separately
    "book_the_memory_thief_20260404_054221.md",
}

PROGRESS_FILE = ROOT / "data" / "complete_and_publish_progress.json"


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"completed": [], "failed": [], "published": []}


def save_progress(p: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(p, indent=2, ensure_ascii=False))


def complete_and_publish(item: dict, skip_publish: bool, bot: BaseBot, progress: dict) -> dict:
    from bots.books.volume_completion_bot import VolumeCompletionBot
    from core.kdp_uploader import upload_book

    src = item["file"]
    genre = item["genre"]
    name = Path(src).name

    print(f"\n{'─' * 60}")
    print(f"  📖 {item['title']} [{genre}]")
    print(f"{'─' * 60}")

    # Step 1–3: Complete the manuscript
    vcb = VolumeCompletionBot()
    result = vcb.complete_volume(src, genre)

    if "error" in result:
        print(f"  ❌ Completion failed: {result['error']}")
        return result

    sequel_path = result.get("sequel_file")
    qc_verdict = result.get("qc_verdict", "UNKNOWN")
    qc_score = result.get("qc_score", 0)
    word_count = result.get("word_count", 0)

    print(f"  ✅ Written: {word_count:,} words")
    print(f"  🔬 QC: {qc_verdict} ({qc_score}/100)")

    progress["completed"].append({
        "name": name, "genre": genre,
        "sequel_file": sequel_path,
        "qc_verdict": qc_verdict, "qc_score": qc_score,
        "word_count": word_count,
    })
    save_progress(progress)

    if skip_publish or not sequel_path:
        return result

    # Step 4–5: Package HTML + publish to KDP
    print("  📦 Packaging + uploading to KDP...")
    try:
        # Build KDP-ready HTML from the completed manuscript
        from bots.books.publisher_engine.distribution_agent import _package_html
        import re
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = result.get("title", Path(sequel_path).stem.replace("_", " ").title())
        safe_title = re.sub(r"[^\w]+", "_", title.lower())[:40]
        html_path = _package_html(
            manuscript=Path(sequel_path).read_text(encoding="utf-8"),
            title=title,
            author="J.K. Blaze",
            cover_path=None,
            description=f"<p>A complete {genre} novel by J.K. Blaze.</p>",
            ts=ts,
            safe_title=safe_title,
        )

        # Write KDP package metadata so upload_book reads the right title

        pub_dir = ROOT / "outputs" / "books" / "published"
        pub_dir.mkdir(parents=True, exist_ok=True)
        kdp_pkg = pub_dir / f"{genre}_{safe_title}_{ts}_kdp_package.md"
        kdp_pkg.write_text(
            f"# KDP Package — {title}\n\n"
            f"**BOOK TITLE:** {title}\n"
            f"**Author:** J.K. Blaze\n"
            f"**Genre:** {genre.replace('_', ' ').title()}\n"
            f"**Price:** $3.99\n"
            f"**Language:** en\n\n"
            f"## Description\n\n<p>A gripping {genre.replace('_', ' ')} novel that keeps you reading until the last page.</p>\n\n"
            f"## KEYWORDS\n1. {genre} fiction\n2. {genre} novel\n3. J.K. Blaze\n"
            f"4. WheellsVerse\n5. fiction\n6. {genre} book\n7. bestseller\n",
            encoding="utf-8",
        )

        kdp_result = upload_book(
            genre=genre,
            manuscript_path=str(html_path),
            cover_path=None,
            headless=True,
        )
        kdp_status = kdp_result.get("status", "unknown")
        print(f"  📤 KDP: {kdp_status}")

        progress["published"].append({
            "name": name, "genre": genre, "title": title,
            "kdp_status": kdp_status,
            "kdp_url": kdp_result.get("kdp_url", ""),
        })
        save_progress(progress)

        result["kdp_status"] = kdp_status
        result["kdp_url"] = kdp_result.get("kdp_url", "")

    except Exception as e:
        print(f"  ⚠️  KDP publish failed: {e}")
        result["kdp_status"] = f"error: {e}"

    return result


def main():
    parser = argparse.ArgumentParser(description="Complete + publish all incomplete books")
    parser.add_argument("--skip-publish", action="store_true", help="Complete only, don't publish to KDP")
    parser.add_argument("--resume", action="store_true", help="Skip books already in progress file")
    args = parser.parse_args()

    from bots.books.volume_completion_bot import VolumeCompletionBot
    vcb = VolumeCompletionBot()

    print("\n" + "═" * 60)
    print("  NarAI — Complete & Publish All Incomplete Books")
    print("═" * 60)

    # Scan for incomplete
    scan = vcb.scan_all_manuscripts()
    incomplete = scan.get("incomplete", [])

    # Filter skipped files
    incomplete = [i for i in incomplete if Path(i["file"]).name not in SKIP_FILES]

    print(f"\n  Found {len(incomplete)} books to complete\n")

    progress = load_progress()
    already_done = {p["name"] for p in progress.get("completed", [])}

    results = []
    failed = []

    for i, item in enumerate(incomplete, 1):
        name = Path(item["file"]).name

        if args.resume and name in already_done:
            print(f"  ⏭️  Skipping (already completed): {item['title']}")
            continue

        print(f"\n[{i}/{len(incomplete)}]", end="")

        try:
            result = complete_and_publish(item, args.skip_publish, None, progress)
            if "error" in result:
                failed.append(item["title"])
            else:
                results.append(result)
        except Exception as e:
            print(f"\n  ❌ Exception: {e}")
            failed.append(f"{item['title']}: {e}")
            progress["failed"].append({"name": name, "error": str(e)})
            save_progress(progress)

        # Pace the API calls — avoid rate limits
        if i < len(incomplete):
            print("\n  ⏳ Pausing 5s before next book...")
            time.sleep(5)

    # Final summary
    print("\n\n" + "═" * 60)
    print("  COMPLETE")
    print("═" * 60)
    print(f"  ✅ Completed: {len(results)}")
    print(f"  ❌ Failed:    {len(failed)}")
    if not args.skip_publish:
        pub = [r for r in results if r.get("kdp_status") == "published"]
        print(f"  📤 Published: {len(pub)}")

    for r in results:
        status = r.get("kdp_status", "not published")
        print(f"  • {r.get('title', '?')} — {r.get('word_count', 0):,}w — KDP: {status}")

    if failed:
        print("\n  Failed:")
        for f in failed:
            print(f"  ✗ {f}")

    print("═" * 60)

    # Telegram summary
    try:
        from core.telegram import notify
        notify(
            f"📚 Complete & Publish All Done\n"
            f"✅ {len(results)} completed\n"
            f"📤 {len([r for r in results if r.get('kdp_status') == 'published'])} published to KDP\n"
            f"❌ {len(failed)} failed"
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
