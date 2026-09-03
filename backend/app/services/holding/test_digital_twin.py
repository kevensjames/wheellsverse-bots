"""Pure tests for the Holding Digital Twin + StartupState (§4-7, §15, §59 matrix).
Run: python3 backend/app/services/holding/test_digital_twin.py"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.digital_twin import (  # noqa: E402
    HoldingDigitalTwin, StartupState, UNAVAILABLE, fact, _freshness)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _ent(eid, name, etype="product", **kw):
    base = dict(entity_id=eid, brand_name=name, entity_type=etype, stage="live", operational_status="LIVE",
                products=[], repository=None, deployment=None, domains=[], integrations=[],
                incidents=[], risks=[], last_verified_at="2026-08-30")
    base.update(kw)
    return SimpleNamespace(**base)


def _money(mapping):
    """report_value fake: returns (value, prov) or (None, disclaim) for un-sourced fields."""
    def rv(eid, fld):
        v = mapping.get((eid, fld))
        return (v, "source: test") if v is not None else (None, f"{fld} REQUIRES_OPERATOR_CONFIRMATION")
    return rv


def _twin(entities, *, proposals=None, money=None, today="2026-09-01"):
    return HoldingDigitalTwin(
        observed_at=today + "T08:00:00", today=today,
        sources={
            "entities": lambda: entities,
            "report_value": _money(money or {}),
            "open_proposals": lambda: (proposals or []),
            "priorities": lambda: [{"rank": 1, "severity": "HIGH", "title": "x", "source": "registry:sol.risks"}],
            "autonomy": lambda: {"overall": "AUTONOMOUS_READ_ONLY"},
            "workers": lambda: [{"worker_id": "w1", "online": True}],
            "capabilities": lambda: {"available_count": 2, "catalog_total": 126},
        })


def t_discovers_only_startup_types():
    ents = [_ent("sol", "SOL"), _ent("holding", "Holding", etype="holding"),
            _ent("wmos", "W-MOS", etype="project"), _ent("solcircle", "SOLCIRCLE", etype="LLC")]
    ids = {c.company_id for c in _twin(ents).companies()}
    assert ids == {"sol", "solcircle"}, ids   # holding + project excluded


def t_new_company_auto_included():
    """§5: adding an entity to the source → twin includes it with no code change here."""
    ents = [_ent("sol", "SOL")]
    assert len(_twin(ents).companies()) == 1
    ents.append(_ent("newco", "NewCo"))
    assert {c.company_id for c in _twin(ents).companies()} == {"sol", "newco"}


def t_money_never_fabricated():
    """§58: un-sourced money/customers ⇒ UNAVAILABLE, not a number."""
    st = _twin([_ent("sol", "SOL")]).companies()[0]
    assert st.revenue_summary["value"] == UNAVAILABLE and st.revenue_summary["status"] == UNAVAILABLE
    assert st.customers_summary["value"] == UNAVAILABLE
    # a source-backed revenue comes through as REAL with provenance
    st2 = _twin([_ent("sol", "SOL")], money={("sol", "revenue_metrics"): "Pre-revenue (confirmed)"}).companies()[0]
    assert st2.revenue_summary["value"] == "Pre-revenue (confirmed)" and st2.revenue_summary["status"] == "REAL"
    assert "source" in st2.revenue_summary


def t_unknowns_are_unavailable():
    st = _twin([_ent("sol", "SOL")]).companies()[0]
    for f in ("mission", "current_goal", "analytics_summary", "today_plan", "seven_day_plan"):
        assert getattr(st, f) == UNAVAILABLE, f


def t_freshness_from_last_verified():
    assert _freshness("2026-08-31", 30, "2026-09-01") == "FRESH"
    assert _freshness("2026-06-01", 30, "2026-09-01") == "STALE"
    assert _freshness(UNAVAILABLE, 30, "2026-09-01") == "UNKNOWN"
    assert _freshness("garbage", 30, "2026-09-01") == "UNKNOWN"


def t_fact_provenance_shape():
    f = fact("v", "src", observed_at="2026-09-01", fact_type="money", today="2026-09-01")
    assert set(f) == {"value", "source", "observed_at", "freshness", "status"}
    assert f["status"] == "REAL" and f["freshness"] == "FRESH"
    assert fact(None, "src")["status"] == UNAVAILABLE


def t_owner_actions_routed_per_company():
    props = [{"id": 7, "entity": "sol", "title": "Approve staging cert", "severity": "HIGH"},
             {"id": 8, "entity": "kai", "title": "Rotate key", "severity": "CRITICAL"}]
    twin = _twin([_ent("sol", "SOL"), _ent("kai", "KAI")], proposals=props)
    sol = next(c for c in twin.companies() if c.company_id == "sol")
    assert len(sol.owner_actions_required) == 1 and sol.owner_actions_required[0]["proposal_id"] == 7
    snap = twin.snapshot()
    assert snap["company_count"] == 2 and len(snap["owner_actions"]) == 2
    assert snap["money_mode"] == "MOCK" and snap["autonomy_overall"] == "AUTONOMOUS_READ_ONLY"
    assert snap["shared_resources"]["capabilities_available"] == 2


def t_portfolio_view_from_real_state():
    props = [{"id": 7, "entity": "kai", "title": "Rotate key", "severity": "CRITICAL"}]
    ents = [_ent("sol", "SOL"), _ent("kai", "KAI"),
            _ent("nex", "Nexora", incidents=["money-theft vuln"])]
    pv = _twin(ents, proposals=props).portfolio_view()
    assert "kai" in pv["blocked"] and "kai" in pv["needs_attention"]     # owner action pending
    assert "nex" in pv["needs_attention"] and "nex" not in pv["blocked"]  # incident, not owner-blocked
    assert "sol" in pv["healthy"]
    assert pv["owner_work_count"] == 1


def t_fail_open_on_broken_source():
    def boom(): raise RuntimeError("db down")
    twin = HoldingDigitalTwin(sources={"entities": boom, "open_proposals": boom, "priorities": boom,
                                        "autonomy": boom, "workers": boom, "capabilities": boom})
    snap = twin.snapshot()   # must not raise
    assert snap["companies"] == [] and snap["owner_actions"] == []
    assert snap["autonomy_overall"] == UNAVAILABLE


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
