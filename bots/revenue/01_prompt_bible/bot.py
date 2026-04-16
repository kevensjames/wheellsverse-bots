#!/usr/bin/env python3
"""
Revenue Stream #1 — The Prompt Bible
Purpose: Generates and sells a mega-pack of 10,000 ChatGPT prompts.
         Organized into 20 categories, 500 prompts each.
         Sells at $47 on Gumroad. Auto-promotes on FB + IG daily.
         Generates new prompt batches and refreshes the product.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a master prompt engineer with deep expertise in ChatGPT, Claude,
and all major AI systems. You've created prompt libraries used by 50,000+ people.
Your prompts are specific, tested, and produce remarkable results — not vague
generic instructions. You write prompts for real-world use cases that save time,
make money, or create value. Each prompt follows the structure: Role + Context +
Task + Format + Constraints. You organize prompts logically and make every pack
feel like it's worth 10x the price."""

CATEGORIES = [
    ("Business & Entrepreneurship", "starting businesses, revenue ideas, pitch decks, business plans"),
    ("Passive Income & Finance", "investments, side hustles, crypto analysis, financial planning"),
    ("AI & Automation", "automating tasks, building AI tools, prompt chaining, workflows"),
    ("Content Creation", "blog posts, social media, viral content, storytelling"),
    ("Email Marketing", "subject lines, sequences, cold outreach, newsletters"),
    ("Copywriting & Sales", "sales pages, ads, VSLs, persuasion, conversion"),
    ("YouTube & Video", "scripts, hooks, titles, thumbnails, video SEO"),
    ("SEO & Blogging", "keyword research, article outlines, meta descriptions, link building"),
    ("eCommerce & Dropshipping", "product descriptions, store copy, customer service, ads"),
    ("Crypto & DeFi", "coin analysis, DeFi strategies, tokenomics, market signals"),
    ("Productivity & Life Hacks", "time management, focus, routines, habits, decision making"),
    ("Career & Job Search", "resumes, cover letters, interview prep, salary negotiation"),
    ("Education & Learning", "study guides, explanations, quizzes, course creation"),
    ("Health & Fitness", "workout plans, meal prep, motivation, habit tracking"),
    ("Real Estate", "property analysis, rental strategies, flipping, negotiation"),
    ("Social Media Growth", "Instagram, Facebook, TikTok, community building, engagement"),
    ("Customer Research", "ICP definition, survey creation, pain point analysis, personas"),
    ("Product Development", "ideation, validation, MVP planning, feature prioritization"),
    ("Legal & Compliance", "contracts, terms of service, privacy policies, disclaimer templates"),
    ("Mindset & Motivation", "goal setting, affirmations, journaling, mental models"),
]


class PromptBibleBot(BaseBot):

    def __init__(self):
        super().__init__("01_prompt_bible", "revenue")
        import os
        self.gumroad_url = os.getenv("GUMROAD_PROMPT_BIBLE_URL", "https://gum.co/wheellsverse-prompts")
        self.price = "$47"

    def run(self, action: str = "generate", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "generate")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "generate": self._generate_batch,
            "promote": self._promote,
            "full": self._generate_full_bible,
            "listing": self._gumroad_listing,
        }
        fn = actions.get(action, self._generate_batch)
        return fn(ts, **kwargs)

    def _generate_batch(self, ts: str, **kwargs) -> dict:
        """Generate 50 prompts per category for a daily refresh."""
        category_idx = kwargs.get("category_idx", datetime.now().day % len(CATEGORIES))
        cat_name, cat_desc = CATEGORIES[category_idx]

        prompt = f"""Generate 50 high-quality, unique ChatGPT prompts for the category: {cat_name}

Category focus: {cat_desc}

For each prompt:
- Number it (1-50)
- Make it immediately usable — copy-paste ready
- Include [VARIABLES] in brackets where customization is needed
- Range from beginner to advanced use cases
- Each prompt should produce a genuinely useful output

Format:
## {cat_name} Prompts

**Prompt 1:** [prompt text here]
**Best for:** [1-line use case]
---
[repeat for all 50]

Quality bar: Every prompt must be specific enough that you'd pay $1 for it individually.
No filler. No generic "write me a blog post" type prompts."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=4000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "prompt_bible"
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"prompts_{cat_name.lower().replace(' ', '_').replace('&', 'and')}_{ts}.md"
        (out_dir / fname).write_text(result, encoding="utf-8")
        path = self.save_output(result, fname, ext="md")
        self.logger.info("Generated 50 prompts for: %s", cat_name)
        return {"file": str(path), "action": "generate", "category": cat_name}

    def _generate_full_bible(self, ts: str, **kwargs) -> dict:
        """Generate the master prompt bible table of contents + sample."""
        prompt = f"""Create the complete table of contents and introduction for the PROMPT BIBLE.

