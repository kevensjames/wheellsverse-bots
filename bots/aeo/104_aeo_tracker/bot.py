#!/usr/bin/env python3
"""bots/aeo/104_aeo_tracker/bot.py — AEO tracker: monitors answer-engine optimization scores over time"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db, ensure_tables  # noqa: E402

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


class AEOTrackerBot(BaseBot):
    """Tracks AEO scores for domains over time, generates trend reports, and compares domains."""

    def __init__(self):
        super().__init__("104_aeo_tracker", "aeo")

    # ─── Inline scoring (mirrors AEOAuditBot to avoid circular import) ───────

    @staticmethod
    def _score_faq(soup: BeautifulSoup) -> int:
        score = 0
        details = soup.find_all("details")
        if details:
            score += min(len(details), 5)
        faq_headings = soup.find_all(re.compile(r"^h[1-6]$"), string=re.compile(r"(?i)faq|frequently\s+asked"))
        if faq_headings:
            score += 5
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") == "FAQPage":
                        score += 7
                        break
            except (json.JSONDecodeError, TypeError):
                continue
        text = soup.get_text(" ", strip=True).lower()
        qa_patterns = re.findall(r"\b(?:q:|question:|a:|answer:)\s", text)
        if len(qa_patterns) >= 4:
            score += 3
        return min(score, 20)

    @staticmethod
    def _score_schema(soup: BeautifulSoup) -> int:
        score = 0
        ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
        if not ld_scripts:
            return 0
        score += 5
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
        valuable_types = {"FAQPage", "HowTo", "Article", "BlogPosting", "Product",
                          "Review", "Recipe", "BreadcrumbList", "Organization",
                          "WebPage", "ItemList"}
        found_valuable = schema_types & valuable_types
        score += min(len(found_valuable) * 3, 9)
        if len(ld_scripts) >= 2:
            score += 3
        if len(ld_scripts) >= 4:
            score += 3
        return min(score, 20)

    @staticmethod
    def _score_qa_headings(soup: BeautifulSoup) -> int:
        question_words = re.compile(r"(?i)\b(how|what|why|when|which|where|who|can|do|does|is|are|should)\b")
        headings = soup.find_all(re.compile(r"^h[2-3]$"))
        question_headings = sum(1 for h in headings if "?" in h.get_text(strip=True) or question_words.search(h.get_text(strip=True)))
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
        total = len(soup.find_all("ul")) + len(soup.find_all("ol")) + len(soup.find_all("table"))
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
        meta = soup.find("meta", attrs={"name": "description"})
        if not meta:
            return 0
        length = len(meta.get("content", ""))
        if 120 <= length <= 160:
            return 10
        if 80 <= length <= 200:
            return 7
        if length > 0:
            return 4
        return 0

    @staticmethod
    def _score_headings(soup: BeautifulSoup) -> int:
        score = 0
        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        h3s = soup.find_all("h3")
        if len(h1s) == 1:
            score += 4
        elif len(h1s) >= 1:
            score += 2
        if h2s:
            score += 3
        if h3s:
            score += 3
        return min(score, 10)

    @staticmethod
    def _score_length(soup: BeautifulSoup) -> int:
        word_count = len(soup.get_text(" ", strip=True).split())
        if word_count > 1500:
            return 10
        if word_count > 1000:
            return 7
        if word_count > 500:
            return 4
        return 0

    def _scan_domain(self, domain: str) -> dict:
        """Fetch domain homepage and compute all AEO scores."""
        url = f"https://{domain}"
        headers = {"User-Agent": "WheellsVerse-AEO-Tracker/1.0"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        faq_score = self._score_faq(soup)
        schema_score = self._score_schema(soup)
        qa_score = self._score_qa_headings(soup)
        format_score = self._score_format(soup)
        meta_score = self._score_meta(soup)
        heading_score = self._score_headings(soup)
        length_score = self._score_length(soup)
        total = faq_score + schema_score + qa_score + format_score + meta_score + heading_score + length_score

        return {
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
            "scanned_at": datetime.now().isoformat(),
        }

    # ─── Actions ─────────────────────────────────────────────────────────────

    def _action_track(self, domain: str) -> dict:
        """Scan domain and store score."""
        self.logger.info(f"Tracking AEO score for: {domain}")
        scores = self._scan_domain(domain)

        ensure_tables()
        db = get_db()
        db["aeo_scores"].insert(scores)
        self.logger.info(f"AEO score tracked: {scores['score']}/100 for {domain}")

        grade = "A+" if scores["score"] >= 90 else "A" if scores["score"] >= 80 else "B" if scores["score"] >= 70 else "C" if scores["score"] >= 60 else "D" if scores["score"] >= 50 else "F"

        report = f"""# AEO Tracking — {domain}
