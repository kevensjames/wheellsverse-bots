# core/portfolio/seed.py
"""Seed supervisor loop.json files for the portfolio.

The W-MOS playbook is identical across businesses except the one business-specific
"build pack" step (registry.Business.build_step). seed_all_loops() writes a loop.json
for each of the ten so the supervisor can operate the whole portfolio, not just n8n."""
from __future__ import annotations

from pathlib import Path

from core.portfolio import paths
from core.portfolio.registry import get_business, list_businesses


def _loop_for(build_step: str) -> list[dict]:
    """The standard 9-step acquisition pipeline; `build_step` is the per-business pack."""
    return [
        {"verb": "research_niche", "agent": "kai.research", "class": "green"},
        {"verb": build_step, "agent": "kai.planning", "class": "green"},
        {"verb": "generate_lead_list", "agent": "places_scanner", "class": "green"},
        {"verb": "enrich_leads", "agent": "email_enricher", "class": "green"},
        {"verb": "draft_outreach", "agent": "cold_outreach", "class": "green"},
        {"verb": "run_outreach_campaign", "agent": "cold_outreach", "class": "auto_capped",
         "preconditions": ["warmup_complete", "campaign_approved_once", "under_daily_cap"]},
        {"verb": "publish_landing_page", "agent": "site_builder", "class": "auto_capped",
         "preconditions": ["page_approved_once", "unpublish_handle"]},
        {"verb": "deploy_demo_instance", "agent": "infra", "class": "auto_capped",
         "preconditions": ["first_of_kind_approved", "under_cost_ceiling", "teardown_handle"]},
        {"verb": "draft_proposal", "agent": "kai.research", "class": "green"},
    ]


def seed_business_loop(slug: str) -> Path:
    b = get_business(slug)
    build_step = b.build_step if (b and b.build_step) else "build_pack"
    target = paths.business_dir(slug) / "loop.json"
    paths.save_json_atomic(target, {"business": slug, "build_step": build_step,
                                    "steps": _loop_for(build_step)})
    return target


def seed_all_loops() -> list[Path]:
    """Seed an operating loop for every business in the registry."""
    return [seed_business_loop(b.slug) for b in list_businesses()]


def seed_n8n_loop() -> Path:
    """Back-compat: the original n8n-only pilot seed."""
    return seed_business_loop("n8n")
