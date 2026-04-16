#!/usr/bin/env python3
"""
Revenue Stream #7 — SEO Blog (AI Tools for Beginners)
Purpose: Publishes 1 SEO-optimized article daily to wheellsverse.com/blog.
         Targets high-value keywords: AI tools, passive income, crypto.
         Monetized via affiliate links + product CTAs.
         Organic Google traffic → affiliate commissions.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an expert SEO content writer who has helped websites go from 0 to
500,000 monthly organic visitors. You understand Google's EEAT requirements, keyword
intent, and content depth. Your articles rank because they genuinely answer questions
better than anything else on the web. You write for humans first and search engines
second. Your affiliate recommendations feel natural and trustworthy because you only
recommend what you'd use yourself. You specialize in AI tools, passive income,
crypto investing, and digital business content."""

ARTICLE_QUEUE = [
    ("Best Free AI Tools for Beginners in 2026", "free ai tools beginners 2026", "commercial"),
    ("How to Make Money with ChatGPT in 2026 (7 Proven Methods)", "make money chatgpt 2026", "commercial"),
    ("Coinbase vs Binance: Which Is Better for Beginners?", "coinbase vs binance beginners", "commercial"),
    ("What Is DeFi and How Does It Work? Complete Beginner Guide", "what is defi how does it work", "informational"),
    ("Best AI Writing Tools in 2026: Ranked and Reviewed", "best ai writing tools 2026", "commercial"),
    ("How to Earn Passive Income with Cryptocurrency", "passive income cryptocurrency", "commercial"),
    ("ChatGPT Prompts for Business: 50+ Templates That Work", "chatgpt prompts business", "informational"),
    ("Is Investing in Bitcoin Still Worth It in 2026?", "investing bitcoin 2026 worth it", "informational"),
    ("Best AI Tools for Social Media Management (Free + Paid)", "ai tools social media management", "commercial"),
    ("How to Start a Faceless YouTube Channel with AI", "faceless youtube channel ai", "how-to"),
    ("Crypto Staking Guide: Earn Passive Income Without Trading", "crypto staking passive income", "how-to"),
    ("Top 10 Side Hustles Using AI Tools in 2026", "side hustles ai tools 2026", "commercial"),
    ("How to Use Claude AI: Complete Beginner's Guide", "how to use claude ai beginner", "how-to"),
    ("Best Crypto Exchanges for Beginners (Low Fees, Safe)", "best crypto exchanges beginners", "commercial"),
    ("AI Automation Tools That Save 10+ Hours Per Week", "ai automation tools save time", "commercial"),
]


class SEOBlogBot(BaseBot):

    def __init__(self):
        super().__init__("07_seo_blog", "revenue")
        import os
        self.blog_url = os.getenv("BLOG_URL", "https://wheellsverse.com/blog")
        self.coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/wheellsverse")
        self.course_url = os.getenv("GUMROAD_COURSE_URL", "https://gum.co/wheellsverse-course")
        self.prompts_url = os.getenv("GUMROAD_PROMPT_BIBLE_URL", "https://gum.co/wheellsverse-prompts")

    def run(self, action: str = "write", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "write")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "write": self._write_article,
            "batch": self._article_batch,
            "outline": self._article_outline,
            "update": self._update_article,
            "internal": self._internal_links,
        }
        fn = actions.get(action, self._write_article)
        return fn(ts, **kwargs)

    def _write_article(self, ts: str, **kwargs) -> dict:
        article_idx = kwargs.get("article_idx", datetime.now().day % len(ARTICLE_QUEUE))
        title, keyword, intent = ARTICLE_QUEUE[article_idx]

        prompt = f"""Write a complete, SEO-optimized blog article for WheellsVerse.

TARGET KEYWORD: "{keyword}"
TITLE: {title}
SEARCH INTENT: {intent}
BLOG: {self.blog_url}

SEO Requirements:
- Include keyword in: H1, first 100 words, 1 H2, meta description, URL slug
- Keyword density: 1-1.5% (natural usage)
- Include LSI keywords related to {keyword}
- Word count: 1,800-2,200 words

Article structure:
# {title}

[META_DESCRIPTION: 155 chars with keyword and CTA]
[URL_SLUG: keyword-based, hyphens]

**Introduction** (150 words)
- Hook with surprising stat or question
- What they'll learn
- Why trust WheellsVerse on this topic

**[5-7 H2 sections]** (250-350 words each)
- Each answers a specific sub-question
- Include real examples, numbers, comparisons
- One affiliate mention per relevant section (natural)
  - Coinbase: {self.coinbase_url}
  - Prompt Bible: {self.prompts_url}
  - Mini-Course: {self.course_url}

**FAQ Section** (5 questions — targets "People Also Ask")
Q: [question]
A: [concise answer, 50-80 words]

**Conclusion** (100 words)
- Summary of key points
- Final CTA (affiliate or product)

**Author Note**: "Written by J.K. Blaze, founder of WheellsVerse"

EEAT elements to include:
- Specific data points with sources (mention "according to [source]")
- Personal experience statements
- Clear expertise signals"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=5000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "seo_articles"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_kw = keyword.replace(" ", "_").replace(",", "")[:50]
        (out_dir / f"{safe_kw}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"article_{ts}.md", ext="md")

        # Try to publish via PublishPipeline blog
        try:
            from core.publish_pipeline import PublishPipeline
            pp = PublishPipeline()
            pp.publish(result, platforms=["blog"], metadata={
                "title": title, "keyword": keyword, "type": "seo_article"
            })
        except Exception as e:
            self.logger.debug("Blog publish skipped: %s", e)

        return {"file": str(path), "action": "write", "title": title, "keyword": keyword}

    def _article_batch(self, ts: str, **kwargs) -> dict:
        """Write first 5 articles back-to-back."""
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "seo_articles"
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []

        for i, (title, keyword, intent) in enumerate(ARTICLE_QUEUE[:5]):
            prompt = f"""Write a complete SEO article (1,500 words):
