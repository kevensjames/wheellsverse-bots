#!/usr/bin/env python3
"""
core/intelligence.py
─────────────────────────────────────────────────────────────────────────────
Self-Improving Intelligence System

Tracks performance of every content piece, pipeline run, and decision.
Uses historical data to score topics, adjust strategies, and improve
the Decision Engine's choices over time.

Storage: JSON (data/intelligence.json)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

INTEL_FILE     = DATA_DIR / "intelligence.json"
STRATEGY_FILE  = DATA_DIR / "strategy.json"

logger = logging.getLogger("intelligence")


# ─── Performance Record ───────────────────────────────────────────────────────

class ContentRecord:
    """Tracks a single piece of content's lifecycle."""

    def __init__(self, content_id: str, topic: str, content_type: str = "blog"):
        self.content_id   = content_id
        self.topic        = topic
        self.content_type = content_type
        self.created_at   = datetime.now().isoformat()
        self.published_to: List[str] = []
        self.word_count:   int  = 0
        self.published_at: Optional[str] = None
        self.engagement:   Dict[str, int] = {
            "views": 0, "clicks": 0, "shares": 0, "comments": 0,
        }
        self.revenue_signals: Dict[str, float] = {
            "affiliate_clicks": 0, "leads": 0, "estimated_value": 0,
        }
        self.performance_score: float = 0.0

    def update_engagement(self, views: int = 0, clicks: int = 0,
                          shares: int = 0, comments: int = 0):
        self.engagement["views"]    += views
        self.engagement["clicks"]   += clicks
        self.engagement["shares"]   += shares
        self.engagement["comments"] += comments
        self._recalc_score()

    def _recalc_score(self):
        e = self.engagement
        # Weighted engagement score (0-100)
        raw = (
            e["views"]    * 0.1 +
            e["clicks"]   * 1.5 +
            e["shares"]   * 3.0 +
            e["comments"] * 2.0
        )
        self.performance_score = min(100, raw)

    def to_dict(self) -> Dict:
        return {
            "content_id":     self.content_id,
            "topic":          self.topic,
            "content_type":   self.content_type,
            "created_at":     self.created_at,
            "published_to":   self.published_to,
            "word_count":     self.word_count,
            "published_at":   self.published_at,
            "engagement":     self.engagement,
            "revenue_signals": self.revenue_signals,
            "performance_score": self.performance_score,
        }

    @staticmethod
    def from_dict(d: Dict) -> "ContentRecord":
        rec = ContentRecord(d["content_id"], d["topic"], d.get("content_type","blog"))
        rec.created_at      = d.get("created_at", rec.created_at)
        rec.published_to    = d.get("published_to", [])
        rec.word_count      = d.get("word_count", 0)
        rec.published_at    = d.get("published_at")
        rec.engagement      = d.get("engagement", rec.engagement)
        rec.revenue_signals = d.get("revenue_signals", rec.revenue_signals)
        rec.performance_score = d.get("performance_score", 0.0)
        return rec


# ─── Strategy Advisor ─────────────────────────────────────────────────────────

