#!/usr/bin/env python3
"""
Bot #45 — Multi-Platform Content Adapter
Category: Social Media
Purpose: Take one core piece of content and adapt it into platform-optimized posts
         for every major social media channel -- maximizing reach from a single idea.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

PLATFORM_SPECS = {
    "twitter": {
        "format": "Single tweet or thread",
        "length": "280 chars per tweet; threads up to 25 tweets",
        "tone": "Concise, punchy, direct -- conversational or bold takes",
        "hashtags": "1-2 max, only if trending or essential",
        "cta": "Reply, retweet, follow, click link",
        "strength": "Real-time conversation, thought leadership, viral threads",
    },
    "linkedin": {
        "format": "Long-form text post or article",
        "length": "150-300 words for posts; 1,500+ for articles",
        "tone": "Professional but personal -- storytelling + data",
        "hashtags": "3-5 industry hashtags at end",
        "cta": "Comment your thoughts, connect, visit website",
        "strength": "B2B audience, professional authority, career/business topics",
    },
    "instagram": {
        "format": "Caption + image/carousel/reel concept",
        "length": "125-150 chars before 'more' -- hook immediately",
        "tone": "Aspirational, visual-first, authentic voice",
        "hashtags": "20-30 highly targeted (first comment or end of caption)",
        "cta": "Save, share, follow, comment, link in bio",
        "strength": "Visual storytelling, lifestyle/brand building, DM conversion",
    },
    "tiktok": {
        "format": "Video concept + caption",
        "length": "Caption under 150 chars; video 15-90s",
        "tone": "Entertaining, fast-paced, trend-aware, unpolished is OK",
        "hashtags": "3-5 niche + trending tags",
        "cta": "Follow, duet, stitch, comment, try this",
        "strength": "Discovery, mass reach, Gen Z/Millennial, fast virality",
    },
    "facebook": {
        "format": "Post or group content",
        "length": "40-80 words for best reach; can go longer for groups",
        "tone": "Warm, community-oriented, shareable",
        "hashtags": "1-3 hashtags",
        "cta": "Share, comment, tag a friend",
        "strength": "Groups, community building, ads ecosystem",
    },
    "youtube_shorts": {
        "format": "60-second video concept + description",
        "length": "Description 1-2 sentences; video max 60s",
        "tone": "Educational or entertaining -- hook in first 3 seconds",
        "hashtags": "#Shorts + 2-3 topic hashtags in title/description",
        "cta": "Subscribe, watch full video, leave a comment",
        "strength": "Search discovery, long-term SEO, YouTube ecosystem",
    },
}


class MultiPlatformPosterBot(BaseBot):

    def __init__(self):
        super().__init__("45_multi_platform_poster", "social_media")

    def run(self, core_content: str = None, platforms: str = None,
            content_type: str = None, goal: str = None, **kwargs):

        cfg = self.config
        core_content = core_content or cfg.get("core_content",
            "AI bots can automate 80% of repetitive business tasks, freeing entrepreneurs to focus on growth")
        platforms = platforms or cfg.get("platforms", "twitter,linkedin,instagram,tiktok")
        content_type = content_type or cfg.get("content_type", "educational tip")
        goal = goal or cfg.get("goal", "drive traffic to WheellsVerse and grow followers")

        platform_list = [p.strip() for p in platforms.split(",")]
        self.logger.info(f"Adapting content for {len(platform_list)} platforms: {platforms}")

        platform_spec_text = "\n".join([
            f"**{p.upper()}**: {PLATFORM_SPECS.get(p, {}).get('tone', 'standard')} | "
            f"Length: {PLATFORM_SPECS.get(p, {}).get('length', 'varies')} | "
            f"Strength: {PLATFORM_SPECS.get(p, {}).get('strength', 'general')}"
            for p in platform_list
        ])

        # Pre-compute platform adaptations to avoid nested triple-quoted f-strings (Python 3.11)
        platform_adaptations = "".join(
            f"### {p.upper()} VERSION\n\n"
            f"**Format:** {PLATFORM_SPECS.get(p, {}).get('format', 'Post')}\n"
            "**Tone shift from original:** [How this differs from the core content's raw tone]\n"
            f"**Native elements added:** [What was added to make it feel native to {p}]\n\n"
            "**Post content:**\n"
            "```\n"
            f"{{{p.upper()}_CONTENT}}\n"
            f"[Write the full, complete, publish-ready post for {p} here]\n"
            "```\n\n"
            "**Hashtags:**\n"
            "```\n"
            f"[Platform-appropriate hashtags for {p}]\n"
            "```\n\n"
            f"**Visual/media note:** [What image, graphic, or video concept works for {p}]\n"
            f"**Best post time:** [Specific day/time recommendation for {p}]\n"
            f"**Expected outcome:** [What this post is designed to do on {p} specifically]\n\n"
            "---\n\n"
            for p in platform_list
        )

        system = (
            "You are a multi-platform content strategist who understands that each social "
            "media platform is a different country with its own language, culture, and rules. "
            "You take one strong core idea and transform it -- not just copy-paste with minor edits -- "
            "into content that feels native to each platform. A LinkedIn post should sound like "
            "LinkedIn. A TikTok caption should sound like TikTok. You never post the same thing "
            "on every platform. You also understand content repurposing strategy: which platform "
            "to post on first (the 'primary'), and how to sequence the others for maximum reach."
        )

        prompt = f"""Adapt this core content for {len(platform_list)} platforms:

