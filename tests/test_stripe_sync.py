"""The Stripe connector (core/board/connectors/stripe_sync.py) and its route,
POST /api/board/sync/stripe. Stripe money comes only from balance
transactions. No network: Stripe and Supabase are faked in tests/board_fakes.py."""
from datetime import date, datetime, timedelta, timezone

import pytest

from core.board import ledger, routes
from core.board.connectors import stripe_sync
from tests import board_fakes as bf

SAME_ORIGIN = {"Origin": "http://testserver"}
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 in New York


@pytest.fixture
def db(monkeypatch):
    return bf.install_board(monkeypatch)


@pytest.fixture
def stripe(monkeypatch):
    return bf.install_stripe(monkeypatch)


def _stripe_rows(db):
    return db.rows("stripe")


# ─── mapping: one balance transaction, one ledger row ───────────────────────

def test_a_charge_is_a_sale_keyed_on_its_balance_transaction():
    bt = bf.charge_bt("txn_1", "ch_1", 2999, "2026-11-02T04:30:00Z", 117, payment_intent="pi_1")
    kind, skip = stripe_sync.classify(bt)
    row = stripe_sync.to_row(bt, kind)
    assert (kind, skip) == ("sale", None)
    assert row.external_id == "txn_1" and row.order_ref == "ch_1"
    assert (row.amount_minor, row.currency, row.amount_usd_cents, row.fx_source) == (2999, "USD", 2999, "stripe")
    assert row.fee_usd_cents == 117
    assert row.occurred_at == datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)
    assert "billing_details" not in row.raw and row.raw["source"] == "ch_1"     # no card or buyer data in raw


def test_a_refund_is_negative_and_points_at_its_charge():
    bt = bf.refund_bt("txn_r", "re_1", "ch_0", 1999, "2026-11-01T14:00:00Z")
    row = stripe_sync.to_row(bt, stripe_sync.classify(bt)[0])
    assert (row.kind, row.amount_minor, row.amount_usd_cents, row.order_ref) == ("refund", -1999, -1999, "ch_0")
    assert stripe_sync.classify(bf.refund_bt("txn_p", "pyr_1", "py_1", 500, "2026-11-01T14:00:00Z",
                                             kind="payment_refund"))[0] == "refund"


def test_a_dispute_and_its_reversal_go_by_sign_and_the_returned_fee_is_negative():
    lost = bf.dispute_bt("txn_d", "du_9", "ch_9", 1500, "2026-11-01T10:00:00Z", fee=1500)
    won = bf.dispute_bt("txn_w", "du_9", "ch_9", 1500, "2026-11-01T20:00:00Z", fee=-1500, won=True)
    d, w = (stripe_sync.to_row(bt, stripe_sync.classify(bt)[0]) for bt in (lost, won))
    assert (d.kind, d.amount_minor, d.fee_usd_cents, d.order_ref) == ("dispute", -1500, 1500, "ch_9")
    assert (w.kind, w.amount_minor, w.fee_usd_cents, w.order_ref) == ("dispute_reversal", 1500, -1500, "ch_9")
    # a dispute is told apart by its source, even without a reporting category
    bare = dict(lost, reporting_category=None, source="du_10")
    assert stripe_sync.classify(bare)[0] == "dispute"


def test_stripe_fees_are_negative_fee_rows_and_a_fee_credit_is_named_not_guessed():
    fee = stripe_sync.to_row(bf.plain_bt("txn_f", "stripe_fee", -200, "2026-11-01T12:00:00Z"), "fee")
    assert (fee.kind, fee.amount_minor, fee.amount_usd_cents, fee.fee_usd_cents, fee.order_ref) == \
        ("fee", -200, -200, 0, None)
    assert stripe_sync.classify(bf.plain_bt("txn_c", "stripe_fee", 300, "2026-11-01T12:00:00Z")) == \
        (None, ("unmapped", "stripe_fee (a credit)"))


def test_a_failed_refund_is_an_adjustment_and_payouts_are_not_revenue():
    failed = bf.refund_bt("txn_rf", "re_2", "ch_2", 700, "2026-11-01T14:00:00Z", kind="refund_failure")
    failed["amount"] = 700
    row = stripe_sync.to_row(failed, stripe_sync.classify(failed)[0])
    assert (row.kind, row.amount_minor, row.order_ref) == ("adjustment", 700, "ch_2")
    for kind in ("payout", "transfer", "topup", "reserve_transaction", "contribution"):
        assert stripe_sync.classify(bf.plain_bt("t", kind, -100, "2026-11-01T12:00:00Z")) == \
            (None, ("not_revenue", kind))
    assert stripe_sync.classify(bf.plain_bt("t", "payment_reversal", -100, "2026-11-01T12:00:00Z")) == \
        (None, ("unmapped", "payment_reversal"))
    assert stripe_sync.classify(bf.plain_bt("t", "adjustment", -100, "2026-11-01T12:00:00Z",
                                            category="other_adjustment")) == \
        (None, ("unmapped", "adjustment (not a dispute)"))


