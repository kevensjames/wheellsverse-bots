#!/usr/bin/env python3
"""
Bot #68 — Visual Design Brief & AI Prompt Generator
Category: Specialized
Purpose: Generate detailed design briefs, AI image prompts (Midjourney/DALL-E),
         and creative direction for branding, social media, and marketing assets.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

DESIGN_TYPES = {
    "logo":           "Brand logo and identity system",
    "social_banner":  "Social media profile banner or cover image",
    "post_graphic":   "Social media post or carousel graphics",
    "ad_creative":    "Paid advertising creative (Facebook/Instagram/Google)",
    "website_hero":   "Website hero section or landing page visual",
    "thumbnail":      "YouTube thumbnail or blog featured image",
    "brand_kit":      "Complete brand style guide -- colors, fonts, logo usage",
    "presentation":   "Presentation or pitch deck visual style",
    "product_mockup": "Product screenshot or UI mockup",
    "infographic":    "Data visualization or process infographic",
}

DESIGN_STYLES = {
    "modern_minimal":   "Clean lines, lots of white space, minimal elements",
    "bold_energetic":   "Strong colors, bold typography, high contrast",
    "professional":     "Corporate-appropriate, trust-building, conservative",
    "creative_playful": "Colorful, fun, personality-driven",
    "dark_premium":     "Dark backgrounds, gold/silver accents, luxury feel",
    "techy_futuristic": "Neon, gradients, tech aesthetic, AI/crypto vibes",
    "warm_authentic":   "Natural colors, human-centered, relatable and warm",
}


class DesigningBot(BaseBot):

    def __init__(self):
        super().__init__("68_designing_bot", "specialized")

    def run(self, design_type: str = None, brand_name: str = None,
            style: str = None, colors: str = None,
            assets_needed: str = None, **kwargs):

        cfg = self.config
        design_type   = design_type or cfg.get("design_type", "brand_kit")
        brand_name    = brand_name or cfg.get("brand_name", "WheellsVerse")
        style         = style or cfg.get("style", "techy_futuristic")
        colors        = colors or cfg.get("colors",
            "deep navy #0A1628, electric blue #1E90FF, white #FFFFFF, gold accent #FFD700")
        assets_needed = assets_needed or cfg.get("assets_needed",
            "logo, social banners, post templates, thumbnail template")

        type_desc  = DESIGN_TYPES.get(design_type, design_type)
        style_desc = DESIGN_STYLES.get(style, style)
        asset_list = [a.strip() for a in assets_needed.split(",")]

        self.logger.info(f"Generating design brief for: {design_type} -- {brand_name}")

        system = (
            "You are a creative director and brand designer with 10+ years building visual "
            "identities for startups and 7-figure brands. You understand that design is strategy -- "
            "every visual choice communicates something about the brand. You write briefs that "
            "designers (human or AI) can execute immediately, without ambiguity. "
            "You also write expert AI image prompts for Midjourney, DALL-E, and Stable Diffusion "
            "that produce professional, usable results on the first try. "
            "You don't just describe what things look like -- you describe what they should FEEL like."
        )

        # Pre-compute asset briefs to avoid nested triple-quoted f-strings (Python 3.11)
        asset_briefs = "".join(
            f"### Asset: {asset.upper()}\n\n"
            "**Dimensions:** [Standard sizes for this asset type]\n"
            "**Purpose:** [What this asset does and where it appears]\n\n"
            "**Design Direction:**\n"
            "- Concept: [What to design - describe the scene, composition, or layout]\n"
            "- Visual hierarchy: [What the eye should see first > second > third]\n"
            "- Must include: [Required elements - logo placement, brand colors, text]\n"
            "- Mood: [Emotional feel this asset should convey]\n"
            '- Visual reference: [Style reference - e.g., "like Apple\'s product pages but warmer"]\n\n'
            "**Content/Copy to include:**\n"
            "[Any text that goes on this design]\n\n"
            "---\n\n"
            for asset in asset_list
        )

        primary_color = colors.split(",")[0].strip()

        prompt = f"""Generate a complete design brief and AI prompts for:

DESIGN TYPE: {design_type} -- {type_desc}
BRAND NAME: {brand_name}
VISUAL STYLE: {style} -- {style_desc}
COLOR PALETTE: {colors}
ASSETS NEEDED: {assets_needed}
BRAND: WheellsVerse -- AI automation tools for entrepreneurs

---

## BRAND VISUAL IDENTITY

### Brand Essence
**In 3 words, {brand_name} feels:** [3 adjectives that describe the brand personality]
**Visual metaphor:** [If {brand_name} were a physical place, it would be: ...]
**Design principle:** [The single most important thing every design element must communicate]

### Color System
Based on: {colors}

