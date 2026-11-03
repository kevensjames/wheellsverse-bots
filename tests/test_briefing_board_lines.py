"""The NarAI morning briefing's revenue and KPI lines (narai/integrations/
briefing.py), read from the daily numbers board by New York day: the board's
own revenue line (core.board.day.summary_line) and /go clicks counted in SQL
(core.click_tracker.clicks_on). A number the board cannot read is "not
connected" or "—", never 0, and every value is escaped for Telegram.

Runs on tests/board_fakes.py's FakeBoardDB and FakeStripe: no network.
(narai/tests/test_briefing.py covers the same sections with patched sources,
but cannot be collected where feedparser is missing.)"""
from datetime import date, datetime, timedelta, timezone

import pytest

import core.click_tracker as ct
from core.board.connectors import stripe_sync
from narai.integrations import briefing
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York


@pytest.fixture(autouse=True)
def no_connector_settings(monkeypatch):
    bf.clear_connectors(monkeypatch)
    monkeypatch.setattr("core.telegram.notify_click", lambda **kwargs: True)
    ct.reset_limits()


@pytest.fixture
def db(monkeypatch):
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    monkeypatch.setattr(ct, "_clock", lambda: NOW)
    return db


@pytest.fixture
def board(db, monkeypatch):
    """The plan's fixture day: Stripe synced, and Kit, Instantly and Meta loaded."""
    stripe = bf.install_stripe(monkeypatch)
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db)
    return db


def click_at(iso: str, key: str = "coinbase") -> None:
    click = ct.new_click(key)
    assert ct.save_click(ct.Click(**{**click.__dict__, "clicked_at": bf._ts(iso)}))


def test_the_revenue_line_is_the_boards_line_for_yesterday(board):
    assert briefing._revenue_section(NOW) == "💰 Revenue: $10.00 net · attributed $29.99 (meta) · fees $3.17"


def test_the_kpi_line_counts_new_york_days(board):
    click_at("2026-11-02T04:30:00Z")             # 23:30 on Sun 1 Nov in New York: yesterday's
    click_at("2026-11-01T12:00:00Z")
    click_at("2026-10-31T15:00:00Z")             # the day before
    click_at("2026-11-02T05:00:00Z")             # 00:00 on 2 Nov: today's, not counted
    # 1 Nov nets $10.00; 31 Oct is the $19.99 sale whose refund came on 1 Nov
    assert briefing._kpi_section(NOW) == (
        "✅ KPIs (yesterday, New York): 2 clicks ▲ (prev 1) · $10.00 net revenue ▼ (prev $19.99)")


def test_the_day_before_is_its_own_new_york_day(board):
    # 31 Oct in New York: the 31 Oct sale ($19.99) only; its refund is on 1 Nov
    out = briefing._kpi_section(NOW)
    assert out == "✅ KPIs (yesterday, New York): 0 clicks → (prev 0) · $10.00 net revenue ▼ (prev $19.99)"


def _only_board_sections(monkeypatch):
    """The briefing's other sections stubbed: no vendor is called."""
    for name in ("_trading_section", "_inbox_section", "_subscribers_section", "_crypto_section"):
        monkeypatch.setattr(briefing, name, lambda: "—")
    monkeypatch.setattr(briefing, "_calendar_section", lambda now: "—")


def test_the_database_down_reads_not_connected_and_dashes_never_zero(db, monkeypatch):
    db.down = True
    assert briefing._revenue_section(NOW) == "💰 Revenue: not connected (database not connected)"
    out = briefing._kpi_section(NOW)
    assert out == "✅ KPIs (yesterday, New York): — clicks (prev —) · — net revenue (prev —)"
    _only_board_sections(monkeypatch)
    text = briefing.assemble_briefing(NOW)
    assert "💰 Revenue: not connected (database not connected)" in text and out in text
    assert "$0" not in text and "0 clicks" not in text


def test_a_note_with_markup_is_escaped(board):
    board.set_source("stripe", last_error="<b>boom</b> & <a href=x>", last_error_at="2026-11-02T11:00:00Z",
                     synced_through="2026-10-31T12:00:00Z")                    # 1 Nov not read yet
    out = briefing._revenue_section(NOW)
    assert out == ("💰 Revenue: no number yet (not synced into this day yet: synced to 08:00 on Sat 31 Oct "
                   "(New York) · last sync failed: &lt;b&gt;boom&lt;/b&gt; &amp; &lt;a href=x&gt;)")


