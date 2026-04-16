#!/usr/bin/env python3
"""bots/aeo/103_aeo_editor/bot.py — AEO editor: rewrites content for AI answer engines + generates JSON-LD schema"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


class AEOEditorBot(BaseBot):
    """Rewrites content to maximize visibility in AI-powered answer engines and generates FAQPage JSON-LD."""

    def __init__(self):
        super().__init__("103_aeo_editor", "aeo")

    def _fetch_content_from_url(self, url: str) -> str:
        """Fetch a URL and extract readable text content."""
        headers = {"User-Agent": "WheellsVerse-AEO-Editor/1.0"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Try to get main content area first
        main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile(r"content|post|entry"))
        if main:
            text = main.get_text("\n", strip=True)
        else:
            text = soup.get_text("\n", strip=True)

        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_qa_pairs(self, content: str) -> list:
        """Extract question-answer pairs from rewritten content for JSON-LD."""
        pairs = []

        # Pattern 1: Q: ... A: ... style
        qa_matches = re.findall(
            r"(?:^|\n)\s*(?:\*\*)?(?:Q|Question)[:\.]?\s*(?:\*\*)?\s*(.+?)(?:\n\s*(?:\*\*)?(?:A|Answer)[:\.]?\s*(?:\*\*)?\s*(.+?)(?=\n\s*(?:\*\*)?(?:Q|Question)[:\.]|\n##|\Z))",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        for q, a in qa_matches:
            q_clean = q.strip().rstrip("?") + "?"
            a_clean = re.sub(r"\s+", " ", a.strip())[:500]
            if len(q_clean) > 5 and len(a_clean) > 10:
                pairs.append({"question": q_clean, "answer": a_clean})

        # Pattern 2: ### heading with ? followed by paragraph
        heading_matches = re.findall(
            r"#{2,3}\s+(.+?\?)\s*\n+([^#]+?)(?=\n#{2,3}|\Z)",
            content,
            re.DOTALL,
        )
        for q, a in heading_matches:
            q_clean = q.strip()
            a_clean = re.sub(r"\s+", " ", a.strip())[:500]
            if len(q_clean) > 5 and len(a_clean) > 10:
                # Avoid duplicates
                if not any(p["question"].lower() == q_clean.lower() for p in pairs):
                    pairs.append({"question": q_clean, "answer": a_clean})

        # Pattern 3: Numbered Q&A (1. Question? \n Answer text)
        numbered_matches = re.findall(
            r"\d+\.\s+(.+?\?)\s*\n+([^0-9#]+?)(?=\d+\.|\Z)",
            content,
            re.DOTALL,
        )
        for q, a in numbered_matches:
            q_clean = q.strip()
            a_clean = re.sub(r"\s+", " ", a.strip())[:500]
            if len(q_clean) > 5 and len(a_clean) > 10:
                if not any(p["question"].lower() == q_clean.lower() for p in pairs):
                    pairs.append({"question": q_clean, "answer": a_clean})

        return pairs[:10]  # Limit to 10 pairs

    def _build_faq_schema(self, pairs: list) -> dict:
        """Build FAQPage JSON-LD schema from Q&A pairs."""
        main_entity = []
        for pair in pairs:
            main_entity.append({
                "@type": "Question",
                "name": pair["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": pair["answer"],
                },
            })

        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": main_entity,
        }

    def run(self, content=None, file_path=None, url=None, **kwargs):
        # Priority: file_path > url > content > AI-generated default
        source = "generated"

        if file_path:
            fp = Path(file_path)
            if not fp.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            content = fp.read_text(encoding="utf-8")
            source = f"file:{fp.name}"
            self.logger.info(f"Reading content from file: {file_path}")
        elif url:
            content = self._fetch_content_from_url(url)
            source = f"url:{url}"
            self.logger.info(f"Fetched content from URL: {url}")
        elif content:
            source = "provided"
            self.logger.info("Using provided content string")
        else:
            # Generate sample content on default topic
            topic = self.config.get("default_topic", "passive income strategies 2025")
            self.logger.info(f"No input provided, generating sample content on: {topic}")
            content = self.ai(
                f"Write a 600-word informational article about {topic}. Include practical tips, examples, and actionable advice. Format as plain text with basic headings.",
                system="You are a knowledgeable content writer. Write informative, engaging articles.",
                max_tokens=1500,
            )
            source = f"generated:{topic}"

        # Truncate if extremely long to manage API costs
        original_length = len(content.split())
        if original_length > 3000:
            words = content.split()[:3000]
            content = " ".join(words)
            self.logger.info(f"Truncated input from {original_length} to 3000 words for API processing")

        self.logger.info(f"Rewriting content for AEO ({len(content.split())} words, source: {source})")

        # Rewrite content for AEO
        system_prompt = (
            "You are an Answer Engine Optimization expert. Rewrite the following content "
            "to maximize visibility in AI-powered answer engines (ChatGPT, Perplexity, "
            "Google AI Overview). Add: "
            "1) FAQ section with 5+ Q&A pairs "
            "2) Direct answer blocks (concise 2-3 sentence answers) "
            "3) Structured lists and tables "
            "4) Clear H2/H3 heading hierarchy. "
            "Keep the same topic and meaning."
        )

        rewritten = self.ai(
            f"Rewrite this content for maximum AEO visibility:\n\n{content}",
            system=system_prompt,
            max_tokens=3000,
            temperature=0.6,
        )

        # Extract Q&A pairs and build JSON-LD
        qa_pairs = self._extract_qa_pairs(rewritten)

        # If extraction found fewer than 3 pairs, try AI extraction as fallback
        if len(qa_pairs) < 3:
            self.logger.info("Few Q&A pairs extracted via regex, using AI to extract from rewritten content")
            try:
                qa_json = self.ai_json(
                    f"Extract all question-and-answer pairs from this content. Return a JSON array of objects with 'question' and 'answer' keys:\n\n{rewritten}",
                    system="Extract Q&A pairs from the content. Return valid JSON: [{\"question\": \"...\", \"answer\": \"...\"}]",
                )
                if isinstance(qa_json, list):
                    qa_pairs = qa_json[:10]
                elif isinstance(qa_json, dict) and "raw" not in qa_json:
                    # Might be wrapped
                    for key in qa_json:
                        if isinstance(qa_json[key], list):
                            qa_pairs = qa_json[key][:10]
                            break
            except Exception as e:
                self.logger.warning(f"AI Q&A extraction failed, using regex results: {e}")

        faq_schema = self._build_faq_schema(qa_pairs)
        schema_json = json.dumps(faq_schema, indent=2, ensure_ascii=False)

        # Build final output
        output = f"""# AEO-Optimized Content
