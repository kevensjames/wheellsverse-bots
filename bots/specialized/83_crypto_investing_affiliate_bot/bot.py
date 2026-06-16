#!/usr/bin/env python3
"""
bots/specialized/83_crypto_investing_affiliate_bot/bot.py
SuperAgent-created bot — Generates content and strategies focused on promoting crypto investing affiliate links.
Revenue goal: Increase affiliate signups and revenue in the crypto investing niche.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


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

        prompt = (
            f"Generate a detailed, engaging article about {topic}. The content should be SEO-optimized "
            f"and include valuable insights into crypto investing. Naturally embed 2-3 affiliate links "
            f"within the content to increase reader interest and drive conversions. Focus on the benefits "
            f"and strategies of using platforms like Coinbase and Robinhood for crypto investments. "
            f"Consider mentioning related products available on Amazon that can aid in crypto investing. "
            f"Ensure the content is informative, persuasive, and encourages action."
        )

        result = self.ai(prompt, system=system_str, max_tokens=2000)

        # OLD footer linked to /go/coinbase, /go/webull (with "Robinhood" anchor),
        # OLD and Amazon ?tag=wheellsverse-20. Per affiliate_swap_pass2_2026_06_02
        # OLD all 3 destinations route to the owned digital product with UTM
        # OLD tagging by source partner key; anchor text is neutralized.
        _BOT_83 = "83_crypto_investing_affiliate_bot"
        _CAMP_83 = "affiliate_swap_pass2_2026_06_02"
        _STAN_83 = "https://stan.store/Wheellsverse"

        def _u83(content: str) -> str:
            return f"{_STAN_83}?utm_source={_BOT_83}&utm_medium=content&utm_campaign={_CAMP_83}&utm_content={content}"

        header = "# Exploring the World of Crypto Investing\n"
        # OLD: footer = (
        # OLD:     "## Start Your Crypto Journey Today!\n\n"
        # OLD:     "Sign up with [Coinbase](https://app.wheellsverse.com/go/coinbase) "
        # OLD:     "in the stock market as well, consider using [Robinhood](https://app.wheellsverse.com/go/webull) "
        # OLD:     "[Amazon](https://www.amazon.com/s?k=crypto+investing+books&tag=wheellsverse-20) to stay ahead..."
        # OLD: )
        footer = (
            "## Start Your Crypto Journey Today!\n\n"
            f"Get the [crypto starter pack]({_u83('coinbase')}) "
            "to buy, sell, and manage your portfolio with ease. For those interested "
            f"in the stock market as well, grab the [free stocks playbook]({_u83('webull')}) "
            "for a seamless investing experience. Enhance your knowledge with the "
            f"[crypto investing books pack]({_u83('amazon_crypto_books')}) to stay ahead."
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
