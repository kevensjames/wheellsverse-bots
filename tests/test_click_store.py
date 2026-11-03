"""Step 2e: the click store. /go/{partner} writes one row of public.clicks per
stored click (no visitor address anywhere; best effort, after the redirect;
at most 30 a minute per client address, counted in memory), and hands the
click id to a Stripe Payment Link as client_reference_id. core.click_tracker's
old functions (record_click, get_stats, _load_clicks, tracking_url) keep their
signatures and shapes, now backed by the table; the conversion log is gone,
and nothing reads the old JSON files.

No network: the board's database is tests/board_fakes.py's FakeBoardDB;
Telegram and Impact are stubbed."""
import inspect
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import core.click_tracker as ct
from core.board import ledger, money
from core.board.ledger import LedgerRow
from tests import board_fakes as bf

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)        # 10:00 on Mon 2 Nov in New York
KEY = {"X-API-Key": bf.API_KEY}
VISITOR = "203.0.113.7"
OTHER = "198.51.100.9"
LINK = "https://buy.stripe.com/test_8wM5kq?prefilled_email=a%40b.example&client_reference_id=old#pay"


class Recorder:
    def __init__(self, result=None):
        self.calls, self.result = [], result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class Clock:
    """A monotonic clock the limiter and the warnings read; tests move it."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def db(monkeypatch):
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    monkeypatch.setattr(ct, "_clock", lambda: NOW)
    return db


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """Fresh limits, a still clock, and the Telegram click note recorded, never sent."""
    clock = Clock()
    monkeypatch.setattr(ct, "_monotonic", clock)
    ct.reset_limits()
    note = Recorder(True)
    monkeypatch.setattr("core.telegram.notify_click", note)
    yield {"clock": clock, "note": note}
    ct.reset_limits()


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.delenv("AFFILIATE_INSIDER_URL", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    return bf.client(monkeypatch)


def go(client, key, query="", ip=VISITOR, referer="https://Blog.Example.com/post/best-apps?ref=x#top"):
    headers = {"CF-Connecting-IP": ip}
    if referer is not None:
        headers["Referer"] = referer
    return client.get(f"/go/{key}{query}", headers=headers, follow_redirects=False)


def stored(db) -> list[dict]:
    return sorted(db.clicks.values(), key=lambda c: (c["clicked_at"], c["id"]))


def sent(db) -> str:
    """Everything the board sent to the database: paths, queries and bodies."""
    return "\n".join(f"{c.url} {(c.content or b'').decode('utf-8', 'replace')}" for c in db.calls)


# ─── the route ──────────────────────────────────────────────────────────────

def test_a_click_redirects_and_stores_one_row_with_no_address(client, db, quiet, caplog):
    caplog.set_level(logging.DEBUG)
    r = go(client, "coinbase", "?utm_source=meta&utm_campaign=Fall%20Sale&utm_medium=&gclid=abc")
    assert r.status_code == 302
    assert r.headers["location"] == ct._stan("coinbase")
    assert r.headers["cache-control"] == "no-store"
    (row,) = stored(db)
    assert (row["partner"], row["referrer_host"], row["destination"]) == ("coinbase", "blog.example.com",
                                                                         ct._stan("coinbase"))
    assert row["utm"] == {"utm_source": "meta", "utm_campaign": "Fall Sale"}     # empty tags left out
    assert row["clicked_at"] == NOW and row["local_day"] == date(2026, 11, 2) and row["import_key"] is None
    assert "ip" not in row and VISITOR not in json.dumps(row, default=str)
    (insert,) = [c for c in db.calls if c.method == "POST"]
    assert set(json.loads(insert.content)) == {"id", "partner", "clicked_at", "referrer_host", "destination", "utm"}
    assert insert.headers["prefer"] == "return=minimal"
    assert VISITOR not in sent(db)                                              # in no request to the database
    assert all(VISITOR not in rec.getMessage() for rec in caplog.records)       # in no log record
    import core.api as api
    assert any(e["message"] == "Affiliate click: coinbase" for e in api._log_buffer)
    assert all(VISITOR not in str(e) for e in api._log_buffer)
    assert len(quiet["note"].calls) == 1 and quiet["note"].calls[0][1] == {"partner": "coinbase"}   # no count


def test_the_key_is_stored_lower_cased(client, db):
    r = go(client, "CoinBase")
    assert r.status_code == 302 and r.headers["location"] == ct._stan("coinbase")
    assert [c["partner"] for c in stored(db)] == ["coinbase"]


@pytest.mark.parametrize("key", ["a" * 65, "a%20b", "a.b", "a%2Fb", "%C3%BCber", "a+b", "a%00b", "%E2%80%AE"])
def test_a_key_that_is_not_a_key_answers_404_and_stores_nothing(client, db, key):
    r = go(client, key)
    assert r.status_code == 404
    assert "location" not in r.headers and db.clicks == {} and db.calls == []
    assert key not in r.text and "a" * 65 not in r.text                          # the key is not echoed


def test_a_64_character_key_is_a_key(client, db):
    assert go(client, "a" * 64).status_code == 302 and len(db.clicks) == 1


@pytest.mark.parametrize("down", ["connection", "relation missing", "timeout"])
def test_the_database_down_never_blocks_the_redirect(client, db, caplog, down, monkeypatch):
    if down == "connection":
        db.down = True
    elif down == "relation missing":
        db.fail["clicks"] = 404                              # migration 0002 not applied
    else:
        def hang(*a, **k):
            raise ledger.BoardDBError("clicks: ReadTimeout")
        monkeypatch.setattr(ledger, "insert_click", hang)
    caplog.set_level(logging.WARNING, logger="click_tracker")
    for _ in range(3):
        r = go(client, "webull")
        assert r.status_code == 302 and r.headers["location"] == ct._stan("webull")
    assert db.clicks == {}
    warnings = [rec.getMessage() for rec in caplog.records if rec.name == "click_tracker"]
    assert len(warnings) == 1 and warnings[0].startswith("a click was not stored (")   # one a minute at most
    assert bf.SERVICE not in warnings[0] and "x@example.com" not in warnings[0]        # no key, no row


def test_31_clicks_a_minute_from_one_client_store_30_and_still_redirect(client, db, quiet, monkeypatch):
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", LINK)
    answers = [go(client, "insider") for _ in range(31)]
    assert all(r.status_code == 302 for r in answers)
    assert len(db.clicks) == 30
    ids = {parse_qs(urlsplit(r.headers["location"]).query).get("client_reference_id", [""])[0] for r in answers}
    assert ids == {c["id"] for c in db.clicks.values()} | {"old"}       # the 31st: the link as it is, not stored
    assert answers[-1].headers["location"] == LINK
    assert go(client, "insider", ip=OTHER).status_code == 302 and len(db.clicks) == 31   # another client still counts
    quiet["clock"].now += 61                                             # a minute later the first client counts again
    assert go(client, "insider").status_code == 302 and len(db.clicks) == 32


def test_everyone_together_is_capped(client, db, monkeypatch, quiet):
    monkeypatch.setattr(ct, "EVERYONE_PER_MINUTE", 5)
    for n in range(7):
        assert go(client, "uber", ip=f"192.0.2.{n}").status_code == 302
    assert len(db.clicks) == 5
    quiet["clock"].now += 60
    assert go(client, "uber", ip="192.0.2.99").status_code == 302 and len(db.clicks) == 6


def test_a_payment_link_carries_the_stored_click_id(client, db, monkeypatch):
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", LINK)
    r = go(client, "insider", "?utm_source=newsletter")
    assert r.status_code == 302 and r.headers["cache-control"] == "no-store"
    (row,) = stored(db)
    location = urlsplit(r.headers["location"])
    assert (location.scheme, location.netloc, location.path, location.fragment) == (
        "https", "buy.stripe.com", "/test_8wM5kq", "pay")
    assert parse_qs(location.query) == {"prefilled_email": ["a@b.example"], "client_reference_id": [row["id"]]}
    assert row["destination"] == LINK                                   # stored without a click id
    assert row["utm"] == {"utm_source": "newsletter"}


@pytest.mark.parametrize("url", [
    "http://buy.stripe.com/x", "https://buy.stripe.com.evil.example/x", "https://evilbuy.stripe.com/x",
    "https://stripe.com/x", "https://buy.stripe.co/x", "https://buy-stripe.com/x", "https://buy.stripe.com./x",
    "ftp://buy.stripe.com/x", "https://[::1/x"])
def test_a_look_alike_host_or_plain_http_never_gets_a_click_id(url, monkeypatch, client, db):
    assert ct.with_click_id(url, "c0ffee00-0000-4000-8000-000000000000") == url
    if "[" not in url:
        monkeypatch.setenv("AFFILIATE_INSIDER_URL", url)
        r = go(client, "insider")
        assert r.status_code == 302 and "client_reference_id" not in r.headers["location"]


def test_the_payment_link_host_is_read_in_any_case():
    out = ct.with_click_id("https://BUY.Stripe.com/x?a=1", "c0ffee00-0000-4000-8000-000000000000")
    assert out == "https://BUY.Stripe.com/x?a=1&client_reference_id=c0ffee00-0000-4000-8000-000000000000"


def test_head_is_not_routed_so_link_checkers_store_nothing(client, db):
    assert client.head("/go/coinbase", follow_redirects=False).status_code == 405 and db.clicks == {}


def test_api_clicks_needs_the_api_key_and_reads_the_table(client, db):
    go(client, "coinbase")
    go(client, "Webull", ip=OTHER, referer=None)
    assert client.get("/api/clicks").status_code == 401
    r = client.get("/api/clicks", headers=KEY)
    assert r.status_code == 200
    body = r.json()
    assert (body["total_clicks"], body["by_partner"]) == (2, {"coinbase": 1, "webull": 1})
    assert [c["partner"] for c in body["recent"]] == ["webull", "coinbase"] or \
           [c["partner"] for c in body["recent"]] == ["coinbase", "webull"]   # same instant: id order
    assert all(set(c) == {"partner", "ts", "referrer", "dest", "id", "utm"} for c in body["recent"])
    assert VISITOR not in r.text and OTHER not in r.text
    assert body["connected"] is True and body["note"] == ""
    import core.api as api
    assert not inspect.iscoroutinefunction(api.get_click_stats)       # its database reads run in the threadpool


# ─── one click, unit by unit ────────────────────────────────────────────────

@pytest.mark.parametrize("referrer, host", [
    ("https://Blog.Example.com:8443/post?q=1#frag", "blog.example.com"),
    ("http://203.0.113.50/page", "203.0.113.50"),             # the referring site's address, not the visitor's
    ("", None), ("   ", None), ("not a url", None), ("http://exa mple.com/", None),
    ("https://xn--bcher-kva.example/", "xn--bcher-kva.example"), ("https://bücher.example/", None),
    ("https://" + "a" * 256 + ".example/", None), (None, None), ("https://[::1/x", None)])
def test_only_the_referring_host_is_kept(referrer, host):
    assert ct.referrer_host(referrer) == host


def test_the_visitors_utm_tags_are_kept_first_value_trimmed_and_short():
    from starlette.datastructures import QueryParams
    q = QueryParams("utm_source=Meta&utm_source=second&utm_medium=%20cpc%20&utm_term=a%00b%01c"
                    f"&utm_content={'x' * 150}&utm_campaign=%09&ref=nope")
    assert ct.utm_tags(q) == {"utm_source": "Meta", "utm_medium": "cpc", "utm_term": "abc",
                              "utm_content": "x" * 100}
    assert ct.utm_tags({"utm_source": ["a", "b"]}) == {"utm_source": "a"}
    assert ct.utm_tags("?utm_source=x&utm_source=y") == {"utm_source": "x"}
    assert ct.utm_tags(None) == {} and ct.utm_tags([("utm_term", "t")]) == {"utm_term": "t"}


def test_a_click_row_is_exactly_the_tables_columns(db):
    click = ct.new_click("Insider", referrer="https://x.example/a?b=c", query={"utm_source": "ig"})
    assert set(click.row()) == {"id", "partner", "clicked_at", "referrer_host", "destination", "utm"}
    assert click.row()["clicked_at"] == NOW.isoformat() and click.partner == "insider"
    assert ct.new_click("bad key") is None and ct.new_click("") is None and ct.new_click(None) is None


def test_a_key_without_a_destination_is_no_key(monkeypatch, db):
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", "   ")
    assert ct.new_click("insider") is None and ct.record_click("insider") is None


def test_a_destination_the_table_cannot_hold_is_never_stored_and_gets_no_click_id(monkeypatch, db, caplog):
    long_link = "https://buy.stripe.com/x?" + "a=1&" * 600
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", long_link)
    click = ct.new_click("insider")
    assert click.url == long_link and len(long_link) > 2048
    assert ct.save_click(click) is False and db.calls == [] and db.clicks == {}


def test_insert_click_sends_only_the_live_columns(db):
    row = {**ct.new_click("webull").row(), "ip": VISITOR, "local_day": "2026-11-02", "import_key": "x"}
    ledger.insert_click(row)
    (call,) = db.calls
    assert set(json.loads(call.content)) == set(ledger.LIVE_CLICK_COLUMNS) and VISITOR not in sent(db)


def test_a_live_click_insert_waits_only_the_short_click_timeout(db):
    """A hung database holds each background save for CLICK_TIMEOUT, never
    the 20 s of an ordinary board call."""
    assert ct.save_click(ct.new_click("webull"))
    (call,) = db.calls
    assert call.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), ledger.CLICK_TIMEOUT)
    assert ledger.CLICK_TIMEOUT <= 5


def test_record_click_keeps_its_signature_and_ignores_the_ip(db, quiet):
    assert list(inspect.signature(ct.record_click).parameters) == ["partner", "referrer", "ip"]
    assert ct.record_click("Webull", referrer="https://x.example/a", ip=OTHER) == ct._stan("webull")
    (row,) = stored(db)
    assert row["partner"] == "webull" and row["referrer_host"] == "x.example"
    assert OTHER not in sent(db) and ct.record_click("no such key!") is None
    assert len(db.clicks) == 1


def test_record_click_returns_the_payment_link_with_its_click_id_only_when_stored(db, monkeypatch):
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", LINK)
    url = ct.record_click("insider")
    (row,) = stored(db)
    assert parse_qs(urlsplit(url).query)["client_reference_id"] == [row["id"]]
    db.down = True
    assert ct.record_click("insider") == LINK


def test_tracking_url_and_the_affiliate_map_are_unchanged(monkeypatch):
    monkeypatch.setenv("CTA_URL", "https://app.example.com/path/x")
    assert ct.tracking_url("webull") == "https://app.example.com/go/webull"
    assert list(inspect.signature(ct.tracking_url).parameters) == ["partner", "base_url"]
    assert set(ct._affiliate_urls()) == {"insider"}


# ─── the old readers, from the table ────────────────────────────────────────

def _clicks(db, *specs):
    """Store clicks through the board's write path: (key, minutes after NOW, utm_source or None)."""
    out = []
    for key, minutes, source in specs:
        click = ct.new_click(key, referrer="https://ref.example/x", query={"utm_source": source} if source else None)
        click = ct.Click(**{**click.__dict__, "clicked_at": NOW + timedelta(minutes=minutes)})
        assert ct.save_click(click)
        out.append(click)
    return out


