"""The daily numbers board has ONE login: production's owner check.

Every /api/board/* route is owner-only through core/api.py's api_key_middleware
and, by construction, verify_api_key and _board_owner_only (owner_request_ok,
which ignores the public tables) on every route of the router (the include in
core/api.py). The owner is the X-API-Key header (API_KEY) or an owner
wv_session cookie (core/operator_session_web.py), with the CSRF origin check on
a cookie-authenticated write; every refusal is a 401, production's convention.
The board's own Supabase sign-in, /board/login, its sessions and its page gate
are gone, and the page carries no key of any kind.

These replace tests/test_board_auth.py, which tested the board's own sign-in:
each protective property it held is checked here against production's check.
No network: the scoreboard snapshot and the syncs are stubbed.
"""
import dataclasses
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

try:
    from fastapi.routing import iter_route_contexts   # FastAPI keeps included routers nested
except ImportError:      # FastAPI 0.116 (requirements allow it): includes are flattened into app.routes
    iter_route_contexts = list

from core.board import routes as board_routes
from tests import board_fakes as bf

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "admin" / "scoreboard.html"
SNAPSHOT = {"headline": "MRR — · users — · places scanned — · — prod deployments", "metrics": {},
            "surfaces": {}, "connected_count": 0, "total_surfaces": 0, "generated_at": "2026-11-04T12:00:00Z"}
GET_URL = "/api/board/scoreboard"
POST_URL = "/api/board/sync/stripe"
KEY = {"X-API-Key": bf.API_KEY}


@pytest.fixture
def board(monkeypatch):
    """core.api with API_KEY set (bf.client), the scoreboard snapshot and the
    Stripe sync stubbed: (client, sync runs)."""
    runs = []
    monkeypatch.setattr("core.scoreboard.snapshot", lambda: SNAPSHOT)

    def run(trigger="schedule", days=None, now=None):
        runs.append((trigger, days))
        return {"id": "run-1", "source_id": "stripe", "trigger_kind": trigger, "status": "ok", "error": None}

    monkeypatch.setattr(board_routes.stripe_sync, "run", run)
    monkeypatch.setattr(board_routes, "_last_sync", {})
    client = bf.client(monkeypatch)

    def post(headers):
        board_routes._last_sync.clear()              # the one-a-minute limit is not under test here
        return client.post(POST_URL, headers=headers)

    client.post_sync = post
    return client, runs


def _board_routes():
    import core.api as api
    found = []
    for ctx in iter_route_contexts(api.app.routes):
        path = ctx.path or ""
        if path.startswith("/api/board/") or path == "/api/board":
            found.append(ctx)
    return found


# ─── by construction ────────────────────────────────────────────────────────

def test_every_board_route_carries_verify_api_key_and_refuses_anonymous_calls(board):
    import core.api as api
    client, runs = board
    found = _board_routes()
    assert sorted((ctx.path, tuple(sorted(ctx.methods))) for ctx in found) == [
        ("/api/board/day", ("GET",)), ("/api/board/opportunities", ("GET",)),
        ("/api/board/scoreboard", ("GET",)), ("/api/board/sync/{source}", ("POST",))]
    for ctx in found:
        assert api.verify_api_key in [d.call for d in ctx.dependant.dependencies], ctx.path
        url = ctx.path.replace("{source}", "stripe")
        for method in ctx.methods:
            r = client.request(method, url, headers=bf.SAME_ORIGIN)
            assert r.status_code == 401, (method, url)
            assert r.json() == {"error": "Unauthorized", "hint": "Set X-API-Key header"}
    assert runs == []


def test_the_board_adds_no_public_path():
    import core.api as api
    for ctx in _board_routes():
        url = ctx.path.replace("{source}", "stripe")
        assert url not in api._PUBLIC_PATHS
        for method in ctx.methods:
            assert api._public_rule_for(url, method) is None, (method, url)
    assert len(api.PUBLIC_API_RULES) == 12 and len(api._PUBLIC_PATHS) == 94    # production's pinned counts


