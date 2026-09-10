"""The HTTP gate does not cover WebSockets, and neither did the guard that was supposed to notice.

`api_key_middleware` is registered as `@app.middleware("http")`. Starlette's BaseHTTPMiddleware only
wraps scopes of type "http" and passes every other scope straight through, so a WebSocket handshake
never reaches it. App A mounts exactly one WebSocket route and it had no dependency of its own:

    @router.websocket("/stream/{run_id}")        core/code_router.py:132
    async def code_stream(websocket, run_id):
        await websocket.accept()                 # unconditionally, before any check

Measured against the app before the fix, anonymously:

    websocket_connect("/api/code/stream/anything")  -> ACCEPTED, then {"error": "No active run: ..."}

It streams the stdout of a code-execution run, and it lives on the same router as POST /api/code/run
and POST /api/code/save — which ARE correctly 401 for an anonymous caller. So the HTTP half of that
subsystem is gated and the WebSocket half was not.

DIRECT IMPACT IS BOUNDED. run_id is a uuid4 the attacker cannot guess (core/code_engine.py), so this
leaks nothing without one. The reason it still matters is structural: every WebSocket route added to
App A from now on is unauthenticated by default and silently so, which is the same "public unless
someone remembers" shape as the fourteen scattered _PUBLIC_PATHS sites that produced this whole
sequence of incidents.

AND MY OWN GUARD COULD NOT SEE IT. test_public_action_routes.py enumerates the surface with

    for m in getattr(r, "methods", set()) or set():
        if m not in ("POST", "PUT", "PATCH", "DELETE"): continue

A WebSocket route has `methods = None`, so the inner loop never runs and the route is skipped in
silence. The guard enumerated 387 mutating routes and this was not one of them. A test that pins "the
surface" pins only the part of the surface it knows how to enumerate — so the pin below is over
WebSocket routes specifically, counted separately, because that is the shape that hid.

CROSS-SITE WEBSOCKET HIJACKING. A WebSocket handshake is not subject to CORS, and browsers have
historically attached cookies to cross-origin WebSocket connections. Checking Origin on the handshake
is the standard defence, and it reuses exactly the allowlist the CSRF guard already uses.
"""
import os

import pytest
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]
TRUSTED = frozenset({"https://app.wheellsverse.com"})

WS_PATH = "/api/code/stream/any-run-id"


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture(autouse=True)
def _prod(monkeypatch):
    monkeypatch.setattr(core_api, "_APP_ENV", "production", raising=False)
    monkeypatch.setattr(core_api, "_CSRF_TRUSTED_ORIGINS", TRUSTED, raising=False)
    core_api._rate_limit_store.clear()
    yield
    core_api._rate_limit_store.clear()


def _connect(client, **kwargs):
    """Returns "ACCEPTED" or "REFUSED". A refused handshake raises out of the context manager."""
    try:
        with client.websocket_connect(WS_PATH, **kwargs):
            return "ACCEPTED"
    except Exception:
        return "REFUSED"


# ── 1. anonymous and forged identities ────────────────────────────────────────────────────────────
def test_an_anonymous_websocket_is_refused(client):
    assert _connect(client) == "REFUSED", "an anonymous WebSocket handshake was accepted"


def test_a_bad_key_is_refused(client):
    assert _connect(client, headers={"X-API-Key": "nope"}) == "REFUSED"


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_a_non_owner_session_is_refused(client, role):
    """A TRUSTED origin is sent deliberately, so role is the only thing left that can refuse this.

    Without it this test passed for the wrong reason: operator and viewer were being rejected for a
    missing Origin header, and a mutant that accepted every role survived untouched. A test that
    cannot fail for the reason it names is not testing that reason.
    """
    cookie = osess.mint_session(role, secret=SESSION_SECRET, ttl_seconds=3600)
    assert _connect(client, cookies={COOKIE_NAME: cookie},
                    headers={"Origin": "https://app.wheellsverse.com"}) == "REFUSED", \
        f"a {role} session opened the stream"


def test_a_session_signed_by_a_foreign_secret_is_refused(client):
    cookie = osess.mint_session("owner", secret="not-our-secret", ttl_seconds=3600)
    assert _connect(client, cookies={COOKIE_NAME: cookie},
                    headers={"Origin": "https://app.wheellsverse.com"}) == "REFUSED"


# ── 2. the owner still gets through ───────────────────────────────────────────────────────────────
def test_the_owner_key_is_accepted(client):
    assert _connect(client, headers={"X-API-Key": OWNER_KEY}) == "ACCEPTED", \
        "the owner was locked out of the stream"


