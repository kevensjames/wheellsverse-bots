"""Synthesis — distill recent signals into PROPOSED lessons via the LLM.

v2 learns from THREE signals, not just explicit feedback:
  - feedback         — 👍/👎 + notes on KAI's replies (the v1 primitive)
  - failures         — past tool/LLM errors (failure_memory): recurring breakage
  - self_correction  — drafts KAI's own critic flagged + revised (mistakes KAI
                       tends to make, caught before the operator ever saw them)

Each proposed lesson is tagged with the source that motivated it. Lessons are
stored as 'proposed' only — the operator approves which go active (and only
active lessons inject into the prompt). Gathering each extra signal is
fail-soft: a subsystem read error degrades to "no records", never raises.
Reuses the critic's balanced-brace JSON extractor, same as planning/revision.
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

# How much of each signal to feed the synthesizer (newest-first, token-bounded).
_FEEDBACK_DOWN = 30
_FEEDBACK_UP = 10
_FAILURE_LIMIT = 25
_SELF_CORRECTION_LIMIT = 25

# Severities that count as "the critic caught a real mistake" worth a lesson.
_CORRECTION_SEVERITIES = ("major", "critical")

_VALID_SOURCES = {"feedback", "failure", "self_correction", "manual", "mixed"}

_SYNTH_SYSTEM = (
    "You are KAI's learning module. You are given recent SIGNALS about KAI's "
    "behavior from up to three sources:\n"
    "  1. FEEDBACK — the operator's thumbs up/down + notes on KAI's replies.\n"
    "  2. FAILURES — tool/LLM errors KAI hit (recurring breakage to avoid).\n"
    "  3. SELF-CORRECTION — drafts KAI's own critic flagged and revised "
    "(mistakes KAI tends to make).\n"
    "\n"
    "Distill these into a short list of concrete, actionable LESSONS KAI should "
    "apply going forward — the kind of guidance that would change future "
    "behavior for the better. Prefer specific, behavioral rules over vague "
    "platitudes. Tag each lesson with the source that motivated it.\n"
    "\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "lessons": [\n'
    '    {"text": "one concrete, imperative lesson", '
    '"source": "feedback|failure|self_correction|mixed"}\n'
    "  ]\n"
    "}\n"
    "Produce {max_lessons} lessons or fewer. If the signals contain nothing "
    "actionable, return an empty list. No commentary outside the JSON."
)


def synthesize_lessons(
    *, router, user_id, max_lessons: int = DEFAULT_MAX_LESSONS,
    prefer_local: bool = False, max_tokens: int = DEFAULT_MAX_TOKENS,
    include_failures: bool = True, include_self_correction: bool = True,
) -> dict[str, Any]:
    """Pull recent signals, ask the LLM for lessons, store them as 'proposed'.

    Signals: explicit feedback (always) + tool/LLM failures + self-correction
    events (both on by default; toggle off per call). Returns
    {"proposed": [lesson dicts], "cost_usd": float, "note": str}.
    Fail-soft: router error or no signals → empty proposal.
    """
    down = storage.list_feedback(rating="down", limit=_FEEDBACK_DOWN)
    up = storage.list_feedback(rating="up", limit=_FEEDBACK_UP)
    failures = _gather_failures() if include_failures else []
    corrections = _gather_self_correction() if include_self_correction else []

    if not (down or up or failures or corrections):
        return {"proposed": [], "cost_usd": 0.0,
                "note": "no signals yet — nothing to learn"}

    user_msg = _build_user_message(down, up, failures, corrections)
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
        storage.add_lesson(p["text"], source=p["source"], status="proposed").as_dict()
        for p in parsed
    ]
    note = (
        f"proposed {len(stored)} lesson(s) from {len(down)}↓+{len(up)}↑ feedback, "
        f"{len(failures)} failure(s), {len(corrections)} self-correction(s)"
    )
    return {"proposed": stored, "cost_usd": cost, "note": note}


# ─── signal gathering (each fail-soft) ───────────────────────────────


def _gather_failures(limit: int = _FAILURE_LIMIT) -> list[dict[str, Any]]:
    """Recent tool/LLM failures, compacted to (category, tool/adapter, detail).
    A read error degrades to an empty list — never raises."""
    try:
        from app.services import failure_memory
        out: list[dict[str, Any]] = []
        for f in failure_memory.list_recent(limit=limit):
            out.append({
                "category": f.category,
                "tool": f.tool_name or f.adapter or "",
                "detail": f.detail,
            })
        return out
    except Exception as e:
        logger.warning("learning.synthesis: gather failures failed: %s", e)
        return []


def _gather_self_correction(limit: int = _SELF_CORRECTION_LIMIT) -> list[dict[str, Any]]:
    """Recent self-correction events that NEEDED a fix (was_revised or
    major/critical severity) — those are the mistakes worth a lesson. The
    'ok/minor' cheap-path events carry no signal, so we drop them."""
    try:
        from app.services.self_correction import loop as sc_loop
        out: list[dict[str, Any]] = []
        for ev in sc_loop.list_events(limit=limit):
            sev = (ev.get("final_severity") or "none").lower()
            if not (ev.get("was_revised") or sev in _CORRECTION_SEVERITIES):
                continue
            verdicts = ev.get("verdicts") or []
            critique = verdicts[-1].get("critique") if verdicts else ""
            out.append({
                "user_message": ev.get("user_message", ""),
                "severity": sev,
                "critique": critique or "",
            })
        return out
    except Exception as e:
        logger.warning("learning.synthesis: gather self-correction failed: %s", e)
        return []


# ─── internals ──────────────────────────────────────────────────────


def _build_user_message(down: list, up: list, failures: list, corrections: list) -> str:
    lines: list[str] = []
    if down or up:
        lines.append("=== FEEDBACK ON KAI'S REPLIES ===")
        if down:
            lines.append("Thumbs-DOWN (what to fix):")
            for f in down:
                lines.append(f"  - {f.note or '(no note)'}")
        if up:
            lines.append("Thumbs-UP (what's working — keep doing):")
            for f in up:
                lines.append(f"  - {f.note or '(no note)'}")
        lines.append("")
    if failures:
        lines.append("=== RECENT FAILURES (avoid repeating) ===")
        for x in failures:
            tool = f" [{x['tool']}]" if x["tool"] else ""
            lines.append(f"  - ({x['category']}{tool}) {x['detail'] or '(no detail)'}")
        lines.append("")
    if corrections:
        lines.append("=== SELF-CORRECTION (mistakes the critic caught + fixed) ===")
        for x in corrections:
            lines.append(
                f"  - on \"{x['user_message']}\" [{x['severity']}]: "
                f"{x['critique'] or '(no critique)'}"
            )
        lines.append("")
    lines.append("Return the JSON lessons, tagging each with its source.")
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
                out.append({"text": t, "source": "mixed"})
        elif isinstance(item, dict):
            t = str(item.get("text") or "").strip()
            if t:
                out.append({"text": t, "source": _norm_source(item.get("source"))})
    return out


def _norm_source(raw: Any) -> str:
    """Trust the model's source tag only if it's one we recognize; otherwise
    'mixed' (v2 has multiple inputs, so 'mixed' is the safe default)."""
    s = str(raw or "").strip().lower()
    return s if s in _VALID_SOURCES else "mixed"


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
