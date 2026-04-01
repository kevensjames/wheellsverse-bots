#!/usr/bin/env python3
"""
Bot #59 — Daily Schedule Optimizer
Category: Time Management
Purpose: Design an optimized daily/weekly schedule aligned with energy levels,
         priorities, and business goals using time-blocking and chronobiology.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

CHRONOTYPES = {
    "early_bird":  "Peak energy 6AM-12PM — morning is sacred for deep work",
    "night_owl":   "Peak energy 8PM-2AM — mornings are low energy, evenings are peak",
    "midday":      "Peak energy 10AM-2PM — ramp up slowly, peak at noon",
    "bimodal":     "Two peak periods — morning and evening, midday dip",
}

SCHEDULE_TYPES = {
    "entrepreneur": "Build/create/market — creative work + admin + business growth",
    "content":      "Content creator — batch creation, filming, editing, posting",
    "hybrid_work":  "Mix of deep focus work and meetings/calls",
    "side_hustle":  "Primary job + side business in limited hours",
    "launch_mode":  "Pre-launch sprint — compressed deadlines, high output required",
}


class ScheduleOptimizerBot(BaseBot):

    def __init__(self):
        super().__init__("59_schedule_optimizer", "time_management")

    def run(self, available_hours: str = None, top_priorities: str = None,
            chronotype: str = None, schedule_type: str = None,
            constraints: str = None, **kwargs):

        cfg = self.config
        available_hours = available_hours or cfg.get("available_hours", "8 hours, 9AM-5PM")
        top_priorities  = top_priorities or cfg.get("top_priorities",
            "1) content creation and bot development, 2) sales and marketing, 3) customer support")
        chronotype      = chronotype or cfg.get("chronotype", "early_bird")
        schedule_type   = schedule_type or cfg.get("schedule_type", "entrepreneur")
        constraints     = constraints or cfg.get("constraints",
            "1 hour for meals/breaks, no meetings before 10AM, gym 3x per week")

        chrono_desc = CHRONOTYPES.get(chronotype, chronotype)
        sched_desc  = SCHEDULE_TYPES.get(schedule_type, schedule_type)

        self.logger.info(f"Optimizing {schedule_type} schedule for {chronotype} chronotype")

        system = (
            "You are a performance coach and schedule designer who blends chronobiology, "
            "behavioral science, and productivity research to build schedules that maximize "
            "output without burning out. You know that most people schedule backwards — "
            "they fill their day with reactive tasks and never protect time for the work "
            "that actually moves the needle. You design schedules around energy peaks, not "
            "arbitrary calendar slots. You protect deep work like a high-value asset. "
            "You build recovery into the system — because rest is productivity infrastructure."
        )

        prompt = f"""Design an optimized daily schedule for:

AVAILABLE TIME: {available_hours}
TOP PRIORITIES: {top_priorities}
CHRONOTYPE: {chronotype} — {chrono_desc}
SCHEDULE TYPE: {schedule_type} — {sched_desc}
CONSTRAINTS: {constraints}
CONTEXT: WheellsVerse entrepreneur — AI bots, content creation, business building

---

## SCHEDULE SCIENCE

### Your Chronotype Breakdown
**Chronotype: {chronotype}**
- Peak mental energy: [Specific hours based on chronotype]
- Secondary energy peak: [If applicable]
- Natural energy dip: [When to avoid deep work]
- Best tasks for each window: [Match task type to energy level]

### Task-Energy Matching
| Energy Level | Best Task Types | Avoid |
| Peak (cognitive) | Deep work, creative, complex problems | Meetings, email, admin |
| Medium | Calls, strategy, writing | Creative breakthroughs |
| Low | Admin, email, routine tasks | Complex decisions |

---

## YOUR OPTIMIZED DAILY SCHEDULE

Based on {available_hours} and {chronotype} chronotype:

```
MORNING BLOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Time] – [Time] | [Activity]
[Notes: why this time for this activity]

[Time] – [Time] | [Activity]
[Notes]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MIDDAY BLOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Time] – [Time] | [Activity]
[Notes]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AFTERNOON BLOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Time] – [Time] | [Activity]
[Notes]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EVENING BLOCK (if applicable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Time] – [Time] | [Activity]
[Notes]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Schedule Logic:**
- Deep work protected at: [Times] because: [Chronotype reason]
- Priority 1 ({top_priorities.split(',')[0].strip()}) gets: [Which blocks]
- Recovery/buffer built into: [Where and why]

---

## WEEKLY SCHEDULE TEMPLATE

| | Monday | Tuesday | Wednesday | Thursday | Friday |
| Morning | | | | | |
| Midday | | | | | |
| Afternoon | | | | | |
| Evening | | | | | |

**Theme days (optional):**
- [Day]: [Theme — e.g., "Creation Monday: only build/create work"]
- [Day]: [Theme — e.g., "Meeting Tuesday: batch all calls"]
[Continue for relevant days]

---

## PROTECTING YOUR PEAK HOURS

**Your #1 enemy:** [The most common way this schedule gets derailed]
**Defense strategy:** [How to protect deep work blocks]

**"Hell yes or no" rule:**
Before accepting anything that takes time: [Decision framework for your situation]

**Batching strategy:**
| Task Type | Batch Window | Why Batch |
| Email | [Time] | [Reason] |
| DMs/social | [Time] | |
| Calls/meetings | [Time] | |
[Continue for relevant tasks]

---

## STARTUP & SHUTDOWN RITUALS

### Morning Startup (10-15 min)
1. [Step 1 — what to do first to enter work mode]
2. [Step 2]
3. [Step 3]
4. [Step 4 — set intention for the day]

### End-of-Day Shutdown (10 min)
1. [Step 1 — capture open loops]
2. [Step 2 — set tomorrow's Top 3]
3. [Step 3 — close work context completely]

---

## 2-WEEK IMPLEMENTATION PLAN

**Week 1 — Test:** Run this schedule, note what breaks, don't adjust yet
**Week 2 — Optimize:** Make targeted adjustments based on Week 1 data

**Track daily:**
- [ ] Deep work hours logged: [Target X hours]
- [ ] Top 3 priorities completed: [Y/N]
- [ ] Schedule derailments: [Count + cause]
- [ ] Energy levels: [Rate 1-5 at noon and 5PM]

**After 2 weeks, reassess:** [What data to review and how to iterate]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")

        output = f"""# Optimized Schedule: {schedule_type}
**Chronotype:** {chronotype}
**Available Hours:** {available_hours}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Schedule Optimizer Bot*
"""
        path = self.save_output(output, f"schedule_{schedule_type}_{ts}.md", ext="md")
        self.logger.info(f"Optimized schedule saved → {path}")
        return {"file": str(path), "schedule_type": schedule_type, "chronotype": chronotype}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily Schedule Optimizer")
    parser.add_argument("--hours",       type=str, default="8 hours, 9AM-5PM")
    parser.add_argument("--priorities",  type=str, default=None)
    parser.add_argument("--chronotype",  type=str, default="early_bird",
                        choices=list(CHRONOTYPES.keys()))
    parser.add_argument("--type",        type=str, default="entrepreneur",
                        choices=list(SCHEDULE_TYPES.keys()))
    parser.add_argument("--constraints", type=str, default=None)
    args = parser.parse_args()
    bot = ScheduleOptimizerBot()
    result = bot.execute(available_hours=args.hours, top_priorities=args.priorities,
                         chronotype=args.chronotype, schedule_type=args.type,
                         constraints=args.constraints)
    print(f"\n✅ Optimized Schedule: {result['file']}")
