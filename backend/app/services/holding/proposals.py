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


def _entity_facts(entity: Optional[str]) -> dict:
    """Real registry facts for an entity (repo, status, confidence) — grounds a richer proposal. Fail-open."""
    if not entity:
        return {}
    try:
        from app.services.holding import registry as reg
        e = reg.get(entity)
        if not e:
            return {}
        return {"repo": e.repository, "status": e.operational_status, "confidence": e.confidence.value,
                "deployment": e.deployment}
    except Exception:
        return {}


def _template(priority: dict) -> dict:
    """priority -> {action_class, proposed_action, plan[], risk, reversible, worker?, impact, effort}.
    Read-only actions only. Entity-aware: pulls the entity's real repo/status to be specific, and hints
    which isolated worker (github/browser) could carry the read-only action if dispatched (Wave 3)."""
    src = priority.get("source", "") or ""
    title = priority.get("title", "") or ""
    ent = priority.get("entity")
    who = ent or "the entity"
    f = _entity_facts(ent)
    repo = f.get("repo")
    ctx = (f" (repo {repo.split(' ')[0]}, currently {f.get('status')})" if repo else "")
    if ".risks" in src:
        return {"action_class": INVESTIGATE, "risk": "low", "reversible": True, "impact": "high", "effort": "30m",
                "worker": "github" if repo else None,
                "proposed_action": f"Confirm the logged risk on {who}{ctx} is remediated.",
                "plan": ([f"Pull {repo.split(' ')[0]}'s open PRs + latest CI (read-only GitHub worker)"] if repo
                         else ["Gather read-only evidence on the risk's current state"]) + [
                         f"Verify the specific issue in “{title[:60]}” is closed, no regression",
                         "If confirmed → propose clearing the risk from the registry (a separate approval); else escalate"]}
    if ".confidence" in src:
        return {"action_class": VERIFY, "risk": "low", "reversible": True, "impact": "medium", "effort": "20m",
                "worker": "github" if repo else None,
                "proposed_action": f"Re-verify {who}{ctx} to move it off {f.get('confidence','UNVERIFIED')}.",
                "plan": [f"Re-probe {who}'s live endpoints / in-process status"] +
                        ([f"Pull {repo.split(' ')[0]}'s repo + CI health (read-only GitHub worker)"] if repo else []) +
                        ["Update the registry confidence with cited evidence"]}
    if src.startswith("live-signal") or ":live" in src or "health" in title.lower() or "DOWN" in title:
        return {"action_class": INVESTIGATE, "risk": "low", "reversible": True, "impact": "high", "effort": "20m",
                "worker": None,
                "proposed_action": f"Diagnose the live-signal issue: {title}.",
                "plan": [f"Pull {who}'s health detail + the last deploy's status",
                         "Classify: transient blip vs real outage (check duration + recent change)",
                         "If real → prepare an escalation summary + a rollback option for approval"]}
    if "needs_confirmation" in src or title.startswith("Confirm"):
        return {"action_class": REQUEST_INFO, "risk": "none", "reversible": True, "impact": "medium", "effort": "5m",
                "worker": None,
                "proposed_action": "Assemble a single consolidated data-confirmation request for the operator.",
                "plan": ["List the exact fields awaiting confirmation, grouped by entity (from the registry)",
                         "Draft one message the operator can answer in one pass",
                         "On reply, record confirmed values with provenance"]}
    return {"action_class": REVIEW, "risk": "low", "reversible": True, "impact": "low", "effort": "15m", "worker": None,
            "proposed_action": f"Review and recommend a next step for: {title}.",
            "plan": ["Gather the relevant read-only context", "Summarize + recommend the next action for approval"]}


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
    """A ranked, time-boxed plan from the open proposals (draft-only; the operator approves/edits).
    Ranked by the ONE §22 ranker (priorities.rank_key) — no local severity→ordinal map."""
    from app.services.holding.priorities import rank_key
    est = {INVESTIGATE: "30m", VERIFY: "20m", REQUEST_INFO: "5m", REVIEW: "15m"}
    ranked = sorted([p for p in proposals if p.get("status") == _OPEN], key=rank_key)
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