CORE CONTENT: {core_content}
CONTENT TYPE: {content_type}
GOAL: {goal}
PLATFORMS: {', '.join(platform_list)}
BRAND: WheellsVerse - AI automation tools for entrepreneurs

Platform profiles:
{platform_spec_text}

## CONTENT STRATEGY

**Core message (distilled):** [Single sentence -- the idea that powers every adaptation]
**Primary audience segment:** [Who this content is reaching across all platforms]
**Content pillar:** [Education / Inspiration / Entertainment / Promotion / Behind-the-scenes]

**Publishing sequence recommendation:**
1. **First:** [Platform + why -- where to get the most initial traction]
2. **Second:** [Platform + timing after first post]
3. **Third:** [Platform + timing]
[Continue for all {len(platform_list)} platforms]

---

## PLATFORM ADAPTATIONS

{platform_adaptations}

## CROSS-PLATFORM AMPLIFICATION TACTICS

**Within 24 hours of your primary post:**
1. [Action to amplify across platforms]
2. [Action to drive cross-platform traffic]
3. [Engagement strategy to boost all posts simultaneously]

**How to repurpose the performance data:**
[What to measure after 48 hours and how it informs your next multi-platform post]

## CONTENT RECYCLING SCHEDULE

How to reuse this content batch over the next 30 days:
| Week | Platform | Angle/Variation | Notes |
| Week 1 | Primary platform | Original post | |
| Week 2 | [Platform] | [Different angle] | |
| Week 3 | [Platform] | [Different angle] | |
| Week 4 | All | Updated version with results | Add performance data |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_content = "".join(c if c.isalnum() else "_" for c in core_content[:25])

        output = f"""# Multi-Platform Content Adaptation
**Core Content:** {core_content}
**Platforms:** {platforms}
**Goal:** {goal}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Multi-Platform Poster Bot*
"""
        path = self.save_output(output, f"multipost_{safe_content}_{ts}.md", ext="md")
        self.logger.info(f"Multi-platform content saved -> {path}")
        return {"file": str(path), "platforms": platform_list, "content_type": content_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Platform Content Adapter")
    parser.add_argument("--content", type=str, default=None,
                        help="Core content idea or message to adapt")
    parser.add_argument("--platforms", type=str, default="twitter,linkedin,instagram,tiktok")
    parser.add_argument("--type", type=str, default="educational tip")
    parser.add_argument("--goal", type=str, default=None)
    args = parser.parse_args()
    bot = MultiPlatformPosterBot()
    result = bot.execute(core_content=args.content, platforms=args.platforms,
                         content_type=args.type, goal=args.goal)
    print(f"\n✅ Multi-Platform Content: {result['file']}")
