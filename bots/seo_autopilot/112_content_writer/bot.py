#!/usr/bin/env python3
"""bots/seo_autopilot/112_content_writer/bot.py — SEO content writer"""
import sys
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class SEOContentWriterBot(BaseBot):
    """Generates full SEO-optimized articles from a target keyword using Claude."""

    def __init__(self):
        super().__init__("112_content_writer", "seo_autopilot")

    def run(self, keyword=None, word_count=None, tone=None, **kwargs):
        cfg = self.config
        keyword = keyword or cfg.get("default_keyword", "best passive income ideas 2025")
        word_count = int(word_count or cfg.get("word_count", 2000))
        tone = tone or cfg.get("tone", "authoritative, helpful, engaging")

        self.logger.info(f"Writing SEO article for keyword: '{keyword}' (~{word_count} words)")

        system_prompt = (
            f"You are an expert SEO content writer. Write a comprehensive, SEO-optimized "
            f"article targeting the keyword: '{keyword}'. Requirements: "
            f"1) Keyword-rich H1 title "
            f"2) Meta description (150 chars) "
            f"3) 4-6 H2 sections with keyword variations "
            f"4) FAQ section with 5 Q&A pairs "
            f"5) Strong CTA at the end "
            f"6) ~{word_count} words. "
            f"Tone: {tone}. "
            f"Format as clean Markdown. Start with a YAML frontmatter block:\n"
            f"---\ntitle: ...\nmeta_description: ...\ntarget_keyword: ...\n---"
        )

        user_prompt = (
            f"Write a full SEO article for keyword: {keyword}\n"
            f"Target word count: {word_count}\n"
            f"Tone: {tone}\n\n"
            f"Include:\n"
            f"- YAML frontmatter (title, meta_description, target_keyword)\n"
            f"- Keyword-rich H1\n"
            f"- Introduction paragraph with keyword in first 100 words\n"
            f"- 4-6 H2 sections with keyword variations and supporting content\n"
            f"- FAQ section with 5 Q&A pairs\n"
            f"- Strong CTA at the end\n"
            f"Return only the Markdown article, nothing else."
        )

        article = self.claude(user_prompt, system=system_prompt, max_tokens=6000)

        # Count actual words (excluding frontmatter markers)
        text_only = re.sub(r"^---.*?---", "", article, flags=re.DOTALL).strip()
        actual_word_count = len(text_only.split())

        self.logger.info(f"Article generated — {actual_word_count} words")

        # Try to store in SQLite
        try:
            from core.db import get_db
            db = get_db()
            now = datetime.now().isoformat()
            record = {
                "keyword": keyword,
                "word_count": actual_word_count,
                "status": "draft",
                "created_at": now,
                "updated_at": now,
            }
            db["articles"].insert(record, alter=True)
            self.logger.info("Article record stored in SQLite articles table")
        except Exception as e:
            self.logger.warning(f"Could not store article in SQLite: {e}")

        # Save output
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r"[^\w]+", "_", keyword.lower())[:50]
        fname = f"article_{safe_kw}_{ts}.md"
        path = self.save_output(article, fname, ext="md")

        self.logger.info(f"Article saved -> {path}")
        return {
            "file": str(path),
            "keyword": keyword,
            "word_count": actual_word_count,
        }


if __name__ == "__main__":
    bot = SEOContentWriterBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    print(f"Keyword: {result['keyword']}")
    print(f"Word count: {result['word_count']}")
