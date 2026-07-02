"""KAI v1 build #4 — persistent goal store + non-destructive advance engine."""
import pytest

from app.services import _sqlite_util
from app.services.goals import engine, store


@pytest.fixture(autouse=True)
def _isolated_goals_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GOALS_DB_PATH", tmp_path / "goals.db")
    _sqlite_util.reset_for_tests()
    yield
    _sqlite_util.reset_for_tests()


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRouter:
    def __init__(self, content):
        self._content = content

    def complete(self, **kwargs):
        return _FakeResult(self._content)


def test_goal_crud_persists():
    g = store.create_goal("Register the LLC", done_when="LLC filed + EIN issued")
    assert g.status == "active" and g.title == "Register the LLC"
    got = store.get_goal(g.id)
    assert got is not None and got.done_when == "LLC filed + EIN issued"
    assert [x.id for x in store.list_goals(status="active")] == [g.id]
    store.update_goal(g.id, status="done", progress="filed")
    assert store.get_goal(g.id).status == "done"
    assert store.list_goals(status="active") == []


def test_update_goal_rejects_bad_status():
    g = store.create_goal("X")
    with pytest.raises(ValueError):
        store.update_goal(g.id, status="nonsense")


def test_advance_marks_done():
    store.create_goal("Ship v1")
    router = _FakeRouter('{"is_done": true, "progress": "shipped", "next_action": "", "blocked": false}')
    out = engine.advance_active_goals(router=router)
    assert len(out) == 1 and out[0]["status"] == "done"
    assert store.list_goals(status="active") == []


def test_advance_proposes_next_without_executing():
    g = store.create_goal("Ship v1")
    router = _FakeRouter('{"is_done": false, "progress": "in progress", "next_action": "write the README", "blocked": false}')
    out = engine.advance_active_goals(router=router)
    assert out[0]["status"] == "active"                 # stays active
    assert out[0]["proposed_next"] == "write the README"
    assert store.get_goal(g.id).next_action == "write the README"  # recorded, not executed


def test_advance_blocks():
    store.create_goal("Register LLC")
    router = _FakeRouter('{"is_done": false, "blocked": true, "blocked_reason": "need EIN first", "progress": "stuck", "next_action": ""}')
    out = engine.advance_active_goals(router=router)
    assert out[0]["status"] == "blocked"
    assert store.list_goals(status="blocked")[0].blocked_reason == "need EIN first"


def test_advance_failsoft_on_bad_json():
    store.create_goal("X")
    out = engine.advance_active_goals(router=_FakeRouter("not json at all"))
    assert out[0]["assessed"] is False
    assert store.list_goals(status="active")[0].title == "X"  # goal untouched


def test_goal_has_linked_plan_id_default_none():
    g = store.create_goal("X")
    assert g.linked_plan_id is None
    assert "linked_plan_id" in g.as_dict()


def test_update_goal_sets_linked_plan_id():
    g = store.create_goal("X")
    store.update_goal(g.id, linked_plan_id="42")
    assert store.get_goal(g.id).linked_plan_id == "42"


def test_migration_upgrades_preexisting_db(tmp_path, monkeypatch):
    """A goals.db created by build #4 (9 columns, no linked_plan_id) must be
    upgraded in place by _ensure_columns on first connect — without it, an
    update touching linked_plan_id raises 'no such column'."""
    import sqlite3
    from app.services import _sqlite_util
    from app.services.goals import store

    db = tmp_path / "old_goals.db"
    old_schema = """
    CREATE TABLE goals (
      id             TEXT PRIMARY KEY,
      title          TEXT NOT NULL,
      done_when      TEXT NOT NULL DEFAULT '',
      status         TEXT NOT NULL DEFAULT 'active',
      progress       TEXT NOT NULL DEFAULT '',
      next_action    TEXT NOT NULL DEFAULT '',
      blocked_reason TEXT NOT NULL DEFAULT '',
      created_at     TEXT NOT NULL,
      updated_at     TEXT NOT NULL
    );
    """
    con = sqlite3.connect(str(db))
    con.executescript(old_schema)
    con.execute(
        "INSERT INTO goals (id,title,done_when,status,progress,next_action,"
        "blocked_reason,created_at,updated_at) VALUES "
        "('g1','Old goal','','active','','','','2026-01-01T00:00:00','2026-01-01T00:00:00')"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(store, "GOALS_DB_PATH", db)
    _sqlite_util.reset_for_tests()

    # read path works and back-fills None for the new column
    g = store.get_goal("g1")
    assert g is not None and g.linked_plan_id is None

    # the update that would raise "no such column" without the ALTER now succeeds
    store.update_goal("g1", linked_plan_id="42")
    assert store.get_goal("g1").linked_plan_id == "42"

    _sqlite_util.reset_for_tests()
