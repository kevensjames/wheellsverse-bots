#!/usr/bin/env python3
"""
Bot #70 — Business Reporting Dashboard Builder
Category: Specialized
Purpose: Generate structured business performance reports (weekly/monthly/quarterly)
         with KPI analysis, trend identification, and actionable recommendations.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

REPORT_TYPES = {
    "weekly":    "Weekly operations and performance review",
    "monthly":   "Monthly business performance summary",
    "quarterly": "Quarterly strategic review and goal assessment",
    "annual":    "Annual business review and next-year planning",
    "launch":    "Product or campaign launch performance report",
    "marketing": "Marketing and content performance breakdown",
    "revenue":   "Revenue and financial performance report",
    "growth":    "Growth metrics and audience/follower report",
}

BUSINESS_STAGES = {
    "pre_revenue":   "Pre-revenue -- tracking activities and pipeline",
    "early_revenue": "Early revenue ($0-$10K MRR) -- proving the model",
    "growth":        "Growth ($10K-$100K MRR) -- scaling what works",
    "scale":         "Scale ($100K+ MRR) -- optimizing for efficiency",
}


class ReportingDashboardBot(BaseBot):

    def __init__(self):
        super().__init__("70_reporting_dashboard", "specialized")

    def run(self, report_type: str = None, business_type: str = None,
            metrics: str = None, period: str = None,
            stage: str = None, **kwargs):

        cfg = self.config
        report_type   = report_type or cfg.get("report_type", "weekly")
        business_type = business_type or cfg.get("business_type",
            "SaaS/AI automation tools -- WheellsVerse")
        metrics       = metrics or cfg.get("metrics",
            "revenue, new subscribers, content views, bot executions, email list growth, social followers")
        period        = period or cfg.get("period", "current week")
        stage         = stage or cfg.get("stage", "early_revenue")

        type_desc  = REPORT_TYPES.get(report_type, report_type)
        stage_desc = BUSINESS_STAGES.get(stage, stage)

        self.logger.info(f"Building {report_type} business report for: {business_type}")

        metric_list = [m.strip() for m in metrics.split(",")]

        # Pre-compute dynamic sections to avoid nested triple-quoted f-strings (Python 3.11)
        metric_rows = "".join(
            f"| {m.strip()} | [Previous] | [Current] | [+/-%] | [Target] | [On track/Watch/Action needed] |\n"
            for m in metric_list
        )

        growth_metrics = "".join(
            f"**{m.strip().upper()}:**\n"
            "- Current: [Value]\n"
            "- Previous period: [Value]\n"
            "- Change: [+/-X%]\n"
            "- Trend: [Growing / Stable / Declining]\n"
            "- Benchmark: [Industry average or personal target]\n"
            "- Analysis: [Why this changed - 1-2 sentences]\n"
            "- Action if below target: [Specific step to take]\n\n"
            for m in metric_list[:5]
        )

        data_sources = "".join(
            f"| {m.strip()} | [Platform/tool] | [How to export/pull] | [Automated/Manual] |\n"
            for m in metric_list
        )

        system = (
            "You are a business analyst and performance consultant who has built reporting "
            "systems for startups and fast-growing businesses. You know that most business "
            "reports are useless -- they show data without insight. Great reports answer: "
            "'What happened, why it happened, and what to do about it.' "
            "You design reports with clear traffic-light signals (green/yellow/red), "
            "trend indicators (up/down/stable), and always end with 3 concrete next actions. "
            "You know that the best metrics are leading indicators -- they predict future "
            "performance, not just report the past."
        )

        prompt = f"""Build a complete {report_type} business report template and framework for:

BUSINESS: {business_type}
REPORT TYPE: {report_type} -- {type_desc}
PERIOD: {period}
BUSINESS STAGE: {stage} -- {stage_desc}
METRICS TO TRACK: {metrics}

---

## REPORT TEMPLATE: {report_type.upper()} PERFORMANCE REPORT

---

**{business_type}**
**{report_type.capitalize()} Report: {period}**
**Date Generated:** [Date]
**Prepared by:** [Name]

---

## EXECUTIVE SUMMARY (2-minute read)

### Wins This {report_type.capitalize()}:
1. [Win 1 -- specific metric that improved]
2. [Win 2]
3. [Win 3]

