import pytest
from app.services.ceo import floor as fl
from app.services.ceo import store as st


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.setenv("KAI_CEO_PERIOD", "weekly")
    monkeypatch.setenv("KAI_CEO_CATASTROPHIC_USD", "50")
    monkeypatch.setenv("KAI_CEO_MASS_SEND_N", "25")
    monkeypatch.delenv("KAI_CEO_KILLED", raising=False)
    yield


def test_catastrophic_kinds_flagged():
    assert fl.is_catastrophic({"type": "deploy", "kind": "prod_deploy"})
    assert fl.is_catastrophic({"type": "money", "kind": "money_transfer", "amount": 80})
    assert not fl.is_catastrophic({"type": "money", "kind": "money_transfer", "amount": 10})
    assert fl.is_catastrophic({"type": "email", "kind": "mass_send", "recipients": 100})
    assert not fl.is_catastrophic({"type": "chat", "kind": "assignment"})


def test_ceiling_blocks_over_budget():
    assert fl.within_ceiling(40)
    st.add_ledger(80, "ads")
    assert not fl.within_ceiling(40)
    assert fl.within_ceiling(10)


def test_classify_precedence():
    assert fl.classify({"type": "chat", "kind": "assignment"}) == "in_policy"
    assert fl.classify({"type": "deploy", "kind": "prod_deploy"}) == "catastrophic"
    st.add_ledger(95, "ads")
    assert fl.classify({"type": "spend", "kind": "spend", "amount": 20}) == "over_ceiling"


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("KAI_CEO_KILLED", "1")
    assert fl.is_killed()
