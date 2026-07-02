import pytest
from factory import cli, project as P, state


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_tick_runs_a_cycle():
    _seed()
    out = cli.tick("a", now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "completed"
    assert out["slug"] == "a"


def test_main_tick_returns_zero():
    _seed()
    rc = cli.main(["tick", "a", "--now", "2026-06-30T02:00:00Z"])
    assert rc == 0


def test_main_unknown_command_returns_nonzero():
    assert cli.main(["bogus"]) != 0
