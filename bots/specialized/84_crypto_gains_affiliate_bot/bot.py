#!/usr/bin/env python3
"""
bots/specialized/84_crypto_gains_affiliate_bot/bot.py
SuperAgent-created bot — Leverages crypto investment strategies to promote affiliate links.
Revenue goal: Generate $50 daily from crypto-focused affiliates.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class CryptoGainsAffiliateBotBot(BaseBot):
    """Leverages crypto investment strategies to promote affiliate links."""

    def __init__(self):
        super().__init__("84_crypto_gains_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto investment tips")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are an expert content writer focused on generating revenue "
            "through affiliate marketing in the cryptocurrency niche. Your goal "
            "is to create engaging and informative content that naturally incorporates "
            "affiliate links to drive clicks and conversions. The content should be "
            "SEO-optimized and provide value to readers interested in crypto investment tips."
        )

        topic = "Crypto investment tips"

        prompt = (
            "Generate a detailed and engaging article about crypto investment tips. "
            "Include practical advice and strategies for investing in cryptocurrencies. "
            "Naturally incorporate the following affiliate links where contextually appropriate: "
            "1. Coinbase: https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1 "
            "2. Robinhood: https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1 "
            "Ensure the content is valuable, SEO-optimized, and encourages readers to click the links."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Maximize Your Crypto Gains with Expert Investment Tips"
        footer = (
            "For more insights into crypto investments, consider starting your journey "
            "with trusted platforms like [Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1) "
            "and [Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1). "
            "These platforms offer user-friendly interfaces and valuable resources for both "
            "beginners and seasoned investors."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoGainsAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
