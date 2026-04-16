#!/usr/bin/env python3
"""
Bot #48 — Long-Form Script Writer (YouTube / Podcast / Webinar / Sales Video)
Category: Writing
Purpose: Write complete, production-ready scripts for YouTube videos, podcasts,
         webinars, and sales videos — with hooks, segments, transitions, and CTAs.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

SCRIPT_FORMATS = {
    "youtube_video": {
        "desc": "YouTube educational/entertainment video with retention tactics",
        "length": "8-15 minutes (~1,500-2,500 words of spoken script)",
        "structure": "Hook → Context → Promise → Main Content (5-7 segments) → CTA → Outro",
    },
    "podcast_episode": {
        "desc": "Podcast episode — solo or interview format",
        "length": "20-45 minutes (~3,000-6,000 words)",
        "structure": "Intro → Topic intro → Main discussion (4-6 segments) → Key takeaways → CTA → Outro",
    },
    "webinar": {
        "desc": "Live or recorded webinar for lead generation or sales",
        "length": "45-90 minutes (~6,000-12,000 words)",
        "structure": "Welcome → Problem agitation → Content (5-7 sections) → Offer reveal → Q&A → Close",
    },
    "sales_video": {
        "desc": "VSL (Video Sales Letter) for product or service promotion",
        "length": "10-20 minutes (~2,000-3,500 words)",
        "structure": "Attention → Problem → Agitation → Solution → Proof → Offer → Urgency → CTA",
    },
    "explainer_video": {
        "desc": "Short explainer or product demo video",
        "length": "2-5 minutes (~400-900 words)",
        "structure": "Hook → Problem → Solution → How it works → Social proof → CTA",
    },
}


class ScriptWriterBot(BaseBot):

    def __init__(self):
        super().__init__("48_script_writer", "writing")

    def run(self, topic: str = None, format_type: str = None,
            duration: str = None, audience: str = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("topic", "How I automated my business with 70 AI bots")
        format_type = format_type or cfg.get("format_type", "youtube_video")
        duration = duration or cfg.get("duration", None)
        audience = audience or cfg.get("audience", "entrepreneurs and business owners")

        fmt = SCRIPT_FORMATS.get(format_type, SCRIPT_FORMATS["youtube_video"])
        fmt_desc = fmt["desc"]
        fmt_length = duration or fmt["length"]
        fmt_structure = fmt["structure"]

        self.logger.info(f"Writing {format_type} script: {topic}")

        system = (
            "You are a professional scriptwriter with credits on YouTube channels that have "
            "generated 10M+ views, podcast episodes in the top 1% globally, and webinars that "
            "have converted at 15%+. You write scripts that are spoken, not read — your sentences "
            "are shorter, your transitions are conversational, and your pacing builds engagement "
            "deliberately. You know the three laws of retention: hook them fast, promise value early, "
            "and deliver more than expected. You write for the ear, not the eye. Every script you "
            "deliver is production-ready — talent can read it word-for-word and it sounds natural."
        )

        prompt = f"""Write a complete, production-ready script for:

TOPIC: {topic}
FORMAT: {format_type} — {fmt_desc}
TARGET LENGTH: {fmt_length}
AUDIENCE: {audience}
STRUCTURE: {fmt_structure}
BRAND: WheellsVerse — AI automation tools for entrepreneurs

---

## PRE-SCRIPT BRIEF

**Core message:** [Single sentence — what the audience will take away]
**Emotional arc:** [How the audience should feel: curious → engaged → inspired → motivated]
**Key talking points (in order):**
1. [Point 1]
2. [Point 2]
3. [Point 3]
[Continue...]

**On-screen/production notes overview:** [Global notes for this format]

---

## FULL SCRIPT

> NOTATION:
> [PAUSE] = natural pause for effect
> [B-ROLL: description] = visual suggestion
> [TEXT ON SCREEN: text] = on-screen graphic
> [ENERGY: note] = delivery instruction
> **Bold** = emphasize this word
> --- = scene/segment break

---

### HOOK / COLD OPEN (first 30-60 seconds)
[ENERGY: high energy, pattern interrupt]

[Write the exact spoken words for the hook — make the first sentence impossible to skip]

[B-ROLL: opening visual]

---

### INTRO / CONTEXT SETTING

[Spoken intro — establish credibility, set up the topic, tease what's coming]

[TEXT ON SCREEN: {topic}]

---

### [MAIN SEGMENT 1 — Title]
[ENERGY: conversational, clear]

[Spoken content for this segment]

[B-ROLL: relevant visual]
[PAUSE]

---

### [MAIN SEGMENT 2 — Title]

[Spoken content]

---

[Continue all segments following the structure: {fmt_structure}]

---

### CALL TO ACTION

[ENERGY: direct and warm, not salesy]

[Exact CTA language — what to do, why, how]

---

### OUTRO

[Closing — thank them, tease next content, sign-off]

---

## PRODUCTION CHECKLIST

- [ ] Hook uses pattern interrupt (question/statement/visual)
- [ ] Value promised within first 60 seconds
- [ ] B-roll opportunities marked throughout
- [ ] On-screen text reinforces key points
- [ ] Natural pauses built in (not wall-of-text delivery)
- [ ] CTA is specific with a clear next step
- [ ] Outro teases future content

## TIMESTAMPS / CHAPTERS

For {format_type} — suggested chapter markers:
| Timestamp | Chapter Name |
| 0:00 | [Hook/Intro] |
[Continue for all segments]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:25])

        output = f"""# Script: {topic}
**Format:** {format_type}
**Target Length:** {fmt_length}
**Audience:** {audience}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Script Writer Bot*
"""
        path = self.save_output(output, f"script_{format_type}_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Script saved → {path}")
        return {"file": str(path), "topic": topic, "format": format_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Long-Form Script Writer")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--format", type=str, default="youtube_video",
                        choices=list(SCRIPT_FORMATS.keys()))
    parser.add_argument("--duration", type=str, default=None)
    parser.add_argument("--audience", type=str, default=None)
    args = parser.parse_args()
    bot = ScriptWriterBot()
    result = bot.execute(topic=args.topic, format_type=args.format,
                         duration=args.duration, audience=args.audience)
    print(f"\n✅ Script: {result['file']}")
