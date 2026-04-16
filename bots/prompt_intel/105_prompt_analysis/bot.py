#!/usr/bin/env python3
"""bots/prompt_intel/105_prompt_analysis/bot.py — Prompt intelligence: analyzes brand visibility in AI engine responses"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db, ensure_tables  # noqa: E402


class PromptAnalysisBot(BaseBot):
    """Generates realistic AI prompts for an industry, tests brand visibility in AI responses, and reports gaps."""

    def __init__(self):
        super().__init__("105_prompt_analysis", "prompt_intel")

    def _generate_prompts(self, industry: str, count: int) -> list:
        """Use Claude to generate realistic prompts users would type into AI engines."""
        self.logger.info(f"Generating {count} realistic prompts for industry: {industry}")

        system = (
            "You are a market research expert. Generate realistic prompts and questions "
            "that real people would type into ChatGPT, Perplexity, or Google AI. "
            "Return ONLY a JSON array of strings, no other text."
        )

        prompt = (
            f"Generate {count} realistic prompts/questions that a person interested in "
            f"{industry} would type into ChatGPT or Perplexity. Cover:\n"
            f"- Beginner questions (e.g., 'What is...', 'How do I start...')\n"
            f"- Comparison queries (e.g., 'X vs Y', 'Best alternatives to...')\n"
            f"- 'Best X' queries (e.g., 'Best tools for...', 'Top 10...')\n"
            f"- How-to questions (e.g., 'How to set up...', 'Step by step...')\n"
            f"- Buying intent questions (e.g., 'Is X worth it?', 'Where to buy...')\n\n"
            f"Return as a JSON array of strings. Example: [\"What is passive income?\", \"Best crypto to invest in 2025\"]"
        )

        try:
            result = self.claude_json(prompt, system=system)
        except Exception as e:
            self.logger.warning(f"Claude JSON failed, trying raw: {e}")
            raw = self.claude(prompt, system=system)
            # Try to extract JSON array from raw text
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    result = {"raw": raw}
            else:
                result = {"raw": raw}

        if isinstance(result, list):
            prompts = [str(p).strip() for p in result if isinstance(p, str) and len(p.strip()) > 5]
            return prompts[:count]
        elif isinstance(result, dict) and "raw" not in result:
            # Might be nested
            for key in result:
                if isinstance(result[key], list):
                    return [str(p).strip() for p in result[key] if isinstance(p, str)][:count]

        # Fallback: parse raw text line by line
        raw_text = result.get("raw", "") if isinstance(result, dict) else str(result)
        lines = [line.strip().strip("-").strip("*").strip('"').strip("'").strip()
                 for line in raw_text.split("\n") if line.strip() and "?" in line]
        return lines[:count]

    def _classify_mention(self, brand: str, response_text: str) -> str:
        """Classify whether the brand is mentioned in an AI response."""
        brand_lower = brand.lower()
        response_lower = response_text.lower()

        # Direct mention
        if brand_lower in response_lower:
            return "mentioned"

        # Partial mention — check for brand name parts and related terms
        brand_parts = brand_lower.split()
        for part in brand_parts:
            if len(part) > 3 and part in response_lower:
                return "partial"

        # Check for domain-like mentions (wheellsverse.com, etc.)
        domain_pattern = re.compile(re.escape(brand_lower.replace(" ", "")) + r"[.\-]", re.IGNORECASE)
        if domain_pattern.search(response_text):
            return "partial"

        return "not_mentioned"

    def _categorize_prompt(self, prompt_text: str) -> str:
        """Categorize a prompt into a topic category."""
        prompt_lower = prompt_text.lower()
        if any(w in prompt_lower for w in ["vs", "versus", "compare", "comparison", "alternative", "difference"]):
            return "comparison"
        if any(w in prompt_lower for w in ["best", "top", "recommend", "favorite"]):
            return "best_of"
        if any(w in prompt_lower for w in ["how to", "how do", "step by step", "guide", "tutorial"]):
            return "how_to"
        if any(w in prompt_lower for w in ["buy", "purchase", "invest", "worth it", "price", "cost"]):
            return "buying_intent"
        if any(w in prompt_lower for w in ["what is", "what are", "explain", "define", "meaning"]):
            return "beginner"
        return "general"

    def run(self, brand=None, industry=None, count=50, **kwargs):
        brand = brand or self.config.get("default_brand", "WheellsVerse")
        industry = industry or self.config.get("default_industry", "passive income and crypto investing")
        count = int(count)

        self.logger.info(f"Starting prompt analysis: brand={brand}, industry={industry}, count={count}")

        # Step 1: Generate prompts
        prompts = self._generate_prompts(industry, count)
        self.logger.info(f"Generated {len(prompts)} prompts")

        if not prompts:
            raise RuntimeError("Failed to generate any prompts. Check AI provider configuration.")

        # Step 2: Test each prompt (limit to first 20 for API cost management)
        test_limit = min(len(prompts), 20)
        self.logger.info(f"Testing {test_limit} prompts against AI for brand mentions")

        ensure_tables()
        db = get_db()

        results = []
        mentioned_count = 0
        partial_count = 0
        not_mentioned_count = 0

        for i, prompt_text in enumerate(prompts[:test_limit]):
            self.logger.info(f"Testing prompt {i + 1}/{test_limit}: {prompt_text[:60]}...")

            try:
                # Query AI with the prompt
                ai_response = self.ai(
                    prompt_text,
                    system="You are a helpful AI assistant. Answer the user's question thoroughly with specific recommendations, tools, and resources.",
                    max_tokens=800,
                    temperature=0.7,
                )

                # Classify mention
                mention_type = self._classify_mention(brand, ai_response)
                category = self._categorize_prompt(prompt_text)

                # Store result in SQLite
                db["prompt_results"].insert({
                    "brand": brand,
                    "prompt_text": prompt_text,
                    "engine": "openai",
                    "ai_response": ai_response[:2000],  # Truncate for storage
                    "brand_mentioned": mention_type != "not_mentioned",
                    "mention_type": mention_type,
                    "topic_category": category,
                    "tested_at": datetime.now().isoformat(),
                })

                results.append({
                    "prompt": prompt_text,
                    "mention_type": mention_type,
                    "category": category,
                })

                if mention_type == "mentioned":
                    mentioned_count += 1
                elif mention_type == "partial":
                    partial_count += 1
                else:
                    not_mentioned_count += 1

            except Exception as e:
                self.logger.warning(f"Failed to test prompt '{prompt_text[:40]}': {e}")
                results.append({
                    "prompt": prompt_text,
                    "mention_type": "error",
                    "category": self._categorize_prompt(prompt_text),
                })

        # Step 3: Calculate metrics
        tested_total = mentioned_count + partial_count + not_mentioned_count
        mention_rate = (mentioned_count + partial_count) / max(tested_total, 1)
        direct_rate = mentioned_count / max(tested_total, 1)

        # Step 4: Generate report
        # Results table
        result_rows = []
        for r in results:
            status_icon = "MENTIONED" if r["mention_type"] == "mentioned" else "PARTIAL" if r["mention_type"] == "partial" else "NOT FOUND" if r["mention_type"] == "not_mentioned" else "ERROR"
            result_rows.append(f"| {r['prompt'][:70]} | {status_icon} | {r['category']} |")

        results_table = "\n".join(result_rows)

        # Not-mentioned prompts list
        not_mentioned_list = [r["prompt"] for r in results if r["mention_type"] == "not_mentioned"]
        not_mentioned_section = "\n".join(f"- {p}" for p in not_mentioned_list) if not_mentioned_list else "None -- brand was mentioned in all tested prompts."

        # Category breakdown
        category_stats = {}
        for r in results:
            cat = r["category"]
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "mentioned": 0, "partial": 0, "not_mentioned": 0}
            category_stats[cat]["total"] += 1
            if r["mention_type"] in category_stats[cat]:
                category_stats[cat][r["mention_type"]] += 1

        cat_rows = []
        for cat, stats in sorted(category_stats.items()):
            cat_mention_rate = (stats["mentioned"] + stats["partial"]) / max(stats["total"], 1)
            cat_rows.append(f"| {cat} | {stats['total']} | {stats['mentioned']} | {stats['partial']} | {stats['not_mentioned']} | {cat_mention_rate:.0%} |")
        category_table = "\n".join(cat_rows)

        report = f"""# Prompt Intelligence Report — {brand}
