"""Synthesis — distill recent feedback into PROPOSED lessons via the LLM.

v1 input is explicit feedback (the new primitive); recent thumbs-down + their
notes are the strongest learning signal. (Failures and self-correction events
are future inputs — kept out of v1 to keep the dependency surface small.)

Lessons are stored as 'proposed' only — the operator approves which ones go
active (and only active lessons inject into the prompt). Reuses the critic's
balanced-brace JSON extractor, same as planning/revision.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.learning import storage
from app.services.self_correction.critic import _extract_json_block

logger = logging.getLogger(__name__)

DEFAULT_MAX_LESSONS = 5
DEFAULT_MAX_TOKENS = 1200

_SYNTH_SYSTEM = (
    "You are KAI's learning module. You are given recent USER FEEDBACK on KAI's "
    "replies (thumbs up/down + notes). Distill it into a short list of concrete, "
    "actionable LESSONS KAI should apply going forward — the kind of guidance "
    "that would change future replies for the better. Prefer specific, "
    "behavioral rules over vague platitudes.\n"
    "\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "lessons": [\n'
    '    {"text": "one concrete, imperative lesson", "source": "feedback"}\n'
    "  ]\n"
    "}\n"
    "Produce {max_lessons} lessons or fewer. If the feedback contains nothing "
    "actionable, return an empty list. No commentary outside the JSON."
)


def synthesize_lessons(
    *, router, user_id, max_lessons: int = DEFAULT_MAX_LESSONS,
    prefer_local: bool = False, max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Pull recent feedback, ask the LLM for lessons, store them as 'proposed'.

    Returns {"proposed": [lesson dicts], "cost_usd": float, "note": str}.
    Fail-soft: router error or no feedback → empty proposal.
    """
    down = storage.list_feedback(rating="down", limit=30)
    up = storage.list_feedback(rating="up", limit=10)
    if not down and not up:
        return {"proposed": [], "cost_usd": 0.0, "note": "no feedback yet — nothing to learn"}

    user_msg = _build_user_message(down, up)
    system = _SYNTH_SYSTEM.replace("{max_lessons}", str(max_lessons))
    try:
        result = router.complete(
            user_id=user_id,
            messages=[{"role": "user", "content": user_msg}],
            system=system, max_tokens=max_tokens, temperature=0.4,
            prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("learning.synthesis: router.complete failed: %s", e)
        return {"proposed": [], "cost_usd": 0.0, "note": f"synthesis unavailable: {e}"}

    text = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    parsed = _parse_lessons(text)[:max_lessons]
    stored = [
        storage.add_lesson(p["text"], source=p.get("source", "feedback"),
                           status="proposed").as_dict()
        for p in parsed
    ]
    return {"proposed": stored, "cost_usd": cost,
            "note": f"proposed {len(stored)} lesson(s) from {len(down)} down + {len(up)} up"}


# ─── internals ──────────────────────────────────────────────────────


def _build_user_message(down: list, up: list) -> str:
    lines = ["RECENT FEEDBACK ON KAI'S REPLIES:", ""]
    if down:
        lines.append("Thumbs-DOWN (what to fix):")
        for f in down:
            lines.append(f"  - {f.note or '(no note)'}")
    if up:
        lines.append("")
        lines.append("Thumbs-UP (what's working — keep doing):")
        for f in up:
            lines.append(f"  - {f.note or '(no note)'}")
    lines.append("")
    lines.append("Return the JSON lessons.")
    return "\n".join(lines)


def _parse_lessons(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    data: Any = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        blob = _extract_json_block(cleaned)
        if not blob:
            return []
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return []
    raw = data.get("lessons") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            t = item.strip()
            if t:
                out.append({"text": t, "source": "feedback"})
        elif isinstance(item, dict):
            t = str(item.get("text") or "").strip()
            if t:
                out.append({"text": t, "source": str(item.get("source") or "feedback")})
    return out


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
