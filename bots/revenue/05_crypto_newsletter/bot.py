#!/usr/bin/env python3
"""
Revenue Stream #5 — Paid Crypto Signals Newsletter ($9/month)
Purpose: Autonomous paid newsletter with weekly crypto signals, market analysis,
         and DeFi opportunities. Sent via ConvertKit. 200 subs = $1,800/month recurring.
         Auto-generates and sends every week.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a professional crypto analyst and newsletter writer with a track record
of helping subscribers make money in both bull and bear markets. Your newsletter is
the one paid subscription people keep even when canceling everything else — because
it consistently delivers actionable signals and educational content that others
charge $50-$100/month for. You write with authority and specificity. Your market
reads are accurate and your educational content is clear. You always hedge properly
(not financial advice) but you give real opinions, not empty disclaimers."""

NEWSLETTER_NAME = "WheellsVerse Crypto Insider"
PRICE = "$9/month"


class CryptoNewsletterBot(BaseBot):

    def __init__(self):
        super().__init__("05_crypto_newsletter", "revenue")
        self.subscribe_url = os.getenv("NEWSLETTER_SUBSCRIBE_URL",
                                       "https://wheellsverse.ck.page/crypto-insider")
        self.coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/wheellsverse")

    def run(self, action: str = "send", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "send")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "send": self._weekly_issue,
            "welcome": self._welcome_email,
            "promote": self._promote_newsletter,
            "preview": self._free_preview,
            "sequence": self._drip_sequence,
        }
        fn = actions.get(action, self._weekly_issue)
        return fn(ts, **kwargs)

    def _get_market_data(self) -> dict:
        try:
            from bots.narai.narai.bot import NarAIInternet
            i = NarAIInternet()
            prices = i.crypto_price(["bitcoin", "ethereum", "solana"])
            news = i.news("crypto bitcoin market 2026", num=5)
            trending = i.trending()
            return {"prices": prices, "news": news, "trending": trending}
        except Exception:
            return {}

    def _weekly_issue(self, ts: str, **kwargs) -> dict:
        data = self._get_market_data()
        week = datetime.now().strftime("Week of %B %d, %Y")

        prices = data.get("prices", {})
        btc = prices.get("bitcoin", {})
        eth = prices.get("ethereum", {})
        sol = prices.get("solana", {})
        news = data.get("news", [])
        trending = data.get("trending", ["Bitcoin", "Ethereum", "Solana"])

        price_ctx = f"""
BTC: ${btc.get('usd', 'N/A')} ({btc.get('usd_24h_change', 0):.1f}% 24h)
ETH: ${eth.get('usd', 'N/A')} ({eth.get('usd_24h_change', 0):.1f}% 24h)
SOL: ${sol.get('usd', 'N/A')} ({sol.get('usd_24h_change', 0):.1f}% 24h)
Trending: {', '.join(trending[:5])}"""

        news_ctx = "\n".join(f"- {n.get('title', '')}" for n in news[:5]) or "Market data unavailable"

        prompt = f"""Write Issue #{datetime.now().isocalendar()[1]} of {NEWSLETTER_NAME}.

{week}
Subscription: {PRICE}

Live market data:
{price_ctx}

This week's news:
{news_ctx}

Newsletter structure (600-700 words):

SUBJECT LINE: [Compelling, specific, 7 words max — A/B test 3 options]

---
{NEWSLETTER_NAME} | {week}
---

1. MARKET SNAPSHOT (80 words)
   - One-sentence market mood
   - BTC/ETH reading
   - One number that matters this week

2. SIGNAL OF THE WEEK (150 words)
   - One specific coin/trade idea (educational, not financial advice)
   - Entry context, key levels to watch
   - Bull case + bear case in 2 sentences each
   - Risk rating: Conservative / Moderate / Aggressive

3. DeFi YIELD SPOTLIGHT (100 words)
   - One DeFi opportunity with real APY
   - Protocol name, risk level, minimum entry
   - How to access it (simple steps)

4. CHART TO WATCH (80 words)
   - One chart pattern / indicator to monitor
   - What it means if it breaks up vs down

5. EDUCATIONAL CORNER (150 words)
   - Teach one concept that helps subscribers understand this week's moves

6. SUBSCRIBER ONLY TIP (50 words)
   - One exclusive insight/tool/resource not in the free version

7. AFFILIATE SECTION (natural)
   - "Get $10 free on Coinbase → {self.coinbase_url}"

FOOTER: "Not financial advice. Always DYOR. {NEWSLETTER_NAME}"

Make it worth every cent of {PRICE}."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(
            f"# {NEWSLETTER_NAME} — {week}\n\n{result}",
            f"newsletter_{ts}.md", ext="md")

        # Send via ConvertKit
        try:
            from core.convertkit import get_convertkit
            ck = get_convertkit()
            if ck.is_connected():
                subject = f"📊 {NEWSLETTER_NAME} — {week}"
                ck.create_broadcast(subject=subject, content=result)
                self.logger.info("Newsletter broadcast created in ConvertKit")
        except Exception as e:
            self.logger.debug("ConvertKit skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"📬 Crypto Newsletter — {week} sent!\n{price_ctx}\n💰 {PRICE}/subscriber")
        except Exception:
            pass

        return {"file": str(path), "action": "send"}

    def _welcome_email(self, ts: str, **kwargs) -> dict:
        prompt = f"""Write the welcome email for new {NEWSLETTER_NAME} subscribers.

