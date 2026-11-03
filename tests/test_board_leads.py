"""Leads and Meta spend in the board's data layer (core/board/ledger.py), and
the test fake's copy of their SQL (tests/board_fakes.py): LeadRow and
AdSpendRow, board_ingest_leads in chunks, the ad_spend_daily upsert,
board_fill_fx, update_source, the stop rule's settings, and board_day's
optins, replies, spend and cpl blocks. No network: Supabase is faked. The fake
itself is checked against PostgreSQL 16 outside the suite."""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.board import ledger
from core.board.connectors import stripe_sync
from core.board.ledger import AdSpendRow, BoardDBError, LeadRow
from tests import board_fakes as bf

NY = ZoneInfo("America/New_York")
AT = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York
SCHEMA = (Path(__file__).resolve().parents[1] / "replica" / "schema.sql").read_text()
LEAD_KEYS = {"external_id", "kind", "occurred_at", "email", "funnel", "channel", "campaign_ref", "tags",
             "is_auto_reply", "raw"}


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("BOARD_CPL_DAYS", raising=False)
    monkeypatch.delenv("BOARD_CPL_STOP_CENTS", raising=False)
    return bf.install_board(monkeypatch)


def _day(day: str) -> dict:
    return ledger.board_day(date.fromisoformat(day))


def _days(first: str, n: int) -> list[str]:
    start = date.fromisoformat(first)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _sql_function(name: str) -> str:
    start = SCHEMA.index(f"create or replace function public.{name}(")
    return SCHEMA[start:SCHEMA.index("\n$$;", start)]


def _sql_columns(table: str) -> set[str]:
    start = SCHEMA.index(f"create table if not exists public.{table} (")
    return set(re.findall(r"^  (\w+) ", SCHEMA[start:SCHEMA.index("\n);", start)], re.M)) - {"constraint"}


def _code(error: BaseException) -> str:
    """The SQLSTATE in a BoardDBError's message: '...: HTTP 400 (23514: ...)'."""
    found = re.search(r"\(([0-9A-Z]{5}|PGRST\d+):", str(error))
    return found.group(1) if found else ""


# ─── LeadRow ────────────────────────────────────────────────────────────────

def test_a_lead_row_refuses_what_would_fail_the_sql():
    ok = dict(external_id="toodle:sub:1", kind="optin", occurred_at=AT)
    for bad in ("signup", "Optin", None):
        with pytest.raises(ValueError):
            LeadRow(**{**ok, "kind": bad})
    with pytest.raises(ValueError):
        LeadRow(**{**ok, "occurred_at": datetime(2026, 11, 1, 13, 0)})          # no time zone
    for bad in (date(2026, 11, 1), "2026-11-01T13:00:00Z"):
        with pytest.raises(TypeError):
            LeadRow(**{**ok, "occurred_at": bad})
    for bad in ("", "x" * 256, "a\x00b"):
        with pytest.raises(ValueError):
            LeadRow(**{**ok, "external_id": bad})
    with pytest.raises(TypeError):
        LeadRow(**{**ok, "external_id": 123})
    assert LeadRow(**{**ok, "external_id": "x" * 255}).external_id == "x" * 255
    with pytest.raises(ValueError):
        LeadRow(**ok, is_auto_reply=True)                                         # only a reply can be one
    assert LeadRow(**{**ok, "kind": "reply"}, is_auto_reply=True).is_auto_reply is True
    with pytest.raises(TypeError):
        LeadRow(**{**ok, "kind": "reply"}, is_auto_reply=1)
    for bad in ("Toodle Guide", "toodle-guide", "x" * 33, "tööd"):               # the funnel check has no fallback
        with pytest.raises(ValueError):
            LeadRow(**ok, funnel=bad)
    for bad in ("toodle", [1], ("a", None)):
        with pytest.raises(TypeError):
            LeadRow(**ok, tags=bad)
    with pytest.raises(TypeError):
        LeadRow(**ok, raw=["not", "an", "object"])
    with pytest.raises(TypeError):
        LeadRow(**ok, email=42)
    assert LeadRow(**ok, tags=["toodle", "meta_ad"]).tags == ("toodle", "meta_ad")


def test_labels_stay_as_given_for_the_sql_to_normalise():
    row = LeadRow("toodle:sub:2", "optin", AT, email=" Lead@Example.COM ", funnel=" Toodle ",
                  channel="Meta Ads!", tags=("Toodle", "META_AD"))
    out = row.as_json()
    assert (out["email"], out["funnel"], out["channel"], out["tags"]) == \
        (" Lead@Example.COM ", " Toodle ", "Meta Ads!", ["Toodle", "META_AD"])


def test_a_lead_rows_json_has_exactly_the_columns_the_sql_reads():
    sql = re.search(r"jsonb_to_recordset\(p_rows\) as x\((.*?)\)", _sql_function("board_ingest_leads"), re.S)
    assert {c.split()[0] for c in sql.group(1).split(",")} == LEAD_KEYS
    est = datetime(2026, 11, 1, 23, 30, tzinfo=NY)                                # 23:30 EST on the 25-hour day
    out = LeadRow("em1", "reply", est).as_json()
    assert set(out) == LEAD_KEYS
    assert out == {"external_id": "em1", "kind": "reply", "occurred_at": "2026-11-02T04:30:00+00:00",
                   "email": None, "funnel": None, "channel": None, "campaign_ref": None, "tags": [],
                   "is_auto_reply": False, "raw": {}}


