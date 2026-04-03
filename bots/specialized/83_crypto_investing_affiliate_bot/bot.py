#!/usr/bin/env python3
"""
bots/specialized/83_crypto_investing_affiliate_bot/bot.py
SuperAgent-created bot — Generates content and strategies focused on promoting crypto investing affiliate links.
Revenue goal: Increase affiliate signups and revenue in the crypto investing niche.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot


class CryptoInvestingAffiliateBotBot(BaseBot):
    """Generates content and strategies focused on promoting crypto investing affiliate links."""

    def __init__(self):
        super().__init__("83_crypto_investing_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto Investing")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer specializing in generating high-quality, "
            "SEO-optimized content for affiliate marketing. Your goal is to create engaging, "
            "informative, and persuasive content that naturally incorporates affiliate links, "
            "driving reader interest and conversions in the crypto investing niche."
        )

        topic = "Crypto Investing"
        affiliate_links = {
            "Amazon": "https://www.amazon.com/s?k=PRODUCT&tag=wheellsverse-20",
            "Coinbase": "https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1",
            "Robinhood": "https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1"
        }

        prompt = (
            f"Generate a detailed, engaging article about {topic}. The content should be SEO-optimized "
            f"and include valuable insights into crypto investing. Naturally embed 2-3 affiliate links "
            f"within the content to increase reader interest and drive conversions. Focus on the benefits "
            f"and strategies of using platforms like Coinbase and Robinhood for crypto investments. "
            f"Consider mentioning related products available on Amazon that can aid in crypto investing. "
            f"Ensure the content is informative, persuasive, and encourages action."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Exploring the World of Crypto Investing\n"
        footer = (
            "## Start Your Crypto Journey Today!\n\n"
            "Sign up with [Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1) "
            "to buy, sell, and manage your cryptocurrency portfolio with ease. For those interested "
            "in the stock market as well, consider using [Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1) "
            "for a seamless investment experience. Enhance your knowledge and tools with products from "
            "[Amazon](https://www.amazon.com/s?k=crypto+investing+books&tag=wheellsverse-20) to stay ahead in the crypto world."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoInvestingAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
