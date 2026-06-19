from __future__ import annotations
import json, logging, re
from typing import Any

logger = logging.getLogger(__name__)

EXEC_SYSTEM = (
    "You are KAI operating as the autonomous CEO of WheellsVerse. Your single "
    "north-star is growing NET REVENUE. Given the company goal, the latest KPI "
    "snapshot, and your org/plan status, decide what to do THIS cycle. Reply with "
    "ONLY a JSON object of the form:\n"
    '{"initiatives":[{"title":"...","rationale":"...","expected_impact":"..."}],'
    '"reprioritize":["..."],"escalations":["..."]}\n'
    "Each initiative must trace to the company goal. Keep it to the few highest-"
    "leverage moves. Do not include commentary outside the JSON."
)

_EMPTY = {"initiatives": [], "reprioritize": [], "escalations": []}


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    if not m:
        s, e = candidate.find("{"), candidate.rfind("}")
        if s == -1 or e == -1 or e < s:
            return None
        candidate = candidate[s : e + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce(obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return dict(_EMPTY)
    inits = []
    for it in obj.get("initiatives", []) or []:
        if isinstance(it, dict) and (it.get("title") or "").strip():
            inits.append({"title": str(it["title"]).strip(),
                          "rationale": str(it.get("rationale", "")).strip(),
                          "expected_impact": str(it.get("expected_impact", "")).strip()})
    repr_ = [str(x).strip() for x in (obj.get("reprioritize", []) or []) if str(x).strip()]
    esc = [str(x).strip() for x in (obj.get("escalations", []) or []) if str(x).strip()]
    return {"initiatives": inits, "reprioritize": repr_, "escalations": esc}


def decide(*, router, user_id, company: dict, snapshot: dict, org: list[dict]) -> dict[str, Any]:
    user_msg = (
        "COMPANY GOAL:\n" + json.dumps(company, default=str)
        + "\n\nKPI SNAPSHOT:\n" + json.dumps(snapshot, default=str)
        + "\n\nORG / WORKFORCE:\n" + json.dumps(org, default=str)
        + "\n\nDecide this cycle. JSON only."
    )
    try:
        result = router.complete(user_id=user_id, messages=[{"role": "user", "content": user_msg}],
                                 system=EXEC_SYSTEM, max_tokens=900, temperature=0.4)
        content = getattr(result, "content", "") or ""
    except Exception as e:
        logger.warning("ceo.brain: router failed: %s", e)
        return dict(_EMPTY)
    return _coerce(_extract_json(content))
