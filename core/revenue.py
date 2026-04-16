"""
core/revenue.py — Unified Revenue Dashboard

All money flows into one view:
  - Stripe: one-time sales + subscriptions
  - Affiliate: commissions from Impact.com + tracked links
  - Ad Spend ROI: budget spent vs revenue attributed
  - Email Funnel: subscriber value + broadcast conversions
  - Totals: daily / weekly / monthly / all-time

NarAI uses this to know exactly how much money she's making and where
it's coming from, so she can double down on what's working.
"""

from __future__ import annotations
import json
import os
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

DATA_FILE = Path("data/revenue.json")
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Revenue record ───────────────────────────────────────────────────────────


class RevenueRecord:
    def __init__(self, amount: float, source: str, label: str,
                 ts: str = "", metadata: Dict = None):
        self.amount = amount
        self.source = source   # stripe / affiliate / ad_attribution / manual
        self.label = label    # product name, affiliate program, etc.
        self.ts = ts or datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}

    def to_dict(self) -> Dict:
        return {"amount": self.amount, "source": self.source,
                "label": self.label, "ts": self.ts, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: Dict) -> "RevenueRecord":
        return cls(d["amount"], d["source"], d["label"],
                   d.get("ts", ""), d.get("metadata", {}))


# ─── Revenue Engine ───────────────────────────────────────────────────────────

