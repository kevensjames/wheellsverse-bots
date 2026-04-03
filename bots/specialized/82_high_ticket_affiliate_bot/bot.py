#!/usr/bin/env python3
"""
bots/specialized/82_high_ticket_affiliate_bot/bot.py
SuperAgent-created bot — Targets high-ticket affiliate programs to maximize commissions
Revenue goal: Increase affiliate sales significantly
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot


class HighTicketAffiliateBotBot(BaseBot):
    """Targets high-ticket affiliate programs to maximize commissions"""

    def __init__(self):
        super().__init__("82_high_ticket_affiliate_bot", "specialized")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "High-ticket affiliate programs")
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a content writer focused on generating high-revenue affiliate marketing content. "
            "Your goal is to create engaging, informative, and SEO-optimized content that naturally integrates "
            "affiliate links to drive conversions and increase affiliate sales significantly. The content should "
            "appeal to readers interested in high-ticket affiliate programs and encourage them to click on the "
            "embedded affiliate links."
        )

        topic = "High-ticket affiliate programs"
        user_prompt = (
            f"Generate a detailed, engaging, and SEO-optimized article about '{topic}'. "
            "The article should highlight the benefits of high-ticket affiliate programs, "
            "provide valuable insights for potential affiliates, and naturally integrate "
            "affiliate links to Amazon, Coinbase, and Robinhood where contextually relevant. "
            "Ensure the content is informative and encourages readers to explore the affiliate links."
        )

        result = self.ai(prompt=user_prompt, system=system_str, max_tokens=2000)

        header = "# Exploring High-Ticket Affiliate Programs: Maximize Your Earnings"
        footer = (
            "## Affiliate Links\n"
            "- [Explore high-ticket products on Amazon](https://www.amazon.com/s?k=high-ticket+items&tag=wheellsverse-20)\n"
            "- [Start trading with Coinbase](https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1)\n"
            "- [Invest smartly with Robinhood](https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1)\n"
        )

        output = header + "\n\n" + result + "\n\n" + footer

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "bot": self.name}


if __name__ == "__main__":
    bot = HighTicketAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
