#!/usr/bin/env python3
"""
scripts/dedupe_autopilot_queue.py
───────────────────────────────────────────────────────────────────────────────
Collapse duplicate entries in data/kdp_autopilot_queue.json.

Rules:
  - Group by normalized title (strip + lowercase)
  - If any entry in the group has status="published", drop the whole group
    (don't re-publish what's already live)
  - Otherwise keep the entry with the highest qc_score; ties broken by most
    recent queued_at
  - Backup the original queue to data/kdp_autopilot_queue.json.bak.<ts> before writing

Idempotent. Safe to re-run.

Usage:
  .venv/bin/python scripts/dedupe_autopilot_queue.py            # dry-run
  .venv/bin/python scripts/dedupe_autopilot_queue.py --apply    # write changes
"""
import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_FILE = ROOT / "data" / "kdp_autopilot_queue.json"


def _norm(title: str) -> str:
    return (title or "").strip().lower()


def dedupe(queue: list) -> tuple[list, dict]:
    """Return (kept, summary). Pure function — does not write."""
    groups: dict[str, list] = defaultdict(list)
    for it in queue:
        groups[_norm(it.get("title", ""))].append(it)

    kept: list = []
    dropped_published_groups: list[str] = []
    dropped_dupes: list[tuple[str, int]] = []

    for key, items in groups.items():
        if any(it.get("status") == "published" for it in items):
            dropped_published_groups.append(items[0].get("title", key))
            continue
        if len(items) == 1:
            kept.append(items[0])
            continue
        winner = max(
            items,
            key=lambda x: (
                int(x.get("qc_score") or 0),
                x.get("queued_at", ""),
            ),
        )
        kept.append(winner)
        dropped_dupes.append((winner.get("title", key), len(items) - 1))

    summary = {
        "input_count": len(queue),
        "output_count": len(kept),
        "dropped_already_published": dropped_published_groups,
        "collapsed_dupes": dropped_dupes,
    }
    return kept, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes to disk")
    args = ap.parse_args()

    if not QUEUE_FILE.exists():
        print(f"Queue file not found: {QUEUE_FILE}", file=sys.stderr)
        return 1

    queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    kept, summary = dedupe(queue)

    print(f"Input:  {summary['input_count']} entries")
    print(f"Output: {summary['output_count']} entries")
    print()
    if summary["dropped_already_published"]:
        print("Dropped (already published — would re-publish):")
        for t in summary["dropped_already_published"]:
            print(f"  - {t}")
        print()
    if summary["collapsed_dupes"]:
        print("Collapsed duplicates (kept best qc_score):")
        for title, n_dropped in summary["collapsed_dupes"]:
            print(f"  - {title}  (-{n_dropped} dupes)")
        print()

    if not args.apply:
        print("DRY RUN — pass --apply to write.")
        return 0

    backup = QUEUE_FILE.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(QUEUE_FILE, backup)
    print(f"Backed up to {backup.name}")

    QUEUE_FILE.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(kept)} entries to {QUEUE_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
