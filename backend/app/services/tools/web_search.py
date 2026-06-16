"""Web search tool — uses Perplexity directly for predictability.

Bypassing the model router here is intentional: search is a deterministic
provider choice and we don't want intent classification adding latency or
ambiguity inside a tool call.
"""
from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from app.services.tools.base import ToolContext, ToolError


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the live web for current information. Use this when the answer "
        "requires up-to-date facts the assistant couldn't know from training data "
        "(news, prices, current events, recent releases). Returns a concise answer "
        "and citation URLs."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific. 1-2 sentences max.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, model: str = "sonar-pro", api_key: str | None = None):
        self.model = model
        key = api_key or os.environ.get("PERPLEXITY_API_KEY")
        if not key:
            raise RuntimeError("PERPLEXITY_API_KEY not set")
        self._client = OpenAI(api_key=key, base_url="https://api.perplexity.ai")

    def execute(self, ctx: ToolContext, *, query: str) -> dict[str, Any]:
        if not query or not query.strip():
            raise ToolError("query cannot be empty")

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": query.strip()}],
            max_tokens=512,
            temperature=0.2,
        )
        answer = resp.choices[0].message.content or ""
        citations = getattr(resp, "citations", None) or []
        return {
            "answer": answer,
            "citations": citations[:5],
            "model": self.model,
        }
