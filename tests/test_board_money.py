"""Step 2a: the old money routes read the board's ledger by New York day.

GET /api/money/summary, /api/money/stripe and /api/money/record, POST
/api/money/record, the /api/revenue/* routes (RevenueEngine), the scoreboard
(GET /api/narai/scoreboard, GET /api/board/scoreboard) and the morning
message's revenue lines. Every figure is checked against the SQL's own
numbers (board_day for each day, board_revenue_daily), in dollars. A number
that is not measured is null, never 0; manual entries are manual ledger rows;
no code writes the old JSON stores; the invented KDP figure and the
launch()-only 08:00 report are gone. The Money Command Center's own
JavaScript (dashboard/index.html) runs in Node on the routes' answers, and the
monthly revenue goal follows the ledger.

No network: Supabase and Stripe are faked (tests/board_fakes.py); ConvertKit,
email capture, monetization, Impact, BudgetManager, GoalTracker and Telegram
are stubbed."""
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import types
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.board import day as board_day
from core.board import ledger, money
from core.board.connectors import stripe_sync
from core.board.ledger import LedgerRow
from tests import board_fakes as bf

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)      # 11:00 on Tue 3 Nov in New York
T = date(2026, 11, 3)
SINCE = date(2026, 1, 1)                                      # Stripe's measured_from (BOARD_BACKFILL_FROM)
KEY = {"X-API-Key": bf.API_KEY}
MONEY_KINDS = ("sale", "refund", "dispute", "dispute_reversal", "adjustment")


# ─── the fixture: Stripe through its sync, manual entries, all faked ────────

def extra_stripe():
    """Stripe sales beyond the plan's fixture day: 3 Nov (today), 28 Oct (in
    the week), 10 Oct (in the month) and 1 Aug (all time only)."""
    bts = [bf.charge_bt("txn_nov3", "ch_nov3", 4900, "2026-11-03T14:00:00Z", 172, payment_intent="pi_nov3",
                        email="carol@example.com"),
           bf.charge_bt("txn_oct28", "ch_oct28", 1200, "2026-10-28T16:00:00Z", 65, payment_intent="pi_oct28"),
           bf.charge_bt("txn_oct10", "ch_oct10", 9900, "2026-10-10T16:00:00Z", 317, payment_intent="pi_oct10"),
           bf.charge_bt("txn_aug1", "ch_aug1", 2500, "2026-08-01T16:00:00Z", 103)]
    sessions = [bf.session("pi_nov3", ("Prompt Bible", 1), email="carol@example.com"),
                bf.session("pi_oct28", ("Toodle Guide", 1)),
                bf.session("pi_oct10", ("AI Entrepreneur Blueprint Kit", 1))]
    return bts, sessions


def manual(external_id, at, cents, product, source="gumroad"):
    return ledger.manual_row(external_id, cents, datetime.fromisoformat(at.replace("Z", "+00:00")),
                             product=product, raw={"entered_via": "test", "source": source})


MANUAL_ROWS = (("manual:m1", "2026-10-30T18:00:00Z", 4000, "gumroad: course", "gumroad"),
               ("manual:m2", "2026-11-02T15:00:00Z", -700, "paypal: chargeback fee", "paypal"),
               ("manual:m3", "2026-09-15T15:00:00Z", 1500, "kdp_royalty: August payout", "kdp_royalty"),
               # the windows' edges: 27 Oct is T-7 (outside the week), 4 Oct is T-30 (outside the month)
               ("manual:m4", "2026-10-27T15:00:00Z", 300, "gumroad: sticker", "gumroad"),
               ("manual:m5", "2026-10-04T15:00:00Z", 200, "gumroad: postcard", "gumroad"))


class Recorder:
    def __init__(self, result=None):
        self.calls, self.result = [], result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def fake_module(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def world(monkeypatch):
    """The board's database and Stripe faked; today is Tue 3 Nov in New York;
    every vendor and file the routes touch is stubbed."""
    bf.clear_connectors(monkeypatch)
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    stripe = bf.install_stripe(monkeypatch)
    monkeypatch.setattr(money, "_clock", lambda: NOW)
    w = types.SimpleNamespace(db=db, stripe=stripe, telegram=Recorder(), goal=Recorder())

    class CK:                                   # ConvertKit: never called for real
        def _get(self, path, params=None):
            return {"total_subscribers": 7}

    fake_module(monkeypatch, "core.convertkit", ConvertKitClient=CK)
    fake_module(monkeypatch, "core.email_capture",
                get_email_capture=lambda: types.SimpleNamespace(get_stats=lambda: {"total": 3, "today": 1}))
    fake_module(monkeypatch, "core.monetization", get_monetization_engine=lambda: types.SimpleNamespace(
        get_injection_stats=lambda: {"total_injections": 2, "total_links": 5}))
    goals = types.SimpleNamespace(_goals={"monthly_revenue": types.SimpleNamespace(target=1000)}, update=w.goal)
    fake_module(monkeypatch, "core.goal_tracker", GoalTracker=types.SimpleNamespace(get=lambda: goals))
    monkeypatch.setattr("core.siteboost_state.stats", lambda: {"places_scanned": 40, "emails_sent": 10})
    from core.revenue import RevenueEngine
    monkeypatch.setattr(RevenueEngine, "pull_affiliate", lambda self, days=30: {
        "configured": True, "total_earned": 12.5, "period_days": days, "by_program": {}})
    monkeypatch.setattr(RevenueEngine, "pull_ad_roi", lambda self: {"today_spent": 0})
    import requests
    monkeypatch.setattr(requests, "post", w.telegram)
    monkeypatch.setattr("core.telegram.notify", w.telegram)
    w.client = bf.client(monkeypatch)
    import core.api as api
    monkeypatch.setattr(api, "_kdp_load_results", lambda: {"self_help": {"status": "published"},
                                                            "fantasy": {"status": "error"}})
    w.api = api
    return w


@pytest.fixture
def ledger_day(world):
    """Stripe synced at NOW (measured from 1 Jan), plus manual entries on
    30 Oct, 2 Nov, 15 Sep, 27 Oct and 4 Oct, and one entered today through
    the route."""
    world.stripe.add(*bf.fixture_day()).add(*extra_stripe())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    assert world.db.sources["stripe"]["measured_from"] == SINCE
    ledger.ingest_ledger("manual", None, [manual(*m) for m in MANUAL_ROWS])
    r = world.client.post("/api/money/record?source=kdp_royalty&amount=25&note=March%20payout", headers=KEY)
    assert r.status_code == 200 and r.json()["status"] == "recorded"
    return world


# ─── the SQL's own numbers ──────────────────────────────────────────────────

def days(first, last):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)


def sql_net(db, first, last, source=None) -> int:
    """Net cents from board_day, one day at a time (estimates left out)."""
    total = 0
    for d in days(first, last):
        view = db._rpc_board_day(d.isoformat())
        total += sum(v for k, v in view["by_source"].items() if (source is None or k == source) and k != "kdp")
    return total


def dollars(cents):
    return None if cents is None else cents / 100


def money_rows(db, source=None, first=None, last=None):
    return [r for r in db.board_ledger() if r["kind"] in MONEY_KINDS and not r["is_estimate"]
            and (source is None or r["source_id"] == source)
            and (first is None or r["local_day"] >= first) and (last is None or r["local_day"] <= last)]


def newest_first(rows):
    return sorted(rows, key=lambda r: (r["occurred_at"], r["external_id"]), reverse=True)


def masked(email):
    return "" if not email else email[0] + "***" + email[email.index("@"):]


# ─── the dashboard's own JavaScript, run in Node ────────────────────────────

def dashboard_js(*signatures: str) -> str:
    """dashboard/index.html's top-level functions that start with these
    signatures, as written: a one-line function, or up to its closing brace."""
    page = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    out = []
    for signature in signatures:
        start = page.index(signature)
        line = page[start:page.index("\n", start)]
        out.append(line + "\n" if line.count("{") == line.count("}") else page[start:page.index("\n}\n", start) + 3])
    return "".join(out)


def run_node(tmp_path, script: str) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    path = tmp_path / "dashboard_test.js"
    path.write_text(script, encoding="utf-8")
    ran = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


# ─── (a) the old JSON stores are gone ───────────────────────────────────────

