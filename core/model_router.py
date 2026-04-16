#!/usr/bin/env python3
"""
core/model_router.py
─────────────────────────────────────────────────────────────────────────────
Unified multi-model chat router.

Supported providers:
  anthropic — Claude claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5
  openai    — gpt-4o, gpt-4o-mini
  google    — gemini-1.5-pro, gemini-1.5-flash  (requires google-generativeai)
  mistral   — mistral-large-latest, mistral-small-latest  (requires mistralai)

Usage:
  from core.model_router import chat, stream_chat, MODELS

  # Non-streaming
  result = chat("claude-sonnet-4-6", messages, system="You are NarAI")
  # → {content, tokens, model, provider}

  # Streaming generator
  for chunk in stream_chat("gpt-4o", messages):
      print(chunk["token"], end="", flush=True)
  # → yields {token} then {done, tokens, model, provider}
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("model_router")

# ─── Model registry ───────────────────────────────────────────────────────────

MODELS: Dict[str, Dict] = {
    # Anthropic / Claude
    "claude-sonnet-4-6": {
        "id": "claude-sonnet-4-6",
        "display": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "context_window": 200_000,
        "cost_per_1k_in": 0.003,
        "cost_per_1k_out": 0.015,
        "supports_vision": True,
        "supports_tools": True,
    },
    "claude-opus-4-6": {
        "id": "claude-opus-4-6",
        "display": "Claude Opus 4.6",
        "provider": "anthropic",
        "context_window": 200_000,
        "cost_per_1k_in": 0.015,
        "cost_per_1k_out": 0.075,
        "supports_vision": True,
        "supports_tools": True,
    },
    "claude-haiku-4-5-20251001": {
        "id": "claude-haiku-4-5-20251001",
        "display": "Claude Haiku 4.5",
        "provider": "anthropic",
        "context_window": 200_000,
        "cost_per_1k_in": 0.00025,
        "cost_per_1k_out": 0.00125,
        "supports_vision": True,
        "supports_tools": True,
    },
    # OpenAI
    "gpt-4o": {
        "id": "gpt-4o",
        "display": "GPT-4o",
        "provider": "openai",
        "context_window": 128_000,
        "cost_per_1k_in": 0.005,
        "cost_per_1k_out": 0.015,
        "supports_vision": True,
        "supports_tools": True,
    },
    "gpt-4o-mini": {
        "id": "gpt-4o-mini",
        "display": "GPT-4o Mini",
        "provider": "openai",
        "context_window": 128_000,
        "cost_per_1k_in": 0.00015,
        "cost_per_1k_out": 0.0006,
        "supports_vision": True,
        "supports_tools": True,
    },
    # Google Gemini
    "gemini-1.5-pro": {
        "id": "gemini-1.5-pro",
        "display": "Gemini 1.5 Pro",
        "provider": "google",
        "context_window": 1_000_000,
        "cost_per_1k_in": 0.00125,
        "cost_per_1k_out": 0.005,
        "supports_vision": True,
        "supports_tools": True,
    },
    "gemini-1.5-flash": {
        "id": "gemini-1.5-flash",
        "display": "Gemini 1.5 Flash",
        "provider": "google",
        "context_window": 1_000_000,
        "cost_per_1k_in": 0.000075,
        "cost_per_1k_out": 0.0003,
        "supports_vision": True,
        "supports_tools": False,
    },
    # Mistral
    "mistral-large-latest": {
        "id": "mistral-large-latest",
        "display": "Mistral Large",
        "provider": "mistral",
        "context_window": 32_000,
        "cost_per_1k_in": 0.003,
        "cost_per_1k_out": 0.009,
        "supports_vision": False,
        "supports_tools": True,
    },
    "mistral-small-latest": {
        "id": "mistral-small-latest",
        "display": "Mistral Small",
        "provider": "mistral",
        "context_window": 32_000,
        "cost_per_1k_in": 0.0002,
        "cost_per_1k_out": 0.0006,
        "supports_vision": False,
        "supports_tools": False,
    },
}

_DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


def get_model(model_id: str) -> Dict:
    """Return model metadata, falling back to default if unknown."""
    return MODELS.get(model_id, MODELS[_DEFAULT_MODEL])


def list_models() -> List[Dict]:
    """Return all models enriched with availability flags."""
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_AI_API_KEY"))
    has_mistral = bool(os.getenv("MISTRAL_API_KEY"))
    provider_available = {
        "anthropic": has_anthropic,
        "openai": has_openai,
        "google": has_google,
        "mistral": has_mistral,
    }
    result = []
    for m in MODELS.values():
        result.append({**m, "available": provider_available.get(m["provider"], False)})
    return result


# ─── Provider implementations ─────────────────────────────────────────────────

def _chat_anthropic(model_id: str, messages: List, system: str, max_tokens: int, temperature: float, tools: Optional[List]) -> Dict:
    import anthropic as _ant
    client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    kwargs: Dict[str, Any] = dict(model=model_id, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = tools
    resp = client.messages.create(**kwargs)
    content = resp.content[0].text if resp.content else ""
    tokens = (resp.usage.input_tokens + resp.usage.output_tokens) if hasattr(resp, "usage") else 0
    return {"content": content, "tokens": tokens, "model": model_id, "provider": "anthropic"}


def _chat_openai(model_id: str, messages: List, system: str, max_tokens: int, temperature: float, tools: Optional[List]) -> Dict:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    oai_messages = []
    if system:
        oai_messages.append({"role": "system", "content": system})
    oai_messages.extend(messages)
    kwargs: Dict[str, Any] = dict(model=model_id, messages=oai_messages, max_tokens=max_tokens)
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    tokens = (resp.usage.prompt_tokens + resp.usage.completion_tokens) if resp.usage else 0
    return {"content": content, "tokens": tokens, "model": model_id, "provider": "openai"}


def _chat_google(model_id: str, messages: List, system: str, max_tokens: int, temperature: float, tools: Optional[List]) -> Dict:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed. Run: pip install google-generativeai")
    genai.configure(api_key=os.getenv("GOOGLE_AI_API_KEY", ""))
    model = genai.GenerativeModel(model_id, system_instruction=system or None)
    # Convert Anthropic-style messages to Gemini format
    gemini_msgs = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        content = m["content"] if isinstance(m["content"], str) else str(m["content"])
        gemini_msgs.append({"role": role, "parts": [content]})
    resp = model.generate_content(
        gemini_msgs,
        generation_config={"max_output_tokens": max_tokens, "temperature": temperature or 0.7},
    )
    content = resp.text or ""
    tokens = getattr(resp.usage_metadata, "total_token_count", 0)
    return {"content": content, "tokens": tokens, "model": model_id, "provider": "google"}


def _chat_mistral(model_id: str, messages: List, system: str, max_tokens: int, temperature: float, tools: Optional[List]) -> Dict:
    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError("mistralai not installed. Run: pip install mistralai")
    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY", ""))
    mis_messages = []
    if system:
        mis_messages.append({"role": "system", "content": system})
    mis_messages.extend(messages)
    resp = client.chat.complete(
        model=model_id,
        messages=mis_messages,
        max_tokens=max_tokens,
        temperature=temperature or 0.7,
    )
    content = resp.choices[0].message.content or ""
    tokens = (resp.usage.prompt_tokens + resp.usage.completion_tokens) if resp.usage else 0
    return {"content": content, "tokens": tokens, "model": model_id, "provider": "mistral"}


# ─── Streaming implementations ────────────────────────────────────────────────

def _stream_anthropic(model_id: str, messages: List, system: str, max_tokens: int, temperature: float) -> Generator[Dict, None, None]:
    import anthropic as _ant
    client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    kwargs: Dict[str, Any] = dict(model=model_id, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield {"token": text}
        final = stream.get_final_message()
        tokens = (final.usage.input_tokens + final.usage.output_tokens) if hasattr(final, "usage") else 0
    yield {"done": True, "tokens": tokens, "model": model_id, "provider": "anthropic"}


def _stream_openai(model_id: str, messages: List, system: str, max_tokens: int, temperature: float) -> Generator[Dict, None, None]:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    oai_messages = []
    if system:
        oai_messages.append({"role": "system", "content": system})
    oai_messages.extend(messages)
    stream = client.chat.completions.create(
        model=model_id, messages=oai_messages, max_tokens=max_tokens,
        temperature=temperature or 0.7, stream=True,
    )
    tokens = 0
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"token": delta}
        if chunk.usage:
            tokens = chunk.usage.total_tokens
    yield {"done": True, "tokens": tokens, "model": model_id, "provider": "openai"}


def _stream_google(model_id: str, messages: List, system: str, max_tokens: int, temperature: float) -> Generator[Dict, None, None]:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")
    genai.configure(api_key=os.getenv("GOOGLE_AI_API_KEY", ""))
    model = genai.GenerativeModel(model_id, system_instruction=system or None)
    gemini_msgs = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        content = m["content"] if isinstance(m["content"], str) else str(m["content"])
        gemini_msgs.append({"role": role, "parts": [content]})
    for chunk in model.generate_content(
        gemini_msgs,
        generation_config={"max_output_tokens": max_tokens, "temperature": temperature or 0.7},
        stream=True,
    ):
        if chunk.text:
            yield {"token": chunk.text}
    yield {"done": True, "tokens": 0, "model": model_id, "provider": "google"}


def _stream_mistral(model_id: str, messages: List, system: str, max_tokens: int, temperature: float) -> Generator[Dict, None, None]:
    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError("mistralai not installed")
    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY", ""))
    mis_messages = []
    if system:
        mis_messages.append({"role": "system", "content": system})
    mis_messages.extend(messages)
    tokens = 0
    for chunk in client.chat.stream(
        model=model_id, messages=mis_messages,
        max_tokens=max_tokens, temperature=temperature or 0.7,
    ):
        delta = chunk.data.choices[0].delta.content if chunk.data.choices else None
        if delta:
            yield {"token": delta}
        if chunk.data.usage:
            tokens = chunk.data.usage.prompt_tokens + chunk.data.usage.completion_tokens
    yield {"done": True, "tokens": tokens, "model": model_id, "provider": "mistral"}


# ─── Public interface ─────────────────────────────────────────────────────────

def chat(
    model_id: str = _DEFAULT_MODEL,
    messages: Optional[List] = None,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    tools: Optional[List] = None,
) -> Dict:
    """
    Non-streaming chat call.
    Returns {content, tokens, model, provider}
    """
    messages = messages or []
    meta = get_model(model_id)
    provider = meta["provider"]

    dispatch = {
        "anthropic": _chat_anthropic,
        "openai": _chat_openai,
        "google": _chat_google,
        "mistral": _chat_mistral,
    }
    fn = dispatch.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider: {provider}")
    try:
        return fn(model_id, messages, system, max_tokens, temperature, tools)
    except Exception as e:
        logger.error(f"[model_router] {provider}/{model_id} failed: {e}")
        raise


def stream_chat(
    model_id: str = _DEFAULT_MODEL,
    messages: Optional[List] = None,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> Generator[Dict, None, None]:
    """
    Streaming generator. Yields {token} then {done, tokens, model, provider}.
    """
    messages = messages or []
    meta = get_model(model_id)
    provider = meta["provider"]

    dispatch = {
        "anthropic": _stream_anthropic,
        "openai": _stream_openai,
        "google": _stream_google,
        "mistral": _stream_mistral,
    }
    fn = dispatch.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider: {provider}")
    try:
        yield from fn(model_id, messages, system, max_tokens, temperature)
    except Exception as e:
        logger.error(f"[model_router] stream {provider}/{model_id} failed: {e}")
        yield {"done": True, "error": str(e), "tokens": 0, "model": model_id, "provider": provider}
