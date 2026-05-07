"""
NarAI Patterns — Step 6 (proactive context) + Step 7 (behavioral learning).

Step 6: get_proactive_context() reads mined patterns from the patterns table
        and returns a brief system prompt modifier for the current turn.
        Called on every chat turn — fast SQL read, no LLM.

Step 7: mine_patterns_async() analyzes the episode stream, extracts behavioral
        patterns via statistics + one cheap LLM call, and writes them to the
        patterns SQLite table. Triggered as a background task every N turns.
        Never raises — failures are logged so chat is never blocked.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from infra.brain.interface import MemoryStore

logger = logging.getLogger("narai.patterns")

MIN_EPISODES = 10
_LLMCall = Callable[[str, str], Awaitable[str]]

_LLM_SYSTEM = (
    "You analyze NarAI conversation episode summaries and identify behavioral patterns. "
    "Each episode has the format: [mode=X overwhelm=Y] User: <msg>\\nNarAI: <reply>\\n\\n"
    "Return a JSON array (max 3 items). Each item must be:\n"
    '{"pattern_type": "temporal|topic|interaction|outcome", '
    '"description": "<one concise sentence>", '
    '"observations_count": <integer>}\n'
    "Focus only on clear, recurring patterns visible in the data. "
    "If none are clear, return []."
)


# ── Step 6: Proactive Context ─────────────────────────────────────────────────

def get_proactive_context(user_id: str, store: "MemoryStore") -> str:
    """Read mined patterns and return a system prompt modifier string.

    Returns empty string before any patterns are mined — safe to call always.
    """
    try:
        patterns = store.get_patterns(user_id, limit=3)
    except Exception as e:
        logger.warning(f"get_patterns failed (non-fatal): {e}")
        return ""
    if not patterns:
        return ""
    lines = ["Behavioral patterns detected (adjust your style accordingly):"]
    for p in patterns:
        lines.append(f"- {p.description}")
    return "\n".join(lines)


# ── Step 7: Pattern Mining ────────────────────────────────────────────────────

async def mine_patterns_async(
    user_id: str,
    store: "MemoryStore",
    async_llm_call: _LLMCall,
) -> None:
    """Mine the episode stream and write discovered patterns to the patterns table.

    Triggered as a background task every MINE_EVERY_N_TURNS turns from chat.py.
    """
    try:
        episodes = store.get_recent_episodes_raw(user_id, limit=100)
        if len(episodes) < MIN_EPISODES:
            logger.info(
                f"pattern mining skipped: only {len(episodes)} episodes "
                f"(need {MIN_EPISODES})"
            )
            return

        stat_patterns = _extract_stat_patterns(episodes)
        llm_patterns = await _extract_llm_patterns(episodes[:20], async_llm_call)

        all_patterns = stat_patterns + llm_patterns
        for p in all_patterns:
            store.upsert_pattern(
                user_id=user_id,
                pattern_type=p.get("pattern_type", "interaction"),
                description=p["description"],
                observations_count=p.get("observations_count", 1),
            )

        logger.info(
            f"pattern mining complete for {user_id!r}: "
            f"{len(stat_patterns)} statistical + {len(llm_patterns)} LLM patterns"
        )
    except Exception as e:
        logger.warning(f"pattern mining failed (non-fatal): {e}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_stat_patterns(episodes: list[dict]) -> list[dict]:
    """Pure-Python statistical analysis of tagged episodes. No LLM needed."""
    overwhelm_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()

    for ep in episodes:
        m = re.match(r"\[mode=(\w+)\s+overwhelm=(\w+)\]", ep.get("content", ""))
        if m:
            mode_counts[m.group(1)] += 1
            overwhelm_counts[m.group(2)] += 1

    total = len(episodes)
    if total == 0:
        return []

    patterns: list[dict] = []

    high_count = overwhelm_counts.get("high", 0)
    high_pct = high_count / total * 100
    if high_pct >= 30:
        patterns.append({
            "pattern_type": "interaction",
            "description": (
                f"User enters high-overwhelm state in {high_pct:.0f}% of turns — "
                "prefer shorter replies and single-task focus"
            ),
            "observations_count": high_count,
        })

    companion_count = mode_counts.get("companion", 0)
    companion_pct = companion_count / total * 100
    if companion_pct >= 60:
        patterns.append({
            "pattern_type": "interaction",
            "description": (
                f"User frequently routes to companion mode ({companion_pct:.0f}%) — "
                "lean toward listening-first, low-list responses"
            ),
            "observations_count": companion_count,
        })

    return patterns


async def _extract_llm_patterns(
    recent_episodes: list[dict],
    async_llm_call: _LLMCall,
) -> list[dict]:
    """Ask the LLM to spot nuanced behavioral patterns in the recent episode window."""
    episode_text = "\n---\n".join(
        ep["content"][:300] for ep in recent_episodes
    )
    user_prompt = f"Episodes:\n{episode_text}\n\nIdentify recurring behavioral patterns."

    try:
        raw = await async_llm_call(_LLM_SYSTEM, user_prompt)
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        parsed = json.loads(raw[start:end])
        if not isinstance(parsed, list):
            return []
        return [
            p for p in parsed
            if isinstance(p, dict) and "description" in p
        ]
    except Exception as e:
        logger.warning(f"LLM pattern extraction failed (non-fatal): {e}")
        return []
