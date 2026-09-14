#!/usr/bin/env python3
"""
Bot #40 — DM Automation Sequence Builder
Category: Social Media
Purpose: Build complete DM automation sequences for new followers, lead nurturing,
         collaboration outreach, and sales conversations on social platforms.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

SEQUENCE_TYPES = {
    "new_follower_welcome": "Welcome new followers and introduce your brand value",
    "lead_magnet_delivery": "Deliver a free resource and begin nurturing toward offer",
    "sales_conversation": "Warm up cold leads and open a sales dialogue",
    "collaboration_outreach": "Reach out to potential partners or co-creators",
    "re_engagement": "Re-engage followers who haven't interacted recently",
    "event_invitation": "Invite followers to a webinar, launch, or event",
    "feedback_request": "Collect testimonials or product feedback via DM",
}


class DMAutomationBot(BaseBot):

    def __init__(self):
        super().__init__("40_dm_automation", "social_media")

    def run(self, sequence_type: str = None, platform: str = None,
            goal: str = None, num_messages: int = None, **kwargs):

        cfg = self.config
        sequence_type = sequence_type or cfg.get("sequence_type", "new_follower_welcome")
        platform = platform or cfg.get("platform", "instagram")
        goal = goal or cfg.get("goal", "convert followers into email subscribers")
        num_messages = num_messages or cfg.get("num_messages", 4)

        seq_desc = SEQUENCE_TYPES.get(sequence_type, sequence_type)
        self.logger.info(f"Building DM sequence: {sequence_type} on {platform}")

        system = (
            "You are a DM automation strategist who has built high-converting direct message "
            "sequences for 7-figure creators and coaches. You know the psychology of the DM inbox — "
            "it's personal space, and people are extremely sensitive to feeling sold to. "
            "Your sequences feel like hearing from a thoughtful friend, not a bot. "
            "You build trust before you ask for anything. Every message has ONE clear purpose, "
            "ends with a soft CTA or question, and leaves the person wanting to reply. "
            "You never write walls of text in DMs — short, punchy, conversational."
        )

        prompt = f"""Build a complete DM automation sequence for:

SEQUENCE TYPE: {sequence_type} — {seq_desc}
PLATFORM: {platform}
GOAL: {goal}
NUMBER OF MESSAGES: {num_messages}
BRAND: WheellsVerse — AI automation tools for entrepreneurs

## SEQUENCE STRATEGY

**Trigger event:** [What action fires Message 1]
**Sequence goal:** {goal}
**Success metric:** [How to measure if this sequence is working]
**Tone arc:** [How the tone evolves across {num_messages} messages]

## THE {num_messages}-MESSAGE SEQUENCE

For each message:

---
### MESSAGE [N] — [Name/Purpose]
**Send timing:** [When relative to trigger or previous message]
**Goal of this message:** [Single objective]
**Subject/opener:** [First line — must grab attention]

**Full message:**
```
[Complete DM text — conversational, {platform}-appropriate length]
```

**CTA:** [Exactly what you want them to do/say]
**If they reply with YES:** [What message to send next]
**If no reply after [X] days:** [Move to next message or exit sequence]

---
[Repeat for all {num_messages} messages]

## REPLY HANDLING SCRIPTS

**If they say "not interested":**
```
[Graceful exit message that leaves door open]
```

**If they ask "what is this?":**
```
[Quick, honest explanation without sounding salesy]
```

**If they engage positively:**
```
[Message to move conversation forward toward {goal}]
```

**If they ghost mid-sequence:**
```
[One final re-engagement attempt]
```

## PLATFORM BEST PRACTICES: {platform.upper()}

- **Character limits:** [DM length limits]
- **Formatting rules:** [What works/doesn't in {platform} DMs]
- **Sending timing:** [Best times to send for open rates]
- **Automation tools:** [Top 3 tools for automating {platform} DMs]
- **Terms of Service notes:** [What's allowed vs. what gets accounts flagged]

## PERSONALIZATION VARIABLES

Variables to insert for higher response rates:
| Variable | Where to use | Example |
| {{first_name}} | | |
| {{their_niche}} | | |
| {{recent_post_topic}} | | |
[Add 2-3 more relevant variables]

## SEQUENCE PERFORMANCE BENCHMARKS

| Metric | Poor | Average | Great |
| Open rate | | | |
| Reply rate | | | |
| CTA completion | | | |
| Unsubscribe/block rate | | | |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_type = self.slugify(sequence_type, 25)

        output = f"""# DM Automation Sequence: {sequence_type}
**Platform:** {platform}
**Goal:** {goal}
**Messages:** {num_messages}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse DM Automation Bot*
"""
        path = self.save_output(output, f"dm_sequence_{safe_type}_{ts}.md", ext="md")
        self.logger.info(f"DM sequence saved → {path}")
        return {"file": str(path), "sequence_type": sequence_type, "platform": platform}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DM Automation Sequence Builder")
    parser.add_argument("--type", type=str, default=None,
                        choices=list(SEQUENCE_TYPES.keys()),
                        help=f"Sequence type: {', '.join(SEQUENCE_TYPES.keys())}")
    parser.add_argument("--platform", type=str, default="instagram")
    parser.add_argument("--goal", type=str, default=None)
    parser.add_argument("--messages", type=int, default=4)
    args = parser.parse_args()
    bot = DMAutomationBot()
    result = bot.execute(sequence_type=args.type, platform=args.platform,
                         goal=args.goal, num_messages=args.messages)
    print(f"\n✅ DM Sequence: {result['file']}")
