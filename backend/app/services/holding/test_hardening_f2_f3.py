"""F2 (owner-queue visibility, writer-only) + F3 (malformed-authority robustness) — pure, python3.

F2: a cycle that finds genuine owner work persists ONE item into the EXISTING owner queue with
create-if-absent / update-safe-if-open / skip-if-terminal semantics — never a status transition, never
auto-close. F3: one corrupt autonomy value fails closed for that task (BLOCKED_POLICY / INVALID_ACTION_CLASS)
without crashing the whole cycle and without ever defaulting to A0. DB-free (pure classifier + injected
writer). Run: python3 test_hardening_f2_f3.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.holding.autonomous_work import (  # noqa: E402
    run_cycle, OWNER_QUEUED, EXECUTED, BLOCKED_POLICY)
from app.services.holding.holding_cycle import build_live_engine, run_persistent_cycle  # noqa: E402
from app.services.holding.state_reconciler import reconcile_result  # noqa: E402
from app.services.holding.plan import (  # noqa: E402
    tasks_from_changes, reconcile_plan, PlanTask, Assignee, AutonomyClass, TaskStatus)
from app.services.holding.owner_queue import (  # noqa: E402
    prepare_owner_actions, persist_owner_actions, owner_upsert_disposition)

_p = 0
def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def snap(status="OK", owner=None):
    return {"companies": [{"company_id": "sol", "status": status, "active_incidents": [],
            "owner_actions_required": owner or [], "deployments": ["sha-abc"]}],
            "shared_resources": {"workers_online": 1, "capabilities_available": 7},
            "autonomy_overall": "AUTONOMOUS_READ_ONLY"}


def _task(autonomy, assignee=Assignee.KAI, *, task_type="", source_key="t"):
    return PlanTask(task_id=source_key, company_id="sol", goal="g", reason="r", source_key=source_key,
                    task_type=task_type, autonomy=autonomy, assigned_to=assignee.value)


# ── F3 ───────────────────────────────────────────────────────────────────────────────────────────
def t_f3_malformed_autonomy_fails_closed():
    """Every malformed authority value -> BLOCKED_POLICY / INVALID_ACTION_CLASS, never executes, never A0."""
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    for bad in (None, "garbage", -1, 10 ** 9, {}, [], 2.5):
        r = eng.run_task(_task(bad, source_key="bad"))
        assert r.outcome == BLOCKED_POLICY, (bad, r.outcome)
        assert r.reason == "INVALID_ACTION_CLASS", (bad, r.reason)
        assert r.outcome != EXECUTED and not r.verified


def t_f3_one_bad_task_does_not_crash_the_cycle():
    """A batch with a corrupt task + a valid A0 task: bad -> BLOCKED_POLICY, good -> EXECUTED, no raise."""
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    good = _task(int(AutonomyClass.A0_OBSERVE), Assignee.KAI, task_type="HEALTH_PROBE", source_key="good")
    bad = _task("garbage", Assignee.KAI, source_key="bad")
    out = eng.run([bad, good])                              # must not raise
    by = {r.task_id: r.outcome for r in out}
    assert by["bad"] == BLOCKED_POLICY and by["good"] == EXECUTED, by


def t_f3_valid_authority_regression():
    """The guard must not disturb valid tasks: A0/KAI executes; A3/OWNER is owner-queued."""
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    a0 = eng.run_task(_task(int(AutonomyClass.A0_OBSERVE), Assignee.KAI, task_type="HEALTH_PROBE", source_key="a0"))
    a3 = eng.run_task(_task(int(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT), Assignee.OWNER, source_key="a3"))
    assert a0.outcome == EXECUTED and a3.outcome == OWNER_QUEUED, (a0.outcome, a3.outcome)


# ── F2 ───────────────────────────────────────────────────────────────────────────────────────────
def t_f2_classify_never_reopens_terminal():
    """The security-critical writer decision: absent->insert, open->update, ANY terminal->skip (no reopen)."""
    assert owner_upsert_disposition(None) == "insert"
    assert owner_upsert_disposition("proposed") == "update"
    for terminal in ("approved", "rejected", "executed", "superseded"):
        assert owner_upsert_disposition(terminal) == "skip_terminal", terminal


def _fake_writer():
    box = {"items": []}
    def w(items):
        box["items"] = list(items); return {"ok": True, "inserted": len(items), "updated": 0, "skipped_terminal": 0}
    return box, w


def t_f2_persist_is_writer_only_owner_decision():
    """Prepared owner action -> exactly one queue item, marked OWNER_REQUIRED (a decision, not an execution),
    carrying last_observed_at; the writer performs no status transition."""
    recon = reconcile_result(snap(owner=[]), snap(owner=["decide pricing"]))
    actions = prepare_owner_actions(reconcile_plan([], tasks_from_changes(recon["changes"])), [], now="t")
    box, w = _fake_writer()
    r = persist_owner_actions(actions, writer=w, now="t")
    assert r["ok"] and len(box["items"]) == 1
    it = box["items"][0]
    assert it["source_key"] and it["action_class"] == "OWNER_REQUIRED" and it["last_observed_at"] == "t"
    assert "status" not in it   # the writer never carries a status transition


def t_f2_cycle_wires_owner_blocker_into_the_queue():
    """run_persistent_cycle with an owner-blocker transition writes exactly one owner item (autonomy ON)."""
    box, w = _fake_writer()
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    rec = run_persistent_cycle(snap(owner=[]), snap(owner=["decide"]), engine=eng, cycle_id="c", now="t",
                               owner_writer=w)
    assert len(box["items"]) == 1 and rec.owner_actions_created == 1 and rec.status != "OWNER_QUEUE_PERSIST_FAILED"


def t_f2_a0_only_cycle_writes_no_owner_item():
    """An A0 health-probe cycle produces no owner item (only genuine owner work is queued)."""
    box, w = _fake_writer()
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    run_persistent_cycle(snap("OK"), snap("DEGRADED"), engine=eng, cycle_id="c", now="t", owner_writer=w)
    assert box["items"] == []


def t_f2_a4_mislabeled_kai_still_makes_an_owner_item():
    """An A4 financial task mis-assigned to KAI is owner-required (>=A3) -> an owner item, never executed."""
    a4 = _task(int(AutonomyClass.A4_FINANCIAL_CREDENTIAL_DESTRUCTIVE), Assignee.KAI, source_key="a4")
    actions = prepare_owner_actions([a4], [], now="t")
    box, w = _fake_writer()
    persist_owner_actions(actions, writer=w, now="t")
    assert len(box["items"]) == 1 and box["items"][0]["source_key"] == "a4"


def t_f2_persist_failure_is_degraded_never_execution_bypass():
    """If the owner-queue write fails, the cycle records OWNER_QUEUE_PERSIST_FAILED and still executes 0
    owner work — a write failure is never permission to proceed."""
    def fail_writer(items):
        return {"ok": False, "inserted": 0, "updated": 0, "skipped_terminal": 0}
    eng = build_live_engine(autonomy_on=True, execution_on=True)
    rec = run_persistent_cycle(snap(owner=[]), snap(owner=["decide"]), engine=eng, cycle_id="c", now="t",
                               owner_writer=fail_writer)
    assert rec.status == "OWNER_QUEUE_PERSIST_FAILED"
    assert rec.tasks_executed == 0 and rec.owner_actions_created == 1   # owner work queued, never executed


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