def test_no_code_writes_or_reads_the_old_json_revenue_stores():
    allowed = {ROOT / "scripts" / "board_import_json.py"}
    found = []
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if (path.suffix not in (".py", ".sh", ".js", ".mjs", ".ts", ".tsx", ".html") or not path.is_file()
                or path in allowed or parts[0] in ("tests", "replica", ".git") or "node_modules" in parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "stripe_payments.json" in text or "revenue.json" in text:
            found.append(str(path.relative_to(ROOT)))
    assert found == []
    import core.api as api
    import core.revenue as revenue
    for name in ("_stripe_payments_file", "_save_stripe_payment", "_load_stripe_payments"):
        assert not hasattr(api, name)
    for name in ("DATA_FILE", "RevenueRecord", "STRIPE_KEY"):
        assert not hasattr(revenue, name)
    assert not hasattr(revenue.RevenueEngine, "_save") and not hasattr(revenue.RevenueEngine, "_load")


def test_the_dashboard_shows_no_estimate_and_never_a_dollar_zero_for_a_null():
    page = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    money = page[page.index("async function refreshMoney(){"):page.index("async function loadIncomeAssets(){")]
    for gone in ("est_daily", "money-kdp-daily", "money-kdp-monthly", "Stripe + KDP est.", "est. $"):
        assert gone not in page
    assert "stripe?.total||0" not in money and "(p.amount||0)" not in money     # a null is a dash, not $0.00
    for cell in ("esc(p.ts?.slice(0,16)||'—')", "esc(p.type||'—')", "esc(p.email||'—')", "esc(fmt(p.amount))"):
        assert cell in money                                                     # every payment cell escaped
    start = page.index("async function moneyRecordManual(){")
    record = page[start:page.index("\n}\n", start)]                              # the whole function
    assert "r.error" in record                                                   # the server's reason is shown


MONEY_HARNESS = """
const els = {};
const document = {getElementById: id => els[id] || (els[id] = {textContent: '', innerHTML: '', style: {}})};
const answers = %s;
async function fetch(url) {
  const body = answers[url.split('?')[0]];
  if (body === undefined) throw new TypeError('no answer for ' + url);
  return {status: 200, json: async () => body};
}
function loadIncomeAssets() {}
"""


def _money_center(tmp_path, client) -> dict:
    """The Money Command Center after refreshMoney(), on the routes' real answers."""
    answers = {path: client.get(path, headers=KEY).json() for path in ("/api/money/summary", "/api/money/record")}
    out = run_node(tmp_path, MONEY_HARNESS % json.dumps(answers) + dashboard_js("function esc(s){",
                                                                                  "async function refreshMoney(){")
                   + "refreshMoney().then(() => console.log(JSON.stringify(els)));")
    return json.loads(out)


def test_the_money_center_shows_a_manual_entry_without_stripe(world, tmp_path):
    r = world.client.post("/api/money/record?source=kdp_royalty&amount=40&note=royalty", headers=KEY)
    assert r.json()["status"] == "recorded"
    els = _money_center(tmp_path, world.client)
    assert els["money-today"]["textContent"] == "—"                     # Stripe is not measured here
    assert els["money-manual-week"]["textContent"] == "$40.00"
    assert els["money-manual-sub"]["textContent"] == "last 7 New York days · all time $40.00"
    table = els["money-stripe-payments"]["innerHTML"]
    assert "manual_kdp_royalty" in table and "$40.00" in table
    assert els["money-goal-lbl"]["textContent"] == "— / $1,000"         # Stripe not measured: no progress


def test_the_money_center_lists_manual_entries_and_counts_them_in_the_goal(ledger_day, tmp_path):
    w = ledger_day
    summary = w.client.get("/api/money/summary", headers=KEY).json()
    els = _money_center(tmp_path, w.client)
    total = summary["stripe"]["total"] + summary["manual"]["total"]
    assert els["money-goal-lbl"]["textContent"] == f"${total:.2f} / $1,000"
    assert els["money-manual-week"]["textContent"] == "$58.00"
    types_listed = re.findall(r'<td style="padding:6px 8px;color:var\(--cyan2\)">(.*?)</td>',
                              els["money-stripe-payments"]["innerHTML"])
    assert types_listed[:2] == ["manual_kdp_royalty", "sale"]            # today 11:00, then Stripe's 09:00
    assert len(types_listed) == 8


RECORD_HARNESS = """
const calls = [], toasts = [];
let asked = 0;
function prompt(q) { asked++; return asked === 1 ? 'kdp_royalty' : (q.startsWith('Amount') ? '250' : 'March'); }
function toast(m, kind) { toasts.push([m, kind]); }
function refreshMoney() {}
const answers = %s;                      // one per call: 'drop' (no answer), or [status, body]
async function fetch(url, opts) {
  const headers = (opts || {}).headers || {};
  calls.push({url, key: headers['Idempotency-Key'] || null});
  const a = answers[calls.length - 1];
  if (a === 'drop') throw new TypeError('Failed to fetch');
  if (a[1] === null) return {status: a[0], json: async () => { throw new SyntaxError('not JSON'); }};
  return {status: a[0], json: async () => a[1]};
}
"""


def _record_from_the_dashboard(tmp_path, *answers) -> dict:
    out = run_node(tmp_path, RECORD_HARNESS % json.dumps(list(answers)) + dashboard_js(
        "async function moneyRecordManual(){") + "moneyRecordManual().then(() => console.log(JSON.stringify({calls, toasts})));")
    return json.loads(out)


REPLAYED = [200, {"status": "recorded", "amount": 250.0, "id": "manual:idem:x", "replayed": True}]


@pytest.mark.parametrize("first", ["drop", [502, None], [503, {"status": "not recorded", "error": money.DB_DOWN}]])
def test_the_dashboard_sends_one_idempotency_key_and_asks_again_with_it(tmp_path, first):
    """No answer, a proxy's HTML 502 or the server's 503: the entry may be
    written all the same, so the dashboard asks once more with the same key
    and the server answers from the stored entry."""
    out = _record_from_the_dashboard(tmp_path, first, REPLAYED)
    keys = [c["key"] for c in out["calls"]]
    assert len(keys) == 2 and keys[0] and keys[0] == keys[1]
    assert out["toasts"] == [["Recorded $250.00 from kdp_royalty", "success"]]


def test_the_dashboard_says_it_is_not_sure_when_the_server_never_finishes(tmp_path):
    out = _record_from_the_dashboard(tmp_path, "drop", [503, {"status": "not recorded", "error": money.DB_DOWN}])
    assert len(out["calls"]) == 2
    assert out["toasts"] == [["Not sure it was recorded: the server did not finish. Check Money before you "
                              "enter it again.", "error"]]


def test_the_dashboard_shows_a_refusal_in_the_servers_words_and_asks_once(tmp_path):
    out = _record_from_the_dashboard(tmp_path, [422, {"status": "not recorded", "error": "The amount cannot be 0."}])
    assert len(out["calls"]) == 1 and out["toasts"] == [["The amount cannot be 0.", "error"]]


def test_today_is_the_new_york_date(monkeypatch):
    monkeypatch.setattr(money, "_clock", lambda: datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc))
    assert money.today() == date(2026, 11, 3)              # 22:00 on 3 Nov in New York, 4 Nov in UTC
    monkeypatch.setattr(money, "_clock", lambda: datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc))
    assert money.today() == date(2026, 11, 1)              # 01:30 EDT, before the clocks go back


# ─── (b) each route equals the SQL's numbers ────────────────────────────────

def test_money_summary_is_the_ledgers_by_new_york_day(ledger_day):
    w = ledger_day
    j = w.client.get("/api/money/summary", headers=KEY).json()
    db, week0 = w.db, T - timedelta(days=6)
    assert j["stripe"]["today"] == dollars(sql_net(db, T, T, "stripe")) == 49.0
    assert j["stripe"]["week"] == dollars(sql_net(db, week0, T, "stripe")) == 95.99
    assert j["stripe"]["total"] == dollars(sql_net(db, SINCE, T, "stripe"))
    assert j["manual"] == {"today": 25.0, "week": dollars(sql_net(db, week0, T, "manual")),
                           "total": dollars(sql_net(db, date(2026, 8, 1), T, "manual"))}
    assert j["manual"]["week"] == 58.0                                          # 40.00 - 7.00 + 25.00
    assert j["total_revenue_today"] == dollars(sql_net(db, T, T)) == 74.0       # Stripe 49 + manual 25
    expected = newest_first(money_rows(db, "stripe"))[:5]
    assert [p["event_id"] for p in j["stripe"]["recent"]] == [r["external_id"] for r in expected]
    assert [p["email"] for p in j["stripe"]["recent"]] == [masked(r["customer_email"]) for r in expected]
    first = j["stripe"]["recent"][0]
    assert first == {"ts": "2026-11-03T09:00:00-05:00", "type": "sale", "amount": 49.0, "currency": "usd",
                     "email": "c***@example.com", "product": "Prompt Bible", "event_id": "txn_nov3"}
    assert j["kdp"]["est_daily"] is None and j["kdp"]["published"] == 1 and j["kdp"]["errors"] == 1
    assert j["leads"] == {"total": 3, "today": 1, "list_size": 7}
    assert j["affiliate_clicks_7d"] == 0                                    # the clicks table, counted in SQL
    assert j["ledger"]["connected"] is True and j["ledger"]["tz"] == "America/New_York"
    assert j["ledger"]["today"] == "2026-11-03" and j["ledger"]["measured_from"] == "2026-01-01"
    assert "@example.com" not in json.dumps(j).replace("***@example.com", "")