def test_load_clicks_and_get_stats_keep_the_old_shapes(db, monkeypatch):
    monkeypatch.setenv("AFFILIATE_INSIDER_URL", LINK)
    clicks = _clicks(db, ("coinbase", 1, None), ("insider", 2, "meta"), ("coinbase", 3, None), ("webull", 4, None))
    loaded = ct._load_clicks()
    assert [c["partner"] for c in loaded] == ["coinbase", "insider", "coinbase", "webull"]      # the oldest first
    assert loaded[1] == {"partner": "insider", "ts": "2026-11-02T15:02:00.000000Z", "referrer": "ref.example",
                         "dest": LINK, "id": clicks[1].id, "utm": {"utm_source": "meta"}}
    assert all(isinstance(c["referrer"], str) for c in loaded)
    # a sale through the insider click, as the Stripe sync writes it
    ledger.ingest_ledger("stripe", None, [LedgerRow(
        external_id="txn_click", kind="sale", amount_minor=2999, currency="USD",
        occurred_at=NOW + timedelta(minutes=30), amount_usd_cents=2999, fx_source="stripe", fee_usd_cents=117,
        channel="meta", attribution="click_id", click_id=clicks[1].id, order_ref="ch_click")])
    stats = ct.get_stats()
    assert stats["total_clicks"] == 4 and stats["by_partner"] == {"coinbase": 2, "insider": 1, "webull": 1}
    assert [c["partner"] for c in stats["recent"]] == ["webull", "coinbase", "insider", "coinbase"]  # newest first
    assert all("ip" not in c for c in stats["recent"])
    assert (stats["total_conversions"], stats["conversions_by_partner"]) == (1, {"insider": 1})
    assert stats["revenue_by_partner_usd"] == {"insider": 29.99} and stats["total_revenue_usd"] == 29.99
    assert (stats["connected"], stats["note"]) == (True, "")
    assert set(stats) == {"total_clicks", "by_partner", "recent", "total_conversions", "conversions_by_partner",
                          "revenue_by_partner_usd", "total_revenue_usd", "connected", "note"}


