"""Anthropic adapter — used for code + reasoning."""
from __future__ import annotations

import logging
import os
import time
from typing import Iterator

from anthropic import Anthropic

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult

logger = logging.getLogger(__name__)


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = Anthropic(api_key=key)

    @staticmethod
    def _split_system(
        messages: list[dict], system: str | None
    ) -> tuple[str | None, list[dict]]:
        """Anthropic takes `system` as a top-level param, not a message role."""
        extracted_system: str | None = None
        cleaned: list[dict] = []
        for m in messages:
            if m.get("role") == "system":
                extracted_system = m["content"]
            else:
                cleaned.append(m)
        final_system = system if system is not None else extracted_system
        return final_system, cleaned

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult:
        sys_prompt, cleaned = self._split_system(messages, system)
        kwargs: dict = {
            "model": self.model,
            "messages": cleaned,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if sys_prompt:
            kwargs["system"] = sys_prompt
        start = time.time()
        resp = self._client.messages.create(**kwargs)
        latency_ms = int((time.time() - start) * 1000)

        content = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        return CompletionResult(
            content=content,
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason=resp.stop_reason,
        )

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        sys_prompt, cleaned = self._split_system(messages, system)
        kwargs: dict = {
            "model": self.model,
            "messages": cleaned,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if sys_prompt:
            kwargs["system"] = sys_prompt
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