| Color | Hex | Usage | Psychology |
| Primary | | Headlines, buttons, key elements | |
| Secondary | | Accents, hover states | |
| Neutral | | Backgrounds, body text | |
| Accent | | CTAs, highlights, badges | |

**Accessibility:** [Contrast ratios -- ensure AA compliance]
**Dark mode:** [How to adapt for dark backgrounds]

### Typography System
| Font Role | Font Name | Weight | Usage |
| Heading H1 | [Font] | Bold/800 | Page titles |
| Heading H2 | [Font] | SemiBold/600 | Section headers |
| Body | [Font] | Regular/400 | Paragraph text |
| UI/Caption | [Font] | Medium/500 | Buttons, labels |
| Brand tagline | [Font] | Light/300 | Optional, for taglines |

**Free alternatives on Google Fonts:** [Fallback options]

---

## DESIGN BRIEFS BY ASSET

{asset_briefs}

---

## AI IMAGE PROMPTS

Ready-to-use prompts for AI image generation:

### Midjourney Prompts

**Prompt 1 -- {brand_name} Brand Visual:**
```
/imagine {brand_name} brand visual, {style_desc}, {primary_color} color palette, professional marketing design, [specific composition], high resolution, 8k --ar 16:9 --v 6
```

**Prompt 2 -- Social Media Post Background:**
```
/imagine abstract background for {brand_name} social media post, {style.replace("_", " ")} aesthetic, [primary color from {colors}], gradient, minimal, professional --ar 1:1 --v 6
```

**Prompt 3 -- Hero Banner:**
```
/imagine website hero banner background for AI automation company, {style_desc}, tech atmosphere, [2 colors from {colors}], clean, modern --ar 16:9 --v 6
```

### DALL-E Prompts

**Prompt 1:**
```
A professional {design_type.replace("_", " ")} for {brand_name}, an AI automation platform. Style: {style_desc}. Colors: {colors}. Clean, modern, high quality, suitable for business use.
```

**Prompt 2:**
```
[Alternative prompt with different composition/angle]
```

### Stable Diffusion Prompts

**Prompt 1:**
```
[SD-optimized prompt with quality boosters: masterpiece, best quality, ultra detailed, professional design, etc.]
```

---

## DESIGN TOOLS & WORKFLOW

### Recommended Tools
| Tool | Purpose | Price | Skill Level |
| Canva | Social templates, quick designs | Free-$15/mo | Beginner |
| Figma | UI/web design, brand kits | Free-$15/mo | Intermediate |
| Adobe Express | Marketing materials | Free-$10/mo | Beginner |
| Midjourney | AI-generated visuals | $10-$60/mo | Any |
| Remove.bg | Background removal | Free-$10/mo | Any |

### 5-Step Design Workflow for Non-Designers
1. [Step 1: Generate raw visual with AI prompt above]
2. [Step 2: Import to Canva, add text and brand elements]
3. [Step 3: Apply brand colors using the color codes]
4. [Step 4: Check visual hierarchy and readability]
5. [Step 5: Export in correct format for each use case]

## BRAND STYLE GUIDE SUMMARY

One-page brand guide for {brand_name}:
- **Logo usage:** [Rules for clear space, minimum size, what backgrounds to use on]
- **Color don'ts:** [What color combinations to avoid]
- **Font pairing rule:** [How to combine the fonts]
- **Photography style:** [If using photos -- what style, filters, subjects]
- **Icon style:** [Outline/filled/duotone + recommended icon library]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_brand = "".join(c if c.isalnum() else "_" for c in brand_name[:20])

        output = f"""# Design Brief: {design_type} for {brand_name}
**Style:** {style}
**Assets:** {assets_needed}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Designing Bot*
"""
        path = self.save_output(output, f"design_{design_type}_{safe_brand}_{ts}.md", ext="md")
        self.logger.info(f"Design brief saved -> {path}")
        return {"file": str(path), "design_type": design_type, "brand": brand_name}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Visual Design Brief & AI Prompt Generator")
    parser.add_argument("--type",    type=str, default="brand_kit",
                        choices=list(DESIGN_TYPES.keys()))
    parser.add_argument("--brand",   type=str, default="WheellsVerse")
    parser.add_argument("--style",   type=str, default="techy_futuristic",
                        choices=list(DESIGN_STYLES.keys()))
    parser.add_argument("--colors",  type=str, default=None)
    parser.add_argument("--assets",  type=str, default=None,
                        help="Comma-separated list of design assets to generate")
    args = parser.parse_args()
    bot = DesigningBot()
    result = bot.execute(design_type=args.type, brand_name=args.brand,
                         style=args.style, colors=args.colors,
                         assets_needed=args.assets)
    print(f"\n✅ Design Brief: {result['file']}")
