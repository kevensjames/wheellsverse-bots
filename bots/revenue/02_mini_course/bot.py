#!/usr/bin/env python3
"""
Revenue Stream #2 — Mini-Course: Make Your First $500 With AI
Purpose: Full 5-module video course. Sold at $97.
         Bot generates all course content, scripts, workbooks, and promotes daily.
         Sells via Gumroad/Stripe. Target: 20 sales/month = $1,940.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an elite online course creator who has built 7-figure course businesses.
You know that the best courses deliver ONE clear transformation with a step-by-step path.
You write course content that is practical, engaging, and produces real results.
Your scripts feel like a trusted mentor walking you through exactly what to do.
You design for action: every module ends with a homework assignment that moves the
student closer to their first $500. Your content is for absolute beginners —
assume they know nothing about AI but want to make money."""

MODULES = [
    ("Module 1: Your AI Money Foundation",
     "AI tools overview, picking your niche, setting up your workspace, the $500 roadmap"),
    ("Module 2: Building Your AI Income Machine",
     "The 5 fastest AI income methods, choosing your first stream, your first offer"),
    ("Module 3: Creating Products in Hours, Not Weeks",
     "AI-assisted product creation, digital products, prompts, templates, mini-courses"),
    ("Module 4: Selling Without a Big Audience",
     "Free traffic sources, Gumroad setup, social selling, WhatsApp marketing"),
    ("Module 5: Scaling to $500 and Beyond",
     "Automating your income, affiliate marketing, stacking revenue streams, your 90-day plan"),
]


class MiniCourseBot(BaseBot):

    def __init__(self):
        super().__init__("02_mini_course", "revenue")
        import os
        self.course_url = os.getenv("GUMROAD_COURSE_URL", "https://gum.co/wheellsverse-course")
        self.price = "$97"

    def run(self, action: str = "build", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "build")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "build": self._build_module,
            "script": self._video_script,
            "workbook": self._workbook,
            "promote": self._promote,
            "full": self._build_full_course,
            "listing": self._course_listing,
        }
        fn = actions.get(action, self._build_module)
        return fn(ts, **kwargs)

    def _build_module(self, ts: str, **kwargs) -> dict:
        module_idx = kwargs.get("module_idx", 0)
        module_name, module_topics = MODULES[module_idx % len(MODULES)]

        prompt = f"""Write the complete course module content for:
{module_name}

Topics covered: {module_topics}

Module structure:
## {module_name}

### Learning Objectives (3-4 bullet points — what they can do after this module)

### Lesson 1: [Title] (800-1000 words)
- Concept explanation with analogy
- Real example from WheellsVerse brand
- Step-by-step action section
- Common mistake to avoid

### Lesson 2: [Title] (800-1000 words)
[same structure]

### Lesson 3: [Title] (800-1000 words)
[same structure]

### Module Action Assignment
- Homework task (specific, completable in under 2 hours)
- Success criteria (how they know they did it right)
- Expected result (what they should have after completing)

### Quick Win
- One thing they can do RIGHT NOW (under 30 minutes) to see progress

Total word count target: 3,000-3,500 words
Tone: Friendly coach. Clear, simple, energizing."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=5000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "mini_course"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = module_name.lower().replace(" ", "_").replace(":", "").replace("$", "")
        fname = f"{safe_name}.md"
        (out_dir / fname).write_text(result, encoding="utf-8")
        path = self.save_output(result, f"module_{module_idx}_{ts}.md", ext="md")
        return {"file": str(path), "action": "build", "module": module_name}

    def _video_script(self, ts: str, **kwargs) -> dict:
        module_idx = kwargs.get("module_idx", 0)
        module_name, module_topics = MODULES[module_idx % len(MODULES)]

        prompt = f"""Write a video script for course module: {module_name}

Target video length: 15-20 minutes

Script format:
[INTRO — 2 min]
"Hey [student name], welcome to Module {module_idx + 1}..."
- Welcome + what they'll learn
- Quick win from this module

[LESSON CONTENT — 12-15 min]
[SECTION 1: Title]
Script: (word-for-word what to say)
[B-ROLL: what to show on screen]
[SLIDE: key point text]

[SECTION 2: Title]
[same format]

[SECTION 3: Title]
[same format]

[OUTRO — 2 min]
- Module recap (3 key takeaways)
- Homework assignment
- Tease next module

