#!/usr/bin/env python3
"""
Bot #60 — Deep Work Focus Session Planner
Category: Time Management
Purpose: Design structured deep work / focus sessions with pre-session setup,
         distraction management, Pomodoro variants, and post-session review.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

SESSION_TYPES = {
    "pomodoro": "Classic 25/5 or 50/10 sprint intervals",
    "deep_work": "Single long block (2-4 hours) of uninterrupted focus",
    "creative": "Open-ended creative exploration — no timer pressure",
    "sprint": "Compressed high-output session — max 90 minutes",
    "flow_state": "Extended session designed to enter and maintain flow",
    "batch_tasks": "Group similar tasks into a timed batch window",
    "review": "Analysis, reflection, and planning session",
}

DISTRACTION_PROFILES = {
    "social_media": "Phone + social platforms are the primary distraction",
    "email": "Email and messaging apps break focus",
    "noise": "Environmental noise is the main issue",
    "multitasking": "Tendency to switch tasks mid-session",
    "perfectionism": "Getting stuck perfecting instead of progressing",
}

ENERGY_LEVELS = {
    "peak": "High energy — schedule hardest, most creative work",
    "medium": "Moderate energy — good for structured analytical work",
    "low": "Low energy — batch light tasks, avoid major decisions",
    "varied": "Unknown — include energy ramp-up strategy",
}


class FocusSessionBot(BaseBot):

    def __init__(self):
        super().__init__("60_focus_session", "time_management")

    def run(self, task: str = None, session_type: str = None,
            duration: str = None, energy_level: str = None,
            distractions: str = None, **kwargs):

        cfg = self.config
        task = task or cfg.get("task", "build new WheellsVerse bot — research + code + test")
        session_type = session_type or cfg.get("session_type", "deep_work")
        duration = duration or cfg.get("duration", "2 hours")
        energy_level = energy_level or cfg.get("energy_level", "peak")
        distractions = distractions or cfg.get("distractions", "social_media")

        type_desc = SESSION_TYPES.get(session_type, session_type)
        energy_desc = ENERGY_LEVELS.get(energy_level, energy_level)
        distract_desc = DISTRACTION_PROFILES.get(distractions, distractions)

        self.logger.info(f"Planning {duration} {session_type} focus session: {task}")

        system = (
            "You are a deep work coach and performance scientist who helps entrepreneurs and "
            "creators achieve peak cognitive performance. You've studied Cal Newport, Andrew "
            "Huberman, and the neuroscience of focus. You know that the brain takes 23 minutes "
            "to fully re-engage after an interruption — so your sessions eliminate distractions "
            "before they happen. You design sessions that match the task to the cognitive mode "
            "required (convergent vs. divergent thinking), prime the brain properly, and build "
            "in strategic recovery. You treat focus as a skill that improves with deliberate practice."
        )

        prompt = f"""Design a complete focus session plan for:

TASK: {task}
SESSION TYPE: {session_type} — {type_desc}
DURATION: {duration}
ENERGY LEVEL: {energy_level} — {energy_desc}
PRIMARY DISTRACTION: {distractions} — {distract_desc}
CONTEXT: WheellsVerse entrepreneur — building AI automation systems

---

## SESSION BRIEF

**Cognitive mode required:** [Convergent (analysis/code/structured) or Divergent (creative/strategy/ideas)]
**Task complexity:** [High/Medium/Low — determines sprint length]
**Risk of getting stuck:** [What could block progress — pre-solve this]
**Definition of done for this session:** [What does success look like specifically?]

---

## PRE-SESSION SETUP (10-15 minutes before)

### Environment Setup
**Physical space:**
- [ ] [Setup item 1]
- [ ] [Setup item 2 — surface cleared, tools ready]
- [ ] [Phone position]

