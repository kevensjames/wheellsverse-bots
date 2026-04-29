#!/usr/bin/env python3
"""
bots/specialized/85_crypto_trends_affiliate_bot/bot.py
SuperAgent-created bot — Track cryptocurrency trends and integrate affiliate links.
Revenue goal: Generate $50/day from crypto-related affiliate programs
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class CryptoTrendsAffiliateBotBot(BaseBot):
    """Track cryptocurrency trends and integrate affiliate links."""

    def __init__(self):
        super().__init__("85_crypto_trends_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Cryptocurrency trends")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer with expertise in cryptocurrency trends. "
            "Your goal is to create engaging, SEO-optimized content that naturally integrates "
            "affiliate links to generate revenue. The content should be valuable to readers, "
            "providing insights into current cryptocurrency trends and encouraging them to "
            "click on affiliate links for further exploration."
        )

        topic = "Cryptocurrency trends"
        prompt = (
            f"Generate a detailed article on '{topic}'. The article should provide insights into "
            "current trends in the cryptocurrency market, including emerging technologies, market "
            "movements, and investment strategies. Naturally integrate 2-3 affiliate links into the "
            "content where contextually appropriate. Use the following affiliate links:\n"
            "- Coinbase: https://app.wheellsverse.com/go/coinbase\n"
            "- Robinhood: https://app.wheellsverse.com/go/webull\n"
            "Ensure the content is engaging, informative, and optimized for search engines to drive "
            "traffic and clicks."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Cryptocurrency Trends: Insights and Opportunities\n"
        footer = (
            "For those looking to dive into the world of cryptocurrency trading, platforms like "
            "[Coinbase](https://app.wheellsverse.com/go/coinbase) and "
            "[Robinhood](https://app.wheellsverse.com/go/webull) offer "
            "accessible ways to start investing. Whether you're a seasoned investor or just starting "
            "out, keeping up with the latest trends is crucial for making informed decisions."
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoTrendsAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
