#!/usr/bin/env python3
"""
Bot #57 — Code Debugging Assistant
Category: Problem Solving
Purpose: Analyze code errors, identify root causes, provide step-by-step fixes,
         and suggest defensive coding patterns to prevent similar bugs.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

LANGUAGES = [
    "python", "javascript", "typescript", "bash", "sql",
    "go", "rust", "java", "php", "ruby", "c++",
]

ERROR_CATEGORIES = {
    "syntax":      "SyntaxError, IndentationError, ParseError — code won't run",
    "runtime":     "Exception raised during execution — TypeError, ValueError, AttributeError",
    "logic":       "Code runs but produces wrong output — off-by-one, wrong condition",
    "performance": "Code runs but is too slow or uses too much memory",
    "import":      "ModuleNotFoundError, ImportError, dependency issues",
    "api":         "API calls failing — 4xx/5xx errors, auth issues, rate limits",
    "async":       "Async/await issues, event loop errors, race conditions",
    "environment": "Works locally but not in production — env vars, paths, permissions",
}


class DebuggingAssistantBot(BaseBot):

    def __init__(self):
        super().__init__("57_debugging_assistant", "problem_solving")

    def run(self, error_message: str = None, language: str = None,
            code_snippet: str = None, context: str = None, **kwargs):

        cfg = self.config
        error_message = error_message or cfg.get("error_message",
            "TypeError: 'NoneType' object is not subscriptable")
        language      = language or cfg.get("language", "python")
        code_snippet  = code_snippet or cfg.get("code_snippet",
            "# Paste your problematic code here")
        context       = context or cfg.get("context",
            "WheellsVerse bot automation — Python bot calling OpenAI API")

        # Detect error category from message
        detected_category = "runtime"
        for cat, desc in ERROR_CATEGORIES.items():
            if any(kw in error_message.lower() for kw in [cat, desc.split(" ")[0].lower()]):
                detected_category = cat
                break

        self.logger.info(f"Debugging {language} error: {error_message[:50]}...")

        system = (
            "You are a senior software engineer and debugging specialist with 15+ years of "
            "experience across multiple languages and systems. You approach bugs methodically: "
            "you never guess, you trace the cause. You explain bugs in plain English first, "
            "then provide the exact fix, then teach the developer how to catch this class of "
            "bug in the future. You understand that the developer is frustrated — you're direct, "
            "not condescending. You give the minimum viable fix first, then the ideal fix if "
            "they differ. You include defensive coding patterns to prevent recurrence."
        )

        prompt = f"""Debug this error and provide a complete solution:

ERROR MESSAGE: {error_message}
LANGUAGE: {language}
ERROR CATEGORY: {detected_category} — {ERROR_CATEGORIES.get(detected_category, "general error")}
CONTEXT: {context}

CODE WITH THE BUG:
```{language}
{code_snippet}
```

---

## DIAGNOSIS

### What This Error Means (Plain English)
[Explain what "{error_message}" means — no jargon, 2-3 sentences]

### Root Cause Analysis
**The actual problem:**
[What specifically in the code is causing this — be precise about the line/variable/logic]

**Why it happens:**
[The underlying mechanism — why Python/JS/etc raises this specific error in this situation]

**Trigger condition:**
[What input, state, or sequence of events causes this error]

---

## THE FIX

### Minimum Viable Fix (quickest to implement)
```{language}
# BEFORE (broken)
[The problematic code]

# AFTER (fixed)
[The corrected code with inline comment explaining the fix]
```

**What changed:** [1-2 sentences]

### Ideal Fix (production-quality)
```{language}
# Complete fixed version with proper error handling
[Full corrected code with defensive patterns]
```

**What improved beyond the minimum fix:**
[List the additional improvements — error handling, type checks, etc.]

---

## STEP-BY-STEP DEBUGGING PROCESS

How to verify this is the right fix:

1. **Reproduce the bug:**
```{language}
# Minimal reproducer
[Smallest possible code that triggers the error]
```

2. **Apply the fix:**
[Instructions]

3. **Verify the fix:**
```{language}
# Test cases to confirm the fix works
[2-3 test cases]
```

4. **Edge cases to test:**
[List 3-5 edge cases that could still cause issues]

---

## ROOT CAUSE: DEEPER ISSUE

[If this error is a symptom of a larger design problem, call it out here]

**The real question is:** [If there's a design issue worth addressing]
**Recommended refactor:** [Brief suggestion — only if genuinely needed]

---

## PREVENTION: DEFENSIVE CODING PATTERNS

To prevent this class of error in the future:

### Pattern 1: [Name]
```{language}
# Example of defensive pattern
[Code example]
```

### Pattern 2: [Name]
```{language}
[Code example]
```

### Linting/Type checking setup:
[Recommend tools: mypy for Python, ESLint for JS, etc. with config]

---

## SIMILAR BUGS TO WATCH FOR

In code similar to this, these related bugs commonly appear:
1. **[Bug type]:** [What causes it + one-line prevention]
2. **[Bug type]:** [What causes it + one-line prevention]
3. **[Bug type]:** [What causes it + one-line prevention]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_error = "".join(c if c.isalnum() else "_" for c in error_message[:25])

        output = f"""# Debug Report: {error_message[:60]}
**Language:** {language}
**Context:** {context}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Debugging Assistant Bot*
"""
        path = self.save_output(output, f"debug_{language}_{safe_error}_{ts}.md", ext="md")
        self.logger.info(f"Debug report saved → {path}")
        return {"file": str(path), "error": error_message, "language": language}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Code Debugging Assistant")
    parser.add_argument("--error",    type=str, default=None,
                        help="The error message")
    parser.add_argument("--language", type=str, default="python",
                        choices=LANGUAGES)
    parser.add_argument("--code",     type=str, default=None,
                        help="The problematic code snippet")
    parser.add_argument("--context",  type=str, default=None)
    args = parser.parse_args()
    bot = DebuggingAssistantBot()
    result = bot.execute(error_message=args.error, language=args.language,
                         code_snippet=args.code, context=args.context)
    print(f"\n✅ Debug Report: {result['file']}")
