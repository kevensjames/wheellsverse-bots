"""Pure tests for the Operational Self-Model (§37/§38/§72/§74).
Run: python3 backend/app/services/holding/test_self_model.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.self_model import OperationalSelfModel, UNAVAILABLE  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _model(**src):
    base = {
        "capabilities": lambda: {"available": ["kai-memory", "yt-dlp"], "available_count": 2,
                                 "unavailable_count": 124, "catalog_total": 126},
        "companies": lambda: ["sol", "nurtelle", "kai"],
        "autonomy": lambda: {"overall": "AUTONOMOUS_READ_ONLY"},
        "workers": lambda: [{"worker_id": "w1", "online": True}, {"worker_id": "w2", "online": False}],
        "open_proposals": lambda: [{"id": 7, "entity_id": "sol", "title": "Approve the prepared staging cert",
                                    "rationale": "SOL staging is green and awaiting your go"}],
    }
    base.update(src)
    return OperationalSelfModel(deployment_sha="3b9caff", environment="production",
                               software_version="exec-v1", owner_principal="owner", sources=base)


def t_snapshot_has_operational_fields():
    s = _model().snapshot()
    for k in ("identity", "system_role", "deployment_sha", "environment", "available_capabilities",
              "known_companies", "money_mode", "owner_required_action_count", "known_limitations"):
        assert k in s, f"missing {k}"
    assert s["identity"] == "KAI" and s["money_mode"] == "MOCK"
    assert s["deployment_sha"] == "3b9caff" and s["environment"] == "production"
    assert s["available_capability_count"] == 2 and s["capability_catalog_total"] == 126
    assert s["workers_online"] == 1 and s["workers_known"] == 2


def t_never_claims_consciousness():
    s = _model().snapshot()
    assert s["claims_consciousness"] is False
    d = _model().describe().lower()
    assert "no claim to consciousness" in d or "no claim to conscious" in d
    for banned in ("i am conscious", "i am sentient", "i feel", "my emotions", "i am alive"):
        assert banned not in d, f"self-description must not assert: {banned}"


def t_unknowns_are_unavailable_not_fabricated():
    m = OperationalSelfModel(sources={"capabilities": lambda: {}, "companies": lambda: [],
                                      "autonomy": lambda: {}, "workers": lambda: [], "open_proposals": lambda: []})
    s = m.snapshot()
    assert s["deployment_sha"] == UNAVAILABLE and s["environment"] == UNAVAILABLE
    assert s["owner_principal"] == UNAVAILABLE and s["autonomy_overall"] == UNAVAILABLE


def t_fail_open_on_broken_subsystem():
    """A subsystem that raises must yield UNAVAILABLE/empty, never crash the self-model (§38)."""
    def boom():
        raise RuntimeError("db down")
    m = _model(capabilities=boom, companies=boom, autonomy=boom, workers=boom, open_proposals=boom)
    s = m.snapshot()   # must not raise
    assert s["available_capabilities"] == [] and s["known_companies"] == []
    assert s["owner_required_action_count"] == 0 and s["autonomy_overall"] == UNAVAILABLE


def t_what_do_you_need_is_owner_gated_only():
    """§74 key acceptance: returns only things the OWNER must do (open proposals), formatted usefully."""
    needs = _model().what_do_you_need_from_me()
    assert len(needs) == 1
    n = needs[0]
    assert n["company"] == "sol" and n["proposal_id"] == 7
    assert "approve" in n["owner_action"].lower() or "staging cert" in n["owner_action"].lower()
    assert n["why"] and n["kai_already_did"]


def t_what_am_i_doing_from_live_state():
    txt = _model().what_am_i_doing()
    assert "AUTONOMOUS_READ_ONLY" in txt and "3 holding companies" in txt and "waiting for your approval" in txt
    idle = _model(open_proposals=lambda: []).what_am_i_doing()
    assert "No material action is waiting on you" in idle


def t_no_owner_actions_when_queue_empty():
    assert _model(open_proposals=lambda: []).what_do_you_need_from_me() == []


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