def test_stripe_not_connected_is_not_zero(db, monkeypatch):
    out = briefing._revenue_section(NOW)
    assert out.startswith("💰 Revenue: not connected (Stripe key not set") and "$0" not in out


def test_the_briefing_passes_now_to_both_sections_never_now_minus_a_day(board, monkeypatch):
    seen = []
    monkeypatch.setattr(briefing, "_revenue_section", lambda now: seen.append(("revenue", now)) or "💰 x")
    monkeypatch.setattr(briefing, "_kpi_section", lambda now: seen.append(("kpi", now)) or "✅ x")
    _only_board_sections(monkeypatch)
    briefing.assemble_briefing(NOW)
    assert seen == [("revenue", NOW), ("kpi", NOW)]


def test_a_23_hour_day_is_still_the_right_new_york_day(db, monkeypatch):
    """00:30 on Mon 15 Mar 2027 in New York (EDT since the 14th): yesterday is
    Sun 14 Mar, the 23-hour day. 'Now minus 24 hours' would have landed on
    Sat 13 Mar."""
    now = datetime(2027, 3, 15, 4, 30, tzinfo=timezone.utc)
    calls = []
    monkeypatch.setattr("core.board.day.day_view", lambda day=None: calls.append(day) or
                        {"numbers": {"revenue": {"value": None, "connected": False, "note": "x"}}})
    briefing._revenue_section(now)
    assert calls == [date(2027, 3, 14)]
    assert (now - timedelta(hours=24)).astimezone(bf.NY).date() == date(2027, 3, 13)


def test_late_in_the_evening_both_lines_read_new_york_days(monkeypatch):
    """23:30 on Sun 1 Nov in New York is 04:30 on 2 Nov in UTC: yesterday is
    31 Oct, never the UTC date minus a day (1 Nov)."""
    now = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)
    views, clicks = [], []
    view = {"numbers": {"revenue": {"value": None, "connected": False, "note": "x"}}}
    monkeypatch.setattr("core.board.day.day_view", lambda day=None: views.append(day) or view)
    monkeypatch.setattr("core.click_tracker.clicks_on", lambda day: clicks.append(day) or 0)
    briefing._revenue_section(now)
    briefing._kpi_section(now)
    assert views == [date(2026, 10, 31), date(2026, 10, 31), date(2026, 10, 30)]
    assert clicks == [date(2026, 10, 31), date(2026, 10, 30)]


def test_a_partial_day_reads_so_far_and_gets_no_arrow(board):
    """The Stripe sync stopped at 15:00 on 1 Nov: yesterday is partial, and a
    day still being read is no drop against a full one."""
    board.set_source("stripe", synced_through="2026-11-01T20:00:00Z")      # 15:00 on Sun 1 Nov in New York
    assert briefing._revenue_section(NOW).endswith(" (partial)")
    assert briefing._kpi_section(NOW) == (
        "✅ KPIs (yesterday, New York): 0 clicks → (prev 0) · $10.00 net revenue so far (prev $19.99)")


def test_a_partial_day_before_gives_no_arrow_either(monkeypatch):
    views = {date(2026, 11, 1): {"value": 6000, "state": "final"}, date(2026, 10, 31): {"value": 1000, "state": "partial"}}
    monkeypatch.setattr("core.board.day.day_view", lambda day=None: {"numbers": {"revenue": views[day]}})
    monkeypatch.setattr("core.click_tracker.clicks_on", lambda day: 1)
    assert briefing._kpi_section(NOW).endswith("· $60.00 net revenue (prev $10.00)")
    views[date(2026, 10, 31)]["state"] = "final"
    assert briefing._kpi_section(NOW).endswith("· $60.00 net revenue ▲ (prev $10.00)")


# ─── the briefing routes: the owner's only, built off the event loop ────────

def _briefing_app(monkeypatch, build):
    """The NarAI briefing router on an app of its own, with the briefing
    builders replaced: no section calls a vendor."""
    from fastapi import FastAPI
    import narai.api.routes.briefing as routes
    monkeypatch.setattr(routes, "assemble_briefing", build)
    monkeypatch.setattr(routes, "assemble_briefing_markdown", build)
    app = FastAPI()
    app.include_router(routes.rt, prefix="/api/v2/narai")
    return app