def test_a_nul_in_a_label_is_dropped_so_it_cannot_fail_the_batch(db):
    row = LeadRow("em9", "reply", AT, email="p\x00@shop.example", tags=("a\x00",),
                  raw={"subject": "re\x00: hi", "list": ["x\x00"]})
    assert "\\u0000" not in json.dumps(row.as_json())
    assert ledger.ingest_leads("instantly", None, [row])["inserted"] == 1
    stored = db.lead_rows("instantly")["em9"]
    assert stored["email"] == "p@shop.example" and stored["raw"] == {"subject": "re: hi", "list": ["x"]}


# ─── ingest_leads ───────────────────────────────────────────────────────────

def test_ingest_leads_sends_chunks_and_sums_the_counts(db, monkeypatch):
    monkeypatch.setattr(ledger, "_INGEST_CHUNK", 2)
    rows = [bf.optin(i, f"2026-11-01T1{i}:00:00Z", "meta") for i in range(5)]
    assert ledger.ingest_leads("kit", None, rows) == {"received": 5, "inserted": 5, "relabelled": 0}
    calls = db.rpc_calls("board_ingest_leads")
    assert [len(c["p_rows"]) for c in calls] == [2, 2, 1]
    assert all(c["p_source_id"] == "kit" and c["p_job_run_id"] is None for c in calls)
    assert calls[0]["p_rows"][0] == rows[0].as_json()
    assert ledger.ingest_leads("kit", None, rows) == {"received": 5, "inserted": 0, "relabelled": 5}
    assert ledger.ingest_leads("kit", None, []) == {"received": 0, "inserted": 0, "relabelled": 0}
    assert len(db.rpc_calls("board_ingest_leads")) == 6                        # nothing sent for no rows


def test_rows_sharing_an_external_id_are_never_split_across_calls(db, monkeypatch):
    monkeypatch.setattr(ledger, "_INGEST_CHUNK", 2)
    rows = [bf.optin("a", "2026-11-01T15:00:00Z"), bf.optin("b", "2026-11-01T15:00:00Z"),
            bf.optin("a", "2026-11-01T12:00:00Z", "meta"), bf.optin("c", "2026-11-01T15:00:00Z")]
    assert ledger.ingest_leads("kit", None, rows) == {"received": 3, "inserted": 3, "relabelled": 0}
    calls = [[r["external_id"] for r in c["p_rows"]] for c in db.rpc_calls("board_ingest_leads")]
    assert calls == [["toodle:sub:a", "toodle:sub:a"], ["toodle:sub:b", "toodle:sub:c"]]
    many = [bf.optin("d", f"2026-11-01T1{i}:00:00Z") for i in range(3)]          # more than a chunk: one call
    ledger.ingest_leads("kit", None, many)
    assert len(db.rpc_calls("board_ingest_leads")[-1]["p_rows"]) == 3


def test_a_refused_batch_raises_and_writes_nothing(db):
    with pytest.raises(BoardDBError) as e:
        ledger.ingest_leads("kdp", None, [bf.optin(1, "2026-11-01T12:00:00Z")])
    assert "not an API or manual source" in str(e.value) and db.leads == {}
    db.fail["rpc/board_ingest_leads"] = 500
    with pytest.raises(BoardDBError) as e:
        ledger.ingest_leads("kit", None, [bf.optin(1, "2026-11-01T12:00:00Z")])
    assert "HTTP 500" in str(e.value) and "x@example.com" not in str(e.value)    # never the row in details


# ─── the fake's board_ingest_leads: the SQL's merge rules ───────────────────

def test_the_earliest_time_wins_in_one_batch_and_across_runs(db):
    ledger.ingest_leads("kit", None, [bf.optin(102, "2026-11-01T14:00:00Z", "organic", tags=("Blog",)),
                                      bf.optin(102, "2026-11-01T12:00:00Z", tags=("Toodle",))])
    row = db.lead_rows("kit")["toodle:sub:102"]
    # within one call the earliest row wins whole: the later row's channel and tag are dropped
    assert (row["occurred_at"], row["channel"], row["tags"]) == \
        (datetime(2026, 11, 1, 12, tzinfo=timezone.utc), "unknown", ["toodle"])
    ledger.ingest_leads("kit", None, [bf.optin(102, "2026-11-01T15:00:00Z", "organic", tags=("blog",))])
    row = db.lead_rows("kit")["toodle:sub:102"]
    assert (row["occurred_at"].hour, row["channel"], row["tags"]) == (12, "organic", ["blog", "toodle"])
    ledger.ingest_leads("kit", None, [bf.optin(102, "2026-11-01T11:00:00Z")])
    assert db.lead_rows("kit")["toodle:sub:102"]["occurred_at"].hour == 11


def test_a_known_channel_fills_unknown_and_is_never_replaced(db):
    run = lambda channel: ledger.ingest_leads("kit", None, [bf.optin(1, "2026-11-01T12:00:00Z", channel)])
    run(None)
    assert db.lead_rows()["toodle:sub:1"]["channel"] == "unknown"
    run("Meta")
    assert db.lead_rows()["toodle:sub:1"]["channel"] == "meta"
    run("organic")
    assert db.lead_rows()["toodle:sub:1"]["channel"] == "meta"
    ledger.ingest_leads("kit", None, [bf.optin(2, "2026-11-01T12:00:00Z", "Facebook Ads!")])
    assert db.lead_rows()["toodle:sub:2"]["channel"] == "other"                 # malformed: other, not a failure
    ledger.ingest_leads("kit", None, [bf.optin(2, "2026-11-01T12:00:00Z", "meta")])
    assert db.lead_rows()["toodle:sub:2"]["channel"] == "other"                 # only 'unknown' is filled


