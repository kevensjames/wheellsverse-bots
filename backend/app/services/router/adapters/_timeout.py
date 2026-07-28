"""Shared, configurable provider timeout.

The OpenAI/Anthropic SDKs default to a ~600s (10-minute) per-request timeout, so
a stalled provider could pin a worker for minutes. This bounds every hosted
provider call to a production-safe default, overridable via NAI_PROVIDER_TIMEOUT_S.
(ollama + cloudflare adapters already pass their own httpx timeouts.)
"""
from __future__ import annotations

import os

_DEFAULT_S = 30.0


def provider_timeout() -> float:
    try:
        v = float(os.environ.get("NAI_PROVIDER_TIMEOUT_S", _DEFAULT_S))
        return v if v > 0 else _DEFAULT_S
    except (TypeError, ValueError):
        return _DEFAULT_S
