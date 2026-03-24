#!/usr/bin/env python3
"""ColdEmailBot — cold email sequences"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot


class ColdEmailBot(BaseBot):
    def __init__(self):
        super().__init__("32_cold_email", "sales")

    def run(self, topic: str = None, **kwargs):
        topic = topic or self.config.get("topic", "CEO of SaaS startup outreach")
        self.logger.info("Running 32_cold_email: " + str(topic))

        system = (
            "You are a world-class expert in cold email sequences. "
            "You produce comprehensive, actionable, and professional-grade outputs. "
            "Format responses with clear headers, specific examples, and step-by-step guidance."
        )

        task_title = "32_cold_email".replace("_", " ").title()

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
            "# ColdEmailBot Output\n"
            f"**Topic:** {topic}\n"
            f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            "---\n\n"
            f"{result}\n\n"
            "---\n"
            "*WheellsVerse 32_cold_email Bot*"
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output_text, f"32_cold_email_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="cold email sequences")
    parser.add_argument("--topic", type=str, default=None)
    args = parser.parse_args()
    bot = ColdEmailBot()
    result = bot.execute(topic=args.topic)
    print(f"\n Output: {result['file']}")
