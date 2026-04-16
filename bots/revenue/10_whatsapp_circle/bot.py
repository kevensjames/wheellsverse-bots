#!/usr/bin/env python3
"""
Revenue Stream #10 — WhatsApp Inner Circle ($19/month)
Purpose: Manages a paid private WhatsApp community where members get:
         - Daily AI income tips
         - Exclusive crypto signals
         - Access to J.K. Blaze directly
         - Early access to all WheellsVerse products
         Target: 200 members × $19 = $3,800/month recurring.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an expert community monetization specialist. You've built paid
communities generating $10,000+/month in recurring revenue. You know that the
WhatsApp Inner Circle model works because it combines three irresistible elements:
exclusivity (you have to be invited/approved), intimacy (direct access to the creator),
and consistent value (daily tips they can't get anywhere else). Your content for the
Inner Circle is more personal, more specific, and more actionable than anything public.
Members feel like they're in a secret club — because they are."""

CIRCLE_PRICE = "$19/month"
CIRCLE_NAME = "WheellsVerse Inner Circle"
MAX_MEMBERS = 200


class WhatsAppCircleBot(BaseBot):

    def __init__(self):
        super().__init__("10_whatsapp_circle", "revenue")
        self.subscribe_url = os.getenv("CIRCLE_SUBSCRIBE_URL",
                                       "https://wheellsverse.ck.page/inner-circle")
        self.payment_url = os.getenv("STRIPE_CIRCLE_URL",
                                     "https://buy.stripe.com/wheellsverse-circle")
        self.price = CIRCLE_PRICE

    def run(self, action: str = "daily_tip", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "daily_tip")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "daily_tip": self._daily_tip,
            "recruit": self._recruit,
            "welcome": self._welcome_member,
            "weekly": self._weekly_value_drop,
            "exclusive": self._exclusive_content,
            "promo": self._promo_post,
        }
        fn = actions.get(action, self._daily_tip)
        return fn(ts, **kwargs)

    def _daily_tip(self, ts: str, **kwargs) -> dict:
        """Generate the daily tip to send to Inner Circle members."""
        today = datetime.now().strftime("%A, %B %d")
        day_themes = {
            "Monday": "motivation + weekly income goal setting",
            "Tuesday": "AI tool deep-dive or hack",
            "Wednesday": "crypto/market insight",
            "Thursday": "passive income strategy",
            "Friday": "product recommendation + affiliate tip",
            "Saturday": "weekend action item (one thing to do for income)",
            "Sunday": "reflection + next week planning",
        }
        weekday = datetime.now().strftime("%A")
        theme = day_themes.get(weekday, "AI income tip")

        # Get live data for context
        market_ctx = ""
        try:
            from bots.narai.narai.bot import NarAIInternet
            prices = NarAIInternet().crypto_price(["bitcoin"])
            btc = prices.get("bitcoin", {})
            market_ctx = f"(BTC: ${btc.get('usd', 'N/A')})"
        except Exception:
            pass

        prompt = f"""Write today's Inner Circle daily tip for {today}.

Theme: {theme} {market_ctx}
Community: {CIRCLE_NAME} — paid WhatsApp group ({CIRCLE_PRICE}/month)
Members: exclusive early adopters, serious about AI income

Rules for Inner Circle content:
- More personal and specific than public content
- Include ONE actionable tip they can use TODAY
- Feel like a text from a successful friend, not a brand
- Max 250 words
- End with a question to drive replies

Today's message:
- Brief greeting (1 line, include day)
- Main tip (specific, numbered steps if needed)
- Why this matters for their income
- Action item: "Do this before tonight:"
- Question: "How many of you have tried [related thing]?"

Tone: peer-level, confident, warm, slightly exclusive ("As Inner Circle members, you get this first...")"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=600)
        path = self.save_output(result, f"daily_tip_{ts}.md", ext="md")

        # Send to WhatsApp
        try:
            from core.whatsapp import get_whatsapp
            wa = get_whatsapp()
            if hasattr(wa, 'send_message'):
                wa.send_message(result)
                self.logger.info("Inner Circle daily tip sent via WhatsApp")
        except Exception as e:
            self.logger.debug("WhatsApp send skipped: %s", e)

        return {"file": str(path), "action": "daily_tip"}

    def _recruit(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create recruitment content for the {CIRCLE_NAME}.

Price: {CIRCLE_PRICE}/month | Max members: {MAX_MEMBERS}
Join: {self.payment_url}
Info: {self.subscribe_url}

What members get:
- Daily AI income tip (exclusive content, not on any public platform)
- Weekly crypto signal (specific coin + level + strategy)
- Early access to all WheellsVerse products (20-50% off)
- Direct WhatsApp access to J.K. Blaze
- Monthly "members only" live Q&A
- Private deals and partnerships shared first

Generate:
1. FACEBOOK POST (200 words):
   - "I'm opening 50 spots in my private WhatsApp group..."
   - Tease the exclusive content (don't give it away)
   - FOMO: "Once it's full, I'm closing it"
   - CTA: {self.payment_url}

2. INSTAGRAM CAPTION (100 words + 20 hashtags)

3. EMAIL ANNOUNCEMENT (subject + 200 words):
   - To existing email list
   - "This is only for my most engaged subscribers"
   - List everything included
   - Limited spots urgency

4. WORD-OF-MOUTH TEMPLATE:
   - What to tell a friend in 30 seconds"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1800)
        path = self.save_output(result, f"circle_recruit_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            lines = result.split("\n")
            fb_lines, ig_lines = [], []
            in_fb, in_ig = False, False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb, in_ig = True, False
                elif "INSTAGRAM" in line.upper():
                    in_fb, in_ig = False, True
                elif "EMAIL" in line.upper():
                    in_fb = in_ig = False
                elif in_fb:
                    fb_lines.append(line)
                elif in_ig:
                    ig_lines.append(line)
            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
            if ig.is_configured() and ig_lines:
                ig.post("\n".join(ig_lines).strip())
        except Exception as e:
            self.logger.debug("Circle recruit post skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"💬 WhatsApp Inner Circle — Recruitment Running\n{MAX_MEMBERS} spots @ {CIRCLE_PRICE}/month\n🎯 Full = ${int(CIRCLE_PRICE.replace('$', '').replace('/month', '')) * MAX_MEMBERS}/month MRR!")
        except Exception:
            pass

        return {"file": str(path), "action": "recruit"}

    def _welcome_member(self, ts: str, **kwargs) -> dict:
        member_name = kwargs.get("name", "[MEMBER NAME]")
        prompt = f"""Write the welcome message for a new {CIRCLE_NAME} member.

