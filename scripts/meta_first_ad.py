#!/usr/bin/env python3
"""
scripts/meta_first_ad.py
─────────────────────────────────────────────────────────────────────────────
The Toodle "Ads Agent, manual rep zero" — creates one Meta ad campaign at
$5/day, status PAUSED, via the Marketing API. Verifies state, prints IDs,
and exits. Does NOT activate; the user reviews in Ads Manager and flips it
to ACTIVE manually.

Usage:
  python scripts/meta_first_ad.py \\
      --image ./creative.jpg \\
      --dest-url "https://wheellsverse-bots.pages.dev/landing" \\
      --copy "Stop trading time for money. Get the AI Entrepreneur Blueprint." \\
      --campaign-name "toodle_test_01"

Required (CLI or .env):
  --image / ./creative.jpg
  --dest-url
  --copy

Env (.env):
  META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID  (see .env.example)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

# Make repo root importable when running from scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.meta_ads import MetaAdsClient, MetaAdsError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("meta_first_ad")


DEFAULT_UTM = {
    "utm_source": "meta",
    "utm_medium": "cpc",
    "utm_campaign": "toodle_test_01",
}


def add_utm(url: str, campaign_name: str) -> str:
    """Add Toodle UTM params, preserving any existing query string."""
    parts = urlparse(url)
    existing = dict(parse_qsl(parts.query, keep_blank_values=True))
    utm = dict(DEFAULT_UTM)
    utm["utm_campaign"] = campaign_name
    merged = {**utm, **existing}  # caller-supplied params win
    return urlunparse(parts._replace(query=urlencode(merged)))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create one PAUSED $5/day Meta ad.")
    p.add_argument("--image", default=str(ROOT / "creative.jpg"),
                   help="Path to the ad creative (jpg/png). Default: ./creative.jpg")
    p.add_argument("--dest-url", required=True, help="Landing page URL (UTMs will be appended).")
    p.add_argument("--copy", required=True, help="Ad body copy (the 'message' field).")
    p.add_argument("--campaign-name", default="toodle_test_01")
    p.add_argument("--daily-budget-cents", type=int, default=500, help="Daily budget in cents. Default 500 = $5.00")
    p.add_argument("--country", default="US")
    p.add_argument("--age-min", type=int, default=25)
    p.add_argument("--age-max", type=int, default=55)
    p.add_argument("--cta", default="LEARN_MORE")
    p.add_argument("--objective", default="OUTCOME_TRAFFIC")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    client = MetaAdsClient()
    if not client.is_configured():
        log.error("META_ACCESS_TOKEN / AD_ACCOUNT_ID / PAGE_ID not all set in .env "
                  "(see .env.example). Aborting before any API call.")
        return 2

    image_path = Path(args.image)
    if not image_path.exists():
        log.error("Creative image not found: %s — pass --image or drop a "
                  "creative.jpg in the repo root.", image_path)
        return 2

    dest_with_utm = add_utm(args.dest_url, args.campaign_name)
    log.info("Destination URL with UTMs: %s", dest_with_utm)

    targeting = {
        "geo_locations": {"countries": [args.country]},
        "age_min": args.age_min,
        "age_max": args.age_max,
    }

    try:
        # ── Step 1 — upload image ────────────────────────────────────────────
        log.info("Step 1/5 — uploading creative image…")
        image_hash = client.upload_image(str(image_path))
        log.info("  image_hash=%s", image_hash)

        # ── Step 2 — campaign ────────────────────────────────────────────────
        log.info("Step 2/5 — creating campaign (PAUSED)…")
        campaign_id = client.create_campaign(
            name=args.campaign_name,
            objective=args.objective,
            special_ad_categories=[],
            status="PAUSED",
        )
        log.info("  campaign_id=%s", campaign_id)

        # ── Step 3 — adset ───────────────────────────────────────────────────
        log.info("Step 3/5 — creating ad set (PAUSED)…")
        start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        adset_id = client.create_adset(
            name=f"{args.campaign_name}__adset",
            campaign_id=campaign_id,
            daily_budget_cents=args.daily_budget_cents,
            billing_event="IMPRESSIONS",
            optimization_goal="LINK_CLICKS",
            bid_strategy="LOWEST_COST_WITHOUT_CAP",
            targeting=targeting,
            status="PAUSED",
            start_time=start_time,
        )
        log.info("  adset_id=%s", adset_id)

        # ── Step 4 — creative ────────────────────────────────────────────────
        log.info("Step 4/5 — creating ad creative…")
        creative_id = client.create_creative(
            name=f"{args.campaign_name}__creative",
            message=args.copy,
            link_url=dest_with_utm,
            image_hash=image_hash,
            call_to_action=args.cta,
        )
        log.info("  creative_id=%s", creative_id)

        # ── Step 5 — ad ──────────────────────────────────────────────────────
        log.info("Step 5/5 — creating ad (PAUSED)…")
        ad_id = client.create_ad(
            name=f"{args.campaign_name}__ad",
            adset_id=adset_id,
            creative_id=creative_id,
            status="PAUSED",
        )
        log.info("  ad_id=%s", ad_id)

    except MetaAdsError as e:
        log.error("Graph API error: %s", e)
        if e.payload:
            log.error("Full payload: %s", e.payload)
        return 1
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2

    # ── Verify status=PAUSED on every node ────────────────────────────────────
    log.info("Verifying every node is PAUSED…")
    failures = []
    for label, node_id in [("campaign", campaign_id), ("adset", adset_id), ("ad", ad_id)]:
        info = client.get_node(node_id)
        status = info.get("status") or info.get("effective_status")
        log.info("  %s %s status=%s effective_status=%s",
                 label, node_id, info.get("status"), info.get("effective_status"))
        if status not in {"PAUSED", "ARCHIVED"}:
            failures.append((label, node_id, status))

    print("\n" + "=" * 60)
    print("  TOODLE — Meta first ad created (PAUSED)")
    print("=" * 60)
    print(f"  campaign_id : {campaign_id}")
    print(f"  adset_id    : {adset_id}")
    print(f"  ad_id       : {ad_id}")
    print(f"  image_hash  : {image_hash}")
    print(f"  dest_url    : {dest_with_utm}")
    print()
    if failures:
        print("  ⚠  One or more nodes are NOT PAUSED:")
        for label, node_id, status in failures:
            print(f"     {label} {node_id} status={status}")
        print()
        print("  Review in Ads Manager before doing anything else.")
        return 1

    print("  ✅ All three nodes verified PAUSED.")
    print()
    print("  Next:")
    print("    1. Open Meta Ads Manager.")
    print(f"    2. Find campaign id {campaign_id}.")
    print("    3. Confirm targeting, copy, image, destination URL look right.")
    print("    4. Flip the ad to ACTIVE manually when you're ready.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