def test_a_not_revenue_transactions_fee_is_a_fee_row_with_no_amount():
    paid = stripe_sync.fee_row(bf.plain_bt("txn_ip", "payout", -10000, "2026-11-01T15:00:00Z", fee=150,
                                           category="payout", source="po_1"))
    assert (paid.kind, paid.amount_minor, paid.amount_usd_cents, paid.fee_usd_cents, paid.order_ref) == \
        ("fee", 0, 0, 150, None)
    assert paid.external_id == "txn_ip" and paid.raw["type"] == "payout"
    returned = stripe_sync.fee_row(bf.plain_bt("txn_pf", "payout_failure", 10000, "2026-11-01T16:00:00Z",
                                               fee=-150, category="payout_reversal", source="po_1"))
    assert (returned.amount_minor, returned.fee_usd_cents) == (0, -150)            # Stripe's sign, kept


def test_a_non_usd_sale_keeps_the_buyers_amount_and_stripes_own_usd():
    bt = bf.charge_bt("txn_eur", "ch_e", 1000, "2026-10-30T16:00:00Z", 62, currency="eur",
                      settled=1090, exchange_rate=1.09)
    row = stripe_sync.to_row(bt, "sale")
    assert (row.amount_minor, row.currency) == (1000, "EUR")                 # what the buyer paid
    assert (row.amount_usd_cents, row.fx_source, row.fee_usd_cents) == (1090, "stripe", 62)   # what settled
    assert row.raw["exchange_rate"] == 1.09
    refund = bf.refund_bt("txn_eur_r", "re_e", "ch_e", 1000, "2026-10-31T16:00:00Z")
    refund["amount"], refund["source"]["currency"] = -1085, "eur"
    r = stripe_sync.to_row(refund, "refund")
    assert (r.amount_minor, r.currency, r.amount_usd_cents) == (-1000, "EUR", -1085)


def test_an_account_that_settles_in_another_currency_leaves_usd_unknown():
    bt = bf.charge_bt("txn_gbp", "ch_g", 1000, "2026-10-30T16:00:00Z", 40, currency="gbp",
                      settled_currency="gbp")
    row = stripe_sync.to_row(bt, "sale")
    assert (row.amount_minor, row.currency, row.amount_usd_cents, row.fx_source, row.fee_usd_cents) == \
        (1000, "GBP", None, None, None)


def test_a_malformed_money_field_raises_instead_of_guessing():
    bt = bf.charge_bt("txn_x", "ch_x", 2999, "2026-11-01T12:00:00Z", 117)
    bt["amount"] = "29.99"
    with pytest.raises(ValueError):
        stripe_sync.to_row(bt, "sale")
    with pytest.raises(TypeError):
        ledger.LedgerRow(external_id="t", kind="sale", amount_minor=29.99, currency="USD",
                         occurred_at=NOW)


def test_sale_labels_come_from_the_checkout_session_then_the_charge():
    charge = {"description": "fallback", "billing_details": {"email": "c@x.com"}, "application": "ca_123",
              "metadata": {"utm_source": "Meta"}}
    s = bf.session("pi_1", ("Kit", 1), ("Bonus", 2), email="s@x.com",
                   client_reference_id="7b0c3c1e-5a52-4d62-9e7c-2a2b8f1c9d00")
    labels = stripe_sync.sale_labels(charge, s)
    assert labels["product"] == "Kit and 1 more" and labels["quantity"] == 3
    assert labels["customer_email"] == "s@x.com" and labels["via_platform"] == "ca_123"
    assert (labels["channel"], labels["attribution"]) == ("meta", "checkout_utm")
    assert str(labels["click_id"]) == "7b0c3c1e-5a52-4d62-9e7c-2a2b8f1c9d00"
    bare = stripe_sync.sale_labels(charge, None)
    assert bare["product"] == "fallback" and bare["customer_email"] == "c@x.com"
    assert stripe_sync.sale_labels({}, bf.session("pi_2", client_reference_id="not-a-uuid"))["click_id"] is None


# ─── a run: claim, read, write, move the watermark ──────────────────────────