def test_tags_are_lower_cased_then_unioned_sorted_and_distinct(db):
    ledger.ingest_leads("kit", None, [bf.optin(1, "2026-11-01T12:00:00Z", tags=("Toodle", "META_AD", "toodle"))])
    assert db.lead_rows()["toodle:sub:1"]["tags"] == ["toodle", "meta_ad", "toodle"]   # an insert keeps them as sent
    ledger.ingest_leads("kit", None, [bf.optin(1, "2026-11-01T12:00:00Z", tags=("Blog",))])
    assert db.lead_rows()["toodle:sub:1"]["tags"] == ["blog", "meta_ad", "toodle"]


def test_email_funnel_and_campaign_are_normalised_and_filled_only_where_missing(db):
    ledger.ingest_leads("instantly", None, [LeadRow("em1", "reply", AT, email="not-an-email", funnel=" SiteBoost ")])
    row = db.lead_rows("instantly")["em1"]
    assert (row["email"], row["funnel"], row["channel"], row["campaign_ref"]) == (None, "siteboost", "unknown", None)
    ledger.ingest_leads("instantly", None, [LeadRow("em1", "reply", AT, email=" P1@Shop.Example ",
                                                    campaign_ref="camp-1")])
    ledger.ingest_leads("instantly", None, [LeadRow("em1", "reply", AT, email="other@shop.example",
                                                    campaign_ref="camp-2")])
    row = db.lead_rows("instantly")["em1"]
    assert (row["email"], row["campaign_ref"]) == ("p1@shop.example", "camp-1")


def test_an_auto_reply_flag_is_ored_and_only_a_reply_can_carry_it(db):
    flag = lambda auto: ledger.ingest_leads("instantly", None, [bf.reply("em10", "2026-11-01T15:00:00Z",
                                                                        "p6@shop.example", auto=auto)])
    flag(False)
    flag(True)
    flag(False)
    assert db.lead_rows("instantly")["em10"]["is_auto_reply"] is True           # once an auto-reply, always one
    row = {"external_id": "toodle:sub:9", "kind": "optin", "occurred_at": "2026-11-01T12:00:00Z",
           "is_auto_reply": True}
    with pytest.raises(BoardDBError) as e:                                       # past LeadRow: the SQL's own check
        ledger.rpc("board_ingest_leads", {"p_source_id": "kit", "p_job_run_id": None, "p_rows": [row]})
    assert _code(e.value) == "23514" and "lead_events_auto_reply_is_reply" in str(e.value)
    ledger.ingest_leads("kit", None, [bf.optin(9, "2026-11-01T12:00:00Z")])
    with pytest.raises(BoardDBError):                                            # the merge would make an opt-in one
        ledger.rpc("board_ingest_leads", {"p_source_id": "kit", "p_job_run_id": None,
                                          "p_rows": [{**row, "kind": "reply"}]})
    assert db.lead_rows("kit")["toodle:sub:9"]["is_auto_reply"] is False


def test_the_fake_refuses_what_the_sql_refuses_and_writes_nothing(db):
    good = {"external_id": "x1", "kind": "optin", "occurred_at": "2026-11-01T12:00:00Z"}
    cases = [({**good, "funnel": "Toodle Guide"}, None, "23514"), ({**good, "occurred_at": None}, None, "23502"),
             ({**good, "external_id": ""}, None, "23514"), ({**good, "kind": "Optin"}, None, "23514"),
             ({**good, "raw": [1]}, None, "23514"), ({**good, "occurred_at": "not a time"}, None, "22007"),
             (good, "not-a-uuid", "22P02"), (good, "0b7e3c2a-1111-4222-8333-944455566677", "23503"),
             ({**good, "email": "a\u0000@b.example"}, None, "22P05")]
    for row, run_id, code in cases:
        with pytest.raises(BoardDBError) as e:
            ledger.rpc("board_ingest_leads", {"p_source_id": "kit", "p_job_run_id": run_id,
                                              "p_rows": [good | {"external_id": "x0"}, row]})
        assert _code(e.value) == code, (row, str(e.value))
    assert db.leads == {}
    ledger.rpc("board_ingest_leads", {"p_source_id": "kit", "p_job_run_id": None,      # a word Postgres takes
                                      "p_rows": [{**good, "occurred_at": "epoch"}]})
    assert db.lead_rows()["x1"]["occurred_at"] == datetime(1970, 1, 1, tzinfo=timezone.utc)
    run_id = ledger.claim_run("kit_sync", "run-1", "schedule", "kit")
    assert ledger.ingest_leads("kit", run_id, [bf.optin(1, "2026-11-01T12:00:00Z")])["inserted"] == 1
    assert db.lead_rows()["toodle:sub:1"]["job_run_id"] == run_id


# ─── board_day: optins, replies, spend and cpl ──────────────────────────────

def test_the_plans_day_has_its_opt_ins_replies_spend_and_stop_rule(db):
    bf.load_fixture_leads(db)
    j = _day("2026-11-01")
    assert j["hours_in_day"] == 25
    assert j["optins"] == {"total": 2, "by_channel": {"meta": 1, "organic": 1}}
    assert j["replies"] == {"people": 1, "auto_replies": 1, "people_7d": 2}
    assert j["spend"] == {"toodle_usd_cents": 502, "all_usd_cents": 1502, "toodle_link_clicks": 9,
                          "impressions": 10200, "unconverted_rows": 0, "last_pulled_at": j["spend"]["last_pulled_at"]}
    assert ledger.parse_ts(j["spend"]["last_pulled_at"]) is not None
    assert j["cpl"] == {"spend_days": 5, "first_day": "2026-10-28", "last_day": "2026-11-01",
                        "spend_usd_cents": 2510, "unconverted_spend_rows": 0, "meta_optins": 4,
                        "toodle_optins": 5, "cpl_meta_usd_cents": 628, "cpl_all_usd_cents": 502,
                        "stop_above_cents": 500, "verdict": "stop"}
    states = {s["id"]: s["state"] for s in j["sources"]}
    assert (states["kit"], states["instantly"], states["meta_ads"]) == ("final", "final", "final")
    nov2 = _day("2026-11-02")
    assert nov2["optins"] == {"total": 1, "by_channel": {"meta": 1}} and nov2["spend"]["toodle_usd_cents"] == 0


