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


# ─── the briefing routes: a NarAI token, and the board's lines for the owner ─
#
# Every POST needs a NarAI token (require_auth, production's direct dependency).
# The board's two lines, the revenue line and the KPI line, go in only when the
# request also passes the app's one owner check: the X-API-Key header or an
# owner wv_session cookie, as core.api decides it (owner_request_ok). Without it
# the briefing is the same, without those lines, and the board is not read.

USER = "5d1f0c3e-2b7a-4e9c-8f10-3a4b5c6d7e8f"      # any NarAI user
POSTS = ["/briefing/preview", "/briefing/markdown", "/briefing/now", "/briefing/test"]
REVENUE = "💰 Revenue: $5.00 net · attributed $0.00 · fees $0.45"
KPIS = "✅ KPIs (yesterday, New York): 3 clicks ▲ (prev 1) · $5.00 net revenue ▲ (prev $1.00)"


def test_board_false_leaves_out_both_board_lines_and_reads_nothing_of_the_board(monkeypatch):
    """assemble_briefing(board=False): the same briefing without the revenue
    line and the KPI line, and neither section runs."""
    seen = []
    monkeypatch.setattr(briefing, "_revenue_section", lambda now: seen.append("revenue") or REVENUE)
    monkeypatch.setattr(briefing, "_kpi_section", lambda now: seen.append("kpi") or KPIS)
    _only_board_sections(monkeypatch)
    without = briefing.assemble_briefing(NOW, board=False)
    assert seen == []
    full = briefing.assemble_briefing(NOW)                     # the default keeps them (the cron's)
    assert seen == ["revenue", "kpi"] and REVENUE in full and KPIS in full
    assert [line for line in full.split("\n") if line not in (REVENUE, KPIS)] == without.split("\n")
    md = briefing.assemble_briefing_markdown(NOW, board=False)
    assert REVENUE not in md and KPIS not in md and "<b>" not in md and "Good morning, J.K." in md
    assert seen == ["revenue", "kpi"]


def test_the_cron_keeps_the_boards_lines(monkeypatch):
    """The 07:00 cron goes to the owner's own chat, outside HTTP: APScheduler
    calls _fire_briefing() with no arguments, and the board's lines are in."""
    import asyncio
    import narai.integrations.scheduler as scheduler
    sent, logged = [], []
    _only_board_sections(monkeypatch)
    monkeypatch.setattr(briefing, "_revenue_section", lambda now: REVENUE)
    monkeypatch.setattr(briefing, "_kpi_section", lambda now: KPIS)

    async def deliver(text):
        sent.append(text)
        return True

    monkeypatch.setattr(scheduler, "deliver_via_telegram", deliver)
    monkeypatch.setattr(scheduler, "log_briefing_to_memory", logged.append)
    asyncio.run(scheduler._fire_briefing())
    assert len(sent) == 1 and REVENUE in sent[0] and KPIS in sent[0] and logged == sent


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


@pytest.fixture
def owner_key(monkeypatch):
    """core.api's owner key for this test (core.api reads API_KEY once, at import)."""
    monkeypatch.setattr("core.api._API_KEY", bf.API_KEY)
    return {"X-API-Key": bf.API_KEY}


@pytest.fixture
def briefing_app(monkeypatch):
    """The NarAI briefing router on an app of its own, running the real
    briefing with every section stubbed (no vendor is called) and every send
    recorded: (client, read, sent). `read` lists the board sections the
    briefing ran; `sent` every text that went to Telegram, from /briefing/now
    or from the cron's callback that /briefing/test fires."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import narai.api.routes.briefing as routes
    import narai.integrations.scheduler as scheduler
    read, sent = [], []
    _only_board_sections(monkeypatch)
    monkeypatch.setattr(briefing, "_revenue_section", lambda now: read.append("revenue") or REVENUE)
    monkeypatch.setattr(briefing, "_kpi_section", lambda now: read.append("kpi") or KPIS)

    async def deliver(text):
        sent.append(text)
        return True

    monkeypatch.setattr(routes, "deliver_via_telegram", deliver)
    monkeypatch.setattr(scheduler, "deliver_via_telegram", deliver)
    monkeypatch.setattr(scheduler, "log_briefing_to_memory", lambda text: None)
    app = FastAPI()
    app.include_router(routes.rt, prefix="/api/v2/narai")
    return TestClient(app), read, sent


def _briefing_text(path: str, r, sent: list) -> str:
    """The briefing a route produced: its answer's text (/briefing/now also
    sent that same text), or what the cron's callback sent (/briefing/test)."""
    if path == "/briefing/test":
        assert r.json()["status"] == "fired" and len(sent) == 1
        return sent[0]
    text = r.json()["text"]
    assert sent == ([text] if path == "/briefing/now" else [])
    return text


