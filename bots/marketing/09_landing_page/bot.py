#!/usr/bin/env python3
"""
Bot #9 — Landing Page Generator
Generates complete, conversion-optimized landing page HTML + copy.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot  # noqa: E402


class LandingPageBot(BaseBot):

    def __init__(self):
        super().__init__("09_landing_page", "marketing")

    def run(self, product: str = None, headline: str = None,
            offer: str = None, audience: str = None,
            color_scheme: str = None, cta: str = None, **kwargs):

        cfg = self.config
        product = product or cfg.get("product", "WheellsVerse AI Platform")
        headline = headline or cfg.get("headline", None)
        offer = offer or cfg.get("offer", "Free 14-day trial")
        audience = audience or cfg.get("audience", "entrepreneurs and creators")
        color_scheme = color_scheme or cfg.get("color_scheme", "dark: #0d1117 bg, #58a6ff accent")
        cta = cta or cfg.get("cta", "Get Started Free")

        self.logger.info(f"Generating landing page for: {product}")

        system = "You are a CRO expert and web designer who builds 7-figure landing pages. You write persuasive copy and provide clean, modern HTML."

        # Step 1: Generate copy
        copy_prompt = f"""Create high-converting landing page copy for:

PRODUCT: {product}
OFFER: {offer}
AUDIENCE: {audience}
CTA: {cta}
{"HEADLINE: " + headline if headline else ""}

Write ALL copy sections:
1. POWER HEADLINE (outcome-focused, specific)
2. SUBHEADLINE (clarify the promise)
3. HERO SECTION BODY (2-3 sentences max)
4. SOCIAL PROOF BAR (3 logos or stats, e.g., "Trusted by 1,000+ entrepreneurs")
5. PAIN POINTS SECTION (3 problems with emojis)
6. SOLUTION SECTION (how your product solves it)
7. FEATURES/BENEFITS (6 items: feature + benefit)
8. HOW IT WORKS (3 steps)
9. TESTIMONIALS (3 realistic testimonials with name, role, quote)
10. PRICING SECTION (1-3 tiers with features)
11. FAQ (5 questions with answers)
12. FINAL CTA SECTION (urgency headline + button + trust signals)
13. FOOTER (links, copyright)"""

        copy = self.ai(copy_prompt, system=system, max_tokens=2500)

        # Step 2: Generate HTML
        html_prompt = f"""Build a complete, professional landing page HTML for this product:

PRODUCT: {product}
OFFER: {offer}
CTA BUTTON TEXT: {cta}
COLOR SCHEME: {color_scheme}

COPY TO USE:
{copy[:3000]}

Requirements:
- Single HTML file (inline CSS + JS)
- Mobile-responsive with CSS Grid/Flexbox
- Modern design: dark theme preferred
- Sticky navigation bar
- Hero section with gradient background
- Animated CTA button
- Smooth scroll
- Mobile hamburger menu
- Font: Google Fonts (Inter or Poppins)
- Include conversion elements: trust badges, countdown timer (optional), sticky CTA
- Real-looking testimonial cards with avatar placeholders
- Pricing cards with highlighted recommended plan

Return ONLY the complete HTML code starting with <!DOCTYPE html>"""

        html = self.ai(html_prompt, system=system, max_tokens=3500,
                       model="gpt-4o")

        # Clean up potential markdown fences
        import re
        html = re.sub(r"^```html\s*|^```\s*|\s*```$", "", html, flags=re.MULTILINE).strip()

        safe = product.replace(" ", "_")[:30]
        html_path = self.save_output(html, f"landing_{safe}.html", ext="html")
        copy_path = self.save_output(
            f"# Landing Page Copy\n**Product:** {product}\n\n---\n\n{copy}",
            f"landing_copy_{safe}.md", ext="md"
        )

        self.logger.info(f"Landing page saved → {html_path}")
        return {"html": str(html_path), "copy": str(copy_path), "product": product}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Landing Page Generator")
    p.add_argument("--product", default=None)
    p.add_argument("--offer", default="Free 14-day trial")
    p.add_argument("--audience", default=None)
    p.add_argument("--cta", default="Get Started Free")
    a = p.parse_args()
    bot = LandingPageBot()
    result = bot.execute(product=a.product, offer=a.offer,
                         audience=a.audience, cta=a.cta)
    print(f"\n✅ Landing page HTML: {result['html']}")
    print(f"   Copy: {result['copy']}")
