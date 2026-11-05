"""The board's day view (core/board/day.py) and GET /api/board/day: one New York
calendar day, from Stripe's balance transactions to the revenue card, and Kit's
opt-ins, Instantly's replies, Meta's spend and the stop rule to theirs. A
source that is not connected reads null, never 0. No network: Stripe and
Supabase are faked in tests/board_fakes.py; Kit, Instantly and Meta are only
configured here (their rows go in through core.board.ledger, as their syncs
write them). The page's script runs in Node, when it is installed, against a
stub DOM and the day JSON."""
import itertools
import json
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.board import day as board_day
from core.board import ledger
from core.board.connectors import meta_sync, stripe_sync
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York


@pytest.fixture
def db(monkeypatch):
    return bf.install_board(monkeypatch)


@pytest.fixture
def stripe(monkeypatch):
    return bf.install_stripe(monkeypatch)


@pytest.fixture(autouse=True)
def no_connector_settings(monkeypatch):
    """Kit, Instantly and Meta start unconfigured, whatever this machine has set."""
    bf.clear_connectors(monkeypatch)


@pytest.fixture
def synced(db, stripe):
    """The plan's fixture day, synced at 07:00 on 2 Nov."""
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    return db


@pytest.fixture
def leads(db, monkeypatch):
    """The plan's opt-ins, replies and Meta spend, every connector configured,
    each source measured from 1 Jan and synced to 06:55 on 2 Nov."""
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db)
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
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" "FAKEsecret01")
    synced.set_source(last_error="Stripe HTTP 401 (invalid_request_error)",
                      last_error_at="2026-11-02T12:07:00Z")
    note = _revenue(board_day.day_view(date(2026, 11, 1)))["note"]
    assert "read with STRIPE_SECRET_KEY" in note and "STRIPE_READ_KEY is safer" in note
    assert "last sync failed: Stripe HTTP 401" in note
    assert "sk_live" not in note


def test_a_test_mode_key_reads_not_connected(synced, monkeypatch):
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_test_" "FAKEboardTest2")
    view = board_day.day_view(date(2026, 11, 1))
    rev = _revenue(view)
    assert (rev["value"], rev["connected"], rev["state"]) == (None, False, "not_connected")
    assert "STRIPE_READ_KEY is a test-mode key: test payments are not revenue" in rev["note"]
    assert view["sales"] == [] and "rk_test_" "FAKEboardTest2" not in str(view)


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
    stripe.key = "rk_live_" "FAKEotherKey1"                                # the key stops working
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


# ─── the four numbers: opt-ins, replies, spend and the stop rule ────────────

_subscribers = itertools.count(100)


def _toodle_spend(first: str, days: int, cents: int, currency: str = "USD") -> None:
    """Toodle spend on `days` ad-account days from `first`, as the Meta sync writes it."""
    start = date.fromisoformat(first)
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend((start + timedelta(days=i)).isoformat(), cents,
                                                       currency=currency) for i in range(days)])


def _optins(channel, n: int) -> None:
    """n Toodle opt-ins on 28 Oct to 1 Nov in New York, each from a new subscriber."""
    tags = ("toodle", "meta_ad") if channel == "meta" else ("toodle",)
    ledger.ingest_leads("kit", None, [bf.optin(next(_subscribers), f"2026-10-{28 + i % 4}T16:00:00Z", channel,
                                               tags=tags) for i in range(n)])


def _measured(db, synced_through="2026-11-02T11:55:00Z", **sources):
    """Kit, Instantly and Meta measured from 1 Jan and synced to `synced_through`,
    with the Meta run that labelled the spend from the plan's Toodle campaign."""
    bf.record_meta_run(db)
    for source_id in ("kit", "instantly", "meta_ads"):
        db.set_source(source_id, measured_from="2026-01-01", synced_through=synced_through,
                      **sources.get(source_id, {}))


def test_the_plans_fixture_day_has_all_four_numbers(synced, leads):
    view = board_day.day_view(date(2026, 11, 1))
    n = view["numbers"]
    assert list(n) == ["optins", "replies", "revenue", "spend", "cpl"]
    assert n["optins"] == {"value": 2, "connected": True, "state": "final", "source": "kit", "note": "",
                           "by_channel": {"meta": 1, "organic": 1}, "target": 3}
    assert n["replies"] == {"value": 1, "connected": True, "state": "final", "source": "instantly", "note": "",
                            "value_7d": 2, "auto_replies_ignored": 1, "target_per_week": 1}
    assert n["spend"] == {"value": 502, "connected": True, "state": "final", "source": "meta_ads", "note": "",
                          "toodle_usd_cents": 502, "all_usd_cents": 1502, "toodle_link_clicks": 9,
                          "impressions": 10200, "unconverted_rows": 0, "day_tz": "America/New_York"}
    assert n["cpl"] == {"value": 628, "connected": True, "state": "final", "source": "meta_ads, kit", "note": "",
                        "verdict": "stop",
                        "verdict_text": "STOP: $6.28 per Meta opt-in over the last 5 spend days, above $5.00.",
                        "first_day": "2026-10-28", "last_day": "2026-11-01", "spend_days": 5,
                        "spend_usd_cents": 2510, "unconverted_spend_rows": 0, "meta_optins": 4, "toodle_optins": 5,
                        "cpl_meta_usd_cents": 628, "cpl_all_usd_cents": 502, "spend_days_needed": 5,
                        "stop_above_cents": 500}
    # the sale is the meta opt-in's buyer: attributed through the lead's email, as in the plan
    assert (n["revenue"]["value"], n["revenue"]["attributed_usd_cents"]) == (1000, 2999)
    assert n["revenue"]["by_channel"] == {"meta": 2999, "unattributed": -1999}
    assert [(s["id"], s["name"], s["state"], s["connected"], s["note"]) for s in view["sources"]] == [
        ("stripe", "Stripe", "final", True, ""), ("kit", "Kit", "final", True, ""),
        ("instantly", "Instantly", "final", True, ""), ("meta_ads", "Meta", "final", True, "")]