def test_the_first_run_backfills_writes_every_movement_and_sets_measured_from(db, stripe):
    stripe.add(*bf.fixture_day())
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok", out
    rows = _stripe_rows(db)
    assert set(rows) == {"txn_sale0", "txn_ref0", "txn_sale9", "txn_dsp9", "txn_dsr9", "txn_fee1",
                         "txn_sale1", "txn_next"}                       # the payout is not revenue
    assert out["detail"]["not_revenue"] == {"payout": 1} and out["detail"]["unmapped_types"] == {}
    assert rows["txn_sale1"]["product"] == "AI Entrepreneur Blueprint Kit"
    assert rows["txn_sale1"]["customer_email"] == "buyer@example.com"      # lower-cased by the SQL
    assert rows["txn_ref0"]["order_ref"] == "ch_0" and rows["txn_ref0"]["amount_usd_cents"] == -1999
    # the window: from midnight in New York on BOARD_BACKFILL_FROM (default 1 Jan 2026) to the run's start
    listed = stripe.calls_to("/v1/balance_transactions")[0].url.params
    assert int(listed["created[gte]"]) == bf.unix("2026-01-01T05:00:00Z")
    assert int(listed["created[lt]"]) == int(NOW.timestamp())
    src = db.sources["stripe"]
    assert src["measured_from"] == date(2026, 1, 1)
    assert src["synced_through"] == NOW - timedelta(minutes=5)              # the run's start minus 5 min
    assert src["last_error"] is None and src["last_ok_at"] is not None
    (run,) = db.runs("stripe_sync")
    assert run["status"] == "ok" and run["source_id"] == "stripe" and run["rows_written"] == 8
    assert run["covered_until"] == NOW - timedelta(minutes=5) and run["detail"]["key"] == "STRIPE_READ_KEY"
    assert all(r["job_run_id"] == run["id"] for r in rows.values())


def test_a_resync_lands_on_the_same_rows_and_labels_each_sale_once(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=NOW)
    before = {k: dict(v) for k, v in _stripe_rows(db).items()}
    sessions_read = len(stripe.calls_to("/v1/checkout/sessions"))
    out = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok"
    # the 48-hour overlap re-reads 7 of the 8 movements (the 20 Oct sale is older)
    assert out["detail"]["inserted"] == 0 and out["detail"]["relabelled"] == 7
    assert out["detail"]["money_mismatches"] == 0 and out["rows_written"] == 0
    assert _stripe_rows(db) == before                                          # no second row, nothing changed
    assert len(stripe.calls_to("/v1/checkout/sessions")) == sessions_read      # labels fetched once
    second = stripe.calls_to("/v1/balance_transactions")[-1].url.params
    assert int(second["created[gte]"]) == int((NOW - timedelta(minutes=5) - timedelta(hours=48)).timestamp())
    assert db.sources["stripe"]["synced_through"] == NOW + timedelta(hours=1) - timedelta(minutes=5)
    assert db.sources["stripe"]["measured_from"] == date(2026, 1, 1)


def test_the_watermark_never_moves_back(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=NOW + timedelta(hours=2))
    assert stripe_sync.run(now=NOW)["status"] == "ok"                 # a run that started earlier finishes later
    assert db.sources["stripe"]["synced_through"] == NOW + timedelta(hours=2) - timedelta(minutes=5)


def test_new_movements_since_the_last_run_are_added(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=NOW)
    stripe.add([bf.charge_bt("txn_late", "ch_l", 900, "2026-11-02T12:30:00Z", 56)])
    out = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert out["detail"]["inserted"] == 1 and "txn_late" in _stripe_rows(db)


def test_a_money_mismatch_keeps_the_first_amount_and_is_reported(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=NOW)
    changed = next(b for b in stripe.balance_transactions if b["id"] == "txn_sale1")
    changed["amount"] = 3999
    out = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok" and out["detail"]["money_mismatches"] == 1
    assert "disagree" in out["error"]
    assert _stripe_rows(db)["txn_sale1"]["amount_usd_cents"] == 2999
    assert "disagree" in db.sources["stripe"]["last_error"]


