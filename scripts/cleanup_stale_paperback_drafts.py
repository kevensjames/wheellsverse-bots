#!/usr/bin/env python3
"""
scripts/cleanup_stale_paperback_drafts.py
───────────────────────────────────────────────────────────────────────────────
Remove paperback entries with status="ready_to_publish" from data/kdp_registry.json.

These are stale drafts that hit KDP's anti-automation gates (ISBN / marketplace
/ previewer) and have been waiting for manual finishing. The user has chosen
to scrap them and start fresh on the new orchestrator.

This script ONLY cleans the local registry. It writes the dropped entries +
their KDP draft URLs to outputs/books/stale_paperback_drafts_to_delete.json
so you can delete them manually at https://kdp.amazon.com/en_US/bookshelf
(KDP doesn't expose a stable "delete draft" API).

Usage:
  .venv/bin/python scripts/cleanup_stale_paperback_drafts.py            # dry-run
  .venv/bin/python scripts/cleanup_stale_paperback_drafts.py --apply    # apply
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "kdp_registry.json"
DROPLIST = ROOT / "outputs" / "books" / "stale_paperback_drafts_to_delete.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not REGISTRY.exists():
        print(f"Registry missing: {REGISTRY}", file=sys.stderr)
        return 1

    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    stale = [
        e for e in reg
        if e.get("format") == "paperback" and e.get("status") == "ready_to_publish"
    ]
    kept = [e for e in reg if e not in stale]

    print(f"Registry total: {len(reg)}")
    print(f"Stale paperback ready_to_publish drafts: {len(stale)}")
    for e in stale:
        url = e.get("kdp_url", "(no kdp_url stored)")
        print(f"  - [{e.get('genre')}] {e.get('title')[:60]}")
        print(f"     URL: {url}")
    print(f"Will keep: {len(kept)}")

    if not args.apply:
        print("\nDRY RUN — pass --apply to write.")
        return 0

    backup = REGISTRY.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(REGISTRY, backup)
    print(f"\nBacked up registry to {backup.name}")

    DROPLIST.parent.mkdir(parents=True, exist_ok=True)
    DROPLIST.write_text(
        json.dumps(
            {
                "saved_at": datetime.now().isoformat(),
                "count": len(stale),
                "instructions": "Delete each draft manually at https://kdp.amazon.com/en_US/bookshelf — KDP has no stable delete API.",
                "drafts": stale,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Dropped entries saved to {DROPLIST.relative_to(ROOT)} (so you have the KDP URLs for manual deletion)")

    REGISTRY.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote cleaned registry: {len(kept)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
