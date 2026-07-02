import pytest
from factory import project as P


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def test_upsert_and_get_roundtrip():
    P.upsert_project(P.Project(slug="acme", name="Acme", repo_url="git@x:acme.git"))
    got = P.get_project("acme")
    assert got is not None
    assert got.name == "Acme"
    assert got.phase == "active"
    assert got.consecutive_failures == 0


def test_get_missing_returns_none():
    assert P.get_project("nope") is None


def test_list_active_excludes_non_active():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    P.upsert_project(P.Project(slug="b", name="B", repo_url="x", phase="done"))
    actives = [p.slug for p in P.list_active()]
    assert actives == ["a"]


def test_set_phase_persists():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    P.set_phase("a", "dormant")
    assert P.get_project("a").phase == "dormant"


def test_bump_failure_flags_red_at_threshold():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    assert P.bump_failure("a", threshold=3) == 1
    assert P.bump_failure("a", threshold=3) == 2
    assert P.bump_failure("a", threshold=3) == 3
    assert P.get_project("a").phase == "blocked_red"


def test_reset_failure_zeroes_count():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x", consecutive_failures=2))
    P.reset_failure("a")
    assert P.get_project("a").consecutive_failures == 0
