#!/usr/bin/env python3
"""
Bot #96 — AI Tool Catalog
Category: Tool Catalog
Purpose: Browse, search, and recommend from 50+ AI tools organized by category.
         Maintains a persistent catalog in data/tool_catalog.json.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

# ─── Default catalog seed (50+ tools across 8 categories) ───────────────────

DEFAULT_CATALOG = [
    # Writing
    {"name": "Jasper", "category": "writing", "logo_url": "", "tutorial_minutes": 20, "link": "https://jasper.ai", "tier": "starter"},
    {"name": "Copy.ai", "category": "writing", "logo_url": "", "tutorial_minutes": 10, "link": "https://copy.ai", "tier": "free"},
    {"name": "Writesonic", "category": "writing", "logo_url": "", "tutorial_minutes": 15, "link": "https://writesonic.com", "tier": "free"},
    {"name": "Grammarly", "category": "writing", "logo_url": "", "tutorial_minutes": 10, "link": "https://grammarly.com", "tier": "free"},
    {"name": "Rytr", "category": "writing", "logo_url": "", "tutorial_minutes": 10, "link": "https://rytr.me", "tier": "free"},
    {"name": "Sudowrite", "category": "writing", "logo_url": "", "tutorial_minutes": 15, "link": "https://sudowrite.com", "tier": "starter"},
    {"name": "Wordtune", "category": "writing", "logo_url": "", "tutorial_minutes": 10, "link": "https://wordtune.com", "tier": "free"},
    # Video
    {"name": "Synthesia", "category": "video", "logo_url": "", "tutorial_minutes": 25, "link": "https://synthesia.io", "tier": "starter"},
    {"name": "Runway ML", "category": "video", "logo_url": "", "tutorial_minutes": 20, "link": "https://runwayml.com", "tier": "free"},
    {"name": "Descript", "category": "video", "logo_url": "", "tutorial_minutes": 20, "link": "https://descript.com", "tier": "free"},
    {"name": "HeyGen", "category": "video", "logo_url": "", "tutorial_minutes": 15, "link": "https://heygen.com", "tier": "starter"},
    {"name": "Pictory", "category": "video", "logo_url": "", "tutorial_minutes": 15, "link": "https://pictory.ai", "tier": "starter"},
    {"name": "InVideo", "category": "video", "logo_url": "", "tutorial_minutes": 15, "link": "https://invideo.io", "tier": "free"},
    # Voice
    {"name": "ElevenLabs", "category": "voice", "logo_url": "", "tutorial_minutes": 15, "link": "https://elevenlabs.io", "tier": "free"},
    {"name": "Murf AI", "category": "voice", "logo_url": "", "tutorial_minutes": 15, "link": "https://murf.ai", "tier": "free"},
    {"name": "Play.ht", "category": "voice", "logo_url": "", "tutorial_minutes": 10, "link": "https://play.ht", "tier": "free"},
    {"name": "Resemble AI", "category": "voice", "logo_url": "", "tutorial_minutes": 20, "link": "https://resemble.ai", "tier": "starter"},
    {"name": "Speechify", "category": "voice", "logo_url": "", "tutorial_minutes": 10, "link": "https://speechify.com", "tier": "free"},
    {"name": "WellSaid Labs", "category": "voice", "logo_url": "", "tutorial_minutes": 15, "link": "https://wellsaidlabs.com", "tier": "pro"},
    # SEO
    {"name": "Surfer SEO", "category": "seo", "logo_url": "", "tutorial_minutes": 25, "link": "https://surferseo.com", "tier": "starter"},
    {"name": "Semrush", "category": "seo", "logo_url": "", "tutorial_minutes": 30, "link": "https://semrush.com", "tier": "pro"},
    {"name": "Ahrefs", "category": "seo", "logo_url": "", "tutorial_minutes": 30, "link": "https://ahrefs.com", "tier": "starter"},
    {"name": "Clearscope", "category": "seo", "logo_url": "", "tutorial_minutes": 20, "link": "https://clearscope.io", "tier": "pro"},
    {"name": "NeuronWriter", "category": "seo", "logo_url": "", "tutorial_minutes": 15, "link": "https://neuronwriter.com", "tier": "starter"},
    {"name": "Frase", "category": "seo", "logo_url": "", "tutorial_minutes": 15, "link": "https://frase.io", "tier": "starter"},
    # Analytics
    {"name": "Mixpanel", "category": "analytics", "logo_url": "", "tutorial_minutes": 25, "link": "https://mixpanel.com", "tier": "free"},
    {"name": "Amplitude", "category": "analytics", "logo_url": "", "tutorial_minutes": 25, "link": "https://amplitude.com", "tier": "free"},
    {"name": "Hotjar", "category": "analytics", "logo_url": "", "tutorial_minutes": 15, "link": "https://hotjar.com", "tier": "free"},
    {"name": "Google Analytics", "category": "analytics", "logo_url": "", "tutorial_minutes": 30, "link": "https://analytics.google.com", "tier": "free"},
    {"name": "Heap", "category": "analytics", "logo_url": "", "tutorial_minutes": 20, "link": "https://heap.io", "tier": "free"},
    {"name": "Plausible", "category": "analytics", "logo_url": "", "tutorial_minutes": 10, "link": "https://plausible.io", "tier": "starter"},
    # Code
    {"name": "GitHub Copilot", "category": "code", "logo_url": "", "tutorial_minutes": 15, "link": "https://github.com/features/copilot", "tier": "starter"},
    {"name": "Cursor", "category": "code", "logo_url": "", "tutorial_minutes": 15, "link": "https://cursor.sh", "tier": "free"},
    {"name": "Tabnine", "category": "code", "logo_url": "", "tutorial_minutes": 10, "link": "https://tabnine.com", "tier": "free"},
    {"name": "Replit AI", "category": "code", "logo_url": "", "tutorial_minutes": 15, "link": "https://replit.com", "tier": "free"},
    {"name": "Codeium", "category": "code", "logo_url": "", "tutorial_minutes": 10, "link": "https://codeium.com", "tier": "free"},
    {"name": "Amazon CodeWhisperer", "category": "code", "logo_url": "", "tutorial_minutes": 15, "link": "https://aws.amazon.com/codewhisperer", "tier": "free"},
    {"name": "Claude Code", "category": "code", "logo_url": "", "tutorial_minutes": 10, "link": "https://claude.ai", "tier": "pro"},
    # Image
    {"name": "Midjourney", "category": "image", "logo_url": "", "tutorial_minutes": 20, "link": "https://midjourney.com", "tier": "starter"},
    {"name": "DALL-E 3", "category": "image", "logo_url": "", "tutorial_minutes": 10, "link": "https://openai.com/dall-e-3", "tier": "starter"},
    {"name": "Stable Diffusion", "category": "image", "logo_url": "", "tutorial_minutes": 30, "link": "https://stability.ai", "tier": "free"},
    {"name": "Leonardo AI", "category": "image", "logo_url": "", "tutorial_minutes": 15, "link": "https://leonardo.ai", "tier": "free"},
    {"name": "Canva AI", "category": "image", "logo_url": "", "tutorial_minutes": 15, "link": "https://canva.com", "tier": "free"},
    {"name": "Adobe Firefly", "category": "image", "logo_url": "", "tutorial_minutes": 20, "link": "https://firefly.adobe.com", "tier": "starter"},
    # Automation
    {"name": "Zapier", "category": "automation", "logo_url": "", "tutorial_minutes": 20, "link": "https://zapier.com", "tier": "free"},
    {"name": "Make (Integromat)", "category": "automation", "logo_url": "", "tutorial_minutes": 25, "link": "https://make.com", "tier": "free"},
    {"name": "n8n", "category": "automation", "logo_url": "", "tutorial_minutes": 30, "link": "https://n8n.io", "tier": "free"},
    {"name": "Bardeen", "category": "automation", "logo_url": "", "tutorial_minutes": 15, "link": "https://bardeen.ai", "tier": "free"},
    {"name": "Activepieces", "category": "automation", "logo_url": "", "tutorial_minutes": 20, "link": "https://activepieces.com", "tier": "free"},
    {"name": "Pipedream", "category": "automation", "logo_url": "", "tutorial_minutes": 20, "link": "https://pipedream.com", "tier": "free"},
    {"name": "Relevance AI", "category": "automation", "logo_url": "", "tutorial_minutes": 20, "link": "https://relevanceai.com", "tier": "starter"},
]


class ToolCatalogBot(BaseBot):
    """Browse, search, and recommend from 50+ AI tools."""

    def __init__(self):
        super().__init__("96_tool_catalog", "tool_catalog")
        self.catalog_path = self.data_dir / "tool_catalog.json"

    # ─── Catalog persistence ────────────────────────────────────────────────

    def _load_catalog(self) -> list:
        """Load the catalog from disk or seed it on first run."""
        if self.catalog_path.exists():
            try:
                data = json.loads(self.catalog_path.read_text())
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception:
                pass
        # Seed the catalog
        self.logger.info("Seeding tool catalog with 50+ AI tools")
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_path.write_text(json.dumps(DEFAULT_CATALOG, indent=2))
        return list(DEFAULT_CATALOG)

    def _save_catalog(self, catalog: list) -> None:
        self.catalog_path.write_text(json.dumps(catalog, indent=2))

    # ─── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _tools_to_table(tools: list, title: str = "AI Tools") -> str:
        """Convert a list of tool dicts to a markdown table."""
        lines = [
            f"# {title}",
            "",
            "| # | Name | Category | Tier | Tutorial (min) | Link |",
            "|---|------|----------|------|----------------|------|",
        ]
        for i, t in enumerate(tools, 1):
            lines.append(
                f"| {i} | **{t['name']}** | {t['category']} | {t['tier']} "
                f"| {t['tutorial_minutes']} | [{t['name']}]({t['link']}) |"
            )
        lines.append("")
        lines.append(f"*{len(tools)} tools listed*")
        return "\n".join(lines)

    # ─── Main run ───────────────────────────────────────────────────────────

    def run(self, action: str = "browse", category: str = None,
            query: str = None, **kwargs):

        catalog = self._load_catalog()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ── Browse ──────────────────────────────────────────────────────────
        if action == "browse":
            if category:
                filtered = [t for t in catalog if t["category"] == category.lower()]
                title = f"AI Tools  Category: {category.title()}"
            else:
                filtered = catalog
                title = "AI Tool Catalog  All Categories"

            # Group by category for nicer output
            if not category:
                cats = sorted(set(t["category"] for t in catalog))
                sections = []
                for cat in cats:
                    cat_tools = [t for t in catalog if t["category"] == cat]
                    sections.append(self._tools_to_table(cat_tools, f"{cat.title()} Tools"))
                output = "\n\n---\n\n".join(sections)
                output = f"# AI Tool Catalog\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n**Total tools:** {len(catalog)}\n\n---\n\n{output}"
            else:
                output = self._tools_to_table(filtered, title)
                output = f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{output}"

            fname = f"catalog_browse_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "tools_count": len(filtered) if category else len(catalog)}

        # ── Search ──────────────────────────────────────────────────────────
        elif action == "search":
            q = (query or "").lower().strip()
            if not q:
                self.logger.warning("No query provided for search, returning full catalog")
                q = ""

            if q:
                filtered = [
                    t for t in catalog
                    if q in t["name"].lower()
                    or q in t["category"].lower()
                    or q in t["tier"].lower()
                    or q in t["link"].lower()
                ]
            else:
                filtered = catalog

            output = self._tools_to_table(filtered, f"Search Results for '{query or 'all'}'")
            output = f"**Query:** {query}\n**Matches:** {len(filtered)}\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{output}"

            fname = f"catalog_search_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "tools_count": len(filtered)}

        # ── Recommend ───────────────────────────────────────────────────────
        elif action == "recommend":
            use_case = query or "general AI automation for a small business"

            # Build catalog summary for the AI
            cat_summary = json.dumps(
                [{"name": t["name"], "category": t["category"], "tier": t["tier"],
                  "link": t["link"]}
                 for t in catalog],
                indent=2
            )

            system = (
                "You are an expert AI tools consultant. You recommend the best tool "
                "stacks for specific use cases. Be concise, opinionated, and practical. "
                "Always explain WHY a tool fits the use case."
            )

            prompt = f"""Given the following use case, recommend the best AI tools from our catalog.

