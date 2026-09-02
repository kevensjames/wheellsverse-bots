"""Tests for the Holding UI view-model (Part E, §25-30).
Run: python3 backend/app/services/holding/test_holding_view.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.holding_view import build_holding_view  # noqa: E402
from app.services.holding.briefing import NO_ACTION  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _twin():
    return {"autonomy_overall": "AUTONOMOUS_READ_ONLY", "money_mode": "MOCK",
            "companies": [{"company_id": "sol", "name": "SOL", "status": "LIVE", "source_freshness": "FRESH",
                           "risks": ["pre-revenue"], "owner_actions_required": []},
                          {"company_id": "kai", "name": "KAI", "status": "LIVE", "source_freshness": "FRESH",
                           "owner_actions_required": [{}]}]}


def _sm():
    return {"identity": "KAI", "software_version": "exec-v1", "environment": "production",
            "available_capability_count": 7, "workers_online": 1, "owner_required_action_count": 1}


def t_today_first_and_sections_present():
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm(),
                           owner_actions=[{"entity": "kai", "title": "Rotate key", "severity": "CRITICAL",
                                           "proposed_action": "rotate", "source_key": "k1"}],
                           cycle_record={"cycle_id": "c9", "completed_at": "2026-09-02T08:00:00",
                                         "verdict": "MATERIAL_CHANGE"})
    for k in ("today_for_you", "kai_working", "self_improvement_ready", "company_cards",
              "operational_self_model", "autonomy"):
        assert k in v, k
    assert isinstance(v["today_for_you"], list) and v["today_for_you"][0]["company"] == "kai"


def t_no_action_when_empty():
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm(), owner_actions=[])
    assert v["today_for_you"] == NO_ACTION


def t_self_model_never_sentient():
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm())
    osm = v["operational_self_model"]
    assert osm["label"] == "Operational Self Model" and osm["claims_consciousness"] is False
    assert osm["identity"] == "KAI" and osm["capabilities_ready"] == 7
    blob = str(v).lower()
    assert "sentient" not in blob and "conscious" not in blob.replace("claims_consciousness", "")


def t_kai_work_buckets():
    work = [{"company_id": "sol", "task_id": "t1", "capability_id": "holding.health", "outcome": "EXECUTED",
             "status": "COMPLETE"},
            {"company_id": "kai", "task_id": "t2", "outcome": "A2_READY_FOR_REVIEW"},
            {"company_id": "nex", "task_id": "t3", "outcome": "BLOCKED_CAPABILITY"}]
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm(), kai_work=work)
    assert len(v["kai_working"]["ready_for_review"]) == 1 and len(v["kai_working"]["blocked"]) == 1


def t_self_improvement_ready_only():
    sis = [{"status": "READY_FOR_REVIEW", "problem": "bug", "owner_action": "review",
            "files_changed": ["x.py"], "tests_after": "8 passed"},
           {"status": "BLOCKED", "problem": "other"},
           # recheck: an un-ready item with a truthy owner_action must NOT surface as ready-for-review
           {"status": "IN_PROGRESS", "problem": "premature", "owner_action": "needs input"}]
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm(), self_improvements=sis)
    assert len(v["self_improvement_ready"]) == 1 and v["self_improvement_ready"][0]["problem"] == "bug"


def t_company_cards_and_autonomy():
    v = build_holding_view(twin_snapshot=_twin(), self_model=_sm(),
                           cycle_record={"completed_at": "2026-09-02T08:00:00", "verdict": "NO_MATERIAL_CHANGE"})
    ids = {c["company_id"] for c in v["company_cards"]}
    assert ids == {"sol", "kai"}
    kai = next(c for c in v["company_cards"] if c["company_id"] == "kai")
    assert kai["owner_blocker"] is True
    assert v["autonomy"]["money_mode"] == "MOCK" and "SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1" in v["autonomy"]["a2_certified_grants"]


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
