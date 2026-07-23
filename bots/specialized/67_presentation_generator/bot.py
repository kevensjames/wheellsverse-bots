#!/usr/bin/env python3
"""
Bot #67 — Presentation & Pitch Deck Generator
Category: Specialized
Purpose: Generate complete presentation scripts and slide-by-slide content for
         pitch decks, keynotes, sales presentations, and educational slideshows.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

PRESENTATION_TYPES = {
    "investor_pitch": "Startup pitch deck — problem/solution/market/traction/ask",
    "sales_deck": "Customer-facing sales presentation — value prop and ROI",
    "keynote_talk": "Conference keynote or main stage presentation",
    "product_demo": "Product walkthrough and feature demonstration",
    "educational": "Training or workshop presentation for skill-building",
    "webinar_deck": "Webinar slides — value-first + soft pitch at the end",
    "case_study": "Client success story or before/after presentation",
    "board_update": "Quarterly business review for stakeholders or investors",
}

SLIDE_COUNT_GUIDE = {
    "investor_pitch": 12,
    "sales_deck": 15,
    "keynote_talk": 25,
    "product_demo": 10,
    "educational": 20,
    "webinar_deck": 30,
    "case_study": 10,
    "board_update": 15,
}


class PresentationGeneratorBot(BaseBot):

    def __init__(self):
        super().__init__("67_presentation_generator", "specialized")

    def run(self, topic: str = None, presentation_type: str = None,
            audience: str = None, num_slides: int = None,
            key_message: str = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("topic",
            "WheellsVerse: The AI automation platform for entrepreneurs")
        presentation_type = presentation_type or cfg.get("presentation_type", "investor_pitch")
        audience = audience or cfg.get("audience",
            "angel investors and early-stage VCs")
        num_slides = num_slides or cfg.get("num_slides",
            SLIDE_COUNT_GUIDE.get(presentation_type, 15))
        key_message = key_message or cfg.get("key_message",
            "WheellsVerse gives entrepreneurs the power of a 10-person team through AI automation")

        type_desc = PRESENTATION_TYPES.get(presentation_type, presentation_type)
        self.logger.info(f"Generating {presentation_type}: {topic}")

        system = (
            "You are a presentation designer and storytelling coach who has helped founders "
            "raise $50M+, keynote speakers fill 10,000-seat venues, and sales teams close "
            "enterprise deals with their decks. You know that great presentations have one job: "
            "change what the audience believes. You apply the Pyramid Principle for structure, "
            "the Rule of Three for clarity, and emotional storytelling for impact. "
            "You write slides that work without a presenter (the content communicates), "
            "but come alive when someone presents them. Every slide has ONE clear message. "
            "You never put more than 40 words on a slide — if it can't fit, it's not clear enough."
        )

        prompt = f"""Generate a complete presentation for:

TOPIC: {topic}
TYPE: {presentation_type} — {type_desc}
AUDIENCE: {audience}
NUMBER OF SLIDES: {num_slides}
KEY MESSAGE: {key_message}
BRAND: WheellsVerse — AI automation tools for entrepreneurs

---

## PRESENTATION STRATEGY

**Core narrative arc:** [The story this presentation tells — beginning/middle/end]
**The BIG idea (one sentence):** {key_message}
**What the audience should THINK after:** [Belief change]
**What the audience should FEEL after:** [Emotional state]
**What the audience should DO after:** [Specific action]

---

## COMPLETE SLIDE-BY-SLIDE BREAKDOWN

For each slide:

---
### SLIDE [N]: [Slide Name]

**Slide headline (max 8 words):** [The one-sentence message of this slide]

**Visual concept:**
[What the main visual should be — data viz, image, icon, diagram, full-bleed photo]

**Content:**
```
[Exact text that appears on the slide — bullet points, stats, or key statements]
[Keep under 40 words total on the slide]
```

**Speaker notes (what to say aloud):**
[30-60 seconds of spoken content that expands on the slide — the words you say, not just what's on screen]

**Transition to next slide:** [One sentence bridging to the next topic]

---

[Repeat for all {num_slides} slides]

---

## DESIGN BRIEF

**Color palette:** [3-5 colors with hex codes — professional, brand-aligned]
**Typography:** [Headline font + body font recommendation]
**Slide layouts to use:** [Simple, visual-first: no clutter, one idea per slide]
**Visual style:** [Modern/Minimalist/Bold/Corporate/Startup/etc.]
**Tools to build it:** [Canva / Google Slides / Keynote / Figma — with template recommendation]

---

## SPEAKER GUIDE

### Opening (first 60 seconds)
[Exact opening — how to start: story, statistic, or provocative question]

### How to handle questions about [most likely tough topic]:
[Prepared response]

### Closing call to action (last 30 seconds):
[Exact closing words — what to leave them with]

### Presentation timing:
| Section | Slides | Time |
[Breakdown of pacing for {num_slides} slides]

---

## PRESENTATION ASSETS CHECKLIST

- [ ] Title slide with your name/title/date
- [ ] Agenda or roadmap slide
- [ ] Problem/pain slide (visual/emotional)
- [ ] Solution slide (clear mechanism)
- [ ] Proof/evidence slides (data, case studies)
- [ ] Key message summary slide
- [ ] CTA/next steps slide
- [ ] Contact/Q&A slide

## FOLLOW-UP PACKAGE

**Post-presentation email subject line:** [For follow-up after the presentation]
**One-page summary leave-behind:** [Key points in bullet form for a printed handout]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = self.slugify(topic, 25)

        output = f"""# Presentation: {topic}
**Type:** {presentation_type}
**Slides:** {num_slides}
**Audience:** {audience}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Presentation Generator Bot*
"""
        path = self.save_output(output, f"deck_{presentation_type}_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Presentation saved → {path}")
        return {"file": str(path), "topic": topic, "slides": num_slides}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Presentation & Pitch Deck Generator")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--type", type=str, default="investor_pitch",
                        choices=list(PRESENTATION_TYPES.keys()))
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--slides", type=int, default=None)
    parser.add_argument("--message", type=str, default=None)
    args = parser.parse_args()
    bot = PresentationGeneratorBot()
    result = bot.execute(topic=args.topic, presentation_type=args.type,
                         audience=args.audience, num_slides=args.slides,
                         key_message=args.message)
    print(f"\n✅ Presentation: {result['file']}")
