"""
Launch queue — polls the KDP registry and auto-posts when books go live.

Design:
    data/launch_queue.json         — pending launches (FIFO)
    data/launch_queue_posted.json  — history of completed launches
    data/launch_queue_state.json   — last-seen registry snapshot per book

Usage:

    # One-off: enqueue a book you just published
    python -m narai_godmode.launch_queue add \\
        --title "The Last Cartographer" --genre adventure \\
        --ebook-url "https://amazon.com/dp/B0XXXX" \\
        --paperback-url "https://amazon.com/dp/979XXXX"

    # Scan kdp_registry for newly-live books and auto-enqueue them
    python -m narai_godmode.launch_queue detect

    # Process the queue once (cron-friendly)
    python -m narai_godmode.launch_queue run

    # Daemon mode — poll every 60s forever
    python -m narai_godmode.launch_queue daemon --interval 60

    # List what's pending and what's been posted
    python -m narai_godmode.launch_queue list

How "is it live?" is detected:
    A registry entry is considered LIVE when BOTH:
      - status == "published" or "live"
      - kdp_url contains "/dp/" (real Amazon product URL, not /pricing draft)
         OR asin starts with "B0" (Kindle) or "97" (ISBN-13 paperback)
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
QUEUE_FILE = DATA_DIR / "launch_queue.json"
POSTED_FILE = DATA_DIR / "launch_queue_posted.json"
REGISTRY_FILE = DATA_DIR / "kdp_registry.json"

logger = logging.getLogger("launch_queue")


# ── State helpers ────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to read %s: %s", path, e)
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _load_queue() -> list[dict]:
    return _read(QUEUE_FILE, [])


def _load_posted() -> list[dict]:
    return _read(POSTED_FILE, [])


# ── Core API ─────────────────────────────────────────────────────────────────

def enqueue(title: str, genre: str,
            ebook_url: str = "", paperback_url: str = "",
            ig_image_url: str = "") -> dict:
    """Append a book to the launch queue. Dedupes by (title, genre)."""
    q = _load_queue()
    posted = _load_posted()
    key = (title.strip().lower(), genre.strip().lower())

    for e in q:
        if (e["title"].strip().lower(), e["genre"].strip().lower()) == key:
            logger.info("Already queued: %s", title)
            return e
    for e in posted:
        if (e["title"].strip().lower(), e["genre"].strip().lower()) == key:
            logger.info("Already posted: %s", title)
            return e

    entry = {
        "title": title, "genre": genre,
        "ebook_url": ebook_url, "paperback_url": paperback_url,
        "ig_image_url": ig_image_url,
        "queued_at": _iso_now(),
        "attempts": 0,
    }
    q.append(entry)
    _write(QUEUE_FILE, q)
    logger.info("Queued: [%s] %s", genre, title)
    return entry


def _is_live(entry: dict) -> bool:
    """Return True if this registry entry looks like an actually-live Amazon listing."""
    status = (entry.get("status") or "").lower()
    if status not in ("published", "live"):
        return False
    kdp_url = entry.get("kdp_url") or ""
    asin = entry.get("asin") or ""
    if "/dp/" in kdp_url:
        return True
    if re.match(r"^(B0[A-Z0-9]{8}|97[89][0-9]{10})$", asin):
        return True
    return False


def _public_amazon_url(entry: dict) -> str:
    """Build a real Amazon product URL from a registry entry.
    Prefers /dp/ links and valid ASINs over KDP draft URLs."""
    url = entry.get("kdp_url") or ""
    asin = entry.get("asin") or ""
    if "/dp/" in url:
        return url
    # Valid Kindle (B0...) or ISBN-13 (97...) ASIN — build canonical URL
    if re.match(r"^(B0[A-Z0-9]{8}|97[89][0-9]{10})$", asin):
        return f"https://amazon.com/dp/{asin}"
    # Else: no reliable public URL — caller should decide what to do
    return ""


def _kindle_vs_paperback(asin: str, fmt: str) -> str:
    """Return 'ebook' or 'paperback' based on ASIN prefix first, format label second."""
    if asin.startswith("B0"):
        return "ebook"
    if asin.startswith(("97", "979", "978")):
        return "paperback"
    return (fmt or "ebook").lower()


def detect_from_registry() -> list[dict]:
    """Scan kdp_registry for freshly-live books and enqueue any not yet queued/posted.
    Groups by title so ebook + paperback with the same title share one queue entry."""
    reg = _read(REGISTRY_FILE, [])
    # Collect all live entries grouped by title
    by_title: dict[str, dict] = {}
    for entry in reg:
        if not _is_live(entry):
            continue
        title = entry.get("title", "").strip()
        if not title:
            continue
        asin = entry.get("asin") or ""
        url = _public_amazon_url(entry)
        kind = _kindle_vs_paperback(asin, entry.get("format") or "")
        g = by_title.setdefault(title, {"title": title, "genre": entry.get("genre", ""),
                                         "ebook_url": "", "paperback_url": ""})
        if kind == "ebook" and url and not g["ebook_url"]:
            g["ebook_url"] = url
        elif kind == "paperback" and url and not g["paperback_url"]:
            g["paperback_url"] = url

    newly_queued = []
    for g in by_title.values():
        # Skip books that don't have at least one public URL — nothing useful to post
        if not g["ebook_url"] and not g["paperback_url"]:
            logger.debug("Skipping %s — no public Amazon URL available", g["title"])
            continue
        result = enqueue(title=g["title"], genre=g["genre"],
                         ebook_url=g["ebook_url"], paperback_url=g["paperback_url"])
        newly_queued.append(result)
    return newly_queued


def _verify_amazon_url(url: str, expected_title: str = "") -> tuple[bool, str]:
    """Fetch url with a browser UA; return (ok, reason).

    ok == True means we saw book-page markers AND (if expected_title) a title match.
    Amazon returns HTTP 200 for every ASIN-shaped URL, even dead ones (they show
    a 'Looking for something?' / 'dogs of Amazon' page), so we check for real
    book-page markers in the HTML and cross-reference the expected title.
    """
    import requests
    if not url or "/dp/" not in url:
        return False, "not an Amazon product URL"
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
    except Exception as e:
        return False, f"fetch error: {e}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    html = r.text.lower()
    # Book-page markers — at least one must be present on a real product page
    markers = ("producttitle", "kindle edition", "paperback", "a-price", "buy now with 1-click")
    if not any(m in html for m in markers):
        return False, "no book-page markers (likely dead ASIN or bot wall)"
    # Title match — at least 3 consecutive significant words from the expected title.
    # Strip punctuation so "Seven Suspects, One Alibi:" matches against a page that
    # renders the title without the comma/colon.
    if expected_title:
        stripped = re.sub(r"[^\w\s]", " ", expected_title.lower())
        words = [w for w in stripped.split() if len(w) > 3][:3]
        needle = " ".join(words)
        if needle and needle not in html:
            return False, f"title mismatch (no '{needle}' in page)"
    return True, "ok"


def run_once(platforms: tuple[str, ...] = ("x", "fb", "ig", "gmail"),
             max_retries: int = 3,
             skip_verify: bool = False) -> list[dict]:
    """Process the queue: post every pending entry, move successful ones to posted.
    Returns the list of entries processed this pass.

    skip_verify=True bypasses the Amazon URL liveness check. Only use after
    you've manually confirmed each URL in a browser.
    """
    from .launch import post_to_all

    queue = _load_queue()
    if not queue:
        logger.info("Queue empty — nothing to post.")
        return []

    posted = _load_posted()
    still_pending = []
    processed = []

    for entry in queue:
        entry["attempts"] = entry.get("attempts", 0) + 1
        logger.info("Posting [%s] %s (attempt %d)", entry["genre"], entry["title"], entry["attempts"])

        # Verification gate — check each URL is actually live on Amazon.
        # Entries failing verification stay in queue with last_error but are NOT
        # retried automatically (would just hammer Amazon and loop). User must
        # re-run with --skip-verify after manual inspection.
        if not skip_verify:
            urls_to_check = [(k, entry.get(k + "_url", ""))
                             for k in ("ebook", "paperback")
                             if entry.get(k + "_url")]
            fails = []
            for kind, url in urls_to_check:
                ok, reason = _verify_amazon_url(url, expected_title=entry["title"])
                if not ok:
                    fails.append(f"{kind}: {reason}")
            if fails:
                entry["last_error"] = "verify_failed: " + " | ".join(fails)
                entry["last_verify_failed_at"] = _iso_now()
                still_pending.append(entry)
                logger.warning("⚠ %s — URL verification failed: %s",
                               entry["title"], entry["last_error"])
                processed.append({**entry, "status": "verify_blocked"})
                continue

        try:
            result = post_to_all(
                title=entry["title"],
                genre=entry["genre"],
                ebook_url=entry.get("ebook_url", ""),
                paperback_url=entry.get("paperback_url", ""),
                ig_image_url=entry.get("ig_image_url", ""),
                platforms=platforms,
            )
            entry["result"] = result
            entry["posted_at"] = _iso_now()
            # Success if at least one platform reported ok
            any_ok = any(v.get("ok") for v in result.values())
            if any_ok:
                posted.append(entry)
                processed.append({**entry, "status": "posted"})
                logger.info("✓ Posted: %s (platforms: %s)", entry["title"],
                            ", ".join(k for k, v in result.items() if v.get("ok")))
            else:
                entry["last_error"] = "all platforms failed"
                if entry["attempts"] < max_retries:
                    still_pending.append(entry)
                    logger.warning("All platforms failed for %s — will retry", entry["title"])
                else:
                    posted.append({**entry, "status": "failed_max_retries"})
                    processed.append({**entry, "status": "failed"})
                    logger.error("Gave up on %s after %d attempts", entry["title"], entry["attempts"])
        except Exception as e:
            logger.error("Crash posting %s: %s", entry["title"], e)
            entry["last_error"] = str(e)[:500]
            if entry["attempts"] < max_retries:
                still_pending.append(entry)
            else:
                posted.append({**entry, "status": "failed_exception"})
                processed.append({**entry, "status": "error"})

    _write(QUEUE_FILE, still_pending)
    _write(POSTED_FILE, posted)
    return processed


def run_loop(interval: int = 60, detect_registry: bool = True,
             skip_verify: bool = False) -> None:
    """Daemon: forever poll the registry + queue. Ctrl-C to stop."""
    logger.info("Daemon started — poll interval %ds (skip_verify=%s)", interval, skip_verify)
    try:
        while True:
            if detect_registry:
                newly = detect_from_registry()
                if newly:
                    logger.info("Auto-detected %d new live book(s) from registry", len(newly))
            processed = run_once(skip_verify=skip_verify)
            if processed:
                logger.info("Processed %d entries this tick", len(processed))
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user.")


def list_state() -> dict:
    """Return a snapshot of queue + history."""
    return {
        "pending": _load_queue(),
        "posted":  _load_posted(),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    parent = argparse.ArgumentParser(description="NarAI launch queue — auto-post when books go live")
    sub = parent.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="Enqueue a book manually")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--genre", required=True)
    add_p.add_argument("--ebook-url", default="")
    add_p.add_argument("--paperback-url", default="")
    add_p.add_argument("--ig-image", default="")

    sub.add_parser("detect", help="Scan kdp_registry.json for live books, enqueue them")
    run_p = sub.add_parser("run", help="Process queue once and exit (good for cron)")
    run_p.add_argument("--skip-verify", action="store_true",
                       help="Skip Amazon URL liveness check (use only after manual verification)")

    daemon_p = sub.add_parser("daemon", help="Poll forever — auto-detect + auto-post")
    daemon_p.add_argument("--interval", type=int, default=60, help="Seconds between polls (default 60)")
    daemon_p.add_argument("--no-detect", action="store_true", help="Disable registry auto-detect")
    daemon_p.add_argument("--skip-verify", action="store_true",
                          help="Skip Amazon URL liveness check (use only after manual verification)")

    sub.add_parser("list", help="Print pending + posted entries")

    clear_p = sub.add_parser("clear", help="Clear the queue (does NOT touch posted history)")
    clear_p.add_argument("--yes", action="store_true", help="Skip confirmation")

    args = parent.parse_args()

    if args.cmd == "add":
        entry = enqueue(args.title, args.genre,
                        args.ebook_url, args.paperback_url, args.ig_image)
        print(json.dumps(entry, indent=2))
        return 0

    if args.cmd == "detect":
        newly = detect_from_registry()
        print(f"Detected {len(newly)} newly-live book(s)")
        for e in newly:
            print(f"  • [{e['genre']}] {e['title']}")
        return 0

    if args.cmd == "run":
        processed = run_once(skip_verify=args.skip_verify)
        print(f"Processed {len(processed)} entries")
        for e in processed:
            status = e.get("status", "?")
            if status == "verify_blocked":
                print(f"  ⚠ [{e.get('genre')}] {e.get('title')} → {status}: {e.get('last_error','')}")
            else:
                plats = ", ".join(k for k, v in (e.get("result") or {}).items() if v.get("ok"))
                print(f"  • [{e.get('genre')}] {e.get('title')} → {status} ({plats})")
        return 0

    if args.cmd == "daemon":
        run_loop(interval=args.interval,
                 detect_registry=not args.no_detect,
                 skip_verify=args.skip_verify)
        return 0

    if args.cmd == "list":
        state = list_state()
        print(f"\nPending ({len(state['pending'])}):")
        for e in state["pending"]:
            print(f"  • [{e['genre']}] {e['title']}  (attempts={e.get('attempts',0)})")
        print(f"\nPosted ({len(state['posted'])}):")
        for e in state["posted"][-10:]:
            print(f"  • [{e['genre']}] {e['title']}  → {e.get('status', 'posted')} at {e.get('posted_at','?')}")
        return 0

    if args.cmd == "clear":
        if not args.yes:
            resp = input("Clear the pending queue? (y/N): ")
            if resp.strip().lower() != "y":
                print("Aborted.")
                return 1
        _write(QUEUE_FILE, [])
        print("Queue cleared.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