@pytest.mark.parametrize("source, number, settings, reason", [
    ("kit", "optins", {}, "Kit key not set: KIT_API_KEY"),
    ("kit", "optins", {"KIT_API_KEY": "kit key with spaces"},
     "KIT_API_KEY holds spaces or other characters a key cannot have"),
    ("kit", "optins", {"KIT_API_KEY": bf.KIT_KEY}, "Toodle tags not set: BOARD_TOODLE_KIT_TAGS"),
    ("instantly", "replies", {}, "no Instantly key: set INSTANTLY_API_KEY (a key with the emails:read scope)"),
    ("instantly", "replies", {"INSTANTLY_API_KEY": bf.INSTANTLY_KEY, "BOARD_SITEBOOST_CAMPAIGN_IDS": "not-a-uuid"},
     "BOARD_SITEBOOST_CAMPAIGN_IDS: entry 1 is not an Instantly campaign id"),
    ("meta_ads", "spend", {}, "Meta token not set: META_INSIGHTS_TOKEN (or META_ACCESS_TOKEN)"),
    ("meta_ads", "spend", {"META_INSIGHTS_TOKEN": bf.META_TOKEN},
     "Meta ad account not set: AD_ACCOUNT_ID (or FB_AD_ACCOUNT_ID)"),
    ("meta_ads", "spend", {"META_INSIGHTS_TOKEN": bf.META_TOKEN, "AD_ACCOUNT_ID": "act_12x"},
     "AD_ACCOUNT_ID is not an ad account number (digits, with or without act_)"),
])
def test_a_connector_that_is_not_configured_reads_not_connected_with_its_own_reason(
        db, monkeypatch, source, number, settings, reason):
    bf.configure_connectors(monkeypatch, *({"kit", "instantly", "meta_ads"} - {source}))
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    bf.load_fixture_leads(db)                  # rows and sync states are there: only the setting is missing
    view = board_day.day_view(date(2026, 11, 1))
    n = view["numbers"][number]
    assert (n["value"], n["connected"], n["state"], n["note"]) == (None, False, "not_connected", reason)
    extras = {"optins": ("by_channel",), "replies": ("value_7d", "auto_replies_ignored"),
              "spend": ("toodle_usd_cents", "all_usd_cents", "toodle_link_clicks", "unconverted_rows")}[number]
    assert all(n[k] is None for k in extras)
    pill = next(s for s in view["sources"] if s["id"] == source)
    assert (pill["state"], pill["connected"], pill["note"]) == ("not_connected", False, reason)
    cpl = view["numbers"]["cpl"]
    if source == "instantly":
        assert cpl["verdict"] == "stop"                             # the stop rule needs Meta and Kit only
    else:
        assert (cpl["value"], cpl["verdict"], cpl["connected"], cpl["state"]) == (None, None, False, "not_connected")
        assert cpl["note"] == f"needs {'Meta' if source == 'meta_ads' else 'Kit'}"
        assert cpl["spend_usd_cents"] is None and cpl["meta_optins"] is None
    others = [k for k in ("optins", "replies", "spend") if k != number]
    assert all(view["numbers"][k]["connected"] and view["numbers"][k]["value"] is not None for k in others)
    for value in (bf.KIT_KEY, bf.INSTANTLY_KEY, bf.META_TOKEN, "kit key with spaces"):
        assert value not in str(view)


def test_measured_days_with_no_leads_or_spend_are_real_zeros(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    _measured(db)
    n = board_day.day_view(date(2026, 10, 15))["numbers"]
    assert (n["optins"]["value"], n["optins"]["by_channel"], n["optins"]["state"]) == (0, {}, "final")
    assert (n["replies"]["value"], n["replies"]["value_7d"], n["replies"]["auto_replies_ignored"]) == (0, 0, 0)
    assert (n["spend"]["value"], n["spend"]["all_usd_cents"], n["spend"]["toodle_link_clicks"]) == (0, 0, 0)
    assert (n["cpl"]["verdict"], n["cpl"]["connected"], n["cpl"]["spend_days"]) == ("no_spend", True, 0)
    assert n["cpl"]["verdict_text"] == "No Toodle ad spend in the last 30 days."
    assert n["cpl"]["note"] == ""              # the last Meta sync saw spend for every listed campaign


@pytest.mark.parametrize("source, number, name", [("kit", "optins", "Kit"), ("instantly", "replies", "Instantly"),
                                                  ("meta_ads", "spend", "Meta")])
def test_a_day_before_kit_instantly_or_meta_measured_or_synced_is_not_connected(db, monkeypatch, source, number,
                                                                                 name):
    bf.configure_connectors(monkeypatch)
    n = board_day.day_view(date(2026, 11, 1))["numbers"][number]
    assert (n["value"], n["connected"], n["note"]) == (None, False, f"no {name} sync has completed yet")
    db.set_source(source, measured_from="2026-11-02", synced_through="2026-11-03T11:55:00Z")
    n = board_day.day_view(date(2026, 11, 1))["numbers"][number]
    assert (n["value"], n["state"], n["note"]) == (None, "not_connected", "not measured before 2026-11-02")
    db.set_source(source, measured_from="2026-01-01", enabled=False)
    n = board_day.day_view(date(2026, 11, 1))["numbers"][number]
    assert (n["value"], n["note"]) == (None, f"the {source} source is disabled")


def test_a_day_not_synced_to_its_end_is_partial_and_says_how_far(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db, synced_through="2026-11-01T22:00:00Z")          # 17:00 EST on Sun 1 Nov
    n = board_day.day_view(date(2026, 11, 1))["numbers"]
    for name in ("optins", "replies", "spend"):
        assert (n[name]["connected"], n[name]["state"]) == (True, "partial"), name
        assert n[name]["note"] == "synced to 17:00 on Sun 1 Nov (New York)", name
    assert (n["optins"]["value"], n["replies"]["value"], n["spend"]["value"]) == (2, 1, 502)    # so far
    cpl = n["cpl"]                      # Kit has not read the evening of the last spend day: no verdict yet
    assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == (None, None, True, "partial")
    assert cpl["note"] == "waiting for Kit to finish Sun 1 Nov"
    assert (cpl["spend_usd_cents"], cpl["meta_optins"]) == (None, None)


def test_a_day_no_sync_has_reached_has_no_number_rather_than_zero(db, stripe, monkeypatch):
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db, synced_through="2026-10-31T12:00:00Z")          # 08:00 on Sat 31 Oct
    db.set_source("stripe", measured_from="2026-01-01", synced_through="2026-10-31T12:00:00Z")
    view = board_day.day_view(date(2026, 11, 1))
    for name in ("optins", "replies", "revenue", "spend"):
        n = view["numbers"][name]
        assert (n["value"], n["connected"], n["state"]) == (None, True, "partial"), name
        assert n["note"] == "not synced into this day yet: synced to 08:00 on Sat 31 Oct (New York)", name
    assert view["numbers"]["optins"]["by_channel"] is None and view["numbers"]["replies"]["value_7d"] is None
    assert view["numbers"]["revenue"]["net_usd_cents"] is None and view["sales"] == []
    cpl = view["numbers"]["cpl"]
    assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == (None, None, True, "partial")
    assert cpl["note"] == "waiting for Kit to finish Sun 1 Nov"
    text = board_day.render_report(view)
    assert ("Toodle opt-ins: no number yet (not synced into this day yet: synced to 08:00 on Sat 31 Oct "
            "(New York))") in text
    assert "Stop rule: no verdict yet (waiting for Kit to finish Sun 1 Nov)" in text
    assert ": 0 " not in text and "$0.00" not in text


