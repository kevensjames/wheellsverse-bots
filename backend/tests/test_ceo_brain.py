import json, uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.services.ceo import brain


def _router(content):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content)
    return r


def test_decide_parses_json():
    payload = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                                "expected_impact": "+$2k/mo"}],
               "reprioritize": ["pause cold email"], "escalations": []}
    out = brain.decide(router=_router(json.dumps(payload)), user_id=uuid.uuid4(),
                       company={"goal": "grow revenue"}, snapshot={"revenue": 0}, org=[])
    assert out["initiatives"][0]["title"] == "Launch KDP bundle"
    assert out["reprioritize"] == ["pause cold email"]


def test_decide_failsoft_on_garbage():
    out = brain.decide(router=_router("not json at all"), user_id=uuid.uuid4(),
                       company={"goal": "grow revenue"}, snapshot={}, org=[])
    assert out == {"initiatives": [], "reprioritize": [], "escalations": []}


def test_decide_extracts_fenced_json():
    payload = {"initiatives": [], "reprioritize": [], "escalations": ["budget ceiling near"]}
    fenced = "Here is my plan:\n```json\n" + json.dumps(payload) + "\n```\n"
    out = brain.decide(router=_router(fenced), user_id=uuid.uuid4(),
                       company={"goal": "x"}, snapshot={}, org=[])
    assert out["escalations"] == ["budget ceiling near"]


def test_decide_router_exception_failsoft():
    r = MagicMock()
    r.complete.side_effect = RuntimeError("brain down")
    out = brain.decide(router=r, user_id=uuid.uuid4(), company={"goal": "x"}, snapshot={}, org=[])
    assert out == {"initiatives": [], "reprioritize": [], "escalations": []}
