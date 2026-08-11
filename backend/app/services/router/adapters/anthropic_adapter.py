"""Anthropic adapter — used for code + reasoning."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterator

from anthropic import Anthropic

from app.services.router.adapters.base import calculate_cost
from app.services.router.types import CompletionResult, ToolCallSpec

logger = logging.getLogger(__name__)


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        from app.services.router.adapters._timeout import provider_timeout
        # Bound per-request time (SDK default ~600s) so a stalled provider can't
        # pin a worker. max_retries=0: a message completion is non-idempotent and
        # the SDK sends no Idempotency-Key, so an auto-retry on a read timeout
        # would double-generate (and double-bill). The caller retries instead.
        self._client = Anthropic(api_key=key, timeout=provider_timeout(), max_retries=0)

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

    @staticmethod
    def _translate_to_anthropic(messages: list[dict]) -> list[dict]:
        """OpenAI-style messages → Anthropic block format.

        OpenAI tool turns:
            {"role": "assistant", "content": "...", "tool_calls": [{...}]}
            {"role": "tool", "tool_call_id": "...", "content": "..."}

        Anthropic tool turns:
            {"role": "assistant", "content": [{"type":"text",...},
                                              {"type":"tool_use",...}]}
            {"role": "user", "content": [{"type":"tool_result",
                                          "tool_use_id":..., "content":...}]}
        """
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue  # extracted by _split_system

            if role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m["tool_call_id"],
                                "content": m["content"],
                            }
                        ],
                    }
                )
                continue

            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                text = m.get("content") or ""
                if text:
                    blocks.append({"type": "text", "text": text})
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    name = tc.get("name") or fn.get("name")
                    raw_args = tc.get("arguments") or fn.get("arguments")
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = raw_args or {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": name,
                            "input": args,
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue

            out.append({"role": role, "content": m["content"]})
        return out

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> CompletionResult:
        sys_prompt, cleaned = self._split_system(messages, system)
        translated = self._translate_to_anthropic(cleaned)
        kwargs: dict = {
            "model": self.model,
            "messages": translated,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if sys_prompt:
            kwargs["system"] = sys_prompt
        if tools:
            kwargs["tools"] = tools

        start = time.time()
        resp = self._client.messages.create(**kwargs)
        latency_ms = int((time.time() - start) * 1000)

        text_parts: list[str] = []
        tc_specs: list[ToolCallSpec] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tc_specs.append(
                    ToolCallSpec(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    )
                )

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        return CompletionResult(
            content="".join(text_parts),
            adapter=self.name,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=calculate_cost(self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            finish_reason=resp.stop_reason,
            tool_calls=tc_specs,
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