def test_a_meta_day_not_begun_in_the_ad_accounts_zone_has_no_number_rather_than_zero(db, monkeypatch):
    # Every source synced to 06:00Z on Mon 2 Nov: 01:00 on 2 Nov in New York, but 22:00 on 1 Nov in Los
    # Angeles, the ad account's zone. Whether a sync has reached a day is judged in the source's own zone:
    # Kit's 2 Nov has begun (a real 0 so far), Meta's has not (no number, never $0.00).
    bf.configure_connectors(monkeypatch)
    _measured(db, synced_through="2026-11-02T06:00:00Z", meta_ads={"day_tz": "America/Los_Angeles"})
    view = board_day.day_view(date(2026, 11, 2))
    spend = view["numbers"]["spend"]
    assert (spend["value"], spend["toodle_usd_cents"], spend["all_usd_cents"]) == (None, None, None)
    assert (spend["connected"], spend["state"]) == (True, "partial")
    assert spend["note"].startswith("not synced into this day yet: synced to 01:00 on Mon 2 Nov (New York)")
    assert (view["numbers"]["optins"]["value"], view["numbers"]["optins"]["state"]) == (0, "partial")
    text = board_day.render_report(view)
    assert "Meta: no number yet (not synced into this day yet" in text and "$0.00" not in text
    # The next sync, at 01:00 on 2 Nov in Los Angeles, has read the start of the account's day.
    db.set_source("meta_ads", synced_through="2026-11-02T09:00:00Z")
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-02", 12, link_clicks=1)])
    spend = board_day.day_view(date(2026, 11, 2))["numbers"]["spend"]
    assert (spend["value"], spend["state"], spend["toodle_link_clicks"]) == (12, "partial", 1)


def test_a_warning_and_a_failed_sync_are_told_apart_for_every_source(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db)
    synced_to = datetime(2026, 11, 2, 11, 55, tzinfo=timezone.utc)
    ledger.mark_source_ok("kit", synced_to, warning='tag "blog" is not in Kit')
    ledger.mark_source_error("instantly", "Instantly refused the API key (HTTP 401): check INSTANTLY_API_KEY")
    ledger.mark_source_ok("meta_ads", synced_to, warning="BOARD_TOODLE_META_CAMPAIGN_IDS is not set, so no Meta "
                                                         "spend counts as Toodle spend")
    view = board_day.day_view(date(2026, 11, 1))
    n = view["numbers"]
    assert n["optins"]["note"] == 'last sync: tag "blog" is not in Kit'
    assert n["replies"]["note"] == ("last sync failed: Instantly refused the API key (HTTP 401): "
                                    "check INSTANTLY_API_KEY")
    assert n["spend"]["note"].startswith("last sync: BOARD_TOODLE_META_CAMPAIGN_IDS is not set")
    assert [s["note"] for s in view["sources"][1:]] == [n["optins"]["note"], n["replies"]["note"],
                                                       n["spend"]["note"]]
    ledger.mark_source_ok("instantly", synced_to)                             # the next run is clean
    assert board_day.day_view(date(2026, 11, 1))["numbers"]["replies"]["note"] == ""


def test_the_database_down_or_never_migrated_reads_not_connected_for_every_number(db, stripe, monkeypatch):
    bf.configure_connectors(monkeypatch)
    db.down = True
    view = board_day.day_view(date(2026, 11, 1))
    assert view["database"] == "not_connected" and view["sales"] == []
    for name, n in view["numbers"].items():
        assert (n["value"], n["connected"], n["state"], n["note"]) == (
            None, False, "not_connected", "database not connected"), name
    assert view["numbers"]["cpl"]["verdict"] is None
    assert view["numbers"]["optins"]["by_channel"] is None and view["numbers"]["spend"]["toodle_usd_cents"] is None
    assert [(s["id"], s["state"], s["note"]) for s in view["sources"]] == [
        (sid, "not_connected", "database not connected") for sid in ("stripe", "kit", "instantly", "meta_ads")]
    db.down = False
    db.sources.clear()
    view = board_day.day_view(date(2026, 11, 1))
    assert {n["note"] for n in view["numbers"].values()} == {
        "database not connected: the board migration has not run"}


def _day_and_line(day="2026-11-01"):
    view = board_day.day_view(date.fromisoformat(day))
    return view["numbers"]["cpl"], board_day.cpl_line(view["numbers"]["cpl"])


@pytest.mark.parametrize("case, verdict, text, line", [
    ("no spend", "no_spend", "No Toodle ad spend in the last 30 days.",
     "Stop rule: no Toodle ad spend in the last 30 days"),
    ("euro spend with no rate yet", "check_currency",
     "Check the currency: 5 spend rows have no US dollar amount yet, so the cost per opt-in cannot be worked out.",
     "Stop rule: check the currency: 5 spend rows have no US dollar amount yet"),
    ("4 dollar days and 1 euro day with no rate", "check_currency",
     "Check the currency: 1 spend row has no US dollar amount yet, so the cost per opt-in cannot be worked out.",
     "Stop rule: check the currency: 1 spend row has no US dollar amount yet"),
    ("3 spend days", "collecting", "Collecting: 3 of 5 spend days so far.",
     "Stop rule: collecting, 3 of 5 spend days so far"),
    ("5 cheap days and no opt-in", "collecting",
     "Collecting: $2.50 spent over the last 5 spend days and no opt-in yet. It stops above $5.00.",
     "Stop rule: collecting, $2.50 spent over the last 5 spend days and no opt-in yet (it stops above $5.00)"),
    ("opt-ins none tagged meta", "check_tags",
     "Check the tags: 3 Toodle opt-ins came in over the last 5 spend days, but none is tagged meta. "
     "Fix the tags before stopping.",
     "Stop rule: check the tags: 3 Toodle opt-ins over the last 5 spend days and none tagged meta"),
    ("$25.10 for 4 Meta opt-ins", "stop", "STOP: $6.28 per Meta opt-in over the last 5 spend days, above $5.00.",
     "Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)"),
    ("$25.10 and no opt-in", "stop", "STOP: $25.10 spent over the last 5 spend days and no Meta opt-in.",
     "Stop rule: $25.10 spent over the last 5 spend days and no Meta opt-in → STOP (above $5.00)"),
    ("$15.00 for 4 Meta opt-ins", "ok", "OK: $3.75 per Meta opt-in over the last 5 spend days, at or below $5.00.",
     "Stop rule: CPL $3.75 over the last 5 spend days (4 Meta opt-ins) → OK (at or below $5.00)"),
])
def test_the_stop_rules_verdict_is_passed_through_in_plain_words(db, monkeypatch, case, verdict, text, line):
    bf.configure_connectors(monkeypatch)
    _measured(db)
    if case == "euro spend with no rate yet":
        _toodle_spend("2026-10-28", 5, 450, currency="EUR")
        _optins("meta", 4)
    elif case == "4 dollar days and 1 euro day with no rate":
        _toodle_spend("2026-10-28", 4, 502)
        _toodle_spend("2026-11-01", 1, 450, currency="EUR")
        _optins("meta", 4)
    elif case == "3 spend days":
        _toodle_spend("2026-10-30", 3, 502)
        _optins("meta", 4)
    elif case == "5 cheap days and no opt-in":
        _toodle_spend("2026-10-28", 5, 50)
    elif case == "opt-ins none tagged meta":
        _toodle_spend("2026-10-28", 5, 502)
        _optins("organic", 2)
        _optins(None, 1)
    elif case == "$25.10 for 4 Meta opt-ins":
        _toodle_spend("2026-10-28", 5, 502)
        _optins("meta", 4)
        _optins("organic", 1)
    elif case == "$25.10 and no opt-in":
        _toodle_spend("2026-10-28", 5, 502)
    elif case == "$15.00 for 4 Meta opt-ins":
        _toodle_spend("2026-10-28", 5, 300)
        _optins("meta", 4)
    cpl, said = _day_and_line()
    raw = ledger.board_day(date(2026, 11, 1))["cpl"]
    assert (cpl["verdict"], cpl["connected"], cpl["state"]) == (raw["verdict"], True, "final") == (verdict, True,
                                                                                                    "final")
    # While any spend has no US dollar amount, SQL sums only the converted days: that partial spend and
    # the CPLs made from it are never shown, so the card reads "—" beside its "check the currency" pill.
    hidden = {"spend_usd_cents", "cpl_meta_usd_cents", "cpl_all_usd_cents"} if verdict == "check_currency" else set()
    assert {k: cpl[k] for k in raw if k not in hidden} == {k: v for k, v in raw.items() if k not in hidden}
    assert [cpl[k] for k in sorted(hidden)] == [None] * len(hidden)
    assert cpl["value"] == (None if hidden else raw["cpl_meta_usd_cents"])
    assert (cpl["verdict_text"], said) == (text, line)


