#!/usr/bin/env python3
"""
Bot #55 — Smart Reminder System Builder
Category: Assistant
Purpose: Build a complete reminder and follow-up system for projects, deadlines,
         recurring tasks, and important milestones with customizable cadences.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

REMINDER_TYPES = {
    "project_deadline": "Countdown reminders leading up to a project deadline",
    "recurring_tasks": "Regular recurring task reminders (daily/weekly/monthly)",
    "follow_up_sequence": "Follow-up reminders for sales, partnerships, or commitments",
    "habit_tracker": "Daily habit and routine reminder system",
    "content_calendar": "Content creation and publishing deadline reminders",
    "financial": "Bill payments, invoices, tax deadlines, subscriptions",
    "review_checkpoint": "Periodic review reminders (weekly review, quarterly planning)",
}

CADENCE_OPTIONS = {
    "daily": "Every day at the same time",
    "weekly": "Once per week on a specified day",
    "biweekly": "Every 2 weeks",
    "monthly": "Once per month on a specified date",
    "custom": "Custom schedule based on milestones or days before deadline",
}


class ReminderBot(BaseBot):

    def __init__(self):
        super().__init__("55_reminder_bot", "assistant")

    def run(self, project: str = None, deadline: str = None,
            reminder_type: str = None, cadence: str = None,
            milestone_count: int = None, **kwargs):

        cfg = self.config
        project = project or cfg.get("project",
            "WheellsVerse product launch — 78 AI bots ready for customers")
        deadline = deadline or cfg.get("deadline", "30 days from today")
        reminder_type = reminder_type or cfg.get("reminder_type", "project_deadline")
        cadence = cadence or cfg.get("cadence", "custom")
        milestone_count = milestone_count or cfg.get("milestone_count", 5)

        type_desc = REMINDER_TYPES.get(reminder_type, reminder_type)
        cadence_desc = CADENCE_OPTIONS.get(cadence, cadence)

        self.logger.info(f"Building reminder system for: {project}")

        system = (
            "You are a systems thinker and productivity coach who designs reminder systems "
            "that people actually use. You know that most reminder systems fail because they "
            "create too many notifications, making people tune them out. You design smart "
            "reminder systems with the right frequency — not too many (ignored), not too few "
            "(missed). You build context into reminders (not just 'do X' but 'do X because Y '). "
            "You understand that the best reminder systems are automated, low-friction, and "
            "contain just enough information to take action immediately."
        )

        prompt = f"""Build a complete, smart reminder system for:

PROJECT/GOAL: {project}
DEADLINE: {deadline}
REMINDER TYPE: {reminder_type} — {type_desc}
CADENCE: {cadence} — {cadence_desc}
MILESTONES: {milestone_count}
CONTEXT: WheellsVerse entrepreneur managing multiple automation projects

---

## REMINDER SYSTEM DESIGN

### System Overview
- **What this system tracks:** [Specific things to be reminded about]
- **Why these reminders matter:** [What goes wrong without them]
- **Success criteria:** [How you'll know the system is working]
- **Total reminders per week:** [Number to prevent notification fatigue]

---

## MILESTONE BREAKDOWN

Break "{project}" into {milestone_count} checkpoints:

| # | Milestone | Target Date | Why This Matters | Risk if Missed |
[{milestone_count} rows — specific, measurable milestones]

---

## REMINDER SCHEDULE

### Pre-Deadline Countdown Reminders

| When | Message | Action Required | Priority |
| {deadline} minus 30 days | | | |
| {deadline} minus 14 days | | | |
| {deadline} minus 7 days | | | |
| {deadline} minus 3 days | | | |
| {deadline} minus 1 day | | | |
| Day of deadline | | | |

### Milestone-Specific Reminders

For each milestone, provide:
**Milestone [N]: [Name]**
- Reminder 1 (3 days before): [Exact message]
- Reminder 2 (day of): [Exact message]
- Completion check: [What to verify when done]

---

## REMINDER MESSAGE TEMPLATES

**Effective reminder format:**
> **[TASK NAME]** — [One-sentence context]
> Due: [Date/Time]
> Next action: [Exactly what to do right now]
> If blocked: [Who to contact or what to check]

**5 pre-written reminder messages for this project:**
1. [Message — early phase]
2. [Message — mid-project check-in]
3. [Message — deadline approaching]
4. [Message — day before]
5. [Message — completion verification]

---

## AUTOMATION SETUP

### Tool Recommendations
| Tool | Platform | Best For | Setup Time |
| Notion | All platforms | Project + task reminders | 30 min |
| Google Calendar | Desktop/Mobile | Time-based reminders | 10 min |
| Zapier/Make | Web automations | Automated sequence triggers | 1 hour |
| Slack | Team environments | Channel reminders | 15 min |
| [Best for {reminder_type}] | | | |

### Step-by-Step Setup (Recommended Tool)
1. [Step 1]
2. [Step 2]
3. [Step 3]
[5-7 steps to set this system up]

---

## RECURRING REMINDER SYSTEM

For tasks that repeat after this project:

**Weekly non-negotiables:**
- [Recurring task] — every [Day] at [Time]
- [Recurring task] — every [Day] at [Time]
[5 weekly items]

**Monthly must-dos:**
- [Recurring task] — [Day of month]
[3-5 monthly items]

## REMINDER FATIGUE PREVENTION

Rules for this system to stay useful:
1. [Rule — max X reminders per day]
2. [Rule — batch similar reminders]
3. [Rule — when to silence vs. when to escalate]
4. [Rule — quarterly system audit]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_project = self.slugify(project, 25)

        output = f"""# Reminder System: {project}
**Deadline:** {deadline}
**Type:** {reminder_type}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Reminder Bot*
"""
        path = self.save_output(output, f"reminders_{safe_project}_{ts}.md", ext="md")
        self.logger.info(f"Reminder system saved → {path}")
        return {"file": str(path), "project": project, "deadline": deadline}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Smart Reminder System Builder")
    parser.add_argument("--project", type=str, default=None)
    parser.add_argument("--deadline", type=str, default="30 days from today")
    parser.add_argument("--type", type=str, default="project_deadline",
                        choices=list(REMINDER_TYPES.keys()))
    parser.add_argument("--cadence", type=str, default="custom",
                        choices=list(CADENCE_OPTIONS.keys()))
    parser.add_argument("--milestones", type=int, default=5)
    args = parser.parse_args()
    bot = ReminderBot()
    result = bot.execute(project=args.project, deadline=args.deadline,
                         reminder_type=args.type, cadence=args.cadence,
                         milestone_count=args.milestones)
    print(f"\n✅ Reminder System: {result['file']}")