def test_with_the_middleware_taken_away_verify_api_key_alone_still_gates_the_board(board, monkeypatch):
    """Defence in depth: core.api's app without api_key_middleware (as a
    refactor of the middleware could leave it) still refuses every board call
    that is not the owner's, through verify_api_key on each route. The board's
    other dependency (_board_owner_only) is made to let every call through here,
    so this checks verify_api_key on its own, a wrong key included;
    test_a_board_path_made_public_in_the_tables_still_needs_the_owner checks
    _board_owner_only on its own."""
    import core.api as api
    client, runs = board
    kept = [m for m in api.app.user_middleware if m.kwargs.get("dispatch") is not api.api_key_middleware]
    assert len(kept) == len(api.app.user_middleware) - 1
    monkeypatch.setattr(api.app, "user_middleware", kept)
    monkeypatch.setattr(api.app, "middleware_stack", None)          # rebuilt, without it, on the next call
    monkeypatch.setattr(api, "owner_request_ok", lambda request: True)    # _board_owner_only passes all
    r = client.get(GET_URL)
    assert (r.status_code, r.json()) == (401, {"detail": "Invalid or missing API key"})
    r = client.get(GET_URL, headers={"X-API-Key": "wrong-key"})
    assert (r.status_code, r.json()) == (401, {"detail": "Invalid or missing API key"})
    for headers in (bf.SAME_ORIGIN, {"X-API-Key": "wrong-key"},
                    {**bf.owner_headers(), "Origin": "https://evil.example"},
                    {**bf.owner_headers("operator"), **bf.SAME_ORIGIN}):
        assert client.post_sync(headers).status_code == 401
    assert client.get(f"{GET_URL}?api_key={bf.API_KEY}").status_code == 401
    assert runs == []
    assert client.get(GET_URL, headers=KEY).status_code == 200
    assert client.get(GET_URL, headers=bf.owner_headers()).status_code == 200
    assert client.post_sync({**bf.owner_headers(), **bf.SAME_ORIGIN}).status_code == 200
    assert runs == [("owner", None)]


def test_a_board_path_made_public_in_the_tables_still_needs_the_owner(board, monkeypatch):
    """The include's second dependency, core.api._board_owner_only, asks
    owner_request_ok, which never reads the public tables. So if a change to
    _PUBLIC_PATHS or PUBLIC_API_RULES made the board's paths public, which opens
    both api_key_middleware and verify_api_key, every board route would still
    answer 401 to anyone but the owner, and the owner would still get in."""
    import core.api as api
    client, runs = board
    monkeypatch.setattr(board_routes.board_day, "day_view", lambda d=None: {"day": "stub"})   # never reached
    monkeypatch.setattr("core.opportunities.scan", lambda limit=8: {"opportunities": []})    # never reached
    found = _board_routes()
    urls = {ctx.path.replace("{source}", "stripe") for ctx in found}
    monkeypatch.setattr(api, "_PUBLIC_PATHS", set(api._PUBLIC_PATHS) | urls)
    rule = api.PublicRule("/api/board", frozenset({"GET", "POST"}), True, "made public by this test, on purpose")
    monkeypatch.setattr(api, "PUBLIC_API_RULES", api.PUBLIC_API_RULES + (rule,))
    for ctx in found:
        url = ctx.path.replace("{source}", "stripe")
        for method in ctx.methods:
            assert url in api._PUBLIC_PATHS and api._public_rule_for(url, method) is rule   # public now
            for headers in (bf.SAME_ORIGIN, {"X-API-Key": "wrong-key", **bf.SAME_ORIGIN},
                            {**bf.owner_headers("operator"), **bf.SAME_ORIGIN}):
                r = client.request(method, url, headers=headers)
                assert (r.status_code, r.json()) == (401, {"detail": "Invalid or missing API key"}), (method, url)
    assert client.post_sync({**bf.owner_headers(), "Origin": "https://evil.example"}).status_code == 401
    assert runs == []
    assert client.get(GET_URL, headers=KEY).status_code == 200
    assert client.get(GET_URL, headers=bf.owner_headers()).status_code == 200
    assert client.post_sync({**bf.owner_headers(), **bf.SAME_ORIGIN}).status_code == 200
    assert runs == [("owner", None)]
    for ctx in found:                                                    # on every route, by construction
        assert api._board_owner_only in [d.call for d in ctx.dependant.dependencies], ctx.path


def test_the_boards_own_sign_in_is_gone(board):
    client, runs = board
    import core.api as api
    assert importlib.util.find_spec("core.board.auth") is None
    assert not (ROOT / "frontend" / "admin" / "board_login.html").exists()
    assert "AdminPageGate" not in {getattr(m.cls, "__name__", "") for m in api.app.user_middleware}
    assert client.get("/board/login").status_code == 404
    for path in ("/board/auth/login", "/board/auth/logout"):
        assert client.post(path, headers=bf.SAME_ORIGIN).status_code in (404, 405)


