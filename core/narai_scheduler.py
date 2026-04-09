#!/usr/bin/env python3
"""
core/narai_scheduler.py
─────────────────────────────────────────────────────────────────────────────
NarAI Schedule Registry

Central registry for all NarAI scheduled tasks. Provides:
  - Persistent schedule state (enabled/disabled, last run, next run)
  - API-accessible schedule list for the dashboard
  - Individual schedule enable/disable and manual trigger
  - Used by the dashboard "Schedules" module

State file: data/narai_schedules.json
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR       = ROOT / "data"
SCHEDULES_FILE = DATA_DIR / "narai_schedules.json"

log = logging.getLogger("narai_scheduler")

# ── Master schedule catalog ───────────────────────────────────────────────────
# These are the canonical schedules NarAI runs. Each has a unique id.
# `trigger_fn` is the dotted import path + function name to call.
DEFAULT_SCHEDULES: List[Dict] = [
    {
        "id":          "market_intel",
        "name":        "Market Intelligence Scan",
        "description": "Full scan of 12 platforms (Gumroad, Etsy, TikTok, Reddit…) to gather product + content trends",
        "frequency":   "weekly",
        "day":         "monday",
        "time":        "01:00",
        "category":    "intelligence",
        "icon":        "🔭",
        "enabled":     True,
        "trigger_fn":  "core.market_intelligence.start_scan_background",
    },
    {
        "id":          "narai_autopilot",
        "name":        "NarAI Daily Creation Session",
        "description": "Full autonomous session: social posts + 2 products per platform (Gumroad, Etsy, Payhip, Shopify, KDP) + social promotion",
        "frequency":   "daily",
        "time":        "01:30",
        "category":    "products",
        "icon":        "🤖",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot.start_autopilot_background",
    },
    {
        "id":          "shopify_autopilot",
        "name":        "Shopify Autopilot Session",
        "description": "Viral trend scan → digital products → POD (Printful) → service packages → 5-step funnel → performance review",
        "frequency":   "daily",
        "time":        "02:30",
        "category":    "products",
        "icon":        "🛍️",
        "enabled":     True,
        "trigger_fn":  "core.narai_shopify_autopilot.start_shopify_autopilot_background",
    },
    {
        "id":          "social_blast_morning",
        "name":        "Morning Social Blast",
        "description": "NarAI posts to Facebook, Instagram, Twitter — passive income + AI tools content",
        "frequency":   "daily",
        "time":        "09:15",
        "category":    "social",
        "icon":        "📱",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot._narai_social_blast",
    },
    {
        "id":          "reel_morning",
        "name":        "Morning Reel — Power of AI",
        "description": "Inspiring/cinematic AI Reel posted to Instagram + Facebook",
        "frequency":   "daily",
        "time":        "10:00",
        "category":    "video",
        "icon":        "🎬",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot.start_reels_background:morning",
    },
    {
        "id":          "reel_afternoon",
        "name":        "Afternoon Reel — AI Tries to Be Human",
        "description": "Comedy/cartoon Reel posted to Instagram + Facebook",
        "frequency":   "daily",
        "time":        "15:00",
        "category":    "video",
        "icon":        "😂",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot.start_reels_background:afternoon",
    },
    {
        "id":          "reel_evening",
        "name":        "Evening Reel — AI in Real Life Viral",
        "description": "Punchy viral Reel posted to Instagram + Facebook",
        "frequency":   "daily",
        "time":        "20:00",
        "category":    "video",
        "icon":        "🔥",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot.start_reels_background:evening",
    },
    {
        "id":          "revenue_pipeline",
        "name":        "Revenue Pipeline",
        "description": "Full revenue bot run: affiliate, ads, product links, conversion optimization",
        "frequency":   "daily",
        "time":        "08:30",
        "category":    "revenue",
        "icon":        "💰",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:full_revenue_blast",
    },
    {
        "id":          "seo_pipeline",
        "name":        "SEO Daily Pipeline",
        "description": "SEO content creation, keyword optimization, blog publishing",
        "frequency":   "daily",
        "time":        "06:30",
        "category":    "seo",
        "icon":        "📈",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:seo_daily",
    },
    {
        "id":          "social_domination_am",
        "name":        "Social Domination — Morning",
        "description": "High-engagement social posts batch — all platforms",
        "frequency":   "daily",
        "time":        "09:00",
        "category":    "social",
        "icon":        "⚡",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:social_domination",
    },
    {
        "id":          "social_domination_pm",
        "name":        "Social Domination — Afternoon",
        "description": "High-engagement social posts batch — all platforms",
        "frequency":   "daily",
        "time":        "14:00",
        "category":    "social",
        "icon":        "⚡",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:social_domination",
    },
    {
        "id":          "social_domination_eve",
        "name":        "Social Domination — Evening",
        "description": "High-engagement social posts batch — all platforms",
        "frequency":   "daily",
        "time":        "19:00",
        "category":    "social",
        "icon":        "⚡",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:social_domination",
    },
    {
        "id":          "affiliate_am",
        "name":        "Affiliate Revenue — Morning",
        "description": "Affiliate link posts, comparison content, signup promotions",
        "frequency":   "daily",
        "time":        "10:00",
        "category":    "revenue",
        "icon":        "🔗",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:affiliate_revenue",
    },
    {
        "id":          "affiliate_pm",
        "name":        "Affiliate Revenue — Afternoon",
        "description": "Affiliate link posts, comparison content, signup promotions",
        "frequency":   "daily",
        "time":        "15:00",
        "category":    "revenue",
        "icon":        "🔗",
        "enabled":     True,
        "trigger_fn":  "core.pipeline_engine.run_pipeline:affiliate_revenue",
    },
    {
        "id":          "telegram_summary",
        "name":        "Telegram Daily Summary",
        "description": "Daily performance report sent to Telegram channel",
        "frequency":   "daily",
        "time":        "07:00",
        "category":    "reporting",
        "icon":        "📊",
        "enabled":     True,
        "trigger_fn":  "core.api.telegram_daily_alert",
    },
    {
        "id":          "inbox_handler",
        "name":        "Inbox Handler",
        "description": "NarAI replies to comments, DMs, and messages across all platforms",
        "frequency":   "every_30min",
        "time":        "*/30",
        "category":    "social",
        "icon":        "💬",
        "enabled":     True,
        "trigger_fn":  "core.narai_autopilot._narai_inbox_handler",
    },
    {
        "id":          "video_creator",
        "name":        "Video Creator",
        "description": "AI video creation session: scripts, Runway ML generation, posting",
        "frequency":   "daily",
        "time":        "11:00",
        "category":    "video",
        "icon":        "🎥",
        "enabled":     True,
        "trigger_fn":  "core.video_engine.run_video_session",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> Dict[str, Dict]:
    """Load schedule state from file. Returns {id: schedule_dict}."""
    try:
        if SCHEDULES_FILE.exists():
            data = json.loads(SCHEDULES_FILE.read_text())
            return {s["id"]: s for s in data if "id" in s}
    except Exception:
        pass
    return {}


def _save(schedules: Dict[str, Dict]):
    try:
        DATA_DIR.mkdir(exist_ok=True)
        SCHEDULES_FILE.write_text(json.dumps(list(schedules.values()), indent=2, default=str))
    except Exception as e:
        log.error(f"[Scheduler] Save failed: {e}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_run(schedule: Dict) -> str:
    """Calculate the next run time for a schedule."""
    freq = schedule.get("frequency", "daily")
    t    = schedule.get("time", "00:00")

    now = datetime.now(timezone.utc)
    try:
        if freq == "every_30min":
            # Next 30-min boundary
            minutes = now.minute
            next_min = 30 - (minutes % 30) if minutes % 30 != 0 else 30
            return (now + timedelta(minutes=next_min)).replace(second=0, microsecond=0).isoformat()

        hour, minute = (int(x) for x in t.split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if freq == "weekly":
            day_name = schedule.get("day", "monday").lower()
            days_map  = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                         "friday": 4, "saturday": 5, "sunday": 6}
            target_dow = days_map.get(day_name, 0)
            days_ahead = (target_dow - now.weekday()) % 7
            if days_ahead == 0 and now >= candidate:
                days_ahead = 7
            return (candidate + timedelta(days=days_ahead)).isoformat()

        # daily
        if now >= candidate:
            candidate = candidate + timedelta(days=1)
        return candidate.isoformat()

    except Exception:
        return (now + timedelta(hours=1)).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_schedules() -> List[Dict]:
    """
    Return all schedules merged with persisted state.
    Always returns the full canonical list with runtime state overlaid.
    """
    persisted = _load()
    result    = []

    for sched in DEFAULT_SCHEDULES:
        sid   = sched["id"]
        saved = persisted.get(sid, {})

        merged = dict(sched)
        # Overlay persisted state
        merged["enabled"]   = saved.get("enabled",  sched["enabled"])
        merged["last_run"]  = saved.get("last_run",  None)
        merged["last_status"] = saved.get("last_status", "never")
        merged["run_count"] = saved.get("run_count", 0)
        merged["next_run"]  = _next_run(merged) if merged["enabled"] else None

        result.append(merged)

    return result


def get_schedule(schedule_id: str) -> Optional[Dict]:
    """Return a single schedule by id."""
    schedules = {s["id"]: s for s in get_schedules()}
    return schedules.get(schedule_id)


def update_schedule(schedule_id: str, enabled: Optional[bool] = None, time: Optional[str] = None) -> Dict:
    """
    Update a schedule's enabled state or run time.

    Args:
        schedule_id: the schedule id
        enabled: True/False to enable/disable
        time: new run time in HH:MM format

    Returns:
        Updated schedule dict
    """
    persisted = _load()

    if schedule_id not in persisted:
        # Initialize from defaults
        defaults  = {s["id"]: s for s in DEFAULT_SCHEDULES}
        base      = defaults.get(schedule_id, {})
        persisted[schedule_id] = {
            "id":          schedule_id,
            "enabled":     base.get("enabled", True),
            "last_run":    None,
            "last_status": "never",
            "run_count":   0,
        }

    if enabled is not None:
        persisted[schedule_id]["enabled"] = enabled
    if time is not None:
        persisted[schedule_id]["time"] = time

    _save(persisted)
    return get_schedule(schedule_id) or {}


def mark_ran(schedule_id: str, status: str = "success"):
    """Record that a schedule just ran."""
    persisted = _load()
    if schedule_id not in persisted:
        persisted[schedule_id] = {"id": schedule_id, "enabled": True}

    persisted[schedule_id]["last_run"]    = _now_iso()
    persisted[schedule_id]["last_status"] = status
    persisted[schedule_id]["run_count"]   = persisted[schedule_id].get("run_count", 0) + 1
    _save(persisted)


def trigger_schedule(schedule_id: str) -> Dict:
    """
    Manually trigger a schedule immediately in a background thread.

    Returns:
        {success, message, schedule_id}
    """
    schedule = get_schedule(schedule_id)
    if not schedule:
        return {"success": False, "message": f"Unknown schedule: {schedule_id}"}

    trigger_fn = schedule.get("trigger_fn", "")
    if not trigger_fn:
        return {"success": False, "message": "No trigger_fn defined"}

    def _run():
        try:
            mark_ran(schedule_id, "running")
            _dispatch_trigger(trigger_fn, schedule_id)
            mark_ran(schedule_id, "success")
            log.info(f"[Scheduler] Manual trigger complete: {schedule_id}")
        except Exception as e:
            mark_ran(schedule_id, f"error: {str(e)[:80]}")
            log.error(f"[Scheduler] Manual trigger failed {schedule_id}: {e}")

    t = threading.Thread(target=_run, daemon=True, name=f"schedule-trigger-{schedule_id}")
    t.start()

    return {
        "success":     True,
        "message":     f"Schedule '{schedule['name']}' triggered",
        "schedule_id": schedule_id,
    }


def _dispatch_trigger(trigger_fn: str, schedule_id: str):
    """
    Dispatch a trigger_fn string.
    Format: "module.path.function" or "module.path.function:arg"
    """
    arg = None
    if ":" in trigger_fn:
        trigger_fn, arg = trigger_fn.rsplit(":", 1)

    parts   = trigger_fn.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid trigger_fn: {trigger_fn}")

    module_path, fn_name = parts

    import importlib
    mod = importlib.import_module(module_path)
    fn  = getattr(mod, fn_name)

    if arg is not None:
        fn(arg)
    else:
        fn()


def get_schedule_stats() -> Dict:
    """Return summary stats for the dashboard."""
    schedules = get_schedules()
    enabled   = [s for s in schedules if s.get("enabled")]
    ran_today = [
        s for s in schedules
        if s.get("last_run") and s["last_run"][:10] == datetime.now().strftime("%Y-%m-%d")
    ]
    return {
        "total":      len(schedules),
        "enabled":    len(enabled),
        "disabled":   len(schedules) - len(enabled),
        "ran_today":  len(ran_today),
        "categories": list({s["category"] for s in schedules}),
    }