def test_a_sale_is_attributed_through_the_buyers_earlier_opt_in(db, monkeypatch):
    stripe = bf.install_stripe(monkeypatch)
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    bf.load_fixture_leads(db)
    j = _day("2026-11-01")
    assert j["revenue"]["attributed_usd_cents"] == 2999
    assert j["by_channel"] == {"meta": 2999, "unattributed": -1999}                # the plan's JSON
    sale = j["sales"][-1]
    assert (sale["kind"], sale["channel"], sale["attribution"]) == ("sale", "meta", "lead_email")


def test_opt_ins_count_on_new_york_days_through_the_25_hour_day(db):
    edges = [("a", "2026-11-01T03:59:59Z"),     # 23:59:59 EDT on 31 Oct
             ("b", "2026-11-01T04:00:00Z"),     # 00:00 EDT on 1 Nov: the day starts
             ("c", "2026-11-01T05:30:00Z"),     # 01:30 EDT
             ("d", "2026-11-01T06:30:00Z"),     # 01:30 EST: the hour that repeats
             ("e", "2026-11-02T04:59:59Z"),     # 23:59:59 EST: the day's last second
             ("f", "2026-11-02T05:00:00Z")]     # 00:00 EST on 2 Nov
    ledger.ingest_leads("kit", None, [bf.optin(s, at, "meta") for s, at in edges])
    totals = lambda: [_day(d)["optins"]["total"] for d in ("2026-10-31", "2026-11-01", "2026-11-02")]
    assert totals() == [1, 4, 1]
    ledger.ingest_leads("kit", None, [bf.optin("f", "2026-11-02T04:00:00Z")])   # an earlier tag moves it back a day
    assert totals() == [1, 5, 0]


def test_replies_count_distinct_prospects_over_seven_new_york_days(db):
    ledger.ingest_leads("instantly", None, [
        bf.reply("em1", "2026-11-01T13:00:00Z", "p1@shop.example"),
        bf.reply("em2", "2026-11-01T18:00:00Z", " P1@Shop.Example "),         # the same prospect
        bf.reply("em3", "2026-11-01T19:00:00Z", "p2@shop.example", auto=True),
        bf.reply("em4", "2026-11-02T04:30:00Z"),                               # no address: counted by its id
        bf.reply("em5", "2026-10-26T04:00:00Z", "p3@shop.example"),            # 00:00 EDT, 6 days back: in
        bf.reply("em6", "2026-10-26T03:59:59Z", "p4@shop.example"),            # 7 days back: out
        bf.reply("em7", "2026-11-02T05:00:00Z", "p5@shop.example"),            # the next day: out
        bf.reply("em8", "2026-10-29T12:00:00Z", "p1@shop.example")])           # p1 again, earlier in the week
    assert _day("2026-11-01")["replies"] == {"people": 2, "auto_replies": 1, "people_7d": 3}
    other_funnel = LeadRow("em9", "reply", AT, email="p9@shop.example", funnel="other_campaign")
    ledger.ingest_leads("instantly", None, [other_funnel])
    assert _day("2026-11-01")["replies"]["people"] == 2                         # SiteBoost replies only


def _spend_days(first: str, n: int, cents: int, **kw) -> None:
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend(d, cents, **kw) for d in _days(first, n)])


@pytest.mark.parametrize("scenario, verdict", [
    ("no spend in the 30 days", "no_spend"),
    ("3 spend days", "collecting"),
    ("$6.28 a Meta opt-in", "stop"),
    ("opt-ins, none tagged meta", "check_tags"),
    ("no opt-ins after $25.10", "stop"),
    ("no opt-ins after $2.50", "collecting"),
    ("exactly $5.00 a Meta opt-in", "ok"),
    ("a euro day not yet converted", "check_currency"),
])
def test_the_stop_rule_verdicts(db, scenario, verdict):
    day = "2026-11-01"
    if scenario == "no spend in the 30 days":
        _spend_days("2026-09-20", 5, 502)                                      # 31 days before: outside
    elif scenario == "3 spend days":
        _spend_days("2026-10-30", 3, 502)
    elif scenario == "$6.28 a Meta opt-in":
        bf.load_fixture_leads(db)
    elif scenario == "opt-ins, none tagged meta":
        _spend_days("2026-10-28", 5, 502)
        ledger.ingest_leads("kit", None, [bf.optin(i, f"2026-10-2{8 + i}T15:00:00Z", "organic") for i in range(2)])
    elif scenario == "no opt-ins after $25.10":
        _spend_days("2026-10-28", 5, 502)
    elif scenario == "no opt-ins after $2.50":
        _spend_days("2026-10-28", 5, 50)
    elif scenario == "exactly $5.00 a Meta opt-in":
        _spend_days("2026-10-28", 5, 100)
        ledger.ingest_leads("kit", None, [bf.optin(1, "2026-10-29T15:00:00Z", "meta")])
    elif scenario == "a euro day not yet converted":
        _spend_days("2026-10-28", 4, 502)
        ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 450, currency="EUR")])
    assert _day(day)["cpl"]["verdict"] == verdict


