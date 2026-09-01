"""Pure tests for the Holding State Reconciler (§8-10, §17, §60 matrix).
Run: python3 backend/app/services/holding/test_state_reconciler.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.state_reconciler import (  # noqa: E402
    reconcile, reconcile_result, MATERIALITY_VERSION)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _snap(companies, *, workers_online=1, caps=7, autonomy="AUTONOMOUS_READ_ONLY"):
    return {"companies": companies, "shared_resources": {"workers_online": workers_online,
            "capabilities_available": caps}, "autonomy_overall": autonomy}


def _co(cid, status="LIVE", incidents=0, owner_actions=0):
    return {"company_id": cid, "status": status,
            "active_incidents": ["x"] * incidents, "owner_actions_required": [{}] * owner_actions}


def _types(changes):
    return {c.change_type for c in changes}


def t_baseline_is_silent():
    """§17: first observation (no prior) produces zero changes."""
    assert reconcile(None, _snap([_co("sol")])) == []
    assert reconcile({}, _snap([_co("sol")])) == []


def t_no_change_yields_empty():
    """§17 required no-change behavior: materially identical snapshots → NO_MATERIAL_CHANGE."""
    s = _snap([_co("sol"), _co("kai")])
    assert reconcile(s, s) == []
    r = reconcile_result(s, s)
    assert r["verdict"] == "NO_MATERIAL_CHANGE" and r["material_change"] is False


def t_immaterial_metric_change_ignored():
    """§9: worker plane 3→2 (still online) is NOT material; no work created by a polling cycle."""
    a = _snap([_co("sol")], workers_online=3)
    b = _snap([_co("sol")], workers_online=2)
    assert reconcile(a, b) == []


def t_status_transition_always_material():
    a = _snap([_co("sol", status="LIVE")])
    b = _snap([_co("sol", status="DEGRADED")])
    ch = reconcile(a, b)
    assert _types(ch) == {"STATUS_CHANGED"} and ch[0].severity == "HIGH"   # into a degraded status
    # a non-degraded transition is still material but ranks MEDIUM
    ch2 = reconcile(_snap([_co("sol", status="LIVE")]), _snap([_co("sol", status="MAINTENANCE")]))
    assert ch2[0].severity == "MEDIUM"


def t_incident_open_and_close():
    opened = reconcile(_snap([_co("sol", incidents=0)]), _snap([_co("sol", incidents=1)]))
    assert opened[0].change_type == "INCIDENT_OPENED" and opened[0].severity == "CRITICAL"
    closed = reconcile(_snap([_co("sol", incidents=1)]), _snap([_co("sol", incidents=0)]))
    assert closed[0].change_type == "INCIDENT_RESOLVED" and closed[0].severity == "INFO"


def t_owner_blocker_add_and_resolve():
    added = reconcile(_snap([_co("kai", owner_actions=0)]), _snap([_co("kai", owner_actions=1)]))
    assert added[0].change_type == "OWNER_BLOCKER_ADDED" and added[0].severity == "HIGH"
    resolved = reconcile(_snap([_co("kai", owner_actions=2)]), _snap([_co("kai", owner_actions=1)]))
    assert resolved[0].change_type == "OWNER_BLOCKER_RESOLVED"


def t_worker_plane_and_capability_and_autonomy():
    ch = reconcile(_snap([_co("sol")], workers_online=1, caps=7, autonomy="AUTONOMOUS_READ_ONLY"),
                   _snap([_co("sol")], workers_online=0, caps=5, autonomy="DEGRADED"))
    t = _types(ch)
    assert "WORKER_PLANE_DEGRADED" in t and "CAPABILITY_UNAVAILABLE" in t and "AUTONOMY_CHANGED" in t
    # capability recovery is INFO, worker recovery is INFO
    ch2 = reconcile(_snap([_co("sol")], workers_online=0, caps=5),
                    _snap([_co("sol")], workers_online=1, caps=7))
    assert "WORKER_PLANE_RECOVERED" in _types(ch2) and "CAPABILITY_RECOVERED" in _types(ch2)


def t_company_added_and_removed():
    added = reconcile(_snap([_co("sol")]), _snap([_co("sol"), _co("newco")]))
    assert added[0].change_type == "COMPANY_ADDED" and added[0].scope == "newco"
    removed = reconcile(_snap([_co("sol"), _co("gone")]), _snap([_co("sol")]))
    assert any(c.change_type == "COMPANY_REMOVED" and c.scope == "gone" for c in removed)


def t_most_severe_first_and_versioned():
    a = _snap([_co("sol", status="LIVE", incidents=0)])
    b = _snap([_co("sol", status="DEGRADED", incidents=1)])
    ch = reconcile(a, b)
    assert ch[0].severity == "CRITICAL", [c.severity for c in ch]   # incident outranks status
    r = reconcile_result(a, b)
    assert r["materiality_version"] == MATERIALITY_VERSION and r["verdict"] == "MATERIAL_CHANGE"


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
