"""Cloudflare Workers AI adapter — edge-hosted Llama / Mistral / Qwen.

Why this exists alongside OpenAI/Anthropic/Ollama/Perplexity:
  - **Cost**: ~$0.28/M input + $0.83/M output for Llama-3.1-8B (5-10× cheaper
    than GPT-4o-mini for many use cases). Free tier covers ~10K neurons/day.
  - **Latency**: served at Cloudflare's edge — closer to the user than
    OpenAI's regional datacenters in many geographies.
  - **No local compute**: unlike Ollama which depends on the Mac mini's
    CPU/GPU budget, CF Workers AI runs on their infra. Frees local compute
    for other things (the daemon, embeddings, etc).

What it's NOT good for:
  - Function calling / tool use — CF's chat API doesn't expose the
    OpenAI-compatible tool_calls shape, so tools= is silently ignored.
    Use OpenAI/Anthropic when the conversation needs the tool loop.
  - State-of-the-art reasoning — Llama 3.1 8b is fine for chat but
    weaker than GPT-4o / Claude 3.5 Sonnet on complex tasks.

How it fits in the router:
  This adapter is REGISTERED but not auto-selected by default. Operators
  can route specific intents to it via the Router's select() override,
  or expose a "fast / cheap" toggle in the UI alongside "prefer local".
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterator

import httpx

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct"
_BROWSER_UA = "Mozilla/5.0 wheellsverse-cli/1.0"


class CloudflareAdapter:
    name = "cloudflare"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_token: str | None = None,
        account_id: str | None = None,
    ):
        self.model = model
        self._token = api_token or os.environ.get("CLOUDFLARE_AI_TOKEN")
        self._account = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if not self._token:
            raise RuntimeError("CLOUDFLARE_AI_TOKEN not set")
        if not self._account:
            raise RuntimeError("CLOUDFLARE_ACCOUNT_ID not set")
        self._base = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self._account}/ai/run"
        )

    @staticmethod
    def _build_messages(messages: list[dict], system: str | None) -> list[dict]:
        if system is None:
            return messages
        if messages and messages[0].get("role") == "system":
            merged = system + "\n\n" + messages[0]["content"]
            return [{"role": "system", "content": merged}] + messages[1:]
        return [{"role": "system", "content": system}] + messages

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            # CF's API edge runs Browser Integrity Check on some routes.
            # A Mozilla UA gets through reliably; default httpx UA gets 1010s.
            "User-Agent": _BROWSER_UA,
        }

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
        tools: list[dict] | None = None,  # accepted for interface parity, ignored
    ) -> CompletionResult:
        if tools:
            logger.info(
                "cloudflare adapter: tools= passed but CF chat API does "
                "not expose tool_calls; silently ignoring"
            )

        msgs = self._build_messages(messages, system)
        body = {
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        start = time.time()
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{self._base}/{self.model}",
                headers=self._headers(),
                json=body,
            )
        latency_ms = int((time.time() - start) * 1000)

        if r.status_code >= 400:
            raise RuntimeError(
                f"Cloudflare AI HTTP {r.status_code}: {r.text[:300]}"
            )

        data = r.json()
        if not data.get("success"):
            errs = data.get("errors") or []
            msg = errs[0].get("message") if errs else "unknown CF AI error"
            raise RuntimeError(f"Cloudflare AI error: {msg}")

        result = data.get("result") or {}
        content = result.get("response", "")
        usage = result.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))

        return CompletionResult(
            content=content,
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason="stop",
            tool_calls=[],
        )

    def stream(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        """Stream tokens via CF's SSE endpoint.

        Same /ai/run/{model} URL but with `stream=true` in the body. Each
        SSE data line is a JSON chunk with `response` containing the next
        token fragment. Final line is `data: [DONE]`."""
        msgs = self._build_messages(messages, system)
        body = {
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        with httpx.Client(timeout=60.0) as client:
            with client.stream(
                "POST",
                f"{self._base}/{self.model}",
                headers=self._headers(),
                json=body,
            ) as r:
                if r.status_code >= 400:
                    raise RuntimeError(
                        f"Cloudflare AI stream HTTP {r.status_code}"
                    )
                for line in r.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("response")
                    if delta:
                        yield delta
