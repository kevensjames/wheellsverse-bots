"""core/scoreboard.py snapshot(): revenue from the board's ledger by New York
day, MRR and users from Stripe's live subscriptions (stubbed here), places
scanned from SiteBoost's counter, and surfaces from public.sources. A surface
that is not measured reads not connected, value None, never a fake 0.
No network: the database is tests/board_fakes.py's FakeBoardDB."""
from datetime import datetime, timezone

import pytest

from core import scoreboard
from core.board import ledger, money
from tests import board_fakes as bf

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)      # Tue 3 Nov in New York


@pytest.fixture
def db(monkeypatch):
    bf.clear_connectors(monkeypatch)
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    monkeypatch.setattr(money, "_clock", lambda: NOW)
    monkeypatch.setattr("core.siteboost_state.stats", lambda: {"places_scanned": 40, "emails_sent": 10})
    return db


def _sale(external_id, at, cents):
    return ledger.LedgerRow(external_id=external_id, kind="sale", amount_minor=cents, currency="USD",
                            occurred_at=datetime.fromisoformat(at))


def test_snapshot_real_values_from_the_ledger_and_stripe(db, monkeypatch):
    monkeypatch.setenv("STRIPE_READ_KEY", bf.STRIPE_KEY)
    monkeypatch.setattr("core.board.connectors.stripe_sync.mrr", lambda key: (9900, 3, None))
    db.set_source("stripe", measured_from="2026-01-01", synced_through="2026-11-03T15:55:00+00:00")
    ledger.ingest_ledger("stripe", None, [_sale("txn_a", "2026-11-02T15:00:00+00:00", 12000),
                                          _sale("txn_b", "2026-06-01T15:00:00+00:00", 38000)])
    ledger.ingest_ledger("manual", None, [ledger.manual_row("manual:a", 2500, NOW, product="kdp_royalty")])
    snap = scoreboard.snapshot()
    m = snap["metrics"]
    assert m["mrr"]["connected"] is True and m["mrr"]["value"] == 99.0
    assert m["users"]["value"] == 3
    assert m["revenue_month"]["value"] == 145.0                # 120.00 + 25.00 in the last 30 New York days
    assert m["revenue_all_time"]["value"] == 525.0             # since Stripe's measured_from
    assert m["places_scanned"]["value"] == 40 and m["places_scanned"]["label"] == "places scanned (outreach)"
    assert "deploy resets it" in m["places_scanned"]["note"]
    assert "leads" not in m and "conversion" not in m
    assert m["deployments"]["value"] == 0          # honest: nothing deployed
    assert snap["surfaces"]["stripe"] is True and snap["surfaces"]["siteboost"] is True
    assert "instantly_stats" not in snap["surfaces"] and snap["surfaces"]["instantly"] is False
    assert snap["headline"] == "MRR $99.00 · users 3 · places scanned 40 · 0 prod deployments"


def test_not_connected_is_never_a_fake_zero(db, monkeypatch):
    # Stripe unconfigured -> revenue/mrr/users are NOT measured (None), not fake 0.
    monkeypatch.setattr("core.siteboost_state.stats", lambda: {"places_scanned": 0, "emails_sent": 0})
    db.set_source("stripe", measured_from="2026-01-01", synced_through="2026-11-03T15:55:00+00:00")
    snap = scoreboard.snapshot()
    m = snap["metrics"]
    assert m["mrr"]["connected"] is False and m["mrr"]["value"] is None
    assert m["users"]["connected"] is False and m["users"]["value"] is None
    assert m["revenue_month"]["connected"] is False and m["revenue_month"]["value"] is None
    assert "Stripe key not set" in m["revenue_month"]["note"]
    assert m["open_bugs"]["connected"] is False and m["open_bugs"]["value"] is None
    # places scanned ARE connected (file-backed) and a real 0
    assert m["places_scanned"]["connected"] is True and m["places_scanned"]["value"] == 0
    # unconnected commerce surfaces are named plainly, not faked
    assert snap["surfaces"]["ds24"] is False
    assert snap["surfaces"]["stan"] is False
    assert snap["surfaces"]["bigcommerce"] is False
    assert snap["surfaces"]["stripe"] is False                 # its key is not set here
    assert snap["headline"].startswith("MRR — · users — · places scanned 0")


def test_the_database_down_reads_not_connected(db, monkeypatch):
    monkeypatch.setenv("STRIPE_READ_KEY", bf.STRIPE_KEY)
    monkeypatch.setattr("core.board.connectors.stripe_sync.mrr", lambda key: (9900, 3, None))
    db.down = True
    snap = scoreboard.snapshot()
    m = snap["metrics"]
    assert m["revenue_month"]["value"] is None and m["revenue_all_time"]["value"] is None
    assert m["revenue_month"]["note"] == "not measured: database not connected"
    assert m["mrr"]["value"] == 99.0                            # read from Stripe, not the database
    assert {k: snap["surfaces"][k] for k in ("stripe", "kit", "instantly", "meta_ads")} == dict.fromkeys(
        ("stripe", "kit", "instantly", "meta_ads"), False)