def test_the_stop_rules_settings_reach_the_sql(db, monkeypatch, leads):
    monkeypatch.setenv("BOARD_CPL_DAYS", "3")
    monkeypatch.setenv("BOARD_CPL_STOP_CENTS", "700")
    cpl, said = _day_and_line()
    assert db.rpc_calls("board_day")[-1] == {"p_day": "2026-11-01", "p_cpl_days": 3, "p_cpl_stop_cents": 700}
    assert (cpl["verdict"], cpl["spend_days"], cpl["spend_days_needed"], cpl["stop_above_cents"]) == ("ok", 3, 3, 700)
    assert cpl["verdict_text"] == "OK: $5.02 per Meta opt-in over the last 3 spend days, at or below $7.00."
    assert said == "Stop rule: CPL $5.02 over the last 3 spend days (3 Meta opt-ins) → OK (at or below $7.00)"


def test_the_stop_rule_waits_until_kit_has_counted_every_spend_day(db, monkeypatch, leads):
    db.set_source("kit", measured_from="2026-10-30")
    cpl, said = _day_and_line()
    assert (cpl["verdict"], cpl["connected"], cpl["value"]) == (None, False, None)
    assert cpl["note"] == "Kit counts opt-ins only from 2026-10-30, but the spend days start on 2026-10-28"
    assert said == f"Stop rule: not connected ({cpl['note']})"
    db.set_source("kit", measured_from="2026-01-01", synced_through="2026-10-31T12:00:00Z")   # Kit stopped syncing
    cpl, said = _day_and_line()
    assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == (None, None, True, "partial")
    assert cpl["note"] == "waiting for Kit to finish Sun 1 Nov"
    assert said == "Stop rule: no verdict yet (waiting for Kit to finish Sun 1 Nov)"
    assert cpl["verdict_text"] == "No verdict until Kit has counted every opt-in of Sun 1 Nov."
    # Kit read only part of the last spend day (to 00:20 or 17:00 there): its evening's opt-ins are not
    # counted yet, so a verdict would lean towards STOP. None until Kit has read to the day's end.
    for kit_to in ("2026-11-01T04:20:00Z", "2026-11-01T22:00:00Z", "2026-11-02T04:59:59Z"):
        db.set_source("kit", synced_through=kit_to)
        cpl, said = _day_and_line()
        assert (cpl["verdict"], cpl["value"], cpl["state"]) == (None, None, "partial"), kit_to
        assert said == "Stop rule: no verdict yet (waiting for Kit to finish Sun 1 Nov)", kit_to
    db.set_source("kit", synced_through="2026-11-02T05:00:00Z")                 # 00:00 on 2 Nov in New York
    cpl, said = _day_and_line()
    assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == ("stop", 628, True, "final")
    assert said == "Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)"


def test_kit_measured_from_the_first_spend_day_covers_that_day(db, monkeypatch, leads):
    # BOARD_BACKFILL_FROM is the day the ads started: Kit has counted that whole day, so there is a verdict.
    db.set_source("kit", measured_from="2026-10-28")
    cpl, said = _day_and_line()
    assert (cpl["first_day"], cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == \
        ("2026-10-28", "stop", 628, True, "final")
    assert said == "Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)"
    db.set_source("kit", measured_from="2026-10-29")                            # a day after the first spend day
    cpl, _ = _day_and_line()
    assert (cpl["verdict"], cpl["connected"]) == (None, False)
    assert cpl["note"] == "Kit counts opt-ins only from 2026-10-29, but the spend days start on 2026-10-28"


def test_the_stop_rule_on_a_day_still_in_progress_waits_for_its_end(db, monkeypatch, leads):
    # 2 Nov, seen at 07:00 that day: Meta has its spend so far, Kit its opt-ins so far. Neither can
    # have read the whole of a day that has not ended, so there is no verdict on it yet.
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-02", 120)])
    cpl, said = _day_and_line("2026-11-02")
    assert (cpl["verdict"], cpl["connected"], cpl["state"]) == (None, True, "partial")
    assert said == "Stop rule: no verdict yet (waiting for Kit to finish Mon 2 Nov)"
    # The same view a day later, once Kit and Meta have both read past the end of 2 Nov.
    for source_id in ("kit", "meta_ads"):
        db.set_source(source_id, synced_through="2026-11-03T12:00:00Z")
    cpl, said = _day_and_line("2026-11-02")          # $21.28 over 29 Oct to 2 Nov for 5 Meta opt-ins
    assert (cpl["verdict"], cpl["value"], cpl["state"], cpl["last_day"]) == ("ok", 426, "final", "2026-11-02")


def test_spend_with_no_us_dollar_amount_is_not_shown_as_a_smaller_number(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    _measured(db)
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 450, currency="EUR", link_clicks=7),
                                              bf.spend("2026-11-01", 300, campaign="120000000000000001", funnel=None)])
    spend = board_day.day_view(date(2026, 11, 1))["numbers"]["spend"]
    assert (spend["value"], spend["toodle_usd_cents"], spend["all_usd_cents"]) == (None, None, None)
    assert (spend["connected"], spend["unconverted_rows"], spend["toodle_link_clicks"]) == (True, 1, 7)
    assert spend["note"] == ("1 spend row has no US dollar amount yet (no exchange rate), "
                             "so the spend is not shown")
    db.add_fx_rate("EUR", "2026-10-30", "1.1")
    assert ledger.fill_fx() == 1
    spend = board_day.day_view(date(2026, 11, 1))["numbers"]["spend"]
    assert (spend["value"], spend["all_usd_cents"], spend["unconverted_rows"], spend["note"]) == (495, 795, 0, "")


NO_TOODLE_CAMPAIGNS = "Toodle campaigns not set: BOARD_TOODLE_META_CAMPAIGN_IDS names no campaign"


def _fixture_spend(funnel):
    """The fixture's Toodle campaign spend on 28 Oct to 1 Nov, labelled `funnel`."""
    return [bf.spend(f"2026-{d}", 502, funnel=funnel, link_clicks=9 if d == "11-01" else 7, impressions=1200)
            for d in ("10-28", "10-29", "10-30", "10-31", "11-01")]


