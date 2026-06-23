# core/portfolio/seed.py
"""Seed supervisor loop.json files. n8n pilot loop per spec §4."""
from __future__ import annotations

from pathlib import Path

from core.portfolio import paths

_N8N_STEPS = [
    {"verb": "research_niche", "agent": "kai.research", "class": "green"},
    {"verb": "build_workflow_pack", "agent": "kai.planning", "class": "green"},
    {"verb": "generate_lead_list", "agent": "places_scanner", "class": "green"},
    {"verb": "draft_outreach", "agent": "cold_outreach", "class": "green"},
    {"verb": "run_outreach_campaign", "agent": "cold_outreach", "class": "auto_capped",
     "preconditions": ["warmup_complete", "campaign_approved_once", "under_daily_cap"]},
    {"verb": "publish_landing_page", "agent": "site_builder", "class": "auto_capped",
     "preconditions": ["page_approved_once", "unpublish_handle"]},
    {"verb": "deploy_demo_instance", "agent": "infra", "class": "auto_capped",
     "preconditions": ["first_of_kind_approved", "under_cost_ceiling", "teardown_handle"]},
    {"verb": "draft_proposal", "agent": "kai.research", "class": "green"},
]


def seed_n8n_loop() -> Path:
    target = paths.business_dir("n8n") / "loop.json"
    paths.save_json_atomic(target, {"business": "n8n", "steps": _N8N_STEPS})
    return target
