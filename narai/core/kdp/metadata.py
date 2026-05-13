"""KDP metadata optimizer — generate SEO-tuned title/subtitle/description/keywords.

Amazon KDP rules: title <200 chars, subtitle <200, description <4000, 7 keywords,
3 categories. Uses NarAI router for copywriting."""
from __future__ import annotations

from typing import Any

from infra.brain.interface import BrainClient

# Scheduler-driven module: not per-request. Uses the synthetic "system"
# user_id so telemetry + memory are scoped distinctly from any human user.
_brain = BrainClient(user_id="system", mode="narai")


async def optimize_metadata(topic: str, genre: str = "self-help",
                            target_reader: str = "entrepreneurs",
                            existing_title: str = "") -> dict[str, Any]:
    prompt = (
        f"Optimize KDP book metadata for a book on '{topic}' in the '{genre}' category, "
        f"targeting {target_reader}. "
        f"{'Current title: ' + existing_title if existing_title else ''}\n\n"
        "Rules: Title <200 chars, benefit-driven + keyword-rich. "
        "Subtitle <200 chars, expands the promise. "
        "Description <4000 chars, HTML bullets + social proof hooks, "
        "end with a clear reason to buy. "
        "7 KDP keyword phrases (long-tail, buyer-intent, no duplicates), each <50 chars. "
        "3 BISAC-style categories.\n\n"
        "Output JSON:\n"
        '{"title": "...", "subtitle": "...", "description": "...", '
        '"keywords": ["...", ...7 items], "categories": ["...", ...3 items]}'
    )
    system = _brain.skills.build_system_prompt(
        base=("You are NarAI as a KDP SEO expert. Use Amazon search-volume heuristics. "
              "Output valid JSON only, no surrounding text.")
    )
    result = await _brain.router.call(prompt, tier="deep", system=system)
    text = result.get("content", "")

    # Extract JSON block
    import json
    import re
    m = re.search(r"\{.*\}", text, re.DOTALL)
    parsed: dict[str, Any] = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            pass

    return {
        "topic": topic,
        "metadata": parsed,
        "raw": text,
        "model": result.get("model", ""),
    }
