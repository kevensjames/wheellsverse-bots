"""
core/conversion_analytics.py — Unified Conversion Analytics

Tracks the full funnel from first touch to revenue:
  Impression → Click → Lead → Subscriber → Buyer → VIP

Metrics:
  - Funnel conversion rates at each stage
  - Platform attribution (which platform drives most leads/revenue)
  - Weekly cohort analysis
  - Lifetime value (LTV) per source/niche
  - Content ROI per post
  - A/B testing for headlines, CTAs, hooks
"""

from __future__ import annotations
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)
DATA_FILE = Path("data/conversion_analytics.json")

FUNNEL_STAGES = ["impression", "click", "lead", "subscriber", "buyer", "vip"]

EVENT_TYPES = {
    "impression": {"stage": "impression", "value": 0.001},
    "content_view": {"stage": "impression", "value": 0.005},
    "link_click": {"stage": "click", "value": 0.05},
    "affiliate_click": {"stage": "click", "value": 0.10},
    "landing_visit": {"stage": "click", "value": 0.15},
    "optin": {"stage": "lead", "value": 0.50},
    "lead_captured": {"stage": "lead", "value": 0.75},
    "email_opened": {"stage": "subscriber", "value": 0.10},
    "purchase": {"stage": "buyer", "value": 10.0},
    "subscription": {"stage": "buyer", "value": 5.0},
    "affiliate_sale": {"stage": "buyer", "value": 2.0},
}


