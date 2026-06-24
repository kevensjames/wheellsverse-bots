from core import scoreboard


def test_snapshot_real_values_and_derivations(monkeypatch):
    monkeypatch.setattr(
        "core.revenue.get_dashboard",
        lambda **k: {"stripe": {"configured": True, "active_subscriptions": 3,
                                "trialing_subscriptions": 1, "canceled_30d": 0},
                     "period": {"month": 120, "all_time": 500}, "mrr": 99},
    )
    monkeypatch.setattr("core.siteboost_state.stats",
                        lambda: {"places_scanned": 40, "emails_sent": 10})
    m = scoreboard.snapshot()["metrics"]
    assert m["mrr"]["connected"] is True and m["mrr"]["value"] == 99
    assert m["users"]["value"] == 3
    assert m["leads"]["value"] == 40
    assert m["conversion"]["value"] == round(3 / 40, 4)
    assert m["deployments"]["value"] == 0          # honest: nothing deployed


def test_not_connected_is_never_a_fake_zero(monkeypatch):
    # Stripe unconfigured -> revenue/mrr/users are NOT measured (None), not fake 0.
    monkeypatch.setattr("core.revenue.get_dashboard",
                        lambda **k: {"stripe": {"configured": False}, "period": {}, "mrr": 0})
    monkeypatch.setattr("core.siteboost_state.stats",
                        lambda: {"places_scanned": 0, "emails_sent": 0})
    snap = scoreboard.snapshot()
    m = snap["metrics"]
    assert m["mrr"]["connected"] is False and m["mrr"]["value"] is None
    assert m["users"]["connected"] is False and m["users"]["value"] is None
    assert m["open_bugs"]["connected"] is False and m["open_bugs"]["value"] is None
    # leads ARE connected (file-backed) and a real 0
    assert m["leads"]["connected"] is True and m["leads"]["value"] == 0
    # unconnected commerce surfaces are named plainly, not faked
    assert snap["surfaces"]["ds24"] is False
    assert snap["surfaces"]["stan"] is False
    assert snap["surfaces"]["bigcommerce"] is False
