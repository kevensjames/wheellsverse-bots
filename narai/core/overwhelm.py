"""
NarAI Overwhelm Engine.
Two-pass detector: fast keyword scoring, then LLM classifier for ambiguous cases.
Produces an OverwhelmState that modifies the system prompt for one turn.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Literal

Level = Literal["none", "mild", "high"]


@dataclass
class OverwhelmState:
    level: Level
    score: float  # 0.0 - 1.0
    reason: str
    signals: list[str]


# ---------- Fast pass ----------

HIGH_SIGNALS = [
    # "can't keep going", "can't do this", "cannot handle" — phrase-anchored so
    # "can't find the file" type tech usages don't trip it.
    r"\b(?:can'?t|cannot) (?:do this|keep going|handle (?:it|this)|take it|cope|anymore)\b",
    r"\btoo much\b",
    r"\btoo many\b",
    # "lost" and "stuck" have innocent uses (e.g. "I got stuck on this query") —
    # keep the "i'm" anchor for those two.
    r"\bi'?m (?:lost|stuck)\b",
    # "drowning", "exhausted", "burnt/burned out" — unambiguous, no anchor needed.
    r"\b(?:drowning|exhausted|burnt out|burned out)\b",
    r"\bgiving up\b",
    r"\bi don'?t know (?:what to do|where to start|anymore)\b",
    r"\beverything is\b.*\b(?:falling apart|broken|wrong)\b",
    r"\bovewhelm(?:ed|ing)\b",  # typo catch
    r"\boverwhelm(?:ed|ing)\b",
    r"\bno idea\b.*\b(?:where|how) to\b",
]

MILD_SIGNALS = [
    r"\bnot sure\b",
    r"\ba lot\b",
    r"\bhard to\b",
    r"\bstruggl(?:e|ing)\b",
    r"\btired\b",
    r"\bstress(?:ed)?\b",
    r"\bconfus(?:ed|ing)\b",
    r"\bwhere (?:do|should) i (?:start|begin)\b",
    r"\bbehind\b",
]

STRUCTURAL_SIGNALS = {
    "many_questions": lambda t: t.count("?") >= 3,
    "fragmented": lambda t: len([s for s in re.split(r"[.!?]", t) if s.strip()]) >= 6 and len(t) < 400,
    "all_caps_burst": lambda t: sum(1 for w in t.split() if len(w) > 2 and w.isupper()) >= 3,
    "ellipsis_chain": lambda t: t.count("...") >= 2,
}


def fast_score(text: str) -> tuple[float, list[str]]:
    """Return (score 0-1, list of matched signal names)."""
    t = text.lower()
    signals: list[str] = []
    score = 0.0

    for pat in HIGH_SIGNALS:
        if re.search(pat, t):
            signals.append(f"high:{pat}")
            score += 0.45

    for pat in MILD_SIGNALS:
        if re.search(pat, t):
            signals.append(f"mild:{pat}")
            score += 0.15

    for name, fn in STRUCTURAL_SIGNALS.items():
        if fn(text):
            signals.append(f"struct:{name}")
            score += 0.2

    return min(score, 1.0), signals


# ---------- Deep pass ----------

CLASSIFIER_SYSTEM = """You classify whether a user is overwhelmed.
Return ONLY JSON: {"level": "none"|"mild"|"high", "reason": "short phrase"}.
Rules:
- "high": user expresses inability to cope, feels stuck/lost/burnt out, or can't prioritize.
- "mild": user is stressed or confused but still functional.
- "none": user is focused, curious, or neutral.
Be strict. Do not invent distress that isn't there.
"""


def deep_classify(
    user_message: str,
    llm_call: Callable[[str, str], str],
) -> tuple[Level, str]:
    raw = llm_call(CLASSIFIER_SYSTEM, user_message).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
        lvl = data.get("level", "none")
        if lvl not in ("none", "mild", "high"):
            lvl = "none"
        return lvl, data.get("reason", "")
    except json.JSONDecodeError:
        return "none", "classifier parse failed"


# ---------- Public detector ----------

def detect(
    user_message: str,
    llm_call: Callable[[str, str], str] | None = None,
) -> OverwhelmState:
    """
    Two-pass detection.
    - score >= 0.6 → high (skip deep pass)
    - score < 0.15 → none (skip deep pass)
    - 0.15 <= score < 0.6 → deep pass decides (at exactly 0.15, a single MILD
      hit, the LLM classifier owns the call instead of defaulting to none)
    """
    score, signals = fast_score(user_message)

    if score >= 0.6:
        return OverwhelmState("high", score, "strong overwhelm signals", signals)
    if score < 0.15:
        return OverwhelmState("none", score, "no signals", signals)

    # Ambiguous zone
    if llm_call is None:
        lvl: Level = "mild" if score >= 0.3 else "none"
        return OverwhelmState(lvl, score, "fast pass only", signals)

    deep_lvl, deep_reason = deep_classify(user_message, llm_call)
    return OverwhelmState(deep_lvl, score, deep_reason, signals)


# ---------- Prompt modifier ----------

OVERWHELM_INSTRUCTIONS = {
    "none": "",
    "mild": (
        "The user shows signs of stress or confusion. "
        "Keep the reply short. Offer one clear next step before anything else. "
        "Don't stack options. Don't lecture."
    ),
    "high": (
        "The user is overwhelmed. Override your normal style:\n"
        "- Start by naming it in one sentence (not dramatic, just grounded).\n"
        "- Give ONE task. Not two. Not a list.\n"
        "- Explicitly tell them to ignore everything else for now.\n"
        "- Keep total reply under 5 short sentences.\n"
        "- No motivation speech. No 'you've got this.'"
    ),
}


def modifier_for(state: OverwhelmState) -> str:
    return OVERWHELM_INSTRUCTIONS[state.level]


# ---------- Async helper for production chat loops ----------

async def detect_async(
    user_message: str,
    async_llm_call: Callable | None = None,
) -> OverwhelmState:
    """Async variant — same two-pass logic, await the deep-pass LLM.

    async_llm_call signature: (system: str, user: str) -> Awaitable[str]
    """
    score, signals = fast_score(user_message)

    if score >= 0.6:
        return OverwhelmState("high", score, "strong overwhelm signals", signals)
    if score < 0.15:
        return OverwhelmState("none", score, "no signals", signals)

    if async_llm_call is None:
        lvl: Level = "mild" if score >= 0.3 else "none"
        return OverwhelmState(lvl, score, "fast pass only", signals)

    try:
        raw = (await async_llm_call(CLASSIFIER_SYSTEM, user_message)).strip()
    except Exception:
        lvl = "mild" if score >= 0.3 else "none"
        return OverwhelmState(lvl, score, "async classifier failed", signals)

    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
        lvl = data.get("level", "none")
        if lvl not in ("none", "mild", "high"):
            lvl = "none"
        return OverwhelmState(lvl, score, data.get("reason", ""), signals)
    except json.JSONDecodeError:
        return OverwhelmState("none", score, "classifier parse failed", signals)
