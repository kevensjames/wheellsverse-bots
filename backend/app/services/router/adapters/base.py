"""Base adapter Protocol + pricing reference."""
from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from app.services.router.types import CompletionResult


# Pricing per 1M tokens (input, output). Single source of truth.
# Verify against each provider's pricing page before any rollout.
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Anthropic
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    # Perplexity
    "sonar-pro": (3.00, 15.00),
    "sonar": (1.00, 1.00),
    # Ollama (local — no cost)
    "llama3.1:8b": (0.0, 0.0),
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a call. Returns 0.0 for unknown models (and silently)."""
    if model not in PRICING:
        return 0.0
    in_price, out_price = PRICING[model]
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


@runtime_checkable
class Adapter(Protocol):
    """All adapters expose the same surface."""

    name: str
    model: str

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult: ...

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]: ...
