"""Owner-only is not enough: a cookie is presented by the browser, not by the user.

GATE 1 — CSRF. The previous fix made 26 action routes owner-only. That stops an anonymous caller.
It does not stop another website from making the OWNER'S OWN BROWSER issue the request, because a
session cookie is attached by the browser on the basis of the destination, not the sender.

What actually protects those routes today, and where it stops:

  SameSite=Lax   blocks cross-SITE cookie sending on unsafe methods. "Site" is the registrable
                 domain, so it blocks evil.com -> app.wheellsverse.com. It does NOT block
                 kai.wheellsverse.com -> app.wheellsverse.com: those are cross-ORIGIN but
                 same-SITE, and the cookie is sent. Every wheellsverse.com subdomain, including
                 the Cloudflare Pages apex and anything ever hosted on one, is inside the trust
                 boundary that Lax draws.
  CORS           does NOT stop this. A cross-origin POST with a form or text/plain content type is
                 a "simple request": the browser SENDS it and only withholds the RESPONSE. The side
                 effect has already happened. An allowlist of origins protects data confidentiality,
                 never state change.

So the guard here is an explicit same-origin requirement on cookie-authenticated unsafe requests,
checked against the origins the app already trusts for credentialed CORS.

The machine path is deliberately untouched: a header credential (X-API-Key) cannot be attached by
a foreign page — setting it forces a CORS preflight the attacker cannot satisfy — so header-
authenticated requests carry no CSRF risk and must keep working with no Origin at all. That is what
"preserve legitimate non-browser authentication only through an explicit machine-credential path"
means in code: the cookie is the browser path and gets the check; the header is the machine path
and does not.

GATE 2 — the side-effecting GET. GET /api/sa/trend-scan is documented as a cached read. On a cold
cache run_trend_scan(refresh=False) falls through to the LLM scan AND writes the cache file, so a
single top-level navigation spends money and mutates state. SameSite=Lax deliberately DOES send
cookies on top-level GET navigation, so being owner-only does not save it: a link is enough.

The pure matcher is tested directly, not only through the app. Two mutants survived a prior round
because TestClient normalised paths and FastAPI answered 405 before the guard ran. A check that
sits below the framework has to be tested below the framework.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")
os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]

TRUSTED = ("https://app.wheellsverse.com", "https://wheellsverse.com")

# The routes the previous commit gated. A CSRF bypass would hand every one of them back.
ACTIONS = [
    ("POST", "/api/narai-autopilot/start"), ("POST", "/api/narai-autopilot/stop"),
    ("POST", "/api/narai-autopilot/reels"), ("POST", "/api/narai-autopilot/queue/0/mark_done"),
    ("POST", "/api/factory/start"), ("POST", "/api/factory/stop"),
    ("DELETE", "/api/factory/reset"), ("POST", "/api/qc/review"),
    ("POST", "/api/pod/start"), ("POST", "/api/pod/stop"),
    ("POST", "/api/nexora/recruit"), ("POST", "/api/nexora/growth"),
    ("POST", "/api/sa/start"), ("POST", "/api/sa/stop"), ("POST", "/api/sa/trend-scan"),
    ("POST", "/api/sa/setup-boutique"),
    ("POST", "/api/shopify-autopilot/start"), ("POST", "/api/shopify-autopilot/stop"),
    ("POST", "/api/shopify-autopilot/trend-scan"),
    ("POST", "/api/shopify/agents/start"), ("POST", "/api/shopify/agents/stop"),
    ("POST", "/api/shopify/agents/dispatch"), ("POST", "/api/shopify/agents/upgrade-now"),
    ("POST", "/api/shopify/discount"), ("POST", "/api/shopify/products"),
    ("DELETE", "/api/shopify/products/1"), ("PUT", "/api/shopify/products/1"),
    ("POST", "/api/shopify/publish-narai-product"), ("POST", "/api/shopify/register-webhooks"),
    ("POST", "/api/shopify/media/generate-batch"),
    ("POST", "/api/shopify/intelligence/analyze"), ("POST", "/api/shopify/intelligence/autopilot"),
]


def owner_cookie():
    return {COOKIE_NAME: osess.mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)}


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture(autouse=True)
def _prod(monkeypatch):
    monkeypatch.setattr(core_api, "_APP_ENV", "production", raising=False)
    monkeypatch.setattr(core_api, "_CSRF_TRUSTED_ORIGINS", frozenset(TRUSTED), raising=False)
    # This module fires the full action matrix several times over — well past the per-IP limit in
    # rate_limit_middleware, which is process-global and keyed on client IP. Left alone it does not
    # fail THIS file; it starves whatever runs next, and the resulting 429s look exactly like an
    # authorization regression somewhere else in the suite. Clear it around each test so the noise
    # stays inside the file that makes it.
    core_api._rate_limit_store.clear()
    yield
    core_api._rate_limit_store.clear()


# ── GATE 1a: the matcher, tested below the framework ──────────────────────────────────────────────
ALLOWED = frozenset(TRUSTED)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_need_no_origin(method):
    """A safe method changes nothing, so requiring an Origin on it would break ordinary navigation
    without buying anything. Gate 2 is what makes this true for THIS app."""
    assert core_api._trusted_origin_ok(method, None, None, ALLOWED) is True


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_unsafe_methods_require_a_trusted_origin(method):
    assert core_api._trusted_origin_ok(method, "https://app.wheellsverse.com", None, ALLOWED) is True
    assert core_api._trusted_origin_ok(method, "https://evil.com", None, ALLOWED) is False


def test_null_origin_is_refused():
    """Origin: null comes from a sandboxed iframe, a data: URL, or certain redirects. It is a real
    value an attacker can produce, and it must never be treated as absent."""
    assert core_api._trusted_origin_ok("POST", "null", None, ALLOWED) is False
    assert core_api._trusted_origin_ok("POST", "null", "https://app.wheellsverse.com/x", ALLOWED) is False


def test_missing_origin_falls_back_to_referer_then_fails_closed():
    assert core_api._trusted_origin_ok("POST", None, "https://app.wheellsverse.com/admin", ALLOWED) is True
    assert core_api._trusted_origin_ok("POST", None, "https://evil.com/page", ALLOWED) is False
    # Neither header: no evidence of provenance at all. Refuse.
    assert core_api._trusted_origin_ok("POST", None, None, ALLOWED) is False
    assert core_api._trusted_origin_ok("POST", "", "", ALLOWED) is False


def test_a_trusted_origin_is_not_a_prefix_match():
    """The whole reason the last incident happened was startswith(). An origin comparison has the
    same trap: https://wheellsverse.com.evil.com starts with a trusted string."""
    for hostile in ("https://app.wheellsverse.com.evil.com",
                    "https://app.wheellsverse.com@evil.com",
                    "https://evil.com/https://app.wheellsverse.com",
                    "https://app.wheellsverse.commercial.example"):
        assert core_api._trusted_origin_ok("POST", hostile, None, ALLOWED) is False, hostile


