"""
core/revenue.py — Unified Revenue Dashboard

All money flows into one view, read from the daily numbers board's ledger
(core/board/money.py) by New York calendar day:
  - Stripe: one-time sales and subscriptions, from the Stripe sync's balance
    transactions (net of refunds and disputes, before fees)
  - Manual entries: money recorded by hand (POST /api/revenue/record,
    POST /api/money/record), as manual ledger rows
  - Affiliate: commissions from Impact.com, read live
  - Ad spend ROI: BudgetManager's numbers
  - Totals: today, the last 7 days, the last 30 days, all time

Nothing here keeps a file of its own: the old JSON revenue store is gone.
A number that is not measured is None, never 0. Money never includes an
estimate. Live Stripe calls are only for the MRR card.

NarAI uses this to know exactly how much money she's making and where
it's coming from, so she can double down on what's working.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import os

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_LIMIT = 4096        # characters in one Telegram message
GOAL_TARGET_DEFAULT = 1000   # dollars a month, when GoalTracker has no monthly_revenue goal


def _telegram() -> Optional[tuple]:
    """(token, chat id), read when needed; None while either is unset."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return (token, chat) if token and chat else None


def telegram_configured() -> bool:
    return _telegram() is not None


# ─── Revenue Engine ───────────────────────────────────────────────────────────