def test_pages_are_followed(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe.page_size = 2
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    assert len(_stripe_rows(db)) == 8
    assert len(stripe.calls_to("/v1/balance_transactions")) == 5      # 9 transactions, 2 a page
    assert stripe.calls_to("/v1/balance_transactions")[1].url.params["starting_after"]


def test_a_rate_limit_or_a_stripe_outage_is_retried(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe.fail_next = [429, 503]
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    assert len(_stripe_rows(db)) == 8


def test_a_refused_key_fails_the_run_and_keeps_the_watermark(db, stripe, monkeypatch):
    db.set_source(measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_live_FAKEotherKey1")
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "failed" and "HTTP 401" in out["error"]
    assert "rk_live" not in out["error"] and "0000" not in out["error"]       # never the key, nor its tail
    assert db.sources["stripe"]["synced_through"] == datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)
    assert "HTTP 401" in db.sources["stripe"]["last_error"]
    (run,) = db.runs("stripe_sync")
    assert run["status"] == "failed" and run["finished_at"] is not None and _stripe_rows(db) == {}


def test_a_bad_money_field_fails_the_whole_batch_loudly(db, stripe):
    bts, sessions = bf.fixture_day()
    bad = bf.refund_bt("txn_bad", "re_x", "ch_1", 500, "2026-11-01T15:00:00Z")
    bad["amount"] = 500                                    # a refund that adds money: the SQL refuses it
    stripe.add(bts + [bad], sessions)
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "failed" and "ledger_entries_sign" in out["error"]
    assert "@" not in out["error"]                         # PostgREST's details (the failing row) are not passed on
    assert _stripe_rows(db) == {} and db.sources["stripe"]["synced_through"] is None
    assert db.sources["stripe"]["measured_from"] is None


def test_labels_never_block_money(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe.session_status = 403                            # a read key without Checkout access
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["label_errors"] == 3
    rows = _stripe_rows(db)
    assert len(rows) == 8 and rows["txn_sale1"]["product"] is None
    assert rows["txn_sale1"]["customer_email"] == "buyer@example.com"         # from the charge itself


def test_test_mode_objects_are_never_written(db, stripe):
    bts, sessions = bf.fixture_day()
    stripe.add(bts + [bf.charge_bt("txn_test", "ch_t", 100, "2026-11-01T15:00:00Z", 3, livemode=False)],
               sessions)
    out = stripe_sync.run(now=NOW)
    assert out["detail"]["skipped_test_mode"] == 1 and "txn_test" not in _stripe_rows(db)


def test_a_test_mode_key_is_refused_and_leaves_nothing_for_the_live_key(db, monkeypatch):
    test = bf.install_stripe(monkeypatch, key="sk_test_FAKEboardTest1", env="STRIPE_SECRET_KEY")
    test.add([bf.charge_bt("txn_test", "ch_t", 5000, "2026-10-20T15:00:00Z", 175, livemode=False)])
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "skipped" and "STRIPE_SECRET_KEY is a test-mode key" in out["error"]
    assert "sk_test_FAKEboardTest1" not in out["error"]
    assert test.calls == [] and db.calls == []          # no claim, no read, no watermark, no measured_from
    # the live key set afterwards runs as a first run: its backfill starts at BOARD_BACKFILL_FROM
    live = bf.install_stripe(monkeypatch)
    live.add([bf.charge_bt("txn_live", "ch_l", 2999, "2026-10-20T16:00:00Z", 117)])
    assert stripe_sync.run(now=NOW + timedelta(days=1))["status"] == "ok"
    listed = live.calls_to("/v1/balance_transactions")[0].url.params
    assert int(listed["created[gte]"]) == bf.unix("2026-01-01T05:00:00Z")
    assert set(_stripe_rows(db)) == {"txn_live"}
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_test_FAKEboardTest2")         # a restricted test key too
    assert stripe_sync.run(now=NOW + timedelta(days=2))["error"].startswith("STRIPE_READ_KEY is a test-mode key")


def test_a_payouts_fee_counts_in_fees_and_its_amount_does_not(db, stripe):
    stripe.add([bf.plain_bt("txn_ipo", "payout", -10000, "2026-11-01T15:00:00Z", fee=150, category="payout",
                            source="po_9"),
                bf.plain_bt("txn_po", "payout", -5000, "2026-11-01T16:00:00Z", category="payout", source="po_8")])
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and out["error"] is None
    assert out["detail"]["not_revenue"] == {"payout": 2} and out["detail"]["fees_kept"] == {"payout": 1}
    assert set(_stripe_rows(db)) == {"txn_ipo"}                       # a payout without a fee writes nothing
    row = _stripe_rows(db)["txn_ipo"]
    assert (row["kind"], row["amount_minor"], row["amount_usd_cents"], row["fee_usd_cents"]) == ("fee", 0, 0, 150)
    again = stripe_sync.run(now=NOW + timedelta(hours=1))             # re-read in the overlap: the same row
    assert again["detail"]["inserted"] == 0 and again["detail"]["money_mismatches"] == 0
    from core.board import day as board_day
    rev = board_day.day_view(date(2026, 11, 1))["numbers"]["revenue"]
    assert (rev["value"], rev["fees_usd_cents"], rev["counts"]) == (0, 150, {})


def test_an_unknown_type_is_skipped_named_and_reported(db, stripe):
    stripe.add([bf.plain_bt("txn_odd", "payment_reversal", -900, "2026-11-01T12:00:00Z", category="other"),
                bf.plain_bt("txn_cr", "stripe_fee", 300, "2026-11-01T13:00:00Z")])
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and _stripe_rows(db) == {}
    assert out["detail"]["unmapped_types"] == {"payment_reversal": 1, "stripe_fee (a credit)": 1}
    assert out["error"] == ("skipped 2 balance transactions of a type the board does not map "
                            "(payment_reversal, stripe_fee (a credit)): totals may differ from Stripe")
    (run,) = db.runs("stripe_sync")
    assert run["status"] == "ok" and run["error"] == out["error"]
    src = db.sources["stripe"]
    assert src["last_error"] == out["error"] and src["last_error_at"] == src["last_ok_at"]   # a warning
    assert src["measured_from"] == date(2026, 1, 1)                   # the money that was read still counts


def test_no_key_means_no_run_and_no_call(db, monkeypatch):
    monkeypatch.delenv("STRIPE_READ_KEY", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_your_stripe_key")    # the .env.example placeholder
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "skipped" and "STRIPE_READ_KEY" in out["error"]
    assert db.calls == [] and stripe_sync.read_key() is None


def test_the_read_key_wins_over_the_secret_key(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_FAKEsecret01")
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_live_FAKEread001")
    assert stripe_sync.read_key() == ("rk_live_FAKEread001", "STRIPE_READ_KEY")
    monkeypatch.delenv("STRIPE_READ_KEY")
    assert stripe_sync.read_key() == ("sk_live_FAKEsecret01", "STRIPE_SECRET_KEY")


def test_one_run_at_a_time_and_a_dead_run_is_recovered(db, stripe):
    stripe.add(*bf.fixture_day())
    db._rpc_board_claim_run("stripe_sync", "an-earlier-run", "schedule", "stripe")     # still running
    assert stripe_sync.run(now=NOW)["status"] == "busy"
    assert stripe.calls == []
    db.clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=31)              # it died 31 min ago
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    assert {r["run_key"]: r["status"] for r in db.runs("stripe_sync")}["an-earlier-run"] == "failed"


def test_days_widens_the_window_but_never_narrows_it(db, stripe):
    db.set_source(measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")
    stripe_sync.run(now=NOW, days=7)
    gte = int(stripe.calls_to("/v1/balance_transactions")[-1].url.params["created[gte]"])
    assert gte == int((NOW - timedelta(days=7)).timestamp())
    stripe_sync.run(now=NOW + timedelta(hours=1), days=1)
    gte = int(stripe.calls_to("/v1/balance_transactions")[-1].url.params["created[gte]"])
    assert gte == int((NOW - timedelta(minutes=5) - timedelta(hours=48)).timestamp())


def test_backfill_from_follows_the_setting(monkeypatch):
    monkeypatch.setenv("BOARD_BACKFILL_FROM", "2026-11-01")
    assert stripe_sync.backfill_start() == datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)   # EDT
    monkeypatch.setenv("BOARD_BACKFILL_FROM", "2026-12-01")
    assert stripe_sync.backfill_start() == datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)   # EST
    monkeypatch.setenv("BOARD_BACKFILL_FROM", "first of the year")
    assert stripe_sync.backfill_from() == date(2026, 1, 1)


def test_the_database_down_fails_the_run_without_calling_stripe(db, stripe):
    db.down = True
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"].startswith("database:")
    assert stripe.calls == []


# ─── the route: POST /api/board/sync/stripe ─────────────────────────────────

@pytest.fixture
def owner(monkeypatch):
    fake = bf.install(monkeypatch)
    monkeypatch.setattr(routes, "_last_sync", {})
    return bf.client(monkeypatch), bf.cookie(fake.add_session())


def test_the_sync_route_needs_the_owner_and_the_boards_own_origin(owner, db, stripe):
    client, cookie = owner
    assert client.post("/api/board/sync/stripe", headers=SAME_ORIGIN).status_code == 401
    assert client.post("/api/board/sync/stripe", headers={**cookie, "Origin": "https://evil.example"}
                       ).status_code == 403
    assert client.post("/api/board/sync/stripe", headers=cookie).status_code == 403      # no Origin at all
    assert stripe.calls == [] and db.runs("stripe_sync") == []


def test_the_sync_route_runs_one_sync_a_minute(owner, db, stripe, monkeypatch):
    client, cookie = owner
    stripe.add(*bf.fixture_day())
    r = client.post("/api/board/sync/stripe", headers={**cookie, **SAME_ORIGIN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["trigger_kind"] == "owner" and body["id"]
    assert db.runs("stripe_sync")[0]["trigger_kind"] == "owner" and len(_stripe_rows(db)) == 8
    again = client.post("/api/board/sync/stripe", headers={**cookie, **SAME_ORIGIN})
    assert again.status_code == 429 and int(again.headers["retry-after"]) >= 1
    assert len(db.runs("stripe_sync")) == 1


def test_the_sync_route_answers_each_outcome(owner, db, stripe, monkeypatch):
    client, cookie = owner
    headers = {**cookie, **SAME_ORIGIN}
    assert client.post("/api/board/sync/kdp", headers=headers).status_code == 404
    assert client.post("/api/board/sync/stripe?days=32", headers=headers).status_code == 422
    for status, code in (("busy", 409), ("skipped", 503), ("failed", 502)):
        monkeypatch.setattr(routes, "_last_sync", {})
        monkeypatch.setattr(stripe_sync, "run", lambda trigger, days, s=status: {"status": s})
        assert client.post("/api/board/sync/stripe", headers=headers).status_code == code


# ─── click attribution: a tracked /go link names the sale's channel ─────────

CLICKED = datetime(2026, 11, 1, 23, 50, tzinfo=timezone.utc)      # 19:50 on 1 Nov in New York


@pytest.fixture
def clicks(monkeypatch, db):
    """Store a /go click the way the route does; returns its id."""
    import core.click_tracker as ct
    monkeypatch.setattr(ct, "_clock", lambda: CLICKED)
    monkeypatch.setattr("core.telegram.notify_click", lambda **kwargs: True)
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", "https://buy.stripe.com/test_kit")

    def store(key="insider", utm_source=None):
        click = ct.new_click(key, referrer="https://blog.example.com/p",
                             query={"utm_source": utm_source} if utm_source else None)
        assert ct.save_click(click)
        return click.id
    return store


def _sessions(pi1=None, pi0=None):
    """The fixture day's Checkout Sessions, with these extra fields on pi_1's and pi_0's."""
    bts, (s0, s1) = bf.fixture_day()
    return bts, [{**s0, **(pi0 or {})}, {**s1, **(pi1 or {})}]


def _day_sale(day, external_kind, product=None):
    from core.board import day as board_day
    view = board_day.day_view(date.fromisoformat(day))
    return view, [s for s in view["sales"] if s["kind"] == external_kind and (product is None or s["product"] == product)]


def test_a_sale_through_a_tracked_link_is_credited_to_its_click(db, stripe, clicks):
    click_id = clicks("insider", utm_source="meta")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id}))
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["click_attributed"] == 1 and out["detail"]["label_errors"] == 0
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("click_id", "meta", click_id)
    view, (listed,) = _day_sale("2026-11-01", "sale")
    assert (listed["channel"], listed["attribution"]) == ("meta", "click_id")
    rev = view["numbers"]["revenue"]
    assert rev["attributed_usd_cents"] == 2999 and rev["by_channel"] == {"meta": 2999, "unattributed": -1999}


def test_a_refund_takes_its_sales_click(db, stripe, clicks):
    click_id = clicks("insider", utm_source="newsletter")
    stripe.add(*_sessions(pi0={"client_reference_id": click_id}))          # the 31 Oct sale, refunded on 1 Nov
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    assert _stripe_rows(db)["txn_sale0"]["click_id"] == click_id
    assert _stripe_rows(db)["txn_ref0"]["click_id"] is None                 # the refund stores no click itself
    view, (refund,) = _day_sale("2026-11-01", "refund")
    assert (refund["channel"], refund["attribution"]) == ("newsletter", "click_id")
    assert view["numbers"]["revenue"]["by_channel"]["newsletter"] == -1999


def test_a_click_with_no_utm_source_is_credited_to_its_key(db, stripe, clicks):
    click_id = clicks("insider")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id}))
    stripe_sync.run(now=NOW)
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("click_id", "insider", click_id)


