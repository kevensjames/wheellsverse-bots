import pytest
from app.services.ceo import injection, store as st


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def test_preamble_empty_when_scope_off(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_CEO", raising=False)
    st.upsert_company("Grow net revenue")
    assert injection.ceo_preamble() == ""


def test_preamble_present_when_on(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    st.upsert_company("Grow net revenue to $1M")
    out = injection.ceo_preamble()
    assert "CEO" in out and "$1M" in out


def test_preamble_empty_without_company(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    assert injection.ceo_preamble() == ""
