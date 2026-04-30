#!/usr/bin/env python3
"""
scripts/daily_kdp_publish.py
───────────────────────────────────────────────────────────────────────────────
Publishes ONE book to Amazon KDP per day.

Queue priority:
  1. data/kdp_autopilot_queue.json  — books already written and waiting
  2. data/kdp_registry.json          — registry entries with status="draft"

Each run:
  1. Picks the next queued book
  2. Generates a cover (DALL-E 3 + uploads to Canva)
  3. Uploads to KDP and clicks Publish automatically
  4. Updates registry + queue
  5. Sends Telegram notification

Schedule: macOS LaunchAgent fires this every day at 09:00 AM.
Manual run: /Volumes/Wheellsverse/wheellsverse_bots/.venv/bin/python scripts/daily_kdp_publish.py
"""
import json
import logging
import sys
import time
from datetime import datetime
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
    format="%(asctime)s [kdp_daily] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs" / "kdp_daily.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("kdp_daily")

QUEUE_FILE   = ROOT / "data" / "kdp_autopilot_queue.json"
REGISTRY_FILE = ROOT / "data" / "kdp_registry.json"


# ── Queue helpers ──────────────────────────────────────────────────────────────

def _load_queue() -> list:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_queue(queue: list):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_registry() -> list:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _pick_next_book() -> dict | None:
    """
    Return the next book to publish.
    Checks autopilot queue first, then registry drafts.
    """
    # Source 1: autopilot queue
    queue = _load_queue()
    for item in queue:
        if item.get("status") in ("queued", "draft", "pending"):
            return {"source": "queue", "item": item}

    # Source 2: registry drafts
    registry = _load_registry()
    for entry in registry:
        if entry.get("status") == "draft":
            return {"source": "registry", "item": entry}

    return None


def _mark_done(source: str, item: dict, result: dict):
    """Mark the book as published in queue + registry."""
    # Update queue
    if source == "queue":
        queue = _load_queue()
        for q in queue:
            if q.get("title") == item.get("title"):
                q["status"] = "published"
                q["kdp_url"] = result.get("kdp_url", "")
                q["published_at"] = datetime.now().isoformat()
        _save_queue(queue)

    # Update registry
    try:
        from core.kdp_registry import get_registry
        reg = get_registry()
        entry = reg.find_by_title(item.get("title", ""))
        if entry:
            reg.update_entry(
                entry["id"],
                status=result.get("status", "published"),
                kdp_url=result.get("kdp_url", ""),
                publish_date=datetime.now().strftime("%Y-%m-%d"),
            )
    except Exception as e:
        log.warning("Registry update failed: %s", e)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    log.info("=== Daily KDP Publish — %s ===", datetime.now().strftime("%Y-%m-%d %H:%M"))

    picked = _pick_next_book()
    if not picked:
        log.info("Queue empty — no books to publish today.")
        try:
            from core.telegram import notify
            notify("📚 KDP Daily: Queue is empty — no books to publish today.\nRun the book writer to add more books.")
        except Exception:
            pass
        return

    source = picked["source"]
    item   = picked["item"]
    title  = item.get("title", "Unknown")
    genre  = item.get("genre", "mystery")

    log.info("Publishing: [%s] %s (source: %s)", genre, title, source)

    # Find manuscript
    manuscript_path = item.get("manuscript_path") or item.get("html_path") or ""
    if manuscript_path and not Path(manuscript_path).exists():
        log.warning("Manuscript not found at %s — letting uploader search by genre", manuscript_path)
        manuscript_path = ""

    # Upload + publish
    try:
        from core.kdp_uploader import upload_book
        result = upload_book(
            genre=genre,
            manuscript_path=manuscript_path or None,
            auto_publish=True,
            headless=True,
        )
    except Exception as e:
        log.error("Upload failed: %s", e)
        try:
            from core.telegram import notify
            notify(f"❌ KDP Daily failed for '{title}'\nError: {str(e)[:200]}")
        except Exception:
            pass
        return

    status = result.get("status", "error")
    _mark_done(source, item, result)

    log.info("Result: %s — %s", status, title)

    # Telegram notification
    try:
        from core.telegram import notify
        if status == "published":
            notify(
                f"✅ KDP Daily Published!\n"
                f"📖 {title}\n"
                f"🏷 Genre: {genre}\n"
                f"💰 ${result.get('price', '?')}\n"
                f"🔗 kdp.amazon.com/en_US/bookshelf"
            )
        else:
            notify(
                f"⚠️ KDP Daily — {status}\n"
                f"📖 {title}\n"
                f"Error: {result.get('error', result.get('note', ''))[:150]}"
            )
    except Exception:
        pass


if __name__ == "__main__":
    run()
