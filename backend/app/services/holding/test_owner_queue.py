"""Pure tests for owner-queue reconciliation (§1-3, §32 matrix).
Run: python3 backend/app/services/holding/test_owner_queue.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.plan import PlanTask, AutonomyClass, Assignee, ReconciledTask, Disposition  # noqa: E402
from app.services.holding.autonomous_work import WorkResult, OWNER_QUEUED, EXECUTED  # noqa: E402
from app.services.holding.owner_queue import (  # noqa: E402
    prepare_owner_actions, reconcile_owner_queue, to_proposals, OwnerAction)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _rt(tid, *, autonomy=AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, assignee=Assignee.OWNER, cid="kai",
        goal="Approve prepared release", reason="deploy required", evidence=None, expected="approve/deploy release"):
    t = PlanTask(task_id=tid, company_id=cid, goal=goal, reason=reason, source_key=tid,
                 autonomy=int(autonomy), assigned_to=assignee.value, expected_outcome=expected,
                 evidence=evidence or [])
    return ReconciledTask(t, Disposition.ADD.value)


def _wr(tid, outcome, cid="kai"):
    return WorkResult(task_id=tid, company_id=cid, autonomy=int(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT),
                      assigned_to=Assignee.OWNER.value, outcome=outcome, task_status="BLOCKED")


def t_owner_task_prepared_with_fields():
    acts = prepare_owner_actions([_rt("deploy:kai", evidence=[{"probe": "staging green"}])],
                                 [_wr("deploy:kai", OWNER_QUEUED)])
    assert len(acts) == 1
    a = acts[0]
    assert a.company_id == "kai" and a.source_key == "deploy:kai"
    assert "approve" in a.exact_owner_action.lower()
    assert "1 evidence" in a.kai_completed              # §2 preparation surfaced
    assert a.next_after_owner != "UNAVAILABLE" and a.evidence


def t_kai_capable_task_never_reaches_owner():
    """§32: an A0 KAI task that succeeded produces NO owner item."""
    kai = ReconciledTask(PlanTask("h:sol", "sol", "probe health", "r", "h:sol",
                                  autonomy=int(AutonomyClass.A0_OBSERVE), assigned_to=Assignee.KAI.value),
                         Disposition.KEEP.value)
    acts = prepare_owner_actions([kai], [WorkResult("h:sol", "sol", 0, Assignee.KAI.value, EXECUTED, "COMPLETE")])
    assert acts == []


def t_generic_titles_rejected():
    """§2: vague work is never queued."""
    acts = prepare_owner_actions([_rt("x:kai", goal="Review startup")], [])
    assert acts == []


def t_dedup_one_item_per_requirement():
    acts = prepare_owner_actions([_rt("deploy:kai"), _rt("deploy:kai")], [])
    assert len(acts) == 1                                # §1 no duplicate


def t_reconcile_upsert_and_auto_resolve():
    """§3: a prior open item whose requirement is gone this cycle is flagged to resolve."""
    prior = [{"source_key": "deploy:kai"}, {"source_key": "gone:sol"}]
    acts = prepare_owner_actions([_rt("deploy:kai")], [])
    delta = reconcile_owner_queue(prior, acts)
    assert delta["active_source_keys"] == ["deploy:kai"]
    assert delta["would_resolve"] == ["gone:sol"]       # vanished blocker auto-resolves
    assert len(delta["upsert"]) == 1 and delta["upsert"][0]["source_key"] == "deploy:kai"


def t_to_proposals_shape_matches_store():
    acts = prepare_owner_actions([_rt("deploy:kai", evidence=[{"x": 1}])], [])
    p = to_proposals(acts)[0]
    for k in ("source_key", "severity", "entity", "title", "action_class", "proposed_action", "kai_completed"):
        assert k in p, k
    assert p["action_class"] == "OWNER_REQUIRED" and p["entity"] == "kai"


def t_empty_when_no_owner_work():
    """§6/§7: nothing owner-required → empty queue (KAI invents no work)."""
    assert prepare_owner_actions([], []) == []
    assert reconcile_owner_queue([], [])["upsert"] == []


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