@pytest.mark.parametrize("campaign_ids", [None, "abc", " , act_120249191226470279"])
def test_without_toodle_campaigns_toodle_spend_and_the_stop_rule_have_no_value(db, monkeypatch, campaign_ids):
    bf.configure_connectors(monkeypatch)
    if campaign_ids is None:
        monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    else:
        monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", campaign_ids)     # no item is a campaign id
    bf.load_fixture_leads(db)
    # What the Meta sync writes while no Toodle campaign is listed: all the spend, none of it Toodle's.
    ledger.upsert_ad_spend("meta_ads", None, _fixture_spend(None))
    for rows in ("unlabelled", "labelled by an earlier list"):
        view = board_day.day_view(date(2026, 11, 1))
        spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
        assert (spend["value"], spend["toodle_usd_cents"], spend["toodle_link_clicks"]) == (None, None, None), rows
        assert (spend["connected"], spend["state"], spend["note"]) == (False, "not_connected", NO_TOODLE_CAMPAIGNS)
        assert (spend["all_usd_cents"], spend["impressions"]) == (1502, 10200)     # every campaign is still read
        assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == (None, None, False, "not_connected")
        assert (cpl["note"], cpl["spend_usd_cents"], cpl["meta_optins"]) == (NO_TOODLE_CAMPAIGNS, None, None)
        assert cpl["verdict_text"] == "No verdict until the Toodle campaigns are set."
        assert [(s["state"], s["connected"]) for s in view["sources"]][3] == ("final", True)    # Meta itself is read
        text = board_day.render_report(view)
        assert f"Meta: not connected ({NO_TOODLE_CAMPAIGNS})\n" in text
        assert f"Stop rule: not connected ({NO_TOODLE_CAMPAIGNS})\n" in text
        assert "$0.00" not in text and "no Toodle ad spend" not in text, rows
        ledger.upsert_ad_spend("meta_ads", None, _fixture_spend("toodle"))
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", bf.TOODLE_CAMPAIGN)
    n = board_day.day_view(date(2026, 11, 1))["numbers"]
    assert (n["spend"]["value"], n["spend"]["note"], n["cpl"]["verdict"], n["cpl"]["value"]) == (502, "", "stop", 628)


TOODLE_CHANGED = "Toodle campaigns changed: waiting for the next Meta sync"
SECOND_CAMPAIGN = "120249191226470280"
TYPO_CAMPAIGN = "120249191226470278"          # the plan's Toodle campaign one digit off: no campaign of the account


@pytest.mark.parametrize("case", ["set after a Meta sync without it", "changed since the last Meta sync",
                                  "no Meta sync recorded"])
def test_a_campaign_list_the_last_meta_sync_did_not_use_gives_no_toodle_number_until_the_next(db, monkeypatch,
                                                                                              case):
    # The Meta sync labels every stored day from the list it runs with. A list set or changed since its last
    # complete run reaches the stored days only at the next run (06:30, 12:30 or Sync now). Until then the
    # labels are the old list's: the Toodle spend and the stop rule have no number, never a final $0.00 or
    # "no Toodle ad spend". Every campaign's spend is still shown.
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db)                                     # synced with the plan's Toodle campaign listed
    if case == "set after a Meta sync without it":
        ledger.upsert_ad_spend("meta_ads", None, _fixture_spend(None))      # that run labelled nothing Toodle's
        bf.record_meta_run(db, campaigns=())
    elif case == "changed since the last Meta sync":
        monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{bf.TOODLE_CAMPAIGN}, {SECOND_CAMPAIGN}")
    else:
        db.job_runs.clear()
    view = board_day.day_view(date(2026, 11, 1))
    spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
    assert (spend["value"], spend["toodle_usd_cents"], spend["toodle_link_clicks"]) == (None, None, None)
    assert (spend["connected"], spend["state"], spend["note"]) == (True, "partial", TOODLE_CHANGED)
    assert (spend["all_usd_cents"], spend["impressions"]) == (1502, 10200)
    assert (cpl["verdict"], cpl["value"], cpl["connected"], cpl["state"]) == (None, None, True, "partial")
    assert (cpl["note"], cpl["spend_usd_cents"], cpl["meta_optins"]) == (TOODLE_CHANGED, None, None)
    assert cpl["verdict_text"] == "No verdict until the next Meta sync."
    assert view["sources"][3]["state"] == "final"                                  # Meta itself is read
    text = board_day.render_report(view)
    assert f"Meta: no number yet ({TOODLE_CHANGED})\n" in text
    assert f"Stop rule: no verdict yet ({TOODLE_CHANGED})\n" in text
    assert "$0.00" not in text and "no Toodle ad spend" not in text and "STOP" not in text
    # The next Meta run labels every stored day from the list, then records the list it used.
    campaigns = meta_sync.toodle_campaigns()[0]
    ledger.label_spend_funnel("meta_ads", "toodle", campaigns)
    bf.record_meta_run(db, campaigns=campaigns)
    n = board_day.day_view(date(2026, 11, 1))["numbers"]
    assert (n["spend"]["value"], n["spend"]["state"], n["spend"]["note"]) == (502, "final", "")
    assert (n["cpl"]["verdict"], n["cpl"]["value"], n["cpl"]["state"], n["cpl"]["note"]) == ("stop", 628, "final", "")


def test_the_toodle_numbers_wait_when_the_last_meta_sync_cannot_be_read(db, monkeypatch, leads):
    db.fail["job_runs"] = 500
    view = board_day.day_view(date(2026, 11, 1))
    spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
    unchecked = "Toodle campaigns not checked: database not connected"
    assert (spend["value"], spend["connected"], spend["state"], spend["note"]) == (None, True, "partial", unchecked)
    assert (cpl["verdict"], cpl["value"], cpl["state"], cpl["note"]) == (None, None, "partial", unchecked)
    assert cpl["verdict_text"] == "No verdict: database not connected."
    assert (view["numbers"]["optins"]["value"], view["numbers"]["replies"]["value"]) == (2, 1)    # the rest is read
    assert "Failing row" not in str(view) and "injected" not in str(view)


