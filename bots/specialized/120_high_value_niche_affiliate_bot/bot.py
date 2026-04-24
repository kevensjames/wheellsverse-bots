#!/usr/bin/env python3
"""
bots/specialized/120_high_value_niche_affiliate_bot/bot.py
SuperAgent-created bot — Focuses on high-value affiliate niches such as AI tools, crypto, and stock investing to maximize revenue.
Revenue goal: Increase affiliate conversions in high-value niches
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class HighValueNicheAffiliateBotBot(BaseBot):
    """Focuses on high-value affiliate niches such as AI tools, crypto, and stock investing to maximize revenue."""

    def __init__(self):
        super().__init__("120_high_value_niche_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "High-value niches")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are an expert content writer specializing in creating high-value, "
            "SEO-optimized affiliate content. Your goal is to maximize affiliate "
            "conversions by crafting engaging and informative articles that naturally "
            "integrate affiliate links. Focus on high-value niches like AI tools, "
            "cryptocurrency, and stock investing."
        )

        topic = "High-value niches"
        prompt = (
            f"Write an engaging and informative article about {topic}. The content should "
            "highlight the benefits and opportunities within these niches, and naturally "
            "embed affiliate links to relevant products or services. Aim to optimize the "
            "content for search engines and encourage readers to click on the affiliate "
            "links. Use the following affiliate links where appropriate:\n"
            "- Amazon Associates: https://www.amazon.com/s?k=PRODUCT&tag=wheellsverse-20\n"
            "- Coinbase: https://app.wheellsverse.com/go/coinbase\n"
            "- Robinhood: https://app.wheellsverse.com/go/robinhood"
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Exploring High-Value Niches: AI, Crypto, and Stock Investing"
        footer = (
            "For those looking to delve deeper into these lucrative areas, consider exploring "
            "[AI tools on Amazon](https://www.amazon.com/s?k=AI+tools&tag=wheellsverse-20), "
            "or start your cryptocurrency journey with [Coinbase](https://app.wheellsverse.com/go/coinbase). "
            "Additionally, if stock investing piques your interest, [Robinhood](https://app.wheellsverse.com/go/robinhood) "
            "offers a user-friendly platform to begin trading."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = HighValueNicheAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
