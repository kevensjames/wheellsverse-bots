"""KAI v1 build #4b — goal-loop heartbeat scheduler."""
import pytest

from app.services.goals import scheduler


class _FakeSession:
    def close(self):
        pass


def test_start_disabled_returns_false(monkeypatch):
    monkeypatch.delenv("KAI_GOALS_HEARTBEAT_ENABLED", raising=False)
    assert scheduler.start() is False
    assert scheduler.is_running() is False


def test_status_shape(monkeypatch):
    monkeypatch.setenv("KAI_GOALS_HEARTBEAT_HOUR_UTC", "8")
    st = scheduler.status()
    assert set(st) == {"enabled", "running", "hour_utc", "scope_on", "notify"}
    assert st["hour_utc"] == 8


def test_run_cycle_summarizes(monkeypatch):
    monkeypatch.setattr("app.database.SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr("app.services.router.build_default_router", lambda s: object())
    monkeypatch.setattr(
        "app.services.goals.engine.advance_active_goals",
        lambda **kw: [
            {"goal_id": "a", "status": "done", "proposed_next": "", "assessed": True},
            {"goal_id": "b", "status": "active", "proposed_next": "write readme", "assessed": True},
        ],
    )
    res = scheduler.run_cycle(notify=False)
    assert res["advanced"] == 2
    assert res["done"] == 1
    assert res["proposals"] == 1
    assert res["notified"] is False


def test_run_cycle_failsoft(monkeypatch):
    monkeypatch.setattr("app.database.SessionLocal", lambda: _FakeSession())

    def _boom(s):
        raise RuntimeError("no router")

    monkeypatch.setattr("app.services.router.build_default_router", _boom)
    res = scheduler.run_cycle(notify=False)
    assert res["advanced"] == 0
    assert "error" in res


def test_notify_sends_summary(monkeypatch):
    sent = {}

    def _fake_send(text):
        sent["text"] = text
        return True

    monkeypatch.setattr("app.services.supreme.scanner.telegram_send", _fake_send)
    ok = scheduler._notify([
        {"goal_id": "b", "status": "active", "proposed_next": "write readme", "assessed": True},
    ])
    assert ok is True
    assert "write readme" in sent["text"]


def test_notify_noop_when_nothing(monkeypatch):
    assert scheduler._notify([]) is False


def test_app_mounts_goals_and_lifespan_safe():
    # importing the app must not raise, and the goals routes must be mounted
    from app.main import app
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/admin/goals/stats" in paths
    assert "/admin/goals/{goal_id}/approve-proposal" in paths
    # lifespan wiring imports the scheduler start/stop by name — assert they exist
    from app.services.goals import scheduler as sch
    assert callable(sch.start) and callable(sch.stop)
