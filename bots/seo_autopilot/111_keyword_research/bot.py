#!/usr/bin/env python3
"""bots/seo_autopilot/111_keyword_research/bot.py — SEO keyword research bot"""
import sys
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db  # noqa: E402


class KeywordResearchBot(BaseBot):
    """Discovers high-value long-tail keywords from seed terms using Claude."""

    def __init__(self):
        super().__init__("111_keyword_research", "seo_autopilot")

    def run(self, seed_keywords=None, count=50, niche=None, **kwargs):
        cfg = self.config
        seed_keywords = seed_keywords or cfg.get(
            "default_seeds", "passive income, crypto investing, side hustle, AI tools"
        )
        niche = niche or cfg.get("default_niche", "finance")
        count = int(count)

        self.logger.info(
            f"Researching {count} keywords from seeds: {seed_keywords} (niche: {niche})"
        )

        # Step 1: Use Claude to expand seed keywords into long-tail variations
        system_prompt = (
            f"You are an SEO keyword researcher. Generate {count} long-tail keyword "
            f"variations from these seeds: {seed_keywords}. Focus on: high search intent, "
            f"question-based queries, comparison queries, 'best X' queries. "
            f"Return ONLY valid JSON — an array of objects: "
            f'[{{"keyword": "...", "intent": "informational|transactional|navigational", '
            f'"estimated_difficulty": "low|medium|high"}}]'
        )

        user_prompt = (
            f"Seeds: {seed_keywords}\n"
            f"Niche: {niche}\n"
            f"Count: {count}\n\n"
            f"Generate exactly {count} long-tail keyword variations. Include a mix of:\n"
            f"- Question-based queries (how to, what is, why, when)\n"
            f"- Comparison queries (X vs Y, best X for Y)\n"
            f"- Transactional queries (buy, best, top, review)\n"
            f"- Informational queries (guide, tutorial, explained)\n"
            f"Return ONLY the JSON array, no other text."
        )

        raw = self.claude(user_prompt, system=system_prompt, max_tokens=4000)

        # Parse the JSON response
        raw_clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
        try:
            keywords_list = json.loads(raw_clean)
        except json.JSONDecodeError:
            self.logger.warning("Claude response was not valid JSON, attempting extraction")
            match = re.search(r"\[.*\]", raw_clean, re.DOTALL)
            if match:
                keywords_list = json.loads(match.group())
            else:
                keywords_list = [{"keyword": seed_keywords, "intent": "informational",
                                  "estimated_difficulty": "medium"}]

        if not isinstance(keywords_list, list):
            keywords_list = [keywords_list]

        # Step 2: Store keywords in SQLite
        db = get_db()
        now = datetime.now().isoformat()
        stored_count = 0

        for item in keywords_list:
            if not isinstance(item, dict) or "keyword" not in item:
                continue
            kw = item["keyword"].strip()
            if not kw:
                continue

            record = {
                "keyword": kw,
                "volume": 0,
                "difficulty": 0,
                "category": niche,
                "tracked_since": now,
                "last_checked": now,
            }
            try:
                db["keywords"].upsert(record, pk="id", alter=True)
                stored_count += 1
            except Exception as e:
                # If upsert fails on duplicate keyword, try to update
                try:
                    existing = list(
                        db["keywords"].rows_where("keyword = ?", [kw])
                    )
                    if existing:
                        db["keywords"].update(existing[0]["id"], {
                            "category": niche,
                            "last_checked": now,
                        })
                        stored_count += 1
                    else:
                        self.logger.warning(f"Failed to store keyword '{kw}': {e}")
                except Exception as e2:
                    self.logger.warning(f"Failed to store keyword '{kw}': {e2}")

        self.logger.info(f"Stored {stored_count} keywords in database")

        # Step 3: Generate markdown report grouped by intent
        informational = [k for k in keywords_list if isinstance(k, dict) and
                         k.get("intent") == "informational"]
        transactional = [k for k in keywords_list if isinstance(k, dict) and
                         k.get("intent") == "transactional"]
        navigational = [k for k in keywords_list if isinstance(k, dict) and
                        k.get("intent") == "navigational"]

        report_lines = [
            "# Keyword Research Report",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Seeds:** {seed_keywords}",
            f"**Niche:** {niche}",
            f"**Keywords Found:** {len(keywords_list)}",
            f"**Stored in DB:** {stored_count}",
            "",
            "---",
            "",
        ]

        for label, group in [("Informational", informational),
                              ("Transactional", transactional),
                              ("Navigational", navigational)]:
            report_lines.append(f"## {label} Keywords ({len(group)})")
            report_lines.append("")
            if group:
                report_lines.append("| Keyword | Difficulty |")
                report_lines.append("|---------|------------|")
                for kw in group:
                    report_lines.append(
                        f"| {kw.get('keyword', 'N/A')} | "
                        f"{kw.get('estimated_difficulty', 'N/A')} |"
                    )
            else:
                report_lines.append("_No keywords in this category._")
            report_lines.append("")

        # Add uncategorized keywords
        categorized_intents = {"informational", "transactional", "navigational"}
        other = [k for k in keywords_list if isinstance(k, dict) and
                 k.get("intent") not in categorized_intents]
        if other:
            report_lines.append(f"## Other Keywords ({len(other)})")
            report_lines.append("")
            report_lines.append("| Keyword | Intent | Difficulty |")
            report_lines.append("|---------|--------|------------|")
            for kw in other:
                report_lines.append(
                    f"| {kw.get('keyword', 'N/A')} | "
                    f"{kw.get('intent', 'N/A')} | "
                    f"{kw.get('estimated_difficulty', 'N/A')} |"
                )
            report_lines.append("")

        report_lines.append("---")
        report_lines.append("*Generated by WheellsVerse Keyword Research Bot*")

        output = "\n".join(report_lines)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"keyword_research_{niche}_{ts}.md"
        path = self.save_output(output, fname, ext="md")

        self.logger.info(f"Report saved -> {path}")
        return {"file": str(path), "keywords_found": stored_count}


if __name__ == "__main__":
    bot = KeywordResearchBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    print(f"Keywords found: {result['keywords_found']}")