def _token(user_id: str) -> dict:
    from narai.api.auth import create_token
    return {"Authorization": f"Bearer {create_token(user_id)}"}


@pytest.mark.parametrize("path", ["/briefing/preview", "/briefing/markdown", "/briefing/now", "/briefing/test"])
def test_another_users_token_cannot_read_or_fire_the_briefing(monkeypatch, path):
    """The briefing holds the board's numbers, which are the owner's: any
    other NarAI user's token gets 403, and nothing is built or sent."""
    import uuid
    from fastapi.testclient import TestClient
    import narai.api.routes.briefing as routes
    import narai.integrations.scheduler as scheduler
    monkeypatch.setenv("BOARD_OWNER_USER_ID", bf.OWNER_ID)
    built, sent = [], []

    def build(now=None):
        built.append(1)
        return "💰 Revenue: $5.00 net · attributed $0.00 · fees $0.45"

    async def fire():
        sent.append("cron")

    async def deliver(text):
        sent.append(text)
        return True

    monkeypatch.setattr(scheduler, "_fire_briefing", fire)
    monkeypatch.setattr(routes, "deliver_via_telegram", deliver)
    client = TestClient(_briefing_app(monkeypatch, build))
    r = client.post(f"/api/v2/narai{path}", headers=_token(str(uuid.uuid4())))
    assert r.status_code == 403 and "Revenue" not in r.text and built == [] and sent == []
    assert client.post(f"/api/v2/narai{path}").status_code in (401, 403)          # no token at all
    assert client.post(f"/api/v2/narai{path}", headers=_token(bf.OWNER_ID.upper())).status_code == 200
    monkeypatch.delenv("BOARD_OWNER_USER_ID")
    assert client.post(f"/api/v2/narai{path}", headers=_token(bf.OWNER_ID)).status_code == 503   # fails closed


@pytest.mark.parametrize("path", ["/briefing/preview", "/briefing/markdown", "/briefing/now"])
def test_the_briefing_routes_build_the_briefing_off_the_event_loop(monkeypatch, path):
    """Its sections read the board's database and call Google, Telegram and
    Discord over blocking HTTP: built on the event loop, they would hold every
    other request (a /go redirect, the Stripe webhook) while they wait."""
    import asyncio
    from fastapi.testclient import TestClient
    import narai.api.routes.briefing as routes
    monkeypatch.setenv("BOARD_OWNER_USER_ID", bf.OWNER_ID)
    where = []

    def build(now=None):
        try:
            asyncio.get_running_loop()
            where.append("event loop")
        except RuntimeError:
            where.append("worker thread")
        return "briefing"

    async def deliver(text):
        return False

    monkeypatch.setattr(routes, "deliver_via_telegram", deliver)
    client = TestClient(_briefing_app(monkeypatch, build))
    r = client.post(f"/api/v2/narai{path}", headers=_token(bf.OWNER_ID))
    assert r.status_code == 200 and r.json()["text"] == "briefing"
    assert where == ["worker thread"]


# ─── the /briefing page's script, run in Node ───────────────────────────────