def test_the_click_wins_over_a_checkout_utm_and_an_earlier_lead(db, stripe, clicks):
    ledger.ingest_leads("kit", None, [bf.optin(1, "2026-10-30T12:00:00Z", "organic", email="buyer@example.com")])
    click_id = clicks("insider", utm_source="meta")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id.upper(), "metadata": {"utm_source": "google"}}))
    stripe_sync.run(now=NOW)
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("click_id", "meta", click_id)
    _, (listed,) = _day_sale("2026-11-01", "sale")
    assert (listed["channel"], listed["attribution"]) == ("meta", "click_id")


def test_an_unknown_click_id_falls_back_to_the_checkout_utm_or_the_buyers_lead(db, stripe, clicks):
    clicks("insider", utm_source="meta")                                    # a stored click, not this one
    stranger = "7b0c3c1e-5a52-4d62-9e7c-2a2b8f1c9d00"
    stripe.add(*_sessions(pi1={"client_reference_id": stranger, "metadata": {"utm_source": "google"}},
                          pi0={"client_reference_id": "not-a-uuid"}))
    ledger.ingest_leads("kit", None, [bf.optin(7, "2026-10-01T12:00:00Z", "organic", email="old@example.com")])
    out = stripe_sync.run(now=NOW)
    assert out["detail"]["click_attributed"] == 0
    rows = _stripe_rows(db)
    assert (rows["txn_sale1"]["attribution"], rows["txn_sale1"]["channel"], rows["txn_sale1"]["click_id"]) == (
        "checkout_utm", "google", None)
    assert (rows["txn_sale0"]["attribution"], rows["txn_sale0"]["click_id"]) == ("none", None)
    _, (refund,) = _day_sale("2026-11-01", "refund")                        # the 31 Oct buyer's earlier opt-in
    assert (refund["channel"], refund["attribution"]) == ("organic", "lead_email")