def test_money_stripe_is_the_window_from_the_ledger(ledger_day):
    w = ledger_day
    j = w.client.get("/api/money/stripe?days=7", headers=KEY).json()
    first = T - timedelta(days=7)                                   # the old cutoff: today minus 7
    rows = money_rows(w.db, "stripe", first, T)
    assert j["total"] == dollars(sql_net(w.db, first, T, "stripe")) == 95.99
    assert j["count"] == len(rows) == 8
    assert j["by_type"] == {"sale": 115.98, "refund": -19.99}       # the dispute and its reversal net to 0
    assert sum(j["by_type"].values()) == pytest.approx(j["total"])
    assert [p["event_id"] for p in j["payments"]] == [r["external_id"] for r in newest_first(rows)]
    refund = next(p for p in j["payments"] if p["type"] == "refund")
    assert refund == {"ts": "2026-11-01T09:00:00-05:00", "type": "refund", "amount": -19.99, "currency": "usd",
                      "email": "o***@example.com", "product": "Toodle Guide", "event_id": "txn_ref0"}
    year = w.client.get("/api/money/stripe?days=3660", headers=KEY).json()     # starts before Stripe is measured
    assert year["total"] is None and year["count"] is None and year["by_type"] == {}
    assert len(year["payments"]) == len(money_rows(w.db, "stripe"))           # rows are still listed
    huge = w.client.get("/api/money/stripe?days=99999999999999", headers=KEY)
    assert huge.status_code == 200 and huge.json()["total"] is None          # kept to 3660 days, no 500