def test_a_sibling_subdomain_is_not_trusted_by_default():
    """THE POINT OF THIS GUARD. kai.wheellsverse.com is same-SITE, so SameSite=Lax sends the cookie
    to app.wheellsverse.com. Only an explicit origin allowlist stops it."""
    assert core_api._trusted_origin_ok("POST", "https://kai.wheellsverse.com", None, ALLOWED) is False


def test_scheme_and_port_are_part_of_the_origin():
    assert core_api._trusted_origin_ok("POST", "http://app.wheellsverse.com", None, ALLOWED) is False
    assert core_api._trusted_origin_ok("POST", "https://app.wheellsverse.com:8443", None, ALLOWED) is False


def test_case_and_trailing_slash_do_not_defeat_the_match():
    for ok in ("https://APP.wheellsverse.com", "https://app.wheellsverse.com/"):
        assert core_api._trusted_origin_ok("POST", ok, None, ALLOWED) is True, ok


# ── GATE 1b: through the app ──────────────────────────────────────────────────────────────────────
def test_cookie_authenticated_action_from_a_foreign_origin_is_refused(client):
    for method, path in ACTIONS:
        r = client.request(method, path, cookies=owner_cookie(),
                           headers={"Origin": "https://evil.com"}, json={})
        assert r.status_code == 401, f"CSRF reached {method} {path} ({r.status_code})"


