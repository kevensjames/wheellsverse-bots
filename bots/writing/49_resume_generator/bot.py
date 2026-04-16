#!/usr/bin/env python3
"""
Bot #49 — ATS-Optimized Resume Generator
Category: Writing
Purpose: Generate complete, ATS-beating resumes tailored to specific job roles
         with optimized bullet points, keyword placement, and formatting guidance.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

EXPERIENCE_LEVELS = {
    "entry": "0-2 years — recent graduate or career starter",
    "mid": "3-6 years — experienced individual contributor",
    "senior": "7-12 years — senior specialist or team lead",
    "director": "12+ years — director, VP, or executive level",
    "career_change": "Pivoting industries or roles — transferable skills focus",
}

INDUSTRIES = [
    "technology / software",
    "AI and machine learning",
    "marketing and growth",
    "sales and business development",
    "finance and fintech",
    "healthcare and biotech",
    "e-commerce and retail",
    "consulting and strategy",
    "content creation and media",
    "entrepreneurship / startup",
]


class ResumeGeneratorBot(BaseBot):

    def __init__(self):
        super().__init__("49_resume_generator", "writing")

    def run(self, target_role: str = None, experience_level: str = None,
            industry: str = None, key_skills: str = None,
            achievements: str = None, **kwargs):

        cfg = self.config
        target_role = target_role or cfg.get("target_role", "AI Automation Specialist")
        experience_level = experience_level or cfg.get("experience_level", "mid")
        industry = industry or cfg.get("industry", "technology / software")
        key_skills = key_skills or cfg.get("key_skills",
            "Python, AI/ML, automation workflows, n8n, Zapier, API integrations")
        achievements = achievements or cfg.get("achievements",
            "built 70 AI bots, automated 80% of business operations, grew social presence to 10K+")

        level_desc = EXPERIENCE_LEVELS.get(experience_level, experience_level)
        self.logger.info(f"Generating resume for: {target_role} ({experience_level})")

        system = (
            "You are a professional resume writer and career coach who has helped 500+ candidates "
            "land roles at Google, Apple, McKinsey, and top startups. You know that modern resumes "
            "must pass two gates: the ATS (Applicant Tracking System) bot, and the 6-second human "
            "scan. You write bullet points that lead with strong action verbs, quantify results "
            "whenever possible, and use keywords from the job description naturally. You build "
            "resumes that tell a clear career story — each role building logically on the last. "
            "You never use passive voice, filler phrases ('responsible for'), or vague claims."
        )

        prompt = f"""Generate a complete, ATS-optimized resume for:

TARGET ROLE: {target_role}
EXPERIENCE LEVEL: {experience_level} — {level_desc}
INDUSTRY: {industry}
KEY SKILLS: {key_skills}
KEY ACHIEVEMENTS: {achievements}

---

## ATS KEYWORD ANALYSIS

**Primary keywords for {target_role}:**
[15-20 keywords that ATS systems scan for in this role — in order of importance]

**How to use them:**
[Where to place keywords for maximum ATS score — title, summary, skills, bullets]

---

## COMPLETE RESUME

---

**[FULL NAME]**
[City, State] | [email@example.com] | [Phone] | [LinkedIn URL] | [Portfolio/GitHub URL]

---

### PROFESSIONAL SUMMARY
[3-4 sentences: who you are → your expertise → your biggest achievement → what you bring to {target_role}]
[Include "{target_role}" naturally in first sentence. Target 50-75 words.]

---

### CORE COMPETENCIES
[Keyword-rich skills section — 12-18 skills in 3 columns or comma-separated]
Based on: {key_skills}

---

### PROFESSIONAL EXPERIENCE

**[Most Recent Job Title] | [Company Name] | [City, State] | [Start Date] – Present**

- [Bullet 1: Lead with power verb + specific achievement + quantified result]
- [Bullet 2: Lead with power verb + responsibility that maps to {target_role}]
- [Bullet 3: Lead with power verb + technology/skill used + outcome]
- [Bullet 4: Lead with power verb + scope/scale of work]
- [Bullet 5 if senior: Lead with power verb + leadership/mentoring achievement]

**[Previous Job Title] | [Company Name] | [City, State] | [Start] – [End]**

- [Bullet 1: Quantified achievement]
- [Bullet 2: Skill/technology relevant to {target_role}]
- [Bullet 3: Problem solved + impact]
- [Bullet 4: Collaboration or cross-functional contribution]

**[Earlier Job Title] | [Company Name] | [Start] – [End]**
- [2-3 concise bullets for older experience]

---

### EDUCATION

**[Degree] in [Field] | [University Name] | [Year]**
- Relevant coursework: [3-4 courses relevant to {target_role}]
- [Honors, GPA if 3.5+, thesis if relevant]

---

### CERTIFICATIONS & TRAINING
- [Cert 1] — [Issuer] — [Year]
- [Cert 2] — [Issuer] — [Year]
[Include AI, automation, or relevant certs]

---

### PROJECTS / PORTFOLIO (if applicable for {target_role})
**[Project Name]** — [1-sentence description + link]
**[Project Name]** — [1-sentence description + link]

---

## BULLET POINT REWRITES

**From generic → to ATS-optimized:**

| Before (weak) | After (strong) |
| "Responsible for managing social media" | "Grew Instagram following 340% in 6 months by implementing data-driven content strategy" |
| "Worked with APIs" | "Integrated 15+ REST APIs to automate workflows, reducing manual processing time by 70%" |
[5 more before/after rewrites tailored to {target_role}]

## COVER LETTER HOOK

First paragraph of a cover letter for {target_role}:
```
[Write a compelling first paragraph that references a specific achievement and connects it to the role]
```

## ATS SCORE CHECKLIST

- [ ] Job title appears in summary or headline
- [ ] 80%+ of keywords from job description present
- [ ] No tables, columns, headers/footers (ATS can't read these)
- [ ] Dates in consistent format (Month Year)
- [ ] No graphics, logos, or images
- [ ] Saved as .docx or plain PDF (not image PDF)
- [ ] File name: FirstName_LastName_Resume.pdf"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_role = "".join(c if c.isalnum() else "_" for c in target_role[:25])

        output = f"""# Resume: {target_role}
**Experience Level:** {experience_level}
**Industry:** {industry}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Resume Generator Bot*
"""
        path = self.save_output(output, f"resume_{safe_role}_{ts}.md", ext="md")
        self.logger.info(f"Resume saved → {path}")
        return {"file": str(path), "role": target_role, "level": experience_level}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ATS-Optimized Resume Generator")
    parser.add_argument("--role", type=str, default=None)
    parser.add_argument("--level", type=str, default="mid",
                        choices=list(EXPERIENCE_LEVELS.keys()))
    parser.add_argument("--industry", type=str, default=None)
    parser.add_argument("--skills", type=str, default=None)
    parser.add_argument("--wins", type=str, default=None,
                        help="Key achievements to highlight")
    args = parser.parse_args()
    bot = ResumeGeneratorBot()
    result = bot.execute(target_role=args.role, experience_level=args.level,
                         industry=args.industry, key_skills=args.skills,
                         achievements=args.wins)
    print(f"\n✅ Resume: {result['file']}")
