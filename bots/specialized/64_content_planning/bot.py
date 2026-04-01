#!/usr/bin/env python3
"""
Bot #64 — 30/60/90-Day Content Strategy Planner
Category: Specialized
Purpose: Build a complete content strategy and calendar spanning 30, 60, or 90 days
         with content themes, platform breakdown, weekly rhythms, and growth goals.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

PLAN_DURATIONS = {
    "30_days":  "Month 1 -- Foundation: establish presence and test content",
    "60_days":  "Months 1-2 -- Build: grow audience and identify what works",
    "90_days":  "Months 1-3 -- Scale: double down on winners, expand reach",
}

CONTENT_GOALS = {
    "grow_audience":   "Maximize follower growth and reach",
    "drive_revenue":   "Convert audience into customers",
    "build_authority": "Establish thought leadership and credibility",
    "launch_product":  "Build anticipation and launch a product/service",
    "grow_email_list": "Convert social followers to email subscribers",
    "mixed":           "Balance of all the above",
}


class ContentPlanningBot(BaseBot):

    def __init__(self):
        super().__init__("64_content_planning", "specialized")

    def run(self, niche: str = None, plan_duration: str = None,
            platforms: str = None, goal: str = None,
            content_themes: str = None, **kwargs):

        cfg = self.config
        niche          = niche or cfg.get("niche", "AI automation and entrepreneurship")
        plan_duration  = plan_duration or cfg.get("plan_duration", "90_days")
        platforms      = platforms or cfg.get("platforms", "twitter,instagram,linkedin,tiktok")
        goal           = goal or cfg.get("goal", "grow_audience")
        content_themes = content_themes or cfg.get("content_themes",
            "AI tools, automation tips, entrepreneur mindset, passive income, behind-the-scenes")

        duration_desc = PLAN_DURATIONS.get(plan_duration, plan_duration)
        goal_desc     = CONTENT_GOALS.get(goal, goal)
        platform_list = [p.strip() for p in platforms.split(",")]
        days          = int(plan_duration.split("_")[0])
        weeks         = days // 7

        self.logger.info(f"Building {plan_duration} content plan for {niche}")

        system = (
            "You are a content strategist and growth consultant who has helped creators go "
            "from 0 to 50K+ followers using systematic, repeatable content plans. "
            "You know that most content strategies fail because they're reactive, not planned. "
            "You build plans around content pillars, weekly rhythms, and clear growth metrics -- "
            "not vague 'post more' advice. You understand the compounding nature of content: "
            "Week 1 builds Week 2, Month 1 feeds Month 2. You plan for learning -- the plan "
            "includes data checkpoints so the creator knows what to adjust and when."
        )

        # Pre-compute conditional phase blocks to avoid backslash in f-string expressions (Python 3.11)
        phase2_block = ""
        if days >= 60:
            phase2_title = PLAN_DURATIONS["60_days"].split("--")[1].strip()
            phase2_block = (
                f"\n### Phase 2: Days 31-60 - {phase2_title}\n"
                "**Focus:** [Build on Phase 1 learnings]\n"
                "**Double down on:** [What Phase 1 data will tell you to scale]\n\n"
                "**Weekly themes:**\n"
                "| Week | Theme | Content Focus | Posting Frequency |\n"
                "| Week 5 | [Theme] | | |\n"
                "| Week 6 | [Theme] | | |\n"
                "| Week 7 | [Theme] | | |\n"
                "| Week 8 | [Theme] | | |\n"
            )

        phase3_block = ""
        if days >= 90:
            phase3_title = PLAN_DURATIONS["90_days"].split("--")[1].strip()
            phase3_block = (
                f"\n### Phase 3: Days 61-90 - {phase3_title}\n"
                "**Focus:** [Scale what works, cut what doesn't]\n"
                "**Key moves:** [What to try in Phase 3 based on 60-day data]\n\n"
                "**Weekly themes:**\n"
                "| Week | Theme | Content Focus | Posting Frequency |\n"
                "| Week 9 | | | |\n"
                "| Week 10 | | | |\n"
                "| Week 11 | | | |\n"
                "| Week 12 | | | |\n"
            )

        platform_quotas = "".join(
            f"**{p.upper()}:**\n"
            "- Posts per week: [X]\n"
            "- Format: [Primary format]\n"
            "- Best content for this platform: [Pillar + type that performs best here]\n"
            f"- Growth tactic: [One specific growth lever for {p} in {niche}]\n\n"
            for p in platform_list
        )

        day60_review = ""
        if days >= 60:
            day60_review = (
                "\n**At Day 60 - Mid-Point Review:**\n"
                "- [ ] Total audience growth: [Target]\n"
                "- [ ] Revenue attributed to content: [Target]\n"
                "- [ ] Top 3 posts to repurpose or expand\n"
                "- [ ] Decision: [What to double down on in Phase 3]\n"
            )

        phase1_title = PLAN_DURATIONS["30_days"].split("--")[1].strip()

        prompt = f"""Build a complete {days}-day content strategy plan for:

