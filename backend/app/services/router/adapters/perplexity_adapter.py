"""Perplexity adapter — used for realtime / fact-grounded queries.

Perplexity's API is OpenAI-compatible, so we reuse the OpenAI SDK with a
different base_url.
"""
from __future__ import annotations

import os
import time
from typing import Iterator

from openai import OpenAI

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult


class PerplexityAdapter:
    name = "perplexity"

    def __init__(self, model: str = "sonar-pro", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("PERPLEXITY_API_KEY")
        if not key:
            raise RuntimeError("PERPLEXITY_API_KEY not set")
        from app.services.router.adapters._timeout import provider_timeout
        # max_retries=0: non-idempotent completion, no Idempotency-Key — an
        # auto-retry on a read timeout would double-generate/-bill (see openai_adapter).
        self._client = OpenAI(api_key=key, base_url="https://api.perplexity.ai",
                              timeout=provider_timeout(), max_retries=0)

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult:
        msgs = ([{"role": "system", "content": system}] + messages) if system else messages
        start = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_ms = int((time.time() - start) * 1000)
        choice = resp.choices[0]
        in_tok = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens
        citations = getattr(resp, "citations", None) or []
        return CompletionResult(
            content=choice.message.content or "",
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
            metadata={"citations": citations},
        )

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        msgs = ([{"role": "system", "content": system}] + messages) if system else messages
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