def test_a_listed_id_with_no_spend_is_named_on_a_no_spend_stop_rule(tmp_path, db, monkeypatch):
    # The list names an id that is no campaign of the ad account (a typo). The Meta sync labels nothing
    # Toodle's and warns about that id, which the Meta line and pill show. A no_spend verdict carries the
    # same warning, ids only. It stays a verdict, with its real 0: a paused campaign's 0 is just as real.
    bf.configure_connectors(monkeypatch)
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TYPO_CAMPAIGN)
    bf.load_fixture_leads(db)
    ledger.upsert_ad_spend("meta_ads", None, _fixture_spend(None))           # the run labelled nothing Toodle's
    warning = f"no spend seen for campaign {TYPO_CAMPAIGN} since 2026-10-05: check BOARD_TOODLE_META_CAMPAIGN_IDS"
    bf.record_meta_run(db, campaigns=(TYPO_CAMPAIGN,), unseen=(TYPO_CAMPAIGN,), since="2026-10-05")
    ledger.mark_source_ok("meta_ads", datetime(2026, 11, 2, 11, 55, tzinfo=timezone.utc), warning=warning)
    view = board_day.day_view(date(2026, 11, 1))
    spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
    assert (spend["value"], spend["state"], spend["note"]) == (0, "final", f"last sync: {warning}")
    assert (cpl["verdict"], cpl["connected"], cpl["state"], cpl["spend_usd_cents"]) == ("no_spend", True, "final", 0)
    assert (cpl["note"], cpl["verdict_text"]) == (warning, "No Toodle ad spend in the last 30 days.")
    lines = board_day.render_report(view).split("\n")
    stop_rule = lines.index("Stop rule: no Toodle ad spend in the last 30 days")
    assert lines[stop_rule + 1] == f"  {warning}"
    assert lines[stop_rule - 1] == f"  last sync: {warning}"                    # the Meta line's note, as before
    card = _cards(_page(tmp_path, view))["cpl-card"]
    assert '<span class="pill off">no spend</span>' in card and f'<div class="note">{warning}</div>' in card
    cpl = board_day.day_view(date(2026, 11, 2))["numbers"]["cpl"]               # a day still in progress
    assert (cpl["verdict"], cpl["state"]) == ("no_spend", "partial")
    assert cpl["note"] == f"partial: Meta and Kit have not both synced past the end of this day · {warning}"
    # On any other verdict the stop rule's note is left as it is: the Meta line carries the warning.
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{bf.TOODLE_CAMPAIGN},{TYPO_CAMPAIGN}")
    ledger.label_spend_funnel("meta_ads", "toodle", {bf.TOODLE_CAMPAIGN, TYPO_CAMPAIGN})
    bf.record_meta_run(db, campaigns=(bf.TOODLE_CAMPAIGN, TYPO_CAMPAIGN), unseen=(TYPO_CAMPAIGN,))
    cpl = board_day.day_view(date(2026, 11, 1))["numbers"]["cpl"]
    assert (cpl["verdict"], cpl["value"], cpl["state"], cpl["note"]) == ("stop", 628, "final", "")


def test_the_cards_say_the_toodle_numbers_wait_for_the_next_meta_sync(tmp_path, db, monkeypatch, leads):
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{bf.TOODLE_CAMPAIGN},{SECOND_CAMPAIGN}")
    cards = _cards(_page(tmp_path, board_day.day_view(date(2026, 11, 1))))
    assert '<div class="val off">no number yet</div>' in cards["spend-card"]
    assert '<div class="val off">no verdict yet</div>' in cards["cpl-card"]
    assert "No verdict until the next Meta sync." in cards["cpl-card"]
    for name in ("spend-card", "cpl-card"):
        assert '<span class="pill part">partial</span>' in cards[name]
        assert f'<div class="note">{TOODLE_CHANGED}</div>' in cards[name]
        assert "$0.00" not in cards[name] and "no spend" not in cards[name] and "not connected" not in cards[name]


def test_an_ad_account_in_another_zone_says_whose_days_meta_counts(db, monkeypatch, leads):
    ledger.update_source("meta_ads", day_tz="America/Los_Angeles", currency="USD", account_ref="act_1234567890")
    view = board_day.day_view(date(2026, 11, 1))
    spend = view["numbers"]["spend"]
    assert (spend["state"], spend["day_tz"], spend["value"]) == ("final", "America/Los_Angeles", 502)
    assert spend["note"] == "Meta counts days in the ad account's time zone (America/Los_Angeles), not New York time"
    assert view["sources"][3]["note"] == spend["note"]
    assert view["numbers"]["optins"]["note"] == ""                         # Kit's days are New York's


def test_notes_say_when_meta_is_read_with_the_token_that_creates_ads(db, monkeypatch, leads):
    monkeypatch.delenv("META_INSIGHTS_TOKEN")
    monkeypatch.setenv("META_ACCESS_TOKEN", bf.META_TOKEN)
    spend = board_day.day_view(date(2026, 11, 1))["numbers"]["spend"]
    assert spend["note"] == "read with META_ACCESS_TOKEN; a read-only META_INSIGHTS_TOKEN is safer"
    assert spend["value"] == 502 and bf.META_TOKEN not in str(spend)


def test_a_7_day_reply_count_with_days_before_the_first_measured_day_has_no_value(db, monkeypatch, leads):
    db.set_source("instantly", measured_from="2026-10-28")                  # the day of the first reply
    replies = board_day.day_view(date(2026, 11, 1))["numbers"]["replies"]
    assert (replies["value"], replies["value_7d"]) == (1, None)             # 28 Oct to 1 Nov: 5 days, not 7
    assert replies["note"] == "no 7-day count: replies are counted only from 2026-10-28"
    assert (replies["connected"], replies["state"], replies["auto_replies_ignored"]) == (True, "final", 1)
    db.set_source("instantly", measured_from="2026-10-27")                  # 26 Oct, the 7th day back, is not
    replies = board_day.day_view(date(2026, 11, 1))["numbers"]["replies"]
    assert (replies["value"], replies["value_7d"]) == (1, None)
    assert replies["note"] == "no 7-day count: replies are counted only from 2026-10-27"
    db.set_source("instantly", measured_from="2026-10-26")                  # 26 Oct to 1 Nov: all 7 measured
    replies = board_day.day_view(date(2026, 11, 1))["numbers"]["replies"]
    assert (replies["value"], replies["value_7d"], replies["note"]) == (1, 2, "")


# ─── the route: GET /api/board/day ──────────────────────────────────────────

@pytest.fixture
def owner(monkeypatch):
    return bf.client(monkeypatch), bf.owner_headers()        # production's owner session cookie


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
    # yesterday is decided in SQL; the stop rule's settings go with every call
    assert synced.rpc_calls("board_day") == [{"p_day": None, "p_cpl_days": 5, "p_cpl_stop_cents": 500}]