Talking notes format (conversational, not formal)
Include [PAUSE], [DEMO:], [SCREEN SHARE:] cues
Keep sentences short — reading aloud test."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "mini_course"
        (out_dir / f"script_module_{module_idx + 1}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"script_m{module_idx + 1}_{ts}.md", ext="md")
        return {"file": str(path), "action": "script"}

    def _workbook(self, ts: str, **kwargs) -> dict:
        prompt = """Create a complete course workbook for: Make Your First $500 With AI

Workbook for all 5 modules. For each module:
- Module overview + learning objectives
- Key concepts (fill-in-the-blank notes)
- Action worksheet (step-by-step exercises)
- Income tracker template
- Reflection prompts (3 questions)
- Checklist before moving to next module

Also include:
- COURSE OVERVIEW page (welcome + how to use this workbook)
- MY $500 GOAL worksheet (deadline + daily action tracker)
- RESOURCE LIST (tools, links, templates)
- CERTIFICATE OF COMPLETION (they fill in their name)

Format as markdown. Total length: 2,000-2,500 words."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "mini_course"
        (out_dir / "course_workbook.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"workbook_{ts}.md", ext="md")
        return {"file": str(path), "action": "workbook"}

    def _build_full_course(self, ts: str, **kwargs) -> dict:
        """Build the complete course outline + welcome content."""
        prompt = f"""Create the complete course guide for: Make Your First $500 With AI
Price: {self.price} | Creator: WheellsVerse / J.K. Blaze

Write:
1. WELCOME MESSAGE — warm letter from the instructor (300 words)
2. COURSE OVERVIEW — what they'll learn and achieve (200 words)
3. HOW TO USE THIS COURSE — pace, community, support (150 words)
4. MODULE ROADMAP — visual text map of all 5 modules with estimated times
5. BONUS RESOURCES LIST — 3 bonuses included with purchase
6. COMMUNITY ACCESS — where to get help (WheellsVerse community)
7. SUCCESS CONTRACT — student signs commitment to complete

Modules overview:
{chr(10).join(f"  Module {i + 1}: {m[0]} — {m[1]}" for i, m in enumerate(MODULES))}

Tone: Excited, warm, this is the beginning of their transformation."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "mini_course"
        (out_dir / "00_WELCOME_AND_OVERVIEW.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"course_overview_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🎓 Mini-Course — Master Overview Built\n'Make Your First $500 With AI'\n💰 {self.price} | 5 modules")
        except Exception:
            pass

        return {"file": str(path), "action": "full"}

    def _promote(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create promotional content for: Make Your First $500 With AI Course
Price: {self.price} | Link: {self.course_url}

Modules:
{chr(10).join(f"  ✅ Module {i + 1}: {m[0]}" for i, m in enumerate(MODULES))}

Generate:
1. FACEBOOK AD COPY (150 words) — transformation story structure, CTA to enroll
2. INSTAGRAM CAPTION (80 words + 20 hashtags) — scroll-stop hook, quick benefits, CTA
3. EMAIL SUBJECT LINE (5 variations A/B test)
4. WHATSAPP BROADCAST (60 words) — personal, direct, urgency

Target: beginner who wants to make money but feels overwhelmed by AI.
Outcome promise: first $500 in 30 days or less."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"course_promo_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            fb = get_facebook()
            if fb.is_configured():
                lines = result.split("\n")
                fb_lines = []
                in_fb = False
                for line in lines:
                    if "FACEBOOK" in line.upper():
                        in_fb = True
                    elif in_fb and any(k in line.upper() for k in ["INSTAGRAM", "EMAIL", "WHATSAPP"]):
                        break
                    elif in_fb:
                        fb_lines.append(line)
                fb_text = "\n".join(fb_lines).strip()
                if fb_text:
                    fb.post(fb_text)
        except Exception as e:
            self.logger.debug("Promo post skipped: %s", e)

        return {"file": str(path), "action": "promote"}

    def _course_listing(self, ts: str, **kwargs) -> dict:
        prompt = f"""Write a complete Gumroad course listing for: Make Your First $500 With AI
Price: {self.price}

1. TITLE — compelling, SEO-friendly
2. SHORT DESCRIPTION (150 chars)
3. SALES PAGE COPY (1000 words):
   - Hook: "What if you could make your first $500 online in the next 30 days..."
   - Problem: overwhelm, not knowing where to start
   - Solution: step-by-step AI-powered system
   - What's inside: all 5 modules + bonuses
   - Testimonials (3)
   - Instructor bio (J.K. Blaze, WheellsVerse)
   - Price reveal + guarantee
4. CURRICULUM BREAKDOWN (detailed module descriptions)
5. BONUSES (3 bonuses worth more than the course)
6. FAQ (8 questions)
7. GUARANTEE (30-day money-back)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "mini_course"
        (out_dir / "gumroad_listing.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"course_listing_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🎓 Mini-Course Listing Ready\n💰 {self.price}/student\n20 sales = $1,940/month\n📁 Upload to Gumroad!")
        except Exception:
            pass

        return {"file": str(path), "action": "listing"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mini-Course Revenue Bot")
    parser.add_argument("--action", default="build",
                        choices=["build", "script", "workbook", "promote", "full", "listing"])
    parser.add_argument("--module", type=int, default=0, help="Module index 0-4")
    args = parser.parse_args()
    bot = MiniCourseBot()
    result = bot.execute(action=args.action, module_idx=args.module)
    print(f"\n✅ Mini-Course: {result['file']}")
