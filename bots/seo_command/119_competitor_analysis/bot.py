#!/usr/bin/env python3
"""bots/seo_command/119_competitor_analysis/bot.py — Competitor analysis bot"""
import sys
import re
from collections import Counter
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

# Common English stopwords to exclude from top-word analysis
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "shall", "can",
    "this", "that", "these", "those", "it", "its", "we", "you", "he", "she",
    "they", "i", "me", "my", "your", "our", "their", "his", "her", "not",
    "no", "as", "if", "so", "than", "when", "which", "who", "how", "what",
    "all", "any", "both", "each", "more", "most", "other", "some", "such",
    "only", "own", "same", "too", "very", "just", "also", "s", "t", "re",
    "ve", "ll", "d", "m", "com", "www", "http", "https",
}


class CompetitorAnalysisBot(BaseBot):
    """Fetches and analyzes competitor domains for keyword overlap and content gaps."""

    def __init__(self):
        super().__init__("119_competitor_analysis", "seo_command")

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _fetch_and_parse(self, domain: str) -> dict:
        """Fetch domain homepage and extract SEO signals. Returns a data dict."""
        import requests
        from bs4 import BeautifulSoup

        url = domain if domain.startswith("http") else f"https://{domain}"
        result = {
            "domain": domain,
            "url": url,
            "title": "N/A",
            "meta_description": "N/A",
            "h1_count": 0,
            "h2_count": 0,
            "word_count": 0,
            "top_words": [],
            "error": None,
        }

        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; WheellsVerseBot/1.0)"}
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            html = resp.text
        except requests.exceptions.RequestException as e:
            result["error"] = str(e)
            self.logger.warning(f"Failed to fetch {domain}: {e}")
            return result

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Title
            title_tag = soup.find("title")
            result["title"] = title_tag.get_text(strip=True) if title_tag else "N/A"

            # Meta description
            meta = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
            if meta:
                result["meta_description"] = meta.get("content", "N/A")[:200]

            # H1 / H2 counts
            result["h1_count"] = len(soup.find_all("h1"))
            result["h2_count"] = len(soup.find_all("h2"))

            # Visible text — remove scripts, styles, nav, footer
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ")
            words = re.findall(r"[a-z]{3,}", text.lower())
            result["word_count"] = len(words)

            # Top repeated words (excluding stopwords)
            filtered = [w for w in words if w not in _STOPWORDS]
            top = Counter(filtered).most_common(20)
            result["top_words"] = [w for w, _ in top]

        except Exception as e:
            result["error"] = f"Parse error: {e}"
            self.logger.warning(f"Parse error for {domain}: {e}")

        return result

    def _build_analysis_prompt(self, your_domain: str, your_data: dict,
                                competitor_data: list) -> str:
        """Build the detailed prompt for Claude's strategic analysis."""
        lines = [
            f"Your domain: {your_domain}",
            f"  Title: {your_data.get('title', 'N/A')}",
            f"  Meta: {your_data.get('meta_description', 'N/A')}",
            f"  H1s: {your_data.get('h1_count', 0)}, H2s: {your_data.get('h2_count', 0)}",
            f"  Word count: {your_data.get('word_count', 0)}",
            f"  Top words: {', '.join(your_data.get('top_words', [])[:10])}",
            "",
            "Competitors:",
        ]
        for c in competitor_data:
            if c.get("error"):
                lines.append(f"\n  [{c['domain']}] ERROR: {c['error']}")
                continue
            lines += [
                f"\n  [{c['domain']}]",
                f"    Title: {c.get('title', 'N/A')}",
                f"    Meta: {c.get('meta_description', 'N/A')}",
                f"    H1s: {c.get('h1_count', 0)}, H2s: {c.get('h2_count', 0)}",
                f"    Word count: {c.get('word_count', 0)}",
                f"    Top words: {', '.join(c.get('top_words', [])[:10])}",
            ]

        data_summary = "\n".join(lines)

        return (
            f"{data_summary}\n\n"
            f"Based on the above data, provide a comprehensive SEO competitive analysis "
            f"in markdown format covering:\n"
            f"1. **Keyword Overlap Estimation** — which keywords your domain and competitors "
            f"   likely share, and where gaps exist\n"
            f"2. **Content Gap Opportunities** — topics competitors rank for that you are "
            f"   missing or underserving\n"
            f"3. **Structural Improvements** — H1/H2 usage, word count benchmarks, "
            f"   meta description recommendations\n"
            f"4. **Strategic Recommendations** — prioritized action list to outperform "
            f"   competitors over the next 90 days\n\n"
            f"Be specific, actionable, and data-driven based on the extracted information."
        )

    # ─── Main entry ───────────────────────────────────────────────────────────

    def run(self, competitors=None, domain=None, **kwargs):
        cfg = self.config
        domain = domain or cfg.get("default_domain", "wheellsverse-bots.pages.dev")
        competitors_str = competitors or cfg.get(
            "default_competitors", "nerdwallet.com,investopedia.com,bankrate.com"
        )

        # Parse up to 5 competitor domains
        competitor_domains = [
            d.strip() for d in competitors_str.split(",") if d.strip()
        ][:5]

        self.logger.info(
            f"CompetitorAnalysisBot: domain='{domain}', "
            f"competitors={competitor_domains}"
        )

        # Fetch own domain data
        self.logger.info(f"Fetching own domain: {domain}")
        your_data = self._fetch_and_parse(domain)

        # Fetch each competitor
        competitor_data = []
        for comp_domain in competitor_domains:
            self.logger.info(f"Fetching competitor: {comp_domain}")
            data = self._fetch_and_parse(comp_domain)
            competitor_data.append(data)

        successful = [c for c in competitor_data if not c.get("error")]
        self.logger.info(
            f"Successfully fetched {len(successful)}/{len(competitor_domains)} competitors"
        )

        # Build comparison table
        report_lines = [
            "# Competitor Analysis Report",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Your Domain:** {domain}",
            f"**Competitors Analyzed:** {len(successful)}/{len(competitor_domains)}",
            "",
            "---",
            "",
            "## 1. Domain Comparison Table",
            "",
            "| Domain | Title | Meta Description | H1s | H2s | Word Count |",
            "|--------|-------|-----------------|-----|-----|------------|",
        ]

        # Add own domain row
        own_title = (your_data.get("title") or "N/A")[:50]
        own_meta = (your_data.get("meta_description") or "N/A")[:60]
        report_lines.append(
            f"| **{domain}** (you) | {own_title} | {own_meta} | "
            f"{your_data.get('h1_count', 0)} | "
            f"{your_data.get('h2_count', 0)} | "
            f"{your_data.get('word_count', 0):,} |"
        )

        for c in competitor_data:
            title = (c.get("title") or "N/A")[:50]
            meta = (c.get("meta_description") or "N/A")[:60]
            error_note = " *(fetch failed)*" if c.get("error") else ""
            report_lines.append(
                f"| {c['domain']}{error_note} | {title} | {meta} | "
                f"{c.get('h1_count', 0)} | "
                f"{c.get('h2_count', 0)} | "
                f"{c.get('word_count', 0):,} |"
            )

        # Top keyword themes per competitor
        report_lines += [
            "",
            "## 2. Top Keyword Themes by Domain",
            "",
        ]

        report_lines.append(f"**{domain} (you):** {', '.join(your_data.get('top_words', [])[:15])}")
        report_lines.append("")

        for c in competitor_data:
            if c.get("error"):
                report_lines.append(f"**{c['domain']}:** *(fetch failed — {c['error'][:60]})*")
            else:
                words = ", ".join(c.get("top_words", [])[:15]) or "N/A"
                report_lines.append(f"**{c['domain']}:** {words}")
            report_lines.append("")

        # Claude's strategic analysis
        report_lines += [
            "---",
            "",
            "## 3. Strategic Analysis (AI-Powered)",
            "",
        ]

        try:
            system_prompt = "You are an SEO competitive intelligence analyst."
            analysis_prompt = self._build_analysis_prompt(domain, your_data, competitor_data)
            claude_analysis = self.claude(
                analysis_prompt,
                system=system_prompt,
                max_tokens=4000,
            )
            report_lines.append(claude_analysis)
        except Exception as e:
            self.logger.error(f"Claude analysis failed: {e}")
            # Fallback: produce a basic gap analysis without AI
            your_words = set(your_data.get("top_words", []))
            report_lines.append("### Keyword Overlap (Automated Fallback)\n")
            for c in competitor_data:
                if c.get("error"):
                    continue
                comp_words = set(c.get("top_words", []))
                overlap = your_words & comp_words
                gaps = comp_words - your_words
                report_lines.append(f"**{c['domain']}**")
                report_lines.append(f"- Overlap: {', '.join(overlap) or 'none detected'}")
                report_lines.append(f"- Gaps (they have, you don't): {', '.join(list(gaps)[:10]) or 'none'}")
                report_lines.append("")

        # Prioritized action items summary
        report_lines += [
            "",
            "---",
            "",
            "## 4. Quick-Reference Action Items",
            "",
        ]

        # Auto-generate basic structural action items from the data
        avg_comp_wc = 0
        valid_comps = [c for c in competitor_data if not c.get("error") and c.get("word_count", 0) > 0]
        if valid_comps:
            avg_comp_wc = sum(c["word_count"] for c in valid_comps) // len(valid_comps)

        own_wc = your_data.get("word_count", 0)

        if your_data.get("h1_count", 0) == 0:
            report_lines.append("- [ ] Add an H1 tag to your homepage — currently missing.")
        if your_data.get("meta_description") in ("N/A", None, ""):
            report_lines.append("- [ ] Write a meta description for your homepage.")
        if avg_comp_wc > 0 and own_wc < avg_comp_wc * 0.7:
            report_lines.append(
                f"- [ ] Increase homepage content depth — your ~{own_wc:,} words vs "
                f"competitor avg ~{avg_comp_wc:,}."
            )
        if your_data.get("h2_count", 0) < 3:
            report_lines.append(
                "- [ ] Add more H2 sub-sections to improve content structure and "
                "keyword coverage."
            )

        # Keyword gap items
        your_words = set(your_data.get("top_words", []))
        all_comp_words: Counter = Counter()
        for c in valid_comps:
            for w in c.get("top_words", []):
                all_comp_words[w] += 1
        gap_words = [w for w, _ in all_comp_words.most_common(30) if w not in your_words][:10]
        if gap_words:
            report_lines.append(
                f"- [ ] Target these competitor keyword themes not found on your site: "
                f"{', '.join(gap_words)}"
            )

        report_lines += ["", "---", "*Generated by WheellsVerse Competitor Analysis Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"competitor_analysis_{ts}.md"
        path_out = self.save_output(report, fname, ext="md")

        self.logger.info(f"Competitor analysis complete -> {path_out}")
        return {
            "file": str(path_out),
            "competitors_analyzed": len(successful),
            "domain": domain,
        }


if __name__ == "__main__":
    bot = CompetitorAnalysisBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    print(f"Competitors analyzed: {result['competitors_analyzed']}")
    print(f"Domain: {result['domain']}")