**Source:** {source}
**Original word count:** {original_length}
**Rewritten word count:** {len(rewritten.split())}
**Q&A pairs extracted:** {len(qa_pairs)}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

{rewritten}

---

## JSON-LD FAQPage Schema

Paste this into your page's `<head>` section inside a `<script type="application/ld+json">` tag:

```json
{schema_json}
```

---

## Implementation Checklist

- [ ] Replace existing content with the AEO-optimized version above
- [ ] Add the JSON-LD FAQPage schema to `<head>`
- [ ] Ensure all H2/H3 headings use question format where possible
- [ ] Verify FAQ section renders correctly on mobile
- [ ] Test structured data with Google Rich Results Test
- [ ] Submit updated URL to Google Search Console for re-indexing

---
*Generated by WheellsVerse AEO Editor Bot*
"""
        safe_source = re.sub(r"[^a-zA-Z0-9]", "_", source)[:30]
        fname = f"aeo_rewrite_{safe_source}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(output, fname, ext="md")

        self.logger.info(f"AEO rewrite complete: {len(qa_pairs)} Q&A pairs, saved to {path}")
        return {"file": str(path), "action": "rewrite"}


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AEO Editor Bot")
    parser.add_argument("--file", type=str, default=None, help="Path to content file")
    parser.add_argument("--url", type=str, default=None, help="URL to fetch content from")
    parser.add_argument("--content", type=str, default=None, help="Direct content string")
    args = parser.parse_args()

    bot = AEOEditorBot()
    result = bot.execute(content=args.content, file_path=args.file, url=args.url)
    print(f"\nOutput: {result['file']}")
    print(f"Action: {result['action']}")