**Industry:** {industry}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Prompts generated:** {len(prompts)}
**Prompts tested:** {tested_total}

---

## Overall Brand Visibility

| Metric | Value |
|--------|-------|
| Direct mention rate | **{direct_rate:.1%}** |
| Total visibility rate (direct + partial) | **{mention_rate:.1%}** |
| Directly mentioned | {mentioned_count} |
| Partially mentioned | {partial_count} |
| Not mentioned | {not_mentioned_count} |

---

## Results by Category

| Category | Tested | Mentioned | Partial | Not Found | Visibility |
|----------|--------|-----------|---------|-----------|------------|
{category_table}

---

## Full Results

| Prompt | Status | Category |
|--------|--------|----------|
{results_table}

---

## Prompts Where Brand Was NOT Found

These represent content gaps — creating targeted content for these queries could improve AI visibility:

{not_mentioned_section}

---

## Untested Prompts

The following {len(prompts) - test_limit} prompts were generated but not tested (API cost limit):

{chr(10).join(f"- {p}" for p in prompts[test_limit:test_limit + 30]) if len(prompts) > test_limit else "All prompts were tested."}
{"..." if len(prompts) > test_limit + 30 else ""}

---

## Next Steps

1. Run **PromptFixBot** (106) to generate content plans for "not found" prompts
2. Create targeted blog posts, FAQ pages, and schema markup
3. Re-run this analysis in 2-4 weeks to measure improvement

---
*Generated by WheellsVerse Prompt Analysis Bot*
"""
        fname = f"prompt_analysis_{brand.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(report, fname, ext="md")

        self.logger.info(f"Prompt analysis complete: {mention_rate:.1%} visibility rate across {tested_total} prompts")
        return {
            "file": str(path),
            "brand": brand,
            "mention_rate": round(mention_rate, 4),
            "total_prompts": len(prompts),
        }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prompt Analysis Bot")
    parser.add_argument("--brand", type=str, default=None, help="Brand name to check")
    parser.add_argument("--industry", type=str, default=None, help="Industry to generate prompts for")
    parser.add_argument("--count", type=int, default=50, help="Number of prompts to generate")
    args = parser.parse_args()

    bot = PromptAnalysisBot()
    result = bot.execute(brand=args.brand, industry=args.industry, count=args.count)
    print(f"\nOutput:       {result['file']}")
    print(f"Brand:        {result['brand']}")
    print(f"Mention rate: {result['mention_rate']:.1%}")
    print(f"Prompts:      {result['total_prompts']}")
