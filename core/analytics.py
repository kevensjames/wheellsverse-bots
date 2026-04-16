#!/usr/bin/env python3
"""
core/analytics.py
─────────────────────────────────────────────────────────────────────────────
Platform Analytics — tracks posts, leads, traffic, and conversions.

Aggregates data from:
  • ContentPipeline run history
  • EmailCapture leads
  • Intelligence records
  • Publisher output

Saves daily summaries to /outputs/reports/
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "outputs" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_FILE = REPORTS_DIR / "platform_analytics.json"

logger = logging.getLogger("analytics")


class PlatformAnalytics:
    """
    Central analytics hub. Tracks posts, leads, traffic, conversion rates.
    Persists data daily so history accumulates across restarts.
    """

    def __init__(self):
        self._lock: threading.Lock = threading.Lock()
        self._daily: Dict[str, Dict] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if ANALYTICS_FILE.exists():
            try:
                self._daily = json.loads(ANALYTICS_FILE.read_text(encoding="utf-8"))
                logger.info(f"Analytics loaded: {len(self._daily)} days of data")
            except Exception as e:
                logger.warning(f"Could not load analytics: {e}")

    def _save(self):
        try:
            ANALYTICS_FILE.write_text(json.dumps(self._daily, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Could not save analytics: {e}")

    def _today_key(self) -> str:
        return date.today().isoformat()

    def _ensure_day(self, day_key: str) -> Dict:
        if day_key not in self._daily:
            self._daily[day_key] = {
                "date": day_key,
                "posts_created": 0,
                "posts_published": 0,
                "leads_captured": 0,
                "estimated_traffic": 0,
                "affiliate_clicks": 0,
                "conversion_rate": 0.0,
                "topics": [],
                "platforms": {},
                "errors": 0,
            }
        return self._daily[day_key]

    # ── Track Events ──────────────────────────────────────────────────────────

    def track_post_created(self, topic: str = "", count: int = 1):
        with self._lock:
            day = self._ensure_day(self._today_key())
            day["posts_created"] += count
            if topic and topic[:60] not in day["topics"]:
                day["topics"].append(topic[:60])
            self._calc_conversion(day)
            self._save()

    def track_post_published(self, platform: str = "static", count: int = 1):
        with self._lock:
            day = self._ensure_day(self._today_key())
            day["posts_published"] += count
            day["platforms"][platform] = day["platforms"].get(platform, 0) + count
            day["estimated_traffic"] += count * 50   # ~50 visitors per post (conservative)
            self._save()

    def track_lead(self, source: str = "landing_page"):
        with self._lock:
            day = self._ensure_day(self._today_key())
            day["leads_captured"] += 1
            self._calc_conversion(day)
            self._save()

    def track_affiliate_click(self, count: int = 1):
        with self._lock:
            day = self._ensure_day(self._today_key())
            day["affiliate_clicks"] += count
            self._save()

    def track_error(self):
        with self._lock:
            day = self._ensure_day(self._today_key())
            day["errors"] += 1
            self._save()

    def _calc_conversion(self, day: Dict):
        traffic = day.get("estimated_traffic", 0)
        leads = day.get("leads_captured", 0)
        # Only calculate rate when we have actual traffic data
        day["conversion_rate"] = round(leads / traffic * 100, 3) if traffic > 0 else 0.0

    # ── Reports ───────────────────────────────────────────────────────────────

    def get_today(self) -> Dict:
        day = self._ensure_day(self._today_key())
        self._calc_conversion(day)  # always recalculate so stale JSON values are corrected
        return day

    def get_summary(self, days: int = 30) -> Dict:
        """Aggregate stats for the last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
        recent = [v for k, v in self._daily.items() if k >= cutoff]
        if not recent:
            return {
                "days": days, "total_posts": 0, "total_leads": 0,
                "total_traffic": 0, "avg_conversion": 0.0,
                "best_day": None, "daily": [],
            }
        total_posts = sum(d.get("posts_created", 0) for d in recent)
        total_leads = sum(d.get("leads_captured", 0) for d in recent)
        total_traffic = sum(d.get("estimated_traffic", 0) for d in recent)
        avg_conv = round(
            sum(d.get("conversion_rate", 0) for d in recent) / len(recent), 3
        )
        best_day = max(recent, key=lambda d: d.get("leads_captured", 0))
        return {
            "days": days,
            "total_posts": total_posts,
            "total_leads": total_leads,
            "total_traffic": total_traffic,
            "avg_conversion": avg_conv,
            "best_day": best_day.get("date"),
            "daily": sorted(recent, key=lambda d: d["date"], reverse=True),
        }

    def get_full_summary(self) -> Dict:
        """Comprehensive platform analytics combining all subsystems."""
        today = self.get_today()
        last_7 = self.get_summary(7)
        last_30 = self.get_summary(30)
        content = self._load_content_analytics()
        leads = self._load_lead_stats()
        return {
            "today": today,
            "last_7_days": last_7,
            "last_30_days": last_30,
            "content": content,
            "leads": leads,
            "generated_at": datetime.now().isoformat(),
        }

    def _load_content_analytics(self) -> Dict:
        try:
            from pipelines.content_pipeline import get_content_pipeline
            analytics = get_content_pipeline().get_analytics()
            if not analytics:
                return {"total_runs": 0, "total_pieces": 0, "recent_runs": []}
            total_pieces = sum(a.get("pieces_created", 0) for a in analytics)
            return {
                "total_runs": len(analytics),
                "total_pieces": total_pieces,
                "recent_runs": analytics[:5],
            }
        except Exception:
            return {"total_runs": 0, "total_pieces": 0, "recent_runs": []}

    def _load_lead_stats(self) -> Dict:
        try:
            from core.email_capture import get_email_capture
            return get_email_capture().get_stats()
        except Exception:
            return {"total_leads": 0, "leads_today": 0}

    def generate_daily_report(self) -> str:
        """Generate and save the daily analytics report as Markdown."""
        summary = self.get_full_summary()
        today = summary["today"]
        report = f"""# WheellsVerse Daily Analytics Report
Date: {date.today().isoformat()}
Generated: {datetime.now().strftime('%H:%M:%S')}

## Today's Performance
- Posts Created:    {today.get('posts_created', 0)}
- Posts Published:  {today.get('posts_published', 0)}
- Leads Captured:   {today.get('leads_captured', 0)}
- Est. Traffic:     {today.get('estimated_traffic', 0)} visitors
- Conversion Rate:  {today.get('conversion_rate', 0):.3f}%
- Affiliate Clicks: {today.get('affiliate_clicks', 0)}

## Topics Today
{chr(10).join(f"  • {t}" for t in today.get('topics', ['None yet']))}

## Last 30 Days
- Total Posts:    {summary['last_30_days']['total_posts']}
- Total Leads:    {summary['last_30_days']['total_leads']}
- Total Traffic:  {summary['last_30_days']['total_traffic']}
- Avg Conversion: {summary['last_30_days']['avg_conversion']:.3f}%
- Best Day:       {summary['last_30_days']['best_day'] or 'N/A'}

## Lead Stats
- Total Leads:  {summary['leads'].get('total_leads', 0)}
- Today's Leads: {summary['leads'].get('leads_today', 0)}
- By Source:    {json.dumps(summary['leads'].get('by_source', {}), indent=2)}

## Content Pipeline
- Total Runs:   {summary['content'].get('total_runs', 0)}
- Total Pieces: {summary['content'].get('total_pieces', 0)}
"""
        path = REPORTS_DIR / f"daily_report_{date.today().isoformat()}.md"
        path.write_text(report, encoding="utf-8")
        logger.info(f"Daily report saved: {path.name}")
        return report


# ─── Singleton ────────────────────────────────────────────────────────────────

_analytics: Optional[PlatformAnalytics] = None
_analytics_lock = threading.Lock()


def get_analytics() -> PlatformAnalytics:
    global _analytics
    if _analytics is None:
        with _analytics_lock:
            if _analytics is None:
                _analytics = PlatformAnalytics()
    return _analytics
