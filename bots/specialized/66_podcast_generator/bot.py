#!/usr/bin/env python3
"""
Bot #66 — Podcast Episode Generator
Category: Specialized
Purpose: Generate complete podcast episode packages including episode script,
         show notes, title options, timestamps, and promotion materials.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

EPISODE_FORMATS = {
    "solo": "Solo host deep dive — monologue with storytelling",
    "interview": "Guest interview with prepared questions and flow",
    "co_hosted": "Two-host conversation with dynamic back-and-forth",
    "panel": "Multiple guests discussing a topic or case study",
    "case_study": "In-depth walkthrough of a specific example or story",
    "q_and_a": "Audience questions answered by the host",
    "roundup": "Weekly/monthly news roundup or trend analysis",
}

EPISODE_LENGTHS = {
    "short": "15-20 minutes — quick insight or news format",
    "medium": "30-45 minutes — standard episode with story arc",
    "long": "60-90 minutes — deep dive or extended interview",
}


class PodcastGeneratorBot(BaseBot):

    def __init__(self):
        super().__init__("66_podcast_generator", "specialized")

    def run(self, topic: str = None, episode_format: str = None,
            episode_length: str = None, show_name: str = None,
            episode_number: int = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("topic",
            "How AI bots run your business while you sleep")
        episode_format = episode_format or cfg.get("episode_format", "solo")
        episode_length = episode_length or cfg.get("episode_length", "medium")
        show_name = show_name or cfg.get("show_name", "The WheellsVerse Podcast")
        episode_number = episode_number or cfg.get("episode_number", 1)

        fmt_desc = EPISODE_FORMATS.get(episode_format, episode_format)
        length_desc = EPISODE_LENGTHS.get(episode_length, episode_length)

        self.logger.info(f"Generating podcast episode: {topic}")

        system = (
            "You are a podcast producer and content strategist who has helped creators build "
            "podcasts in the top 1% globally. You know that great podcast episodes have a "
            "narrative arc — not just a topic, but a journey. You write for the ear: "
            "conversational sentences, deliberate pacing, and moments that make people stop "
            "and think. You create episodes that are so useful, listeners feel obligated to "
            "share them. You produce the full package — not just the script, but show notes "
            "optimized for SEO, social clips, and email subject lines to promote the episode."
        )

        prompt = f"""Generate a complete podcast episode package for:

TOPIC: {topic}
FORMAT: {episode_format} — {fmt_desc}
LENGTH: {episode_length} — {length_desc}
SHOW NAME: {show_name}
EPISODE NUMBER: {episode_number}
HOST/BRAND: WheellsVerse — AI automation tools for entrepreneurs

---

## EPISODE STRATEGY

**Core thesis:** [The single idea or insight that makes this episode worth listening to]
**Target listener:** [Specific person — what they're struggling with, what they hope to learn]
**Episode promise:** [What the listener will walk away with — specific and tangible]
**Emotional arc:** [Confused/skeptical → curious → engaged → inspired → ready to act]

---

## 5 TITLE OPTIONS

Rank by predicted click/listen rate:
1. **[Best title]** — [Why this works]
2. [Alternative]
3. [Alternative]
4. [Alternative]
5. [Alternative]

**Recommended title:** Option 1 — [Title]
**SEO-optimized title (for directories):** [Include searchable keywords]

---

## FULL EPISODE SCRIPT

> FORMAT:
> [HOST] = Speaking as the host
> [GUEST] = If interview format
> [PAUSE] = Deliberate pause for effect
> [SOUND CUE] = Music/sound note
> [AD BREAK] = Sponsorship position

---

### COLD OPEN (Hook — 30-60 seconds)
[SOUND CUE: intro music fades in]

[HOST] [Write the hook — a story, statement, or question that makes it impossible to stop listening]

[SOUND CUE: intro music]

---

### SHOW INTRO (1-2 minutes)
[HOST] Welcome back to {show_name}...
[Standard intro + episode tease + what listeners will learn]

---

### EPISODE BODY — {episode_length} format

[Write the full episode following the {episode_format} format.
For solo: 5-7 main talking points with stories, examples, and transitions.
For interview: intro of guest, 8-10 questions with suggested answers/talking points.
Include [PAUSE] markers, transition phrases, and engagement hooks throughout.]

**Segment 1: [Title]**
[HOST] [Full spoken content...]

[Transition phrase]

**Segment 2: [Title]**
[HOST] [Full spoken content...]

[Continue for all segments...]

---

### CLOSE + CTA (2-3 minutes)
[HOST] [Summary of key takeaways — 3 bullets]

[Call to action: follow, review, share, join email list, visit WheellsVerse.com]

[Tease next episode]

[SOUND CUE: outro music]

---

## SHOW NOTES (SEO-OPTIMIZED)

**Episode {episode_number}: {topic}**

[2-3 sentence episode summary — include primary keyword naturally]

**What You'll Learn:**
- [Takeaway 1]
- [Takeaway 2]
- [Takeaway 3]

**Resources Mentioned:**
- [Resource 1 with URL]
- [Resource 2 with URL]

**Episode Timestamps:**
| Timestamp | Section |
| 0:00 | [Intro/hook] |
[Continue for all segments]

**Connect with WheellsVerse:**
- Website: [URL]
- Instagram: [Handle]
- Twitter: [Handle]

---

## EPISODE PROMOTION KIT

### Social Captions (ready to post)

**Instagram/Facebook:**
```
[Caption with hook, key insight, and CTA to listen]
```

**Twitter/X:**
```
[Thread version — 3-5 tweets]
```

**LinkedIn:**
```
[Professional framing — what business lesson this episode teaches]
```

### Email Subject Lines (A/B test these)
1. [Subject line 1]
2. [Subject line 2]
3. [Subject line 3]

### Audiogram/Clip Selection
**Best 60-second clip for promotion:**
[Timestamp range + transcript of the clip + why it'll perform]

### Podcast Directory Description
[For Apple Podcasts, Spotify, etc. — 200 words, keyword-rich]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = self.slugify(topic, 25)

        output = f"""# Podcast Episode #{episode_number}: {topic}
**Show:** {show_name}
**Format:** {episode_format}
**Length:** {episode_length}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Podcast Generator Bot*
"""
        path = self.save_output(output, f"podcast_ep{episode_number}_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Podcast episode saved → {path}")
        return {"file": str(path), "topic": topic, "episode": episode_number}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Podcast Episode Generator")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--format", type=str, default="solo",
                        choices=list(EPISODE_FORMATS.keys()))
    parser.add_argument("--length", type=str, default="medium",
                        choices=list(EPISODE_LENGTHS.keys()))
    parser.add_argument("--show", type=str, default="The WheellsVerse Podcast")
    parser.add_argument("--episode", type=int, default=1)
    args = parser.parse_args()
    bot = PodcastGeneratorBot()
    result = bot.execute(topic=args.topic, episode_format=args.format,
                         episode_length=args.length, show_name=args.show,
                         episode_number=args.episode)
    print(f"\n✅ Podcast Episode: {result['file']}")
