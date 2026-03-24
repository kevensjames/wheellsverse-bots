#!/usr/bin/env python3
"""Bot #10 — Analytics Reporter"""
import sys, json
from pathlib import Path
from datetime import datetime, timedelta
import random
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class AnalyticsReporterBot(BaseBot):
    def __init__(self):
        super().__init__("10_analytics_reporter", "marketing")

    def run(self, data_file: str = None, period: str = "monthly",
            channels: list = None, **kwargs):
        cfg = self.config
        period   = period or cfg.get("period", "monthly")
        channels = channels or cfg.get("channels", ["email","social","organic","paid"])

        # Load or simulate analytics data
        if data_file and Path(data_file).exists():
            with open(data_file) as f:
                data = json.load(f)
        else:
            # Simulate realistic analytics
            data = self._simulate_analytics(channels, period)

        self.logger.info(f"Generating {period} analytics report")

        system = "You are a data analyst and marketing strategist who turns raw metrics into actionable insights and clear recommendations."

        data_str = json.dumps(data, indent=2)
        prompt = f"""Analyze this marketing analytics data and create a comprehensive report:

PERIOD: {period}
DATA:
{data_str}

Create a PROFESSIONAL ANALYTICS REPORT with:

## EXECUTIVE SUMMARY (3-5 sentences, key highlights)

## 📊 PERFORMANCE OVERVIEW TABLE
| Metric | This Period | Last Period | Change | Goal | Status |

## 🏆 TOP PERFORMERS
What's working best and why

## ⚠️ UNDERPERFORMERS
What needs attention and specific recommendations

## 📈 TREND ANALYSIS
Identify patterns, seasonal trends, anomalies

## 💡 INSIGHTS & RECOMMENDATIONS (Top 5)
Ranked by potential impact, with specific action items

## 🎯 NEXT PERIOD GOALS
Set SMART goals based on current performance

## 🔧 OPTIMIZATION OPPORTUNITIES
Specific A/B tests or changes to implement

Format with clear headers, emoji indicators, and data tables."""

        report = self.ai(prompt, system=system, max_tokens=2500)

        out = f"# Marketing Analytics Report\n**Period:** {period}\n**Generated:** {datetime.now():%Y-%m-%d %H:%M}\n\n---\n\n{report}\n\n---\n**Raw Data:**\n```json\n{data_str}\n```\n\n*WheellsVerse Analytics Bot*"
        ts = datetime.now().strftime("%Y%m%d")
        path = self.save_output(out, f"analytics_{period}_{ts}.md", ext="md")
        self.save_json(data, f"analytics_data_{period}_{ts}.json")
        return {"file": str(path), "period": period}

    def _simulate_analytics(self, channels, period):
        metrics = {}
        for ch in channels:
            base = random.randint(500, 5000)
            metrics[ch] = {
                "sessions": base + random.randint(-100, 500),
                "conversions": int(base * random.uniform(0.01, 0.08)),
                "revenue": round(base * random.uniform(2, 15), 2),
                "ctr": round(random.uniform(1.5, 8.5), 2),
                "cpc": round(random.uniform(0.5, 5.0), 2),
                "roas": round(random.uniform(1.5, 6.0), 2)
            }
        return {"period": period, "channels": metrics,
                "total_revenue": sum(m["revenue"] for m in metrics.values()),
                "generated": datetime.now().isoformat()}

if __name__ == "__main__":
    bot = AnalyticsReporterBot()
    print(bot.execute())
