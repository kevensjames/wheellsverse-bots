from __future__ import annotations
import logging
from typing import Any
from . import store, floor

logger = logging.getLogger(__name__)


def apply(decision_set: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    created: list[int] = []
    queued: list[dict[str, Any]] = []
    decisions = 0

    for init in decision_set.get("initiatives", []):
        title = (init.get("title") or "").strip()
        if not title:
            continue
        # Initiatives are chat/assignment work → in_policy unless they declare a
        # catastrophic kind or a spend amount. The floor re-derives this; the
        # brain's opinion is never trusted.
        action = {"type": "initiative", "kind": init.get("kind", "assignment"),
                  "amount": float(init.get("amount", 0) or 0)}
        verdict = floor.classify(action)
        rationale = (init.get("rationale") or "") + (
            f" | expected: {init.get('expected_impact')}" if init.get("expected_impact") else "")
        if verdict != "in_policy":
            store.record_decision("escalation", f"{title}: {rationale}",
                                  is_catastrophic=(verdict == "catastrophic"))
            queued.append({"title": title, "verdict": verdict})
            decisions += 1
            continue
        if dry_run:
            store.record_decision("new_initiative", f"[dry-run] {title}: {rationale}")
            decisions += 1
            continue
        try:
            from app.services.planning import storage as pl
            plan = pl.create_plan(title[:120], f"{title}. {rationale}".strip(), status="draft",
                                  meta={"source": "ceo", "expected_impact": init.get("expected_impact", "")})
            store.record_decision("new_initiative", f"{title}: {rationale}", linked_plan_id=plan.id)
            created.append(plan.id)
            decisions += 1
        except Exception as e:
            logger.warning("ceo.executor: create_plan failed for %r: %s", title, e)
            store.record_decision("new_initiative", f"FAILED {title}: {e}", outcome="error")
            decisions += 1

    for note in decision_set.get("reprioritize", []):
        store.record_decision("reprioritize", str(note))
        decisions += 1
    for esc in decision_set.get("escalations", []):
        store.record_decision("escalation", str(esc))
        decisions += 1

    return {"created": created, "queued": queued, "decisions": decisions}
