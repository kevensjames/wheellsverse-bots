#!/usr/bin/env python3
"""
scripts/daily_kdp_publish.py
───────────────────────────────────────────────────────────────────────────────
Daily multi-format KDP publisher.

Per run:
  1. Pick the next book from kdp_autopilot_queue.json or kdp_registry.json
  2. Gate: qc_score >= QC_THRESHOLD (default 90) → otherwise skip with notice
  3. Kindle ebook    → auto_publish=True   (goes live immediately)
  4. Paperback       → auto_publish=False  (creates KDP draft, status=ready_to_publish)
  5. Hardcover       → STUB (Phase B); will fall back to "not_implemented" until kdp_hardcover.py lands
  6. Registry + queue updated per format
  7. Telegram notification with per-format status

The QC gate only blocks AUTO_PUBLISH on Kindle; paperback/hardcover always go to
ready_to_publish (KDP's anti-automation gates require manual finishing anyway).

Usage:
  .venv/bin/python scripts/daily_kdp_publish.py                  # one book, all formats
  .venv/bin/python scripts/daily_kdp_publish.py --dry-run        # show what would happen
  .venv/bin/python scripts/daily_kdp_publish.py --formats kindle # restrict formats
  .venv/bin/python scripts/daily_kdp_publish.py --qc-min 85      # override QC threshold

Schedule: Railway scheduler (post-migration). Local launchd plist will be
disabled once Railway is verified.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [kdp_daily] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "kdp_daily.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("kdp_daily")

QUEUE_FILE    = ROOT / "data" / "kdp_autopilot_queue.json"
REGISTRY_FILE = ROOT / "data" / "kdp_registry.json"
DEFAULT_QC_MIN = int(os.getenv("KDP_QC_MIN", "90"))
DEFAULT_FORMATS = os.getenv("KDP_FORMATS", "kindle,paperback,hardcover").split(",")


# ═══════════════════════════════════════════════════════════════════════════════
# Queue / registry helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not parse %s: %s", path.name, e)
        return default


def _save_queue(queue: list) -> None:
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def _pick_next_book(qc_min: int) -> dict | None:
    """
    Return next eligible book. Eligibility = status not yet 'published' AND
    qc_score >= qc_min. Queue is preferred over registry. Returns None if none.
    """
    queue = _load_json(QUEUE_FILE, [])
    for it in queue:
        if it.get("status") in ("queued", "draft", "pending") and \
           int(it.get("qc_score") or 0) >= qc_min:
            return {"source": "queue", "item": it}

    registry = _load_json(REGISTRY_FILE, [])
    for entry in registry:
        if entry.get("status") == "draft" and \
           int(entry.get("qc_score") or 0) >= qc_min and \
           entry.get("format") in (None, "", "kindle"):
            return {"source": "registry", "item": entry}

    return None


def _mark_format_done(source: str, item: dict, fmt: str, result: dict) -> None:
    """Update queue + registry for a single format's result."""
    title = item.get("title", "")

    if source == "queue":
        queue = _load_json(QUEUE_FILE, [])
        for q in queue:
            if q.get("title") == title:
                q.setdefault("formats", {})[fmt] = {
                    "status": result.get("status"),
                    "kdp_url": result.get("kdp_url", ""),
                    "completed_at": datetime.now().isoformat(),
                }
                # Mark the queue entry as 'published' once Kindle is live
                # (paperback/hardcover may still be at ready_to_publish)
                if fmt == "kindle" and result.get("status") == "published":
                    q["status"] = "published"
                    q["kdp_url"] = result.get("kdp_url", "")
                    q["published_at"] = datetime.now().isoformat()
        _save_queue(queue)

    try:
        from core.kdp_registry import get_registry
        reg = get_registry()
        existing = reg.find_by_title(title)
        if existing:
            reg.update_entry(
                existing["id"],
                status=result.get("status", "ready_to_publish"),
                kdp_url=result.get("kdp_url", "") or existing.get("kdp_url", ""),
                publish_date=datetime.now().strftime("%Y-%m-%d") if result.get("status") == "published" else existing.get("publish_date", ""),
            )
        else:
            reg.add_book(
                title=title,
                genre=item.get("genre", "mystery"),
                status=result.get("status", "ready_to_publish"),
                format=fmt,
                kdp_url=result.get("kdp_url", ""),
                manuscript_path=item.get("manuscript_path", ""),
                qc_score=int(item.get("qc_score") or 0),
            )
    except Exception as e:
        log.warning("Registry update failed for %s/%s: %s", title, fmt, e)


