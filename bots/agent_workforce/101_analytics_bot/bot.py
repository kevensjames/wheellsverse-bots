#!/usr/bin/env python3
"""
Bot #101 — Analytics Agent Bot
Category: Agent Workforce
Purpose: Generate weekly performance reports and actionable insights by
         reading operational data files and using Claude for analysis.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class AnalyticsAgentBot(BaseBot):
    """Analytics agent  weekly reports and insights powered by Claude."""

    def __init__(self):
        super().__init__("101_analytics_bot", "agent_workforce")

    # ─── Data loading helpers ───────────────────────────────────────────────

    def _load_json_safe(self, filename: str) -> dict | list | None:
        """Load a JSON file from data/ directory, returning None on failure."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            self.logger.info(f"Data file not found (skipping): {filename}")
            return None
        try:
            data = json.loads(filepath.read_text())
            self.logger.info(f"Loaded {filename}: {type(data).__name__} with {len(data) if isinstance(data, (list, dict)) else '?'} entries")
            return data
        except Exception as e:
            self.logger.warning(f"Error reading {filename}: {e}")
            return None

    def _summarize_data(self, data, label: str, max_items: int = 50) -> str:
        """Create a concise text summary of a data structure for Claude."""
        if data is None:
            return f"[{label}: No data available]"

        if isinstance(data, list):
            count = len(data)
            sample = data[-max_items:] if count > max_items else data
            return f"[{label}: {count} records, showing last {len(sample)}]\n{json.dumps(sample, indent=2, default=str)}"

        if isinstance(data, dict):
            # For dicts, show structure + sample
            keys = list(data.keys())
            summary = {k: data[k] for k in keys[:max_items]}
            return f"[{label}: dict with {len(keys)} keys]\n{json.dumps(summary, indent=2, default=str)}"

        return f"[{label}]: {str(data)[:500]}"

    def _build_data_context(self) -> str:
        """Load all available data files and build a context string."""
        sections = []

        # Bot health
        bot_health = self._load_json_safe("bot_health.json")
        sections.append(self._summarize_data(bot_health, "Bot Health"))

        # Click tracking
        clicks = self._load_json_safe("clicks.json")
        sections.append(self._summarize_data(clicks, "Click Tracking"))

        # Token usage
        token_usage = self._load_json_safe("token_usage.json")
        sections.append(self._summarize_data(token_usage, "Token Usage"))

        # Platform analytics
        platform = self._load_json_safe("platform_analytics.json")
        sections.append(self._summarize_data(platform, "Platform Analytics"))

        # Also check for any other interesting data files
        for extra in ["pm_board.json", "tool_catalog.json", "used_topics.json"]:
            extra_data = self._load_json_safe(extra)
            if extra_data:
                sections.append(self._summarize_data(extra_data, extra.replace(".json", "").replace("_", " ").title()))

        return "\n\n---\n\n".join(sections)

    # ─── Main run ───────────────────────────────────────────────────────────

    def run(self, action: str = "report", timeframe: str = "week",
            query: str = None, **kwargs):

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ts_display = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Build context from all available data
        data_context = self._build_data_context()

        # ── Report ──────────────────────────────────────────────────────────
        if action == "report":
            self.logger.info(f"Generating {timeframe} performance report")

            system = (
                "You are a data analyst and business intelligence expert. You turn "
                "raw operational data into clear, actionable reports. Use specific "
                "numbers, calculate percentages and trends. Highlight what's working, "
                "what's not, and what to do next. Format with clear sections and tables."
            )

            prompt = f"""Generate a {timeframe}ly performance report based on the following operational data.

TODAY: {datetime.now().strftime('%Y-%m-%d')}
TIMEFRAME: Last {timeframe}

DATA:
{data_context}

Generate a comprehensive report with:

## Executive Summary
[3-4 bullet points: top-level metrics and headline takeaway]

## Bot Operations
[Which bots ran, success/failure rates, any issues]

## Traffic & Clicks
[Click volume, top sources, conversion patterns]

## AI Token Usage
[Total tokens consumed, cost estimate at $0.01/1K tokens, busiest bots]

## Platform Performance
[Any platform-specific metrics available]

## Key Metrics Table
| Metric | This {timeframe} | Trend |
[Fill with actual numbers from the data]

## Recommendations
[3-5 specific, actionable recommendations based on the data]

If data for a section is unavailable, note it and suggest how to start tracking it."""

            result = self.claude(prompt, system=system, max_tokens=2500)

            output = f"""# {timeframe.title()}ly Performance Report
**Period:** Last {timeframe}
**Generated:** {ts_display}

---

{result}

---
*Generated by WheellsVerse Analytics Agent Bot*
"""
            fname = f"analytics_report_{timeframe}_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "timeframe": timeframe}

        # ── Insights ────────────────────────────────────────────────────────
        elif action == "insights":
            self.logger.info(f"Generating top insights for {timeframe}")

            system = (
                "You are a growth strategist who spots patterns in data that others miss. "
                "You provide sharp, specific insights -- not generic advice. Each insight "
                "must reference actual data points and include a concrete next step."
            )

            prompt = f"""Analyze the following operational data and provide the TOP 5 actionable insights.

TODAY: {datetime.now().strftime('%Y-%m-%d')}
TIMEFRAME: Last {timeframe}

DATA:
{data_context}

For each insight:

### Insight [N]: [Title]
**Data Point:** [The specific number or pattern you noticed]
**Why It Matters:** [Business impact in plain English]
**Action:** [Exactly what to do, by when]
**Expected Impact:** [What will change if we act on this]

Rank them by potential impact (highest first).
If data is sparse, focus on what IS available and what's missing that should be tracked."""

            result = self.claude(prompt, system=system, max_tokens=2000)

            output = f"""# Top 5 Actionable Insights
**Timeframe:** Last {timeframe}
**Generated:** {ts_display}

---

{result}

---
*Generated by WheellsVerse Analytics Agent Bot*
"""
            fname = f"analytics_insights_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "timeframe": timeframe}

        # ── Query (natural language) ────────────────────────────────────────
        elif action == "query":
            question = query or "What is the overall health of the bot ecosystem?"

            self.logger.info(f"Answering analytics query: {question[:60]}")

            system = (
                "You are a data analyst answering questions about operational data. "
                "Be precise, cite specific numbers from the data, and clearly state "
                "when you're making assumptions due to incomplete data. Keep answers "
                "concise but thorough."
            )

            prompt = f"""Answer the following question based on the available operational data.

QUESTION: {question}

AVAILABLE DATA:
{data_context}

Provide:
1. **Direct Answer** (1-3 sentences)
2. **Supporting Data** (specific numbers and context)
3. **Caveats** (any limitations in the data)
4. **Related Questions** (2-3 follow-up questions worth investigating)"""

            result = self.claude(prompt, system=system, max_tokens=1500)

            output = f"""# Analytics Query
**Question:** {question}
**Generated:** {ts_display}

---

{result}

---
*Generated by WheellsVerse Analytics Agent Bot*
"""
            fname = f"analytics_query_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "timeframe": timeframe}

        else:
            raise ValueError(f"Unknown action: {action}. Use report, insights, or query.")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analytics Agent Bot")
    parser.add_argument("--action", type=str, default="report",
                        choices=["report", "insights", "query"])
    parser.add_argument("--timeframe", type=str, default="week")
    parser.add_argument("--query", type=str, default=None)
    args = parser.parse_args()

    bot = AnalyticsAgentBot()
    result = bot.execute(action=args.action, timeframe=args.timeframe,
                         query=args.query)
    print(f"\nOutput: {result['file']}")
    print(f"Action: {result['action']}  |  Timeframe: {result['timeframe']}")
