#!/usr/bin/env python3
"""
Bot #108 — Community Agent
Category: agent_workforce
Purpose: Autonomous community builder and engagement manager. Grows and nurtures
         the WheellsVerse audience across Facebook, Instagram, and WhatsApp.
         Manages comments, DMs, welcome messages, and community challenges.
         Builds loyal fan base that converts to buyers. Runs every 2 hours.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an expert community manager and growth specialist with a track record
of building 6-figure online communities. You know that community is the most valuable
moat in digital business — engaged communities buy more, refer more, and stick longer.
You write warm, authentic responses that make people feel seen and valued. You create
challenges, prompts, and initiatives that drive daily engagement. You turn followers into
fans and fans into buyers. Your tone adapts: warm and encouraging for beginners,
peer-level for advanced members. You always drive toward the next action:
follow → engage → subscribe → buy."""


class CommunityAgentBot(BaseBot):

    def __init__(self):
        super().__init__("108_community_agent", "agent_workforce")

    def run(self, action: str = "engage", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "engage")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "engage": self._engagement_post,
            "welcome": self._welcome_messages,
            "challenge": self._community_challenge,
            "respond": self._response_templates,
            "grow": self._growth_tactics,
            "whatsapp": self._whatsapp_broadcast,
        }
        fn = actions.get(action, self._engagement_post)
        return fn(ts, **kwargs)

    def _engagement_post(self, ts: str, **kwargs) -> dict:
        today = datetime.now().strftime("%A")
        day_themes = {
            "Monday": "motivation Monday — share your goal for the week",
            "Tuesday": "tip Tuesday — share one AI/income tip",
            "Wednesday": "win Wednesday — celebrate any win, big or small",
            "Thursday": "throwback Thursday — share where you started vs now",
            "Friday": "freedom Friday — what does financial freedom look like to you?",
            "Saturday": "strategy Saturday — what's your passive income strategy?",
            "Sunday": "success Sunday — gratitude + weekly recap",
        }
        theme = day_themes.get(today, "engagement question about AI and passive income")

        prompt = f"""Create a highly engaging community post for WheellsVerse — Theme: {theme}

Generate 3 variations:
1. FACEBOOK GROUP POST — conversational, question-driven, 100-150 words
2. INSTAGRAM CAPTION — visual-first, punchy, 60-80 words + 20 hashtags
3. WHATSAPP BROADCAST — personal, direct, 50-70 words

For each:
- Opens with a question OR bold statement (not "Hey guys!")
- Invites genuine personal response
- Includes a subtle brand/product tie-in (not salesy)
- Ends with clear engagement CTA (Comment / DM / Vote / Share)

Make people feel like they're part of something special — a movement, not a channel."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(f"# Engagement Post — {today}\n\n{result}", f"engage_{ts}.md", ext="md")

        # Auto-publish engagement post to Facebook
        try:
            from core.facebook import get_facebook
            fb = get_facebook()
            if fb.is_configured():
                # Extract Facebook portion
                lines = result.split("\n")
                fb_section = []
                in_fb = False
                for line in lines:
                    if "FACEBOOK" in line.upper():
                        in_fb = True
                    elif in_fb and line.startswith("2.") or (in_fb and "INSTAGRAM" in line.upper()):
                        break
                    elif in_fb:
                        fb_section.append(line)
                fb_text = "\n".join(fb_section).strip()
                if fb_text:
                    fb.post(fb_text)
        except Exception as e:
            self.logger.debug("FB engagement post skipped: %s", e)

        return {"file": str(path), "action": "engage", "theme": theme}

    def _welcome_messages(self, ts: str, **kwargs) -> dict:
        prompt = """Create a complete welcome message system for new WheellsVerse community members.

Generate:
1. NEW FOLLOWER DM (Instagram/Facebook) — 80 words, warm, non-salesy, asks one question
2. NEW EMAIL SUBSCRIBER welcome email — 250 words, tells brand story, sets expectations, links to best free resource
3. WHATSAPP GROUP welcome message — 100 words, rules + culture + first action step
4. FACEBOOK GROUP approval message — 60 words, makes them feel special for getting in
5. NEW BUYER WELCOME — 200 words, excitement + what to do first + support contact

