#!/usr/bin/env python3
"""
Bot #46 — Long-Form Blog Article Writer
Category: Writing
Purpose: Write complete, SEO-optimized long-form blog articles with proper structure,
         internal linking suggestions, meta data, and readability optimization.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

BLOG_TYPES = {
    "how_to": "Step-by-step tutorial with actionable instructions",
    "listicle": "Numbered or bulleted list article with depth per item",
    "opinion": "Thought leadership piece with a clear stance and argument",
    "case_study": "Real-world example with problem, approach, and results",
    "comparison": "X vs Y analysis to help readers make a decision",
    "ultimate_guide": "Comprehensive reference guide covering a topic in full",
    "news_analysis": "Current event or trend with expert commentary",
    "interview": "Q&A or curated expert insights format",
}

WORD_COUNT_MAP = {
    "short": "800-1200",
    "medium": "1500-2000",
    "long": "2500-3500",
    "pillar": "4000-6000",
}


class BlogWriterBot(BaseBot):

    def __init__(self):
        super().__init__("46_blog_writer", "writing")

    def run(self, topic: str = None, target_keyword: str = None,
            word_count: str = None, audience: str = None,
            blog_type: str = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("topic", "10 Ways AI Will Transform Small Business in 2025")
        target_keyword = target_keyword or cfg.get("target_keyword", "AI for small business")
        word_count = word_count or cfg.get("word_count", "medium")
        audience = audience or cfg.get("audience", "entrepreneurs and small business owners")
        blog_type = blog_type or cfg.get("blog_type", "listicle")

        type_desc = BLOG_TYPES.get(blog_type, blog_type)
        wc_range = WORD_COUNT_MAP.get(word_count, word_count)

        self.logger.info(f"Writing {blog_type} blog post: {topic}")

        system = (
            "You are a professional content writer and SEO strategist who writes blog articles "
            "that rank on Google AND get read by humans. You know that search engines reward "
            "content that satisfies user intent — so you write for people first, algorithms second. "
            "You structure articles with clear hierarchies (H1/H2/H3), use short paragraphs for "
            "readability, include specific data and examples, and embed natural keyword usage "
            "without stuffing. You understand the E-E-A-T principle: Experience, Expertise, "
            "Authoritativeness, Trustworthiness. Every article you write demonstrates all four."
        )

        prompt = f"""Write a complete, publish-ready long-form blog article:

TOPIC: {topic}
TARGET KEYWORD: {target_keyword}
WORD COUNT: {wc_range} words
AUDIENCE: {audience}
ARTICLE TYPE: {blog_type} — {type_desc}
BRAND: WheellsVerse — AI automation tools for entrepreneurs

---

## SEO META BLOCK

**Title tag (under 60 chars):** [Keyword-optimized title]
**Meta description (under 155 chars):** [Compelling description with target keyword]
**URL slug:** [url-friendly-slug]
**Target keyword:** {target_keyword}
**Secondary keywords:** [5 related keywords to weave in naturally]
**Search intent:** [Informational / Commercial / Navigational / Transactional]
**Estimated read time:** [X minutes]

---

## THE FULL ARTICLE

# [H1: Article Title]

*[Optional 1-sentence intro hook — the "why this matters" moment]*

## Introduction (150-200 words)
[Hook → Problem → Promise of what this article will teach them]

---

[Full article body structured for a {blog_type} with H2 and H3 subheadings.
Target {wc_range} words total.
Use short paragraphs (2-4 sentences max).
Include specific examples, data points, and actionable advice.
Naturally use "{target_keyword}" and secondary keywords.]

---

## Conclusion (100-150 words)
[Summarize key takeaways → reinforce value → clear CTA]

**[CTA Box]:**
> [Call to action — drive to WheellsVerse product or email signup]

---

## POST-PUBLISH CHECKLIST

Before hitting publish, verify:
- [ ] Target keyword in H1, first paragraph, one H2, meta description
- [ ] All H2s answer a specific sub-question or search intent
- [ ] Article has at least one original insight (not just restated info)
- [ ] Internal links: [2-3 suggested anchor texts + what to link to]
- [ ] External links: [1-2 authoritative sources to cite]
- [ ] Featured image alt text: [Suggested alt text]
- [ ] Word count meets target: {wc_range}
- [ ] Reading level: Grade 8 or below (Flesch-Kincaid)

## CONTENT UPGRADE IDEAS

Bonus content to offer readers for email capture:
1. [Upgrade idea 1 — e.g., downloadable checklist, template, or cheat sheet]
2. [Upgrade idea 2]

## REPURPOSING PLAN

| Format | Platform | Angle |
| Twitter thread | Twitter | [Key thread hook] |
| Carousel | LinkedIn/Instagram | [Top 5 points] |
| Short video | TikTok/Reels | [Best 60-second hook from this article] |
| Email | Newsletter | [Subject line + first paragraph] |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=3500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:25])

        output = f"""# Blog Article: {topic}
**Type:** {blog_type}
**Target Keyword:** {target_keyword}
**Word Count:** {wc_range}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Blog Writer Bot*
"""
        path = self.save_output(output, f"blog_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Blog article saved → {path}")
        return {"file": str(path), "topic": topic, "keyword": target_keyword}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Long-Form Blog Article Writer")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--keyword", type=str, default=None)
    parser.add_argument("--length", type=str, default="medium",
                        choices=list(WORD_COUNT_MAP.keys()))
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--type", type=str, default="listicle",
                        choices=list(BLOG_TYPES.keys()))
    args = parser.parse_args()
    bot = BlogWriterBot()
    result = bot.execute(topic=args.topic, target_keyword=args.keyword,
                         word_count=args.length, audience=args.audience,
                         blog_type=args.type)
    print(f"\n✅ Blog Article: {result['file']}")
