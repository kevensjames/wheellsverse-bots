"""Tests for multi-model router — uses mocked litellm to avoid real API calls."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_litellm_response():
    resp = MagicMock()
    resp.choices[0].message.content = "NarAI response"
    resp.usage.total_tokens = 42
    return resp


@pytest.mark.asyncio
async def test_call_fast_tier(mock_litellm_response):
    from infra.brain import router

    with patch("infra.brain.router.litellm.acompletion", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_litellm_response
        result = await router.call("quick question", tier="fast")

    assert result["content"] == "NarAI response"
    assert result["tokens"] == 42
    assert "model" in result


@pytest.mark.asyncio
async def test_call_deep_tier(mock_litellm_response):
    from infra.brain import router

    with patch("infra.brain.router.litellm.acompletion", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_litellm_response
        result = await router.call("analyze this market", tier="deep")

    assert result["content"] == "NarAI response"


@pytest.mark.asyncio
async def test_fallback_on_primary_failure(mock_litellm_response):
    from infra.brain import router

    call_count = 0

    async def flaky_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Primary model down")
        return mock_litellm_response

    with patch("infra.brain.router.litellm.acompletion", side_effect=flaky_call):
        result = await router.call("test fallback", tier="fast")

    assert result["content"] == "NarAI response"
    assert call_count == 2  # tried primary, fell back to first fallback


@pytest.mark.asyncio
async def test_all_models_fail():
    from infra.brain import router

    with patch(
        "infra.brain.router.litellm.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("all down"),
    ):
        with pytest.raises(RuntimeError, match="All models failed"):
            await router.call("test", tier="fast")


def test_set_config():
    from infra.brain import router
    router.set_config(temperature=0.3)
    assert router._config.temperature == 0.3
    router.set_config(temperature=0.7)  # reset
