#!/usr/bin/env python3
"""
bots/specialized/86_crypto_affiliate_automator/bot.py
SuperAgent-created bot — Automates crypto affiliate marketing strategies to increase sign-ups and revenue.
Revenue goal: Generate $50+ daily from crypto affiliates
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class CryptoAffiliateAutomatorBot(BaseBot):
    """Automates crypto affiliate marketing strategies to increase sign-ups and revenue."""

    def __init__(self):
        super().__init__("86_crypto_affiliate_automator", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "Crypto trends and investing")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a revenue-focused content writer specializing in crypto affiliate marketing. "
            "Your goal is to craft engaging, SEO-optimized content that naturally incorporates "
            "affiliate links to increase sign-ups and revenue. The content should appeal to readers "
            "interested in crypto trends and investing, and should subtly encourage them to click on "
            "affiliate links without being overly promotional."
        )

        topic = "Crypto trends and investing"
        prompt = (
            f"Generate a comprehensive article about {topic}. The content should be informative and "
            "engaging, providing value to readers while embedding affiliate links naturally. Aim to "
            "increase affiliate sign-ups and revenue by including relevant links to Coinbase and "
            "Robinhood where appropriate. Highlight the benefits of using these platforms for "
            "investing in cryptocurrencies. Ensure the content is SEO-optimized and encourages "
            "readers to explore further through the affiliate links."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        header = "# Exploring the Latest Crypto Trends and Investing Strategies\n"

        footer = (
            "For those ready to dive into the world of crypto investing, consider starting with "
            "[Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1) for a user-friendly "
            "experience, or explore the benefits of commission-free trading with "
            "[Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1). "
            "Stay informed and make the most out of your investments!"
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = CryptoAffiliateAutomatorBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
