"""Stage 6 security-headers tests.

Asserts the SecurityHeadersMiddleware stamps the expected headers on every
response and gates HSTS on APP_ENV correctly.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware


def _build_app(app_env: str) -> FastAPI:
    """Minimal app — we don't want the real main.py middleware stack here
    because asserting headers requires isolating what THIS middleware adds."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, app_env=app_env)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


# --- non-prod: every header EXCEPT HSTS ---

def test_security_headers_set_in_non_prod():
    client = TestClient(_build_app("development"))
    r = client.get("/ping")
    assert r.status_code == 200

    h = r.headers
    assert "content-security-policy" in h
    assert "default-src 'self'" in h["content-security-policy"]
    assert "script-src 'self'" in h["content-security-policy"]
    # frame-ancestors is an allowlist (not 'none') so the AI Command Center at
    # app.wheellsverse.com can iframe KAI cross-origin (commit 48ddb16).
    assert "frame-ancestors 'self' https://app.wheellsverse.com https://wheellsverse.com" \
        in h["content-security-policy"]
    assert h.get("x-content-type-options") == "nosniff"
    # X-Frame-Options is intentionally NOT set — it has only DENY/SAMEORIGIN
    # (no cross-origin allowlist), which would block the Command Center iframe.
    # CSP frame-ancestors above is the modern, allowlist-capable replacement.
    assert "x-frame-options" not in h
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in h.get("permissions-policy", "")
    # Critical: HSTS must NOT be set in dev — browsers would pin HTTP→HTTPS
    # on localhost and break subsequent dev sessions.
    assert "strict-transport-security" not in h


# --- prod: same headers PLUS HSTS ---

@pytest.mark.parametrize("env", ["production", "staging", "prod", "PRODUCTION"])
def test_hsts_only_in_production(env):
    client = TestClient(_build_app(env))
    r = client.get("/ping")
    h = r.headers
    assert "strict-transport-security" in h
    assert "max-age=" in h["strict-transport-security"]
    assert "includeSubDomains" in h["strict-transport-security"]


@pytest.mark.parametrize("env", ["development", "dev", "local", "test"])
def test_hsts_not_set_in_dev_envs(env):
    client = TestClient(_build_app(env))
    r = client.get("/ping")
    assert "strict-transport-security" not in r.headers


# --- explicit route headers win ---

def test_route_set_header_is_not_overridden():
    """If a route explicitly sets one of our headers, don't clobber it."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, app_env="production")

    @app.get("/custom")
    def custom():
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    r = TestClient(app).get("/custom")
    # The route's choice survives — middleware only adds when absent.
    assert r.headers.get("x-frame-options") == "SAMEORIGIN"


# --- real app integration ---

def test_real_app_has_security_headers():
    """The actual app.main.app must have the middleware mounted."""
    from app.main import app as real_app

    client = TestClient(real_app)
    r = client.get("/health")
    assert r.status_code == 200
    assert "content-security-policy" in r.headers
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert r.headers.get("x-content-type-options") == "nosniff"
    # X-Frame-Options intentionally removed in favor of CSP frame-ancestors
    # (cross-origin allowlist for the AI Command Center iframe).
    assert "x-frame-options" not in r.headers


def test_static_html_pages_get_headers():
    """The /nai-ui/*.html static files must carry security headers too —
    that's the whole point of CSP, it protects the rendered pages."""
    from app.main import app as real_app

    client = TestClient(real_app)
    r = client.get("/nai-ui/signup.html")
    assert r.status_code == 200
    assert "content-security-policy" in r.headers
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_csp_blocks_inline_script_intent():
    """Sanity: the CSP we set doesn't include 'unsafe-inline' — that's the
    whole point of moving the bindAuthForm() blocks to external -init.js
    files. If anyone re-adds 'unsafe-inline' this test catches it."""
    from app.main import app as real_app

    client = TestClient(real_app)
    r = client.get("/health")
    csp = r.headers.get("content-security-policy", "")
    assert "unsafe-inline" not in csp, (
        f"CSP contains 'unsafe-inline' — defeats XSS protection: {csp}"
    )
    assert "unsafe-eval" not in csp, (
        f"CSP contains 'unsafe-eval' — defeats XSS protection: {csp}"
    )
