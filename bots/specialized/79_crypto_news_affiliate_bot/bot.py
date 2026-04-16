#!/usr/bin/env python3
"""
bots/specialized/79_crypto_news_affiliate_bot/bot.py
SuperAgent-created bot — Generates and disseminates crypto news with affiliate links to drive signups.
Revenue goal: $50.00
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class CryptoNewsAffiliateBotBot(BaseBot):
    """Generates and disseminates crypto news with affiliate links to drive signups."""

    def __init__(self):
        super().__init__("79_crypto_news_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto News")
        self.logger.info(f"Running {self.name}: {topic}")

        topic = "Crypto News"
        system_str = (
            "You are a revenue-focused content writer specializing in generating "
            "engaging and affiliate-rich content. Your goal is to craft content that "
            "not only informs but also naturally incorporates affiliate links to drive "
            "conversions and revenue, specifically targeting the crypto niche."
        )

        prompt = (
            f"Generate a comprehensive and engaging piece of content about {topic}. "
            "The content should be SEO-optimized and valuable for readers interested in "
            "cryptocurrency updates. Include 2-3 affiliate links naturally within the "
            "content. Make sure the content is informative and encourages readers to "
            "click on the affiliate links. Focus on recent trends, market analysis, or "
            "new developments in the crypto world. Use the following affiliate links "
            "where contextually appropriate:\n"
            "- Coinbase: https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1\n"
            "- Amazon: https://www.amazon.com/s?k=PRODUCT&tag=wheellsverse-20\n"
            "- Robinhood: https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1"
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Latest in Crypto News\n\nStay updated with the most recent trends and "
        "developments in the world of cryptocurrency. Discover insights and opportunities "
        "that could shape your investment strategy."

        footer = (
            "For those looking to dive deeper into the world of crypto investments, consider "
            "[joining Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1) "
            "for a reliable platform to buy and sell cryptocurrencies. Additionally, explore "
            "crypto-related books on [Amazon](https://www.amazon.com/s?k=crypto&tag=wheellsverse-20) "
            "to expand your knowledge. For traditional stock and crypto trading, "
            "[Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1) offers "
            "a user-friendly interface to manage your investments."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoNewsAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
