"""Decide-as-operator — predict the decision the OPERATOR would most likely make,
grounded in the twin self-model.

STRICTLY ADVISORY. This returns a *prediction* (decision + rationale + confidence
+ caveats) for the operator to consider. It NEVER executes, sends, posts, or
authorizes anything — it is KAI reasoning about what its principal would probably
choose, not KAI acting as the principal. The output is text; no tool runs as a
result of it.

Mirrors draft.py (active profile as the model, fail-soft). Each prediction is
logged to data/twin/decisions.jsonl so the operator can later calibrate how well
KAI predicts them (and so there's a record of every "what would I decide" call).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.self_correction.critic import _extract_json_block
from app.services.twin import composer, storage

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
DECIDE_LOG_PATH = Path(
    os.environ.get("KAI_TWIN_DECIDE_LOG_PATH", str(_REPO_ROOT / "data" / "twin" / "decisions.jsonl"))
)
DECIDE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_TOKENS = 900
_CONFIDENCES = ("low", "medium", "high")

_DECIDE_SYSTEM = (
    "You are predicting what the OPERATOR (your principal) would most likely "
    "DECIDE about the question below, reasoning from their self-model (identity, "
    "values, preferences, goals).\n"
    "\n"
    "This is ADVISORY ONLY. You are predicting their choice for THEM to consider "
    "— you are NOT deciding for them, and NOTHING is executed, sent, or authorized "
    "based on your answer. Be honest about uncertainty: if the profile doesn't "
    "support a confident call, say so (low confidence) and name what you'd need.\n"
    "\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "decision": "the choice you predict the operator would make",\n'
    '  "rationale": "why — grounded in their profile",\n'
    '  "confidence": "low|medium|high",\n'
    '  "caveats": ["what could change this, or what you are unsure about"]\n'
    "}\n"
    "No commentary outside the JSON.\n"
    "\n"
    "OPERATOR PROFILE:\n{profile}"
)


def decide_as_operator(
    *, router, user_id, question: str, options: list[str] | None = None,
    context: str = "", prefer_local: bool = False, max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Predict the operator's decision for `question`. Advisory only — logs +
    returns {"decision", "rationale", "confidence", "caveats", "cost_usd",
    "advisory", "note"}. Fail-soft on router error."""
    question = (question or "").strip()
    if not question:
        raise ValueError("question cannot be empty")
    active = storage.list_entries(status="active")
    profile = composer.compose_profile(active) or (
        "(no profile entries yet — predict cautiously and flag low confidence)"
    )
    system = _DECIDE_SYSTEM.replace("{profile}", profile)
    user_msg = _build_user_message(question, options, context)
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": user_msg}],
            system=system, max_tokens=max_tokens, temperature=0.4, prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("twin.decide: router.complete failed: %s", e)
        return {"decision": "", "rationale": "", "confidence": "low", "caveats": [],
                "cost_usd": 0.0, "advisory": True, "note": f"decision unavailable: {e}"}
    text = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    parsed = _parse_decision(text)
    _log(question, parsed, cost)
    return {**parsed, "cost_usd": cost, "advisory": True,
            "note": f"ADVISORY prediction (not executed) from {len(active)} profile entry(ies)"}


def list_decisions(limit: int = 50) -> list[dict[str, Any]]:
    if not DECIDE_LOG_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in reversed(DECIDE_LOG_PATH.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= max(1, min(int(limit), 200)):
                break
    except Exception:
        return out
    return out


# ─── internals ──────────────────────────────────────────────────────


def _build_user_message(question: str, options: list[str] | None, context: str) -> str:
    lines = [f"DECISION TO MAKE:\n{question}"]
    if options:
        lines.append("\nOPTIONS:")
        for i, o in enumerate(options, 1):
            lines.append(f"  {i}. {o}")
    if context and context.strip():
        lines.append(f"\nCONTEXT:\n{context.strip()}")
    lines.append("\nReturn the JSON decision.")
    return "\n".join(lines)


def _parse_decision(text: str) -> dict[str, Any]:
    empty = {"decision": "", "rationale": "", "confidence": "low",
             "caveats": ["model returned no output"]}
    if not text:
        return empty
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
        if blob:
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        # Unstructured reply — keep it as rationale rather than lose it.
        return {"decision": "(see rationale)", "rationale": text.strip(),
                "confidence": "low", "caveats": ["model did not return structured JSON"]}
    decision = str(data.get("decision") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    conf = str(data.get("confidence") or "").strip().lower()
    if conf not in _CONFIDENCES:
        conf = "low"
    raw_caveats = data.get("caveats")
    if isinstance(raw_caveats, list):
        caveats = [str(c).strip() for c in raw_caveats if str(c).strip()]
    elif raw_caveats:
        caveats = [str(raw_caveats).strip()]
    else:
        caveats = []
    if not decision and rationale:
        decision = "(see rationale)"
    if not decision and not rationale:
        return empty
    return {"decision": decision, "rationale": rationale, "confidence": conf, "caveats": caveats}


def _log(question: str, parsed: dict[str, Any], cost: float) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "question": question,
           "decision": parsed.get("decision", ""), "confidence": parsed.get("confidence", ""),
           "cost_usd": cost, "advisory": True}
    try:
        with DECIDE_LOG_PATH.open("a") as fp:
            fp.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:  # pragma: no cover
        logger.warning("twin.decide: log write failed: %s", e)


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