def test_the_stop_rule_counts_the_last_spend_days_not_calendar_days(db):
    _spend_days("2026-10-20", 2, 502)                                          # 20 and 21 Oct
    _spend_days("2026-10-30", 3, 502)                                          # 30, 31 Oct and 1 Nov
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-10-25", 0)])      # a zero day is not a spend day
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-10-26", 9999, funnel=None)])   # not Toodle
    cpl = _day("2026-11-01")["cpl"]
    assert (cpl["spend_days"], cpl["first_day"], cpl["last_day"], cpl["spend_usd_cents"]) == \
        (5, "2026-10-20", "2026-11-01", 2510)


def test_a_converted_euro_day_counts_in_usd(db):
    _spend_days("2026-10-28", 4, 502)
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 450, currency="EUR")])
    ledger.ingest_leads("kit", None, [bf.optin(i, f"2026-10-2{8 + i}T15:00:00Z", "meta") for i in range(2)])
    assert _day("2026-11-01")["spend"]["unconverted_rows"] == 1
    db.add_fx_rate("EUR", "2026-10-30", "1.1")                                 # Friday's rate for Sunday
    assert ledger.fill_fx() == 1
    j = _day("2026-11-01")
    assert j["spend"]["toodle_usd_cents"] == 495 and j["spend"]["unconverted_rows"] == 0
    assert (j["cpl"]["spend_usd_cents"], j["cpl"]["cpl_meta_usd_cents"], j["cpl"]["verdict"]) == (2503, 1252, "stop")


# ─── the stop rule's settings ───────────────────────────────────────────────

def test_board_day_sends_the_stop_rule_settings(db, monkeypatch):
    bf.load_fixture_leads(db)
    ledger.board_day(date(2026, 11, 1))
    ledger.board_day(None)                                                      # yesterday, decided in SQL
    assert db.rpc_calls("board_day") == [{"p_day": "2026-11-01", "p_cpl_days": 5, "p_cpl_stop_cents": 500},
                                         {"p_day": None, "p_cpl_days": 5, "p_cpl_stop_cents": 500}]
    monkeypatch.setenv("BOARD_CPL_DAYS", " 3 ")
    monkeypatch.setenv("BOARD_CPL_STOP_CENTS", "700")
    cpl = _day("2026-11-01")["cpl"]
    assert db.rpc_calls("board_day")[-1] == {"p_day": "2026-11-01", "p_cpl_days": 3, "p_cpl_stop_cents": 700}
    # the last 3 spend days: $15.06 for 3 Meta opt-ins = $5.02, under $7.00
    assert (cpl["spend_days"], cpl["first_day"], cpl["meta_optins"], cpl["stop_above_cents"], cpl["verdict"]) == \
        (3, "2026-10-30", 3, 700, "ok")


@pytest.mark.parametrize("bad", ["0", "31", "five", "5.5", "-1", "1_0", "٥", "99999999999"])
def test_an_invalid_cpl_days_falls_back_to_5_with_one_warning(db, monkeypatch, caplog, bad):
    monkeypatch.setattr(ledger, "_cpl_warned", set())
    monkeypatch.setenv("BOARD_CPL_DAYS", bad)
    caplog.set_level(logging.WARNING, logger="board.ledger")
    assert ledger.cpl_settings() == (5, 500)
    ledger.board_day(date(2026, 11, 1))
    assert db.rpc_calls("board_day")[-1]["p_cpl_days"] == 5
    warnings = [r.getMessage() for r in caplog.records if r.name == "board.ledger" and r.levelno == logging.WARNING]
    assert warnings == ["BOARD_CPL_DAYS must be a whole number of days from 1 to 30; using 5"]   # never the value


@pytest.mark.parametrize("bad", ["0", "-500", "$5", "5.00", "2147483648"])
def test_an_invalid_stop_threshold_falls_back_to_500_with_one_warning(db, monkeypatch, caplog, bad):
    monkeypatch.setattr(ledger, "_cpl_warned", set())
    monkeypatch.setenv("BOARD_CPL_STOP_CENTS", bad)
    caplog.set_level(logging.WARNING, logger="board.ledger")
    assert ledger.cpl_settings() == (5, 500) and ledger.cpl_settings().stop_cents == 500
    assert len([r for r in caplog.records if "BOARD_CPL_STOP_CENTS" in r.getMessage()]) == 1


def test_the_settings_defaults_and_bounds_match_the_sql():
    signature = _sql_function("board_day")
    assert int(re.search(r"p_cpl_days int default (\d+)", signature).group(1)) == ledger.CPL_DAYS_DEFAULT
    assert int(re.search(r"p_cpl_stop_cents int default (\d+)", signature).group(1)) == ledger.CPL_STOP_CENTS_DEFAULT
    assert re.search(r"p_lookback_days int default (\d+)", _sql_function("board_cpl")).group(1) == "30"


# ─── AdSpendRow and the upsert ──────────────────────────────────────────────

def test_an_ad_spend_row_refuses_what_would_fail_the_table():
    ok = dict(campaign_id="120249191226470279", day=date(2026, 11, 1), currency="USD", spend_minor=502)
    for name, bad, error in [("spend_minor", -1, ValueError), ("spend_minor", 12.5, TypeError),
                             ("spend_minor", True, TypeError), ("spend_minor", "502", TypeError),
                             ("spend_minor", 2 ** 63, ValueError), ("day", datetime(2026, 11, 1), TypeError),
                             ("day", "2026-11-01", TypeError), ("currency", "US", ValueError),
                             ("currency", "USDX", ValueError), ("currency", 5, TypeError),
                             ("campaign_id", "", ValueError), ("campaign_id", "1" * 65, ValueError),
                             ("funnel", "toodle guide", ValueError), ("impressions", -1, ValueError),
                             ("link_clicks", None, TypeError), ("platform_leads", 2 ** 31, ValueError),
                             ("campaign_name", 7, TypeError)]:
        with pytest.raises(error):
            AdSpendRow(**{**ok, name: bad})
    row = AdSpendRow(**ok, funnel=" Toodle ", campaign_name="Toodle", platform_leads=None)
    assert (row.funnel, row.currency) == ("toodle", "USD")
    assert AdSpendRow(**{**ok, "currency": " eur "}).currency == "EUR"
    assert AdSpendRow(**{**ok, "campaign_id": "1" * 64}, funnel="").funnel is None
    with pytest.raises(TypeError):
        AdSpendRow("120249191226470279", None, "toodle", date(2026, 11, 1), "USD", 502)   # keywords only


