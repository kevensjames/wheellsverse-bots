"""
core/bot_registry.py
Central Bot Registry — maps task names to executable bot instances.

Every bot NarAI Core can run is registered here.
Uses safe_import() — a failed import logs a warning and returns None.
The registry filters out None entries so NarAI never crashes on a bad import.

To add a new task:
  1. Add an entry to _REGISTRY_CONFIG below
  2. Map: "task_name" → ("module.path", "ClassName")
"""
from __future__ import annotations

import importlib
import logging
from typing import Dict, Optional, Any

log = logging.getLogger("BotRegistry")


# ══════════════════════════════════════════════════════════════════════════════
# TASK → BOT MAPPING
# All paths are relative to the project root (wheellsverse_bots/).
# Class names must match exactly what's in the bot file.
# ══════════════════════════════════════════════════════════════════════════════

_REGISTRY_CONFIG: Dict[str, tuple] = {
    # ── Market Intelligence ────────────────────────────────────────────────
    "trend_scan":          ("bots.marketing.13_trend_analyzer.bot",       "TrendAnalyzerBot"),
    "research":            ("bots.problem_solving.58_research_bot.bot",   "ResearchBot"),

    # ── Content Creation ───────────────────────────────────────────────────
    "generate_content":    ("bots.marketing.01_content_generator.bot",    "ContentGeneratorBot"),
    "write_blog":          ("bots.writing.46_blog_writer.bot",             "BlogWriterBot"),
    "hashtags":            ("bots.marketing.14_hashtag_generator.bot",     "HashtagGeneratorBot"),

    # ── SEO & Optimization ─────────────────────────────────────────────────
    "seo_optimize":        ("bots.marketing.02_seo_optimizer.bot",         "SEOOptimizerBot"),

    # ── Email & Sales ─────────────────────────────────────────────────────
    "email_campaign":      ("bots.marketing.03_email_campaign.bot",        "EmailCampaignBot"),
    "cold_email":          ("bots.sales.32_cold_email.bot",                "ColdEmailBot"),

    # ── Product & eCommerce ────────────────────────────────────────────────
    "create_product":      ("bots.ecommerce.61_product_description.bot",   "ProductDescriptionBot"),

    # ── Analytics ─────────────────────────────────────────────────────────
    "analyze_performance": ("bots.marketing.10_analytics_reporter.bot",    "AnalyticsReporterBot"),
}


# ══════════════════════════════════════════════════════════════════════════════
# SAFE IMPORT HELPER
# ══════════════════════════════════════════════════════════════════════════════

class _BotWrapper:
    """
    Wraps a bot instance to expose a uniform execute() interface.
    BaseBot bots use run() not execute() — this adapter bridges that.
    """
    def __init__(self, instance: Any, task: str) -> None:
        self._bot  = instance
        self._task = task

    def execute(self) -> Any:
        # BaseBot uses run() — call it with no args for autonomous execution
        if hasattr(self._bot, "run"):
            return self._bot.run()
        if hasattr(self._bot, "execute"):
            return self._bot.execute()
        raise NotImplementedError(f"Bot for '{self._task}' has neither run() nor execute()")


def _safe_import(module_path: str, class_name: str, task: str) -> Optional[_BotWrapper]:
    """
    Safely import and instantiate a bot class.
    Returns None on any failure — never raises.
    """
    try:
        module   = importlib.import_module(module_path)
        cls      = getattr(module, class_name)
        instance = cls()
        log.debug(f"  ✅ {task} → {class_name}")
        return _BotWrapper(instance, task)
    except ImportError as e:
        log.warning(f"  ⚠️  {task}: import failed ({module_path}) — {e}")
        return None
    except Exception as e:
        log.warning(f"  ⚠️  {task}: init failed ({class_name}) — {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# BUILD REGISTRY AT IMPORT TIME
# ══════════════════════════════════════════════════════════════════════════════

log.info("Building bot registry…")

_raw: Dict[str, Optional[_BotWrapper]] = {
    task: _safe_import(mod, cls, task)
    for task, (mod, cls) in _REGISTRY_CONFIG.items()
}

# Registered = only tasks where import succeeded
BOT_REGISTRY: Dict[str, _BotWrapper] = {
    task: bot for task, bot in _raw.items() if bot is not None
}

_failed = [task for task, bot in _raw.items() if bot is None]

log.info(
    f"Bot registry ready: {len(BOT_REGISTRY)} active, "
    f"{len(_failed)} failed{(' — ' + str(_failed)) if _failed else ''}"
)