Member: {member_name}
Price they paid: {CIRCLE_PRICE}/month

Welcome message (send via WhatsApp — 150 words max):
- Personal welcome (excited to have them)
- Quick orientation: what to expect, when to expect it
- First exclusive tip as a welcome gift (real, valuable tip)
- How to engage: how to ask questions, when you respond
- Community rules (1-2 lines: respect, no spam)
- "Your first weekly signal drops [day]"

Also generate:
- Welcome email (300 words) — sent alongside WhatsApp welcome
- First week schedule: what they receive on days 1, 3, 5, 7"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(result, f"circle_welcome_{ts}.md", ext="md")

        # Send WhatsApp welcome
        try:
            from core.whatsapp import get_whatsapp
            wa = get_whatsapp()
            if hasattr(wa, 'send_message'):
                # Extract first 150 words for WhatsApp
                lines = result.split("\n")[:15]
                wa.send_message("\n".join(lines).strip())
        except Exception as e:
            self.logger.debug("WhatsApp welcome skipped: %s", e)

        return {"file": str(path), "action": "welcome"}

    def _weekly_value_drop(self, ts: str, **kwargs) -> dict:
        """Weekly exclusive content drop for members."""
        week = datetime.now().strftime("Week %W — %B %d, %Y")

        # Get market data
        prices = {}
        try:
            from bots.narai.narai.bot import NarAIInternet
            prices = NarAIInternet().crypto_price(["bitcoin", "ethereum", "solana"])
        except Exception:
            pass

        btc = prices.get("bitcoin", {})
        prompt = f"""Write the weekly value drop for {CIRCLE_NAME} members.

{week}
BTC: ${btc.get('usd', 'N/A')} ({btc.get('usd_24h_change', 0):.1f}% 24h)

Weekly drop (send via WhatsApp — 400 words max):
1. 🔥 SIGNAL OF THE WEEK — specific crypto/stock pick with entry context
   (Educational only — "not financial advice but here's what I'm watching...")
2. 🛠 TOOL SPOTLIGHT — one AI tool or resource they need to know
3. 💡 INCOME MOVE — one specific action to take this week for money
4. 📊 MARKET TEMPERATURE — 3-sentence read on where things are headed
5. 🎁 INNER CIRCLE EXCLUSIVE — early access or discount on a WheellsVerse product

Feel: private intelligence briefing from a trusted source.
End with: "Any questions? Reply to this message directly."

Remember: this is PREMIUM — they pay {CIRCLE_PRICE}/month for this level of access."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(result, f"weekly_drop_{ts}.md", ext="md")

        try:
            from core.whatsapp import get_whatsapp
            wa = get_whatsapp()
            if hasattr(wa, 'send_message'):
                wa.send_message(f"🔐 Inner Circle Weekly Drop — {week}\n\n{result}")
        except Exception as e:
            self.logger.debug("Weekly drop skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"📦 Inner Circle — Weekly Drop Sent!\n{week}")
        except Exception:
            pass

        return {"file": str(path), "action": "weekly"}

    def _exclusive_content(self, ts: str, **kwargs) -> dict:
        topic = kwargs.get("topic", "The 3 AI tools I use to make money every day")
        prompt = f"""Create exclusive Inner Circle content on: {topic}

