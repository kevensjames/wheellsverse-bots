"""Composer — format the twin profile, and suggest new entries from signals.

compose_profile() is pure (entries → grouped text), used by both injection and
draft. suggest_entries() pulls what KAI already knows about the operator (KG
facts) and asks the LLM to propose structured profile entries, stored as
'proposed' for the operator to approve. Reuses the critic JSON extractor.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.self_correction.critic import _extract_json_block
from app.services.twin import storage

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 8
DEFAULT_MAX_TOKENS = 1200


def compose_profile(entries: list[storage.Entry]) -> str:
    """Group entries by section into a compact text block. Pure (no I/O)."""
    if not entries:
        return ""
    by_section: dict[str, list[str]] = {}
    for e in entries:
        by_section.setdefault(e.section, []).append(e.text)
    lines: list[str] = []
    for section in storage.SECTIONS:  # stable, meaningful order
        items = by_section.get(section)
        if not items:
            continue
        lines.append(f"[{section}]")
        for text in items:
            lines.append(f"- {text}")
    return "\n".join(lines)


_SUGGEST_SYSTEM = (
    "You are building a structured self-model of the OPERATOR (KAI's principal) "
    "from facts KAI already knows. Propose concise profile entries, each tagged "
    "with one section: identity, voice, values, preferences, or goals.\n"
    "\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "entries": [\n'
    '    {"section": "identity", "text": "one concise fact about the operator"}\n'
    "  ]\n"
    "}\n"
    "Produce {max_entries} entries or fewer. Only include things supported by the "
    "facts provided. No commentary outside the JSON."
)


def suggest_entries(*, router, user_id, max_entries: int = DEFAULT_MAX_ENTRIES,
                    prefer_local: bool = False,
                    max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Propose profile entries from KG facts about the operator. Stores them as
    'proposed'. Fail-soft: {"proposed": [...], "cost_usd": float, "note": str}."""
    facts = _gather_operator_facts()
    if not facts:
        return {"proposed": [], "cost_usd": 0.0,
                "note": "no operator facts in the KG yet — teach KAI some first"}
    system = _SUGGEST_SYSTEM.replace("{max_entries}", str(max_entries))
    user_msg = "FACTS KAI KNOWS ABOUT THE OPERATOR:\n" + "\n".join(
        f"- {f}" for f in facts
    ) + "\n\nReturn the JSON entries."
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": user_msg}],
            system=system, max_tokens=max_tokens, temperature=0.4, prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("twin.composer: router.complete failed: %s", e)
        return {"proposed": [], "cost_usd": 0.0, "note": f"suggestion unavailable: {e}"}
    text = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    parsed = _parse_entries(text)[:max_entries]
    stored = [
        storage.add_entry(p["section"], p["text"], source="llm", status="proposed").as_dict()
        for p in parsed
    ]
    return {"proposed": stored, "cost_usd": cost, "note": f"proposed {len(stored)} entry(ies)"}


# ─── internals ──────────────────────────────────────────────────────


def _gather_operator_facts(limit: int = 30) -> list[str]:
    """Pull triples about person-type entities from the KG as raw facts."""
    try:
        from app.services.kg import find_entities, neighbors
    except Exception:
        return []
    facts: list[str] = []
    try:
        people = find_entities(type="person", limit=10)
        for person in people:
            for edge in neighbors(person.label, direction="both", limit=limit):
                facts.append(" ".join(edge.as_triple()))
            if len(facts) >= limit:
                break
    except Exception as e:
        logger.warning("twin.composer: KG read failed: %s", e)
    return facts[:limit]


def _parse_entries(text: str) -> list[dict[str, str]]:
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
    raw = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        section = str(item.get("section") or "").strip().lower()
        if not text:
            continue
        if section not in storage.SECTIONS:
            section = "identity"
        out.append({"section": section, "text": text})
    return out


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