**Scanned:** {scores['scanned_at'][:19]}
**Score:** {scores['score']}/100 (Grade: {grade})

| Category | Score | Max |
|----------|-------|-----|
| FAQ | {scores['faq_score']} | 20 |
| Schema | {scores['schema_score']} | 20 |
| Q&A Headings | {scores['qa_score']} | 15 |
| Formatting | {scores['format_score']} | 15 |
| Meta | {scores['meta_score']} | 10 |
| Headings | {scores['heading_score']} | 10 |
| Length | {scores['length_score']} | 10 |
| **Total** | **{scores['score']}** | **100** |

---
*Generated by WheellsVerse AEO Tracker Bot*
"""
        safe_domain = re.sub(r"[^a-zA-Z0-9]", "_", domain)[:40]
        fname = f"aeo_track_{safe_domain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(report, fname, ext="md")

        return {"file": str(path), "action": "track", "score": scores["score"], "domain": domain}

    def _action_report(self, domain: str) -> dict:
        """Generate trend report from historical scores."""
        self.logger.info(f"Generating AEO report for: {domain}")

        ensure_tables()
        db = get_db()

        rows = list(db["aeo_scores"].rows_where(
            "domain = ?", [domain], order_by="scanned_at desc", limit=50
        ))

        if not rows:
            report = f"""# AEO Report — {domain}

No historical AEO scores found for this domain.

Run `action="track"` first to scan the domain and record a baseline score.

---
*Generated by WheellsVerse AEO Tracker Bot*
"""
            fname = f"aeo_report_{re.sub(r'[^a-zA-Z0-9]', '_', domain)[:40]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            path = self.save_output(report, fname, ext="md")
            return {"file": str(path), "action": "report", "domain": domain}

        latest = rows[0]
        latest_score = latest["score"]

        # Determine trend
        if len(rows) >= 2:
            previous_score = rows[1]["score"]
            delta = latest_score - previous_score
            if delta > 5:
                trend = "IMPROVING"
                trend_icon = "+"
            elif delta < -5:
                trend = "DECLINING"
                trend_icon = ""
            else:
                trend = "STABLE"
                trend_icon = ""
            delta_str = f"{trend_icon}{delta}"
        else:
            trend = "BASELINE"
            delta = 0
            delta_str = "N/A (first scan)"

        grade = "A+" if latest_score >= 90 else "A" if latest_score >= 80 else "B" if latest_score >= 70 else "C" if latest_score >= 60 else "D" if latest_score >= 50 else "F"

        # Build history table
        history_rows = []
        for row in rows[:20]:
            scan_date = row["scanned_at"][:10] if row["scanned_at"] else "unknown"
            history_rows.append(f"| {scan_date} | {row['score']} | {row['faq_score']} | {row['schema_score']} | {row['qa_score']} | {row['format_score']} | {row['meta_score']} | {row['heading_score']} | {row['length_score']} |")

        history_table = "\n".join(history_rows)

        # Calculate averages
        all_scores = [r["score"] for r in rows]
        avg_score = sum(all_scores) / len(all_scores)
        max_score = max(all_scores)
        min_score = min(all_scores)

        report = f"""# AEO Trend Report — {domain}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Data points:** {len(rows)} scans

---

## Current Status

| Metric | Value |
|--------|-------|
| Latest Score | **{latest_score}/100** (Grade: {grade}) |
| Trend | **{trend}** |
| Change from previous | {delta_str} |
| Average score | {avg_score:.1f} |
| All-time high | {max_score} |
| All-time low | {min_score} |
| Total scans | {len(rows)} |

---

## Score History

| Date | Total | FAQ | Schema | Q&A | Format | Meta | Headings | Length |
|------|-------|-----|--------|-----|--------|------|----------|--------|
{history_table}

---

## Trend Analysis

{"Scores are **improving** — AEO optimizations are paying off. Keep adding FAQ sections, structured data, and question-based headings." if trend == "IMPROVING" else ""}{"Scores are **declining** — review recent content changes. Check if structured data, FAQ sections, or heading hierarchy was removed or broken." if trend == "DECLINING" else ""}{"Scores are **stable** — consider adding more FAQ content, JSON-LD schema types, and question-format headings to push the score higher." if trend == "STABLE" else ""}{"This is the **first scan** — run the tracker weekly to build trend data and monitor improvements." if trend == "BASELINE" else ""}

