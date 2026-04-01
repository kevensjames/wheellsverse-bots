#!/usr/bin/env python3
"""
Bot #43 — Short-Form Video Script Generator
Category: Social Media
Purpose: Write complete, production-ready video scripts for TikTok, Instagram Reels,
         and YouTube Shorts with hooks, beat-by-beat structure, and on-screen text cues.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

SCRIPT_STYLES = {
    "educational":   "teach one concept with clear steps and aha moments",
    "storytelling":  "personal story arc with relatable struggle and resolution",
    "listicle":      "numbered tips/tools/ideas with fast cuts",
    "talking_head":  "direct-to-camera commentary or opinion piece",
    "tutorial":      "step-by-step how-to with screen shares or demos",
    "reaction":      "react to a trend, tool, or common belief in the niche",
    "comparison":    "X vs Y breakdown to help audience make a decision",
    "hook_challenge": "controversial opener that challenges a common belief",
}

PLATFORM_LENGTHS = {
    "tiktok":          {"short": "15-30s", "medium": "45-60s", "long": "90-180s"},
    "instagram_reels": {"short": "15-30s", "medium": "30-60s", "long": "60-90s"},
    "youtube_shorts":  {"short": "30-45s", "medium": "45-60s", "long": "55-60s"},
}


class VideoScriptBot(BaseBot):

    def __init__(self):
        super().__init__("43_video_script", "social_media")

    def run(self, topic: str = None, platform: str = None,
            duration: str = None, style: str = None, **kwargs):

        cfg = self.config
        topic    = topic or cfg.get("topic", "5 AI tools that replace an entire team")
        platform = platform or cfg.get("platform", "tiktok")
        duration = duration or cfg.get("duration", "60s")
        style    = style or cfg.get("style", "listicle")

        style_desc = SCRIPT_STYLES.get(style, style)
        self.logger.info(f"Writing video script: {topic} ({duration} {style} for {platform})")

        system = (
            "You are a short-form video scriptwriter who has written scripts for creators "
            "with 500K-5M followers. You know that short-form video lives and dies by "
            "the first 2 seconds — if you don't hook them instantly, they're gone. "
            "You write scripts that are conversational, scannable, and paced for video. "
            "You think in beats, not paragraphs. You include on-screen text cues, "
            "B-roll suggestions, and delivery notes so creators can film confidently. "
            "You know the difference between a script that reads well and one that FILMS well."
        )

        prompt = f"""Write a complete, production-ready video script for:

TOPIC: {topic}
PLATFORM: {platform}
DURATION: {duration}
STYLE: {style} — {style_desc}
BRAND: WheellsVerse — AI automation tools for entrepreneurs

---

## PRE-PRODUCTION NOTES

**Core message (one sentence):** [The single idea the viewer walks away with]
**Target viewer:** [Who this is made for — be specific]
**Emotional journey:** [How viewer feels at start → middle → end]
**Hook strategy:** [Why this specific hook was chosen]

---

## FULL VIDEO SCRIPT

> FORMAT KEY:
> **[VISUAL]** = camera direction / B-roll / on-screen visual
> **[TEXT]** = on-screen text overlay
> **[DELIVERY]** = tone/energy note for the creator
> Spoken words are written out normally

---

### HOOK (0-3 seconds)
**[VISUAL]:** [Opening shot description]
**[TEXT]:** [On-screen text if any]
**[DELIVERY]:** [Energy — fast/slow/whisper/intense]

"[Exact spoken hook — must be under 15 words]"

---

### SETUP / PROBLEM (3-10 seconds)
**[VISUAL]:** [Shot description]
**[TEXT]:** [Text overlay]

"[Spoken lines — set up the tension or promise]"

---

### MAIN CONTENT — [Beat-by-beat for {duration}]

[Break into timed beats based on {duration} and {style}. For listicles: one beat per item. For stories: setup/conflict/resolution beats. For tutorials: step beats.]

**Beat 1 — [Name] (~[timestamp])**
**[VISUAL]:** [Description]
**[TEXT]:** [Text overlay]
"[Spoken lines]"

**Beat 2 — [Name] (~[timestamp])**
**[VISUAL]:** [Description]
**[TEXT]:** [Text overlay]
"[Spoken lines]"

[Continue for all beats...]

---

### PAYOFF / RESOLUTION (~{duration} minus 10s)
**[VISUAL]:** [Shot]
**[TEXT]:** [Text overlay]

"[The satisfying conclusion or revelation]"

---

### CTA / CLOSER (last 5 seconds)
**[VISUAL]:** [Shot]
**[TEXT]:** [Text overlay with CTA]

"[Spoken CTA — specific ask: follow, comment, click link in bio, etc.]"

---

## PRODUCTION CHECKLIST

**Before filming:**
- [ ] [Prep item 1]
- [ ] [Prop or tool needed]
- [ ] [Lighting/setup note]

**Filming tips for this script:**
- [Tip specific to this script's style/format]
- [Pacing note]
- [Common mistake to avoid]

## ALTERNATIVE HOOKS (A/B TEST THESE)

Hook A (Curiosity gap):
```
[15 words or less]
```

Hook B (Controversy):
```
[15 words or less]
```

Hook C (Bold claim):
```
[15 words or less]
```

## ON-SCREEN TEXT STRATEGY

Key text overlays that boost watch time for this video:
1. [Text + when to show it]
2. [Text + when to show it]
3. [Text + when to show it]

## REPURPOSING THIS SCRIPT

How to adapt this {duration} script for other formats:
- **Twitter thread:** [First 3 tweets of a thread version]
- **LinkedIn post:** [Opening paragraph of a LinkedIn adaptation]
- **Email subject line:** [If promoting this video via email]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:25])

        output = f"""# Video Script: {topic}
**Platform:** {platform}
**Duration:** {duration}
**Style:** {style}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Video Script Bot*
"""
        path = self.save_output(output, f"script_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Video script saved → {path}")
        return {"file": str(path), "topic": topic, "platform": platform, "duration": duration}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Short-Form Video Script Generator")
    parser.add_argument("--topic",    type=str, default=None)
    parser.add_argument("--platform", type=str, default="tiktok",
                        choices=["tiktok", "instagram_reels", "youtube_shorts"])
    parser.add_argument("--duration", type=str, default="60s")
    parser.add_argument("--style",    type=str, default="listicle",
                        choices=list(SCRIPT_STYLES.keys()))
    args = parser.parse_args()
    bot = VideoScriptBot()
    result = bot.execute(topic=args.topic, platform=args.platform,
                         duration=args.duration, style=args.style)
    print(f"\n✅ Video Script: {result['file']}")
