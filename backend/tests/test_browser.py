"""Browser (computer-control) tests.

The policy layer (config.check_url) is the security-critical core, so it gets
the most coverage: kill-switch, scheme allowlist, SSRF guard, domain allowlist.
log + session-guard + tool + admin endpoints follow.

No real Playwright is launched in unit tests (too heavy/flaky) — the session
guard tests assert policy fires BEFORE any I/O, and tool/endpoint tests stub
the read with a monkeypatch. The real browser is exercised by the live smoke.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.browser import config as bc
from app.services.browser import log as blog
from app.services.browser import session as bsession

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _enabled_with_allowlist(monkeypatch):
    """Default test posture: browser enabled, allowlist = example.com + HN.
    Individual tests override (disable, empty allowlist, etc.)."""
    monkeypatch.setenv("KAI_BROWSER_ENABLED", "1")
    monkeypatch.setenv("KAI_BROWSER_ALLOWLIST", "example.com,news.ycombinator.com")
    yield


@pytest.fixture(autouse=True)
def _isolated_browser_log(tmp_path, monkeypatch):
    p = tmp_path / "actions.jsonl"
    monkeypatch.setattr(blog, "BROWSER_LOG_PATH", p)
    yield p


# ─── policy: kill-switch ─────────────────────────────────────────────


def test_check_url_disabled_raises(monkeypatch):
    monkeypatch.delenv("KAI_BROWSER_ENABLED", raising=False)
    with pytest.raises(bc.BrowserPolicyError, match="disabled"):
        bc.check_url("https://example.com")


def test_browser_enabled_default_off(monkeypatch):
    monkeypatch.delenv("KAI_BROWSER_ENABLED", raising=False)
    assert bc.browser_enabled() is False


# ─── policy: scheme allowlist ────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,<h1>x</h1>",
    "about:blank",
    "ftp://example.com/x",
])
def test_check_url_blocks_bad_schemes(url):
    with pytest.raises(bc.BrowserPolicyError, match="scheme"):
        bc.check_url(url)


# ─── policy: SSRF guard ──────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://127.0.0.1:8001/admin/planning/stats",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://[::1]/",
])
def test_check_url_blocks_ssrf(url, monkeypatch):
    # Even if the operator somehow allowlists these, the SSRF guard wins.
    monkeypatch.setenv("KAI_BROWSER_ALLOWLIST",
                       "localhost,127.0.0.1,10.0.0.5,192.168.1.1,169.254.169.254,::1")
    with pytest.raises(bc.BrowserPolicyError, match="SSRF|localhost"):
        bc.check_url(url)


# ─── policy: domain allowlist ────────────────────────────────────────


def test_check_url_allows_allowlisted_and_subdomains():
    assert bc.check_url("https://example.com/page") == "https://example.com/page"
    assert bc.check_url("https://www.example.com") == "https://www.example.com"
    assert bc.check_url("https://news.ycombinator.com/news") == "https://news.ycombinator.com/news"


def test_check_url_blocks_non_allowlisted():
    with pytest.raises(bc.BrowserPolicyError, match="not allowlisted"):
        bc.check_url("https://evil.com/steal")


def test_check_url_defaults_bare_host_to_https():
    # operator types "example.com" with no scheme → normalized to https
    assert bc.check_url("example.com") == "https://example.com"
    assert bc.check_url("example.com/path?q=1") == "https://example.com/path?q=1"


def test_check_url_bare_non_allowlisted_gives_truthful_reason():
    # "app.wheellsverse.com/admin" (no scheme, not allowlisted) must report the
    # ALLOWLIST reason, not a confusing scheme error.
    with pytest.raises(bc.BrowserPolicyError, match="not allowlisted"):
        bc.check_url("app.wheellsverse.com/admin")


def test_normalization_does_not_mask_dangerous_schemes():
    # scheme-bearing inputs keep their scheme and are still rejected as schemes
    for url in ("javascript:alert(1)", "data:text/html,<h1>x</h1>", "file:///etc/passwd"):
        with pytest.raises(bc.BrowserPolicyError, match="scheme"):
            bc.check_url(url)


def test_check_url_empty_allowlist_blocks_everything(monkeypatch):
    monkeypatch.setenv("KAI_BROWSER_ALLOWLIST", "")
    with pytest.raises(bc.BrowserPolicyError, match="allowlist is empty"):
        bc.check_url("https://example.com")


def test_host_allowed_suffix_match():
    allow = ["example.com"]
    assert bc.host_allowed("example.com", allow)
    assert bc.host_allowed("sub.example.com", allow)
    assert not bc.host_allowed("notexample.com", allow)
    assert not bc.host_allowed("example.com.evil.com", allow)


def test_allowlist_parsing(monkeypatch):
    monkeypatch.setenv("KAI_BROWSER_ALLOWLIST", " example.com , .news.ycombinator.com ,")
    assert bc.allowlist() == ["example.com", "news.ycombinator.com"]


# ─── session guard: policy fires before any browser I/O ──────────────


def test_read_page_rechecks_policy_when_disabled(monkeypatch):
    monkeypatch.delenv("KAI_BROWSER_ENABLED", raising=False)
    # Must raise on policy, NOT attempt to launch playwright.
    with pytest.raises(bc.BrowserPolicyError):
        bsession.read_page("https://example.com")


def test_read_page_rechecks_policy_not_allowlisted():
    with pytest.raises(bc.BrowserPolicyError):
        bsession.read_page("https://evil.com")


# ─── action log ──────────────────────────────────────────────────────


def test_log_record_and_list_newest_first():
    blog.record_action(kind="navigate", status="ok", url="https://example.com", detail="Example")
    blog.record_action(kind="blocked", status="blocked", url="https://evil.com", detail="not allowlisted")
    rows = blog.list_actions()
    assert len(rows) == 2
    assert rows[0]["kind"] == "blocked"   # newest first
    assert rows[1]["url"] == "https://example.com"


def test_log_propose_write_payload():
    blog.record_action(
        kind="propose_write", status="ok", url="https://example.com",
        detail="would submit search",
        proposed={"action": "type", "selector": "#q", "value": "kai"},
    )
    rows = blog.list_actions()
    assert rows[0]["proposed"]["selector"] == "#q"


def test_log_stats():
    blog.record_action(kind="navigate", status="ok", url="https://example.com")
    blog.record_action(kind="navigate", status="ok", url="https://news.ycombinator.com")
    blog.record_action(kind="propose_write", status="ok")
    s = blog.stats()
    assert s["total"] == 3
    assert s["by_kind"]["navigate"] == 2
    assert s["last_url"] == "https://news.ycombinator.com"


def test_log_never_raises_on_bad_path(monkeypatch):
    monkeypatch.setattr(blog, "BROWSER_LOG_PATH", blog.Path("/nonexistent-dir/x/y.jsonl"))
    # Should not raise even though the dir doesn't exist.
    rec = blog.record_action(kind="navigate", status="ok", url="https://example.com")
    assert rec.kind == "navigate"


# ─── browser tool (read + propose, session stubbed) ──────────────────

from app.services.tools.base import ToolContext, ToolError  # noqa: E402
from app.services.tools.browser_tool import BrowserTool  # noqa: E402


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_browser_tool_disabled_not_constructable(monkeypatch):
    monkeypatch.delenv("KAI_BROWSER_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        BrowserTool()


def test_browser_tool_read_blocked_logs_and_raises():
    with pytest.raises(ToolError, match="blocked"):
        BrowserTool().execute(_ctx(), action="read", url="https://evil.com")
    assert blog.list_actions()[0]["kind"] == "blocked"


def test_browser_tool_read_success_stubbed(monkeypatch):
    monkeypatch.setattr(bsession, "read_page", lambda u: {
        "url": u, "title": "Example Domain", "text": "hello", "links": []})
    out = BrowserTool().execute(_ctx(), action="read", url="https://example.com")
    assert out["title"] == "Example Domain"
    assert out["text"] == "hello"
    row = blog.list_actions()[0]
    assert row["kind"] == "navigate" and row["status"] == "ok"


def test_browser_tool_read_unavailable(monkeypatch):
    def _boom(u):
        raise bsession.BrowserUnavailable("chromium missing")
    monkeypatch.setattr(bsession, "read_page", _boom)
    with pytest.raises(ToolError, match="browser error"):
        BrowserTool().execute(_ctx(), action="read", url="https://example.com")


def test_browser_tool_propose_write_is_dry_run():
    out = BrowserTool().execute(
        _ctx(), action="propose_write", action_type="type",
        selector="#q", value="kai", description="search for kai",
    )
    assert "DRY RUN" in out["note"]
    assert out["proposed"]["selector"] == "#q"
    assert blog.list_actions()[0]["kind"] == "propose_write"


def test_browser_tool_unknown_action():
    with pytest.raises(ToolError):
        BrowserTool().execute(_ctx(), action="click")


# ─── admin endpoints ─────────────────────────────────────────────────


@pytest.fixture
def _isolated_audit(monkeypatch):
    import tempfile
    from app.services.governance import audit_log as _al
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


def test_admin_browser_status_requires_token(client):
    assert client.get("/admin/browser/status").status_code == 403


def test_admin_browser_status_reports_enabled_and_allowlist(client):
    r = client.get("/admin/browser/status", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert "example.com" in body["allowlist"]


def test_admin_browser_log_endpoint(client):
    blog.record_action(kind="navigate", status="ok", url="https://example.com", detail="Example")
    r = client.get("/admin/browser/log", headers=ADMIN_HEADERS)
    assert r.json()["count"] == 1


def test_admin_navigate_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_BROWSER", raising=False)
    monkeypatch.delenv("KAI_SCOPE_BROWSER_NAVIGATE", raising=False)
    r = client.post("/admin/browser/navigate", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com"})
    assert r.status_code == 403


def test_admin_navigate_success_stubbed(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    monkeypatch.setattr(bsession, "read_page", lambda u: {
        "url": u, "title": "Example Domain", "text": "hi", "links": []})
    r = client.post("/admin/browser/navigate", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com"})
    assert r.status_code == 200
    assert r.json()["result"]["title"] == "Example Domain"
    assert blog.list_actions()[0]["kind"] == "navigate"


def test_admin_navigate_non_allowlisted_400(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    r = client.post("/admin/browser/navigate", headers=ADMIN_HEADERS,
                    json={"url": "https://evil.com"})
    assert r.status_code == 400
    assert blog.list_actions()[0]["kind"] == "blocked"


def test_admin_propose_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_BROWSER", raising=False)
    monkeypatch.delenv("KAI_SCOPE_BROWSER_PROPOSE", raising=False)
    r = client.post("/admin/browser/propose", headers=ADMIN_HEADERS,
                    json={"action_type": "click", "selector": "#x", "description": "x"})
    assert r.status_code == 403


def test_admin_propose_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    r = client.post("/admin/browser/propose", headers=ADMIN_HEADERS,
                    json={"action_type": "type", "selector": "#q", "value": "kai",
                          "description": "search"})
    assert r.status_code == 200
    assert "DRY RUN" in r.json()["note"]
    assert blog.list_actions()[0]["kind"] == "propose_write"


# ─── envelope B: write execution (gates fire before any browser launch) ──


def test_write_enabled_default_off(monkeypatch):
    monkeypatch.delenv("KAI_BROWSER_WRITE_ENABLED", raising=False)
    assert bc.write_enabled() is False


def test_execute_actions_blocked_when_writes_disabled(monkeypatch):
    # browser enabled + allowlisted, but write kill-switch off → raise, no launch
    monkeypatch.delenv("KAI_BROWSER_WRITE_ENABLED", raising=False)
    with pytest.raises(bc.BrowserPolicyError, match="writes are disabled"):
        bsession.execute_actions("https://example.com",
                                 [{"type": "click", "selector": "#x"}])


def test_execute_actions_bad_action_type(monkeypatch):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    with pytest.raises(bc.BrowserPolicyError, match="not allowed"):
        bsession.execute_actions("https://example.com",
                                 [{"type": "evileval", "selector": "#x"}])


def test_execute_actions_non_allowlisted(monkeypatch):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    with pytest.raises(bc.BrowserPolicyError):
        bsession.execute_actions("https://evil.com",
                                 [{"type": "click", "selector": "#x"}])


def test_execute_actions_empty(monkeypatch):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    with pytest.raises(bc.BrowserPolicyError, match="no actions"):
        bsession.execute_actions("https://example.com", [])


def test_admin_execute_write_disabled_403(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    monkeypatch.delenv("KAI_BROWSER_WRITE_ENABLED", raising=False)
    r = client.post("/admin/browser/execute", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com",
                          "actions": [{"type": "click", "selector": "#x"}],
                          "approved": True})
    assert r.status_code == 403
    assert "writes are disabled" in r.json()["detail"]


def test_admin_execute_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    monkeypatch.delenv("KAI_SCOPE_BROWSER", raising=False)
    monkeypatch.delenv("KAI_SCOPE_BROWSER_EXECUTE", raising=False)
    r = client.post("/admin/browser/execute", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com",
                          "actions": [{"type": "click", "selector": "#x"}],
                          "approved": True})
    assert r.status_code == 403


def test_admin_execute_no_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    r = client.post("/admin/browser/execute", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com",
                          "actions": [{"type": "click", "selector": "#x"}],
                          "approved": False})
    assert r.status_code == 409


# ─── envelope B v2: per-request nav-guard policy ─────────────────────


_ALLOW = ["example.com", "news.ycombinator.com"]


@pytest.mark.parametrize("url,is_nav,should_block", [
    ("https://example.com/page", True, False),       # allowlisted nav → allow
    ("https://www.example.com/x", True, False),      # allowlisted subdomain nav → allow
    ("https://iana.org/help", True, True),           # off-allowlist NAV → block
    ("https://iana.org/logo.png", False, False),     # off-allowlist SUB-RESOURCE → allow (render)
    ("http://169.254.169.254/latest", False, True),  # cloud-metadata sub-resource → block (SSRF)
    ("http://localhost/x", False, True),             # localhost sub-resource → block
    ("http://10.0.0.1/x", True, True),               # private IP nav → block
    ("javascript:alert(1)", True, True),             # bad scheme → block
])
def test_request_blocked_reason(url, is_nav, should_block):
    reason = bc.request_blocked_reason(url, allow=_ALLOW, is_main_nav=is_nav)
    assert (reason is not None) == should_block, f"{url} nav={is_nav} → {reason!r}"


def test_request_blocked_reason_offallowlist_subresource_allowed():
    # a CDN/font on a public non-allowlisted host must NOT be blocked (pages render)
    assert bc.request_blocked_reason("https://cdn.jsdelivr.net/x.js",
                                     allow=_ALLOW, is_main_nav=False) is None


def test_admin_execute_success_stubbed(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_BROWSER_WRITE_ENABLED", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER", "1")
    monkeypatch.setenv("KAI_SCOPE_BROWSER_EXECUTE", "1")  # destructive: exact scope required
    monkeypatch.setattr(bsession, "execute_actions", lambda url, actions: {
        "results": [{"type": "click", "selector": "#more", "ok": True}],
        "final": {"url": "https://example.com/more", "title": "More", "text": "ok"},
    })
    r = client.post("/admin/browser/execute", headers=ADMIN_HEADERS,
                    json={"url": "https://example.com",
                          "actions": [{"type": "click", "selector": "#more"}],
                          "approved": True})
    assert r.status_code == 200
    assert r.json()["final"]["url"] == "https://example.com/more"
    assert blog.list_actions()[0]["kind"] == "execute_write"
