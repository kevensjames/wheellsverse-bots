#!/usr/bin/env python3
"""
scripts/meta_first_ad_sdk.py
─────────────────────────────────────────────────────────────────────────────
Same 5-step PAUSED $5/day campaign as scripts/meta_first_ad.py, but built on
the official `facebook_business` Python SDK. The SDK is initialised with the
registered FB app context (META_APP_ID), which lets ad creatives publish
through Meta's normal app-on-Page channel — the path our hand-rolled HTTP
client got blocked on with "app in development" errors.

Steps:
  1. Upload creative image  → AdImage
  2. Create Campaign        (PAUSED, OUTCOME_TRAFFIC)
  3. Create Ad Set          (PAUSED, $5/day, LINK_CLICKS, US 25-55)
  4. Create Ad Creative     (link_data with Page + image_hash)
  5. Create Ad              (PAUSED)
  6. GET each node → verify status=PAUSED

Outputs: prints all IDs at the end. Does NOT activate — flip to ACTIVE
manually in Ads Manager after reviewing.

Env vars consumed (.env):
  META_ACCESS_TOKEN   — User Token w/ ads_management + ads_read
  META_APP_ID         — registered Facebook app id
  AD_ACCOUNT_ID       — numeric, no act_ prefix
  PAGE_ID             — numeric FB Page id
  META_GRAPH_VERSION  — e.g. v19.0 (optional)
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from facebook_business.api import FacebookAdsApi  # noqa: E402
from facebook_business.adobjects.adaccount import AdAccount  # noqa: E402
from facebook_business.adobjects.campaign import Campaign  # noqa: E402
from facebook_business.adobjects.adset import AdSet  # noqa: E402
from facebook_business.adobjects.adimage import AdImage  # noqa: E402
from facebook_business.adobjects.adcreative import AdCreative  # noqa: E402
from facebook_business.adobjects.ad import Ad  # noqa: E402
from facebook_business.exceptions import FacebookRequestError  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("meta_first_ad_sdk")

DEFAULT_UTM = {"utm_source": "meta", "utm_medium": "cpc"}


def add_utm(url: str, campaign_name: str) -> str:
    parts = urlparse(url)
    existing = dict(parse_qsl(parts.query, keep_blank_values=True))
    utm = dict(DEFAULT_UTM)
    utm["utm_campaign"] = campaign_name
    merged = {**utm, **existing}
    return urlunparse(parts._replace(query=urlencode(merged)))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create one PAUSED $5/day Meta ad via the official SDK.")
    p.add_argument("--image", default=str(ROOT / "assets" / "meta_ad_creative_v1.png"))
    p.add_argument("--dest-url", required=True)
    p.add_argument("--copy", required=True)
    p.add_argument("--campaign-name", default="toodle_test_01")
    p.add_argument("--daily-budget-cents", type=int, default=500)
    p.add_argument("--country", default="US")
    p.add_argument("--age-min", type=int, default=25)
    p.add_argument("--age-max", type=int, default=55)
    p.add_argument("--cta", default="LEARN_MORE")
    p.add_argument("--objective", default="OUTCOME_TRAFFIC")
    return p.parse_args()


def _require_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        log.error("required env var %s is not set", name)
        sys.exit(2)
    return val


def main() -> int:
    args = parse_args()

    token = _require_env("META_ACCESS_TOKEN")
    app_id = _require_env("META_APP_ID")
    ad_account_id_raw = _require_env("AD_ACCOUNT_ID").replace("act_", "")
    page_id = _require_env("PAGE_ID")
    version = os.getenv("META_GRAPH_VERSION", "v19.0")

    image_path = Path(args.image)
    if not image_path.exists():
        log.error("creative image not found: %s", image_path)
        return 2

    dest_with_utm = add_utm(args.dest_url, args.campaign_name)
    log.info("destination URL with UTMs: %s", dest_with_utm)

    FacebookAdsApi.init(
        access_token=token,
        app_id=app_id,
        api_version=version,
    )

    account = AdAccount(f"act_{ad_account_id_raw}")

    try:
        # ── Step 1: image ───────────────────────────────────────────────────
        log.info("Step 1/5 — uploading creative image…")
        image = account.create_ad_image(params={
            AdImage.Field.filename: str(image_path),
        })
        image_hash = image[AdImage.Field.hash]
        log.info("  image_hash=%s", image_hash)

        # ── Step 2: campaign (PAUSED) ───────────────────────────────────────
        log.info("Step 2/5 — creating campaign (PAUSED)…")
        campaign = account.create_campaign(params={
            Campaign.Field.name: args.campaign_name,
            Campaign.Field.objective: args.objective,
            Campaign.Field.status: Campaign.Status.paused,
            Campaign.Field.special_ad_categories: [],
            # Adset-level budget (not campaign budget) → Meta requires explicit
            # opt-in/out on the sharing-pool optimisation. False keeps budgets isolated.
            "is_adset_budget_sharing_enabled": False,
        })
        campaign_id = campaign.get_id()
        log.info("  campaign_id=%s", campaign_id)

        # ── Step 3: ad set (PAUSED) ─────────────────────────────────────────
        log.info("Step 3/5 — creating ad set (PAUSED)…")
        start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        targeting = {
            "geo_locations": {"countries": [args.country]},
            "age_min": args.age_min,
            "age_max": args.age_max,
            "targeting_automation": {"advantage_audience": 0},
        }
        adset = account.create_ad_set(params={
            AdSet.Field.name: f"{args.campaign_name}__adset",
            AdSet.Field.campaign_id: campaign_id,
            AdSet.Field.daily_budget: args.daily_budget_cents,
            AdSet.Field.billing_event: AdSet.BillingEvent.impressions,
            AdSet.Field.optimization_goal: AdSet.OptimizationGoal.link_clicks,
            AdSet.Field.bid_strategy: AdSet.BidStrategy.lowest_cost_without_cap,
            AdSet.Field.targeting: targeting,
            AdSet.Field.status: AdSet.Status.paused,
            AdSet.Field.start_time: start_time,
        })
        adset_id = adset.get_id()
        log.info("  adset_id=%s", adset_id)

        # ── Step 4: ad creative ─────────────────────────────────────────────
        log.info("Step 4/5 — creating ad creative…")
        link_data = {
            "message": args.copy,
            "link": dest_with_utm,
            "image_hash": image_hash,
            "call_to_action": {
                "type": args.cta,
                "value": {"link": dest_with_utm},
            },
        }
        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }
        creative = account.create_ad_creative(params={
            AdCreative.Field.name: f"{args.campaign_name}__creative",
            AdCreative.Field.object_story_spec: object_story_spec,
        })
        creative_id = creative.get_id()
        log.info("  creative_id=%s", creative_id)

        # ── Step 5: ad (PAUSED) ─────────────────────────────────────────────
        log.info("Step 5/5 — creating ad (PAUSED)…")
        ad = account.create_ad(params={
            Ad.Field.name: f"{args.campaign_name}__ad",
            Ad.Field.adset_id: adset_id,
            Ad.Field.creative: {"creative_id": creative_id},
            Ad.Field.status: Ad.Status.paused,
        })
        ad_id = ad.get_id()
        log.info("  ad_id=%s", ad_id)

    except FacebookRequestError as e:
        log.error("Graph API error: %s", e.api_error_message() or str(e))
        try:
            log.error("  subcode: %s  user_title: %s  user_msg: %s",
                      e.api_error_subcode(),
                      e.body().get("error", {}).get("error_user_title"),
                      e.body().get("error", {}).get("error_user_msg"))
        except Exception:
            pass
        return 1

    # ── Step 6: verify status=PAUSED on every node ──────────────────────────
    log.info("Verifying every node is PAUSED…")
    failures: list[tuple[str, str, str]] = []
    for label, oid, klass in (
        ("campaign", campaign_id, Campaign),
        ("adset",    adset_id,    AdSet),
        ("ad",       ad_id,       Ad),
    ):
        node = klass(oid).api_get(fields=["id", "name", "status", "effective_status"])
        status = node.get("status")
        eff = node.get("effective_status")
        log.info("  %-9s %s  status=%s  effective_status=%s",
                 label, oid, status, eff)
        if status not in {"PAUSED", "ARCHIVED"}:
            failures.append((label, oid, str(status)))

    print()
    print("=" * 60)
    print("  TOODLE — Meta first ad created via official SDK (PAUSED)")
    print("=" * 60)
    print(f"  campaign_id : {campaign_id}")
    print(f"  adset_id    : {adset_id}")
    print(f"  creative_id : {creative_id}")
    print(f"  ad_id       : {ad_id}")
    print(f"  image_hash  : {image_hash}")
    print(f"  dest_url    : {dest_with_utm}")
    print()
    if failures:
        print("  ⚠  one or more nodes NOT paused:")
        for label, oid, status in failures:
            print(f"     {label} {oid} status={status}")
        return 1
    print("  ✅ all three nodes verified PAUSED.")
    print()
    print("  Next: open Meta Ads Manager → review → flip to ACTIVE manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
