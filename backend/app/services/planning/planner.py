"""Planner — decompose a goal into an ordered list of steps via the LLM.

Different from the executor: the planner runs ONCE per goal to propose a
draft plan. The operator then edits/approves before any step executes.

The model is asked to return a JSON object ``{"steps": [...]}``. Parsing is
forgiving (strips ```fences, falls back to the balanced-brace extractor
reused from self_correction.critic) so a slightly-chatty model doesn't
break plan creation. On any failure we return an EMPTY step list rather
than raising — the operator gets a draft plan with zero steps they can
fill in by hand, which is more useful than a 502.
"""
from __future__ import annotations

import json
import logging
from typing import Any

# Reuse the robust balanced-brace JSON extractor from the self-correction
# critic (handles nested braces + prose-wrapped objects).
from app.services.self_correction.critic import _extract_json_block
from app.services.planning import storage

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 15
DEFAULT_PLANNER_MAX_TOKENS = 1500
DEFAULT_PLANNER_TEMPERATURE = 0.4


_PLANNER_SYSTEM = (
    "You are KAI's planning module. Given a GOAL, break it into an ordered "
    "list of concrete, actionable steps (typically 5-15). Each step is one "
    "discrete action that can be executed and verified on its own.\n"
    "\n"
    "Return ONLY a JSON object with this exact shape:\n"
    "{\n"
    '  "steps": [\n'
    '    {"action": "short imperative description", "kind": "chat", '
    '"tool_name": null, "on_fail": null}\n'
    "  ]\n"
    "}\n"
    "\n"
    "Rules:\n"
    '  - "kind": "chat" for a reasoning/writing/decision step KAI performs '
    'itself; "tool" if the step should invoke a named tool (then set '
    '"tool_name", e.g. "kg_query", "web_fetch").\n'
    '  - "on_fail": optional branch directive. null (default) = if this step '
    'fails, block the plan for operator review. "goto:N" = jump to step N. '
    '"stop" = end the plan.\n'
    "  - Keep steps concrete, ordered, and free of commentary outside the JSON.\n"
    "  - Produce {max_steps} steps or fewer."
)


def parse_steps_json(text: str) -> list[dict[str, Any]]:
    """Forgiving parse of a planner reply into a list of normalized step dicts.

    Accepts: a clean JSON object ``{"steps": [...]}``, a bare JSON array,
    a ```json-fenced``` block, or an object embedded in prose. Returns [] if
    nothing parseable is found.
    """
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip a leading ```json / ``` fence and trailing ```
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()

    data: Any = None
    # 1) try the whole thing (covers clean object AND bare array)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 2) fall back to extracting the first balanced {...} object from prose
        blob = _extract_json_block(cleaned)
        if blob:
            try:
                data = json.loads(blob)
            except json.JSONDecodeError as e:
                logger.warning("planner: JSON parse failed: %s", e)
                return []
        else:
            logger.warning("planner: no JSON object/array found in reply")
            return []

    if isinstance(data, dict):
        raw_steps = data.get("steps", [])
    elif isinstance(data, list):
        raw_steps = data
    else:
        return []
    if not isinstance(raw_steps, list):
        return []

    return [s for s in (_normalize_step(r) for r in raw_steps) if s is not None]


def propose_steps(
    goal: str,
    *,
    router,
    user_id,
    max_steps: int = DEFAULT_MAX_STEPS,
    prefer_local: bool = False,
    max_tokens: int = DEFAULT_PLANNER_MAX_TOKENS,
) -> tuple[list[dict[str, Any]], float]:
    """Ask the LLM to decompose ``goal`` into steps. Returns (steps, cost_usd).

    Fail-soft: on router error or unparseable reply, returns ([], 0.0).
    """
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal cannot be empty")
    # NB: use .replace() not .format() — the template is full of literal JSON
    # braces that .format() would treat as (empty) field names.
    system = _PLANNER_SYSTEM.replace("{max_steps}", str(max_steps))
    msgs = [{"role": "user", "content": f"GOAL:\n{goal}\n\nReturn the JSON plan."}]
    try:
        result = router.complete(
            user_id=user_id,
            messages=msgs,
            system=system,
            max_tokens=max_tokens,
            temperature=DEFAULT_PLANNER_TEMPERATURE,
            prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("planner: router.complete failed: %s", e)
        return [], 0.0
    text = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    steps = parse_steps_json(text)
    return steps[:max_steps], cost


def generate_plan(
    goal: str,
    *,
    router,
    user_id,
    title: str | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    prefer_local: bool = False,
    meta: dict[str, Any] | None = None,
) -> tuple[storage.Plan, float]:
    """Propose steps and persist a DRAFT plan. Returns (Plan, cost_usd).

    The plan always exists even if step generation produced nothing — the
    operator can then add steps by hand. Status is 'draft' until approved.
    """
    steps, cost = propose_steps(
        goal, router=router, user_id=user_id,
        max_steps=max_steps, prefer_local=prefer_local,
    )
    plan = storage.create_plan(
        title or _title_from_goal(goal),
        goal,
        status="draft",
        meta={**(meta or {}), "proposal_cost_usd": round(cost, 6)},
    )
    if steps:
        storage.replace_steps(plan.id, steps)
    full = storage.get_plan(plan.id)
    assert full is not None
    return full, cost


# ─── internals ──────────────────────────────────────────────────────


def _normalize_step(raw: Any) -> dict[str, Any] | None:
    """Coerce a raw step (dict, or a bare string) into the storage shape.
    Returns None for unusable rows."""
    if isinstance(raw, str):
        action = raw.strip()
        return {"action": action, "kind": "chat"} if action else None
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or raw.get("description") or "").strip()
    if not action:
        return None
    kind = str(raw.get("kind") or "chat").strip().lower()
    if kind not in storage.STEP_KINDS:
        kind = "chat"
    out: dict[str, Any] = {"action": action, "kind": kind}
    tool_name = raw.get("tool_name")
    if tool_name:
        out["tool_name"] = str(tool_name).strip()
    on_fail = raw.get("on_fail")
    if on_fail not in (None, "", "null"):
        out["on_fail"] = str(on_fail).strip()
    on_done = raw.get("on_done")
    if on_done not in (None, "", "null"):
        out["on_done"] = str(on_done).strip()
    return out


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _title_from_goal(goal: str) -> str:
    """Cheap title: first line, trimmed to ~70 chars."""
    first = (goal or "").strip().splitlines()[0] if goal.strip() else "Untitled plan"
    return first[:70].strip() or "Untitled plan"