# ─── who gets in ────────────────────────────────────────────────────────────

def test_no_credentials_get_401(board):
    client, runs = board
    assert client.get(GET_URL).status_code == 401
    assert client.post_sync(bf.SAME_ORIGIN).status_code == 401
    assert client.post_sync({}).status_code == 401
    assert runs == []


def test_the_owner_key_gets_in_and_needs_no_origin(board):
    client, runs = board
    r = client.get(GET_URL, headers=KEY)
    assert r.status_code == 200 and r.json()["headline"] == SNAPSHOT["headline"]
    for headers in (KEY, {**KEY, "Origin": "https://evil.example"}):              # the machine path
        assert client.post_sync(headers).status_code == 200
    assert runs == [("owner", None), ("owner", None)]


def test_the_owner_session_cookie_gets_in(board):
    client, runs = board
    r = client.get(GET_URL, headers=bf.owner_headers())
    assert r.status_code == 200 and r.json()["headline"] == SNAPSHOT["headline"]
    assert client.get(GET_URL, headers={**bf.owner_headers(), "Origin": "https://evil.example"}
                      ).status_code == 200                                         # reads are not origin-checked
    assert client.post_sync({**bf.owner_headers(), **bf.SAME_ORIGIN}).status_code == 200
    assert client.post_sync({**bf.owner_headers(), "Referer": "http://testserver/admin/scoreboard"}
                            ).status_code == 200                                   # no Origin: the Referer decides
    assert runs == [("owner", None), ("owner", None)]


@pytest.mark.parametrize("role", ["operator", "viewer", "release_verifier"])
def test_a_session_that_is_not_the_owners_gets_401(board, role):
    client, runs = board
    assert client.get(GET_URL, headers=bf.owner_headers(role)).status_code == 401
    assert client.post_sync({**bf.owner_headers(role), **bf.SAME_ORIGIN}).status_code == 401
    assert runs == []


def test_an_expired_or_forged_cookie_a_wrong_key_and_a_query_key_get_401(board):
    client, runs = board
    for headers in (bf.owner_headers(ttl_seconds=-60), {"Cookie": "wv_session=not-a-token"},
                    {"X-API-Key": "wrong-key"}):
        assert client.get(GET_URL, headers=headers).status_code == 401, headers
    assert client.get(f"{GET_URL}?api_key={bf.API_KEY}").status_code == 401        # a key in the URL is no key
    assert client.get(GET_URL, headers={"X-API-Key": "wrong-key", **bf.owner_headers()}).status_code == 200
    assert runs == []


@pytest.mark.parametrize("provenance", [
    {"Origin": "https://evil.example"}, {"Origin": "null"}, {}, {"Origin": "https://testserver.evil.example"},
    {"Referer": "https://evil.example/admin/scoreboard"}])
def test_a_cookie_post_without_a_trusted_origin_gets_401(board, provenance):
    client, runs = board
    assert client.post_sync({**bf.owner_headers(), **provenance}).status_code == 401
    assert runs == []


def test_behind_the_tls_proxy_only_the_https_origin_gets_through(board):
    client, runs = board
    proxied = {**bf.owner_headers(), "X-Forwarded-Proto": "https"}
    assert client.post_sync({**proxied, "Origin": "http://testserver"}).status_code == 401
    assert client.post_sync({**proxied, "Origin": "https://testserver"}).status_code == 200
    assert runs == [("owner", None)]


def test_a_trusted_origin_from_the_allowlist_gets_through(board, monkeypatch):
    import core.api as api
    client, runs = board
    monkeypatch.setattr(api, "_CSRF_TRUSTED_ORIGINS", frozenset({"https://app.wheellsverse.com"}))
    assert client.post_sync({**bf.owner_headers(), "Origin": "https://app.wheellsverse.com"}).status_code == 200
    assert client.post_sync({**bf.owner_headers(), "Origin": "https://kai.wheellsverse.com"}).status_code == 401
    assert runs == [("owner", None)]


def test_while_the_operator_session_is_off_only_the_owner_key_works(board, monkeypatch):
    """OPERATOR_SESSION_ENABLED off: the cookie is never consulted, so the
    owner's cookie gets 401 for a read and a same-origin write alike, and the
    key keeps working (scripts that send X-API-Key are unaffected)."""
    import core.api as api
    client, runs = board
    monkeypatch.setattr(api, "_OPERATOR_SESSION_CFG", dataclasses.replace(api._OPERATOR_SESSION_CFG, enabled=False))
    assert client.get(GET_URL, headers=bf.owner_headers()).status_code == 401
    assert client.post_sync({**bf.owner_headers(), **bf.SAME_ORIGIN}).status_code == 401
    assert runs == []
    assert client.get(GET_URL, headers=KEY).status_code == 200
    assert client.post_sync(KEY).status_code == 200
    assert client.get(f"{GET_URL}?api_key={bf.API_KEY}").status_code == 401
    assert runs == [("owner", None)]


