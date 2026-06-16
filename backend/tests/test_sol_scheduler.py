"""Sol scheduler — gating, tick behavior (reminder + non-destructive autopilot).

No real Telegram, no real network: observability.notify is monkeypatched.
"""
import pytest

from app.services.sol import storage as st
from app.services.sol import engine, scheduler
from app.services import observability


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SOL_DB_PATH", tmp_path / "sol.db")
    st.init_db()
    monkeypatch.setattr(engine, "MAX_RETRIES", 2)
    for v in ("KAI_SOL_SCHEDULER_ENABLED", "KAI_SOL_AUTOPILOT",
              "KAI_SCOPE_SOL", "KAI_SOL_SCHEDULER_HOUR_UTC"):
        monkeypatch.delenv(v, raising=False)
    yield


@pytest.fixture
def captured_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(observability, "notify", lambda text: sent.append(text))
    return sent


def _active_circle(n=3, contribution_cents=20000):
    c = engine.create_circle("Scheduler Circle", contribution_cents, n)
    for i in range(n):
        engine.add_member(c.id, f"M{i}", dwolla_customer_id=f"cust{i}",
                          funding_source_href=f"https://api-sandbox.dwolla.com/funding-sources/fs{i}")
    engine.activate_circle(c.id)
    return c


def _pay_cycle_to_paid(cycle_id):
    for ct in st.list_contributions(cycle_id):
        engine.mark_contribution_result(ct.id, True)
    out = engine.close_collection_and_create_payout(cycle_id)
    engine.mark_payout_result(out["payout"]["id"], True)


# ─── gating + status ───────────────────────────────────────────────────
def test_start_disabled_by_default():
    assert scheduler.start() is False
    assert scheduler.is_running() is False


def test_status_reflects_env(monkeypatch):
    monkeypatch.setenv("KAI_SOL_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("KAI_SOL_SCHEDULER_HOUR_UTC", "9")
    monkeypatch.setenv("KAI_SOL_AUTOPILOT", "1")
    s = scheduler.status()
    assert s["enabled"] is True and s["hour_utc"] == 9 and s["autopilot"] is True
    assert s["running"] is False  # status doesn't start the thread


def test_hour_clamps_and_defaults(monkeypatch):
    monkeypatch.setenv("KAI_SOL_SCHEDULER_HOUR_UTC", "99")
    assert scheduler.status()["hour_utc"] == 23
    monkeypatch.setenv("KAI_SOL_SCHEDULER_HOUR_UTC", "nonsense")
    assert scheduler.status()["hour_utc"] == 14  # default


# ─── tick behavior ─────────────────────────────────────────────────────
def test_tick_notifies_on_due_actions(captured_notifications):
    _active_circle(n=3)  # fresh cycle 1 → collect_due
    res = scheduler.run_sol_tick(autopilot=False)
    assert res["scanned"] >= 1
    assert res["notified"] is True
    assert len(captured_notifications) == 1
    assert "Sol circles" in captured_notifications[0]


def test_tick_no_actions_no_notify(captured_notifications):
    # a forming (not active) circle → nothing due
    engine.create_circle("forming-only", 20000, 3)
    res = scheduler.run_sol_tick(autopilot=False)
    assert res["scanned"] == 0
    assert res["notified"] is False
    assert captured_notifications == []


def test_tick_does_not_move_money(captured_notifications):
    # The tick must NEVER create transfers — contributions stay pending.
    c = _active_circle(n=3)
    cyc = st.list_cycles(c.id)[-1]
    scheduler.run_sol_tick(autopilot=True)
    contribs = st.list_contributions(cyc.id)
    assert all(ct.status == "pending" and ct.dwolla_transfer_url is None for ct in contribs)


def test_autopilot_advances_paid_cycle(captured_notifications):
    c = _active_circle(n=3)
    cyc1 = st.list_cycles(c.id)[-1]
    _pay_cycle_to_paid(cyc1.id)              # cycle 1 → paid → advance_ready
    assert len(st.list_cycles(c.id)) == 1
    res = scheduler.run_sol_tick(autopilot=True)
    assert len(res["advanced"]) == 1
    assert len(st.list_cycles(c.id)) == 2    # cycle 2 auto-opened (no money)


def test_no_autopilot_leaves_cycle_unadvanced(captured_notifications):
    c = _active_circle(n=3)
    cyc1 = st.list_cycles(c.id)[-1]
    _pay_cycle_to_paid(cyc1.id)
    res = scheduler.run_sol_tick(autopilot=False)
    assert res["advanced"] == []
    assert len(st.list_cycles(c.id)) == 1    # not advanced — operator must act
