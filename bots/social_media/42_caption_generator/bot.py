#!/usr/bin/env python3
"""
Bot #42 — Social Media Caption Generator
Category: Social Media
Purpose: Generate platform-optimized social media captions for multiple platforms
         with different styles, hooks, hashtags, and CTAs for maximum engagement.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

CAPTION_STYLES = {
    "storytelling":    "Personal story or journey narrative -- relatable and emotional",
    "educational":     "Teach something valuable -- tips, how-to, facts, frameworks",
    "controversial":   "Bold opinion or contrarian take -- sparks debate and comments",
    "inspirational":   "Motivating and uplifting -- quotes, mindset, success stories",
    "behind_scenes":   "Transparency and authenticity -- process, failures, daily reality",
    "promotional":     "Product/service focused -- benefits, social proof, CTA-driven",
    "question":        "Engagement-first -- asks audience a question to drive comments",
    "listicle":        "Numbered tips or ranked items -- easy to consume, highly shareable",
}

PLATFORM_RULES = {
    "instagram": {"max_chars": 2200, "hashtags": "20-30", "line_breaks": "frequent"},
    "tiktok":    {"max_chars": 150,  "hashtags": "3-5",   "line_breaks": "minimal"},
    "twitter":   {"max_chars": 280,  "hashtags": "1-2",   "line_breaks": "minimal"},
    "linkedin":  {"max_chars": 3000, "hashtags": "3-5",   "line_breaks": "strategic"},
    "facebook":  {"max_chars": 500,  "hashtags": "1-3",   "line_breaks": "moderate"},
}


class CaptionGeneratorBot(BaseBot):

    def __init__(self):
        super().__init__("42_caption_generator", "social_media")

    def run(self, topic: str = None, platforms: str = None,
            num_captions: int = None, style: str = None, **kwargs):

        cfg = self.config
        topic       = topic or cfg.get("topic", "How AI automation saves entrepreneurs 10+ hours per week")
        platforms   = platforms or cfg.get("platforms", "instagram,tiktok,twitter,linkedin")
        num_captions = num_captions or cfg.get("num_captions", 3)
        style       = style or cfg.get("style", "storytelling")

        platform_list = [p.strip() for p in platforms.split(",")]
        style_desc    = CAPTION_STYLES.get(style, style)

        platform_specs = "\n".join([
            f"- **{p.upper()}**: max {PLATFORM_RULES.get(p, {}).get('max_chars', 'varies')} chars, "
            f"{PLATFORM_RULES.get(p, {}).get('hashtags', '5-10')} hashtags"
            for p in platform_list
        ])

        self.logger.info(f"Generating {num_captions} {style} captions for: {topic}")

        # Pre-compute caption sets to avoid nested triple-quoted f-strings (Python 3.11)
        def _platform_version(p):
            rules = PLATFORM_RULES.get(p, {})
            return (
                f"### {p.upper()} VERSION\n"
                "**Hook (first line):** [Scroll-stopping opener]\n\n"
                "**Full caption:**\n"
                "```\n"
                f"[Complete platform-optimized caption for {p} - max {rules.get('max_chars', 'varies')} chars]\n"
                "```\n\n"
                "**Hashtags:**\n"
                "```\n"
                f"[{rules.get('hashtags', '5-10')} hashtags for {p}]\n"
                "```\n\n"
                f"**Best posting time:** [Optimal time for {p}]\n"
                "**Expected engagement type:** [What this will drive - saves/comments/shares/clicks]\n\n"
            )

        caption_sets = "".join(
            f"## CAPTION SET {i+1} - [Angle/Hook]\n\n"
            "**Core angle:** [What unique take/hook this caption leads with]\n"
            "**Emotional trigger:** [Curiosity / Aspiration / Fear of missing out / Relatability / etc.]\n\n"
            + "".join(_platform_version(p) for p in platform_list)
            + "---\n\n"
            for i in range(num_captions)
        )

        system = (
            "You are a social media copywriter who has written captions that have generated "
            "millions of impressions across Instagram, TikTok, LinkedIn, and Twitter. "
            "You know that the first line is everything -- if it doesn't stop the scroll, "
            "nothing else matters. You write captions that feel native to each platform: "
            "Instagram is visual and emotional, TikTok is raw and trendy, LinkedIn is "
            "professional but personal, Twitter is punchy and opinionated. "
            "You never write generic captions -- every word earns its place."
        )

        prompt = f"""Generate {num_captions} unique social media captions for:

TOPIC: {topic}
STYLE: {style} -- {style_desc}
PLATFORMS: {', '.join(platform_list)}
BRAND: WheellsVerse -- AI automation tools for entrepreneurs

Platform specifications:
{platform_specs}

## CAPTION STRATEGY NOTE
[In 2-3 sentences: why the {style} style works well for "{topic}" and what emotional angle to take]

---

{caption_sets}

## HOOK SWIPE FILE

10 proven first-line hooks for {topic} content:
1. [Hook]
2. [Hook]
3. [Hook]
4. [Hook]
5. [Hook]
6. [Hook]
7. [Hook]
8. [Hook]
9. [Hook]
10. [Hook]

## CTA VARIATIONS

5 different CTAs ranked by conversion intent:
| CTA | Intent Level | Best Used When |
| [CTA 1] | High | |
| [CTA 2] | Medium | |
| [CTA 3] | Low | |
| [CTA 4] | Engagement | |
| [CTA 5] | Soft | |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:25])

        output = f"""# Social Media Captions: {topic}
**Style:** {style}
**Platforms:** {platforms}
**Captions Generated:** {num_captions}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Caption Generator Bot*
"""
        path = self.save_output(output, f"captions_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Captions saved -> {path}")
        return {"file": str(path), "topic": topic, "platforms": platform_list}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Social Media Caption Generator")
    parser.add_argument("--topic",    type=str, default=None)
    parser.add_argument("--platform", type=str, default="instagram,tiktok,twitter,linkedin")
    parser.add_argument("--count",    type=int, default=3)
    parser.add_argument("--style",    type=str, default="storytelling",
                        choices=list(CAPTION_STYLES.keys()))
    args = parser.parse_args()
    bot = CaptionGeneratorBot()
    result = bot.execute(topic=args.topic, platforms=args.platform,
                         num_captions=args.count, style=args.style)
    print(f"\n✅ Captions: {result['file']}")