def test_a_tracked_link_sale_without_us_dollars_makes_its_revenue_null(db):
    click = ct.new_click("coinbase", query={"utm_source": "meta"})
    assert ct.save_click(click)
    at = NOW + timedelta(minutes=5)
    ledger.ingest_ledger("stripe", None, [
        LedgerRow(external_id="txn_usd", kind="sale", amount_minor=1000, currency="USD", occurred_at=at,
                  amount_usd_cents=1000, fx_source="stripe", channel="meta", attribution="click_id",
                  click_id=click.id),
        LedgerRow(external_id="txn_eur", kind="sale", amount_minor=1000, currency="EUR", occurred_at=at,
                  channel="meta", attribution="click_id", click_id=click.id)])       # no USD amount yet
    stats = ct.get_stats()
    assert stats["conversions_by_partner"] == {"coinbase": 2} and stats["total_conversions"] == 2
    assert stats["revenue_by_partner_usd"] == {"coinbase": None}       # never the smaller $10.00
    assert stats["total_revenue_usd"] is None


def test_a_clicks_table_past_the_read_cap_still_counts_and_stays_connected(db, monkeypatch):
    """More clicks than one whole read takes is not 'the database is down':
    the total is the database's exact count, and only the clicks by key are
    left out, with a note that says why."""
    for _ in range(6):
        assert ct.save_click(ct.new_click("coinbase"))
    monkeypatch.setattr(ledger, "READ_ALL_MOST", 5)                    # stands in for 200,000
    stats = ct.get_stats()
    assert stats["total_clicks"] == 6 and stats["connected"] is True
    assert stats["by_partner"] == {} and len(stats["recent"]) == 6
    assert stats["note"] == "Clicks by key are left out: more than 5 clicks to read."
    assert stats["total_conversions"] == 0                             # the sales are still read
    with pytest.raises(ledger.TooManyRows):                            # the database answered: not 'down'
        ledger.read_clicks("partner")
    db.down = True
    assert ct.get_stats()["connected"] is False                        # a database that is down still says so


