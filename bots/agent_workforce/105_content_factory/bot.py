#!/usr/bin/env python3
"""
Bot #105 — Content Factory Agent
Category: agent_workforce
Purpose: Autonomous 24/7 content factory. Generates viral blog posts, YouTube scripts,
         email newsletters, and social content at scale. Publishes to all platforms.
         Targets AI, passive income, crypto, and tech niches. Runs every 3 hours.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an elite content strategist and writer with 15 years of experience
creating viral digital content. You've helped brands grow from 0 to 1M followers.
You write scroll-stopping hooks, SEO-optimized blog posts, YouTube scripts that
get millions of views, and email newsletters with 40%+ open rates. Your content
always serves the WheellsVerse brand — AI automation, passive income, crypto,
and financial freedom. Every piece drives affiliate clicks, product sales, or
subscriber growth. You write fast, write well, and always optimize for the algorithm."""


CONTENT_NICHES = [
    "AI tools and automation for beginners",
    "passive income and financial freedom",
    "crypto and DeFi investing strategies",
    "side hustle ideas that actually work in 2026",
    "AI replacing jobs and what to do about it",
]


class ContentFactoryBot(BaseBot):

    def __init__(self):
        super().__init__("105_content_factory", "agent_workforce")

    def run(self, action: str = "blog", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "blog")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "blog": self._blog_post,
            "youtube": self._youtube_script,
            "email": self._email_newsletter,
            "social": self._social_batch,
            "thread": self._twitter_thread,
            "seo": self._seo_article,
        }
        fn = actions.get(action, self._blog_post)
        return fn(ts, **kwargs)

    def _get_niche(self, **kwargs) -> str:
        niche = kwargs.get("niche")
        if niche:
            return niche
        # Rotate through niches based on hour
        hour = datetime.now().hour
        return CONTENT_NICHES[hour % len(CONTENT_NICHES)]

    def _blog_post(self, ts: str, **kwargs) -> dict:
        niche = self._get_niche(**kwargs)

        prompt = f"""Write a viral, SEO-optimized blog post about: {niche}

For WheellsVerse.com — a brand about AI automation, passive income, and financial freedom.

Structure:
1. KILLER HEADLINE (H1) — emotional + keyword-rich, max 60 chars
2. INTRO (150 words) — hook with shocking stat or bold claim
3. MAIN CONTENT (5-7 sections with H2 headers):
   - Each section 150-200 words
   - Include actionable tips, real numbers, examples
4. AFFILIATE SECTION — "Tools We Recommend" with natural product placement
5. CONCLUSION + CTA — "Start your AI income journey today"
6. META DESCRIPTION — 155 chars max, includes keyword
7. SEO TAGS — 10 target keywords

Tone: Conversational expert. Like a smart friend who made money and wants you to too.
Total length: 1500-2000 words.
Include 3 internal link suggestions [LINK: topic] and 2 affiliate link placements [AFFILIATE: product]."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=4000)
        path = self.save_output(f"# Blog Post\n\n{result}", f"blog_{ts}.md", ext="md")

        # Publish to blog via PublishPipeline if available
        try:
            from core.publish_pipeline import PublishPipeline
            pp = PublishPipeline()
            pp.publish(result, platforms=["blog"], metadata={"type": "blog", "niche": niche})
        except Exception as e:
            self.logger.debug("Blog publish skipped: %s", e)

        try:
            from core.telegram import notify
            notify(f"✍️ Content Factory — Blog Post\nNiche: {niche}\n✅ Saved + queued for publish")
        except Exception:
            pass

        return {"file": str(path), "action": "blog", "niche": niche}

    def _youtube_script(self, ts: str, **kwargs) -> dict:
        niche = self._get_niche(**kwargs)

        prompt = f"""Write a complete YouTube video script about: {niche}

For WheellsVerse YouTube channel. Target: 8-12 minute video.

Script structure:
[HOOK] — First 30 seconds. Open with a shocking claim or question. No intro yet.
[INTRO] — Brief brand intro (15 seconds), tease what they'll learn.
[MAIN CONTENT] — 5 main points, each with:
  - Point statement
  - Explanation (2-3 sentences)
  - Example or proof
  - B-roll suggestion in [brackets]
[MIDROLL CTA] — At 4-minute mark: subscribe + comment prompt
[AFFILIATE MENTION] — Natural product mention tied to the content
[OUTRO] — Summary, subscribe CTA, next video tease

