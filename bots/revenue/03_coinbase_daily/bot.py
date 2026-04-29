#!/usr/bin/env python3
"""
Revenue Stream #3 — Coinbase Daily Affiliate Poster
Purpose: Posts 1 crypto beginner education post daily to FB + IG with Coinbase
         affiliate link. Each signup earns up to $10. 100 signups = $1,000.
         Also promotes Robinhood and Binance affiliate links.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a crypto educator who makes complex concepts simple and exciting.
You've helped 20,000+ beginners buy their first crypto safely. You post daily educational
content that genuinely helps people understand crypto — and naturally leads them to
sign up for Coinbase, where you earn a referral commission. Your content is NOT
salesy — it's genuinely educational. The affiliate link is a natural recommendation,
not a pushy CTA. You write like a knowledgeable friend, not a crypto bro."""

DAILY_ANGLES = [
    "What is Bitcoin and why should I care in 2026?",
    "The safest way for a complete beginner to buy their first crypto",
    "Why 100 million people are using Coinbase right now",
    "3 crypto mistakes that cost beginners thousands (and how to avoid them)",
    "How to earn passive income with crypto (no trading required)",
    "Bitcoin vs Ethereum: which should you buy first?",
    "What is a crypto wallet and do you need one?",
    "How I turned $100 into $340 in 6 months with crypto (step by step)",
    "The truth about crypto taxes (what you actually need to know)",
    "DeFi for beginners: earn 10%+ on your savings legally",
    "Is it too late to buy Bitcoin? Here's the honest answer",
    "5 crypto terms every beginner MUST know",
    "How to dollar cost average into crypto (the safest strategy)",
    "Coinbase vs Binance vs Robinhood: which is best for beginners?",
    "What happens to your crypto if Coinbase shuts down?",
]


class CoinbaseDailyBot(BaseBot):

    def __init__(self):
        super().__init__("03_coinbase_daily", "revenue")
        self.coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/wheellsverse")
        self.robinhood_url = os.getenv("AFFILIATE_WEBULL_URL", "https://robinhood.com/us/en/")
        self.binance_url = os.getenv("AFFILIATE_BINANCE_URL", "https://binance.com/en/register")

    def run(self, action: str = "post", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "post")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "post": self._daily_post,
            "reel": self._reel_script,
            "story": self._story_content,
            "thread": self._edu_thread,
        }
        fn = actions.get(action, self._daily_post)
        return fn(ts, **kwargs)

    def _daily_post(self, ts: str, **kwargs) -> dict:
        day_of_year = datetime.now().timetuple().tm_yday
        angle = DAILY_ANGLES[day_of_year % len(DAILY_ANGLES)]

        # Get live crypto price for context
        price_ctx = ""
        try:
            from bots.narai.narai.bot import NarAIInternet
            prices = NarAIInternet().crypto_price(["bitcoin", "ethereum"])
            btc = prices.get("bitcoin", {})
            eth = prices.get("ethereum", {})
            price_ctx = f"(BTC is currently ${btc.get('usd', 'N/A'):,}, ETH is ${eth.get('usd', 'N/A'):,})"
        except Exception:
            pass

        prompt = f"""Create today's crypto education post for WheellsVerse.

Topic: {angle}
{f"Live data: {price_ctx}" if price_ctx else ""}

Generate:

1. FACEBOOK POST (200-250 words):
   - Hook: question or surprising stat in first line
   - Educational body: genuinely useful info about the topic
   - Natural recommendation: "I use Coinbase because it's the safest for beginners"
   - Affiliate CTA: "Get $10 free Bitcoin when you sign up → {self.coinbase_url}"
   - 3 hashtags: #Bitcoin #Crypto #CryptoForBeginners

2. INSTAGRAM CAPTION (100-120 words + 20 hashtags):
   - Bold first line (all caps or punchy)
   - 5-6 quick teaching points with emojis
   - "Sign up to Coinbase → link in bio 🔗"
   - 20 relevant crypto hashtags

Remember: Education first. Affiliate link feels like a helpful recommendation, not an ad."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"coinbase_post_{ts}.md", ext="md")

        # Auto-publish
        published = []
        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            lines = result.split("\n")
            fb_lines, ig_lines = [], []
            in_fb, in_ig = False, False
            for line in lines:
                if "FACEBOOK" in line.upper() and "POST" in line.upper():
                    in_fb, in_ig = True, False
                elif "INSTAGRAM" in line.upper():
                    in_fb, in_ig = False, True
                elif in_fb:
                    fb_lines.append(line)
                elif in_ig:
                    ig_lines.append(line)

            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
                published.append("Facebook")
            if ig.is_configured() and ig_lines:
                ig.post("\n".join(ig_lines).strip())
                published.append("Instagram")
        except Exception as e:
            self.logger.debug("Publish skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"💰 Coinbase Daily — Posted!\nTopic: {angle}\n{'✅ ' + ' + '.join(published) if published else '📁 Saved only'}")
        except Exception:
            pass

        return {"file": str(path), "action": "post", "angle": angle, "published": published}

    def _reel_script(self, ts: str, **kwargs) -> dict:
        day_of_year = datetime.now().timetuple().tm_yday
        angle = DAILY_ANGLES[(day_of_year + 3) % len(DAILY_ANGLES)]

        prompt = f"""Write a 60-second Instagram/Facebook Reel script about: {angle}

