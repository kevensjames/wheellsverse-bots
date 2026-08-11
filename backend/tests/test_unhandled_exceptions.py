"""Global unhandled-exception observability. Contract:
  - genuine 500s: logged + correlation id + generic body (no leak) + prod-only
    deduplicated, redacted alert;
  - HTTPException / cancellation preserved; alerts off in non-prod.
"""
import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.main as main
from app.main import unhandled_exception_handler


def _req(method="POST", path="/x"):
    return Request({"type": "http", "method": method, "path": path,
                    "headers": [], "query_string": b""})


def _run(exc, req=None):
    return asyncio.run(unhandled_exception_handler(req or _req(), exc))


# ── response shape (no leakage) ──────────────────────────────────────────────
def test_returns_generic_500_with_correlation_id():
    resp = _run(RuntimeError("db password=hunter2 leaked"))
    assert resp.status_code == 500
    import json
    body = json.loads(resp.body)
    assert body["detail"] == "Internal server error"
    assert len(body["correlation_id"]) == 12
    assert b"hunter2" not in resp.body  # exception text never reaches the client


# ── cancellation is never consumed ───────────────────────────────────────────
def test_cancelled_error_is_reraised_not_swallowed():
    with pytest.raises(asyncio.CancelledError):
        _run(asyncio.CancelledError())


# ── alert only in prod, deduplicated, redacted ──────────────────────────────
@pytest.fixture(autouse=True)
def _reset_dedup():
    main._last_unhandled_alert.clear()
    yield
    main._last_unhandled_alert.clear()


def test_no_alert_in_non_prod(monkeypatch):
    monkeypatch.setattr(main.settings, "APP_ENV", "test")
    calls = []
    monkeypatch.setattr("app.services.observability.notify", lambda t: calls.append(t))
    _run(RuntimeError("boom"))
    assert calls == []  # dev/test must not page the operator


def test_alert_fires_once_in_prod_and_is_redacted(monkeypatch):
    monkeypatch.setattr(main.settings, "APP_ENV", "production")
    calls = []
    monkeypatch.setattr("app.services.observability.notify", lambda t: calls.append(t))
    exc = RuntimeError("Authorization: Bearer ghs_abcdefghijklmnopqrstuvwxyz012345")
    _run(exc, _req(path="/kai/chat"))
    _run(exc, _req(path="/kai/chat"))  # same signature within the window
    assert len(calls) == 1                       # deduplicated
    assert "ghs_" not in calls[0]                # token redacted (the security property)
    assert "redacted" in calls[0]                # redaction happened (HTML-escaped in the alert)


# ── wired into an app: clean 500, HTTPException preserved ────────────────────
def _wired_app():
    a = FastAPI(debug=False)  # debug=False so the handler is invoked (not Starlette's traceback)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    return a


def test_wired_unhandled_returns_clean_500():
    a = _wired_app()

    @a.get("/boom")
    def boom():
        raise RuntimeError("internal secret sk-live_zzz")

    c = TestClient(a, raise_server_exceptions=False)
    r = c.get("/boom")
    assert r.status_code == 500
    assert r.json()["detail"] == "Internal server error"
    assert "secret" not in r.text and "sk-live_zzz" not in r.text


def test_wired_httpexception_is_not_swallowed():
    a = _wired_app()

    @a.get("/notfound")
    def nf():
        raise HTTPException(status_code=404, detail="nope")

    c = TestClient(a, raise_server_exceptions=False)
    r = c.get("/notfound")
    assert r.status_code == 404  # keeps its own handler — NOT converted to 500