def test_the_revenue_summary_dashboard_and_report_are_the_ledgers(ledger_day, monkeypatch):
    w, db = ledger_day, ledger_day.db
    month0, week0 = T - timedelta(days=29), T - timedelta(days=6)
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert (s["today"], s["week"], s["month"], s["all_time"]) == (
        dollars(sql_net(db, T, T)), dollars(sql_net(db, week0, T)), dollars(sql_net(db, month0, T)),
        dollars(sql_net(db, SINCE, T)))
    assert s["by_source_30d"] == {"stripe": dollars(sql_net(db, month0, T, "stripe")),
                                  "manual": dollars(sql_net(db, month0, T, "manual"))}
    products: dict = {}
    for d in days(month0, T):
        for p in db._rpc_board_day(d.isoformat())["products"]:
            products[p["product"]] = products.get(p["product"], 0) + p["net_usd_cents"]
    top = sorted(products.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    assert s["top_earners_30d"] == [{"label": k, "amount": dollars(v)} for k, v in top]
    assert s["top_earners_30d"][0] == {"label": "AI Entrepreneur Blueprint Kit", "amount": 128.99}
    every = money.summary(top=20)["top_earners_30d"]
    assert [e["label"] for e in every] == [k for k, v in sorted(products.items(), key=lambda kv: (-kv[1], kv[0]))
                                           if v > 0]
    assert "paypal: chargeback fee" in products and products["paypal: chargeback fee"] < 0
    assert all(e["amount"] > 0 for e in every)          # a product that lost money in the window earns nothing
    assert s["total_records"] == len(money_rows(db)) == 17
    assert s["stripe_configured"] is True and s["measured_from"] == "2026-01-01"

    monkeypatch.setattr(stripe_sync, "mrr", lambda key: (2475, 3, None))        # the one live Stripe call
    d = w.client.get("/api/revenue/dashboard", headers=KEY).json()
    assert d["period"] == {k: s[k] for k in ("today", "week", "month", "all_time")}
    assert d["by_source"] == {"stripe": s["by_source_30d"]["stripe"], "affiliate": 12.5, "ad_attributed": None,
                              "manual": s["by_source_30d"]["manual"]}
    assert d["mrr"] == 24.75 and d["stripe"]["active_subscriptions"] == 3
    assert d["stripe"]["total_revenue"] == dollars(sql_net(db, month0, T, "stripe"))
    sales = [r for r in newest_first(money_rows(db, "stripe", month0, T)) if r["kind"] == "sale"]
    assert d["stripe"]["charge_count"] == len(sales)
    assert [c["id"] for c in d["stripe"]["recent_charges"]] == [r["order_ref"] for r in sales][:10]
    assert d["stripe"]["recent_charges"][0]["customer_email"] == "c***@example.com"
    assert d["goal_progress"] == {"target": 1000, "current": s["month"],
                                  "progress_pct": round(s["month"] / 1000 * 100, 1)}
    assert len(d["top_earners_30d"]) == 5 and d["total_records"] == 17

    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    lines = report.split("\n")
    assert lines[0] == "NarAI revenue report: Tue 3 Nov (New York)"
    assert lines[1:5] == [f"Today so far: {board_day.money(sql_net(db, T, T))}",
                          f"Last 7 days: {board_day.money(sql_net(db, week0, T))}",
                          f"Last 30 days: {board_day.money(sql_net(db, month0, T))}",
                          f"All time since 1 Jan 2026: {board_day.money(sql_net(db, SINCE, T))}"]
    assert lines[5] == (f"By source (30 days): Stripe {board_day.money(sql_net(db, month0, T, 'stripe'))} · "
                        f"Manual entries {board_day.money(sql_net(db, month0, T, 'manual'))}")
    assert lines[6].startswith("Top earners (30 days): AI Entrepreneur Blueprint Kit $128.99 · ")
    assert lines[7].startswith("Monthly goal: ") and "of $1,000.00" in lines[7]
    assert "est." not in report and "royalty est" not in report.lower() and "<" not in report


def test_the_scoreboard_cards_read_the_ledger(ledger_day, monkeypatch):
    w, db = ledger_day, ledger_day.db
    monkeypatch.setattr(stripe_sync, "mrr", lambda key: (9900, 4, None))
    for r in (w.client.get("/api/narai/scoreboard", headers=KEY),
              w.client.get("/api/board/scoreboard", headers=bf.owner_headers())):
        assert r.status_code == 200
        m = r.json()["metrics"]
        assert m["revenue_month"]["value"] == dollars(sql_net(db, T - timedelta(days=29), T))
        assert m["revenue_all_time"]["value"] == dollars(sql_net(db, SINCE, T))
        assert m["revenue_month"]["connected"] is True and "New York days" in m["revenue_month"]["note"]
        assert m["revenue_all_time"]["note"].startswith("since 1 Jan 2026; ")
        assert (m["mrr"]["value"], m["users"]["value"]) == (99.0, 4)
        assert m["places_scanned"] == {"value": 40, "connected": True, "source": "siteboost",
                                       "note": "counted on the server disk; a deploy resets it",
                                       "label": "places scanned (outreach)"}
        # the Command Center's keys stay: leads is the places-scanned counter, conversion users / leads
        assert (m["leads"]["value"], m["leads"]["connected"]) == (40, True)
        assert (m["conversion"]["value"], m["conversion"]["connected"]) == (round(4 / 40, 4), True)
        assert m["trials"]["connected"] is False and m["churn"]["connected"] is False
        s = r.json()["surfaces"]
        assert s == {"stripe": True, "kit": False, "instantly": False, "meta_ads": False, "siteboost": True,
                     "ds24": False, "stan": False, "bigcommerce": False}
        # deployments: not measured (production's scoreboard), so a dash, never a fake 0
        assert r.json()["headline"] == "MRR $99.00 · users 4 · places scanned 40 · — prod deployments"


def test_the_scoreboard_page_shows_the_cards_with_their_labels(ledger_day, monkeypatch, tmp_path):
    from tests.test_board_day import _page                 # frontend/admin/scoreboard.html's script, in Node
    monkeypatch.setattr(stripe_sync, "mrr", lambda key: (9900, 4, None))
    metrics = ledger_day.client.get("/api/narai/scoreboard", headers=KEY).json()["metrics"]
    metrics["revenue_all_time"]["value"] = -5.5                       # a month of refunds shows as a loss
    metrics["emails_sent"]["note"] = "<b>sent</b> & counted"
    grid = _page(tmp_path, board_day.day_view(date(2026, 11, 1)), metrics=metrics)["loaded"]["grid"]["html"]
    labels = re.findall(r'<div class="label">(.*?)</div>', grid)
    assert labels == ["MRR", "revenue, last 30 days", "revenue, all time", "users", "trials",
                      "places scanned (outreach)", "emails sent", "churn", "open bugs", "deployments"]
    month = dollars(sql_net(ledger_day.db, T - timedelta(days=29), T))
    assert f'<div class="val">${month:.2f}</div>' in grid and '<div class="val">$99.00</div>' in grid
    assert '<div class="val">-$5.50</div>' in grid and "$-" not in grid
    assert "counted on the server disk; a deploy resets it" in grid
    assert "&lt;b&gt;sent&lt;/b&gt; &amp; counted" in grid and "<b>sent" not in grid
    assert "leads" not in grid and "conversion" not in grid


# ─── (c) manual entries are manual ledger rows ──────────────────────────────

def test_a_manual_entry_is_one_manual_ledger_row(ledger_day):
    w = ledger_day
    (row,) = [r for r in w.db.rows("manual").values() if r["raw"].get("entered_via") == "/api/money/record"]
    assert re.fullmatch(r"manual:[0-9a-f-]{36}", row["external_id"]) and uuid.UUID(row["external_id"][7:])
    assert (row["kind"], row["amount_minor"], row["currency"], row["amount_usd_cents"], row["fx_source"]) == (
        "sale", 2500, "USD", 2500, "identity")
    assert row["fee_usd_cents"] is None and row["occurred_at"] == NOW and row["local_day"] == T
    assert row["product"] == "kdp_royalty: March payout"
    assert row["raw"] == {"entered_via": "/api/money/record", "source": "kdp_royalty", "note": "March payout"}
    records = w.client.get("/api/money/record", headers=KEY).json()["records"]
    assert records[0] == {"ts": "2026-11-03T11:00:00-05:00", "type": "manual_kdp_royalty", "amount": 25.0,
                          "currency": "usd", "email": "", "product": "kdp_royalty: March payout",
                          "event_id": row["external_id"]}
    assert [r["event_id"] for r in records] == [row["external_id"], "manual:m2", "manual:m1", "manual:m4"]  # T-29..T
    assert records[1]["type"] == "manual_paypal" and records[1]["amount"] == -7.0


def test_the_routes_answer_the_old_contract_and_refuse_plainly(world):
    c, db = world.client, world.db
    r = c.post("/api/money/record?source=gumroad&amount=19.99&note=ebook", headers=KEY)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "recorded" and j["amount"] == 19.99 and j["id"].startswith("manual:")
    neg = c.post("/api/money/record?source=paypal&amount=-5.5", headers=KEY).json()
    assert neg["status"] == "recorded" and db.rows("manual")[neg["id"]]["kind"] == "adjustment"
    assert db.rows("manual")[neg["id"]]["amount_minor"] == -550
    before = dict(db.ledger)
    for query, message in (
            ("source=kdp&amount=0", "The amount cannot be 0."),
            ("source=kdp&amount=nan", "The amount must be a number of dollars, such as 25.00."),
            ("source=kdp&amount=inf", "The amount must be a number of dollars, such as 25.00."),
            ("source=kdp&amount=1e400", "The amount must be a number of dollars, such as 25.00."),
            ("source=kdp&amount=12.345", "The amount can have at most 2 decimal places (whole cents)."),
            ("source=kdp&amount=2e6", "The amount is too large. One entry can record at most $1,000,000.00."),
            ("source=stripe&amount=10", "Stripe money comes from the Stripe sync."),
            ("source=%20Stripe%20&amount=10", "Stripe money comes from the Stripe sync."),
            ("source=%20&amount=10", "Say where the money came from, such as kdp_royalty."),
            ("source=" + "x" * 65 + "&amount=10", "The source is too long. Keep it to 64 characters or fewer."),
            ("source=kdp&amount=10&note=" + "n" * 501, "The note is too long. Keep it to 500 characters or fewer.")):
        r = c.post(f"/api/money/record?{query}", headers=KEY)
        assert (r.status_code, r.json()) == (422, {"status": "not recorded", "error": message}), query
    assert db.ledger == before
    r = c.post("/api/revenue/record?source=affiliate&label=Impact%20payout&amount=40", headers=KEY)
    j = r.json()
    assert r.status_code == 200 and {k: j[k] for k in ("status", "source", "label", "amount")} == {
        "status": "recorded", "source": "affiliate", "label": "Impact payout", "amount": 40.0}
    row = db.rows("manual")[j["id"]]
    assert row["product"] == "affiliate: Impact payout"
    assert row["raw"] == {"entered_via": "RevenueEngine.record", "source": "affiliate", "label": "Impact payout"}
    assert world.goal.calls == []                   # Stripe is not measured yet: the goal is left alone
    r = c.post("/api/revenue/record?source=stripe&label=x&amount=40", headers=KEY)
    assert (r.status_code, r.json()["error"]) == (422, "Stripe money comes from the Stripe sync.")


def test_an_idempotency_key_makes_a_retry_safe(world):
    c, db = world.client, world.db
    headers = {**KEY, "Idempotency-Key": "order-2026-11-03-0001"}
    first = c.post("/api/money/record?source=kdp_royalty&amount=25&note=x", headers=headers).json()
    expected = "manual:idem:" + hashlib.sha256(b"order-2026-11-03-0001").hexdigest()[:48]
    assert first == {"status": "recorded", "amount": 25.0, "id": expected}
    again = c.post("/api/money/record?source=kdp_royalty&amount=25&note=another%20note", headers=headers).json()
    assert again == {"status": "recorded", "amount": 25.0, "id": expected, "replayed": True}
    assert len(db.rows("manual")) == 1 and db.rows("manual")[expected]["product"] == "kdp_royalty: x"
    assert len(db.rpc_calls("board_ingest_ledger")) == 1                    # the key was never written twice
    r = c.post("/api/money/record?source=kdp_royalty&amount=26", headers=headers)
    assert r.status_code == 409 and r.json()["status"] == "not recorded"
    assert "another amount" in r.json()["error"] and len(db.rows("manual")) == 1
    assert "order-2026-11-03-0001" not in json.dumps(db.rows("manual"), default=str)   # only its hash is kept
    for bad in ("", b"\xe9-key", "bad\tkey", "x" * 256):
        r = c.post("/api/money/record?source=kdp&amount=1", headers={**KEY, "Idempotency-Key": bad})
        assert r.status_code == 422 and "Idempotency-Key" in r.json()["error"], bad
    assert len(db.rows("manual")) == 1


def test_the_revenue_record_route_honours_an_idempotency_key_too(world):
    c, db = world.client, world.db
    headers = {**KEY, "Idempotency-Key": "payout-2026-10"}
    url = "/api/revenue/record?source=affiliate&label=Impact%20payout&amount=40"
    first = c.post(url, headers=headers).json()
    again = c.post(url, headers=headers).json()                     # a retry after a lost answer
    assert first["status"] == again["status"] == "recorded" and first["id"] == again["id"]
    assert first["id"] == "manual:idem:" + hashlib.sha256(b"payout-2026-10").hexdigest()[:48]
    assert again["replayed"] is True and "replayed" not in first
    assert len(db.rows("manual")) == 1 and len(db.rpc_calls("board_ingest_ledger")) == 1
    r = c.post("/api/revenue/record?source=affiliate&label=Impact%20payout&amount=41", headers=headers)
    assert r.status_code == 409 and "another amount" in r.json()["error"] and len(db.rows("manual")) == 1
    r = c.post(url, headers={**KEY, "Idempotency-Key": "bad\tkey"})
    assert r.status_code == 422 and "Idempotency-Key" in r.json()["error"]
    assert c.post(url, headers=KEY).status_code == 200 and len(db.rows("manual")) == 2   # no key: a new entry


class MissOnce:
    """ledger.find_row whose first answer is 'not there': the check before
    writing ran while another request with the same key had not committed,
    so both requests reach board_ingest_ledger."""

    def __init__(self, real):
        self.real, self.missed = real, False

    def __call__(self, source_id, external_id):
        if not self.missed:
            self.missed = True
            return None
        return self.real(source_id, external_id)


def test_the_same_idempotency_key_at_the_same_moment_is_answered_from_the_stored_entry(world, monkeypatch):
    c, db = world.client, world.db
    headers = {**KEY, "Idempotency-Key": "race-key-1"}
    assert c.post("/api/money/record?source=kdp&amount=25&note=x", headers=headers).status_code == 200
    real = ledger.find_row
    monkeypatch.setattr(ledger, "find_row", MissOnce(real))
    r = c.post("/api/money/record?source=kdp&amount=26&note=y", headers=headers)
    assert r.status_code == 409 and "another amount" in r.json()["error"]
    (row,) = db.rows("manual").values()
    assert row["amount_minor"] == 2500
    monkeypatch.setattr(ledger, "find_row", MissOnce(real))
    r = c.post("/api/money/record?source=kdp&amount=25&note=z", headers=headers)
    assert (r.status_code, r.json().get("replayed"), r.json()["amount"]) == (200, True, 25.0)
    assert len(db.rows("manual")) == 1 and len(db.rpc_calls("board_ingest_ledger")) == 3


def test_the_database_down_records_nothing_and_says_so(world):
    c, db = world.client, world.db
    db.down = True
    for url in ("/api/money/record?source=kdp&amount=5", "/api/revenue/record?source=kdp&label=x&amount=5"):
        r = c.post(url, headers=KEY)
        assert (r.status_code, r.json()) == (503, {"status": "not recorded",
                                                   "error": "Not recorded: the database is not connected."})
        assert '"recorded"' not in r.text
    db.down = False
    assert db.ledger == {}
    db.fail["rpc/board_ingest_ledger"] = 400                   # a refusal from PostgREST: still nothing
    r = c.post("/api/money/record?source=kdp&amount=5", headers=KEY)
    assert r.status_code == 503 and "Failing row" not in r.text and "x@example.com" not in r.text


# ─── (d) not measured is null, never 0 ──────────────────────────────────────

def test_without_a_stripe_key_stripe_figures_are_null_and_manual_ones_are_numbers(ledger_day, monkeypatch):
    w = ledger_day
    monkeypatch.delenv("STRIPE_READ_KEY")
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert (j["stripe"]["today"], j["stripe"]["week"], j["stripe"]["total"], j["total_revenue_today"]) == (
        None, None, None, None)
    assert j["manual"]["today"] == 25.0 and j["manual"]["week"] == 58.0
    assert "Stripe key not set" in j["ledger"]["note"] and j["ledger"]["connected"] is True
    assert len(j["stripe"]["recent"]) == 5                       # the rows are real; only totals are unknown
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert (s["today"], s["week"], s["month"], s["all_time"]) == (None, None, None, None)
    assert s["by_source_30d"] == {"stripe": None, "manual": dollars(sql_net(w.db, T - timedelta(days=29), T, "manual"))}
    assert s["stripe_configured"] is False
    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    assert "Today so far: not measured (Stripe key not set: STRIPE_READ_KEY (or STRIPE_SECRET_KEY))" in report
    assert "$0.00" not in report and "Monthly goal: not measured yet (target $1,000.00)" in report
    m = w.client.get("/api/narai/scoreboard", headers=KEY).json()
    assert m["metrics"]["revenue_month"]["connected"] is False and m["metrics"]["revenue_month"]["value"] is None
    assert m["metrics"]["mrr"]["value"] is None and "Stripe key not set" in m["metrics"]["mrr"]["note"]
    assert m["surfaces"]["stripe"] is False
    stripe = w.client.get("/api/money/stripe?days=7", headers=KEY).json()
    assert stripe["total"] is None and stripe["count"] is None and len(stripe["payments"]) == 8
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_" "FAKEtestmodekey123")         # a test key is no key
    assert w.client.get("/api/money/summary", headers=KEY).json()["stripe"]["today"] is None


def test_a_window_that_starts_before_stripe_is_measured_is_null(ledger_day):
    w = ledger_day
    w.db.set_source("stripe", measured_from="2026-10-31")
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert j["stripe"]["today"] == 49.0 and j["stripe"]["week"] is None             # the week starts 28 Oct
    assert j["stripe"]["total"] == dollars(sql_net(w.db, date(2026, 10, 31), T, "stripe"))   # since 31 Oct
    assert "measured only from 31 Oct 2026" in j["ledger"]["note"]
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert s["today"] == 74.0 and s["week"] is None and s["month"] is None
    assert s["all_time"] == dollars(sql_net(w.db, date(2026, 10, 31), T))
    assert w.client.get("/api/money/stripe?days=7", headers=KEY).json()["total"] is None
    assert w.client.get("/api/money/stripe?days=2", headers=KEY).json()["total"] == dollars(
        sql_net(w.db, date(2026, 11, 1), T, "stripe"))
    w.db.set_source("stripe", measured_from=None)                            # no sync has completed
    assert w.client.get("/api/money/summary", headers=KEY).json()["stripe"]["total"] is None


def test_a_stripe_sync_that_stopped_before_today_makes_stripe_figures_null(ledger_day):
    w = ledger_day
    w.db.set_source("stripe", synced_through="2026-11-02T20:00:00+00:00")     # 15:00 on Mon 2 Nov in New York
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert (j["stripe"]["today"], j["stripe"]["week"], j["stripe"]["total"], j["total_revenue_today"]) == (
        None, None, None, None)                                                 # never a $0 for an unread day
    assert j["manual"]["today"] == 25.0                                         # entered by hand: still a number
    assert j["ledger"]["stripe_synced_through"] == "2026-11-02T20:00:00+00:00"
    assert j["ledger"]["note"].startswith(
        "Stripe is not measured today: the Stripe sync has read only up to 15:00 on Mon 2 Nov (New York).")
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert (s["today"], s["week"], s["month"], s["all_time"]) == (None, None, None, None)
    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    assert "Today so far: not measured (the Stripe sync has read only up to 15:00 on Mon 2 Nov (New York))" in report
    stripe = w.client.get("/api/money/stripe?days=7", headers=KEY).json()
    assert stripe["total"] is None and stripe["count"] is None and len(stripe["payments"]) == 8
    cards = w.client.get("/api/narai/scoreboard", headers=KEY).json()["metrics"]
    assert cards["revenue_month"]["connected"] is False and "15:00 on Mon 2 Nov" in cards["revenue_month"]["note"]
    w.db.set_source("stripe", synced_through="2026-11-03T05:05:00+00:00")     # 00:05 on Tue 3 Nov: into today
    assert w.client.get("/api/money/summary", headers=KEY).json()["stripe"]["today"] == 49.0


def test_the_database_down_makes_every_money_number_null(ledger_day):
    w = ledger_day
    w.db.down = True
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert j["stripe"] == {"today": None, "week": None, "total": None, "recent": []}
    assert j["manual"] == {"today": None, "week": None, "total": None}
    assert j["total_revenue_today"] is None and j["affiliate_clicks_7d"] is None
    assert j["ledger"]["connected"] is False and j["ledger"]["note"] == "database not connected"
    assert w.client.get("/api/money/record", headers=KEY).json() == {"records": [], "error": "database not connected"}
    stripe = w.client.get("/api/money/stripe", headers=KEY).json()
    assert (stripe["total"], stripe["count"], stripe["by_type"], stripe["payments"]) == (None, None, {}, [])
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert {k: s[k] for k in ("today", "week", "month", "all_time", "total_records")} == dict.fromkeys(
        ("today", "week", "month", "all_time", "total_records"))
    assert s["top_earners_30d"] == [] and s["by_source_30d"] == {"stripe": None, "manual": None}
    m = w.client.get("/api/narai/scoreboard", headers=KEY).json()
    assert m["metrics"]["revenue_all_time"]["value"] is None and m["surfaces"]["stripe"] is False
    assert "$0" not in json.dumps(j) + json.dumps(s)


def test_a_row_without_us_dollars_makes_its_window_null_never_smaller(ledger_day):
    w = ledger_day
    eur = LedgerRow(external_id="txn_eur", kind="sale", amount_minor=1000, currency="EUR",
                    occurred_at=datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc))      # no USD amount yet
    ledger.ingest_ledger("stripe", None, [eur])
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert j["stripe"]["today"] == 49.0                                     # 3 Nov has no such row
    assert j["stripe"]["week"] is None and j["stripe"]["total"] is None
    assert j["manual"]["week"] == 58.0 and j["total_revenue_today"] == 74.0
    s = w.client.get("/api/revenue/summary", headers=KEY).json()
    assert s["week"] is None and s["month"] is None and s["today"] == 74.0
    assert s["by_source_30d"] == {"stripe": None, "manual": 61.0}       # 27 Oct is in the 30 days
    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    assert "Last 7 days: not measured (a row has no US dollar amount yet)" in report
    stripe = w.client.get("/api/money/stripe?days=7", headers=KEY).json()
    assert stripe["total"] is None and stripe["by_type"] == {} and stripe["count"] == 9


