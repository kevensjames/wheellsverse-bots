"""Owner sign-in for the daily numbers board and every /admin page
(core/board/auth.py, core/board/routes.py). No network: Supabase Auth and
PostgREST are faked in tests/board_fakes.py."""
import hashlib
import importlib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.routing import WebSocketRoute

from core.board import auth
from tests import board_fakes as bf

ROOT = Path(__file__).resolve().parents[1]
SAME_ORIGIN = {"Origin": "http://testserver"}
OWNER = {"email": bf.OWNER_EMAIL, "password": bf.OWNER_PASSWORD}
WRONG = {"email": bf.OWNER_EMAIL, "password": "not the password"}
SNAPSHOT = {"headline": "test snapshot", "metrics": {}, "surfaces": {}}


@pytest.fixture
def fake(monkeypatch):
    return bf.install(monkeypatch)


@pytest.fixture
def client(monkeypatch, fake):
    # The data behind these routes comes from live services: keep the tests offline.
    monkeypatch.setattr("core.scoreboard.snapshot", lambda: dict(SNAPSHOT))
    monkeypatch.setattr("core.opportunities.scan", lambda limit=8: {"opportunities": [], "limit": limit})
    return bf.client(monkeypatch)


def _all_routes():
    """Every route the app serves, with router includes flattened."""
    from core.api import app
    try:
        from fastapi.routing import iter_route_contexts   # FastAPI keeps includes nested
    except ImportError:
        return list(app.routes)
    return list(iter_route_contexts(app.routes))


def _fill(path):
    return re.sub(r"\{[^}]+\}", "x", path)


def _admin_pages():
    return sorted({_fill(r.path) for r in _all_routes()
                   if (r.path or "").startswith("/admin") and "GET" in (r.methods or ())})


def _set_cookies(r):
    """The response's Set-Cookie headers by name: (value, {attribute: value or True})."""
    out = {}
    for header in r.headers.get_list("set-cookie"):
        first, *attrs = [part.strip() for part in header.split(";")]
        name, value = first.split("=", 1)
        out[name] = (value, {a.split("=", 1)[0].lower(): (a.split("=", 1)[1] if "=" in a else True)
                             for a in attrs})
    return out