Subscription: {PRICE}/month

Subject: Welcome to {NEWSLETTER_NAME} 🎉 — Your first signal is inside

Email body (300 words):
- Warm welcome (they made a great decision)
- What they'll receive every week
- Sneak peek: 1 free crypto tip to deliver immediate value
- How to whitelist the email
- Link to subscriber-only resource page
- Quick intro to the brand (WheellsVerse / J.K. Blaze)
- Reminder: cancel anytime, no questions asked
- Affiliate reminder: "Use our Coinbase link for $10 free Bitcoin"

PS line: tease next week's issue topic"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(result, f"newsletter_welcome_{ts}.md", ext="md")
        return {"file": str(path), "action": "welcome"}

    def _promote_newsletter(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create promotional content to grow {NEWSLETTER_NAME} subscribers.

Price: {PRICE}/month (less than a coffee per week)
Subscribe: {self.subscribe_url}

Free preview teaser: "Weekly crypto signals, DeFi yields, 1 exclusive trade idea"

Generate:
1. FACEBOOK POST (200 words) — emphasize the recurring value vs the small price
2. INSTAGRAM CAPTION (80 words + 20 hashtags)
3. LEAD MAGNET OFFER — "Subscribe today and get our FREE Crypto Starter Checklist"
4. FREE TRIAL PITCH — "Try 1 issue free before you pay"

Focus on the pain: crypto is confusing, there's too much noise, our newsletter
cuts through it with only what matters."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"newsletter_promo_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            lines = result.split("\n")
            fb_lines = []
            in_fb = False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb = True
                elif in_fb and any(k in line.upper() for k in ["INSTAGRAM", "LEAD", "FREE TRIAL"]):
                    break
                elif in_fb:
                    fb_lines.append(line)
            fb = get_facebook()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
        except Exception as e:
            self.logger.debug("Newsletter promo post skipped: %s", e)

        return {"file": str(path), "action": "promote"}

    def _free_preview(self, ts: str, **kwargs) -> dict:
        """Generate a free preview issue to attract subscribers."""
        data = self._get_market_data()
        prices = data.get("prices", {})
        btc = prices.get("bitcoin", {})

        prompt = f"""Write a FREE PREVIEW issue of {NEWSLETTER_NAME} to attract subscribers.

This is the teaser — show the quality but hold back the best content.
BTC context: ${btc.get('usd', '~$95,000')}

Free preview (400 words):
- Market snapshot (full)
- One educational tip (full)
- Signal of the Week — show the format but blur/redact the specific coin
  ("This week's pick is a Layer-2 token with [SUBSCRIBER ONLY]...")
- DeFi yield — show the format, redact APY ("[SUBSCRIBER ONLY] protocol at XX%")
- CTA at the end: "Unlock all signals for just {PRICE}/month → {self.subscribe_url}"

Make them feel the FOMO of not being a subscriber."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1200)
        path = self.save_output(result, f"free_preview_{ts}.md", ext="md")
        return {"file": str(path), "action": "preview"}

    def _drip_sequence(self, ts: str, **kwargs) -> dict:
        """5-email drip sequence to convert free subscribers to paid."""
        prompt = f"""Write a 5-email drip sequence to upgrade free subscribers to paid {NEWSLETTER_NAME}.

Paid price: {PRICE}/month
Goal: convert within 7 days

Email 1 (Day 0): Welcome + free value — "Your first crypto tip"
Email 2 (Day 2): Social proof — "What paid subscribers made last week"
Email 3 (Day 4): Exclusive preview — show a blurred signal, unlock for {PRICE}
Email 4 (Day 6): Objection handling — "Is {PRICE}/month worth it? Let me show you..."
Email 5 (Day 7): Last chance — "Your free access expires tomorrow"

Each email:
- Subject line (+ emoji)
- Preview text
- Body (150-200 words)
- One clear CTA: Subscribe → {self.subscribe_url}"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"drip_sequence_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📧 Crypto Newsletter — Drip Sequence Built\n5 emails to convert free → paid\n💰 {PRICE}/subscriber")
        except Exception:
            pass

        return {"file": str(path), "action": "sequence"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Crypto Newsletter Revenue Bot")
    parser.add_argument("--action", default="send",
                        choices=["send", "welcome", "promote", "preview", "sequence"])
    args = parser.parse_args()
    bot = CryptoNewsletterBot()
    result = bot.execute(action=args.action)
    print(f"\n✅ Crypto Newsletter: {result['file']}")
