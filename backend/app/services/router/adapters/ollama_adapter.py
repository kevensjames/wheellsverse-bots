"""Ollama adapter — local model on the Mac mini."""
from __future__ import annotations

import json
import os
import time
from typing import Iterator

import httpx

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult


class OllamaAdapter:
    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout: float | None = None,
    ):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        # Env-configurable so the operator can fail fast on a wedged/slow local
        # model and let the router fall back to cloud (Router._runtime_fallback),
        # instead of hanging the chat for the full default window. Default 120s
        # preserves prior behaviour for long local generations.
        self.timeout = (
            timeout if timeout is not None
            else float(os.environ.get("OLLAMA_TIMEOUT", "120"))
        )

    @staticmethod
    def _build(messages: list[dict], system: str | None) -> list[dict]:
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult:
        payload = {
            "model": self.model,
            "messages": self._build(messages, system),
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        start = time.time()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.time() - start) * 1000)

        content = data.get("message", {}).get("content", "")
        in_tok = data.get("prompt_eval_count", 0)
        out_tok = data.get("eval_count", 0)
        return CompletionResult(
            content=content,
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason=data.get("done_reason"),
        )

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": self._build(messages, system),
            "stream": True,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if data.get("done"):
                        break
