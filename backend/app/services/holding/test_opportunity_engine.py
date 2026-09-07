"""§20 OpportunityEngine — pure tests (injectable fakes, no DB/network).
Run: python3 backend/app/services/holding/test_opportunity_engine.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.opportunity_engine import (  # noqa: E402
    detect_opportunities, HoldingOpportunity, _has_real_evidence)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


# ── fixtures: real-shaped source outputs ──────────────────────────────────────────────────────────
def _gaps():
    return [
        {"goal_id": 1, "company": "sol", "metric": "customers", "verdict": "GAP",
         "gap": {"current": 40, "target": 100, "remaining_to_target": 60, "direction": "increase"},
         "evidence": [{"claim": "current customers", "value": 40,
                       "source": "registry:sol.customers (operator-confirmed)"}],
         "recommended_actions": [{"action": "Increase customers on sol by 60", "source": "computed"}],
         "blockers": []},
        {"goal_id": 2, "company": "kai", "metric": "revenue", "verdict": "UNAVAILABLE",
         "gap": {"status": "UNAVAILABLE", "reason": "no owner-set target"},
         "evidence": [{"claim": "target for revenue", "value": "UNAVAILABLE",
                       "source": "no target on record"}],
         "recommended_actions": [], "blockers": [{"blocker": "no owner-set target", "source": "goal:2"}]},
        {"goal_id": 3, "company": "sol", "metric": "churn", "verdict": "MET",
         "gap": {"status": "MET", "current": 2, "target": 5},
         "evidence": [{"claim": "current churn", "value": 2, "source": "x"}],
         "recommended_actions": [], "blockers": []},
    ]


def _issues():
    return [
        {"issue_type": "DUPLICATE_CAPABILITY", "companies": ["holding"], "shared_resource": "send_email",
         "recommended_actions": ["INVESTIGATE", "DEFER"], "confidence": "MEDIUM", "owner_required": False,
         "observed_facts": "capability 'send_email' provided by 2 AVAILABLE capabilities",
         "evidence": [{"capability_id": "cap-a", "provides": "send_email"}],
         "root_signature": "DUPLICATE_CAPABILITY:send_email"},
        {"issue_type": "SHARED_INFRA_FAILURE", "companies": ["a", "b"], "shared_resource": "railway",
         "recommended_actions": ["INVESTIGATE"], "confidence": "MEDIUM", "owner_required": True,
         "observed_facts": "2 companies failing on railway", "evidence": [{"company": "a"}],
         "root_signature": "SHARED_INFRA_FAILURE:railway"},
    ]


def _problems():
    return [
        {"problem_id": "p1", "company": "kai", "category": "CODE_DEFECT", "severity": "HIGH",
         "observed_facts": "certified suite 'x' failing", "confidence": "HIGH",
         "recommended_actions": ["INVESTIGATE", "PREPARE_FIX", "EVIDENCE"], "owner_required": False,
         "evidence": [{"suite_id": "x", "failed": 1}], "root_signature": "failing_suite:x"},
        {"problem_id": "p2", "company": "kai", "category": "DOCUMENTATION", "severity": "LOW",
         "observed_facts": "maybe stale doc", "confidence": "LOW",
         "recommended_actions": ["INVESTIGATE", "PREPARE_FIX"], "owner_required": False,
         "evidence": [{"source": "UNKNOWN"}], "root_signature": "doc:README.md"},
        {"problem_id": "p3", "company": "kai", "category": "HEALTH", "severity": "CRITICAL",
         "observed_facts": "health probe down", "confidence": "HIGH",
         "recommended_actions": ["INVESTIGATE", "CREATE_MISSION", "EVIDENCE"], "owner_required": True,
         "evidence": [{"probe": "down"}], "root_signature": "priority:health"},   # no PREPARE_FIX → not an opp
    ]


# ── tests ──────────────────────────────────────────────────────────────────────────────────────────
def t_each_source_becomes_the_right_category():
    opps = detect_opportunities(goal_gaps=_gaps(), shared_issues=_issues(), problems=_problems())
    cats = {o.category for o in opps}
    assert cats == {"GROWTH", "CONSOLIDATION", "RELIABILITY"}, cats
    assert all(o.evidence and o.why_now and o.recommended_next_step != "UNKNOWN" for o in opps), opps


def t_no_evidence_opportunity_dropped():
    """§0 #16-19: a candidate whose evidence is empty or UNKNOWN-only is DROPPED — no generic idea."""
    assert not _has_real_evidence([])
    assert not _has_real_evidence([{"source": "UNKNOWN"}])
    assert not _has_real_evidence([{}])
    assert _has_real_evidence([{"suite_id": "x"}])
    opps = detect_opportunities(goal_gaps=[], shared_issues=[], problems=_problems())
    # p1 (real evidence) surfaces; p2 (UNKNOWN-only) is dropped; p3 (not fixable) never built
    sigs = {o.signature for o in opps}
    assert "opp:failing_suite:x" in sigs, sigs
    assert "opp:doc:README.md" not in sigs, "UNKNOWN-only evidence must be dropped"
    assert "opp:priority:health" not in sigs, "a non-fixable problem is not an opportunity"


def t_unavailable_and_met_goals_are_not_opportunities():
    opps = detect_opportunities(goal_gaps=_gaps(), shared_issues=[], problems=[])
    assert [o.signature for o in opps] == ["opp:goal:1:customers"], opps
    g = opps[0]
    assert g.category == "GROWTH" and g.confidence == "HIGH" and "60" in g.why_now, g


def t_failure_class_shared_issue_is_not_an_opportunity():
    opps = detect_opportunities(goal_gaps=[], shared_issues=_issues(), problems=[])
    sigs = {o.signature for o in opps}
    assert sigs == {"opp:DUPLICATE_CAPABILITY:send_email"}, sigs
    assert opps[0].category == "CONSOLIDATION" and opps[0].dependencies == ["holding"]


def t_dedup_by_signature_and_ranked_by_confidence():
    gaps = _gaps()
    opps = detect_opportunities(goal_gaps=gaps + [gaps[0]], shared_issues=_issues(), problems=_problems())
    # same goal gap twice → ONE opportunity
    assert len([o for o in opps if o.signature == "opp:goal:1:customers"]) == 1, opps
    # ranked HIGH-confidence first
    from app.services.holding.opportunity_engine import _CONF_ORDER
    confs = [_CONF_ORDER.get(o.confidence, 3) for o in opps]
    assert confs == sorted(confs), confs


def t_empty_and_fail_open():
    assert detect_opportunities(goal_gaps=[], shared_issues=[], problems=[]) == []
    # a producer that raises contributes nothing (never crashes) — inject a bad shape
    opps = detect_opportunities(goal_gaps=[{"verdict": "GAP"}], shared_issues=[], problems=[])
    # verdict GAP but no gap/evidence → its evidence is empty → dropped
    assert opps == [], opps


def t_owner_impact_and_next_step_cited():
    opps = detect_opportunities(goal_gaps=[], shared_issues=_issues(), problems=_problems())
    cons = next(o for o in opps if o.category == "CONSOLIDATION")
    assert cons.owner_impact is False and cons.recommended_next_step.startswith("INVESTIGATE"), cons
    rel = next(o for o in opps if o.category == "RELIABILITY")
    assert rel.recommended_next_step.startswith("PREPARE_FIX"), rel


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
