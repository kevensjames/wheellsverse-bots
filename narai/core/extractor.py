"""
Extract structured facts from a user turn.
Pluggable LLM — pass any callable that takes (system, user) -> str.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

EXTRACTION_SYSTEM = """You extract stable facts about a user from their message.
Return ONLY a JSON array. Each item: {"category": str, "content": str}.
Categories: goal, preference, identity, project, skill, other.
Rules:
- Only extract stable facts (not moods, not one-off questions).
- Skip if the message contains nothing worth remembering.
- Keep content short. One fact per item.
- Return [] if nothing qualifies.
"""


def _parse_facts_json(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and "content" in d]
    except json.JSONDecodeError:
        pass
    return []


def extract_facts(
    user_message: str,
    llm_call: Callable[[str, str], str],
) -> list[dict]:
    raw = llm_call(EXTRACTION_SYSTEM, user_message)
    return _parse_facts_json(raw)


async def extract_facts_async(
    user_message: str,
    async_llm_call: Callable[[str, str], Awaitable[str]],
) -> list[dict]:
    """Async variant for production chat loops — same parser, await the call."""
    raw = await async_llm_call(EXTRACTION_SYSTEM, user_message)
    return _parse_facts_json(raw)
