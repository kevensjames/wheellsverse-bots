"""Pure tests for the Today brief + owner queries (§4-8, §33-34 matrix).
Run: python3 backend/app/services/holding/test_today_brief.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.briefing import (  # noqa: E402
    today_for_you, what_do_you_need_from_me, what_should_i_do_today, NO_ACTION, TODAY_MAX)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _oa(entity, title, severity="MEDIUM", sk=None, evidence=None):
    return {"entity": entity, "title": title, "severity": severity, "proposed_action": f"do {title}",
            "impact": "why", "kai_completed": "prepped", "source_key": sk or title, "evidence": evidence or []}


def t_zero_actions_is_no_action_message():
    """§6: empty owner queue → exact NO_ACTION line, nothing invented."""
    b = today_for_you()
    assert b["today_for_you"] == NO_ACTION
    assert b["kai_working_now"] == [] and b["decisions_needed"] == []


def t_one_action():
    b = today_for_you(owner_actions=[_oa("sol", "approve cert", "HIGH")])
    assert isinstance(b["today_for_you"], list) and len(b["today_for_you"]) == 1
    assert b["today_for_you"][0]["company"] == "sol"


def t_caps_at_seven_and_groups_overflow():
    """§5/§28: default 3–7; extra work grouped, not dropped silently."""
    actions = [_oa("c%d" % i, "t%d" % i) for i in range(10)]
    b = today_for_you(owner_actions=actions)
    assert len(b["today_for_you"]) == TODAY_MAX
    assert "3 lower-priority" in b["today_overflow_grouped"]
    assert len(b["decisions_needed"]) == 10             # decisions_needed keeps them all


def t_critical_ranks_first():
    b = today_for_you(owner_actions=[_oa("a", "low", "INFO"), _oa("b", "crit", "CRITICAL")])
    assert b["today_for_you"][0]["company"] == "b"      # critical surfaced first


def t_provenance_present():
    """§34: every Today item links back to company + evidence."""
    b = today_for_you(owner_actions=[_oa("sol", "x", "HIGH", sk="k1", evidence=[{"probe": 1}])])
    item = b["today_for_you"][0]
    assert item["source_key"] == "k1" and item["evidence"] == [{"probe": 1}]
    assert item["kai_completed"] == "prepped"


def t_seven_sections_present():
    b = today_for_you(owner_actions=[_oa("sol", "x")], kai_completed=["did y"],
                      kai_working_now=["probing z"], material_changes=[{"c": 1}],
                      risks=["r"], watching=["w"])
    for k in ("today_for_you", "kai_completed_since_last_visit", "kai_working_now",
              "material_changes", "risks", "decisions_needed", "watching"):
        assert k in b, k
    assert b["kai_working_now"] == ["probing z"] and b["risks"] == ["r"]


def t_what_do_you_need_empty_and_full():
    assert what_do_you_need_from_me([])["message"] == "Nothing currently requires your action."
    r = what_do_you_need_from_me([_oa("kai", "rotate", "CRITICAL")])
    assert r["actions"][0]["company"] == "kai" and "1 item" in r["message"]


def t_what_should_i_do_today_uses_queue():
    assert what_should_i_do_today([])["today_for_you"] == NO_ACTION
    r = what_should_i_do_today([_oa("sol", "x", "HIGH")])
    assert isinstance(r["today_for_you"], list) and len(r["today_for_you"]) == 1


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
