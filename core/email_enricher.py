"""Email enrichment — finds a contact email for businesses that have no website.

Stage 2 of the SiteBoost pipeline. Strategy:
    1) If business has a phone number, try Hunter.io's email-finder by company name
    2) If Hunter returns nothing, mark as "phone-only" — user can later run a Twilio SMS
       campaign or skip
    3) Optional fallback: Apollo.io (deferred — Hunter coverage is usually enough)

Hit rate expectation: ~40-60% of businesses without websites yield an email.
That's normal — the rest get phone-only outreach via a different channel.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("email_enricher")


def _hunter_key() -> str:
    k = os.getenv("HUNTER_API_KEY", "").strip()
    if not k:
        raise RuntimeError("HUNTER_API_KEY not set. Either set it in .env, or run with --dry-run.")
    return k


def _hunter_company_search(company_name: str, key: str) -> Optional[dict]:
    """Best-effort company → email via Hunter's email-finder + company-search."""
    # Step 1: company name → domain (Hunter company endpoint)
    cs = requests.get(
        "https://api.hunter.io/v2/email-finder",
        params={"company": company_name, "api_key": key, "type": "personal"},
        timeout=15,
    )
    if cs.status_code != 200:
        logger.debug(f"Hunter {cs.status_code} for {company_name!r}: {cs.text[:200]}")
        return None
    data = cs.json().get("data", {})
    if not data.get("email"):
        return None
    return {
        "email": data["email"],
        "first_name": data.get("first_name", ""),
        "last_name": data.get("last_name", ""),
        "position": data.get("position", ""),
        "confidence": data.get("score", 0),
        "source": "hunter",
    }


def _dry_run_enrich(prospect: dict) -> Optional[dict]:
    """Realistic fake enrichment. ~50% hit rate to mirror real Hunter coverage."""
    # Hash-based determinism: same prospect → same enrichment result
    h = sum(ord(c) for c in prospect.get("name", ""))
    if h % 10 < 5:  # 50% hit rate
        first = prospect["name"].split()[0].rstrip("'s")
        return {
            "email": f"{first.lower()}@{prospect['name'].lower().replace(' ', '').replace(chr(39), '')[:20]}.com",
            "first_name": first,
            "last_name": "Owner",
            "position": "Owner",
            "confidence": 72,
            "source": "dry-run",
        }
    return None


def enrich_scan(scan_path: Path, dry_run: bool = True) -> Path:
    """Read a scan JSON, enrich each targetable prospect, write enriched JSON."""
    scan = json.loads(scan_path.read_text())
    targetable = scan["targetable"]

    if not dry_run:
        key = _hunter_key()

    enriched = []
    phone_only = []
    for p in targetable:
        if dry_run:
            hit = _dry_run_enrich(p)
        else:
            hit = _hunter_company_search(p["name"], key)
            time.sleep(0.1)  # 10 req/sec ceiling

        if hit:
            p_with_email = {**p, **{"contact": hit}}
            enriched.append(p_with_email)
        else:
            phone_only.append(p)

    out = scan_path.with_name(scan_path.stem + "-enriched.json")
    out.write_text(json.dumps({
        "_meta": {
            **scan["_meta"],
            "enriched_at": time.strftime("%Y-%m-%d"),
            "n_enriched": len(enriched),
            "n_phone_only": len(phone_only),
            "hit_rate": f"{len(enriched) / max(len(targetable), 1):.0%}",
            "dry_run": dry_run,
        },
        "enriched": enriched,
        "phone_only": phone_only,
    }, indent=2))
    logger.info(f"[enrich] wrote {out}: {len(enriched)}/{len(targetable)} with email")
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--scan", required=True)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    out = enrich_scan(Path(args.scan), dry_run=not args.live)
    print(f"OK · enriched output: {out}")
