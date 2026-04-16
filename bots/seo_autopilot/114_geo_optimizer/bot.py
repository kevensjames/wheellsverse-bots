#!/usr/bin/env python3
"""bots/seo_autopilot/114_geo_optimizer/bot.py — GEO (Generative Engine Optimization) optimizer"""
import sys
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class GEOOptimizerBot(BaseBot):
    """
    Rewrites content to maximize visibility in AI-powered answer engines
    (ChatGPT, Perplexity, Google AI Overviews).
    Adds Quick Answer box, FAQ section, comparison tables, step-by-step lists,
    key takeaways, and JSON-LD FAQPage schema.
    """

    def __init__(self):
        super().__init__("114_geo_optimizer", "seo_autopilot")

    def run(self, file_path=None, content=None, keyword=None, **kwargs):
        # Resolve content source
        if file_path:
            src = Path(file_path)
            if not src.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            content = src.read_text(encoding="utf-8")
            self.logger.info(f"Loaded content from file: {file_path}")
            if not keyword:
                # Try to extract keyword from frontmatter
                fm_match = re.search(
                    r"^---.*?target_keyword:\s*(.+?)\s*\n.*?---", content, re.DOTALL
                )
                if fm_match:
                    keyword = fm_match.group(1).strip()
        elif content:
            self.logger.info("Using provided content string")
        else:
            # Generate a short demonstration article
            kw = keyword or "passive income ideas"
            self.logger.info(f"No content provided — generating demo article on: {kw}")
            content = self.ai(
                f"Write a 400-word introductory article about: {kw}. "
                f"Include a title, 3 short sections, and a conclusion.",
                system="You are a helpful content writer. Return only the article text.",
                max_tokens=800,
            )

        keyword = keyword or "article topic"
        self.logger.info(f"Running GEO optimization for keyword: '{keyword}'")

        # Enhance content with GEO techniques
        system_prompt = (
            "You are a GEO (Generative Engine Optimization) expert. "
            "Rewrite the following content to maximize visibility in AI-powered answer engines "
            "(ChatGPT, Perplexity, Google AI Overviews). "
            "Add: "
            "1) 'Quick Answer' box at top (2-3 sentence direct answer) "
            "2) FAQ section with 5+ Q&A pairs "
            "3) Comparison table if topic allows "
            "4) Step-by-step numbered list where appropriate "
            "5) Key takeaways section. "
            "Keep the same meaning and topic. "
            "Format as clean Markdown."
        )

        user_prompt = (
            f"Keyword/topic: {keyword}\n\n"
            f"Original content:\n\n{content}\n\n"
            f"Rewrite and enhance this content with all GEO elements described. "
            f"Return only the enhanced Markdown content."
        )

        enhanced = self.claude(user_prompt, system=system_prompt, max_tokens=6000)
        self.logger.info("GEO-enhanced content generated")

        # Extract FAQ pairs for JSON-LD schema
        faq_pairs = self._extract_faq_pairs(enhanced)
        json_ld = self._build_faq_schema(faq_pairs, keyword)
        json_ld_block = f"\n\n```json\n{json.dumps(json_ld, indent=2, ensure_ascii=False)}\n```"

        final_output = enhanced + json_ld_block

        # Save output
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r"[^\w]+", "_", keyword.lower())[:50]
        fname = f"geo_optimized_{safe_kw}_{ts}.md"
        path = self.save_output(final_output, fname, ext="md")

        self.logger.info(f"GEO optimized article saved -> {path}")
        return {
            "file": str(path),
            "action": "optimize",
            "keyword": keyword,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_faq_pairs(self, markdown: str) -> list:
        """
        Extract Q&A pairs from markdown FAQ section.
        Supports patterns like:
          ### Q: ...  \n A: ...
          **Q:** ...  \n **A:** ...
          #### Question  \n Answer text
        Falls back to heading + next paragraph if no explicit Q/A markers found.
        """
        pairs = []

        # Pattern 1: explicit Q: / A: markers (with or without bold)
        pattern1 = re.finditer(
            r"(?:\*{0,2}Q(?:uestion)?[:\.\s]+\*{0,2})\s*(.+?)\s*\n+(?:\*{0,2}A(?:nswer)?[:\.\s]+\*{0,2})\s*(.+?)(?=\n\n|\n#{1,4}|\Z)",
            markdown, re.DOTALL | re.IGNORECASE
        )
        for m in pattern1:
            q = m.group(1).strip().lstrip("#").strip()
            a = m.group(2).strip()
            if q and a:
                pairs.append({"question": q, "answer": a})

        if pairs:
            return pairs[:10]

        # Pattern 2: FAQ-style headings (### or ####) followed by answer paragraphs
        pattern2 = re.finditer(
            r"#{2,4}\s+(.+?)\n+([^#\n].+?)(?=\n#{2,4}|\Z)",
            markdown, re.DOTALL
        )
        for m in pattern2:
            q = m.group(1).strip()
            a = re.sub(r"\n+", " ", m.group(2)).strip()
            # Only include if question-like (ends with ? or contains common question words)
            if "?" in q or re.search(r"\b(what|how|why|when|where|which|can|does|is|are)\b", q, re.I):
                pairs.append({"question": q, "answer": a[:300]})

        return pairs[:10]

    def _build_faq_schema(self, pairs: list, keyword: str) -> dict:
        """Build a JSON-LD FAQPage schema object from Q&A pairs."""
        if not pairs:
            # Generate a minimal FAQ schema with a placeholder if no pairs found
            pairs = [
                {"question": f"What is {keyword}?",
                 "answer": f"{keyword} is an important topic covered in this article."},
                {"question": f"How does {keyword} work?",
                 "answer": f"See the full article above for a detailed explanation of {keyword}."},
            ]

        schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": pair["question"],
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": pair["answer"],
                    },
                }
                for pair in pairs
            ],
        }
        return schema


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="Path to markdown article to optimize")
    parser.add_argument("--keyword", default=None, help="Target keyword")
    args = parser.parse_args()

    bot = GEOOptimizerBot()
    result = bot.execute(file_path=args.file, keyword=args.keyword)
    print(f"Output: {result['file']}")
    print(f"Keyword: {result['keyword']}")