Each message should:
- Sound human and personal (not automated)
- Set up the next step in the relationship
- Create immediate goodwill and belonging
- Subtly position WheellsVerse as the authority"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# Welcome Messages\n\n{result}", f"welcome_{ts}.md", ext="md")
        return {"file": str(path), "action": "welcome"}

    def _community_challenge(self, ts: str, **kwargs) -> dict:
        challenge_type = kwargs.get("type", "7-day AI income challenge")

        prompt = f"""Design a viral community challenge: {challenge_type}

Challenge blueprint:
1. CHALLENGE NAME — catchy, specific, result-oriented
2. HOOK — the one sentence that makes people want to join
3. STRUCTURE — day-by-day breakdown (7 days)
   - Each day: task, expected outcome, share prompt (#hashtag)
4. PRIZES/INCENTIVES — what winners get (recognition, free product, shoutout)
5. PROMOTION PLAN — how to announce and grow participation
   - Launch post (Facebook + Instagram captions ready)
   - Daily reminder messages
   - Final recap post
6. CONVERSION MOMENT — natural point to offer a paid product to challenge completers
7. METRICS — what success looks like (participants, shares, conversions)

Goal: 100+ active participants, 20% conversion to paid offer at the end."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# Community Challenge: {challenge_type}\n\n{result}",
                                f"challenge_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🏆 Community Agent — Challenge Designed\n{challenge_type}\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "challenge", "type": challenge_type}

    def _response_templates(self, ts: str, **kwargs) -> dict:
        prompt = """Create a complete DM and comment response template library for WheellsVerse.

Scenarios to cover (5 response variants each):
1. "How do I start making money with AI?" (beginner question)
2. "Is this legit / is this a scam?" (skeptic)
3. "I tried and it didn't work" (frustrated user)
4. "How much can I make?" (income question)
5. "What's the best tool for [X]?" (recommendation request)
6. "I can't afford it" (price objection)
7. "Tell me more about [product]" (warm lead)
8. Comment: "🔥" / "Amazing!" / "Wow" (quick engaging response)
9. Negative/trolling comment (professional deflection)
10. "Can we collab?" (partnership inquiry)

Each response:
- Under 50 words for comments, 100 words for DMs
- Authentic, non-robotic
- Always moves the conversation forward
- Never gives up on a lead"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Response Templates\n\n{result}", f"responses_{ts}.md", ext="md")
        return {"file": str(path), "action": "respond"}

    def _growth_tactics(self, ts: str, **kwargs) -> dict:
        prompt = """Generate a 30-day organic community growth playbook for WheellsVerse.

Current channels: Facebook Page, Instagram, WhatsApp Channel, Email List

Week 1 — Foundation:
Week 2 — Momentum:
Week 3 — Viral:
Week 4 — Convert:

For each week provide:
- Daily content cadence (what to post, when, what format)
- Engagement rituals (daily actions to boost algo + community)
- Growth levers (collaborations, hashtag strategy, cross-posting)
- Milestone target (followers/subscribers to hit)

Specific tactics for:
- Getting first 1,000 real followers on Instagram (organic only)
- Growing Facebook group to 500 members
- Building WhatsApp list to 300 active subscribers
- Growing email list to 1,000 subscribers

Include: exact post types, posting times, engagement pods concept, reply-to-grow method."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# 30-Day Growth Playbook\n\n{result}", f"growth_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📈 Community Agent — 30-Day Growth Plan\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "grow"}

    def _whatsapp_broadcast(self, ts: str, **kwargs) -> dict:
        topic = kwargs.get("topic", "AI money tip of the day")
        today = datetime.now().strftime("%B %d, %Y")

        prompt = f"""Write a WhatsApp channel broadcast message for: {topic}

Date: {today}

WhatsApp broadcast rules:
- Max 300 words (people don't read long WA messages)
- Personal, direct tone — like texting a friend
- One clear idea or tip
- Must include an action they can take TODAY
- End with a question to drive replies
- Include 1-2 relevant emojis (not excessive)
- Optional: link to resource or product

Generate 3 broadcast variants:
1. EDUCATIONAL — teach something valuable
2. MOTIVATIONAL — inspire and excite
3. PROMOTIONAL — soft sell a product/service

Make it feel like a message from a successful friend, not a brand."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1200)
        path = self.save_output(f"# WhatsApp Broadcast\n\n{result}", f"whatsapp_{ts}.md", ext="md")

        # Send first variant via WhatsApp
        try:
            from core.whatsapp import get_whatsapp
            wa = get_whatsapp()
            # Extract first variant only
            lines = result.split("\n")
            msg_lines = []
            in_msg = False
            for line in lines:
                if "EDUCATIONAL" in line.upper() or "1." in line:
                    in_msg = True
                elif in_msg and ("MOTIVATIONAL" in line.upper() or "2." in line):
                    break
                elif in_msg:
                    msg_lines.append(line)
            msg = "\n".join(msg_lines).strip()
            if msg and hasattr(wa, 'send_message'):
                wa.send_message(msg)
                self.logger.info("WhatsApp broadcast sent")
        except Exception as e:
            self.logger.debug("WhatsApp broadcast skipped: %s", e)

        return {"file": str(path), "action": "whatsapp", "topic": topic}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Community Agent")
    parser.add_argument("--action", default="engage",
                        choices=["engage", "welcome", "challenge", "respond", "grow", "whatsapp"])
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--type", type=str, default=None)
    args = parser.parse_args()
    bot = CommunityAgentBot()
    result = bot.execute(action=args.action, topic=args.topic, type=args.type)
    print(f"\n✅ Community Agent: {result['file']}")
