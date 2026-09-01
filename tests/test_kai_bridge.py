"""Bridge tests (merge Phase P3/P5). A mock App B (httpx.MockTransport) stands in
for the real upstream, so the full proxy path is exercised with no network:
fail-closed, allowlists, scope/ultra enforcement, secret stripping, SSE, upstream
error mapping, and correlation-id propagation.
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import operator_session as osess
from core.operator_session_web import SessionConfig, COOKIE_NAME
from core.kai_bridge import BridgeConfig, install_kai_bridge

SECRET = "bridge-secret"
OWNER_KEY = "owner-key"
ADMIN_TOKEN = "admin-token"
captured = {}
audit_events = []


def _handler(request: httpx.Request) -> httpx.Response:
    """Mock App B: echo what the bridge forwarded; special paths for stream/errors."""
    captured["url"] = str(request.url)
    captured["path"] = request.url.path
    captured["method"] = request.method
    captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
    captured["content"] = request.content
    if request.url.path.endswith("/timeout"):
        raise httpx.TimeoutException("boom", request=request)
    if request.url.path.endswith("/down"):
        raise httpx.ConnectError("refused", request=request)
    if request.url.path.endswith("/status500"):
        return httpx.Response(500, json={"error": "upstream_boom"})
    if "stream" in request.url.path:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"data: a\n\ndata: b\n\n")
    return httpx.Response(200, json={"ok": True, "saw_path": request.url.path})


def _client(enabled=True, methods=frozenset({"GET", "POST"})):
    captured.clear()
    audit_events.clear()
    app = FastAPI()
    sess = SessionConfig(enabled=True, owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN,
                         session_secret=SECRET)
    cfg = BridgeConfig(
        enabled=enabled, upstream="http://kai-upstream.internal", session=sess,
        allow_methods=methods,
        client_factory=lambda: httpx.AsyncClient(
            base_url="http://kai-upstream.internal",
            transport=httpx.MockTransport(_handler)),
        audit_sink=audit_events.append,
    )
    install_kai_bridge(app, cfg)
    return TestClient(app)


def _cookie(role):
    return {COOKIE_NAME: osess.mint_session(role, secret=SECRET, ttl_seconds=3600)}


# ── fail-closed / health ─────────────────────────────────────────────────────
def test_disabled_returns_404():
    c = _client(enabled=False)
    r = c.get("/admin/kai/kai-chat", cookies=_cookie("owner"))
    assert r.status_code == 404 and r.json()["error"] == "kai_bridge_disabled"
    assert not captured  # never touched upstream


def test_health_reports_status_without_leaking_upstream():
    c = _client(enabled=True)
    r = c.get("/admin/kai-bridge/health")
    body = r.json()
    assert body["enabled"] is True and body["upstream_configured"] is True
    assert "kai-upstream.internal" not in r.text  # upstream URL not leaked


# ── authn / authz ────────────────────────────────────────────────────────────
def test_anonymous_denied():
    c = _client()
    r = c.get("/admin/kai/kai-chat")
    assert r.status_code == 401 and not captured


def test_owner_allowed():
    c = _client()
    r = c.get("/admin/kai/kai-chat", cookies=_cookie("owner"))
    assert r.status_code == 200 and r.json()["ok"] is True
    # Maps to App B's real route /admin/kai-chat (NOT /kai-chat).
    assert captured["path"] == "/admin/kai-chat"


def test_upstream_path_prefix_mapping():
    # /admin/kai/kg/nodes → <upstream>/admin/kg/nodes (App B's real KG path).
    c = _client()
    c.get("/admin/kai/kg/nodes", cookies=_cookie("owner"))
    assert captured["path"] == "/admin/kg/nodes"


def test_operator_allowed_on_read_route():
    # Read routes (kg/twin/…) are operator-appropriate → kai.chat suffices.
    c = _client()
    r = c.get("/admin/kai/kg/nodes", cookies=_cookie("operator"))
    assert r.status_code == 200


def test_operator_denied_on_chat_ultra_endpoint():
    # /admin/kai-chat ALWAYS runs tier=ultra on App B, so the bridge gates the
    # whole kai-chat prefix to owner-only — an operator must be denied (§12).
    c = _client()
    r = c.post("/admin/kai/kai-chat", json={"m": "hi"}, cookies=_cookie("operator"))
    assert r.status_code == 403 and r.json()["need"] == osess.SCOPE_KAI_ULTRA
    assert not captured  # never forwarded to App B


def test_operator_denied_on_ultra_path():
    c = _client()
    r = c.post("/admin/kai/kai-chat/ultra", json={}, cookies=_cookie("operator"))
    assert r.status_code == 403 and r.json()["need"] == osess.SCOPE_KAI_ULTRA
    assert not captured  # blocked before reaching upstream


def test_owner_allowed_on_ultra_path():
    c = _client()
    r = c.post("/admin/kai/kai-chat/ultra", json={}, cookies=_cookie("owner"))
    assert r.status_code == 200


def test_ultra_query_flag_gated_for_operator():
    c = _client()
    r = c.post("/admin/kai/kai-chat?ultra=1", json={}, cookies=_cookie("operator"))
    assert r.status_code == 403


# ── allowlists / SSRF guards ─────────────────────────────────────────────────
def test_path_not_in_allowlist_404():
    c = _client()
    r = c.get("/admin/kai/secret-internal", cookies=_cookie("owner"))
    assert r.status_code == 404 and not captured


def test_path_traversal_blocked():
    c = _client()
    r = c.get("/admin/kai/kg/../../etc/passwd", cookies=_cookie("owner"))
    assert r.status_code == 404 and not captured


def test_method_not_allowed():
    c = _client(methods=frozenset({"GET"}))
    r = c.request("DELETE", "/admin/kai/kai-chat", cookies=_cookie("owner"))
    assert r.status_code == 405


def test_upstream_host_is_fixed_not_from_request():
    c = _client()
    c.get("/admin/kai/kg", cookies=_cookie("owner"))
    # Whatever the client sends, upstream host is always the configured one.
    assert captured["url"].startswith("http://kai-upstream.internal/")


# ── header hygiene ───────────────────────────────────────────────────────────
def test_api_key_not_forwarded_but_cookie_is():
    c = _client()
    c.get("/admin/kai/kg", cookies=_cookie("owner"),
          headers={"x-api-key": "SECRET-OWNER-KEY"})
    assert "x-api-key" not in captured["headers"]      # raw secret stripped
    assert "cookie" in captured["headers"]              # session cookie forwarded
    assert "wv_session" in captured["headers"]["cookie"]


def test_correlation_id_generated_and_propagated():
    c = _client()
    r = c.get("/admin/kai/kg", cookies=_cookie("owner"))
    assert "x-correlation-id" in captured["headers"]        # sent upstream
    assert r.headers.get("x-correlation-id")                # returned to caller


def test_correlation_id_preserved_when_supplied():
    c = _client()
    r = c.get("/admin/kai/kg", cookies=_cookie("owner"),
              headers={"x-correlation-id": "trace-123"})
    assert captured["headers"]["x-correlation-id"] == "trace-123"
    assert r.headers.get("x-correlation-id") == "trace-123"


# ── streaming / status / errors ──────────────────────────────────────────────
def test_sse_streaming_preserved():
    c = _client()
    r = c.get("/admin/kai/kai-chat/stream", cookies=_cookie("owner"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"data: a" in r.content and b"data: b" in r.content


def test_upstream_status_preserved():
    c = _client()
    r = c.get("/admin/kai/kg/status500", cookies=_cookie("owner"))
    assert r.status_code == 500


def test_upstream_timeout_maps_504():
    c = _client()
    r = c.get("/admin/kai/kg/timeout", cookies=_cookie("owner"))
    assert r.status_code == 504 and "correlation_id" in r.json()


def test_upstream_down_maps_502():
    c = _client()
    r = c.get("/admin/kai/kg/down", cookies=_cookie("owner"))
    assert r.status_code == 502


# ── audit (P8) ───────────────────────────────────────────────────────────────
def test_audit_emitted_on_dispatch_with_actor_and_no_secret():
    c = _client()
    c.get("/admin/kai/kai-chat", cookies=_cookie("owner"),
          headers={"x-api-key": "SUPER-SECRET-KEY"})
    assert len(audit_events) == 1
    ev = audit_events[0]
    assert ev["actor_role"] == "owner" and ev["module"] == "kai-chat"
    assert ev["action"] == "GET" and ev["status"] == 200
    assert ev["correlation_id"]
    # No secret anywhere in the event.
    blob = str(ev)
    assert "SUPER-SECRET-KEY" not in blob and "wv_session" not in blob
    assert "cookie" not in {k.lower() for k in ev}


def test_audit_emitted_on_denied_scope():
    c = _client()
    c.post("/admin/kai/kai-chat/ultra", json={}, cookies=_cookie("operator"))
    assert len(audit_events) == 1
    ev = audit_events[0]
    assert ev["status"] == 403 and ev["actor_role"] == "operator"


def test_audit_emitted_on_anonymous_denied():
    c = _client()
    c.get("/admin/kai/kai-chat")
    assert audit_events and audit_events[-1]["status"] == 401
    assert audit_events[-1]["actor_role"] == "anonymous"


# ── capability EXECUTION prefix (§6/§16) — owner-only, mapped to App B /admin/capabilities ──
def test_capabilities_owner_allowed_and_mapped():
    c = _client()
    r = c.get("/admin/kai/capabilities", cookies=_cookie("owner"))
    assert r.status_code == 200
    assert captured["path"] == "/admin/capabilities"   # bridged to App B's execution route


def test_capabilities_operator_denied_owner_only():
    # execution is owner-only; an operator session must be denied at the bridge, never forwarded.
    c = _client()
    r = c.post("/admin/kai/capabilities/yt-dlp/invoke", json={"operation": "metadata"},
               cookies=_cookie("operator"))
    assert r.status_code == 403 and r.json()["need"] == osess.SCOPE_KAI_ULTRA
    assert not captured


def test_capabilities_anonymous_denied():
    c = _client()
    r = c.get("/admin/kai/capabilities")
    assert r.status_code in (401, 403) and not captured
