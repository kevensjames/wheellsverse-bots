"""SiteBoost persistent state — anti-duplicate guards across runs.

Problem this solves: NAI runs the pipeline weekly on different ZIPs. Without
state tracking, the same business could be scanned, enriched, AND emailed
twice — instant spam-trap. This module is the source of truth for:

    - Which place_ids have ever been scanned (so we skip on re-scan)
    - Which emails have ever been sent (so we never double-email)
    - Which ZIP/category combos were scanned and when (so we rotate)

State lives in data/launches/siteboost/state.json — single source of truth.
Module is idempotent; safe to call from multiple places.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "launches" / "siteboost" / "state.json"


def _load() -> dict:
    if not STATE_FILE.exists():
        return {
            "_meta": {"created_at": time.strftime("%Y-%m-%d"),
                      "schema_version": 1},
            "seen_place_ids": [],         # list[str] — Google place_ids scanned
            "sent_emails": [],            # list[str] — lowercased emails ever sent
            "scanned_locations": {},      # {"<zip>:<cat>": iso_date}
            "blocklist_emails": [],       # user-managed: never send
            "blocklist_domains": [],      # e.g. ["walmart.com"]
        }
    return json.loads(STATE_FILE.read_text())


def _save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["_meta"]["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Public API ──────────────────────────────────────────────────────────────

def filter_unseen_places(place_ids: list[str]) -> list[str]:
    """Return only place_ids we've never scanned."""
    state = _load()
    seen = set(state["seen_place_ids"])
    return [pid for pid in place_ids if pid not in seen]


def mark_places_seen(place_ids: list[str]) -> int:
    """Add place_ids to the seen set. Returns count of new additions."""
    state = _load()
    seen = set(state["seen_place_ids"])
    new = [pid for pid in place_ids if pid not in seen]
    seen.update(new)
    state["seen_place_ids"] = sorted(seen)
    _save(state)
    return len(new)


def filter_unsent_emails(emails: list[str]) -> list[str]:
    """Return only emails we've never sent + not in blocklists."""
    state = _load()
    sent = set(e.lower() for e in state["sent_emails"])
    block_e = set(e.lower() for e in state["blocklist_emails"])
    block_d = set(d.lower() for d in state["blocklist_domains"])

    out = []
    for e in emails:
        el = e.lower().strip()
        if el in sent:
            continue
        if el in block_e:
            continue
        domain = el.split("@", 1)[-1] if "@" in el else ""
        if domain in block_d:
            continue
        out.append(e)
    return out


def mark_emails_sent(emails: list[str]) -> int:
    """Record that these emails were sent. Returns count of new entries."""
    state = _load()
    sent = set(e.lower() for e in state["sent_emails"])
    new = [e for e in emails if e.lower() not in sent]
    sent.update(e.lower() for e in new)
    state["sent_emails"] = sorted(sent)
    _save(state)
    return len(new)


def record_scan(location: str, category: str) -> None:
    """Note that we scanned this location/category combo. Used to rotate."""
    state = _load()
    key = f"{location.lower()}:{category}"
    state["scanned_locations"][key] = time.strftime("%Y-%m-%d")
    _save(state)


def least_recently_scanned(locations: list[str], categories: list[str], n: int = 5) -> list[tuple[str, str]]:
    """Return n (location, category) pairs that are oldest or never scanned.
    Useful for NAI's weekly cron — picks the next ZIP+category combo automatically.
    """
    state = _load()
    scanned = state["scanned_locations"]
    pairs = [(loc, cat) for loc in locations for cat in categories]
    pairs.sort(key=lambda p: scanned.get(f"{p[0].lower()}:{p[1]}", "0000-00-00"))
    return pairs[:n]


def block_email(email: str) -> None:
    """Permanent block — never send to this email again."""
    state = _load()
    el = email.lower().strip()
    if el not in state["blocklist_emails"]:
        state["blocklist_emails"].append(el)
        _save(state)


def block_domain(domain: str) -> None:
    """Permanent block — never send to any address on this domain."""
    state = _load()
    dl = domain.lower().strip()
    if dl not in state["blocklist_domains"]:
        state["blocklist_domains"].append(dl)
        _save(state)


def stats() -> dict:
    """Snapshot for the morning report."""
    state = _load()
    return {
        "places_scanned": len(state["seen_place_ids"]),
        "emails_sent": len(state["sent_emails"]),
        "locations_scanned": len(state["scanned_locations"]),
        "blocked_emails": len(state["blocklist_emails"]),
        "blocked_domains": len(state["blocklist_domains"]),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stats", action="store_true")
    p.add_argument("--block-email")
    p.add_argument("--block-domain")
    p.add_argument("--next-targets", nargs=2, metavar=("LOCATIONS_CSV", "CATEGORIES_CSV"),
                   help="Show next 5 location/category pairs to scan (oldest first)")
    args = p.parse_args()

    if args.stats:
        print(json.dumps(stats(), indent=2))
    if args.block_email:
        block_email(args.block_email)
        print(f"Blocked email: {args.block_email}")
    if args.block_domain:
        block_domain(args.block_domain)
        print(f"Blocked domain: {args.block_domain}")
    if args.next_targets:
        locs = args.next_targets[0].split(",")
        cats = args.next_targets[1].split(",")
        for loc, cat in least_recently_scanned(locs, cats, n=5):
            print(f"  {loc} :: {cat}")