def test_spend_json_is_its_own_usd_or_sends_explicit_nulls():
    usd = bf.spend("2026-11-01", 502, link_clicks=9).as_json()
    eur = bf.spend("2026-11-01", 450, currency="EUR").as_json()
    assert set(usd) == set(eur)                                                 # every row, the same columns
    assert (usd["spend_usd_cents"], usd["fx_source"], usd["fx_rate"]) == (502, "identity", None)
    assert (eur["spend_usd_cents"], eur["fx_source"], eur["fx_rate"]) == (None, None, None)
    assert all(k in eur for k in ("spend_usd_cents", "fx_source", "fx_rate"))   # explicit, not left out
    assert usd["day"] == "2026-11-01" and usd["link_clicks"] == 9
    columns = _sql_columns("ad_spend_daily")
    assert set(usd) | {"source_id", "job_run_id", "pulled_at"} <= columns
    assert set(bf.SPEND_COLUMNS) <= columns


def test_upsert_ad_spend_posts_an_upsert_on_the_tables_key(db, monkeypatch):
    monkeypatch.setattr(ledger, "_SPEND_CHUNK", 2)
    rows = [bf.spend(d, 502) for d in _days("2026-10-28", 4)] + [bf.spend("2026-11-01", 450, currency="EUR")]
    assert ledger.upsert_ad_spend("meta_ads", None, rows) == 5
    posts = [c for c in db.calls if c.url.path == "/rest/v1/ad_spend_daily"]
    assert [c.method for c in posts] == ["POST"] * 3
    for c in posts:
        assert c.url.params["on_conflict"] == "source_id,campaign_id,day"
        assert c.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    bodies = [json.loads(c.content) for c in posts]
    assert [len(b) for b in bodies] == [2, 2, 1]
    sent = [r for b in bodies for r in b]
    assert {r["source_id"] for r in sent} == {"meta_ads"} and {r["job_run_id"] for r in sent} == {None}
    assert len({r["pulled_at"] for r in sent}) == 1 and ledger.parse_ts(sent[0]["pulled_at"]) is not None
    assert {k: sent[-1][k] for k in ("spend_usd_cents", "fx_source", "fx_rate")} == \
        {"spend_usd_cents": None, "fx_source": None, "fx_rate": None}
    assert len(db.ad_spend) == 5
    assert ledger.upsert_ad_spend("meta_ads", None, []) == 0 and len(db.calls) == len(posts)


def test_the_same_campaign_and_day_twice_is_refused_before_any_request(db):
    with pytest.raises(ValueError):
        ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 502), bf.spend("2026-11-01", 510)])
    assert db.calls == []


def test_a_re_pulled_day_replaces_its_row_and_clears_a_stale_conversion(db):
    run_id = ledger.claim_run("meta_sync", "run-1", "schedule", "meta_ads")
    ledger.upsert_ad_spend("meta_ads", run_id, [bf.spend("2026-11-01", 502, impressions=100),
                                                bf.spend("2026-08-03", 1000, currency="EUR", campaign="c3")])
    db.add_fx_rate("EUR", "2026-08-01", "1.0850000000")
    assert ledger.fill_fx() == 1
    eur = db.spend_rows()[("c3", "2026-08-03")]
    assert (eur["spend_usd_cents"], eur["fx_source"], eur["fx_rate"]) == (1085, "ecb", Decimal("1.085"))
    first_pull = db.spend_rows()[(bf.TOODLE_CAMPAIGN, "2026-11-01")]["pulled_at"]
    db.clock = lambda: datetime.now(timezone.utc) + timedelta(hours=6)
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 510, impressions=130),
                                              bf.spend("2026-08-03", 1200, currency="EUR", campaign="c3")])
    usd = db.spend_rows()[(bf.TOODLE_CAMPAIGN, "2026-11-01")]
    assert (usd["spend_minor"], usd["spend_usd_cents"], usd["impressions"], usd["job_run_id"]) == (510, 510, 130, None)
    assert usd["pulled_at"] >= first_pull
    eur = db.spend_rows()[("c3", "2026-08-03")]
    assert (eur["spend_usd_cents"], eur["fx_source"], eur["fx_rate"]) == (None, None, None)   # stale USD cleared
    assert _day("2026-08-03")["spend"]["unconverted_rows"] == 1
    assert ledger.fill_fx() == 1 and db.spend_rows()[("c3", "2026-08-03")]["spend_usd_cents"] == 1302
    assert len(db.ad_spend) == 2


