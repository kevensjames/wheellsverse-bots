#!/usr/bin/env python3
"""
Bot #53 — AI Proofreader & Editor
Category: Writing
Purpose: Proofread, edit, and improve written content — grammar, style, clarity,
         tone consistency, and brand voice alignment — with tracked changes.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

EDIT_MODES = {
    "proofread": "Fix grammar, spelling, punctuation only — preserve voice and structure",
    "line_edit": "Improve sentence clarity, flow, and word choice while preserving meaning",
    "substantive": "Full structural and content edit — reorganize, strengthen arguments, cut weak sections",
    "style_guide": "Enforce a specific style guide (AP, Chicago, APA, brand voice)",
    "seo_optimize": "Improve keyword density, meta elements, and on-page SEO without losing readability",
    "tone_adjust": "Shift the tone (formal→casual, casual→professional, aggressive→friendly)",
    "shorten": "Cut length by 25-40% while preserving all key information",
    "strengthen_copy": "Make copy more persuasive, benefit-focused, and conversion-oriented",
}

STYLE_GUIDES = {
    "ap": "Associated Press (journalism standard — numerals, abbreviations, dates)",
    "chicago": "Chicago Manual of Style (book/academic publishing)",
    "apa": "APA Style (academic papers, psychology, social sciences)",
    "brand": "WheellsVerse brand voice: direct, conversational, expert but approachable",
    "plain": "Plain English: short sentences, active voice, no jargon",
    "web": "Web writing: scannable, headers, bullets, front-loaded info",
}


class ProofreaderBot(BaseBot):

    def __init__(self):
        super().__init__("53_proofreader", "writing")

    def run(self, content: str = None, content_type: str = None,
            edit_mode: str = None, style_guide: str = None,
            goals: str = None, **kwargs):

        cfg = self.config
        content = content or cfg.get("content",
            "[Paste your text here to proofread and edit]")
        content_type = content_type or cfg.get("content_type",
            "blog post / marketing copy / social media post")
        edit_mode = edit_mode or cfg.get("edit_mode", "line_edit")
        style_guide = style_guide or cfg.get("style_guide", "brand")
        goals = goals or cfg.get("goals",
            "improve clarity, strengthen persuasion, ensure brand voice consistency")

        mode_desc = EDIT_MODES.get(edit_mode, edit_mode)
        guide_desc = STYLE_GUIDES.get(style_guide, style_guide)

        self.logger.info(f"Proofreading {content_type} using {edit_mode} mode")

        system = (
            "You are a senior editor with 15+ years of experience editing content for "
            "The New York Times, HubSpot, and top creator brands. You have a razor-sharp eye "
            "for grammar, but you know that grammar is the least important part of editing. "
            "The most important part is meaning: is every sentence clear? Does it earn its place? "
            "Does it serve the reader? You edit with tracked-change discipline — you always "
            "explain WHY you changed something so writers learn, not just what you changed. "
            "You preserve the writer's voice; you improve it, not replace it with your own."
        )

        prompt = f"""Proofread and edit the following content:

CONTENT TYPE: {content_type}
EDIT MODE: {edit_mode} — {mode_desc}
STYLE GUIDE: {style_guide} — {guide_desc}
EDITING GOALS: {goals}
BRAND: WheellsVerse — direct, conversational, expert but approachable

---

## CONTENT TO EDIT:

```
{content}
```

---

## EDITORIAL REPORT

### Overall Assessment
**Strengths:** [What's working well — be specific]
**Primary issues:** [Top 3 things holding this content back]
**Priority fixes:** [What to address first for maximum impact]

### Readability Scores (estimated)
- **Flesch-Kincaid Grade Level:** [X]
- **Average sentence length:** [X words]
- **Passive voice instances:** [X]
- **Recommended grade level for {content_type}:** [X]

---

## TRACKED CHANGES

Format: ~~strikethrough~~ = removed | **bold** = added/changed | [NOTE: explanation]

```
[Full edited version of the content with tracked changes inline.
Show every change made. After each significant edit, add [NOTE: why this change improves the writing]]
```

---

## CLEAN VERSION (FINAL)

```
[The complete edited text with all changes applied — clean, ready to publish]
```

---

## SPECIFIC CORRECTIONS LOG

| # | Original | Revised | Issue Type | Why |
[List every change made — grammar fixes, word swaps, structural moves]
| 1 | [original phrase] | [revised phrase] | [Grammar/Style/Clarity/Tone/SEO] | [Reason] |
[Continue for all changes]

## STYLISTIC RECOMMENDATIONS

Issues that go beyond this edit and should be addressed in future writing:
1. **[Pattern]:** [Recurring issue + how to fix it going forward]
2. **[Pattern]:** [Recurring issue + how to fix it going forward]
3. **[Pattern]:** [Recurring issue + how to fix it going forward]

## BRAND VOICE CHECK (WheellsVerse)

✅ **On brand:**
[What the content does well that aligns with WheellsVerse voice]

⚠️ **Off brand:**
[Where the content drifts from the intended voice + suggested fixes]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_type = self.slugify(content_type, 20)

        output = f"""# Proofreading Report: {content_type}
**Edit Mode:** {edit_mode}
**Style Guide:** {style_guide}
**Goals:** {goals}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Proofreader Bot*
"""
        path = self.save_output(output, f"proofread_{safe_type}_{ts}.md", ext="md")
        self.logger.info(f"Proofreading report saved → {path}")
        return {"file": str(path), "content_type": content_type, "edit_mode": edit_mode}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Proofreader & Editor")
    parser.add_argument("--content", type=str, default=None,
                        help="Text to proofread (or path to .txt file)")
    parser.add_argument("--type", type=str, default="blog post")
    parser.add_argument("--mode", type=str, default="line_edit",
                        choices=list(EDIT_MODES.keys()))
    parser.add_argument("--style", type=str, default="brand",
                        choices=list(STYLE_GUIDES.keys()))
    parser.add_argument("--goals", type=str, default=None)
    args = parser.parse_args()

    # Allow reading content from a file
    content_input = args.content
    if content_input and content_input.endswith(".txt"):
        try:
            content_input = open(content_input).read()
        except FileNotFoundError:
            pass

    bot = ProofreaderBot()
    result = bot.execute(content=content_input, content_type=args.type,
                         edit_mode=args.mode, style_guide=args.style,
                         goals=args.goals)
    print(f"\n✅ Proofreading Report: {result['file']}")