USE CASE: {use_case}

AVAILABLE TOOLS:
{cat_summary}

Return your recommendation as a markdown document with:
1. **Top 3 Must-Have Tools** with reasons
2. **Recommended Stack** (the ideal combination for this use case)
3. **Budget-Friendly Alternative** (free-tier tools only)
4. **Getting Started** steps (numbered, actionable)

Be specific about which tools to pair together and why."""

            recommendation = self.ai(prompt, system=system, max_tokens=2000)

            output = f"""# AI Tool Recommendations
**Use Case:** {use_case}
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

{recommendation}

---
*Generated by WheellsVerse Tool Catalog Bot*
"""
            fname = f"catalog_recommend_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "tools_count": len(catalog)}

        # ── Bundle ──────────────────────────────────────────────────────────
        elif action == "bundle":
            tiers = sorted(set(t["tier"] for t in catalog))
            sections = []
            for tier in tiers:
                tier_tools = [t for t in catalog if t["tier"] == tier]
                sections.append(self._tools_to_table(tier_tools, f"{tier.title()} Tier"))

            output = f"""# AI Tool Bundles by Tier
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Total tools:** {len(catalog)}

"""
            for tier in tiers:
                tier_tools = [t for t in catalog if t["tier"] == tier]
                output += f"\n---\n\n## {tier.upper()} Tier ({len(tier_tools)} tools)\n\n"
                output += "| # | Name | Category | Tutorial (min) | Link |\n"
                output += "|---|------|----------|----------------|------|\n"
                for i, t in enumerate(tier_tools, 1):
                    output += (
                        f"| {i} | **{t['name']}** | {t['category']} "
                        f"| {t['tutorial_minutes']} | [{t['name']}]({t['link']}) |\n"
                    )

            output += "\n---\n*Generated by WheellsVerse Tool Catalog Bot*\n"

            fname = f"catalog_bundles_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "tools_count": len(catalog)}

        else:
            raise ValueError(f"Unknown action: {action}. Use browse, search, recommend, or bundle.")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Tool Catalog Bot")
    parser.add_argument("--action", type=str, default="browse",
                        choices=["browse", "search", "recommend", "bundle"])
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--query", type=str, default=None)
    args = parser.parse_args()

    bot = ToolCatalogBot()
    result = bot.execute(action=args.action, category=args.category, query=args.query)
    print(f"\nOutput: {result['file']}")
    print(f"Action: {result['action']}  |  Tools: {result['tools_count']}")
