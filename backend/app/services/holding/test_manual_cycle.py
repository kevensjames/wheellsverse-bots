"""Pure tests for the manual single-cycle control (§3,§7,§8,§9,§11,§14,§15,§18,§24,§25).
Run: python3 backend/app/services/holding/test_manual_cycle.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.manual_cycle import (  # noqa: E402
    validate_request, normalize_record, run_manual_cycle, InMemoryCycleStore,
    ManualCycleDenied, CycleRunning)
from app.services.holding.holding_cycle import build_live_engine  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _co(cid, status="LIVE"):
    return {"company_id": cid, "status": status, "active_incidents": [], "owner_actions_required": [], "deployments": []}


def _snap(status="LIVE"):
    return {"companies": [_co("sol", status)], "shared_resources": {"workers_online": 1,
            "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}


def t_validate_rejects_forbidden_keys():
    """§3/§25: the request can carry only idempotency_key; task/capability/company/snapshot/authority denied."""
    for bad in ({"task": "x"}, {"capability_id": "financial"}, {"company": "acme"}, {"command": "rm"},
                {"snapshot": {}}, {"action_class": "FINANCIAL"}, {"autonomy_override": True},
                {"role": "owner"}, {"approved": True}, {"environment": "production"}, {"money_mode": "REAL"}):
        try:
            validate_request(bad); assert False, bad
        except ManualCycleDenied:
            pass
    assert validate_request({"idempotency_key": "k1"})["idempotency_key"] == "k1"
    assert validate_request({})["idempotency_key"] == ""


def t_normalize_record_safe_fields_only():
    """§11: only safe normalized fields; no secrets/env/logs/reasoning."""
    n = normalize_record({"cycle_id": "c1", "verdict": "NO_MATERIAL_CHANGE", "material_changes": 0,
                          "plan_dispositions": {"KEEP": 2}, "auto_executed": 0, "owner_queued": 0,
                          "started_at": "t", "completed_at": "t", "SESSION_SIGNING_SECRET": "leak"})
    for k in ("cycle_id", "status", "material_changes_count", "plan_updates_count", "auto_actions_executed",
              "owner_actions_created", "duration_ms"):
        assert k in n, k
    assert "SESSION_SIGNING_SECRET" not in n and "leak" not in str(n)
    assert n["plan_updates_count"] == 2


def t_quiet_cycle_zero_work():
    """§15 (mandatory): cycle N establishes state; cycle N+1 with no change → 0 everything."""
    store = InMemoryCycleStore()
    eng = build_live_engine(autonomy_on=False, execution_on=False)   # dark → deterministic, no network
    snaps = [_snap("LIVE")]
    rec1 = run_manual_cycle(store, eng, lambda: snaps[0], now="2026-09-02T08:00:00")
    assert rec1["material_changes_count"] == 0 and rec1["auto_actions_executed"] == 0   # baseline
    rec2 = run_manual_cycle(store, eng, lambda: snaps[0], now="2026-09-02T08:05:00")     # nothing changed
    assert rec2["material_changes_count"] == 0 and rec2["auto_actions_executed"] == 0 \
        and rec2["owner_actions_created"] == 0 and rec2["plan_updates_count"] == 0


def t_material_change_detected_across_cycles():
    """A real transition between two authoritative snapshots is detected (client can't fake it)."""
    store = InMemoryCycleStore()
    eng = build_live_engine(autonomy_on=False, execution_on=False)
    state = {"cur": _snap("LIVE")}
    run_manual_cycle(store, eng, lambda: state["cur"], now="2026-09-02T08:00:00")   # baseline LIVE
    state["cur"] = _snap("DEGRADED")                                                # real transition
    rec = run_manual_cycle(store, eng, lambda: state["cur"], now="2026-09-02T08:05:00")
    assert rec["material_changes_count"] == 1


def t_autonomy_off_no_auto_actions():
    """§18: autonomy OFF + a material change → observed but auto_actions_executed = 0 (no loophole)."""
    store = InMemoryCycleStore()
    eng = build_live_engine(autonomy_on=False, execution_on=True)
    state = {"cur": _snap("LIVE")}
    run_manual_cycle(store, eng, lambda: state["cur"], now="2026-09-02T08:00:00")
    state["cur"] = _snap("DEGRADED")
    rec = run_manual_cycle(store, eng, lambda: state["cur"], now="2026-09-02T08:05:00")
    assert rec["material_changes_count"] == 1 and rec["auto_actions_executed"] == 0 and rec["autonomy_off"] >= 1


def t_single_flight_lock():
    """§7: a concurrent cycle while one is running → CycleRunning (409)."""
    store = InMemoryCycleStore()
    eng = build_live_engine(autonomy_on=False, execution_on=False)
    other_token = store.try_lock("wheellsverse", 120, "now")   # simulate an in-progress cycle
    assert other_token and store.try_lock("wheellsverse", 120, "now") is None   # second acquire blocked
    try:
        run_manual_cycle(store, eng, lambda: _snap(), now="t")
        assert False, "should be single-flight blocked"
    except CycleRunning:
        pass
    # a late releaser with the WRONG token must NOT clear the live lease (recheck fix)
    store.release_lock("wheellsverse", "stale-token")
    assert store.try_lock("wheellsverse", 120, "now") is None   # still locked by other_token
    store.release_lock("wheellsverse", other_token)             # correct token releases
    assert store.try_lock("wheellsverse", 120, "now") is not None


def t_idempotent_replay():
    """§8: same idempotency_key → replay the prior record, no new cycle."""
    store = InMemoryCycleStore()
    eng = build_live_engine(autonomy_on=False, execution_on=False)
    r1 = run_manual_cycle(store, eng, lambda: _snap(), now="t1", idempotency_key="K1")
    seq_after_first = store._seq
    r2 = run_manual_cycle(store, eng, lambda: _snap(), now="t2", idempotency_key="K1")
    assert r2.get("replayed") is True and r2["cycle_id"] == r1["cycle_id"] and store._seq == seq_after_first


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