def test_without_api_key_a_hosted_run_refuses_the_board_and_a_local_run_opens_it(board, monkeypatch):
    """Production's rule for every protected route (core.api.auth_config_state)."""
    import core.api as api
    client, runs = board
    monkeypatch.setattr(api, "_API_KEY", "")
    monkeypatch.setattr(api, "_APP_ENV", "production")
    for headers in ({}, {"X-API-Key": bf.API_KEY}, bf.owner_headers()):
        assert client.get(GET_URL, headers=headers).status_code == 401
    assert client.post_sync({**bf.owner_headers(), **bf.SAME_ORIGIN}).status_code == 401
    assert runs == []
    monkeypatch.setattr(api, "_APP_ENV", "test")                                   # a declared local run
    assert client.get(GET_URL).status_code == 200


def test_signing_in_with_the_owner_key_opens_the_board(board):
    """The real flow: POST /admin/session/login with the owner key answers the
    wv_session cookie, and the board accepts that cookie."""
    import core.api as api
    from core.operator_session_web import COOKIE_NAME
    client, runs = board
    r = client.post("/admin/session/login", json={"secret": api._OPERATOR_SESSION_CFG.owner_key})
    assert r.status_code == 200 and r.json()["role"] == "owner"
    token = r.cookies.get(COOKIE_NAME)
    assert token
    cookie = {"Cookie": f"{COOKIE_NAME}={token}"}
    assert client.get(GET_URL, headers=cookie).status_code == 200
    assert client.post_sync({**cookie, **bf.SAME_ORIGIN}).status_code == 200
    assert client.post("/admin/session/login", json={"secret": "not-the-key"}).status_code == 401


# ─── the page ───────────────────────────────────────────────────────────────

def _script() -> str:
    return re.search(r"<script>(.*?)</script>", PAGE.read_text(encoding="utf-8"), re.S).group(1)


def test_the_board_page_sends_no_key_stores_none_and_reads_none_from_the_url():
    page, script = PAGE.read_text(encoding="utf-8"), _script()
    assert "x-api-key" not in page.lower() and "%%API_KEY%%" not in page
    for piece in ("sessionStorage", "localStorage", "document.cookie", "?key=", "api_key", "prompt(",
                  "board/login", "board/auth"):
        assert piece not in script, piece
    assert script.count("credentials:'same-origin'") >= 5            # every board call carries the cookie


def test_the_board_page_carries_no_secret_for_any_identity(board, monkeypatch):
    """An open shell, as production serves every /admin page: the same bytes
    for anonymous, the owner key and the owner session, none of them a key."""
    import core.api as api
    client, runs = board
    pages = [client.get("/admin/scoreboard", headers=h) for h in ({}, KEY, bf.owner_headers())]
    assert {r.status_code for r in pages} == {200} and len({r.text for r in pages}) == 1
    for secret in (bf.API_KEY, api._OPERATOR_SESSION_CFG.owner_key, api._OPERATOR_SESSION_CFG.session_secret):
        assert secret and secret not in pages[0].text


_SIGNIN_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const [scriptPath, answersPath, typed] = process.argv.slice(2);
const answers = JSON.parse(fs.readFileSync(answersPath, 'utf8'));
const els = {}, calls = [];
const el = id => els[id] || (els[id] = {id, innerHTML: '', textContent: '', value: '', style: {}, on: {},
  addEventListener(type, f) { this.on[type] = f; }});
const page = {
  document: {getElementById: el}, location: {pathname: '/admin/scoreboard', search: '', href: ''},
  history: {replaceState() {}}, URLSearchParams, Intl, setTimeout() { return 0; },
  fetch: async (url, opts) => {
    const key = ((opts && opts.method) || 'GET') + ' ' + String(url).split('?')[0];
    calls.push({key, body: (opts && opts.body) || null, credentials: (opts && opts.credentials) || null,
                headers: (opts && opts.headers) || {}});
    const list = answers[key] || [{status: 404, body: {}}];
    const a = list.length > 1 ? list.shift() : list[0];
    return {status: a.status, ok: a.status >= 200 && a.status < 300, json: async () => a.body};
  },
};
vm.createContext(page);
vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), page);
const settle = async () => { for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r)); };
const state = () => ({signin: el('signin').style.display || '', msg: el('signin-msg').textContent,
                      field: el('owner-key').value, calls: calls.splice(0)});
