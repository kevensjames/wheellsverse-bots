"""Router selection tests — mock adapters, no API calls or DB."""
import uuid
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from app.services.router.router import Router
from app.services.router.types import CompletionResult, Intent


@dataclass
class MockAdapter:
    name: str
    model: str = "mock-model"

    def complete(self, messages, **kwargs):
        return CompletionResult(
            content=f"reply-from-{self.name}",
            adapter=self.name,
            model=self.model,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            latency_ms=50,
        )

    def stream(self, messages, **kwargs) -> Iterator[str]:
        for word in ["hello", " ", "from", " ", self.name]:
            yield word


@pytest.fixture()
def adapters():
    return {
        "openai": MockAdapter("openai"),
        "anthropic": MockAdapter("anthropic"),
        "perplexity": MockAdapter("perplexity"),
        "ollama": MockAdapter("ollama"),
        "cloudflare": MockAdapter("cloudflare"),
    }


@pytest.fixture()
def fake_tracker():
    tracker = MagicMock()
    tracker.over_daily_cap.return_value = False
    return tracker


@pytest.fixture()
def router(adapters, fake_tracker):
    return Router(adapters=adapters, spend_tracker=fake_tracker)


def test_code_routes_to_anthropic(router):
    assert router.select(Intent.CODE, uuid.uuid4()).name == "anthropic"


def test_realtime_routes_to_perplexity(router):
    assert router.select(Intent.REALTIME, uuid.uuid4()).name == "perplexity"


def test_general_routes_to_openai(router):
    assert router.select(Intent.GENERAL, uuid.uuid4()).name == "openai"


def test_simple_routes_to_cloudflare(router):
    assert router.select(Intent.SIMPLE, uuid.uuid4()).name == "cloudflare"


def test_simple_falls_back_to_openai_when_cloudflare_missing(fake_tracker):
    """SIMPLE prefers cloudflare; without it, degrade to openai (don't crash)."""
    r = Router(adapters={"openai": MockAdapter("openai")}, spend_tracker=fake_tracker)
    assert r.select(Intent.SIMPLE, uuid.uuid4()).name == "openai"


def test_prefer_local_overrides_intent(router):
    chosen = router.select(Intent.CODE, uuid.uuid4(), prefer_local=True)
    assert chosen.name == "ollama"


def test_over_daily_cap_forces_local(adapters, fake_tracker):
    fake_tracker.over_daily_cap.return_value = True
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    assert r.select(Intent.CODE, uuid.uuid4()).name == "ollama"


def test_missing_openai_raises(fake_tracker):
    """Only openai is structurally required — it's the fallback for unknown
    intents. Missing perplexity / ollama / anthropic should NOT raise;
    select() degrades to openai instead (tested in test_select_*)."""
    with pytest.raises(ValueError, match="missing adapters"):
        Router(adapters={"ollama": MockAdapter("ollama")}, spend_tracker=fake_tracker)


def test_missing_optional_adapter_does_not_raise(fake_tracker):
    """Missing perplexity is fine — graceful degradation."""
    Router(adapters={"openai": MockAdapter("openai")}, spend_tracker=fake_tracker)


def test_select_falls_back_to_openai_when_specialised_missing(fake_tracker):
    """REALTIME intent prefers perplexity; with perplexity absent, falls back."""
    r = Router(adapters={"openai": MockAdapter("openai")}, spend_tracker=fake_tracker)
    fake_tracker.over_daily_cap.return_value = False
    assert r.select(Intent.REALTIME, uuid.uuid4()).name == "openai"


