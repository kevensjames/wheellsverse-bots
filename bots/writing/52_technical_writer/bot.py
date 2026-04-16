#!/usr/bin/env python3
"""
Bot #52 — Technical Documentation Writer
Category: Writing
Purpose: Write clear, comprehensive technical documentation including API docs,
         user guides, tutorials, SOPs, and release notes for technical products.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

DOC_TYPES = {
    "api_reference": {
        "desc": "Complete API reference documentation",
        "sections": "Overview, authentication, endpoints, request/response examples, error codes, rate limits, SDKs",
        "audience": "developers integrating the API",
    },
    "user_guide": {
        "desc": "End-user product guide from setup to advanced usage",
        "sections": "Introduction, installation, core features, advanced usage, troubleshooting, FAQ",
        "audience": "end users of the product",
    },
    "tutorial": {
        "desc": "Step-by-step tutorial for a specific task",
        "sections": "Prerequisites, overview, step-by-step instructions, code examples, next steps",
        "audience": "users learning to do a specific thing",
    },
    "sop": {
        "desc": "Standard Operating Procedure for a business process",
        "sections": "Purpose, scope, responsibilities, step-by-step procedure, quality checks, revision history",
        "audience": "team members executing the process",
    },
    "release_notes": {
        "desc": "Product release notes / changelog",
        "sections": "Version, date, new features, improvements, bug fixes, breaking changes, upgrade notes",
        "audience": "existing users and developers upgrading",
    },
    "readme": {
        "desc": "GitHub/project README documentation",
        "sections": "Overview, features, installation, quick start, usage, configuration, contributing, license",
        "audience": "developers evaluating or using the project",
    },
    "architecture_doc": {
        "desc": "Technical architecture and system design document",
        "sections": "System overview, components, data flow, tech stack, scalability, security, decisions",
        "audience": "engineers and technical stakeholders",
    },
}

COMPLEXITY_LEVELS = {
    "beginner": "Assume no prior technical knowledge — explain every concept",
    "intermediate": "Assume basic technical knowledge — focus on the product-specific details",
    "advanced": "Assume technical expertise — skip basics, focus on edge cases and nuances",
}


class TechnicalWriterBot(BaseBot):

    def __init__(self):
        super().__init__("52_technical_writer", "writing")

    def run(self, product: str = None, doc_type: str = None,
            audience: str = None, complexity: str = None,
            specific_topic: str = None, **kwargs):

        cfg = self.config
        product = product or cfg.get("product",
            "WheellsVerse Bot Platform — Python-based AI automation bot ecosystem")
        doc_type = doc_type or cfg.get("doc_type", "user_guide")
        audience = audience or cfg.get("audience", "developers and technical entrepreneurs")
        complexity = complexity or cfg.get("complexity", "intermediate")
        specific_topic = specific_topic or cfg.get("specific_topic",
            "Getting started with WheellsVerse bots")

        dt = DOC_TYPES.get(doc_type, DOC_TYPES["user_guide"])
        dt_desc = dt["desc"]
        dt_sections = dt["sections"]
        cx_desc = COMPLEXITY_LEVELS.get(complexity, complexity)

        self.logger.info(f"Writing {doc_type} for: {product}")

        system = (
            "You are a technical writer who has written documentation for Stripe, Twilio, "
            "GitHub, and other developer-first companies. You follow the Docs-as-Code philosophy: "
            "documentation should be clear, accurate, versioned, and maintained like source code. "
            "You write in plain English — short sentences, active voice, concrete examples. "
            "You know the difference between reference docs (look up a fact) and conceptual docs "
            "(understand why) and tutorials (do a task). Each type has different structure and tone. "
            "Your code examples always work. Your explanations never assume knowledge the reader doesn't have."
        )

        prompt = f"""Write complete technical documentation:

PRODUCT: {product}
DOCUMENTATION TYPE: {doc_type} — {dt_desc}
SPECIFIC TOPIC: {specific_topic}
TARGET AUDIENCE: {audience}
COMPLEXITY LEVEL: {complexity} — {cx_desc}
SECTIONS TO COVER: {dt_sections}

---

## DOCUMENTATION PLAN

**Document purpose:** [One sentence — what this doc helps the reader DO]
**Success criteria:** [Reader can [accomplish X] after reading this doc]
**Prerequisites:** [What the reader needs to know/have before starting]
**Scope:** [What this doc covers / what it explicitly does NOT cover]

---

## COMPLETE DOCUMENTATION

[Write the full documentation following the structure for a {doc_type}.

Guidelines:
- Use H1 for document title, H2 for major sections, H3 for subsections
- Write in present tense ("The bot returns..." not "The bot will return...")
- Use active voice ("Call the endpoint" not "The endpoint should be called")
- Use second person ("you") not third person
- Include code examples with proper syntax highlighting markers
- Add callout boxes for warnings, notes, and tips
- Include concrete examples for every concept
- Complexity level: {cx_desc}]

---

## CODE EXAMPLES (where applicable)

All code examples for this documentation:

```python
# [Example 1: Most common use case]
[Working code example]
```

```python
# [Example 2: Advanced use case]
[Working code example]
```

## TROUBLESHOOTING SECTION

Common issues and solutions for {specific_topic}:

| Error / Issue | Likely Cause | Solution |
| [Error 1] | | |
| [Error 2] | | |
| [Error 3] | | |
[5-7 rows]

## DOCUMENTATION QUALITY CHECKLIST

- [ ] Every technical claim is accurate and verified
- [ ] All code examples are complete and runnable
- [ ] No undefined acronyms or unexplained jargon
- [ ] All steps are in logical order with no gaps
- [ ] Screenshots/diagrams noted where they'd help (marked as [INSERT IMAGE])
- [ ] Links to related docs included
- [ ] Version/last-updated date included

## SEO / DISCOVERABILITY (for web docs)

**Page title:** [SEO-optimized title for documentation search]
**Meta description:** [Under 155 chars]
**Related docs to link from this page:** [3-5 related topics]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in specific_topic[:25])

        output = f"""# Technical Documentation: {specific_topic}
**Product:** {product}
**Doc Type:** {doc_type}
**Complexity:** {complexity}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Technical Writer Bot*
"""
        path = self.save_output(output, f"docs_{doc_type}_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Documentation saved → {path}")
        return {"file": str(path), "product": product, "doc_type": doc_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Technical Documentation Writer")
    parser.add_argument("--product", type=str, default=None)
    parser.add_argument("--type", type=str, default="user_guide",
                        choices=list(DOC_TYPES.keys()))
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--complexity", type=str, default="intermediate",
                        choices=list(COMPLEXITY_LEVELS.keys()))
    parser.add_argument("--topic", type=str, default=None)
    args = parser.parse_args()
    bot = TechnicalWriterBot()
    result = bot.execute(product=args.product, doc_type=args.type,
                         audience=args.audience, complexity=args.complexity,
                         specific_topic=args.topic)
    print(f"\n✅ Documentation: {result['file']}")