# ═══════════════════════════════════════════════════════════════════════════════
# Per-format publishers
# ═══════════════════════════════════════════════════════════════════════════════

def publish_kindle(item: dict, *, auto_publish: bool, headless: bool) -> dict:
    """Kindle ebook: auto-publishes when QC gate passes."""
    from core.kdp_uploader import upload_book

    manuscript_path = item.get("manuscript_path") or item.get("html_path") or ""
    if manuscript_path and not Path(manuscript_path).exists():
        log.warning("Kindle manuscript missing on disk: %s — letting uploader search by genre", manuscript_path)
        manuscript_path = ""

    return upload_book(
        genre=item.get("genre", "mystery"),
        manuscript_path=manuscript_path or None,
        auto_publish=auto_publish,
        headless=headless,
        title=item.get("title") or None,
    )


def publish_paperback(item: dict, *, headless: bool) -> dict:
    """
    Paperback: always auto_publish=False. KDP's ISBN/marketplace/previewer gates
    require manual finishing on the web UI even when fields are pre-filled.
    """
    from core.kdp_paperback import upload_paperback

    title = item.get("title", "")
    html_path = item.get("html_path") or ""
    if not html_path or not Path(html_path).exists():
        # Fall back to looking inside outputs/books/packaged for a matching slug
        slug = "_".join(title.lower().split()[:6])
        candidates = sorted(
            (ROOT / "outputs" / "books" / "packaged").glob(f"*{slug}*.html"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        html_path = str(candidates[0]) if candidates else ""

    if not html_path:
        return {"status": "error", "error": f"No paperback HTML for '{title}'"}

    return upload_paperback(
        genre=item.get("genre", "mystery"),
        title=title,
        manuscript_html_path=html_path,
        auto_publish=False,
        headless=headless,
    )


def publish_hardcover(item: dict, *, headless: bool) -> dict:
    """Phase-B stub. Will call core.kdp_hardcover.upload_hardcover once landed."""
    try:
        from core.kdp_hardcover import upload_hardcover  # type: ignore
    except ImportError:
        log.info("Hardcover module not yet implemented — skipping for %s", item.get("title", "?"))
        return {
            "status": "not_implemented",
            "note": "core.kdp_hardcover not yet shipped; this slot will activate in Phase B.",
        }

    title = item.get("title", "")
    html_path = item.get("html_path") or ""
    if not html_path or not Path(html_path).exists():
        slug = "_".join(title.lower().split()[:6])
        candidates = sorted(
            (ROOT / "outputs" / "books" / "packaged").glob(f"*{slug}*.html"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        html_path = str(candidates[0]) if candidates else ""

    if not html_path:
        return {"status": "error", "error": f"No hardcover HTML for '{title}'"}

    return upload_hardcover(
        genre=item.get("genre", "mystery"),
        title=title,
        manuscript_html_path=html_path,
        auto_publish=False,
        headless=headless,
    )


PUBLISHERS = {
    "kindle":    publish_kindle,
    "paperback": publish_paperback,
    "hardcover": publish_hardcover,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Notification
# ═══════════════════════════════════════════════════════════════════════════════

def _format_emoji(status: str) -> str:
    return {
        "published":         "✅",
        "ready_to_publish":  "📝",
        "not_implemented":   "⏭",
        "skipped":           "⏭",
    }.get(status, "❌")


def _notify(title: str, results: dict) -> None:
    lines = [f"📚 KDP Daily — {datetime.now().strftime('%a %b %d, %Y')}", f"📖 {title}"]
    needs_clicks = []
    for fmt, r in results.items():
        st = r.get("status", "error")
        line = f"{_format_emoji(st)} {fmt.title()}: {st}"
        if r.get("kdp_url") and st in ("ready_to_publish", "review_required"):
            needs_clicks.append((fmt, r["kdp_url"]))
            line += f"\n   🔗 {r['kdp_url']}"
        elif r.get("error"):
            line += f"\n   ⚠ {str(r['error'])[:120]}"
        lines.append(line)

    if needs_clicks:
        lines.append("")
        lines.append(f"⚠ {len(needs_clicks)} format(s) need manual finish in KDP web UI (ISBN + marketplace + previewer gates).")

    msg = "\n".join(lines)
    log.info("\n%s", msg)
    try:
        from core.telegram import notify
        notify(msg)
    except Exception as e:
        log.warning("Telegram notify failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run(*, qc_min: int, formats: list[str], dry_run: bool, headless: bool) -> int:
    log.info("=== Daily KDP Publish — %s ===", datetime.now().strftime("%Y-%m-%d %H:%M"))
    log.info("Config: qc_min=%d formats=%s headless=%s dry_run=%s", qc_min, formats, headless, dry_run)

    picked = _pick_next_book(qc_min)
    if not picked:
        log.info("No eligible book (qc_score >= %d). Queue empty or all below threshold.", qc_min)
        try:
            from core.telegram import notify
            notify(f"📚 KDP Daily ({datetime.now().strftime('%a')}): nothing to publish — no books with qc_score >= {qc_min}.")
        except Exception:
            pass
        return 0

    source = picked["source"]
    item   = picked["item"]
    title  = item.get("title", "Unknown")
    qc     = int(item.get("qc_score") or 0)

    log.info("Picked: '%s' [genre=%s, qc=%d, source=%s]", title, item.get("genre"), qc, source)

    if dry_run:
        log.info("DRY RUN — would publish formats: %s", formats)
        return 0

    results: dict[str, dict] = {}
    kindle_failed = False

    for fmt in formats:
        if fmt not in PUBLISHERS:
            log.warning("Unknown format: %s", fmt)
            continue

        # If Kindle failed (likely auth issue), don't burn the print attempts
        if fmt in ("paperback", "hardcover") and kindle_failed:
            results[fmt] = {"status": "skipped", "error": "Kindle failed first; not attempting print formats."}
            continue

        log.info("─── Publishing %s ───", fmt)
        try:
            if fmt == "kindle":
                result = publish_kindle(item, auto_publish=True, headless=headless)
            else:
                result = PUBLISHERS[fmt](item, headless=headless)
        except Exception as e:
            log.exception("%s upload crashed: %s", fmt, e)
            result = {"status": "error", "error": str(e)[:200]}

        results[fmt] = result
        _mark_format_done(source, item, fmt, result)

        if fmt == "kindle" and result.get("status") not in ("published", "ready_to_publish"):
            kindle_failed = True
            log.warning("Kindle did not reach a happy state — skipping print formats this run.")

    _notify(title, results)
    log.info("=== Done ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily multi-format KDP publisher")
    ap.add_argument("--qc-min", type=int, default=DEFAULT_QC_MIN)
    ap.add_argument("--formats", type=str, default=",".join(DEFAULT_FORMATS),
                    help="Comma-separated: kindle,paperback,hardcover")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--visible", action="store_true", help="Show browser (debug)")
    args = ap.parse_args()

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    return run(
        qc_min=args.qc_min,
        formats=formats,
        dry_run=args.dry_run,
        headless=not args.visible,
    )


if __name__ == "__main__":
    sys.exit(main())
