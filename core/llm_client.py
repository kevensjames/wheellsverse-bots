"""Safe OpenAI call wrapper — coordinates with the global TPM/RPM limiter.

Single entry point used by every OpenAI caller in the codebase. Replaces
direct `client.chat.completions.create(...)` calls with a flow that:

  1. Estimates token cost via tiktoken (or chars/4 fallback)
  2. Blocks via core.llm_limiter until the sliding window has room
  3. Issues the OpenAI call ONCE — no internal 429 retry (limiter prevents
     the 429 in the first place)
  4. Records actual token usage back to the limiter (corrects estimate drift)
  5. Forwards usage to core.base_bot._log_token_usage() so cost accounting
     and the daily-budget guard keep working

Public API:
    safe_openai_call(messages, model, max_tokens, ...) -> ChatCompletion

Local-backend support (LLM_BACKEND=ollama):
    When LLM_BACKEND is set to "ollama" (or any non-empty value other than
    "openai"), calls are routed to a local OpenAI-compatible endpoint
    (default http://localhost:11434/v1) using OLLAMA_BASE_URL. Model names
    are translated via OLLAMA_MODEL_MAP (JSON) or fall through unchanged.
    The TPM limiter and cost logging are short-circuited on the local
    path (no rate limit, no spend to track).

Exceptions:
    LLMCapacityTimeout — limiter waited >timeout for room (re-export from limiter)
    Native openai.* exceptions pass through unchanged
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from core.llm_limiter import LLMCapacityTimeout, limiter_for

logger = logging.getLogger("llm_client")


def _is_local_backend() -> bool:
    """True when LLM_BACKEND env routes calls to a local OpenAI-compatible server."""
    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    return backend in ("ollama", "local", "lmstudio", "llamacpp")


def _local_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _map_model(model: str) -> str:
    """Translate a cloud model name (e.g. 'gpt-4o') to a local tag (e.g. 'qwen2.5:7b').

    Source: OLLAMA_MODEL_MAP env var as a JSON object, e.g.
        {"gpt-4o": "qwen2.5:7b", "gpt-4o-mini": "llama3.2:3b"}

    Unknown models pass through unchanged so Ollama-native tags
    (`qwen2.5:7b`, `llama3.2:latest`) still work directly.
    """
    raw = os.getenv("OLLAMA_MODEL_MAP", "").strip()
    if not raw:
        return model
    try:
        mapping = json.loads(raw)
        return mapping.get(model, model)
    except json.JSONDecodeError:
        logger.warning("OLLAMA_MODEL_MAP is not valid JSON — passing model through")
        return model

# Token-counting strategy: tiktoken (accurate) with chars/4 fallback
_encoders: dict[str, Any] = {}


def _estimate_tokens(messages: list[dict], model: str) -> int:
    """Return a slightly-conservative token estimate for the prompt.

    Uses tiktoken when available; falls back to chars/4 (industry rule of
    thumb) when the encoding can't be resolved (e.g., brand-new model).
    """
    try:
        import tiktoken
        if model not in _encoders:
            try:
                _encoders[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                _encoders[model] = tiktoken.get_encoding("o200k_base")
        enc = _encoders[model]
        # Per-message overhead: ~4 tokens for role + structural tokens
        total = 0
        for m in messages:
            content = m.get("content", "") or ""
            total += len(enc.encode(str(content))) + 4
        return total + 2  # 2-token reply primer
    except Exception:
        # Fallback: rough chars/4 estimate
        chars = sum(len(str(m.get("content", "") or "")) for m in messages)
        return max(1, chars // 4 + 8)


def safe_openai_call(
    messages: list[dict],
    model: str = "gpt-4o",
    max_tokens: int = 2000,
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
    bot_name: str = "anonymous",
    api_key: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Issue an OpenAI chat-completion call coordinated by the global limiter.

    Args:
        messages: standard OpenAI chat messages list
        model: gpt-4o, gpt-4o-mini, etc.
        max_tokens: completion budget (also used to estimate window cost)
        temperature: forwarded as-is
        response_format: optional, e.g. {"type": "json_object"}
        bot_name: for token-usage attribution in data/token_usage.json
        api_key: override OPENAI_API_KEY env (rarely needed)
        **kwargs: forwarded to client.chat.completions.create()

    Returns:
        The raw ChatCompletion response object — drop-in compatible with
        existing call sites.
    """
    import openai

    local = _is_local_backend()
    effective_model = _map_model(model) if local else model

    if not local:
        estimated = _estimate_tokens(messages, model) + max_tokens
        limiter = limiter_for(model)
        limiter.wait_for_capacity(estimated_tokens=estimated)

    if local:
        client = openai.OpenAI(
            base_url=_local_base_url(),
            api_key=api_key or os.getenv("OLLAMA_API_KEY", "ollama"),
        )
    else:
        client = openai.OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY", ""))

    call_kwargs: dict = {
        "model": effective_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        call_kwargs["response_format"] = response_format
    call_kwargs.update(kwargs)

    resp = client.chat.completions.create(**call_kwargs)

    # Correct the limiter with the actual token cost. On the local path
    # there is no limiter and no cost — skip both.
    if not local:
        actual_total = 0
        try:
            usage = getattr(resp, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                actual_total = prompt_tokens + completion_tokens
                limiter.record(actual_total)
                # Forward to existing token-usage log for cost accounting parity
                try:
                    from core.base_bot import _log_token_usage
                    _log_token_usage("openai", model, prompt_tokens, completion_tokens, bot_name)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Token-usage post-processing failed: {e}")

    return resp


__all__ = ["safe_openai_call", "LLMCapacityTimeout"]