NOT_THE_OWNER = [{}, {"X-API-Key": "wrong-key"},
                 # a non-ASCII key (sent as raw bytes) makes hmac.compare_digest raise inside
                 # core.api.owner_request_ok: it must fail closed, not open
                 {"X-API-Key": b"\xff"},
                 {**bf.owner_headers("operator"), **bf.SAME_ORIGIN},
                 {**bf.owner_headers(ttl_seconds=-60), **bf.SAME_ORIGIN},          # expired
                 {"Cookie": "wv_session=not-a-token", **bf.SAME_ORIGIN},
                 {**bf.owner_headers(), "Origin": "https://evil.example"},          # the owner's cookie, another site
                 bf.owner_headers()]                                                # the owner's cookie, no Origin


@pytest.mark.parametrize("path", POSTS)
def test_a_narai_token_without_the_owner_gets_the_briefing_without_the_boards_lines(briefing_app, owner_key,
                                                                                     path):
    """Production's briefing for any NarAI token, as before; the board's
    numbers are the owner's, so without the owner check they are left out
    (sent ones included) and the board is not read."""
    client, read, sent = briefing_app
    url, token = f"/api/v2/narai{path}", _token(USER)
    for headers in NOT_THE_OWNER:
        sent.clear()
        r = client.post(url, headers={**token, **headers})
        assert r.status_code == 200, headers
        text = _briefing_text(path, r, sent)
        assert "Good morning, J.K." in text, headers
        assert "Revenue" not in text and "KPIs" not in text and "$" not in text, headers
    assert read == []


@pytest.mark.parametrize("path", POSTS)
def test_the_owner_key_or_the_owner_session_puts_the_boards_lines_in(briefing_app, owner_key, path):
    client, read, sent = briefing_app
    url, token = f"/api/v2/narai{path}", _token(USER)
    for headers in (owner_key, {**owner_key, "Origin": "https://evil.example"},     # the key: no Origin check
                    {**bf.owner_headers(), **bf.SAME_ORIGIN},
                    {**bf.owner_headers(), "Referer": "http://testserver/api/v2/narai/briefing"},
                    {"X-API-Key": "wrong-key", **bf.owner_headers(), **bf.SAME_ORIGIN}):
        sent.clear()
        read.clear()
        r = client.post(url, headers={**token, **headers})
        assert r.status_code == 200, headers
        text = _briefing_text(path, r, sent)
        assert REVENUE in text and KPIS in text, headers
        assert read == ["revenue", "kpi"], headers


@pytest.mark.parametrize("path", POSTS)
def test_without_a_narai_token_no_owner_credential_opens_a_briefing_route(briefing_app, owner_key, path):
    """The owner key and the owner session are not NarAI tokens: every POST
    stays refused by require_auth, and nothing is built or sent."""
    client, read, sent = briefing_app
    url = f"/api/v2/narai{path}"
    for headers in ({}, owner_key, {**bf.owner_headers(), **bf.SAME_ORIGIN}):
        assert client.post(url, headers=headers).status_code in (401, 403), headers      # HTTPBearer: no token
    r = client.post(url, headers={"Authorization": "Bearer not-a-token", **owner_key})
    assert (r.status_code, r.json()) == (401, {"detail": "Invalid or expired token"})
    assert read == [] and sent == []