Product: The Prompt Bible — 10,000 ChatGPT Prompts for Entrepreneurs
Price: {self.price} | Seller: WheellsVerse

TOC Structure:
{chr(10).join(f"- Category {i + 1}: {cat} — 500 prompts" for i, (cat, _) in enumerate(CATEGORIES))}

Write:
1. PRODUCT DESCRIPTION (300 words) — sell the transformation
2. FULL TABLE OF CONTENTS — with brief description of each category
3. SAMPLE PROMPTS — 5 example prompts from 3 different categories to show quality
4. GUARANTEE TEXT — 30-day money back guarantee copy
5. FAQ SECTION — 8 questions and answers
6. WHAT'S INCLUDED — bullet list of everything in the pack

This is the master file that introduces the entire product."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "prompt_bible"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "00_PROMPT_BIBLE_MASTER.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"prompt_bible_master_{ts}.md", ext="md")
        return {"file": str(path), "action": "full"}

    def _promote(self, ts: str, **kwargs) -> dict:
        """Generate and publish daily promotional post."""
        prompt = f"""Create a viral promotional post for The Prompt Bible.

Product: 10,000 ChatGPT Prompts | Price: {self.price}
Link: {self.gumroad_url}

Generate 2 versions:
1. FACEBOOK POST (200 words):
   - Hook: surprising benefit or shocking stat about AI prompts
   - Value: what 10,000 prompts means for their daily work
   - Social proof: "50,000+ prompts downloaded" (aspirational)
   - Urgency: limited launch pricing
   - CTA: link to {self.gumroad_url}
   - 3-5 hashtags

2. INSTAGRAM CAPTION (100 words):
   - First line stops scroll (question or bold claim)
   - Quick benefits list with emojis
   - CTA: "Link in bio → Prompt Bible"
   - 20 hashtags including #ChatGPT #AIPrompts #AITools

Make it feel like you're sharing a secret weapon, not selling a product."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"promo_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            lines = result.split("\n")
            fb_lines, ig_lines = [], []
            in_fb, in_ig = False, False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb, in_ig = True, False
                elif "INSTAGRAM" in line.upper():
                    in_fb, in_ig = False, True
                elif in_fb:
                    fb_lines.append(line)
                elif in_ig:
                    ig_lines.append(line)
            fb_text = "\n".join(fb_lines).strip()
            ig_text = "\n".join(ig_lines).strip()
            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured() and fb_text:
                fb.post(fb_text)
            if ig.is_configured() and ig_text:
                ig.post(ig_text)
        except Exception as e:
            self.logger.debug("Promo post skipped: %s", e)

        return {"file": str(path), "action": "promote"}

    def _gumroad_listing(self, ts: str, **kwargs) -> dict:
        """Generate complete Gumroad product listing."""
        prompt = f"""Write a complete Gumroad product listing for The Prompt Bible.

Product: 10,000 ChatGPT Prompts for Entrepreneurs
Price: {self.price}
Creator: WheellsVerse

Gumroad listing sections:
1. TITLE (max 80 chars) — keyword-rich, benefit-driven
2. SHORT DESCRIPTION (150 chars) — shows in search results
3. LONG DESCRIPTION (800-1000 words) — full sales copy
   - Opening hook
   - Who it's for
   - What's inside (categories + prompt count)
   - 10 specific use cases with results
   - Testimonials (3, realistic but aspirational)
   - Price justification
   - Guarantee
4. BULLET POINTS (8 key benefits)
5. TAGS (10 Gumroad tags for discoverability)
6. SUGGESTED UPSELL — what to offer at checkout

Format ready to copy-paste into Gumroad."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "prompt_bible"
        (out_dir / "gumroad_listing.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"gumroad_listing_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📚 Prompt Bible — Gumroad Listing Ready\n💰 Price: {self.price}\n📁 {Path(str(path)).name}\n🔗 Upload to: {self.gumroad_url}")
        except Exception:
            pass

        return {"file": str(path), "action": "listing"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prompt Bible Revenue Bot")
    parser.add_argument("--action", default="generate",
                        choices=["generate", "promote", "full", "listing"])
    parser.add_argument("--category-idx", type=int, default=None)
    args = parser.parse_args()
    bot = PromptBibleBot()
    result = bot.execute(action=args.action, category_idx=args.category_idx)
    print(f"\n✅ Prompt Bible: {result['file']}")
