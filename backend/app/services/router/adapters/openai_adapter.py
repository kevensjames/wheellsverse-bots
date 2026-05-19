"""OpenAI adapter — default for general chat."""
from __future__ import annotations

import logging
import os
import time
from typing import Iterator

from openai import OpenAI

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self._client = OpenAI(api_key=key)

    @staticmethod
    def _build_messages(messages: list[dict], system: str | None) -> list[dict]:
        if system is None:
            return messages
        if messages and messages[0].get("role") == "system":
            merged = system + "\n\n" + messages[0]["content"]
            return [{"role": "system", "content": merged}] + messages[1:]
        return [{"role": "system", "content": system}] + messages

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult:
        msgs = self._build_messages(messages, system)
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
        return CompletionResult(
            content=choice.message.content or "",
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
        )

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        msgs = self._build_messages(messages, system)
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
