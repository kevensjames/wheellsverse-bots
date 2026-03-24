#!/usr/bin/env python3
"""Bot #6 — Lead Magnet Creator"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class LeadMagnetBot(BaseBot):
    def __init__(self):
        super().__init__("06_lead_magnet", "marketing")

    def run(self, niche: str = None, audience: str = None,
            format_type: str = None, **kwargs):
        cfg = self.config
        niche       = niche or cfg.get("niche", "AI automation")
        audience    = audience or cfg.get("audience", "entrepreneurs")
        format_type = format_type or cfg.get("format", "checklist")

        self.logger.info(f"Creating {format_type} lead magnet for {niche}")

        formats = {
            "checklist": "a step-by-step checklist PDF",
            "ebook": "a short ebook (10-15 pages)",
            "template": "a ready-to-use template",
            "cheat_sheet": "a 1-page cheat sheet",
            "mini_course": "a 3-5 day email mini course",
            "toolkit": "a resource toolkit with multiple assets",
            "quiz": "an interactive quiz with results",
            "webinar": "a 45-min webinar outline"
        }

        system = "You are a lead generation expert who creates irresistible free offers that convert cold traffic into hot leads."

        prompt = f"""Create a complete lead magnet in the format of {formats.get(format_type, format_type)} for:

NICHE: {niche}
AUDIENCE: {audience}
FORMAT: {format_type}

Provide:
1. TITLE (magnetic, specific, outcome-focused — "The [Number] [Thing] That [Result] in [Timeframe]")
2. SUBTITLE (supporting promise)
3. HOOK (why they MUST have this)
4. FULL CONTENT OUTLINE (with all sections, headers, bullet points)
5. ACTUAL CONTENT for the first 3 sections (full text, not placeholders)
6. LANDING PAGE COPY (headline, subheadline, 5 bullet benefits, CTA button)
7. THANK YOU PAGE copy
8. DELIVERY EMAIL subject line + body
9. UPSELL BRIDGE (how to transition from free to paid)
10. DESIGN NOTES (colors, style, layout recommendations)

Make the content genuinely valuable — it should make them think "this is better than paid stuff."
"""
        result = self.ai(prompt, system=system, max_tokens=3000)
        out = f"# Lead Magnet: {format_type.title()} for {niche}\n**Audience:** {audience}\n\n---\n\n{result}\n\n---\n*WheellsVerse Lead Magnet Bot*"
        path = self.save_output(out, f"lead_magnet_{format_type}_{niche.replace(' ','_')[:20]}.md", ext="md")
        return {"file": str(path)}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--niche", default=None)
    p.add_argument("--audience", default=None)
    p.add_argument("--format", default="checklist")
    a = p.parse_args()
    bot = LeadMagnetBot()
    print(bot.execute(niche=a.niche, audience=a.audience, format_type=a.format))
