#!/usr/bin/env python3
"""
Revenue Stream #9 — NEXORA Beta Program ($49/month)
Purpose: Launches NEXORA as an invite-only paid beta.
         10 founding creators at $49/month = $490 MRR from day one.
         Bot manages recruitment, onboarding, landing page, and beta comms.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a SaaS product launch expert who specializes in creator economy
platforms. You've launched 10+ subscription platforms and know exactly how to recruit
founding members: make them feel special, give them real value, and lock in
recurring revenue before the product is fully built. You understand creator psychology —
they want: more income, more control, less middlemen. NEXORA delivers all three.
Your messaging positions NEXORA as the premium alternative creators have been waiting
for: better revenue share than OnlyFans, more control than Patreon, more AI tools
than Fanvue. Founding member spots are genuinely limited."""

NEXORA_PRICE = "$49/month"
NEXORA_FOUNDING_PRICE = "$29/month"
NEXORA_SPOTS = 50
NEXORA_REVENUE_SHARE = "90%"


class NexoraBetaBot(BaseBot):

    def __init__(self):
        super().__init__("09_nexora_beta", "revenue")
        self.beta_url = os.getenv("NEXORA_BETA_URL", "https://nexora.wheellsverse.com/beta")
        self.stripe_url = os.getenv("STRIPE_NEXORA_URL", "https://buy.stripe.com/wheellsverse-nexora")
        self.waitlist_url = os.getenv("NEXORA_WAITLIST_URL", "https://wheellsverse.ck.page/nexora")

    def run(self, action: str = "recruit", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "recruit")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "recruit": self._recruit_creators,
            "onboard": self._onboard_sequence,
            "landing": self._beta_landing,
            "announce": self._launch_announcement,
            "status": self._beta_status,
            "pitch": self._creator_pitch,
        }
        fn = actions.get(action, self._recruit_creators)
        return fn(ts, **kwargs)

    def _recruit_creators(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create creator recruitment content for NEXORA Beta Launch.

NEXORA — The Creator Platform That Pays More
- Creators keep {NEXORA_REVENUE_SHARE} of all revenue (vs 80% on OnlyFans)
- Live video streaming + exclusive content + fan subscriptions
- AI-powered content suggestions + growth tools
- Direct payouts, no delays
- WheellsVerse powered

Beta offer: Founding creators get locked in at {NEXORA_FOUNDING_PRICE}/month forever
(Regular price: {NEXORA_PRICE}/month after beta)
Only {NEXORA_SPOTS} founding spots available.

Generate recruitment content:
1. FACEBOOK POST (250 words):
   - Hook: "I'm looking for 50 creators to join something that will change how you earn"
   - Pain points: losing 20-30% to platforms, payment delays, limited control
   - NEXORA as the solution
   - Social proof: "Limited to {NEXORA_SPOTS} founding creators"
   - CTA: Apply at {self.waitlist_url}

2. INSTAGRAM CAPTION (120 words + 20 hashtags):
   - Creator-focused: "Attention content creators 👇"
   - Key benefit vs competitors
   - Founding creator urgency
   - CTA: waitlist link in bio

3. DIRECT MESSAGE TEMPLATE (80 words):
   - Personalized outreach to content creators
   - Soft invitation, not hard sell
   - Easy reply action ("Reply 'NEXORA' and I'll send you details")"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"nexora_recruit_{ts}.md", ext="md")

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
                elif "DIRECT" in line.upper():
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
            self.logger.debug("NEXORA recruit post skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"🚀 NEXORA Beta — Recruitment Campaign Running\n{NEXORA_SPOTS} spots | {NEXORA_FOUNDING_PRICE}/month founding price\n🔗 {self.waitlist_url}")
        except Exception:
            pass

        return {"file": str(path), "action": "recruit"}

    def _onboard_sequence(self, ts: str, **kwargs) -> dict:
        prompt = f"""Write the complete NEXORA founding creator onboarding sequence.

Founding Creator Benefits:
- Price locked at {NEXORA_FOUNDING_PRICE}/month (regular: {NEXORA_PRICE})
- {NEXORA_REVENUE_SHARE} revenue share on all content
- Direct input on platform features
- Founding Creator badge on profile
- Priority support + 1-on-1 setup call

Email sequence (5 emails):
Email 1 (Immediate — Access Confirmed):
Subject: 🎉 Welcome to NEXORA, Founding Creator #{"{number}"}
- Celebrate their decision
- Beta access instructions
- Setup checklist (5 steps)
- Direct contact for questions

Email 2 (Day 2 — First Post):
Subject: Ready to post your first exclusive content?
- How to create first post
- Subscription tier recommendations
- First 10 fan acquisition tips

Email 3 (Day 7 — First Revenue):
Subject: How's your first week going?
- Check in + celebrate any wins
- Common setup issues solved
- How to promote NEXORA profile

Email 4 (Day 14 — Growth):
Subject: Your NEXORA growth report
- Analytics breakdown
- How top creators are performing
- Feature spotlight: live streaming setup

Email 5 (Day 30 — Results):
Subject: 30-day NEXORA check-in
- Revenue report
- Referral program invite (earn 20% commission)
- Beta feedback request"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"nexora_onboard_{ts}.md", ext="md")
        return {"file": str(path), "action": "onboard"}

    def _beta_landing(self, ts: str, **kwargs) -> dict:
        """Generate NEXORA beta landing page HTML."""
        prompt = f"""Build a high-converting landing page for NEXORA Beta signup.

Design: Dark (#080b11 bg), cyan (#00d4ff) accents, gold (#ffd700) for urgency
Platform: Creator monetization — better than OnlyFans

Page sections:
1. HERO:
   - Headline: "The Creator Platform That Keeps You in Control"
   - Subheadline: "{NEXORA_REVENUE_SHARE} Revenue Share. Instant Payouts. Zero Drama."
   - CTA Button: "Apply for Founding Creator Access" → {self.waitlist_url}
   - Counter: "{NEXORA_SPOTS} founding spots remaining"

2. COMPARISON TABLE:
   NEXORA vs OnlyFans vs Patreon vs Fanvue
   Rows: Revenue share, payout speed, live streaming, AI tools, price

3. FEATURES (6 cards):
   - Live Video Streaming
   - Exclusive Content Feed
   - Fan Subscriptions (you set the price)
   - Direct Fan Messaging
   - AI Content Suggestions
   - Same-Day Payouts

4. FOUNDING CREATOR OFFER:
   - "{NEXORA_FOUNDING_PRICE}/month locked forever (vs {NEXORA_PRICE} regular)"
   - Counter/timer showing remaining spots

5. HOW IT WORKS (3 steps):
   1. Apply + get approved
   2. Set up your profile + price
   3. Post content + earn

6. TESTIMONIAL PLACEHOLDER

7. FAQ (6 questions)

8. FOOTER CTA

Output: Complete HTML file (dark theme, mobile-first, inline CSS)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=5000)
        nexora_dir = Path(__file__).resolve().parents[3] / "frontend" / "nexora"
        nexora_dir.mkdir(parents=True, exist_ok=True)
        (nexora_dir / "beta.html").write_text(result, encoding="utf-8")
        path = self.save_output("# NEXORA Beta Landing\n\nSaved to: frontend/nexora/beta.html",
                                f"nexora_beta_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🌐 NEXORA Beta Landing Page Built!\n📁 frontend/nexora/beta.html\n💰 {NEXORA_FOUNDING_PRICE}/month | {NEXORA_SPOTS} spots")
        except Exception:
            pass

        return {"file": str(path), "action": "landing", "html": str(nexora_dir / "beta.html")}

    def _launch_announcement(self, ts: str, **kwargs) -> dict:
        prompt = f"""Write NEXORA's full launch announcement campaign.

Platform: NEXORA by WheellsVerse
Founding price: {NEXORA_FOUNDING_PRICE}/month (limited to {NEXORA_SPOTS} creators)
Regular price: {NEXORA_PRICE}/month
Apply: {self.waitlist_url}

Launch campaign:
1. LAUNCH DAY FACEBOOK POST (300 words) — big announcement energy
2. LAUNCH DAY INSTAGRAM CAPTION (150 words + 25 hashtags) — visual-first
3. LAUNCH DAY EMAIL (to existing list — 300 words):
   Subject: "I've been building something for you..."
   - Personal story of why NEXORA exists
   - Exclusive list-subscriber offer (get in before public announcement)
4. WHATSAPP BROADCAST (80 words) — personal, excited
5. PRESS RELEASE (200 words) — for blogs/media

Make the launch feel like an event, not a product release."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"nexora_launch_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🚀 NEXORA LAUNCH CAMPAIGN READY!\n{NEXORA_SPOTS} founding spots @ {NEXORA_FOUNDING_PRICE}/month\n10 sold = $290 MRR. 50 sold = $1,450 MRR!")
        except Exception:
            pass

        return {"file": str(path), "action": "announce"}

    def _beta_status(self, ts: str, **kwargs) -> dict:
        """Check NEXORA beta status and built pages."""
        nexora_dir = Path(__file__).resolve().parents[3] / "frontend" / "nexora"
        pages = list(nexora_dir.glob("*.html")) if nexora_dir.exists() else []
        status = {
            "pages_built": [p.name for p in pages],
            "beta_url": self.beta_url,
            "waitlist_url": self.waitlist_url,
            "founding_price": NEXORA_FOUNDING_PRICE,
            "regular_price": NEXORA_PRICE,
            "spots_available": NEXORA_SPOTS,
        }
        path = self.save_output(
            "# NEXORA Beta Status\n\n" + "\n".join(f"- {k}: {v}" for k, v in status.items()),
            f"nexora_status_{ts}.md", ext="md")
        return {"file": str(path), "action": "status", "status": status}

    def _creator_pitch(self, ts: str, **kwargs) -> dict:
        creator_type = kwargs.get("creator_type", "fitness content creator")
        prompt = f"""Write a personalized NEXORA pitch for: {creator_type}

The pitch should:
1. Reference their specific pain points (platform takes too much, slow payments, no control)
2. Show exactly how NEXORA solves THEIR specific problem
3. Calculate their potential earnings: "If you have 100 subscribers at $9.99, you keep
   {NEXORA_REVENUE_SHARE} = ${100 * 9.99 * 0.9:.0f}/month vs ${{100 * 9.99 * 0.8:.0f}}/month on OnlyFans"
4. Founding creator FOMO: spots are limited, price goes up
5. Easy next step: apply at {self.waitlist_url}

Format: 200-word DM or email pitch
Tone: Excited peer, not salesperson"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=600)
        path = self.save_output(result, f"creator_pitch_{ts}.md", ext="md")
        return {"file": str(path), "action": "pitch", "creator_type": creator_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEXORA Beta Revenue Bot")
    parser.add_argument("--action", default="recruit",
                        choices=["recruit", "onboard", "landing", "announce", "status", "pitch"])
    parser.add_argument("--creator-type", type=str, default=None)
    args = parser.parse_args()
    bot = NexoraBetaBot()
    result = bot.execute(action=args.action, creator_type=args.creator_type)
    print(f"\n✅ NEXORA Beta: {result['file']}")