def test_the_day_route_without_stripe_shows_not_connected(owner, db, monkeypatch):
    client, cookie = owner
    monkeypatch.delenv("STRIPE_READ_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    j = client.get("/api/board/day?date=2026-11-01", headers=cookie).json()
    assert j["numbers"]["revenue"]["value"] is None and j["numbers"]["revenue"]["connected"] is False
    assert "$0" not in str(j)


def test_the_board_page_shows_the_day_and_carries_no_secret(owner, monkeypatch):
    client, cookie = owner
    anon = "anon-key-3c1d5e7f-for-tests"                     # a public key core.api writes into some pages
    monkeypatch.setenv("STRIPE_READ_KEY", bf.STRIPE_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_board_page_test_secret")
    monkeypatch.setattr("core.api._SUPABASE_ANON", anon)
    r = client.get("/admin/scoreboard", headers=cookie)
    assert r.status_code == 200
    for piece in ("/api/board/day", "'/api/board/sync/'+encodeURIComponent(id)", 'id="rev-card"',
                  'id="optins-card"', 'id="replies-card"', 'id="spend-card"', 'id="cpl-card"', 'id="sales-body"',
                  'id="day-sources"', "esc(", "credentials:'same-origin'", "data-sync=",
                  "{stripe:'Stripe',kit:'Kit',instantly:'Instantly',meta_ads:'Meta'}"):
        assert piece in r.text
    for secret in (bf.STRIPE_KEY, "whsec_board_page_test_secret", bf.SERVICE, anon, bf.API_KEY, "X-API-Key"):
        assert secret not in r.text


def test_the_day_route_shows_every_number(owner, synced, leads):
    client, cookie = owner
    j = client.get("/api/board/day?date=2026-11-01", headers=cookie).json()
    n = j["numbers"]
    assert (n["optins"]["value"], n["replies"]["value"], n["revenue"]["value"], n["spend"]["value"]) == (
        2, 1, 1000, 502)
    assert (n["cpl"]["verdict"], n["cpl"]["cpl_meta_usd_cents"]) == ("stop", 628)
    assert [s["id"] for s in j["sources"]] == ["stripe", "kit", "instantly", "meta_ads"]
    for value in (bf.KIT_KEY, bf.INSTANTLY_KEY, bf.META_TOKEN, bf.STRIPE_KEY, bf.SERVICE):
        assert value not in str(j)


# ─── the page: frontend/admin/scoreboard.html's script, run in Node ─────────

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "admin" / "scoreboard.html"

# A stub DOM: every element the script asks for, its innerHTML, textContent and
# display; fetch answers from a table ("METHOD /path" -> status and JSON); timers
# are recorded, not run. Prints what the page showed, then what one click on a
# source's "Sync now" button did, then what the timers of a minute or more did.
_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const [scriptPath, answersPath, click] = process.argv.slice(2);
const answers = JSON.parse(fs.readFileSync(answersPath, 'utf8'));
const els = {}, calls = [], timers = [];
const el = id => els[id] || (els[id] = {id, innerHTML: '', textContent: '', value: '', style: {}, on: {},
  addEventListener(type, f) { this.on[type] = f; }});
const page = {
  document: {getElementById: el}, location: {pathname: '/admin/scoreboard', search: '', href: ''},
  history: {replaceState() {}}, URLSearchParams, Intl,
  setTimeout(f, ms) { timers.push({f, ms}); return timers.length; },
  fetch: async (url, opts) => {
    const key = ((opts && opts.method) || 'GET') + ' ' + String(url).split('?')[0];
    calls.push(key);
    const a = answers[key] || {status: 404, body: {}};
    return {status: a.status, ok: a.status >= 200 && a.status < 300, json: async () => a.body};
  },
};
vm.createContext(page);
vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), page);
const settle = async () => { for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r)); };
const shown = () => Object.fromEntries(Object.entries(els).map(([k, v]) =>
  [k, {html: v.innerHTML, text: v.textContent, display: v.style.display || ''}]));
