from app.services.router.adapters import (
    PRICING,
    Adapter,
    AnthropicAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    PerplexityAdapter,
    calculate_cost,
)
from app.services.router.intent import classify_intent
from app.services.router.router import Router
from app.services.router.spend_tracker import SpendTracker
from app.services.router.types import (
    CompletionResult,
    Intent,
    Message,
    Role,
    to_message_dicts,
)


def build_default_router(session) -> Router:
    """Convenience factory — wires all four adapters with default models."""
    adapters: dict[str, Adapter] = {
        "openai": OpenAIAdapter(),
        "anthropic": AnthropicAdapter(),
        "perplexity": PerplexityAdapter(),
        "ollama": OllamaAdapter(),
    }
    return Router(adapters=adapters, spend_tracker=SpendTracker(session))


__all__ = [
    "Adapter",
    "AnthropicAdapter",
    "CompletionResult",
    "Intent",
    "Message",
    "OllamaAdapter",
    "OpenAIAdapter",
    "PRICING",
    "PerplexityAdapter",
    "Role",
    "Router",
    "SpendTracker",
    "build_default_router",
    "calculate_cost",
    "classify_intent",
    "to_message_dicts",
]
