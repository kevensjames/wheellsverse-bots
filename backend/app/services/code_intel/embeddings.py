"""Embedding backends for code chunks: OpenAI (egress) or local Ollama (no
egress). Provider is chosen per-tenant by policy; a residency-restricted tenant
(egress_allowed=False) is forced to Ollama so code never leaves the host."""
from __future__ import annotations

import json
import logging
import os
from typing import Sequence

logger = logging.getLogger(__name__)

OPENAI_MODEL = "text-embedding-3-small"
OLLAMA_MODEL = os.environ.get("KAI_CODE_INTEL_OLLAMA_EMBED_MODEL", "nomic-embed-text")


def embed_texts(texts: Sequence[str], *, provider: str = "openai") -> list[list[float] | None]:
    """One vector per input (or None on failure). Never raises."""
    if not texts:
        return []
    if provider == "ollama":
        return _embed_ollama(list(texts))
    return _embed_openai(list(texts))


def _embed_openai(texts: list[str]) -> list[list[float] | None]:
    import urllib.request

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("code_intel: OPENAI_API_KEY missing — skipping embeddings")
        return [None] * len(texts)
    body = json.dumps({"model": OPENAI_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings", data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
    except Exception as e:
        logger.warning("code_intel: openai embed failed: %s", e)
        return [None] * len(texts)
    by_idx = {d["index"]: d["embedding"] for d in payload.get("data", [])}
    return [by_idx.get(i) for i in range(len(texts))]


def _embed_ollama(texts: list[str]) -> list[list[float] | None]:
    import urllib.request

    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    out: list[list[float] | None] = []
    for t in texts:
        body = json.dumps({"model": OLLAMA_MODEL, "prompt": t}).encode()
        req = urllib.request.Request(
            f"{host}/api/embeddings", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out.append(json.loads(r.read()).get("embedding"))
        except Exception as e:
            logger.warning("code_intel: ollama embed failed: %s", e)
            out.append(None)
    return out