(async () => {
  await settle();
  const before = state();
  el('owner-key').value = typed;
  await vm.runInContext('submitSignIn()', page);
  await settle();
  process.stdout.write(JSON.stringify({before, after: state()}));
})().catch(e => { console.error((e && e.stack) || e); process.exit(1); });
"""


def _sign_in(tmp_path, login, ui=(200, {"operator_session_enabled": True}), typed="typed-owner-key"):
    """Load the page with no session (the board answers 401 once, then 200),
    type `typed` in the owner key field and press Sign in; /admin/session/login
    answers `login` (status, JSON)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed, so the page's script cannot run")
    day = {"day": "2026-11-03", "label": "Tue 3 Nov", "numbers": {}, "sources": [], "sales": []}
    answers = {"GET /api/board/day": [{"status": 401, "body": {"error": "Unauthorized"}}, {"status": 200, "body": day}],
               "GET /api/board/scoreboard": [{"status": 401, "body": {"error": "Unauthorized"}},
                                             {"status": 200, "body": SNAPSHOT}],
               "GET /api/board/opportunities": [{"status": 200, "body": {"opportunities": []}}],
               "GET /admin/ui-config": [{"status": ui[0], "body": ui[1]}],
               "POST /admin/session/login": [{"status": login[0], "body": login[1]}]}
    for name, text in (("page.js", _script()), ("answers.json", json.dumps(answers)), ("harness.js", _SIGNIN_HARNESS)):
        (tmp_path / name).write_text(text, encoding="utf-8")
    ran = subprocess.run([node, str(tmp_path / "harness.js"), str(tmp_path / "page.js"),
                          str(tmp_path / "answers.json"), typed], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    out = json.loads(ran.stdout)
    for call in out["before"]["calls"] + out["after"]["calls"]:
        assert not any(k.lower() == "x-api-key" for k in call["headers"]), call
    return out


def test_the_page_signs_the_owner_in_with_the_operator_session_and_keeps_no_key(tmp_path):
    out = _sign_in(tmp_path, (200, {"role": "owner", "scopes": ["read"]}))
    before, after = out["before"], out["after"]
    assert before["signin"] == "block" and before["msg"] == ""                # a 401: the sign-in shows
    assert [c["key"] for c in before["calls"]] == ["GET /api/board/day", "GET /api/board/scoreboard",
                                                   "GET /admin/ui-config"]
    login = after["calls"][0]
    assert login["key"] == "POST /admin/session/login" and login["credentials"] == "same-origin"
    assert json.loads(login["body"]) == {"secret": "typed-owner-key"}
    assert after["field"] == ""                                                 # cleared at once
    assert after["signin"] == "none"
    assert [c["key"] for c in after["calls"][1:]] == ["GET /api/board/day", "GET /api/board/scoreboard",
                                                      "GET /api/board/opportunities"]
    assert all(c["credentials"] == "same-origin" for c in after["calls"])


@pytest.mark.parametrize("login, shown", [
    ((401, {"error": "invalid_credentials"}), "That key was not accepted."),
    ((404, {"detail": "Not Found"}), "Owner sign-in is not available on this deployment."),
    ((405, {"detail": "Method Not Allowed"}), "Owner sign-in is not available on this deployment."),
    ((503, {"error": "session_not_configured"}), "Sign-in unavailable (HTTP 503)."),
    ((200, {"role": "operator", "scopes": ["read"]}), "Signed in, but not as the owner: the board needs the owner key."),
])
def test_a_sign_in_that_does_not_make_the_owner_says_why_and_reloads_nothing(tmp_path, login, shown):
    after = _sign_in(tmp_path, login)["after"]
    assert (after["signin"], after["msg"], after["field"]) == ("block", shown, "")
    assert [c["key"] for c in after["calls"]] == ["POST /admin/session/login"]


def test_the_page_says_so_when_this_deployment_has_no_owner_sign_in(tmp_path):
    before = _sign_in(tmp_path, (404, {}), ui=(200, {"operator_session_enabled": False}))["before"]
    assert before["signin"] == "block"
    assert before["msg"] == "Owner sign-in is not available on this deployment."