def _sign_in(client, **data):
    """Sign in (the owner by default); returns {cookie name: value}."""
    r = client.post("/board/auth/login", data=data or OWNER, headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 303, r.text
    return {name: value for name, (value, _) in _set_cookies(r).items()}


def _login(client, data, ip, device=None):
    """One sign-in attempt from a client address, with a known-device cookie or not."""
    headers = {**SAME_ORIGIN, "CF-Connecting-IP": ip}
    if device:
        headers["Cookie"] = f"{auth.DEVICE_COOKIE}={device}"
    return client.post("/board/auth/login", data=data, headers=headers, follow_redirects=False)


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ── no session ──────────────────────────────────────────────────────────────

def test_without_a_session_every_admin_page_redirects_to_sign_in(client):
    pages = _admin_pages()
    assert {"/admin", "/admin/hub", "/admin/scoreboard", "/admin/siteboost", "/admin/portfolio/x",
            "/admin/leadgen", "/admin/shopify", "/admin/second-brain-inbox", "/admin/toodle"} <= set(pages)
    for path in pages:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302, path
        assert r.headers["location"] == "/board/login?next=" + quote(path, safe=""), path
        assert r.headers["cache-control"] == "no-store", path
        assert "content-security-policy" in r.headers, path   # still behind the security headers
    r = client.get("/admin/scoreboard?date=2026-11-01", follow_redirects=False)
    assert r.headers["location"] == "/board/login?next=%2Fadmin%2Fscoreboard%3Fdate%3D2026-11-01"
    assert client.get("/admin/no-such-page", follow_redirects=False).status_code == 302
    assert client.post("/admin/scoreboard").status_code == 401


def test_without_a_session_the_board_api_answers_401(client, fake):
    for path in ("/api/board/scoreboard", "/api/board/opportunities"):
        assert client.get(path).status_code == 401
        # the board API takes the owner session only, not the server key
        assert client.get(path, headers={"X-API-Key": bf.API_KEY}).status_code == 401
    assert fake.calls == []


def test_every_admin_route_and_board_api_route_is_gated(client):
    routes = _all_routes()
    admin = [r for r in routes if (r.path or "").startswith("/admin")]
    assert len(admin) >= 12
    for route in admin:
        assert not isinstance(route.original_route if hasattr(route, "original_route") else route,
                              WebSocketRoute), f"websocket route {route.path} is not covered by the gate"
        methods = sorted((route.methods or {"GET"}) - {"HEAD"})
        path = _fill(route.path) if route.methods else _fill(route.path) + "/x"   # a mount
        for method in methods:
            r = client.request(method, path, follow_redirects=False)
            assert r.status_code in (302, 401), (method, path, r.status_code)
            if r.status_code == 302:
                assert r.headers["location"].startswith("/board/login?next="), (method, path)

    board = [r for r in routes if (r.path or "").startswith("/api/board/")]
    assert {"/api/board/scoreboard", "/api/board/opportunities"} <= {r.path for r in board}
    for route in board:
        calls = [d.call for d in route.dependant.dependencies]
        assert auth.require_owner in calls, f"{route.path} lacks the require_owner dependency"
        for method in (route.methods or set()) - {"HEAD"}:
            assert client.request(method, _fill(route.path)).status_code == 401, (method, route.path)

    # no static mount can serve the admin pages around the gate
    admin_dir = (ROOT / "frontend" / "admin").resolve()
    for route in routes:
        directory = getattr(getattr(route, "app", None), "directory", None)
        if directory:
            served = Path(directory).resolve()
            assert served != admin_dir and served not in admin_dir.parents, f"{route.path} serves {served}"


# ── sign-in ─────────────────────────────────────────────────────────────────

def test_owner_sign_in_sets_the_session_cookie(client, fake):
    r = client.post("/board/auth/login", data={**OWNER, "next": "/admin/siteboost?tab=runs"},
                    headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/siteboost?tab=runs"
    cookies = _set_cookies(r)
    assert set(cookies) == {"__Host-board_session", "__Host-board_device"}
    token, flags = cookies["__Host-board_session"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)          # 32 random bytes
    assert flags.get("httponly") is True and flags.get("secure") is True
    assert str(flags.get("samesite")).lower() == "lax" and flags.get("path") == "/"
    assert flags.get("max-age") == str(7 * 86400)
    assert "domain" not in flags

    # the known-device cookie: a signed random id, kept a year, never sent cross-site
    device, flags = cookies["__Host-board_device"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}\.[0-9]+\.[0-9a-f]{64}", device)
    assert flags.get("httponly") is True and flags.get("secure") is True
    assert str(flags.get("samesite")).lower() == "strict" and flags.get("path") == "/"
    assert flags.get("max-age") == str(365 * 86400)
    assert "domain" not in flags
    assert auth.known_device(auth.board_settings(), device)
    assert bf.SERVICE not in device and bf.OWNER_ID not in device

    # only the token's SHA-256 is stored, for the owner, for 7 days
    assert list(fake.sessions) == [_digest(token)]
    row = fake.sessions[_digest(token)]
    assert row["user_id"] == bf.OWNER_ID and row["revoked_at"] is None
    left = datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)
    assert token not in repr(fake.sessions)

    # one stateless password grant with the anon key; the session row with the service key
    grants = fake.calls_to("/auth/v1/token")
    assert len(grants) == 1 and grants[0].method == "POST"
    assert grants[0].url.params["grant_type"] == "password"
    assert grants[0].headers["apikey"] == bf.ANON and bf.SERVICE not in str(grants[0].headers)
    inserts = fake.calls_to("/rest/v1/owner_sessions", "POST")
    assert len(inserts) == 1 and inserts[0].headers["apikey"] == bf.SERVICE

    assert client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False).status_code == 200
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).json() == SNAPSHOT
    assert client.get("/api/board/opportunities?limit=3", headers=bf.cookie(token)).json()["limit"] == 3


