"""Grounding — verify a statement against the user's indexed documents and score
confidence. Phase 2 of the professional-knowledge layer.

Turns "retrieved context" into "cited + verified, or honestly refused":
  - retrieve the most relevant passages (services/rag → pgvector top-k),
  - ask the LLM whether the statement is SUPPORTED by ONLY those passages
    (citing which), at low temperature,
  - blend that judgment with retrieval strength into a confidence label.

Fail-soft and conservative by design: no indexed sources → "no_sources"; LLM
error → "unknown". It never fabricates support — an unverifiable claim is
reported as such, which is what lets a professional agent honestly refuse
instead of guessing. Reuses the critic's balanced-brace JSON extractor.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.self_correction.critic import _extract_json_block

logger = logging.getLogger(__name__)

VERDICTS = ("supported", "partial", "unsupported", "contradicted", "no_sources", "unknown")
_CONF = ("high", "medium", "low")
DEFAULT_K = 5
DEFAULT_MAX_TOKENS = 600

_VERIFY_SYSTEM = (
    "You are a strict fact-checker. You are given numbered SOURCES (excerpts "
    "from the user's own documents) and a STATEMENT. Decide whether the SOURCES "
    "support the statement, using ONLY the sources — never outside knowledge.\n"
    "\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "verdict": "supported|partial|unsupported|contradicted",\n'
    '  "confidence": "high|medium|low",\n'
    '  "supporting_sources": [1, 2],\n'
    '  "reason": "one sentence, citing source numbers"\n'
    "}\n"
    "Rules: 'supported' ONLY if the sources directly back the statement. "
    "'contradicted' if a source asserts the opposite. 'partial' if only part "
    "holds. 'unsupported' if the sources are silent/irrelevant. Cite the source "
    "numbers you relied on. No commentary outside the JSON."
)


def verify_statement(
    *, db, router, user_id, statement: str, k: int = DEFAULT_K,
    prefer_local: bool = False, max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Verify `statement` against the user's indexed documents.

    Returns {"verdict", "supported": bool, "confidence", "support": [{source,
    position, excerpt}], "reason", "sources_checked", "cost_usd"}.
    """
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("statement cannot be empty")

    from app.services import rag
    try:
        chunks = rag.retrieve(db, user_id=user_id, query=statement, k=k)
    except Exception as e:
        logger.warning("grounding: retrieve failed: %s", e)
        return _result("unknown", False, "low", [], f"retrieval failed: {e}", 0, 0.0)

    if not chunks:
        return _result("no_sources", False, "low", [],
                       "no indexed documents to verify against — upload sources first", 0, 0.0)

    sources_block = "\n".join(
        f"[{i + 1}] (\"{c['filename']}\" #{c['position']}): {c['content']}"
        for i, c in enumerate(chunks)
    )
    user_msg = (
        f"SOURCES:\n{sources_block}\n\nSTATEMENT TO VERIFY:\n{statement}\n\n"
        "Return the JSON verdict."
    )
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": user_msg}],
            system=_VERIFY_SYSTEM, max_tokens=max_tokens, temperature=0.1,
            prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("grounding: verifier router.complete failed: %s", e)
        return _result("unknown", False, "low", [],
                       f"verification unavailable: {e}", len(chunks), 0.0)

    parsed = _parse_verdict((getattr(result, "content", "") or ""), chunks)
    parsed["confidence"] = _blend_confidence(parsed, chunks)
    parsed["sources_checked"] = len(chunks)
    parsed["cost_usd"] = _result_cost(result)
    return parsed


# ─── internals ──────────────────────────────────────────────────────


def _result(verdict, supported, confidence, support, reason, n, cost) -> dict[str, Any]:
    return {"verdict": verdict, "supported": supported, "confidence": confidence,
            "support": support, "reason": reason, "sources_checked": n, "cost_usd": cost}


def _parse_verdict(text: str, chunks: list[dict]) -> dict[str, Any]:
    data = _extract_json(text)
    if not isinstance(data, dict):
        return _result("unknown", False, "low", [],
                       "verifier returned no parseable verdict", len(chunks), 0.0)
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        verdict = "unknown"
    supported = verdict == "supported" or bool(data.get("supported") is True)
    conf = str(data.get("confidence") or "").strip().lower()
    if conf not in _CONF:
        conf = "low"
    raw_idx = data.get("supporting_sources")
    support: list[dict[str, Any]] = []
    if isinstance(raw_idx, list):
        for n in raw_idx:
            try:
                i = int(n) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(chunks):
                c = chunks[i]
                support.append({"source": c["filename"], "position": c["position"],
                                "excerpt": c["content"][:300]})
    return {"verdict": verdict, "supported": supported, "confidence": conf,
            "support": support, "reason": str(data.get("reason") or "").strip()}


def _extract_json(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        blob = _extract_json_block(cleaned)
        if not blob:
            return None
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return None


def _blend_confidence(parsed: dict[str, Any], chunks: list[dict]) -> str:
    """Combine the LLM's confidence with retrieval strength (top similarity).
    A confident verdict on weakly-retrieved sources is NOT high confidence."""
    llm = parsed.get("confidence", "low")
    verdict = parsed.get("verdict")
    # cosine distance: smaller = more similar. similarity = 1 - distance.
    top_sim = 1.0 - float(min((c.get("distance", 1.0) for c in chunks), default=1.0))
    if verdict in ("unknown", "no_sources", "unsupported"):
        return "low"
    if verdict == "supported" and llm == "high" and top_sim >= 0.55:
        return "high"
    if top_sim < 0.30:
        return "low"  # retrieval too weak to trust regardless of the LLM
    return "medium"


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