class StrategyAdvisor:
    """
    Analyzes historical data to recommend:
    - Which topics to prioritize
    - Which content types perform best
    - Which pipelines to run more/less often
    - Optimal posting times
    """

    def __init__(self, records: List[ContentRecord]):
        self.records = records

    def get_top_topics(self, limit: int = 10) -> List[Dict]:
        """Return topics ranked by average performance score."""
        topic_scores: Dict[str, List[float]] = defaultdict(list)
        for rec in self.records:
            if rec.performance_score > 0:
                key = rec.topic.lower()[:40]
                topic_scores[key].append(rec.performance_score)

        ranked = [
            {
                "topic":     topic,
                "avg_score": round(sum(scores) / len(scores), 2),
                "count":     len(scores),
            }
            for topic, scores in topic_scores.items()
        ]
        return sorted(ranked, key=lambda x: x["avg_score"], reverse=True)[:limit]

    def get_content_type_performance(self) -> Dict[str, Dict]:
        """Compare performance across blog, twitter, linkedin, etc."""
        by_type: Dict[str, List[float]] = defaultdict(list)
        for rec in self.records:
            by_type[rec.content_type].append(rec.performance_score)
        return {
            ctype: {
                "avg_score": round(sum(scores)/len(scores), 2) if scores else 0,
                "total_pieces": len(scores),
                "total_engagement": sum(scores),
            }
            for ctype, scores in by_type.items()
        }

    def get_strategy_recommendation(self) -> Dict:
        """
        Generate adaptive strategy recommendations.
        """
        if len(self.records) < 3:
            return {
                "status": "insufficient_data",
                "message": "Need at least 3 content pieces to generate recommendations.",
                "recommendations": ["Create more content to build baseline data"],
            }

        top_topics     = self.get_top_topics(5)
        type_perf      = self.get_content_type_performance()
        recent_records = sorted(self.records, key=lambda r: r.created_at, reverse=True)[:10]
        recent_scores  = [r.performance_score for r in recent_records]
        avg_recent     = sum(recent_scores) / len(recent_scores) if recent_scores else 0

        recommendations = []
        strategy_adjustments = {}

        # Determine if performance is trending up/down
        if len(recent_scores) >= 4:
            first_half  = sum(recent_scores[len(recent_scores)//2:]) / max(1, len(recent_scores)//2)
            second_half = sum(recent_scores[:len(recent_scores)//2]) / max(1, len(recent_scores)//2)
            trend = "improving" if second_half > first_half else "declining"
        else:
            trend = "neutral"

        # Topic recommendations
        if top_topics:
            best = top_topics[0]
            recommendations.append(
                f"Prioritize topics similar to '{best['topic'][:40]}' "
                f"(avg score: {best['avg_score']})"
            )
            strategy_adjustments["prioritize_topic"] = best["topic"]

        # Content type recommendations
        if type_perf:
            best_type = max(type_perf.items(), key=lambda x: x[1]["avg_score"])
            recommendations.append(
                f"Focus more on {best_type[0]} content "
                f"(best performer: {best_type[1]['avg_score']} avg score)"
            )
            strategy_adjustments["best_content_type"] = best_type[0]

        # Performance trend
        if trend == "declining" and avg_recent < 20:
            recommendations.append(
                "Performance is declining — consider switching topic categories "
                "or increasing content length"
            )
            strategy_adjustments["action"] = "pivot_strategy"
        elif trend == "improving":
            recommendations.append(
                "Performance is improving — maintain current strategy and increase frequency"
            )
            strategy_adjustments["action"] = "scale_current"
        else:
            recommendations.append(
                "Performance is stable — test new topic categories for growth"
            )
            strategy_adjustments["action"] = "test_new_topics"

        return {
            "status":          "ready",
            "avg_recent_score": round(avg_recent, 2),
            "trend":           trend,
            "top_topics":      top_topics[:3],
            "type_performance": type_perf,
            "recommendations": recommendations,
            "strategy_adjustments": strategy_adjustments,
            "generated_at":    datetime.now().isoformat(),
        }


# ─── Intelligence System ──────────────────────────────────────────────────────

class IntelligenceSystem:
    """
    Central learning system that tracks all content performance
    and provides adaptive recommendations to the Decision Engine.
    """

    MAX_RECORDS = 2000

    def __init__(self):
        self._records: Dict[str, ContentRecord] = {}
        self._pipeline_stats: Dict[str, Dict]   = defaultdict(lambda: {
            "runs": 0, "successes": 0, "failures": 0,
            "avg_duration": 0.0, "last_run": None,
        })
        self._topic_scores: Dict[str, float]    = {}
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if INTEL_FILE.exists():
            try:
                data = json.loads(INTEL_FILE.read_text(encoding="utf-8"))
                for rec_data in data.get("records", []):
                    rec = ContentRecord.from_dict(rec_data)
                    self._records[rec.content_id] = rec
                self._pipeline_stats = defaultdict(
                    lambda: {"runs":0,"successes":0,"failures":0,"avg_duration":0.0,"last_run":None},
                    data.get("pipeline_stats", {})
                )
                self._topic_scores = data.get("topic_scores", {})
                logger.info(f"Intelligence loaded: {len(self._records)} records")
            except Exception as e:
                logger.warning(f"Could not load intelligence data: {e}")

    def _save(self):
        try:
            records_list = [r.to_dict() for r in list(self._records.values())[-self.MAX_RECORDS:]]
            data = {
                "records":        records_list,
                "pipeline_stats": dict(self._pipeline_stats),
                "topic_scores":   self._topic_scores,
                "saved_at":       datetime.now().isoformat(),
                "total_records":  len(records_list),
            }
            INTEL_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Could not save intelligence data: {e}")

    # ── Content Tracking ──────────────────────────────────────────────────────

    def record_content_created(self, topic: str, piece: Dict) -> ContentRecord:
        """Call after content_pipeline generates a piece."""
        with self._lock:
            content_id = f"c_{int(time.time())}_{len(self._records)}"
            rec = ContentRecord(content_id, topic, "blog")
            rec.word_count  = piece.get("blog", {}).get("word_count", 0)
            self._records[content_id] = rec
            # Bump topic creation count
            key = topic.lower()[:40]
            self._topic_scores.setdefault(key, 0.0)
            self._save()
            logger.info(f"Content recorded: {content_id} — {topic[:40]}")
            return rec

    def record_content_published(
        self, content_id: str, platforms: List[str]
    ) -> Optional[ContentRecord]:
        with self._lock:
            rec = self._records.get(content_id)
            if rec:
                rec.published_to   = platforms
                rec.published_at   = datetime.now().isoformat()
                self._save()
            return rec

    def record_engagement(
        self, content_id: str,
        views: int = 0, clicks: int = 0, shares: int = 0, comments: int = 0,
    ) -> Optional[ContentRecord]:
        with self._lock:
            rec = self._records.get(content_id)
            if rec:
                rec.update_engagement(views, clicks, shares, comments)
                # Update topic score based on engagement
                key = rec.topic.lower()[:40]
                self._topic_scores[key] = max(
                    self._topic_scores.get(key, 0),
                    rec.performance_score,
                )
                self._save()
            return rec

    # ── Pipeline Tracking ────────────────────────────────────────────────────

    def record_pipeline_run(
        self, pipeline_name: str, success: bool, duration_s: float = 0
    ):
        with self._lock:
            stats = self._pipeline_stats[pipeline_name]
            stats["runs"] += 1
            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1
            # Rolling average duration
            if duration_s > 0:
                prev = stats.get("avg_duration", 0) or 0
                n    = stats["runs"]
                stats["avg_duration"] = round((prev * (n-1) + duration_s) / n, 2)
            stats["last_run"] = datetime.now().isoformat()
            self._save()

    # ── Scoring + Recommendations ─────────────────────────────────────────────

    def get_topic_scores(self) -> Dict[str, float]:
        """Return topic → performance score mapping."""
        return dict(self._topic_scores)

    def score_topic(self, topic: str) -> float:
        """Get the historical performance score for a topic."""
        key = topic.lower()[:40]
        return self._topic_scores.get(key, 0.0)

    def get_strategy(self) -> Dict:
        """Get adaptive strategy recommendations."""
        advisor = StrategyAdvisor(list(self._records.values()))
        return advisor.get_strategy_recommendation()

    def get_pipeline_performance(self) -> Dict[str, Dict]:
        """Return pipeline success rates and stats."""
        result = {}
        for name, stats in self._pipeline_stats.items():
            runs = stats.get("runs", 0)
            result[name] = {
                **stats,
                "success_rate": round(stats.get("successes",0) / max(runs,1) * 100, 1),
            }
        return result

    def get_summary(self) -> Dict:
        """High-level system intelligence summary."""
        records = list(self._records.values())
        scores  = [r.performance_score for r in records if r.performance_score > 0]
        return {
            "total_content_pieces": len(records),
            "published_pieces":     sum(1 for r in records if r.published_at),
            "avg_performance_score": round(sum(scores)/len(scores), 2) if scores else 0,
            "top_topics":           StrategyAdvisor(records).get_top_topics(3),
            "pipeline_stats":       self.get_pipeline_performance(),
            "total_topic_scores":   len(self._topic_scores),
            "last_updated":         datetime.now().isoformat(),
        }

    def generate_improvement_report(self) -> str:
        """Generate a text report with system insights."""
        summary  = self.get_summary()
        strategy = self.get_strategy()

        report = f"""# WheellsVerse Intelligence Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Performance Overview
- Total content pieces: {summary['total_content_pieces']}
- Published pieces: {summary['published_pieces']}
- Average performance score: {summary['avg_performance_score']}/100

## Top Performing Topics
{chr(10).join(f"  {i+1}. {t['topic']} (score: {t['avg_score']}, {t['count']} pieces)"
              for i, t in enumerate(summary.get('top_topics', [])))}

## Pipeline Performance
{chr(10).join(f"  • {name}: {stats['runs']} runs, {stats['success_rate']}% success"
              for name, stats in summary.get('pipeline_stats', {}).items())}

## Strategy Recommendations
Status: {strategy.get('status', 'unknown')}
Trend: {strategy.get('trend', 'neutral')}

{chr(10).join(f"  → {r}" for r in strategy.get('recommendations', []))}

## Strategy Adjustments
{json.dumps(strategy.get('strategy_adjustments', {}), indent=2)}
"""
        # Save report
        report_path = ROOT / "outputs" / "reports" / f"intelligence_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        return report

    def get_all_records(self, limit: int = 50) -> List[Dict]:
        records = sorted(self._records.values(),
                        key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in records[:limit]]

    # ── Conversion Tracking ───────────────────────────────────────────────────

    def record_lead(self, topic: str = "", source: str = "landing_page"):
        """Record that a lead was captured — ties lead count to topic performance."""
        with self._lock:
            key = topic.lower()[:40] if topic else "_general"
            # Boost the topic score when it generates a lead (high-value signal)
            current = self._topic_scores.get(key, 0.0)
            self._topic_scores[key] = min(100.0, current + 5.0)
            self._save()
            logger.info(f"Lead recorded for topic: {key[:40]} (source: {source})")

    def get_conversion_stats(self) -> Dict:
        """Return conversion-related metrics from intelligence data."""
        records = list(self._records.values())
        total_leads = sum(r.revenue_signals.get("leads", 0) for r in records)
        total_views = sum(r.engagement.get("views", 0) for r in records)
        total_clicks = sum(r.engagement.get("clicks", 0) for r in records)
        conversion_rate = round(total_leads / max(total_views, 1) * 100, 3)
        click_rate      = round(total_clicks / max(total_views, 1) * 100, 2)

        # Top converting topics
        topic_leads: Dict[str, float] = defaultdict(float)
        for rec in records:
            topic_leads[rec.topic[:40]] += rec.revenue_signals.get("leads", 0)
        top_converting = sorted(
            [{"topic": k, "leads": v} for k, v in topic_leads.items() if v > 0],
            key=lambda x: x["leads"], reverse=True
        )[:5]

        return {
            "total_leads":       total_leads,
            "total_views":       total_views,
            "total_clicks":      total_clicks,
            "conversion_rate":   conversion_rate,
            "click_rate":        click_rate,
            "top_converting_topics": top_converting,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_intel: Optional[IntelligenceSystem] = None
_intel_lock = threading.Lock()


def get_intelligence() -> IntelligenceSystem:
    global _intel
    if _intel is None:
        with _intel_lock:
            if _intel is None:
                _intel = IntelligenceSystem()
    return _intel