# ─── (e) the API's row cap never shortens a total ───────────────────────────

def _numbers(c):
    j = c.get("/api/money/summary", headers=KEY).json()
    s = c.get("/api/revenue/summary", headers=KEY).json()
    return ({k: v for k, v in j["stripe"].items() if k != "recent"}, j["manual"], j["total_revenue_today"],
            {k: s[k] for k in ("today", "week", "month", "all_time", "by_source_30d", "total_records")})


def test_a_row_cap_never_makes_a_total_smaller(ledger_day, monkeypatch):
    w = ledger_day
    uncapped = _numbers(w.client)
    w.db.max_rows = 3                                   # every window reads in parts now
    assert _numbers(w.client) == uncapped
    reads = [c for c in w.db.calls if c.url.path == "/rest/v1/board_revenue_daily"]
    assert len(reads) > 10 and all("count=exact" in c.headers.get("prefer", "") for c in reads)
    # A server that sends no count: a read is whole only while it is under MAX_ROWS rows.
    w.db.exact_counts = False
    monkeypatch.setattr(ledger, "MAX_ROWS", 3)
    no_count = _numbers(w.client)
    assert no_count[:3] == uncapped[:3]
    assert {k: v for k, v in no_count[3].items() if k != "total_records"} == {
        k: v for k, v in uncapped[3].items() if k != "total_records"}
    assert no_count[3]["total_records"] is None          # a count is the database's, never a guess
    w.db.exact_counts = True
    # one day with four groups (source, channel): it can never be read whole, so no total is shown
    at = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    ledger.ingest_ledger("stripe", None, [
        LedgerRow(external_id=f"txn_cap{n}", kind="sale", amount_minor=100, currency="USD", occurred_at=at,
                  channel=channel, attribution="checkout_utm" if channel else "none")
        for n, channel in enumerate(("meta", "google", "organic", None))])
    capped = _numbers(w.client)
    assert capped[0] == {"today": None, "week": None, "total": None} and capped[2] is None
    assert capped[3]["month"] is None and capped[3]["all_time"] is None


