#!/usr/bin/env python3
"""
scripts/nexora_waitlist_kit.py
─────────────────────────────────────────────────────────────────────────────
Idempotently wire the NEXORA founding-creator waitlist in Kit (ConvertKit v4):

  1. ensure a `nexora-waitlist` tag exists                         (API-creatable)
  2. populate the "NEXORA Waitlist" sequence with 3 welcome emails  (sequence SHELL
     must already exist — Kit's API can't create a sequence; create an empty one
     named exactly "NEXORA Waitlist" in the Kit dashboard, then re-run)

Honors KIT_DRY_RUN: with it on, reads still hit the API (to show current state)
but NO write is sent — every create is logged as a plan only.

Usage:
    cd /Volumes/Wheellsverse/wheellsverse-bots
    KIT_DRY_RUN=1 python scripts/nexora_waitlist_kit.py      # preview (no writes)
    KIT_DRY_RUN=0 python scripts/nexora_waitlist_kit.py      # live (creates tag + emails)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.kit import KitClient  # noqa: E402

TAG_NAME = "nexora-waitlist"
SEQUENCE_NAME = "NEXORA Waitlist"

EMAILS = [
    {
        "subject": "You're on the NEXORA founding list \U0001F389",
        "delay_value": 0,
        "delay_unit": "days",
        "preview_text": "The creator platform that pays you 90%.",
        "content": (
            "<p>You just claimed early access to <strong>NEXORA</strong> — the creator "
            "platform built so the money is actually yours: <strong>90% to you, 10% to us.</strong> "
            "Subscriptions, pay-per-view, tips, and live rooms, all in one place.</p>"
            "<p>We’re onboarding founding creators in small waves. You’ll get your invite "
            "— and the chance to reserve your handle — soon.</p>"
            "<p>Reply and tell me what you create. Founding creators get priority verification.</p>"
            "<p>— The NEXORA team</p>"
        ),
    },
    {
        "subject": "Here's exactly what you'll get",
        "delay_value": 2,
        "delay_unit": "days",
        "preview_text": "Every way to earn, one dashboard.",
        "content": (
            "<p>While we open the next wave, here’s what’s waiting for you inside NEXORA:</p>"
            "<ul>"
            "<li><strong>Recurring subscriptions</strong> — set your price, keep 90%.</li>"
            "<li><strong>Pay-per-view posts</strong> — lock premium drops, sell them individually.</li>"
            "<li><strong>Tips &amp; live tipping</strong> — one-tap support during posts and live rooms.</li>"
            "<li><strong>Direct messages</strong> — talk to your top fans, your way.</li>"
            "<li><strong>A payout you can read</strong> — real-time balance, $20 minimum, no mystery holds.</li>"
            "</ul>"
            "<p>No 50% platform cut. No algorithm deciding who sees your offer.</p>"
            "<p>Reply with your handle of choice and we’ll do our best to hold it for you.</p>"
            "<p>— The NEXORA team</p>"
        ),
    },
    {
        "subject": "Your wave is opening — reserve your handle",
        "delay_value": 5,
        "delay_unit": "days",
        "preview_text": "Founding-creator perks end at 100.",
        "content": (
            "<p>Founding spots are filling. As a founding creator you lock in "
            "<strong>reduced platform fees for life</strong> and <strong>priority verification</strong> "
            "— both end once we hit 100.</p>"
            "<p>When your invite lands, you’ll go from signup to first paid post in minutes.</p>"
            "<p>Want in on the first wave? Just reply “ready” and we’ll prioritize your invite.</p>"
            "<p>— The NEXORA team</p>"
        ),
    },
]


def _find_by_name(items, name):
    target = name.strip().lower()
    for it in items:
        if str(it.get("name", "")).strip().lower() == target:
            return it
    return None


def ensure_tag(kit: KitClient) -> None:
    print(f"\n— Tag '{TAG_NAME}' —")
    existing = _find_by_name(kit.list_tags(), TAG_NAME)
    if existing:
        print(f"  ✓ exists (id={existing.get('id')})")
        return
    res = kit.create_tag(TAG_NAME)
    if res.get("_dry_run"):
        print(f"  ▷ WOULD create tag (dry-run): POST {res['url']}")
    elif res.get("tag") or res.get("id"):
        print(f"  ✓ created (id={(res.get('tag') or res).get('id')})")
    else:
        print(f"  ✗ create failed: {res}")


def ensure_sequence_emails(kit: KitClient) -> None:
    print(f"\n— Sequence '{SEQUENCE_NAME}' —")
    seq = _find_by_name(kit.list_sequences(), SEQUENCE_NAME)
    if not seq:
        print("  ✗ sequence not found. Kit's API can't create sequences — create an")
        print(f"    EMPTY sequence named exactly '{SEQUENCE_NAME}' in the Kit dashboard")
        print("    (Automate → Sequences → New), then re-run this script to add the emails.")
        return
    seq_id = seq.get("id")
    print(f"  ✓ found (id={seq_id})")
    existing_subjects = {
        str(e.get("subject", "")).strip().lower() for e in kit.list_sequence_emails(seq_id)
    }
    for i, em in enumerate(EMAILS, 1):
        if em["subject"].strip().lower() in existing_subjects:
            print(f"  ✓ email {i} already present: {em['subject']!r}")
            continue
        res = kit.create_sequence_email(
            seq_id,
            subject=em["subject"],
            delay_value=em["delay_value"],
            delay_unit=em["delay_unit"],
            content=em["content"],
            preview_text=em["preview_text"],
            position=i,
            published=False,  # left as DRAFT — operator reviews + publishes in Kit
        )
        if res.get("_dry_run"):
            print(f"  ▷ WOULD add email {i} (dry-run): {em['subject']!r} (+{em['delay_value']}{em['delay_unit'][0]})")
        elif res.get("email") or res.get("id"):
            print(f"  ✓ added email {i}: {em['subject']!r} (DRAFT)")
        else:
            print(f"  ✗ add email {i} failed: {res}")


def main() -> int:
    kit = KitClient()
    print("=== NEXORA waitlist · Kit setup ===")
    print(f"dry_run={kit.dry_run}   base={kit.base_url}")
    if not kit.is_configured():
        print("✗ KIT_API_KEY not set — nothing to do. Set it in the repo .env.")
        return 1
    acct = kit.get_account()
    name = (acct.get("account") or {}).get("name") if isinstance(acct.get("account"), dict) else acct.get("name")
    if acct.get("error") or acct.get("status", 200) >= 400:
        print(f"✗ account check failed: {acct}")
        return 1
    print(f"✓ authenticated to Kit account: {name or '(unknown)'}")
    ensure_tag(kit)
    ensure_sequence_emails(kit)
    print("\nDone." + ("  (dry-run — no writes were sent)" if kit.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