def test_complete_logs_spend(router, fake_tracker):
    result = router.complete(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result.content == "reply-from-openai"
    fake_tracker.log_result.assert_called_once()


def test_complete_logs_failure(adapters, fake_tracker):
    class BoomAdapter(MockAdapter):
        def complete(self, messages, **kwargs):
            raise RuntimeError("boom")

    adapters["openai"] = BoomAdapter("openai")
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    with pytest.raises(RuntimeError):
        r.complete(user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hi"}])
    fake_tracker.log_call.assert_called()
    assert fake_tracker.log_call.call_args.kwargs["success"] is False


# ─── runtime fallback: local adapter fails → retry on cloud ──────────


def _boom(name):
    class _B(MockAdapter):
        def complete(self, messages, **kwargs):
            raise RuntimeError(f"{name} down")
    return _B(name)


def test_runtime_fallback_helper(router):
    # only a failing LOCAL adapter has a distinct cloud fallback
    assert router._runtime_fallback(router.adapters["ollama"]).name == "openai"
    assert router._runtime_fallback(router.adapters["openai"]) is None
    assert router._runtime_fallback(router.adapters["anthropic"]) is None


def test_prefer_local_failure_falls_back_to_cloud(adapters, fake_tracker):
    # a wedged/failing local model must NOT propagate — retry once on openai
    adapters["ollama"] = _boom("ollama")
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    result = r.complete(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hi"}],
        prefer_local=True,
    )
    assert result.content == "reply-from-openai"  # fell back to cloud
    # the local failure was logged before the cloud retry succeeded
    assert fake_tracker.log_call.call_args_list[0].kwargs["success"] is False
    fake_tracker.log_result.assert_called_once()


def test_prefer_local_fallback_also_failing_raises(adapters, fake_tracker):
    # if cloud ALSO fails, propagate — no infinite retry, both failures logged
    adapters["ollama"] = _boom("ollama")
    adapters["openai"] = _boom("openai")
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    with pytest.raises(RuntimeError):
        r.complete(
            user_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "hi"}],
            prefer_local=True,
        )
    assert fake_tracker.log_call.call_count >= 2


def test_cloud_failure_does_not_fall_back(adapters, fake_tracker):
    # openai failing is terminal (it IS the fallback target) — no silent loop
    adapters["openai"] = _boom("openai")
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    with pytest.raises(RuntimeError):
        r.complete(user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hi"}])


def test_chat_fails_over_to_anthropic(adapters, fake_tracker):
    # OpenAI tool-brain down (429) → chat() FAILS OVER to Anthropic, KEEPING
    # tools (not degrading to a plain local answer). The key 429-resilience path.
    from unittest.mock import MagicMock
    adapters["openai"] = _boom("openai")  # primary tool brain down
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    reg = MagicMock()
    reg.openai_schema.return_value = []
    reg.anthropic_schema.return_value = []
    res = r.chat(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hi"}],
        tool_registry=reg, tool_context=MagicMock(),
    )
    assert res.adapter == "anthropic"  # failed over to the other tool brain
    assert res.content == "reply-from-anthropic"


def test_chat_both_brains_down_degrades_to_local(adapters, fake_tracker):
    # BOTH tool brains down → degrade to a PLAIN local answer (no tools).
    from unittest.mock import MagicMock
    adapters["openai"] = _boom("openai")
    adapters["anthropic"] = _boom("anthropic")
    r = Router(adapters=adapters, spend_tracker=fake_tracker)
    reg = MagicMock()
    reg.openai_schema.return_value = []
    reg.anthropic_schema.return_value = []
    res = r.chat(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hi"}],
        tool_registry=reg, tool_context=MagicMock(),
    )
    assert res.adapter == "ollama"  # both brains failed → plain local
    assert res.content == "reply-from-ollama"


def test_chat_no_local_reraises(fake_tracker):
    # No local fallback configured → the tool-adapter failure propagates.
    from unittest.mock import MagicMock

    class _Boom(MockAdapter):
        def complete(self, messages, **kwargs):
            raise RuntimeError("openai down")
    r = Router(adapters={"openai": _Boom("openai")}, spend_tracker=fake_tracker)
    reg = MagicMock(); reg.openai_schema.return_value = []
    with pytest.raises(RuntimeError):
        r.chat(user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hi"}],
               tool_registry=reg, tool_context=MagicMock())


def test_ollama_timeout_env_configurable(monkeypatch):
    from app.services.router.adapters.ollama_adapter import OllamaAdapter
    monkeypatch.setenv("OLLAMA_TIMEOUT", "30")
    assert OllamaAdapter().timeout == 30.0
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    assert OllamaAdapter().timeout == 120.0
    assert OllamaAdapter(timeout=7).timeout == 7.0  # explicit arg still wins


def test_stream_yields_deltas(router):
    deltas = list(
        router.stream(
            user_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "say hi"}],
        )
    )
    assert "".join(deltas) == "hello from openai"