---
*Generated by WheellsVerse AEO Tracker Bot*
"""
        safe_domain = re.sub(r"[^a-zA-Z0-9]", "_", domain)[:40]
        fname = f"aeo_report_{safe_domain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(report, fname, ext="md")

        return {"file": str(path), "action": "report", "domain": domain}

    def _action_compare(self, domains_str: str) -> dict:
        """Compare latest AEO scores across multiple domains."""
        domains = [d.strip() for d in domains_str.split(",") if d.strip()]
        if not domains:
            raise ValueError("No domains provided for comparison. Pass domains='domain1.com,domain2.com'")

        self.logger.info(f"Comparing AEO scores for {len(domains)} domains: {', '.join(domains)}")

        ensure_tables()
        db = get_db()

        comparison_data = []
        for domain in domains:
            rows = list(db["aeo_scores"].rows_where(
                "domain = ?", [domain], order_by="scanned_at desc", limit=1
            ))
            if rows:
                comparison_data.append(rows[0])
            else:
                comparison_data.append({
                    "domain": domain, "score": None, "faq_score": None,
                    "schema_score": None, "qa_score": None, "format_score": None,
                    "meta_score": None, "heading_score": None, "length_score": None,
                    "scanned_at": None,
                })

        # Sort by score descending
        scored = [d for d in comparison_data if d["score"] is not None]
        unscored = [d for d in comparison_data if d["score"] is None]
        scored.sort(key=lambda x: x["score"], reverse=True)
        ordered = scored + unscored

        # Build comparison table
        comp_rows = []
        for i, data in enumerate(ordered, 1):
            if data["score"] is not None:
                grade = "A+" if data["score"] >= 90 else "A" if data["score"] >= 80 else "B" if data["score"] >= 70 else "C" if data["score"] >= 60 else "D" if data["score"] >= 50 else "F"
                scan_date = data["scanned_at"][:10] if data["scanned_at"] else "?"
                comp_rows.append(
                    f"| {i} | {data['domain']} | **{data['score']}** | {grade} | "
                    f"{data['faq_score']} | {data['schema_score']} | {data['qa_score']} | "
                    f"{data['format_score']} | {data['meta_score']} | {data['heading_score']} | "
                    f"{data['length_score']} | {scan_date} |"
                )
            else:
                comp_rows.append(f"| {i} | {data['domain']} | -- | -- | -- | -- | -- | -- | -- | -- | -- | No data |")

        comparison_table = "\n".join(comp_rows)

        # Find winner
        if scored:
            winner = scored[0]["domain"]
            winner_score = scored[0]["score"]
        else:
            winner = "N/A"
            winner_score = 0

        report = f"""# AEO Domain Comparison
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Domains compared:** {len(domains)}

---

## Comparison Table

| Rank | Domain | Score | Grade | FAQ | Schema | Q&A | Format | Meta | Headings | Length | Last Scan |
|------|--------|-------|-------|-----|--------|-----|--------|------|----------|--------|-----------|
{comparison_table}

---

## Summary

{"**Winner:** " + winner + f" with a score of {winner_score}/100" if winner != "N/A" else "No scored domains found. Run `action='track'` for each domain first."}

{f"**Gap analysis:** The top domain leads by {scored[0]['score'] - scored[-1]['score']} points over the lowest." if len(scored) >= 2 else ""}

---

### Category Scoring Guide
- **FAQ (20):** FAQ sections, details/summary tags, FAQPage schema
- **Schema (20):** JSON-LD structured data richness
- **Q&A (15):** Question-format H2/H3 headings
- **Format (15):** Lists, tables, structured elements
- **Meta (10):** Meta description (120-160 chars optimal)
- **Headings (10):** H1 + proper H2/H3 hierarchy
- **Length (10):** Word count (1500+ words = max)

---
*Generated by WheellsVerse AEO Tracker Bot*
"""
        fname = f"aeo_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(report, fname, ext="md")

        return {"file": str(path), "action": "compare"}

    # ─── Main run ────────────────────────────────────────────────────────────

    def run(self, domain=None, action="track", **kwargs):
        domain = domain or self.config.get("default_domain", "wheellsverse-bots.pages.dev")

        if action == "track":
            return self._action_track(domain)
        elif action == "report":
            return self._action_report(domain)
        elif action == "compare":
            domains_str = kwargs.get("domains", domain)
            return self._action_compare(domains_str)
        else:
            raise ValueError(f"Unknown action: {action}. Use 'track', 'report', or 'compare'.")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AEO Tracker Bot")
    parser.add_argument("--domain", type=str, default=None, help="Domain to track")
    parser.add_argument("--action", type=str, default="track", choices=["track", "report", "compare"])
    parser.add_argument("--domains", type=str, default=None, help="Comma-separated domains for compare action")
    args = parser.parse_args()

    bot = AEOTrackerBot()
    result = bot.execute(domain=args.domain, action=args.action, domains=args.domains)
    print(f"\nOutput: {result['file']}")
    print(f"Action: {result['action']}")
    if "score" in result:
        print(f"Score:  {result['score']}/100")
