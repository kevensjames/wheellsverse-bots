"""The board's day view (core/board/day.py) and GET /api/board/day: one New York
calendar day, from Stripe's balance transactions to the revenue card. A source
that is not connected reads null, never $0. No network: Stripe and Supabase are
faked in tests/board_fakes.py."""
from datetime import date, datetime, timedelta, timezone

import pytest

from core.board import day as board_day
from core.board.connectors import stripe_sync
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York


@pytest.fixture
def db(monkeypatch):
    return bf.install_board(monkeypatch)


@pytest.fixture
def stripe(monkeypatch):
    return bf.install_stripe(monkeypatch)


@pytest.fixture
def synced(db, stripe):
    """The plan's fixture day, synced at 07:00 on 2 Nov."""
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    return db


def _revenue(view):
    return view["numbers"]["revenue"]


def test_the_fixture_day_matches_stripe_to_the_cent(synced):
    view = board_day.day_view(date(2026, 11, 1))
    rev = _revenue(view)
    assert (rev["value"], rev["connected"], rev["state"], rev["source"]) == (1000, True, "final", "stripe")
    assert rev["net_usd_cents"] == 1000          # 29.99 sale - 19.99 refund - 15.00 dispute + 15.00 won back
    assert (rev["gross_usd_cents"], rev["refunds_usd_cents"], rev["disputes_usd_cents"]) == (2999, 1999, 0)
    assert rev["fees_usd_cents"] == 317          # 1.17 + 15.00 dispute fee - 15.00 returned + 2.00 Stripe fee
    assert rev["by_source"] == {"stripe": 1000}
    assert rev["counts"] == {"sale": 1, "refund": 1, "dispute": 1, "dispute_reversal": 1}
    assert (view["day"], view["label"], view["hours_in_day"]) == ("2026-11-01", "Sun 1 Nov", 25)
    assert view["database"] == "connected" and view["sources"][0]["state"] == "final"


def test_every_sale_is_listed_in_time_order_with_buyers_masked(synced):
    sales = board_day.day_view(date(2026, 11, 1))["sales"]
    assert [(s["kind"], s["amount_usd_cents"]) for s in sales] == [
        ("dispute", -1500), ("refund", -1999), ("dispute_reversal", 1500), ("sale", 2999)]
    sale = sales[-1]
    assert sale["product"] == "AI Entrepreneur Blueprint Kit" and sale["buyer"] == "b***@example.com"
    assert sale["at"].startswith("2026-11-02T04:30:00")           # 23:30 on 1 Nov in New York
    refund = sales[1]
    assert refund["product"] == "Toodle Guide" and refund["buyer"] == "o***@example.com"   # from its sale
    assert all(s["buyer"] is None or s["buyer"][1:4] == "***" for s in sales)    # never a whole address
    assert "buyer@example.com" not in str(sales) and "old@example.com" not in str(sales)


def test_new_york_day_boundaries_and_the_25_hour_day(db, stripe):
    edges = [("txn_a", "2026-11-01T03:59:59Z", 100),     # 23:59:59 EDT on 31 Oct
             ("txn_b", "2026-11-01T04:00:00Z", 200),     # 00:00 EDT on 1 Nov: the day starts
             ("txn_c", "2026-11-01T05:30:00Z", 400),     # 01:30 EDT
             ("txn_d", "2026-11-01T06:30:00Z", 800),     # 01:30 EST: the hour that repeats
             ("txn_e", "2026-11-02T04:59:59Z", 1600),    # 23:59:59 EST: the day's last second
             ("txn_f", "2026-11-02T05:00:00Z", 3200)]    # 00:00 EST on 2 Nov
    stripe.add([bf.charge_bt(txn, "ch_" + txn, cents, at, 0) for txn, at, cents in edges])
    assert stripe_sync.run(now=NOW + timedelta(days=1))["status"] == "ok"
    oct31, nov1, nov2 = (board_day.day_view(d) for d in (date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)))
    assert _revenue(oct31)["value"] == 100
    assert _revenue(nov1)["value"] == 200 + 400 + 800 + 1600 and nov1["hours_in_day"] == 25
    assert _revenue(nov2)["value"] == 3200 and nov2["hours_in_day"] == 24
    assert board_day.hours_note(25) == "a 25-hour day: clocks went back"
    assert board_day.hours_note(23) == "a 23-hour day: clocks went forward"


