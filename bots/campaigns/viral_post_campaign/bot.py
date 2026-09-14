#!/usr/bin/env python3
"""
Bot — Viral Post Campaign Generator
Category: Campaigns
Purpose: Orchestrates all viral marketing and social media growth expert bots to generate
         5 HIGH-CONVERTING posts per platform (Facebook, Instagram, Twitter) with full
         9-component structure: Hook, Value Offer, Social Proof, Urgency, CTA,
         Hashtags, Image Idea, Psychology.

Niche: AI, Make Money Online, Automation, Tech Tools
"""
import os
import sys
from datetime import datetime as _dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.base_bot import BaseBot  # noqa: E402

# ── Platform specifications ──────────────────────────────────────────────────
PLATFORM_SPECS = {
    "facebook": {
        "format": "Storytelling narrative — start with a hook story, then reveal the offer",
        "length": "150–300 words",
        "tone": "Inspiring, conversational, slightly personal — like a friend sharing a secret",
        "hashtags": "3–5 hashtags, broad community tags only",
        "cta": "Comment with a trigger word (e.g., 'Comment AI below') OR DM instruction",
        "strength": "Shares and comments — storytelling drives emotional reactions and reshares",
    },
    "instagram": {
        "format": "Clean spaced lines — one idea per line, generous whitespace, emoji accents",
        "length": "80–120 words (body) + 20–25 hashtags in first comment or end",
        "tone": "Visual, punchy, aspirational — feels like a pro creator post",
        "hashtags": "20–25 hashtags mixing mega (1M+), mid (100K–1M), niche (<100K)",
        "cta": "Comment trigger word on its own line, then emoji (e.g., 'Drop AI below 👇')",
        "strength": "Saves and shares — Instagram rewards saves for reach",
    },
    "twitter": {
        "format": "Short punchy tweet OR 3-tweet thread (mark Thread: 1/3, 2/3, 3/3)",
        "length": "240–260 characters per tweet, max 280",
        "tone": "Controversial, direct, slightly provocative — makes people want to reply",
        "hashtags": "2–3 hashtags maximum, inline or at end",
        "cta": "Reply trigger word (e.g., 'Reply PROMPTS') or retweet hook",
        "strength": "Replies and retweets — controversy and utility drive quote-tweets",
    },
}

# ── 5 core niche angles (same across platforms, adapted per tone) ─────────────
NICHE_ANGLES = [
    {
        "angle": "Free AI tool — 6-month free access giveaway",
        "hook_theme": "shocking free offer",
        "value": "6 months free on a premium AI tool",
        "proof_stat": "50,000+ users already using this",
        "urgency": "Only available until [date] — then it's gone",
        "offer_detail": "AI writing/automation tool with $297/mo value — free for 6 months",
    },
    {
        "angle": "$500/day income automation system",
        "hook_theme": "income result revelation",
        "value": "Step-by-step automation system to generate $500/day",
        "proof_stat": "3,200+ people already running this system",
        "urgency": "Limited spots — closing this week",
        "offer_detail": "Full automation workflow (AI + no-code tools) for passive income",
    },
    {
        "angle": "10,000 ChatGPT prompts mega-pack giveaway",
        "hook_theme": "massive free resource",
        "value": "10,000 battle-tested ChatGPT prompts across 50+ categories",
        "proof_stat": "Downloaded 12,000+ times — top creators are using these",
        "urgency": "Free for 48 hours only — then it's $97",
        "offer_detail": "Prompts for content, business, sales, coding, social media, and more",
    },
    {
        "angle": "Secret automation workflow used by top creators",
        "hook_theme": "insider secret reveal",
        "value": "The exact AI automation stack top creators use to 10x output",
        "proof_stat": "Used by creators doing $10K–$50K/month",
        "urgency": "Sharing this for free — before it becomes a paid course",
        "offer_detail": "Full workflow: content → repurpose → schedule → monetize, all automated",
    },
    {
        "angle": "AI tool that replaces a full team",
        "hook_theme": "replace expensive staff",
        "value": "One AI tool that does the work of a $5,000/month team",
        "proof_stat": "Saved 8,000+ businesses over $2M in staffing costs",
        "urgency": "Beta access closing soon — get in before price hike",
        "offer_detail": "AI handles: content, emails, customer service, social media, analytics",
    },
]

SYSTEM_PROMPT = """You are the world's most elite viral social media campaign strategist — a fusion of five specialist experts:

1. VIRAL FORMULA ARCHITECT: You reverse-engineer exactly why content goes viral — not vague advice, but specific psychological triggers (curiosity gap, social proof, identity signal, FOMO, controversy, utility) with replicable formulas.

2. MULTI-PLATFORM NATIVE STRATEGIST: You know each platform is a different country. Facebook needs story. Instagram needs spacing and aesthetics. Twitter needs controversy and punch. You never copy-paste — you rewrite for native feel.

3. SCROLL-STOPPING COPYWRITER: The first line is everything. You write hooks so magnetic they physically stop thumbs mid-scroll. You use power words, numbers, and pattern interrupts.

4. HASHTAG & ALGORITHM OPTIMIZER: You build hashtag stacks that beat the algorithm — mixing reach tiers, platform-specific limits, and trending tags.

5. GROWTH HACKER: You engineer engagement loops — CTAs that force replies, comment triggers that spike reach, DM funnels that convert followers into leads.

YOUR RULES:
- Use simple, powerful words. No corporate speak.
- No long paragraphs — bullets, line breaks, white space.
- Make content feel exclusive, secret, and insider.
- Use numbers always (10K, 20x, $500/day, 6 months, etc.)
- Tone: confident, slightly mysterious, urgency-driven.
- Every post must feel irresistible — like the viewer would feel STUPID not to engage."""


