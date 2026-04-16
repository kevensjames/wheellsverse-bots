#!/usr/bin/env python3
"""bots/aeo/102_aeo_audit/bot.py — AEO audit: scores content for AI answer engine readiness (0-100)"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db, ensure_tables  # noqa: E402

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


class AEOAuditBot(BaseBot):
    """Audits a web page and scores it for AI Answer Engine Optimization readiness."""

    def __init__(self):
        super().__init__("102_aeo_audit", "aeo")

    # ─── Scoring helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _score_faq(soup: BeautifulSoup) -> int:
        """FAQ score (0-20): FAQ sections, <details>/<summary>, FAQ headings, FAQ schema."""
        score = 0

        # Check for <details>/<summary> elements
        details = soup.find_all("details")
        if details:
            score += min(len(details), 5)  # up to 5 pts

        # Check for headings containing "FAQ" or "Frequently Asked"
        faq_headings = soup.find_all(re.compile(r"^h[1-6]$"), string=re.compile(r"(?i)faq|frequently\s+asked"))
        if faq_headings:
            score += 5

        # Check for schema FAQ markup in JSON-LD
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "FAQPage":
                    score += 7
                    break
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "FAQPage":
                            score += 7
                            break
            except (json.JSONDecodeError, TypeError):
                continue

        # Check for FAQ-like sections (divs with Q&A patterns)
        text = soup.get_text(" ", strip=True).lower()
        qa_patterns = re.findall(r"\b(?:q:|question:|a:|answer:)\s", text)
        if len(qa_patterns) >= 4:
            score += 3

        return min(score, 20)

    @staticmethod
    def _score_schema(soup: BeautifulSoup) -> int:
        """Schema score (0-20): structured data presence and richness."""
        score = 0
        ld_scripts = soup.find_all("script", {"type": "application/ld+json"})

        if not ld_scripts:
            return 0

        score += 5  # baseline for having any structured data

        schema_types = set()
        for script in ld_scripts:
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        t = item.get("@type", "")
                        if isinstance(t, list):
                            schema_types.update(t)
                        else:
                            schema_types.add(t)
            except (json.JSONDecodeError, TypeError):
                continue

        # Bonus for rich schema types
        valuable_types = {"FAQPage", "HowTo", "Article", "BlogPosting", "Product",
                          "Review", "Recipe", "BreadcrumbList", "Organization",
                          "WebPage", "ItemList"}
        found_valuable = schema_types & valuable_types
        score += min(len(found_valuable) * 3, 9)

        # Bonus for multiple schema blocks
        if len(ld_scripts) >= 2:
            score += 3
        if len(ld_scripts) >= 4:
            score += 3

        return min(score, 20)

    @staticmethod
    def _score_qa_headings(soup: BeautifulSoup) -> int:
        """QA score (0-15): question-like headings."""
        question_words = re.compile(r"(?i)\b(how|what|why|when|which|where|who|can|do|does|is|are|should)\b")
        headings = soup.find_all(re.compile(r"^h[2-3]$"))
        question_headings = 0
        for h in headings:
            text = h.get_text(strip=True)
            if "?" in text or question_words.search(text):
                question_headings += 1

        if question_headings >= 8:
            return 15
        if question_headings >= 5:
            return 12
        if question_headings >= 3:
            return 9
        if question_headings >= 1:
            return 5
        return 0

    @staticmethod
    def _score_format(soup: BeautifulSoup) -> int:
        """Format score (0-15): lists, tables, structured elements."""
        ul_count = len(soup.find_all("ul"))
        ol_count = len(soup.find_all("ol"))
        table_count = len(soup.find_all("table"))
        total = ul_count + ol_count + table_count

        if total >= 8:
            return 15
        if total >= 5:
            return 12
        if total >= 3:
            return 9
        if total >= 1:
            return 5
        return 0

    @staticmethod
    def _score_meta(soup: BeautifulSoup) -> int:
        """Meta score (0-10): meta description presence and optimal length."""
        meta = soup.find("meta", attrs={"name": "description"})
        if not meta:
            return 0
        content = meta.get("content", "")
        length = len(content)
        if 120 <= length <= 160:
            return 10
        if 80 <= length <= 200:
            return 7
        if length > 0:
            return 4
        return 0

    @staticmethod
    def _score_headings(soup: BeautifulSoup) -> int:
        """Heading score (0-10): H1 exists, proper hierarchy."""
        score = 0
        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        h3s = soup.find_all("h3")

        if len(h1s) == 1:
            score += 4  # exactly one H1 is ideal
        elif len(h1s) >= 1:
            score += 2  # at least one H1

        if h2s:
            score += 3  # has H2 structure
        if h3s:
            score += 3  # has H3 for deeper hierarchy

        return min(score, 10)

    @staticmethod
    def _score_length(soup: BeautifulSoup) -> int:
        """Length score (0-10): word count of page content."""
        text = soup.get_text(" ", strip=True)
        word_count = len(text.split())
        if word_count > 1500:
            return 10
        if word_count > 1000:
            return 7
        if word_count > 500:
            return 4
        return 0

    # ─── Main run ────────────────────────────────────────────────────────────

    def run(self, url=None, domain=None, **kwargs):
        url = url or self.config.get("default_url", "https://wheellsverse-bots.pages.dev")
        if domain and not url:
            url = f"https://{domain}"

        parsed = urlparse(url)
        domain = domain or parsed.netloc or parsed.path.split("/")[0]

        self.logger.info(f"Auditing AEO readiness: {url}")

        # Fetch page
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WheellsVerse-AEO-Audit/1.0)"}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as fetch_err:
            self.logger.warning(f"Could not fetch {url}: {fetch_err} — running audit on placeholder content")
            soup = BeautifulSoup(f"<html><head><title>{domain}</title></head><body><h1>{domain}</h1></body></html>", "html.parser")

        # Calculate scores
        faq_score = self._score_faq(soup)
        schema_score = self._score_schema(soup)
        qa_score = self._score_qa_headings(soup)
        format_score = self._score_format(soup)
        meta_score = self._score_meta(soup)
        heading_score = self._score_headings(soup)
        length_score = self._score_length(soup)

        total = faq_score + schema_score + qa_score + format_score + meta_score + heading_score + length_score

        scanned_at = datetime.now().isoformat()

        # Store in SQLite
        ensure_tables()
        db = get_db()
        db["aeo_scores"].insert({
            "domain": domain,
            "url": url,
            "score": total,
            "faq_score": faq_score,
            "schema_score": schema_score,
            "qa_score": qa_score,
            "format_score": format_score,
            "meta_score": meta_score,
            "heading_score": heading_score,
            "length_score": length_score,
            "scanned_at": scanned_at,
        })
        self.logger.info(f"AEO score stored: {total}/100 for {domain}")

        # Generate recommendations
        recommendations = []
        if faq_score < 10:
            recommendations.append("- **Add an FAQ section** with 5-10 Q&A pairs using `<details>`/`<summary>` tags and FAQPage schema")
        if schema_score < 10:
            recommendations.append("- **Add structured data** (JSON-LD): FAQPage, Article, HowTo, BreadcrumbList")
        if qa_score < 8:
            recommendations.append("- **Use question-based H2/H3 headings** ('How to...', 'What is...', 'Why should...')")
        if format_score < 8:
            recommendations.append("- **Add structured formatting**: numbered lists, bullet points, comparison tables")
        if meta_score < 7:
            recommendations.append("- **Optimize meta description** to 120-160 characters with target keywords")
        if heading_score < 7:
            recommendations.append("- **Fix heading hierarchy**: ensure exactly one H1, with logical H2/H3 nesting")
        if length_score < 7:
            recommendations.append("- **Increase content length** to 1500+ words for comprehensive coverage")

        grade = "A+" if total >= 90 else "A" if total >= 80 else "B" if total >= 70 else "C" if total >= 60 else "D" if total >= 50 else "F"

        # Build report
        report = f"""# AEO Audit Report
