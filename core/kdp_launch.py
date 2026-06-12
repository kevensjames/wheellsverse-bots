#!/usr/bin/env python3
"""
core/kdp_launch.py
───────────────────────────────────────────────────────────────────────────────
Unified KDP launcher — publishes ebook AND paperback for the same book together.

Why this module exists:
    - `core/kdp_uploader.py`   → handles Kindle ebook only
    - `core/kdp_paperback.py`  → handles paperback only
    Running them separately means duplicate work (login, screenshots, etc.)
    and the two editions aren't launched in sync.

Public API:
    launch_book(genre, title, manuscript_html_path, ...) → {"ebook": {...}, "paperback": {...}}
    launch_all(...) → [{"genre":..., "ebook":..., "paperback":...}, ...]

CLI:
    python -m core.kdp_launch --genre mystery
    python -m core.kdp_launch --all                 # loops over every unpublished genre
    python -m core.kdp_launch --all --auto-post     # also fans out launch posts to X/FB/IG
    python -m core.kdp_launch --genre mystery --visible --no-publish
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .kdp_uploader import upload_book
from .kdp_paperback import upload_paperback

logger = logging.getLogger("kdp_launch")
ROOT = Path(__file__).resolve().parent.parent


def launch_book(
    genre: str,
    title: str,
    manuscript_html_path: str,
    auto_publish: bool = False,
    headless: bool = True,
    auto_post_social: bool = False,
    cover_path: Optional[str] = None,
) -> dict:
    """
    Launch both editions for a single book in sequence.

    Ebook first (so it gets the Amazon product page live faster), then paperback
    (which Amazon auto-links to the ebook listing if title/author/pub match).

    Returns {"ebook": {status, kdp_url, ...}, "paperback": {status, kdp_url, ...}, "title": str, "genre": str}
    """
    logger.info("═" * 60)
    logger.info("LAUNCHING: [%s] %s", genre, title)
    logger.info("═" * 60)

    result: dict = {"genre": genre, "title": title}

    # ── 1. EBOOK ────────────────────────────────────────────────────────
    logger.info("\n▶ Phase 1/2: EBOOK")
    try:
        ebook_result = upload_book(
            genre=genre,
            manuscript_path=manuscript_html_path,
            cover_path=cover_path,
            headless=headless,
            auto_publish=auto_publish,
        )
        result["ebook"] = ebook_result
        logger.info("✓ Ebook %s: %s", ebook_result.get("status"),
                    ebook_result.get("kdp_url", "(no url)"))
    except Exception as e:
        logger.error("✗ Ebook failed: %s", e)
        result["ebook"] = {"status": "error", "error": str(e)}

    # Small cooldown so KDP's rate limiter doesn't flag us
    time.sleep(10)

    # ── 2. PAPERBACK ────────────────────────────────────────────────────
    logger.info("\n▶ Phase 2/2: PAPERBACK")
    try:
        paperback_result = upload_paperback(
            genre=genre,
            title=title,
            manuscript_html_path=manuscript_html_path,
            auto_publish=auto_publish,
            headless=headless,
        )
        result["paperback"] = paperback_result
        logger.info("✓ Paperback %s: %s", paperback_result.get("status"),
                    paperback_result.get("kdp_url", "(no url)"))
    except Exception as e:
        logger.error("✗ Paperback failed: %s", e)
        result["paperback"] = {"status": "error", "error": str(e)}

    # ── 3. Social fan-out (optional) ────────────────────────────────────
    if auto_post_social:
        try:
            from narai.godmode.launch import post_to_all
            social = post_to_all(
                title=title, genre=genre,
                ebook_url=result["ebook"].get("kdp_url", ""),
                paperback_url=result["paperback"].get("kdp_url", ""),
            )
            result["social"] = social
            logger.info("✓ Social: posted to %d platforms", sum(1 for v in social.values() if v.get("ok")))
        except Exception as e:
            logger.warning("Social fan-out failed: %s", e)
            result["social"] = {"error": str(e)}

    # ── 4. Save combined result ─────────────────────────────────────────
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "outputs" / "books" / f"launch_{genre}_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    logger.info("\nCombined result saved: %s\n", out)

    return result


def launch_all(
    auto_publish: bool = False,
    headless: bool = True,
    auto_post_social: bool = False,
) -> list[dict]:
    """
    Launch ebook+paperback for every published-kindle book that doesn't yet
    have a paperback. Skips books that already went through this flow.
    """
    registry_path = ROOT / "data" / "kdp_registry.json"
    registry = json.loads(registry_path.read_text())

    # Eligible: books with a manuscript_path but no paperback yet
    paperback_titles = {
        e["title"] for e in registry
        if e.get("format") == "paperback" and e.get("status") in ("published", "ready_to_publish")
    }

    candidates = [
        e for e in registry
        if e.get("status") in ("published", "ready_to_publish")
        and e.get("title") not in paperback_titles
        and e.get("manuscript_path")
        and e.get("format") != "paperback"
    ]

    results = []
    for i, entry in enumerate(candidates, 1):
        logger.info("\n[%d/%d] Starting launch for: %s", i, len(candidates), entry["title"])
        ms_path = entry["manuscript_path"]
        if not Path(ms_path).exists():
            # Search outputs/books/packaged/ for a matching HTML
            packaged = ROOT / "outputs" / "books" / "packaged"
            words = [w.lower() for w in entry["title"].split() if len(w) > 3][:3]
            hits = [
                f for f in packaged.glob("*.html")
                if all(w in f.stem.lower() for w in words)
            ]
            if hits:
                ms_path = str(sorted(hits, key=lambda f: f.stat().st_mtime, reverse=True)[0])
                logger.info("Manuscript fallback: %s", ms_path)
            else:
                logger.warning("No manuscript for '%s' — skipping", entry["title"])
                continue

        result = launch_book(
            genre=entry.get("genre", "")[:20].rstrip(),
            title=entry["title"],
            manuscript_html_path=ms_path,
            auto_publish=auto_publish,
            headless=headless,
            auto_post_social=auto_post_social,
        )
        results.append(result)
        time.sleep(15)  # breathing room between books

    return results


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    p = argparse.ArgumentParser(description="KDP Unified Launcher — ebook + paperback together")
    p.add_argument("--genre", type=str, help="Launch both editions for one genre")
    p.add_argument("--all", action="store_true", help="Launch every eligible book")
    p.add_argument("--visible", action="store_true", help="Show browser window")
    p.add_argument("--no-publish", action="store_true", help="Stop before clicking Publish")
    p.add_argument("--auto-post", action="store_true",
                   help="After launch, fan out posts to X/FB/IG via narai.godmode")
    args = p.parse_args()

    headless = not args.visible
    auto_publish = not args.no_publish

    if args.all:
        print("\n" + "═" * 64)
        print("  KDP UNIFIED LAUNCHER — ebook + paperback for every genre")
        print("═" * 64 + "\n")
        results = launch_all(
            auto_publish=auto_publish,
            headless=headless,
            auto_post_social=args.auto_post,
        )
        ok_ebook = sum(1 for r in results if r.get("ebook", {}).get("status") in ("published", "ready_to_publish"))
        ok_pb = sum(1 for r in results if r.get("paperback", {}).get("status") in ("published", "ready_to_publish"))
        print(f"\n✅ {len(results)} books processed · {ok_ebook} ebooks OK · {ok_pb} paperbacks OK")
    elif args.genre:
        reg = json.loads((ROOT / "data" / "kdp_registry.json").read_text())
        entry = next(
            (e for e in reg if e.get("genre", "").startswith(args.genre[:5])),
            None
        )
        if not entry:
            print(f"No registry entry for genre '{args.genre}'")
            sys.exit(1)
        launch_book(
            genre=args.genre,
            title=entry["title"],
            manuscript_html_path=entry.get("manuscript_path", ""),
            auto_publish=auto_publish,
            headless=headless,
            auto_post_social=args.auto_post,
        )
    else:
        print("Usage:")
        print("  python -m core.kdp_launch --genre mystery")
        print("  python -m core.kdp_launch --all [--auto-post] [--visible] [--no-publish]")
