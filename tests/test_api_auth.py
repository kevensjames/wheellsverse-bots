"""Deny-by-default authorization tests for the Core API middleware.

Verifies that the ~40 unauthenticated state-changing operator routes the audit
flagged now require the operator key, while reads and genuinely-public routes
(webhooks, login, self-authing /api/nx/*) are unchanged.

Imports only the pure `core.api_auth` (no FastAPI / the 633 KB app), so it runs
anywhere.
"""
import importlib

import pytest

aa = importlib.import_module("core.api_auth")


@pytest.mark.parametrize("path,method,locked", [
    # dangerous operator mutations → locked
    ("/api/factory/reset", "DELETE", True),
    ("/api/factory/start", "POST", True),
    ("/api/shopify/discount", "POST", True),
    ("/api/shopify/products", "POST", True),
    ("/api/shopify/products/123", "PUT", True),        # path-param prefix
    ("/api/shopify/products/123", "DELETE", True),
    ("/api/shopify/media/generate/42", "POST", True),  # path-param prefix
    ("/api/shopify/agents/start", "POST", True),
    ("/api/narai-autopilot/start", "POST", True),
    ("/api/narai-autopilot/queue/2/mark_done", "POST", True),
    ("/api/sa/setup-boutique", "POST", True),
    ("/api/narai/run_bot", "POST", True),
    ("/api/narai/schedules/7/trigger", "POST", True),  # path-param prefix
    ("/api/qc/review", "POST", True),
    # same routes via a READ method → NOT locked (reads unchanged)
    ("/api/factory/reset", "GET", False),
    ("/api/shopify/products", "GET", False),
    # genuinely public / self-authing routes → NOT locked
    ("/api/shopify/webhook", "POST", False),
    ("/api/nx/subscribe", "POST", False),
    ("/api/nx/posts/9", "DELETE", False),
    ("/api/v2/narai/auth/login", "POST", False),
])
def test_is_locked_mutation(path, method, locked):
    assert aa.is_locked_mutation(path, method) is locked


@pytest.mark.parametrize("path,method,existing_public,require", [
    # locked mutations must require the key EVEN THOUGH the legacy allowlist marks
    # them public (that mislabelling is the bug being fixed)
    ("/api/factory/reset", "DELETE", True, True),
    ("/api/shopify/discount", "POST", True, True),
    ("/api/shopify/products/5", "PUT", True, True),
    # genuinely public routes stay public
    ("/api/shopify/webhook", "POST", True, False),
    ("/api/nx/subscribe", "POST", True, False),
    ("/api/health", "GET", True, False),
    # reads to locked routes stay public (unchanged)
    ("/api/shopify/products", "GET", True, False),
    # default behavior preserved: unknown /api route with no public status → require
    ("/api/something/new", "POST", False, True),
    ("/api/something/new", "GET", False, True),
    # non-/api paths are never gated here
    ("/dashboard", "POST", False, False),
    ("/admin", "GET", False, False),
])
def test_requires_api_key(path, method, existing_public, require):
    assert aa.requires_api_key(path, method, existing_public) is require