# ─── (f) an estimate never changes a legacy number ──────────────────────────

def test_a_kdp_estimate_changes_no_legacy_number(ledger_day):
    w = ledger_day
    before = _numbers(w.client)
    w.db.add_estimate("kdp:2026-11-03:B0TEST", "2026-11-03", 999)
    w.db.add_estimate("kdp:2026-11-02:B0TEST", "2026-11-02", 500, product="Big Book")
    assert _numbers(w.client) == before
    view = w.db._rpc_board_day("2026-11-03")
    assert view["by_source"]["kdp"] == 999 and view["revenue"]["has_estimates"] is True    # the board shows it
    labels = [e["label"] for e in w.client.get("/api/revenue/summary", headers=KEY).json()["top_earners_30d"]]
    assert "Big Book" not in labels and "KDP royalties" not in labels


# ─── (g) one daily revenue message: the board's ─────────────────────────────

def test_launch_schedules_no_revenue_report():
    import core.api as api
    source = inspect.getsource(api.launch)
    assert "RevenueEngine" not in source and "revenue-reporter" not in source and "core.revenue" not in source


def test_autopilots_daily_cycle_reads_the_revenue_and_sends_nothing(ledger_day):
    from core.autopilot import AutopilotEngine, AutopilotState
    engine = AutopilotEngine.__new__(AutopilotEngine)            # no state file read or written
    engine._state = AutopilotState()
    results: dict = {}
    engine._daily_revenue(results)
    assert ledger_day.telegram.calls == []
    assert results["revenue"]["today"] == 74.0 and results["revenue"]["month"] == dollars(
        sql_net(ledger_day.db, T - timedelta(days=29), T))
    assert engine._state.log[-1]["message"] == "Revenue: the board 07:00 message reports it"
    run_daily = inspect.getsource(AutopilotEngine.run_daily)
    assert "send_daily_report()" in run_daily and "RevenueEngine" not in run_daily   # the goal report only


def test_send_report_says_whether_telegram_took_it(world, monkeypatch):
    c = world.client
    r = c.post("/api/revenue/send-report", headers=KEY)
    assert (r.status_code, r.json()) == (503, {"status": "not sent", "error": "Telegram is not configured"})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE-telegram-token-for-tests")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    world.telegram.result = types.SimpleNamespace(status_code=401, json=lambda: {"ok": False})
    r = c.post("/api/revenue/send-report", headers=KEY)
    assert (r.status_code, r.json()["error"]) == (503, "Telegram did not accept the message")
    world.telegram.result = types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})
    r = c.post("/api/revenue/send-report", headers=KEY)
    assert (r.status_code, r.json()) == (200, {"status": "sent"})
    args, kwargs = world.telegram.calls[-1]
    assert "parse_mode" not in kwargs["json"] and kwargs["json"]["text"].startswith("NarAI revenue report:")


def test_a_failed_telegram_send_never_logs_the_token(world, monkeypatch, caplog):
    from core.revenue import RevenueEngine
    token = "123456:FAKE-telegram-token-for-tests"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(url, **kwargs):
        raise ConnectionError(f"cannot reach {url}")              # requests quotes the URL, token and all

    import requests
    monkeypatch.setattr(requests, "post", boom)
    caplog.set_level("INFO")
    assert RevenueEngine.get().send_daily_report() is False
    assert token not in caplog.text and "ConnectionError" in caplog.text


# ─── (h) the morning message: a line per source ─────────────────────────────

def test_the_morning_message_shows_manual_entries_on_a_line_of_their_own(world):
    world.stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))["status"] == "ok"
    stripe_only = board_day.render_report(board_day.day_view(date(2026, 11, 1))).split("\n")
    assert stripe_only[3:5] == ["Revenue: $10.00 net · attributed $0.00 · fees $3.17",
                                "  Stripe $10.00: 1 sale, 1 refund, 1 dispute, 1 dispute won"]
    ledger.ingest_ledger("manual", None, [manual("manual:nov1", "2026-11-01T17:00:00Z", 2500,
                                                 "kdp_royalty: <b>payout</b> & co", "kdp_royalty")])
    view = board_day.day_view(date(2026, 11, 1))
    lines = board_day.render_report(view).split("\n")
    assert lines[3:7] == ["Revenue: $35.00 net · attributed $0.00 · fees $3.17",   # a manual entry has no channel
                          "  Stripe $10.00: 1 sale, 1 refund, 1 dispute, 1 dispute won",
                          "  Manual entries $25.00: 1 sale",
                          "  fees unknown on 1 row"]
    rev = view["numbers"]["revenue"]
    assert rev["source"] == "stripe, manual" and rev["counts_by_source"]["manual"] == {"sale": 1}
    assert rev["counts_by_source"]["stripe"] == {"sale": 1, "refund": 1, "dispute": 1, "dispute_reversal": 1}
    assert "<b>payout" not in "\n".join(lines)


# ─── (i) the monthly goal follows the ledger ────────────────────────────────

def test_an_ok_stripe_sync_job_moves_the_monthly_goal(ledger_day, monkeypatch):
    from core.board import jobs
    w = ledger_day
    later = NOW + timedelta(minutes=30)
    w.stripe.add([bf.charge_bt("txn_big", "ch_big", 50000, "2026-11-03T16:10:00Z", 1480, payment_intent="pi_big")])
    monkeypatch.setattr(money, "_clock", lambda: later)
    w.db.clock = lambda: later
    real_run = stripe_sync.run
    monkeypatch.setattr(stripe_sync, "run", lambda trigger="schedule", days=None: real_run(trigger, days, now=later))
    w.goal.calls.clear()
    assert jobs.sync_stripe()["status"] == "ok"
    month = money.month_total()
    assert month == dollars(sql_net(w.db, T - timedelta(days=29), T)) and month > 500
    assert [c[0] for c in w.goal.calls] == [("monthly_revenue", month)]
    w.goal.calls.clear()
    monkeypatch.setattr(stripe_sync, "run", lambda trigger="schedule", days=None: {"status": "failed"})
    assert jobs.sync_stripe()["status"] == "failed" and w.goal.calls == []       # only after an ok run


def test_a_manual_entry_from_the_money_route_moves_the_monthly_goal(ledger_day):
    w = ledger_day
    w.goal.calls.clear()
    assert w.client.post("/api/money/record?source=gumroad&amount=10", headers=KEY).status_code == 200
    assert [c[0] for c in w.goal.calls] == [("monthly_revenue", money.month_total())]
    w.goal.calls.clear()
    headers = {**KEY, "Idempotency-Key": "goal-replay"}
    assert w.client.post("/api/money/record?source=gumroad&amount=5", headers=headers).status_code == 200
    w.goal.calls.clear()
    assert w.client.post("/api/money/record?source=gumroad&amount=5", headers=headers).json()["replayed"] is True
    assert w.goal.calls == []                                                    # a replay changes nothing


# ─── (j) top earners only over 30 measured days ─────────────────────────────

def test_no_top_earners_are_listed_while_the_last_30_days_are_not_measured(ledger_day):
    w = ledger_day
    assert money.summary_cents()["top_earners_30d"]                              # measured: listed
    w.db.set_source("stripe", measured_from="2026-10-20")                        # inside the 30 days
    s = money.summary_cents()
    assert s["month"] is None and s["top_earners_30d"] == []
    assert w.client.get("/api/revenue/summary", headers=KEY).json()["top_earners_30d"] == []
    assert w.client.get("/api/revenue/dashboard", headers=KEY).json()["top_earners_30d"] == []
    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    assert "Last 30 days: not measured (Stripe is measured only from 20 Oct 2026)" in report
    assert "Top earners" not in report
    w.db.set_source("stripe", measured_from="2026-01-01", synced_through="2026-10-31T12:00:00+00:00")
    assert money.summary_cents()["top_earners_30d"] == []                        # a sync that stopped days ago


