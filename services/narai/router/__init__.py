"""NarAI router engine — public API surface.

Real implementation lives at ``backend/app/services/router/``. This shim
preserves the locked Stage 0 namespace ``services.narai.router`` so consumer
code is decoupled from the current physical layout. When NarAI is lifted to
its own deployable in Phase B, only this shim moves; call-sites stay stable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.router import (  # noqa: E402
    PRICING,
    Adapter,
    AnthropicAdapter,
    CompletionResult,
    Intent,
    Message,
    OllamaAdapter,
    OpenAIAdapter,
    PerplexityAdapter,
    Role,
    Router,
    SpendTracker,
    build_default_router,
    calculate_cost,
    classify_intent,
    to_message_dicts,
)

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