def test_a_sale_whose_click_id_names_no_click_is_no_conversion(db):
    ledger.ingest_ledger("stripe", None, [LedgerRow(
        external_id="txn_x", kind="sale", amount_minor=500, currency="USD", occurred_at=NOW,
        amount_usd_cents=500, fx_source="stripe", channel="meta", attribution="click_id",
        click_id="7b0c3c1e-5a52-4d62-9e7c-2a2b8f1c9d00")])
    assert db.rows()["txn_x"]["click_id"] is None and db.rows()["txn_x"]["attribution"] == "none"
    stats = ct.get_stats()
    assert (stats["total_conversions"], stats["total_revenue_usd"], stats["total_clicks"]) == (0, 0.0, 0)


def test_every_click_is_read_past_the_apis_row_cap(db):
    for n in range(1205):                                        # straight into the table: fast
        cid = f"00000000-0000-4000-8000-{n:012d}"
        at = NOW - timedelta(seconds=n)
        db.clicks[cid] = {"id": cid, "partner": "coinbase" if n % 2 else "webull", "clicked_at": at,
                          "local_day": at.astimezone(bf.NY).date(), "referrer_host": None,
                          "destination": ct._stan("x"), "utm": {}, "import_key": None,
                          "created_at": at, "updated_at": at}
    for cap, pages in ((1000, 3), (300, 6)):                     # Supabase's cap, and a server set lower
        db.max_rows = cap
        db.calls.clear()
        loaded = ct._load_clicks()
        assert len(loaded) == 1205 and len({c["id"] for c in loaded}) == 1205
        assert len(db.calls) == pages                            # it stops only at an empty page
        stats = ct.get_stats()
        assert stats["total_clicks"] == 1205 and stats["by_partner"] == {"webull": 603, "coinbase": 602}
        assert len(stats["recent"]) == 20
    db.max_rows = 7                                              # fewer than the 20 newest in one read
    newest = ct.get_stats()["recent"]
    assert len(newest) == 20 and newest[0]["id"] == "00000000-0000-4000-8000-000000000000"
    assert ct.clicks_on(date(2026, 11, 2)) == 1205 and ct.total_clicks() == 1205    # counted, never len()
    with pytest.raises(ledger.BoardDBError):
        ledger.read_all("clicks", "id", order="clicked_at.asc,id.asc", most=1000)