NICHE: {niche}
DURATION: {plan_duration} -- {duration_desc}
PLATFORMS: {', '.join(platform_list)}
PRIMARY GOAL: {goal} -- {goal_desc}
CONTENT THEMES: {content_themes}
BRAND: WheellsVerse -- AI automation tools for entrepreneurs

---

## CONTENT STRATEGY FOUNDATION

### Content Pillars
5 recurring content pillars for {niche}:
| Pillar | Description | % of Content | Example Topics |
| 1. [Pillar] | | 25% | [3 example ideas] |
| 2. [Pillar] | | 25% | [3 example ideas] |
| 3. [Pillar] | | 20% | [3 example ideas] |
| 4. [Pillar] | | 20% | [3 example ideas] |
| 5. [Pillar] | | 10% | [3 example ideas] |

### Content Mix
| Type | % | Platforms | Purpose |
| Educational | 40% | All | Build authority and following |
| Entertaining | 25% | TikTok/Instagram | Discovery and virality |
| Inspirational | 20% | All | Emotional connection |
| Promotional | 15% | All | Revenue and conversions |

---

## PHASE BREAKDOWN

### Phase 1: Days 1-30 - {phase1_title}
**Focus:** [What to achieve in the first 30 days]
**Primary content type:** [What format to focus on to build momentum]
**Success metric:** [Specific number to hit by Day 30]

**Weekly themes:**
| Week | Theme | Content Focus | Posting Frequency |
| Week 1 | [Theme] | [What to create] | [Posts per platform] |
| Week 2 | [Theme] | | |
| Week 3 | [Theme] | | |
| Week 4 | [Theme] | | |
{phase2_block}
{phase3_block}

---

## WEEKLY CONTENT RHYTHM

Standard week template for all {weeks} weeks:

| Day | Platform(s) | Content Type | Pillar | Notes |
| Monday | [Platform] | [Type] | [Pillar] | [Why Monday for this type] |
| Tuesday | [Platform] | [Type] | [Pillar] | |
| Wednesday | [Platform] | [Type] | [Pillar] | |
| Thursday | [Platform] | [Type] | [Pillar] | |
| Friday | [Platform] | [Type] | [Pillar] | |
| Saturday | [Platform] | [Type] | [Pillar] | |
| Sunday | Rest or repurpose | | | |

**Total pieces per week:** [Count by platform]

---

## PLATFORM-SPECIFIC QUOTAS

{platform_quotas}

---

## CONTENT BATCH CALENDAR

Recommended batching session (once per week -- 3-4 hours):

| Session | Time | What to Create |
| Research | 30 min | Find trending topics, gather references |
| Writing | 90 min | Draft captions, scripts, threads |
| Media | 60 min | Create or select visuals, record short videos |
| Schedule | 30 min | Queue everything in scheduling tool |

**Scheduling tool recommendation:** [Best tool for {platforms} combo]

---

## GROWTH CHECKPOINTS

**At Day 7 -- First Data Check:**
- [ ] Which post got the most engagement? Replicate the format
- [ ] Follower growth: [Target]
- [ ] Top performing content type: [Note for next week]

**At Day 30 -- Phase 1 Review:**
- [ ] Follower growth rate: [Target %]
- [ ] Best performing pillar: [Note]
- [ ] Email/lead captures: [Target]
- [ ] Decision: [What to do more of / less of in Phase 2]
{day60_review}

---

## 30 CONTENT IDEAS TO KICKSTART THE PLAN

High-potential ideas for {niche} -- ready to execute:
| # | Platform | Format | Hook | Pillar |
[30 rows -- specific, immediately usable ideas]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_niche = "".join(c if c.isalnum() else "_" for c in niche[:20])

        output = f"""# {days}-Day Content Plan: {niche}
**Platforms:** {platforms}
**Goal:** {goal}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Content Planning Bot*
"""
        path = self.save_output(output, f"contentplan_{plan_duration}_{safe_niche}_{ts}.md", ext="md")
        self.logger.info(f"Content plan saved -> {path}")
        return {"file": str(path), "niche": niche, "duration": plan_duration, "platforms": platform_list}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="30/60/90-Day Content Strategy Planner")
    parser.add_argument("--niche",     type=str, default=None)
    parser.add_argument("--duration",  type=str, default="90_days",
                        choices=list(PLAN_DURATIONS.keys()))
    parser.add_argument("--platforms", type=str, default="twitter,instagram,linkedin,tiktok")
    parser.add_argument("--goal",      type=str, default="grow_audience",
                        choices=list(CONTENT_GOALS.keys()))
    parser.add_argument("--themes",    type=str, default=None)
    args = parser.parse_args()
    bot = ContentPlanningBot()
    result = bot.execute(niche=args.niche, plan_duration=args.duration,
                         platforms=args.platforms, goal=args.goal,
                         content_themes=args.themes)
    print(f"\n✅ Content Plan: {result['file']}")