### Concerns:
1. [Concern 1 -- specific metric or issue]
2. [Concern 2]

### Top 3 Actions for Next {report_type.capitalize()}:
1. [Action 1 -- specific and assignable]
2. [Action 2]
3. [Action 3]

---

## KEY METRICS SCORECARD

| Metric | Last {report_type.capitalize()} | This {report_type.capitalize()} | Change | Target | Status |
{metric_rows}
**Traffic light key:** On track / Watch / Action needed

---

## DEEP DIVE ANALYSIS

### Revenue & Financial

**Revenue breakdown:**
| Source | {period} | vs. Prior Period | % of Total |
| [Revenue source 1] | $[X] | +/-[Y]% | [Z]% |
[Continue for all revenue sources]

**MRR/ARR tracking:**
- Current MRR: $[X]
- MRR Growth: [+/-X%]
- Annualized: $[Y]
- Runway (if applicable): [X months]

---

### Growth Metrics

{growth_metrics}

---

### Content & Marketing Performance

| Platform | Followers | Gained | Posts Published | Avg Engagement | Top Post |
[Row for each active platform]

**Best performing content:**
- Format: [What type performed best]
- Topic: [What subject got most engagement]
- Insight: [What this tells us about the audience]

**What to double down on next {report_type}:**
[Based on this data, the top 2 content investments]

---

## TREND ANALYSIS

### 4-{report_type.capitalize()} Rolling Average

| Metric | {report_type.capitalize()} -3 | {report_type.capitalize()} -2 | {report_type.capitalize()} -1 | This {report_type.capitalize()} | Trend |
[Track key metrics over 4 periods]

**Key trend insights:**
1. [Trend 1 -- what the data shows + implication]
2. [Trend 2]
3. [Trend 3]

---

## GOAL TRACKING

| Goal | Target | Current | % Complete | On Track? | Days Remaining |
[Track active goals against targets]

**Goal health assessment:**
[Which goals are at risk? What's needed to get back on track?]

---

## NEXT {report_type.upper()} PRIORITIES

### Must Do (High Impact / Urgent)
1. [Specific task with owner and deadline]
2. [Specific task]
3. [Specific task]

### Should Do (High Impact / Not Urgent)
1. [Task]
2. [Task]

### Watch (Low Impact / Consider Dropping)
1. [Activity to evaluate for elimination]

---

## REPORTING SETUP GUIDE

### How to populate this report automatically:

**Data sources to connect:**
| Metric | Source | How to Pull | Frequency |
{data_sources}
**Automation tools:**
- Zapier/Make: [Automate data collection from key sources]
- Google Sheets: [Build live dashboard from API data]
- Notion: [Team-friendly reporting template]
- Data Studio/Looker: [Visual dashboard for stakeholders]

**Time to complete this report:** [Target: under 30 minutes with proper automation]

---

## REPORT DISTRIBUTION

**Internal:** [Who gets this report and when]
**Format:** [Slack message summary + full report link]
**Archiving:** [Where to store reports for trend analysis]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")

        output = f"""# {report_type.capitalize()} Business Report: {business_type[:40]}
**Period:** {period}
**Stage:** {stage}
**Metrics:** {metrics}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Reporting Dashboard Bot*
"""
        path = self.save_output(output, f"report_{report_type}_{ts}.md", ext="md")
        self.logger.info(f"Business report saved -> {path}")
        return {"file": str(path), "report_type": report_type, "period": period}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Business Reporting Dashboard Builder")
    parser.add_argument("--type",     type=str, default="weekly",
                        choices=list(REPORT_TYPES.keys()))
    parser.add_argument("--business", type=str, default=None)
    parser.add_argument("--metrics",  type=str, default=None,
                        help="Comma-separated list of metrics to include")
    parser.add_argument("--period",   type=str, default="current week")
    parser.add_argument("--stage",    type=str, default="early_revenue",
                        choices=list(BUSINESS_STAGES.keys()))
    args = parser.parse_args()
    bot = ReportingDashboardBot()
    result = bot.execute(report_type=args.type, business_type=args.business,
                         metrics=args.metrics, period=args.period,
                         stage=args.stage)
    print(f"\n✅ Business Report: {result['file']}")
