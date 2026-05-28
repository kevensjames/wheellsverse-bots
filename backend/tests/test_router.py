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


def test_stream_yields_deltas(router):
    deltas = list(
        router.stream(
            user_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "say hi"}],
        )
    )
    assert "".join(deltas) == "hello from openai"