class AnalyticsEvent:
    def __init__(self, event_type: str, platform: str = "", niche: str = "",
                 user_id: str = "", content_id: str = "", value: float = 0.0,
                 metadata: Dict = None):
        self.event_type = event_type
        self.platform = platform
        self.niche = niche
        self.user_id = user_id
        self.content_id = content_id
        self.value = value or EVENT_TYPES.get(event_type, {}).get("value", 0)
        self.stage = EVENT_TYPES.get(event_type, {}).get("stage", "unknown")
        self.metadata = metadata or {}
        self.ts = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {k: v for k, v in {
            "event_type": self.event_type, "platform": self.platform,
            "niche": self.niche, "user_id": self.user_id,
            "content_id": self.content_id, "value": self.value,
            "stage": self.stage, "metadata": self.metadata, "ts": self.ts,
        }.items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "AnalyticsEvent":
        e = cls(d["event_type"], d.get("platform", ""), d.get("niche", ""),
                d.get("user_id", ""), d.get("content_id", ""), d.get("value", 0), d.get("metadata", {}))
        e.ts = d.get("ts", e.ts)
        e.stage = d.get("stage", e.stage)
        return e


class ABTest:
    def __init__(self, test_id: str, name: str, variants: List[str]):
        self.test_id = test_id
        self.name = name
        self.variants = variants
        self.results: Dict[str, Dict] = {
            v: {"impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0.0}
            for v in variants
        }
        self.status = "running"
        self.winner = ""
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.ended_at = ""

    @property
    def cvr(self) -> Dict[str, float]:
        return {v: round(r["conversions"] / max(r["clicks"], 1) * 100, 2)
                for v, r in self.results.items()}

    @property
    def ctr(self) -> Dict[str, float]:
        return {v: round(r["clicks"] / max(r["impressions"], 1) * 100, 2)
                for v, r in self.results.items()}

    def record(self, variant: str, event: str, value: float = 0):
        if variant not in self.results:
            return
        r = self.results[variant]
        if event == "impression":
            r["impressions"] += 1
        elif event == "click":
            r["clicks"] += 1
        elif event in ("conversion", "purchase"):
            r["conversions"] += 1
            r["revenue"] = round(r["revenue"] + value, 2)

    def evaluate(self) -> Optional[str]:
        if any(r["impressions"] < 50 for r in self.results.values()):
            return None
        best = max(self.results, key=lambda v: self.cvr.get(v, 0))
        others = [v for v in self.results if v != best]
        if others:
            second_best = max(others, key=lambda v: self.cvr.get(v, 0))
            if self.cvr.get(best, 0) >= self.cvr.get(second_best, 0) * 1.2:
                self.winner = best
                self.status = "completed"
                self.ended_at = datetime.now(timezone.utc).isoformat()
                return best
        return None

    def to_dict(self) -> Dict:
        return {
            "test_id": self.test_id, "name": self.name, "variants": self.variants,
            "results": self.results, "status": self.status, "winner": self.winner,
            "ctr": self.ctr, "cvr": self.cvr,
            "created_at": self.created_at, "ended_at": self.ended_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ABTest":
        t = cls(d["test_id"], d["name"], d.get("variants", []))
        t.results = d.get("results", t.results)
        t.status = d.get("status", "running")
        t.winner = d.get("winner", "")
        t.created_at = d.get("created_at", t.created_at)
        t.ended_at = d.get("ended_at", "")
        return t


class ConversionAnalytics:
    _instance: Optional["ConversionAnalytics"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._events: List[AnalyticsEvent] = []
        self._ab_tests: Dict[str, ABTest] = {}
        self._load()

    @classmethod
    def get(cls) -> "ConversionAnalytics":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self):
        if DATA_FILE.exists():
            try:
                raw = json.loads(DATA_FILE.read_text())
                self._events = [AnalyticsEvent.from_dict(e) for e in raw.get("events", [])]
                self._ab_tests = {k: ABTest.from_dict(v)
                                  for k, v in raw.get("ab_tests", {}).items()}
            except Exception as e:
                log.error(f"ConversionAnalytics load error: {e}")

    def _save(self):
        DATA_FILE.write_text(json.dumps({
            "events": [e.to_dict() for e in self._events[-10000:]],
            "ab_tests": {k: v.to_dict() for k, v in self._ab_tests.items()},
        }, indent=2))

    # ── Tracking ───────────────────────────────────────────────────────────────

    def track(self, event_type: str, platform: str = "", niche: str = "",
              user_id: str = "", content_id: str = "", value: float = 0.0,
              metadata: Dict = None) -> AnalyticsEvent:
        event = AnalyticsEvent(event_type, platform, niche, user_id,
                               content_id, value, metadata)
        with self._lock:
            self._events.append(event)
            if len(self._events) % 50 == 0:
                self._save()
        return event

    def flush(self):
        self._save()

    # ── Funnel ────────────────────────────────────────────────────────────────

    def funnel(self, days: int = 30, platform: str = "", niche: str = "") -> Dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = [e for e in self._events
                  if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= cutoff]
        if platform:
            events = [e for e in events if e.platform == platform]
        if niche:
            events = [e for e in events if e.niche == niche]

        by_stage: Dict[str, int] = {s: 0 for s in FUNNEL_STAGES}
        for e in events:
            if e.stage in by_stage:
                by_stage[e.stage] += 1

        rates = {}
        for i in range(len(FUNNEL_STAGES) - 1):
            a, b = FUNNEL_STAGES[i], FUNNEL_STAGES[i + 1]
            rates[f"{a}→{b}"] = round(by_stage[b] / max(by_stage[a], 1) * 100, 2)

        return {
            "period_days": days,
            "platform": platform or "all",
            "niche": niche or "all",
            "stages": by_stage,
            "conversion_rates": rates,
            "total_events": len(events),
            "total_value": round(sum(e.value for e in events), 2),
        }

    # ── Attribution ────────────────────────────────────────────────────────────

    def attribution(self, days: int = 30) -> Dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = [e for e in self._events
                  if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= cutoff]
        by_platform: Dict[str, Dict] = {}
        for e in events:
            p = e.platform or "unknown"
            if p not in by_platform:
                by_platform[p] = {"events": 0, "leads": 0, "buyers": 0, "value": 0.0}
            by_platform[p]["events"] += 1
            by_platform[p]["value"] = round(by_platform[p]["value"] + e.value, 2)
            if e.stage == "lead":
                by_platform[p]["leads"] += 1
            if e.stage == "buyer":
                by_platform[p]["buyers"] += 1
        ranked = sorted(by_platform.items(), key=lambda x: x[1]["value"], reverse=True)
        return {
            "period_days": days,
            "platforms": [{"platform": k, **v} for k, v in ranked],
            "best_platform": ranked[0][0] if ranked else None,
        }

    # ── Cohorts ───────────────────────────────────────────────────────────────

    def cohorts(self, weeks: int = 8) -> Dict:
        now = datetime.now(timezone.utc)
        result = []
        for w in range(weeks):
            ws = now - timedelta(weeks=w + 1)
            we = now - timedelta(weeks=w)
            wevents = [e for e in self._events
                       if ws <= datetime.fromisoformat(e.ts.replace("Z", "+00:00")) < we]
            leads = sum(1 for e in wevents if e.stage == "lead")
            buyers = sum(1 for e in wevents if e.stage == "buyer")
            revenue = sum(e.value for e in wevents if e.stage == "buyer")
            result.append({
                "week": ws.strftime("%Y-%m-%d"),
                "leads": leads, "buyers": buyers,
                "conversion_pct": round(buyers / max(leads, 1) * 100, 1),
                "revenue": round(revenue, 2),
            })
        return {"cohorts": list(reversed(result))}

    # ── LTV ───────────────────────────────────────────────────────────────────

    def ltv_by_source(self, days: int = 90) -> Dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        buyers = [e for e in self._events
                  if e.stage == "buyer"
                  and datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= cutoff]
        by_src: Dict[str, Dict] = {}
        for e in buyers:
            src = e.platform or "unknown"
            if src not in by_src:
                by_src[src] = {"buyers": 0, "revenue": 0.0}
            by_src[src]["buyers"] += 1
            by_src[src]["revenue"] = round(by_src[src]["revenue"] + e.value, 2)
        return {
            "period_days": days,
            "by_source": {
                src: {**d, "avg_ltv": round(d["revenue"] / max(d["buyers"], 1), 2)}
                for src, d in by_src.items()
            },
        }

    # ── Content ROI ───────────────────────────────────────────────────────────

    def content_roi(self, days: int = 30) -> Dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = [e for e in self._events
                  if e.content_id
                  and datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= cutoff]
        by_content: Dict[str, Dict] = {}
        for e in events:
            c = e.content_id
            if c not in by_content:
                by_content[c] = {"impressions": 0, "clicks": 0, "leads": 0, "revenue": 0.0}
            if e.stage == "impression":
                by_content[c]["impressions"] += 1
            elif e.stage == "click":
                by_content[c]["clicks"] += 1
            elif e.stage == "lead":
                by_content[c]["leads"] += 1
            by_content[c]["revenue"] = round(by_content[c]["revenue"] + e.value, 2)
        ranked = sorted(by_content.items(), key=lambda x: x[1]["revenue"], reverse=True)
        return {"period_days": days,
                "top_content": [{"content_id": k, **v} for k, v in ranked[:10]]}

    # ── A/B Testing ───────────────────────────────────────────────────────────

    def create_ab_test(self, test_id: str, name: str, variants: List[str]) -> ABTest:
        test = ABTest(test_id, name, variants)
        self._ab_tests[test_id] = test
        self._save()
        return test

    def record_ab(self, test_id: str, variant: str, event: str, value: float = 0):
        if test_id not in self._ab_tests:
            return
        self._ab_tests[test_id].record(variant, event, value)
        winner = self._ab_tests[test_id].evaluate()
        if winner:
            log.info(f"A/B test '{test_id}' winner: {winner}")
        self._save()

    def get_ab_test(self, test_id: str) -> Optional[Dict]:
        t = self._ab_tests.get(test_id)
        return t.to_dict() if t else None

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def dashboard(self, days: int = 30) -> Dict:
        return {
            "period_days": days,
            "funnel": self.funnel(days),
            "attribution": self.attribution(days),
            "cohorts": self.cohorts(4),
            "ltv": self.ltv_by_source(90),
            "content_roi": self.content_roi(days),
            "ab_tests_running": sum(1 for t in self._ab_tests.values() if t.status == "running"),
            "total_events": len(self._events),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def summary(self) -> Dict:
        funnel = self.funnel(30)
        attr = self.attribution(30)
        return {
            "total_events": len(self._events),
            "funnel_30d": funnel["stages"],
            "best_platform": attr.get("best_platform"),
            "total_value_30d": funnel["total_value"],
            "ab_tests": len(self._ab_tests),
            "ab_running": sum(1 for t in self._ab_tests.values() if t.status == "running"),
        }


# ─── Module-level convenience ─────────────────────────────────────────────────

def track(event_type: str, platform: str = "", niche: str = "",
          user_id: str = "", content_id: str = "", value: float = 0.0) -> Dict:
    return ConversionAnalytics.get().track(
        event_type, platform, niche, user_id, content_id, value
    ).to_dict()


def get_dashboard(days: int = 30) -> Dict:
    return ConversionAnalytics.get().dashboard(days)


def get_funnel(days: int = 30, platform: str = "") -> Dict:
    return ConversionAnalytics.get().funnel(days, platform)
