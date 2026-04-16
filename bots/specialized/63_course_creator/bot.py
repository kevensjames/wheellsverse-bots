#!/usr/bin/env python3
"""
Bot #63 — Online Course Curriculum Designer
Category: Specialized
Purpose: Design a complete online course curriculum with modules, lessons, exercises,
         assessments, and delivery strategy for maximum student transformation.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

COURSE_TYPES = {
    "masterclass": "Premium comprehensive course -- full transformation, high ticket",
    "mini_course": "Focused quick-win course -- one specific outcome, lower price",
    "bootcamp": "Intensive cohort-based program with live support",
    "workshop": "Single-session deep dive -- 2-4 hours, one skill",
    "certification": "Curriculum leading to a certification or credential",
    "self_paced": "Evergreen self-paced course with no live component",
}

SKILL_LEVELS = {
    "beginner": "No prior knowledge required -- start from zero",
    "intermediate": "Working knowledge of the subject -- level up",
    "advanced": "Expert practitioners looking for mastery",
    "all_levels": "Mix of beginner-friendly and advanced content",
}


class CourseCreatorBot(BaseBot):

    def __init__(self):
        super().__init__("63_course_creator", "specialized")

    def run(self, course_topic: str = None, target_audience: str = None,
            skill_level: str = None, num_modules: int = None,
            course_type: str = None, **kwargs):

        cfg = self.config
        course_topic = course_topic or cfg.get("course_topic",
            "AI Automation for Entrepreneurs: Build 10 Income-Generating Bots")
        target_audience = target_audience or cfg.get("target_audience",
            "entrepreneurs and small business owners with no coding background")
        skill_level = skill_level or cfg.get("skill_level", "beginner")
        num_modules = num_modules or cfg.get("num_modules", 6)
        course_type = course_type or cfg.get("course_type", "self_paced")

        type_desc = COURSE_TYPES.get(course_type, course_type)
        level_desc = SKILL_LEVELS.get(skill_level, skill_level)

        self.logger.info(f"Designing course curriculum: {course_topic}")

        system = (
            "You are an instructional designer and online course expert who has built "
            "courses that have enrolled 50,000+ students and generated $M in revenue. "
            "You design for transformation, not information -- the goal is behavioral change, "
            "not just knowledge transfer. You apply adult learning theory (andragogy), "
            "spaced repetition, and skill scaffolding. You know that courses fail because "
            "they teach too much without practice. You build courses with strong learning "
            "loops: teach -> demonstrate -> practice -> apply -> review. "
            "Every module has a clear outcome the student can feel and measure."
        )

        # Pre-compute modules block to avoid nested triple-quoted f-strings (Python 3.11)
        def _make_lessons(module_idx):
            return "".join(
                f"#### Lesson {module_idx + 1}.{j + 1}: [Lesson Title]\n"
                "- **Format:** [Video/PDF/Worksheet/Quiz/Live call]\n"
                "- **Duration:** [X minutes]\n"
                "- **What you teach:** [Main concept + key insight]\n"
                "- **Student exercise:** [Practical activity to solidify the concept]\n"
                "- **Common mistake:** [What students get wrong here + how to prevent it]\n\n"
                for j in range(3)
            )

        modules_block = "".join(
            f"### Module {i + 1}: [Module Title]\n\n"
            "**Learning Objective:** By the end of this module, students will [specific outcome]\n"
            "**Why This Module:** [How it builds on previous module and sets up the next]\n"
            "**Estimated Time:** [X minutes]\n\n"
            "**Lessons:**\n"
            + _make_lessons(i)
            + "**Module Assignment:** [Hands-on project that proves the student learned the module outcome]\n"
            "**Assessment:** [Quiz questions or self-assessment rubric]\n"
            "**Module Resources:** [Templates, swipe files, tools, or downloads included]\n\n"
            "---\n\n"
            for i in range(num_modules)
        )

        prompt = f"""Design a complete online course curriculum for:

COURSE TOPIC: {course_topic}
TARGET AUDIENCE: {target_audience}
SKILL LEVEL: {skill_level} -- {level_desc}
NUMBER OF MODULES: {num_modules}
COURSE TYPE: {course_type} -- {type_desc}
BRAND: WheellsVerse -- AI automation tools for entrepreneurs

---

## COURSE STRATEGY

### Course Positioning
**Transformation promise:** [What the student is AFTER completing this course -- specific and measurable]
**Core belief change:** [What false belief do students have entering? What true belief do they leave with?]
**Target student:** [Specific person -- job title, pain point, aspiration]
**Why students fail without this course:** [What they've tried before that didn't work]

### Learning Outcomes (Module Level)
By the end of this course, students will be able to:
1. [Outcome 1 -- measurable skill or result]
2. [Outcome 2]
3. [Outcome 3]
[Up to {num_modules} outcomes]

### Differentiation
**Why this course over alternatives:**
[3 specific things that make this better than existing options]

---

## COMPLETE CURRICULUM

### Course Overview
- **Total modules:** {num_modules}
- **Estimated total time:** [X hours]
- **Format:** {course_type}
- **Delivery platform recommendations:** [Teachable / Kajabi / Gumroad / Podia -- with reason]

---

{modules_block}

## COURSE PRODUCTION PLAN

### Content Creation Order
1. [First module to record and why]
2. [Second module]
[Continue...]

### Equipment & Setup Recommendations
| Asset | Minimum (Budget) | Recommended | Why It Matters |
| Camera | [Budget option] | [Recommended] | |
| Microphone | [Budget option] | [Recommended] | |
| Screen recording | [Budget option] | [Recommended] | |
| Editing | [Budget option] | [Recommended] | |

### Recording Time Estimate
[Total hours to record {num_modules} modules with {num_modules * 3} lessons]

---

## LAUNCH STRATEGY

### Pre-Launch (4 weeks before)
- [Week -4 action]
- [Week -3 action]
- [Week -2 action]
- [Week -1 action]

### Launch Week
- [Day 1 action]
- [Day 3 action]
- [Day 5 -- cart close]

### Pricing Recommendation
| Version | Price | Includes |
| Core | $[X] | Videos + materials |
| Premium | $[Y] | Core + community + Q&A calls |
| VIP | $[Z] | Premium + 1-on-1 coaching |

---

## STUDENT SUCCESS METRICS

How to measure if the course is working:
| Metric | Target | How to Measure |
| Completion rate | >40% | Platform analytics |
| Transformation rate | >60% applied skills | Post-course survey |
| Testimonial rate | >20% | Follow-up email |
| Refund rate | <5% | Payment platform |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in course_topic[:25])

        output = f"""# Course Curriculum: {course_topic}
**Type:** {course_type}
**Skill Level:** {skill_level}
**Modules:** {num_modules}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Course Creator Bot*
"""
        path = self.save_output(output, f"course_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Course curriculum saved -> {path}")
        return {"file": str(path), "topic": course_topic, "modules": num_modules}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Online Course Curriculum Designer")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--level", type=str, default="beginner",
                        choices=list(SKILL_LEVELS.keys()))
    parser.add_argument("--modules", type=int, default=6)
    parser.add_argument("--type", type=str, default="self_paced",
                        choices=list(COURSE_TYPES.keys()))
    args = parser.parse_args()
    bot = CourseCreatorBot()
    result = bot.execute(course_topic=args.topic, target_audience=args.audience,
                         skill_level=args.level, num_modules=args.modules,
                         course_type=args.type)
    print(f"\n✅ Course Curriculum: {result['file']}")
