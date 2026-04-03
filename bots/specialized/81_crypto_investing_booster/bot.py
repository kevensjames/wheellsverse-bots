#!/usr/bin/env python3
"""
bots/specialized/81_crypto_investing_booster/bot.py
SuperAgent-created bot — Generates high-engagement crypto investing content to attract potential affiliate signups.
Revenue goal: Boost affiliate signups and revenue in the crypto niche.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot


class CryptoInvestingBoosterBot(BaseBot):
    """Generates high-engagement crypto investing content to attract potential affiliate signups."""

    def __init__(self):
        super().__init__("81_crypto_investing_booster", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto Investing")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer specializing in creating high-engagement "
            "crypto investing content. Your goal is to generate valuable and SEO-optimized content "
            "that naturally incorporates affiliate links to increase signups and revenue. Focus on "
            "the crypto niche and ensure content is informative and engaging."
        )

        user_prompt = (
            "Generate a compelling piece of content about crypto investing. The content should be "
            "engaging, informative, and optimized for SEO to attract readers interested in the "
            "crypto niche. Naturally embed affiliate links to Coinbase and Robinhood where they fit "
            "contextually. Use these links: Coinbase - https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1, "
            "Robinhood - https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1. Focus on "
            "crypto investing strategies, benefits, and tips to maximize returns."
        )

        result = self.ai(user_prompt, system=system_str, max_tokens=2000)

        header = "# Boost Your Crypto Portfolio with Smart Investing Strategies"
        footer = (
            "Ready to take your crypto investing to the next level? Consider using platforms like "
            "[Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1) for secure "
            "transactions and [Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1) "
            "for commission-free trading. Start optimizing your portfolio today!"
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoInvestingBoosterBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
