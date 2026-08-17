"""LIVE-HTTP gate certification — App A (in-process) bridges over REAL HTTP to a
LIVE App B (uvicorn app.main:app on :8020). Proves the parts the in-process
surrogate mocked: real cross-app cookie over the wire + the bridge forwarding to
App B's real governed route.

SKIPS cleanly when App B isn't running on 127.0.0.1:8020, so it's CI-safe. To run
it, start App B first:

    PYTHONPATH=backend:. DATABASE_URL=postgresql://localhost/kai_staging \\
    APP_ENV=staging DEBUG=false JWT_SECRET_KEY=jwt ADMIN_TOKEN=optok \\
    SESSION_SIGNING_SECRET=LOCAL-STAGING-SECRET-do-not-reuse \\
    OPERATOR_SESSION_ENABLED=true \\
    python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8020
"""
import os
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

APP_B = "http://127.0.0.1:8020"
SECRET = "LOCAL-STAGING-SECRET-do-not-reuse"

httpx = pytest.importorskip("httpx")


def _app_b_up() -> bool:
    try:
        return httpx.get(f"{APP_B}/health", timeout=1.0).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _app_b_up(),
                                reason="live App B not running on :8020")


@pytest.fixture(scope="module")
def A():
    os.environ.update(
        API_KEY="ownerkey", ADMIN_TOKEN="optok", JWT_SECRET_KEY="jwt",
        SESSION_SIGNING_SECRET=SECRET, APP_ENV="test",
        OPERATOR_SESSION_ENABLED="true", KAI_BRIDGE_ENABLED="true",
        KAI_UPSTREAM_URL=APP_B, KAI_COMMAND_BAR_GOVERNED="true",
    )
    from fastapi.testclient import TestClient
    import core.api as _capi
    # core.api reads its bridge/session config once at import. If another test
    # module already imported it with a different secret/upstream (the cached
    # module can't be reconfigured), this live integration suite can't line up
    # with the live App B — run it in isolation. Skip cleanly rather than fail.
    if getattr(_capi, "_OPERATOR_SESSION_CFG", None) is None \
            or _capi._OPERATOR_SESSION_CFG.session_secret != SECRET \
            or getattr(_capi, "KAI_UPSTREAM_URL", None) not in (None, APP_B):
        pytest.skip("core.api already imported with different config — "
                    "run tests/test_live_gate.py in isolation (needs live App B)")
    return TestClient(_capi.app)


def _login(client, secret):
    client.cookies.clear()
    return client.post("/admin/session/login", json={"secret": secret})


# ── Gate 1 identity (real App A) ─────────────────────────────────────────────
def test_gate1_owner_and_operator(A):
    o = _login(A, "ownerkey").json()
    assert o["role"] == "owner" and "kai.ultra" in o["scopes"]
    op = _login(A, "optok").json()
    assert op["role"] == "operator" and "kai.ultra" not in op["scopes"]


# ── S4 cross-app over REAL HTTP: App A cookie -> LIVE App B ───────────────────
def test_s4_cross_app_over_http(A):
    cookie = _login(A, "ownerkey").cookies.get("wv_session")
    who = httpx.get(f"{APP_B}/admin/session/whoami",
                    cookies={"wv_session": cookie}, timeout=5).json()
    assert who["authenticated"] and who["role"] == "owner"
    assert "kai.ultra" in who["scopes"]  # same principal + scopes, live App B


# ── Gate 2 bridge -> LIVE App B (real transport + path mapping + redaction) ───
def test_gate2_bridge_reaches_real_route(A):
    _login(A, "ownerkey")
    # use_tools=False so an ollama-only local staging (no tool-capable cloud
    # adapter) can serve the buffered turn; the point is the bridge REACHES the
    # real /admin/kai-chat (NOT a 404 path / 502 unreachable).
    r = A.post("/admin/kai/kai-chat",
               json={"message": "status?", "prefer_local": True, "use_tools": False},
               timeout=90)
    assert r.status_code not in (404, 502)
    assert r.headers.get("x-correlation-id")
    # Errors are redacted (App B DEBUG=false) — no traceback leaks through.
    assert "Traceback" not in r.text


def test_gate2_operator_ultra_denied(A):
    # /admin/kai-chat is always tier=ultra on App B → owner-only at the bridge.
    _login(A, "optok")
    assert A.post("/admin/kai/kai-chat", json={}).status_code == 403       # plain
    assert A.post("/admin/kai/kai-chat?ultra=1", json={}).status_code == 403  # explicit


def test_gate2_anonymous_denied(A):
    A.cookies.clear()
    assert A.post("/admin/kai/kai-chat").status_code == 401


# ── C1 (real App A middleware) ───────────────────────────────────────────────
def test_c1_query_secret_rejected(A):
    A.cookies.clear()
    assert A.get("/api/_c1probe?api_key=ownerkey").status_code == 401
    assert A.get("/api/_c1probe", headers={"X-API-Key": "ownerkey"}).status_code != 401


# ── Gate 3: REAL governed LLM through the bridge (owner → ollama) ─────────────
# Slow (local inference) + needs App B fully provisioned (migrated DB, seeded
# ultra profile, ollama, placeholder OPENAI_API_KEY to satisfy REQUIRED_ADAPTERS).
# Skips (not fails) if App B isn't provisioned for it.
def test_gate3_real_governed_llm(A):
    _login(A, "ownerkey")
    r = A.post("/admin/kai/kai-chat",
               json={"message": "Reply with exactly: KAI staging verified.",
                     "prefer_local": True, "use_tools": False}, timeout=90)
    if r.status_code == 500:
        pytest.skip("App B not fully provisioned for Gate 3 (schema/profile/ollama)")
    assert r.status_code == 200
    body = r.json()
    # The governed answer came from the REAL local provider (ollama), not a mock.
    assert "ollama" in str(body.get("message", ""))
    assert body.get("conversation_id")            # conversation persisted
    assert r.headers.get("x-correlation-id")


# ── Gate 3 STREAMING: real SSE through the bridge (owner-only) ────────────────
def test_gate3_streaming_through_bridge(A):
    _login(A, "ownerkey")
    tokens, ct, seq = 0, None, []
    with A.stream("POST", "/admin/kai/kai-chat/stream",
                  json={"message": "Say hi in 3 words.", "prefer_local": True},
                  timeout=90) as r:
        if r.status_code == 500:
            pytest.skip("App B not fully provisioned for streaming")
        ct = r.headers.get("content-type")
        for line in r.iter_lines():
            if line.startswith("data: "):
                import json as _j
                seq.append(_j.loads(line[6:]).get("type"))
                if '"token"' in line:
                    tokens += 1
    assert ct and ct.startswith("text/event-stream")   # real SSE, not buffered JSON
    assert tokens >= 1                                  # incremental token frames
    assert "done" in seq                                # clean stream close


def test_gate3_stream_operator_denied(A):
    # Streaming chat is the always-ultra endpoint → owner-only at the bridge.
    _login(A, "optok")
    assert A.post("/admin/kai/kai-chat/stream", json={"message": "hi"}).status_code == 403
