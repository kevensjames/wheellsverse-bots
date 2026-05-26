#!/usr/bin/env python3
"""
scripts/toodle_kit_check.py
─────────────────────────────────────────────────────────────────────────────
Verify the Kit (formerly ConvertKit) workspace is wired correctly for the
Toodle Capture Agent. Reads live tags + sequences via Kit v4 API and reports
which of the three expected sequences exist by name.

This script is read-only — it makes only GET calls. Safe to run even with
KIT_DRY_RUN=true (read calls always go to the real Kit API; only writes are
gated by the dry-run flag).

Usage:
  KIT_API_KEY=... python scripts/toodle_kit_check.py
  (or set KIT_API_KEY in .env / wvkey)

Exit codes:
  0 = all expected sequences resolved
  1 = at least one expected sequence is missing — create it in Kit's UI
  2 = KIT_API_KEY not set or Kit API unreachable
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.kit import get_kit  # noqa: E402

EXPECTED_SEQUENCES = {
    "kdp": os.getenv("KIT_SEQUENCE_KDP_NAME", "KDP Launch"),
    "welcome": os.getenv("KIT_SEQUENCE_WELCOME_NAME", "Welcome"),
    "longtail": os.getenv("KIT_SEQUENCE_KDP_LONGTAIL_NAME", "KDP Long-Tail"),
}


def main() -> int:
    client = get_kit()
    if not client.is_configured():
        print("✗ KIT_API_KEY not set in env (.env or shell)", file=sys.stderr)
        print("  Generate v4 key at Kit → Settings → Advanced → API Keys.", file=sys.stderr)
        return 2

    # Account sanity check first
    account = client.get_account()
    if "error" in account or "account" not in account:
        print(f"✗ Cannot reach Kit API. Response: {account}", file=sys.stderr)
        return 2
    acc = account.get("account") or {}
    print(f"✓ Connected to Kit account: {acc.get('name', '(no name)')} "
          f"({acc.get('primary_email_address', '(no email)')})")
    print(f"  Base URL: {client.base_url}")
    print(f"  Dry run : {client.dry_run}")
    print()

    # Tags
    tags = client.list_tags()
    print(f"Tags ({len(tags)} total):")
    for t in sorted(tags, key=lambda x: x.get("name", "").lower())[:25]:
        print(f"  {t.get('id'):>6}  {t.get('name')}")
    if len(tags) > 25:
        print(f"  … {len(tags) - 25} more")
    print()

    # Sequences — the load-bearing check
    sequences = client.list_sequences()
    by_name_lower = {(s.get("name") or "").strip().lower(): s for s in sequences}
    print(f"Sequences ({len(sequences)} total):")
    for s in sequences:
        print(f"  {s.get('id'):>6}  {s.get('name')}")
    print()

    print("Expected sequences (from .env defaults):")
    missing = []
    for key, expected_name in EXPECTED_SEQUENCES.items():
        match = by_name_lower.get(expected_name.strip().lower())
        if match:
            print(f"  ✓ {key:8} → '{expected_name}'  (id={match['id']})")
        else:
            print(f"  ✗ {key:8} → '{expected_name}'  MISSING")
            missing.append(expected_name)
    print()

    if missing:
        print("Action needed — create these sequences in Kit's UI:")
        for name in missing:
            print(f"  • {name}")
        print()
        print("Where to paste the email content:")
        print("  KDP Launch    → marketing/kdp_nurture_sequence.md   (5 emails)")
        print("  Welcome       → marketing/welcome_sequence.md       (2 emails)")
        print("  KDP Long-Tail → marketing/kdp_longtail_sequence.md  (3 emails)")
        return 1

    print("All expected sequences exist. Toodle Capture Agent will resolve them by name.")
    print("Next: POST a real capture (e.g. from your own email) and watch /toodle/status.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