def _build_platform_prompt(platform: str, spec: dict, angles: list, posts_count: int) -> str:
    """Build a generation prompt for one platform."""

    # Pre-build angle blocks to avoid nested f-strings
    angle_blocks = []
    for i, a in enumerate(angles[:posts_count], 1):
        block = (
            f"POST {i} ANGLE: {a['angle']}\n"
            f"  Hook theme: {a['hook_theme']}\n"
            f"  Core value: {a['value']}\n"
            f"  Social proof stat: {a['proof_stat']}\n"
            f"  Urgency: {a['urgency']}\n"
            f"  Offer detail: {a['offer_detail']}"
        )
        angle_blocks.append(block)
    angles_section = "\n\n".join(angle_blocks)

    prompt = f"""Generate {posts_count} VIRAL posts for **{platform.upper()}** in the AI / Make Money Online / Automation niche.

## PLATFORM SPECS
- Format: {spec['format']}
- Length: {spec['length']}
- Tone: {spec['tone']}
- Hashtags: {spec['hashtags']}
- CTA style: {spec['cta']}
- Platform strength: {spec['strength']}

## ANGLES TO USE (one per post)
{angles_section}

---

## OUTPUT FORMAT — Repeat this exact structure for each post:

### POST [N] — [ANGLE NAME]

**🪝 HOOK**
[First line — shocking, bold, curiosity-driven. Must stop the scroll instantly.]

**🎁 VALUE OFFER**
[What they get — specific, tangible, high perceived value]

**📊 SOCIAL PROOF**
[Stats line: "X,000+ people", "used by top creators", etc.]

**⏰ URGENCY / SCARCITY**
[Time or quantity limit — feels real, not fake]

**📣 FULL POST COPY**
[Complete ready-to-copy post in {platform.upper()} native format and tone.
{spec['format']}. Length: {spec['length']}. Include all elements naturally woven in.]

**#️⃣ HASHTAGS**
[{spec['hashtags']}]

**🖼️ IMAGE IDEA**
[Exact image description: background color, person/object, text overlay, font style, mood.
Be specific enough for a designer or DALL-E to recreate it.]

**🧠 PSYCHOLOGY USED**
[1–2 sentences: name the exact triggers (FOMO, curiosity gap, social proof, etc.) and why this post works]

---

Generate all {posts_count} posts now. Make each one feel different — vary hooks, tone shifts, and CTAs so they don't repeat each other.
"""
    return prompt


class ViralPostCampaignBot(BaseBot):
    NAME = "Viral Post Campaign"

    def __init__(self):
        super().__init__("viral_post_campaign", "campaigns")

    def run(self, **kwargs):
        cfg = self.config
        niche = kwargs.get("niche") or cfg.get("niche", "AI, Make Money Online, Automation, Tech Tools")
        posts_per_platform = int(kwargs.get("posts") or cfg.get("posts_per_platform", 5))
        platforms = kwargs.get("platforms") or cfg.get("platforms", "facebook,instagram")
        platform_list = [p.strip().lower() for p in platforms.split(",")]

        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_niche = self.slugify(niche, 25)
        timestamp_readable = _dt.now().strftime("%Y-%m-%d %H:%M")

        self.logger.info(f"Generating {posts_per_platform} viral posts for: {platform_list}")

        # ── Header ────────────────────────────────────────────────────────────
        all_output = f"""# Viral Post Campaign — {niche}
**Platforms:** {', '.join(p.upper() for p in platform_list)}
**Posts per platform:** {posts_per_platform}
**Generated:** {timestamp_readable}

---

"""
        # ── Generate per platform ─────────────────────────────────────────────
        for platform in platform_list:
            if platform not in PLATFORM_SPECS:
                self.logger.warning(f"Unknown platform '{platform}' — skipping.")
                continue

            spec = PLATFORM_SPECS[platform]
            self.logger.info(f"Generating {posts_per_platform} posts for {platform.upper()}...")

            prompt = _build_platform_prompt(platform, spec, NICHE_ANGLES, posts_per_platform)

            result = self.ai(
                prompt,
                system=SYSTEM_PROMPT,
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=4000,
            )

            all_output += f"---\n\n## {platform.upper()} POSTS\n\n{result}\n\n"

        # ── Footer ────────────────────────────────────────────────────────────
        all_output += "---\n*Generated by WheellsVerse Viral Post Campaign Bot*\n"

        # ── Save ──────────────────────────────────────────────────────────────
        filename = f"viral_campaign_{safe_niche}_{ts}.md"
        path = self.save_output(all_output, filename, ext="md")

        self.logger.info(f"Campaign saved: {path}")
        return {
            "file": str(path),
            "niche": niche,
            "platforms": platform_list,
            "posts_per_platform": posts_per_platform,
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Viral Post Campaign Generator")
    parser.add_argument("--niche", type=str, default=None, help="Content niche")
    parser.add_argument("--posts", type=int, default=None, help="Posts per platform (default 5)")
    parser.add_argument("--platforms", type=str, default=None, help="Comma-separated platforms (default: facebook,instagram,twitter)")
    args = parser.parse_args()

    bot = ViralPostCampaignBot("Viral Post Campaign", "campaigns")
    result = bot.run(
        niche=args.niche,
        posts=args.posts,
        platforms=args.platforms,
    )
    print(f"\n✅ Campaign saved: {result['file']}")
    print(f"   Platforms: {', '.join(result['platforms'])}")
    print(f"   Posts per platform: {result['posts_per_platform']}")
