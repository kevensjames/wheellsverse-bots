"""scripts/board_import_json.py: the old JSON files' manual entries become
manual ledger rows and their clicks become rows of public.clicks, with keys
made from the records themselves, so the import can run any number of times.
Stripe's own payments are left to the Stripe sync, and no IP address is ever
stored or hashed. No network: the database is tests/board_fakes.py's
FakeBoardDB."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import board_fakes as bf

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
IPS = ("203.0.113.7", "198.51.100.9")


def _script():
    spec = importlib.util.spec_from_file_location("board_import_json", ROOT / "scripts" / "board_import_json.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imp = _script()

KDP = {"ts": "2026-09-30T10:15:00.123456", "type": "manual_kdp_royalty", "amount": 25.5, "currency": "usd",
       "email": "", "product": "September payout", "event_id": "manual_1759227300"}
PAYMENTS = [
    {"ts": "2026-10-01T12:00:00.000001", "type": "checkout.session.completed", "amount": 29.99, "currency": "usd",
     "email": "buyer@example.com", "product": "", "event_id": "evt_1"},             # the webhook's: Stripe's own
    KDP,
    {"ts": "2026-10-02T09:00:00", "type": "manual_stripe", "amount": 10.0, "currency": "usd", "email": "",
     "product": "", "event_id": "manual_1"},
    {"ts": "2026-10-03T09:00:00", "type": "manual_gumroad", "amount": 0, "currency": "usd", "email": "",
     "product": "", "event_id": "manual_2"},
    {"ts": "2026-10-04T09:00:00", "type": "manual_paypal", "amount": -4.5, "currency": "usd", "email": "",
     "product": "chargeback", "event_id": "manual_3"},
    {"ts": "2026-10-05T09:00:00", "type": "manual_x", "amount": 12.345, "currency": "usd", "email": "",
     "product": "", "event_id": "manual_4"},
    {"ts": "2026-10-06T09:00:00", "type": "manual_y", "amount": "abc", "currency": "usd", "email": "",
     "product": "", "event_id": "manual_5"},
    {"type": "manual_z", "amount": 3.0, "currency": "usd", "email": "", "product": "", "event_id": "manual_6"},
    {"ts": "2026-12-01T09:00:00", "type": "manual_future", "amount": 3.0, "currency": "usd", "email": "",
     "product": "", "event_id": "manual_7"},
    "not a record",
    dict(KDP),                                                                       # the same entry twice
]
AFFILIATE = {"amount": 40.0, "source": "affiliate", "label": "Impact payout", "ts": "2026-10-15T12:00:00+00:00",
             "metadata": {"program": "webull", "buyer_email": "x@y.example", "count": 2}}
REVENUE = {"records": [
    {"amount": 19.99, "source": "stripe", "label": "Blueprint", "ts": "2026-10-10T12:00:00+00:00",
     "metadata": {"stripe_id": "ch_1", "email": "a@b.example"}},
    {"amount": 7.0, "source": "manual", "label": "Coffee", "ts": "2026-10-11T12:00:00+00:00",
     "metadata": {"stripe_id": "ch_2"}},
    AFFILIATE]}
COINBASE = {"partner": "Coinbase", "ts": "2026-06-01T10:00:00.000001Z", "referrer": "https://Blog.Example.com/post?x=1",
            "ip": IPS[0], "dest": "https://stan.store/Wheellsverse?utm_source=wv&utm_content=coinbase"}
CLICKS = [
    COINBASE,
    {**COINBASE, "ip": IPS[1]},                                                      # differs only in its IP
    {"partner": "bad key!", "ts": "2026-06-01T10:00:00Z", "referrer": "", "ip": IPS[0], "dest": "https://x.example"},
    {"partner": "webull", "ts": "2026-06-02T11:00:00Z", "referrer": "", "ip": IPS[1], "dest": "https://buy.stripe.com/a"},
    {"partner": "x", "ts": "nope", "referrer": "", "ip": IPS[0], "dest": "https://x.example"},
    {"partner": "y", "ts": "2026-06-02T11:00:00Z", "referrer": "", "ip": IPS[0], "dest": "d" * 2049},
]


def _key(prefix, record):
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return prefix + hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def _click_key(record):
    canonical = {"partner": record["partner"], "ts": record["ts"], "referrer": record["referrer"],
                 "dest": record["dest"]}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def files(tmp_path):
    (tmp_path / "stripe_payments.json").write_text(json.dumps(PAYMENTS), encoding="utf-8")
    (tmp_path / "revenue.json").write_text(json.dumps(REVENUE), encoding="utf-8")
    (tmp_path / "clicks.json").write_text(json.dumps(CLICKS), encoding="utf-8")
    return tmp_path


@pytest.fixture
def db(monkeypatch):
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    return db


def run(folder, *extra, now=NOW):
    return imp.main(["--dir", str(folder), *extra], now=now)


def report(out: str, folder) -> str:
    """What the script said after its first line, which names the folder it read."""
    first, _, rest = out.partition("\n")
    assert first == f"Reading the files in {folder}."
    return rest


def test_only_manual_entries_and_clicks_are_imported_with_their_own_keys(files, db, capsys):
    assert run(files) == 0
    out = report(capsys.readouterr().out, files)
    rows = db.rows("manual")
    kdp = rows[_key("import:stripe_payments:", KDP)]
    assert (kdp["kind"], kdp["amount_minor"], kdp["currency"], kdp["amount_usd_cents"], kdp["fee_usd_cents"]) == (
        "sale", 2550, "USD", 2550, None)
    assert kdp["occurred_at"] == datetime(2026, 9, 30, 10, 15, 0, 123456, tzinfo=timezone.utc)   # naive: UTC
    assert kdp["product"] == "kdp_royalty: September payout"
    assert kdp["raw"] == {"imported_from": "stripe_payments.json", "source": "kdp_royalty",
                          "note": "September payout", "legacy_event_id": "manual_1759227300"}
    paypal = rows[_key("import:stripe_payments:", PAYMENTS[4])]
    assert (paypal["kind"], paypal["amount_minor"]) == ("adjustment", -450)
    assert rows[_key("import:stripe_payments:", PAYMENTS[5])]["amount_minor"] == 1235      # 12.345: half up
    affiliate = rows[_key("import:revenue:", AFFILIATE)]
    assert (affiliate["amount_minor"], affiliate["product"]) == (4000, "affiliate: Impact payout")
    assert affiliate["raw"] == {"imported_from": "revenue.json", "source": "affiliate", "label": "Impact payout",
                                "metadata": {"program": "webull", "count": 2}}       # never an email key
    assert len(rows) == 4 and db.rows("stripe") == {}                                 # Stripe's money: the sync's
    (run_row,) = db.runs("json_import")
    assert (run_row["status"], run_row["trigger_kind"], run_row["source_id"]) == ("ok", "script", "manual")
    assert all(r["job_run_id"] == run_row["id"] for r in rows.values())
    detail = run_row["detail"]
    assert detail["manual"]["new"] == 4 and detail["manual"]["already_there"] == 0
    assert detail["manual"]["skipped"] == {"bad_amount": 1, "bad_time": 1, "future": 1, "not_a_record": 1,
                                           "same_entry_twice": 1, "stripe_entries": 3, "stripe_payments": 1,
                                           "zero": 1}
    assert detail["manual"]["rounded"] == 1
    assert detail["clicks"] == {"read": 6, "to_import": 2, "new": 2, "already_there": 0,
                                "skipped": {"bad_destination": 1, "bad_partner": 1, "bad_time": 1,
                                            "same_click_twice": 1}}
    assert run_row["rows_written"] == 6
    clicks = sorted(db.clicks.values(), key=lambda c: c["clicked_at"])
    assert [(c["partner"], c["referrer_host"], c["destination"], c["import_key"]) for c in clicks] == [
        ("coinbase", "blog.example.com", COINBASE["dest"], _click_key(COINBASE)),
        ("webull", None, "https://buy.stripe.com/a", _click_key(CLICKS[3]))]
    assert clicks[0]["utm"] == {} and clicks[1]["utm"] == {}      # the old log never held the visitor's own tags
    assert clicks[0]["clicked_at"] == datetime(2026, 6, 1, 10, 0, 0, 1, tzinfo=timezone.utc)
    assert clicks[0]["local_day"].isoformat() == "2026-06-01"
    stored = json.dumps(list(db.clicks.values()), default=str) + json.dumps(list(rows.values()), default=str)
    sent = "".join(f"{c.url} {(c.content or b'').decode()}" for c in db.calls)
    for ip in IPS:
        assert ip not in stored and ip not in sent                            # no IP in a field, a key or a request
        assert hashlib.sha256(ip.encode()).hexdigest() not in stored          # nor its hash
    assert _click_key({**COINBASE, "ip": IPS[1]}) == _click_key(COINBASE)       # the IP is not in the key
    assert out.startswith("Imported 4 manual entries (4 new, 0 already there) and 2 clicks (2 new, 0 already "
                          "there). IP addresses were dropped.")
    assert "\n  Manual entries skipped, Stripe's own payments (the Stripe sync reads them from Stripe): 1\n" in out
    assert "\n  Manual entries skipped, marked as Stripe money (the Stripe sync reads it from Stripe): 3\n" in out
    assert "\n  Manual entries rounded to the cent (more than 2 decimal places): 1\n" in out
    assert "\n  Clicks skipped, listed twice (some differ only in IP address): 1\n" in out
    for secret in ("buyer@example.com", "x@y.example", "a@b.example", *IPS, bf.SERVICE, bf.URL):
        assert secret not in out


def test_a_second_run_writes_nothing_new_and_changes_no_money(files, db, capsys):
    assert run(files) == 0
    before = {k: dict(v) for k, v in db.ledger.items()}
    clicks = {k: dict(v) for k, v in db.clicks.items()}
    capsys.readouterr()
    assert run(files, now=NOW.replace(hour=17)) == 0
    out = report(capsys.readouterr().out, files)
    assert out.startswith("Imported 4 manual entries (0 new, 4 already there) and 2 clicks (0 new, 2 already there).")
    assert "another time or amount" not in out
    assert {k: {c: v[c] for c in ("kind", "amount_minor", "occurred_at", "product")} for k, v in db.ledger.items()} \
        == {k: {c: v[c] for c in ("kind", "amount_minor", "occurred_at", "product")} for k, v in before.items()}
    assert db.clicks == clicks
    first, second = db.runs("json_import")
    assert second["status"] == "ok" and second["detail"]["manual"]["money_mismatches"] == 0
    assert second["rows_written"] == 0


def test_another_time_zone_on_a_second_run_never_moves_money(files, db, capsys):
    assert run(files) == 0
    key = _key("import:stripe_payments:", KDP)
    at = db.rows("manual")[key]["occurred_at"]
    capsys.readouterr()
    assert run(files, "--naive-tz", "America/New_York", now=NOW.replace(hour=17)) == 0
    out = capsys.readouterr().out
    # the three naive times of stripe_payments.json moved; revenue.json's time carries its own zone
    assert "3 entries were already there with another time or amount. They were kept as they were" in out
    assert db.rows("manual")[key]["occurred_at"] == at


def test_the_naive_time_zone_is_honoured(files, db):
    assert run(files, "--naive-tz", "America/New_York") == 0
    kdp = db.rows("manual")[_key("import:stripe_payments:", KDP)]
    assert kdp["occurred_at"] == datetime(2026, 9, 30, 14, 15, 0, 123456, tzinfo=timezone.utc)   # 10:15 EDT
    affiliate = db.rows("manual")[_key("import:revenue:", AFFILIATE)]
    assert affiliate["occurred_at"] == datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)        # had its own zone


def test_a_dry_run_writes_nothing(files, db, capsys):
    assert run(files, "--dry-run") == 0
    out = report(capsys.readouterr().out, files)
    assert out.startswith("Dry run: nothing was written. 4 manual entries and 2 clicks would be imported")
    assert db.ledger == {} and db.clicks == {} and db.job_runs == {} and db.calls == []


def test_only_one_kind(files, db):
    assert run(files, "--only", "clicks") == 0
    assert db.ledger == {} and len(db.clicks) == 2
    assert run(files, "--only", "manual", now=NOW.replace(hour=17)) == 0
    assert len(db.rows("manual")) == 4


def test_nothing_is_imported_without_the_database(files, db, monkeypatch, capsys):
    db.down = True
    assert run(files) == 1
    assert "Nothing was imported: the database is not connected, or migration 0002 is not applied" in \
        capsys.readouterr().out
    db.down = False
    assert db.ledger == {} and db.clicks == {} and db.job_runs == {}
    db.fail["rpc/board_claim_run"] = 404                        # the migration is not applied
    assert run(files) == 1 and db.ledger == {}
    del db.fail["rpc/board_claim_run"]
    monkeypatch.delenv("SUPABASE_SERVICE_KEY")
    assert run(files) == 1
    assert "set SUPABASE_URL and SUPABASE_SERVICE_KEY" in capsys.readouterr().out


def test_a_write_that_fails_marks_the_run_failed(files, db, capsys):
    db.fail["clicks"] = 400
    assert run(files) == 1
    out = report(capsys.readouterr().out, files)
    assert out.startswith("The import stopped: the database refused a write") and "x@example.com" not in out
    (run_row,) = db.runs("json_import")
    assert run_row["status"] == "failed" and len(db.rows("manual")) == 4      # what was written is kept
    del db.fail["clicks"]
    assert run(files, now=NOW.replace(hour=17)) == 0 and len(db.clicks) == 2    # the next run finishes it


def test_another_import_running_is_left_alone(files, db, capsys):
    db._rpc_board_claim_run("json_import", "json_import:elsewhere", "script", "manual")
    assert run(files) == 1
    out = capsys.readouterr().out
    assert "another import is running" in out and "released after 30 minutes" in out and db.ledger == {}


def test_bad_input_exits_2_and_names_the_file(tmp_path, db, capsys):
    (tmp_path / "clicks.json").write_text("{not json", encoding="utf-8")
    assert run(tmp_path) == 2
    assert "clicks.json could not be read as JSON" in capsys.readouterr().out
    (tmp_path / "clicks.json").write_text('{"a": 1}', encoding="utf-8")
    assert run(tmp_path) == 2
    assert "clicks.json is not a list of clicks." in capsys.readouterr().out
    assert run(tmp_path, "--naive-tz", "Mars/Olympus") == 2
    assert db.calls == []


def test_missing_files_are_nothing_to_import(tmp_path, db, capsys):
    assert run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "stripe_payments.json is not in" in out and "clicks.json is not in" in out
    assert "Imported 0 manual entries (0 new, 0 already there) and 0 clicks" in out


def test_a_manual_stripe_entry_is_skipped_in_any_case(tmp_path, db):
    """The old POST /api/money/record wrote type manual_<source> as typed, so
    ?source=Stripe left 'manual_Stripe'. That money is the Stripe sync's: it
    is never imported a second time."""
    payments = [{"ts": "2026-10-02T09:00:00", "type": kind, "amount": 10.0, "currency": "usd", "email": "",
                 "product": "", "event_id": f"manual_{n}"}
                for n, kind in enumerate(("manual_Stripe", "manual_STRIPE", "manual_ Stripe "))]
    (tmp_path / "stripe_payments.json").write_text(json.dumps(payments), encoding="utf-8")
    assert run(tmp_path, "--only", "manual") == 0
    assert db.rows("manual") == {}
    (run_row,) = db.runs("json_import")
    assert run_row["detail"]["manual"]["skipped"] == {"stripe_entries": 3}