@pytest.mark.parametrize("next_value", ["https://evil.example/", "//evil.example/x", "/\\evil.example",
                                        "javascript:alert(1)", "admin/scoreboard", "/admin\r\nX-A: b", ""])
def test_sign_in_returns_only_to_a_page_on_this_site(client, next_value):
    r = client.post("/board/auth/login", data={**OWNER, "next": next_value},
                    headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/scoreboard"


def test_a_user_who_is_not_the_owner_gets_403(client, fake):
    r = client.post("/board/auth/login", data={"email": bf.OTHER_EMAIL, "password": bf.OTHER_PASSWORD},
                    headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 403
    assert "set-cookie" not in r.headers
    assert fake.sessions == {}


def test_a_wrong_password_gets_401(client, fake):
    for data in (WRONG, {"email": "nobody@example.com", "password": "whatever"}):
        r = client.post("/board/auth/login", data=data, headers=SAME_ORIGIN, follow_redirects=False)
        assert r.status_code == 401
        assert r.json() == {"error": "Wrong email or password."}   # the same answer for both
        assert "set-cookie" not in r.headers
    assert fake.sessions == {}


def test_supabase_refusing_the_servers_key_is_not_a_wrong_password(client, fake, monkeypatch, caplog):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key-of-another-project")
    for _ in range(8):                                 # more than an address's 5 free failures
        r = client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN, follow_redirects=False)
        assert r.status_code == 502
        assert r.json() == {"error": "The sign-in service refused this server's settings."}
    assert "HTTP 401" in caplog.text and "SUPABASE_ANON_KEY" in caplog.text
    monkeypatch.setenv("SUPABASE_ANON_KEY", bf.ANON)
    r = client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 303                        # none of those counted as a failure


def test_setup_problems_read_as_wrong_credentials_but_are_logged(client, fake, caplog):
    fake.unconfirmed.add(bf.OWNER_EMAIL)
    r = client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN, follow_redirects=False)
    assert r.status_code == 401 and r.json() == {"error": "Wrong email or password."}
    assert "email_not_confirmed" in caplog.text
    caplog.clear()
    assert client.post("/board/auth/login", data=WRONG, headers=SAME_ORIGIN).status_code == 401
    assert not [rec for rec in caplog.records if rec.name == "board.auth" and rec.levelno >= logging.WARNING]
    assert bf.OWNER_PASSWORD not in caplog.text and WRONG["password"] not in caplog.text
    # GoTrue's older error shape, and a body that is not JSON
    assert auth._error_code(httpx.Response(400, json={"error": "invalid_grant"})) == "invalid_grant"
    assert auth._error_code(httpx.Response(401, text="<html>")) == "none"


def test_sign_in_must_come_from_this_site(client, fake):
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"},
                    {"Referer": "https://evil.example/login"}):
        r = client.post("/board/auth/login", data=OWNER, headers=headers, follow_redirects=False)
        assert r.status_code == 403, headers
    assert fake.calls == []                                  # Supabase never asked
    r = client.post("/board/auth/login", data=OWNER, headers={"Referer": "http://testserver/board/login"},
                    follow_redirects=False)
    assert r.status_code == 303                              # this site's Referer stands in for Origin


def test_sign_in_never_uses_a_supabase_py_client(client, fake, monkeypatch):
    import core.narai_user

    def shared_client():
        raise AssertionError("board sign-in must not touch the shared service-role client")

    monkeypatch.setattr(core.narai_user, "get_supabase", shared_client)
    token = _sign_in(client)[bf.COOKIE]
    assert client.get("/admin/scoreboard", headers=bf.cookie(token)).status_code == 200
    r = client.post("/board/auth/logout", headers={**bf.cookie(token), **SAME_ORIGIN}, follow_redirects=False)
    assert r.status_code == 303
    for name in ("auth.py", "routes.py"):
        assert "sign_in_with_password" not in (ROOT / "core" / "board" / name).read_text(encoding="utf-8")