def test_a_buyer_with_an_earlier_opt_in_and_no_click_is_credited_by_email(db, stripe):
    ledger.ingest_leads("kit", None, [bf.optin(1, "2026-10-30T12:00:00Z", "meta", email="buyer@example.com")])
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=NOW)
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("none", None, None)   # nothing stored
    _, (listed,) = _day_sale("2026-11-01", "sale")
    assert (listed["channel"], listed["attribution"]) == ("meta", "lead_email")      # matched when read


def test_a_failed_click_lookup_never_fails_the_run(db, stripe, clicks):
    click_id = clicks("insider", utm_source="meta")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id}))
    db.fail["clicks"] = 500
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["label_errors"] == 1 and out["detail"]["click_attributed"] == 0
    sale = _stripe_rows(db)["txn_sale1"]
    assert sale["amount_usd_cents"] == 2999 and sale["product"] == "AI Entrepreneur Blueprint Kit"
    # the SQL keeps a stored click's id even with no channel; nothing is credited to it
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("none", None, click_id)


UNLABELLED_3 = ("3 sales could not be labelled (Stripe's Checkout Session or the click could not be read): "
                "product and channel may be missing, so attributed revenue may be low")


def test_sales_that_could_not_be_labelled_are_named_and_labelled_by_a_later_run(db, stripe, clicks):
    """A key without Checkout Sessions read: the run is ok, but its warning
    says so (the board's note, the morning message), never a quiet
    'attributed $0.00'; once the key can read them, the next run labels the
    sales still in its read window."""
    from core.board import day as board_day
    click_id = clicks("insider", utm_source="newsletter")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id}))
    stripe.session_status = 403
    out = stripe_sync.run(now=NOW)
    assert out["status"] == "ok" and out["error"] == UNLABELLED_3
    assert out["detail"]["label_errors"] == 3 and out["detail"]["unlabelled"] == ["txn_sale0", "txn_sale1", "txn_sale9"]
    assert db.sources["stripe"]["last_error"] == UNLABELLED_3
    view = board_day.day_view(date(2026, 11, 1))
    assert f"last sync: {UNLABELLED_3}" in view["numbers"]["revenue"]["note"]
    assert UNLABELLED_3 in board_day.render_report(view)
    stripe.session_status = 200                                 # the key now reads Checkout Sessions
    again = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert again["status"] == "ok" and again["error"] is None and again["detail"]["unlabelled"] == []
    assert again["detail"]["click_attributed"] == 1 and again["detail"]["money_mismatches"] == 0
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["product"], sale["attribution"], sale["channel"], sale["click_id"]) == (
        "AI Entrepreneur Blueprint Kit", "click_id", "newsletter", click_id)
    assert _stripe_rows(db)["txn_sale0"]["product"] == "Toodle Guide"
    assert _stripe_rows(db)["txn_sale9"]["product"] is None     # 20 Oct: out of the read window, not tried again
    assert db.sources["stripe"]["last_error"] is None
    _, (listed,) = _day_sale("2026-11-01", "sale")
    assert (listed["channel"], listed["attribution"]) == ("newsletter", "click_id")