# A stub DOM (each element's textContent, innerHTML and classes), a token in
# localStorage and fetch answering from a table ("METHOD /path" -> status and
# JSON; a null body is not JSON, as a proxy's HTML error page). The page loads
# the briefing, then "Send to Telegram" is pressed; prints what #meta showed.
_PAGE_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const [scriptPath, answersPath] = process.argv.slice(2);
const answers = JSON.parse(fs.readFileSync(answersPath, 'utf8'));
const els = {}, calls = [];
const el = id => els[id] || (els[id] = (() => {
  const classes = new Set();
  return {id, innerHTML: '', textContent: '', classes,
          classList: {add: c => classes.add(c), remove: c => classes.delete(c)}};
})());
const page = {
  document: {getElementById: el},
  localStorage: {getItem: () => 'a-narai-token', removeItem() {}},
  fetch: async (url, opts) => {
    const key = ((opts && opts.method) || 'GET') + ' ' + url;
    calls.push(key);
    const a = answers[key];
    if (!a) throw new TypeError('no answer for ' + key);
    return {status: a.status, ok: a.status >= 200 && a.status < 300, json: async () => {
      if (a.body === null) throw new SyntaxError('Unexpected token < in JSON');
      return a.body;
    }};
  },
};
vm.createContext(page);
vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), page);
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };
(async () => {
  await settle();
  await vm.runInContext('fire()', page);
  const m = els.meta;
  process.stdout.write(JSON.stringify({calls, text: m.textContent, html: m.innerHTML, error: m.classes.has('err')}));
})().catch(e => { console.error((e && e.stack) || e); process.exit(1); });
"""


def _page_script() -> str:
    import re
    from narai.api.routes.briefing import _PAGE_HTML
    return re.search(r"<script>(.*?)</script>", _PAGE_HTML, re.S).group(1)


def _fire(tmp_path, status: int, body) -> dict:
    """Press the page's "Send to Telegram" when /briefing/test answers `status` and `body`."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed, so the page's script cannot run")
    answers = {"POST /api/v2/narai/briefing/markdown": {"status": 200, "body": {"text": "📋 the briefing"}},
               "POST /api/v2/narai/briefing/test": {"status": status, "body": body}}
    for name, text in (("page.js", _page_script()), ("answers.json", json.dumps(answers)),
                       ("harness.js", _PAGE_HARNESS)):
        (tmp_path / name).write_text(text, encoding="utf-8")
    ran = subprocess.run([node, str(tmp_path / "harness.js"), str(tmp_path / "page.js"),
                          str(tmp_path / "answers.json")], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    out = json.loads(ran.stdout)
    assert out["calls"] == ["POST /api/v2/narai/briefing/markdown", "POST /api/v2/narai/briefing/test"]
    return out


def test_the_briefing_page_says_not_sent_in_the_servers_words_when_the_route_refuses(tmp_path, monkeypatch):
    """The routes' own answers: another user's token (403), the owner's while
    BOARD_OWNER_USER_ID is unset (503), and a token that is not valid (401).
    Nothing was fired, so the page never says 'Fired … ok'."""
    import uuid
    from fastapi.testclient import TestClient
    import narai.integrations.scheduler as scheduler

    async def fire():
        raise AssertionError("the briefing was fired")

    monkeypatch.setattr(scheduler, "_fire_briefing", fire)
    client = TestClient(_briefing_app(monkeypatch, lambda now=None: "briefing"))
    monkeypatch.setenv("BOARD_OWNER_USER_ID", bf.OWNER_ID)
    refusals = [client.post("/api/v2/narai/briefing/test", headers=_token(str(uuid.uuid4()))),
                client.post("/api/v2/narai/briefing/test", headers={"Authorization": "Bearer not-a-token"})]
    monkeypatch.delenv("BOARD_OWNER_USER_ID")
    refusals.append(client.post("/api/v2/narai/briefing/test", headers=_token(bf.OWNER_ID)))
    assert [r.status_code for r in refusals] == [403, 401, 503]
    shown = [_fire(tmp_path, r.status_code, r.json()) for r in refusals]
    assert [(out["text"], out["error"]) for out in shown] == [
        ("Not sent: The briefing is the owner's only", True), ("Not sent: Invalid or expired token", True),
        ("Not sent: The briefing is not configured", True)]


@pytest.mark.parametrize("status, body, shown", [
    (502, None, "Not sent: HTTP 502"),                                        # a proxy's HTML page
    (500, {"error": "Telegram <b>refused</b> & more"}, "Not sent: Telegram <b>refused</b> & more"),
    (429, {"detail": [{"msg": "a list, not text"}]}, "Not sent: HTTP 429"),
])
def test_the_briefing_page_shows_a_refusal_as_text(tmp_path, status, body, shown):
    out = _fire(tmp_path, status, body)
    assert (out["text"], out["error"], out["html"]) == (shown, True, "")      # textContent, never HTML
    assert "innerHTML" not in _page_script()


def test_the_briefing_page_says_fired_when_the_route_fired(tmp_path):
    import re
    out = _fire(tmp_path, 200, {"status": "fired", "note": "check logs + Telegram for delivery confirmation"})
    assert re.fullmatch(r"Fired at .+ — check logs \+ Telegram for delivery confirmation", out["text"])
    assert out["error"] is False