def test_cookie_authenticated_action_with_no_origin_is_refused(client):
    for method, path in ACTIONS:
        r = client.request(method, path, cookies=owner_cookie(), json={})
        assert r.status_code == 401, f"origin-less cookie request reached {method} {path}"


def test_cookie_authenticated_action_with_null_origin_is_refused(client):
    for method, path in ACTIONS:
        r = client.request(method, path, cookies=owner_cookie(),
                           headers={"Origin": "null"}, json={})
        assert r.status_code == 401, f"null origin reached {method} {path}"


def test_a_cross_origin_page_cannot_act_while_the_owner_is_signed_in(client, monkeypatch):
    """The scenario in full: the owner is signed in, and a page on another origin fires every
    action. Record-and-refuse spies stand behind the gate, so a bypass is caught even if the
    status code were to lie."""
    import sys, types
    fired = []

    def spy(name):
        def _f(*a, **k):
            fired.append(name)
            raise RuntimeError(f"SPY REFUSED: {name}")
        return _f

    for modname, fns in {
        "core.narai_autopilot": ("start_autopilot_background", "stop_autopilot",
                                 "run_autopilot_session", "generate_reels"),
        "core.narai_pod_engine": ("run_pod_session", "get_pod_session_status"),
        "core.viral_trend_engine": ("run_trend_scan", "scan_viral_opportunities",
                                    "save_opportunities"),
    }.items():
        mod = types.ModuleType(modname)
        for fn in fns:
            setattr(mod, fn, spy(f"{modname}.{fn}"))
        mod._session_state = {}
        monkeypatch.setitem(sys.modules, modname, mod)

    for origin in ("https://evil.com", "null", "https://kai.wheellsverse.com",
                   "https://app.wheellsverse.com.evil.com"):
        for method, path in ACTIONS:
            client.request(method, path, cookies=owner_cookie(),
                           headers={"Origin": origin}, json={})
    assert fired == [], f"a cross-origin request reached: {fired}"


def test_the_owner_can_still_act_from_a_trusted_origin(client):
    """The guard must not brick the operator. A same-origin cookie request has to get PAST the
    CSRF check — it may fail later for its own reasons, but never with the CSRF refusal."""
    r = client.request("POST", "/api/factory/start", cookies=owner_cookie(),
                       headers={"Origin": "https://app.wheellsverse.com"}, json={})
    assert r.status_code != 401, "a same-origin owner request was refused — the operator is locked out"


def test_the_machine_credential_path_is_untouched(client):
    """A header credential cannot be attached by a foreign page: setting X-API-Key forces a CORS
    preflight an attacker cannot satisfy. So header auth carries no CSRF risk and must keep working
    with a foreign Origin and with no Origin at all — this is the non-browser path."""
    for headers in ({"X-API-Key": OWNER_KEY},
                    {"X-API-Key": OWNER_KEY, "Origin": "https://evil.com"},
                    {"X-API-Key": OWNER_KEY, "Origin": "null"}):
        r = client.request("POST", "/api/factory/start", headers=headers, json={})
        assert r.status_code != 401, f"the machine path was broken by the CSRF guard: {headers}"


def test_safe_cookie_requests_are_unaffected(client):
    """Reads must not require an Origin, or every dashboard poll breaks."""
    for path in ("/api/factory/status", "/api/narai-autopilot/status", "/api/pod/status"):
        r = client.get(path, cookies=owner_cookie())
        assert r.status_code != 401, f"{path} broke for a signed-in owner"


def test_the_guard_only_applies_to_the_cookie(monkeypatch):
    """A principal resolved from a HEADER must not be subjected to the origin check, or the machine
    path dies. The distinguishing field is Principal.source == "session"."""
    assert core_api._csrf_required_for("session", "POST") is True
    assert core_api._csrf_required_for("owner_key", "POST") is False
    assert core_api._csrf_required_for("admin_token", "POST") is False
    assert core_api._csrf_required_for("session", "GET") is False