**Digital environment:**
- [ ] Close: [Specific apps to close]
- [ ] Open: [Only what's needed for: {task}]
- [ ] Turn off: [Notifications, Slack, email, etc.]
- [ ] Browser tabs: [Maximum X tabs rule]

### Distraction Blocking ({distractions})
**For {distract_desc}:**
- Tool to use: [App blocker recommendation — Freedom, Cold Turkey, etc.]
- Block list: [Specific sites/apps to block]
- Emergency exception: [How to handle a genuine emergency without breaking flow]

### Mental Setup (5 minutes)
1. **Write your session intention:** "In this {duration} session I will complete: ___"
2. **Clear open loops:** [Capture any other thoughts on paper — brain dump]
3. **Prime task:** [30-second preview of what you're about to work on]
4. **Energy optimization:** [Based on {energy_level}: coffee/walk/breathwork/etc.]

---

## {session_type.upper().replace("_", " ")} SESSION STRUCTURE

{"### Pomodoro Schedule" if session_type == "pomodoro" else f"### {duration} Deep Work Block"}

```
[Write the detailed time structure for {duration} using {type_desc} approach]

Example structure:
├── [Time] START — [Brief ritual to enter focus]
├── [Time block] — [Work phase with specific milestone]
├── [Time] BREAK — [What to do during break — movement, water, no screens]
├── [Time block] — [Work phase continued]
├── [Time] END — [Shutdown ritual]
```

**Interval rationale:** [Why these specific timing choices for {task}]

**Progress checkpoints:**
- At [25% through]: [What should be done — mini milestone]
- At [50% through]: [What should be done]
- At [75% through]: [What should be done]
- At [100% — end]: [Complete definition of done]

---

## IN-SESSION PROTOCOLS

**If you get stuck (brain locks up):**
1. [Protocol 1 — step back and re-read the last thing you completed]
2. [Protocol 2 — change the question: "what's the smallest next step?"]
3. [Protocol 3 — set a 5-minute timer and just write/code anything]

**If a distraction thought appears:**
→ Capture it on paper → return immediately → do NOT act on it during session

**If energy drops mid-session:**
→ [Protocol for energy dip based on {energy_level}]

**If you're in flow and the timer ends:**
→ [Decision rule — continue vs. stop]

---

## POST-SESSION REVIEW (10 minutes)

Fill in after the session:
- Session started: [Time] / Ended: [Time] / Actual: ___
- Flow achieved: [Yes/No/Partial]
- Definition of done met: [Yes/No/Partial — what's left]
- Distractions that broke focus: [Count and type]
- Energy level end vs. start: [Rating]

**What went well:**
[Space to fill in]

**What to do differently next session:**
[Space to fill in]

**Capture incomplete items:**
[Open loops to close in next session]

---

## FOCUS PERFORMANCE TRACKING

Weekly focus metrics to improve your sessions:
| Metric | This Week | Target | Trend |
| Total deep work hours | | 4+ hours/day | |
| Average session length | | {duration} | |
| Flow sessions (unbroken) | | 3+ per week | |
| Distraction events per session | | <2 | |

**Monthly review question:**
[Am I making progress on the right things? What should I stop spending focus time on?]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_task = self.slugify(task, 25)

        output = f"""# Focus Session Plan: {task[:60]}
**Type:** {session_type}
**Duration:** {duration}
**Energy Level:** {energy_level}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Focus Session Bot*
"""
        path = self.save_output(output, f"focus_{session_type}_{safe_task}_{ts}.md", ext="md")
        self.logger.info(f"Focus session plan saved → {path}")
        return {"file": str(path), "task": task, "session_type": session_type, "duration": duration}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deep Work Focus Session Planner")
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("--type", type=str, default="deep_work",
                        choices=list(SESSION_TYPES.keys()))
    parser.add_argument("--duration", type=str, default="2 hours")
    parser.add_argument("--energy", type=str, default="peak",
                        choices=list(ENERGY_LEVELS.keys()))
    parser.add_argument("--distraction", type=str, default="social_media",
                        choices=list(DISTRACTION_PROFILES.keys()))
    args = parser.parse_args()
    bot = FocusSessionBot()
    result = bot.execute(task=args.task, session_type=args.type,
                         duration=args.duration, energy_level=args.energy,
                         distractions=args.distraction)
    print(f"\n✅ Focus Session Plan: {result['file']}")