**URL:** {url}
**Domain:** {domain}
**Scanned:** {scanned_at[:19]}
**Overall Score:** {total}/100 (Grade: {grade})

---

## Score Breakdown

| Category | Score | Max | Status |
|----------|-------|-----|--------|
| FAQ Sections | {faq_score} | 20 | {"PASS" if faq_score >= 10 else "NEEDS WORK"} |
| Structured Data (Schema) | {schema_score} | 20 | {"PASS" if schema_score >= 10 else "NEEDS WORK"} |
| Question Headings (Q&A) | {qa_score} | 15 | {"PASS" if qa_score >= 8 else "NEEDS WORK"} |
| Formatting (Lists/Tables) | {format_score} | 15 | {"PASS" if format_score >= 8 else "NEEDS WORK"} |
| Meta Description | {meta_score} | 10 | {"PASS" if meta_score >= 7 else "NEEDS WORK"} |
| Heading Hierarchy | {heading_score} | 10 | {"PASS" if heading_score >= 7 else "NEEDS WORK"} |
| Content Length | {length_score} | 10 | {"PASS" if length_score >= 7 else "NEEDS WORK"} |
| **TOTAL** | **{total}** | **100** | **{grade}** |

---

## Recommendations

{chr(10).join(recommendations) if recommendations else "Great job! All categories are performing well."}

---

## What is AEO?

Answer Engine Optimization (AEO) ensures your content is structured so AI-powered
search engines (ChatGPT, Perplexity, Google AI Overview, Bing Copilot) can extract
and cite your answers directly. Higher AEO scores correlate with more AI mentions.

---
*Generated by WheellsVerse AEO Audit Bot*
"""
        safe_domain = re.sub(r"[^a-zA-Z0-9]", "_", domain)[:40]
        fname = f"aeo_audit_{safe_domain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(report, fname, ext="md")

        return {"file": str(path), "score": total, "url": url}


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AEO Audit Bot")
    parser.add_argument("--url", type=str, default=None, help="URL to audit")
    parser.add_argument("--domain", type=str, default=None, help="Domain to audit")
    args = parser.parse_args()

    bot = AEOAuditBot()
    result = bot.execute(url=args.url, domain=args.domain)
    print(f"\nOutput: {result['file']}")
    print(f"Score:  {result['score']}/100")
    print(f"URL:    {result['url']}")