Script format (for teleprompter or reading):
[0:00-0:05] HOOK — shocking statement or question (must stop scrolling)
[0:05-0:45] CONTENT — 4-5 key points, punchy sentences, 1-2 words on screen each
[0:45-0:55] CTA — "Link in bio to get $10 free Bitcoin on Coinbase"
[0:55-1:00] OUTRO — subscribe + follow prompt

Voiceover style: conversational, fast-paced, confident
On-screen text suggestions in [BRACKETS]
Include 3 suggested background music moods"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=800)
        path = self.save_output(result, f"reel_script_{ts}.md", ext="md")
        return {"file": str(path), "action": "reel"}

    def _story_content(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create a 5-slide Instagram Story series promoting Coinbase affiliate.

Theme: "Your first $10 in crypto — step by step"

Each slide:
SLIDE 1: Hook question (big text, colorful background)
SLIDE 2: The problem (why beginners fail at crypto)
SLIDE 3: The solution (Coinbase — safest way to start)
SLIDE 4: Step by step (3 steps to buy first crypto)
SLIDE 5: CTA (swipe up / link in bio for free $10 Bitcoin via {self.coinbase_url})

For each slide: background color, main text (max 6 words), subtext (max 15 words)
Add poll/question sticker suggestion for engagement."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=800)
        path = self.save_output(result, f"story_{ts}.md", ext="md")
        return {"file": str(path), "action": "story"}

    def _edu_thread(self, ts: str, **kwargs) -> dict:
        """Educational long-form thread for Facebook group or WhatsApp."""
        day_of_year = datetime.now().timetuple().tm_yday
        angle = DAILY_ANGLES[(day_of_year + 7) % len(DAILY_ANGLES)]

        prompt = f"""Write a detailed educational post about: {angle}

For WheellsVerse Facebook Group. Long-form, genuine education:
- 400-500 words total
- 5 numbered teaching points
- Real examples with numbers
- Common misconceptions corrected
- Ends with: "Questions? Drop them below 👇"
- Soft CTA: mention Coinbase naturally in context

This should genuinely help beginners. No hype, no pressure."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(result, f"edu_thread_{ts}.md", ext="md")
        return {"file": str(path), "action": "thread"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Coinbase Daily Affiliate Bot")
    parser.add_argument("--action", default="post", choices=["post", "reel", "story", "thread"])
    args = parser.parse_args()
    bot = CoinbaseDailyBot()
    result = bot.execute(action=args.action)
    print(f"\n✅ Coinbase Daily: {result['file']}")
