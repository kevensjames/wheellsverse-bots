"""OpenAI embeddings wrapper. Sync, batched, cost-logged."""
from __future__ import annotations

import logging
import os
from typing import Sequence

from openai import OpenAI

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
COST_PER_1K_TOKENS_USD = 0.00002
BATCH_SIZE = 100
TRUNCATE_CHARS = 24_000


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        _client = OpenAI(api_key=api_key)
    return _client


def _truncate(text: str) -> str:
    return text[:TRUNCATE_CHARS] if len(text) > TRUNCATE_CHARS else text


def embed_one(text: str) -> list[float]:
    return embed_many([text])[0]


def embed_many(texts: Sequence[str]) -> list[list[float]]:
    if not texts:
        return []

    client = _get_client()
    inputs = [_truncate(t) for t in texts]
    results: list[list[float]] = []

    for i in range(0, len(inputs), BATCH_SIZE):
        chunk = inputs[i : i + BATCH_SIZE]
        response = client.embeddings.create(model=MODEL, input=chunk)
        results.extend(d.embedding for d in response.data)

        tokens = response.usage.total_tokens
        cost = tokens / 1000 * COST_PER_1K_TOKENS_USD
        logger.info(
            "embedded chunk=%d items, tokens=%d, cost=$%.6f", len(chunk), tokens, cost
        )

    return results
