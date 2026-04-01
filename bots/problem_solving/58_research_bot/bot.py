#!/usr/bin/env python3
"""
Bot #58 — Deep Research & Analysis Report Generator
Category: Problem Solving
Purpose: Produce comprehensive research reports on any topic — market analysis,
         competitor research, technical evaluation, or investment due diligence.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

RESEARCH_TYPES = {
    "market_analysis":    "Market size, trends, growth drivers, key players, opportunities",
    "competitor_research": "Deep competitive intelligence on specific companies or products",
    "technology_eval":    "Technical assessment of tools, frameworks, or platforms",
    "investment_thesis":  "Due diligence on investment opportunities",
    "trend_report":       "Emerging trends, signals, and future implications",
    "problem_research":   "Systematic analysis of a specific problem or challenge",
    "literature_review":  "Survey of existing knowledge, frameworks, and best practices",
    "feasibility_study":  "Assess viability of an idea, project, or strategy",
}

DEPTH_LEVELS = {
    "overview":     "High-level summary — 500-800 words, key points only",
    "standard":     "Comprehensive report — 1,500-2,500 words with analysis",
    "deep_dive":    "Exhaustive analysis — 3,000+ words with frameworks and models",
    "executive":    "Executive summary format — decision-focused, under 500 words",
}


class ResearchBot(BaseBot):

    def __init__(self):
        super().__init__("58_research_bot", "problem_solving")

    def run(self, research_topic: str = None, research_type: str = None,
            depth: str = None, focus_area: str = None,
            decision_needed: str = None, **kwargs):

        cfg = self.config
        research_topic  = research_topic or cfg.get("research_topic",
            "AI agents landscape 2025 — autonomous AI systems for business automation")
        research_type   = research_type or cfg.get("research_type", "market_analysis")
        depth           = depth or cfg.get("depth", "standard")
        focus_area      = focus_area or cfg.get("focus_area",
            "opportunities for WheellsVerse to position in the AI automation market")
        decision_needed = decision_needed or cfg.get("decision_needed",
            "which AI agent frameworks to build integrations for")

        type_desc  = RESEARCH_TYPES.get(research_type, research_type)
        depth_desc = DEPTH_LEVELS.get(depth, depth)

        self.logger.info(f"Researching: {research_topic} ({research_type})")

        system = (
            "You are a senior research analyst and consultant who has produced reports for "
            "McKinsey, a16z, and Fortune 500 strategy teams. You are rigorous but practical — "
            "your research ends with decisions, not just information. You structure reports "
            "with a clear thesis, evidence hierarchy, and actionable conclusions. "
            "You separate facts from analysis from opinion — always signaling which is which. "
            "You include confidence levels on key claims. You surface counterarguments and risks. "
            "You never write vague conclusions — every report ends with specific recommended actions."
        )

        prompt = f"""Produce a comprehensive research report:

RESEARCH TOPIC: {research_topic}
RESEARCH TYPE: {research_type} — {type_desc}
DEPTH: {depth} — {depth_desc}
FOCUS AREA: {focus_area}
DECISION TO MAKE: {decision_needed}
ORGANIZATION: WheellsVerse — AI automation tools for entrepreneurs

---

## EXECUTIVE SUMMARY

**Research question:** [The specific question this report answers]
**Key finding:** [The single most important conclusion — 1-2 sentences]
**Recommended action:** [What to do based on this research — specific]
**Confidence level:** [High/Medium/Low — and why]

---

## RESEARCH SCOPE

**What this report covers:** [Define the scope]
**What it doesn't cover:** [Explicit limitations]
**Methodology:** [How this analysis was structured]
**Key assumptions:** [What we're assuming to be true]

---

## CORE ANALYSIS

[Write the full research report at {depth} depth — {depth_desc}.

For {research_type}, structure with these key areas: {type_desc}

Include:
- Data, statistics, and concrete examples (with sources noted)
- Expert perspectives and consensus view
- Contrarian or minority viewpoints
- Trend direction (increasing/stable/decreasing)
- Geographic or segment variations if relevant
- Signal vs. noise distinction for key claims

For {focus_area}: weave in specific relevance to WheellsVerse throughout.]

---

## KEY FINDINGS SUMMARY

Top 5 findings from this research:
1. **[Finding]** — Confidence: [High/Med/Low] — Implication: [What this means]
2. **[Finding]** — Confidence: [High/Med/Low] — Implication: [What this means]
3. **[Finding]** — Confidence: [High/Med/Low] — Implication: [What this means]
4. **[Finding]** — Confidence: [High/Med/Low] — Implication: [What this means]
5. **[Finding]** — Confidence: [High/Med/Low] — Implication: [What this means]

---

## DECISION FRAMEWORK

Addressing: "{decision_needed}"

**Option A: [Name]**
- Evidence supporting: [Key data points]
- Evidence against: [Key risks]
- Verdict: [Recommended / Not Recommended / Conditional]

**Option B: [Name]**
- Evidence supporting: [Key data points]
- Evidence against: [Key risks]
- Verdict: [Recommended / Not Recommended / Conditional]

**Recommended path:** [Clear recommendation + reasoning]

---

## RISKS & UNKNOWNS

**Known risks:**
| Risk | Likelihood | Impact | Mitigation |
[3-5 rows]

**Key unknowns that could change this analysis:**
1. [Unknown 1 — what we'd need to know to change the recommendation]
2. [Unknown 2]
3. [Unknown 3]

---

## NEXT STEPS

Based on this research, the recommended actions for WheellsVerse:

**This week:**
1. [Specific action]
2. [Specific action]

**This month:**
1. [Specific action]
2. [Specific action]

**Track these signals:**
[3-4 metrics or developments to monitor that would update this analysis]

## SOURCES & FURTHER READING

**Primary sources cited:**
[List key sources used]

**For deeper research:**
[3-5 recommended resources for going deeper on this topic]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in research_topic[:25])

        output = f"""# Research Report: {research_topic[:60]}
**Type:** {research_type}
**Depth:** {depth}
**Focus:** {focus_area}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Research Bot*
"""
        path = self.save_output(output, f"research_{research_type}_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Research report saved → {path}")
        return {"file": str(path), "topic": research_topic, "type": research_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deep Research & Analysis Report Generator")
    parser.add_argument("--topic",    type=str, default=None)
    parser.add_argument("--type",     type=str, default="market_analysis",
                        choices=list(RESEARCH_TYPES.keys()))
    parser.add_argument("--depth",    type=str, default="standard",
                        choices=list(DEPTH_LEVELS.keys()))
    parser.add_argument("--focus",    type=str, default=None)
    parser.add_argument("--decision", type=str, default=None)
    args = parser.parse_args()
    bot = ResearchBot()
    result = bot.execute(research_topic=args.topic, research_type=args.type,
                         depth=args.depth, focus_area=args.focus,
                         decision_needed=args.decision)
    print(f"\n✅ Research Report: {result['file']}")