# ─── (k) an entry's text stays on one line ──────────────────────────────────

def test_a_note_cannot_add_lines_to_the_revenue_report(ledger_day):
    w = ledger_day
    note = "royalty%0AToday%20so%20far:%20$1,000,000.00%0D%0ALast%207%20days:%20$2,000,000.00%E2%80%AE%09x"
    r = w.client.post(f"/api/money/record?source=kdp%0Aextra&amount=5000&note={note}", headers=KEY)
    assert r.status_code == 200
    one_line = "kdp extra: royalty Today so far: $1,000,000.00 Last 7 days: $2,000,000.00 x"
    (row,) = [x for x in w.db.rows("manual").values() if x["amount_minor"] == 500000]
    assert row["product"] == one_line and row["raw"]["source"] == "kdp extra"
    report = w.client.get("/api/revenue/report", headers=KEY).json()["report"]
    lines = report.split("\n")
    assert f"Top earners (30 days): {one_line} $5,000.00" in [line.split(" · ")[0] for line in lines]
    assert not any(line.startswith(("Today so far: $1,000,000.00", "Last 7 days: $2,000,000.00")) for line in lines)
    assert "\u202e" not in report and "\t" not in report and "\r" not in report


def test_the_report_keeps_every_product_name_on_one_line(world):
    """A product name from anywhere (a Stripe product, an imported entry)
    stays on its line too."""
    s = money.summary_cents()
    s["top_earners_30d"] = [("Course\nToday so far: $9,999.00\u202e", 100)]
    text = money.report_text(s)
    assert "Top earners (30 days): Course Today so far: $9,999.00 $1.00" in text.split("\n")
    assert "\u202e" not in text


# ─── (l) the money routes need the API key ──────────────────────────────────

def test_the_money_routes_need_the_api_key(world):
    c, db = world.client, world.db
    routes = (("POST", "/api/money/record?source=kdp&amount=999999"),
              ("POST", "/api/revenue/record?source=kdp&label=x&amount=999999"),
              ("GET", "/api/money/summary"), ("GET", "/api/money/stripe"), ("GET", "/api/money/record"),
              ("GET", "/api/revenue/summary"), ("GET", "/api/revenue/dashboard"), ("GET", "/api/revenue/report"),
              ("POST", "/api/revenue/send-report"), ("GET", "/api/narai/scoreboard"))
    for headers in ({}, {"X-API-Key": "wrong-key"}):
        for method, url in routes:
            assert c.request(method, url, headers=headers).status_code == 401, (method, url, headers)
    assert db.ledger == {}
    assert c.post("/api/money/record?source=kdp&amount=5", headers=KEY).status_code == 200   # the key works


# ─── (l2) without API_KEY on the server, only an owner session records ──────

WRITES = ("/api/money/record?source=kdp&amount=999999", "/api/revenue/record?source=kdp&label=x&amount=999999")
OWN_PAGE = bf.SAME_ORIGIN                                      # a write from the site's own page


@pytest.fixture
def no_api_key(world, monkeypatch):
    """API_KEY not set on the server, in a declared local environment (the
    suite runs with APP_ENV=test): api_key_middleware lets every /api route
    through, so _manual_entry_denial alone decides. The owner is production's
    owner session (bf.owner_headers)."""
    monkeypatch.setattr(world.api, "_API_KEY", "")
    monkeypatch.delenv("API_KEY", raising=False)
    assert world.api._auth_config_allows_open_access()
    return world


def test_without_an_api_key_a_manual_entry_without_an_owner_session_is_refused(no_api_key, monkeypatch):
    """Manual entries change the owner's board (SEC-1): they fail closed. No
    session, any key, an operator's session, an expired or forged cookie, the
    owner's cookie sent from another site or with no Origin, or the owner's
    cookie while the operator session is switched off: 503 in plain words, and
    nothing is written."""
    import dataclasses
    w = no_api_key
    c = w.client
    refused = (503, {"error": "Not recorded: API_KEY is not set on the server."})
    owner = bf.owner_headers()
    for url in WRITES + ("/api/money/record?source=kdp&amount=0",):          # refused before any check
        for headers in ({}, {"X-API-Key": "any-key"}, {**bf.owner_headers("operator"), **OWN_PAGE},
                        {**bf.owner_headers(ttl_seconds=-60), **OWN_PAGE},
                        {"Cookie": "wv_session=not-a-token", **OWN_PAGE},
                        {**owner, "Origin": "https://elsewhere.example"},     # the owner's cookie, another site
                        owner):                                               # the owner's cookie, no Origin
            r = c.post(url, headers=headers)
            assert (r.status_code, r.json()) == refused, (url, headers)
    monkeypatch.setenv("API_KEY", "set-later")      # as POST /api/settings would: the server read API_KEY at start
    for headers in ({}, {"X-API-Key": "set-later"}):
        r = c.post(WRITES[1], headers=headers)
        assert (r.status_code, r.json()) == refused
    monkeypatch.setattr(w.api, "_OPERATOR_SESSION_CFG",                        # the session switched off
                        dataclasses.replace(w.api._OPERATOR_SESSION_CFG, enabled=False))
    r = c.post(WRITES[0], headers={**owner, **OWN_PAGE})
    assert (r.status_code, r.json()) == refused
    assert w.db.ledger == {} and w.db.rpc_calls("board_ingest_ledger") == [] and w.goal.calls == []


def test_without_an_api_key_the_owner_session_still_records(no_api_key):
    w = no_api_key
    owner = {**bf.owner_headers(), **OWN_PAGE}
    first = w.client.post("/api/money/record?source=kdp_royalty&amount=25&note=March", headers=owner)
    second = w.client.post("/api/revenue/record?source=affiliate&label=payout&amount=40", headers=owner)
    assert (first.status_code, first.json()["status"], first.json()["amount"]) == (200, "recorded", 25.0)
    assert (second.status_code, second.json()["status"], second.json()["amount"]) == (200, "recorded", 40.0)
    assert {r["raw"]["entered_via"] for r in w.db.rows("manual").values()} == {
        "/api/money/record", "RevenueEngine.record"}


def test_with_an_api_key_the_manual_routes_answer_as_before(no_api_key, monkeypatch):
    w = no_api_key
    c = w.client
    monkeypatch.setattr(w.api, "_API_KEY", bf.API_KEY)
    monkeypatch.setenv("API_KEY", bf.API_KEY)
    owner = {**bf.owner_headers(), **OWN_PAGE}
    for url in WRITES:
        assert c.post(url).status_code == 401                                   # api_key_middleware, as before
        assert c.post(url, headers={"X-API-Key": "wrong-key"}).status_code == 401
        assert c.post(url, headers=KEY).json()["status"] == "recorded"
        assert c.post(url, headers=owner).json()["status"] == "recorded"        # the owner session, no key
    assert len(w.db.rows("manual")) == 4


def test_the_dashboard_and_narai_show_the_refusal_and_do_not_ask_again(no_api_key, monkeypatch, tmp_path):
    """The refusal writes nothing, so asking again with the same key cannot
    change it: the Money Command Center and NarAI's record_revenue say it in
    the server's words, once, never 'could not confirm'."""
    w = no_api_key
    r = w.client.post("/api/money/record?source=kdp_royalty&amount=250&note=March")
    refused = [r.status_code, r.json()]
    out = _record_from_the_dashboard(tmp_path, refused, refused)
    assert len(out["calls"]) == 1 and out["toasts"] == [[money.NO_API_KEY, "error"]]
    import requests
    from tests.test_narai_money_tools import narai
    sent = []

    def post(url, params=None, headers=None, timeout=10, **kwargs):                # NarAI's call, to this app
        sent.append(url)
        return w.client.post(url.replace("http://localhost:5050", ""), params=params, headers=headers)

    monkeypatch.setattr(requests, "post", post)
    bot = narai.NarAIBot.__new__(narai.NarAIBot)
    assert bot._narai_record_revenue("kdp_royalty", 250.0, "March") == money.NO_API_KEY
    assert sent == ["http://localhost:5050/api/money/record"] and w.db.ledger == {}
    assert narai._NO_API_KEY == money.NO_API_KEY


# ─── (m) the window edges and the rules each figure keeps ───────────────────

@pytest.fixture
def lost_dispute(world):
    """The fixture, plus a $30 sale on 30 Oct whose dispute is lost on 2 Nov (no reversal)."""
    bts, sessions = extra_stripe()
    bts += [bf.charge_bt("txn_dsale", "ch_d", 3000, "2026-10-30T16:00:00Z", 117, payment_intent="pi_d"),
            bf.dispute_bt("txn_dlost", "du_d", "ch_d", 3000, "2026-11-02T16:00:00Z", fee=1500)]
    sessions += [bf.session("pi_d", ("Disputed Kit", 1))]
    world.stripe.add(*bf.fixture_day()).add(bts, sessions)
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    return world


