"""
core/revenue_loop.py
Unified Revenue Loop — one call drives the full money engine.

Executes in order:
  1. Shopify autopilot session  (digital products + POD + funnels)
  2. POD top-up if session under-delivered
  3. Stripe revenue snapshot
  4. Memory update

This is the ONLY revenue automation that should be triggered from
the API or scheduler. Everything else is an implementation detail.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger("RevenueLoop")


class RevenueLoop:
    """
    One call → full revenue cycle.

    Usage:
        loop = RevenueLoop()
        report = loop.run()
    """

    def __init__(
        self,
        shopify_target_products: int = 3,
        pod_top_up_target: int = 2,
    ) -> None:
        self.shopify_target = shopify_target_products
        self.pod_top_up     = pod_top_up_target

    def run(self) -> Dict[str, Any]:
        """Execute one complete revenue cycle. Never raises."""
        start  = datetime.now(timezone.utc)
        report: Dict[str, Any] = {
            "cycle_id":      start.isoformat(),
            "shopify":       {},
            "pod":           {},
            "stripe":        {},
            "errors":        [],
            "status":        "complete",
        }

        log.info("=" * 56)
        log.info("Revenue Loop starting…")

        # ── Step 1: Shopify autopilot session ─────────────────────────────
        log.info("Step 1 — Shopify autopilot session")
        try:
            from core.narai_shopify_autopilot import run_shopify_session
            shopify_result = run_shopify_session()
            report["shopify"] = {
                "status":     "success",
                "session_id": shopify_result.get("session_id"),
                "stats":      shopify_result.get("stats", {}),
                "progress":   shopify_result.get("progress", 0),
            }
            products_created = shopify_result.get("stats", {}).get("products_published", 0)
            log.info(f"Shopify session complete: {products_created} products published")
        except Exception as e:
            log.error(f"Shopify session failed: {e}")
            report["shopify"] = {"status": "error", "error": str(e)}
            report["errors"].append({"step": "shopify", "error": str(e)})
            products_created = 0

        # ── Step 2: POD top-up if needed ──────────────────────────────────
        pod_needed = max(0, self.shopify_target - products_created)
        if pod_needed > 0:
            log.info(f"Step 2 — POD top-up ({pod_needed} products needed)")
            try:
                from core.narai_pod_engine import run_pod_session
                pod_result = run_pod_session(target=min(pod_needed, self.pod_top_up))
                report["pod"] = {
                    "status":           "success",
                    "products_created": pod_result.get("products_created", 0),
                    "summary":          pod_result.get("summary", {}),
                }
                log.info(f"POD session: {pod_result.get('products_created', 0)} products created")
            except Exception as e:
                log.error(f"POD session failed: {e}")
                report["pod"] = {"status": "error", "error": str(e)}
                report["errors"].append({"step": "pod", "error": str(e)})
        else:
            log.info("Step 2 — POD top-up skipped (target met)")
            report["pod"] = {"status": "skipped", "reason": "target_met"}

        # ── Step 3: Stripe revenue snapshot ───────────────────────────────
        log.info("Step 3 — Stripe revenue snapshot")
        try:
            from core.revenue import RevenueEngine
            dashboard = RevenueEngine.get().dashboard()
            report["stripe"] = {
                "status":        "success",
                "total_revenue": dashboard.get("total", 0),
                "mrr":           dashboard.get("mrr", 0),
                "period":        dashboard.get("period", {}),
            }
            log.info(
                f"Revenue snapshot: total=${dashboard.get('total', 0):.2f} "
                f"MRR=${dashboard.get('mrr', 0):.2f}"
            )
        except Exception as e:
            log.warning(f"Stripe snapshot failed (non-fatal): {e}")
            report["stripe"] = {"status": "error", "error": str(e)}

        # ── Step 4: Update system state ───────────────────────────────────
        log.info("Step 4 — Updating system state")
        try:
            from core.narai_memory_manager import load_state, update_state
            state = load_state()
            # Update revenue from Stripe snapshot
            stripe_total = report["stripe"].get("total_revenue", 0)
            if stripe_total:
                state["revenue"] = stripe_total
            # Count new assets
            new_assets = (
                report["pod"].get("products_created", 0)
                + report["shopify"].get("stats", {}).get("products_published", 0)
            )
            state["assets"] = state.get("assets", 0) + new_assets

            results_for_memory = [
                {"task": "shopify_session", "status": "success" if report["shopify"].get("status") == "success" else "error"},
                {"task": "pod_session",     "status": "success" if report["pod"].get("status")     == "success" else "skipped"},
            ]
            metrics = {
                "success": sum(1 for r in results_for_memory if r["status"] == "success"),
                "failure": sum(1 for r in results_for_memory if r["status"] == "error"),
                "skipped": sum(1 for r in results_for_memory if r["status"] == "skipped"),
            }
            update_state(state, "make_money", results_for_memory, metrics)
            log.info("System state updated")
        except Exception as e:
            log.warning(f"State update failed (non-fatal): {e}")

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        report["duration_seconds"] = round(duration, 2)
        report["errors_count"]     = len(report["errors"])

        log.info(
            f"Revenue Loop complete in {duration:.2f}s | "
            f"errors={len(report['errors'])}"
        )
        log.info("=" * 56)
        return report


# ── Singleton helper ───────────────────────────────────────────────────────────
_loop_instance: Optional[RevenueLoop] = None


def get_revenue_loop() -> RevenueLoop:
    """Return singleton RevenueLoop instance."""
    global _loop_instance
    if _loop_instance is None:
        _loop_instance = RevenueLoop()
    return _loop_instance
