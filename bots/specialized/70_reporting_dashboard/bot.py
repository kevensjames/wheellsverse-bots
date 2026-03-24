#!/usr/bin/env python3
"""ReportingDashboardBot — weekly and monthly business reports"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot


class ReportingDashboardBot(BaseBot):
    def __init__(self):
        super().__init__("70_reporting_dashboard", "specialized")

    def run(self, topic: str = None, **kwargs):
        topic = topic or self.config.get("topic", "Weekly performance report")
        self.logger.info("Running 70_reporting_dashboard: " + str(topic))

        system = (
            "You are a world-class expert in weekly and monthly business reports. "
            "You produce comprehensive, actionable, and professional-grade outputs. "
            "Format responses with clear headers, specific examples, and step-by-step guidance."
        )

        task_title = "70_reporting_dashboard".replace("_", " ").title()

        prompt = f"""Generate a professional, detailed output for this request:

TASK: {task_title}
INPUT/TOPIC: {topic}

Business Context:
- Brand: WheellsVerse / J.K. Blaze
- Owner: Jhon Kevens D Wheeler
- Niche: AI automation and entrepreneurship
- Goal: Build automated income streams and a scalable business

Provide:
1. Comprehensive main output (the primary deliverable)
2. Key insights and recommendations
3. Step-by-step implementation guide
4. Success metrics to track
5. Common mistakes to avoid

Be specific, professional, and immediately actionable."""

        result = self.ai(prompt, system=system, max_tokens=2500)

        from datetime import datetime
        output_text = (
            "# ReportingDashboardBot Output\n"
            f"**Topic:** {topic}\n"
            f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            "---\n\n"
            f"{result}\n\n"
            "---\n"
            "*WheellsVerse 70_reporting_dashboard Bot*"
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output_text, f"70_reporting_dashboard_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="weekly and monthly business reports")
    parser.add_argument("--topic", type=str, default=None)
    args = parser.parse_args()
    bot = ReportingDashboardBot()
    result = bot.execute(topic=args.topic)
    print(f"\n Output: {result['file']}")