def test_a_sale_whose_click_could_not_be_checked_is_credited_by_the_next_run(db, stripe, clicks):
    import core.click_tracker as ct
    click_id = clicks("insider", utm_source="newsletter")
    stripe.add(*_sessions(pi1={"client_reference_id": click_id, "metadata": {"utm_source": "meta"}}))
    db.fail["clicks"] = 503                                     # one lookup fails
    out = stripe_sync.run(now=NOW)
    del db.fail["clicks"]
    assert out["status"] == "ok" and out["detail"]["unlabelled"] == ["txn_sale1"]
    assert out["error"].startswith("1 sale could not be labelled (")
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("checkout_utm", "meta", click_id)
    again = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert again["error"] is None and again["detail"]["click_attributed"] == 1
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["attribution"], sale["channel"], sale["click_id"]) == ("click_id", "newsletter", click_id)
    view, _ = _day_sale("2026-11-01", "sale")
    assert view["numbers"]["revenue"]["by_channel"]["newsletter"] == 2999
    assert ct.get_stats()["conversions_by_partner"] == {"insider": 1}       # /api/clicks agrees with the board


def test_a_sale_that_fails_again_keeps_the_labels_stored_the_first_time(db, stripe, clicks):
    click_id = clicks("insider", utm_source="newsletter")
    bts, sessions = _sessions(pi1={"client_reference_id": click_id})
    next(bt for bt in bts if bt["id"] == "txn_sale1")["source"]["description"] = "Stripe's own charge text"
    stripe.add(bts, sessions)
    db.fail["clicks"] = 503
    assert stripe_sync.run(now=NOW)["detail"]["unlabelled"] == ["txn_sale1"]
    del db.fail["clicks"]
    stripe.session_status = 403                                 # the retry cannot read its Checkout Session
    again = stripe_sync.run(now=NOW + timedelta(hours=1))
    assert again["detail"]["unlabelled"] == ["txn_sale1"]       # still to label: tried again next time
    sale = _stripe_rows(db)["txn_sale1"]
    assert (sale["product"], sale["click_id"]) == ("AI Entrepreneur Blueprint Kit", click_id)
    stripe.session_status = 200
    third = stripe_sync.run(now=NOW + timedelta(hours=2))
    assert third["error"] is None and _stripe_rows(db)["txn_sale1"]["channel"] == "newsletter"


