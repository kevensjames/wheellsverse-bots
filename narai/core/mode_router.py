"""
NarAI Dual Mode Router.
Picks Companion or Operator per turn. Fast keyword pass, LLM fallback for ambiguity.
Respects manual override and overwhelm state.

Priority stack (top to bottom):
  1. Manual override (user said "stay in operator / companion / release")
  2. Overwhelm = high → force companion (crisis state beats task routing)
  3. Fast intent score — operator if >= 0.4, companion if <= -0.3
  4. Deep pass LLM classifier for the ambiguous band in between
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

Mode = Literal["operator", "companion"]


@dataclass
class ModeDecision:
    mode: Mode
    score: float       # operator-leaning: >0 operator, <0 companion
    reason: str
    forced: bool       # True if manual override or overwhelm forced it


# ---------- Fast signals ----------

OPERATOR_SIGNALS = [
    r"\bhow (?:do|can|should) i\b",
    r"\bwrite (?:me )?(?:a|the|some)\b",
    r"\bbuild\b",
    r"\bdebug\b",
    r"\berror\b",
    r"\bcode\b",
    r"\bscript\b",
    r"\bfunction\b",
    r"\bdeploy\b",
    r"\bapi\b",
    r"\bdatabase\b",
    r"\bplan (?:for|to|the)\b",
    r"\bstrategy\b",
    r"\bsteps?\b",
    r"\bfix\b",
    r"\bgenerate\b",
    r"\bexplain how\b",
    r"\bcompare\b",
    r"\bpredict\b",
    r"```",  # code block
]

COMPANION_SIGNALS = [
    r"\bi feel\b",
    r"\bi'?m (?:tired|exhausted|frustrated|stuck|lost|sad|anxious|worried)\b",
    r"\bi don'?t know\b",
    r"\bi think i\b",
    r"\bhonestly\b",
    r"\bjust wanted to\b",
    r"\bvent\b",
    r"\btalk\b",
    r"\bmy day\b",
    r"\bsometimes i\b",
    r"\bno one\b",
    r"\bit'?s been\b.*\b(?:rough|hard|tough|a lot)\b",
]

CODE_HINTS = [r"```", r"\bdef \w+", r"\bclass \w+", r"function\s*\(", r"import\s+\w+"]


def fast_intent(text: str) -> tuple[float, list[str]]:
    """
    Return (score, matched signals).
    Score > 0 leans operator, < 0 leans companion.
    """
    t = text.lower()
    score = 0.0
    signals: list[str] = []

    for pat in OPERATOR_SIGNALS:
        if re.search(pat, t):
            score += 0.25
            signals.append(f"op:{pat}")

    for pat in COMPANION_SIGNALS:
        if re.search(pat, t):
            score -= 0.30
            signals.append(f"comp:{pat}")

    for pat in CODE_HINTS:
        if re.search(pat, text):
            score += 0.4
            signals.append(f"code:{pat}")

    # Short, no-signal messages lean companion (small talk, check-ins)
    if not signals and len(text.split()) <= 8:
        score -= 0.2
        signals.append("short_nosignal")

    return max(-1.0, min(1.0, score)), signals


# ---------- Deep classifier ----------

CLASSIFIER_SYSTEM = """You classify whether a user wants EXECUTION or CONNECTION.
Return ONLY JSON: {"mode": "operator"|"companion", "reason": "short phrase"}.
- "operator": user wants a task done, code, a plan, analysis, strategy, debugging.
- "companion": user wants to be heard, reflect, vent, process emotion, share progress casually.
Default to operator when purely informational with no emotional content.
"""


def _parse_mode_json(raw: str) -> tuple[Mode, str]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        mode = data.get("mode", "operator")
        if mode not in ("operator", "companion"):
            mode = "operator"
        return mode, data.get("reason", "")
    except json.JSONDecodeError:
        return "operator", "parse failed, defaulted operator"


def deep_intent(
    user_message: str,
    llm_call: Callable[[str, str], str],
) -> tuple[Mode, str]:
    raw = llm_call(CLASSIFIER_SYSTEM, user_message)
    return _parse_mode_json(raw)


# ---------- Router ----------

def route(
    user_message: str,
    overwhelm_level: str = "none",
    manual_override: Mode | None = None,
    llm_call: Callable[[str, str], str] | None = None,
) -> ModeDecision:
    # Rule 1: manual override always wins
    if manual_override:
        return ModeDecision(manual_override, 0.0, "manual override", forced=True)

    # Rule 2: high overwhelm forces companion
    if overwhelm_level == "high":
        return ModeDecision("companion", -1.0, "overwhelm=high forces companion", forced=True)

    # Rule 3: score-based routing
    score, signals = fast_intent(user_message)

    if score >= 0.4:
        return ModeDecision("operator", score, "strong operator signals", forced=False)
    if score <= -0.3:
        return ModeDecision("companion", score, "strong companion signals", forced=False)

    # Ambiguous zone → LLM
    if llm_call is None:
        mode: Mode = "operator" if score >= 0 else "companion"
        return ModeDecision(mode, score, "fast pass only", forced=False)

    deep_mode, deep_reason = deep_intent(user_message, llm_call)
    return ModeDecision(deep_mode, score, deep_reason, forced=False)


async def route_async(
    user_message: str,
    overwhelm_level: str = "none",
    manual_override: Mode | None = None,
    async_llm_call: Callable[[str, str], Awaitable[str]] | None = None,
) -> ModeDecision:
    """Async variant — same priority stack, awaits the deep-pass LLM."""
    if manual_override:
        return ModeDecision(manual_override, 0.0, "manual override", forced=True)

    if overwhelm_level == "high":
        return ModeDecision("companion", -1.0, "overwhelm=high forces companion", forced=True)

    score, signals = fast_intent(user_message)

    if score >= 0.4:
        return ModeDecision("operator", score, "strong operator signals", forced=False)
    if score <= -0.3:
        return ModeDecision("companion", score, "strong companion signals", forced=False)

    if async_llm_call is None:
        mode: Mode = "operator" if score >= 0 else "companion"
        return ModeDecision(mode, score, "fast pass only", forced=False)

    try:
        raw = await async_llm_call(CLASSIFIER_SYSTEM, user_message)
    except Exception:
        mode = "operator" if score >= 0 else "companion"
        return ModeDecision(mode, score, "async classifier failed", forced=False)

    mode, reason = _parse_mode_json(raw)
    return ModeDecision(mode, score, reason, forced=False)


# ---------- Mode modifiers ----------

MODE_INSTRUCTIONS = {
    "operator": (
        "Mode: OPERATOR.\n"
        "- Execute the task. Give the answer, the code, the plan.\n"
        "- Direct and technical. No check-in questions unless critical.\n"
        "- Structure output (steps, code blocks, short bullets) when it helps clarity.\n"
        "- Skip emotional framing. User wants results."
    ),
    "companion": (
        "Mode: COMPANION.\n"
        "- Listen first. Reflect what you heard in one short sentence.\n"
        "- Keep reply short — usually 2–4 sentences.\n"
        "- Ask at most one question, only if it helps the user think.\n"
        "- No code, no long plans, no lists.\n"
        "- Grounded, not performative. Don't fake warmth."
    ),
}


def modifier_for(decision: ModeDecision) -> str:
    return MODE_INSTRUCTIONS[decision.mode]


# ---------- Manual override parsing ----------

OVERRIDE_PATTERNS = {
    "operator": [
        r"\bstay in operator\b",
        r"\bswitch to operator\b",
        r"\boperator mode\b",
        r"\bjust execute\b",
    ],
    "companion": [
        r"\bstay in companion\b",
        r"\bswitch to companion\b",
        r"\bcompanion mode\b",
        r"\bjust listen\b",
    ],
    "release": [
        r"\brelease (?:the )?mode\b",
        r"\bauto mode\b",
        r"\breset mode\b",
    ],
}


def parse_override(text: str) -> Mode | Literal["release"] | None:
    t = text.lower()
    for pat in OVERRIDE_PATTERNS["release"]:
        if re.search(pat, t):
            return "release"
    for pat in OVERRIDE_PATTERNS["operator"]:
        if re.search(pat, t):
            return "operator"
    for pat in OVERRIDE_PATTERNS["companion"]:
        if re.search(pat, t):
            return "companion"
    return None
