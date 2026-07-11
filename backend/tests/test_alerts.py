"""Unit tests for the rate-limited provider-degradation alerter."""
from app.services import alerts


def _capture(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.observability.notify", lambda text: sent.append(text))
    return sent


def test_provider_alert_dispatches(monkeypatch):
    alerts.reset_state()
    sent = _capture(monkeypatch)
    ok = alerts.provider_alert(
        provider="anthropic", exc=RuntimeError("x"), active_fallback="openai"
    )
    assert ok is True
    assert len(sent) == 1
    assert "anthropic" in sent[0]
    assert "openai" in sent[0]
    assert "RuntimeError" in sent[0]


def test_provider_alert_rate_limited_per_provider(monkeypatch):
    alerts.reset_state()
    monkeypatch.setenv("KAI_ALERT_MIN_INTERVAL_SECONDS", "3600")
    sent = _capture(monkeypatch)
    assert alerts.provider_alert(provider="openai", exc=RuntimeError("a"), active_fallback="ollama") is True
    # Second alert for the SAME provider within the window is suppressed.
    assert alerts.provider_alert(provider="openai", exc=RuntimeError("b"), active_fallback="ollama") is False
    assert len(sent) == 1


def test_distinct_providers_not_rate_limited(monkeypatch):
    alerts.reset_state()
    monkeypatch.setenv("KAI_ALERT_MIN_INTERVAL_SECONDS", "3600")
    sent = _capture(monkeypatch)
    assert alerts.provider_alert(provider="openai", exc=RuntimeError("a"), active_fallback="ollama") is True
    assert alerts.provider_alert(provider="anthropic", exc=RuntimeError("b"), active_fallback="ollama") is True
    assert len(sent) == 2


def test_zero_interval_allows_repeat(monkeypatch):
    alerts.reset_state()
    monkeypatch.setenv("KAI_ALERT_MIN_INTERVAL_SECONDS", "0")
    sent = _capture(monkeypatch)
    assert alerts.provider_alert(provider="openai", exc=RuntimeError("a"), active_fallback="ollama") is True
    assert alerts.provider_alert(provider="openai", exc=RuntimeError("b"), active_fallback="ollama") is True
    assert len(sent) == 2


def test_http_status_included(monkeypatch):
    alerts.reset_state()
    sent = _capture(monkeypatch)

    class RateLimited(Exception):
        status_code = 429

    alerts.provider_alert(provider="anthropic", exc=RateLimited("rate"), active_fallback="openai")
    assert "429" in sent[0]


def test_no_fallback_message(monkeypatch):
    alerts.reset_state()
    sent = _capture(monkeypatch)
    alerts.provider_alert(provider="openai", exc=RuntimeError("x"), active_fallback=None)
    assert "no fallback" in sent[0].lower()


def test_alert_never_raises(monkeypatch):
    alerts.reset_state()

    def boom(text):
        raise RuntimeError("telegram unreachable")

    monkeypatch.setattr("app.services.observability.notify", boom)
    # Must swallow the downstream failure and simply report False.
    assert alerts.provider_alert(provider="openai", exc=ValueError("x"), active_fallback=None) is False