This is ONLY for paying members. Higher quality than anything public.
Format: personal coaching-style message (350 words)

Structure:
- "This is exclusive to Inner Circle — please don't share publicly"
- Context: why you're sharing this now
- The actual content (specific, actionable, insider-level)
- Results they can expect
- How to implement TODAY (3 steps)
- Optional upsell: "If you want me to set this up for you, grab a strategy call [link]"

End: "Who's going to try this this week? Reply with 🙋 so I can follow up with you."

Tone: mentor sharing his actual playbook, not a marketer selling."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=800)
        path = self.save_output(result, f"exclusive_{ts}.md", ext="md")
        return {"file": str(path), "action": "exclusive"}

    def _promo_post(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create a promotional campaign to grow the {CIRCLE_NAME}.

Goal: recruit next 50 members at {CIRCLE_PRICE}/month
Join: {self.payment_url}

Campaign (3 posts to run over 3 days):

DAY 1 — TEASE:
"I'm about to share something I've never talked about publicly..."
[Create curiosity without revealing the offer]

DAY 2 — REVEAL:
Full announcement with all benefits listed
Price + spots remaining + social proof

DAY 3 — LAST CALL:
"Closing the doors tonight. Last chance to join at this price."
[Final urgency push]

Each post: Facebook version (200 words) + Instagram version (80 words + hashtags)
Include a "members are saying..." testimonial section in Day 2"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"circle_promo_{ts}.md", ext="md")
        return {"file": str(path), "action": "promo"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="WhatsApp Inner Circle Revenue Bot")
    parser.add_argument("--action", default="daily_tip",
                        choices=["daily_tip", "recruit", "welcome", "weekly", "exclusive", "promo"])
    parser.add_argument("--name", type=str, default=None)
    parser.add_argument("--topic", type=str, default=None)
    args = parser.parse_args()
    bot = WhatsAppCircleBot()
    result = bot.execute(action=args.action, name=args.name, topic=args.topic)
    print(f"\n✅ WhatsApp Circle: {result['file']}")