def test_with_the_operator_session_off_only_the_owner_key_puts_the_boards_lines_in(briefing_app, owner_key,
                                                                                    monkeypatch):
    import dataclasses
    import core.api as api
    client, read, sent = briefing_app
    monkeypatch.setattr(api, "_OPERATOR_SESSION_CFG", dataclasses.replace(api._OPERATOR_SESSION_CFG, enabled=False))
    url, token = "/api/v2/narai/briefing/preview", _token(USER)
    r = client.post(url, headers={**token, **bf.owner_headers(), **bf.SAME_ORIGIN})
    assert r.status_code == 200 and "Revenue" not in r.json()["text"] and read == []
    r = client.post(url, headers={**token, **owner_key})
    assert r.status_code == 200 and REVENUE in r.json()["text"]


def test_without_api_key_a_hosted_run_leaves_the_boards_lines_out_and_a_local_run_puts_them_in(briefing_app,
                                                                                                monkeypatch):
    """The same rule as every owner /api route (core.api.auth_config_state):
    no API_KEY on a hosted run is no owner for anyone, and a declared local
    environment (APP_ENV=test here) is the owner's; a NarAI token is still
    required either way."""
    import core.api as api
    client, read, sent = briefing_app
    url, token = "/api/v2/narai/briefing/preview", _token(USER)
    monkeypatch.setattr(api, "_API_KEY", "")
    monkeypatch.setattr(api, "_APP_ENV", "production")
    for headers in ({}, {"X-API-Key": bf.API_KEY}, {**bf.owner_headers(), **bf.SAME_ORIGIN}):
        r = client.post(url, headers={**token, **headers})
        assert r.status_code == 200 and "Revenue" not in r.json()["text"], headers
    assert read == []
    monkeypatch.setattr(api, "_APP_ENV", "test")
    assert client.post(url).status_code in (401, 403)
    r = client.post(url, headers=token)
    assert r.status_code == 200 and REVENUE in r.json()["text"]


def test_an_owner_check_that_fails_leaves_the_boards_lines_out(briefing_app, owner_key, monkeypatch):
    def broken(request):
        raise RuntimeError("the owner check is broken")

    client, read, sent = briefing_app
    monkeypatch.setattr("core.api.owner_request_ok", broken)
    r = client.post("/api/v2/narai/briefing/preview", headers={**_token(USER), **owner_key})
    assert r.status_code == 200 and "Revenue" not in r.json()["text"] and read == []


def test_every_briefing_post_keeps_require_auth_as_a_direct_dependency():
    """Production's guard (tests/test_router_manifest_gate.py) reads each v2
    mutating route's direct dependencies, and in this FastAPI it cannot see
    included routes. So, by construction, on the router and on core.api's own
    route table (fastapi.routing.iter_route_contexts): require_auth stays the
    first direct dependency of each briefing POST, the owner check beside it."""
    from fastapi.routing import APIRoute
    try:
        from fastapi.routing import iter_route_contexts   # FastAPI keeps included routers nested
    except ImportError:  # FastAPI 0.116 (requirements allow it): includes are flattened into app.routes
        iter_route_contexts = list
    import core.api as api
    import narai.api.routes.briefing as routes
    from narai.api.auth import require_auth
    posts = [r for r in routes.rt.routes if isinstance(r, APIRoute) and "POST" in r.methods]
    assert sorted(r.path for r in posts) == sorted(POSTS)
    for r in posts:
        assert [d.call for d in r.dependant.dependencies][:2] == [require_auth, routes.owner_check], r.path
    mounted = {}
    for ctx in iter_route_contexts(api.app.routes):
        path = ctx.path or ""
        if path.startswith("/api/v2/narai/briefing/") and "POST" in (ctx.methods or ()):
            mounted[path] = [d.call for d in ctx.dependant.dependencies]
    assert sorted(mounted) == sorted(f"/api/v2/narai{p}" for p in POSTS)
    for path, calls in mounted.items():
        assert calls[:2] == [require_auth, routes.owner_check], path