def test_an_owner_session_from_a_trusted_origin_is_accepted(client):
    cookie = osess.mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    assert _connect(client, cookies={COOKIE_NAME: cookie},
                    headers={"Origin": "https://app.wheellsverse.com"}) == "ACCEPTED"


# ── 3. cross-site WebSocket hijacking ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("origin", [
    "https://evil.com",
    "null",
    "https://kai.wheellsverse.com",              # same-SITE, different origin
    "https://app.wheellsverse.com.evil.com",     # the suffix trap
])
def test_a_cookie_authenticated_handshake_from_a_foreign_origin_is_refused(client, origin):
    """A WebSocket handshake is not subject to CORS, so an origin check is the defence — and it must
    be the same allowlist the CSRF guard uses, or the two drift apart."""
    cookie = osess.mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    assert _connect(client, cookies={COOKIE_NAME: cookie},
                    headers={"Origin": origin}) == "REFUSED", \
        f"a cookie-authenticated handshake from {origin} was accepted"


def test_the_key_path_is_not_subject_to_the_origin_check(client):
    """Same rule as the HTTP CSRF guard: a header credential cannot be attached by a foreign page, so
    it is the machine path and carries no cross-origin risk."""
    assert _connect(client, headers={"X-API-Key": OWNER_KEY,
                                     "Origin": "https://evil.com"}) == "ACCEPTED"


# ── 4. the guard must be able to SEE websocket routes ─────────────────────────────────────────────
def test_every_websocket_route_is_pinned_and_guarded():
    """The blind spot itself, pinned.

    A WebSocket route has methods=None, so the mutating-surface enumeration in
    test_public_action_routes.py skips it silently — it found 387 mutating routes and this was not
    among them. Counting WebSocket routes separately is the only way a new one cannot be added
    without a decision.
    """
    import importlib.util

    def importable(m):
        try:
            return importlib.util.find_spec(m) is not None
        except Exception:
            return False

    # THE ENVIRONMENT DECIDES WHAT THIS TEST CAN SEE. /api/v2/narai/voice/ws only exists when the
    # NarAI v2 voice router imports, which needs chromadb + litellm. The venv used for every earlier
    # audit in this sequence had neither, so this pin passed while asserting the WebSocket surface
    # was a single route — and production was serving two more. A guard that audits less than
    # production and reports success is the exact failure it exists to prevent.
    missing = [m for m in ("chromadb", "litellm") if not importable(m)]
    assert not missing, (
        f"optional deps missing: {missing} — the v2 voice router will not load and this test would "
        "pin a SMALLER WebSocket surface than production serves. Both are pinned in requirements.txt.")

    ws = [r for r in core_api.app.routes
          if isinstance(r, WebSocketRoute) or r.__class__.__name__ == "APIWebSocketRoute"]
    paths = sorted(set(getattr(r, "path", "") for r in ws))
    assert paths == ["/api/code/stream/{run_id}", "/api/v2/narai/voice/ws"], (
        f"the WebSocket surface changed: {paths}. Every WebSocket route bypasses api_key_middleware "
        "by construction, so a new one needs its own gate and its own entry here.")

    import inspect
    for r in ws:
        path = getattr(r, "path", "?")
        try:
            src = inspect.getsource(r.endpoint)
        except Exception:
            src = ""
        if path == "/api/v2/narai/voice/ws":
            # Guarded, but by a JWT in a QUERY PARAMETER: `token: str = Query(...)`, verified before
            # accept(). That is the standard WebSocket workaround — a browser cannot set headers on a
            # handshake — but it is still a credential in a URL, which is what ?api_key= was removed
            # from this codebase for. It lands in edge logs, access logs, Referer and history, none of
            # which it can be revoked from. Carried as a known residual, not endorsed.
            assert "token" in src and ("Query(" in src or "verify" in src.lower()), (
                f"{path} no longer verifies its JWT before accepting — it is on the one code path "
                "the HTTP middleware never sees")
            continue
        assert "_ws_owner_ok" in src, (
            f"{path} does not call the WebSocket owner gate — the HTTP middleware will not do it "
            "for you")


def test_the_gate_runs_before_accept():
    """`await websocket.accept()` came first, so the connection was established and then answered.
    Accepting an unauthenticated peer and closing afterwards still completes a handshake with them;
    the refusal has to happen before."""
    import inspect
    from core import code_router
    src = inspect.getsource(code_router.code_stream)
    gate_at = src.find("_ws_owner_ok")
    accept_at = src.find("await websocket.accept()")
    assert gate_at != -1 and accept_at != -1
    assert gate_at < accept_at, "the owner gate runs after accept() — refuse before accepting"