def test_the_fake_upsert_follows_postgrest_and_the_tables_checks(db):
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 502)])
    row = {**bf.spend("2026-11-01", 510).as_json(), "source_id": "meta_ads", "job_run_id": None,
           "pulled_at": "2026-11-02T11:30:00Z"}
    merge = "resolution=merge-duplicates,return=minimal"
    attempts = [({}, merge, [row], "23505"),                                    # no on_conflict: the primary key
                ({"on_conflict": "source_id,campaign_id,day"}, "return=minimal", [row], "23505"),
                ({"on_conflict": "source_id,campaign_id,day"}, merge, [row, row], "21000"),
                ({"on_conflict": "campaign_id"}, merge, [row], "42P10"),
                ({"on_conflict": "source_id,campaign_id,day"}, merge,
                 [{**row, "spend_usd_cents": 999}], "23514"),                    # identity must equal spend
                ({"on_conflict": "source_id,campaign_id,day"}, merge,
                 [{**row, "day": "2026-11-02"}, {**row, "day": "2026-11-03", "spend_minor": -1}], "23514"),
                ({"on_conflict": "source_id,campaign_id,day"}, merge,
                 [{**row, "job_run_id": "0b7e3c2a-1111-4222-8333-944455566677"}], "23503"),
                ({"on_conflict": "source_id,campaign_id,day"}, merge, [{**row, "clicks": 1}], "PGRST204")]
    for params, prefer, body, code in attempts:
        with pytest.raises(BoardDBError) as e:
            ledger._call("POST", "ad_spend_daily", params=params, json=body, prefer=prefer)
        assert _code(e.value) == code, (params, prefer, str(e.value))
    assert list(db.spend_rows()) == [(bf.TOODLE_CAMPAIGN, "2026-11-01")]          # one statement: nothing half-written
    assert db.spend_rows()[(bf.TOODLE_CAMPAIGN, "2026-11-01")]["spend_minor"] == 502
    ledger._call("POST", "ad_spend_daily", params={"on_conflict": "source_id,campaign_id,day"}, json=[row],
                 prefer="resolution=ignore-duplicates,return=minimal")
    assert db.spend_rows()[(bf.TOODLE_CAMPAIGN, "2026-11-01")]["spend_minor"] == 502


def test_the_funnel_label_of_every_stored_row_follows_the_campaign_list(db):
    a, b, c = "120000000000000001", "120000000000000002", "120000000000000003"
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-08-03", 100, campaign=a, funnel=None),
                                              bf.spend("2026-11-01", 200, campaign=a, funnel=None),
                                              bf.spend("2026-08-03", 300, campaign=b),           # labelled toodle
                                              bf.spend("2026-08-03", 400, campaign=c, funnel=None)])
    ledger.upsert_ad_spend("manual", None, [bf.spend("2026-08-03", 500, campaign=b)])          # another source
    ledger.label_spend_funnel("meta_ads", "toodle", {a, f" {c} "})

    def funnels(source="meta_ads"):
        return {(cid, d): r["funnel"] for (cid, d), r in db.spend_rows(source).items()}
    assert funnels() == {(a, "2026-08-03"): "toodle", (a, "2026-11-01"): "toodle", (b, "2026-08-03"): None,
                         (c, "2026-08-03"): "toodle"}
    assert funnels("manual") == {(b, "2026-08-03"): "toodle"}                                   # left alone
    assert {r["spend_minor"] for r in db.spend_rows().values()} == {100, 200, 300, 400}        # a label only
    ledger.label_spend_funnel("meta_ads", "toodle", [])
    assert set(funnels().values()) == {None}                                                   # no list, no Toodle
    sent = len(db.calls)
    for bad in ({"12x"}, {""}, {120000000000000001}, {"1" * 65}):
        with pytest.raises(ValueError):
            ledger.label_spend_funnel("meta_ads", "toodle", bad)
    with pytest.raises(ValueError):
        ledger.label_spend_funnel("meta_ads", " ", {a})
    assert len(db.calls) == sent                                                               # refused before a call


def test_last_ok_detail_reads_the_run_that_finished_last(db):
    assert ledger.last_ok_detail("kit_sync") is None
    finished = {}
    for n, (status, at) in enumerate((("ok", "2026-11-02T08:00:00Z"), ("ok", "2026-11-02T10:00:00Z"),
                                      ("failed", "2026-11-02T11:00:00Z"), ("ok", "2026-11-02T09:00:00Z"))):
        run_id = ledger.claim_run("kit_sync", f"run-{n}", "schedule", "kit")
        ledger.finish_run(run_id, status, detail={"n": n})
        db.job_runs[run_id]["finished_at"] = ledger.parse_ts(at)
        finished[n] = run_id
    ledger.claim_run("kit_sync", "run-running", "schedule", "kit")                             # still running
    assert ledger.last_ok_detail("kit_sync") == {"n": 1}            # not the later failed one, not the last claimed
    assert ledger.last_ok_detail("meta_sync") is None
    (call,) = [c for c in db.calls if c.method == "GET" and c.url.path == "/rest/v1/job_runs"][-1:]
    assert dict(call.url.params) == {"select": "detail", "job": "eq.meta_sync", "status": "eq.ok",
                                     "order": "finished_at.desc.nullslast", "limit": "1"}


# ─── FX ─────────────────────────────────────────────────────────────────────

def test_fill_fx_uses_the_rate_on_or_before_the_day_at_most_six_days_back(db):
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-08-03", 1000, currency="EUR", campaign="c3"),
                                              bf.spend("2026-08-05", 1000, currency="JPY", campaign="c6"),
                                              bf.spend("2026-08-04", 1, currency="GBP", campaign="c5")])
    db.add_fx_rate("EUR", "2026-07-27", "1.2")                                   # 7 days back: too old
    db.add_fx_rate("EUR", "2026-08-04", "1.3")                                   # after the day: not used
    assert ledger.fill_fx() == 0
    db.add_fx_rate("EUR", "2026-07-28", "1.0850000000")                         # 6 days back: used
    db.add_fx_rate("JPY", "2026-08-05", "0.0067")
    db.add_fx_rate("GBP", "2026-08-04", "1.5")
    assert ledger.fill_fx() == 3
    got = {cid: r["spend_usd_cents"] for (cid, _), r in db.spend_rows().items()}
    assert got == {"c3": 1085, "c6": 670, "c5": 2}                               # JPY has no cents; 1.5 rounds up
    assert ledger.fill_fx() == 0


