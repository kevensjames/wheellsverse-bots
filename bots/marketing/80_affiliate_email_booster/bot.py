#!/usr/bin/env python3
"""
bots/marketing/80_affiliate_email_booster/bot.py
SuperAgent-created bot — Automates and optimizes email campaigns specifically for driving affiliate sales.
Revenue goal: Generate $50+ in affiliate revenue per day
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class AffiliateEmailBoosterBot(BaseBot):
    """Automates and optimizes email campaigns specifically for driving affiliate sales."""

    def __init__(self):
        super().__init__("80_affiliate_email_booster", "marketing")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "High-converting email strategies")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer skilled in creating compelling, "
            "affiliate-rich content for email campaigns. Your goal is to generate content "
            "that drives affiliate sales and meets a revenue target of $50+ per day. "
            "Focus on high-converting email strategies and naturally incorporate affiliate links."
        )

        topic = "High-converting email strategies"
        prompt = (
            f"Generate a detailed and engaging piece of content about {topic}. "
            "Include actionable tips and insights that are valuable to readers. "
            "The content should be SEO-optimized and designed to encourage clicks on affiliate links. "
            "Naturally embed the following affiliate links where contextually appropriate:\n"
            "- Amazon Associates: https://www.amazon.com/s?k=PRODUCT&tag=wheellsverse-20\n"
            "- Coinbase: https://app.wheellsverse.com/go/coinbase\n"
            "- Robinhood: https://app.wheellsverse.com/go/robinhood\n"
            "Ensure the content is tailored to drive affiliate revenue and appeal to readers interested in affiliate marketing."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# High-Converting Email Strategies to Boost Your Affiliate Revenue"
        footer = (
            "Explore more ways to enhance your email campaigns with these tools: "
            "[Amazon Associates](https://www.amazon.com/s?k=PRODUCT&tag=wheellsverse-20), "
            "[Coinbase](https://app.wheellsverse.com/go/coinbase), "
            "and [Robinhood](https://app.wheellsverse.com/go/robinhood)."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = AffiliateEmailBoosterBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
