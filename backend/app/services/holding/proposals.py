"""Proposal Engine (Wave 2) — turn a source-backed priority into a concrete PROPOSED action + plan.

KAI DRAFTS; it never executes. Every proposal here is a read-only / investigative action
(INVESTIGATE · VERIFY · REQUEST_INFO · REVIEW) built from a DETERMINISTIC template keyed by the
priority — no fabrication, no consequential action. Consequential proposals (write / money / deploy)
are a separate, more-gated type introduced only alongside the execution wave. The operator approves
or rejects; a decision is RECORDED and audited — executing an approved proposal is Wave 3, separate.
"""
from __future__ import annotations

INVESTIGATE, VERIFY, REQUEST_INFO, REVIEW = "INVESTIGATE", "VERIFY", "REQUEST_INFO", "REVIEW"
_OPEN = "proposed"


def _template(priority: dict) -> dict:
    """priority -> {action_class, proposed_action, plan[], risk, reversible}. Read-only actions only."""
    src = priority.get("source", "") or ""
    title = priority.get("title", "") or ""
    ent = priority.get("entity") or "the entity"
    if ".risks" in src:
        return {"action_class": INVESTIGATE, "risk": "low", "reversible": True,
                "proposed_action": f"Investigate and confirm remediation of the logged risk on {ent}.",
                "plan": [f"Pull {ent}'s repo + recent PRs (read-only GitHub worker) to confirm the fix landed",
                         "Verify the vulnerability is closed with no regression",
                         "If confirmed, propose clearing the risk from the registry; else escalate"]}
    if ".confidence" in src:
        return {"action_class": VERIFY, "risk": "low", "reversible": True,
                "proposed_action": f"Re-verify {ent} to move it off UNVERIFIED.",
                "plan": [f"Probe {ent}'s live endpoints / in-process status",
                         f"Check {ent}'s repo + CI health (read-only GitHub worker)",
                         "Update the registry confidence with cited evidence"]}
    if src.startswith("live-signal") or ":live" in src or "health" in title.lower() or "DOWN" in title:
        return {"action_class": INVESTIGATE, "risk": "low", "reversible": True,
                "proposed_action": f"Investigate the live-signal issue: {title}.",
                "plan": ["Pull the failing endpoint's health detail + recent deploys",
                         "Determine if it is a transient blip or a real outage",
                         "If real, prepare an escalation summary for approval"]}
    if "needs_confirmation" in src or title.startswith("Confirm"):
        return {"action_class": REQUEST_INFO, "risk": "none", "reversible": True,
                "proposed_action": "Request the operator confirm the pending holding-data fields.",
                "plan": ["List the exact fields awaiting confirmation, grouped by entity",
                         "Send one consolidated confirmation request",
                         "Record any confirmed values with provenance"]}
    return {"action_class": REVIEW, "risk": "low", "reversible": True,
            "proposed_action": f"Review: {title}.",
            "plan": ["Gather the relevant read-only context", "Summarize and recommend the next step for approval"]}


def build_proposals(priorities: list) -> list:
    """Ranked priorities -> draft proposals (status='proposed'). Pure + deterministic."""
    out = []
    for p in (priorities or []):
        if not isinstance(p, dict):
            continue
        out.append({"source_key": p.get("source", ""), "severity": p.get("severity", ""),
                    "entity": p.get("entity"), "title": p.get("title", ""),
                    "status": _OPEN, **_template(p)})
    return out


def build_daily_plan(proposals: list) -> dict:
    """A ranked, time-boxed plan from the open proposals (draft-only; the operator approves/edits)."""
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3, "": 4}
    est = {INVESTIGATE: "30m", VERIFY: "20m", REQUEST_INFO: "5m", REVIEW: "15m"}
    ranked = sorted([p for p in proposals if p.get("status") == _OPEN],
                    key=lambda p: order.get(p.get("severity", ""), 9))
    steps = [{"n": i + 1, "severity": p.get("severity"), "do": p.get("proposed_action"),
              "est": est.get(p.get("action_class"), "15m"), "class": p.get("action_class"),
              "entity": p.get("entity")} for i, p in enumerate(ranked)]
    return {"count": len(steps), "steps": steps,
            "note": "Draft plan — read-only/investigative steps only. Approve or edit; nothing runs until approved."}


def demo() -> None:
    prios = [
        {"severity": "HIGH", "title": "Nexora: risk — money-theft vuln", "source": "registry:nexora.risks", "entity": "nexora"},
        {"severity": "MEDIUM", "title": "Re-verify SOLCIRCLE", "source": "registry:solcircle.confidence", "entity": "solcircle"},
        {"severity": "LOW", "title": "Confirm 62 operator data field(s)", "source": "registry.needs_confirmation()"},
    ]
    props = build_proposals(prios)
    assert len(props) == 3 and all(p["status"] == "proposed" for p in props)
    assert props[0]["action_class"] == INVESTIGATE and props[1]["action_class"] == VERIFY
    assert props[2]["action_class"] == REQUEST_INFO
    assert all(p["reversible"] and p["plan"] for p in props), "every proposal has a reversible plan"
    plan = build_daily_plan(props)
    assert plan["count"] == 3 and plan["steps"][0]["severity"] == "HIGH", plan
    print(f"proposals.demo OK — {len(props)} draft proposals (all read-only), daily plan ranked {plan['count']} steps")


if __name__ == "__main__":
    demo()