def test_a_store_that_cannot_be_read_gives_nulls_never_zero(db):
    db.down = True
    stats = ct.get_stats()
    assert stats == {"total_clicks": None, "by_partner": {}, "recent": [], "total_conversions": None,
                     "conversions_by_partner": {}, "revenue_by_partner_usd": {}, "total_revenue_usd": None,
                     "connected": False, "note": stats["note"]}
    assert stats["note"].startswith("Not connected: the clicks and the sales through tracked links cannot be read.")
    assert ct._load_clicks() == []
    assert ct.clicks_on(date(2026, 11, 1)) is None and ct.total_clicks() is None and ct.clicks_today() is None
    assert ct.clicks_between(date(2026, 10, 1), date(2026, 11, 1)) is None


def test_clicks_count_by_new_york_day(db):
    for at in ("2026-11-02T04:30:00Z", "2026-11-02T04:59:59Z", "2026-11-02T05:00:00Z", "2026-11-03T03:00:00Z"):
        click = ct.new_click("coinbase")
        assert ct.save_click(ct.Click(**{**click.__dict__, "clicked_at": bf._ts(at)}))
    assert ct.clicks_on(date(2026, 11, 1)) == 2                   # 23:30 and 23:59 in New York
    assert ct.clicks_on(date(2026, 11, 2)) == 2 and ct.clicks_today() == 2
    assert ct.clicks_between(date(2026, 11, 1), date(2026, 11, 2)) == 4 and ct.total_clicks() == 4


def test_todays_clicks_are_new_yorks_today_late_in_the_evening_too(db, monkeypatch):
    late = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)          # 22:00 on Mon 2 Nov in New York
    monkeypatch.setattr(ct, "_clock", lambda: late)
    assert ct.save_click(ct.new_click("coinbase"))
    assert ct.clicks_today() == 1                                    # not 0: 3 Nov in UTC has no clicks


def test_the_money_summary_counts_seven_new_york_days_of_clicks(db, monkeypatch):
    monkeypatch.setattr(money, "_clock", lambda: NOW)
    for at in ("2026-10-27T15:00:00Z", "2026-10-27T03:00:00Z", "2026-11-02T14:00:00Z"):  # 27 Oct, 26 Oct, 2 Nov
        click = ct.new_click("webull")
        ct.save_click(ct.Click(**{**click.__dict__, "clicked_at": bf._ts(at)}))
    assert money.clicks_7d() == 2                                  # 27 Oct to 2 Nov
    db.down = True
    assert money.clicks_7d() is None


# ─── the limiter keeps no address ───────────────────────────────────────────

def test_the_limiter_forgets_idle_clients_and_never_holds_an_address(monkeypatch, quiet):
    monkeypatch.setattr(ct, "_MAX_CLIENTS", 3)
    for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        assert ct.allow_click(ip)
    assert all(isinstance(k, bytes) and len(k) == 16 for k in ct._by_client)
    assert not any(b"192.0.2" in k for k in ct._by_client)
    quiet["clock"].now += 61
    assert ct.allow_click("192.0.2.4") and len(ct._by_client) == 1     # the idle three went first
    for _ in range(29):
        assert ct.allow_click("192.0.2.4")
    assert not ct.allow_click("192.0.2.4")                              # 30 a minute
    quiet["clock"].now += 30
    assert not ct.allow_click("192.0.2.4")                              # still within the minute
    quiet["clock"].now += 31
    assert ct.allow_click("192.0.2.4")