def test_a_measured_day_with_no_sales_is_a_real_zero(db, stripe):
    db.set_source(measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")
    rev = _revenue(board_day.day_view(date(2026, 10, 15)))
    assert (rev["value"], rev["connected"], rev["state"]) == (0, True, "final")
    assert rev["fees_usd_cents"] == 0


def test_no_stripe_key_reads_not_connected_never_zero(synced, monkeypatch):
    monkeypatch.delenv("STRIPE_READ_KEY")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    view = board_day.day_view(date(2026, 11, 1))
    rev = _revenue(view)
    assert (rev["value"], rev["connected"], rev["state"]) == (None, False, "not_connected")
    assert rev["net_usd_cents"] is None and rev["fees_usd_cents"] is None
    assert "STRIPE_READ_KEY" in rev["note"]
    assert view["sales"] == [] and view["products"] == []
    assert view["sources"][0]["connected"] is False


def test_a_day_before_measurement_or_before_any_sync_is_not_connected(db, stripe):
    rev = _revenue(board_day.day_view(date(2026, 11, 1)))
    assert (rev["value"], rev["connected"]) == (None, False) and "no Stripe sync has completed" in rev["note"]
    db.set_source(measured_from="2026-06-01", synced_through="2026-11-02T11:55:00Z")
    rev = _revenue(board_day.day_view(date(2026, 5, 31)))
    assert (rev["value"], rev["state"]) == (None, "not_connected") and "not measured before 2026-06-01" in rev["note"]


def test_a_day_not_synced_to_its_end_is_partial(db, stripe):
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc))["status"] == "ok"
    rev = _revenue(board_day.day_view(date(2026, 11, 1)))
    assert (rev["value"], rev["connected"], rev["state"]) == (-1999, True, "partial")   # so far: refund, dispute pair
    assert "synced to 17:55 on Sun 1 Nov (New York)" in rev["note"]


def test_the_database_down_or_never_migrated_reads_not_connected(db, stripe):
    db.down = True
    view = board_day.day_view(date(2026, 11, 1))
    assert view["database"] == "not_connected"
    assert _revenue(view)["value"] is None and _revenue(view)["note"] == "database not connected"
    db.down = False
    db.sources.clear()
    view = board_day.day_view(date(2026, 11, 1))
    assert _revenue(view)["value"] is None and "migration" in _revenue(view)["note"]
    db.fail["rpc/board_day"] = 500
    assert board_day.day_view(None)["numbers"]["revenue"]["connected"] is False


def test_notes_say_which_key_reads_stripe_and_name_the_last_error(synced, monkeypatch):
    monkeypatch.delenv("STRIPE_READ_KEY")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_FAKEsecret01")
    synced.set_source(last_error="Stripe HTTP 401 (invalid_request_error)",
                      last_error_at="2026-11-02T12:07:00Z")
    note = _revenue(board_day.day_view(date(2026, 11, 1)))["note"]
    assert "read with STRIPE_SECRET_KEY" in note and "STRIPE_READ_KEY is safer" in note
    assert "last sync failed: Stripe HTTP 401" in note
    assert "sk_live" not in note


def test_a_test_mode_key_reads_not_connected(synced, monkeypatch):
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_test_FAKEboardTest2")
    view = board_day.day_view(date(2026, 11, 1))
    rev = _revenue(view)
    assert (rev["value"], rev["connected"], rev["state"]) == (None, False, "not_connected")
    assert "STRIPE_READ_KEY is a test-mode key: test payments are not revenue" in rev["note"]
    assert view["sales"] == [] and "rk_test_FAKEboardTest2" not in str(view)


def test_an_ok_runs_warning_is_shown_and_not_called_a_failure(synced, stripe):
    odd = bf.plain_bt("txn_odd", "payment_reversal", -2999, "2026-11-01T21:00:00Z", category="other")
    stripe.add([odd])
    assert stripe_sync.run(now=NOW + timedelta(hours=1))["status"] == "ok"
    view = board_day.day_view(date(2026, 11, 1))
    note = _revenue(view)["note"]
    assert ("last sync: skipped 1 balance transaction of a type the board does not map (payment_reversal)"
            in note) and "failed" not in note
    assert "last sync: skipped 1 balance transaction" in board_day.render_report(view)    # the morning message
    stripe.balance_transactions.remove(odd)
    stripe.key = "rk_live_FAKEotherKey1"                                   # the key stops working
    assert stripe_sync.run(now=NOW + timedelta(hours=2))["status"] == "failed"
    assert "last sync failed: Stripe HTTP 401" in _revenue(board_day.day_view(date(2026, 11, 1)))["note"]
    stripe.key = bf.STRIPE_KEY
    assert stripe_sync.run(now=NOW + timedelta(hours=3))["error"] is None
    assert "last sync" not in _revenue(board_day.day_view(date(2026, 11, 1)))["note"]