# ── GATE 2: the GET that computes ─────────────────────────────────────────────────────────────────
def test_get_trend_scan_never_computes(client, monkeypatch):
    """GET must read the cache and nothing else — no scrape, no LLM call, no file write."""
    import core.viral_trend_engine as vte
    fired = []
    monkeypatch.setattr(vte, "run_trend_scan",
                        lambda *a, **k: fired.append("run_trend_scan"), raising=False)
    monkeypatch.setattr(vte, "scan_viral_opportunities",
                        lambda *a, **k: fired.append("scan_viral_opportunities"), raising=False)
    monkeypatch.setattr(vte, "save_opportunities",
                        lambda *a, **k: fired.append("save_opportunities"), raising=False)
    r = client.get("/api/sa/trend-scan", headers={"X-API-Key": OWNER_KEY})
    assert r.status_code == 200, r.text
    assert fired == [], f"the GET performed work: {fired}"


def test_get_trend_scan_reports_state_honestly(client, monkeypatch, tmp_path):
    """An absent cache is not an empty result. Returning [] for "never scanned" is the same lie the
    scheduler told when it reported zeros for state it could not read."""
    import core.viral_trend_engine as vte
    monkeypatch.setattr(vte, "TRENDS_FILE", tmp_path / "absent.json", raising=False)
    body = client.get("/api/sa/trend-scan", headers={"X-API-Key": OWNER_KEY}).json()
    assert body.get("status") == "UNAVAILABLE", body
    assert body.get("opportunities") == []
    assert "count" not in body or body["count"] == 0

    import json as _j
    good = tmp_path / "fresh.json"
    good.write_text(_j.dumps({"saved_at": "2026-09-09T00:00:00+00:00", "count": 1,
                              "opportunities": [{"t": "x"}]}))
    monkeypatch.setattr(vte, "TRENDS_FILE", good, raising=False)
    body = client.get("/api/sa/trend-scan", headers={"X-API-Key": OWNER_KEY}).json()
    assert body.get("status") in ("OK", "STALE"), body
    assert body.get("opportunities") == [{"t": "x"}]

    unreadable = tmp_path / "broken.json"
    unreadable.write_text("{not json")
    monkeypatch.setattr(vte, "TRENDS_FILE", unreadable, raising=False)
    body = client.get("/api/sa/trend-scan", headers={"X-API-Key": OWNER_KEY}).json()
    assert body.get("status") == "UNAVAILABLE", body


def test_the_pure_cache_reader_distinguishes_absent_from_empty(tmp_path, monkeypatch):
    """Tested below the endpoint: three different states must not collapse into one."""
    import core.viral_trend_engine as vte
    import json as _j

    monkeypatch.setattr(vte, "TRENDS_FILE", tmp_path / "nope.json", raising=False)
    assert vte.cached_opportunities()[0] == "UNAVAILABLE"

    f = tmp_path / "t.json"
    f.write_text("{oops")
    monkeypatch.setattr(vte, "TRENDS_FILE", f, raising=False)
    assert vte.cached_opportunities()[0] == "UNAVAILABLE"

    f.write_text(_j.dumps({"saved_at": "1999-01-01T00:00:00+00:00", "opportunities": []}))
    status, opps, _ = vte.cached_opportunities()
    assert status == "STALE" and opps == []          # genuinely empty, and old — both facts kept

    from datetime import datetime, timezone
    f.write_text(_j.dumps({"saved_at": datetime.now(timezone.utc).isoformat(),
                           "opportunities": [{"a": 1}]}))
    status, opps, _ = vte.cached_opportunities()
    assert status == "OK" and opps == [{"a": 1}]


def test_no_public_get_can_still_trigger_paid_work(client, monkeypatch):
    """Gate 2 in its general form: walk the anonymously-reachable GET surface and assert none of it
    reaches the trend engine or the store-intelligence analyser."""
    import core.viral_trend_engine as vte
    fired = []
    for fn in ("run_trend_scan", "scan_viral_opportunities", "save_opportunities"):
        monkeypatch.setattr(vte, fn, lambda *a, _n=fn, **k: fired.append(_n), raising=False)
    for r in core_api.app.routes:
        path = getattr(r, "path", "")
        if "{" in path or "GET" not in (getattr(r, "methods", set()) or set()):
            continue
        if not (core_api._public_rule_for(path, "GET") or path in core_api._PUBLIC_PATHS):
            continue
        try:
            client.get(path)
        except Exception:
            pass
    assert fired == [], f"an anonymous GET reached the trend engine: {fired}"