(async () => {
  await settle();
  const out = {loaded: shown(), calls: calls.splice(0)};
  if (click) {
    const button = {dataset: {sync: click}, disabled: false, textContent: 'Sync now'};
    await el('day-sources').on.click({target: {closest: () => button}});
    await settle();
    out.clicked = {els: shown(), calls: calls.splice(0), timers: timers.map(t => t.ms),
                   button: [button.disabled, button.textContent]};
    for (const t of timers.splice(0)) if (t.ms >= 30000) t.f();
    await settle();
    out.later = {els: shown(), calls: calls.splice(0)};
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error((e && e.stack) || e); process.exit(1); });
"""


def _page(tmp_path, view: dict, click: str = "", sync: tuple = (200, {}), metrics: dict = None) -> dict:
    """Run the page's script on `view` (the day JSON); with `click`, press that
    source's "Sync now", whose POST answers `sync` (status, JSON)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed, so the page's script cannot run")
    script = re.search(r"<script>(.*?)</script>", PAGE.read_text(encoding="utf-8"), re.S).group(1)
    answers = {"GET /api/board/day": {"status": 200, "body": json.loads(json.dumps(view))},
               "GET /api/board/scoreboard": {"status": 200, "body": {"metrics": metrics or {}, "surfaces": {}}},
               "GET /api/board/opportunities": {"status": 200, "body": {"opportunities": []}},
               f"POST /api/board/sync/{click}": {"status": sync[0], "body": sync[1]}}
    for name, text in (("page.js", script), ("answers.json", json.dumps(answers)), ("harness.js", _HARNESS)):
        (tmp_path / name).write_text(text, encoding="utf-8")
    ran = subprocess.run([node, str(tmp_path / "harness.js"), str(tmp_path / "page.js"),
                          str(tmp_path / "answers.json"), click], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


def _cards(out: dict) -> dict:
    return {k: v["html"] for k, v in out["loaded"].items() if k.endswith("-card")}


def test_the_page_says_a_sync_still_running_and_reloads_the_day_a_minute_later(tmp_path, synced, leads):
    view = board_day.day_view(date(2026, 11, 1))
    running = {"source": "kit", "status": "running", "note": "Still running. The board updates when it finishes."}
    out = _page(tmp_path, view, click="kit", sync=(202, running))
    assert out["calls"] == ["GET /api/board/day", "GET /api/board/scoreboard", "GET /api/board/opportunities"]
    clicked = out["clicked"]
    assert clicked["calls"] == ["POST /api/board/sync/kit"]                    # not reloaded yet: still running
    assert (clicked["els"]["msg"]["text"], clicked["els"]["msg"]["display"]) == (
        "Kit sync: Still running. The board updates when it finishes.", "block")
    assert clicked["els"].get("err", {}).get("display", "") != "block"           # not an error
    assert clicked["button"] == [False, "Sync now"]                             # a second press gets 409 or 429
    assert [ms for ms in clicked["timers"] if ms >= 30000] == [60000, 60000]    # the note's, and the reload's
    assert out["later"]["calls"] == ["GET /api/board/day"]                      # the day again, a minute later
    assert out["later"]["els"]["msg"]["display"] == "none"


@pytest.mark.parametrize("status, answer, error", [
    (200, {"status": "ok", "error": None}, None),
    (200, {"status": "ok", "error": "tag \"blog\" is not in Kit"}, "Kit sync: tag \"blog\" is not in Kit"),
    (409, {"status": "busy", "error": "another Kit sync is running"}, "Kit sync: another Kit sync is running"),
    (429, {"error": "One sync a minute per source"}, "Kit sync: One sync a minute per source"),
])
def test_a_sync_that_answers_in_time_reloads_the_day_at_once(tmp_path, synced, leads, status, answer, error):
    out = _page(tmp_path, board_day.day_view(date(2026, 11, 1)), click="kit", sync=(status, answer))
    clicked = out["clicked"]
    assert clicked["calls"] == ["POST /api/board/sync/kit", "GET /api/board/day"]
    assert clicked["els"].get("msg", {}).get("display", "") != "block"
    assert clicked["els"].get("err", {}).get("text", "") == (f"⚠ {error}" if error else "")
    assert [ms for ms in clicked["timers"] if ms >= 30000] == [] and out["later"]["calls"] == []


def test_every_card_shows_a_dash_for_a_null_and_never_a_dollar_zero(tmp_path, db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    _measured(db)
    db.set_source("instantly", measured_from="2026-10-28")             # 7-day count: 2 days unmeasured
    _toodle_spend("2026-10-28", 5, 450, currency="EUR")                # no exchange rate yet
    _optins("meta", 4)
    ledger.ingest_leads("instantly", None, [bf.reply("e1", "2026-11-01T13:00:00Z", "p@shop.example"),
                                            bf.reply("e2", "2026-11-01T14:00:00Z", "q@shop.example", auto=True)])
    view = board_day.day_view(date(2026, 11, 1))
    assert (view["numbers"]["replies"]["value_7d"], view["numbers"]["cpl"]["verdict"]) == (None, "check_currency")
    cards = _cards(_page(tmp_path, view))
    assert "$0.00" not in str(cards)
    assert "last 7 days: — · target 1 a week" in cards["replies-card"]
    assert "1 automatic reply or bounce ignored" in cards["replies-card"]
    assert '<div class="val">—</div>' in cards["cpl-card"]                      # no CPL from part of the spend
    assert "check the currency" in cards["cpl-card"] and "— over 5 of 5 spend days" in cards["cpl-card"]
    assert "— per Toodle opt-in" in cards["cpl-card"]
    assert '<div class="val off">no number yet</div>' in cards["spend-card"]   # the day's euros: no dollars yet
    # Fields a card shows beside a value it has: each one null here.
    spend = dict(view["numbers"]["spend"], value=502, toodle_usd_cents=502, toodle_link_clicks=None,
                 all_usd_cents=None, impressions=None)
    cpl = dict(view["numbers"]["cpl"], verdict="ok", meta_optins=None, toodle_optins=None, first_day=None)
    view["numbers"].update(spend=spend, cpl=cpl)
    old = {"mrr": {"connected": True, "value": None, "source": "stripe", "note": ""},
           "users": {"connected": True, "value": None, "source": "supabase", "note": ""}}
    out = _page(tmp_path, view, metrics=old)
    cards = _cards(out)
    assert "— link clicks" in cards["spend-card"] and "all campaigns — · — impressions" in cards["spend-card"]
    assert "— Meta opt-ins of — ·" in cards["cpl-card"] and "spend days, — to 2026-11-01" in cards["cpl-card"]
    grid = out["loaded"]["grid"]["html"]                                          # the scoreboard below
    assert grid.count('<div class="val">—</div>') == 2 and "$0" not in grid and ">0<" not in grid
    assert "$0.00" not in str(cards) and "undefined" not in str(cards) and "null" not in str(cards)


def test_the_stop_rule_card_waits_for_kit_and_names_the_missing_setting(tmp_path, db, monkeypatch, leads):
    db.set_source("kit", synced_through="2026-11-01T22:00:00Z")                # 17:00 on 1 Nov in New York
    card = _cards(_page(tmp_path, board_day.day_view(date(2026, 11, 1))))["cpl-card"]
    assert '<div class="val off">no verdict yet</div>' in card and "not connected" not in card
    assert '<span class="pill part">partial</span>' in card
    assert "No verdict until Kit has counted every opt-in of Sun 1 Nov." in card
    assert "waiting for Kit to finish Sun 1 Nov" in card
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    db.set_source("kit", synced_through="2026-11-02T11:55:00Z")
    cards = _cards(_page(tmp_path, board_day.day_view(date(2026, 11, 1))))
    assert '<div class="val off">not connected</div>' in cards["cpl-card"]
    assert '<div class="val off">not connected</div>' in cards["spend-card"]
    for name in ("cpl-card", "spend-card"):
        assert NO_TOODLE_CAMPAIGNS in cards[name] and "$0.00" not in cards[name] and "no spend" not in cards[name]


def test_the_page_shows_attributed_revenue_and_how_each_sale_was_credited(tmp_path, db, stripe, monkeypatch):
    import core.click_tracker as ct
    monkeypatch.setattr(ct, "_clock", lambda: datetime(2026, 11, 1, 23, 50, tzinfo=timezone.utc))
    monkeypatch.setattr("core.telegram.notify_click", lambda **kwargs: True)
    click = ct.new_click("insider", query={"utm_source": "meta"})
    assert ct.save_click(click)
    bts, (s0, s1) = bf.fixture_day()
    stripe.add(bts, [s0, {**s1, "client_reference_id": click.id}])        # the 1 Nov sale came through the link
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    ledger.ingest_leads("kit", None, [bf.optin(9, "2026-10-01T12:00:00Z", "organic", email="old@example.com")])
    view = board_day.day_view(date(2026, 11, 1))
    assert {(s["kind"], s["channel"], s["attribution"]) for s in view["sales"]} == {
        ("sale", "meta", "click_id"), ("refund", "organic", "lead_email"),
        ("dispute", "unattributed", "none"), ("dispute_reversal", "unattributed", "none")}
    out = _page(tmp_path, view)
    card = out["loaded"]["rev-card"]["html"]
    assert '<div class="src">attributed $10.00 · meta $29.99 · organic -$19.99</div>' in card   # 0s left out
    body = out["loaded"]["sales-body"]["html"]
    assert 'meta<div class="src">tracked link</div>' in body
    assert 'organic<div class="src">earlier lead, same email</div>' in body
    assert "checkout tag" not in body and body.count('<div class="src">') == 2          # 'none' says nothing
    for text in (card, body):
        assert "undefined" not in text and "null" not in text and "NaN" not in text
    # a hostile channel and an attribution that names an Object property are escaped, never run
    hostile = '<img src=x onerror=alert(1)>'
    sales = [dict(s, channel=hostile, attribution="constructor") if s["kind"] == "sale" else
             dict(s, attribution="checkout_utm") if s["kind"] == "refund" else s for s in view["sales"]]
    rev = dict(view["numbers"]["revenue"], by_channel={hostile: 2999, "organic": -1999, "unattributed": 0})
    out = _page(tmp_path, dict(view, sales=sales, numbers=dict(view["numbers"], revenue=rev)))
    card, body = out["loaded"]["rev-card"]["html"], out["loaded"]["sales-body"]["html"]
    assert "&lt;img src=x onerror=alert(1)&gt; $29.99" in card and "<img" not in card
    assert "&lt;img src=x onerror=alert(1)&gt;" in body and "<img" not in body
    assert "function" not in body and 'organic<div class="src">checkout tag</div>' in body


def test_the_page_lists_the_largest_channel_first_by_amount_not_by_name(tmp_path, synced):
    view = board_day.day_view(date(2026, 11, 1))
    rev = dict(view["numbers"]["revenue"], by_channel={"meta": 1999, "organic": 2999, "unattributed": -1999},
               attributed_usd_cents=4998)
    card = _page(tmp_path, dict(view, numbers=dict(view["numbers"], revenue=rev)))["loaded"]["rev-card"]["html"]
    assert '<div class="src">attributed $49.98 · organic $29.99 · meta $19.99 · unattributed -$19.99</div>' in card


def test_the_page_has_no_attribution_line_on_a_day_without_money(tmp_path, db, stripe):
    db.set_source(measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")
    view = board_day.day_view(date(2026, 11, 1))
    card = _page(tmp_path, view)["loaded"]["rev-card"]["html"]
    assert "attributed" not in card and "$0.00" in card
    # money rows that cancel out: attributed $0.00, as the morning message says
    rev = dict(view["numbers"]["revenue"], counts={"sale": 1, "refund": 1}, by_channel={"meta": 0},
               attributed_usd_cents=0)
    card = _page(tmp_path, dict(view, numbers=dict(view["numbers"], revenue=rev)))["loaded"]["rev-card"]["html"]
    assert '<div class="src">attributed $0.00</div>' in card
    assert board_day.summary_line({"numbers": {"revenue": dict(rev, value=0, net_usd_cents=0, fees_usd_cents=0)}}) \
        == "Revenue: $0.00 net · attributed $0.00 · fees $0.00"