class RevenueEngine:
    _instance: Optional["RevenueEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[RevenueRecord] = []
        self._load()

    @classmethod
    def get(cls) -> "RevenueEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if DATA_FILE.exists():
            try:
                raw = json.loads(DATA_FILE.read_text())
                self._records = [RevenueRecord.from_dict(r) for r in raw.get("records", [])]
                log.info(f"RevenueEngine: loaded {len(self._records)} records")
            except Exception as e:
                log.error(f"RevenueEngine load error: {e}")

    def _save(self):
        DATA_FILE.write_text(json.dumps(
            {"records": [r.to_dict() for r in self._records]}, indent=2
        ))

    # ── Recording ─────────────────────────────────────────────────────────────

    def record(self, amount: float, source: str, label: str, metadata: Dict = None):
        with self._lock:
            self._records.append(RevenueRecord(amount, source, label, metadata=metadata))
            self._save()
        # Sync to GoalTracker monthly_revenue
        try:
            from core.goal_tracker import GoalTracker
            current = self._total(days=30)
            GoalTracker.get().update("monthly_revenue", current)
        except Exception:
            pass

    # ── Stripe live pull ───────────────────────────────────────────────────────

    def pull_stripe(self, days: int = 30) -> Dict:
        if not STRIPE_KEY or STRIPE_KEY.startswith("sk_test_your"):
            return {"configured": False, "charges": [], "mrr": 0, "total": 0}
        try:
            import stripe
            stripe.api_key = STRIPE_KEY
            since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

            # One-time charges
            charges = stripe.Charge.list(limit=100, created={"gte": since})
            charge_list = []
            total = 0.0
            for c in charges.auto_paging_iter():
                if c.status == "succeeded":
                    amt = c.amount / 100.0
                    total += amt
                    charge_list.append({
                        "id": c.id,
                        "amount": amt,
                        "description": c.description or c.metadata.get("product", ""),
                        "customer_email": c.billing_details.email if c.billing_details else "",
                        "ts": datetime.fromtimestamp(c.created, timezone.utc).isoformat(),
                    })

            # Subscriptions MRR
            subs = stripe.Subscription.list(status="active", limit=100)
            mrr = 0.0
            for s in subs.auto_paging_iter():
                for item in s["items"]["data"]:
                    price = item["price"]
                    if price["recurring"]["interval"] == "month":
                        mrr += price["unit_amount"] / 100.0
                    elif price["recurring"]["interval"] == "year":
                        mrr += price["unit_amount"] / 100.0 / 12

            # Record new charges we haven't seen
            existing_ids = {r.metadata.get("stripe_id") for r in self._records
                           if r.source == "stripe"}
            for c in charge_list:
                if c["id"] not in existing_ids:
                    self.record(c["amount"], "stripe", c["description"] or "Stripe sale",
                                {"stripe_id": c["id"], "email": c.get("customer_email", "")})

            return {
                "configured": True,
                "period_days": days,
                "total_revenue": round(total, 2),
                "mrr": round(mrr, 2),
                "charge_count": len(charge_list),
                "recent_charges": charge_list[:10],
                "active_subscriptions": subs.total_count if hasattr(subs, "total_count") else 0,
            }
        except Exception as e:
            log.warning(f"Stripe pull failed: {e}")
            return {"configured": True, "error": str(e), "total": 0, "mrr": 0}

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
            return {"configured": False, "error": str(e), "total_earned": 0}

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
        except Exception as e:
            return {"error": str(e)}

    # ── Calculations ──────────────────────────────────────────────────────────

    def _total(self, days: int = 0, source: str = "") -> float:
        records = self._records
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            records = [r for r in records
                      if datetime.fromisoformat(r.ts.replace("Z", "+00:00")) >= cutoff]
        if source:
            records = [r for r in records if r.source == source]
        return round(sum(r.amount for r in records), 2)

    def _by_source(self, days: int = 30) -> Dict[str, float]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result: Dict[str, float] = {}
        for r in self._records:
            try:
                if datetime.fromisoformat(r.ts.replace("Z", "+00:00")) >= cutoff:
                    result[r.source] = round(result.get(r.source, 0) + r.amount, 2)
            except Exception:
                pass
        return result

    def _top_earners(self, days: int = 30, limit: int = 5) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        tally: Dict[str, float] = {}
        for r in self._records:
            try:
                if datetime.fromisoformat(r.ts.replace("Z", "+00:00")) >= cutoff:
                    tally[r.label] = round(tally.get(r.label, 0) + r.amount, 2)
            except Exception:
                pass
        return [{"label": k, "amount": v}
                for k, v in sorted(tally.items(), key=lambda x: x[1], reverse=True)[:limit]]

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def dashboard(self, refresh_live: bool = True) -> Dict:
        """Full revenue dashboard — optionally pulls live data from Stripe + Affiliate."""
        stripe_data = self.pull_stripe(30) if refresh_live else {}
        affiliate_data = self.pull_affiliate(30) if refresh_live else {}
        ad_roi = self.pull_ad_roi()

        today = self._total(days=1)
        week = self._total(days=7)
        month = self._total(days=30)
        alltime = self._total()

        by_source_30d = self._by_source(30)
        top_earners = self._top_earners(30)

        # Live data overrides/supplements local records
        stripe_total = stripe_data.get("total_revenue", 0)
        affiliate_total = affiliate_data.get("total_earned", 0)
        live_total_30d = stripe_total + affiliate_total

        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "period": {
                "today": today,
                "week": week,
                "month": max(month, live_total_30d),
                "all_time": alltime,
            },
            "by_source": {
                "stripe": stripe_total or by_source_30d.get("stripe", 0),
                "affiliate": affiliate_total or by_source_30d.get("affiliate", 0),
                "ad_attributed": by_source_30d.get("ad_attribution", 0),
                "manual": by_source_30d.get("manual", 0),
            },
            "stripe": stripe_data,
            "affiliate": affiliate_data,
            "ad_roi": ad_roi,
            "top_earners_30d": top_earners,
            "total_records": len(self._records),
            "mrr": stripe_data.get("mrr", 0),
            "goal_progress": self._goal_progress(max(month, live_total_30d)),
        }

    def _goal_progress(self, current: float) -> Dict:
        try:
            from core.goal_tracker import GoalTracker
            g = GoalTracker.get()._goals.get("monthly_revenue")
            if g:
                return {"target": g.target, "current": current,
                        "progress_pct": round(min(100, current / max(g.target, 1) * 100), 1)}
        except Exception:
            pass
        return {"target": 1000, "current": current,
                "progress_pct": round(min(100, current / 1000 * 100), 1)}

    def summary(self) -> Dict:
        return {
            "today": self._total(days=1),
            "week": self._total(days=7),
            "month": self._total(days=30),
            "all_time": self._total(),
            "by_source_30d": self._by_source(30),
            "top_earners_30d": self._top_earners(30, 3),
            "total_records": len(self._records),
            "stripe_configured": bool(STRIPE_KEY and not STRIPE_KEY.startswith("sk_test_your")),
        }

    # ── Reporting ─────────────────────────────────────────────────────────────

    def daily_report(self) -> str:
        s = self.summary()
        lines = [
            f"💰 NarAI Revenue Report — {datetime.now().strftime('%b %d')}",
            "",
            f"Today:    ${s['today']:.2f}",
            f"This week: ${s['week']:.2f}",
            f"This month: ${s['month']:.2f}",
            f"All-time: ${s['all_time']:.2f}",
        ]
        if s["by_source_30d"]:
            lines.append("\nBy source (30d):")
            for src, amt in s["by_source_30d"].items():
                lines.append(f"  {src}: ${amt:.2f}")
        if s["top_earners_30d"]:
            lines.append("\nTop earners (30d):")
            for e in s["top_earners_30d"]:
                lines.append(f"  {e['label']}: ${e['amount']:.2f}")
        goal = self._goal_progress(s["month"])
        lines.append(f"\n🎯 Monthly goal: ${goal['current']:.2f} / ${goal['target']} ({goal['progress_pct']}%)")
        return "\n".join(lines)

    def send_daily_report(self):
        report = self.daily_report()
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            import requests
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT, "text": report},
                    timeout=5,
                )
            except Exception:
                pass


# ─── Module-level convenience ─────────────────────────────────────────────────

def record_revenue(amount: float, source: str, label: str, metadata: Dict = None):
    RevenueEngine.get().record(amount, source, label, metadata)


def get_dashboard(refresh_live: bool = True) -> Dict:
    return RevenueEngine.get().dashboard(refresh_live)


def get_summary() -> Dict:
    return RevenueEngine.get().summary()