# ── rate limit ──────────────────────────────────────────────────────────────

def test_sign_in_backs_off_per_ip_and_never_locks_the_owner_out(client, fake, monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])

    def attempt(data):
        return client.post("/board/auth/login", data=data, headers=SAME_ORIGIN, follow_redirects=False)

    for _ in range(5):
        assert attempt(WRONG).status_code == 401
    r = attempt(WRONG)
    assert r.status_code == 429
    assert 0 < int(r.headers["retry-after"]) <= 30
    assert attempt(OWNER).status_code == 429          # no guessing while backing off...
    assert len(fake.calls_to("/auth/v1/token")) == 5  # ...and Supabase is not asked
    clock[0] += 31
    assert attempt(WRONG).status_code == 401           # the wait passed
    clock[0] += 31
    assert attempt(WRONG).status_code == 429           # and it doubled to 60 s
    clock[0] += 30
    assert attempt(OWNER).status_code == 303           # a wait, not a lockout
    assert attempt(WRONG).status_code == 401           # success cleared the count


def test_sign_in_backs_off_per_email_across_addresses(client, fake, monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 20_000.0)

    def attempt(data, ip, header="X-Forwarded-For"):
        return client.post("/board/auth/login", data=data, headers={**SAME_ORIGIN, header: ip},
                           follow_redirects=False)

    for i in range(10):
        assert attempt(WRONG, f"203.0.113.{i}").status_code == 401
    assert attempt(WRONG, "203.0.113.200").status_code == 429
    assert attempt(WRONG, "198.51.100.9", "CF-Connecting-IP").status_code == 429
    # another email from a fresh address is not slowed down
    assert attempt({"email": bf.OTHER_EMAIL, "password": "nope"}, "198.51.100.7").status_code == 401


