"""Agent router (the "super-router") — classify a question to the best domain
expert preset, so KAI can auto-pick the right specialist instead of the operator
choosing from the dropdown.

LLM classifier over the shipped preset catalog (id + description), at temperature
0. Fail-soft: empty question / router error / unparseable reply → preset_id None
(= bare KAI, general chat). Reuses the critic's balanced-brace JSON extractor.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.presets import list_presets
from app.services.self_correction.critic import _extract_json_block

logger = logging.getLogger(__name__)

_CONF = ("high", "medium", "low")

_ROUTER_SYSTEM = (
    "You are KAI's agent router. Given a user's QUESTION, pick the single best "
    "expert agent to handle it from this catalog:\n"
    "{catalog}\n"
    "\n"
    "Return ONLY a JSON object:\n"
    '{"preset_id": "<one id from the catalog, or null>", '
    '"confidence": "high|medium|low", "reason": "short justification"}\n'
    "Choose the MOST SPECIFIC matching domain. Use null only when no agent "
    "clearly fits (ordinary general-purpose chat). No commentary outside the JSON."
)


def classify_domain(*, router, user_id, question: str, prefer_local: bool = False) -> dict[str, Any]:
    """Return {"preset_id": str|None, "confidence", "reason", "cost_usd"}."""
    question = (question or "").strip()
    if not question:
        return {"preset_id": None, "confidence": "low", "reason": "empty question", "cost_usd": 0.0}

    presets = list_presets()
    valid_ids = {p.id for p in presets}
    catalog = "\n".join(f"- {p.id}: {p.description}" for p in presets)
    system = _ROUTER_SYSTEM.replace("{catalog}", catalog)
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": question}],
            system=system, max_tokens=200, temperature=0.0, prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("agent_router: router.complete failed: %s", e)
        return {"preset_id": None, "confidence": "low", "reason": f"router unavailable: {e}", "cost_usd": 0.0}

    parsed = _parse((getattr(result, "content", "") or ""), valid_ids)
    parsed["cost_usd"] = _result_cost(result)
    return parsed


# ─── internals ──────────────────────────────────────────────────────


def _parse(text: str, valid_ids: set[str]) -> dict[str, Any]:
    data = _extract(text)
    if not isinstance(data, dict):
        return {"preset_id": None, "confidence": "low", "reason": "router returned no parseable choice"}
    pid = data.get("preset_id")
    pid = str(pid).strip() if pid not in (None, "", "null") else None
    if pid is not None and pid not in valid_ids:
        pid = None  # hallucinated id → no preset
    conf = str(data.get("confidence") or "").strip().lower()
    if conf not in _CONF:
        conf = "low"
    if pid is None:
        conf = "low"
    return {"preset_id": pid, "confidence": conf, "reason": str(data.get("reason") or "").strip()}


def _extract(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        blob = _extract_json_block(cleaned)
        if not blob:
            return None
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return None


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
