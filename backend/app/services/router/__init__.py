import logging

from app.services.router.adapters import (
    PRICING,
    Adapter,
    AnthropicAdapter,
    CloudflareAdapter,
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
    ToolCallSpec,
    to_message_dicts,
)


logger = logging.getLogger(__name__)


def _try_adapter(name: str, factory):
    """Construct an adapter, returning None and logging a warning if its env
    isn't configured. Lets the router degrade gracefully — e.g. chat still
    works on OpenAI when PERPLEXITY_API_KEY is unset."""
    try:
        return factory()
    except RuntimeError as e:
        logger.warning("router: skipping %s adapter — %s", name, e)
        return None


def build_default_router(session) -> Router:
    """Convenience factory — wires adapters whose env is set.

    Each adapter's __init__ raises RuntimeError when its API key is missing;
    we skip those rather than crashing the whole router at first request.
    """
    candidates = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "perplexity": PerplexityAdapter,
        "ollama": OllamaAdapter,
        # Cloudflare Workers AI — cheap edge inference (Llama/Mistral).
        # Registered alongside the others; the intent classifier doesn't
        # auto-route to it yet, but it's available for explicit selection.
        "cloudflare": CloudflareAdapter,
    }
    adapters: dict[str, Adapter] = {}
    for name, cls in candidates.items():
        a = _try_adapter(name, cls)
        if a is not None:
            adapters[name] = a
    if not adapters:
        raise RuntimeError("router: no adapters configured — set at least one of OPENAI/ANTHROPIC/PERPLEXITY/OLLAMA env")
    return Router(adapters=adapters, spend_tracker=SpendTracker(session))


__all__ = [
    "Adapter",
    "AnthropicAdapter",
    "CloudflareAdapter",
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
    "ToolCallSpec",
    "build_default_router",
    "calculate_cost",
    "classify_intent",
    "to_message_dicts",
]
