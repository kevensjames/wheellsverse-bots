#!/usr/bin/env python3
"""
Bot #54 — Daily Task Planning Assistant
Category: Assistant
Purpose: Build a structured, prioritized daily task plan using proven productivity
         frameworks (Eisenhower Matrix, time blocking, MIT method) for entrepreneurs.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

WORK_STYLES = {
    "deep_work": "Long uninterrupted blocks — 2-4 hours per session",
    "pomodoro": "25-minute sprints with 5-minute breaks",
    "time_boxing": "Fixed-duration boxes per task — strict cutoffs",
    "flow_based": "Work until natural stopping points, no fixed intervals",
    "batch_work": "Group similar tasks together, switch contexts minimally",
}

FRAMEWORKS = {
    "eisenhower": "Urgent/Important matrix — eliminate, delegate, schedule, or do",
    "eat_frog": "Do the hardest/most important task first",
    "ivy_lee": "Pick 6 tasks, work in strict priority order",
    "time_block": "Assign every hour to a specific task category",
    "mit": "3 Most Important Tasks — everything else is secondary",
}


class TaskAssistantBot(BaseBot):

    def __init__(self):
        super().__init__("54_task_assistant", "assistant")

    def run(self, tasks_today: str = None, priorities: str = None,
            available_hours: str = None, work_style: str = None, **kwargs):

        cfg = self.config
        tasks_today = tasks_today or cfg.get("tasks_today",
            "write 3 blog posts, fix API bug, reply to 20 DMs, review bot outputs, record video")
        priorities = priorities or cfg.get("priorities",
            "content creation is highest, revenue-generating tasks second, admin last")
        available_hours = available_hours or cfg.get("available_hours", "8 hours")
        work_style = work_style or cfg.get("work_style", "time_block")

        style_desc = WORK_STYLES.get(work_style, work_style)
        self.logger.info(f"Planning {available_hours} of tasks: {work_style} style")

        system = (
            "You are a productivity coach and operations strategist who has worked with "
            "high-performing entrepreneurs, CEOs, and creators. You apply science-backed "
            "productivity principles — not hustle culture. You know that energy management "
            "is more important than time management, that decision fatigue is real, and that "
            "most people massively overestimate what they can do in a day. You build plans "
            "that are ambitious but realistic — with buffer time, decision checkpoints, and "
            "explicit protection for deep work. You never suggest 'just work harder.'"
        )

        prompt = f"""Build a complete, optimized daily task plan for:

TASKS TO DO TODAY: {tasks_today}
PRIORITIES: {priorities}
AVAILABLE WORK TIME: {available_hours}
WORK STYLE: {work_style} — {style_desc}
CONTEXT: Entrepreneur running WheellsVerse AI automation business

---

## TASK AUDIT

First, analyze the task list:

**Task inventory:**
[Parse "{tasks_today}" into individual tasks]

**Eisenhower Matrix Sort:**
| Quadrant | Tasks |
| Q1: Urgent + Important (DO NOW) | |
| Q2: Not Urgent + Important (SCHEDULE) | |
| Q3: Urgent + Not Important (DELEGATE/AUTOMATE) | |
| Q4: Not Urgent + Not Important (ELIMINATE) | |

**Energy requirements:** [Which tasks need peak mental energy vs. low energy]

**Estimated time per task:**
| Task | Estimate | Actual (fill in) | Energy Level Needed |
[All tasks from the list]

**Total estimated time:** [Sum]
**Available time:** {available_hours}
**Gap/Surplus:** [Difference + recommendation]

---

## PRIORITIZED TASK LIST

Applying the MIT (Most Important Tasks) method:

**🔥 Top 3 MIT (Must complete today):**
1. [Task] — Why: [Reason] — Est: [X min]
2. [Task] — Why: [Reason] — Est: [X min]
3. [Task] — Why: [Reason] — Est: [X min]

**✅ Should-Do (If time allows):**
4. [Task] — Est: [X min]
5. [Task] — Est: [X min]
[Continue...]

**🚫 Cut or defer today:**
[Tasks not worth doing today + reason]

---

## {work_style.upper().replace("_", " ")} DAILY SCHEDULE

Based on {style_desc}:

| Time Block | Task | Notes |
| [Start time] – [End time] | [Task name] | [Any setup/context notes] |
[Full {available_hours} schedule broken into blocks]

**Buffer time built in:** [How much and where]
**Energy peak used for:** [Which task gets the best mental hours]

---

## EXECUTION PROTOCOL

**Morning startup ritual (5-10 min):**
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Task switching protocol:**
[What to do when moving between tasks — close tabs, 2-minute recap, etc.]

**Decision rule for interruptions:**
[How to handle unexpected tasks, requests, or distractions]

**End-of-day shutdown checklist:**
- [ ] [Incomplete tasks — capture for tomorrow]
- [ ] [Quick wins to celebrate]
- [ ] [Tomorrow's Top 3 set]
- [ ] [Close all work apps/tabs]

---

## AUTOMATION OPPORTUNITIES

Tasks in this list that could be automated with WheellsVerse bots:
| Task | Bot to Use | Time Saved |
[Identify tasks that bots could handle]

## TOMORROW'S PREP

Based on today's task list, tasks likely to carry over:
[Suggested Top 3 for tomorrow + why]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")

        output = f"""# Daily Task Plan
**Date:** {_dt.now().strftime('%Y-%m-%d')}
**Available Hours:** {available_hours}
**Work Style:** {work_style}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Task Assistant Bot*
"""
        path = self.save_output(output, f"taskplan_{ts}.md", ext="md")
        self.logger.info(f"Task plan saved → {path}")
        return {"file": str(path), "hours": available_hours, "style": work_style}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily Task Planning Assistant")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated list of today's tasks")
    parser.add_argument("--priority", type=str, default=None)
    parser.add_argument("--hours", type=str, default="8 hours")
    parser.add_argument("--style", type=str, default="time_block",
                        choices=list(WORK_STYLES.keys()))
    args = parser.parse_args()
    bot = TaskAssistantBot()
    result = bot.execute(tasks_today=args.tasks, priorities=args.priority,
                         available_hours=args.hours, work_style=args.style)
    print(f"\n✅ Task Plan: {result['file']}")
