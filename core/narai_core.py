"""
core/narai_core.py
NarAI Core Engine — Autonomous Goal-Driven Execution System
Version: 1.0.0

Cycle: State → Goal → Plan → Execute → Evaluate → Learn → Repeat

This is the clean public interface to NarAI's autonomous capabilities.
It wraps the existing working engines (narai_autopilot, narai_shopify_autopilot,
narai_pod_engine) — it does NOT replace them.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("NarAI-Core")

# ── State file (lightweight — separate from the 5-tier memory system) ─────────
_STATE_FILE = Path("data/system_state.json")


def _load_system_state() -> Dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception as e:
        log.warning(f"State load failed: {e}")
    return {
        "revenue": 0.0,
        "audience": 0,
        "assets": 0,
        "last_goal": None,
        "consecutive_failures": 0,
        "total_cycles": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _save_system_state(state: Dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.error(f"State save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# NARAI CORE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class NarAICore:
    """
    NarAI Core Engine.
    Exposes run_cycle() — one full autonomous iteration.

    Goal selection → plan building → execution → evaluation → memory update.
    Each task is isolated: one task failure never kills the whole cycle.
    """

    GOALS = ["make_money", "grow_audience", "create_assets", "optimize_system"]

    PLANS: Dict[str, List[str]] = {
        "make_money": [
            "trend_scan",
            "create_product",
            "email_campaign",
            "analyze_performance",
        ],
        "grow_audience": [
            "trend_scan",
            "generate_content",
            "write_blog",
            "hashtags",
        ],
        "create_assets": [
            "trend_scan",
            "create_product",
            "generate_content",
            "write_blog",
        ],
        "optimize_system": [
            "analyze_performance",
            "research",
            "seo_optimize",
        ],
    }

    def __init__(self) -> None:
        # Import here to avoid circular imports at module load time
        from core.bot_registry import BOT_REGISTRY
        self._registry = BOT_REGISTRY
        log.info(
            f"NarAI Core initialized | "
            f"{len(self._registry)} bots registered: "
            f"{list(self._registry.keys())}"
        )

    # ── MAIN CYCLE ────────────────────────────────────────────────────────────
    def run_cycle(self, force_goal: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute one full autonomous cycle.
        Returns a complete cycle report dict.

        Args:
            force_goal: override goal selection (for testing / revenue loop)
        """
        cycle_start = datetime.now(timezone.utc)
        log.info("=" * 56)
        log.info("NarAI Core cycle starting…")

        state = _load_system_state()
        log.info(
            f"State loaded | revenue=${state.get('revenue', 0):.2f} "
            f"audience={state.get('audience', 0)} "
            f"assets={state.get('assets', 0)} "
            f"cycles={state.get('total_cycles', 0)}"
        )

        goal = force_goal or self.decide_goal(state)
        log.info(f"Goal: {goal}")

        plan = self.build_plan(goal)
        log.info(f"Plan: {' → '.join(plan) if plan else '(empty)'}")

        results = self.execute_plan(plan)

        metrics = self.evaluate(results)
        log.info(
            f"Metrics | success={metrics['success']} "
            f"failure={metrics['failure']} "
            f"rate={metrics['success_rate']}%"
        )

        self._update_state(state, goal, metrics)

        # Save to 5-tier memory system
        self._persist_to_memory(goal, results, metrics)

        duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        report = {
            "cycle_id": cycle_start.isoformat(),
            "goal": goal,
            "plan": plan,
            "results": results,
            "metrics": metrics,
            "duration_seconds": round(duration, 2),
            "status": "complete",
        }

        log.info(f"Cycle complete in {duration:.2f}s")
        log.info("=" * 56)
        return report

    # ── GOAL DECISION ─────────────────────────────────────────────────────────
    def decide_goal(self, state: Dict) -> str:
        """
        Select the most strategic goal based on current system state.
        Heuristic-based. Phase 2 can replace with LLM decision.
        """
        consecutive_failures = state.get("consecutive_failures", 0)
        revenue              = state.get("revenue", 0.0)
        audience             = state.get("audience", 0)
        assets               = state.get("assets", 0)

        if consecutive_failures >= 3:
            log.info(f"  → optimize_system (failures={consecutive_failures})")
            return "optimize_system"

        if revenue < 500:
            log.info(f"  → make_money (revenue=${revenue:.2f} < $500)")
            return "make_money"

        if audience < 1000:
            log.info(f"  → grow_audience (audience={audience} < 1000)")
            return "grow_audience"

        if assets < 10:
            log.info(f"  → create_assets (assets={assets} < 10)")
            return "create_assets"

        log.info("  → make_money (default)")
        return "make_money"

    # ── PLAN BUILDER ──────────────────────────────────────────────────────────
    def build_plan(self, goal: str) -> List[str]:
        """
        Return the ordered task list for a goal.
        Only includes tasks that have a registered bot.
        """
        raw_plan  = self.PLANS.get(goal, [])
        valid     = [t for t in raw_plan if t in self._registry]
        skipped   = set(raw_plan) - set(valid)
        if skipped:
            log.warning(f"Skipped (no bot registered): {skipped}")
        return valid

    # ── EXECUTION ENGINE ──────────────────────────────────────────────────────
    def execute_plan(self, plan: List[str]) -> List[Dict]:
        """
        Execute each task in order.
        Never raises — captures success/failure per task.
        """
        results: List[Dict] = []

        for task in plan:
            bot = self._registry.get(task)
            if bot is None:
                log.error(f"No bot for task '{task}' — skipping")
                results.append({"task": task, "status": "skipped", "reason": "bot_not_registered"})
                continue

            try:
                log.info(f"  ▶ {task}")
                t0 = time.time()
                output = bot.execute()   # BaseBot interface
                duration = round(time.time() - t0, 2)
                results.append({
                    "task": task,
                    "status": "success",
                    "output": str(output)[:500] if output else "",
                    "duration_seconds": duration,
                })
                log.info(f"  ✅ {task} ({duration}s)")
            except Exception as exc:
                log.error(f"  ❌ {task} failed: {exc}")
                results.append({"task": task, "status": "error", "error": str(exc)})

        return results

    # ── EVALUATION ────────────────────────────────────────────────────────────
    def evaluate(self, results: List[Dict]) -> Dict:
        """Compute cycle performance metrics."""
        total   = len(results)
        success = sum(1 for r in results if r["status"] == "success")
        failure = sum(1 for r in results if r["status"] == "error")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        rate    = round(success / total * 100, 2) if total > 0 else 0.0
        return {
            "total_tasks":   total,
            "success":       success,
            "failure":       failure,
            "skipped":       skipped,
            "success_rate":  rate,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    # ── STATE UPDATE ──────────────────────────────────────────────────────────
    def _update_state(self, state: Dict, goal: str, metrics: Dict) -> None:
        if metrics["failure"] > metrics["success"]:
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        else:
            state["consecutive_failures"] = 0
        state["last_goal"]    = goal
        state["total_cycles"] = state.get("total_cycles", 0) + 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        _save_system_state(state)

    # ── MEMORY PERSISTENCE ────────────────────────────────────────────────────
    def _persist_to_memory(self, goal: str, results: List[Dict], metrics: Dict) -> None:
        """Save cycle summary to the 5-tier memory system."""
        try:
            from core.narai_memory_manager import save as mem_save
            session_id = f"core_cycle_{int(time.time())}"
            stats = {"goal": goal, "metrics": metrics}
            content_count = metrics.get("success", 0)
            mem_save(
                tier="autopilot",
                key=session_id,
                content=json.dumps(stats),
                tags=["core_cycle", goal],
                importance=5,
            )
            log.info("Cycle saved to memory (autopilot tier)")
        except Exception as e:
            log.warning(f"Memory persist failed (non-fatal): {e}")


# ── Public singleton helper ────────────────────────────────────────────────────
_core_instance: Optional[NarAICore] = None


def get_narai_core() -> NarAICore:
    """Return singleton NarAICore instance."""
    global _core_instance
    if _core_instance is None:
        _core_instance = NarAICore()
    return _core_instance
