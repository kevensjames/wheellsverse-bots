"""Multi-model router. Primary: Claude Sonnet 4.6. Fallback: GPT-4o → Ollama.
Uses litellm so callers never touch provider SDKs directly."""
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import litellm

from .resilience import guarded

litellm.drop_params = True  # ignore unsupported params per-model silently

# ── Model registry ────────────────────────────────────────────────────────────

FAST_MODELS = [
    "claude/claude-haiku-4-5-20251001",   # cheapest, fastest
    "gpt-4o-mini",
    "ollama/llama3.2",
]

DEEP_MODELS = [
    "claude/claude-sonnet-4-6",           # primary
    "gpt-4o",
    "ollama/llama3.2",
]


@dataclass
class RouterConfig:
    primary_fast: str = field(default_factory=lambda: os.getenv("NARAI_FAST_MODEL", FAST_MODELS[0]))
    primary_deep: str = field(default_factory=lambda: os.getenv("NARAI_DEEP_MODEL", DEEP_MODELS[0]))
    fallback_fast: list[str] = field(default_factory=lambda: FAST_MODELS[1:])
    fallback_deep: list[str] = field(default_factory=lambda: DEEP_MODELS[1:])
    max_tokens_fast: int = 512
    max_tokens_deep: int = 4096
    temperature: float = 0.7


_config = RouterConfig()


# ── Core call ─────────────────────────────────────────────────────────────────

def _build_messages(
    prompt: str,
    system: str | None = None,
    history: list[dict] | None = None,
) -> list[dict]:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    for h in (history or []):
        msgs.append(h)
    msgs.append({"role": "user", "content": prompt})
    return msgs


@guarded("llm", retries=2, calls_per_minute=120)
async def call(
    prompt: str,
    *,
    tier: str = "fast",
    system: str | None = None,
    history: list[dict] | None = None,
    stream: bool = False,
    **kwargs: Any,
) -> dict:
    """Route a prompt to the appropriate model tier with auto-fallback.

    Returns {"content": str, "model": str, "tokens": int}
    """
    models = [_config.primary_fast] + _config.fallback_fast if tier == "fast" \
        else [_config.primary_deep] + _config.fallback_deep
    max_tokens = _config.max_tokens_fast if tier == "fast" else _config.max_tokens_deep
    messages = _build_messages(prompt, system=system, history=history)

    last_exc: Exception | None = None
    for model in models:
        try:
            resp = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=_config.temperature,
                stream=stream,
                **kwargs,
            )
            if stream:
                return {"stream": resp, "model": model}
            content = resp.choices[0].message.content or ""
            tokens = resp.usage.total_tokens if resp.usage else 0
            return {"content": content, "model": model, "tokens": tokens}
        except Exception as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"All models failed. Last error: {last_exc}")


def preview_model(tier: str = "fast") -> str:
    """Return the model name that ``call()``/``stream()`` would dispatch to
    for the given routing tier, without invoking any LLM. Useful for
    pre-emptive subscription-tier whitelist checks before streaming starts.

    Returns the *primary* model only — runtime fallbacks aren't reflected.
    If the primary errors, ``call()`` walks the fallback chain; callers
    relying on this preview for whitelist gating should accept that the
    actual model used may differ from the previewed one in rare cases
    (e.g., the primary is unreachable). For tier-whitelist purposes this
    is fine because fallback models are usually the same tier or cheaper.
    """
    return _config.primary_fast if tier == "fast" else _config.primary_deep


async def stream(
    prompt: str,
    *,
    tier: str = "deep",
    system: str | None = None,
    history: list[dict] | None = None,
) -> AsyncIterator[str]:
    """Streaming call — yields text chunks."""
    result = await call(prompt, tier=tier, system=system, history=history, stream=True)
    async for chunk in result["stream"]:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def set_config(**kwargs: Any) -> None:
    for k, v in kwargs.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