def test_the_limit_holds_under_concurrent_clicks(quiet, caplog):
    import threading
    caplog.set_level(logging.INFO, logger="click_tracker")
    results, start = [], threading.Barrier(16)

    def hammer():
        start.wait()
        for _ in range(10):
            results.append(ct.allow_click(VISITOR))

    threads = [threading.Thread(target=hammer) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 30 and len(results) == 160            # the check and the count are one step
    notes = [r.getMessage() for r in caplog.records if r.name == "click_tracker"]
    assert notes == ["click limit reached: 1 click not stored since this was last logged (the links still redirect)"]
    assert all(VISITOR not in n for n in notes)


def test_save_click_warns_at_most_once_a_minute_and_says_how_many(db, quiet, caplog):
    caplog.set_level(logging.WARNING, logger="click_tracker")
    db.down = True
    for _ in range(3):
        assert ct.save_click(ct.new_click("uber")) is False
    quiet["clock"].now += 61
    assert ct.save_click(ct.new_click("uber")) is False
    said = [r.getMessage() for r in caplog.records if r.name == "click_tracker"]
    assert said == ["a click was not stored (clicks: ConnectError); 1 not stored since the last warning",
                    "a click was not stored (clicks: ConnectError); 3 not stored since the last warning"]
    assert quiet["note"].calls == []                                     # no click note for a click not stored


# ─── the other old readers, now on the table ────────────────────────────────

def test_revenue_v2_and_the_blog_board_count_clicks_in_sql(client, db, monkeypatch):
    monkeypatch.setattr("core.impact.get_earnings", lambda days=30: {"total_earned": 0, "by_program": {},
                                                                     "by_day": {}})
    _clicks(db, ("coinbase", 1, None), ("webull", 2, None))
    old = ct.new_click("coinbase")
    ct.save_click(ct.Click(**{**old.__dict__, "clicked_at": NOW - timedelta(days=3)}))
    r = client.get("/api/revenue/v2", headers=KEY)
    assert r.status_code == 200 and (r.json()["tracker_clicks"], r.json()["tracker_today"]) == (3, 2)
    blog = client.get("/api/blog/articles", headers=KEY)
    assert blog.status_code == 200 and blog.json()["clicks_total"] == 3
    db.down = True
    r = client.get("/api/revenue/v2", headers=KEY)
    assert (r.json()["tracker_clicks"], r.json()["tracker_today"]) == (None, None)     # not 0
    assert client.get("/api/blog/articles", headers=KEY).json()["clicks_total"] is None


def test_the_blog_board_shows_no_per_article_click_count_it_cannot_measure(client, db):
    """A stored click keeps only the referring host, so a click cannot be
    tied to an article: each article's clicks is null, never 0, whether the
    database answers or not."""
    article = "https://wheellsverse-bots.pages.dev/blog/20260326-top-side-hustles-earning-2000-a-month-in-2025.html"
    for _ in range(3):
        assert go(client, "coinbase", referer=article).status_code == 302
    blog = client.get("/api/blog/articles", headers=KEY).json()
    assert blog["clicks_total"] == 3 and len(blog["articles"]) == 20
    assert {a["clicks"] for a in blog["articles"]} == {None}
    assert blog["clicks_note"] == "Clicks per article are not measured: a stored click keeps only the referring site."
    db.down = True
    blog = client.get("/api/blog/articles", headers=KEY).json()
    assert blog["clicks_total"] is None and {a["clicks"] for a in blog["articles"]} == {None}


def test_the_blog_cards_show_a_dash_for_clicks_that_are_not_measured(tmp_path):
    from tests.test_board_money import dashboard_js, run_node
    cards = [{"title": "Not <counted>", "category": "Crypto", "date": "2026-03-26", "url": "u1", "slug": "s1",
              "affiliates": [], "clicks": None},
             {"title": "Counted", "category": "Crypto", "date": "2026-03-26", "url": "u2", "slug": "s2",
              "affiliates": [], "clicks": 4}]
    out = run_node(tmp_path, (
        "const els={};const document={getElementById:id=>els[id]||(els[id]={})};"
        "let _blogSearch='',_blogFilter='All';const BLOG_CAT_COLORS={},BLOG_AFF_META={};"
        f"let _blogData={json.dumps(cards)};\n"
        + dashboard_js("function esc(s){", "function renderBlogCards(){")
        + "renderBlogCards();console.log(els['blog-grid'].innerHTML);"))
    counts = re.findall(r'<span class="blog-click-count">(.*?)</span>', out)
    bars = re.findall(r'<div class="blog-click-bar" style="width:(.*?)%"></div>', out)
    assert counts == ["—", "4"] and bars == ["0", "100"]
    assert "null" not in out and "NaN" not in out and "Not &lt;counted&gt;" in out


def test_the_daily_telegram_summary_counts_todays_clicks(client, db, monkeypatch):
    monkeypatch.setattr("core.impact.get_earnings", lambda days=1: {"total_earned": 0})
    sent_messages = Recorder(True)
    monkeypatch.setattr("core.telegram.notify", sent_messages)
    _clicks(db, ("coinbase", 1, None), ("webull", 2, None))
    assert client.post("/api/telegram/alerts/daily", headers=KEY).status_code == 200
    assert "🖱 Affiliate Clicks Today: <b>2</b>" in sent_messages.calls[-1][0][0]
    db.down = True
    assert client.post("/api/telegram/alerts/daily", headers=KEY).status_code == 200
    assert "🖱 Affiliate Clicks Today: <b>—</b>" in sent_messages.calls[-1][0][0]


def impact_actions(payouts_by_days: dict, fail_page=None):
    """core.impact._get for Actions, one action a page: the payouts of the
    window get_earnings asks for (1 or 7 days); `fail_page` answers an error."""
    def get(endpoint, params=None):
        assert endpoint == "Actions"
        if params["Page"] == fail_page:
            return {"error": "502 Server Error", "status_code": 502}
        days = (date.fromisoformat(params["EndDate"][:10]) - date.fromisoformat(params["StartDate"][:10])).days
        payouts = payouts_by_days[days]
        return {"Actions": [{"Payout": str(p), "CampaignName": "Coinbase", "EventDate": "2026-11-02T10:00:00Z",
                             "LockingStatus": "Pending"} for p in payouts[params["Page"] - 1:params["Page"]]],
                "@total": str(len(payouts))}
    return get


def test_the_daily_telegram_summary_never_prints_earnings_it_could_not_read(client, db, monkeypatch):
    """money-6 and T17: Impact's earnings read 'not connected' when Impact is
    not set up or its numbers could not be read in full, never $0.00; read in
    full, they are numbers (a real 0 too). The rest of the summary stays."""
    import core.impact as impact
    sent = Recorder(True)
    monkeypatch.setattr("core.telegram.notify", sent)
    _clicks(db, ("coinbase", 1, None))
    asked = []

    def summary(get=None) -> str:
        monkeypatch.setattr(impact, "_get", lambda endpoint, params=None: asked.append(endpoint) or get(endpoint, params))
        assert client.post("/api/telegram/alerts/daily", headers=KEY).status_code == 200
        return sent.calls[-1][0][0]

    def earnings(msg: str) -> tuple:
        return tuple(line for line in msg.split("\n") if line.startswith(("💰", "📈")))

    for name in ("IMPACT_ACCOUNT_SID", "IMPACT_API_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    msg = summary()                                                  # Impact not set up: nothing is asked
    assert earnings(msg) == ("💰 Today's Earnings: <b>not connected</b>", "📈 7-Day Total: <b>not connected</b>")
    assert "$0.00" not in msg and asked == []
    assert msg.startswith("📊 <b>WheellsVerse Daily Summary</b>\n📅 ")
    assert "\n🖱 Affiliate Clicks Today: <b>1</b>\n📝 Blog Articles Live: <b>" in msg
    assert msg.endswith("\n\n🌐 <a href='https://wheellsverse-bots.pages.dev'>View Blog</a>")
    monkeypatch.setenv("IMPACT_ACCOUNT_SID", "IRfakeAccountSid")
    monkeypatch.setenv("IMPACT_API_PASSWORD", "fake-impact-password")
    read = {1: [10, 2.5], 7: [10, 2.5, 27.5]}
    assert earnings(summary(impact_actions(read))) == (                # every page read
        "💰 Today's Earnings: <b>$12.50</b>", "📈 7-Day Total: <b>$40.00</b>")
    assert earnings(summary(impact_actions({1: [], 7: [5]}))) == (     # Impact said 0: a real 0
        "💰 Today's Earnings: <b>$0.00</b>", "📈 7-Day Total: <b>$5.00</b>")
    for failing in (impact_actions(read, fail_page=1), impact_actions(read, fail_page=2)):   # refused, or part read
        msg = summary(failing)
        assert earnings(msg) == ("💰 Today's Earnings: <b>not connected</b>", "📈 7-Day Total: <b>not connected</b>")
        assert "$" not in msg and "🖱 Affiliate Clicks Today: <b>1</b>" in msg
    monkeypatch.setattr(impact, "get_earnings", lambda days=30: 1 / 0)                       # the read raises
    assert "$" not in summary(impact_actions(read))
    assert "fake-impact-password" not in str(sent.calls) and "IRfakeAccountSid" not in str(sent.calls)


def test_impact_earnings_say_whether_every_page_was_read(monkeypatch):
    import core.impact as impact
    monkeypatch.setattr(impact, "_get", impact_actions({7: [1, 2, 3]}))
    full = impact.get_earnings(days=7)
    assert (full["total_earned"], full["action_count"], full["complete"]) == (6.0, 3, True)
    monkeypatch.setattr(impact, "_get", impact_actions({7: [1, 2, 3]}, fail_page=3))
    part = impact.get_earnings(days=7)
    assert (part["total_earned"], part["action_count"], part["complete"]) == (3.0, 2, False)
    monkeypatch.setattr(impact, "_get", impact_actions({7: list(range(1, 12))}))
    assert impact._read_pages("Actions", "Actions", {"StartDate": full["start_date"], "EndDate": full["end_date"]},
                              max_pages=10)[1] is False                          # 11 pages: more than were read
    monkeypatch.setenv("IMPACT_ACCOUNT_SID", "IRfakeAccountSid")
    monkeypatch.setenv("IMPACT_API_PASSWORD", "fake-impact-password")
    monkeypatch.setattr(impact, "get_earnings", lambda days=30: {"total_earned": 0.0, "complete": False})
    assert impact.earned_total(7) is None
    monkeypatch.setattr(impact, "get_earnings", lambda days=30: {"total_earned": float("nan"), "complete": True})
    assert impact.earned_total(7) is None
    monkeypatch.setattr(impact, "get_earnings", lambda days=30: {"total_earned": 4.25, "complete": True})
    assert impact.earned_total(7) == 4.25
    monkeypatch.delenv("IMPACT_API_PASSWORD")
    assert impact.earned_total(7) is None                                        # not set up: not asked


def test_the_analytics_bot_and_the_optimizer_read_clicks_through_the_tracker(db, monkeypatch, tmp_path):
    _clicks(db, ("coinbase", 1, None))
    (tmp_path / "clicks.json").write_text(json.dumps([{"partner": "stale", "ip": VISITOR}]), encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "analytics_bot_101", ROOT / "bots" / "agent_workforce" / "101_analytics_bot" / "bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bot = module.AnalyticsAgentBot.__new__(module.AnalyticsAgentBot)
    bot.data_dir, bot.logger = tmp_path, logging.getLogger("test.analytics_bot")
    context = bot._build_data_context()
    assert "[Click Tracking: 1 records" in context and '"partner": "coinbase"' in context
    assert "stale" not in context and VISITOR not in context            # the old file is not read
    from core.affiliate_optimizer import AffiliateOptimizer
    seen = []

    class Test:
        def record_click(self, partner):
            seen.append(partner)

    opt = AffiliateOptimizer.__new__(AffiliateOptimizer)
    opt._tests = {"general": Test()}
    monkeypatch.setattr(AffiliateOptimizer, "_save", lambda self: None, raising=False)
    opt._sync_clicks()
    assert seen == ["coinbase"]


def test_the_analytics_bot_says_no_data_when_the_clicks_cannot_be_read(db, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "analytics_bot_101_down", ROOT / "bots" / "agent_workforce" / "101_analytics_bot" / "bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bot = module.AnalyticsAgentBot.__new__(module.AnalyticsAgentBot)
    bot.data_dir, bot.logger = tmp_path, logging.getLogger("test.analytics_bot")
    db.down = True
    context = bot._build_data_context()
    assert "[Click Tracking: No data available]" in context and "[Click Tracking: 0 records" not in context


def test_the_hourly_fleet_status_reads_the_click_stats_off_the_event_loop(db, monkeypatch):
    """get_stats reads the database over blocking HTTP: the async Discord job
    runs it in a worker thread, so /go and the webhook never wait for it."""
    import asyncio
    import sys
    import types
    from narai.integrations import scheduler_promo as sp
    _clicks(db, ("coinbase", 1, None), ("webull", 2, None))
    where, posted = [], []
    real = ct.get_stats

    def watched():
        try:
            asyncio.get_running_loop()
            where.append("event loop")
        except RuntimeError:
            where.append("worker thread")
        return real()

    async def post(channel, text):
        posted.append(text)
        return True

    monkeypatch.setattr(ct, "get_stats", watched)
    monkeypatch.setattr(sp, "_post_to_discord", post)
    monkeypatch.setenv("DISCORD_STATUS_CHANNEL_ID", "1")
    monkeypatch.setitem(sys.modules, "core.bot_manager", types.SimpleNamespace(list_bots=lambda: []))
    asyncio.run(sp._send_discord_fleet_status())
    assert where == ["worker thread"]
    assert "  Affiliate: $0.00 · 2 clicks (lifetime)" in posted[0].split("\n")


# ─── nothing reads the old files, and the conversion log is gone ───────────

def _python_files():
    for top in ("core", "bots", "narai", "scripts"):
        for path in (ROOT / top).rglob("*.py"):
            if not {"__pycache__", "_archive", "node_modules", ".venv", "venv"} & set(path.parts):
                yield path


def test_nothing_reads_the_old_click_or_conversion_files():
    clicks_json, conversions_json, guess = [], [], []
    for path in _python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(ROOT).as_posix()
        if "clicks.json" in text:
            clicks_json.append(rel)
        if "conversions.json" in text:
            conversions_json.append(rel)
        if re.search(r"click_tracker\b.*\brecord_conversion|_load_conversions", text):
            guess.append(rel)
    assert clicks_json == ["scripts/board_import_json.py"]          # the one-off import reads a copy
    assert conversions_json == [] and guess == []
    assert not hasattr(ct, "record_conversion") and not hasattr(ct, "_load_conversions")
    assert not hasattr(ct, "CLICKS_FILE") and not hasattr(ct, "_save_clicks")
    assert "data/" not in (ct.__doc__ or "")