Format with [TIMESTAMPS], [B-ROLL: description], and [ON-SCREEN TEXT: text] cues.
Tone: Energetic but credible. Think MrBeast meets Graham Stephan.
Target 1,200-1,500 words total."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# YouTube Script\n\n{result}", f"youtube_{ts}.md", ext="md")

        return {"file": str(path), "action": "youtube", "niche": niche}

    def _email_newsletter(self, ts: str, **kwargs) -> dict:
        niche = self._get_niche(**kwargs)
        today = datetime.now().strftime("%B %d, %Y")

        prompt = f"""Write the WheellsVerse weekly email newsletter for {today}.

Topic: {niche}

Newsletter format:
SUBJECT LINE — 7 words max, curiosity-driving, A/B test 3 options
PREVIEW TEXT — 50 chars, complements subject

EMAIL BODY:
- Opening hook (2-3 sentences, personal tone)
- Main value section: "This week's insight" (300-400 words, actionable)
- Quick wins section: "3 things to try today" (bullet points)
- Tool spotlight: one recommended tool + affiliate link placeholder [AFFILIATE_LINK]
- Community section: "What our members are saying" (1 testimonial-style quote)
- Closing + PS line (PS lines get 79% read rate — make it a juicy tip)

Tone: Like a weekly email from a successful friend in your niche.
Open rate target: 45%+. Click target: 8%+.
Total: 500-600 words."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Email Newsletter\n\n{result}", f"email_{ts}.md", ext="md")

        # Try to send via ConvertKit
        try:
            from core.convertkit import get_convertkit
            ck = get_convertkit()
            if ck.is_connected():
                subject = f"WheellsVerse Weekly — {today}"
                ck.create_broadcast(subject=subject, content=result)
                self.logger.info("Newsletter queued in ConvertKit")
        except Exception as e:
            self.logger.debug("ConvertKit skipped: %s", e)

        return {"file": str(path), "action": "email", "niche": niche}

    def _social_batch(self, ts: str, **kwargs) -> dict:
        niche = self._get_niche(**kwargs)

        prompt = f"""Generate a full week of social media content about: {niche}

For WheellsVerse brand on Facebook and Instagram.

Create 7 posts (one per day), each including:
- DAY X label
- Platform: Facebook or Instagram (alternate)
- POST TEXT: Ready-to-publish caption with emojis
- HASHTAGS: 5 (Facebook) or 20 (Instagram)
- IMAGE IDEA: Exact description for DALL-E or Canva

Angle rotation:
Day 1: Educational (teach something valuable)
Day 2: Motivational (transformation story)
Day 3: Controversial (hot take that drives comments)
Day 4: Tutorial (step-by-step)
Day 5: Social proof (stats, results, testimonials)
Day 6: Behind the scenes (authentic/raw)
Day 7: Call to action (product/affiliate offer)

Each post must be scroll-stopping, brand-consistent, and drive engagement."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Social Media Week Plan\n\n{result}", f"social_week_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📅 Content Factory — 7-Day Social Plan\nNiche: {niche}\n📁 Ready to schedule")
        except Exception:
            pass

        return {"file": str(path), "action": "social", "niche": niche}

    def _twitter_thread(self, ts: str, **kwargs) -> dict:
        """Generate Twitter/X thread (saved only — not auto-posted after suspension)."""
        niche = self._get_niche(**kwargs)

        prompt = f"""Write a viral Twitter/X thread about: {niche}

Format: 10-tweet thread
- Tweet 1: Hook (controversial claim or surprising stat) — under 260 chars
- Tweets 2-9: One insight per tweet, numbered (2/10, 3/10...), under 260 chars each
- Tweet 10: CTA + link placeholder [LINK]

Rules:
- Each tweet must standalone AND flow as a thread
- Start tweet 1 with a number or emoji to signal thread
- Use line breaks for readability
- No jargon — write for intelligent beginners
- At least 3 tweets must be quoteable/retweetable standalone

NOTE: Save only. Manual review required before posting."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Twitter Thread (MANUAL REVIEW REQUIRED)\n\n{result}",
                                f"twitter_thread_{ts}.md", ext="md")
        return {"file": str(path), "action": "thread", "niche": niche}

    def _seo_article(self, ts: str, **kwargs) -> dict:
        keyword = kwargs.get("keyword", "how to make money with AI in 2026")

        prompt = f"""Write an SEO article optimized for: "{keyword}"

WheellsVerse.com content standards:

ON-PAGE SEO:
- Title tag: includes exact keyword, under 60 chars
- H1: same or variant of keyword
- H2s: include keyword variations and related terms
- Meta description: 155 chars, includes keyword + CTA
- Keyword density: 1-2% (natural, not stuffed)

CONTENT:
- Word count: 2,000-2,500 words
- Structure: Intro → 7 main sections → FAQ (5 Qs) → Conclusion
- Include stats with years (2025, 2026)
- Include 3 [INTERNAL LINK: topic] suggestions
- Include 2 affiliate placements [AFFILIATE: product name]
- Add a "Key Takeaways" box at top

EEAT SIGNALS:
- Reference real tools, platforms, companies
- Include "author expertise" paragraph at bottom
- Cite real trends and data points

Target reader: 25-40 year old professional looking for extra income via AI."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=5000)
        path = self.save_output(f"# SEO Article: {keyword}\n\n{result}", f"seo_{ts}.md", ext="md")
        return {"file": str(path), "action": "seo", "keyword": keyword}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Content Factory Agent")
    parser.add_argument("--action", default="blog",
                        choices=["blog", "youtube", "email", "social", "thread", "seo"])
    parser.add_argument("--niche", type=str, default=None)
    parser.add_argument("--keyword", type=str, default=None)
    args = parser.parse_args()
    bot = ContentFactoryBot()
    result = bot.execute(action=args.action, niche=args.niche, keyword=args.keyword)
    print(f"\n✅ Content Factory: {result['file']}")