class RevenueEngine:
    _instance: Optional["RevenueEngine"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "RevenueEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Recording ─────────────────────────────────────────────────────────────

    def record(self, amount: float, source: str, label: str, metadata: Dict = None,
               idempotency_key: Optional[str] = None) -> Dict:
        """Record money that did not come through Stripe, as a manual ledger
        row (core.board.money.record_manual). With an idempotency_key, the
        same key again answers from the stored entry (replayed: true) and is
        never written twice. Returns {id, amount, cents, replayed}; raises
        money.NotRecorded (422 a refused amount or text, 409 the key was used
        for another amount, 503 the database is not connected). Then the
        monthly revenue goal follows the last 30 days, when they are measured."""
        from core.board import money
        result = money.record_manual(source, amount, label=label, entered_via="RevenueEngine.record",
                                     metadata=metadata, idempotency_key=idempotency_key)
        self._update_goal()
        return result

    def _update_goal(self) -> None:
        """GoalTracker's monthly_revenue follows the ledger's last 30 New York
        days (all sources); left alone while they are not measured. Never
        raises."""
        try:
            from core.board import money
            month = money.month_total()
            if month is None:
                return
            from core.goal_tracker import GoalTracker
            GoalTracker.get().update("monthly_revenue", month)
        except Exception as e:  # noqa: BLE001 — the goal must never undo a recorded entry
            log.warning("revenue goal not updated (%s)", type(e).__name__)

    # ── Stripe live pull: the MRR card only ───────────────────────────────────

    def live_mrr(self) -> Dict:
        """{configured, mrr (dollars), active_subscriptions, error}, read live
        from Stripe's active subscriptions (core.board.connectors.stripe_sync
        mrr). The key is read now: STRIPE_READ_KEY, else STRIPE_SECRET_KEY; a
        placeholder or test-mode key is not configured. An error is named by
        its type only: a Stripe error can quote part of the key."""
        from core.board.connectors import stripe_sync
        key = stripe_sync.read_key()
        if key is None or stripe_sync.is_test_key(key[0]):
            from core.board.day import read_problem
            return {"configured": False, "mrr": None, "active_subscriptions": None,
                    "note": read_problem("stripe") or "Stripe key not set"}
        try:
            cents, count, problem = stripe_sync.mrr(key[0])
        except Exception as e:  # noqa: BLE001 — a card that cannot be read reads null
            log.warning("Stripe MRR not read (%s)", type(e).__name__)
            return {"configured": True, "mrr": None, "active_subscriptions": None, "error": type(e).__name__}
        out = {"configured": True, "mrr": None if cents is None else cents / 100, "active_subscriptions": count}
        if problem:
            out["error"] = problem
        return out

    def pull_stripe(self, days: int = 30) -> Dict:
        """The Stripe card: MRR and active subscriptions read live
        (live_mrr), and the last `days` New York days from the ledger:
        total_revenue (net dollars), charge_count (sales) and recent_charges
        (the 10 newest sales, buyers masked). Nothing is written."""
        from core.board import money
        live = self.live_mrr()
        if not live["configured"]:
            return {"configured": False, "period_days": days, "total_revenue": None, "mrr": None,
                    "charge_count": None, "recent_charges": [], "active_subscriptions": None}
        out = {"configured": True, "period_days": days, **money.stripe_window(days),
               "mrr": live["mrr"], "active_subscriptions": live["active_subscriptions"]}
        if live.get("error"):
            out["error"] = live["error"]
        return out

    # ── Affiliate live pull ────────────────────────────────────────────────────

    def pull_affiliate(self, days: int = 30) -> Dict:
        try:
            from core.impact import get_summary
            data = get_summary()
            earned = data.get("last_30_days", {}).get("total_earned", 0)
            return {
                "configured": data.get("configured", False),
                "total_earned": earned,
                "period_days": days,
                "by_program": data.get("last_30_days", {}).get("by_program", {}),
            }
        except Exception as e:
            return {"configured": False, "error": type(e).__name__, "total_earned": None}

    # ── Budget ROI ────────────────────────────────────────────────────────────

    def pull_ad_roi(self) -> Dict:
        try:
            from core.budget_manager import BudgetManager
            bm = BudgetManager.get()
            return {
                "today_spent": bm.today_spent(),
                "today_revenue": bm.today_revenue(),
                "today_roi_pct": bm.today_roi(),
                "all_time_spent": bm.summary().get("all_time_spent", 0),
                "all_time_revenue": bm.summary().get("all_time_revenue", 0),
            }
        except Exception as e:  # noqa: BLE001 — named by its type: an error's text can quote a setting
            return {"error": type(e).__name__}

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def dashboard(self, refresh_live: bool = True) -> Dict:
        """Full revenue dashboard: the ledger's numbers by New York day, plus,
        with refresh_live, Stripe's MRR and Impact's commissions read live."""
        from core.board import money
        stripe_data = self.pull_stripe(30) if refresh_live else {}
        affiliate_data = self.pull_affiliate(30) if refresh_live else {}
        ad_roi = self.pull_ad_roi()
        s = self.summary(top=5)
        by_30d = s["by_source_30d"]
        affiliate = (affiliate_data.get("total_earned")
                     if affiliate_data.get("configured") and not affiliate_data.get("error") else None)
        by_source = {"stripe": by_30d.get("stripe"), "affiliate": affiliate, "ad_attributed": None,
                     "manual": by_30d.get(money.MANUAL)}
        for source_id, amount in by_30d.items():
            by_source.setdefault(source_id, amount)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "period": {"today": s["today"], "week": s["week"], "month": s["month"], "all_time": s["all_time"]},
            "by_source": by_source,
            "stripe": stripe_data,
            "affiliate": affiliate_data,
            "ad_roi": ad_roi,
            "top_earners_30d": s["top_earners_30d"],
            "total_records": s["total_records"],
            "mrr": stripe_data.get("mrr") if refresh_live else None,
            "goal_progress": self._goal_progress(s["month"]),
            "ledger": {"day": s["day"], "tz": s["tz"], "measured_from": s["measured_from"], "note": s["note"]},
        }

    @staticmethod
    def _goal_target():
        try:
            from core.goal_tracker import GoalTracker
            g = GoalTracker.get()._goals.get("monthly_revenue")
            if g:
                return g.target
        except Exception:  # noqa: BLE001 — the default target then
            pass
        return GOAL_TARGET_DEFAULT

    def _goal_progress(self, current: Optional[float]) -> Dict:
        """{target, current, progress_pct}; current and progress_pct are
        None while the last 30 days are not measured."""
        from core.board import money
        return money.goal_progress(current, self._goal_target())

    def summary(self, top: int = 3) -> Dict:
        """today, week, month and all_time (dollars, every source, None unless
        measured), by_source_30d, top_earners_30d, total_records and
        stripe_configured (core.board.money.summary)."""
        from core.board import money
        return money.summary(top)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def daily_report(self) -> str:
        """The revenue report in plain English and plain text. The owner's
        daily message is the board's at 07:00 New York time; this one goes
        out only when asked (POST /api/revenue/send-report)."""
        from core.board import money
        return money.report_text(money.summary_cents(), self._goal_target())

    def send_daily_report(self) -> bool:
        """Send the report to Telegram as plain text. True only when Telegram
        accepted it. The token is never logged: an error is named by its type."""
        settings = _telegram()
        if settings is None:
            log.info("revenue report not sent: Telegram is not configured")
            return False
        token, chat = settings
        report = self.daily_report()[:TELEGRAM_LIMIT]
        import requests
        try:
            r = requests.post(TELEGRAM_API.format(token=token),
                              json={"chat_id": chat, "text": report, "disable_web_page_preview": True},
                              timeout=10)
            accepted = r.status_code == 200 and (r.json() or {}).get("ok") is True
        except Exception as e:  # noqa: BLE001 — its text can carry the URL, which holds the token
            log.warning("revenue report not sent (%s)", type(e).__name__)
            return False
        if not accepted:
            log.warning("revenue report not sent: Telegram answered HTTP %s", r.status_code)
        return accepted


# ─── Module-level convenience ─────────────────────────────────────────────────

def record_revenue(amount: float, source: str, label: str, metadata: Dict = None,
                   idempotency_key: Optional[str] = None) -> Dict:
    return RevenueEngine.get().record(amount, source, label, metadata, idempotency_key=idempotency_key)


def update_revenue_goal() -> None:
    """The monthly revenue goal follows the ledger's last 30 New York days:
    after a Stripe sync and after a manual entry. Best effort, never raises."""
    RevenueEngine.get()._update_goal()


def get_dashboard(refresh_live: bool = True) -> Dict:
    return RevenueEngine.get().dashboard(refresh_live)


def get_summary() -> Dict:
    return RevenueEngine.get().summary()