def test_the_backoff_wait_is_capped_and_forgotten(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    backoff = auth._Backoff(free=5)
    for _ in range(40):
        backoff.fail("k")
    assert backoff.wait("k") == 900                    # never more than 15 minutes
    clock[0] += 3601
    assert backoff.wait("k") == 0                       # failures are remembered for an hour


def _login_request(ip):
    """A sign-in request as the route hands it to auth.sign_in."""
    return Request({"type": "http", "method": "POST", "path": "/board/auth/login", "root_path": "",
                    "scheme": "http", "query_string": b"", "server": ("testserver", 80),
                    "client": (ip, 50000), "headers": [(b"host", b"testserver"),
                                                       (b"origin", b"http://testserver"),
                                                       (b"cf-connecting-ip", ip.encode())]})


@pytest.mark.parametrize("addresses,allowed", [(1, 5), (30, 10)])
def test_parallel_wrong_guesses_cannot_pass_the_backoff_together(fake, monkeypatch, addresses, allowed):
    monkeypatch.setattr(auth, "_now", lambda: 40_000.0)
    answer = fake.handler

    def slow_grant(request):                           # Supabase Auth takes a moment to answer
        if request.url.path == "/auth/v1/token":
            time.sleep(0.2)
        return answer(request)

    monkeypatch.setattr(auth, "_transport", httpx.MockTransport(slow_grant))
    statuses, start = [], threading.Barrier(30)

    def guess(i):
        start.wait()
        try:
            auth.sign_in(_login_request(f"203.0.113.{i % addresses}"), bf.OWNER_EMAIL, f"guess {i}")
        except auth.SignInError as e:
            statuses.append(e.status)

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # one address: its 5 free failures; 30 addresses: the email's 10. Never more.
    assert len(fake.calls_to("/auth/v1/token")) == allowed
    assert sorted(statuses) == [401] * allowed + [429] * (30 - allowed)


def test_a_known_device_is_not_held_back_by_failures_elsewhere(client, fake, monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 60_000.0)
    device = _sign_in(client)[auth.DEVICE_COOKIE]
    # someone who knows the owner's email fails from many client addresses, real or forged
    for i in range(10):
        assert _login(client, WRONG, f"198.51.100.{i}").status_code == 401
    assert _login(client, WRONG, "198.51.100.10").status_code == 429
    # and fills one address's bucket with another email
    for _ in range(5):
        assert _login(client, {"email": "x@example.com", "password": "x"}, "198.51.100.99").status_code == 401
    # a browser the owner never signed in from waits like everyone else...
    assert _login(client, OWNER, "203.0.113.50").status_code == 429
    # ...the owner's known device gets in, from any address
    for ip in ("203.0.113.50", "198.51.100.10", "198.51.100.99"):
        assert _login(client, OWNER, ip, device).status_code == 303, ip

    # only a cookie this server signed for this owner, in the last year, counts
    other_owner = auth.BoardSettings(url=bf.URL, anon_key=bf.ANON, service_key=bf.SERVICE, owner_id=bf.OTHER_ID)
    other_key = auth.BoardSettings(url=bf.URL, anon_key=bf.ANON, service_key="another key", owner_id=bf.OWNER_ID)
    altered = device[:-1] + ("0" if device[-1] != "0" else "1")
    for value in (altered, auth.new_device_cookie(other_owner), auth.new_device_cookie(other_key),
                  "A" * 22 + ".1700000000." + "0" * 64, "not-a-device"):
        assert _login(client, OWNER, "203.0.113.50", value).status_code == 429, value
    monkeypatch.setattr(auth, "_wall", lambda: time.time() + 366 * 86400)
    assert _login(client, OWNER, "203.0.113.50", device).status_code == 429   # a year old: expired


def test_a_known_device_has_a_backoff_of_its_own(client, fake, monkeypatch):
    clock = [70_000.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    device = _sign_in(client)[auth.DEVICE_COOKIE]
    for i in range(5):                                 # whatever the client address says
        assert _login(client, WRONG, f"203.0.113.{i}", device).status_code == 401
    r = _login(client, OWNER, "203.0.113.200", device)
    assert r.status_code == 429 and 0 < int(r.headers["retry-after"]) <= 30
    assert len(fake.calls_to("/auth/v1/token")) == 6   # 1 sign-in + 5 guesses
    # those guesses were the device's own: the email and the addresses were not charged
    assert _login(client, OWNER, "203.0.113.0").status_code == 303
    clock[0] += 31
    assert _login(client, OWNER, "203.0.113.200", device).status_code == 303   # a wait, not a lockout


def test_a_sustained_attack_on_the_owners_email_never_keeps_a_known_device_out(client, fake, monkeypatch):
    """Three addresses keep the owner's email in backoff for 3 hours: a wrong
    guess whenever its wait ends (about 15 an hour). The owner, signing in from a
    known device every 5 minutes, always gets in."""
    clock = [100_000.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    device = _sign_in(client)[auth.DEVICE_COOKIE]
    addresses = ["198.51.100.1", "198.51.100.2", "198.51.100.3"]
    guesses = owner_in = email_blocked = 0
    for minute in range(3 * 60):
        if auth._email_backoff.wait("email:" + bf.OWNER_EMAIL) <= 0:
            ip = next((a for a in addresses if auth._ip_backoff.wait("ip:" + a) <= 0), None)
            if ip:
                assert _login(client, WRONG, ip).status_code == 401
                guesses += 1
        if minute % 5 == 0:
            email_blocked += auth._email_backoff.wait("email:" + bf.OWNER_EMAIL) > 0
            assert _login(client, OWNER, "203.0.113.77", device).status_code == 303, minute
            owner_in += 1
        clock[0] += 60
    assert owner_in == 36
    assert guesses >= 40 and email_blocked >= 30       # the email itself stayed in backoff


# ── the session cookie on the API ───────────────────────────────────────────

def test_a_cookie_authenticated_write_needs_this_sites_origin(client, fake, monkeypatch):
    ran = []
    monkeypatch.setattr("core.portfolio.leadgen.run_campaign", lambda slug: ran.append(slug) or {"ok": True})
    token = fake.add_session()
    url = "/api/narai/leadgen/run/plumbers"
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {},
                    {"Referer": "https://evil.example/page"}, {"Origin": "http://testserver.evil.example"}):
        r = client.post(url, headers={**bf.cookie(token), **headers})
        assert r.status_code == 403, headers
    assert ran == []
    r = client.post(url, headers={**bf.cookie(token), **SAME_ORIGIN})
    assert r.status_code == 200 and ran == ["plumbers"]

    r = client.post("/board/auth/logout", headers={**bf.cookie(token), "Origin": "https://evil.example"},
                    follow_redirects=False)
    assert r.status_code == 403
    assert fake.sessions[_digest(token)]["revoked_at"] is None


def test_same_origin_behind_the_tls_proxy(client, fake):
    # Railway ends TLS: the app sees http, the browser's Origin says https
    proxied = {"X-Forwarded-Proto": "https"}
    token = fake.add_session()
    r = client.post("/board/auth/logout", headers={**bf.cookie(token), **proxied, "Origin": "http://testserver"},
                    follow_redirects=False)
    assert r.status_code == 403                        # plain http is not this https site
    r = client.post("/board/auth/logout", headers={**bf.cookie(token), **proxied, "Origin": "https://testserver"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_the_session_cookie_works_only_from_this_sites_pages(client, fake):
    token = fake.add_session()
    for url in ("/api/narai/scoreboard", "/api/board/scoreboard"):
        assert client.get(url, headers=bf.cookie(token)).status_code == 200
        assert client.get(url, headers={**bf.cookie(token), "Sec-Fetch-Site": "same-origin"}).status_code == 200
        for headers in ({"Origin": "https://www.wheellsverse.com"}, {"Sec-Fetch-Site": "same-site"},
                        {"Sec-Fetch-Site": "cross-site"}):
            r = client.get(url, headers={**bf.cookie(token), **headers})
            assert r.status_code == 403, (url, headers)


def test_x_api_key_still_works_on_protected_api_routes(client, fake, monkeypatch):
    monkeypatch.setattr("core.portfolio.leadgen.run_campaign", lambda slug: {"ok": slug})
    url = "/api/narai/scoreboard"
    r = client.get(url, headers={"X-API-Key": bf.API_KEY})
    assert r.status_code == 200 and r.json() == SNAPSHOT
    assert client.get(url, headers={"X-API-Key": bf.API_KEY, "Origin": "https://elsewhere.example"}).status_code == 200
    assert client.get(url + "?api_key=" + bf.API_KEY).status_code == 200
    r = client.post("/api/narai/leadgen/run/roofers", headers={"X-API-Key": bf.API_KEY})
    assert r.status_code == 200 and r.json() == {"ok": "roofers"}   # writes need no Origin with the key
    r = client.get(url)
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized", "hint": "Set X-API-Key header"}
    assert client.get(url, headers={"X-API-Key": "wrong"}).status_code == 401
    assert fake.calls == []                            # no session lookups without a cookie


@pytest.mark.parametrize("module,path", [
    ("narai.api.routes.portfolio_admin", "/api/narai/portfolio/overview"),
    ("narai.api.routes.portfolio_cockpit_admin", "/api/narai/portfolio/biz/n8n/audit"),
    ("narai.api.routes.siteboost_admin", "/api/narai/siteboost/runs"),
    ("narai.api.routes.shopify_admin", "/api/narai/shopify/plans"),
])
def test_admin_api_routers_take_the_owner_session(fake, monkeypatch, tmp_path, module, path):
    monkeypatch.setenv("API_KEY", bf.API_KEY)
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    app = FastAPI()
    app.include_router(importlib.import_module(module).router)
    c = TestClient(app, raise_server_exceptions=False)
    token = fake.add_session()
    assert c.get(path).status_code == 401
    assert c.get(path, headers={"X-API-Key": bf.API_KEY}).status_code == 200
    assert c.get(path, headers=bf.cookie(token)).status_code == 200
    assert c.get(path, headers={**bf.cookie(token), "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.get(path, headers=bf.cookie(fake.add_session(revoked=True))).status_code == 401


# ── signed-in pages ─────────────────────────────────────────────────────────

def test_signed_in_admin_pages_are_static_and_carry_no_secrets(client, fake, monkeypatch):
    import core.api
    key = "api-key-that-must-never-reach-a-page-5e1f"
    monkeypatch.setenv("API_KEY", key)
    monkeypatch.setattr(core.api, "_API_KEY", key)
    secret_values = {"API_KEY": key, "SUPABASE_SERVICE_KEY": bf.SERVICE,
                     "SUPABASE_ANON_KEY": bf.ANON, "BOARD_OWNER_USER_ID": bf.OWNER_ID}
    # pages served through core.api._serve_frontend would write out these copies
    assert (core.api._SUPABASE_ANON, core.api._API_KEY) == (bf.ANON, key)
    token, other = fake.add_session(), fake.add_session()
    for path in _admin_pages():
        r = client.get(path, headers=bf.cookie(token), follow_redirects=False)
        assert r.status_code == 200, path
        for name, value in secret_values.items():
            assert value not in r.text, f"{path} contains {name}"
        assert "%%API_KEY%%" not in r.text, path
        same = client.get(path, headers=bf.cookie(other), follow_redirects=False)
        assert same.content == r.content, f"{path} differs between visitors"
    page = client.get("/admin/scoreboard", headers=bf.cookie(token))
    assert page.content == (ROOT / "frontend" / "admin" / "scoreboard.html").read_bytes()

    login = client.get("/board/login")
    assert login.status_code == 200
    assert login.content == (ROOT / "frontend" / "admin" / "board_login.html").read_bytes()
    assert "frame-ancestors 'self'" in login.headers["content-security-policy"]
    for value in secret_values.values():
        assert value not in login.text


@pytest.mark.parametrize("name", ["scoreboard.html", "leadgen.html", "portfolio.html", "portfolio_cockpit.html",
                                  "siteboost.html", "index.html", "shopify.html", "board_login.html"])
def test_admin_page_scripts_send_no_key(name):
    text = (ROOT / "frontend" / "admin" / name).read_text(encoding="utf-8")
    assert "%%API_KEY%%" not in text
    assert "X-API-Key" not in text
    for stored_key in ("admin_api_key", "wv_key", "wmos_key", "siteboost_api_key"):
        assert stored_key not in text


# ── sign-out and dead sessions ──────────────────────────────────────────────

def test_sign_out_revokes_the_session_at_once(client, fake):
    token = _sign_in(client)[bf.COOKIE]
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 200   # cached now
    r = client.post("/board/auth/logout", headers={**bf.cookie(token), **SAME_ORIGIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/board/login"
    cleared = r.headers["set-cookie"].lower()
    assert cleared.startswith("__host-board_session=") and "max-age=0" in cleared
    assert "secure" in cleared and "path=/" in cleared
    assert fake.sessions[_digest(token)]["revoked_at"] is not None
    patches = fake.calls_to("/rest/v1/owner_sessions", "PATCH")
    assert len(patches) == 1 and patches[0].headers["apikey"] == bf.SERVICE
    # the cache let go of it: the same cookie opens nothing, in this process or a fresh one
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 401
    assert client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False).status_code == 302
    auth.reset_state()
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 401


@pytest.mark.parametrize("kind", ["expired", "revoked", "another user", "unknown", "malformed"])
def test_a_dead_session_reads_as_signed_out(client, fake, kind):
    token = {"expired": lambda: fake.add_session(days=-1),
             "revoked": lambda: fake.add_session(revoked=True),
             "another user": lambda: fake.add_session(user_id=bf.OTHER_ID),
             "unknown": lambda: "A" * 43,
             "malformed": lambda: "not-a-token"}[kind]()
    r = client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False)
    assert r.status_code == 302
    assert "max-age=0" in r.headers.get("set-cookie", "").lower()   # the dead cookie is dropped
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 401


def test_a_valid_session_is_cached_for_at_most_a_minute(client, fake, monkeypatch):
    clock = [50_000.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    token = fake.add_session()

    def reads():
        return len(fake.calls_to("/rest/v1/owner_sessions", "GET"))

    for _ in range(3):
        assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 200
    assert reads() == 1
    clock[0] += 61
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 200
    assert reads() == 2
    # a revoke made elsewhere (another process, the database) is seen within that minute
    fake.sessions[_digest(token)]["revoked_at"] = datetime.now(timezone.utc).isoformat()
    clock[0] += 61
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 401


# ── closed when not configured ──────────────────────────────────────────────

def test_without_an_owner_id_the_board_is_closed(client, fake, monkeypatch):
    token = fake.add_session()
    monkeypatch.delenv("BOARD_OWNER_USER_ID")
    assert client.get("/admin/scoreboard", follow_redirects=False).status_code == 503
    assert client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False).status_code == 503
    assert client.get("/admin", headers=bf.cookie(token), follow_redirects=False).status_code == 503
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 503
    assert client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN).status_code == 503
    assert client.post("/board/auth/logout", headers={**bf.cookie(token), **SAME_ORIGIN}).status_code == 503
    assert fake.calls == []                            # nothing reached Supabase
    # the X-API-Key routes are not the board's: they keep working
    assert client.get("/api/narai/scoreboard", headers={"X-API-Key": bf.API_KEY}).status_code == 200


@pytest.mark.parametrize("name,value", [
    ("SUPABASE_URL", ""), ("SUPABASE_ANON_KEY", ""), ("SUPABASE_SERVICE_KEY", ""),
    ("BOARD_OWNER_USER_ID", "not-a-uuid"),
    # values a copy-paste can leave behind: an invisible character, a bad port, no scheme
    ("SUPABASE_URL", bf.URL + "​"), ("SUPABASE_URL", bf.URL + ":abc"),
    ("SUPABASE_URL", "board-tests.supabase.invalid"), ("SUPABASE_URL", "ftp://board-tests.supabase.invalid"),
    ("SUPABASE_ANON_KEY", bf.ANON + "’"), ("SUPABASE_SERVICE_KEY", bf.SERVICE + " x"),
])
def test_any_missing_sign_in_setting_closes_the_board(client, fake, monkeypatch, name, value):
    token = fake.add_session()
    monkeypatch.setenv(name, value)
    assert client.get("/admin/siteboost", follow_redirects=False).status_code == 503
    assert client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False).status_code == 503
    assert client.get("/api/board/opportunities", headers=bf.cookie(token)).status_code == 503
    assert client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN).status_code == 503
    # an X-API-Key route reads a cookie it cannot check as no credential at all
    assert client.get("/api/narai/killswitch", headers=bf.cookie(token)).status_code == 401
    assert fake.calls == []


def test_an_unreachable_session_store_fails_closed(client, fake):
    token = fake.add_session()
    fake.down = True
    assert client.get("/admin/scoreboard", headers=bf.cookie(token), follow_redirects=False).status_code == 503
    assert client.get("/api/board/scoreboard", headers=bf.cookie(token)).status_code == 503
    assert client.get("/api/narai/scoreboard", headers=bf.cookie(token)).status_code == 503
    assert client.post("/board/auth/login", data=OWNER, headers=SAME_ORIGIN).status_code == 502


def test_safe_next_keeps_only_relative_paths_on_this_site():
    assert auth.safe_next("/admin/portfolio/n8n?tab=build") == "/admin/portfolio/n8n?tab=build"
    assert auth.safe_next("  /admin/leadgen ") == "/admin/leadgen"
    for bad in (None, "", "admin", "//evil.example", "/\\evil.example", "https://evil.example/admin",
                "/admin\nx", "/" + "a" * 2048):
        assert auth.safe_next(bad) == "/admin/scoreboard", bad