def test_a_non_usd_settlement_is_counted_not_summed(db, stripe):
    stripe.add([bf.charge_bt("txn_gbp", "ch_g", 1000, "2026-11-01T16:00:00Z", 40, currency="gbp",
                             settled_currency="gbp"),
                bf.charge_bt("txn_usd", "ch_u", 500, "2026-11-01T17:00:00Z", 30)])
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    rev = _revenue(board_day.day_view(date(2026, 11, 1)))
    assert rev["value"] == 500 and rev["unconverted_rows"] == 1
    assert "1 row has no USD amount, left out of the totals" in rev["note"]
    assert "fees unknown on 1 row" in rev["note"]


def test_parse_day_takes_only_a_calendar_day():
    assert board_day.parse_day("2026-11-01") == date(2026, 11, 1)
    for bad in ("2026-11-1", "2026-13-01", "yesterday", "2026-11-01T00:00", ""):
        with pytest.raises(ValueError):
            board_day.parse_day(bad)
    assert board_day.yesterday_ny(datetime(2026, 11, 2, 3, 59, tzinfo=timezone.utc)) == date(2026, 10, 31)
    assert board_day.yesterday_ny(datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)) == date(2026, 11, 1)


# ─── the route: GET /api/board/day ──────────────────────────────────────────

@pytest.fixture
def owner(monkeypatch):
    fake = bf.install(monkeypatch)
    return bf.client(monkeypatch), bf.cookie(fake.add_session())


def test_the_day_route_needs_the_owner_session(owner, synced):
    client, cookie = owner
    assert client.get("/api/board/day").status_code == 401
    assert synced.rpc_calls("board_day") == []
    r = client.get("/api/board/day?date=2026-11-01", headers=cookie)
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    assert r.json()["numbers"]["revenue"]["value"] == 1000


def test_the_day_route_takes_date_or_d_and_defaults_to_yesterday_in_sql(owner, synced):
    client, cookie = owner
    assert client.get("/api/board/day?d=2026-11-01", headers=cookie).json()["day"] == "2026-11-01"
    assert client.get("/api/board/day?date=2026-11-01&d=2026-11-01", headers=cookie).status_code == 200
    assert client.get("/api/board/day?date=2026-11-01&d=2026-10-31", headers=cookie).status_code == 422
    for bad in ("1-11-2026", "2026-02-30", "x" * 40):
        assert client.get(f"/api/board/day?date={bad}", headers=cookie).status_code == 422
    synced.calls.clear()
    synced.clock = lambda: NOW
    r = client.get("/api/board/day", headers=cookie)
    assert r.json()["day"] == "2026-11-01"
    assert synced.rpc_calls("board_day") == [{"p_day": None}]      # yesterday is decided in SQL


def test_the_day_route_without_stripe_shows_not_connected(owner, db, monkeypatch):
    client, cookie = owner
    monkeypatch.delenv("STRIPE_READ_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    j = client.get("/api/board/day?date=2026-11-01", headers=cookie).json()
    assert j["numbers"]["revenue"]["value"] is None and j["numbers"]["revenue"]["connected"] is False
    assert "$0" not in str(j)


def test_the_board_page_shows_the_day_and_carries_no_secret(owner, monkeypatch):
    client, cookie = owner
    monkeypatch.setenv("STRIPE_READ_KEY", bf.STRIPE_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_board_page_test_secret")
    r = client.get("/admin/scoreboard", headers=cookie)
    assert r.status_code == 200
    for piece in ("/api/board/day", "/api/board/sync/stripe", 'id="rev-card"', 'id="sales-body"',
                  'id="day-sources"', "esc(", "credentials:'same-origin'"):
        assert piece in r.text
    for secret in (bf.STRIPE_KEY, "whsec_board_page_test_secret", bf.SERVICE, bf.ANON, "X-API-Key"):
        assert secret not in r.text