def test_fill_fx_converts_ledger_rows_but_never_stripes(db):
    sale = lambda ext: ledger.LedgerRow(external_id=ext, kind="sale", amount_minor=200, currency="GBP",
                                        occurred_at=datetime(2026, 11, 1, 17, tzinfo=timezone.utc))
    ledger.ingest_ledger("manual", None, [sale("man_gbp")])
    ledger.ingest_ledger("stripe", None, [sale("txn_gbp")])
    db.add_fx_rate("GBP", "2026-10-30", "1.30")                                  # Sunday uses Friday's rate
    assert ledger.fill_fx() == 1
    assert db.rows("manual")["man_gbp"]["amount_usd_cents"] == 260
    assert db.rows("stripe")["txn_gbp"]["amount_usd_cents"] is None
    db.fail["rpc/board_fill_fx"] = 500
    with pytest.raises(BoardDBError):
        ledger.fill_fx()


def test_fill_fx_refuses_an_answer_that_is_not_a_count(db, monkeypatch):
    monkeypatch.setattr(ledger, "rpc", lambda name, params: None)
    with pytest.raises(BoardDBError):
        ledger.fill_fx()


# ─── sources ────────────────────────────────────────────────────────────────

def test_update_source_writes_only_the_account_facts(db):
    ledger.update_source("meta_ads", day_tz="America/Los_Angeles", currency=" eur ", account_ref=" act_123 ")
    (patch,) = [c for c in db.calls if c.method == "PATCH"]
    assert patch.url.params["id"] == "eq.meta_ads" and patch.headers["prefer"] == "return=minimal"
    assert json.loads(patch.content) == {"day_tz": "America/Los_Angeles", "currency": "EUR", "account_ref": "act_123"}
    row = ledger.source_row("meta_ads")
    assert (row["day_tz"], row["currency"], row["account_ref"]) == ("America/Los_Angeles", "EUR", "act_123")
    ledger.update_source("meta_ads", currency=None)
    assert ledger.source_row("meta_ads")["currency"] is None
    calls = len(db.calls)
    with pytest.raises(TypeError):
        ledger.update_source("meta_ads", enabled=False)
    with pytest.raises(TypeError):
        ledger.update_source("meta_ads", synced_through="2026-11-02T00:00:00Z", day_tz="UTC")
    for bad in ("America/New York", "../etc/passwd", "", 5):
        with pytest.raises(ValueError):
            ledger.update_source("meta_ads", day_tz=bad)
    with pytest.raises(ValueError):
        ledger.update_source("meta_ads", currency="euro")
    ledger.update_source("meta_ads")                                             # nothing to write: no call
    assert len(db.calls) == calls


def test_a_zone_the_database_does_not_know_is_refused_there(db):
    with pytest.raises(BoardDBError) as e:
        ledger.update_source("meta_ads", day_tz="Mars/Olympus")
    assert _code(e.value) == "22023"
    assert db.sources["meta_ads"]["day_tz"] == "America/New_York"


def test_a_meta_day_is_final_only_past_midnight_in_the_ad_accounts_zone(db):
    ledger.update_source("meta_ads", day_tz="America/Los_Angeles")
    for sid in ("kit", "meta_ads"):
        db.set_source(sid, measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")   # 01:00 EST, 22:00 PST
    states = {s["id"]: (s["state"], s["day_tz"]) for s in _day("2026-11-01")["sources"]}
    assert states["kit"] == ("final", "America/New_York")
    assert states["meta_ads"] == ("partial", "America/Los_Angeles")


# ─── amounts ────────────────────────────────────────────────────────────────

def test_decimal_amounts_become_exact_minor_units():
    cases = [("25.10", "USD", 2510), ("1234", "JPY", 1234), ("1.234", "KWD", 1234), ("0.0001", "CLF", 1),
             (" 12.30 ", "usd", 1230), ("-5.00", "USD", -500), (".5", "USD", 50), ("5.", "USD", 500),
             ("0", "EUR", 0), (Decimal("25.10"), "USD", 2510), (25, "USD", 2500), ("100.50", "JPY", None)]
    for amount, currency, minor in cases:
        if minor is None:
            with pytest.raises(ValueError):
                ledger.to_minor_units(amount, currency)
        else:
            assert ledger.to_minor_units(amount, currency) == minor, (amount, currency)
    for amount in ("12.345", "1e2", "NaN", "Infinity", "1,234.56", "", "12 34", "١٢", Decimal("NaN"),
                   Decimal("1e40"), "1" * 19):
        with pytest.raises(ValueError):
            ledger.to_minor_units(amount, "USD")
    for amount in (12.5, True, None, [1]):
        with pytest.raises(TypeError):
            ledger.to_minor_units(amount, "USD")
    with pytest.raises(ValueError):
        ledger.to_minor_units("1", "US")
    assert ledger.currency_exponent("jpy") == 0 and ledger.currency_exponent("GBP") == 2


def test_the_exponent_table_is_the_sqls():
    groups = re.findall(r"when p_currency in \(([^)]*)\) then (\d)", _sql_function("board_currency_exponent"))
    sql = {code.strip(" '\n"): int(exponent) for codes, exponent in groups for code in codes.split(",")}
    assert sql == ledger._EXPONENTS == bf._EXPONENT
    assert re.search(r"else 2\b", _sql_function("board_currency_exponent"))