Title: {title}
Keyword: "{keyword}"
Intent: {intent}

Include: H1 title, 5 H2 sections, FAQ (3 Qs), conclusion.
Natural affiliate mentions: Coinbase ({self.coinbase_url}), Prompt Bible ({self.prompts_url}).
EEAT signals: stats, examples, author expertise.
Write for humans who are genuinely searching for this info."""

            result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
            safe_kw = keyword.replace(" ", "_").replace(",", "")[:40]
            fpath = out_dir / f"article_{i + 1:02d}_{safe_kw}.md"
            fpath.write_text(f"# {title}\n\n{result}", encoding="utf-8")
            written.append(title)
            self.logger.info("Article %d/5 written: %s", i + 1, title)

        path = self.save_output(
            "# SEO Blog — First 5 Articles\n\n" + "\n".join(f"- {t}" for t in written),
            f"article_batch_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify("📝 SEO Blog — 5 Articles Written!\n" + "\n".join(f"• {t}" for t in written))
        except Exception:
            pass

        return {"file": str(path), "action": "batch", "count": len(written)}

    def _article_outline(self, ts: str, **kwargs) -> dict:
        """Create full 3-month content calendar with outlines."""
        articles_str = "\n".join(f"{i + 1}. {a[0]} [{a[1]}]" for i, a in enumerate(ARTICLE_QUEUE))
        prompt = f"""Create a 90-day SEO content calendar for WheellsVerse blog.

Planned articles (15 already queued):
{articles_str}

Content calendar:
1. PUBLISH SCHEDULE — 1 article/day, organized by content pillar
2. CONTENT PILLARS — 4 main topics (AI Tools, Passive Income, Crypto, Automation)
3. INTERNAL LINKING MAP — how articles link to each other
4. AFFILIATE INTEGRATION — where to naturally place Coinbase, Prompt Bible, Course links
5. FEATURED SNIPPET TARGETS — which articles can win a Google featured snippet
6. ADDITIONAL 15 ARTICLES — suggest 15 more based on keyword gaps

Revenue projection: at 10,000 monthly readers, 2% CTR on affiliates = 200 clicks/month."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"content_calendar_{ts}.md", ext="md")
        return {"file": str(path), "action": "outline"}

    def _update_article(self, ts: str, **kwargs) -> dict:
        """Refresh and update an existing article for Google freshness."""
        article_title = kwargs.get("title", ARTICLE_QUEUE[0][0])
        prompt = f"""Generate an "updated for 2026" section to append to an existing article: {article_title}

Update section (300 words):
- What changed in 2026 vs 2025
- New tools/platforms/rates to mention
- Updated statistics
- Any outdated information to correct
- New FAQ questions based on recent searches

Also generate:
- New meta description (2026 freshness signal)
- Update notice: "Last updated: {datetime.now().strftime('%B %d, %Y')}"
- Social share prompt to re-promote the updated article"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(result, f"article_update_{ts}.md", ext="md")
        return {"file": str(path), "action": "update"}

    def _internal_links(self, ts: str, **kwargs) -> dict:
        """Generate internal linking strategy."""
        articles_str = "\n".join(f"- {a[0]}" for a in ARTICLE_QUEUE)
        prompt = f"""Create an internal linking strategy for WheellsVerse blog.

Articles on the blog:
{articles_str}

Deliverable:
1. LINK CLUSTERS — group related articles that should link to each other
2. PILLAR-CLUSTER MAP — which articles are pillar pages vs cluster pages
3. ANCHOR TEXT VARIATIONS — 5 natural anchor text options per article
4. PRIORITY LINKS — which 10 internal links would have the most SEO impact
5. LINK INSERTION GUIDE — where in each article to naturally add links

Format as a reference guide for the content team."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"internal_links_{ts}.md", ext="md")
        return {"file": str(path), "action": "internal"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEO Blog Bot")
    parser.add_argument("--action", default="write",
                        choices=["write", "batch", "outline", "update", "internal"])
    parser.add_argument("--article-idx", type=int, default=None)
    args = parser.parse_args()
    bot = SEOBlogBot()
    result = bot.execute(action=args.action, article_idx=args.article_idx)
    print(f"\n✅ SEO Blog: {result['file']}")
