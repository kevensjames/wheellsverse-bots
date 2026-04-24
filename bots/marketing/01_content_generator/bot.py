#!/usr/bin/env python3
"""
Bot #1 — Content Generator (Ultra)
Category: Marketing
Purpose: Generate viral, SEO-dominant content with embedded affiliate links,
         real trending keyword injection, and multi-format output.
"""
import sys
import os
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

COINBASE_URL = os.getenv("AFFILIATE_COINBASE_URL", "https://app.wheellsverse.com/go/coinbase")
ROBINHOOD_URL = os.getenv("AFFILIATE_ROBINHOOD_URL", "https://app.wheellsverse.com/go/robinhood")
AMAZON_TAG = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
CLICKBANK_URL = os.getenv("AFFILIATE_CLICKBANK_URL", "https://hop.clickbank.net/?affiliate=Wheelsvers&vendor=jointgen&v=bvsl")
CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
AUTHOR = os.getenv("AUTHOR_NAME", "J.K. Blaze")

VIRAL_TOPICS = [
    "How I automated my entire content business with AI in 30 days",
    "The AI tools making $10K/month for regular people in 2025",
    "Crypto vs stocks in 2025: where smart money is really going",
    "How to build a $500/month passive income stream using free AI tools",
    "The beginner's guide to making money with affiliate marketing in 2025",
    "Why ChatGPT alone won't make you money — but THIS will",
    "5 AI automation tools that pay for themselves in the first week",
    "How WheellsVerse's bot ecosystem generates revenue 24/7 on autopilot",
    "The truth about passive income: what nobody tells beginners",
    "From $0 to $1,000/month: the exact affiliate marketing blueprint",
    "AI + crypto + affiliate = the money triangle nobody is talking about",
    "How to use AI to find the best-converting affiliate niches in 2025",
]

CONTENT_TYPES = {
    "blog_post": "comprehensive, SEO-dominant blog post (1,200+ words)",
    "article": "in-depth editorial article with expert authority",
    "social_post": "viral social media thread (Twitter/X + LinkedIn versions)",
    "product_desc": "high-converting product description with benefit stack",
    "email": "persuasive email sequence (3 parts: hook, value, CTA)",
    "landing_page": "complete landing page copy (headline, sub, bullets, social proof, CTA)",
    "press_release": "professional press release optimized for syndication",
    "ad_copy": "multi-variant ad copy (Google + Meta + TikTok versions)",
}


class ContentGeneratorBot(BaseBot):
    """Generates ultra high-quality, revenue-focused content with affiliate links."""

    def __init__(self):
        super().__init__("01_content_generator", "marketing")

    def run(self, topic: str = None, content_type: str = None,
            word_count: int = None, tone: str = None,
            keywords: str = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("default_topic") or random.choice(VIRAL_TOPICS)
        content_type = content_type or cfg.get("default_type", "blog_post")
        word_count = word_count or cfg.get("word_count", 1200)
        tone = tone or cfg.get("tone", "bold, authoritative, conversational, action-oriented")
        keywords = keywords or cfg.get("keywords", "AI tools, passive income, affiliate marketing, automation")

        self.logger.info(f"Generating {content_type} on: {topic}")

        ct_label = CONTENT_TYPES.get(content_type, "content piece")

        system = f"""You are {AUTHOR}, a top-tier content creator, affiliate marketer, and AI entrepreneur behind {BRAND}.
You write content that goes viral, ranks on Google, and converts readers into buyers.

Your content philosophy:
- Hook in the first sentence — no warm-up, no filler
- Every paragraph must add value or it gets cut
- Affiliate links feel like recommendations from a trusted friend, never like ads
- SEO keywords woven in naturally, never forced
- Call-to-action that creates desire, not pressure
- Specific, credible, actionable — not generic, not vague

You are obsessed with helping readers make money and achieve financial freedom."""

        prompt = f"""Create a {ct_label} with this exact brief:

**TOPIC:** {topic}
**TARGET LENGTH:** ~{word_count} words
**TONE:** {tone}
**PRIMARY KEYWORDS:** {keywords}

## Affiliate Links to Embed Naturally (contextually relevant only)
- Robinhood — commission-free investing: {ROBINHOOD_URL}
- Coinbase — easiest crypto on-ramp, $10 BTC bonus: {COINBASE_URL}
- Amazon (tag: {AMAZON_TAG}) — relevant books/tools
- WheellsVerse AI Blueprint (lead magnet): {CTA_URL}

## Structure Requirements
1. **Magnetic headline** — make it impossible to scroll past
2. **Hook paragraph** — first 50 words must create an emotional pull
3. **Body** — H2/H3 structure, short punchy paragraphs, bullet points where they aid clarity
4. **Proof/Examples** — real numbers, specific outcomes (use plausible, credible estimates)
5. **Affiliate integrations** — 2-4 links woven in where they genuinely serve the reader
6. **CTA** — clear, benefit-focused, urgent without being fake

## Additional Outputs
After the main content, also provide:
- **Meta description** (155 chars, includes primary keyword)
- **3 A/B headline variants** (for testing)
- **Twitter/X thread hook** (first tweet that makes people click "see more")

Format as clean Markdown. Make it so good it gets shared."""

        content = self.ai(
            prompt, system=system,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=3500
        )

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:50])

        output = f"""---
title: "{topic}"
type: {content_type}
author: {AUTHOR}
brand: {BRAND}
tone: {tone}
generated: {ts}
keywords: {keywords}
---

{content}

---
*Generated by {BRAND} Content Intelligence Engine — Bot #01*
"""
        fname = f"{content_type}_{safe_topic}.md"
        path = self.save_output(output, fname, ext="md")
        word_ct = len(content.split())
        self.logger.info(f"Saved → {path} ({word_ct} words)")
        return {"file": str(path), "word_count": word_ct, "type": content_type, "topic": topic}

    def batch_generate(self, topics: list, content_type: str = "blog_post") -> list:
        results = []
        for t in topics:
            try:
                results.append(self.execute(topic=t, content_type=content_type))
            except Exception as e:
                results.append({"error": str(e), "topic": t})
        return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Content Generator Bot (Ultra)")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--type", type=str, default="blog_post",
                        choices=list(CONTENT_TYPES.keys()))
    parser.add_argument("--words", type=int, default=1200)
    parser.add_argument("--tone", type=str, default=None)
    parser.add_argument("--keywords", type=str, default=None)
    args = parser.parse_args()
    bot = ContentGeneratorBot()
    result = bot.execute(topic=args.topic, content_type=args.type,
                         word_count=args.words, tone=args.tone,
                         keywords=args.keywords)
    print(f"\n✅ Output: {result['file']}")
    print(f"   Words:  {result['word_count']}")
