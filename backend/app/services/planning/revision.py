"""Revision — when a step fails and a plan blocks, propose a fix.

Mirrors the self-correction critic→reviser shape (diagnose, then re-generate)
as ONE structured LLM call: the model returns a short diagnosis plus a
revised step list. The result is a PROPOSAL only — it is not applied. The
operator reviews it on the dashboard and, if they like it, saves it via the
normal edit/approve path. Nothing destructive happens here.

Reuses planner.parse_steps_json (which in turn reuses the balanced-brace
extractor from self_correction.critic) so revision and planning share one
forgiving parser.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.planning import planner, storage
from app.services.self_correction.critic import _extract_json_block

logger = logging.getLogger(__name__)

DEFAULT_REVISION_MAX_TOKENS = 1500
DEFAULT_REVISION_TEMPERATURE = 0.4


_REVISION_SYSTEM = (
    "You are KAI's plan-revision module. A step in a multi-step plan just "
    "FAILED. Given the GOAL, the current STEPS (with their status), and the "
    "FAILED step plus its error, do two things:\n"
    "  1. Diagnose, in one or two sentences, why the step failed and what "
    "should change.\n"
    "  2. Propose a REVISED ordered list of steps that gets the plan back on "
    "track. You may keep, drop, reorder, or add steps. Preserve work already "
    "marked done; focus the revision on the failure and everything after it.\n"
    "\n"
    "Return ONLY a JSON object with this exact shape:\n"
    "{\n"
    '  "diagnosis": "1-2 sentences",\n'
    '  "steps": [\n'
    '    {"action": "short imperative", "kind": "chat", "tool_name": null, '
    '"on_fail": null}\n'
    "  ]\n"
    "}\n"
    "No commentary outside the JSON."
)


def propose_revision(
    plan_id: int,
    *,
    router,
    user_id,
    prefer_local: bool = False,
    max_tokens: int = DEFAULT_REVISION_MAX_TOKENS,
) -> dict[str, Any]:
    """Diagnose the most recent failure and propose revised steps.

    Returns a proposal dict (never raises for LLM problems — fail-soft):
        {
          "plan_id": int,
          "failed_step": {"seq", "action", "error"} | None,
          "diagnosis": str,
          "proposed_steps": [ {action, kind, ...} ],   # NOT applied
          "cost_usd": float,
        }
    """
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise ValueError(f"no plan with id {plan_id}")

    failed = _latest_failure(plan_id)
    failed_meta = (
        {"seq": failed[0].seq, "action": failed[0].action, "error": failed[1]}
        if failed else None
    )
    if failed is None:
        # Nothing failed — nothing to revise. Return an empty proposal rather
        # than fabricate one.
        return {
            "plan_id": plan_id,
            "failed_step": None,
            "diagnosis": "no failed step found for this plan",
            "proposed_steps": [],
            "cost_usd": 0.0,
        }

    failed_step, error = failed
    user_msg = _build_user_message(plan, failed_step, error)
    try:
        result = router.complete(
            user_id=user_id,
            messages=[{"role": "user", "content": user_msg}],
            system=_REVISION_SYSTEM,
            max_tokens=max_tokens,
            temperature=DEFAULT_REVISION_TEMPERATURE,
            prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("planning.revision: router.complete failed: %s", e)
        return {
            "plan_id": plan_id,
            "failed_step": failed_meta,
            "diagnosis": f"(revision unavailable: {e})",
            "proposed_steps": [],
            "cost_usd": 0.0,
        }

    text = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    diagnosis, proposed = _parse_revision(text)
    return {
        "plan_id": plan_id,
        "failed_step": failed_meta,
        "diagnosis": diagnosis or "(model returned no diagnosis)",
        "proposed_steps": proposed,
        "cost_usd": cost,
    }


# ─── internals ──────────────────────────────────────────────────────


def _latest_failure(plan_id: int) -> tuple[storage.Step, str] | None:
    """Find the most recent failed step + its error via the run history."""
    for run in storage.list_step_runs(plan_id):  # newest first
        if run.status == "failed":
            step = storage.get_step(run.step_id)
            if step is not None:
                return step, (run.error or "step failed")
    # Fallback: any step currently in 'failed' status (e.g. runs were cleared)
    for step in storage.get_plan(plan_id).steps:  # type: ignore[union-attr]
        if step.status == "failed":
            return step, (step.result or "step failed")
    return None


def _build_user_message(plan: storage.Plan, failed_step: storage.Step, error: str) -> str:
    lines = [f"GOAL:\n{plan.goal}\n", "CURRENT STEPS:"]
    for s in plan.steps:
        lines.append(f"  {s.seq}. [{s.status}] {s.action}")
    lines.append("")
    lines.append(f"FAILED STEP: #{failed_step.seq} {failed_step.action}")
    lines.append(f"ERROR: {error}")
    lines.append("")
    lines.append("Return the JSON revision.")
    return "\n".join(lines)


def _parse_revision(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull (diagnosis, steps) out of the model's reply. Forgiving."""
    obj = _to_object(text)
    diagnosis = str(obj.get("diagnosis") or "").strip()
    raw = obj.get("steps")
    if raw is None:
        raw = obj.get("proposed_steps")
    # Reuse the planner's normalizer by handing it an object with "steps".
    steps = (
        planner.parse_steps_json(json.dumps({"steps": raw}))
        if isinstance(raw, list) else []
    )
    return diagnosis, steps


def _to_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        blob = _extract_json_block(cleaned)
        if not blob:
            return {}
        try:
            data = json.loads(blob)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
