"""Regression: the health/readiness environment label must be DERIVED from the
canonical config (settings.APP_ENV) — never a hardcoded string. Local defaults to
'development'; staging reports 'staging'; production reports 'production'. This
guards the Pass-5 LOW where /health reported 'development' on staging.

Run: DATABASE_URL=... python3 -m pytest app/test_health_env.py
"""
import os


def test_app_env_defaults_to_development(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://localhost/x"))
    from app.config import Settings
    # _env_file=None so a developer's local .env can't mask the true default
    assert Settings(_env_file=None).APP_ENV == "development"


def test_app_env_reports_staging_then_production(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://localhost/x"))
    monkeypatch.setenv("APP_ENV", "staging")
    assert Settings(_env_file=None).APP_ENV == "staging"
    monkeypatch.setenv("APP_ENV", "production")
    assert Settings(_env_file=None).APP_ENV == "production"


def test_health_handler_reflects_configured_env(monkeypatch):
    """The /health handler must return settings.APP_ENV verbatim — not a literal."""
    from app import main
    for env in ("development", "staging", "production"):
        monkeypatch.setattr(main.settings, "APP_ENV", env)
        assert main.health() == {"status": "ok", "env": env}