def test_click_channel_follows_the_ledgers_channel_rule():
    assert ledger.click_channel({"partner": "insider", "utm": {"utm_source": " Meta-Ads "}}) == "meta_ads"
    assert ledger.click_channel({"partner": "insider", "utm": {}}) == "insider"
    assert ledger.click_channel({"partner": "my-key", "utm": {"utm_source": "Facebook Ads"}}) == "my_key"
    assert ledger.click_channel({"partner": "insider", "utm": {"utm_source": "unattributed"}}) == "insider"
    assert ledger.click_channel({"partner": "insider", "utm": {"utm_source": "x" * 33}}) == "insider"
    assert ledger.click_channel({"partner": "unattributed", "utm": {}}) is None
    assert ledger.click_channel({"partner": "k" * 40, "utm": None}) is None
    assert ledger.click_channel(None) is None


def test_clicks_by_id_reads_canonical_ids_in_chunks(db, clicks):
    stored = [clicks("insider") for _ in range(3)]
    db.calls.clear()
    ids = [stored[0].upper(), stored[1], "not-a-uuid", None, *[f"00000000-0000-4000-8000-{n:012d}" for n in range(205)]]
    found = ledger.clicks_by_id(ids)
    assert set(found) == {stored[0], stored[1]}
    assert found[stored[0]] == {"id": stored[0], "partner": "insider", "utm": {}}
    asked = [c.url.params["id"].removeprefix("in.(").removesuffix(")").split(",")
             for c in db.calls if c.url.path == "/rest/v1/clicks"]
    assert max(len(a) for a in asked) == 100                                      # 207 ids, 100 a call
    assert len({i for a in asked for i in a}) == 207 and "not-a-uuid" not in str(asked)
    db.max_rows = 1                                                               # a server that answers 1 row
    assert set(ledger.clicks_by_id(stored)) == set(stored)                        # still finds all three