@pytest.mark.parametrize("path", ["/briefing/preview", "/briefing/markdown", "/briefing/now"])
def test_the_briefing_routes_build_the_briefing_off_the_event_loop(monkeypatch, owner_key, path):
    """Its sections read the board's database and call Google, Telegram and
    Discord over blocking HTTP: built on the event loop, they would hold every
    other request (a /go redirect, the Stripe webhook) while they wait."""
    import asyncio
    from fastapi.testclient import TestClient
    import narai.api.routes.briefing as routes
    where = []

    def build(now=None, *, board=True):
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
    r = client.post(f"/api/v2/narai{path}", headers={**_token(USER), **owner_key})
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
const els = {}, calls = [], removed = [];
const el = id => els[id] || (els[id] = (() => {
  const classes = new Set();
  return {id, innerHTML: '', textContent: '', classes,
          classList: {add: c => classes.add(c), remove: c => classes.delete(c)}};
})());
const page = {
  document: {getElementById: el},
  localStorage: {getItem: () => 'a-narai-token', removeItem(k) { removed.push(k); }},
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
  const m = els.meta, c = el('content');
  process.stdout.write(JSON.stringify({calls, text: m.textContent, html: m.innerHTML, error: m.classes.has('err'),
                                       content: c.textContent, content_error: c.classes.has('err'), removed}));
})().catch(e => { console.error((e && e.stack) || e); process.exit(1); });
"""


def _page_script() -> str:
    import re
    from narai.api.routes.briefing import _PAGE_HTML
    return re.search(r"<script>(.*?)</script>", _PAGE_HTML, re.S).group(1)


def _fire(tmp_path, status: int, body, markdown=(200, {"text": "📋 the briefing"})) -> dict:
    """Press the page's "Send to Telegram" when /briefing/test answers `status`
    and `body`, after the page loaded /briefing/markdown's `markdown` answer."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed, so the page's script cannot run")
    answers = {"POST /api/v2/narai/briefing/markdown": {"status": markdown[0], "body": markdown[1]},
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


def test_the_briefing_page_says_not_sent_in_the_servers_words_when_the_route_refuses(tmp_path, monkeypatch,
                                                                                     owner_key):
    """The route's own refusals: a token that is not valid (401), the owner
    key notwithstanding, and no token at all. Nothing was fired, so the page
    never says 'Fired … ok'."""
    from fastapi.testclient import TestClient
    import narai.integrations.scheduler as scheduler

    async def fire(board=True):
        raise AssertionError("the briefing was fired")

    monkeypatch.setattr(scheduler, "_fire_briefing", fire)
    client = TestClient(_briefing_app(monkeypatch, lambda now=None, *, board=True: "briefing"))
    invalid = client.post("/api/v2/narai/briefing/test", headers={"Authorization": "Bearer not-a-token",
                                                                   **owner_key})
    none = client.post("/api/v2/narai/briefing/test", headers=owner_key)
    assert invalid.status_code == 401 and none.status_code in (401, 403)
    shown = [_fire(tmp_path, r.status_code, r.json()) for r in (invalid, none)]
    assert [(out["text"], out["error"]) for out in shown] == [
        ("Not sent: Invalid or expired token", True), ("Not sent: Not authenticated", True)]


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


def test_the_briefing_page_drops_the_narai_token_only_on_a_401(tmp_path):
    """A 401 from /briefing/markdown is an expired NarAI token: the page drops
    it and says so. Any other refusal shows its status and keeps the token."""
    out = _fire(tmp_path, 200, {"status": "fired"}, markdown=(503, {"detail": "unavailable"}))
    assert (out["content"], out["content_error"], out["removed"]) == ("Error: HTTP 503", True, [])
    expired = _fire(tmp_path, 200, {"status": "fired"}, markdown=(401, {"detail": "Invalid or expired token"}))
    assert expired["removed"] == ["narai_v2_token"] and expired["content"].startswith("Session expired")
