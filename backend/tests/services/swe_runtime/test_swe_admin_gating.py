"""SWE admin gating: scope-root separation (swepush disjoint from swe) and the
non-prod-only mount allow-list."""
from app.services.governance.actions import is_scope_enabled
from app.services.swe_runtime.config import swe_admin_enabled


def test_swepush_scope_not_enabled_by_swe_wildcard(monkeypatch):
    # The SWE module wildcard (KAI_SCOPE_SWE) must NOT reach the destructive
    # push scope — that is the whole reason push lives under the SWEPUSH root.
    monkeypatch.setenv("KAI_SCOPE_SWE", "1")
    monkeypatch.delenv("KAI_SCOPE_SWEPUSH", raising=False)
    monkeypatch.delenv("KAI_SCOPE_SWEPUSH_EXECUTE", raising=False)
    assert is_scope_enabled("swe.plan") is True            # wildcard reaches swe.*
    assert is_scope_enabled("swe.brain.execute") is True
    assert is_scope_enabled("swepush.execute") is False    # disjoint root — refused


def test_swepush_scope_enabled_only_explicitly(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_SWE", raising=False)
    monkeypatch.setenv("KAI_SCOPE_SWEPUSH_EXECUTE", "1")
    assert is_scope_enabled("swepush.execute") is True
    assert is_scope_enabled("swe.plan") is False


def test_swe_admin_mount_allowlist(monkeypatch):
    from app.config import settings
    monkeypatch.delenv("ENV", raising=False)
    for env in ("development", "dev", "local", "test", "testing", "ci"):
        monkeypatch.setattr(settings, "APP_ENV", env)
        assert swe_admin_enabled() is True, env
    for env in ("production", "prod", "staging", "", "weird"):
        monkeypatch.setattr(settings, "APP_ENV", env)
        assert swe_admin_enabled() is False, env


def test_env_prod_marker_vetoes_nonprod_app_env(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setenv("ENV", "production")
    assert swe_admin_enabled() is False
