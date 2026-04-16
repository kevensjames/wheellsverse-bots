#!/usr/bin/env python3
"""
Bot #50 — Personalized Cover Letter Generator
Category: Writing
Purpose: Generate compelling, personalized cover letters tailored to specific roles
         and companies, with multiple tone options and interview-winning frameworks.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

LETTER_STYLES = {
    "storytelling": "Opens with a compelling personal story that connects to the role",
    "achievement": "Leads with a specific quantified achievement that proves fit",
    "problem_solver": "Opens by identifying a company challenge and positioning yourself as the solution",
    "passion_driven": "Leads with genuine enthusiasm for the company's mission",
    "concise": "Ultra-brief (200 words), every sentence earns its place",
}

FRAMEWORKS = {
    "STAR": "Situation → Task → Action → Result",
    "Problem_Agitate_Solve": "State a problem they have → make it feel urgent → show how you solve it",
    "They_You_Fit": "Open with them (show you know the company) → bridge to you → show the fit",
}


class CoverLetterBot(BaseBot):

    def __init__(self):
        super().__init__("50_cover_letter", "writing")

    def run(self, role: str = None, company: str = None,
            your_background: str = None, key_achievements: str = None,
            letter_style: str = None, **kwargs):

        cfg = self.config
        role = role or cfg.get("role", "AI Automation Specialist")
        company = company or cfg.get("company", "WheellsVerse")
        your_background = your_background or cfg.get("your_background",
            "entrepreneur with 3 years building AI automation systems and 70+ production bots")
        key_achievements = key_achievements or cfg.get("key_achievements",
            "automated 80% of business operations, built social presence from 0 to 10K, earned $X in automated revenue")
        letter_style = letter_style or cfg.get("letter_style", "achievement")

        style_desc = LETTER_STYLES.get(letter_style, letter_style)
        self.logger.info(f"Writing cover letter for: {role} at {company}")

        system = (
            "You are a career coach and cover letter specialist who has helped hundreds of "
            "candidates land interviews at their dream companies. You know that hiring managers "
            "spend 30 seconds on a cover letter — so every word must pull its weight. "
            "You write letters that feel personal, not templated. You mirror the company's language "
            "and culture. You lead with impact, not duties. You make the hiring manager feel like "
            "NOT interviewing this person would be a mistake. You never start with 'I am writing to "
            "apply for...' — that's the fastest way to the rejection pile."
        )

        prompt = f"""Write 3 versions of a compelling, personalized cover letter for:

ROLE: {role}
COMPANY: {company}
YOUR BACKGROUND: {your_background}
KEY ACHIEVEMENTS: {key_achievements}
PRIMARY STYLE: {letter_style} — {style_desc}

---

## LETTER ANALYSIS

**What {company} is likely looking for in this {role}:**
[3-4 bullet points on what the company values in this hire]

**Your strongest angle:**
[The single most compelling reason you're right for this role — lead with this]

**Red flags to address:** (if any)
[Any potential objections — career gap, industry pivot, overqualified/underqualified]

---

## VERSION 1 — {letter_style.upper().replace("_", " ")} STYLE

**Subject line (for email applications):**
[Compelling subject line — not just "Application for [Role]"]

---

[Full Name]
[Date]

Hiring Manager / [Hiring Manager Name if known]
{company}

**Dear [Hiring Manager's Name],**

[Opening paragraph — hook using {style_desc}. 2-3 sentences max. Never start with "I am writing to..."]

[Second paragraph — connect your top achievement from "{key_achievements}" directly to what {company} needs. Be specific. Use numbers.]

[Third paragraph — show you know the company. Reference their mission, recent news, or culture. Show this isn't a mass application.]

[Closing paragraph — confident close. Specific ask for interview. Brief statement of mutual benefit.]

**Best regards,**
[Full Name]
[Contact Info]

---

## VERSION 2 — ACHIEVEMENT-FIRST STYLE

[Alternative version leading with your strongest quantified achievement]

---

## VERSION 3 — CONCISE (under 200 words)

[Ultra-brief version for companies that prefer brevity or for email body applications]

---

## CUSTOMIZATION GUIDE

**If you know the hiring manager's name:** [How to personalize further]
**If applying via email vs. portal:** [Format adjustments]
**If {company} is known for a specific culture:** [Tone adjustments]

**DO / DON'T:**
| ✅ Do | ❌ Don't |
| Start with a hook or achievement | Start with "I am writing to apply..." |
| Use their exact words from the job description | Use generic industry buzzwords |
| [3 more dos specific to this role] | [3 more don'ts] |

## FOLLOW-UP EMAIL TEMPLATE

One week after submitting — if no response:
**Subject:** [Subject line]
```
[Brief, confident follow-up — under 100 words]
```"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_role = "".join(c if c.isalnum() else "_" for c in role[:20])
        safe_co = "".join(c if c.isalnum() else "_" for c in company[:15])

        output = f"""# Cover Letter: {role} at {company}
**Style:** {letter_style}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Cover Letter Bot*
"""
        path = self.save_output(output, f"coverletter_{safe_role}_{safe_co}_{ts}.md", ext="md")
        self.logger.info(f"Cover letter saved → {path}")
        return {"file": str(path), "role": role, "company": company}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Personalized Cover Letter Generator")
    parser.add_argument("--role", type=str, default=None)
    parser.add_argument("--company", type=str, default=None)
    parser.add_argument("--background", type=str, default=None)
    parser.add_argument("--achievements", type=str, default=None)
    parser.add_argument("--style", type=str, default="achievement",
                        choices=list(LETTER_STYLES.keys()))
    args = parser.parse_args()
    bot = CoverLetterBot()
    result = bot.execute(role=args.role, company=args.company,
                         your_background=args.background,
                         key_achievements=args.achievements,
                         letter_style=args.style)
    print(f"\n✅ Cover Letter: {result['file']}")