def test_a_lost_dispute_is_negative_in_by_type_with_no_made_up_adjustment(lost_dispute):
    w = lost_dispute
    j = w.client.get("/api/money/stripe?days=7", headers=KEY).json()
    assert j["total"] == dollars(sql_net(w.db, T - timedelta(days=7), T, "stripe")) == 95.99
    assert j["by_type"] == {"sale": 145.98, "refund": -19.99, "dispute": -30.0}
    assert sum(j["by_type"].values()) == pytest.approx(j["total"])


@pytest.fixture
def card_edges(world, monkeypatch):
    """The fixture, plus Stripe sales on 4 Oct (T-30, outside the card's 30 days) and 5 Oct (T-29, inside)."""
    bts, sessions = extra_stripe()
    bts += [bf.charge_bt("txn_e30", "ch_e30", 700, "2026-10-04T16:00:00Z", 30, payment_intent="pi_e30"),
            bf.charge_bt("txn_e29", "ch_e29", 800, "2026-10-05T16:00:00Z", 31, payment_intent="pi_e29")]
    world.stripe.add(*bf.fixture_day()).add(bts, sessions)
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    monkeypatch.setattr(stripe_sync, "mrr", lambda key: (2475, 3, None))
    return world


def test_the_stripe_card_reads_exactly_30_new_york_days(card_edges):
    w = card_edges
    month0 = T - timedelta(days=29)
    d = w.client.get("/api/revenue/dashboard", headers=KEY).json()["stripe"]
    sales = [r for r in money_rows(w.db, "stripe", month0, T) if r["kind"] == "sale"]
    assert d["total_revenue"] == dollars(sql_net(w.db, month0, T, "stripe"))
    assert d["charge_count"] == len(sales) and "ch_e29" in {r["order_ref"] for r in sales}
    assert "ch_e30" not in [c["id"] for c in d["recent_charges"]]


def test_the_stripe_card_counts_no_charges_while_the_sync_lags(card_edges):
    w = card_edges
    w.db.set_source("stripe", synced_through="2026-11-02T20:00:00+00:00")     # 15:00 on Mon 2 Nov in New York
    d = w.client.get("/api/revenue/dashboard", headers=KEY).json()["stripe"]
    assert d["total_revenue"] is None and d["charge_count"] is None
    assert d["recent_charges"]                                                 # the rows are still listed


def test_the_manual_total_never_depends_on_stripes_measured_from(ledger_day):
    w = ledger_day
    expected = dollars(sql_net(w.db, date(2026, 8, 1), T, "manual"))
    assert expected == 78.0
    w.db.set_source("stripe", measured_from="2026-10-31")
    assert w.client.get("/api/money/summary", headers=KEY).json()["manual"]["total"] == expected
    w.db.set_source("stripe", measured_from=None)                              # no Stripe sync has completed
    assert w.client.get("/api/money/summary", headers=KEY).json()["manual"]["total"] == expected


def test_a_listed_row_without_us_dollars_shows_null_not_zero(ledger_day):
    w = ledger_day
    eur = LedgerRow(external_id="txn_eur", kind="sale", amount_minor=1000, currency="EUR",
                    occurred_at=datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc))      # no USD amount yet
    ledger.ingest_ledger("stripe", None, [eur])
    payments = w.client.get("/api/money/stripe?days=7", headers=KEY).json()["payments"]
    assert next(p for p in payments if p["event_id"] == "txn_eur")["amount"] is None
    recent = w.client.get("/api/money/summary", headers=KEY).json()["stripe"]["recent"]
    assert next(p for p in recent if p["event_id"] == "txn_eur")["amount"] is None


def test_a_disabled_stripe_source_makes_stripe_figures_null(ledger_day):
    w = ledger_day
    w.db.set_source("stripe", enabled=False)
    j = w.client.get("/api/money/summary", headers=KEY).json()
    assert (j["stripe"]["today"], j["stripe"]["week"], j["stripe"]["total"], j["total_revenue_today"]) == (
        None, None, None, None)
    assert "disabled" in j["ledger"]["note"] and j["manual"]["today"] == 25.0


def test_a_scoreboard_surface_needs_a_completed_stripe_sync(world, monkeypatch):
    monkeypatch.setattr(stripe_sync, "mrr", lambda key: (9900, 4, None))
    world.db.set_source("stripe", enabled=True, measured_from=None)           # key set, no sync completed yet
    assert world.client.get("/api/narai/scoreboard", headers=KEY).json()["surfaces"]["stripe"] is False


def test_a_product_that_nets_to_zero_is_no_top_earner(ledger_day):
    at = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    ledger.ingest_ledger("manual", None, [
        ledger.manual_row("manual:z1", 900, at, product="gumroad: refunded", raw={"source": "gumroad"}),
        ledger.manual_row("manual:z2", -900, at + timedelta(hours=1), product="gumroad: refunded",
                          raw={"source": "gumroad"})])
    earners = money.summary(top=50)["top_earners_30d"]
    assert "gumroad: refunded" not in [e["label"] for e in earners] and all(e["amount"] > 0 for e in earners)


def test_money_stripe_for_zero_days_is_today_only(ledger_day):
    j = ledger_day.client.get("/api/money/stripe?days=0", headers=KEY).json()
    assert (j["total"], j["count"]) == (49.0, 1)
    assert [p["event_id"] for p in j["payments"]] == ["txn_nov3"]


# ─── the MRR card, from Stripe's active subscriptions ───────────────────────

def test_mrr_sums_every_active_subscription_in_cents(world):
    world.stripe.subscriptions = [
        bf.subscription("sub_1", (2900, "month")),                         # $29.00
        bf.subscription("sub_2", (29000, "year")),                         # $290 a year: $24.1666...
        bf.subscription("sub_3", (1000, "month", 2), (500, "month", 1, "usd", 3)),   # 2 seats; quarterly 5.00
        bf.subscription("sub_4", (4900, "month"), status="canceled")]
    world.stripe.page_size = 2                                             # three pages
    cents, count, problem = stripe_sync.mrr(bf.STRIPE_KEY)
    assert (cents, count, problem) == (7483, 3, None)        # 2900 + 2416.67 + 2000 + 166.67, rounded once
    paged = bf.subscription("sub_6", (1000, "month"))
    paged["items"]["has_more"] = True                                      # an item not in this read
    metered = bf.subscription("sub_7", (5, "month"))
    metered["items"]["data"][0]["price"]["recurring"]["usage_type"] = "metered"
    for odd, problem in ((paged, "a subscription has more items than one read returns"),
                         (metered, "a subscription has a price that is not a plain amount")):
        world.stripe.subscriptions.append(odd)
        assert stripe_sync.mrr(bf.STRIPE_KEY) == (None, 4, problem)        # never a smaller number
        world.stripe.subscriptions.remove(odd)
    world.stripe.subscriptions.append(bf.subscription("sub_5", (1000, "month", 1, "eur")))
    assert stripe_sync.mrr(bf.STRIPE_KEY) == (None, 4, "a subscription is priced in another currency than USD")
    from core.revenue import RevenueEngine
    live = RevenueEngine.get().live_mrr()
    assert live == {"configured": True, "mrr": None, "active_subscriptions": 4,
                    "error": "a subscription is priced in another currency than USD"}
    world.stripe.fail_next = [401]
    live = RevenueEngine.get().live_mrr()
    assert live["mrr"] is None and live["error"] == "StripeError" and bf.STRIPE_KEY not in json.dumps(live)


def test_mrr_counts_weekly_and_daily_prices_per_month(world):
    world.stripe.subscriptions = [bf.subscription("sub_w", (1200, "week")), bf.subscription("sub_d", (100, "day"))]
    assert stripe_sync.mrr(bf.STRIPE_KEY) == (8242, 2, None)       # 1200 x 52/12 + 100 x 365/12, rounded once


def test_a_test_mode_key_reads_no_mrr_and_is_not_configured(world, monkeypatch):
    for name in ("STRIPE_READ_KEY", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_" "FAKEtestmodekey123")
    called = []
    monkeypatch.setattr(stripe_sync, "mrr", lambda key: called.append(key) or (9900, 4, None))
    from core.revenue import RevenueEngine
    live = RevenueEngine.get().live_mrr()
    assert (live["configured"], live["mrr"], live["active_subscriptions"]) == (False, None, None)
    assert called == [] and money.stripe_configured() is False
    assert world.client.get("/api/revenue/summary", headers=KEY).json()["stripe_configured"] is False
