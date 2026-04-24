#!/usr/bin/env python3
"""
bots/specialized/87_crypto_investing_affiliate_bot/bot.py
SuperAgent-created bot — Automates the distribution of affiliate links in crypto investment content.
Revenue goal: Revenue goal
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class CryptoInvestingAffiliateBotBot(BaseBot):
    """Automates the distribution of affiliate links in crypto investment content."""

    def __init__(self):
        super().__init__("87_crypto_investing_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto investing")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer specializing in crypto investing. "
            "Your goal is to create engaging, informative content that naturally incorporates "
            "affiliate links to maximize click-through rates and conversions. The content should "
            "be SEO-optimized and valuable to readers interested in crypto investing."
        )

        topic = "Crypto investing"
        prompt = (
            f"Create a detailed article about {topic}. The content should be engaging and informative, "
            f"highlighting the benefits and opportunities within the crypto investment space. Naturally "
            f"embed affiliate links to Coinbase and Robinhood where appropriate, encouraging readers to "
            f"explore these platforms for their crypto trading needs. Additionally, suggest relevant products "
            f"from Amazon that could assist in crypto investing, using the Amazon Associates tag. Ensure the "
            f"content is SEO-optimized and provides real value to readers."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Exploring the World of Crypto Investing\n"
        footer = (
            "## Affiliate Links\n"
            "\n"
            "Consider starting your crypto investment journey with [Coinbase](https://app.wheellsverse.com/go/coinbase) "
            "for a user-friendly platform to buy, sell, and manage your cryptocurrencies. "
            "Additionally, [Robinhood](https://app.wheellsverse.com/go/robinhood) offers commission-free trading, "
            "making it an attractive option for new investors.\n"
            "\n"
            "For those looking to enhance their crypto knowledge, consider checking out books and resources on Amazon. "
            "Browse the latest crypto investment books [here](https://www.amazon.com/s?k=crypto+investment+books&tag=wheellsverse-20)."
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
