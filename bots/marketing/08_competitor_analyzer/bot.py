#!/usr/bin/env python3
"""Bot #8 — Competitor Analyzer"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class CompetitorAnalyzerBot(BaseBot):
    def __init__(self):
        super().__init__("08_competitor_analyzer", "marketing")

    def run(self, your_brand: str = None, competitors: list = None,
            niche: str = None, **kwargs):
        cfg = self.config
        your_brand  = your_brand or cfg.get("your_brand", "WheellsVerse")
        competitors = competitors or cfg.get("competitors", ["Zapier", "Make.com", "n8n"])
        niche       = niche or cfg.get("niche", "AI automation tools")

        self.logger.info(f"Analyzing competitors: {competitors}")
        system = "You are a competitive intelligence analyst who helps businesses find gaps and opportunities in their market."

        prompt = f"""Perform a comprehensive competitive analysis for:

YOUR BRAND: {your_brand}
NICHE: {niche}
COMPETITORS TO ANALYZE: {', '.join(competitors)}

For EACH competitor provide:

### [Competitor Name]
**Overview:** What they do, their positioning, target customer
**Strengths:** Top 5 strengths (features, marketing, pricing, UX)
**Weaknesses:** Top 5 weaknesses or gaps
**Pricing Model:** How they charge + price points
**Key Marketing Channels:** Where they advertise/get traffic
**Content Strategy:** What content they produce
**Social Proof:** How they use testimonials/case studies
**USP:** Their core unique selling proposition
**SEO Keywords:** Top 5 keywords they likely rank for

---

## COMPETITIVE MATRIX
Create a comparison table: Your Brand vs all competitors across:
Pricing | Features | UX | Customer Support | Integrations | Target Market | Growth

## MARKET GAPS & OPPORTUNITIES
Top 5 gaps none of the competitors are addressing (your blue ocean)

## YOUR DIFFERENTIATION STRATEGY
3 concrete ways {your_brand} can win against these competitors

## SWOT ANALYSIS FOR {your_brand.upper()}
Strengths / Weaknesses / Opportunities / Threats

## 90-DAY ACTION PLAN
Specific steps to outcompete in your top 3 weakness areas"""

        result = self.ai(prompt, system=system, max_tokens=3000)
        out = f"# Competitor Analysis: {your_brand}\n**vs. {', '.join(competitors)}**\n**Niche:** {niche}\n\n---\n\n{result}\n\n---\n*WheellsVerse Competitor Analyzer Bot*"
        safe = your_brand.replace(" ","_")[:20]
        path = self.save_output(out, f"competitor_analysis_{safe}.md", ext="md")
        return {"file": str(path)}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--brand", default=None)
    p.add_argument("--competitors", default="Zapier,Make.com")
    p.add_argument("--niche", default=None)
    a = p.parse_args()
    comps = [c.strip() for c in a.competitors.split(",")]
    bot = CompetitorAnalyzerBot()
    print(bot.execute(your_brand=a.brand, competitors=comps, niche=a.niche))
